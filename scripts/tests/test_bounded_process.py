# -*- coding: utf-8 -*-
"""
scripts/tests/test_bounded_process.py

Positive and negative controls for scripts/bounded_process.py (B-107 slice 2): exit codes and
separate output capture, launch errors, whole-tree termination on timeout, and a bounded return
when a descendant survives and keeps the inherited output handle open.
"""

import os
import signal
import subprocess
import sys
import time

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


def alive(pid):
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", "PID eq " + str(pid), "/NH"], capture_output=True).stdout
        return str(pid) in out.decode("utf-8", "replace")
    stat = "/proc/" + str(pid) + "/stat"
    if os.path.exists("/proc"):
        try:
            with open(stat, encoding="utf-8") as f:
                return f.read().rsplit(")", 1)[1].split()[0] != "Z"
        except OSError:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


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
