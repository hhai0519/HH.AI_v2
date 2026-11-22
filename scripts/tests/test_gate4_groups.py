"""D9 batch 1: grouped concurrent execution of the unit-test gate (scripts/gate4_groups.py).

Commitment -> test table (E27):
  C1 only the local runner gate enables grouping, CI and collect-only never      test_requested_*
  C2 group count N = min(4, cpu // 2), below 2 the sequential command runs        test_group_count_*, test_run_grouped_returns_none_*
  C3 deterministic LPT plan, crowd-sensitive files alone, default weights          test_plan_*
  C4 own basetemp / no cache / own JUnit per process                               test_command_*
  C5 any failing, timed-out or unlaunchable process fails the gate                 test_fault_*
  C6 counted tests must equal collected tests (missing or extra test fails)        test_fault_count_*, test_collect_*
  C7 internal deadline below the runner limit, nothing runs after it               test_fault_deadline_*
  C8 output order and progress lines                                              test_output_*
  C9 verify_all hook: grouped result used, None falls back, CI table unchanged     test_verify_all_*
  C10 real processes end to end (pass, failing group, missing JUnit)               test_real_*
  C11 calibration of the timing table                                              test_calibrate_*
"""
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(REPO_ROOT, 'scripts'))

import gate4_groups as g  # noqa: E402
import verify_all  # noqa: E402

FILES = ['scripts/tests/test_%s.py' % n for n in ('a', 'b', 'c', 'd', 'e', 'f', 'g', 'h')]
SEQ = ('scripts/tests/test_a.py',)
CMD = [sys.executable, '-m', 'pytest', 'scripts/tests', '-q', '--durations=25']


def nodeids(per_file=2):
    return ['%s::test_%d' % (f, i) for f in FILES for i in range(per_file)]


def collect_text(ids, declared=None):
    n = len(ids) if declared is None else declared
    return '\n'.join(ids) + '\n\n%d tests collected in 0.10s\n' % n


def write_junit(path, tests, failures=0, errors=0, skipped=0, cases=()):
    """JUnit file: suite counts as given, one test case per entry of `cases` (a module path such as scripts/tests/x.py)."""
    root = ET.Element('testsuites')
    suite = ET.SubElement(root, 'testsuite', name='pytest', tests=str(tests), failures=str(failures), errors=str(errors),
                          skipped=str(skipped))
    for i, case in enumerate(cases):
        ET.SubElement(suite, 'testcase', classname=case[:-3].replace('/', '.'), name='test_%d' % i)
    ET.ElementTree(root).write(path)


class FakeRunner:
    """Stands in for run_bounded: `per_name` maps a process name (seq, g1, ...) to overrides."""

    def __init__(self, ids, per_name=None, collect_override=None, clock=None):
        self.ids = ids
        self.per_name = per_name or {}
        self.collect_override = collect_override
        self.calls = []
        self.clock = clock
        self.cmds = {}

    def __call__(self, cmd, cwd, timeout, env=None, merge_stderr=False, capture_path=None, **kw):
        self.calls.append((list(cmd), timeout))
        if '--collect-only' in cmd:
            if self.collect_override is not None:
                return self.collect_override
            return SimpleNamespace(returncode=0, timed_out=False, launch_error=None,
                                   stdout=collect_text(self.ids).encode(), stderr=b'', kill_status='NOT_NEEDED')
        name = os.path.basename(cmd[cmd.index('--basetemp') + 1])[len('bt-'):]
        self.cmds[name] = list(cmd)
        files = [a for a in cmd if a.endswith('.py')]
        n_tests = sum(1 for i in self.ids if i.split('::')[0] in files)
        own_cases = [i.split('::')[0] for i in self.ids if i.split('::')[0] in files]
        spec = dict(rc=0, tests=n_tests, failures=0, errors=0, skipped=0, timed_out=False, launch_error=None,
                    junit=True, out=name + ' output\n', advance=0.0, cases=own_cases)
        spec.update(self.per_name.get(name, {}))
        if self.clock is not None:
            self.clock.now += spec['advance']
        if spec['junit']:
            write_junit(cmd[cmd.index('--junitxml') + 1], spec['tests'], spec['failures'], spec['errors'], spec['skipped'],
                        spec['cases'])
        return SimpleNamespace(returncode=spec['rc'], timed_out=spec['timed_out'], launch_error=spec['launch_error'],
                               stdout=spec['out'].encode(), stderr=b'', kill_status='NOT_NEEDED')


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def run(runner, tmp_path, cpu=8, **kw):
    lines = []
    kw.setdefault('timings_path', str(tmp_path / 'none.json'))
    kw.setdefault('sequential', SEQ)
    kw.setdefault('heartbeat_sec', 0)
    rc = g.run_grouped(CMD, {}, str(tmp_path), cpu_count=cpu, runner=runner, out=lines.append,
                       tmp_parent=str(tmp_path), **kw)
    return rc, '\n'.join(lines)


