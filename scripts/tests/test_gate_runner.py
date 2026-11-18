# -*- coding: utf-8 -*-
"""
scripts/tests/test_gate_runner.py

Negative and positive controls for scripts/gate_runner.py (B-107 canonical tooling).
"""

import ast
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import gate_runner  # noqa: E402
from test_bounded_process import wait_dead  # noqa: E402

PY = gate_runner.PY


def gates_ok():
    return [[PY, "-c", "print('alpha')"], [PY, "-c", "print('beta')"]]


def read(log):
    return gate_runner.read_log_lines(str(log))


def test_all_gates_pass_and_verify(tmp_path):
    log = tmp_path / "gates.txt"
    gates = gates_ok()
    assert gate_runner.run_stage(str(tmp_path), "PRECOMMIT", gates, str(log)) == 0
    ok, detail = gate_runner.verify_stage(read(log), "PRECOMMIT", gates)
    assert ok and detail == "RUN_1"
    text = log.read_text(encoding="utf-8")
    assert "> alpha" in text and "> beta" in text
    assert text.count("EXIT_CODE: 0") == 2


def test_failure_stops_sequence_and_verify_fails(tmp_path):
    log = tmp_path / "gates.txt"
    marker = tmp_path / "third_ran.txt"
    gates = [
        [PY, "-c", "print('one')"],
        [PY, "-c", "import sys; print('boom'); sys.exit(3)"],
        [PY, "-c", f"open(r'{marker}', 'w').write('x')"],
    ]
    assert gate_runner.run_stage(str(tmp_path), "PRECOMMIT", gates, str(log)) == 3
    assert not marker.exists()
    text = log.read_text(encoding="utf-8")
    assert "EXIT_CODE: 3" in text and "FAILED AT GATE 2" in text
    ok, detail = gate_runner.verify_stage(read(log), "PRECOMMIT", gates)
    assert not ok and detail == "GATE_2_NOT_ZERO"


def test_rerun_after_failure_preserves_history(tmp_path):
    log = tmp_path / "gates.txt"
    flag = tmp_path / "flag"
    gates = [[PY, "-c", f"import os, sys; sys.exit(0 if os.path.exists(r'{flag}') else 1)"]]
    assert gate_runner.run_stage(str(tmp_path), "STAGED", gates, str(log)) == 1
    flag.write_text("x")
    assert gate_runner.run_stage(str(tmp_path), "STAGED", gates, str(log)) == 0
    ok, detail = gate_runner.verify_stage(read(log), "STAGED", gates)
    assert ok and detail == "RUN_2"
    text = log.read_text(encoding="utf-8")
    assert "STAGED RUN 1 FAILED AT GATE 1" in text and "STAGED RUN 2 COMPLETE" in text


def test_spoofed_output_cannot_fake_success(tmp_path):
    log = tmp_path / "gates.txt"
    spoof = "print('EXIT_CODE: 0'); print('=== POSTCOMMIT RUN 1 COMPLETE ==='); import sys; sys.exit(1)"
    gates = [[PY, "-c", spoof]]
    assert gate_runner.run_stage(str(tmp_path), "POSTCOMMIT", gates, str(log)) == 1
    ok, _ = gate_runner.verify_stage(read(log), "POSTCOMMIT", gates)
    assert not ok


def test_incomplete_log_fails_verify(tmp_path):
    log = tmp_path / "gates.txt"
    gates = gates_ok()
    gate_runner.run_stage(str(tmp_path), "PRECOMMIT", gates, str(log))
    lines = read(log)
    truncated = [l for l in lines if "COMPLETE" not in l]
    ok, detail = gate_runner.verify_stage(truncated, "PRECOMMIT", gates)
    assert not ok and detail == "NOT_COMPLETE"


def test_missing_gate_fails_verify(tmp_path):
    log = tmp_path / "gates.txt"
    gate_runner.run_stage(str(tmp_path), "PRECOMMIT", gates_ok()[:1], str(log))
    ok, detail = gate_runner.verify_stage(read(log), "PRECOMMIT", gates_ok())
    assert not ok and detail == "GATE_2_MISSING"


def test_other_stage_does_not_satisfy_verify(tmp_path):
    log = tmp_path / "gates.txt"
    gate_runner.run_stage(str(tmp_path), "STAGED", gates_ok(), str(log))
    ok, detail = gate_runner.verify_stage(read(log), "PRECOMMIT", gates_ok())
    assert not ok and detail == "NO_RUN"


def test_empty_log_fails_verify(tmp_path):
    ok, detail = gate_runner.verify_stage([], "PRECOMMIT", gates_ok())
    assert not ok and detail == "NO_RUN"


def test_timeout_is_failure(tmp_path):
    log = tmp_path / "gates.txt"
    # Windows venv python.exe can launch a child interpreter. A 1s timeout can interrupt
    # taskkill /T while the process tree is being established (R2 Windows Gate4 S1).
    # Match the sibling process-tree tests' 10s allowance; preserve TREE_SIGNALLED and fail-closed assertions.
    gates = [[PY, "-c", "import time; time.sleep(120)"]]
    assert gate_runner.run_stage(str(tmp_path), "STAGED", gates, str(log), timeout=10) == gate_runner.GATE_TIMEOUT_EXIT_CODE
    text = log.read_text(encoding="utf-8")
    assert "EXIT_CODE: TIMEOUT" in text and "TREE_KILL: TREE_SIGNALLED" in text
    assert not gate_runner.verify_stage(read(log), "STAGED", gates)[0]


