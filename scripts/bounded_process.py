#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/bounded_process.py

Bounded child-process execution for gates and test referees (B-107 canonical tooling, slice 2).

  run_bounded(cmd, cwd, timeout, env=None, merge_stderr=False) -> BoundedResult

Contract:
1. The child starts in its own process group (POSIX: new session; Windows:
   CREATE_NEW_PROCESS_GROUP) with stdin connected to DEVNULL.
2. stdout and stderr are written to anonymous temporary files, never to pipes, so a
   descendant that keeps an inherited output handle open cannot make the caller wait
   for end-of-file. The operating system removes the files when they are closed.
3. On timeout the process tree is terminated by parent-child relationship, which also
   reaches descendants that run in their own process group or session (for example a
   nested run_bounded call):
   - Windows: taskkill /T /F on the child.
   - POSIX: the live descendants of the child are found through /proc, stopped with
     SIGSTOP until no new descendant appears, then the child's process group and every
     found process receive SIGKILL. Without /proc only the process group is reached.
   The direct child is then killed as a fallback and reaped.
4. Waiting is bounded: after the timeout the call spends at most `grace` seconds in the
   tree-kill call and at most `grace` seconds reaping the direct child; if the child is
   still not reaped, returncode stays None. Reading the captured output afterwards is a
   local file read and is not time-limited.
5. kill_status reports whether the platform kill calls succeeded (TREE_SIGNALLED) or
   failed (TREE_KILL_FAILED). It is not proof that every descendant has exited: a
   descendant whose parent chain to the child was already broken (for example one
   re-parented after its parent exited) is not reachable.
6. Launch errors (OSError) are reported in launch_error and never raised.

Limitation (registered under B-107): descendants left behind by a child that exits
normally before the timeout are not swept.
"""

import os
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Optional

KILL_GRACE_SECONDS = 30
KILL_NOT_NEEDED = "NOT_NEEDED"
KILL_TREE_SIGNALLED = "TREE_SIGNALLED"
KILL_TREE_FAILED = "TREE_KILL_FAILED"
FREEZE_ROUNDS = 20


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


def posix_descendants(root_pid):
    """Return the PIDs of all descendants of root_pid found through /proc ([] without /proc)."""
    try:
        names = os.listdir("/proc")
    except OSError:
        return []
    children = {}
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open("/proc/" + name + "/stat", "rb") as handle:
                fields = handle.read().rsplit(b")", 1)[1].split()
            ppid = int(fields[1])
        except (OSError, IndexError, ValueError):
            continue
        children.setdefault(ppid, []).append(int(name))
    found, stack = [], [root_pid]
    while stack:
        for pid in children.get(stack.pop(), []):
            if pid not in found:
                found.append(pid)
                stack.append(pid)
    return found


def _signal(pid, sig):
    try:
        os.kill(pid, sig)
        return True
    except ProcessLookupError:
        return True
    except OSError:
        return False


def _kill_posix_tree(root_pid):
    ok = _signal(root_pid, signal.SIGSTOP)
    stopped = set()
    for _ in range(FREEZE_ROUNDS):
        fresh = [pid for pid in posix_descendants(root_pid) if pid not in stopped]
        if not fresh:
            break
        for pid in fresh:
            ok = _signal(pid, signal.SIGSTOP) and ok
            stopped.add(pid)
    else:
        ok = False
    try:
        os.killpg(root_pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        ok = False
    for pid in sorted(stopped) + [root_pid]:
        ok = _signal(pid, signal.SIGKILL) and ok
    return ok


def kill_tree(proc, grace=KILL_GRACE_SECONDS):
    """Terminate proc and its descendants. Returns True when the platform kill calls succeeded."""
    if os.name == "nt":
        try:
            done = subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=grace,
            )
            return done.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    return _kill_posix_tree(proc.pid)


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