# ---- C1 -----------------------------------------------------------------------------------------------------------
def test_requested_only_for_local_gate_and_full_command():
    assert g.requested({g.LOCAL_GATE_ENV: 'x.raw'}, CMD)
    assert not g.requested({}, CMD)
    assert not g.requested({g.LOCAL_GATE_ENV: ''}, CMD)
    assert not g.requested({'CI': 'true'}, CMD)
    assert not g.requested({g.LOCAL_GATE_ENV: 'x.raw'}, CMD + ['--collect-only', '-qq'])
    assert not g.requested({g.LOCAL_GATE_ENV: 'x.raw'}, [sys.executable, 'script.py', 'a', 'b'])
    assert not g.requested(None, CMD)


# ---- C2 -----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize('cpu,expected', [(None, 1), (0, 1), (1, 1), (2, 1), (3, 1), (4, 2), (6, 3), (8, 4), (12, 4), (64, 4)])
def test_group_count(cpu, expected):
    assert g.group_count(cpu) == expected


def test_run_grouped_returns_none_below_two_groups_and_runs_nothing(tmp_path):
    runner = FakeRunner(nodeids())
    rc, text = run(runner, tmp_path, cpu=3)
    assert rc is None and 'mode=SEQUENTIAL' in text and runner.calls == []


# ---- C3 -----------------------------------------------------------------------------------------------------------
def test_plan_is_deterministic_lpt_with_crowd_sensitive_files_alone():
    timings = {FILES[0]: 50.0, FILES[1]: 40.0, FILES[2]: 30.0, FILES[3]: 20.0, FILES[4]: 10.0, FILES[5]: 10.0,
               FILES[6]: 5.0, FILES[7]: 5.0}
    first = g.plan_groups(FILES, timings, 2, SEQ)
    assert first == g.plan_groups(list(FILES), dict(timings), 2, SEQ)
    phase1, groups, loads = first
    assert phase1 == [FILES[0]]
    assert sorted(sum(groups, [])) == sorted(FILES[1:])
    assert not set(phase1) & set(sum(groups, []))
    assert loads == [60.0, 60.0] and abs(loads[0] - loads[1]) <= 40.0
    # heaviest rest-file goes to group 1, the next to group 2 (ties to the lowest index)
    assert FILES[1] in groups[0] and FILES[2] in groups[1]


def test_plan_default_weight_is_the_median_and_missing_table_gives_one():
    files = ['x%d.py' % i for i in range(5)]
    _, groups, loads = g.plan_groups(files, {'x0.py': 10.0, 'x1.py': 30.0}, 2, ())
    assert sorted(sum(groups, [])) == sorted(files) and sum(loads) == pytest.approx(10 + 30 + 3 * 20.0)
    _, groups, loads = g.plan_groups(files, {}, 2, ())
    assert sum(loads) == pytest.approx(5.0)


def test_plan_never_makes_more_groups_than_files_and_covers_every_file_once():
    phase1, groups, _ = g.plan_groups(FILES[:3], {}, 4, SEQ)
    assert phase1 == [FILES[0]] and len(groups) == 2 and sorted(sum(groups, [])) == FILES[1:3]
    assert g.plan_groups(SEQ and list(SEQ), {}, 4, SEQ) == ([FILES[0]], [], [])


@pytest.mark.parametrize('payload', ['{', '[]', '{"schema_version": 2, "files": {}}', '{"schema_version": 1, "files": []}',
                                     '{"schema_version": 1, "files": {"a.py": -1}}',
                                     '{"schema_version": 1, "files": {"a.py": "x"}}',
                                     '{"schema_version": 1, "files": {"a.py": true}}',
                                     '{"schema_version": 1, "files": {"a.py": NaN}}'])
def test_unusable_timing_table_gives_defaults_not_a_failure(tmp_path, payload):
    path = tmp_path / 't.json'
    path.write_text(payload, encoding='utf-8', newline='\n')
    table, note = g.load_timings(str(path))
    assert table == {} and note.startswith('UNAVAILABLE')
    assert g.load_timings(str(tmp_path / 'missing.json'))[0] == {}


def test_repository_timing_table_and_crowd_list_are_consistent():
    table, note = g.load_timings()
    assert note == 'OK' and table
    tests = {'scripts/tests/' + n for n in os.listdir(os.path.join(REPO_ROOT, 'scripts', 'tests')) if n.startswith('test_')}
    assert set(g.SEQUENTIAL_FILES) <= tests          # a renamed or removed crowd-sensitive file must be noticed
    assert set(table) <= tests