def test_timeout_terminates_gate_tree_that_holds_output(tmp_path):
    # Counterexample for the pipe-based runner: a grandchild keeps the inherited output handle open.
    log = tmp_path / "gates.txt"
    pid_file = tmp_path / "grandchild.pid"
    child = (
        "import subprocess, sys, time\n"
        "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        f"open(r'{pid_file}', 'w').write(str(g.pid))\n"
        "print('started', flush=True)\n"
        "time.sleep(120)\n"
    )
    gates = [[PY, "-c", child], [PY, "-c", "print('must not run')"]]
    started = time.monotonic()
    assert gate_runner.run_stage(str(tmp_path), "STAGED", gates, str(log), timeout=10) == gate_runner.GATE_TIMEOUT_EXIT_CODE
    assert time.monotonic() - started < 90
    text = log.read_text(encoding="utf-8")
    assert "> started" in text and "must not run" not in text
    assert "TREE_KILL: TREE_SIGNALLED" in text and "STAGED RUN 1 FAILED AT GATE 1" in text
    grandchild = int(pid_file.read_text())
    assert wait_dead(grandchild, 15), "grandchild must be terminated with the gate tree"
    assert not gate_runner.verify_stage(read(log), "STAGED", gates)[0]


def test_launch_failure_is_recorded(tmp_path):
    log = tmp_path / "gates.txt"
    gates = [[os.path.join(str(tmp_path), "no-such-program")]]
    assert gate_runner.run_stage(str(tmp_path), "STAGED", gates, str(log)) == 1
    assert "EXIT_CODE: LAUNCH_FAILED" in log.read_text(encoding="utf-8")


def test_stage_presets_are_canonical():
    assert [gate_runner.display(c) for c in gate_runner.STAGES["PRECOMMIT"]] == [
        "python scripts/execution_record.py verify --as-if-committed",
        "python scripts/fingerprint.py --verify",
        "python scripts/check_consistency.py --as-if-committed",
        "python scripts/verify_all.py",
        "git diff --check",
    ]
    assert [gate_runner.display(c) for c in gate_runner.STAGES["STAGED"]] == ["python scripts/secret_scan.py --staged"]
    assert [gate_runner.display(c) for c in gate_runner.STAGES["POSTCOMMIT"]] == [
        "python scripts/execution_record.py verify",
        "python scripts/check_consistency.py",
        "python scripts/fingerprint.py --verify",
        "git diff --check",
    ]


def test_cli_rejects_without_valid_task_prompt(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    proc = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, "gate_runner.py"), "verify", "--task-id", "NO-PROMPT-1",
         "--stage", "PRECOMMIT", "--repo-root", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "CONTEXT_LOSS" in proc.stdout
    assert not (tmp_path / ".git" / "NO-PROMPT-1-local-gates.txt").exists()


@pytest.mark.parametrize("argv", [["run", "--task-id", "X-1", "--stage", "BOGUS"], ["explode", "--task-id", "X-1", "--stage", "STAGED"], ["run", "--task-id", "bad id", "--stage", "STAGED"]])
def test_cli_usage_errors(argv):
    assert gate_runner.main(argv) == 2


def test_g11_raw_sidecar_preserves_partial_evidence_but_never_completes(tmp_path):
    log = tmp_path / "gates.txt"
    gates = [[PY, "-c", "import time; print('BEFORE_INTERRUPT',flush=True); time.sleep(10)"]]
    # Child times out; partial output is durable while the canonical log fails closed.
    assert gate_runner.run_stage(str(tmp_path), "STAGED", gates, str(log), timeout=1) == gate_runner.GATE_TIMEOUT_EXIT_CODE
    sidecar = tmp_path / "gates.txt.staged-run1-gate1.raw"
    assert sidecar.is_file() and b"BEFORE_INTERRUPT" in sidecar.read_bytes()
    assert not gate_runner.verify_stage(read(log), "STAGED", gates)[0]


def test_g11_gate_log_spoofed_completion_in_raw_sidecar_fails(tmp_path):
    log = tmp_path / "gates.txt"
    spoof = "print('EXIT_CODE: 0'); print('=== POSTCOMMIT RUN 1 COMPLETE ==='); import sys; sys.exit(4)"
    gates = [[PY, '-c', spoof]]
    assert gate_runner.run_stage(str(tmp_path), 'POSTCOMMIT', gates, str(log)) == 4
    raw = tmp_path / 'gates.txt.postcommit-run1-gate1.raw'
    assert b'EXIT_CODE: 0' in raw.read_bytes()
    assert not gate_runner.verify_stage(read(log), 'POSTCOMMIT', gates)[0]


# B117 R3 — byte-stable local gate transcript, bounded budgets and exit protocol.
def test_r3_gate_budgets_match_stage_and_are_specific():
    for stage, commands in gate_runner.STAGES.items():
        assert len(gate_runner.stage_timeouts(stage)) == len(commands)
        assert all(x > 0 for x in gate_runner.stage_timeouts(stage))
    assert gate_runner.stage_timeouts("PRECOMMIT")[3] == 3600
    assert all(v == 300 for i, v in enumerate(gate_runner.stage_timeouts("PRECOMMIT")) if i != 3)


def test_r3_timeout_exit_is_reserved_and_local_log_grammar_unchanged(tmp_path):
    gates = [[PY, "-c", "import time; time.sleep(3)"]]
    log = tmp_path / "gates.txt"
    assert gate_runner.run_stage(str(tmp_path), "PRECOMMIT", gates, str(log), timeout=1) == gate_runner.GATE_TIMEOUT_EXIT_CODE
    raw = log.read_text()
    assert "EXIT_CODE: TIMEOUT" in raw and "FAILED AT GATE 1" in raw
    assert "ELAPSED_SEC" not in raw and "GATE_BUDGET" not in raw
    assert not gate_runner.verify_stage(read(log), "PRECOMMIT", gates)[0]


