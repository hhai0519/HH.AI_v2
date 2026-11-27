"""Unit tests for verification_primitives.py (Pilot INC-C, B-69).

All tests execute the production tool via subprocess using sys.executable.
No parallel comparison logic replaces the production tool.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.server
import json
import os
import subprocess
import sys
import threading
import urllib.parse
from pathlib import Path

import pytest

TOOL_PATH = Path(__file__).resolve().parent.parent / "verification_primitives.py"


def run_tool(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    cmd = [sys.executable, str(TOOL_PATH), *args]
    return subprocess.run(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _td140_vp(name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, TOOL_PATH)
    vp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vp)
    return vp


def _td140_args(**over):
    import argparse
    base = dict(api_base='https://api.github.com', repo='hhai0519/HH.AI_v2', head_sha='c' * 40,
                branch='batch/so-g3', require_job=['verify', 'gateway-windows'], max_attempts=1,
                interval_seconds=0, initial_delay_seconds=0, phase='candidate',
                rate_limit_wait_budget=0, event='push', workflow_name='Verify', diagnostic_file=None)
    base.update(over)
    return argparse.Namespace(**base)


def _td140_clock(monkeypatch, vp, get_cost=0.0, responses=None, base_epoch=100.0):
    from types import SimpleNamespace
    clock = SimpleNamespace(now=0.0, sleeps=[], gets=[])

    def sleep(d):
        assert d >= 0
        clock.sleeps.append(d)
        clock.now += d
    monkeypatch.setattr(vp, 'time', SimpleNamespace(monotonic=lambda: clock.now, sleep=sleep,
                                                    time=lambda: base_epoch + clock.now))

    def fake_get(url, budget):
        assert 0 < budget <= 30.0
        clock.gets.append(url)
        clock.now += get_cost
        return responses(url) if callable(responses) else responses.pop(0)
    monkeypatch.setattr(vp, '_ci_bounded_get', fake_get)
    return clock


def _td140_run(vp, args, capsys):
    with pytest.raises(SystemExit) as caught:
        vp.cmd_ci_status(args)
    return caught.value.code, json.loads(capsys.readouterr().out.strip())


def _td140_ok(obj, **extra):
    import base64
    res = {'kind': 'OK', 'body': base64.b64encode(json.dumps(obj).encode()).decode()}
    res.update(extra)
    return res


def test_td140_helpers_formatting_parsing_and_min_remaining():
    vp = _td140_vp('vp_td140_helpers')
    # 1764209700 = 2025-11-27T02:15:00Z = 2025-11-27T10:15:00+08:00 (kills TAIPEI_TZ 8->9 & format)
    assert vp._format_taipei_iso(1764209700.9) == '2025-11-27T10:15:00+08:00'
    assert vp._parse_nonneg_ascii_int('0') == 0
    assert vp._parse_nonneg_ascii_int('42') == 42
    assert vp._parse_nonneg_ascii_int('١٢') is None
    assert vp._parse_nonneg_ascii_int('abc') is None
    assert vp._parse_nonneg_ascii_int('-1') is None

    st = {'min_rate_limit_remaining': None}
    vp._record_rate_limit_remaining(st, -1)
    assert st['min_rate_limit_remaining'] is None
    vp._record_rate_limit_remaining(st, True)
    assert st['min_rate_limit_remaining'] is None
    vp._record_rate_limit_remaining(st, 0)
    assert st['min_rate_limit_remaining'] == 0
    vp._record_rate_limit_remaining(st, '10')
    assert st['min_rate_limit_remaining'] == 0


def test_td140_http_worker_rate_limit_url_allowlist_and_200_headers(monkeypatch, capsys):
    vp = _td140_vp('vp_td140_worker')
    seen_headers = []
    body_bytes = b'{"resources":{"core":{"remaining":37,"reset":1700001234}}}'

    class FakeResp:
        headers = {'X-RateLimit-Remaining': '37', 'X-RateLimit-Reset': '1700001234'}
        def read(self, n):
            return body_bytes[:n]
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        seen_headers.append(dict(req.header_items()))
        return FakeResp()

    monkeypatch.setattr(vp.urllib.request, 'urlopen', fake_urlopen)
    for ok_url in (
        'https://api.github.com/repos/a/b/actions/runs',
        'https://api.github.com/rate_limit',
        'http://127.0.0.1:8080/rate_limit',
    ):
        vp._ci_http_worker(ok_url)
        out = json.loads(capsys.readouterr().out.strip())
        assert out['kind'] == 'OK' and out['remaining'] == '37' and out['reset'] == '1700001234'
    assert all('Authorization' not in h for h in seen_headers)

    # Exact CI_MAX_BYTES accepted; CI_MAX_BYTES + 1 rejected (read(CI_MAX_BYTES + 1) boundary)
    body_bytes = b'x' * vp.CI_MAX_BYTES
    vp._ci_http_worker('https://api.github.com/rate_limit')
    assert json.loads(capsys.readouterr().out.strip())['kind'] == 'OK'
    body_bytes = b'x' * (vp.CI_MAX_BYTES + 1)
    vp._ci_http_worker('https://api.github.com/rate_limit')
    assert json.loads(capsys.readouterr().out.strip()) == {'kind': 'INVALID'}

    called_bad = []
    monkeypatch.setattr(vp.urllib.request, 'urlopen', lambda *a, **k: called_bad.append(a))
    for bad_url in (
        'https://api.github.com/rate_limit/extra',
        'https://api.github.com/rate_limit?foo=1',
        'http://127.0.0.2:8080/rate_limit',
        'https://evil.example/rate_limit',
    ):
        vp._ci_http_worker(bad_url)
        assert json.loads(capsys.readouterr().out.strip()) == {'kind': 'INVALID'}
    assert called_bad == []


@pytest.mark.parametrize('bad_kwargs', [
    {'require_job': []},
    {'max_attempts': 0},
    {'max_attempts': 61},
    {'max_attempts': True},
    {'initial_delay_seconds': -1},
    {'initial_delay_seconds': 601},
    {'initial_delay_seconds': True},
    {'interval_seconds': -1},
    {'interval_seconds': 121},
    {'interval_seconds': True},
    {'phase': 'invalid'},
    {'rate_limit_wait_budget': -1},
    {'rate_limit_wait_budget': 3661},
    {'rate_limit_wait_budget': True},
])
def test_td140_ci_status_invalid_arguments_fail_closed(monkeypatch, capsys, bad_kwargs):
    vp = _td140_vp('vp_td140_args')
    clock = _td140_clock(monkeypatch, vp, responses=[])
    rc, payload = _td140_run(vp, _td140_args(**bad_kwargs), capsys)
    assert rc == 2 and payload['reason'] == 'INVALID_ARGUMENT' and clock.gets == []


def test_td140_valid_boundary_arguments_accepted(monkeypatch, capsys):
    vp = _td140_vp('vp_td140_bounds_ok')
    sha, branch = 'c' * 40, 'batch/so-g3'
    runs = {'workflow_runs': [{'id': 8809, 'name': 'Verify', 'head_sha': sha, 'head_branch': branch,
                               'event': 'push', 'status': 'completed', 'conclusion': 'success', 'run_attempt': 1}]}
    jobs = {'jobs': [{'name': j, 'status': 'completed', 'conclusion': 'success'} for j in ('verify', 'gateway-windows')]}
    _td140_clock(monkeypatch, vp, responses=[_td140_ok(runs), _td140_ok(jobs)])
    rc, payload = _td140_run(vp, _td140_args(max_attempts=60, interval_seconds=120,
                                             initial_delay_seconds=600, rate_limit_wait_budget=0), capsys)
    assert rc == 0 and payload['status'] == 'PASS'


def test_td140_preflight_rate_limit_low_extends_budget_writes_diag_and_passes(tmp_path, monkeypatch, capsys):
    import base64
    vp = _td140_vp('vp_td140_preflight_ext')
    monkeypatch.chdir(tmp_path)
    (tmp_path / '.git').mkdir()
    diag_rel = '.git/TD140-PROBE-candidate-ci-diagnostic.json'
    sha, branch = 'c' * 40, 'batch/so-g3'
    rl_doc = {'resources': {'core': {'remaining': 5, 'reset': 1764209700 + 1000}}}
    runs = {'workflow_runs': [{'id': 8801, 'name': 'Verify', 'head_sha': sha, 'head_branch': branch,
                               'event': 'push', 'status': 'completed', 'conclusion': 'success', 'run_attempt': 1}]}
    jobs = {'jobs': [{'name': j, 'status': 'completed', 'conclusion': 'success'} for j in ('verify', 'gateway-windows')]}
    diag_snapshots = []

    clock_state = {'now': 0.0, 'sleeps': [], 'gets': []}
    def sleep(d):
        assert d >= 0
        if (tmp_path / diag_rel).is_file():
            diag_snapshots.append(json.loads((tmp_path / diag_rel).read_text('utf-8')))
        clock_state['sleeps'].append(d)
        clock_state['now'] += d

    monkeypatch.setattr(vp, 'time', type(sys)('fake_time'))
    vp.time.monotonic = lambda: clock_state['now']
    vp.time.sleep = sleep
    vp.time.time = lambda: 1764209700.0 + clock_state['now']

    replies = [
        {'kind': 'OK', 'body': base64.b64encode(json.dumps(rl_doc).encode()).decode(), 'remaining': '5', 'reset': '1764210700'},
        {'kind': 'OK', 'body': base64.b64encode(json.dumps(runs).encode()).decode(), 'remaining': '59', 'reset': '1764214300'},
        {'kind': 'OK', 'body': base64.b64encode(json.dumps(jobs).encode()).decode(), 'remaining': '58', 'reset': '1764214300'},
    ]
    def fake_get(url, budget):
        assert 0 < budget <= 30.0
        clock_state['gets'].append(url)
        return replies.pop(0)
    monkeypatch.setattr(vp, '_ci_bounded_get', fake_get)

    args = _td140_args(max_attempts=24, interval_seconds=60, initial_delay_seconds=360,
                       phase='candidate', rate_limit_wait_budget=3660, diagnostic_file=diag_rel)
    rc, payload = _td140_run(vp, args, capsys)
    assert rc == 0 and payload['status'] == 'PASS'
    assert clock_state['sleeps'] == [1005.0]
    assert clock_state['gets'][0] == 'https://api.github.com/rate_limit'
    assert payload['rate_limit_waits'] == 1
    assert payload['min_rate_limit_remaining'] == 5
    # Exact UTC+8 formatted time (+ wait_seconds, not minus): 1764210705 = 10:31:45+08:00
    assert payload['rate_limit_wait_events'] == [{'until': '2025-11-27T10:31:45+08:00', 'phase': 'candidate'}]
    assert len(diag_snapshots) == 1
    assert diag_snapshots[0]['schema_version'] == 1
    assert diag_snapshots[0]['attempts_used'] == 0
    assert diag_snapshots[0]['status'] == 'WAITING_RATE_LIMIT'
    assert diag_snapshots[0]['active_rate_limit_wait']['phase'] == 'candidate'
    final_diag = json.loads((tmp_path / diag_rel).read_text('utf-8'))
    assert final_diag['active_rate_limit_wait'] is None
    assert final_diag['initial_delay_seconds'] == 360
    assert final_diag['transport']['min_rate_limit_remaining'] == 5


def test_td140_preflight_boundaries_and_max_bytes(monkeypatch, capsys):
    import base64
    vp = _td140_vp('vp_td140_preflight_bounds')
    sha, branch = 'c' * 40, 'batch/so-g3'
    runs = {'workflow_runs': [{'id': 8802, 'name': 'Verify', 'head_sha': sha, 'head_branch': branch,
                               'event': 'push', 'status': 'completed', 'conclusion': 'success', 'run_attempt': 1}]}
    jobs = {'jobs': [{'name': j, 'status': 'completed', 'conclusion': 'success'} for j in ('verify', 'gateway-windows')]}

    # 1. Exact core_rem == 12 does NOT preflight-wait even with long reset (kills 12 -> 13)
    c_eq12 = _td140_clock(monkeypatch, vp, responses=[
        _td140_ok({'resources': {'core': {'remaining': 12, 'reset': 2000}}}, remaining='12', reset='2000'),
        _td140_ok(runs, remaining='11', reset='2000'),
        _td140_ok(jobs, remaining='10', reset='2000'),
    ])
    rc, p_eq12 = _td140_run(vp, _td140_args(max_attempts=1, interval_seconds=0, initial_delay_seconds=10,
                                           phase='candidate', rate_limit_wait_budget=3660), capsys)
    assert rc == 0 and c_eq12.sleeps == [10.0] and p_eq12['rate_limit_waits'] == 0

    # 2. Header remaining captured even if JSON body has no core quota; exact len(rl_body) == CI_MAX_BYTES accepted
    pad_prefix = '{"resources":{"core":{"remaining":3,"reset":2000}},"p":"'
    pad_len = vp.CI_MAX_BYTES - len(pad_prefix) - 2
    exact_json = (pad_prefix + ('a' * pad_len) + '"}').encode('utf-8')
    assert len(exact_json) == vp.CI_MAX_BYTES
    c_maxb = _td140_clock(monkeypatch, vp, responses=[
        {'kind': 'OK', 'body': base64.b64encode(exact_json).decode(), 'remaining': '3', 'reset': '2000'},
        _td140_ok(runs, remaining='59', reset='5000'),
        _td140_ok(jobs, remaining='58', reset='5000'),
    ])
    rc, p_maxb = _td140_run(vp, _td140_args(max_attempts=1, interval_seconds=0, initial_delay_seconds=0,
                                           phase='candidate', rate_limit_wait_budget=3660), capsys)
    assert rc == 0 and c_maxb.sleeps == [1905.0] and p_maxb['rate_limit_waits'] == 1

    # 3. Preflight OK header remaining=17 recorded when body has no core object
    c_hdr = _td140_clock(monkeypatch, vp, responses=[
        _td140_ok({}, remaining='17', reset='3000'),
        _td140_ok(runs, remaining='25', reset='3000'),
        _td140_ok(jobs, remaining='24', reset='3000'),
    ])
    rc, p_hdr = _td140_run(vp, _td140_args(max_attempts=1, interval_seconds=0, rate_limit_wait_budget=100), capsys)
    assert rc == 0 and p_hdr['min_rate_limit_remaining'] == 17


def test_td140_dynamic_rate_limit_extension_and_budget_exact_arithmetic(monkeypatch, capsys):
    vp = _td140_vp('vp_td140_dyn_ext')
    sha, branch = 'c' * 40, 'batch/so-g3'
    runs = {'workflow_runs': [{'id': 8803, 'name': 'Verify', 'head_sha': sha, 'head_branch': branch,
                               'event': 'push', 'status': 'completed', 'conclusion': 'success', 'run_attempt': 1}]}
    jobs = {'jobs': [{'name': j, 'status': 'completed', 'conclusion': 'success'} for j in ('verify', 'gateway-windows')]}
    rl_ok = {'resources': {'core': {'remaining': 15, 'reset': 2000}}}

    # 1. Exact budget match (retry_after == budget = 2000) succeeds and consumes budget (-= not +=):
    #    1st 429 consumes all 2000 budget; 2nd 429 needs 20s (> CI_TOTAL_BUDGET=10s) and fails with HTTP_ERROR!
    c1 = _td140_clock(monkeypatch, vp, responses=[
        _td140_ok(rl_ok, remaining='15', reset='2000'),
        {'kind': 'HTTP', 'code': 429, 'remaining': '0', 'reset': None, 'retry_after': '2000'},
        {'kind': 'HTTP', 'code': 429, 'remaining': '0', 'reset': None, 'retry_after': '20'},
    ])
    vp.CI_TOTAL_BUDGET = 10.0
    rc, p1 = _td140_run(vp, _td140_args(max_attempts=1, interval_seconds=0, initial_delay_seconds=0,
                                       phase='postmain', rate_limit_wait_budget=2000), capsys)
    assert rc == 2 and p1['reason'] == 'HTTP_ERROR'
    assert c1.sleeps == [2000.0] and p1['rate_limit_waits'] == 1

    # 2. retry_after == 0 on 429 when budget=0.5s does NOT extend and breaks at deadline=0 -> sleeps=[], waits=0
    vp.CI_TOTAL_BUDGET = 0.0
    c2 = _td140_clock(monkeypatch, vp, responses=[
        {'kind': 'HTTP', 'code': 429, 'remaining': '0', 'reset': None, 'retry_after': '0'},
    ])
    rc, p2 = _td140_run(vp, _td140_args(max_attempts=1, interval_seconds=0, rate_limit_wait_budget=0), capsys)
    assert rc == 2 and c2.sleeps == [] and p2['rate_limit_waits'] == 0

    # 3. TRANSPORT retry does NOT consume rate_limit_wait_budget or count as limited even when budget allows retry_delay
    vp.CI_TOTAL_BUDGET = 1.0
    c3 = _td140_clock(monkeypatch, vp, get_cost=0.95, responses=[
        _td140_ok(rl_ok, remaining='15', reset='2000'),
        {'kind': 'TRANSPORT', 'detail': 'timeout'},
        _td140_ok(runs, remaining='14', reset='2000'),
        _td140_ok(jobs, remaining='13', reset='2000'),
    ])
    rc, p3 = _td140_run(vp, _td140_args(max_attempts=1, interval_seconds=0, rate_limit_wait_budget=100), capsys)
    assert rc == 2 and c3.sleeps == [] and p3['rate_limit_waits'] == 0


def test_td140_point2_no_count_when_limit_break_without_sleep(monkeypatch, capsys):
    vp = _td140_vp('vp_td140_point2')
    vp.CI_TOTAL_BUDGET = 5.0
    c1 = _td140_clock(monkeypatch, vp, responses=[
        {'kind': 'HTTP', 'code': 403, 'retry_after': None, 'remaining': '0', 'reset': '111'},
    ])
    rc, p1 = _td140_run(vp, _td140_args(max_attempts=60, interval_seconds=0, phase='candidate'), capsys)
    assert rc == 2 and c1.sleeps == [] and p1['rate_limit_waits'] == 0 and p1['rate_limit_wait_events'] == []

    # Polling loop cap (max_attempts=1, interval=60 -> deadline uses 60 not 61): checks rate limit break at request_index==2
    vp.CI_TOTAL_BUDGET = 1800.0
    c2 = _td140_clock(monkeypatch, vp, responses=[
        {'kind': 'HTTP', 'code': 503, 'retry_after': None, 'remaining': '20', 'reset': None},
        {'kind': 'HTTP', 'code': 503, 'retry_after': None, 'remaining': '19', 'reset': None},
        {'kind': 'HTTP', 'code': 403, 'retry_after': None, 'remaining': '0', 'reset': '120'},
    ])
    rc, p2 = _td140_run(vp, _td140_args(max_attempts=1, interval_seconds=0, phase='postmain'), capsys)
    assert rc == 2 and len(c2.sleeps) == 2 and p2['rate_limit_waits'] == 0 and p2['rate_limit_wait_events'] == []
    assert p2['min_rate_limit_remaining'] == 0


def test_td140_remaining_cmd_ci_status_and_do_get_json_boundaries(tmp_path, monkeypatch, capsys):
    import argparse
    vp = _td140_vp('vp_td140_more')
    sha, branch = 'c' * 40, 'batch/so-g3'
    empty_runs = {'workflow_runs': []}
    ok_runs = {'workflow_runs': [{'id': 8810, 'name': 'Verify', 'head_sha': sha, 'head_branch': branch,
                                  'event': 'push', 'status': 'completed', 'conclusion': 'success', 'run_attempt': 1}]}
    ok_jobs = {'jobs': [{'name': j, 'status': 'completed', 'conclusion': 'success'} for j in ('verify', 'gateway-windows')]}

    # 1. Default max_attempts=30, interval_seconds=20 via omitted attrs; check diagnostic failures=0 & hard_deadline=True
    (tmp_path / '.git').mkdir(exist_ok=True)
    monkeypatch.chdir(tmp_path)
    diag_rel = '.git/TD140-DEF-candidate-ci-diagnostic.json'
    c_def = _td140_clock(monkeypatch, vp, responses=[_td140_ok(empty_runs, remaining='2') for _ in range(31)])
    ns_def = argparse.Namespace(api_base='https://api.github.com', repo='hhai0519/HH.AI_v2', head_sha=sha,
                                branch=branch, require_job=['verify', 'gateway-windows'],
                                event='push', workflow_name='Verify', diagnostic_file=diag_rel)
    rc_def, p_def = _td140_run(vp, ns_def, capsys)
    assert rc_def == 2 and p_def['attempts_used'] == 30 and p_def['min_rate_limit_remaining'] == 2
    assert c_def.sleeps == [20.0] * 29
    diag_def = json.loads((tmp_path / diag_rel).read_text('utf-8'))
    assert diag_def['transport']['failures'] == 0 and diag_def['transport']['hard_deadline'] is True

    # 2. Deadline formula: 0 + 1*(0+60) = 60.0s (not 61.0!): 2 GETs (20.1s) + 0.1s sleep = 40.3s, 3rd GET 20.1s -> 60.4s >= 60.0s
    #    Also captures exact remaining_budget = 60.0 - 40.3 = 19.7 (kills deadline - monotonic -> +)
    budgets_seen = []
    orig_clock = _td140_clock(monkeypatch, vp, get_cost=20.1, responses=[
        {'kind': 'HTTP', 'code': 503, 'remaining': '20'}, _td140_ok(ok_runs), _td140_ok(ok_jobs)])
    orig_get = vp._ci_bounded_get
    def rec_get(url, budget):
        budgets_seen.append(round(budget, 3))
        return orig_get(url, budget)
    monkeypatch.setattr(vp, '_ci_bounded_get', rec_get)
    rc_60, _ = _td140_run(vp, _td140_args(max_attempts=1, interval_seconds=0, initial_delay_seconds=0), capsys)
    assert rc_60 == 2 and budgets_seen[2] == pytest.approx(19.7) and orig_clock.sleeps == [0.1]

    # remaining_budget <= 0 breaks without calling _ci_bounded_get; remaining_budget == 1.0 succeeds (kills 0 -> 1)
    import base64
    from types import SimpleNamespace
    vp.CI_TOTAL_BUDGET = 10.0
    m_state = {'n': 0, 'gets': 0}
    def step_mono():
        m_state['n'] += 1
        return 0.0 if m_state['n'] <= 7 else 10.0
    def step_get(url, budget):
        m_state['gets'] += 1
        return _td140_ok(ok_runs)
    monkeypatch.setattr(vp, 'time', SimpleNamespace(monotonic=step_mono, sleep=lambda d: None, time=lambda: 100.0))
    monkeypatch.setattr(vp, '_ci_bounded_get', step_get)
    assert _td140_run(vp, _td140_args(initial_delay_seconds=0), capsys)[0] == 2 and m_state['gets'] == 1

    vp.CI_TOTAL_BUDGET = 1.0
    _td140_clock(monkeypatch, vp, responses=[_td140_ok(ok_runs), _td140_ok(ok_jobs)])
    assert _td140_run(vp, _td140_args(initial_delay_seconds=0), capsys)[0] == 0
    vp.CI_TOTAL_BUDGET = 1800.0

    # Exact len(candidate_body) == CI_MAX_BYTES accepted in do_get_json (kills > -> >=)
    max_runs_doc = dict(ok_runs, pad='')
    prefix_bytes = json.dumps(max_runs_doc).encode('utf-8')
    pad_need = vp.CI_MAX_BYTES - len(prefix_bytes)
    exact_runs_body = json.dumps(dict(ok_runs, pad='a' * pad_need)).encode('utf-8')
    assert len(exact_runs_body) == vp.CI_MAX_BYTES
    _td140_clock(monkeypatch, vp, responses=[
        {'kind': 'OK', 'body': base64.b64encode(exact_runs_body).decode()},
        _td140_ok(ok_jobs),
    ])
    assert _td140_run(vp, _td140_args(), capsys)[0] == 0

    # 3. do_get_json: INVALID breaks without retry; bad base64 rejected (validate=True); 404 w/ remaining=0 breaks
    c_inv = _td140_clock(monkeypatch, vp, responses=[{'kind': 'INVALID'}])
    assert _td140_run(vp, _td140_args(), capsys)[0] == 2 and len(c_inv.gets) == 1 and c_inv.sleeps == []
    c_b64 = _td140_clock(monkeypatch, vp, responses=[
        {'kind': 'OK', 'body': _td140_ok(ok_runs)['body'] + '!', 'remaining': '9'},
        _td140_ok(ok_jobs, remaining='8'),
    ])
    assert _td140_run(vp, _td140_args(), capsys)[0] == 2 and len(c_b64.gets) == 1
    c_404 = _td140_clock(monkeypatch, vp, responses=[
        {'kind': 'HTTP', 'code': 404, 'remaining': '0', 'reset': None, 'retry_after': '5'}])
    assert _td140_run(vp, _td140_args(), capsys)[0] == 2 and len(c_404.gets) == 1 and c_404.sleeps == []

    # 4. TRANSPORT/500/504 with budget>0 must not mark limited or extend; tight CI_TOTAL_BUDGET=0.12 reaches L636 and rejects extend
    c_tr = _td140_clock(monkeypatch, vp, responses=[
        _td140_ok({}, remaining='50'),
        {'kind': 'TRANSPORT', 'detail': 'reset'},
        _td140_ok(ok_runs, remaining='49'),
        _td140_ok(ok_jobs, remaining='48'),
    ])
    rc_tr, p_tr = _td140_run(vp, _td140_args(rate_limit_wait_budget=100), capsys)
    assert rc_tr == 0 and c_tr.sleeps == [0.1] and p_tr['rate_limit_waits'] == 0

    vp.CI_TOTAL_BUDGET = 0.12
    c_tr2 = _td140_clock(monkeypatch, vp, get_cost=0.05, responses=[
        _td140_ok({}, remaining='50'),
        {'kind': 'TRANSPORT', 'detail': 'timeout'},
        _td140_ok(ok_runs, remaining='49'),
        _td140_ok(ok_jobs, remaining='48'),
    ])
    rc_tr2, _ = _td140_run(vp, _td140_args(rate_limit_wait_budget=10), capsys)
    assert rc_tr2 == 2 and c_tr2.sleeps == []
    vp.CI_TOTAL_BUDGET = 1800.0

    # 4. Transient HTTP 500, 504 retry with rate_limit_wait_budget=100 without setting rate_limit_waits;
    #    3 consecutive 503s record transport.failures==3 and stop without extra sleep
    c_500 = _td140_clock(monkeypatch, vp, responses=[
        _td140_ok({}, remaining='50'),
        {'kind': 'HTTP', 'code': 500, 'remaining': '10'},
        {'kind': 'HTTP', 'code': 504, 'remaining': '9'},
        _td140_ok(ok_runs, remaining='8'),
        _td140_ok(ok_jobs, remaining='7'),
    ])
    rc_500, p_500 = _td140_run(vp, _td140_args(rate_limit_wait_budget=100), capsys)
    assert rc_500 == 0 and c_500.sleeps == [0.1, 0.2] and p_500['rate_limit_waits'] == 0 and p_500['min_rate_limit_remaining'] == 7

    diag_k = '.git/TD140-K-candidate-ci-diagnostic.json'
    c_k3 = _td140_clock(monkeypatch, vp, responses=[
        {'kind': 'HTTP', 'code': 503, 'remaining': '10'},
        {'kind': 'HTTP', 'code': 503, 'remaining': '9'},
        {'kind': 'HTTP', 'code': 503, 'remaining': '8'},
    ])
    rc_k3, _ = _td140_run(vp, _td140_args(diagnostic_file=diag_k), capsys)
    assert rc_k3 == 2 and len(c_k3.gets) == 3 and c_k3.sleeps == [0.1, 0.2]
    assert json.loads((tmp_path / diag_k).read_text('utf-8'))['transport']['failures'] == 3

    # 5. Exact equality boundary deadline - now == retry_delay (5.0 == 5.0) breaks without sleep
    vp.CI_TOTAL_BUDGET = 5.0
    c_eqd = _td140_clock(monkeypatch, vp, responses=[
        {'kind': 'HTTP', 'code': 429, 'remaining': '0', 'retry_after': '5'},
    ])
    assert _td140_run(vp, _td140_args(rate_limit_wait_budget=0), capsys)[0] == 2 and c_eqd.sleeps == []
    vp.CI_TOTAL_BUDGET = 1800.0

    # 6. Preflight: budget=1 calls /rate_limit; bad base64 'e30=$' ignored; core.remaining=4 lowers min_remaining;
    #    core_rem=0 triggers wait, reset_wait == budget (105 == 105) allowed; preflight consumes budget
    c_pf0 = _td140_clock(monkeypatch, vp, responses=[
        _td140_ok({'resources': {'core': {'remaining': 0, 'reset': 200}}}, remaining='20'),
        {'kind': 'HTTP', 'code': 429, 'remaining': '0', 'retry_after': '50'},
        _td140_ok(ok_runs, remaining='19'),
        _td140_ok(ok_jobs, remaining='18'),
    ])
    # initial=0, reset_wait=(200+5)-100=105 == budget=105 -> preflight sleeps 105, remaining budget=0!
    # 2nd request 429 retry_after=50 with CI_TOTAL_BUDGET=30 -> remaining deadline=30 < 50 & budget=0 -> HTTP_ERROR
    vp.CI_TOTAL_BUDGET = 30.0
    rc_pf0, p_pf0 = _td140_run(vp, _td140_args(max_attempts=1, interval_seconds=0, rate_limit_wait_budget=105), capsys)
    assert rc_pf0 == 2 and c_pf0.sleeps == [105.0] and p_pf0['rate_limit_waits'] == 1 and p_pf0['min_rate_limit_remaining'] == 0
    vp.CI_TOTAL_BUDGET = 1800.0

    # budget=1 -> still queries /rate_limit; invalid base64 rejected (validate=True); over-budget reset_wait skipped
    c_pf1 = _td140_clock(monkeypatch, vp, responses=[
        {'kind': 'OK', 'body': _td140_ok({'resources': {'core': {'remaining': 0, 'reset': 2000}}})['body'] + '!', 'remaining': '11'},
        _td140_ok(ok_runs, remaining='50'),
        _td140_ok(ok_jobs, remaining='50'),
    ])
    rc_pf1, p_pf1 = _td140_run(vp, _td140_args(rate_limit_wait_budget=1), capsys)
    assert rc_pf1 == 0 and c_pf1.gets[0].endswith('/rate_limit') and c_pf1.sleeps == [] and p_pf1['rate_limit_waits'] == 0
    assert p_pf1['min_rate_limit_remaining'] == 11

    c_pf_over = _td140_clock(monkeypatch, vp, responses=[
        _td140_ok({'resources': {'core': {'remaining': 0, 'reset': 500}}}, remaining='20'),
        _td140_ok(ok_runs, remaining='20'),
        _td140_ok(ok_jobs, remaining='20'),
    ])
    rc_po, p_po = _td140_run(vp, _td140_args(initial_delay_seconds=0, rate_limit_wait_budget=100), capsys)
    assert rc_po == 0 and c_pf_over.sleeps == [] and p_po['rate_limit_waits'] == 0

    c_pf_eq = _td140_clock(monkeypatch, vp, responses=[
        _td140_ok({'resources': {'core': {'remaining': 4, 'reset': 195}}}, remaining='20'),
        _td140_ok(ok_runs, remaining='20'),
        _td140_ok(ok_jobs, remaining='20'),
    ])
    rc_peq, p_peq = _td140_run(vp, _td140_args(initial_delay_seconds=100, rate_limit_wait_budget=500), capsys)
    assert rc_peq == 0 and c_pf_eq.sleeps == [100.0] and p_peq['rate_limit_waits'] == 0 and p_peq['min_rate_limit_remaining'] == 4

    # Invalid core_rem / core_reset types (base_epoch=2.0 -> reset=0 or True gives reset_wait > 0 unless filtered!); reset=1 valid
    for bad_core in (
        {'remaining': -1, 'reset': 2000},
        {'remaining': True, 'reset': 2000},
        {'remaining': 0, 'reset': 0},
        {'remaining': 0, 'reset': True},
    ):
        c_bc = _td140_clock(monkeypatch, vp, base_epoch=2.0, responses=[
            _td140_ok({'resources': {'core': bad_core}}, remaining='30'),
            _td140_ok(ok_runs, remaining='30'),
            _td140_ok(ok_jobs, remaining='30'),
        ])
        rc_bc, p_bc = _td140_run(vp, _td140_args(rate_limit_wait_budget=3000), capsys)
        assert rc_bc == 0 and c_bc.sleeps == [] and p_bc['rate_limit_waits'] == 0

    c_r1 = _td140_clock(monkeypatch, vp, base_epoch=2.0, responses=[
        _td140_ok({'resources': {'core': {'remaining': 0, 'reset': 1}}}, remaining='30'),
        _td140_ok(ok_runs, remaining='30'),
        _td140_ok(ok_jobs, remaining='30'),
    ])
    rc_r1, p_r1 = _td140_run(vp, _td140_args(rate_limit_wait_budget=100), capsys)
    assert rc_r1 == 0 and c_r1.sleeps == [4.0] and p_r1['rate_limit_waits'] == 1

    # initial_delay capped by total_deadline - monotonic (start now=5.0 -> 15.0 - 5.0 = 10.0 vs 15.0 + 5.0 = 20.0)
    vp.CI_TOTAL_BUDGET = 10.0
    c_cap = _td140_clock(monkeypatch, vp, responses=[_td140_ok(ok_runs), _td140_ok(ok_jobs)])
    c_cap.now = 5.0
    rc_cap, _ = _td140_run(vp, _td140_args(initial_delay_seconds=50), capsys)
    assert rc_cap == 2 and c_cap.sleeps == [10.0] and c_cap.gets == []
    vp.CI_TOTAL_BUDGET = 1800.0

    c_d1 = _td140_clock(monkeypatch, vp, responses=[_td140_ok(ok_runs), _td140_ok(ok_jobs)])
    assert _td140_run(vp, _td140_args(initial_delay_seconds=1), capsys)[0] == 0 and c_d1.sleeps == [1.0]

    vp.CI_TOTAL_BUDGET = 0.0
    c_z = _td140_clock(monkeypatch, vp, responses=[_td140_ok(ok_runs)])
    rc_z, p_z = _td140_run(vp, _td140_args(initial_delay_seconds=0), capsys)
    assert rc_z == 2 and c_z.gets == [] and p_z['attempts_used'] == 0
    vp.CI_TOTAL_BUDGET = 1800.0

    c_http_pf = _td140_clock(monkeypatch, vp, responses=[
        {'kind': 'HTTP', 'code': 403, 'remaining': '3'},
        _td140_ok(ok_runs, remaining='30'),
        _td140_ok(ok_jobs, remaining='30'),
    ])
    rc_hp, p_hp = _td140_run(vp, _td140_args(rate_limit_wait_budget=100), capsys)
    assert rc_hp == 0 and p_hp['min_rate_limit_remaining'] == 3

    # Attempt loop: max_attempts=2, first attempt empty, second succeeds after initial_delay + interval_seconds
    c_att = _td140_clock(monkeypatch, vp, responses=[
        _td140_ok(empty_runs, remaining='30'),
        _td140_ok(ok_runs, remaining='29'),
        _td140_ok(ok_jobs, remaining='28'),
    ])
    rc_att, p_att = _td140_run(vp, _td140_args(max_attempts=2, interval_seconds=5, initial_delay_seconds=10), capsys)
    assert rc_att == 0 and p_att['attempts_used'] == 2 and c_att.sleeps == [10.0, 5.0]


def test_t1_count_match(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    needle = tmp_path / "needle.txt"
    target.write_bytes(b"apple\nbanana\napple\ncherry\n")
    needle.write_bytes(b"apple\n")

    res = run_tool("count", "--target", str(target), "--needle-file", str(needle), "--expect", "2")
    assert res.returncode == 0
    data = json.loads(res.stdout.decode("ascii"))
    assert data["tool"] == "verification_primitives"
    assert data["version"] == 1
    assert data["command"] == "count"
    assert data["status"] == "PASS"
    assert data["count"] == 2
    assert data["expect"] == 2
    assert data["target_sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()


def test_t2_count_mismatch(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    needle = tmp_path / "needle.txt"
    target.write_bytes(b"apple\nbanana\napple\n")
    needle.write_bytes(b"apple\n")

    res = run_tool("count", "--target", str(target), "--needle-file", str(needle), "--expect", "1")
    assert res.returncode == 1
    data = json.loads(res.stdout.decode("ascii"))
    assert data["command"] == "count"
    assert data["status"] == "CANDIDATE_INVALID"
    assert data["count"] == 2
    assert data["expect"] == 1


def test_t3_count_no_expect(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    needle = tmp_path / "needle.txt"
    target.write_bytes(b"apple\nbanana\napple\n")
    needle.write_bytes(b"apple\n")

    res = run_tool("count", "--target", str(target), "--needle-file", str(needle))
    assert res.returncode == 0
    data = json.loads(res.stdout.decode("ascii"))
    assert data["command"] == "count"
    assert data["status"] == "REPORT"
    assert data["count"] == 2
    assert data["expect"] is None


def test_t4_count_crlf_target_and_lf_target(tmp_path: Path) -> None:
    target_crlf = tmp_path / "target_crlf.txt"
    target_lf = tmp_path / "target_lf.txt"
    needle_lf = tmp_path / "needle_lf.txt"

    target_crlf.write_bytes(b"item1\r\nitem2\r\nitem1\r\n")
    target_lf.write_bytes(b"item1\nitem2\nitem1\n")
    needle_lf.write_bytes(b"item1\n")

    res_crlf = run_tool("count", "--target", str(target_crlf), "--needle-file", str(needle_lf))
    res_lf = run_tool("count", "--target", str(target_lf), "--needle-file", str(needle_lf))

    assert res_crlf.returncode == 0
    assert res_lf.returncode == 0
    data_crlf = json.loads(res_crlf.stdout.decode("ascii"))
    data_lf = json.loads(res_lf.stdout.decode("ascii"))

    assert data_crlf["count"] == 2
    assert data_lf["count"] == 2
    assert data_crlf["count"] == data_lf["count"]


def test_t5_needle_trailing_newline_strip(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    needle_single = tmp_path / "needle_single.txt"
    needle_double = tmp_path / "needle_double.txt"

    # target has "token other" without trailing newline after token
    target.write_bytes(b"token other\n")
    needle_single.write_bytes(b"token\n")
    needle_double.write_bytes(b"token\n\n")

    res_single = run_tool("count", "--target", str(target), "--needle-file", str(needle_single))
    res_double = run_tool("count", "--target", str(target), "--needle-file", str(needle_double))

    assert res_single.returncode == 0
    assert res_double.returncode == 0
    data_single = json.loads(res_single.stdout.decode("ascii"))
    data_double = json.loads(res_double.stdout.decode("ascii"))

    # Single trailing newline stripped: "token" matches 1
    assert data_single["count"] == 1
    # Double trailing newline only stripped one: "token\n" matches 0
    assert data_double["count"] == 0


def test_t6_needle_has_bom_and_target_has_bom(tmp_path: Path) -> None:
    needle_bom = tmp_path / "needle_bom.txt"
    needle_bom.write_bytes(b"\xef\xbb\xbfpattern\n")
    target_clean = tmp_path / "target_clean.txt"
    target_clean.write_bytes(b"pattern exists here\n")

    res_bom = run_tool("count", "--target", str(target_clean), "--needle-file", str(needle_bom))
    assert res_bom.returncode == 2
    data_bom = json.loads(res_bom.stdout.decode("ascii"))
    assert data_bom["status"] == "VERIFICATION_TOOL_UNABLE_TO_COMPLETE"
    assert data_bom["reason"] == "NEEDLE_HAS_BOM"

    target_bom = tmp_path / "target_bom.txt"
    target_bom.write_bytes(b"\xef\xbb\xbfpattern exists here\n")
    needle_clean = tmp_path / "needle_clean.txt"
    needle_clean.write_bytes(b"pattern\n")

    res_tb = run_tool("count", "--target", str(target_bom), "--needle-file", str(needle_clean))
    assert res_tb.returncode == 0
    data_tb = json.loads(res_tb.stdout.decode("ascii"))
    assert data_tb["count"] == 1


def test_t7_count_error_conditions(tmp_path: Path) -> None:
    # 1. UTF8_DECODE_ERROR
    bad_target = tmp_path / "bad_target.bin"
    bad_target.write_bytes(b"\xff\xfe\xfa")
    good_needle = tmp_path / "good_needle.txt"
    good_needle.write_bytes(b"test\n")

    res_utf8 = run_tool("count", "--target", str(bad_target), "--needle-file", str(good_needle))
    assert res_utf8.returncode == 2
    assert json.loads(res_utf8.stdout.decode("ascii"))["reason"] == "UTF8_DECODE_ERROR"

    # 2. FILE_READ_ERROR
    missing_target = tmp_path / "non_existent.txt"
    res_fnf = run_tool("count", "--target", str(missing_target), "--needle-file", str(good_needle))
    assert res_fnf.returncode == 2
    assert json.loads(res_fnf.stdout.decode("ascii"))["reason"] == "FILE_READ_ERROR"

    # 3. EMPTY_NEEDLE (empty file, only LF, or only CRLF)
    empty_needle = tmp_path / "empty_needle.txt"
    empty_needle.write_bytes(b"")
    good_target = tmp_path / "good_target.txt"
    good_target.write_bytes(b"some content\n")

    res_empty = run_tool("count", "--target", str(good_target), "--needle-file", str(empty_needle))
    assert res_empty.returncode == 2
    assert json.loads(res_empty.stdout.decode("ascii"))["reason"] == "EMPTY_NEEDLE"

    lf_only_needle = tmp_path / "lf_only.txt"
    lf_only_needle.write_bytes(b"\n")
    res_lf_only = run_tool("count", "--target", str(good_target), "--needle-file", str(lf_only_needle))
    assert res_lf_only.returncode == 2
    assert json.loads(res_lf_only.stdout.decode("ascii"))["reason"] == "EMPTY_NEEDLE"

    crlf_only_needle = tmp_path / "crlf_only.txt"
    crlf_only_needle.write_bytes(b"\r\n")
    res_crlf_only = run_tool("count", "--target", str(good_target), "--needle-file", str(crlf_only_needle))
    assert res_crlf_only.returncode == 2
    assert json.loads(res_crlf_only.stdout.decode("ascii"))["reason"] == "EMPTY_NEEDLE"


def test_t8_near_production_encoding_cp950(tmp_path: Path) -> None:
    test_char = "✓"
    non_bmp_char = "🚀"

    with pytest.raises(UnicodeEncodeError):
        test_char.encode("cp950")
    assert ord(non_bmp_char) > 0xFFFF

    target = tmp_path / "target_cp950.txt"
    needle = tmp_path / "needle_cp950.txt"
    target.write_text(f"prefix {test_char} {non_bmp_char} suffix\n", encoding="utf-8")
    needle.write_text(f"{test_char} {non_bmp_char}\n", encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp950"
    env["PYTHONUTF8"] = "0"

    res = run_tool("count", "--target", str(target), "--needle-file", str(needle), "--expect", "1", env=env)
    assert res.returncode == 0
    assert all(b < 128 for b in res.stdout)
    data = json.loads(res.stdout.decode("ascii"))
    assert data["status"] == "PASS"
    assert data["count"] == 1


def test_t9_sha256_behaviors(tmp_path: Path) -> None:
    crlf_file = tmp_path / "crlf.txt"
    crlf_bytes = b"first line\r\nsecond line\r\n"
    crlf_file.write_bytes(crlf_bytes)

    lf_file = tmp_path / "lf.txt"
    lf_bytes = b"first line\nsecond line\n"
    lf_file.write_bytes(lf_bytes)

    # CRLF file: raw and lf sha256 differ
    res_crlf = run_tool("sha256", "--file", str(crlf_file))
    assert res_crlf.returncode == 0
    data_crlf = json.loads(res_crlf.stdout.decode("ascii"))
    assert data_crlf["sha256_raw"] != data_crlf["sha256_lf"]
    assert data_crlf["sha256_raw"] == hashlib.sha256(crlf_bytes).hexdigest()
    assert data_crlf["sha256_lf"] == hashlib.sha256(lf_bytes).hexdigest()

    # LF file: raw and lf sha256 are identical
    res_lf = run_tool("sha256", "--file", str(lf_file))
    assert res_lf.returncode == 0
    data_lf = json.loads(res_lf.stdout.decode("ascii"))
    assert data_lf["sha256_raw"] == data_lf["sha256_lf"]

    # Expect mismatch -> exit 1 / CANDIDATE_INVALID
    res_mismatch = run_tool("sha256", "--file", str(crlf_file), "--expect-raw", "0" * 64)
    assert res_mismatch.returncode == 1
    data_mm = json.loads(res_mismatch.stdout.decode("ascii"))
    assert data_mm["status"] == "CANDIDATE_INVALID"

    # All expect match -> exit 0 / PASS
    raw_sha = data_crlf["sha256_raw"]
    lf_sha = data_crlf["sha256_lf"]
    res_match = run_tool("sha256", "--file", str(crlf_file), "--expect-raw", raw_sha, "--expect-lf", lf_sha)
    assert res_match.returncode == 0
    data_m = json.loads(res_match.stdout.decode("ascii"))
    assert data_m["status"] == "PASS"

    # Non-hex expect -> exit 2 / INVALID_EXPECT
    res_invalid_expect = run_tool("sha256", "--file", str(crlf_file), "--expect-raw", "not_a_valid_hex")
    assert res_invalid_expect.returncode == 2
    data_ie = json.loads(res_invalid_expect.stdout.decode("ascii"))
    assert data_ie["status"] == "VERIFICATION_TOOL_UNABLE_TO_COMPLETE"
    assert data_ie["reason"] == "INVALID_EXPECT"


def test_t10_git_diff_digest(tmp_path: Path) -> None:
    # 1. Initialize temporary git repository
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=tmp_path, check=True)

    tracked_file = tmp_path / "tracked.txt"
    tracked_file.write_bytes(b"initial line\n")

    subprocess.run(
        ["git", "-c", "user.name=TestUser", "-c", "user.email=test@example.com", "add", "tracked.txt"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "-c", "user.name=TestUser", "-c", "user.email=test@example.com", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # 2. Modify worktree with cp950 non-encodable char and add untracked file
    tracked_file.write_text("initial line\nmodified ✓ 🚀\n", encoding="utf-8")
    untracked_file = tmp_path / "untracked.txt"
    untracked_file.write_text("untracked payload\n", encoding="utf-8")

    # Read-only status before
    status_before = subprocess.run(["git", "status", "--porcelain"], cwd=tmp_path, capture_output=True).stdout

    # 3. Run tool worktree mode
    res1 = run_tool("git-diff-digest", "--base", base_sha, "--repo-root", str(tmp_path))
    assert res1.returncode == 0
    data1 = json.loads(res1.stdout.decode("ascii"))
    assert data1["status"] == "REPORT"
    assert data1["changed_paths"] == ["tracked.txt"]
    assert data1["untracked_paths"] == ["untracked.txt"]

    # 4. Compare diff_sha256 with exact git diff stdout bytes SHA-256
    git_diff_proc = subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "core.quotepath=false",
            "-c",
            "color.ui=never",
            "diff",
            "--binary",
            "--full-index",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            base_sha,
        ],
        capture_output=True,
        check=True,
    )
    expected_diff_sha256 = hashlib.sha256(git_diff_proc.stdout).hexdigest()
    assert data1["diff_sha256"] == expected_diff_sha256

    # 5. Continuous two runs yield identical results
    res2 = run_tool("git-diff-digest", "--base", base_sha, "--repo-root", str(tmp_path))
    assert res2.returncode == 0
    data2 = json.loads(res2.stdout.decode("ascii"))
    assert data1 == data2

    # 6. Read-only negative control: status after equals status before
    status_after = subprocess.run(["git", "status", "--porcelain"], cwd=tmp_path, capture_output=True).stdout
    assert status_before == status_after

    # 7. Expect mismatch -> exit 1
    res_mismatch = run_tool("git-diff-digest", "--base", base_sha, "--expect", "0" * 64, "--repo-root", str(tmp_path))
    assert res_mismatch.returncode == 1
    data_mm = json.loads(res_mismatch.stdout.decode("ascii"))
    assert data_mm["status"] == "CANDIDATE_INVALID"

    # 8. Expect match -> exit 0
    res_match = run_tool(
        "git-diff-digest",
        "--base",
        base_sha,
        "--expect",
        expected_diff_sha256,
        "--repo-root",
        str(tmp_path),
    )
    assert res_match.returncode == 0
    data_m = json.loads(res_match.stdout.decode("ascii"))
    assert data_m["status"] == "PASS"

    # 9. Cached mode
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    res_cached = run_tool("git-diff-digest", "--base", base_sha, "--mode", "cached", "--repo-root", str(tmp_path))
    assert res_cached.returncode == 0
    data_cached = json.loads(res_cached.stdout.decode("ascii"))
    assert data_cached["mode"] == "cached"
    assert data_cached["changed_paths"] == ["tracked.txt"]

    # 10. Head mode
    subprocess.run(
        ["git", "-c", "user.name=TestUser", "-c", "user.email=test@example.com", "commit", "-m", "second"],
        cwd=tmp_path,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    res_head = run_tool("git-diff-digest", "--base", base_sha, "--mode", "head", "--repo-root", str(tmp_path))
    assert res_head.returncode == 0
    data_head = json.loads(res_head.stdout.decode("ascii"))
    assert data_head["mode"] == "head"
    assert data_head["changed_paths"] == ["tracked.txt"]

    # 11. INVALID_BASE -> exit 2
    res_inv = run_tool("git-diff-digest", "--base", "INVALID_BASE_HEX", "--repo-root", str(tmp_path))
    assert res_inv.returncode == 2
    assert json.loads(res_inv.stdout.decode("ascii"))["reason"] == "INVALID_BASE"

    # 12. BASE_NOT_FOUND (non-existent commit) -> exit 2
    res_bnf = run_tool("git-diff-digest", "--base", "0" * 40, "--repo-root", str(tmp_path))
    assert res_bnf.returncode == 2
    assert json.loads(res_bnf.stdout.decode("ascii"))["reason"] == "BASE_NOT_FOUND"

    # 13. BASE_NOT_FOUND (non-repo directory) -> exit 2
    non_repo_dir = tmp_path / "non_repo_directory"
    non_repo_dir.mkdir()
    res_non_repo = run_tool("git-diff-digest", "--base", "a" * 40, "--repo-root", str(non_repo_dir))
    assert res_non_repo.returncode == 2
    assert json.loads(res_non_repo.stdout.decode("ascii"))["reason"] == "BASE_NOT_FOUND"


def test_t11_multiline_crlf_normalization(tmp_path: Path) -> None:
    # target CRLF: "alpha\r\nbeta\r\n", needle LF: "alpha\nbeta\n" -> count 1
    target1 = tmp_path / "target1.txt"
    needle1 = tmp_path / "needle1.txt"
    target1.write_bytes(b"alpha\r\nbeta\r\n")
    needle1.write_bytes(b"alpha\nbeta\n")

    res1 = run_tool("count", "--target", str(target1), "--needle-file", str(needle1), "--expect", "1")
    assert res1.returncode == 0
    data1 = json.loads(res1.stdout.decode("ascii"))
    assert data1["status"] == "PASS"
    assert data1["count"] == 1

    # needle CRLF: "alpha\r\nbeta\r\n", target LF: "alpha\nbeta\n" -> count 1
    target2 = tmp_path / "target2.txt"
    needle2 = tmp_path / "needle2.txt"
    target2.write_bytes(b"alpha\nbeta\n")
    needle2.write_bytes(b"alpha\r\nbeta\r\n")

    res2 = run_tool("count", "--target", str(target2), "--needle-file", str(needle2), "--expect", "1")
    assert res2.returncode == 0
    data2 = json.loads(res2.stdout.decode("ascii"))
    assert data2["status"] == "PASS"
    assert data2["count"] == 1


def test_t12_non_utf8_diff(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo_t12"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=repo_dir, check=True)

    f = repo_dir / "data.bin"
    f.write_bytes(b"initial line\n")
    subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@e.com", "add", "data.bin"], cwd=repo_dir, check=True)
    subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@e.com", "commit", "-m", "init"], cwd=repo_dir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    base_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, check=True).stdout.strip()

    # Modify with non-UTF-8 bytes
    non_utf8_payload = b"initial line\n\x80\x81\xff\xfe\n"
    with pytest.raises(UnicodeDecodeError):
        non_utf8_payload.decode("utf-8")

    f.write_bytes(non_utf8_payload)

    res = run_tool("git-diff-digest", "--base", base_sha, "--repo-root", str(repo_dir))
    assert res.returncode == 0
    data = json.loads(res.stdout.decode("ascii"))

    # Compute expected diff_sha256 from raw git diff bytes
    git_diff_proc = subprocess.run(
        [
            "git",
            "-C",
            str(repo_dir),
            "-c",
            "core.quotepath=false",
            "-c",
            "color.ui=never",
            "diff",
            "--binary",
            "--full-index",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            base_sha,
        ],
        capture_output=True,
        check=True,
    )
    expected_diff_sha256 = hashlib.sha256(git_diff_proc.stdout).hexdigest()
    assert data["diff_sha256"] == expected_diff_sha256


def test_t13_non_ascii_output_digest(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo_t13"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=repo_dir, check=True)

    test_char = "✓"
    with pytest.raises(UnicodeEncodeError):
        test_char.encode("cp950")

    filename = f"tracked_{test_char}.txt"
    f = repo_dir / filename
    f.write_text("initial\n", encoding="utf-8")

    subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@e.com", "add", filename], cwd=repo_dir, check=True)
    subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@e.com", "commit", "-m", "init"], cwd=repo_dir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    base_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, check=True).stdout.strip()

    f.write_text("initial\nmodified\n", encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp950"
    env["PYTHONUTF8"] = "0"

    res = run_tool("git-diff-digest", "--base", base_sha, "--repo-root", str(repo_dir), env=env)
    assert res.returncode == 0
    assert all(b < 128 for b in res.stdout)
    data = json.loads(res.stdout.decode("ascii"))
    assert filename in data["changed_paths"]


class MockGitHubHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        server_state = getattr(self.server, "handler_state", {})
        recorded_requests = server_state.setdefault("recorded_requests", [])
        recorded_requests.append({
            "path": self.path,
            "headers": {k.lower(): v for k, v in self.headers.items()},
        })

        status_sequence = server_state.get("status_sequence")
        status_override = (status_sequence.pop(0) if status_sequence
                           else server_state.get("status_code_override"))
        if status_override is not None:
            self.send_response(status_override)
            self.send_header("Content-Type", "application/json")
            for name, value in server_state.get("status_headers", {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(b'{"message": "error"}')
            return

        raw_override = server_state.get("raw_response_override")
        if raw_override is not None:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(raw_override)
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.endswith("/actions/runs"):
            runs_queue = server_state.get("runs_queue")
            if runs_queue:
                body = runs_queue.pop(0)
            else:
                body = server_state.get("default_runs", {"total_count": 0, "workflow_runs": []})
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.github+json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode("utf-8"))
            return

        if "/actions/runs/" in path and path.endswith("/jobs"):
            parts = path.split("/")
            run_id = None
            try:
                run_id_idx = parts.index("runs") + 1
                run_id = int(parts[run_id_idx])
            except (ValueError, IndexError):
                pass

            jobs_map = server_state.get("jobs_map", {})
            body = jobs_map.get(run_id, {"total_count": 0, "jobs": []})
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.github+json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()


class MockGitHubServer:
    def __init__(self) -> None:
        self.server = http.server.HTTPServer(("127.0.0.1", 0), MockGitHubHandler)
        self.server.handler_state = {
            "recorded_requests": [],
            "runs_queue": [],
            "jobs_map": {},
            "status_code_override": None,
            "status_sequence": [],
            "status_headers": {},
            "raw_response_override": None,
        }
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        port = self.server.server_address[1]
        return f"http://127.0.0.1:{port}"

    @property
    def state(self) -> dict:
        return self.server.handler_state

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@contextlib.contextmanager
def mock_github_server():
    srv = MockGitHubServer()
    try:
        yield srv
    finally:
        srv.close()


def test_t14_ci_status_pass() -> None:
    with mock_github_server() as srv:
        head_sha = "a" * 40
        branch = "main"
        event = "push"
        workflow_name = "Verify"

        # 1. Single attempt PASS
        srv.state["default_runs"] = {
            "total_count": 1,
            "workflow_runs": [
                {
                    "id": 1001,
                    "name": workflow_name,
                    "head_sha": head_sha,
                    "head_branch": branch,
                    "event": event,
                    "status": "completed",
                    "conclusion": "success",
                    "run_attempt": 1,
                }
            ],
        }
        srv.state["jobs_map"][1001] = {
            "total_count": 2,
            "jobs": [
                {"id": 1, "name": "verify", "status": "completed", "conclusion": "success"},
                {"id": 2, "name": "gateway-windows", "status": "completed", "conclusion": "success"},
            ],
        }

        res = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--require-job", "gateway-windows",
            "--api-base", srv.url,
            "--max-attempts", "5",
            "--interval-seconds", "0",
        )
        assert res.returncode == 0
        data = json.loads(res.stdout.decode("ascii"))
        assert data["status"] == "PASS"
        assert data["command"] == "ci-status"
        assert data["attempts_used"] == 1
        assert data["run_id"] == 1001
        assert data["run_attempt"] == 1
        assert data["run_status"] == "completed"
        assert data["run_conclusion"] == "success"
        assert data["jobs"]["verify"] == {"status": "completed", "conclusion": "success"}
        assert data["jobs"]["gateway-windows"] == {"status": "completed", "conclusion": "success"}

        # Assert server received requests do NOT contain Authorization header
        for req in srv.state["recorded_requests"]:
            assert "authorization" not in req["headers"]

        # Assert query params in runs request contain head_sha, branch, event
        runs_req = [r for r in srv.state["recorded_requests"] if "/actions/runs?" in r["path"]][0]
        parsed_q = urllib.parse.parse_qs(urllib.parse.urlparse(runs_req["path"]).query)
        assert parsed_q["head_sha"] == [head_sha]
        assert parsed_q["branch"] == [branch]
        assert parsed_q["event"] == [event]

        # 2. Polling: two in_progress attempts, third completed PASS
        srv.state["recorded_requests"].clear()
        srv.state["runs_queue"] = [
            {
                "total_count": 1,
                "workflow_runs": [
                    {
                        "id": 1002,
                        "name": workflow_name,
                        "head_sha": head_sha,
                        "head_branch": branch,
                        "event": event,
                        "status": "in_progress",
                        "conclusion": None,
                        "run_attempt": 1,
                    }
                ],
            },
            {
                "total_count": 1,
                "workflow_runs": [
                    {
                        "id": 1002,
                        "name": workflow_name,
                        "head_sha": head_sha,
                        "head_branch": branch,
                        "event": event,
                        "status": "in_progress",
                        "conclusion": None,
                        "run_attempt": 1,
                    }
                ],
            },
            {
                "total_count": 1,
                "workflow_runs": [
                    {
                        "id": 1002,
                        "name": workflow_name,
                        "head_sha": head_sha,
                        "head_branch": branch,
                        "event": event,
                        "status": "completed",
                        "conclusion": "success",
                        "run_attempt": 1,
                    }
                ],
            },
        ]
        srv.state["jobs_map"][1002] = {
            "total_count": 2,
            "jobs": [
                {"id": 1, "name": "verify", "status": "completed", "conclusion": "success"},
                {"id": 2, "name": "gateway-windows", "status": "completed", "conclusion": "success"},
            ],
        }

        res2 = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--require-job", "gateway-windows",
            "--api-base", srv.url,
            "--max-attempts", "5",
            "--interval-seconds", "0",
        )
        assert res2.returncode == 0
        data2 = json.loads(res2.stdout.decode("ascii"))
        assert data2["status"] == "PASS"
        assert data2["attempts_used"] == 3
        assert data2["run_id"] == 1002


def test_t15_ci_status_candidate_invalid() -> None:
    with mock_github_server() as srv:
        head_sha = "b" * 40
        branch = "main"

        # 1. run conclusion failure -> exit 1
        srv.state["default_runs"] = {
            "total_count": 1,
            "workflow_runs": [
                {
                    "id": 2001,
                    "name": "Verify",
                    "head_sha": head_sha,
                    "head_branch": branch,
                    "event": "push",
                    "status": "completed",
                    "conclusion": "failure",
                    "run_attempt": 1,
                }
            ],
        }
        srv.state["jobs_map"][2001] = {
            "total_count": 2,
            "jobs": [
                {"id": 1, "name": "verify", "status": "completed", "conclusion": "success"},
                {"id": 2, "name": "gateway-windows", "status": "completed", "conclusion": "success"},
            ],
        }
        res1 = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--require-job", "gateway-windows",
            "--api-base", srv.url,
            "--max-attempts", "2",
            "--interval-seconds", "0",
        )
        assert res1.returncode == 1
        data1 = json.loads(res1.stdout.decode("ascii"))
        assert data1["status"] == "CANDIDATE_INVALID"
        assert data1["run_conclusion"] == "failure"

        # 2. run success but a required job failure -> exit 1
        srv.state["default_runs"] = {
            "total_count": 1,
            "workflow_runs": [
                {
                    "id": 2002,
                    "name": "Verify",
                    "head_sha": head_sha,
                    "head_branch": branch,
                    "event": "push",
                    "status": "completed",
                    "conclusion": "success",
                    "run_attempt": 1,
                }
            ],
        }
        srv.state["jobs_map"][2002] = {
            "total_count": 2,
            "jobs": [
                {"id": 1, "name": "verify", "status": "completed", "conclusion": "failure"},
                {"id": 2, "name": "gateway-windows", "status": "completed", "conclusion": "success"},
            ],
        }
        res2 = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--require-job", "gateway-windows",
            "--api-base", srv.url,
            "--max-attempts", "2",
            "--interval-seconds", "0",
        )
        assert res2.returncode == 1
        data2 = json.loads(res2.stdout.decode("ascii"))
        assert data2["status"] == "CANDIDATE_INVALID"
        assert data2["jobs"]["verify"]["conclusion"] == "failure"

        # 3. required job missing -> exit 1
        srv.state["default_runs"] = {
            "total_count": 1,
            "workflow_runs": [
                {
                    "id": 2003,
                    "name": "Verify",
                    "head_sha": head_sha,
                    "head_branch": branch,
                    "event": "push",
                    "status": "completed",
                    "conclusion": "success",
                    "run_attempt": 1,
                }
            ],
        }
        srv.state["jobs_map"][2003] = {
            "total_count": 1,
            "jobs": [
                {"id": 1, "name": "verify", "status": "completed", "conclusion": "success"},
            ],
        }
        res3 = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--require-job", "gateway-windows",
            "--api-base", srv.url,
            "--max-attempts", "2",
            "--interval-seconds", "0",
        )
        assert res3.returncode == 1
        data3 = json.loads(res3.stdout.decode("ascii"))
        assert data3["status"] == "CANDIDATE_INVALID"
        assert data3["jobs"]["gateway-windows"] is None


def test_t16_ci_status_unable() -> None:
    with mock_github_server() as srv:
        head_sha = "c" * 40
        branch = "main"

        # 1. Always in_progress up to max-attempts -> exit 2 / CI_PENDING_TIMEOUT
        srv.state["default_runs"] = {
            "total_count": 1,
            "workflow_runs": [
                {
                    "id": 3001,
                    "name": "Verify",
                    "head_sha": head_sha,
                    "head_branch": branch,
                    "event": "push",
                    "status": "in_progress",
                    "conclusion": None,
                    "run_attempt": 1,
                }
            ],
        }
        res1 = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--api-base", srv.url,
            "--max-attempts", "2",
            "--interval-seconds", "0",
        )
        assert res1.returncode == 2
        data1 = json.loads(res1.stdout.decode("ascii"))
        assert data1["status"] == "VERIFICATION_TOOL_UNABLE_TO_COMPLETE"
        assert data1["reason"] == "CI_PENDING_TIMEOUT"
        assert data1["attempts_used"] == 2
        assert data1["run_id"] == 3001

        # 2. Always 0 runs -> exit 2 / CI_PENDING_TIMEOUT and run_id is null
        srv.state["default_runs"] = {"total_count": 0, "workflow_runs": []}
        res2 = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--api-base", srv.url,
            "--max-attempts", "2",
            "--interval-seconds", "0",
        )
        assert res2.returncode == 2
        data2 = json.loads(res2.stdout.decode("ascii"))
        assert data2["status"] == "VERIFICATION_TOOL_UNABLE_TO_COMPLETE"
        assert data2["reason"] == "CI_PENDING_TIMEOUT"
        assert data2["run_id"] is None
        assert data2["attempts_used"] == 2

        # 3. Two matching runs -> exit 2 / AMBIGUOUS_RUNS
        srv.state["default_runs"] = {
            "total_count": 2,
            "workflow_runs": [
                {
                    "id": 3002,
                    "name": "Verify",
                    "head_sha": head_sha,
                    "head_branch": branch,
                    "event": "push",
                    "status": "completed",
                    "conclusion": "success",
                    "run_attempt": 1,
                },
                {
                    "id": 3003,
                    "name": "Verify",
                    "head_sha": head_sha,
                    "head_branch": branch,
                    "event": "push",
                    "status": "completed",
                    "conclusion": "success",
                    "run_attempt": 1,
                },
            ],
        }
        res3 = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--api-base", srv.url,
            "--max-attempts", "1",
            "--interval-seconds", "0",
        )
        assert res3.returncode == 2
        data3 = json.loads(res3.stdout.decode("ascii"))
        assert data3["reason"] == "AMBIGUOUS_RUNS"

        # 4. Non-matching runs (different SHA, branch, workflow name, event) are ignored
        srv.state["default_runs"] = {
            "total_count": 4,
            "workflow_runs": [
                {
                    "id": 4001,
                    "name": "Verify",
                    "head_sha": "d" * 40,  # other SHA
                    "head_branch": branch,
                    "event": "push",
                    "status": "completed",
                    "conclusion": "success",
                },
                {
                    "id": 4002,
                    "name": "Verify",
                    "head_sha": head_sha,
                    "head_branch": "other-branch",  # other branch (must be ignored!)
                    "event": "push",
                    "status": "completed",
                    "conclusion": "success",
                },
                {
                    "id": 4003,
                    "name": "OtherWorkflow",  # other workflow name
                    "head_sha": head_sha,
                    "head_branch": branch,
                    "event": "push",
                    "status": "completed",
                    "conclusion": "success",
                },
                {
                    "id": 4004,
                    "name": "Verify",
                    "head_sha": head_sha,
                    "head_branch": branch,
                    "event": "push",  # exactly matching run!
                    "status": "completed",
                    "conclusion": "success",
                    "run_attempt": 1,
                },
            ],
        }
        srv.state["jobs_map"][4004] = {
            "total_count": 1,
            "jobs": [{"id": 1, "name": "verify", "status": "completed", "conclusion": "success"}],
        }
        res4 = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--api-base", srv.url,
            "--max-attempts", "1",
            "--interval-seconds", "0",
        )
        assert res4.returncode == 0
        data4 = json.loads(res4.stdout.decode("ascii"))
        assert data4["status"] == "PASS"
        assert data4["run_id"] == 4004

        # 5. HTTP 403 -> exit 2 / HTTP_ERROR
        srv.state["status_code_override"] = 403
        res5 = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--api-base", srv.url,
            "--max-attempts", "1",
            "--interval-seconds", "0",
        )
        assert res5.returncode == 2
        data5 = json.loads(res5.stdout.decode("ascii"))
        assert data5["reason"] == "HTTP_ERROR"
        srv.state["status_code_override"] = None

        # 6. Non-JSON response -> exit 2 / INVALID_RESPONSE
        srv.state["raw_response_override"] = b"<html>502 Bad Gateway</html>"
        res6 = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--api-base", srv.url,
            "--max-attempts", "1",
            "--interval-seconds", "0",
        )
        assert res6.returncode == 2
        data6 = json.loads(res6.stdout.decode("ascii"))
        assert data6["reason"] == "INVALID_RESPONSE"
        srv.state["raw_response_override"] = None

        # 7. api-base is https://example.invalid -> exit 2 / INVALID_API_BASE and server receives 0 requests
        srv.state["recorded_requests"].clear()
        res7 = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--api-base", "https://example.invalid",
            "--max-attempts", "1",
            "--interval-seconds", "0",
        )
        assert res7.returncode == 2
        data7 = json.loads(res7.stdout.decode("ascii"))
        assert data7["reason"] == "INVALID_API_BASE"
        assert len(srv.state["recorded_requests"]) == 0

        # 8. head-sha invalid -> exit 2 / INVALID_HEAD_SHA
        res8 = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", "NOT_A_HEX_SHA",
            "--branch", branch,
            "--require-job", "verify",
            "--api-base", srv.url,
            "--max-attempts", "1",
            "--interval-seconds", "0",
        )
        assert res8.returncode == 2
        data8 = json.loads(res8.stdout.decode("ascii"))
        assert data8["reason"] == "INVALID_HEAD_SHA"




def test_t16_ci_status_bounded_transport_retry_fail_closed() -> None:
    head_sha = "d" * 40
    branch = "batch/test-ci-resilience"
    with mock_github_server() as srv:
        srv.state["default_runs"] = {
            "total_count": 1,
            "workflow_runs": [{
                "id": 9023, "name": "Verify", "head_sha": head_sha,
                "head_branch": branch, "event": "push", "status": "completed",
                "conclusion": "success", "run_attempt": 1,
            }],
        }
        srv.state["jobs_map"][9023] = {
            "total_count": 2,
            "jobs": [
                {"id": 1, "name": "verify", "status": "completed", "conclusion": "success"},
                {"id": 2, "name": "gateway-windows", "status": "completed", "conclusion": "success"},
            ],
        }

        def query() -> tuple[int, dict]:
            p = run_tool(
                "ci-status", "--repo", "hhai0519/HH.AI_v2",
                "--head-sha", head_sha, "--branch", branch,
                "--require-job", "verify", "--require-job", "gateway-windows",
                "--api-base", srv.url, "--max-attempts", "1", "--interval-seconds", "0",
            )
            return p.returncode, json.loads(p.stdout.decode("ascii"))

        # Transient runs and jobs API failures resolve only after a *real*
        # matching run and two completed required jobs have been received.
        srv.state["status_sequence"] = [503, None, 502, None]
        rc, good = query()
        assert (rc, good["status"], good["attempts_used"]) == (0, "PASS", 1)
        assert good["run_id"] == 9023
        assert len(srv.state["recorded_requests"]) == 4
        assert all("authorization" not in req["headers"] for req in srv.state["recorded_requests"])

        # Persistent 5xx must end in UNKNOWN, never green, within three GETs.
        srv.state["recorded_requests"].clear()
        srv.state["status_code_override"] = 503
        rc, unknown = query()
        assert rc == 2 and unknown["reason"] == "HTTP_ERROR"
        assert len(srv.state["recorded_requests"]) == 3
        srv.state["status_code_override"] = None

        # Rate-limit retry is allowed only for a short explicit Retry-After.
        srv.state["recorded_requests"].clear()
        srv.state["status_headers"] = {"Retry-After": "0"}
        srv.state["status_sequence"] = [429, None, None]
        rc, limited_then_good = query()
        assert rc == 0 and limited_then_good["run_id"] == 9023
        assert len(srv.state["recorded_requests"]) == 3

        # A long server-specified rate limit must not sleep, bypass or PASS.
        srv.state["recorded_requests"].clear()
        srv.state["status_code_override"] = 429
        srv.state["status_headers"] = {"Retry-After": "3600"}
        rc, unknown = query()
        assert rc == 2 and unknown["reason"] == "HTTP_ERROR"
        assert len(srv.state["recorded_requests"]) == 1
        srv.state["status_code_override"] = None
        srv.state["status_headers"] = {}

        # Unauthorized 403 remains immediately fail-closed: no token fallback.
        srv.state["recorded_requests"].clear()
        srv.state["status_code_override"] = 403
        rc, unknown = query()
        assert rc == 2 and unknown["reason"] == "HTTP_ERROR"
        assert len(srv.state["recorded_requests"]) == 1
        srv.state["status_code_override"] = None

        # A malformed 200 is never retried or transformed into a PASS.
        srv.state["recorded_requests"].clear()
        srv.state["raw_response_override"] = b"not json"
        rc, unknown = query()
        assert rc == 2 and unknown["reason"] == "INVALID_RESPONSE"
        assert len(srv.state["recorded_requests"]) == 1


def test_t17_ci_status_reject_trailing_newline() -> None:
    with mock_github_server() as srv:
        head_sha = "c" * 40
        branch = "main"

        # (a) head-sha with trailing LF -> exit 2 / INVALID_HEAD_SHA
        srv.state["recorded_requests"].clear()
        res_sha = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha + "\n",
            "--branch", branch,
            "--require-job", "verify",
            "--api-base", srv.url,
            "--max-attempts", "1",
            "--interval-seconds", "0",
        )
        assert res_sha.returncode == 2
        data_sha = json.loads(res_sha.stdout.decode("ascii"))
        assert data_sha["status"] == "VERIFICATION_TOOL_UNABLE_TO_COMPLETE"
        assert data_sha["reason"] == "INVALID_HEAD_SHA"
        assert len(srv.state["recorded_requests"]) == 0

        # (b) api-base with trailing LF -> exit 2 / INVALID_API_BASE
        srv.state["recorded_requests"].clear()
        res_api = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--api-base", srv.url + "\n",
            "--max-attempts", "1",
            "--interval-seconds", "0",
        )
        assert res_api.returncode == 2
        data_api = json.loads(res_api.stdout.decode("ascii"))
        assert data_api["status"] == "VERIFICATION_TOOL_UNABLE_TO_COMPLETE"
        assert data_api["reason"] == "INVALID_API_BASE"
        assert len(srv.state["recorded_requests"]) == 0

        # (c) repo with trailing LF -> exit 2 / INVALID_ARGUMENT
        srv.state["recorded_requests"].clear()
        res_repo = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2\n",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--api-base", srv.url,
            "--max-attempts", "1",
            "--interval-seconds", "0",
        )
        assert res_repo.returncode == 2
        data_repo = json.loads(res_repo.stdout.decode("ascii"))
        assert data_repo["status"] == "VERIFICATION_TOOL_UNABLE_TO_COMPLETE"
        assert data_repo["reason"] == "INVALID_ARGUMENT"
        assert len(srv.state["recorded_requests"]) == 0


def test_t16_ci_status_retry_network_and_limits_direct(monkeypatch, capsys) -> None:
    """Test the real production function with deterministic GET/clock behavior."""
    import argparse
    import base64
    import importlib.util
    import urllib.error
    from types import SimpleNamespace

    spec = importlib.util.spec_from_file_location('vp_g3_r2_test', TOOL_PATH)
    assert spec and spec.loader
    vp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vp)
    sha = 'd' * 40
    branch = 'batch/test-ci-resilience'
    args = argparse.Namespace(
        api_base='https://api.github.com', repo='hhai0519/HH.AI_v2',
        head_sha=sha, branch=branch, require_job=['verify', 'gateway-windows'],
        max_attempts=1, interval_seconds=0, event='push', workflow_name='Verify',
    )
    runs = {'workflow_runs': [{
        'id': 9023, 'name': 'Verify', 'head_sha': sha,
        'head_branch': branch, 'event': 'push', 'status': 'completed',
        'conclusion': 'success', 'run_attempt': 1,
    }]}
    jobs = {'total_count': 2, 'jobs': [
        {'id': 1, 'name': 'verify', 'status': 'completed', 'conclusion': 'success'},
        {'id': 2, 'name': 'gateway-windows', 'status': 'completed', 'conclusion': 'success'},
    ]}

    class FakeClock:
        now = 0.0
        sleeps = None
        def __init__(self):
            self.now, self.sleeps = 0.0, []
        def monotonic(self):
            return self.now
        def sleep(self, seconds):
            assert seconds >= 0
            self.sleeps.append(seconds)
            self.now += seconds

    def scenario(sequence, *, expected_rc, expected_gets, expected_status,
                 expected_sleeps=None, late=None):
        """Each step can be a success, an exception, or time advancement."""
        clock = FakeClock()
        invocations = []
        work = list(sequence)
        def fake_fetch(url, remaining):
            assert 0 < remaining <= 28.0
            invocations.append((url, remaining))
            result = work.pop(0)
            if late is not None:
                clock.now += late
            if isinstance(result, urllib.error.HTTPError):
                return {'kind': 'HTTP', 'code': result.code,
                        'retry_after': result.headers.get('Retry-After'),
                        'remaining': result.headers.get('X-RateLimit-Remaining'),
                        'reset': result.headers.get('X-RateLimit-Reset')}
            if isinstance(result, BaseException):
                return {'kind': 'TRANSPORT'}
            return {'kind': 'OK', 'body': base64.b64encode(json.dumps(result).encode()).decode()}
        monkeypatch.setattr(vp, '_ci_bounded_get', fake_fetch)
        monkeypatch.setattr(vp, 'time', SimpleNamespace(monotonic=clock.monotonic,
                                                      sleep=clock.sleep, time=lambda: 100.0 + clock.now))
        with pytest.raises(SystemExit) as caught:
            vp.cmd_ci_status(args)
        payload = json.loads(capsys.readouterr().out.strip())
        assert caught.value.code == expected_rc
        assert payload['status'] == expected_status
        assert len(invocations) == expected_gets
        assert all(url.startswith('https://api.github.com/') for url, _ in invocations)
        if expected_sleeps is not None:
            assert clock.sleeps == expected_sleeps
        return clock, invocations, payload

    temporary = urllib.error.URLError('temporary')
    scenario([temporary, temporary, runs, jobs], expected_rc=0, expected_gets=4,
             expected_status='PASS', expected_sleeps=[0.1, 0.2])
    scenario([urllib.error.URLError('still down')] * 3, expected_rc=2, expected_gets=3,
             expected_status='VERIFICATION_TOOL_UNABLE_TO_COMPLETE', expected_sleeps=[0.1, 0.2])
    http = lambda code, headers: urllib.error.HTTPError('https://api.github.com', code, 'error', headers, None)
    scenario([http(429, {}), runs], expected_rc=2, expected_gets=1,
             expected_status='VERIFICATION_TOOL_UNABLE_TO_COMPLETE', expected_sleeps=[])
    scenario([http(403, {'Retry-After': '1', 'X-RateLimit-Remaining': '9'}), runs],
             expected_rc=2, expected_gets=1,
             expected_status='VERIFICATION_TOOL_UNABLE_TO_COMPLETE', expected_sleeps=[])
    scenario([http(503, {}), runs, jobs], expected_rc=0, expected_gets=3,
             expected_status='PASS', expected_sleeps=[0.1])
    scenario([http(503, {})] * 3, expected_rc=2, expected_gets=3,
             expected_status='VERIFICATION_TOOL_UNABLE_TO_COMPLETE', expected_sleeps=[0.1, 0.2])
    # A single urlopen that consumes a whole budget must never be retried or PASS.
    scenario([urllib.error.URLError('slow'), runs], expected_rc=2, expected_gets=1,
             expected_status='VERIFICATION_TOOL_UNABLE_TO_COMPLETE', expected_sleeps=[], late=28.0)
    # A late-successful HTTP read must not become a green CI result.
    scenario([runs, jobs], expected_rc=2, expected_gets=1,
             expected_status='VERIFICATION_TOOL_UNABLE_TO_COMPLETE', expected_sleeps=[], late=29.0)


def test_g3_ci_reset_wait_k_budget_and_diagnostic(tmp_path, monkeypatch, capsys):
    """Fixed offline checks: consecutive K, reset waiting, atomic diagnostic, fail-closed."""
    import argparse
    import base64
    import importlib.util
    from types import SimpleNamespace
    spec = importlib.util.spec_from_file_location('vp_g3_case', TOOL_PATH)
    assert spec and spec.loader
    vp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vp)
    monkeypatch.chdir(tmp_path)
    (tmp_path / '.git').mkdir()
    sha = 'b'*40
    args = argparse.Namespace(api_base='https://api.github.com', repo='hhai0519/HH.AI_v2',
       head_sha=sha, branch='batch/g3-tests', require_job=['verify', 'gateway-windows'],
       max_attempts=1, interval_seconds=0, event='push', workflow_name='Verify',
       diagnostic_file='.git/B115-G3-PROBE-candidate-ci-diagnostic.json')
    runs = {'workflow_runs':[{'id':1234,'name':'Verify','head_sha':sha,'head_branch':args.branch,
             'event':'push','status':'completed','conclusion':'success','run_attempt':1}]}
    jobs = {'jobs':[{'name':job,'status':'completed','conclusion':'success'} for job in args.require_job]}
    times=[]
    clock=SimpleNamespace(now=0.0)
    def get_time(): return clock.now
    def sleep(d):
        assert d>=0 and d<=28
        times.append(d)
        clock.now+=d
    monkeypatch.setattr(vp,'time',SimpleNamespace(monotonic=get_time,sleep=sleep,time=lambda:100+clock.now))
    responses=[{'kind':'HTTP','code':403,'retry_after':None,'remaining':'0','reset':'101'},
               {'kind':'HTTP','code':503},
               {'kind':'OK','body':base64.b64encode(json.dumps(runs).encode()).decode()},
               {'kind':'OK','body':base64.b64encode(json.dumps(jobs).encode()).decode()}]
    def fake_get(url,budget):
        assert budget>0 and budget<=28
        return responses.pop(0)
    monkeypatch.setattr(vp,'_ci_bounded_get',fake_get)
    with pytest.raises(SystemExit) as rc:
        vp.cmd_ci_status(args)
    out=json.loads(capsys.readouterr().out)
    assert rc.value.code==0 and out['status']=='PASS'
    assert len(times)==2 and times[0]==1.0 and times[1]==0.2
    diagnostic=(tmp_path/args.diagnostic_file).read_bytes()
    assert diagnostic.endswith(b'\n') and b'\r\n' not in diagnostic
    d=json.loads(diagnostic)
    assert d['transport']['rate_limit_waits']==1
    assert d['transport']['retries']==2
    assert d['transport']['max_consecutive_failures']==3
    assert d['status']=='PASS' and not responses


def test_g3_ci_diagnostic_write_failure_cannot_pass(tmp_path, monkeypatch, capsys):
    import argparse
    import base64
    import importlib.util
    spec=importlib.util.spec_from_file_location('vp_g3_diag_failure', TOOL_PATH)
    vp=importlib.util.module_from_spec(spec);spec.loader.exec_module(vp)
    monkeypatch.chdir(tmp_path)
    sha='c'*40
    args=argparse.Namespace(api_base='https://api.github.com',repo='hhai0519/HH.AI_v2',
      head_sha=sha,branch='main',require_job=['verify'],max_attempts=1,interval_seconds=0,
      event='push',workflow_name='Verify',diagnostic_file='.git/B115-G3-PROBE-candidate-ci-diagnostic.json')
    runs={'workflow_runs':[{'id':1,'name':'Verify','head_sha':sha,'head_branch':'main',
          'event':'push','status':'completed','conclusion':'success','run_attempt':1}]}
    jobs={'jobs':[{'name':'verify','status':'completed','conclusion':'success'}]}
    q=iter([runs,jobs])
    monkeypatch.setattr(vp,'_ci_bounded_get',lambda *_:{'kind':'OK','body':base64.b64encode(json.dumps(next(q)).encode()).decode()})
    with pytest.raises(SystemExit) as rc: vp.cmd_ci_status(args)
    out=json.loads(capsys.readouterr().out)
    assert rc.value.code==2 and out['reason']=='DIAGNOSTIC_WRITE_FAILED'
    assert out['status']=='VERIFICATION_TOOL_UNABLE_TO_COMPLETE'


def test_g3_ci_hard_timeout_no_get_pass(monkeypatch):
    """OS watchdog rejects requests blocked by DNS or indefinitely trickling bytes."""
    import importlib.util
    spec=importlib.util.spec_from_file_location('vp_g3_deadline',TOOL_PATH)
    vp=importlib.util.module_from_spec(spec);spec.loader.exec_module(vp)
    def timeout(*a,**k):
        assert k['timeout']<=28
        raise subprocess.TimeoutExpired(a[0],k['timeout'])
    monkeypatch.setattr(vp.subprocess,'run',timeout)
    assert vp._ci_bounded_get('https://api.github.com/repos/a/b/actions/runs',28)['kind']=='TRANSPORT'



def test_g3_ci_budget_and_rate_limit_reset_outside_budget(monkeypatch, capsys):
    import argparse
    import importlib.util
    from types import SimpleNamespace
    spec=importlib.util.spec_from_file_location('vp_g3_budget', TOOL_PATH)
    vp=importlib.util.module_from_spec(spec);spec.loader.exec_module(vp)
    vp.CI_TOTAL_BUDGET=5.0
    args=argparse.Namespace(api_base='https://api.github.com',repo='hhai0519/HH.AI_v2',
         head_sha='d'*40,branch='main',require_job=['verify'],max_attempts=60,
         interval_seconds=0,event='push',workflow_name='Verify',diagnostic_file=None)
    clock=SimpleNamespace(now=0.0,sleeps=[])
    def sleep(t):
        clock.sleeps.append(t)
        clock.now+=t
    monkeypatch.setattr(vp,'time',SimpleNamespace(monotonic=lambda:clock.now,
      sleep=sleep,time=lambda:100+clock.now))
    calls=[]
    def fake_get(url,remaining):
        calls.append(remaining)
        return {'kind':'HTTP','code':403,'retry_after':None,'remaining':'0','reset':'111'}
    monkeypatch.setattr(vp,'_ci_bounded_get',fake_get)
    with pytest.raises(SystemExit) as rc: vp.cmd_ci_status(args)
    out=json.loads(capsys.readouterr().out)
    assert rc.value.code==2 and out['reason']=='HTTP_ERROR'
    assert len(calls)==1 and calls[0]<=5 and not clock.sleeps


def test_g3_ci_exact_K_bound_and_consistent_retry(monkeypatch,capsys):
    import argparse
    import base64
    import importlib.util
    from types import SimpleNamespace
    spec=importlib.util.spec_from_file_location('vp_g3_k', TOOL_PATH)
    vp=importlib.util.module_from_spec(spec);spec.loader.exec_module(vp)
    assert vp.CI_TRANSPORT_K==3
    args=argparse.Namespace(api_base='https://api.github.com',repo='hhai0519/HH.AI_v2',
        head_sha='f'*40,branch='main',require_job=['verify'],max_attempts=1,interval_seconds=0,
        event='push',workflow_name='Verify',diagnostic_file=None)
    clock=SimpleNamespace(now=0.0,sleeps=[])
    def sleep(t): clock.sleeps.append(t); clock.now+=t
    monkeypatch.setattr(vp,'time',SimpleNamespace(monotonic=lambda:clock.now,sleep=sleep,time=lambda:100+clock.now))
    replies=iter([{'kind':'TRANSPORT'}]*4)
    counter=[]
    def fail(*_): counter.append(1);return next(replies)
    monkeypatch.setattr(vp,'_ci_bounded_get',fail)
    with pytest.raises(SystemExit) as rc: vp.cmd_ci_status(args)
    out=json.loads(capsys.readouterr().out)
    assert rc.value.code==2 and out['reason']=='HTTP_ERROR'
    assert len(counter)==3 and clock.sleeps==[0.1,0.2]


def test_g3_ci_reset_waits_longer_than_single_get_but_within_total_budget(monkeypatch,capsys):
    """A 41s GitHub reset must wait even though one GET is capped at 28s."""
    import argparse
    import base64
    import importlib.util
    from types import SimpleNamespace
    spec=importlib.util.spec_from_file_location('vp_g3_long_reset', TOOL_PATH)
    vp=importlib.util.module_from_spec(spec);spec.loader.exec_module(vp)
    assert vp.CI_TOTAL_BUDGET==1800.0 and vp.CI_GET_BUDGET==28.0
    sha='e'*40
    args=argparse.Namespace(api_base='https://api.github.com',repo='hhai0519/HH.AI_v2',
        head_sha=sha,branch='main',require_job=['verify'],max_attempts=1,
        interval_seconds=0,event='push',workflow_name='Verify',diagnostic_file=None)
    runs={'workflow_runs':[{'id':2001,'name':'Verify','head_sha':sha,'head_branch':'main',
          'event':'push','status':'completed','conclusion':'success','run_attempt':1}]}
    jobs={'jobs':[{'name':'verify','status':'completed','conclusion':'success'}]}
    clock=SimpleNamespace(now=0.0,sleeps=[])
    def sleep(t):
        clock.sleeps.append(t)
        clock.now+=t
    monkeypatch.setattr(vp,'time',SimpleNamespace(monotonic=lambda:clock.now,sleep=sleep,
                                                 time=lambda:100.0+clock.now))
    responses=iter([{'kind':'HTTP','code':429,'remaining':'0','retry_after':None,'reset':'141'},
                    {'kind':'OK','body':base64.b64encode(json.dumps(runs).encode()).decode()},
                    {'kind':'OK','body':base64.b64encode(json.dumps(jobs).encode()).decode()}])
    per_get=[]
    def fake_get(url,remaining):
        per_get.append(remaining)
        assert remaining>0 and remaining<=28.0
        return next(responses)
    monkeypatch.setattr(vp,'_ci_bounded_get',fake_get)
    with pytest.raises(SystemExit) as rc: vp.cmd_ci_status(args)
    out=json.loads(capsys.readouterr().out)
    assert rc.value.code==0 and out['status']=='PASS'
    assert clock.sleeps==[41.0] and len(per_get)==3


# --- SO E27 reference tests: wall clock, fail-closed branches and diagnostic hygiene. ---
def _so_vp(name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, TOOL_PATH)
    vp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vp)
    return vp


def _so_args(**over):
    import argparse
    base = dict(api_base='https://api.github.com', repo='hhai0519/HH.AI_v2', head_sha='c' * 40,
                branch='batch/so-g3', require_job=['verify', 'gateway-windows'], max_attempts=1,
                interval_seconds=0, event='push', workflow_name='Verify', diagnostic_file=None)
    base.update(over)
    return argparse.Namespace(**base)


def _so_clock(monkeypatch, vp, get_cost=0.0, responses=None):
    from types import SimpleNamespace
    clock = SimpleNamespace(now=0.0, sleeps=[], gets=[])

    def sleep(d):
        assert d >= 0
        clock.sleeps.append(d)
        clock.now += d
    monkeypatch.setattr(vp, 'time', SimpleNamespace(monotonic=lambda: clock.now, sleep=sleep,
                                                    time=lambda: 100.0 + clock.now))

    def fake_get(url, budget):
        assert 0 < budget <= 28.0
        clock.gets.append(url)
        clock.now += get_cost
        return responses(url) if callable(responses) else responses.pop(0)
    monkeypatch.setattr(vp, '_ci_bounded_get', fake_get)
    return clock


def _so_run(vp, args, capsys):
    with pytest.raises(SystemExit) as caught:
        vp.cmd_ci_status(args)
    return caught.value.code, json.loads(capsys.readouterr().out.strip())


def _so_ok(obj):
    import base64
    return {'kind': 'OK', 'body': base64.b64encode(json.dumps(obj).encode()).decode()}


def test_so_g3_outer_poll_loop_respects_1800s_wall_clock(monkeypatch, capsys):
    vp = _so_vp('vp_so_wall')
    clock = _so_clock(monkeypatch, vp, responses=lambda url: _so_ok({'workflow_runs': []}))
    rc, payload = _so_run(vp, _so_args(max_attempts=60, interval_seconds=60), capsys)
    assert rc == 2 and payload['reason'] == 'CI_PENDING_TIMEOUT'
    # 60 x 60 s would be 3600 s; the shared deadline must stop sleeping before 1800 s.
    assert sum(clock.sleeps) < vp.CI_TOTAL_BUDGET and clock.now < vp.CI_TOTAL_BUDGET
    assert len(clock.gets) == 30 and clock.sleeps == [60] * 29


@pytest.mark.parametrize('first', [{'kind': 'INVALID'}, {'kind': 'SURPRISE'}])
def test_so_g3_invalid_child_reply_is_terminal_not_retried(monkeypatch, capsys, first):
    vp = _so_vp('vp_so_invalid')
    clock = _so_clock(monkeypatch, vp, responses=[first, _so_ok({'workflow_runs': []})])
    rc, payload = _so_run(vp, _so_args(), capsys)
    assert rc == 2 and payload['status'] == 'VERIFICATION_TOOL_UNABLE_TO_COMPLETE'
    assert len(clock.gets) == 1 and clock.sleeps == []


@pytest.mark.parametrize('retry_after', ['-5', 'abc', '1.5', ' 3'])
def test_so_g3_malformed_retry_after_fails_closed_without_sleep(monkeypatch, capsys, retry_after):
    vp = _so_vp('vp_so_retry_after')
    clock = _so_clock(monkeypatch, vp, responses=[
        {'kind': 'HTTP', 'code': 429, 'retry_after': retry_after, 'remaining': None, 'reset': None},
        _so_ok({'workflow_runs': []})])
    rc, payload = _so_run(vp, _so_args(), capsys)
    assert rc == 2 and payload['status'] == 'VERIFICATION_TOOL_UNABLE_TO_COMPLETE'
    assert len(clock.gets) == 1 and clock.sleeps == []


def test_so_g3_oversized_body_is_not_accepted(monkeypatch, capsys):
    import base64
    vp = _so_vp('vp_so_size')
    sha, branch = 'c' * 40, 'batch/so-g3'
    runs = json.dumps({'workflow_runs': [{'id': 77, 'name': 'Verify', 'head_sha': sha, 'head_branch': branch,
                       'event': 'push', 'status': 'completed', 'conclusion': 'success', 'run_attempt': 1}]})
    padded = (runs[:-1] + ' ' * (vp.CI_MAX_BYTES + 1) + '}').encode()  # valid JSON, over the cap
    jobs = {'jobs': [{'name': j, 'status': 'completed', 'conclusion': 'success'} for j in ('verify', 'gateway-windows')]}
    clock = _so_clock(monkeypatch, vp, responses=[{'kind': 'OK', 'body': base64.b64encode(padded).decode()},
                                                  _so_ok(jobs)])
    rc, payload = _so_run(vp, _so_args(), capsys)
    assert rc == 2 and payload['status'] == 'VERIFICATION_TOOL_UNABLE_TO_COMPLETE'
    assert len(clock.gets) == 1


def test_so_g3_child_nonzero_exit_is_invalid(monkeypatch):
    vp = _so_vp('vp_so_child')
    good = json.dumps({'kind': 'OK', 'body': ''}).encode()
    monkeypatch.setattr(vp.subprocess, 'run',
                        lambda *a, **k: subprocess.CompletedProcess(a, 1, good, b''))
    assert vp._ci_bounded_get('https://api.github.com/repos/a/b/actions/runs', 28.0) == {'kind': 'INVALID'}


def test_so_g3_worker_refuses_non_github_url_without_network(monkeypatch, capsys):
    vp = _so_vp('vp_so_worker')
    touched = []
    def forbidden(*a, **k):
        touched.append(a)
        raise OSError('network must not be touched')
    monkeypatch.setattr(vp.urllib.request, 'urlopen', forbidden)
    for url in ('https://evil.example/repos/a/b/actions/runs',
                'https://api.github.com.evil.example/repos/a/b/actions/runs',
                'http://127.0.0.2:80/repos/a/b/actions/runs'):
        vp._ci_http_worker(url)
        assert json.loads(capsys.readouterr().out.strip()) == {'kind': 'INVALID'}
    assert touched == []


@pytest.mark.parametrize('bad', ['../x-ci-diagnostic.json', '.git/../x-ci-diagnostic.json',
                                 '.git/a/b-ci-diagnostic.json', 'C:/x/.git/t-ci-diagnostic.json'])
def test_so_g3_bad_diagnostic_path_rejected_before_any_get(monkeypatch, capsys, bad):
    vp = _so_vp('vp_so_diagpath')
    clock = _so_clock(monkeypatch, vp, responses=[_so_ok({'workflow_runs': []})])
    rc, payload = _so_run(vp, _so_args(diagnostic_file=bad), capsys)
    assert rc == 2 and payload['reason'] == 'INVALID_DIAGNOSTIC_PATH'
    assert clock.gets == []


def test_so_g3_failed_replace_leaves_no_temp_diagnostic(tmp_path, monkeypatch):
    vp = _so_vp('vp_so_tmp')
    monkeypatch.chdir(tmp_path)
    (tmp_path / '.git').mkdir()
    def boom(*a, **k):
        raise OSError('replace denied')
    monkeypatch.setattr(vp.os, 'replace', boom)
    assert vp._ci_persist_diagnostic('.git/T-candidate-ci-diagnostic.json', {'a': 1}) is False
    assert list((tmp_path / '.git').iterdir()) == []


def test_so_g3_total_budget_never_exceeds_runner_timeout(monkeypatch, capsys):
    # Promotion verify calls ci-status with attempts=3, interval=10; batch_runner kills it at 330 s.
    vp = _so_vp('vp_so_budget_align')
    clock = _so_clock(monkeypatch, vp, responses=[
        {'kind': 'HTTP', 'code': 429, 'retry_after': '400', 'remaining': None, 'reset': None}])
    rc, payload = _so_run(vp, _so_args(max_attempts=3, interval_seconds=10), capsys)
    assert rc == 2 and payload['status'] == 'VERIFICATION_TOOL_UNABLE_TO_COMPLETE'
    assert clock.sleeps == [] and clock.now < 3 * (10 + 60) + 120


@pytest.mark.parametrize('limit_fields', [
    {'retry_after': '1801', 'reset': None},
    {'retry_after': None, 'reset': '1902'},
])
def test_g3_rate_limit_retry_wait_cannot_cross_total_deadline(monkeypatch, capsys, limit_fields):
    # G03: a mock clock makes the oversleep counterexample deterministic.
    # Never rely on a real-time hanging test as the only guard.
    vp = _so_vp('vp_g3_r2_presleep_absolute_limit')
    reply = {'kind': 'HTTP', 'code': 429, 'remaining': None, **limit_fields}
    clock = _so_clock(monkeypatch, vp, responses=[reply])
    rc, payload = _so_run(vp, _so_args(max_attempts=60, interval_seconds=0), capsys)
    assert rc == 2 and payload['status'] == 'VERIFICATION_TOOL_UNABLE_TO_COMPLETE'
    assert len(clock.gets) == 1
    assert clock.sleeps == [] and clock.now < vp.CI_TOTAL_BUDGET
