#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prospective CHECK16 via the actual CHECK16 parser, ancestry, and lag verdict.

The authoritative checker accepts optional planned EXEC-LOG text and exactly one
future child commit; the normal committed-state check remains unchanged.
No temporary clone or duplicate Markdown parser is needed.
"""
import os
import subprocess
from check_consistency import check_16_exec_log_cadence


class ProspectiveError(Exception):
    pass


def prospective_check16(repo, base_oid, planned_exec_log=None):
    try:
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        p = subprocess.run(['git', '-C', str(repo), 'rev-parse', '--verify', 'HEAD'],
                           capture_output=True, stdin=subprocess.DEVNULL, timeout=20, text=True, env=clean_env)
        q = subprocess.run(['git', '-C', str(repo), 'rev-parse', '--is-shallow-repository'],
                           capture_output=True, stdin=subprocess.DEVNULL, timeout=20, text=True, env=clean_env)
        if planned_exec_log is None:
            # Never trust a dirty worktree for a future check: use the exact Base blob.
            base_log = subprocess.run(['git', '-C', str(repo), 'show', base_oid + ':docs/EXEC-LOG.md'],
                                      capture_output=True, stdin=subprocess.DEVNULL, timeout=20, env=clean_env)
            if base_log.returncode:
                raise ProspectiveError('CHECK16_BASE_LOG_UNAVAILABLE')
            try:
                planned_exec_log = base_log.stdout.decode('utf-8')
            except UnicodeDecodeError:
                raise ProspectiveError('CHECK16_BASE_LOG_UNREADABLE') from None
    except (OSError, subprocess.TimeoutExpired):
        raise ProspectiveError('CHECK16_GIT_UNAVAILABLE') from None
    if p.returncode or q.returncode:
        raise ProspectiveError('CHECK16_GIT_UNAVAILABLE')
    if p.stdout.strip() != base_oid:
        raise ProspectiveError('CHECK16_BASE_DRIFT')
    if q.stdout.strip() != 'false':
        raise ProspectiveError('CHECK16_SHALLOW')
    fails, _ = check_16_exec_log_cadence(str(repo), planned_log_text=planned_exec_log,
                                        future_commits=1)
    if fails:
        raise ProspectiveError('CHECK16_PROSPECTIVE_FAIL')
    return True
