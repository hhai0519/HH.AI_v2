# -*- coding: utf-8 -*-
"""B-119 G1 S1 recovery tool: real-Git positive, idempotence, interruption and fail-closed controls.

Files are written as bytes only, so platform newline translation cannot change any input.
"""
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import s1_recover as rc  # noqa: E402

TASK = 'B119-S1-RECOVER-UNIT-261024'
BRANCH = 'batch/b119-s1-recover-unit-261024'
ALLOWED = ['docs/A.md', 'docs/B.md', 'docs/NEW.md', 'scripts/tool.py']


def git(repo, *args, data=None):
    p = subprocess.run(['git', '-C', str(repo), *args], input=data, capture_output=True, check=True, timeout=60)
    return p.stdout.decode('utf-8').strip()


def _block(name, obj):
    return '<<<BEGIN %s>>>\n%s\n<<<END %s>>>\n' % (name, json.dumps(obj, indent=1), name)


def make_prompt(base, allowed=ALLOWED):
    authors = {p: {'sha256': 'a' * 64, 'source': {'kind': 'base'}} for p in allowed}
    spec = {'schema_version': 1, 'task_id': TASK, 'kind': 'production', 'base_oid': base, 'branch': BRANCH,
            'commit_message': 'unit', 'e24': False, 'focused': None, 'start': {'mode': 'clean'},
            'authors': authors, 'ops': []}
    every = sorted(set(allowed) | {'docs/fingerprints/exec-latest.json', 'docs/governance/execution-record.json'})
    plan = {'task_id': TASK, 'base_oid': base, 'allowed_paths': every, 'required_paths': every}
    return ('unit prompt\n' + _block('BATCH_SPEC_JSON', spec) + _block('PLAN_JSON', plan)).encode('utf-8')


@pytest.fixture
def ws(tmp_path, monkeypatch):
    origin, work = tmp_path / 'origin.git', tmp_path / 'work'
    subprocess.run(['git', 'init', '-q', '--bare', str(origin)], check=True)
    subprocess.run(['git', 'init', '-q', str(work)], check=True)
    git(work, 'config', 'user.name', 'T'); git(work, 'config', 'user.email', 't@example.invalid')
    git(work, 'config', 'core.autocrlf', 'false')
    for rel, data in (('docs/A.md', b'a base\n'), ('docs/B.md', b'b base\n'), ('scripts/tool.py', b'x = 1\n'),
                      ('README.md', b'readme\n')):
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_bytes(data)
    git(work, 'add', '.'); git(work, 'commit', '-qm', 'base')
    base = git(work, 'rev-parse', 'HEAD')
    git(work, 'branch', '-M', 'main'); git(work, 'remote', 'add', 'origin', str(origin))
    git(work, 'push', '-q', 'origin', 'main')
    git(work, 'branch', 'keep-old', base)
    prompt = make_prompt(base)
    (work / '.git' / (TASK + '-prompt.txt')).write_bytes(prompt)
    git(work, 'switch', '-qc', BRANCH)
    monkeypatch.chdir(work)
    return work, base, hashlib.sha256(prompt).hexdigest()


def dirty_uncommitted(work):
    (work / 'docs/A.md').write_bytes(b'a S1 change\r\nwith CRLF\r\n')        # modified, CRLF bytes
    (work / 'docs/B.md').write_bytes(b'b staged\n'); git(work, 'add', 'docs/B.md')
    (work / 'docs/B.md').write_bytes(b'b staged then edited\n')              # index != worktree
    (work / 'docs/NEW.md').write_bytes(b'new untracked author file\n')        # untracked
    (work / 'scripts/tool.py').unlink()                                       # deleted


def run(capsys, *argv):
    code = rc.main(list(argv))
    text = capsys.readouterr().out
    return code, text, dict(line.split('=', 1) for line in text.splitlines() if '=' in line and line.split('=', 1)[0].isupper())


def snapshot(work):
    return (git(work, 'for-each-ref', 'refs/heads', 'refs/remotes'), git(work, 'status', '--porcelain=v1', '--untracked-files=all'),
            git(work, 'rev-parse', 'HEAD'), git(work, 'ls-files', '-s'),
            sorted((p.relative_to(work).as_posix(), p.read_bytes()) for p in work.rglob('*')
                   if p.is_file() and '.git' not in p.relative_to(work).parts))


def preserve(capsys, sha):
    code, text, kv = run(capsys, 'preserve', '--task-id', TASK, '--prompt-sha256', sha)
    assert code == 0, text
    return kv