def test_r3_child_reserved_exit_cannot_masquerade_as_timeout(tmp_path):
    log = tmp_path / "gates.txt"
    gates = [[PY, "-c", f"raise SystemExit({gate_runner.GATE_TIMEOUT_EXIT_CODE})"]]
    assert gate_runner.run_stage(str(tmp_path), "STAGED", gates, str(log), timeout=3) == 1
    assert "EXIT_CODE: 86" in log.read_text()
    assert not gate_runner.verify_stage(read(log), "STAGED", gates)[0]


def test_r3_budget_diagnostics_are_stdout_only_and_warn_at_70pct(tmp_path, monkeypatch, capsys):
    import bounded_process
    durations = iter((6.99, 7.0))
    clock = {'now': 0.0}
    def now():
        clock['now'] += next(durations)
        return clock['now']
    def fake(*args, **kwargs):
        p = kwargs['capture_path']
        open(p, 'wb').write(b'pass\n')
        return bounded_process.BoundedResult(0, False, None, b'pass\n', b'', 'NOT_NEEDED')
    monkeypatch.setattr(gate_runner, 'run_bounded', fake)
    monkeypatch.setattr(gate_runner.time, 'monotonic', now)
    log = tmp_path / 'gates.txt'
    # Each gate takes 7 seconds, i.e. exactly 70% of its 10s budget.
    gates = [[PY, '-c', 'print(1)']]
    assert gate_runner.run_stage(str(tmp_path), 'STAGED', gates, str(log), timeout=10) == 0
    out = capsys.readouterr().out
    assert 'ELAPSED_SEC 7.000' in out
    assert 'GATE_BUDGET stage=STAGED gate=1' in out
    assert 'GATE_BUDGET_WARN stage=STAGED gate=1 elapsed=7.000 limit=10 pct=70.0' in out
    assert 'GATE_BUDGET' not in log.read_text()
    assert gate_runner.verify_stage(read(log), 'STAGED', gates)[0]


def test_g3_f_warn_after_failed_gate_and_multiple_gates(tmp_path, monkeypatch, capsys):
    import bounded_process
    seconds = iter([0., 7., 10., 18.])
    monkeypatch.setattr(gate_runner.time, 'monotonic', lambda:next(seconds))
    outcomes=iter([0,3])
    def fake(*args, **kw):
        code=next(outcomes)
        open(kw['capture_path'],'wb').write(b'fixed\n')
        return bounded_process.BoundedResult(code,False,None,b'fixed\n',b'','NOT_NEEDED')
    monkeypatch.setattr(gate_runner,'run_bounded',fake)
    logfile=tmp_path/'gates.txt'
    assert gate_runner.run_stage(str(tmp_path),'PRECOMMIT',gates_ok(),str(logfile),timeout=10)==3
    out=capsys.readouterr().out
    assert 'GATE_BUDGET_WARN stage=PRECOMMIT gate=1 elapsed=7.000 limit=10 pct=70.0' in out
    assert 'GATE_BUDGET_WARN stage=PRECOMMIT gate=2 elapsed=8.000 limit=10 pct=80.0' in out
    assert not gate_runner.verify_stage(read(logfile),'PRECOMMIT',gates_ok())[0]


# G3 F R3 — prevent recurrence of short Windows process-tree termination deadlines.
_TREE_LAUNCHERS = {'run_stage': 4, 'run_bounded': 2, 'run_bounded_text': 1}  # name -> positional index of timeout
# G7-b3a2 (S1 2026-11-18, B117-G7B3A2-RECORDS-MOVE2-261118): the same recurrence through wrappers that ENCODE the
# tree-kill status as an exit code (124 = TREE_SIGNALLED, 125 = kill not confirmed) and tests that assert 124.
_ENCODED_WRAPPERS = {'default_run': 3, 'cmd': None}  # name -> positional index of timeout (None: keyword only)
_ENCODED_WRAPPER_REGISTRY = {('audit_packet.py', 'default_run'), ('batch_sim.py', 'default_run'),
                             ('draft_precheck.py', 'cmd')}  # product functions that map KILL_TREE_SIGNALLED to 124
_TIMEOUT_POSITION = {**_TREE_LAUNCHERS, **_ENCODED_WRAPPERS}


def _launcher_name(func):
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None


def _launcher_timeout(call):
    keywords = [kw.value for kw in call.keywords if kw.arg == 'timeout']
    if len(keywords) == 1:
        return keywords[0]
    position = _TIMEOUT_POSITION[_launcher_name(call.func)]
    return call.args[position] if position is not None and not keywords and len(call.args) > position else None


def _claims_encoded_124(fn):
    """True when the function asserts that a timeout ended with exit code 124 (tree kill confirmed): `rc == 124`,
    `124 == rc`, or a membership set that holds 124 but not 125."""
    for node in ast.walk(fn):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        if any(isinstance(op, ast.Eq) for op in node.ops) and \
                any(isinstance(o, ast.Constant) and o.value == 124 for o in operands):
            return True
        for container in node.comparators:
            if isinstance(container, (ast.Tuple, ast.List, ast.Set)):
                values = [e.value for e in container.elts if isinstance(e, ast.Constant)]
                if 124 in values and 125 not in values:
                    return True
    return False


