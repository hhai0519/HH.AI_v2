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
3. On timeout the whole process tree is terminated (POSIX: SIGKILL to the process
   group; Windows: taskkill /T /F), the direct child is killed as a fallback and then
   reaped. The call returns within timeout + grace (plus the bounded tree-kill call)
   even when a descendant cannot be terminated. kill_status reports TREE_KILL_FAILED
   when the platform tree kill itself fails; a descendant that left the process group
   is out of reach of the group kill and is not detected.
4. Launch errors (OSError) are reported in launch_error and never raised.

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


def kill_tree(proc, grace=KILL_GRACE_SECONDS):
    """Terminate proc and its descendants. Returns True when the platform tree kill succeeded."""
    if os.name == "nt":
        try:
            done = subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=grace,
            )
            return done.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    try:
        os.killpg(proc.pid, signal.SIGKILL)
        return True
    except ProcessLookupError:
        return True
    except OSError:
        return False


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
