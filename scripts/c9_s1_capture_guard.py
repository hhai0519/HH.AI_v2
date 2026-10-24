#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C9 R3: bounded, read-only verification of a task-specific S1 capture.

NEVER authorizes restore, checkout, reset, branch deletion, or cleanup.
Metadata-only receipts are NOT backups. Even a correctly bound full archive is
only a snapshot; restoration and cross-session safety require separate gates.
"""
import argparse
import hashlib
import io
import json
import re
import os
import subprocess
import stat
import sys
import zipfile
from pathlib import Path

from c9_local_history_guard import inventory
from s1_evidence import TASK, _guarded_bytes, _reject_duplicate
from s1_full_capture import _guarded_large_bytes, MAX_TOTAL

OID = re.compile(r'^[a-f0-9]{40}$')
HEX64 = re.compile(r'^[a-f0-9]{64}$')
MAX_FILES = 86  # S1 producer: <=80 sources + 4 snapshot parts + bundle + manifest
MAX_MEMBER = 64 * 1024 * 1024
MAX_BUNDLE_MEMBER = 128 * 1024 * 1024


class CaptureGuardError(Exception):
    pass


def _regular_file(dirpath, name, limit):
    """Use bounded guarded read and reject Windows reparse points pre-open."""
    file = dirpath / name
    try:
        meta = file.lstat()
    except FileNotFoundError:
        raise CaptureGuardError('CAPTURE_MISSING') from None
    except OSError:
        # B-119 G1: permission or I/O failure is not evidence of absence; both stop.
        raise CaptureGuardError('CAPTURE_STAT_FAILED') from None
    if (not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1 or meta.st_size > limit
            or (getattr(meta, 'st_file_attributes', 0) & 0x400)):
        raise CaptureGuardError('CAPTURE_UNSAFE')
    try:
        raw = (_guarded_bytes(dirpath, name) if limit <= 64 * 1024 * 1024
               else _guarded_large_bytes(dirpath, name, limit))
    except Exception:
        raise CaptureGuardError('CAPTURE_UNREADABLE') from None
    if len(raw) != meta.st_size:
        raise CaptureGuardError('CAPTURE_CHANGED')
    return raw


def _json_exact(raw):
    try:
        x = json.loads(raw.decode('utf-8', 'strict'), object_pairs_hook=_reject_duplicate)
    except (UnicodeError, ValueError, TypeError):
        raise CaptureGuardError('CAPTURE_CARD_INVALID') from None
    if not isinstance(x, dict):
        raise CaptureGuardError('CAPTURE_CARD_INVALID')
    return x


def validate_capture(repo, task, base):
    if (not isinstance(task, str) or not TASK.fullmatch(task) or not OID.fullmatch(base)):
        raise CaptureGuardError('CAPTURE_ARGUMENT_INVALID')
    git_dir = Path(repo) / '.git'
    if not git_dir.is_dir() or git_dir.is_symlink():
        raise CaptureGuardError('CAPTURE_GITDIR_INVALID')
    card_name = task + '-s1-full-capture.json'
    raw_card = _regular_file(git_dir, card_name, 64 * 1024 * 1024)
    c = _json_exact(raw_card)
    archive_name = task + '-s1-full-capture.zip'
    bundle_name = task + '-s1-unpublished.bundle'
    if (c.get('schema_version') != 1 or c.get('kind') != 'S1_FULL_CAPTURE'
            or c.get('complete_capture') is not True or c.get('task_id') != task
            or c.get('base_oid') != base or c.get('archive_file') != archive_name
            or c.get('bundle_file') != bundle_name
            or not isinstance(c.get('step'), str) or not re.fullmatch(r'[a-z][a-z0-9_-]*', c['step'])
            or not isinstance(c.get('s1_code'), str) or not re.fullmatch(r'[A-Z][A-Z0-9_]*', c['s1_code'])
            or c.get('gate_records') != 'ARCHIVED'
            or c.get('git_snapshot') != 'ARCHIVED'
            or c.get('publication_status') != 'NOT_CHECKED_NO_REMOTE_TRAFFIC'
            or not isinstance(c.get('archive_sha256'), str) or not HEX64.fullmatch(c['archive_sha256'])
            or not isinstance(c.get('manifest_sha256'), str) or not HEX64.fullmatch(c['manifest_sha256'])
            or not isinstance(c.get('head_oid'), str) or not OID.fullmatch(c['head_oid'])
            or c['head_oid'] == base or type(c.get('archive_member_count')) is not int
            or not 3 <= c['archive_member_count'] <= MAX_FILES):
        raise CaptureGuardError('CAPTURE_CARD_MISMATCH')
    archive = _regular_file(git_dir, archive_name, MAX_TOTAL)
    if hashlib.sha256(archive).hexdigest() != c['archive_sha256']:
        raise CaptureGuardError('CAPTURE_ARCHIVE_SHA_MISMATCH')
    bundle = _regular_file(git_dir, bundle_name, MAX_TOTAL)
    # Validate the Git bundle's actual HEAD advertisement, not merely a ZIP digest.
    try:
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
        env.update({'GIT_OPTIONAL_LOCKS':'0', 'GIT_TERMINAL_PROMPT':'0',
                    'GIT_CONFIG_NOSYSTEM':'1', 'GIT_CONFIG_GLOBAL':os.devnull})
        cp = subprocess.run(['git', '--no-optional-locks', 'bundle', 'list-heads',
                             str(git_dir / bundle_name)], cwd=str(repo), env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=30, check=False)
        if (cp.returncode != 0 or cp.stdout.replace(b'\r\n', b'\n') !=
                (c['head_oid'] + ' HEAD\n').encode('ascii')):
            raise CaptureGuardError('CAPTURE_BUNDLE_HEAD_MISMATCH')
    except (OSError, subprocess.TimeoutExpired):
        raise CaptureGuardError('CAPTURE_BUNDLE_UNREADABLE') from None
    # Match the external captured bundle to its internal archive member.
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            infos = z.infolist()
            names = [v.filename for v in infos]
            if (len(names) != c['archive_member_count'] or len(set(names)) != len(names)
                    or names != sorted(names) or 'SHA256SUMS.txt' not in names
                    or bundle_name not in names or len(names) > MAX_FILES):
                raise CaptureGuardError('CAPTURE_ZIP_INVENTORY_INVALID')
            total = 0
            files = {}
            for m in infos:
                name = m.filename
                if (name not in ('SHA256SUMS.txt', 'git-snapshot.json', 'git-tracked-status.z',
                                 'git-index.diff', 'git-worktree.diff')
                        and not name.startswith(task + '-')):
                    raise CaptureGuardError('CAPTURE_ZIP_MEMBER_INVALID')
                if ('/' in name or '\\' in name or '\x00' in name or name in ('.', '..')
                        or not m.filename.isascii() or (m.external_attr >> 16) & 0o170000 == 0o120000
                        or m.file_size > (MAX_BUNDLE_MEMBER if name == bundle_name else MAX_MEMBER)):
                    raise CaptureGuardError('CAPTURE_ZIP_MEMBER_UNSAFE')
                total += m.file_size
                if total > MAX_TOTAL:
                    raise CaptureGuardError('CAPTURE_ZIP_TOO_LARGE')
                files[name] = z.read(m)
            if z.testzip() is not None:
                raise CaptureGuardError('CAPTURE_ZIP_CRC_INVALID')
    except (zipfile.BadZipFile, RuntimeError, OSError, ValueError, OverflowError):
        raise CaptureGuardError('CAPTURE_ZIP_UNREADABLE') from None
    if files[bundle_name] != bundle:
        raise CaptureGuardError('CAPTURE_BUNDLE_DRIFT')
    expected = ''.join(hashlib.sha256(files[n]).hexdigest() + '  ' + n + '\n'
                       for n in sorted(files) if n != 'SHA256SUMS.txt').encode('ascii')
    if (files['SHA256SUMS.txt'] != expected or
            hashlib.sha256(expected).hexdigest() != c['manifest_sha256']):
        raise CaptureGuardError('CAPTURE_MANIFEST_INVALID')
    # Validate the embedded metadata source independently; no external trust.
    metadata_name = task + '-s1-evidence.json'
    if metadata_name not in files:
        raise CaptureGuardError('CAPTURE_METADATA_MISSING')
    metadata = _json_exact(files[metadata_name])
    if (metadata.get('kind') != 'S1_METADATA_ONLY' or metadata.get('complete_capture') is not False
            or metadata.get('task_id') != task):
        raise CaptureGuardError('CAPTURE_METADATA_INVALID')
    # Cross-bind metadata to the original S1 control, source files and manifest.
    if (metadata.get('step') != c.get('step') or
            metadata.get('s1_code') != c.get('s1_code') or
            metadata.get('schema_version') != 1):
        raise CaptureGuardError('CAPTURE_METADATA_DRIFT')
    control_name = task + '-control.json'
    if control_name not in files:
        raise CaptureGuardError('CAPTURE_CONTROL_MISSING')
    control = _json_exact(files[control_name])
    if (control.get('task_id') != task or
            control.get('halted') != c.get('step', '') + ':' + c.get('s1_code', '')):
        raise CaptureGuardError('CAPTURE_CONTROL_MISMATCH')
    source_entries = metadata.get('files')
    if not isinstance(source_entries, list) or not 2 <= len(source_entries) <= 10:
        raise CaptureGuardError('CAPTURE_S1_FILES_INVALID')
    seen = set()
    for item in source_entries:
        if (not isinstance(item, dict) or set(item) != {'file', 'bytes', 'sha256'}
                or not isinstance(item['file'], str) or
                item['file'] not in files or item['file'] in seen or
                item['file'] not in (task + '-prompt.txt', task + '-control.json') and
                not re.fullmatch(re.escape(task) + r'-bounded-(focused|precommit|staged|postcommit)\.txt', item['file'])
                or type(item['bytes']) is not int or item['bytes'] != len(files[item['file']])
                or not isinstance(item['sha256'], str) or
                hashlib.sha256(files[item['file']]).hexdigest() != item['sha256']):
            raise CaptureGuardError('CAPTURE_S1_SOURCE_DRIFT')
        seen.add(item['file'])
    if not {task + '-prompt.txt', task + '-control.json'}.issubset(seen):
        raise CaptureGuardError('CAPTURE_S1_SOURCE_MISSING')
    meta_manifest_name = task + '-s1-SHA256SUMS.txt'
    if meta_manifest_name not in files or files[meta_manifest_name] != ''.join(
            item['sha256'] + '  ' + item['file'] + '\n' for item in source_entries).encode('ascii'):
        raise CaptureGuardError('CAPTURE_S1_MANIFEST_MISMATCH')
    snapshot_name = 'git-snapshot.json'
    if snapshot_name not in files:
        raise CaptureGuardError('CAPTURE_GIT_SNAPSHOT_MISSING')
    snap = _json_exact(files[snapshot_name])
    if (snap.get('kind') != 'S1_GIT_SNAPSHOT' or snap.get('task_id') != task
            or snap.get('head_oid') != c['head_oid'] or
            snap.get('base_oid') != base or snap.get('unpublished_commit_available') is not True):
        raise CaptureGuardError('CAPTURE_GIT_SNAPSHOT_MISMATCH')
    # Reject changed active artifacts, including a replaced card after read.
    if (_regular_file(git_dir, card_name, 64 * 1024 * 1024) != raw_card
            or _regular_file(git_dir, archive_name, MAX_TOTAL) != archive
            or _regular_file(git_dir, bundle_name, MAX_TOTAL) != bundle):
        raise CaptureGuardError('CAPTURE_FINAL_DRIFT')
    return {'status': 'SNAPSHOT_VERIFIED_ONLY', 'kind': 'S1_FULL_CAPTURE',
            'task_id': task, 'base_oid': base, 'capture_head_oid': c['head_oid'],
            'archive_sha256': c['archive_sha256'], 'member_count': len(names),
            'restoration_authorized': False, 'deletion_authorized': False,
            'publication_checked': False}


def assess(repo, task, base):
    # A complete byte-wise copy is needed but not sufficient for recovery.
    verified = validate_capture(repo, task, base)
    current = inventory(repo, base)
    if current['status'] != 'READY':
        return {'status': 'HOLD', 'reason': 'BASE_OR_LOCAL_HISTORY_' + current['reason'],
                'capture': 'SNAPSHOT_VERIFIED_ONLY', 'authorization': 'NONE'}
    return {'status': 'SNAPSHOT_VERIFIED_ONLY', 'reason': 'CREDENTIAL_NOT_RECOVERY_PERMIT',
            'archive_sha256': verified['archive_sha256'], 'authorization': 'NONE',
            'restoration_authorized': False, 'deletion_authorized': False}


def main(argv=None):
    p = argparse.ArgumentParser(description='Read-only C9 S1 artifact credential audit')
    p.add_argument('--repo', required=True)
    p.add_argument('--base-oid', required=True)
    p.add_argument('--s1-task-id', required=True)
    a = p.parse_args(argv)
    try:
        r = assess(a.repo, a.s1_task_id, a.base_oid)
    except CaptureGuardError as e:
        r = {'status': 'HOLD', 'reason': str(e), 'authorization': 'NONE'}
    except Exception:
        r = {'status': 'HOLD', 'reason': 'CAPTURE_QUERY_FAILED', 'authorization': 'NONE'}
    print('C9_S1_CREDENTIAL_JSON=' + json.dumps(r, ensure_ascii=True, sort_keys=True,
                                                 separators=(',', ':')))
    # Deliberate: without separate restoration approval, never exit READY/0.
    return 1


if __name__ == '__main__':
    sys.exit(main())