def _encoded_status_functions(source, filename):
    """(filename, function) for every function that reads the tree-kill status, i.e. may turn it into a value; a read outside
    any function is reported as (filename, '<module>'). A read is the attribute or bare name KILL_TREE_SIGNALLED (also under
    an `import ... as` alias) or any string constant holding TREE_SIGNALLED (also covers getattr(..., 'KILL_TREE_SIGNALLED'))."""
    tree = ast.parse(source, filename=filename)
    names = {'KILL_TREE_SIGNALLED'}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {a.asname for a in node.names if a.name == 'KILL_TREE_SIGNALLED' and a.asname}

    def reads(n):
        return ((isinstance(n, ast.Attribute) and n.attr in names) or (isinstance(n, ast.Name) and n.id in names)
                or (isinstance(n, ast.Constant) and isinstance(n.value, str) and 'TREE_SIGNALLED' in n.value))

    def outside_functions(node):
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield child
                yield from outside_functions(child)

    found = {(filename, fn.name) for fn in ast.walk(tree) if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
             and any(reads(n) for n in ast.walk(fn))}
    if any(reads(n) for n in outside_functions(tree)):
        found.add((filename, '<module>'))
    return found


def _unregistered_encoded_wrappers(scripts_dir):
    """Product modules (bounded_process.py defines the status and is the only exclusion) whose functions read
    KILL_TREE_SIGNALLED but are not in _ENCODED_WRAPPER_REGISTRY; a new one must be registered with its timeout position."""
    found = set()
    for path in sorted(Path(scripts_dir).glob('*.py')):
        if path.name != 'bounded_process.py':
            found |= _encoded_status_functions(path.read_text(encoding='utf-8'), path.name)
    return sorted(found - _ENCODED_WRAPPER_REGISTRY)


def _tree_signal_timeout_violations(source, filename):
    """Tests that start a real process tree and claim TREE_SIGNALLED need an explicit >=10 s deadline.

    AST, not regex. A claim is any 'TREE_SIGNALLED' string in the test (assert, pytest.raises match,
    variable), KILL_TREE_SIGNALLED, or (G7-b3a2) an assertion that a timeout returned exit code 124
    (_claims_encoded_124). Launchers: run_stage/run_bounded/run_bounded_text plus the wrappers that encode the
    kill status as an exit code (_ENCODED_WRAPPERS); timeout given by keyword or position. Fail closed on
    launcher aliases and on any unregistered helper that forwards its own timeout parameter to a launcher
    (it could hide a short deadline); a helper that forwards its timeout to an encoded wrapper is accepted as a `run=` test
    double but rejected (forwarded_deadline) when a claiming test calls it. A call inside a claiming test whose timeout is not a literal >=10 fails,
    including a launch-failure call in the same test (split it into its own test).
    """
    tree = ast.parse(source, filename=filename)
    failures = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            failures += [f'{filename}:{node.lineno}:launcher_alias:{a.asname}' for a in node.names
                         if a.name in _TIMEOUT_POSITION and a.asname and a.asname != a.name]
        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.Name, ast.Attribute)) \
                and _launcher_name(node.value) in _TIMEOUT_POSITION:
            failures.append(f'{filename}:{node.lineno}:launcher_alias_assign')
    # helpers that forward their own timeout parameter to an encoded wrapper: legitimate as `run=` test doubles, but a claiming
    # test that CALLS one hides its deadline from this guard
    forwarders = set()
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and not fn.name.startswith('test_') and fn.name not in _TIMEOUT_POSITION:
            params = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
            if any(isinstance(c, ast.Call) and _launcher_name(c.func) in _ENCODED_WRAPPERS
                   and isinstance(_launcher_timeout(c), ast.Name) and _launcher_timeout(c).id in params for c in ast.walk(fn)):
                forwarders.add(fn.name)
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call) and _launcher_name(c.func) in _TREE_LAUNCHERS]
        wrapper_calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call) and _launcher_name(c.func) in _ENCODED_WRAPPERS]
        if not fn.name.startswith('test_'):
            params = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
            for call in calls:
                value = _launcher_timeout(call)
                if fn.name not in _TREE_LAUNCHERS and isinstance(value, ast.Name) and value.id in params:
                    failures.append(f'{filename}:{call.lineno}:{fn.name}:unregistered_launcher_wrapper')
            continue
        claims = any((isinstance(n, ast.Constant) and isinstance(n.value, str) and 'TREE_SIGNALLED' in n.value)
                     or (isinstance(n, ast.Attribute) and n.attr == 'KILL_TREE_SIGNALLED') for n in ast.walk(fn))
        if not (claims or _claims_encoded_124(fn)):
            continue
        failures += [f'{filename}:{c.lineno}:{fn.name}:forwarded_deadline' for c in ast.walk(fn)
                     if isinstance(c, ast.Call) and _launcher_name(c.func) in forwarders]
        for call in calls + wrapper_calls:
            value = _launcher_timeout(call)
            if not (isinstance(value, ast.Constant) and type(value.value) in (int, float) and value.value >= 10):
                failures.append(f'{filename}:{call.lineno}:{fn.name}:timeout_lt_10_or_unproven')
    return failures


def test_g3_f_r3_tree_signal_deadline_guard():
    test_root = Path(__file__).resolve().parent
    violations = []
    for script in sorted(test_root.glob('test_*.py')):
        violations.extend(_tree_signal_timeout_violations(script.read_text(encoding='utf-8'), script.name))
    assert not violations, 'TREE_SIGNALLED deadline guard: ' + '; '.join(violations)


