# -*- coding: utf-8 -*-
"""
scripts/tests/test_bounded_process.py

Positive and negative controls for scripts/bounded_process.py (B-107 slice 2): exit codes and
separate output capture, launch errors, whole-tree termination on timeout (including a nested
run_bounded call whose descendants run in their own process group or session), a bounded
return when a descendant survives and keeps the inherited output handle open, the POSIX
deadline, namespace and PID-identity guards, and a liveness probe that never reports a failed
query as a dead process.
"""

import os
import signal
import sys
import time
import types

import pytest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import bounded_process as bp  # noqa: E402

PY = sys.executable

# A child that starts a long-lived grandchild, records its PID and keeps running.
TREE_CHILD = (
    "import subprocess, sys, time\n"
    "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "open(sys.argv[1], 'w').write(str(g.pid))\n"
    "print('tree started', flush=True)\n"
    "time.sleep(120)\n"
)


# A child that runs a long-lived worker through a nested run_bounded call (its own group or session),
# as gate_runner -> verify_all -> pytest -> gateway referee does; the worker records its PID.
NESTED_CHILD = (
    "import sys\n"
    "sys.path.insert(0, sys.argv[2])\n"
    "from bounded_process import run_bounded\n"
    "worker = \"import os, sys, time\\nopen(sys.argv[1], 'w').write(str(os.getpid()))\\ntime.sleep(120)\\n\"\n"
    "print('nested started', flush=True)\n"
    "run_bounded([sys.executable, '-c', worker, sys.argv[1]], cwd='.', timeout=120)\n"
)


def alive(pid):
    # Shared probe: a failed platform query raises instead of reporting the process as dead.
    return bp.process_alive(pid)


def wait_dead(pid, seconds):
    deadline = time.monotonic() + seconds
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    return not alive(pid)


