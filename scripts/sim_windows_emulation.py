#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/sim_windows_emulation.py
Pytest plugin that emulates, on Linux, Windows behaviours that a Linux test run cannot otherwise show (B-115).

Load it only in a separate auditor-side process:
  python -m pytest -p sim_windows_emulation <test paths>        (with scripts/ on PYTHONPATH)
or through:  python scripts/batch_sim.py winemu --repo <repo> -- <test paths>

Emulated behaviours:
1. Text-mode writes translate "\\n" to "\\r\\n" (pathlib.Path.write_text and open() in a text write mode, when no
   explicit newline argument is given), as Windows does by default.
2. Creating a symbolic link fails with winerror 1314 ("A required privilege is not held by the client"), as for a
   Windows account without the symlink privilege.

Not emulated (a passing run says nothing about these): file locking and "cannot delete or rename an open file",
file identity (st_ino/st_dev) semantics, case-insensitive paths, drive letters, path length and reserved names,
os.name / sys.platform and other platform checks, text writes through APIs not hooked here (io.open, os.fdopen,
codecs, tempfile text mode, subprocess pipes), console encodings, and native processes such as node or git.

This is an emulation, not native evidence: it can show that a test depends on Linux behaviour, it cannot show that
a test passes on Windows. Native Windows evidence is the USER's local Windows run (PRECOMMIT and POSTCOMMIT run the
whole scripts/tests suite there). Never load this plugin in the canonical gates.
"""

import builtins
import pathlib

WINDOWS_PRIVILEGE_NOT_HELD = 1314
_TEXT_WRITE_MODES = ('w', 'a', 'x')


class EmulatedWindowsPrivilegeError(OSError):
    """OSError carrying the Windows error code a real Windows symlink attempt reports."""
    winerror = WINDOWS_PRIVILEGE_NOT_HELD


_original_write_text = pathlib.Path.write_text
_original_open = builtins.open


def _write_text(self, data, encoding=None, errors=None, newline=None):
    # Only the platform default (newline=None) is emulated; an explicit newline argument is honoured unchanged.
    if newline is None:
        return _original_write_text(self, data, encoding=encoding, errors=errors, newline='\r\n')
    return _original_write_text(self, data, encoding=encoding, errors=errors, newline=newline)


def _open(file, mode='r', buffering=-1, encoding=None, errors=None, newline=None, closefd=True, opener=None):
    if 'b' not in mode and any(m in mode for m in _TEXT_WRITE_MODES) and newline is None:
        newline = '\r\n'
    return _original_open(file, mode, buffering, encoding, errors, newline, closefd, opener)


def _symlink_to(self, target, target_is_directory=False):
    raise EmulatedWindowsPrivilegeError(1, 'A required privilege is not held by the client')


def install():
    pathlib.Path.write_text = _write_text
    builtins.open = _open
    pathlib.Path.symlink_to = _symlink_to


def pytest_configure(config):
    install()