def test_g3_f_r3_tree_signal_deadline_guard_mutations():
    specimen = ("def test_real(tmp_path):\n"
                "    assert gate_runner.run_stage(str(tmp_path),'STAGED',[],str(tmp_path/'x'),timeout=10) == 86\n"
                "    assert 'TREE_KILL: TREE_SIGNALLED' in 'x'\n")
    assert _tree_signal_timeout_violations(specimen, 'positive.py') == []
    short = specimen.replace('timeout=10', 'timeout=1')
    assert len(_tree_signal_timeout_violations(short, 'short.py')) == 1
    unknown = specimen.replace('timeout=10', 'timeout=dynamic')
    assert len(_tree_signal_timeout_violations(unknown, 'unknown.py')) == 1
    missing = specimen.replace(',timeout=10', '')
    assert len(_tree_signal_timeout_violations(missing, 'missing.py')) == 1
    positional = specimen.replace(',timeout=10', ',1')
    assert len(_tree_signal_timeout_violations(positional, 'positional.py')) == 1
    raises = ("def test_raises():\n"
              "    with pytest.raises(AssertionError, match='exceeded 2s; process tree TREE_SIGNALLED'):\n"
              "        run_bounded_text([sys.executable, '-c', 'x'], 2)\n")
    assert len(_tree_signal_timeout_violations(raises, 'raises.py')) == 1
    assert _tree_signal_timeout_violations(raises.replace('2s', '10s').replace('], 2)', '], 10)'), 'ok.py') == []
    alias = "from bounded_process import run_bounded as rb\n" + specimen
    assert any(':launcher_alias:rb' in v for v in _tree_signal_timeout_violations(alias, 'alias.py'))
    wrapper = "def _go(t):\n    return gate_runner.run_stage(1, 2, 3, 4, timeout=t)\n" + specimen
    assert any('unregistered_launcher_wrapper' in v for v in _tree_signal_timeout_violations(wrapper, 'wrap.py'))


# G7-b3a2: negative controls use the real S1 writing (test_batch_sim.py, 2026-11-18, 0.5 s deadline and `assert rc == 124`).
_S1_WRITING = ("def test_real(tmp_path):\n"
               "    rc, _ = bs.default_run([sys.executable, '-c', 'import time; time.sleep(5)'], str(tmp_path), dict(os.environ), 0.5)\n"
               "    assert rc == 124\n")


def test_g7_b3a2_encoded_exit_code_guard_catches_the_real_s1_writing_and_its_variants():
    guard = _tree_signal_timeout_violations
    found = guard(_S1_WRITING, 's1.py')
    assert len(found) == 1 and ':test_real:timeout_lt_10_or_unproven' in found[0]
    assert guard(_S1_WRITING.replace('0.5)', '10)'), 'ok10.py') == []
    assert len(guard(_S1_WRITING.replace('assert rc == 124', 'assert 124 == rc'), 'reversed.py')) == 1
    assert len(guard(_S1_WRITING.replace('assert rc == 124', 'assert rc == 124.0'), 'float124.py')) == 1
    assert len(guard(_S1_WRITING.replace('assert rc == 124', 'assert rc in (124,)'), 'only124.py')) == 1
    assert len(guard(_S1_WRITING.replace('assert rc == 124', 'assert rc in [124, 126]'), 'list.py')) == 1
    assert len(guard(_S1_WRITING.replace('assert rc == 124', 'assert rc in {124}'), 'set.py')) == 1
    assert guard(_S1_WRITING.replace('assert rc == 124', 'assert rc in (124, 125)'), 'tolerant.py') == []
    assert guard(_S1_WRITING.replace('assert rc == 124', 'assert rc == 0'), 'noclaim.py') == []
    assert len(guard(_S1_WRITING.replace('0.5)', 't)'), 'variable.py')) == 1
    assert len(guard(_S1_WRITING.replace(', dict(os.environ), 0.5)', ', dict(os.environ))'), 'missing.py')) == 1
    assert len(guard(_S1_WRITING.replace('bs.default_run', 'ap.default_run'), 'other_module.py')) == 1
    # the launch-failure call that shared the S1 test is flagged too (fail closed) until it has its own test
    both = _S1_WRITING.replace('0.5)', '10)') + "    rc, _ = bs.default_run(['missing-exe'], str(tmp_path), dict(os.environ), 5)\n"
    assert len(guard(both, 'both.py')) == 1
    assert guard(both.replace('assert rc == 124', 'assert rc == 127'), 'launch_only.py') == []
    # aliases, assignments and forwarding helpers of the encoded wrappers are as fail-closed as those of run_bounded
    assert any(':launcher_alias:dr' in v for v in guard('from batch_sim import default_run as dr\n' + _S1_WRITING, 'alias_import.py'))
    assert any(':launcher_alias_assign' in v for v in guard('run = bs.default_run\n' + _S1_WRITING, 'alias_assign.py'))
    helper = "def _run(tmp_path, t):\n    return bs.default_run(['x'], str(tmp_path), {}, t)\n"
    via_helper = "def test_real(tmp_path):\n    rc, _ = _run(tmp_path, 0.5)\n    assert rc == 124\n"
    assert any(':forwarded_deadline' in v for v in guard(helper + via_helper, 'helper.py'))
    kw_helper = "def _cmd(tmp_path, t):\n    return dp.cmd(['x'], tmp_path, timeout=t)\n"
    assert any(':forwarded_deadline' in v for v in guard(kw_helper + via_helper.replace('_run(', '_cmd('), 'kw_helper.py'))
    # a forwarding helper used as a `run=` test double, never called by a claiming test, stays accepted
    assert guard(helper + "def test_x(tmp_path):\n    assert 1 == 1\n", 'stub_helper.py') == []


