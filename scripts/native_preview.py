#!/usr/bin/env python3
"""G5 native Windows rehearsal and exact-Base isolation checks."""
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
import tempfile
import sys

sys.dont_write_bytecode = True
import batch_runner as br
import batch_sim as sim
from bounded_process import run_bounded

SIM_ROOT = 'HHAI_BATCH_SIM_ROOT'
# The approved offline uv package cache for the disposable simulation: the one place the repo records it (USER
# S4 `--cache-dir`, see TASKBOARD). Neither the host's default uv cache nor an environment variable is a
# source: Antigravity is not started through a launcher that could set one, and the default cache may lack a
# locked wheel, which makes offline uv fail. A different machine needs a reviewed batch that changes this line.
APPROVED_UV_CACHE_DIR = r'C:\Users\HH.AI_260806\hhai-toolchain\uv-cache'
# Per-stage limits inside batch_sim still apply. This also bounds the entire tree.
PREVIEW_TIMEOUT = 7200
# `uv sync --dry-run` only reads the cache; it still bounds an unexpectedly slow uv.
UV_CHECK_TIMEOUT = 300
UV_PROJECT_FILES = ('pyproject.toml', 'uv.lock', '.python-version')
# The simulator next to this module: W2's own copy for the runner; the authored copy for the
# one-time activation bootstrap, whose W2 still holds a Base simulator without these options.
SIMULATOR = Path(__file__).resolve().parent / 'batch_sim.py'


class PreviewError(Exception):
    """Fixed exit vocabulary; does not carry subprocess output."""


def approved_uv_cache(workspace):
    """The recorded, absolute, existing cache directory, outside the production workspace."""
    value = APPROVED_UV_CACHE_DIR
    if not value or not os.path.isabs(value):
        raise PreviewError('NATIVE_PREVIEW_UV_CACHE_INVALID')
    try:
        cache = Path(value)
        if not cache.is_dir():
            raise PreviewError('NATIVE_PREVIEW_UV_CACHE_INVALID')
        cache = cache.resolve()
        root = Path(workspace).resolve()
    except (OSError, RuntimeError, ValueError):
        raise PreviewError('NATIVE_PREVIEW_UV_CACHE_INVALID') from None
    if cache == root or root in cache.parents or cache in root.parents:
        raise PreviewError('NATIVE_PREVIEW_UV_CACHE_INVALID')
    return cache


def cache_satisfies_lock(workspace, base, cache):
    """Dry-run the exact Base lock against the approved cache, offline, from a throwaway copy of the three
    project files; the workspace is only read (git blobs), never handed to uv. `uv sync --dry-run` exits 0
    even when packages are missing, so the output decides: any 'Would download' line means the cache is
    incomplete and the offline simulation would fail inside uv."""
    uv = shutil.which('uv')
    if uv is None:
        raise PreviewError('NATIVE_PREVIEW_UV_CACHE_INCOMPLETE')
    try:
        files = {name: br.git_bytes(str(workspace), '--no-optional-locks', 'cat-file', 'blob', base + ':' + name)
                 for name in UV_PROJECT_FILES}
        pin = files['.python-version'].decode('utf-8').strip()
    except (br.Halt, UnicodeDecodeError):
        raise PreviewError('NATIVE_PREVIEW_UV_CACHE_INCOMPLETE') from None
    if re.fullmatch(r'\d+\.\d+', pin) is None:
        raise PreviewError('NATIVE_PREVIEW_UV_CACHE_INCOMPLETE')
    env = {key: value for key, value in br.child_env().items()
           if not key.startswith('UV_') and key not in ('VIRTUAL_ENV', 'PYTHONHOME')}
    env.update(UV_OFFLINE='1', UV_PYTHON_DOWNLOADS='never', UV_NO_PROGRESS='1', UV_CACHE_DIR=str(cache))
    with tempfile.TemporaryDirectory(prefix='hhai-uvcheck-') as scratch:
        for name, data in files.items():
            (Path(scratch) / name).write_bytes(data)
        result = run_bounded([uv, '--no-config', 'sync', '--locked', '--offline', '--no-python-downloads',
                              '--python', pin, '--dry-run', '--project', scratch],
                             scratch, UV_CHECK_TIMEOUT, env=env, merge_stderr=True)
    if (result.launch_error or result.timed_out or result.returncode != 0
            or re.search(rb'(?m)^Would download\b', result.stdout)):
        raise PreviewError('NATIVE_PREVIEW_UV_CACHE_INCOMPLETE')


