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


def test_td140_rate_limit_lines_and_summary(monkeypatch, tmp_path, capsys):
    ev = [
        {'until': '2026-11-27T10:15:00+08:00', 'phase': 'candidate'},
        {'until': '2026-11-27T10:25:00+08:00', 'phase': 'candidate'},
    ]
    d = dict(ci_payload(), rate_limit_waits=2, min_rate_limit_remaining=19, rate_limit_wait_events=ev)
    rc, payload = probe(monkeypatch, tmp_path, payload=d, code=0, phase='candidate')
    assert rc == 0 and payload['rate_limit_waits'] == 2
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines == [
        'CI_RATE_LIMIT_WAIT until=2026-11-27T10:15:00+08:00 phase=candidate',
        'CI_RATE_LIMIT_WAIT until=2026-11-27T10:25:00+08:00 phase=candidate',
        'CI_RATE_LIMIT_SUMMARY phase=candidate waits=2 min_remaining=19',
        'CI_RUN phase=candidate run_id=39000000001 attempt=1 event=push branch=batch/b119-probe head_sha=' + SHA + ' verify=success gateway-windows=success',
    ]


def test_td140_zero_waits_and_zero_min_remaining_accepted(monkeypatch, tmp_path, capsys):
    d = dict(ci_payload(), rate_limit_waits=0, min_rate_limit_remaining=0, rate_limit_wait_events=[])
    rc, _ = probe(monkeypatch, tmp_path, payload=d, code=0, phase='candidate')
    assert rc == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == 'CI_RATE_LIMIT_SUMMARY phase=candidate waits=0 min_remaining=0'


def test_td140_rate_limit_cap_10_and_pending_emits_summary(monkeypatch, tmp_path, capsys):
    ev12 = [{'until': f'2026-11-27T10:{i:02d}:00+08:00', 'phase': 'postmain'} for i in range(12)]
    d = dict(ci_payload(), status='VERIFICATION_TOOL_UNABLE_TO_COMPLETE',
             rate_limit_waits=12, min_rate_limit_remaining=None, rate_limit_wait_events=ev12)
    rc, payload = probe(monkeypatch, tmp_path, payload=d, code=2, phase='postmain')
    assert rc == 2 and payload is None
    lines = capsys.readouterr().out.strip().splitlines()
    assert len([x for x in lines if x.startswith('CI_RATE_LIMIT_WAIT ')]) == 10
    assert lines[-1] == 'CI_RATE_LIMIT_SUMMARY phase=postmain waits=12 min_remaining=unknown'
    assert not list(tmp_path.glob('*-ci.json'))


@pytest.mark.parametrize('patch', [
    {'rate_limit_waits': 0},
    {'rate_limit_waits': True, 'min_rate_limit_remaining': 0,
     'rate_limit_wait_events': [{'until': '2026-11-27T10:00:00+08:00', 'phase': 'candidate'}]},
    {'rate_limit_waits': 0, 'min_rate_limit_remaining': True, 'rate_limit_wait_events': []},
    {'rate_limit_waits': 0, 'min_rate_limit_remaining': -1, 'rate_limit_wait_events': []},
    {'rate_limit_waits': 1, 'min_rate_limit_remaining': 0, 'rate_limit_wait_events': 'not-a-list'},
    {'rate_limit_waits': 1, 'min_rate_limit_remaining': 0, 'rate_limit_wait_events': []},
    {'rate_limit_waits': 1, 'min_rate_limit_remaining': 0, 'rate_limit_wait_events': [['until', 'phase']]},
    {'rate_limit_waits': 1, 'min_rate_limit_remaining': 0, 'rate_limit_wait_events': [{'until': 123, 'phase': 'candidate'}]},
    {'rate_limit_waits': 1, 'min_rate_limit_remaining': 0, 'rate_limit_wait_events': [{'until': '2026-11-27T10:00:00', 'phase': 'candidate'}]},
    {'rate_limit_waits': 1, 'min_rate_limit_remaining': 0, 'rate_limit_wait_events': [{'until': '2026-11-27T10:00:00+08:00', 'phase': 'postmain'}]},
    {'rate_limit_waits': 1, 'min_rate_limit_remaining': 0, 'rate_limit_wait_events': [{'until': '2026-02-30T10:00:00+08:00', 'phase': 'candidate'}]},
    {'rate_limit_waits': 1, 'min_rate_limit_remaining': 0, 'rate_limit_wait_events': [{'until': '2026-11-27T10:00:00+08:00', 'phase': 'candidate', 'extra': 1}]},
])
def test_td140_invalid_rate_limit_stats_fail_closed(monkeypatch, tmp_path, patch):
    d = dict(ci_payload(), **patch)
    with pytest.raises(br.Halt, match='CI_STATUS_STATS_INVALID'):
        probe(monkeypatch, tmp_path, payload=d, phase='candidate')
    assert not list(tmp_path.glob('*-ci.json'))