def test_exit_code_and_separate_streams(tmp_path):
    res = bp.run_bounded([PY, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"],
                         cwd=str(tmp_path), timeout=60)
    assert res.returncode == 3 and not res.timed_out and res.launch_error is None
    assert res.stdout.strip() == b"out" and res.stderr.strip() == b"err"
    assert res.kill_status == bp.KILL_NOT_NEEDED


def test_merged_streams(tmp_path):
    res = bp.run_bounded([PY, "-c", "import sys; print('a', flush=True); print('b', file=sys.stderr)"],
                         cwd=str(tmp_path), timeout=60, merge_stderr=True)
    assert res.returncode == 0
    assert b"a" in res.stdout and b"b" in res.stdout and res.stderr == b""


def test_stdin_is_not_inherited(tmp_path):
    res = bp.run_bounded([PY, "-c", "import sys; print(repr(sys.stdin.read()))"], cwd=str(tmp_path), timeout=60)
    assert res.returncode == 0 and res.stdout.strip() == b"''"


def test_launch_error_is_reported_not_raised(tmp_path):
    res = bp.run_bounded([os.path.join(str(tmp_path), "no-such-program")], cwd=str(tmp_path), timeout=60)
    assert res.launch_error is not None and res.returncode is None and not res.timed_out


def test_timeout_terminates_whole_tree(tmp_path):
    pid_file = tmp_path / "grandchild.pid"
    started = time.monotonic()
    # The limit leaves room for two interpreter start-ups on slow Windows hosts before the tree is terminated.
    res = bp.run_bounded([PY, "-c", TREE_CHILD, str(pid_file)], cwd=str(tmp_path), timeout=10)
    assert time.monotonic() - started < 90
    assert res.timed_out and res.returncode is None and res.kill_status == bp.KILL_TREE_SIGNALLED
    assert b"tree started" in res.stdout, "output written before the timeout must be kept"
    assert pid_file.exists(), "grandchild must have started before the timeout"
    assert wait_dead(int(pid_file.read_text()), 15), "grandchild must be terminated with the tree"


def test_timeout_terminates_nested_bounded_tree(tmp_path):
    # Counterexample for a group-only kill: the nested worker runs in its own process group or session.
    pid_file = tmp_path / "nested.pid"
    started = time.monotonic()
    res = bp.run_bounded([PY, "-c", NESTED_CHILD, str(pid_file), SCRIPTS_DIR], cwd=str(tmp_path), timeout=15)
    assert time.monotonic() - started < 90
    assert res.timed_out and res.kill_status == bp.KILL_TREE_SIGNALLED
    assert pid_file.exists(), "nested worker must have started before the timeout"
    worker = int(pid_file.read_text())
    try:
        assert wait_dead(worker, 15), "nested worker in its own group must be terminated with the tree"
    finally:
        try:
            still_running = alive(worker)
        except RuntimeError:
            still_running = True
        if still_running:
            try:
                os.kill(worker, signal.SIGKILL if hasattr(signal, "SIGKILL") else signal.SIGTERM)
            except OSError:
                pass


def test_surviving_descendant_cannot_block_return(tmp_path):
    # Counterexample: the tree kill fails and the grandchild survives with the inherited output handle.
    # A pipe-based implementation would wait for end-of-file until the grandchild exits.
    pid_file = tmp_path / "grandchild.pid"
    started = time.monotonic()
    res = bp.run_bounded([PY, "-c", TREE_CHILD, str(pid_file)], cwd=str(tmp_path), timeout=10, grace=5,
                         killer=lambda proc, grace: False)
    elapsed = time.monotonic() - started
    grandchild = int(pid_file.read_text())
    try:
        assert elapsed < 60, "return must be bounded by timeout and grace"
        assert res.timed_out and res.kill_status == bp.KILL_TREE_FAILED
        assert alive(grandchild), "the counterexample requires a surviving descendant"
    finally:
        try:
            os.kill(grandchild, signal.SIGTERM)
        except OSError:
            pass
        wait_dead(grandchild, 15)


def _fake_tasklist(returncode, stdout, timed_out=False, launch_error=None):
    def runner(cmd, cwd, timeout):
        assert cmd[:5] == ["tasklist", "/FO", "CSV", "/NH", "/FI"]
        return types.SimpleNamespace(returncode=returncode, stdout=stdout, timed_out=timed_out, launch_error=launch_error)
    return runner


def test_tasklist_query_failure_is_not_death():
    # Counterexample for the substring probe: a failed query with empty output must not mean "dead".
    for runner in (_fake_tasklist(1, b""), _fake_tasklist(None, b"", timed_out=True),
                   _fake_tasklist(None, b"", launch_error="FileNotFoundError")):
        with pytest.raises(RuntimeError):
            bp.tasklist_alive(4321, runner=runner)


def test_tasklist_requires_exact_pid_column():
    row = b'"python.exe","4321","Console","1","10,000 K"\r\n'
    assert bp.tasklist_alive(4321, runner=_fake_tasklist(0, row)) is True
    assert bp.tasklist_alive(432, runner=_fake_tasklist(0, row)) is False
    assert bp.tasklist_alive(21, runner=_fake_tasklist(0, b"INFO: No tasks are running which match the specified criteria.\r\n")) is False


posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX tree-kill internals")


@posix_only
def test_posix_discovery_past_deadline_is_reported_as_failed(tmp_path, monkeypatch):
    # Counterexample for a round-limited loop: slow discovery must not end in TREE_SIGNALLED.
    def slow(root_pid, deadline=None):
        time.sleep(0.3)
        return {}, True
    monkeypatch.setattr(bp, "posix_descendants", slow)
    res = bp.run_bounded([PY, "-c", "import time; time.sleep(60)"], cwd=str(tmp_path), timeout=2, grace=0.05)
    assert res.timed_out and res.kill_status == bp.KILL_TREE_FAILED


@posix_only
def test_posix_foreign_proc_namespace_is_reported_as_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(bp, "proc_describes_own_namespace", lambda: False)
    assert bp.posix_descendants(os.getpid()) == ({}, False)
    res = bp.run_bounded([PY, "-c", "import time; time.sleep(60)"], cwd=str(tmp_path), timeout=2)
    assert res.timed_out and res.kill_status == bp.KILL_TREE_FAILED


@posix_only
def test_posix_reused_pid_is_not_signalled(tmp_path):
    # A process whose start time differs from the one first seen stands for a reused PID.
    res_dir = tmp_path
    proc = bp.subprocess.Popen([PY, "-c", "import time; time.sleep(60)"], cwd=str(res_dir))
    try:
        start = bp._start_time(proc.pid)
        assert start is not None
        assert bp._signal_identified(proc.pid, start + 1, signal.SIGKILL) is True
        time.sleep(0.5)
        assert proc.poll() is None, "a process with another start time must not be signalled"
        assert bp._signal_identified(proc.pid, start, signal.SIGKILL) is True
        assert proc.wait(timeout=15) is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=15)
