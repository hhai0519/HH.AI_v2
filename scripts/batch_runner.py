#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/batch_runner.py
Canonical fixed-step batch runner (B-107).

The Macro Auditor delivers a prompt whose machine blocks describe one batch as data
(BATCH_SPEC_JSON, plus PLAN_JSON / ALLOWED_SCOPE_JSON / E24_EVIDENCE_JSON and any content
blocks). The Executor never writes or transcribes code: it runs one fixed command per step.

Usage (from the repository root):
  python scripts/batch_runner.py --task-id <TASK_ID> <step>
  python scripts/batch_runner.py --task-id <TASK_ID> timing

Prompt source: .git/<TASK_ID>-prompt.txt (created by scripts/prompt_intake.py).

Steps
  production: preflight setup [e24] apply [focused] generate precommit stage commit postcommit push
              (e24 when spec "e24" is true; focused when spec "focused" is not null)
  promotion:  preflight verify promote postmain
  timing:     prints TIMING and STATE lines; never changes state.

Invariants (fail closed; a failing step prints one "S1 <CODE> | step <name>" line and exits 1):
- .git/<TASK_ID>-control.json enforces the exact step order, each step exactly once, and locks the
  task after any failure. The control record binds the SHA-256 of the prompt and of this file; any
  later change to either is rejected (CONTROL_BINDING_DRIFT).
- preflight rejects a working-tree copy of this file that differs from the committed blob at HEAD.
- Every git call keeps stderr separate from stdout; path lists come only from NUL-separated stdout,
  so warnings such as CRLF conversion notices can never be parsed as paths.
- Author files are rebuilt only from declared sources (base blob, pinned blob, prompt block, or the
  verified current file in adopt mode) plus unique-anchor replacements, and must match the declared
  LF SHA-256 before anything is written.
- Gate steps write output to a file (never a pipe) and terminate the whole process tree on timeout.
- Main advancement exists only in promotion specs: native pinned full-SHA refspec push with a
  single-use MAIN_EXACT_SHA authorization consumed by the repository pre-push hook.
- Only task artifacts with the .git/<TASK_ID>- prefix, the declared author paths and the two
  canonical generator outputs are written. Nothing is deleted, reset, stashed or force-pushed.
