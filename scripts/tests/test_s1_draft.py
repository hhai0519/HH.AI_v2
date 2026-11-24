# -*- coding: utf-8 -*-
"""B-117 beta-2 (TD-101): unit & integration tests for scripts/s1_draft.py,
batch_runner.report_s1_draft, and reply_check S1_DRAFT_* enforcement.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

import batch_runner as br  # noqa: E402
import reply_check as rc  # noqa: E402
import s1_draft as sd  # noqa: E402


TASK = 'B117-BETA2-DRAFT-UNIT-261124'
BASE = '1' * 40


def _git_init_tracked(tmp_path: Path) -> Path:
    repo = tmp_path / 'repo'
    repo.mkdir(parents=True)
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'core.autocrlf', 'false'], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'user.name', 'Test'], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'user.email', 't@example.test'], check=True)
    reg_dir = repo / 'docs' / 'governance'
    reg_dir.mkdir(parents=True)
    (reg_dir / 's1-registry.json').write_bytes(b'{"schema":2,"causes":[]}\n')
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(repo), 'commit', '-qm', 'base'], check=True)
    return repo


def test_build_draft_schema2_positive_and_unexpected_normalization():
    ts = datetime(2026, 11, 24, 10, 15, 30, 999999, tzinfo=timezone(timedelta(hours=8)))
    d = sd.build_draft(TASK, 'precommit', 'PRECOMMIT_NONZERO', head_oid='a' * 40, now=ts)
    assert d['schema'] == 2
    assert d['kind'] == 'S1_REGISTRY_DRAFT'
    assert d['candidateOnly'] is True
    assert d['id'] is None
    assert d['title'] is None
    assert d['status'] is None
    assert d['tasks'] == [TASK]
    assert d['watch'] == ['precommit:PRECOMMIT_NONZERO']
    assert d['class'] == 'UNCLASSIFIED'
    assert d['confirmed'] is False
    assert d['by'] == 'runner'
    assert d['verified']['by'] == 'runner'
    assert d['verified']['date'] == '2026-11-24'
    assert 'S1 PRECOMMIT_NONZERO | step precommit' in d['evidence']
    assert 'head=' + 'a' * 40 in d['evidence']
    assert 'time=2026-11-24T10:15:30+08:00' in d['evidence']
    assert d['evidenceDetail'] == {
        's1Line': 'S1 PRECOMMIT_NONZERO | step precommit',
        'step': 'precommit',
        'code': 'PRECOMMIT_NONZERO',
        'head': 'a' * 40,
        'timestamp': '2026-11-24T10:15:30+08:00',
    }

    unexp = sd.build_draft(TASK, 'setup', 'UNEXPECTED_RuntimeError', head_oid='UNKNOWN', now=ts)
    assert unexp['watch'] == ['setup:UNEXPECTED_RUNTIMEERROR']
    assert unexp['evidenceDetail']['s1Line'] == 'S1 UNEXPECTED_RuntimeError | step setup'


@pytest.mark.parametrize('kwargs', [
    {'task_id': '../evil', 'step': 'setup', 's1_code': 'SETUP_DIRTY', 'head_oid': BASE},
    {'task_id': TASK, 'step': 'BAD_STEP', 's1_code': 'SETUP_DIRTY', 'head_oid': BASE},
    {'task_id': TASK, 'step': 'setup', 's1_code': 'bad code', 'head_oid': BASE},
    {'task_id': TASK, 'step': 'setup', 's1_code': 'SETUP_DIRTY', 'head_oid': 'abcd'},
])
def test_build_draft_rejects_invalid_arguments(kwargs):
    with pytest.raises(sd.DraftError):
        sd.build_draft(**kwargs)


def test_create_s1_draft_writes_once_in_git_and_leaves_tracked_clean(tmp_path):
    repo = _git_init_tracked(tmp_path)
    head = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    reg_before = (repo / 'docs' / 'governance' / 's1-registry.json').read_bytes()

    seen_rel = []
    def validator(rel):
        seen_rel.append(rel)

    lines = sd.create_s1_draft(repo, TASK, 'precommit', 'PRECOMMIT_NONZERO', validate_artifact=validator)
    assert seen_rel == [f'.git/{TASK}-s1-draft.json']
    assert len(lines) == 1

    draft_path = repo / '.git' / f'{TASK}-s1-draft.json'
    raw = draft_path.read_bytes()
    assert not raw.startswith(b'\xef\xbb\xbf')
    assert b'\r' not in raw and raw.endswith(b'\n')
    sha = hashlib.sha256(raw).hexdigest()
    assert lines[0] == f'S1_DRAFT_FILE=.git/{TASK}-s1-draft.json sha256={sha} bytes={len(raw)}'

    parsed = json.loads(raw.decode('utf-8'))
    assert parsed['evidenceDetail']['head'] == head
    assert parsed['tasks'] == [TASK]
    assert parsed['id'] is None and parsed['status'] is None

    # Tracked repository and s1-registry.json must stay completely untouched
    status = subprocess.check_output(
        ['git', '-C', str(repo), 'status', '--porcelain=v1', '--untracked-files=all'],
        text=True,
    )
    assert status == ''
    assert (repo / 'docs' / 'governance' / 's1-registry.json').read_bytes() == reg_before

    # Second write refuses overwrite and keeps original bytes intact
    with pytest.raises(sd.DraftError, match='S1_DRAFT_ALREADY_EXISTS'):
        sd.create_s1_draft(repo, TASK, 'precommit', 'OTHER_CODE', validate_artifact=validator)
    assert draft_path.read_bytes() == raw


def test_create_s1_draft_fail_closed_missing_git_or_validator(tmp_path):
    no_git = tmp_path / 'plain'
    no_git.mkdir()
    with pytest.raises(sd.DraftError, match='S1_DRAFT_GIT_DIR_MISSING'):
        sd.create_s1_draft(no_git, TASK, 'setup', 'SETUP_DIRTY', validate_artifact=lambda _r: None)

    file_git = tmp_path / 'filegit'
    file_git.mkdir()
    (file_git / '.git').write_bytes(b'gitdir: /somewhere\n')
    with pytest.raises(sd.DraftError, match='S1_DRAFT_GIT_DIR_UNSAFE'):
        sd.create_s1_draft(file_git, TASK, 'setup', 'SETUP_DIRTY', validate_artifact=lambda _r: None)

    repo = _git_init_tracked(tmp_path / 'val')
    with pytest.raises(sd.DraftError, match='BAD_BINDING'):
        def bad_val(_r):
            raise sd.DraftError('BAD_BINDING')
        sd.create_s1_draft(repo, TASK, 'setup', 'SETUP_DIRTY', validate_artifact=bad_val)


def test_create_s1_draft_rejects_symlink_target(tmp_path):
    repo = _git_init_tracked(tmp_path / 'sym')
    # Pre-existing symlink at target must never be followed or overwritten
    target = repo / 'outside.json'
    target.write_bytes(b'keep')
    draft_link = repo / '.git' / f'{TASK}-s1-draft.json'
    try:
        os.symlink(str(target), str(draft_link))
    except OSError as exc:
        if getattr(exc, 'winerror', None) == 1314:
            pytest.skip('Windows symlink privilege unavailable (winerror=1314)')
        raise
    with pytest.raises(sd.DraftError, match='S1_DRAFT_ALREADY_EXISTS'):
        sd.create_s1_draft(repo, TASK, 'setup', 'SETUP_DIRTY', validate_artifact=lambda _r: None)
    assert target.read_bytes() == b'keep'


def test_batch_runner_report_s1_draft_and_unavailable_fallback(tmp_path, monkeypatch, capsys):
    repo = _git_init_tracked(tmp_path)

    class DiagnosticsBatch:
        def __init__(self, r):
            self.root = str(r)
            self.task_id = TASK
        def artifact(self, name):
            return '.git/' + self.task_id + '-' + name

    b = DiagnosticsBatch(repo)
    br.report_s1_draft(b, 'setup', br.Halt('SETUP_DIRTY'))
    out1 = capsys.readouterr().out.splitlines()
    assert len(out1) == 1 and out1[0].startswith(f'S1_DRAFT_FILE=.git/{TASK}-s1-draft.json sha256=')

    # Second call sees existing draft and degrades gracefully to UNAVAILABLE without raising
    br.report_s1_draft(b, 'setup', br.Halt('SETUP_DIRTY'))
    out2 = capsys.readouterr().out.splitlines()
    assert out2 == ['S1_DRAFT_STATUS=UNAVAILABLE']

    monkeypatch.setattr(br, 'create_s1_draft', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('boom')))
    br.report_s1_draft(b, 'setup', br.Halt('SETUP_DIRTY'))
    out3 = capsys.readouterr().out.splitlines()
    assert out3 == ['S1_DRAFT_STATUS=UNAVAILABLE']


def test_batch_runner_execute_step_wiring_emits_s1_draft_after_capture(tmp_path, monkeypatch, capsys):
    repo = _git_init_tracked(tmp_path)

    class HaltBatch:
        def __init__(self, r):
            self.root = str(r)
            self.task_id = TASK
            self.ci_jobs = None
            self.spec = {'kind': 'production', 'base_oid': BASE, 'branch': 'batch/' + TASK.lower()}
        def artifact(self, name):
            return '.git/' + self.task_id + '-' + name
        def step_setup(self):
            raise br.Halt('SETUP_DIRTY')

    monkeypatch.setattr(br, 'save_control', lambda batch, control: None)
    monkeypatch.setattr(br, 'report_failed_list', lambda *a: print('S1_FAILED_LIST kind=FAILED_LIST_UNAVAILABLE reason=NOT_A_TEST_STEP'))
    monkeypatch.setattr(br, 'report_s1_metadata', lambda *a: print('S1_EVIDENCE_STATUS=UNAVAILABLE'))
    monkeypatch.setattr(br, 'report_s1_full_capture', lambda *a: print('S1_FULL_CAPTURE_STATUS=UNAVAILABLE'))
    control = {'task_id': TASK, 'done': ['preflight'], 'halted': None}
    assert br._execute_step(HaltBatch(repo), 'setup', control) == 1
    out = capsys.readouterr().out.splitlines()
    assert out[:4] == [
        'S1 SETUP_DIRTY | step setup',
        'S1_FAILED_LIST kind=FAILED_LIST_UNAVAILABLE reason=NOT_A_TEST_STEP',
        'S1_EVIDENCE_STATUS=UNAVAILABLE',
        'S1_FULL_CAPTURE_STATUS=UNAVAILABLE',
    ]
    assert out[4].startswith(f'S1_DRAFT_FILE=.git/{TASK}-s1-draft.json sha256=')

    # Secondary control save failure must NOT emit S1_DRAFT_* lines
    monkeypatch.setattr(br, 'save_control', lambda *a, **kw: (_ for _ in ()).throw(br.Halt('CONTROL_SAVE_FAILED')))
    control2 = {'task_id': TASK, 'done': ['preflight'], 'halted': None}
    assert br._execute_step(HaltBatch(repo), 'setup', control2) == 1
    out_sec = capsys.readouterr().out
    assert 'S1_DRAFT_' not in out_sec


def _persisted_s1_reply(extra_lines):
    lines = [
        'S1 SETUP_DIRTY | step setup',
        'S1_FAILED_LIST kind=FAILED_LIST_UNAVAILABLE reason=NOT_A_TEST_STEP',
        'S1_EVIDENCE_STATUS=UNAVAILABLE',
        'S1_FULL_CAPTURE_STATUS=UNAVAILABLE',
        *extra_lines,
        'TIMING start=2026-11-24T10:00:00+08:00 end=2026-11-24T10:01:00+08:00 elapsed_sec=60.0 elapsed_min=1',
        'STATE done=preflight,native_preview halted=setup:SETUP_DIRTY',
    ]
    return '\n'.join(lines) + '\n'


def test_reply_check_s1_draft_positive_and_negative_controls():
    spec = {
        'kind': 'production',
        'base_oid': BASE,
        'branch': 'batch/' + TASK.lower(),
        'e24': False,
        'native_preview': True,
        'focused': None,
        'bundle_output': False,
    }
    sha = 'f' * 64

    # Both omitted (backward compat with Base), FILE only, STATUS=UNAVAILABLE only all pass
    for extra in (
        [],
        [f'S1_DRAFT_FILE=.git/{TASK}-s1-draft.json sha256={sha} bytes=412'],
        ['S1_DRAFT_STATUS=UNAVAILABLE'],
    ):
        result = rc.check_spec(TASK, spec, _persisted_s1_reply(extra))
        assert result[2] == 'S1 setup:SETUP_DIRTY'

    # Conflict (both present)
    with pytest.raises(rc.CheckError, match='REPLY_S1_DRAFT_CONFLICT'):
        rc.check_spec(TASK, spec, _persisted_s1_reply([
            f'S1_DRAFT_FILE=.git/{TASK}-s1-draft.json sha256={sha} bytes=412',
            'S1_DRAFT_STATUS=UNAVAILABLE',
        ]))

    # Wrong task filename
    with pytest.raises(rc.CheckError, match='REPLY_S1_DRAFT_FILE_MISMATCH'):
        rc.check_spec(TASK, spec, _persisted_s1_reply([
            f'S1_DRAFT_FILE=.git/OTHER-TASK-s1-draft.json sha256={sha} bytes=412',
        ]))

    # Malformed bytes=0 or bad sha
    with pytest.raises(rc.CheckError, match='REPLY_LINE_MALFORMED'):
        rc.check_spec(TASK, spec, _persisted_s1_reply([
            f'S1_DRAFT_FILE=.git/{TASK}-s1-draft.json sha256={sha} bytes=0',
        ]))
    with pytest.raises(rc.CheckError, match='REPLY_SHA_INVALID'):
        rc.check_spec(TASK, spec, _persisted_s1_reply([
            f'S1_DRAFT_FILE=.git/{TASK}-s1-draft.json sha256=deadbeef bytes=10',
        ]))

    # Forbidden on TASK_ALREADY_HALTED
    already_base = '\n'.join([
        'S1 TASK_ALREADY_HALTED setup:SETUP_DIRTY',
        'TIMING start=2026-11-24T10:00:00+08:00 end=2026-11-24T10:01:00+08:00 elapsed_sec=60.0 elapsed_min=1',
        'STATE done=preflight,native_preview halted=setup:SETUP_DIRTY',
    ]) + '\n'
    assert rc.check_spec(TASK, spec, already_base)[2] == 'S1 setup:SETUP_DIRTY'
    with pytest.raises(rc.CheckError, match='REPLY_LINE_NOT_EXPECTED'):
        rc.check_spec(TASK, spec, f'S1_DRAFT_FILE=.git/{TASK}-s1-draft.json sha256={sha} bytes=412\n' + already_base)

    # Forbidden on pre-step S1
    prestep_base = '\n'.join([
        'S1 START_STATE_MISMATCH | step preflight',
        'TIMING start=2026-11-24T10:00:00+08:00 end=2026-11-24T10:01:00+08:00 elapsed_sec=60.0 elapsed_min=1',
        'STATE done= halted=None',
    ]) + '\n'
    assert rc.check_spec(TASK, spec, prestep_base)[2] == 'S1 preflight:START_STATE_MISMATCH'
    with pytest.raises(rc.CheckError, match='REPLY_LINE_NOT_EXPECTED'):
        rc.check_spec(TASK, spec, 'S1_DRAFT_STATUS=UNAVAILABLE\n' + prestep_base)

    # Forbidden on success reply
    head = '2' * 40
    steps = ','.join(br.derive_steps(spec))
    success_base = '\n'.join([
        f'CI_RUN phase=candidate run_id=101 attempt=1 event=push branch=batch/{TASK.lower()} head_sha={head} verify=success gateway-windows=success',
        f'COMMIT {head} | CI PASS | S1 NONE',
        'TIMING start=2026-11-24T10:00:00+08:00 end=2026-11-24T10:01:00+08:00 elapsed_sec=60.0 elapsed_min=1',
        f'STATE done={steps} halted=None',
    ]) + '\n'
    assert rc.check_spec(TASK, spec, success_base)[2] == f'COMMIT {head}'
    for bad_line in (
        f'S1_DRAFT_FILE=.git/{TASK}-s1-draft.json sha256={sha} bytes=412',
        'S1_DRAFT_STATUS=UNAVAILABLE',
    ):
        with pytest.raises(rc.CheckError, match='REPLY_LINE_NOT_EXPECTED'):
            rc.check_spec(TASK, spec, bad_line + '\n' + success_base)


def test_create_s1_draft_readback_mismatch_fails_closed(tmp_path, monkeypatch):
    repo = _git_init_tracked(tmp_path)
    monkeypatch.setattr(sd, '_guarded_bytes', lambda _g, _f: b'tampered-bytes')
    with pytest.raises(sd.DraftError, match='S1_DRAFT_READBACK_MISMATCH'):
        sd.create_s1_draft(
            repo,
            TASK,
            'precommit',
            'PRECOMMIT_NONZERO',
            validate_artifact=lambda _r: None,
        )
