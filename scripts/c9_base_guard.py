#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G1/C9: read-only, fail-closed pre-return-to-Base classifier.

This is *not* a branch-switcher. A local S1/unpushed commit, a dirty tree,
remote drift, or a detached non-Base HEAD must never be turned into a
``git reset --hard``, ``clean``, ``amend``, ``push``, or implicit checkout.
Only report READY when the active worktree is already exactly at remote Base
and clean. This prevents unnecessary detach merely for clean setup.
"""
import argparse
import os
import json
import re
import subprocess
import sys
from pathlib import Path

OID = re.compile(r'^[0-9a-f]{40}$')
BRANCH = re.compile(r'^batch/[a-z0-9][a-z0-9/_.-]{1,120}$')


def _git(repo, *args):
    try:
        p = subprocess.run(['git', '--no-optional-locks', '-C', str(repo), *args],
                           env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'}, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError('GIT_QUERY_FAILED') from None
    if p.returncode:
        raise RuntimeError('GIT_QUERY_FAILED')
    try:
        return p.stdout.decode('utf-8', 'strict').strip()
    except UnicodeDecodeError:
        raise RuntimeError('GIT_OUTPUT_INVALID') from None


def classify(repo, base):
    if not isinstance(base, str) or not OID.fullmatch(base):
        raise RuntimeError('BASE_OID_INVALID')
    repo = Path(repo)
    if not repo.is_dir() or repo.is_symlink():
        raise RuntimeError('WORKSPACE_INVALID')
    if _git(repo, 'rev-parse', '--is-shallow-repository') != 'false':
        raise RuntimeError('SHALLOW_REPO')
    head = _git(repo, 'rev-parse', '--verify', 'HEAD^{commit}')
    local_main = _git(repo, 'rev-parse', '--verify', 'refs/remotes/origin/main')
    branch = _git(repo, 'branch', '--show-current')
    dirty = _git(repo, 'status', '--porcelain=v1', '--untracked-files=all')
    if not OID.fullmatch(head) or not OID.fullmatch(local_main):
        raise RuntimeError('OID_QUERY_INVALID')
    remote = _git(repo, 'ls-remote', 'origin', 'refs/heads/main').splitlines()
    if len(remote) != 1:
        raise RuntimeError('REMOTE_MAIN_INVALID')
    parts = remote[0].split('\t')
    if len(parts) != 2 or not OID.fullmatch(parts[0]) or parts[1] != 'refs/heads/main':
        raise RuntimeError('REMOTE_MAIN_INVALID')
    # Drifting refs, even when HEAD equals the expected Base, are never accepted.
    if parts[0] != base or local_main != base:
        return {'status': 'HOLD', 'reason': 'MAIN_DRIFT', 'head': head,
                'branch': branch, 'remote_main': parts[0]}
    if dirty:
        return {'status': 'HOLD', 'reason': 'DIRTY_PRESERVE', 'head': head,
                'branch': branch, 'remote_main': parts[0]}
    if head == base:
        return {'status': 'READY', 'reason': 'AT_BASE_NO_SWITCH_NEEDED',
                'head': head, 'branch': branch, 'remote_main': base}
    # A non-Base HEAD includes unpushed/local S1 commits; do not switch or mutate.
    if branch and BRANCH.fullmatch(branch):
        return {'status': 'HOLD', 'reason': 'LOCAL_COMMIT_PRESERVE',
                'head': head, 'branch': branch, 'remote_main': base}
    return {'status': 'HOLD', 'reason': 'HEAD_NOT_BASE_PRESERVE',
            'head': head, 'branch': branch, 'remote_main': base}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only C9 safe return preflight')
    parser.add_argument('--repo', required=True)
    parser.add_argument('--base-oid', required=True)
    args = parser.parse_args(argv)
    try:
        result = classify(args.repo, args.base_oid)
    except RuntimeError as exc:
        result = {'status': 'HOLD', 'reason': str(exc)}
    # Structured, bounded output: no raw status paths/contents or credentials.
    print('C9_BASE_GUARD_JSON=' + json.dumps(result, sort_keys=True, ensure_ascii=True,
                                             separators=(',', ':')))
    return 0 if result['status'] == 'READY' else 1


if __name__ == '__main__':
    sys.exit(main())
