#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/bounded_process.py

Bounded child-process execution for gates and test referees (B-107 canonical tooling, slice 2).

  run_bounded(cmd, cwd, timeout, env=None, merge_stderr=False) -> BoundedResult
  process_alive(pid) -> bool

Contract:
1. The child starts in its own process group (POSIX: new session; Windows:
   CREATE_NEW_PROCESS_GROUP) with stdin connected to DEVNULL.
2. stdout and stderr are written to anonymous temporary files, never to pipes, so a
   descendant that keeps an inherited output handle open cannot make the caller wait
   for end-of-file. The operating system removes the files when they are closed.
3. On timeout the process tree is terminated by parent-child relationship, which also
   reaches descendants that run in their own process group or session (for example a
   nested run_bounded call):
   - Windows: taskkill /T /F on the child, limited to `grace` seconds.
   - POSIX: the descendants of the child are found through /proc and stopped with
     SIGSTOP until no new descendant appears, then the child's process group and every
     found process receive SIGKILL. Discovery and freezing stop at a deadline of `grace`
     seconds. A found process is signalled only while its /proc start time is unchanged,
     through a pidfd where the platform offers one, so a reused PID is not signalled.
     Discovery is skipped (group kill only, reported as failed) when /proc does not
     describe the caller's own PID namespace or is unavailable.
   The direct child is then killed as a fallback and the call tries to reap it.
4. Waiting is bounded: after the timeout the call spends at most about `grace` seconds
   in the tree kill and at most `grace` seconds trying to reap the direct child; if the
   child is not reaped in that time, returncode stays None. Reading the captured output
   afterwards is a local file read and is not time-limited.
5. kill_status is TREE_SIGNALLED only when the platform tree kill succeeded and, on
   POSIX, discovery was complete before the deadline; otherwise TREE_KILL_FAILED. It is
   not proof that every descendant has exited: a descendant whose parent chain to the
   child was already broken (for example one re-parented after its parent exited) is
   not reachable.
6. Launch errors (OSError) are reported in launch_error and never raised.
7. process_alive treats zombies as dead and raises RuntimeError when the platform query
   itself fails, so a failed query is never reported as "not alive".

