# -*- coding: utf-8 -*-
"""B-118: ref whitelist, no-overwrite, failure truth, and runner ordering controls."""
import os
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bundle_after_push as bund
import batch_runner as br


def g(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL).decode().strip()


@pytest.fixture
def small_repo(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    g(repo, 'init', '-q')
    g(repo, 'config', 'user.email', 'test@example.invalid')
    g(repo, 'config', 'user.name', 'Tester')
    (repo / 'a').write_text('a\n')
    g(repo, 'add', 'a')
    g(repo, 'commit', '-q', '-m', 'base')
    base = g(repo, 'rev-parse', 'HEAD')
    g(repo, 'update-ref', 'refs/remotes/origin/main', base)
    g(repo, 'switch', '-q', '-c', 'batch/b118-test')
    (repo / 'a').write_text('b\n')
    g(repo, 'commit', '-qam', 'candidate')
    head = g(repo, 'rev-parse', 'HEAD')
    g(repo, 'update-ref', 'refs/remotes/origin/batch/b118-test', head)
    dl = tmp_path / 'Downloads'
    dl.mkdir()
    return repo, dl, base, head


def test_bundle_exact_refs_non_stash_and_timezone(small_repo):
    root, dl, base, head = small_repo
    g(root, 'update-ref', 'refs/stash', head)
    clock = datetime(2026, 10, 14, 15, 35, 9, tzinfo=timezone(timedelta(hours=8)))
    target = bund.create_bundle(root, 'batch/b118-test', base, head, dl, clock, 'B118-TEST')
    assert Path(target).name == 'HH.AI_v2-20261014-153509-' + base[:7] + '.bundle'
    assert 'complete history' in g(root, 'bundle', 'verify', target)
    heads = g(root, 'bundle', 'list-heads', target)
    assert base + ' refs/remotes/origin/main' in heads
    assert head + ' refs/remotes/origin/batch/b118-test' in heads
    assert 'refs/stash' not in heads
    assert (root / '.git/B118-TEST-bundle.tmp').is_file()


def test_bundle_collision_is_non_destructive(small_repo):
    root, dl, base, head = small_repo
    clock = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)
    name = 'HH.AI_v2-20261014-230000-' + base[:7] + '.bundle'
    (dl / name).write_bytes(b'preserve')
    with pytest.raises(bund.BundleFailure, match='BUNDLE_EXISTS'):
        bund.create_bundle(root, 'batch/b118-test', base, head, dl, clock, 'B118-TEST')
    assert (dl / name).read_bytes() == b'preserve'