def require_uv_cache(workspace, base):
    """Approved cache present, valid and sufficient for the Base lock; nothing is created or written."""
    cache = approved_uv_cache(workspace)
    cache_satisfies_lock(workspace, base, cache)
    return cache


def simulated_worktree(root, base):
    """A hint alone cannot bypass native preview in the production workspace."""
    hint = os.environ.get(SIM_ROOT)
    if not hint:
        return False
    workspace = Path(root).resolve()
    area = Path(hint).resolve()
    bare = area / 'origin.git'
    if (os.environ.get('GIT_CONFIG_GLOBAL') != str(area / 'isolated-gitconfig')
            or workspace != area / 'work' or bare.resolve() != bare
            or not bare.is_dir() or not (workspace / '.git').is_dir()
            or (workspace / '.git').resolve() != workspace / '.git'):
        raise PreviewError('NATIVE_PREVIEW_SIM_IDENTITY')
    try:
        checks = (
            (workspace, ('rev-parse', '--show-toplevel'), str(workspace)),
            (workspace, ('rev-parse', '--absolute-git-dir'), str(workspace / '.git')),
            (workspace, ('rev-parse', '--path-format=absolute', '--git-common-dir'), str(workspace / '.git')),
            (workspace, ('remote', 'get-url', '--all', 'origin'), str(bare)),
            (workspace, ('remote', 'get-url', '--push', '--all', 'origin'), str(bare)),
            (bare, ('rev-parse', '--is-bare-repository'), 'true'),
            (bare, ('rev-parse', '--verify', 'refs/heads/main'), base),
        )
        for directory, args, expected in checks:
            actual = br.git(str(directory), '--no-optional-locks', *args)
            matched = sim._same_path(actual, expected) if os.path.isabs(expected) else actual == expected
            if '\n' in actual or not matched:
                raise PreviewError('NATIVE_PREVIEW_SIM_IDENTITY')
    except br.Halt:
        raise PreviewError('NATIVE_PREVIEW_SIM_IDENTITY') from None
    return True


def checked_simulation_output(stdout, returncode, spec):
    """Require the complete canonical trace with exactly one successful terminal marker."""
    try:
        lines = stdout.decode('utf-8').splitlines()
    except UnicodeDecodeError:
        raise PreviewError('NATIVE_PREVIEW_LOG_INVALID') from None
    if returncode != 0:
        if lines[-1:] == ['BATCH_SIM FAIL BASE_NOT_IN_SOURCE']:
            raise PreviewError('BASE_NOT_IN_SOURCE')
        if lines[-1:] == ['BATCH_SIM FAIL SOURCE_MODIFIED']:
            raise PreviewError('NATIVE_PREVIEW_SOURCE_MODIFIED')
        raise PreviewError('NATIVE_PREVIEW_NONZERO')
    expected = ['BATCH_SIM STEP ' + step + ' rc=0'
                for step in (*sim.production_steps(spec), 'push')]
    if spec.get('bundle_output'):
        expected.append('BATCH_SIM POST_PUSH_BUNDLE NOT_TESTED')
    expected.append('BATCH_SIM PASS production locale=utf8 git_profile=windows')
    if lines != expected:
        raise PreviewError('NATIVE_PREVIEW_LOG_INVALID')


