#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G1 metadata-only S1 receipt; no source content, deletion, or cross-task reads.

S1 is authoritative even when receipt creation fails. A READY receipt contains
only the task-local file size/digest and the original fixed S1 code. It is NOT
an unpushed commit bundle, Git snapshot, complete gate transcript or recovery.
"""

import hashlib
import json
import os
import re
import stat
from pathlib import Path

TASK = re.compile(r'^[A-Za-z0-9_-]+$')
SHA = re.compile(r'^[a-f0-9]{64}$')
ALLOWED_STAGES = ('focused', 'precommit', 'postcommit', 'staged')
MAX_SOURCE_BYTES = 64 * 1024 * 1024


class EvidenceError(Exception):
    """Metadata failure, never alters the original S1 cause."""


def _guarded_bytes(directory, name):
    if '/' in name or '\\' in name or name in ('.', '..'):
        raise EvidenceError('S1_EVIDENCE_SOURCE_NAME_INVALID')
    path = directory / name
    try:
        info = path.lstat()
    except OSError as exc:
        raise EvidenceError('S1_EVIDENCE_SOURCE_UNAVAILABLE') from exc
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_SOURCE_BYTES:
        raise EvidenceError('S1_EVIDENCE_SOURCE_UNSAFE')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    try:
        fd = os.open(str(path), flags)
        with os.fdopen(fd, 'rb') as f:
            opened = os.fstat(f.fileno())
            if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                    or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)):
                raise EvidenceError('S1_EVIDENCE_SOURCE_CHANGED')
            raw = f.read(MAX_SOURCE_BYTES + 1)
            after = os.fstat(f.fileno())
            if len(raw) != opened.st_size or len(raw) > MAX_SOURCE_BYTES or after.st_size != opened.st_size:
                raise EvidenceError('S1_EVIDENCE_SOURCE_CHANGED')
            return raw
    except OSError as exc:
        raise EvidenceError('S1_EVIDENCE_SOURCE_UNAVAILABLE') from exc


def _create_once(directory, name, payload):
    path = directory / name
    # Neither existing file nor symlink may be replaced. Preserve incomplete
    # artifacts for diagnosis rather than deleting or retrying them.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0)
    fd = os.open(str(path), flags, 0o600)
    with os.fdopen(fd, 'wb') as out:
        out.write(payload)
        out.flush()
        os.fsync(out.fileno())
    if _guarded_bytes(directory, name) != payload:
        raise EvidenceError('S1_EVIDENCE_WRITE_MISMATCH')
    return hashlib.sha256(payload).hexdigest()


def create_metadata(root, task_id, step, s1_code, *, validate_artifact):
    """Return safe stdout lines only after both artifacts have been read back.

    validate_artifact is the canonical task-artifact path guard supplied by Batch.
    A control must have already persisted the original halted step and code.
    """
    if not TASK.fullmatch(task_id) or not re.fullmatch(r'[a-z][a-z0-9_-]*', step):
        raise EvidenceError('S1_EVIDENCE_ID_INVALID')
    if not re.fullmatch(r'[A-Z][A-Z0-9_]*', s1_code):
        raise EvidenceError('S1_EVIDENCE_CODE_INVALID')
    root = Path(root)
    git_dir = root / '.git'
    if not git_dir.is_dir() or git_dir.is_symlink():
        raise EvidenceError('S1_EVIDENCE_DIR_INVALID')
    names = [task_id + '-prompt.txt', task_id + '-control.json']
    for stage in ALLOWED_STAGES:
        name = task_id + '-bounded-' + stage + '.txt'
        # Missing bounded captures are normal if S1 occurs before their stage.
        if os.path.lexists(git_dir / name):
            names.append(name)
    records = []
    for name in names:
        validate_artifact('.git/' + name)
        raw = _guarded_bytes(git_dir, name)
        records.append({'file': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    control = json.loads(_guarded_bytes(git_dir, task_id + '-control.json').decode('utf-8'),
                         object_pairs_hook=_reject_duplicate)
    if (not isinstance(control, dict) or control.get('task_id') != task_id
            or control.get('halted') != step + ':' + s1_code):
        raise EvidenceError('S1_EVIDENCE_CONTROL_MISMATCH')
    payload = {'schema_version': 1, 'kind': 'S1_METADATA_ONLY', 'task_id': task_id,
               'step': step, 's1_code': s1_code, 'complete_capture': False,
               'unpublished_commit_bundle': 'NOT_COLLECTED', 'git_snapshot': 'NOT_COLLECTED',
               'gate_records': 'NOT_COLLECTED', 'files': records,
               'next_step': 'USER_FORWARD_METADATA_TO_ACTIVE_AUDITOR_KEEP_ORIGINAL_S1_EVIDENCE'}
    json_raw = (json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(',', ':')) + '\n').encode('ascii')
    manifest = ''.join(r['sha256'] + '  ' + r['file'] + '\n' for r in records).encode('ascii')
    if not manifest or b'\r' in manifest or not all(SHA.fullmatch(r['sha256']) for r in records):
        raise EvidenceError('S1_EVIDENCE_MANIFEST_INVALID')
    jname = task_id + '-s1-evidence.json'
    mname = task_id + '-s1-SHA256SUMS.txt'
    for name in (jname, mname):
        validate_artifact('.git/' + name)
    jsha = _create_once(git_dir, jname, json_raw)
    msha = _create_once(git_dir, mname, manifest)
    # Final verification must bind the exact on-disk bytes of BOTH public
    # outputs to the SHA subsequently printed. A semantically equal JSON
    # document (e.g. with added whitespace) is not byte-equivalent.
    final_json = _guarded_bytes(git_dir, jname)
    final_manifest = _guarded_bytes(git_dir, mname)
    if (final_json != json_raw or hashlib.sha256(final_json).hexdigest() != jsha
            or final_manifest != manifest or hashlib.sha256(final_manifest).hexdigest() != msha):
        raise EvidenceError('S1_EVIDENCE_FINAL_BYTES_MISMATCH')
    for rec in records:
        if hashlib.sha256(_guarded_bytes(git_dir, rec['file'])).hexdigest() != rec['sha256']:
            raise EvidenceError('S1_EVIDENCE_SOURCE_CHANGED')
    return ['S1_EVIDENCE_FILE=.git/' + jname + ' sha256=' + jsha,
            'S1_SHA256SUMS_FILE=.git/' + mname + ' sha256=' + msha,
            'S1_EVIDENCE_JSON=' + json_raw.decode('ascii').rstrip('\n')]


def _reject_duplicate(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result