def test_td140_ci_status_jobs_and_artifact_json_format(monkeypatch, tmp_path):
    for bad_jobs in (
        {'verify': 'not-a-dict', 'gateway-windows': {'status': 'completed', 'conclusion': 'success'}},
        {'verify': {'status': 'in_progress', 'conclusion': 'success'}, 'gateway-windows': {'status': 'completed', 'conclusion': 'success'}},
    ):
        d = dict(ci_payload(), jobs=bad_jobs)
        with pytest.raises(br.Halt, match='CI_STATUS_JOBS_NOT_PASS'):
            probe(monkeypatch, tmp_path, payload=d, phase='candidate')

    rich = dict(ci_payload(), extra_note='中文')
    rc, got = probe(monkeypatch, tmp_path, payload=rich, phase='candidate')
    assert rc == 0 and got['extra_note'] == '中文'
    raw_artifact = (tmp_path / 'candidate-ci.json').read_text(encoding='utf-8')
    assert raw_artifact == json.dumps(rich, sort_keys=True, ensure_ascii=True) + '\n'
    b = br.Batch.__new__(br.Batch)
    with pytest.raises(br.Halt, match='CI_STATUS_STATS_INVALID'):
        b._format_ci_rate_limit_lines({
            'rate_limit_waits': 1,
            'min_rate_limit_remaining': 0,
            'rate_limit_wait_events': ({'until': '2026-11-27T10:00:00+08:00', 'phase': 'candidate'},),
        }, 'candidate')


def test_td140_ci_status_cmd_flags_and_timeout_formula(monkeypatch, tmp_path):
    b = br.Batch.__new__(br.Batch)
    b.root = str(tmp_path)
    b.task_id = 'B117-TD140-FLAGS'
    b.write_new_artifact = lambda suffix, content: str(tmp_path / suffix)
    seen = []

    def runner(args, **kwargs):
        seen.append((args, kwargs['timeout']))
        return subprocess.CompletedProcess(args, 0, json.dumps(ci_payload()).encode(), b'')

    monkeypatch.setattr(br.subprocess, 'run', runner)
    b.ci_status(SHA, BRANCH, 3, 1, 'candidate')
    b.ci_status(SHA, BRANCH, 24, 60, 'postmain', initial_delay=360, rate_limit_wait_budget=3660)
    b.ci_status(SHA, BRANCH, 3, 10, 'candidate', initial_delay=1, rate_limit_wait_budget=1)

    cmd0, t0 = seen[0]
    assert '--initial-delay-seconds' not in cmd0 and '--rate-limit-wait-budget' not in cmd0
    assert t0 == 303  # min(0 + 3*(1+60) + 120, 1920) + 0
    cmd1, t1 = seen[1]
    assert cmd1[cmd1.index('--initial-delay-seconds') + 1] == '360'
    assert cmd1[cmd1.index('--rate-limit-wait-budget') + 1] == '3660'
    assert t1 == 5580  # 1920 + 3660
    cmd2, t2 = seen[2]
    assert cmd2[cmd2.index('--initial-delay-seconds') + 1] == '1'
    assert cmd2[cmd2.index('--rate-limit-wait-budget') + 1] == '1'
    assert t2 == 332  # 1 + 3*(10+60) + 120 + 1