REAL_TREE_KILL = re.compile(r"process_alive\(|time\.sleep\(120\)")


def test_files_with_real_tree_kill_tests_run_in_phase_one():
    tests_dir = os.path.join(REPO_ROOT, 'scripts', 'tests')
    hits = sorted('scripts/tests/' + name for name in os.listdir(tests_dir)
                  if name.startswith('test_') and name.endswith('.py') and name != 'test_gate4_groups.py'
                  and REAL_TREE_KILL.search(open(os.path.join(tests_dir, name), encoding='utf-8').read()))
    assert [h for h in hits if h not in g.SEQUENTIAL_FILES] == []


# ---- C4 -----------------------------------------------------------------------------------------------------------
def test_command_has_own_basetemp_junit_no_cache_and_the_gate_options(tmp_path):
    runner = FakeRunner(nodeids())
    rc, _ = run(runner, tmp_path)
    assert rc == 0
    names = sorted(runner.cmds)
    assert names == ['g1', 'g2', 'g3', 'g4', 'seq']
    basetemps = [c[c.index('--basetemp') + 1] for c in runner.cmds.values()]
    junits = [c[c.index('--junitxml') + 1] for c in runner.cmds.values()]
    assert len(set(basetemps)) == len(set(junits)) == 5
    for cmd in runner.cmds.values():
        assert cmd[:3] == CMD[:3] and '-p' in cmd and 'no:cacheprovider' in cmd and '--durations=25' in cmd
        assert 'junit_family=xunit2' in cmd and 'scripts/tests' not in cmd
    flat = [f for n, c in runner.cmds.items() for f in c if f.endswith('.py') and f.startswith('scripts/tests/')]
    assert sorted(flat) == sorted(FILES)             # every collected file runs exactly once


# ---- C5 / C6 / C7 ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize('name,over,reason', [
    ('g2', dict(rc=1, failures=1), 'g2:EXIT_1'),
    ('g2', dict(rc=1, failures=1), 'g2:FAILED_TESTS'),
    ('seq', dict(rc=1, errors=1), 'seq:FAILED_TESTS'),
    ('g3', dict(rc=0, failures=1), 'g3:FAILED_TESTS'),
    ('g1', dict(rc=None, timed_out=True), 'g1:TIMEOUT'),
    ('g4', dict(rc=0, timed_out=True), 'g4:TIMEOUT'),
    ('g1', dict(rc=None, launch_error='OSError', junit=False), 'g1:LAUNCH_ERROR'),
    ('g2', dict(rc=0, junit=False), 'g2:JUNIT_UNREADABLE'),
    ('seq', dict(rc=3), 'seq:EXIT_3'),
])
def test_fault_one_process_fails_the_whole_gate(tmp_path, name, over, reason):
    runner = FakeRunner(nodeids(), {name: over})
    rc, text = run(runner, tmp_path)
    assert rc == 1 and 'status=FAIL' in text and reason in text
    assert 'ALL' not in text.split('GATE4_GROUPS_RESULT')[-1] and 'status=PASS' not in text
    # the other groups still ran and their complete output is attached
    assert text.count(' output') >= 4


def test_fault_count_a_missing_test_fails_even_if_every_exit_code_is_zero(tmp_path):
    ids = nodeids()
    runner = FakeRunner(ids, {'g2': dict(tests=1)})      # g2 silently ran one test too few (it holds 4 or more)
    rc, text = run(runner, tmp_path)
    assert rc == 1 and 'COUNT_MISMATCH' in text


def test_fault_count_an_extra_test_fails_too(tmp_path):
    runner = FakeRunner(nodeids(), {'g3': dict(tests=99)})
    rc, text = run(runner, tmp_path)
    assert rc == 1 and 'COUNT_MISMATCH' in text


def test_fault_count_skips_count_as_tests_but_not_as_failures(tmp_path):
    runner = FakeRunner(nodeids(), {'g1': dict(skipped=1)})
    rc, text = run(runner, tmp_path)
    assert rc == 0 and 'skipped=1' in text and 'status=PASS' in text


@pytest.mark.parametrize('how', ['rc', 'timeout', 'launch'])
def test_collect_failure_fails_before_anything_runs(tmp_path, how):
    bad = SimpleNamespace(returncode=2 if how == 'rc' else None, timed_out=how == 'timeout',
                          launch_error='OSError' if how == 'launch' else None, stdout=b'collection error', stderr=b'',
                          kill_status='NOT_NEEDED')
    runner = FakeRunner(nodeids(), collect_override=bad)
    rc, text = run(runner, tmp_path)
    assert rc == 1 and 'COLLECT_FAILED' in text and len(runner.calls) == 1