def test_g7_b3a2_encoded_wrapper_guard_covers_keyword_only_cmd_and_string_claims():
    guard = _tree_signal_timeout_violations
    cmd_test = ("def test_cmd(tmp_path):\n"
                "    rc, _ = dp.cmd([sys.executable, '-c', 'import time; time.sleep(5)'], tmp_path, timeout=2)\n"
                "    assert rc == 124\n")
    assert len(guard(cmd_test, 'cmd2.py')) == 1
    assert guard(cmd_test.replace('timeout=2', 'timeout=10'), 'cmd10.py') == []
    assert len(guard(cmd_test.replace(', timeout=2', ''), 'cmdmissing.py')) == 1  # keyword-only: no timeout is unproven
    string_claim = ("def test_string(tmp_path):\n"
                    "    rc, _ = ap.default_run(['x'], str(tmp_path), None, 1)\n"
                    "    assert 'TREE_SIGNALLED' in repr(rc)\n")
    assert len(guard(string_claim, 'string.py')) == 1
    assert guard(string_claim.replace(', None, 1)', ', None, 10)'), 'string10.py') == []
    # a mocked mapping test is accepted only because its timeout literal is >=10 (the guard cannot know the call is mocked)
    fake = ("def test_mapping(monkeypatch, tmp_path):\n"
            "    fake = bp.BoundedResult(None, True, None, b'', b'', 'TREE_SIGNALLED')\n"
            "    monkeypatch.setattr(bs.bounded_process, 'run_bounded', lambda *a, **k: fake)\n"
            "    assert bs.default_run(['x'], str(tmp_path), {}, 10) == (124, b'')\n")
    assert guard(fake, 'fake.py') == []


def test_g7_b3a2_product_wrappers_that_encode_the_kill_status_are_registered(tmp_path):
    scripts_dir = Path(__file__).resolve().parent.parent
    assert _unregistered_encoded_wrappers(scripts_dir) == [], 'register the new wrapper in _ENCODED_WRAPPER_REGISTRY and _ENCODED_WRAPPERS'
    assert {name for _, name in _ENCODED_WRAPPER_REGISTRY} == set(_ENCODED_WRAPPERS)
    present = set()
    for path in scripts_dir.glob('*.py'):
        present |= _encoded_status_functions(path.read_text(encoding='utf-8'), path.name)
    assert _ENCODED_WRAPPER_REGISTRY <= present, 'a registered wrapper no longer exists or no longer maps the kill status'
    mapper = "def run_it(r):\n    return 124 if r.kill_status == bounded_process.KILL_TREE_SIGNALLED else 125\n"
    (tmp_path / 'new_tool.py').write_text(mapper, encoding='utf-8', newline='\n')
    bare = "from bounded_process import KILL_TREE_SIGNALLED\n\n\ndef bare_run(status):\n    return 124 if status == KILL_TREE_SIGNALLED else 125\n"
    (tmp_path / 'bare_tool.py').write_text(bare, encoding='utf-8', newline='\n')
    (tmp_path / 'bounded_process.py').write_text(mapper, encoding='utf-8', newline='\n')          # the defining module is the only exclusion
    (tmp_path / 'batch_sim.py').write_text(mapper.replace('run_it', 'default_run'), encoding='utf-8', newline='\n')
    assert _unregistered_encoded_wrappers(tmp_path) == [('bare_tool.py', 'bare_run'), ('new_tool.py', 'run_it')]
    (tmp_path / 'batch_sim.py').write_text(mapper.replace('run_it', 'renamed_run'), encoding='utf-8', newline='\n')
    assert _unregistered_encoded_wrappers(tmp_path) == [('bare_tool.py', 'bare_run'), ('batch_sim.py', 'renamed_run'),
                                                        ('new_tool.py', 'run_it')]
    # G7-b3a2 R3: the writings the first draft missed (import alias, string literal, getattr, module level)
    samples = {
        'alias_tool.py': "from bounded_process import KILL_TREE_SIGNALLED as K\n\n\ndef run_it(s):\n    return 124 if s == K else 125\n",
        'string_tool.py': "def run_it(r):\n    return 124 if r.kill_status == 'TREE_SIGNALLED' else 125\n",
        'getattr_tool.py': "def run_it(r):\n    return 124 if r.kill_status == getattr(bp, 'KILL_TREE_SIGNALLED') else 125\n",
        'module_tool.py': "OK = bp.KILL_TREE_SIGNALLED\n\n\ndef run_it(r):\n    return 124 if r.kill_status == OK else 125\n",
        'lambda_tool.py': "run_it = lambda r: 124 if r.kill_status == bp.KILL_TREE_SIGNALLED else 125\n",
    }
    expected = {'alias_tool.py': 'run_it', 'string_tool.py': 'run_it', 'getattr_tool.py': 'run_it', 'module_tool.py': '<module>', 'lambda_tool.py': '<module>'}
    for name, text in samples.items():
        sample_dir = tmp_path / ('d_' + name[:-3]); sample_dir.mkdir()
        (sample_dir / name).write_text(text, encoding='utf-8', newline='\n')
        assert (name, expected[name]) in _unregistered_encoded_wrappers(sample_dir), name
    clean_dir = tmp_path / 'clean'; clean_dir.mkdir()
    (clean_dir / 'clean.py').write_text('def f(r):\n    return r.kill_status\n', encoding='utf-8', newline='\n')
    assert _unregistered_encoded_wrappers(clean_dir) == []


# -- X batch: native preview quick mode (PRECOMMIT gate 4 collect-only, simulation area only) ---------------------
import hashlib  # noqa: E402
import json  # noqa: E402


def _git(*args, cwd=None):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, timeout=60)


