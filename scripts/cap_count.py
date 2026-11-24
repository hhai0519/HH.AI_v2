#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/cap_count.py

TD-008 read-only counter shared between Governance Freeze D6 and Cap Condition (2).
Never writes, commits, creates git locks, or fails CI due to unrecorded S1 drift
between repo and the local Dashboard. Fails closed (exit 1) only on structural,
encoding (BOM/CR), missing anchor, or git integrity errors.
"""

import argparse
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass


TASKBOARD_REL = 'docs/TASKBOARD.md'
AUDIT_LOG_REL = 'docs/AUDIT-LOG.md'
EXEC_LOG_REL = 'docs/EXEC-LOG.md'
REGISTRY_REL = 'docs/governance/s1-registry.json'
EXEC_RECORD_REL = 'docs/governance/execution-record.json'

PRODUCT_PREFIXES = ('runtime/', 'skills/', 'SOP/', 'shared/', 'templates/')
CAP2_ANCHOR_TASK = 'B117-G5-BRANCH-MATCH-R4-261115'
CAP2_TARGET = 20

OID40_RE = re.compile(r'^[0-9a-f]{40}$')
HEX_RE = re.compile(r'^[0-9a-f]{7,40}$')
TASK_ID_RE = re.compile(r'\b((?:PROMOTE-|READONLY-)?B[0-9]+[A-Za-z0-9]*-[A-Za-z0-9-]+-[0-9]{6})\b')
TASK_DATE_RE = re.compile(r'-([0-9]{6})$')
FREEZE_LINE_RE = re.compile(
    r'^\*\*治理凍結\*\*：USER 2026-11-20 決定；連續無 S1 批數 (\d+)/(\d+)；'
    r'最後歸零：([A-Za-z0-9_-]+)（([^）]+)）；起算：([A-Za-z0-9_-]+)（不含）$',
    re.M,
)
CAP_RESET_RE = re.compile(
    r'\bCAP_RESET=(ERROR_INTO_MAIN|S1|MANUAL_REMEDIATION|PATCH_BATCH):([A-Za-z0-9_-]+)\b'
)
TABLE_HEADER_PREFIX = '| 批次 commit |'


class CapCountError(Exception):
    """Fixed error code on structural, encoding, anchor, or git failures."""

    def __init__(self, code: str, detail: str = ''):
        self.code = code
        self.detail = detail
        super().__init__(f'{code}: {detail}' if detail else code)


def _isolated_git_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
    env.update({
        'GIT_CONFIG_NOSYSTEM': '1',
        'GIT_CONFIG_GLOBAL': os.devnull,
        'GIT_OPTIONAL_LOCKS': '0',
        'GIT_TERMINAL_PROMPT': '0',
        'GIT_NO_REPLACE_OBJECTS': '1',
    })
    return env


def _git_bytes(root_dir: str, *args: str, error_code: str = 'GIT_FAILED') -> bytes:
    import subprocess
    cmd = [
        'git', '--no-optional-locks', '-c', 'core.fsmonitor=false',
        '-c', 'diff.external=', '-c', 'core.pager=cat', *args,
    ]
    try:
        cp = subprocess.run(
            cmd,
            cwd=root_dir,
            env=_isolated_git_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CapCountError(error_code, type(exc).__name__) from exc
    if cp.returncode != 0:
        err = cp.stderr.decode('utf-8', 'replace').strip()
        raise CapCountError(error_code, err or f'rc={cp.returncode}')
    return cp.stdout


def _git_text(root_dir: str, *args: str, error_code: str = 'GIT_FAILED') -> str:
    return _git_bytes(root_dir, *args, error_code=error_code).decode('utf-8', 'strict')


def _decode_strict_lf(raw: bytes, label: str) -> str:
    if raw.startswith(b'\xef\xbb\xbf'):
        raise CapCountError('DOC_BOM', label)
    if b'\r' in raw:
        raise CapCountError('DOC_CR', label)
    try:
        return raw.decode('utf-8', 'strict')
    except UnicodeDecodeError as exc:
        raise CapCountError('DOC_INVALID_UTF8', f'{label}: {exc}') from exc


def _read_doc_lf(root_dir: str, rel: str, *, ref_oid: str, use_git: bool, required: bool = True) -> str | None:
    if use_git:
        try:
            raw = _git_bytes(root_dir, 'show', f'{ref_oid}:{rel}', error_code='DOC_GIT_READ_FAILED')
        except CapCountError:
            if not required:
                return None
            raise
        return _decode_strict_lf(raw, f'{ref_oid[:7]}:{rel}')

    path = os.path.join(root_dir, *rel.split('/'))
    if not os.path.exists(path):
        if not required:
            return None
        raise CapCountError('DOC_MISSING', rel)
    try:
        with open(path, 'rb') as handle:
            raw = handle.read()
    except OSError as exc:
        raise CapCountError('DOC_READ_FAILED', f'{rel}: {type(exc).__name__}') from exc
    return _decode_strict_lf(raw, rel)


def _resolve_ref_oid(root_dir: str, ref: str) -> str:
    if not isinstance(ref, str) or not ref.strip():
        raise CapCountError('REF_INVALID', repr(ref))
    out = _git_text(root_dir, 'rev-parse', '--verify', '-q', f'{ref}^{{commit}}', error_code='REF_UNRESOLVED').strip()
    if not OID40_RE.fullmatch(out):
        raise CapCountError('REF_INVALID', out)
    return out


def _first_parent_chain(root_dir: str, ref_oid: str) -> list[str]:
    out = _git_text(root_dir, 'rev-list', '--first-parent', '--reverse', ref_oid, error_code='GIT_HISTORY_FAILED')
    return [line.strip() for line in out.splitlines() if line.strip()]


def _commit_task_id(root_dir: str, oid: str) -> str | None:
    try:
        raw = _git_bytes(root_dir, 'show', f'{oid}:{EXEC_RECORD_REL}', error_code='EXEC_RECORD_ABSENT')
        data = json.loads(_decode_strict_lf(raw, f'{oid[:7]}:{EXEC_RECORD_REL}'))
        tid = data.get('task_id')
        if isinstance(tid, str) and tid.strip():
            return tid.strip()
    except (CapCountError, json.JSONDecodeError, ValueError):
        pass
    return None


def _split_md_row(line: str) -> list[str]:
    stripped = line.strip()
    if not (stripped.startswith('|') and stripped.endswith('|')):
        return []
    return [cell.strip() for cell in stripped[1:-1].split('|')]


def parse_audit_log_rows(text: str) -> list[dict]:
    """Parse main table rows of docs/AUDIT-LOG.md, stopping before archive sections."""
    lines = text.split('\n')
    in_table = False
    seen_sep = False
    rows = []
    for idx, line in enumerate(lines, 1):
        if not in_table:
            if line.startswith(TABLE_HEADER_PREFIX):
                in_table = True
            continue
        if not seen_sep:
            if line.startswith('|---'):
                seen_sep = True
                continue
            raise CapCountError('AUDIT_LOG_MALFORMED', f'missing separator at line {idx}')
        if line.startswith('## '):
            break
        if not line.strip():
            continue
        if not line.startswith('|'):
            continue
        cells = _split_md_row(line)
        if len(cells) < 4:
            raise CapCountError('AUDIT_LOG_MALFORMED', f'line {idx} has {len(cells)} cols')
        col1, col2, col3, col4 = cells[0], cells[1], cells[2], cells[3]
        col5 = cells[4] if len(cells) >= 5 else ''
        if col1 == 'BOOTSTRAP':
            continue
        if not HEX_RE.fullmatch(col1):
            raise CapCountError('AUDIT_LOG_OID_INVALID', f'line {idx}: {col1!r}')
        m_tid = TASK_ID_RE.search(col3)
        task_id = m_tid.group(1) if m_tid else None
        rows.append({
            'line_no': idx,
            'oid': col1,
            'date': col2,
            'scope': col3,
            'result': col4,
            'notes': col5,
            'raw': line,
            'task_id': task_id,
            'is_postmain_verified': 'POST-MAIN VERIFIED' in col4,
            'is_readonly': ('READONLY-' in col3) or ('只讀批' in col3) or ('READ_ONLY' in col3),
        })
    if not rows:
        raise CapCountError('AUDIT_LOG_EMPTY', 'no commit rows parsed')
    return rows


def parse_exec_log_rows(text: str) -> list[dict]:
    """Parse rows of docs/EXEC-LOG.md as (base_oid, date, scope, raw)."""
    rows = []
    in_table = False
    seen_sep = False
    for line in text.split('\n'):
        if not in_table:
            if line.startswith(TABLE_HEADER_PREFIX):
                in_table = True
            continue
        if not seen_sep:
            if line.startswith('|---'):
                seen_sep = True
            continue
        if not line.startswith('|'):
            continue
        cells = _split_md_row(line)
        if len(cells) >= 3 and HEX_RE.fullmatch(cells[0]):
            rows.append({'base_oid': cells[0], 'date': cells[1], 'scope': cells[2], 'raw': line})
    return rows


def parse_freeze_header(taskboard_text: str) -> dict:
    """Parse exact `**治理凍結**：...` line from docs/TASKBOARD.md."""
    matches = FREEZE_LINE_RE.findall(taskboard_text)
    if len(matches) != 1:
        raise CapCountError('FREEZE_LINE_INVALID', f'expected 1 freeze line, found {len(matches)}')
    declared_s, target_s, last_reset, last_reason, start_after = matches[0]
    declared = int(declared_s)
    target = int(target_s)
    if target <= 0 or declared < 0:
        raise CapCountError('FREEZE_LINE_VALUES_INVALID', f'{declared}/{target}')
    return {
        'declared': declared,
        'target': target,
        'last_reset': last_reset,
        'last_reset_reason': last_reason,
        'start_after': start_after,
    }


def _load_s1_registry_info(root_dir: str, *, ref_oid: str, use_git: bool) -> tuple[set[str], dict[str, str]]:
    text = _read_doc_lf(root_dir, REGISTRY_REL, ref_oid=ref_oid, use_git=use_git, required=False)
    if text is None:
        return set(), {}
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CapCountError('REGISTRY_INVALID_JSON', str(exc)) from exc
    if not isinstance(doc, dict) or not isinstance(doc.get('causes'), list):
        raise CapCountError('REGISTRY_STRUCTURE_INVALID')

    s1_tasks = set()
    fixed_commits = {}
    for cause in doc['causes']:
        if not isinstance(cause, dict):
            continue
        fc = cause.get('fixedCommit')
        tasks = cause.get('tasks') or []
        if not isinstance(tasks, list):
            continue
        for tid in tasks:
            if not isinstance(tid, str) or not tid:
                continue
            s1_tasks.add(tid)
            if tid.startswith('PROMOTE-'):
                s1_tasks.add(tid[len('PROMOTE-'):])
            else:
                s1_tasks.add('PROMOTE-' + tid)
            if isinstance(fc, str) and HEX_RE.fullmatch(fc):
                fixed_commits[tid] = fc
    return s1_tasks, fixed_commits


def _commit_parent_oid(root_dir: str, oid: str) -> str | None:
    try:
        out = _git_text(root_dir, 'rev-parse', '--verify', '-q', f'{oid}^', error_code='GIT_PARENT_FAILED').strip()
        return out if OID40_RE.fullmatch(out) else None
    except CapCountError:
        return None


def _oid_matches(candidate_oid: str, target_oid: str) -> bool:
    return candidate_oid.startswith(target_oid) or target_oid.startswith(candidate_oid)


def _resolve_d6_start_idx(
    root_dir: str,
    rows: list[dict],
    start_after: str,
    fixed_commits: dict[str, str],
    exec_text: str | None,
) -> int:
    # 1. Exact task_id match in AUDIT-LOG -> start at i + 1
    for idx, row in enumerate(rows):
        if row['task_id'] == start_after:
            return idx + 1

    # 2. s1-registry.json fixedCommit match -> start inclusive at fixedCommit row
    fc = fixed_commits.get(start_after)
    if fc:
        for idx, row in enumerate(rows):
            if _oid_matches(row['oid'], fc):
                return idx

    # 3. EXEC-LOG earliest row mentioning start_after -> match AUDIT-LOG row whose parent == base_oid
    if exec_text is not None:
        exec_rows = parse_exec_log_rows(exec_text)
        for er in exec_rows:
            if re.search(r'(?<![A-Za-z0-9_-])' + re.escape(start_after) + r'(?![A-Za-z0-9_-])', er['scope']):
                base_oid = er['base_oid']
                for idx, row in enumerate(rows):
                    if OID40_RE.fullmatch(row['oid']):
                        parent_oid = _commit_parent_chain_parent(root_dir, row['oid'])
                        if parent_oid and _oid_matches(parent_oid, base_oid):
                            return idx

    raise CapCountError('START_AFTER_UNRESOLVED', start_after)


def _commit_parent_chain_parent(root_dir: str, oid: str) -> str | None:
    return _commit_parent_oid(root_dir, oid)


def _base_task(tid: str) -> str:
    return tid[len('PROMOTE-'):] if tid.startswith('PROMOTE-') else tid


def _task_yymmdd(tid: str) -> str | None:
    m = TASK_DATE_RE.search(tid)
    return m.group(1) if m else None


def _cause_tasks(cause: dict) -> list[str]:
    if not isinstance(cause, dict):
        return []
    tasks = cause.get('tasks') or []
    if not isinstance(tasks, list):
        return []
    return [t for t in tasks if isinstance(t, str) and t]


def _load_registry_causes(root_dir: str, *, ref_oid: str, use_git: bool) -> list[dict] | None:
    text = _read_doc_lf(root_dir, REGISTRY_REL, ref_oid=ref_oid, use_git=use_git, required=False)
    if text is None:
        return None
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CapCountError('REGISTRY_INVALID_JSON', str(exc)) from exc
    if not isinstance(doc, dict) or not isinstance(doc.get('causes'), list):
        raise CapCountError('REGISTRY_STRUCTURE_INVALID')
    return doc['causes']


def _newly_registered_unmerged_s1(
    prior_causes: list[dict] | None,
    cur_causes: list[dict] | None,
    *,
    start_after: str,
    committed_base_tasks: set[str],
) -> list[str]:
    """Return newly registered S1 task IDs absent from main commits, respecting import-point baseline."""
    if cur_causes is None:
        return []
    start_base = _base_task(start_after)
    if prior_causes is not None:
        prior_set = {_base_task(t) for pc in prior_causes for t in _cause_tasks(pc)}
        candidates = [
            t
            for cc in cur_causes
            for t in _cause_tasks(cc)
            if _base_task(t) not in prior_set
        ]
    else:
        # Parent lacked s1-registry.json (initial registry import commit): only tasks strictly
        # after start_after in cause order or by YYMMDD date count as post-anchor S1s.
        start_idx_in_reg = None
        for ci, cc in enumerate(cur_causes):
            if any(_base_task(t) == start_base for t in _cause_tasks(cc)):
                start_idx_in_reg = ci
        start_date = _task_yymmdd(start_base)
        candidates = []
        for ci, cc in enumerate(cur_causes):
            for t in _cause_tasks(cc):
                bt = _base_task(t)
                if bt == start_base:
                    continue
                td = _task_yymmdd(bt)
                if (start_idx_in_reg is not None and ci > start_idx_in_reg) or (
                    start_date and td and td > start_date
                ):
                    candidates.append(t)

    added = []
    seen_base = set()
    for t in candidates:
        bt = _base_task(t)
        if bt == start_base or bt in committed_base_tasks or bt in seen_base:
            continue
        seen_base.add(bt)
        added.append(bt)
    return added


def count_d6(root_dir: str, ref: str = 'HEAD', *, use_git: bool | None = None) -> dict:
    """Compute Governance Freeze D6 consecutive clean-batch count up to `ref`."""
    root = os.path.abspath(root_dir)
    ref_oid = _resolve_ref_oid(root, ref)
    git_docs = (ref != 'HEAD') if use_git is None else bool(use_git)

    taskboard_text = _read_doc_lf(root, TASKBOARD_REL, ref_oid=ref_oid, use_git=git_docs)
    audit_text = _read_doc_lf(root, AUDIT_LOG_REL, ref_oid=ref_oid, use_git=git_docs)
    exec_text = _read_doc_lf(root, EXEC_LOG_REL, ref_oid=ref_oid, use_git=git_docs, required=False)

    freeze = parse_freeze_header(taskboard_text)
    rows = parse_audit_log_rows(audit_text)
    s1_tasks, fixed_commits = _load_s1_registry_info(root, ref_oid=ref_oid, use_git=git_docs)
    fp_list = _first_parent_chain(root, ref_oid)
    fp_set = set(fp_list)

    # Enrich recent rows with execution-record task_id if scope column lacked a canonical TASK_ID
    start_idx = _resolve_d6_start_idx(root, rows, freeze['start_after'], fixed_commits, exec_text)

    window_rows = rows[start_idx:]
    all_committed_base_tasks = {_base_task(r['task_id']) for r in rows if r['task_id']}
    resolved_window = []
    for row in window_rows:
        oid = row['oid']
        if not OID40_RE.fullmatch(oid):
            raise CapCountError('D6_ROW_OID_NOT_40HEX', f'line {row["line_no"]}: {oid}')
        if oid not in fp_set:
            raise CapCountError('D6_ROW_NOT_FIRST_PARENT', oid)

        task_id = row['task_id'] or _commit_task_id(root, oid)
        if not task_id:
            raise CapCountError('D6_ROW_TASK_ID_UNRESOLVED', oid)
        all_committed_base_tasks.add(_base_task(task_id))
        resolved_window.append((row, oid, task_id))

    causes_cache: dict[str, list[dict] | None] = {}

    def _get_causes_at(commit_oid: str) -> list[dict] | None:
        if commit_oid not in causes_cache:
            causes_cache[commit_oid] = _load_registry_causes(root, ref_oid=commit_oid, use_git=True)
        return causes_cache[commit_oid]

    count = 0
    counted_tasks = []
    counted_commits = []
    repo_resets = []
    seen_resets_base = set()
    start_base = _base_task(freeze['start_after'])

    for row, oid, task_id in resolved_window:
        if row['is_readonly']:
            continue

        markers = CAP_RESET_RE.findall(row['raw'])
        parent_oid = _commit_parent_oid(root, oid)
        prior_causes = _get_causes_at(parent_oid) if parent_oid else None
        cur_causes = _get_causes_at(oid)
        added_s1 = _newly_registered_unmerged_s1(
            prior_causes,
            cur_causes,
            start_after=freeze['start_after'],
            committed_base_tasks=all_committed_base_tasks,
        )
        for reason, tgt in markers:
            tgt_base = _base_task(tgt)
            if reason == 'S1' and tgt_base != _base_task(task_id) and tgt_base != start_base:
                if tgt_base not in added_s1:
                    added_s1.append(tgt_base)
        added_s1 = [t for t in added_s1 if _base_task(t) not in seen_resets_base]
        if added_s1:
            count = 0
            counted_tasks = []
            counted_commits = []
            for t in added_s1:
                seen_resets_base.add(_base_task(t))
                repo_resets.append(t)

        s1_marker = any(
            reason == 'S1' and (tgt == task_id or tgt == 'PROMOTE-' + task_id)
            for reason, tgt in markers
        )
        if task_id in s1_tasks or s1_marker:
            count = 0
            counted_tasks = []
            counted_commits = []
            if _base_task(task_id) not in seen_resets_base:
                seen_resets_base.add(_base_task(task_id))
            repo_resets.append(task_id)
            continue

        if not row['is_postmain_verified']:
            continue

        count += 1
        counted_tasks.append(task_id)
        counted_commits.append(oid)

    last_audited_oid = window_rows[-1]['oid'] if window_rows else (rows[start_idx - 1]['oid'] if start_idx > 0 else None)
    last_audited_causes = _get_causes_at(last_audited_oid) if last_audited_oid else None
    final_causes = _load_registry_causes(root, ref_oid=ref_oid, use_git=git_docs)
    added_after = [
        t
        for t in _newly_registered_unmerged_s1(
            last_audited_causes,
            final_causes,
            start_after=freeze['start_after'],
            committed_base_tasks=all_committed_base_tasks,
        )
        if _base_task(t) not in seen_resets_base
    ]
    if added_after:
        count = 0
        counted_tasks = []
        counted_commits = []
        for t in added_after:
            seen_resets_base.add(_base_task(t))
            repo_resets.append(t)

    reset_mismatch = None
    if repo_resets:
        observed_last_reset = repo_resets[-1]
        if _base_task(observed_last_reset) != _base_task(freeze['last_reset']):
            reset_mismatch = {'declared': freeze['last_reset'], 'observed': observed_last_reset}

    return {
        'source': 'repo',
        'ref': ref,
        'ref_oid': ref_oid,
        'count': count,
        'target': freeze['target'],
        'declared': freeze['declared'],
        'match': (count == freeze['declared']) and (reset_mismatch is None),
        'last_reset': freeze['last_reset'],
        'start_after': freeze['start_after'],
        'repo_resets': repo_resets,
        'reset_mismatch': reset_mismatch,
        'counted_tasks': counted_tasks,
        'counted_commits': counted_commits,
        'note': 'repo 僅含已入庫 S1；未入庫 S1 差異由 Dashboard 比對提醒，不在 CI 判 FAIL',
    }


def _row_mentions_cap2_anchor(row: dict) -> bool:
    return (row['task_id'] == CAP2_ANCHOR_TASK) or (CAP2_ANCHOR_TASK in row['scope']) or (CAP2_ANCHOR_TASK in row['result'])


def count_cap2(root_dir: str, ref: str = 'HEAD', *, use_git: bool | None = None) -> dict:
    """Compute Cap Condition (2) consecutive clean product-batch count since CAP2_ANCHOR_TASK."""
    root = os.path.abspath(root_dir)
    ref_oid = _resolve_ref_oid(root, ref)
    git_docs = (ref != 'HEAD') if use_git is None else bool(use_git)

    audit_text = _read_doc_lf(root, AUDIT_LOG_REL, ref_oid=ref_oid, use_git=git_docs)
    rows = parse_audit_log_rows(audit_text)

    anchor_row = next((r for r in rows if _row_mentions_cap2_anchor(r)), None)
    if anchor_row is None or not OID40_RE.fullmatch(anchor_row['oid']):
        raise CapCountError('CAP2_ANCHOR_MISSING', CAP2_ANCHOR_TASK)
    anchor_oid = anchor_row['oid']

    fp_list = _first_parent_chain(root, ref_oid)
    if anchor_oid not in fp_list:
        raise CapCountError('CAP2_ANCHOR_NOT_ON_FIRST_PARENT', anchor_oid)
    anchor_pos = fp_list.index(anchor_oid)
    since_commits = fp_list[anchor_pos + 1:]

    rows_by_oid = {r['oid']: r for r in rows}
    product_batches = []
    product_task_ids = set()

    for oid in since_commits:
        parent_oid = _commit_parent_oid(root, oid)
        if parent_oid is None:
            raise CapCountError('CAP2_PARENT_MISSING', oid)
        diff_out = _git_text(
            root, 'diff', '--name-only', '--no-renames', parent_oid, oid,
            error_code='CAP2_DIFF_FAILED',
        )
        changed = [line.strip() for line in diff_out.splitlines() if line.strip()]
        if not any(path.startswith(PRODUCT_PREFIXES) for path in changed):
            continue

        row = rows_by_oid.get(oid)
        task_id = _commit_task_id(root, oid) or (row['task_id'] if row else None)
        if not task_id:
            raise CapCountError('CAP2_PRODUCT_TASK_UNRESOLVED', oid)
        product_batches.append((task_id, oid))
        product_task_ids.add(task_id)

    # Scan AUDIT-LOG rows strictly after anchor_row for CAP_RESET markers
    anchor_idx = rows.index(anchor_row)
    markers = []
    for row in rows[anchor_idx + 1:]:
        for reason, target_task in CAP_RESET_RE.findall(row['raw']):
            markers.append((reason, target_task))

    reset_reasons_by_task = {}
    resets_applied = []
    resets_ignored_non_product = []
    for reason, target_task in markers:
        normalized = target_task[len('PROMOTE-'):] if target_task.startswith('PROMOTE-') else target_task
        matched = target_task if target_task in product_task_ids else (normalized if normalized in product_task_ids else None)
        if matched is None:
            resets_ignored_non_product.append({'reason': reason, 'task': target_task})
        else:
            reset_reasons_by_task.setdefault(matched, []).append(reason)
            resets_applied.append({'reason': reason, 'task': matched})

    count = 0
    counted_tasks = []
    counted_commits = []
    for task_id, oid in product_batches:
        if task_id in reset_reasons_by_task:
            count = 0
            counted_tasks = []
            counted_commits = []
            continue
        count += 1
        counted_tasks.append(task_id)
        counted_commits.append(oid)

    return {
        'source': 'repo',
        'ref': ref,
        'ref_oid': ref_oid,
        'count': count,
        'target': CAP2_TARGET,
        'anchor_oid': anchor_oid,
        'anchor_task': CAP2_ANCHOR_TASK,
        'product_batches_total': len(product_batches),
        'counted_product_tasks': counted_tasks,
        'counted_product_commits': counted_commits,
        'resets_applied': resets_applied,
        'resets_ignored_non_product': resets_ignored_non_product,
    }


def format_lines(d6_data: dict | None = None, cap2_data: dict | None = None) -> list[str]:
    """Render deterministic single-line summaries for D6 and Cap Condition (2)."""
    lines = []
    if d6_data is not None:
        match_flag = 'YES' if d6_data['match'] else 'NO'
        rm = d6_data.get('reset_mismatch')
        rm_suffix = f' reset_mismatch=declared:{rm["declared"]},observed:{rm["observed"]}' if rm else ''
        lines.append(
            f'CAP_COUNT_D6 source={d6_data["source"]} count={d6_data["count"]} '
            f'target={d6_data["target"]} declared={d6_data["declared"]} match={match_flag} '
            f'last_reset={d6_data["last_reset"]} start_after={d6_data["start_after"]}{rm_suffix}'
        )
    if cap2_data is not None:
        lines.append(
            f'CAP_COUNT_CAP2 source={cap2_data["source"]} count={cap2_data["count"]} '
            f'target={cap2_data["target"]} anchor={cap2_data["anchor_oid"]} '
            f'product_batches={cap2_data["product_batches_total"]} '
            f'resets={len(cap2_data["resets_applied"])}'
        )
    return lines


def compute_all(root_dir: str, ref: str = 'HEAD', mode: str = 'all', *, use_git: bool | None = None) -> dict:
    """Compute requested mode ('all', 'd6', or 'cap2') and return structured dict."""
    if mode not in ('all', 'd6', 'cap2'):
        raise CapCountError('MODE_INVALID', mode)
    result = {'source': 'repo', 'mode': mode}
    if mode in ('all', 'd6'):
        result['d6'] = count_d6(root_dir, ref=ref, use_git=use_git)
    if mode in ('all', 'cap2'):
        result['cap2'] = count_cap2(root_dir, ref=ref, use_git=use_git)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='TD-008 shared read-only counter for D6 freeze and cap condition (2)')
    parser.add_argument('--repo', default='.')
    parser.add_argument('--ref', default='HEAD')
    parser.add_argument('--mode', choices=('all', 'd6', 'cap2'), default='all')
    parser.add_argument('--from-git', action='store_true', help='force reading docs from git --ref instead of working tree')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)

    root = os.path.abspath(args.repo)
    use_git = True if args.from_git else None
    try:
        data = compute_all(root, ref=args.ref, mode=args.mode, use_git=use_git)
    except CapCountError as exc:
        print(f'CAP_COUNT FAIL {exc}')
        return 1

    if args.json:
        print(json.dumps(data, ensure_ascii=False, sort_keys=True))
    else:
        for line in format_lines(data.get('d6'), data.get('cap2')):
            print(line)
    return 0


if __name__ == '__main__':
    sys.exit(main())