Limitation (registered under B-107): descendants left behind by a child that exits
normally before the timeout are not swept.
"""

import csv
import io
import os
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Optional

KILL_GRACE_SECONDS = 30
KILL_NOT_NEEDED = "NOT_NEEDED"
KILL_TREE_SIGNALLED = "TREE_SIGNALLED"
KILL_TREE_FAILED = "TREE_KILL_FAILED"
PROBE_TIMEOUT_SECONDS = 60


@dataclass
class BoundedResult:
    returncode: Optional[int]
    timed_out: bool
    launch_error: Optional[str]
    stdout: bytes
    stderr: bytes
    kill_status: str


def _group_kwargs():
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


# ---------------------------------------------------------------------------
# POSIX process table through /proc
# ---------------------------------------------------------------------------

def _stat_fields(pid):
    """Fields after the command name of /proc/<pid>/stat; raises OSError when unreadable or gone."""
    with open("/proc/" + str(pid) + "/stat", "rb") as handle:
        return handle.read().rsplit(b")", 1)[1].split()


def proc_describes_own_namespace():
    try:
        return os.readlink("/proc/self") == str(os.getpid())
    except OSError:
        return False


def posix_descendants(root_pid, deadline=None):
    """Return ({pid: start_time}, complete) for the descendants of root_pid found through /proc.

    complete is False when /proc is unavailable or describes another PID namespace, when a
    process entry could not be read for a reason other than the process having exited, or
    when the deadline (time.monotonic value) passed during the scan.
    """
    if not proc_describes_own_namespace():
        return {}, False
    try:
        names = os.listdir("/proc")
    except OSError:
        return {}, False
    complete = True
    parent_of, start_of = {}, {}
    for name in names:
        if deadline is not None and time.monotonic() > deadline:
            return {}, False
        if not name.isdigit():
            continue
        try:
            fields = _stat_fields(name)
            parent_of[int(name)] = int(fields[1])
            start_of[int(name)] = int(fields[19])
        except (FileNotFoundError, ProcessLookupError):
            continue
        except (OSError, IndexError, ValueError):
            complete = False
    children = {}
    for pid, ppid in parent_of.items():
        children.setdefault(ppid, []).append(pid)
    found, stack = {}, [root_pid]
    while stack:
        for pid in children.get(stack.pop(), []):
            if pid not in found:
                found[pid] = start_of[pid]
                stack.append(pid)
    return found, complete


def _start_time(pid):
    try:
        return int(_stat_fields(pid)[19])
    except (OSError, IndexError, ValueError):
        return None


def _signal_identified(pid, start, sig):
    """Signal pid only while it is still the process first seen (same start time).

    Returns True when the signal was delivered or the process is already gone or replaced.
    """
    fd = None
    if hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
        try:
            fd = os.pidfd_open(pid)
        except ProcessLookupError:
            return True
        except OSError:
            fd = None
    try:
        if _start_time(pid) != start:
            return True
        if fd is not None:
            signal.pidfd_send_signal(fd, sig)
        else:
            os.kill(pid, sig)
        return True
    except ProcessLookupError:
        return True
    except OSError:
        return False
    finally:
        if fd is not None:
            os.close(fd)


def _signal_child(pid, sig):
    # The direct child is not reaped yet, so its PID cannot be reused.
    try:
        os.kill(pid, sig)
        return True
    except ProcessLookupError:
        return True
    except OSError:
        return False


def _kill_posix_tree(root_pid, grace):
    deadline = time.monotonic() + grace
    ok = _signal_child(root_pid, signal.SIGSTOP)
    stopped = {}
    while True:
        found, complete = posix_descendants(root_pid, deadline)
        fresh = {pid: start for pid, start in found.items() if pid not in stopped}
        for pid, start in fresh.items():
            ok = _signal_identified(pid, start, signal.SIGSTOP) and ok
            stopped[pid] = start
        if not complete or time.monotonic() > deadline:
            ok = False
            break
        if not fresh:
            break
    try:
        os.killpg(root_pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        ok = False
    for pid in sorted(stopped):
        ok = _signal_identified(pid, stopped[pid], signal.SIGKILL) and ok
    return _signal_child(root_pid, signal.SIGKILL) and ok


def kill_tree(proc, grace=KILL_GRACE_SECONDS):
    """Terminate proc and its descendants. Returns True only when the tree kill is known complete."""
    if os.name == "nt":
        try:
            done = subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=grace,
            )
            return done.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    return _kill_posix_tree(proc.pid, grace)


# ---------------------------------------------------------------------------
# Bounded execution
# ---------------------------------------------------------------------------

def _read_all(handle):
    handle.flush()
    handle.seek(0)
    return handle.read()


def run_bounded(cmd, cwd, timeout, env=None, merge_stderr=False, grace=KILL_GRACE_SECONDS, killer=kill_tree):
    out = tempfile.TemporaryFile()
    err = out if merge_stderr else tempfile.TemporaryFile()
    try:
        try:
            proc = subprocess.Popen(
                list(cmd), cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err, **_group_kwargs()
            )
        except OSError as exc:
            return BoundedResult(None, False, type(exc).__name__, b"", b"", KILL_NOT_NEEDED)
        try:
            code = proc.wait(timeout=timeout)
            timed_out = False
            kill_status = KILL_NOT_NEEDED
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_status = KILL_TREE_SIGNALLED if killer(proc, grace) else KILL_TREE_FAILED
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                pass
            code = None
        stdout = _read_all(out)
        stderr = b"" if merge_stderr else _read_all(err)
        return BoundedResult(code, timed_out, None, stdout, stderr, kill_status)
    finally:
        out.close()
        if err is not out:
            err.close()


# ---------------------------------------------------------------------------
# Liveness probe for tests and evidence
# ---------------------------------------------------------------------------

def tasklist_alive(pid, runner=run_bounded):
    """Windows liveness through tasklist CSV output; raises RuntimeError when the query fails."""
    res = runner(["tasklist", "/FO", "CSV", "/NH", "/FI", "PID eq " + str(pid)], cwd=None, timeout=PROBE_TIMEOUT_SECONDS)
    if res.launch_error is not None or res.timed_out or res.returncode != 0:
        raise RuntimeError("tasklist query failed for PID " + str(pid))
    text = res.stdout.decode("utf-8", errors="replace")
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 2 and row[1].strip() == str(pid):
            return True
    return False


def process_alive(pid):
    """True while pid exists and is not a zombie; raises RuntimeError when the state cannot be determined."""
    if os.name == "nt":
        return tasklist_alive(pid)
    if os.path.isdir("/proc") and proc_describes_own_namespace():
        try:
            return _stat_fields(pid)[0] != b"Z"
        except (FileNotFoundError, ProcessLookupError):
            return False
        except (OSError, IndexError) as exc:
            raise RuntimeError("process state unreadable for PID " + str(pid)) from exc
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