def test_uncommitted_preserve_restore_verify_round_trip(ws, capsys):
    work, base, sha = ws
    dirty_uncommitted(work)
    original = {p: (work / p).read_bytes() for p in ('docs/A.md', 'docs/B.md', 'docs/NEW.md')}
    staged_b = git(work, 'ls-files', '-s', '--', 'docs/B.md').split()[1]
    before = snapshot(work)
    kv = preserve(capsys, sha)
    assert snapshot(work) == before                                   # preserve changes no worktree or index
    plan = json.loads(kv['S1_RECOVER_PLAN_JSON'])
    assert hashlib.sha256(kv['S1_RECOVER_PLAN_JSON'].encode()).hexdigest() == kv['S1_RECOVER_PLAN_SHA256']
    assert {a['path']: a['action'] for a in plan['actions']} == {
        'docs/A.md': 'RESTORE_TRACKED', 'docs/B.md': 'RESTORE_TRACKED',
        'docs/NEW.md': 'DELETE_NEW', 'scripts/tool.py': 'RESTORE_TRACKED'}
    oid = kv['S1_PRESERVED_OID']
    assert git(work, 'rev-parse', rc.REF_PREFIX + TASK) == oid
    code, text, _ = run(capsys, 'restore', '--task-id', TASK, '--prompt-sha256', sha,
                        '--preserved-oid', oid, '--plan-sha256', kv['S1_RECOVER_PLAN_SHA256'])
    assert code == 0 and text.splitlines()[-1] == 'WORKSPACE_AT_BASE_READY', text
    assert git(work, 'rev-parse', 'HEAD') == base
    assert subprocess.run(['git', '-C', str(work), 'symbolic-ref', '-q', 'HEAD'], capture_output=True).returncode == 1
    assert git(work, 'status', '--porcelain=v1', '--untracked-files=all') == ''
    assert git(work, 'rev-parse', 'refs/heads/' + BRANCH) == base and git(work, 'rev-parse', 'refs/heads/keep-old') == base
    assert not (work / 'docs/NEW.md').exists() and (work / 'scripts/tool.py').read_bytes() == b'x = 1\n'
    # Every preserved byte is retrievable from the ref after an aggressive gc.
    git(work, 'gc', '-q', '--prune=now')
    _, records = rc.read_snapshot(work, oid)
    got = {r['path']: rc.blob_bytes(work, r['worktree']['oid']) for r in records if r['worktree']}
    assert got == original
    assert {r['path']: r['index']['oid'] for r in records if r['index']}['docs/B.md'] == staged_b
    code, text, _ = run(capsys, 'verify', '--task-id', TASK, '--prompt-sha256', sha, '--preserved-oid', oid)
    assert code == 0 and 'S1_RECOVER VERIFIED' in text


def test_preserve_is_idempotent_and_never_moves_existing_ref(ws, capsys):
    work, base, sha = ws
    dirty_uncommitted(work)
    first = preserve(capsys, sha)
    second = preserve(capsys, sha)
    assert first == second
    (work / 'docs/A.md').write_bytes(b'changed after preserve\n')
    before = snapshot(work)
    code, text, _ = run(capsys, 'preserve', '--task-id', TASK, '--prompt-sha256', sha)
    assert code == 1 and 'S1_RECOVER STOP PRESERVED_REF_CONFLICT' in text
    assert git(work, 'rev-parse', rc.REF_PREFIX + TASK) == first['S1_PRESERVED_OID']
    assert snapshot(work) == before


def test_restore_after_partial_run_resumes_and_is_idempotent(ws, capsys, monkeypatch):
    work, base, sha = ws
    dirty_uncommitted(work)
    kv = preserve(capsys, sha)
    args = ['restore', '--task-id', TASK, '--prompt-sha256', sha, '--preserved-oid', kv['S1_PRESERVED_OID'],
            '--plan-sha256', kv['S1_RECOVER_PLAN_SHA256']]
    real = rc.git
    calls = {'n': 0}
    def fail_second_restore(root, *a, **k):
        if a and a[0] == 'restore':
            calls['n'] += 1
            if calls['n'] == 2:
                raise rc.Stop('GIT_FAILED')
        return real(root, *a, **k)
    monkeypatch.setattr(rc, 'git', fail_second_restore)
    code, text, _ = run(capsys, *args)
    assert code == 1 and 'S1_RECOVER STOP GIT_FAILED' in text and 'WORKSPACE_AT_BASE_READY' not in text
    assert git(work, 'rev-parse', rc.REF_PREFIX + TASK) == kv['S1_PRESERVED_OID']
    monkeypatch.setattr(rc, 'git', real)
    code, text, _ = run(capsys, *args)                                # resume
    assert code == 0 and text.splitlines()[-1] == 'WORKSPACE_AT_BASE_READY', text
    code, text, _ = run(capsys, *args)                                # already at target
    assert code == 0 and text.splitlines()[-1] == 'WORKSPACE_AT_BASE_READY', text