@pytest.mark.parametrize('stdout', [b'', b'no node ids here\n'])
def test_collect_with_no_tests_fails(tmp_path, stdout):
    ok = SimpleNamespace(returncode=0, timed_out=False, launch_error=None, stdout=stdout, stderr=b'', kill_status='NOT_NEEDED')
    rc, text = run(FakeRunner([], collect_override=ok), tmp_path)
    assert rc == 1 and 'COLLECT_COUNT_MISMATCH' in text


def test_collect_declared_count_must_match_the_listed_ids(tmp_path):
    ids = nodeids()
    ok = SimpleNamespace(returncode=0, timed_out=False, launch_error=None, stdout=collect_text(ids, declared=len(ids) + 1).encode(),
                         stderr=b'', kill_status='NOT_NEEDED')
    rc, text = run(FakeRunner(ids, collect_override=ok), tmp_path)
    assert rc == 1 and 'COLLECT_COUNT_MISMATCH' in text


def test_fault_deadline_phase_one_overrun_runs_no_group_and_fails(tmp_path):
    clock = Clock()
    runner = FakeRunner(nodeids(), {'seq': dict(advance=500.0)}, clock=clock)
    rc, text = run(runner, tmp_path, deadline_sec=400, clock=clock)
    assert rc == 1 and 'TIMEOUT' in text and not any('--basetemp' in c and os.path.basename(c[c.index('--basetemp') + 1]).startswith('bt-g') for c, _ in runner.calls)


def test_fault_deadline_timeouts_shrink_with_elapsed_time(tmp_path):
    clock = Clock()
    runner = FakeRunner(nodeids(), {'seq': dict(advance=100.0)}, clock=clock)
    rc, _ = run(runner, tmp_path, deadline_sec=1000, clock=clock)
    assert rc == 0
    limits = [t for c, t in runner.calls if '--collect-only' not in c]
    assert limits[0] == pytest.approx(1000) and all(t <= 900.0 + 1e-6 for t in limits[1:])


def test_default_internal_deadline_is_below_the_runner_gate_limit():
    import gate_runner
    assert g.DEADLINE_SEC < gate_runner.GATE_TIMEOUTS['PRECOMMIT'][3] and g.DEADLINE_SEC >= 3000


# ---- C8 -----------------------------------------------------------------------------------------------------------
def test_output_order_plan_then_phase_one_then_groups_then_one_result_line(tmp_path):
    runner = FakeRunner(nodeids())
    rc, text = run(runner, tmp_path)
    assert rc == 0
    order = [text.index(k) for k in ('GATE4_GROUPS mode=GROUPED', 'GATE4_PLAN phase=1', 'GATE4_PLAN group=g1',
                                      'GATE4_GROUP name=seq', 'GATE4_GROUP name=g1', 'GATE4_GROUP name=g4', 'GATE4_GROUPS_RESULT')]
    assert order == sorted(order) and text.count('GATE4_GROUPS_RESULT') == 1
    assert 'collected=16 counted=16' in text and 'reasons=NONE' in text and text.count('GATE4_GROUPS_RESULT status=PASS') == 1


def test_output_progress_line_while_groups_run_names_every_group(tmp_path):
    import threading
    release = threading.Event()
    base = FakeRunner(nodeids())

    def slow(cmd, cwd, timeout, env=None, merge_stderr=False, capture_path=None, **kw):
        if '--basetemp' in cmd and os.path.basename(cmd[cmd.index('--basetemp') + 1]) == 'bt-g1':
            release.wait(5)
        return base(cmd, cwd, timeout, env=env, merge_stderr=merge_stderr, capture_path=capture_path)

    lines = []

    def out(text):
        lines.append(text)
        if text.startswith('GATE4_PROGRESS'):
            release.set()

    rc = g.run_grouped(CMD, {}, str(tmp_path), cpu_count=8, runner=slow, out=out, tmp_parent=str(tmp_path),
                       timings_path=str(tmp_path / 'none.json'), sequential=SEQ, heartbeat_sec=0.05)
    assert rc == 0
    progress = [l for l in lines if l.startswith('GATE4_PROGRESS')]
    assert progress and all(('g%d=' % i) in progress[0] for i in (1, 2, 3, 4))


# ---- C9 -----------------------------------------------------------------------------------------------------------
def unit_gate():
    return next(x for x in verify_all.GATES if x['name'] == 'unit_tests')


def test_verify_all_uses_the_grouped_result_for_the_local_gate_only(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(verify_all.gate4_groups, 'run_grouped', lambda cmd, env, cwd, **kw: seen.append(cmd) or 7)
    monkeypatch.setattr(verify_all.subprocess, 'run', lambda *a, **kw: pytest.fail('sequential command ran'))
    assert verify_all.run_gate(unit_gate(), {g.LOCAL_GATE_ENV: 'x.raw'}, REPO_ROOT) == 7 and seen == [unit_gate()['cmd']]
    # a different gate never goes through the grouped path
    other = next(x for x in verify_all.GATES if x['name'] == 'webapp_tests')
    monkeypatch.setattr(verify_all.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=0))
    assert verify_all.run_gate(other, {g.LOCAL_GATE_ENV: 'x.raw'}, REPO_ROOT) == 0 and len(seen) == 1