def make_area(tmp_path, monkeypatch, task="T-QUICK", prompt=b"prompt bytes", **marker_overrides):
    """A simulation area as batch_sim lays it out: <area>/work (git, origin = <area>/origin.git), marker, env."""
    area = tmp_path / "area"
    work = area / "work"
    bare = area / "origin.git"
    work.mkdir(parents=True)
    _git("init", "-q", "--bare", str(bare))
    _git("init", "-q", str(work))
    _git("remote", "add", "origin", str(bare), cwd=str(work))
    (area / "isolated-gitconfig").write_bytes(b"")
    (work / ".git" / f"{task}-prompt.txt").write_bytes(prompt)
    marker = {"mode": "quick_gate4", "prompt_sha256": hashlib.sha256(prompt).hexdigest(), "task_id": task}
    marker.update(marker_overrides)
    (area / gate_runner.PREVIEW_QUICK_MARKER).write_text(json.dumps(marker), encoding="utf-8", newline="\n")
    monkeypatch.setenv(gate_runner.PREVIEW_ROOT_ENV, str(area))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(area / "isolated-gitconfig"))
    return area, work


def test_x_quick_gate4_is_active_only_in_a_bound_simulation_area(tmp_path, monkeypatch):
    area, work = make_area(tmp_path, monkeypatch)
    assert gate_runner.quick_gate4_active(str(work), "T-QUICK") is True


def test_x_quick_gate4_never_applies_without_the_area_the_work_tree_or_the_marker(tmp_path, monkeypatch):
    area, work = make_area(tmp_path, monkeypatch)
    # environment variable alone, or an area hint that is not this work tree: the full gate runs
    other = tmp_path / "real-workspace"
    other.mkdir()
    assert gate_runner.quick_gate4_active(str(other), "T-QUICK") is False
    monkeypatch.delenv(gate_runner.PREVIEW_ROOT_ENV)
    assert gate_runner.quick_gate4_active(str(work), "T-QUICK") is False
    monkeypatch.setenv(gate_runner.PREVIEW_ROOT_ENV, str(area))
    (area / gate_runner.PREVIEW_QUICK_MARKER).unlink()
    assert gate_runner.quick_gate4_active(str(work), "T-QUICK") is False


@pytest.mark.parametrize("case", ["task", "prompt", "mode", "extra_key", "missing_key", "not_json", "not_object",
                                  "other_prompt_file", "no_prompt_file", "git_config", "no_bare", "other_origin"])
def test_x_a_marker_that_fails_any_binding_stops_instead_of_weakening_the_gate(tmp_path, monkeypatch, case):
    area, work = make_area(tmp_path, monkeypatch)
    marker = area / gate_runner.PREVIEW_QUICK_MARKER
    good = json.loads(marker.read_text(encoding="utf-8"))
    if case == "task":
        marker.write_text(json.dumps({**good, "task_id": "T-OTHER"}), encoding="utf-8", newline="\n")
    elif case == "prompt":
        marker.write_text(json.dumps({**good, "prompt_sha256": "0" * 64}), encoding="utf-8", newline="\n")
    elif case == "mode":
        marker.write_text(json.dumps({**good, "mode": "full"}), encoding="utf-8", newline="\n")
    elif case == "extra_key":
        marker.write_text(json.dumps({**good, "skip": True}), encoding="utf-8", newline="\n")
    elif case == "missing_key":
        marker.write_text(json.dumps({k: v for k, v in good.items() if k != "mode"}), encoding="utf-8", newline="\n")
    elif case == "not_json":
        marker.write_bytes(b"\xff not json")
    elif case == "not_object":
        marker.write_text("[]", encoding="utf-8", newline="\n")
    elif case == "other_prompt_file":
        (work / ".git" / "T-QUICK-prompt.txt").write_bytes(b"another prompt")
    elif case == "no_prompt_file":
        (work / ".git" / "T-QUICK-prompt.txt").unlink()
    elif case == "git_config":
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "elsewhere"))
    elif case == "no_bare":
        (area / "origin.git" / "HEAD").unlink()
        for child in sorted((area / "origin.git").rglob("*"), reverse=True):
            child.rmdir() if child.is_dir() else child.unlink()
        (area / "origin.git").rmdir()
    elif case == "other_origin":
        _git("remote", "set-url", "origin", str(tmp_path / "somewhere-else.git"), cwd=str(work))
    with pytest.raises(gate_runner.PreviewQuickInvalid):
        gate_runner.quick_gate4_active(str(work), "T-QUICK")


def test_x_a_marker_that_is_a_link_or_not_a_regular_file_is_an_identity_failure(tmp_path, monkeypatch):
    area, work = make_area(tmp_path, monkeypatch)
    marker = area / gate_runner.PREVIEW_QUICK_MARKER
    real_islink = os.path.islink
    monkeypatch.setattr(gate_runner.os.path, "islink", lambda p: True if str(p) == str(marker) else real_islink(p))
    with pytest.raises(gate_runner.PreviewQuickInvalid, match="IDENTITY"):
        gate_runner.quick_gate4_active(str(work), "T-QUICK")
    monkeypatch.setattr(gate_runner.os.path, "islink", real_islink)
    marker.unlink()
    marker.mkdir()
    with pytest.raises(gate_runner.PreviewQuickInvalid, match="IDENTITY"):
        gate_runner.quick_gate4_active(str(work), "T-QUICK")


def test_x_a_second_origin_url_is_refused(tmp_path, monkeypatch):
    area, work = make_area(tmp_path, monkeypatch)
    _git("remote", "set-url", "--add", "origin", str(tmp_path / "second.git"), cwd=str(work))
    with pytest.raises(gate_runner.PreviewQuickInvalid):
        gate_runner.quick_gate4_active(str(work), "T-QUICK")