def test_restore_stops_when_a_path_was_edited_after_interruption(ws, capsys, monkeypatch):
    work, base, sha = ws
    dirty_uncommitted(work)
    kv = preserve(capsys, sha)
    args = ['restore', '--task-id', TASK, '--prompt-sha256', sha, '--preserved-oid', kv['S1_PRESERVED_OID'],
            '--plan-sha256', kv['S1_RECOVER_PLAN_SHA256']]
    real = rc.git
    def fail_first_restore(root, *a, **k):
        if a and a[0] == 'restore':
            raise rc.Stop('GIT_FAILED')
        return real(root, *a, **k)
    monkeypatch.setattr(rc, 'git', fail_first_restore)
    assert run(capsys, *args)[0] == 1
    monkeypatch.setattr(rc, 'git', real)
    (work / 'docs/NEW.md').write_bytes(b'edited by someone after the interruption\n')
    before = snapshot(work)
    code, text, _ = run(capsys, *args)
    assert code == 1 and 'S1_RECOVER STOP PATH_STATE_UNEXPECTED' in text and 'WORKSPACE_AT_BASE_READY' not in text
    assert snapshot(work) == before                                   # classified before the first write


@pytest.mark.parametrize('mutate,code', [
    (lambda w: (w / 'README.md').write_bytes(b'outside plan\n'), 'PATH_OUTSIDE_PLAN'),
    (lambda w: git(w, 'switch', '-qc', 'batch/other-branch-261024'), 'BRANCH_MISMATCH'),
    (lambda w: (git(w, 'stash', '-q'), git(w, 'commit', '-q', '--allow-empty', '-m', 'x'),
                git(w, 'commit', '-q', '--allow-empty', '-m', 'y'), git(w, 'stash', 'pop', '-q')),
     'HEAD_NOT_ONE_COMMIT_ON_BASE'),
])
def test_preserve_preconditions_stop_without_any_write(ws, capsys, mutate, code):
    work, base, sha = ws
    dirty_uncommitted(work)
    mutate(work)
    before = snapshot(work)
    rcode, text, _ = run(capsys, 'preserve', '--task-id', TASK, '--prompt-sha256', sha)
    assert rcode == 1 and ('S1_RECOVER STOP ' + code) in text
    assert snapshot(work) == before
    assert subprocess.run(['git', '-C', str(work), 'rev-parse', '-q', '--verify', rc.REF_PREFIX + TASK],
                          capture_output=True).returncode != 0


def test_prompt_hash_and_restore_binding_negatives(ws, capsys):
    work, base, sha = ws
    dirty_uncommitted(work)
    assert 'PROMPT_HASH_MISMATCH' in run(capsys, 'preserve', '--task-id', TASK, '--prompt-sha256', '0' * 64)[1]
    kv = preserve(capsys, sha)
    before = snapshot(work)
    for oid, plan_sha, want in ((kv['S1_PRESERVED_OID'], '0' * 64, 'PLAN_HASH_MISMATCH'),
                                (base, kv['S1_RECOVER_PLAN_SHA256'], 'SNAPSHOT_UNREADABLE')):
        code, text, _ = run(capsys, 'restore', '--task-id', TASK, '--prompt-sha256', sha,
                            '--preserved-oid', oid, '--plan-sha256', plan_sha)
        assert code == 1 and want in text
        assert snapshot(work) == before
    (work / 'README.md').write_bytes(b'new outside change before restore\n')
    before = snapshot(work)
    code, text, _ = run(capsys, 'restore', '--task-id', TASK, '--prompt-sha256', sha,
                        '--preserved-oid', kv['S1_PRESERVED_OID'], '--plan-sha256', kv['S1_RECOVER_PLAN_SHA256'])
    assert code == 1 and 'UNEXPECTED_CHANGE' in text and snapshot(work) == before