def test_verify_all_ci_and_direct_runs_stay_sequential(monkeypatch):
    monkeypatch.setattr(verify_all.gate4_groups, 'run_grouped', lambda *a, **kw: pytest.fail('grouped path used'))
    ran = []
    monkeypatch.setattr(verify_all.subprocess, 'run', lambda cmd, **kw: ran.append(cmd) or SimpleNamespace(returncode=0))
    assert verify_all.run_gate(unit_gate(), {'CI': 'true', 'GITHUB_ACTIONS': 'true'}, REPO_ROOT) == 0
    assert verify_all.run_gate(unit_gate(), {}, REPO_ROOT) == 0 and ran == [unit_gate()['cmd']] * 2


def test_verify_all_collect_only_variant_is_never_grouped(monkeypatch):
    monkeypatch.setattr(verify_all.gate4_groups, 'run_grouped', lambda *a, **kw: pytest.fail('grouped path used'))
    quick = next(x for x in verify_all.quick_gates() if x['name'] == 'unit_tests')
    monkeypatch.setattr(verify_all.subprocess, 'run', lambda cmd, **kw: SimpleNamespace(returncode=0))
    assert verify_all.run_gate(quick, {g.LOCAL_GATE_ENV: 'x.raw'}, REPO_ROOT) == 0


def test_verify_all_none_from_the_grouped_path_falls_back_to_the_sequential_command(monkeypatch):
    monkeypatch.setattr(verify_all.gate4_groups, 'run_grouped', lambda *a, **kw: None)
    ran = []
    monkeypatch.setattr(verify_all.subprocess, 'run', lambda cmd, **kw: ran.append(cmd) or SimpleNamespace(returncode=5))
    assert verify_all.run_gate(unit_gate(), {g.LOCAL_GATE_ENV: 'x.raw'}, REPO_ROOT) == 5
    assert ran == [unit_gate()['cmd'] + list(g.OUTPUT_FORM)]


def test_verify_all_canonical_gate_four_command_is_unchanged():
    assert unit_gate()['cmd'] == [sys.executable, '-m', 'pytest', os.path.join(REPO_ROOT, 'scripts', 'tests'), '-q', '--durations=25']


def test_ci_workflow_does_not_set_the_local_gate_variable():
    root = os.path.join(REPO_ROOT, '.github')
    for folder, _, names in os.walk(root):
        for name in names:
            with open(os.path.join(folder, name), 'r', encoding='utf-8', errors='replace') as handle:
                assert g.LOCAL_GATE_ENV not in handle.read()


# ---- C10: real processes -------------------------------------------------------------------------------------------
def make_suite(tmp_path, bad=False):
    suite = tmp_path / 'suite'
    suite.mkdir()
    for i in range(4):
        body = 'def test_ok_%d():\n    assert True\n\ndef test_skip_%d():\n    import pytest\n    pytest.skip("x")\n' % (i, i)
        if bad and i == 2:
            body += '\ndef test_bad():\n    assert False\n'
        (suite / ('test_f%d.py' % i)).write_text(body, encoding='utf-8', newline='\n')
    return suite


def real_run(tmp_path, suite, **kw):
    lines = []
    cmd = [sys.executable, '-m', 'pytest', str(suite), '-q']
    env = dict(os.environ)
    env.pop('PYTEST_ADDOPTS', None)
    rc = g.run_grouped(cmd, env, str(tmp_path), cpu_count=4, out=lines.append, tmp_parent=str(tmp_path),
                       timings_path=str(tmp_path / 'none.json'), sequential=(), heartbeat_sec=0, **kw)
    return rc, '\n'.join(lines)


def test_real_processes_pass_with_exact_counts(tmp_path):
    rc, text = real_run(tmp_path, make_suite(tmp_path))
    assert rc == 0 and 'collected=8 counted=8 passed=4 skipped=4 failures=0 errors=0' in text and 'groups=2' in text


def test_real_processes_a_failing_test_in_one_group_fails_the_gate(tmp_path):
    rc, text = real_run(tmp_path, make_suite(tmp_path, bad=True))
    assert rc == 1 and 'FAILED_TESTS' in text and 'EXIT_1' in text and 'failures=1' in text


def test_real_processes_leave_nothing_behind_in_the_working_directory(tmp_path):
    suite = make_suite(tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())
    rc, _ = real_run(tmp_path, suite)
    assert rc == 0 and sorted(p.name for p in tmp_path.iterdir()) == before
    assert not (tmp_path / '.pytest_cache').exists()