def test_td140_step_push_verify_postmain_call_args_and_timeouts(monkeypatch, tmp_path):
    calls = []

    def make_batch(kind):
        b = br.Batch.__new__(br.Batch)
        b.root = str(tmp_path)
        b.task_id = 'B117-TD140-TEST'
        b.spec = {'kind': 'production', 'base_oid': '1' * 40, 'branch': BRANCH} if kind == 'production' else {
            'kind': 'promotion', 'base_oid': '1' * 40, 'candidate_oid': SHA, 'candidate_branch': BRANCH}
        b.remote_sha = lambda ref: SHA if ref != 'refs/heads/main' else '1' * 40
        def fake_ci_status(sha, branch, attempts, interval, phase, initial_delay=0, rate_limit_wait_budget=0):
            calls.append((phase, attempts, interval, initial_delay, rate_limit_wait_budget,
                          min(initial_delay + attempts * (interval + 60) + 120, 1920) + rate_limit_wait_budget))
            return 0, ci_payload()
        b.ci_status = fake_ci_status
        return b

    monkeypatch.setattr(br, 'git', lambda root, *a, **k: SHA if a[:2] == ('rev-parse', 'HEAD')
                        else ('1' * 40 if 'HEAD~1' in a or 'origin/main' in a or 'cand~1' in str(a)
                              else ('false' if '--is-shallow-repository' in a else BRANCH)))
    monkeypatch.setattr(br, 'expect_head_clean', lambda *a, **k: None)
    monkeypatch.setattr(br, 'status_lines', lambda *a, **k: [])
    monkeypatch.setattr(br, 'returncode', lambda *a, **k: 0)
    monkeypatch.setattr(br, 'run', lambda *a, **k: None)

    make_batch('production').step_push()
    p_verify = make_batch('promotion')
    monkeypatch.setattr(br, 'git', lambda root, *a, **k: 'false' if '--is-shallow-repository' in a else (
        SHA if a[:2] == ('rev-parse', 'HEAD') else (BRANCH if '--show-current' in a else '1' * 40)))
    p_verify.step_verify()
    p_verify.remote_sha = lambda ref: SHA
    p_verify.step_postmain()

    assert calls == [
        ('candidate', 24, 60, 360, 3660, 5580),
        ('candidate', 3, 10, 0, 3660, 3990),
        ('postmain', 24, 60, 360, 3660, 5580),
    ]
    assert '--head-sha' in bs.CI_STUB and 'verification_primitives' in bs.CI_STUB


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


def test_g3_ci_runner_diagnostic_path_and_total_budget(monkeypatch, tmp_path):
    b = br.Batch.__new__(br.Batch)
    b.root = str(tmp_path)
    b.task_id = 'B115-G3-CI-POLL-RETRY-R1-261109'
    b.write_new_artifact = lambda suffix, content: str(tmp_path / suffix)
    observed = []
    def runner(args, **kwargs):
        observed.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, json.dumps(ci_payload()).encode(), b'')
    monkeypatch.setattr(br.subprocess, 'run', runner)
    code, result = b.ci_status(SHA, BRANCH, 60, 30, 'candidate')
    assert code == 0 and result['run_id'] == 39000000001
    cmd, kws = observed[-1]
    assert cmd[cmd.index('--diagnostic-file') + 1] == (
        '.git/B115-G3-CI-POLL-RETRY-R1-261109-candidate-ci-diagnostic.json')
    assert kws['timeout'] == 1920
    assert '--require-job' in cmd and cmd.count('--require-job') == 2
