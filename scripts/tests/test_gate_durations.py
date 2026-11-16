# -*- coding: utf-8 -*-
"""
scripts/tests/test_gate_durations.py

G5-a: positive and negative controls for the runner-only per-test duration recorder
(scripts/gate_durations.py) and its wiring in scripts/gate_runner.py.
"""

import os
from pathlib import Path
import subprocess
import sys

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REPO_ROOT = os.path.dirname(SCRIPTS_DIR)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import gate_durations  # noqa: E402
import gate_runner  # noqa: E402

PY = gate_runner.PY

SAMPLE = '''
import os
import pytest

def test_pass():
    assert True

def test_fail():
    assert False

@pytest.mark.skip(reason="sample")
def test_skip():
    pass

def test_child_environment_is_clean():
    assert "HHAI_GATE_DURATIONS_PREFIX" not in os.environ
    assert "scripts.gate_durations" not in os.environ.get("PYTEST_ADDOPTS", "")
'''


def _env(prefix=None, addopts=gate_durations.ADDOPT):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", gate_durations.PREFIX_ENV)}
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if addopts:
        env["PYTEST_ADDOPTS"] = addopts
    if prefix is not None:
        env[gate_durations.PREFIX_ENV] = prefix
    return env


def _run_sample(tmp_path, env, body=SAMPLE):
    tests = tmp_path / "sample"
    tests.mkdir()
    (tests / "test_sample.py").write_text(body, encoding="utf-8", newline="\n")
    # Same interpreter resolution as gate_runner.resolve_command: never depend on PATH's "python".
    args = gate_runner.resolve_command([PY, "-m", "pytest", str(tests), "-q", "-p", "no:cacheprovider"])
    cp = subprocess.run(args, cwd=REPO_ROOT, env=env, stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    return cp, tests


def _records(tmp_path):
    return sorted(tmp_path.glob("raw.durations-*.tsv"))


def test_records_every_test_and_keeps_the_exit_status(tmp_path):
    cp, _ = _run_sample(tmp_path, _env(prefix=str(tmp_path / "raw")))
    assert cp.returncode == 1  # the failing sample test still fails the session
    files = _records(tmp_path)
    assert len(files) == 1 and not list(tmp_path.glob("*.tmp"))
    lines = files[0].read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("# args=") and lines[1] == "nodeid\tsetup\tcall\tteardown\ttotal\toutcome"
    outcome = {line.split("\t")[0].rsplit("::", 1)[1]: line.split("\t")[-1] for line in lines[2:]}
    assert outcome == {"test_pass": "passed", "test_fail": "failed", "test_skip": "skipped",
                       "test_child_environment_is_clean": "passed"}


def test_all_passing_session_stays_zero(tmp_path):
    body = "def test_ok():\n    assert True\n"
    cp, _ = _run_sample(tmp_path, _env(prefix=str(tmp_path / "raw")), body)
    assert cp.returncode == 0
    assert len(_records(tmp_path)) == 1


def test_without_prefix_nothing_is_written(tmp_path):
    cp, _ = _run_sample(tmp_path, _env(prefix=None))
    assert cp.returncode == 1
    assert _records(tmp_path) == [] and list(tmp_path.glob("*.tsv")) == []


def test_unwritable_record_is_reported_and_never_changes_the_result(tmp_path):
    # Fault injection: the prefix points into a directory that does not exist.
    body = "def test_ok():\n    assert True\n"
    cp, _ = _run_sample(tmp_path, _env(prefix=str(tmp_path / "missing" / "raw")), body)
    assert cp.returncode == 0
    assert b"GATE_DURATIONS_UNAVAILABLE FileNotFoundError" in cp.stderr
    assert not (tmp_path / "missing").exists()


def test_two_sessions_with_one_prefix_never_overwrite_each_other():
    assert gate_durations.session_tag(["a", "-q"]) != gate_durations.session_tag(["b", "-q"])
    assert gate_durations.session_tag(["a", "-q"]) == gate_durations.session_tag(["a", "-q"])


def test_scrub_keeps_other_addopts(monkeypatch):
    monkeypatch.setenv("PYTEST_ADDOPTS", "-x " + gate_durations.ADDOPT + " -q")
    monkeypatch.setenv(gate_durations.PREFIX_ENV, "/p")
    assert gate_durations._scrub_environment() == "/p"
    assert os.environ["PYTEST_ADDOPTS"] == "-x -q"
    assert gate_durations.PREFIX_ENV not in os.environ
    monkeypatch.setenv("PYTEST_ADDOPTS", gate_durations.ADDOPT)
    assert gate_durations._scrub_environment() is None
    assert "PYTEST_ADDOPTS" not in os.environ


def _probe_gate():
    code = ("import os; print('PREFIX=' + os.environ.get('HHAI_GATE_DURATIONS_PREFIX', '<none>')); "
            "print('ADDOPTS=' + os.environ.get('PYTEST_ADDOPTS', '<none>'))")
    return [[PY, "-c", code]]


def test_run_stage_passes_the_raw_sidecar_as_prefix_only_when_asked(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.delenv(gate_durations.PREFIX_ENV, raising=False)
    log = tmp_path / "local-gates.txt"
    assert gate_runner.run_stage(str(tmp_path), "PRECOMMIT", _probe_gate(), str(log), durations_prefix=str(log)) == 0
    text = log.read_text(encoding="utf-8")
    assert "PREFIX=" + str(log) + ".precommit-run1-gate1.raw" in text
    assert "ADDOPTS=" + gate_durations.ADDOPT in text
    assert gate_runner.DURATIONS_ADDOPT == gate_durations.ADDOPT
    assert gate_runner.DURATIONS_PREFIX_ENV == gate_durations.PREFIX_ENV
    # Default: no recording, and the runner's own environment is never modified.
    log2 = tmp_path / "plain-gates.txt"
    assert gate_runner.run_stage(str(tmp_path), "PRECOMMIT", _probe_gate(), str(log2)) == 0
    text2 = log2.read_text(encoding="utf-8")
    assert "PREFIX=<none>" in text2 and "ADDOPTS=<none>" in text2
    assert "PYTEST_ADDOPTS" not in os.environ


def test_gate_runner_cli_run_enables_recording_at_the_task_log():
    src = Path(SCRIPTS_DIR, "gate_runner.py").read_text(encoding="utf-8")
    assert src.count("run_stage(root, args.stage, gates, log_path, durations_prefix=log_path)") == 1