def test_real_processes_a_group_that_never_writes_junit_fails_the_gate(tmp_path):
    suite = make_suite(tmp_path)
    (suite / 'conftest.py').write_text(
        'import os\nimport pytest\n\n'
        '@pytest.hookimpl(trylast=True)\n'
        'def pytest_unconfigure(config):\n'
        '    xml = getattr(config.option, "xmlpath", None)\n'
        '    if xml and os.path.exists(xml) and os.path.basename(str(config.option.basetemp)) == "bt-g1":\n'
        '        os.remove(xml)\n', encoding='utf-8', newline='\n')
    rc, text = real_run(tmp_path, suite)
    assert rc == 1 and 'g1:JUNIT_UNREADABLE' in text and 'status=FAIL' in text


# ---- C11 ----------------------------------------------------------------------------------------------------------
def tsv(path, rows, header='nodeid\tsetup\tcall\tteardown\ttotal\toutcome'):
    path.write_text('# args=[]\n' + header + '\n' + '\n'.join(rows) + '\n', encoding='utf-8', newline='\n')


def test_calibrate_sums_total_per_file_and_rounds(tmp_path):
    a = tmp_path / 'a.tsv'
    tsv(a, ['scripts/tests/test_a.py::t1\t0.1\t1.0\t0.0\t1.14\tpassed', 'scripts/tests/test_a.py::t2\t0\t2\t0\t2.0\tpassed',
            'scripts/tests/test_b.py::t1\t0\t0.5\t0\t0.5\tskipped'])
    doc = json.loads(g.calibrate([str(a)]))
    assert doc == {'schema_version': 1, 'unit': 'seconds', 'files': {'scripts/tests/test_a.py': 3.1, 'scripts/tests/test_b.py': 0.5}}


@pytest.mark.parametrize('content', ['', '# only a comment\n', 'wrong\theader\n', 'nodeid\tsetup\tcall\tteardown\ttotal\toutcome\nbad row\n',
                                     'nodeid\tsetup\tcall\tteardown\ttotal\toutcome\n'])
def test_calibrate_rejects_unusable_records(tmp_path, content):
    path = tmp_path / 'x.tsv'
    path.write_text(content, encoding='utf-8', newline='\n')
    with pytest.raises(ValueError):
        g.calibrate([str(path)])


def test_calibrate_command_prints_a_usable_table_and_fails_closed(tmp_path, capsys):
    path = tmp_path / 'x.tsv'
    tsv(path, ['scripts/tests/test_a.py::t1\t0\t1\t0\t1.0\tpassed'])
    assert g.main(['calibrate', str(path)]) == 0
    assert json.loads(capsys.readouterr().out)['files'] == {'scripts/tests/test_a.py': 1.0}
    assert g.main(['calibrate', str(tmp_path / 'missing.tsv')]) == 1


# ---- C12 (alpha batch 1: TD-104 per-file count, TD-112 phase-1 heartbeat, deadline from the start, JSON record) -----
#   C12a per-file JUnit count must equal the collected count of every file, not only the total
#        test_perfile_*
#   C12b phase 1 prints the same progress line as phase 2                          test_phase_one_*
#   C12c the deadline counts from `started` (start of verify_all), not from the grouped start   test_started_*
#   C12d a typed JSON record is written beside the raw output, only when the runner variable is set; write
#        failure prints one fixed line and never changes the gate result           test_record_*
#   C12e verify_all hands its start time to the grouped run                         test_verify_all_passes_*
def raw_env(tmp_path):
    return {g.LOCAL_GATE_ENV: str(tmp_path / 'task.raw')}


def run_env(runner, tmp_path, env, **kw):
    lines = []
    kw.setdefault('timings_path', str(tmp_path / 'none.json'))
    kw.setdefault('sequential', SEQ)
    kw.setdefault('heartbeat_sec', 0)
    rc = g.run_grouped(CMD, env, str(tmp_path), cpu_count=8, runner=runner, out=lines.append, tmp_parent=str(tmp_path), **kw)
    return rc, '\n'.join(lines)


def test_perfile_equal_total_but_wrong_files_fails_with_the_file_named(tmp_path):
    ids = nodeids()
    # g1 owns test_b and test_f: it reports all four cases under test_b, so every total still matches
    runner = FakeRunner(ids, {'g1': dict(cases=['scripts/tests/test_b.py'] * 4)})
    rc, text = run(runner, tmp_path)
    assert rc == 1 and 'collected=16 counted=16' in text and 'reasons=FILE_COUNT_MISMATCH' in text
    assert 'GATE4_FILE_MISMATCH file=scripts/tests/test_b.py expected=2 counted=4' in text
    assert 'GATE4_FILE_MISMATCH file=scripts/tests/test_f.py expected=2 counted=0' in text