def test_untrusted_path_fails_closed(small_repo, tmp_path):
    root, dl, base, head = small_repo
    link = tmp_path / 'link'
    try:
        link.symlink_to(dl, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('symlink creation unavailable')
    with pytest.raises(bund.BundleFailure, match='DOWNLOADS_UNSAFE'):
        bund.create_bundle(root, 'batch/b118-test', base, head, link, task_id='B118-TEST')


def test_ref_mismatch_and_invalid_branch_rejected(small_repo):
    root, dl, base, head = small_repo
    with pytest.raises(bund.BundleFailure, match='ARGUMENT_INVALID'):
        bund.create_bundle(root, 'refs/stash', base, head, dl, task_id='B118-TEST')
    g(root, 'update-ref', 'refs/remotes/origin/main', head)
    with pytest.raises(bund.BundleFailure, match='TRACKING_MAIN_DRIFT'):
        bund.create_bundle(root, 'batch/b118-test', base, head, dl, task_id='B118-TEST')


def test_missing_tracking_candidate_bounded_materialization(small_repo):
    root, dl, base, head = small_repo
    g(root, 'update-ref', '-d', 'refs/remotes/origin/batch/b118-test')
    refs = bund.allowed_refs(str(root), 'batch/b118-test', base, head)
    assert refs['refs/remotes/origin/batch/b118-test'] == head
    assert g(root, 'rev-parse', 'refs/remotes/origin/batch/b118-test') == head


def test_step_order_legacy_runner_update_and_new_production():
    legacy = {'kind': 'production', 'e24': False, 'focused': None, 'runner_update': True}
    assert br.derive_steps(legacy)[-1] == 'push'
    enabled = dict(legacy, bundle_output=True)
    assert br.derive_steps(enabled)[-2:] == ['push', 'bundle']
    assert br.derive_steps({'kind': 'promotion'}) == ['preflight', 'verify', 'promote', 'postmain']
    c = {'task_id': 'T', 'prompt_sha256': 'p', 'runner_sha256': 'r',
         'done': br.derive_steps(enabled)[:-1], 'halted': None}
    assert br.check_control(c, 'T', 'p', 'r', br.derive_steps(enabled), 'bundle') == 'OK'
    with pytest.raises(br.Halt, match='STEP_ORDER_VIOLATION'):
        br.check_control(c, 'T', 'p', 'r', br.derive_steps(enabled), 'push')


def test_bundle_error_after_push_is_non_halting(monkeypatch, small_repo, capsys):
    root, dl, base, head = small_repo
    b = br.Batch.__new__(br.Batch)
    b.root = str(root)
    b.task_id = 'B118-TEST'
    b.spec = {'kind': 'production', 'base_oid': base, 'branch': 'batch/b118-test'}
    monkeypatch.setattr(br, 'status_lines', lambda *_: [])
    monkeypatch.setattr(b, 'remote_sha', lambda ref: base if ref.endswith('/main') else head)
    monkeypatch.setattr(br, 'create_bundle', lambda *a, **k: (_ for _ in ()).throw(bund.BundleFailure('BUNDLE_EXISTS')))
    # Must not call step_push or CI again after a bundle error.
    monkeypatch.setattr(b, 'step_push', lambda: (_ for _ in ()).throw(AssertionError('re-push')))
    assert b.step_bundle() == 'FAILED_BUNDLE_EXISTS'
    assert 'BUNDLE FAILED BUNDLE_EXISTS' in capsys.readouterr().out


def test_symbolic_origin_head_not_exported(small_repo):
    root, dl, base, head = small_repo
    g(root, 'symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/main')
    refs = bund.allowed_refs(str(root), 'batch/b118-test', base, head)
    assert 'refs/remotes/origin/HEAD' not in refs
    assert refs['refs/remotes/origin/main'] == base


def test_git_command_nonzero_never_leaks_raw_output(monkeypatch, small_repo):
    root, dl, base, head = small_repo
    class R:
        returncode = 128
        stdout = b'secret-invalid-output'
        stderr = b'credential value must not be logged'
    monkeypatch.setattr(bund.subprocess, 'run', lambda *args, **kwargs: R())
    with pytest.raises(bund.BundleFailure, match='GIT_NONZERO'):
        bund.git(str(root), 'for-each-ref', 'refs/remotes/origin')


# B-118 first-activation runner and ref fail-closed regression coverage.
@pytest.mark.parametrize('remote_ref,reason', [
    ('refs/heads/main', 'MAIN_DRIFT'),
    ('refs/heads/batch/b118-test', 'REMOTE_SHA_DRIFT'),
])
def test_first_bundle_step_remote_drift_fails_without_retry(small_repo, monkeypatch, capsys, remote_ref, reason):
    root, dl, base, head = small_repo
    b = br.Batch.__new__(br.Batch)
    b.root = str(root)
    b.task_id = 'B118-TEST'
    b.spec = {'kind': 'production', 'base_oid': base, 'branch': 'batch/b118-test'}
    monkeypatch.setattr(br, 'status_lines', lambda *_: [])
    def remote(ref):
        if ref == remote_ref:
            return 'f' * 40
        return base if ref.endswith('/main') else head
    monkeypatch.setattr(b, 'remote_sha', remote)
    monkeypatch.setattr(br, 'create_bundle', lambda *args, **kw: (_ for _ in ()).throw(AssertionError('bundle must not run')) )
    assert b.step_bundle() == 'FAILED_' + reason
    assert 'BUNDLE FAILED ' + reason in capsys.readouterr().out


def test_first_bundle_step_rejects_unlisted_tracking_ref(small_repo):
    root, dl, base, head = small_repo
    g(root, 'update-ref', 'refs/remotes/origin/UpperCase', head)
    with pytest.raises(bund.BundleFailure, match='REF_NOT_WHITELISTED'):
        bund.allowed_refs(str(root), 'batch/b118-test', base, head)


def test_first_bundle_step_rejects_extra_bundle_ref(small_repo, monkeypatch):
    root, dl, base, head = small_repo
    real = bund.git
    def modified(r, *args, **kwargs):
        text = real(r, *args, **kwargs)
        if args[:2] == ('bundle','list-heads'):
            return text + '\n' + head + ' refs/stash'
        return text
    monkeypatch.setattr(bund, 'git', modified)
    with pytest.raises(bund.BundleFailure, match='BUNDLE_REFS_MISMATCH'):
        bund.create_bundle(root, 'batch/b118-test', base, head, dl, task_id='B118-TEST')


def test_first_activation_candidate_tracking_sha_drift_is_fatal(small_repo):
    root, dl, base, head = small_repo
    g(root, 'update-ref', 'refs/remotes/origin/batch/b118-test', base)
    with pytest.raises(bund.BundleFailure, match='TRACKING_CANDIDATE_DRIFT'):
        bund.allowed_refs(str(root), 'batch/b118-test', base, head)


def test_first_activation_copy_verify_mismatch_is_fatal(small_repo, monkeypatch):
    root, dl, base, head = small_repo
    real = bund.git
    counts = {'list_heads': 0}
    def corrupt(r, *args, **kwargs):
        val = real(r, *args, **kwargs)
        if args[:2] == ('bundle', 'list-heads'):
            counts['list_heads'] += 1
            if counts['list_heads'] == 2:
                return val + '\nCORRUPTED COPY'
        return val
    monkeypatch.setattr(bund, 'git', corrupt)
    with pytest.raises(bund.BundleFailure, match='COPY_VERIFY_FAILED'):
        bund.create_bundle(root, 'batch/b118-test', base, head, dl, task_id='B118-COPY')
    assert counts['list_heads'] == 2


def test_first_activation_git_env_isolation_passed_to_child(small_repo, monkeypatch):
    root, dl, base, head = small_repo
    seen = {}
    class Result:
        returncode = 0
        stdout = b'visible\n'
        stderr = b''
    def fake(cmd, **kw):
        seen.update(kw['env'])
        assert cmd[0] == 'git'
        return Result()
    monkeypatch.setattr(bund.subprocess, 'run', fake)
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', '/tmp/unsafe')
    monkeypatch.setenv('GIT_ASKPASS', '/tmp/unsafe-askpass')
    assert bund.git(str(root), 'status') == 'visible'
    assert seen['GIT_CONFIG_NOSYSTEM'] == '1'
    assert seen['GIT_CONFIG_GLOBAL'] == os.devnull
    assert seen['GIT_TERMINAL_PROMPT'] == '0'
    assert seen['GCM_INTERACTIVE'] == 'Never'
    assert 'GIT_ASKPASS' not in seen


def test_first_activation_real_bundle_positive_has_no_extra_refs(small_repo):
    root, dl, base, head = small_repo
    g(root, 'update-ref', 'refs/stash', head)
    dst = bund.create_bundle(root, 'batch/b118-test', base, head, dl, task_id='B118-REAL')
    listed = g(root, 'bundle', 'list-heads', dst)
    expected = bund.allowed_refs(str(root), 'batch/b118-test', base, head)
    observed = {parts[1]: parts[0] for x in listed.splitlines() if (parts:=x.split())}
    assert observed == expected
    assert 'refs/stash' not in observed


@pytest.mark.parametrize('outcome', ['FAILED_BUNDLE_EXISTS', 'READY'])
def test_bundle_result_is_persisted_and_printed_by_real_runner_entrypoint(
        tmp_path, monkeypatch, capsys, outcome):
    """F4: exercise actual main -> save_control -> timing/STATE; not just step ordering.

    A FAILED_* after push must never be serialized as READY or dropped from STATE.
    The READY control proves the positive case exercises the same real code path.
    """
    root = tmp_path / 'repo'
    scripts = root / 'scripts'
    scripts.mkdir(parents=True)
    git_dir = root / '.git'
    git_dir.mkdir()
    task = 'B118-F4-STATE-TEST-261014'
    fake_runner = scripts / 'batch_runner.py'
    fake_runner.write_bytes(b'runner for F4 deterministic test\n')
    (git_dir / (task + '-prompt.txt')).write_bytes(b'F4 test prompt\n')
    spec = {'kind': 'production', 'e24': False, 'focused': None,
            'bundle_output': True}
    steps = br.derive_steps(spec)
    assert steps[-2:] == ['push', 'bundle']
    control_path = git_dir / (task + '-control.json')
    control_path.write_text(__import__('json').dumps({
        'task_id': task,
        'prompt_sha256': br.sha256_bytes(b'F4 test prompt\n'),
        'runner_sha256': br.sha256_bytes(fake_runner.read_bytes()),
        'done': steps[:-1],
        'halted': None,
    }) + '\n', encoding='utf-8')

    class FakeBatch:
        def __init__(self, cwd, task_id):
            self.root, self.task_id = cwd, task_id
            self.spec = spec
            self.prompt_bytes = b'F4 test prompt\n'
            self.control_rel = '.git/' + task_id + '-control.json'

        def artifact(self, suffix):
            return '.git/' + task + '-' + suffix

        def step_bundle(self):
            # Post-push side effect is mocked; state handling is NOT mocked.
            return outcome

    monkeypatch.setattr(br, 'Batch', FakeBatch)
    monkeypatch.setattr(br, '__file__', str(fake_runner))
    monkeypatch.chdir(root)
    assert br.main(['--task-id', task, 'bundle']) == 0
    post = __import__('json').loads(control_path.read_text(encoding='utf-8'))
    assert post['bundle_outcome'] == outcome
    assert post['done'] == steps
    assert post['halted'] is None
    assert br.main(['--task-id', task, 'timing']) == 0
    stdout = capsys.readouterr().out
    assert 'STATE done=' in stdout
    assert ' bundle=' + outcome in stdout
    assert (' bundle=READY' in stdout) is (outcome == 'READY')


def test_bundle_outcome_is_absent_when_disabled(tmp_path, monkeypatch, capsys):
    # The default false production must not fabricate an optional bundle result.
    task = 'B118-F4-FALSE-TEST-261014'
    root = tmp_path / 'repo'
    (root / '.git').mkdir(parents=True)
    prompt = root / '.git' / (task + '-prompt.txt')
    prompt.write_bytes(b'false prompt\n')
    control = root / '.git' / (task + '-control.json')
    control.write_text(__import__('json').dumps({
        'done': br.derive_steps({'kind': 'production', 'e24': False,
                                 'focused': None, 'bundle_output': False}),
        'halted': None,
    }), encoding='utf-8')
    br.timing(str(root), task)
    line = capsys.readouterr().out.splitlines()[-1]
    assert line.startswith('STATE done=')
    assert ' bundle=' not in line


def test_copy_normal_hash_and_actual_bare_fetch(small_repo, tmp_path):
    """Real bytes, not just bundle header, must import into a fresh empty repo."""
    root, dl, base, head = small_repo
    output = bund.create_bundle(root, 'batch/b118-test', base, head, dl, task_id='F3-COPY-GOOD')
    temp = root / '.git/F3-COPY-GOOD-bundle.tmp'
    assert bund.file_sha256(temp) == bund.file_sha256(Path(output))
    imported = tmp_path / 'import.git'
    g(tmp_path, 'init', '-q', '--bare', str(imported))
    fetched = subprocess.run(['git', '-C', str(imported), 'fetch', output,
                              'refs/remotes/origin/*:refs/remotes/origin/*'], capture_output=True)
    assert fetched.returncode == 0
    assert g(imported, 'rev-parse', 'refs/remotes/origin/main') == base
    assert g(imported, 'rev-parse', 'refs/remotes/origin/batch/b118-test') == head


def test_equal_length_pack_corruption_is_failed_not_ready(small_repo, monkeypatch, capsys):
    """Post-copy bit flip must not result in READY or another push."""
    root, dl, base, head = small_repo
    original = bund.shutil.copyfileobj

    def flip_trailer(src, dst, length):
        blob = bytearray(src.read())
        assert len(blob) > 50
        blob[-1] ^= 1
        dst.write(blob)

    monkeypatch.setattr(bund.shutil, 'copyfileobj', flip_trailer)
    with pytest.raises(bund.BundleFailure, match='COPY_HASH_MISMATCH'):
        bund.create_bundle(root, 'batch/b118-test', base, head, dl, task_id='F3-CORRUPTED')
    assert (root / '.git/F3-CORRUPTED-bundle.tmp').stat().st_size == next(dl.glob('*.bundle')).stat().st_size
    damaged = next(dl.glob('*.bundle'))
    assert bund.file_sha256(root / '.git/F3-CORRUPTED-bundle.tmp') != bund.file_sha256(damaged)
    # The header-only verify can still succeed; an actual object import must fail.
    assert subprocess.run(['git', '-C', str(root), 'bundle', 'verify', str(damaged)], capture_output=True).returncode == 0
    imported = root.parent / 'corrupted-import.git'
    g(root.parent, 'init', '-q', '--bare', str(imported))
    assert subprocess.run(['git', '-C', str(imported), 'fetch', str(damaged),
                           'refs/remotes/origin/*:refs/remotes/origin/*'], capture_output=True).returncode != 0
    # Separate isolated repo so this failure path also exercises runner.step_bundle.
    other = br.Batch.__new__(br.Batch)
    other.root, other.task_id = str(root), 'F3-CORRUPTED-AGAIN'
    other.spec = {'kind': 'production', 'base_oid': base, 'branch': 'batch/b118-test'}
    other.remote_sha = lambda ref: base if ref == 'refs/heads/main' else head
    monkeypatch.setattr(br, 'status_lines', lambda *_: [])
    monkeypatch.setattr(br, 'create_bundle', lambda *args, **kwargs: (_ for _ in ()).throw(bund.BundleFailure('COPY_HASH_MISMATCH')))
    other.step_push = lambda: (_ for _ in ()).throw(AssertionError('must never push again'))
    assert other.step_bundle() == 'FAILED_COPY_HASH_MISMATCH'
    out = capsys.readouterr().out
    assert 'BUNDLE FAILED COPY_HASH_MISMATCH' in out
    assert 'READY' not in out
