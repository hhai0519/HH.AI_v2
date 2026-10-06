# -*- coding: utf-8 -*-
"""
scripts/tests/test_gate_runner.py

Negative and positive controls for scripts/gate_runner.py (B-107 canonical tooling).
"""

import os
import subprocess
import sys

import pytest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import gate_runner  # noqa: E402

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
    gates = [[PY, "-c", "import time; time.sleep(5)"]]
    assert gate_runner.run_stage(str(tmp_path), "STAGED", gates, str(log), timeout=1) == 1
    assert "EXIT_CODE: TIMEOUT" in log.read_text(encoding="utf-8")
    assert not gate_runner.verify_stage(read(log), "STAGED", gates)[0]


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
        "python scripts/verify_all.py",
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
