"""B-119 N7/N8: Fail-closed CI_RUN source, identity, and simulation test cases."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import batch_runner as br
from scripts import batch_sim as bs

SHA = 'a' * 40
BRANCH = 'batch/b119-probe'


def ci_payload(sha=SHA, branch=BRANCH):
    return {'tool': 'verification_primitives', 'command': 'ci-status',
            'repo': 'hhai0519/HH.AI_v2', 'workflow_name': 'Verify',
            'head_sha': sha, 'branch': branch, 'event': 'push',
            'required_jobs': ['verify', 'gateway-windows'], 'status': 'PASS',
            'run_status': 'completed', 'run_conclusion': 'success',
            'run_id': 39000000001, 'run_attempt': 1,
            'jobs': {n: {'status': 'completed', 'conclusion': 'success'}
                     for n in ('verify', 'gateway-windows')}}


def probe(monkeypatch, tmp_path, payload=None, code=0, stdout=None, phase='candidate'):
    b = br.Batch.__new__(br.Batch)
    b.root = str(tmp_path)
    b.task_id = 'B119-CI-TEST'
    def make_artifact(suffix, contents):
        p = tmp_path / suffix
        assert not p.exists()
        p.write_text(contents, encoding='utf-8')
        return str(p)
    b.write_new_artifact = make_artifact
    def runner(args, **kwargs):
        return subprocess.CompletedProcess(args, code,
            (json.dumps(ci_payload() if payload is None else payload).encode() if stdout is None else stdout), b'')
    monkeypatch.setattr(br.subprocess, 'run', runner)
    return b.ci_status(SHA, BRANCH, 3, 1, phase)


def test_valid_candidate_and_artifact(monkeypatch, tmp_path, capsys):
    rc, payload = probe(monkeypatch, tmp_path)
    assert rc == 0 and payload['run_id'] == 39000000001
    assert json.loads((tmp_path / 'candidate-ci.json').read_text())['head_sha'] == SHA
    assert capsys.readouterr().out.strip() == (
        'CI_RUN phase=candidate run_id=39000000001 attempt=1 event=push '
        'branch=batch/b119-probe head_sha=' + SHA + ' verify=success gateway-windows=success')


def test_valid_postmain_distinct_artifact(monkeypatch, tmp_path, capsys):
    probe(monkeypatch, tmp_path, phase='postmain')
    assert (tmp_path / 'postmain-ci.json').exists()
    assert 'phase=postmain' in capsys.readouterr().out


@pytest.mark.parametrize('field,value,expected', [
    ('head_sha', 'b'*40, 'CI_STATUS_IDENTITY_DRIFT'),
    ('branch', 'main', 'CI_STATUS_IDENTITY_DRIFT'),
    ('event', 'pull_request', 'CI_STATUS_IDENTITY_DRIFT'),
    ('repo', 'other/other', 'CI_STATUS_IDENTITY_DRIFT'),
    ('run_id', None, 'CI_STATUS_RUN_ID_INVALID'),
    ('run_id', True, 'CI_STATUS_RUN_ID_INVALID'),
    ('run_id', '39000000001', 'CI_STATUS_RUN_ID_INVALID'),
    ('run_attempt', 0, 'CI_STATUS_RUN_ID_INVALID'),
    ('run_attempt', '1', 'CI_STATUS_RUN_ID_INVALID'),
    ('run_status', 'queued', 'CI_STATUS_NOT_PASS'),
    ('run_conclusion', 'failure', 'CI_STATUS_NOT_PASS'),
    ('status', 'CANDIDATE_INVALID', 'CI_STATUS_NOT_PASS'),
    ('required_jobs', ['verify'], 'CI_STATUS_JOBS_INVALID'),
    ('jobs', {'verify': {'status': 'completed', 'conclusion': 'success'}}, 'CI_STATUS_JOBS_INVALID'),
    ('jobs', {'verify': {'status': 'completed', 'conclusion': 'success'},
              'gateway-windows': {'status': 'completed', 'conclusion': 'failure'}}, 'CI_STATUS_JOBS_NOT_PASS'),
])
def test_fail_closed_bad_payload(monkeypatch, tmp_path, capsys, field, value, expected):
    data = ci_payload()
    data[field] = value
    with pytest.raises(br.Halt) as caught:
        probe(monkeypatch, tmp_path, payload=data)
    assert str(caught.value) == expected
    assert not list(tmp_path.glob('*-ci.json'))
    assert 'CI_RUN' not in capsys.readouterr().out


@pytest.mark.parametrize('raw', [b'', b'not json', b'[]', b'{}\n{}', b'\xff'])
def test_fail_closed_stdout(monkeypatch, tmp_path, raw):
    with pytest.raises(br.Halt):
        probe(monkeypatch, tmp_path, stdout=raw)
    assert not list(tmp_path.glob('*-ci.json'))


def test_pending_never_prints_success(monkeypatch, tmp_path, capsys):
    d = ci_payload()
    d['status'] = 'VERIFICATION_TOOL_UNABLE_TO_COMPLETE'
    rc, payload = probe(monkeypatch, tmp_path, payload=d, code=2)
    assert rc == 2 and payload is None
    assert 'CI_RUN' not in capsys.readouterr().out
    assert not list(tmp_path.glob('*-ci.json'))


def test_nonzero_cannot_claim_pass(monkeypatch, tmp_path):
    with pytest.raises(br.Halt, match='CI_STATUS_CONTRADICTION'):
        probe(monkeypatch, tmp_path, code=2)


def test_ci_stub_emits_matching_synthetic_json():
    argv = ['ci-status', '--head-sha', SHA, '--branch', BRANCH, '--event', 'push',
            '--repo', 'hhai0519/HH.AI_v2', '--workflow-name', 'Verify']
    cp = subprocess.run([sys.executable, '-c', bs.CI_STUB, *argv], capture_output=True)
    assert cp.returncode == 0, cp.stderr
    j = json.loads(cp.stdout)
    assert j['head_sha'] == SHA and j['branch'] == BRANCH
    assert j['run_id'] == 999001 and j['jobs']['gateway-windows']['conclusion'] == 'success'


@pytest.mark.parametrize('phase', ['candidate', 'postmain'])
@pytest.mark.parametrize('json_level', ['top', 'jobs', 'job'])
def test_duplicate_json_keys_fail_closed(monkeypatch, tmp_path, capsys, phase, json_level):
    """Duplicates are invalid even when the last value looks valid."""
    good = json.dumps(ci_payload(), separators=(',', ':'))
    if json_level == 'top':
        raw = good.replace('"run_id":39000000001', '"run_id":0,"run_id":39000000001', 1)
    elif json_level == 'jobs':
        raw = good.replace('"jobs":{', '"jobs":{"verify":{"status":"completed","conclusion":"failure"},', 1)
    else:
        raw = good.replace('"status":"completed"', '"status":"failure","status":"completed"', 1)
    assert raw != good
    with pytest.raises(br.Halt, match='CI_STATUS_JSON_INVALID'):
        probe(monkeypatch, tmp_path, stdout=raw.encode('utf-8'), phase=phase)
    assert not list(tmp_path.glob('*-ci.json'))
    assert 'CI_RUN' not in capsys.readouterr().out