def test_committed_unpushed_s1_round_trip_keeps_branch(ws, capsys):
    work, base, sha = ws
    (work / 'docs/A.md').write_bytes(b'committed S1\n'); git(work, 'commit', '-qam', 'S1 local commit')
    s1 = git(work, 'rev-parse', 'HEAD')
    kv = preserve(capsys, sha)
    assert json.loads(kv['S1_RECOVER_PLAN_JSON'])['kind'] == 'COMMITTED'
    code, text, _ = run(capsys, 'restore', '--task-id', TASK, '--prompt-sha256', sha,
                        '--preserved-oid', kv['S1_PRESERVED_OID'], '--plan-sha256', kv['S1_RECOVER_PLAN_SHA256'])
    assert code == 0 and text.splitlines()[-1] == 'WORKSPACE_AT_BASE_READY', text
    assert git(work, 'rev-parse', 'HEAD') == base and git(work, 'rev-parse', 'refs/heads/' + BRANCH) == s1
    assert git(work, 'rev-parse', kv['S1_PRESERVED_OID'] + '^1') == s1


def test_committed_with_extra_changes_or_remote_branch_stops(ws, capsys):
    work, base, sha = ws
    (work / 'docs/A.md').write_bytes(b'committed S1\n'); git(work, 'commit', '-qam', 'S1 local commit')
    (work / 'docs/NEW.md').write_bytes(b'extra after commit\n')
    before = snapshot(work)
    assert 'COMMITTED_WITH_EXTRA_CHANGES' in run(capsys, 'preserve', '--task-id', TASK, '--prompt-sha256', sha)[1]
    assert snapshot(work) == before
    (work / 'docs/NEW.md').unlink()
    git(work, 'push', '-q', 'origin', BRANCH)
    before = snapshot(work)
    assert 'REMOTE_BRANCH_PRESENT' in run(capsys, 'preserve', '--task-id', TASK, '--prompt-sha256', sha)[1]
    assert snapshot(work) == before


def test_verify_fails_closed_when_not_restored_or_ref_differs(ws, capsys):
    work, base, sha = ws
    dirty_uncommitted(work)
    kv = preserve(capsys, sha)
    code, text, _ = run(capsys, 'verify', '--task-id', TASK, '--prompt-sha256', sha, '--preserved-oid', kv['S1_PRESERVED_OID'])
    assert code == 1 and 'POSTCHECK_HEAD' in text
    code, text, _ = run(capsys, 'verify', '--task-id', TASK, '--prompt-sha256', sha, '--preserved-oid', base)
    assert code == 1 and 'SNAPSHOT_UNREADABLE' in text


def test_output_never_contains_file_contents(ws, capsys):
    work, base, sha = ws
    (work / 'docs/NEW.md').write_bytes(b'SECRET-LIKE-CONTENT-MARKER\n')
    code, text, kv = run(capsys, 'preserve', '--task-id', TASK, '--prompt-sha256', sha)
    assert code == 0 and 'SECRET-LIKE-CONTENT-MARKER' not in text
    code, text, _ = run(capsys, 'restore', '--task-id', TASK, '--prompt-sha256', sha, '--preserved-oid',
                        kv['S1_PRESERVED_OID'], '--plan-sha256', kv['S1_RECOVER_PLAN_SHA256'])
    assert code == 0 and 'SECRET-LIKE-CONTENT-MARKER' not in text


def test_round_trip_with_autocrlf_true_keeps_raw_crlf_bytes(ws, capsys):
    # The USER Windows workspace runs with core.autocrlf=true; preserved bytes must be the raw worktree bytes.
    work, base, sha = ws
    git(work, 'config', 'core.autocrlf', 'true')
    dirty_uncommitted(work)
    raw_a = (work / 'docs/A.md').read_bytes()
    assert b'\r\n' in raw_a
    kv = preserve(capsys, sha)
    _, records = rc.read_snapshot(work, kv['S1_PRESERVED_OID'])
    assert rc.blob_bytes(work, {r['path']: r for r in records}['docs/A.md']['worktree']['oid']) == raw_a
    code, text, _ = run(capsys, 'restore', '--task-id', TASK, '--prompt-sha256', sha, '--preserved-oid',
                        kv['S1_PRESERVED_OID'], '--plan-sha256', kv['S1_RECOVER_PLAN_SHA256'])
    assert code == 0 and text.splitlines()[-1] == 'WORKSPACE_AT_BASE_READY', text
    assert git(work, 'status', '--porcelain=v1', '--untracked-files=all') == ''


