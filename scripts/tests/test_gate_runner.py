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


def _launcher_name(func):
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None


def _launcher_timeout(call):
    keywords = [kw.value for kw in call.keywords if kw.arg == 'timeout']
    if len(keywords) == 1:
        return keywords[0]
    position = _TREE_LAUNCHERS[_launcher_name(call.func)]
    return call.args[position] if not keywords and len(call.args) > position else None


def _tree_signal_timeout_violations(source, filename):
    """Tests that start a real process tree and claim TREE_SIGNALLED need an explicit >=10 s deadline.

    AST, not regex. A claim is any 'TREE_SIGNALLED' string in the test (assert, pytest.raises match,
    variable) or KILL_TREE_SIGNALLED. Launchers: run_stage/run_bounded/run_bounded_text, timeout given
    by keyword or position. Fail closed on launcher aliases and on any unregistered helper that
    forwards its own timeout parameter to a launcher (it could hide a short deadline).
    """
    tree = ast.parse(source, filename=filename)
    failures = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            failures += [f'{filename}:{node.lineno}:launcher_alias:{a.asname}' for a in node.names
                         if a.name in _TREE_LAUNCHERS and a.asname and a.asname != a.name]
        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.Name, ast.Attribute)) \
                and _launcher_name(node.value) in _TREE_LAUNCHERS:
            failures.append(f'{filename}:{node.lineno}:launcher_alias_assign')
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call) and _launcher_name(c.func) in _TREE_LAUNCHERS]
        if not fn.name.startswith('test_'):
            params = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
            for call in calls:
                value = _launcher_timeout(call)
                if fn.name not in _TREE_LAUNCHERS and isinstance(value, ast.Name) and value.id in params:
                    failures.append(f'{filename}:{call.lineno}:{fn.name}:unregistered_launcher_wrapper')
            continue
        claims = any((isinstance(n, ast.Constant) and isinstance(n.value, str) and 'TREE_SIGNALLED' in n.value)
                     or (isinstance(n, ast.Attribute) and n.attr == 'KILL_TREE_SIGNALLED') for n in ast.walk(fn))
        if not claims:
            continue
        for call in calls:
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