def run(batch):
    spec = batch.spec
    if simulated_worktree(batch.root, spec['base_oid']):
        print('NATIVE_PREVIEW SIMULATED_WORKTREE')
        return
    if os.name != 'nt':
        raise PreviewError('NATIVE_PREVIEW_WINDOWS_REQUIRED')
    temp = Path(tempfile.gettempdir()).resolve()
    workspace = Path(batch.root).resolve()
    if temp == workspace or workspace in temp.parents:
        raise PreviewError('NATIVE_PREVIEW_TEMP_OVERLAP')
    cache = require_uv_cache(workspace, spec['base_oid'])
    area = Path(tempfile.mkdtemp(prefix='hhai-g5-', dir=temp))
    batch.native_preview_evidence_dir = str(area)
    prompt = area / (batch.task_id + '-prompt.txt')
    prompt.write_bytes(batch.prompt_bytes)
    log = area / 'batch-sim.log'
    try:
        source_check = sim.Sim(workspace, area / 'source-check', verify_source_bytes=True)
        before = source_check.source_refs()
        try:
            result = run_bounded(
                [sys.executable, '-B', str(SIMULATOR), 'production', '--source', str(workspace),
                 '--workdir', str(area / 'sim'), '--prompt', str(prompt), '--git-profile', 'windows',
                 '--uv-cache-dir', str(cache), '--verify-source-bytes', *(['--adopt-source'] if spec['start']['mode'] == 'adopt' else [])],
                str(workspace), PREVIEW_TIMEOUT, env=br.child_env(), merge_stderr=False, capture_path=str(log))
        finally:
            if source_check.source_refs() != before:
                raise PreviewError('NATIVE_PREVIEW_SOURCE_MODIFIED')
    except sim.SimError:
        raise PreviewError('NATIVE_PREVIEW_SOURCE_UNREADABLE') from None
    if result.launch_error:
        raise PreviewError('NATIVE_PREVIEW_LAUNCH_FAILED')
    if result.timed_out:
        raise PreviewError('NATIVE_PREVIEW_TIMEOUT')
    if not log.is_file() or log.read_bytes() != result.stdout:
        raise PreviewError('NATIVE_PREVIEW_LOG_INVALID')
    checked_simulation_output(result.stdout, result.returncode, spec)
    batch.write_new_artifact('native-preview.json', json.dumps({
        'base_oid': spec['base_oid'],
        'prompt_sha256': hashlib.sha256(batch.prompt_bytes).hexdigest(),
        'log_sha256': hashlib.sha256(result.stdout).hexdigest(),
        'temp_name': area.name,
        'task_id': batch.task_id,
        'source_snapshot_sha256': hashlib.sha256(repr(before).encode('utf-8')).hexdigest(),
        'status': 'PASS',
    }, sort_keys=True) + '\n')
    print('NATIVE_PREVIEW PASS')


def require_receipt(batch):
    if simulated_worktree(batch.root, batch.spec['base_oid']):
        return
    try:
        artifact = Path(batch.root) / batch.artifact('native-preview.json')
        receipt = json.loads(artifact.read_bytes(), object_pairs_hook=br.reject_duplicate_json_keys)
        if (receipt['base_oid'] == batch.spec['base_oid']
                and receipt['task_id'] == batch.task_id
                and receipt['prompt_sha256'] == br.sha256_bytes(batch.prompt_bytes)
                and receipt['status'] == 'PASS'
                and br.SHA256_RE.fullmatch(receipt['log_sha256'])
                and br.SHA256_RE.fullmatch(receipt['source_snapshot_sha256'])
                and re.fullmatch(r'hhai-g5-[a-z0-9_]{8}', receipt['temp_name'])):
            directory = Path(tempfile.gettempdir()).resolve() / receipt['temp_name']
            log = directory / 'batch-sim.log'
            if directory.resolve() == directory and log.resolve() == log and log.is_file():
                output = log.read_bytes()
                if br.sha256_bytes(output) == receipt['log_sha256']:
                    checked_simulation_output(output, 0, batch.spec)
                    return
    except (OSError, ValueError, KeyError, TypeError):
        pass
    raise PreviewError('NATIVE_PREVIEW_RECEIPT_INVALID')