"""

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 1
RUNNER_REL = 'scripts/batch_runner.py'
GENERATED = ('docs/fingerprints/exec-latest.json', 'docs/governance/execution-record.json')
AUTH_REL = '.git/hhai-sensitive-push-auth.json'
REPO = 'hhai0519/HH.AI_v2'
OID_RE = re.compile(r'^[0-9a-f]{40}$')
SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
TASK_RE = re.compile(r'^[A-Za-z0-9_-]+$')
BRANCH_RE = re.compile(r'^batch/[a-z0-9][a-z0-9._-]*$')
BLOCK_RE = re.compile(r'^[A-Z][A-Z0-9_]*$')
PY = sys.executable
PRODUCTION_STEPS = ('preflight', 'setup', 'e24', 'apply', 'focused', 'generate', 'precommit', 'stage', 'commit',
                    'postcommit', 'push')
PROMOTION_STEPS = ('preflight', 'verify', 'promote', 'postmain')
GATE_LIMITS = {'PRECOMMIT': 2400, 'STAGED': 900, 'POSTCOMMIT': 2400}


class Halt(Exception):
    """A fail-closed stop; the message is a fixed code without file content."""


# ---------------------------------------------------------------------------
# Process helpers: stdout and stderr are always separate; only stdout is parsed.
# ---------------------------------------------------------------------------

def child_env():
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


def run(args, label, root, timeout=600):
    try:
        r = subprocess.run(args, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=timeout, env=child_env())
    except subprocess.TimeoutExpired:
        raise Halt(label + '_TIMEOUT')
    except OSError:
        raise Halt(label + '_LAUNCH_FAILED')
    if r.returncode != 0:
        raise Halt(label)
    return r.stdout.decode('utf-8', 'replace')


def returncode(args, root, timeout=300):
    try:
        return subprocess.run(args, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=timeout, env=child_env()).returncode
    except subprocess.TimeoutExpired:
        raise Halt('COMMAND_TIMEOUT')
    except OSError:
        raise Halt('COMMAND_LAUNCH_FAILED')


def git(root, *args, label='GIT_FAILED', timeout=600):
    return run(['git', *args], label, root, timeout).strip()


def git_paths(root, *args):
    out = run(['git', *args], 'GIT_FAILED', root)
    return [p for p in out.split(chr(0)) if p]


def git_bytes(root, *args):
    try:
        r = subprocess.run(['git', *args], cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=120)
    except (subprocess.TimeoutExpired, OSError):
        raise Halt('GIT_READ_FAILED')
    if r.returncode != 0:
        raise Halt('GIT_READ_FAILED')
    return r.stdout


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def git_blob_sha1(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + bytes([0]) + data).hexdigest()


# ---------------------------------------------------------------------------
# Prompt blocks and batch specification
# ---------------------------------------------------------------------------

def prompt_lines(data):
    return data.decode('utf-8').replace(chr(13) + chr(10), chr(10)).split(chr(10))


def extract_block(lines, name):
    if not BLOCK_RE.match(name):
        raise Halt('BLOCK_NAME_INVALID')
    b = [i for i, s in enumerate(lines) if s == '<<<BEGIN ' + name + '>>>']
    e = [i for i, s in enumerate(lines) if s == '<<<END ' + name + '>>>']
    if not (len(b) == 1 and len(e) == 1 and b[0] < e[0]):
        raise Halt('BLOCK_BOUNDARY_INVALID')
    return chr(10).join(lines[b[0] + 1:e[0]])


def block_json(lines, name):
    try:
        return json.loads(extract_block(lines, name))
    except ValueError:
        raise Halt('BLOCK_JSON_INVALID')


def _require(cond, code):
    if not cond:
        raise Halt(code)


def load_spec(lines, task_id):
    """Parse and validate BATCH_SPEC_JSON together with its paired blocks."""
    spec = block_json(lines, 'BATCH_SPEC_JSON')
    _require(isinstance(spec, dict) and spec.get('schema_version') == SCHEMA_VERSION, 'SPEC_SCHEMA_INVALID')
    _require(spec.get('task_id') == task_id and TASK_RE.match(task_id), 'SPEC_TASK_MISMATCH')
    _require(isinstance(spec.get('base_oid'), str) and OID_RE.match(spec['base_oid']), 'SPEC_BASE_INVALID')
    kind = spec.get('kind')
    if kind == 'promotion':
        _require(isinstance(spec.get('candidate_oid'), str) and OID_RE.match(spec['candidate_oid']), 'SPEC_CANDIDATE_INVALID')
        _require(spec['candidate_oid'] != spec['base_oid'], 'SPEC_CANDIDATE_INVALID')
        _require(isinstance(spec.get('candidate_branch'), str) and BRANCH_RE.match(spec['candidate_branch']), 'SPEC_BRANCH_INVALID')
        return spec
    _require(kind == 'production', 'SPEC_KIND_INVALID')
    _require(isinstance(spec.get('branch'), str) and BRANCH_RE.match(spec['branch']), 'SPEC_BRANCH_INVALID')
    msg = spec.get('commit_message')
    _require(isinstance(msg, str) and msg.strip() == msg and msg and chr(10) not in msg and len(msg) <= 120, 'SPEC_MESSAGE_INVALID')
    _require(isinstance(spec.get('e24'), bool), 'SPEC_E24_INVALID')
    focused = spec.get('focused')
    if focused is not None:
        _require(isinstance(focused, dict) and isinstance(focused.get('pytest_args'), list) and focused['pytest_args']
                 and all(isinstance(a, str) and a for a in focused['pytest_args'])
                 and isinstance(focused.get('limit_sec'), int) and 60 <= focused['limit_sec'] <= 3600, 'SPEC_FOCUSED_INVALID')
    start = spec.get('start')
    _require(isinstance(start, dict) and start.get('mode') in ('clean', 'adopt'), 'SPEC_START_INVALID')
    authors = spec.get('authors')
    _require(isinstance(authors, dict) and authors, 'SPEC_AUTHORS_INVALID')
    for path, entry in authors.items():
        _require(isinstance(path, str) and path and not path.startswith('/') and '..' not in path.split('/')
                 and '\\' not in path and path not in GENERATED and not path.startswith('.git'), 'SPEC_AUTHOR_PATH_INVALID')
        _require(isinstance(entry, dict) and isinstance(entry.get('sha256'), str) and SHA256_RE.match(entry['sha256']), 'SPEC_AUTHOR_HASH_INVALID')
        src = entry.get('source')
        _require(isinstance(src, dict), 'SPEC_SOURCE_INVALID')
        if src.get('kind') == 'base':
            pass
        elif src.get('kind') == 'blob':
            _require(isinstance(src.get('oid'), str) and OID_RE.match(src['oid']), 'SPEC_SOURCE_INVALID')
        elif src.get('kind') == 'block':
            _require(isinstance(src.get('name'), str) and BLOCK_RE.match(src['name']) and src['name'] not in (
                'BATCH_SPEC_JSON', 'PLAN_JSON', 'ALLOWED_SCOPE_JSON', 'E24_EVIDENCE_JSON'), 'SPEC_SOURCE_INVALID')
        elif src.get('kind') == 'keep':
            _require(start['mode'] == 'adopt', 'SPEC_SOURCE_INVALID')
        else:
            raise Halt('SPEC_SOURCE_INVALID')
    ops = spec.get('ops')
    _require(isinstance(ops, list), 'SPEC_OPS_INVALID')
    for op in ops:
        _require(isinstance(op, dict) and op.get('path') in authors and isinstance(op.get('old'), str) and op['old']
                 and isinstance(op.get('new'), str), 'SPEC_OPS_INVALID')
        _require(authors[op['path']]['source']['kind'] != 'keep', 'SPEC_OPS_INVALID')
    if start['mode'] == 'adopt':
        _require(isinstance(start.get('start_branch'), str) and BRANCH_RE.match(start['start_branch'])
                 and start['start_branch'] != spec['branch'], 'SPEC_START_INVALID')
        adopt = start.get('adopt_hashes')
        _require(isinstance(adopt, dict) and adopt and set(adopt) <= set(authors)
                 and all(isinstance(v, str) and SHA256_RE.match(v) for v in adopt.values()), 'SPEC_START_INVALID')
        for path, entry in authors.items():
            if entry['source']['kind'] == 'keep':
                _require(adopt.get(path) == entry['sha256'], 'SPEC_START_INVALID')
    allowed = sorted(set(authors) | set(GENERATED))
    plan = block_json(lines, 'PLAN_JSON')
    _require(isinstance(plan, dict) and plan.get('task_id') == task_id and plan.get('base_oid') == spec['base_oid'], 'PLAN_BINDING_INVALID')
    _require(sorted(plan.get('allowed_paths') or []) == allowed and sorted(plan.get('required_paths') or []) == allowed, 'PLAN_SCOPE_MISMATCH')
    if spec['e24']:
        scope = block_json(lines, 'ALLOWED_SCOPE_JSON')
        _require(isinstance(scope, dict) and sorted(scope.get('allowed_scope') or []) == allowed, 'E24_SCOPE_MISMATCH')
        evidence = block_json(lines, 'E24_EVIDENCE_JSON')
        _require(isinstance(evidence, dict) and evidence.get('base_oid') == spec['base_oid'], 'E24_BINDING_DRIFT')
    return spec


def derive_steps(spec):
    if spec['kind'] == 'promotion':
        return list(PROMOTION_STEPS)
    steps = list(PRODUCTION_STEPS)
    if not spec['e24']:
        steps.remove('e24')
    if spec.get('focused') is None:
        steps.remove('focused')
    return steps


def allowed_paths(spec):
    return sorted(set(spec['authors']) | set(GENERATED))


# ---------------------------------------------------------------------------
# Author content
# ---------------------------------------------------------------------------

def apply_ops(texts, ops):
    for op in ops:
        text = texts[op['path']]
        if text.count(op['old']) != 1:
            raise Halt('ANCHOR_NOT_UNIQUE')
        texts[op['path']] = text.replace(op['old'], op['new'])
    return texts


def source_text(root, spec, lines, path):
    src = spec['authors'][path]['source']
    kind = src['kind']
    if kind == 'base':
        data = git_bytes(root, 'cat-file', 'blob', spec['base_oid'] + ':' + path)
    elif kind == 'blob':
        data = git_bytes(root, 'cat-file', 'blob', src['oid'])
        if git_blob_sha1(data) != src['oid']:
            raise Halt('SOURCE_BLOB_MISMATCH')
    elif kind == 'block':
        return extract_block(lines, src['name']) + chr(10)
    else:
        data = (Path(root) / path).read_bytes()
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        raise Halt('SOURCE_NOT_UTF8')
    if chr(13) in text:
        raise Halt('CRLF_INPUT')
    return text


def build_authors(root, spec, lines):
    texts = {path: source_text(root, spec, lines, path) for path in sorted(spec['authors'])}
    apply_ops(texts, spec['ops'])
    for path, text in texts.items():
        if sha256_bytes(text.encode('utf-8')) != spec['authors'][path]['sha256']:
            raise Halt('PREWRITE_HASH_MISMATCH')
    return texts


def verify_hashes(root, table, label):
    # Canonical LF-normalized comparison (CRLF -> LF) by the repository verification primitive.
    for path in sorted(table):
        run([PY, 'scripts/verification_primitives.py', 'sha256', '--file', path, '--expect-lf', table[path]], label, root)


def final_hashes(spec):
    return {path: entry['sha256'] for path, entry in spec['authors'].items()}


# ---------------------------------------------------------------------------
# Working tree state
# ---------------------------------------------------------------------------

def changed_paths(root, base):
    tracked = git_paths(root, 'diff', '--name-only', '-z', base)
    untracked = git_paths(root, 'ls-files', '--others', '--exclude-standard', '-z')
    return sorted(set(tracked) | set(untracked))


def staged_paths(root):
    return sorted(set(git_paths(root, 'diff', '--cached', '--name-only', '-z')))


def status_lines(root):
    return [x for x in git(root, 'status', '--porcelain=v1', '--untracked-files=all').split(chr(10)) if x.strip()]


def expect_head_clean(root, head, label):
    if git(root, 'rev-parse', 'HEAD') != head:
        raise Halt(label + '_HEAD_DRIFT')
    if status_lines(root):
        raise Halt(label + '_DIRTY')


def expect_scope(root, spec, label, exact):
    if git(root, 'rev-parse', 'HEAD') != spec['base_oid'] or git(root, 'branch', '--show-current') != spec['branch']:
        raise Halt(label + '_HEAD_DRIFT')
    actual = changed_paths(root, spec['base_oid'])
    allowed = allowed_paths(spec)
    if exact and actual != allowed:
        raise Halt(label + '_SCOPE_MISMATCH')
    if not set(actual) <= set(allowed):
        raise Halt(label + '_SCOPE_DRIFT')


# ---------------------------------------------------------------------------
# Bounded execution: output to a file, whole process tree terminated on timeout.
# ---------------------------------------------------------------------------

def kill_tree(proc):
    if os.name == 'nt':
        subprocess.run(['taskkill', '/T', '/F', '/PID', str(proc.pid)], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def bounded_run(args, cwd, log_path, limit):
    """Run args with output appended to log_path. Returns exit code, or None after a timeout."""
    kwargs = {}
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs['start_new_session'] = True
    with open(log_path, 'ab') as log:
        proc = subprocess.Popen(args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                env=child_env(), **kwargs)
        try:
            return proc.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            kill_tree(proc)
            try:
                proc.wait(timeout=120)
            except subprocess.TimeoutExpired:
                pass
            return None


class Batch:
    def __init__(self, root, task_id):
        self.root = root
        self.task_id = task_id
        self.prompt_rel = '.git/' + task_id + '-prompt.txt'
        self.control_rel = '.git/' + task_id + '-control.json'
        self.prompt_bytes = (Path(root) / self.prompt_rel).read_bytes()
        self.lines = prompt_lines(self.prompt_bytes)
        self.spec = load_spec(self.lines, task_id)

    def artifact(self, suffix):
        rel = '.git/' + self.task_id + '-' + suffix
        run([PY, 'scripts/governance_preflight.py', '--task-id', self.task_id, '--check-task-artifact', rel],
            'ARTIFACT_PATH_GUARD_FAILED', self.root, 120)
        return rel

    def write_new_artifact(self, suffix, text):
        rel = self.artifact(suffix)
        try:
            with open(Path(self.root) / rel, 'x', encoding='utf-8', newline='') as f:
                f.write(text)
        except FileExistsError:
            raise Halt('ARTIFACT_ALREADY_EXISTS')
        return rel

    def bounded(self, stage, args, limit):
        rel = self.artifact('bounded-' + stage.lower() + '.txt')
        path = Path(self.root) / rel
        if os.path.lexists(path):
            raise Halt(stage + '_ALREADY_RUN')
        path.touch(exist_ok=False)
        code = bounded_run([PY] + args, self.root, path, limit)
        tail = [l for l in path.read_bytes().decode('utf-8', 'replace').splitlines() if l.strip()]
        summary = tail[-1][:200] if tail else '(no output)'
        if code is None:
            print('BOUNDED_TIMEOUT ' + stage + ' limit=' + str(limit) + 's tree_terminated')
            raise Halt(stage + '_TIMEOUT')
        print('BOUNDED_EXIT ' + stage + ' code=' + str(code) + ' | ' + summary)
        if code != 0:
            raise Halt(stage + '_NONZERO')

    def gate(self, stage):
        self.bounded(stage, ['scripts/gate_runner.py', 'run', '--task-id', self.task_id, '--stage', stage], GATE_LIMITS[stage])
        run([PY, 'scripts/gate_runner.py', 'verify', '--task-id', self.task_id, '--stage', stage],
            stage + '_COMPLETION_UNPROVEN', self.root)

    def remote_sha(self, ref):
        out = git(self.root, 'ls-remote', 'origin', ref).split()
        return out[0] if out else ''

    def ci_status(self, sha, branch, attempts, interval):
        return returncode([PY, 'scripts/verification_primitives.py', 'ci-status', '--repo', REPO, '--head-sha', sha,
                           '--branch', branch, '--require-job', 'verify', '--require-job', 'gateway-windows',
                           '--event', 'push', '--workflow-name', 'Verify', '--max-attempts', str(attempts),
                           '--interval-seconds', str(interval)], self.root, timeout=attempts * (interval + 60) + 120)

    # -- shared -------------------------------------------------------------

    def step_preflight(self):
        head_blob = git(self.root, 'rev-parse', 'HEAD:' + RUNNER_REL, label='RUNNER_NOT_COMMITTED')
        if git_blob_sha1((Path(self.root) / RUNNER_REL).read_bytes()) != head_blob:
            raise Halt('RUNNER_MODIFIED')
        run([PY, 'scripts/validate_prompt_manifest.py', '--file', self.prompt_rel, '--require-contract'], 'PROMPT_MANIFEST_FAILED', self.root)
        run([PY, 'scripts/governance_preflight.py', '--task-id', self.task_id, '--prompt-file', self.prompt_rel], 'GOVERNANCE_PREFLIGHT_FAILED', self.root)
        run([PY, 'scripts/install_git_hooks.py', '--check'], 'HOOKS_CHECK_FAILED', self.root)

    # -- production -----------------------------------------------------------

    def step_setup(self):
        spec, root = self.spec, self.root
        base, branch = spec['base_oid'], spec['branch']
        run(['git', 'fetch', 'origin', 'main'], 'FETCH_FAILED', root, 300)
        if git(root, 'rev-parse', '--is-shallow-repository') != 'false':
            raise Halt('SHALLOW_CLONE')
        if git(root, 'rev-parse', 'origin/main') != base:
            raise Halt('ORIGIN_MAIN_DRIFT')
        start = spec['start']
        if start['mode'] == 'clean':
            expect_head_clean(root, base, 'SETUP')
        else:
            if git(root, 'rev-parse', 'HEAD') != base:
                raise Halt('START_BASE_DRIFT')
            if git(root, 'branch', '--show-current') != start['start_branch']:
                raise Halt('START_BRANCH_MISMATCH')
            if staged_paths(root):
                raise Halt('START_INDEX_NOT_EMPTY')
            if changed_paths(root, base) != allowed_paths(spec):
                raise Halt('START_SCOPE_MISMATCH')
            verify_hashes(root, start['adopt_hashes'], 'ADOPT_HASH_MISMATCH')
        if returncode(['git', 'ls-remote', '--exit-code', 'origin', 'refs/heads/' + branch], root) != 2:
            raise Halt('REMOTE_BRANCH_EXISTS_OR_UNKNOWN')
        if returncode(['git', 'rev-parse', '--verify', '--quiet', 'refs/heads/' + branch], root, 60) == 0:
            raise Halt('LOCAL_BRANCH_EXISTS')
        run(['git', 'switch', '-c', branch], 'BRANCH_CREATE_FAILED', root)
        if git(root, 'branch', '--show-current') != branch or git(root, 'rev-parse', 'HEAD') != base:
            raise Halt('BRANCH_DRIFT')
        if start['mode'] == 'clean':
            expect_head_clean(root, base, 'SETUP')
        else:
            if staged_paths(root):
                raise Halt('INDEX_NOT_EMPTY')
            expect_scope(root, spec, 'SETUP', exact=True)

    def step_e24(self):
        spec = self.spec
        expect_scope(self.root, spec, 'E24', exact=spec['start']['mode'] == 'adopt')
        if spec['start']['mode'] == 'clean' and status_lines(self.root):
            raise Halt('E24_DIRTY')
        ev = self.write_new_artifact('e24-disposition.json', extract_block(self.lines, 'E24_EVIDENCE_JSON') + chr(10))
        sc = self.write_new_artifact('allowed-scope.json', extract_block(self.lines, 'ALLOWED_SCOPE_JSON') + chr(10))
        run([PY, 'scripts/impact_scan.py', 'check', '--evidence-file', ev, '--allowed-scope-file', sc], 'E24_CHECK_FAILED', self.root)

    def step_apply(self):
        spec, root = self.spec, self.root
        if spec['start']['mode'] == 'adopt':
            expect_scope(root, spec, 'APPLY', exact=True)
            verify_hashes(root, spec['start']['adopt_hashes'], 'APPLY_START_HASH_MISMATCH')
        else:
            expect_head_clean(root, spec['base_oid'], 'APPLY')
            if git(root, 'branch', '--show-current') != spec['branch']:
                raise Halt('APPLY_HEAD_DRIFT')
        texts = build_authors(root, spec, self.lines)
        self.write_new_artifact('plan.json', extract_block(self.lines, 'PLAN_JSON') + chr(10))
        for path in sorted(texts):
            if spec['authors'][path]['source']['kind'] == 'keep':
                continue
            target = Path(root) / path
            if not target.parent.is_dir():
                raise Halt('PARENT_DIRECTORY_MISSING')
            with open(target, 'wb') as f:
                f.write(texts[path].encode('utf-8'))
        verify_hashes(root, final_hashes(spec), 'AUTHOR_HASH_MISMATCH')
        expect_scope(root, spec, 'APPLY', exact=False)

    def step_focused(self):
        spec = self.spec
        expect_scope(self.root, spec, 'FOCUSED', exact=False)
        verify_hashes(self.root, final_hashes(spec), 'FOCUSED_AUTHOR_DRIFT')
        self.bounded('FOCUSED', ['-m', 'pytest'] + spec['focused']['pytest_args'], spec['focused']['limit_sec'])
        expect_scope(self.root, spec, 'FOCUSED', exact=False)
        verify_hashes(self.root, final_hashes(spec), 'FOCUSED_AUTHOR_DRIFT')

    def step_generate(self):
        spec = self.spec
        expect_scope(self.root, spec, 'GENERATE', exact=False)
        run([PY, 'scripts/fingerprint.py', '--write'], 'FINGERPRINT_WRITE_FAILED', self.root)
        run([PY, 'scripts/execution_record.py', 'write', '--plan-file', '.git/' + self.task_id + '-plan.json'],
            'EXECUTION_RECORD_WRITE_FAILED', self.root)
        expect_scope(self.root, spec, 'GENERATE', exact=True)
        verify_hashes(self.root, final_hashes(spec), 'GENERATE_AUTHOR_DRIFT')

    def step_precommit(self):
        expect_scope(self.root, self.spec, 'PRECOMMIT', exact=True)
        self.gate('PRECOMMIT')
        expect_scope(self.root, self.spec, 'PRECOMMIT', exact=True)
        verify_hashes(self.root, final_hashes(self.spec), 'PRECOMMIT_AUTHOR_DRIFT')

    def step_stage(self):
        root, paths = self.root, allowed_paths(self.spec)
        expect_scope(root, self.spec, 'STAGE', exact=True)
        run(['git', 'add', '--', *paths], 'STAGE_FAILED', root)
        if staged_paths(root) != paths:
            raise Halt('STAGED_SET_MISMATCH')
        for line in status_lines(root):
            if not (line.startswith('M  ') or line.startswith('A  ')):
                raise Halt('UNSTAGED_OR_UNTRACKED_PRESENT')
        self.gate('STAGED')
        if staged_paths(root) != paths:
            raise Halt('STAGED_SET_DRIFT')

    def step_commit(self):
        root, spec = self.root, self.spec
        if git(root, 'rev-parse', 'HEAD') != spec['base_oid'] or git(root, 'branch', '--show-current') != spec['branch']:
            raise Halt('COMMIT_HEAD_DRIFT')
        run(['git', 'commit', '-m', spec['commit_message']], 'COMMIT_FAILED', root, 900)
        if git(root, 'rev-parse', 'HEAD~1') != spec['base_oid']:
            raise Halt('PARENT_DRIFT')
        if status_lines(root):
            raise Halt('DIRTY_AFTER_COMMIT')
        if sorted(set(git_paths(root, 'diff', '--name-only', '-z', spec['base_oid'], 'HEAD'))) != allowed_paths(spec):
            raise Halt('COMMITTED_SCOPE_MISMATCH')

    def step_postcommit(self):
        root, spec = self.root, self.spec
        head = git(root, 'rev-parse', 'HEAD')
        if git(root, 'rev-parse', 'HEAD~1') != spec['base_oid'] or git(root, 'branch', '--show-current') != spec['branch']:
            raise Halt('POSTCOMMIT_PARENT_DRIFT')
        self.gate('POSTCOMMIT')
        expect_head_clean(root, head, 'POSTCOMMIT')

    def step_push(self):
        root, spec = self.root, self.spec
        head = git(root, 'rev-parse', 'HEAD')
        expect_head_clean(root, head, 'PUSH')
        if git(root, 'rev-parse', 'HEAD~1') != spec['base_oid'] or git(root, 'branch', '--show-current') != spec['branch']:
            raise Halt('PUSH_BASE_DRIFT')
        run(['git', 'fetch', 'origin', 'main'], 'FETCH_FAILED', root, 300)
        if git(root, 'rev-parse', 'origin/main') != spec['base_oid']:
            raise Halt('PUSH_BASE_DRIFT')
        run(['git', 'push', 'origin', head + ':refs/heads/' + spec['branch']], 'PUSH_FAILED', root, 600)
        if self.remote_sha('refs/heads/' + spec['branch']) != head:
            raise Halt('PUSH_SHA_DRIFT')
        code = self.ci_status(head, spec['branch'], 60, 30)
        if code == 2:
            print('COMMIT ' + head + ' | CI PENDING | S1 NONE')
            return
        if code != 0:
            raise Halt('CANDIDATE_CI_NOT_PASS')
        print('COMMIT ' + head + ' | CI PASS | S1 NONE')

    # -- promotion -------------------------------------------------------------

    def step_verify(self):
        root, spec = self.root, self.spec
        base, cand, branch = spec['base_oid'], spec['candidate_oid'], spec['candidate_branch']
        run(['git', 'fetch', 'origin', 'main', branch], 'FETCH_FAILED', root, 300)
        if git(root, 'rev-parse', '--is-shallow-repository') != 'false':
            raise Halt('SHALLOW_CLONE')
        if git(root, 'rev-parse', 'HEAD') != cand or git(root, 'branch', '--show-current') != branch:
            raise Halt('LOCAL_HEAD_NOT_CANDIDATE')
        if status_lines(root):
            raise Halt('DIRTY_WORKTREE')
        if git(root, 'rev-parse', 'origin/main') != base or self.remote_sha('refs/heads/main') != base:
            raise Halt('MAIN_DRIFT')
        if self.remote_sha('refs/heads/' + branch) != cand:
            raise Halt('REMOTE_CANDIDATE_DRIFT')
        if git(root, 'rev-parse', cand + '~1') != base:
            raise Halt('CANDIDATE_PARENT_DRIFT')
        if returncode(['git', 'merge-base', '--is-ancestor', base, cand], root, 120) != 0:
            raise Halt('NOT_FAST_FORWARD')
        if os.path.lexists(Path(root) / AUTH_REL):
            raise Halt('STALE_AUTH_PRESENT')
        if self.ci_status(cand, branch, 3, 10) != 0:
            raise Halt('CANDIDATE_CI_NOT_PROVEN')

    def step_promote(self):
        root, spec = self.root, self.spec
        base, cand = spec['base_oid'], spec['candidate_oid']
        if git(root, 'rev-parse', 'HEAD') != cand or status_lines(root):
            raise Halt('LOCAL_STATE_DRIFT')
        if self.remote_sha('refs/heads/main') != base:
            raise Halt('MAIN_DRIFT')
        auth = Path(root) / AUTH_REL
        if os.path.lexists(auth):
            raise Halt('STALE_AUTH_PRESENT')
        run([PY, 'scripts/governance_preflight.py', '--create-main-auth', self.task_id, cand, base], 'MAIN_AUTH_CREATE_FAILED', root)
        # Exactly one transport: native pinned full-SHA refspec; the pre-push hook verifies and consumes the authorization.
        if returncode(['git', 'push', 'origin', cand + ':refs/heads/main'], root, 600) != 0:
            raise Halt('MAIN_PUSH_FAILED_' + ('AUTH_FILE_PRESENT' if os.path.lexists(auth) else 'AUTH_FILE_ABSENT'))
        if os.path.lexists(auth):
            raise Halt('MAIN_AUTH_NOT_CONSUMED')
        if self.remote_sha('refs/heads/main') != cand:
            raise Halt('MAIN_SHA_MISMATCH')
        print('MAIN_PROMOTED ' + cand)

    def step_postmain(self):
        cand = self.spec['candidate_oid']
        if self.remote_sha('refs/heads/main') != cand:
            raise Halt('MAIN_SHA_MISMATCH')
        code = self.ci_status(cand, 'main', 60, 30)
        if code == 2:
            print('MAIN ' + cand + ' | POST-MAIN CI PENDING | S1 NONE')
            return
        if code != 0:
            raise Halt('POST_MAIN_CI_NOT_PASS')
        print('MAIN ' + cand + ' | POST-MAIN CI PASS | S1 NONE')


# ---------------------------------------------------------------------------
# Control record and entry point
# ---------------------------------------------------------------------------

def load_control(batch):
    path = Path(batch.root) / batch.control_rel
    if not os.path.lexists(path):
        return None
    batch.artifact('control.json')
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except ValueError:
        raise Halt('CONTROL_INVALID')


def save_control(batch, control):
    batch.artifact('control.json')
    (Path(batch.root) / batch.control_rel).write_text(json.dumps(control, indent=2) + chr(10), encoding='utf-8')


def check_control(control, task_id, prompt_sha, runner_sha, steps, step):
    """Return 'OK' when step may run now, 'HALTED' when the task is locked; raise Halt otherwise."""
    if (control.get('task_id') != task_id or control.get('prompt_sha256') != prompt_sha
            or control.get('runner_sha256') != runner_sha):
        raise Halt('CONTROL_BINDING_DRIFT')
    if control.get('halted'):
        return 'HALTED'
    if step not in steps or control.get('done') != steps[:steps.index(step)]:
        raise Halt('STEP_ORDER_VIOLATION')
    return 'OK'


def timing(root, task_id):
    prompt = Path(root) / ('.git/' + task_id + '-prompt.txt')
    control = Path(root) / ('.git/' + task_id + '-control.json')
    start = datetime.fromtimestamp(os.path.getmtime(prompt)).astimezone()
    end = datetime.now().astimezone()
    sec = (end - start).total_seconds()
    c = {}
    if control.is_file():
        try:
            c = json.loads(control.read_text(encoding='utf-8'))
        except ValueError:
            c = {}
    print('TIMING start=' + start.isoformat() + ' end=' + end.isoformat() + ' elapsed_sec=' + str(round(sec, 1))
          + ' elapsed_min=' + str(int(sec // 60)))
    print('STATE done=' + ','.join(c.get('done', [])) + ' halted=' + str(c.get('halted')))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Canonical fixed-step batch runner (B-107).')
    parser.add_argument('--task-id', required=True)
    parser.add_argument('step')
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        print('S1 USAGE')
        return 2
    task_id, step = args.task_id, args.step
    root = str(Path(__file__).resolve().parent.parent)
    if not TASK_RE.match(task_id):
        print('S1 TASK_ID_INVALID')
        return 2
    try:
        if Path.cwd().resolve() != Path(root):
            raise Halt('WORKING_DIRECTORY_MISMATCH')
        if step == 'timing':
            timing(root, task_id)
            return 0
        batch = Batch(root, task_id)
        steps = derive_steps(batch.spec)
        if step not in steps:
            raise Halt('UNKNOWN_STEP')
        prompt_sha = sha256_bytes(batch.prompt_bytes)
        runner_sha = sha256_bytes((Path(root) / RUNNER_REL).read_bytes())
        control = load_control(batch)
        if control is None:
            if step != 'preflight':
                raise Halt('CONTROL_MISSING')
            control = {'task_id': task_id, 'prompt_sha256': prompt_sha, 'runner_sha256': runner_sha, 'done': [], 'halted': None}
            batch.write_new_artifact('control.json', json.dumps(control, indent=2) + chr(10))
        if check_control(control, task_id, prompt_sha, runner_sha, steps, step) == 'HALTED':
            print('S1 TASK_ALREADY_HALTED ' + str(control['halted']))
            return 1
    except Halt as h:
        print('S1 ' + str(h) + ' | step ' + step)
        return 1
    except (OSError, UnicodeDecodeError):
        print('S1 PROMPT_UNREADABLE | step ' + step)
        return 1
    try:
        getattr(batch, 'step_' + step)()
    except Halt as h:
        control['halted'] = step + ':' + str(h)
        save_control(batch, control)
        print('S1 ' + str(h) + ' | step ' + step)
        return 1
    except Exception as ex:  # noqa: BLE001 - any unexpected failure locks the task with a fixed code
        control['halted'] = step + ':UNEXPECTED_' + type(ex).__name__
        save_control(batch, control)
        print('S1 UNEXPECTED_' + type(ex).__name__ + ' | step ' + step)
        return 1
    control['done'].append(step)
    save_control(batch, control)
    print('STEP_PASS ' + step)
    return 0


if __name__ == '__main__':
    sys.exit(main())