def test_perfile_exact_counts_pass_and_print_no_mismatch_line(tmp_path):
    rc, text = run(FakeRunner(nodeids()), tmp_path)
    assert rc == 0 and 'GATE4_FILE_MISMATCH' not in text and 'FILE_COUNT_MISMATCH' not in text


def test_perfile_unmapped_case_fails(tmp_path):
    runner = FakeRunner(nodeids(), {'g1': dict(cases=['somewhere/else.py'] * 4, tests=4)})
    rc, text = run(runner, tmp_path)
    assert rc == 1 and 'FILE_COUNT_MISMATCH' in text


def test_perfile_unmapped_case_fails_even_when_every_file_count_is_right(tmp_path):
    own = ['scripts/tests/test_b.py'] * 2 + ['scripts/tests/test_f.py'] * 2
    runner = FakeRunner(nodeids(), {'g1': dict(cases=own + ['somewhere/else.py'], tests=4)})
    rc, text = run(runner, tmp_path)
    assert rc == 1 and 'reasons=FILE_COUNT_MISMATCH' in text and 'GATE4_FILE_MISMATCH file=UNMAPPED expected=0 counted=1' in text
    assert text.count('GATE4_FILE_MISMATCH') == 1


def test_perfile_is_not_checked_again_for_a_process_without_a_record(tmp_path):
    runner = FakeRunner(nodeids(), {'g1': dict(junit=False)})
    rc, text = run(runner, tmp_path)
    assert rc == 1 and 'g1:JUNIT_UNREADABLE' in text and 'FILE_COUNT_MISMATCH' not in text


def test_perfile_lines_are_capped(tmp_path):
    ids = ['scripts/tests/test_f%02d.py::test_0' % i for i in range(30)]
    runner = FakeRunner(ids, {n: dict(cases=['scripts/tests/other.py']) for n in ('seq', 'g1', 'g2', 'g3', 'g4')})
    rc, text = run(runner, tmp_path, sequential=())
    assert rc == 1 and text.count('GATE4_FILE_MISMATCH file=') <= g.MAX_FILE_MISMATCH_LINES + 1


def test_phase_one_prints_progress_while_the_sequential_process_runs(tmp_path):
    import threading
    release = threading.Event()
    base = FakeRunner(nodeids())

    def slow(cmd, cwd, timeout, env=None, merge_stderr=False, capture_path=None, **kw):
        if '--basetemp' in cmd and os.path.basename(cmd[cmd.index('--basetemp') + 1]) == 'bt-seq':
            release.wait(5)
        return base(cmd, cwd, timeout, env=env, merge_stderr=merge_stderr, capture_path=capture_path)

    lines = []

    def out(text):
        lines.append(text)
        if text.startswith('GATE4_PROGRESS'):
            release.set()

    rc = g.run_grouped(CMD, {}, str(tmp_path), cpu_count=8, runner=slow, out=out, tmp_parent=str(tmp_path),
                       timings_path=str(tmp_path / 'none.json'), sequential=SEQ, heartbeat_sec=0.05)
    first = next(l for l in lines if l.startswith('GATE4_PROGRESS'))
    assert rc == 0 and 'seq=' in first and 'g1=' not in first


def test_started_deadline_counts_from_the_start_of_the_caller(tmp_path):
    clock = Clock()
    clock.now = 1000.0
    runner = FakeRunner(nodeids(), clock=clock)
    rc, _ = run(runner, tmp_path, deadline_sec=1200, clock=clock, started=0.0)
    assert rc == 0
    limits = [t for c, t in runner.calls]
    assert limits[0] == pytest.approx(200.0) and all(t <= 200.0 + 1e-6 for t in limits)


def test_started_none_means_now(tmp_path):
    clock = Clock()
    clock.now = 1000.0
    runner = FakeRunner(nodeids(), clock=clock)
    rc, _ = run(runner, tmp_path, deadline_sec=1200, clock=clock, started=None)
    assert rc == 0 and max(t for c, t in runner.calls if '--collect-only' not in c) == pytest.approx(1200.0)


def test_started_past_the_deadline_runs_no_test_process_and_fails(tmp_path):
    clock = Clock()
    clock.now = 5000.0
    runner = FakeRunner(nodeids(), clock=clock)
    rc, text = run(runner, tmp_path, deadline_sec=1200, clock=clock, started=0.0)
    assert rc == 1 and 'TIMEOUT' in text
    assert not any('--basetemp' in c and '--collect-only' not in c and 'bt-' in ' '.join(c) and t > 1 for c, t in runner.calls)


