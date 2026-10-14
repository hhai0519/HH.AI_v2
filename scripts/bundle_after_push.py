#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B-118: bounded, post-push only, locally constructed ref-whitelist bundle."""
import os
import re
import shutil
import stat
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
TAIPEI = timezone(timedelta(hours=8))

OID = re.compile(r'^[0-9a-f]{40}$')
BRANCH = re.compile(r'^batch/[a-z0-9][a-z0-9._-]*$')
TRACKING = re.compile(r'^refs/remotes/origin/(?:batch/[a-z0-9][a-z0-9._-]*|main|[a-z0-9][a-z0-9._/-]*)$')

class BundleFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def git(root, *args, timeout=120):
    env = dict(os.environ)
    for name in list(env):
        if name.upper().startswith('GIT_'):
            del env[name]
    env.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'Never'})
    try:
        r = subprocess.run(['git', *args], cwd=root, env=env, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise BundleFailure('GIT_UNAVAILABLE') from None
    if r.returncode != 0 or (not r.stdout and args[0] in ('for-each-ref',)):
        raise BundleFailure('GIT_NONZERO')
    return r.stdout.decode('utf-8', 'strict').strip()


def safe_directory(path):
    """No reparse/symlink ancestor, no redirected Downloads, no new directories."""
    if not path.is_dir() or os.path.realpath(path) != os.path.abspath(path):
        raise BundleFailure('DOWNLOADS_UNSAFE')
    for ancestor in (path, *path.parents):
        st = ancestor.lstat()
        if stat.S_ISLNK(st.st_mode) or (getattr(st, 'st_file_attributes', 0) & 0x400):
            raise BundleFailure('DOWNLOADS_UNSAFE')


def allowed_refs(root, branch, base, head):
    text = git(root, 'for-each-ref', '--format=%(refname) %(objectname)', 'refs/remotes/origin')
    found = {}
    for line in text.splitlines():
        # Git's origin/HEAD is a symbolic convenience pointer, never a bundle ref.
        if line.startswith('refs/remotes/origin/HEAD '):
            continue
        parts = line.split()
        if len(parts) != 2 or not TRACKING.fullmatch(parts[0]) or not OID.fullmatch(parts[1]):
            raise BundleFailure('REF_NOT_WHITELISTED')
        if parts[0] in found:
            raise BundleFailure('REF_DUPLICATE')
        found[parts[0]] = parts[1]
    if found.get('refs/remotes/origin/main') != base:
        raise BundleFailure('TRACKING_MAIN_DRIFT')
    candidate = 'refs/remotes/origin/' + branch
    existing = found.get(candidate)
    if existing is not None and existing != head:
        raise BundleFailure('TRACKING_CANDIDATE_DRIFT')
    if existing is None:
        # Create precisely the proven remote-tracking ref, no network or foreign refs.
        git(root, 'update-ref', candidate, head, '0'*40)
        found[candidate] = head
    return dict(sorted(found.items()))


def create_bundle(root, branch, base, head, downloads=None, now=None, task_id=None):
    if not BRANCH.fullmatch(branch) or not OID.fullmatch(base) or not OID.fullmatch(head) or base == head:
        raise BundleFailure('ARGUMENT_INVALID')
    root = str(Path(root).resolve(strict=True))
    downloads = Path(downloads) if downloads is not None else Path.home() / 'Downloads'
    safe_directory(downloads)
    timestamp = (now or datetime.now(TAIPEI)).astimezone(TAIPEI)
    name = 'HH.AI_v2-' + timestamp.strftime('%Y%m%d-%H%M%S') + '-' + base[:7] + '.bundle'
    if not name.isascii():
        raise BundleFailure('NAME_INVALID')
    target = downloads / name
    if os.path.lexists(target):
        raise BundleFailure('BUNDLE_EXISTS')
    refs = allowed_refs(root, branch, base, head)
    if not task_id or not re.fullmatch(r'[A-Za-z0-9_-]+', task_id):
        raise BundleFailure('TASK_ID_INVALID')
    temp = Path(root) / '.git' / (task_id + '-bundle.tmp')
    if os.path.lexists(temp):
        raise BundleFailure('TEMP_EXISTS')
    # Task-local .git output is retained for forensic examination. No delete or overwrite.
    try:
        git(root, 'bundle', 'create', str(temp), *refs, timeout=300)
        verify = git(root, 'bundle', 'verify', str(temp), timeout=300)
        if not verify and not temp.is_file():
            raise BundleFailure('VERIFY_EMPTY')
        heads = git(root, 'bundle', 'list-heads', str(temp), timeout=300)
        observed = {}
        for line in heads.splitlines():
            parts = line.split()
            if len(parts) != 2 or not OID.fullmatch(parts[0]) or parts[1] in observed:
                raise BundleFailure('LIST_HEADS_INVALID')
            observed[parts[1]] = parts[0]
        if observed != refs:
            raise BundleFailure('BUNDLE_REFS_MISMATCH')
        with temp.open('rb') as src, target.open('xb') as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
        if not target.is_file() or target.stat().st_size != temp.stat().st_size:
            raise BundleFailure('COPY_MISMATCH')
        # Verify actual new file rather than trusting temporary artifact.
        real_heads = git(root, 'bundle', 'list-heads', str(target), timeout=300)
        if real_heads != heads:
            raise BundleFailure('COPY_VERIFY_FAILED')
        return str(target)
    except FileExistsError:
        raise BundleFailure('BUNDLE_EXISTS') from None
    except (OSError, UnicodeError, ValueError):
        raise BundleFailure('BUNDLE_IO_FAILED') from None