def test_ref_created_concurrently_is_never_overwritten(ws, capsys, monkeypatch):
    # The ref appears between the existence check and the write: the create-only update must fail closed.
    work, base, sha = ws
    dirty_uncommitted(work)
    git(work, 'update-ref', rc.REF_PREFIX + TASK, base)
    real = rc.git
    def hide_ref_once(root, *a, **k):
        if a[:3] == ('rev-parse', '-q', '--verify') and a[3] == rc.REF_PREFIX + TASK and not hide_ref_once.done:
            hide_ref_once.done = True
            return 1, ''
        return real(root, *a, **k)
    hide_ref_once.done = False
    monkeypatch.setattr(rc, 'git', hide_ref_once)
    code, text, _ = run(capsys, 'preserve', '--task-id', TASK, '--prompt-sha256', sha)
    assert code == 1 and 'S1_RECOVER STOP' in text and 'S1_PRESERVED_OID' not in text
    assert git(work, 'rev-parse', rc.REF_PREFIX + TASK) == base


# ---- R2 regressions: second-opinion counterexamples B01, B02, B03, N01 must now be handled ----

def _restore_args(sha, kv):
    return ['restore', '--task-id', TASK, '--prompt-sha256', sha, '--preserved-oid', kv['S1_PRESERVED_OID'],
            '--plan-sha256', kv['S1_RECOVER_PLAN_SHA256']]


def test_b01_committed_out_of_plan_file_stops_before_any_write(ws, capsys):
    work, base, sha = ws
    (work / 'OUTSIDE.txt').write_bytes(b'outside committed bytes\n')
    git(work, 'add', 'OUTSIDE.txt'); git(work, 'commit', '-qm', 'out of scope commit')
    before = snapshot(work)
    code, text, _ = run(capsys, 'preserve', '--task-id', TASK, '--prompt-sha256', sha)
    assert code == 1 and 'S1_RECOVER STOP PATH_OUTSIDE_PLAN' in text
    assert snapshot(work) == before and (work / 'OUTSIDE.txt').exists()
    assert subprocess.run(['git', '-C', str(work), 'rev-parse', '-q', '--verify', rc.REF_PREFIX + TASK],
                          capture_output=True).returncode != 0


def test_b01_committed_plan_lists_every_switched_path_with_raw_crlf_bytes(ws, capsys):
    work, base, sha = ws
    git(work, 'config', 'core.autocrlf', 'true')
    raw = b'committed S1 CRLF\r\n'
    (work / 'docs/A.md').write_bytes(raw)
    (work / 'docs/NEW.md').write_bytes(b'new in commit\r\n')
    (work / 'scripts/tool.py').unlink()
    git(work, 'add', '-A', 'docs', 'scripts'); git(work, 'commit', '-qm', 'committed S1')
    assert git(work, 'status', '--porcelain=v1') == ''
    kv = preserve(capsys, sha)
    plan = json.loads(kv['S1_RECOVER_PLAN_JSON'])
    assert plan['kind'] == 'COMMITTED'
    assert {a['path']: a['action'] for a in plan['actions']} == {
        'docs/A.md': 'RESTORE_TRACKED', 'docs/NEW.md': 'DELETE_NEW', 'scripts/tool.py': 'RESTORE_TRACKED'}
    _, records = rc.read_snapshot(work, kv['S1_PRESERVED_OID'])
    assert rc.blob_bytes(work, {r['path']: r for r in records}['docs/A.md']['worktree']['oid']) == raw
    code, text, _ = run(capsys, *_restore_args(sha, kv))
    assert code == 0 and text.splitlines()[-1] == 'WORKSPACE_AT_BASE_READY', text
    assert not (work / 'docs/NEW.md').exists() and (work / 'scripts/tool.py').exists()
    assert git(work, 'status', '--porcelain=v1', '--untracked-files=all') == ''


def test_b02_unstaged_but_not_deleted_new_file_resumes(ws, capsys, monkeypatch):
    work, base, sha = ws
    (work / 'docs/NEW.md').write_bytes(b'new staged\n'); git(work, 'add', 'docs/NEW.md')
    kv = preserve(capsys, sha)
    real = Path.unlink
    def deny(p, *a, **k):
        if p == work / 'docs/NEW.md':
            raise PermissionError('synthetic delete denied')
        return real(p, *a, **k)
    monkeypatch.setattr(Path, 'unlink', deny)
    code, text, _ = run(capsys, *_restore_args(sha, kv))
    assert code == 1 and 'DELETE_FAILED' in text and 'WORKSPACE_AT_BASE_READY' not in text
    monkeypatch.setattr(Path, 'unlink', real)
    assert rc.index_entry(work, 'docs/NEW.md') is None and (work / 'docs/NEW.md').exists()
    code, text, _ = run(capsys, *_restore_args(sha, kv))
    assert code == 0 and text.splitlines()[-1] == 'WORKSPACE_AT_BASE_READY', text
    assert not (work / 'docs/NEW.md').exists()