def read_record(tmp_path):
    return json.loads((tmp_path / 'task.raw.gate4-groups.json').read_text(encoding='utf-8'))


def test_record_content_matches_the_result_line_and_group_lines(tmp_path):
    rc, text = run_env(FakeRunner(nodeids()), tmp_path, raw_env(tmp_path))
    rec = read_record(tmp_path)
    assert rc == 0 and rec['schema_version'] == 1 and rec['status'] == 'PASS' and rec['reasons'] == []
    assert (rec['collected'], rec['counted'], rec['passed'], rec['skipped'], rec['failures'], rec['errors']) == (16, 16, 16, 0, 0, 0)
    assert [x['name'] for x in rec['groups']] == ['seq', 'g1', 'g2', 'g3', 'g4']
    assert sum(x['tests'] for x in rec['groups']) == 16 and all(x['rc'] == 0 for x in rec['groups'])
    assert 'GATE4_GROUPS_RESULT status=PASS' in text


def test_record_of_a_failed_run_lists_the_reasons(tmp_path):
    runner = FakeRunner(nodeids(), {'g2': dict(rc=1, failures=1)})
    rc, _ = run_env(runner, tmp_path, raw_env(tmp_path))
    rec = read_record(tmp_path)
    assert rc == 1 and rec['status'] == 'FAIL' and 'g2:EXIT_1' in rec['reasons'] and rec['failures'] == 1
    assert next(x for x in rec['groups'] if x['name'] == 'g2')['rc'] == 1


def test_record_of_an_early_failure(tmp_path):
    bad = SimpleNamespace(returncode=2, timed_out=False, launch_error=None, stdout=b'boom', stderr=b'', kill_status='NOT_NEEDED')
    rc, _ = run_env(FakeRunner(nodeids(), collect_override=bad), tmp_path, raw_env(tmp_path))
    rec = read_record(tmp_path)
    assert rc == 1 and rec['status'] == 'FAIL' and rec['reasons'] == ['COLLECT_FAILED'] and rec['groups'] == []
    runner = FakeRunner(nodeids(), collect_override=SimpleNamespace(returncode=0, timed_out=False, launch_error=None,
                                                                    stdout=collect_text(nodeids(), declared=3).encode(), stderr=b'',
                                                                    kill_status='NOT_NEEDED'))
    rc, _ = run_env(runner, tmp_path, raw_env(tmp_path))
    assert rc == 1 and read_record(tmp_path)['reasons'] == ['COLLECT_COUNT_MISMATCH']


def test_record_is_not_written_without_the_runner_variable(tmp_path):
    rc, text = run_env(FakeRunner(nodeids()), tmp_path, {})
    assert rc == 0 and not list(tmp_path.glob('*.gate4-groups.json')) and 'RECORD_UNAVAILABLE' not in text


def test_record_write_failure_prints_one_fixed_line_and_keeps_the_result(tmp_path):
    env = {g.LOCAL_GATE_ENV: str(tmp_path / 'missing-dir' / 'task.raw')}
    rc, text = run_env(FakeRunner(nodeids()), tmp_path, env)
    assert rc == 0 and text.count('GATE4_GROUPS_RECORD_UNAVAILABLE') == 1 and 'GATE4_GROUPS_RESULT status=PASS' in text
    rc, text = run_env(FakeRunner(nodeids(), {'g1': dict(rc=1)}), tmp_path, env)
    assert rc == 1 and text.count('GATE4_GROUPS_RECORD_UNAVAILABLE') == 1


def test_record_real_processes_end_to_end(tmp_path):
    suite = make_suite(tmp_path)
    lines = []
    env = dict(os.environ, **raw_env(tmp_path))
    env.pop('PYTEST_ADDOPTS', None)
    rc = g.run_grouped([sys.executable, '-m', 'pytest', str(suite), '-q'], env, str(tmp_path), cpu_count=4, out=lines.append,
                       tmp_parent=str(tmp_path), timings_path=str(tmp_path / 'none.json'), sequential=(), heartbeat_sec=0)
    rec = read_record(tmp_path)
    assert rc == 0 and (rec['collected'], rec['counted'], rec['passed'], rec['skipped']) == (8, 8, 4, 4)
    assert len(rec['groups']) == 2 and not list(tmp_path.glob('*.tmp'))


def test_verify_all_passes_its_start_time_to_the_grouped_run(monkeypatch):
    seen = {}
    monkeypatch.setattr(verify_all.gate4_groups, 'run_grouped', lambda cmd, env, cwd, **kw: seen.update(kw) or 0)
    assert verify_all.run_gate(unit_gate(), {g.LOCAL_GATE_ENV: 'x.raw'}, REPO_ROOT) == 0
    assert seen == {'started': verify_all.START} and isinstance(verify_all.START, float)