def test_x_stage_gates_replace_only_precommit_gate_4_and_never_the_canonical_table(tmp_path):
    before = [list(g) for g in gate_runner.STAGES["PRECOMMIT"]]
    full = gate_runner.stage_gates("PRECOMMIT", False)
    quick = gate_runner.stage_gates("PRECOMMIT", True)
    assert full == before and gate_runner.STAGES["PRECOMMIT"] == before
    assert [i for i, (a, b) in enumerate(zip(full, quick)) if a != b] == [3]
    assert quick[3] == [PY, "scripts/verify_all.py", "--gate4-collect-only"]
    for stage in ("STAGED", "POSTCOMMIT"):
        with pytest.raises(ValueError, match="QUICK_GATE4_NOT_APPLICABLE"):
            gate_runner.stage_gates(stage, True)
        assert gate_runner.stage_gates(stage, False) == [list(g) for g in gate_runner.STAGES[stage]]


def test_x_a_quick_log_never_verifies_as_the_full_gate_run_and_the_reverse(tmp_path):
    full = gate_runner.stage_gates("PRECOMMIT", False)
    quick = gate_runner.stage_gates("PRECOMMIT", True)
    # Same positions and exit codes, different command text in the headers: log what each run would record.
    log = tmp_path / "quick.txt"
    lines = [gate_runner.run_header("PRECOMMIT", 1)]
    for idx, cmd in enumerate(quick, 1):
        lines += [gate_runner.gate_header("PRECOMMIT", 1, idx, cmd), "EXIT_CODE: 0"]
    lines.append(gate_runner.complete_marker("PRECOMMIT", 1))
    log.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    assert gate_runner.verify_stage(read(log), "PRECOMMIT", quick) == (True, "RUN_1")
    ok, detail = gate_runner.verify_stage(read(log), "PRECOMMIT", full)
    assert not ok and detail == "GATE_4_MISSING"


def _main_in_area(tmp_path, monkeypatch, capsys, action):
    area, work = make_area(tmp_path, monkeypatch)
    monkeypatch.setattr(gate_runner, "verify_current_task_prompt", lambda *a, **k: (True, "", "", []))
    monkeypatch.setattr(gate_runner, "verify_task_artifact_path", lambda *a, **k: (True, ""))
    seen = {}

    def fake_run_stage(root, stage, gates, log_path, timeout=None, durations_prefix=None):
        seen["gates"] = gates
        return 0

    monkeypatch.setattr(gate_runner, "run_stage", fake_run_stage)
    code = gate_runner.main([action, "--task-id", "T-QUICK", "--stage", "PRECOMMIT", "--repo-root", str(work)])
    return code, seen, capsys.readouterr().out


def test_x_main_runs_gate_4_collect_only_in_the_area_and_says_so(tmp_path, monkeypatch, capsys):
    code, seen, out = _main_in_area(tmp_path, monkeypatch, capsys, "run")
    assert code == 0
    assert seen["gates"][3] == [PY, "scripts/verify_all.py", "--gate4-collect-only"]
    assert "GATE_RUNNER PREVIEW_QUICK gate4=collect_only" in out


def test_x_main_outside_an_area_runs_the_canonical_gates(tmp_path, monkeypatch, capsys):
    area, work = make_area(tmp_path, monkeypatch)
    monkeypatch.delenv(gate_runner.PREVIEW_ROOT_ENV)
    monkeypatch.setattr(gate_runner, "verify_current_task_prompt", lambda *a, **k: (True, "", "", []))
    monkeypatch.setattr(gate_runner, "verify_task_artifact_path", lambda *a, **k: (True, ""))
    seen = {}
    monkeypatch.setattr(gate_runner, "run_stage", lambda root, stage, gates, log, **k: seen.update(gates=gates) or 0)
    assert gate_runner.main(["run", "--task-id", "T-QUICK", "--stage", "PRECOMMIT", "--repo-root", str(work)]) == 0
    assert seen["gates"] == [list(g) for g in gate_runner.STAGES["PRECOMMIT"]]
    assert "PREVIEW_QUICK" not in capsys.readouterr().out


def test_x_main_stops_with_s1_when_the_marker_does_not_bind(tmp_path, monkeypatch, capsys):
    area, work = make_area(tmp_path, monkeypatch, prompt_sha256="0" * 64)
    monkeypatch.setattr(gate_runner, "verify_current_task_prompt", lambda *a, **k: (True, "", "", []))
    monkeypatch.setattr(gate_runner, "verify_task_artifact_path", lambda *a, **k: (True, ""))
    ran = []
    monkeypatch.setattr(gate_runner, "run_stage", lambda *a, **k: ran.append(1) or 0)
    assert gate_runner.main(["run", "--task-id", "T-QUICK", "--stage", "PRECOMMIT", "--repo-root", str(work)]) == 1
    assert not ran and "S1 PREVIEW_QUICK_INVALID MARKER_BINDING" in capsys.readouterr().out


def test_x_the_marker_does_not_change_the_other_stages(tmp_path, monkeypatch, capsys):
    area, work = make_area(tmp_path, monkeypatch)
    monkeypatch.setattr(gate_runner, "verify_current_task_prompt", lambda *a, **k: (True, "", "", []))
    monkeypatch.setattr(gate_runner, "verify_task_artifact_path", lambda *a, **k: (True, ""))
    seen = {}
    monkeypatch.setattr(gate_runner, "run_stage", lambda root, stage, gates, log, **k: seen.update(gates=gates) or 0)
    for stage in ("STAGED", "POSTCOMMIT"):
        assert gate_runner.main(["run", "--task-id", "T-QUICK", "--stage", stage, "--repo-root", str(work)]) == 0
        assert seen["gates"] == [list(g) for g in gate_runner.STAGES[stage]]
