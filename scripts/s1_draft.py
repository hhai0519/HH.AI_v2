#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B-117 beta-2 (TD-101): runner S1 candidate draft generator.

Writes an unnumbered, read-only-to-registry schema 2 candidate entry into
`.git/<TASK_ID>-s1-draft.json` using the create-once and guarded read-back
primitives from scripts/s1_evidence.py. Never modifies tracked repository files.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from s1_evidence import EvidenceError, TASK, _create_once, _guarded_bytes


DRAFT_SCHEMA = 2
DRAFT_KIND = 'S1_REGISTRY_DRAFT'
TAIWAN_TZ = timezone(timedelta(hours=8))

STEP_RE = re.compile(r'^[a-z][a-z0-9_-]*$')
CODE_RE = re.compile(r'^(?:[A-Z][A-Z0-9_]*|UNEXPECTED_[A-Za-z_][A-Za-z0-9_]*)$')
OID40_RE = re.compile(r'^[0-9a-f]{40}$')


class DraftError(Exception):
    """Fail-closed error raised while building or persisting an S1 draft."""


def _isolated_git_env():
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
    env.update({
        'GIT_CONFIG_NOSYSTEM': '1',
        'GIT_CONFIG_GLOBAL': os.devnull,
        'GIT_OPTIONAL_LOCKS': '0',
        'GIT_TERMINAL_PROMPT': '0',
        'GIT_NO_REPLACE_OBJECTS': '1',
    })
    return env


def _git_head_oid(root: Path) -> str:
    """Resolve current HEAD read-only; returns 'UNKNOWN' when unavailable."""
    cmd = ['git', '--no-optional-locks', '-c', 'core.fsmonitor=false', 'rev-parse', 'HEAD']
    try:
        cp = subprocess.run(
            cmd,
            cwd=str(root),
            env=_isolated_git_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 'UNKNOWN'
    if cp.returncode != 0:
        return 'UNKNOWN'
    out = cp.stdout.decode('utf-8', 'replace').strip()
    return out if OID40_RE.fullmatch(out) else 'UNKNOWN'


def _normalize_taiwan_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(TAIWAN_TZ).replace(microsecond=0)
    if not isinstance(now, datetime):
        raise DraftError('S1_DRAFT_INVALID_TIME')
    if now.tzinfo is None:
        return now.replace(tzinfo=TAIWAN_TZ, microsecond=0)
    return now.astimezone(TAIWAN_TZ).replace(microsecond=0)


def build_draft(
    task_id: str,
    step: str,
    s1_code: str,
    *,
    head_oid: str,
    now: datetime | None = None,
) -> dict:
    """Build a schema-2-aligned candidate S1 draft payload (id/title/status left null)."""
    if not isinstance(task_id, str) or TASK.fullmatch(task_id) is None:
        raise DraftError('S1_DRAFT_INVALID_TASK_ID')
    if not isinstance(step, str) or STEP_RE.fullmatch(step) is None:
        raise DraftError('S1_DRAFT_INVALID_STEP')
    if not isinstance(s1_code, str) or CODE_RE.fullmatch(s1_code) is None:
        raise DraftError('S1_DRAFT_INVALID_CODE')
    if not isinstance(head_oid, str) or (head_oid != 'UNKNOWN' and OID40_RE.fullmatch(head_oid) is None):
        raise DraftError('S1_DRAFT_INVALID_HEAD')

    ts = _normalize_taiwan_now(now)
    iso_tw = ts.isoformat()
    date_str = ts.strftime('%Y-%m-%d')
    s1_line = f'S1 {s1_code} | step {step}'
    watch_code = s1_code.upper()
    evidence_str = f'{s1_line} | head={head_oid} | time={iso_tw}'

    return {
        'schema': DRAFT_SCHEMA,
        'kind': DRAFT_KIND,
        'candidateOnly': True,
        'id': None,
        'title': None,
        'status': None,
        'tasks': [task_id],
        'watch': [f'{step}:{watch_code}'],
        'class': 'UNCLASSIFIED',
        'confirmed': False,
        'by': 'runner',
        'verified': {
            'by': 'runner',
            'date': date_str,
            'basis': 'runner S1 自動草稿（僅供候選，待審查官確認並於寫狀態批正式編號入庫）',
        },
        'evidence': evidence_str,
        'evidenceDetail': {
            's1Line': s1_line,
            'step': step,
            'code': s1_code,
            'head': head_oid,
            'timestamp': iso_tw,
        },
    }


def _check_git_dir(root_path: Path) -> Path:
    git_dir = root_path / '.git'
    try:
        info = git_dir.lstat()
    except OSError as exc:
        raise DraftError('S1_DRAFT_GIT_DIR_MISSING') from exc
    reparse = bool(
        getattr(info, 'st_file_attributes', 0)
        & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
    )
    if stat.S_ISLNK(info.st_mode) or reparse or not stat.S_ISDIR(info.st_mode):
        raise DraftError('S1_DRAFT_GIT_DIR_UNSAFE')
    return git_dir


def create_s1_draft(
    root,
    task_id: str,
    step: str,
    s1_code: str,
    *,
    validate_artifact,
    head_oid: str | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Create `.git/<TASK_ID>-s1-draft.json` once and return fixed stdout lines."""
    if not callable(validate_artifact):
        raise DraftError('S1_DRAFT_VALIDATOR_MISSING')
    if not isinstance(task_id, str) or TASK.fullmatch(task_id) is None:
        raise DraftError('S1_DRAFT_INVALID_TASK_ID')

    root_path = Path(root)
    git_dir = _check_git_dir(root_path)
    fname = f'{task_id}-s1-draft.json'
    rel = f'.git/{fname}'
    validate_artifact(rel)

    resolved_head = _git_head_oid(root_path) if head_oid is None else head_oid
    payload = build_draft(task_id, step, s1_code, head_oid=resolved_head, now=now)
    raw = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')
    if b'\r' in raw:
        raise DraftError('S1_DRAFT_CRLF_UNEXPECTED')

    target_path = git_dir / fname
    try:
        target_path.lstat()
        raise DraftError('S1_DRAFT_ALREADY_EXISTS')
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise DraftError('S1_DRAFT_TARGET_UNSAFE') from exc

    try:
        sha = _create_once(git_dir, fname, raw)
        readback = _guarded_bytes(git_dir, fname)
    except FileExistsError as exc:
        raise DraftError('S1_DRAFT_ALREADY_EXISTS') from exc
    except EvidenceError as exc:
        raise DraftError(str(exc)) from exc
    except OSError as exc:
        raise DraftError('S1_DRAFT_WRITE_FAILED') from exc

    if readback != raw or hashlib.sha256(readback).hexdigest() != sha:
        raise DraftError('S1_DRAFT_READBACK_MISMATCH')

    return [f'S1_DRAFT_FILE=.git/{fname} sha256={sha} bytes={len(raw)}']