def test_b02_staged_new_then_edited_restores_and_keeps_both_versions(ws, capsys):
    work, base, sha = ws
    (work / 'docs/NEW.md').write_bytes(b'staged version\n'); git(work, 'add', 'docs/NEW.md')
    (work / 'docs/NEW.md').write_bytes(b'worktree version\n')
    kv = preserve(capsys, sha)
    code, text, _ = run(capsys, *_restore_args(sha, kv))
    assert code == 0 and text.splitlines()[-1] == 'WORKSPACE_AT_BASE_READY', text
    _, records = rc.read_snapshot(work, kv['S1_PRESERVED_OID'])
    r = records[0]
    assert rc.blob_bytes(work, r['worktree']['oid']) == b'worktree version\n'
    assert rc.blob_bytes(work, r['index']['oid']) == b'staged version\n'


def test_b02_tracked_index_at_target_but_worktree_not_resumes(ws, capsys):
    # Any mix of 'as preserved' and 'at Base' per component (index, worktree) is a resumable state.
    work, base, sha = ws
    (work / 'docs/A.md').write_bytes(b'a staged change\n'); git(work, 'add', 'docs/A.md')
    kv = preserve(capsys, sha)
    git(work, 'restore', '--source=' + base, '--staged', '--', 'docs/A.md')   # simulated partial earlier run
    assert rc.index_entry(work, 'docs/A.md') == rc.tree_entry(work, base, 'docs/A.md')
    assert (work / 'docs/A.md').read_bytes() == b'a staged change\n'
    code, text, _ = run(capsys, *_restore_args(sha, kv))
    assert code == 0 and text.splitlines()[-1] == 'WORKSPACE_AT_BASE_READY', text


def test_b03_missing_preserved_blob_stops_before_any_destructive_step(ws, capsys):
    work, base, sha = ws
    (work / 'docs/NEW.md').write_bytes(b'only surviving source bytes\n')
    kv = preserve(capsys, sha)
    _, records = rc.read_snapshot(work, kv['S1_PRESERVED_OID'])
    oid = records[0]['worktree']['oid']
    obj = work / '.git' / 'objects' / oid[:2] / oid[2:]
    # Git stores loose objects read-only; Windows refuses to delete a read-only file (WinError 5), POSIX does not.
    os.chmod(obj, stat.S_IREAD | stat.S_IWRITE)
    obj.unlink()                                                        # synthetic loss of the preserved object
    before = snapshot(work)
    code, text, _ = run(capsys, *_restore_args(sha, kv))
    assert code == 1 and 'SNAPSHOT_BLOB_MISSING' in text
    assert snapshot(work) == before and (work / 'docs/NEW.md').read_bytes() == b'only surviving source bytes\n'


def test_n01_remote_branch_published_after_preserve_stops_first_restore(ws, capsys):
    work, base, sha = ws
    (work / 'docs/A.md').write_bytes(b'committed S1\n'); git(work, 'commit', '-qam', 'S1')
    kv = preserve(capsys, sha)
    git(work, 'push', '-q', 'origin', BRANCH)
    before = snapshot(work)
    code, text, _ = run(capsys, *_restore_args(sha, kv))
    assert code == 1 and 'REMOTE_BRANCH_PRESENT' in text and snapshot(work) == before


def test_n01_completed_restore_stays_idempotent_after_publication(ws, capsys):
    work, base, sha = ws
    (work / 'docs/A.md').write_bytes(b'committed S1\n'); git(work, 'commit', '-qam', 'S1')
    kv = preserve(capsys, sha)
    assert run(capsys, *_restore_args(sha, kv))[0] == 0
    git(work, 'push', '-q', 'origin', 'refs/heads/' + BRANCH + ':refs/heads/' + BRANCH)
    code, text, _ = run(capsys, *_restore_args(sha, kv))
    assert code == 0 and text.splitlines()[-1] == 'WORKSPACE_AT_BASE_READY', text
