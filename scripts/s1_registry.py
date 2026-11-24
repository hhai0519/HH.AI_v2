#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/s1_registry.py

D8 / TD-101 S1 root-cause registry validator and summary CLI (`schema: 2`).
Called by scripts/check_consistency.py CHECK 31 and scripts/draft_precheck.py.

Design guarantees (fail-closed):
- Reads docs/governance/s1-registry.json in binary to reject UTF-8 BOM, CR newlines,
  or invalid UTF-8 before JSON decoding.
- Strictly validates schema=2 top-level keys, `classes` (precedence + definitions),
  sequential cause IDs (`S1C-001`..`S1C-NNN`), status-dependent fields, watch regex,
  `fixedBy`/`outcomes` task alignment, `distinctFrom`/`distinctBy` consistency, and
  optional `todoIds` cross-reference against docs/TODO-LEDGER.md.
- Compares monotonically against git blob at docs/refactor-backlog.md §5.1 checkpoint
  when present at checkpoint: no deleted S1C IDs, no retracted `tasks`, and no
  `confirmed: true -> false` regressions.
- Never checks wall-clock calendar age inside check() / CHECK 31 (CI deterministic);
  summary() reports `class_changes` vs checkpoint, recurring class counts (excluding
  `UNCLASSIFIED`), and non-blocking >7d stale unfixed reminders (--as-of supported).
"""

import argparse
import ast
import datetime
import hashlib
import json
import os
import re
import stat
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

REGISTRY_REL = 'docs/governance/s1-registry.json'
BACKLOG_REL = 'docs/refactor-backlog.md'
LEDGER_REL = 'docs/TODO-LEDGER.md'
DOC_REF = 'docs/ops/d8-s1-registry.md'

SCHEMA_VERSION = 2
RECURRING_CLASSES = ('A', 'B', 'C', 'D', 'E', 'F')
VALID_CLASSES = RECURRING_CLASSES + ('UNCLASSIFIED',)
EXPECTED_PRECEDENCE = ('A', 'B', 'D', 'C', 'E', 'F')
VALID_STATUSES = ('fixed', 'planned', 'unplanned', 'accepted')
STALE_DAYS = 7

TOP_KEYS = {'schema', 'updated', 'about', 'classes', 'causes'}
CLASSES_KEYS = {'precedence', 'rule', 'definitions'}
FOLLOWUP_KEYS = {'plannedIn', 'note'}
CAUSE_ALLOWED_KEYS = {
    'id', 'title', 'tasks', 'status', 'class', 'watch', 'evidence', 'by',
    'verified', 'confirmed', 'fixedIn', 'fixedCommit', 'fixedBy', 'plannedIn',
    'reason', 'followUp', 'distinctFrom', 'distinctBy', 'outcomes', 'todoIds',
    'reverseVerification',
}

CAUSE_ID_RE = re.compile(r'^S1C-([0-9]{3,})$')
WATCH_RE = re.compile(r'^[a-z0-9_-]+:[A-Z0-9_]+$')
DATE_RE = re.compile(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
COMMIT_RE = re.compile(r'^[0-9a-f]{7,40}$')
TD_ID_RE = re.compile(r'^TD-[0-9]{3}$')
LEDGER_ROW_RE = re.compile(r'^\| (TD-[0-9]{3}) \|')
CHECKPOINT_RE = re.compile(r'^上次核對通過的 HEAD：([0-9a-f]{40})\s*$', re.M)
OID_RE = re.compile(r'^[0-9a-f]{40}$')
TASK_ID_RE = re.compile(r'^[A-Za-z0-9_-]+$')
SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
NODEID_RE = re.compile(r'^[A-Za-z0-9_./-]+\.py::[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)?$')
RV_INJECTABLE_KEYS = {
    'fixTask', 'injectable', 'injectionMethod',
    'oldResult', 'oldOutputSha256',
    'newResult', 'newOutputSha256',
    'mutantResult', 'mutantOutputSha256',
    'regressionTests',
}
RV_NONINJECTABLE_KEYS = {'fixTask', 'injectable', 'status', 'notInjectableReason', 'regressionTests'}
RV_NONINJECTABLE_REQUIRED = {'fixTask', 'injectable', 'status', 'notInjectableReason'}


class RegistryError(Exception):
    """Fail-closed error in registry loading, validation, or git inspection."""


def _is_nonempty_str(val) -> bool:
    return isinstance(val, str) and bool(val.strip())


def _is_valid_followup(val) -> bool:
    return (
        isinstance(val, dict)
        and set(val.keys()) == FOLLOWUP_KEYS
        and _is_nonempty_str(val.get('plannedIn'))
        and _is_nonempty_str(val.get('note'))
    )


def _parse_iso_date(val, label: str) -> datetime.date:
    if not isinstance(val, str) or not DATE_RE.match(val):
        raise RegistryError(f'{label} 格式必須為 YYYY-MM-DD（實為 {val!r}）')
    try:
        return datetime.date.fromisoformat(val)
    except ValueError as exc:
        raise RegistryError(f'{label} 不是合法日期 {val!r}: {exc}') from None


def read_text_lf(root: str, rel: str) -> str:
    path = os.path.join(root, *rel.split('/'))
    try:
        with open(path, 'rb') as handle:
            raw = handle.read()
    except OSError as exc:
        raise RegistryError(f'{rel} 無法讀取（{type(exc).__name__}）') from None
    if raw.startswith(b'\xef\xbb\xbf'):
        raise RegistryError(f'{rel} 含 UTF-8 BOM')
    if b'\r' in raw:
        raise RegistryError(f'{rel} 含 CR（必須是 LF）')
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise RegistryError(f'{rel} 不是合法 UTF-8（{exc}）') from None


def parse_json_lf(root: str, rel: str) -> dict:
    text = read_text_lf(root, rel)
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RegistryError(f'{rel} JSON 解析失敗：{exc}') from None
    if not isinstance(doc, dict):
        raise RegistryError(f'{rel} 頂層必須是 JSON object')
    return doc


def load_ledger_td_ids(root: str) -> set:
    text = read_text_lf(root, LEDGER_REL)
    ids = set()
    for line in text.split('\n'):
        m = LEDGER_ROW_RE.match(line)
        if m:
            ids.add(m.group(1))
    if not ids:
        raise RegistryError(f'{LEDGER_REL} 找不到任何 TD-nnn 條目')
    return ids


def _git(root: str, *args: str):
    try:
        proc = subprocess.run(['git', '-C', root, *args], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RegistryError(f'git 無法執行（{type(exc).__name__}）') from None
    return proc.returncode, proc.stdout.decode('utf-8', 'replace'), proc.stderr.decode('utf-8', 'replace')


def read_checkpoint_oid(root: str) -> str:
    backlog = read_text_lf(root, BACKLOG_REL)
    matches = CHECKPOINT_RE.findall(backlog)
    if len(matches) != 1:
        raise RegistryError(f'{BACKLOG_REL} 的「上次核對通過的 HEAD：」必須恰有一行 40 碼 hex（找到 {len(matches)}）')
    oid = matches[0]
    rc, out, _ = _git(root, 'rev-parse', '--verify', '-q', oid + '^{commit}')
    resolved = out.strip()
    if rc != 0 or not OID_RE.match(resolved) or resolved != oid:
        raise RegistryError(f'{BACKLOG_REL} checkpoint {oid[:7]} 無法於 git 解析為 commit')
    return oid


def read_checkpoint_registry(root: str, checkpoint_oid: str):
    """Return (prior_doc_or_None, status_note). Fails closed on git/JSON errors."""
    rc, _, err = _git(root, 'cat-file', '-e', f'{checkpoint_oid}:{REGISTRY_REL}')
    if rc != 0:
        # Verify git cat-file works on the commit itself so real git/corruption fails closed.
        rc_tree, _, err_tree = _git(root, 'cat-file', '-e', f'{checkpoint_oid}^{{tree}}')
        if rc_tree != 0:
            raise RegistryError(f'無法讀取 checkpoint {checkpoint_oid[:7]} 樹物件（{err_tree.strip()}）')
        return None, f'ABSENT_AT_{checkpoint_oid[:7]}'
    rc_show, raw_text, err_show = _git(root, 'show', f'{checkpoint_oid}:{REGISTRY_REL}')
    if rc_show != 0:
        raise RegistryError(f'git show {checkpoint_oid[:7]}:{REGISTRY_REL} 失敗（{err_show.strip()}）')
    try:
        doc = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RegistryError(f'checkpoint {checkpoint_oid[:7]}:{REGISTRY_REL} JSON 無效（{exc}）') from None
    if not isinstance(doc, dict) or not isinstance(doc.get('causes'), list):
        raise RegistryError(f'checkpoint {checkpoint_oid[:7]}:{REGISTRY_REL} 結構無效')
    return doc, f'PRESENT_AT_{checkpoint_oid[:7]}'


def verify_regression_nodeid(root_dir: str, nodeid: str):
    """Verify nodeid syntax, safe repo-relative path, LF UTF-8 syntax, and AST symbol."""
    if not isinstance(nodeid, str) or not NODEID_RE.match(nodeid):
        return f'regressionTests nodeid 格式無效：{nodeid!r}'
    parts = nodeid.split('::')
    rel = parts[0]
    if rel.startswith('/') or '\\' in rel or rel in ('', '.', '..'):
        return f'regressionTests 路徑不安全：{rel!r}'
    segs = rel.split('/')
    if any(s in ('', '.', '..') for s in segs):
        return f'regressionTests 路徑含不安全區段：{rel!r}'

    root_real = os.path.realpath(root_dir)
    cur = root_dir
    reparse_flag = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
    for seg in segs:
        cur = os.path.join(cur, seg)
        try:
            st = os.lstat(cur)
        except OSError as exc:
            return f'找不到測試檔案 {rel}（{type(exc).__name__}）'
        is_reparse = bool(reparse_flag and (getattr(st, 'st_file_attributes', 0) & reparse_flag))
        if stat.S_ISLNK(st.st_mode) or is_reparse:
            return f'測試路徑不得為 symlink：{rel}'
    if not stat.S_ISREG(st.st_mode):
        return f'測試路徑非一般檔案：{rel}'
    if os.path.commonpath([root_real, os.path.realpath(cur)]) != root_real:
        return f'測試路徑越界：{rel}'

    try:
        with open(cur, 'rb') as handle:
            raw = handle.read()
    except OSError as exc:
        return f'無法讀取測試檔案 {rel}（{type(exc).__name__}）'
    if raw.startswith(b'\xef\xbb\xbf'):
        return f'測試檔案含 UTF-8 BOM：{rel}'
    if b'\r' in raw:
        return f'測試檔案含 CR（必須是 LF）：{rel}'
    try:
        src = raw.decode('utf-8', 'strict')
        tree = ast.parse(src, filename=rel)
    except (UnicodeDecodeError, SyntaxError, ValueError) as exc:
        return f'測試檔案解析失敗 {rel}：{type(exc).__name__}'

    fn_types = (ast.FunctionDef, ast.AsyncFunctionDef)
    if len(parts) == 2:
        fn_name = parts[1]
        if not any(isinstance(n, fn_types) and n.name == fn_name for n in tree.body):
            return f'於 {rel} AST 找不到頂層函式 {fn_name}'
    else:
        cls_name, meth_name = parts[1], parts[2]
        cls_node = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls_name), None)
        if cls_node is None:
            return f'於 {rel} AST 找不到類別 {cls_name}'
        if not any(isinstance(m, fn_types) and m.name == meth_name for m in cls_node.body):
            return f'於 {rel}::{cls_name} AST 找不到方法 {meth_name}'
    return None


def _validate_regression_tests(cid: str, tests, *, required: bool, root_dir: str | None) -> list:
    fails = []
    if not isinstance(tests, list) or not all(isinstance(x, str) for x in tests):
        return [f'{cid} reverseVerification.regressionTests 必須為 nodeid 字串陣列']
    if required and not tests:
        return [f'{cid} reverseVerification.regressionTests 於 injectable=true 時不得為空']
    if len(set(tests)) != len(tests):
        fails.append(f'{cid} reverseVerification.regressionTests 不得重複')
    for nid in tests:
        if not NODEID_RE.match(nid):
            fails.append(f'{cid} reverseVerification.regressionTests 格式無效：{nid!r}')
        elif root_dir is not None:
            err = verify_regression_nodeid(root_dir, nid)
            if err is not None:
                fails.append(f'{cid} reverseVerification：{err}')
    return fails


def validate_reverse_verification(cid: str, rv, root_dir: str | None = None) -> list:
    """Validate D4 reverseVerification block (injectable or not_injectable)."""
    if not isinstance(rv, dict):
        return [f'{cid} reverseVerification 必須為 JSON object']
    fails = []
    fix_task = rv.get('fixTask')
    if not isinstance(fix_task, str) or not TASK_ID_RE.match(fix_task):
        fails.append(f'{cid} reverseVerification.fixTask 格式無效（實為 {fix_task!r}）')
    inj = rv.get('injectable')
    if type(inj) is not bool:
        fails.append(f'{cid} reverseVerification.injectable 必須為布林值（實為 {inj!r}）')
        return fails

    if inj is True:
        missing = sorted(RV_INJECTABLE_KEYS - set(rv.keys()))
        extra = sorted(set(rv.keys()) - RV_INJECTABLE_KEYS)
        if missing:
            fails.append(f'{cid} reverseVerification 缺少欄位：{", ".join(missing)}')
        if extra:
            fails.append(f'{cid} reverseVerification 含未定義欄位：{", ".join(extra)}')
        if not _is_nonempty_str(rv.get('injectionMethod')):
            fails.append(f'{cid} reverseVerification.injectionMethod 不得為空')
        if rv.get('oldResult') != 'FAIL':
            fails.append(f'{cid} reverseVerification.oldResult 必須為 "FAIL"（實為 {rv.get("oldResult")!r}）')
        if rv.get('newResult') != 'PASS':
            fails.append(f'{cid} reverseVerification.newResult 必須為 "PASS"（實為 {rv.get("newResult")!r}）')
        if rv.get('mutantResult') != 'FAIL':
            fails.append(f'{cid} reverseVerification.mutantResult 必須為 "FAIL"（實為 {rv.get("mutantResult")!r}）')
        for sha_key in ('oldOutputSha256', 'newOutputSha256', 'mutantOutputSha256'):
            sval = rv.get(sha_key)
            if not isinstance(sval, str) or not SHA256_RE.match(sval):
                fails.append(f'{cid} reverseVerification.{sha_key} 必須為 64 碼小寫 hex')
        if 'regressionTests' in rv:
            fails.extend(_validate_regression_tests(cid, rv['regressionTests'], required=True, root_dir=root_dir))
    else:
        missing = sorted(RV_NONINJECTABLE_REQUIRED - set(rv.keys()))
        extra = sorted(set(rv.keys()) - RV_NONINJECTABLE_KEYS)
        if missing:
            fails.append(f'{cid} reverseVerification 缺少欄位：{", ".join(missing)}')
        if extra:
            fails.append(f'{cid} reverseVerification 含未定義欄位：{", ".join(extra)}')
        if rv.get('status') != 'not_injectable':
            fails.append(f'{cid} reverseVerification.status 於 injectable=false 時必須為 "not_injectable"')
        if not _is_nonempty_str(rv.get('notInjectableReason')):
            fails.append(f'{cid} reverseVerification.notInjectableReason 不得為空')
        if 'regressionTests' in rv:
            fails.extend(_validate_regression_tests(cid, rv['regressionTests'], required=False, root_dir=root_dir))
    return fails


def validate_doc(doc: dict, ledger_ids: set, root_dir: str | None = None) -> list:
    """Validate schema: 2 registry dict; returns list of failure messages."""
    fails = []
    if not isinstance(doc, dict):
        return [f'{REGISTRY_REL} 必須為 JSON object']

    extra_top = sorted(set(doc.keys()) - TOP_KEYS)
    missing_top = sorted(TOP_KEYS - set(doc.keys()))
    if missing_top:
        fails.append(f'{REGISTRY_REL} 缺少頂層欄位：{", ".join(missing_top)}')
    if extra_top:
        fails.append(f'{REGISTRY_REL} 含有未授權頂層欄位：{", ".join(extra_top)}')

    schema_val = doc.get('schema')
    if type(schema_val) is not int or schema_val != SCHEMA_VERSION:
        fails.append(f'{REGISTRY_REL} schema 必須為整數 {SCHEMA_VERSION}（實為 {schema_val!r}）')

    if 'updated' in doc:
        try:
            _parse_iso_date(doc['updated'], f'{REGISTRY_REL} updated')
        except RegistryError as exc:
            fails.append(str(exc))

    about = doc.get('about')
    if not _is_nonempty_str(about):
        fails.append(f'{REGISTRY_REL} about 不得為空')
    else:
        if 'app/MAINTENANCE.md' in about:
            fails.append(f'{REGISTRY_REL} about 不得再指向 repo 外部之 app/MAINTENANCE.md')
        if DOC_REF not in about:
            fails.append(f'{REGISTRY_REL} about 必須指向 repo 內文件 {DOC_REF}')

    classes = doc.get('classes')
    if not isinstance(classes, dict):
        fails.append(f'{REGISTRY_REL} classes 必須為 object')
    else:
        c_missing = sorted(CLASSES_KEYS - set(classes.keys()))
        c_extra = sorted(set(classes.keys()) - CLASSES_KEYS)
        if c_missing:
            fails.append(f'{REGISTRY_REL} classes 缺少欄位：{", ".join(c_missing)}')
        if c_extra:
            fails.append(f'{REGISTRY_REL} classes 含有未知欄位：{", ".join(c_extra)}')
        if classes.get('precedence') != list(EXPECTED_PRECEDENCE):
            fails.append(f'{REGISTRY_REL} classes.precedence 必須為 {list(EXPECTED_PRECEDENCE)!r}')
        if not _is_nonempty_str(classes.get('rule')):
            fails.append(f'{REGISTRY_REL} classes.rule 不得為空')
        defs = classes.get('definitions')
        if not isinstance(defs, dict):
            fails.append(f'{REGISTRY_REL} classes.definitions 必須為 object')
        else:
            d_missing = sorted(set(VALID_CLASSES) - set(defs.keys()))
            d_extra = sorted(set(defs.keys()) - set(VALID_CLASSES))
            if d_missing:
                fails.append(f'{REGISTRY_REL} classes.definitions 缺少類別定義：{", ".join(d_missing)}')
            if d_extra:
                fails.append(f'{REGISTRY_REL} classes.definitions 含有未知類別：{", ".join(d_extra)}')
            for cls_key in VALID_CLASSES:
                item = defs.get(cls_key)
                if not isinstance(item, dict) or not _is_nonempty_str(item.get('label')) or not _is_nonempty_str(item.get('description')):
                    fails.append(f'{REGISTRY_REL} classes.definitions.{cls_key} 須含非空 label 與 description')

    causes = doc.get('causes')
    if not isinstance(causes, list) or not causes:
        fails.append(f'{REGISTRY_REL} causes 必須為非空陣列')
        return fails

    seen_ids = {}
    for idx, c in enumerate(causes, 1):
        if not isinstance(c, dict):
            fails.append(f'{REGISTRY_REL} causes[{idx}] 必須為 object')
            continue
        cid = c.get('id')
        expected_id = f'S1C-{idx:03d}'
        if cid != expected_id:
            fails.append(f'{REGISTRY_REL} causes[{idx}] id 須依序無缺號為 {expected_id}（實為 {cid!r}）')
        if isinstance(cid, str):
            if cid in seen_ids:
                fails.append(f'{REGISTRY_REL} id 重複：{cid}')
            seen_ids[cid] = c

    all_ids = set(seen_ids.keys())

    for idx, c in enumerate(causes, 1):
        if not isinstance(c, dict):
            continue
        cid = c.get('id') if isinstance(c.get('id'), str) else f'#{idx}'
        unknown_keys = sorted(set(c.keys()) - CAUSE_ALLOWED_KEYS)
        if unknown_keys:
            fails.append(f'{cid} 含有未定義欄位：{", ".join(unknown_keys)}')

        if not _is_nonempty_str(c.get('title')):
            fails.append(f'{cid} title 不得為空')

        tasks = c.get('tasks')
        if not isinstance(tasks, list) or not tasks or not all(_is_nonempty_str(t) for t in tasks):
            fails.append(f'{cid} tasks 必須為非空字串陣列')
            task_set = set()
        else:
            if len(set(tasks)) != len(tasks):
                fails.append(f'{cid} tasks 不得重複')
            task_set = set(tasks)

        cls_val = c.get('class')
        if cls_val not in VALID_CLASSES:
            fails.append(f'{cid} class 必須為 {VALID_CLASSES!r} 之一（實為 {cls_val!r}）')

        status = c.get('status')
        if status not in VALID_STATUSES:
            fails.append(f'{cid} status 必須為 {VALID_STATUSES!r} 之一（實為 {status!r}）')
        elif status == 'fixed':
            if not _is_nonempty_str(c.get('fixedIn')):
                fails.append(f'{cid} status=fixed 必填 fixedIn')
            fc = c.get('fixedCommit')
            if not isinstance(fc, str) or not COMMIT_RE.match(fc):
                fails.append(f'{cid} status=fixed 必填合法 fixedCommit hex（實為 {fc!r}）')
        elif status == 'planned':
            if not _is_nonempty_str(c.get('plannedIn')):
                fails.append(f'{cid} status=planned 必填 plannedIn')
        elif status == 'unplanned':
            if not _is_valid_followup(c.get('followUp')):
                fails.append(f'{cid} status=unplanned 必填合法 followUp 物件（plannedIn 與 note）')
        elif status == 'accepted':
            if not _is_nonempty_str(c.get('reason')):
                fails.append(f'{cid} status=accepted 必填 reason')

        if 'followUp' in c and c['followUp'] is not None and not _is_valid_followup(c['followUp']):
            fails.append(f'{cid} followUp 必須為含非空 plannedIn 與 note 之物件')

        watch = c.get('watch')
        if not isinstance(watch, list) or not watch:
            fails.append(f'{cid} watch 必須為非空陣列')
        else:
            if len(set(watch)) != len(watch):
                fails.append(f'{cid} watch 不得重複')
            for w in watch:
                if not isinstance(w, str) or not WATCH_RE.match(w):
                    fails.append(f'{cid} watch 項目格式不符 ^[a-z0-9_-]+:[A-Z0-9_]+$：{w!r}')

        if not _is_nonempty_str(c.get('evidence')):
            fails.append(f'{cid} evidence 不得為空')
        if not _is_nonempty_str(c.get('by')):
            fails.append(f'{cid} by 不得為空')

        verified = c.get('verified')
        if not isinstance(verified, dict):
            fails.append(f'{cid} verified 必須為 object')
        else:
            if not _is_nonempty_str(verified.get('by')) or not _is_nonempty_str(verified.get('basis')):
                fails.append(f'{cid} verified 必須含非空 by 與 basis')
            try:
                _parse_iso_date(verified.get('date'), f'{cid} verified.date')
            except RegistryError as exc:
                fails.append(str(exc))

        if type(c.get('confirmed')) is not bool:
            fails.append(f'{cid} confirmed 必須為布林值（實為 {c.get("confirmed")!r}）')

        for map_key in ('fixedBy', 'outcomes'):
            if map_key in c:
                mp = c[map_key]
                if not isinstance(mp, dict) or not all(
                    isinstance(k, str) and k in task_set and _is_nonempty_str(v)
                    for k, v in mp.items()
                ):
                    fails.append(f'{cid} {map_key} 之鍵必須全部屬於 tasks 且值為非空字串')

        if 'distinctFrom' in c:
            df = c['distinctFrom']
            if not isinstance(df, list) or not all(isinstance(x, str) for x in df):
                fails.append(f'{cid} distinctFrom 必須為字串陣列')
            else:
                if len(set(df)) != len(df):
                    fails.append(f'{cid} distinctFrom 不得重複')
                if cid in df:
                    fails.append(f'{cid} distinctFrom 不得指向自己')
                unknown_df = sorted(set(df) - all_ids)
                if unknown_df:
                    fails.append(f'{cid} distinctFrom 指向不存在的編號：{", ".join(unknown_df)}')
                if df and not _is_nonempty_str(c.get('distinctBy')):
                    fails.append(f'{cid} distinctFrom 非空時必填 distinctBy')

        if 'todoIds' in c:
            tds = c['todoIds']
            if not isinstance(tds, list) or not all(isinstance(t, str) and TD_ID_RE.match(t) for t in tds):
                fails.append(f'{cid} todoIds 必須為 TD-nnn 字串陣列')
            else:
                if len(set(tds)) != len(tds):
                    fails.append(f'{cid} todoIds 不得重複')
                missing_tds = sorted(set(tds) - ledger_ids)
                if missing_tds:
                    fails.append(f'{cid} todoIds 於 {LEDGER_REL} 找不到編號：{", ".join(missing_tds)}')

        if 'reverseVerification' in c:
            fails.extend(validate_reverse_verification(cid, c['reverseVerification'], root_dir=root_dir))

    return fails


def check_monotonic(prior_doc: dict, current_doc: dict) -> list:
    """Enforce monotonic growth, D4 mandatory reverseVerification on fixed transitions, and N2 immutability."""
    fails = []
    cur_causes = [c for c in current_doc.get('causes', []) if isinstance(c, dict) and isinstance(c.get('id'), str)]
    prior_causes = [pc for pc in prior_doc.get('causes', []) if isinstance(pc, dict) and isinstance(pc.get('id'), str)]
    cur_by_id = {c['id']: c for c in cur_causes}
    prior_by_id = {pc['id']: pc for pc in prior_causes}

    for pc in prior_causes:
        cid = pc['id']
        cc = cur_by_id.get(cid)
        if cc is None:
            fails.append(f'{REGISTRY_REL} {cid}：checkpoint 已有此原因，不得刪除或撤回（只增不減）')
            continue
        prior_tasks = set(pc.get('tasks') or [])
        cur_tasks = set(cc.get('tasks') or [])
        retracted = sorted(prior_tasks - cur_tasks)
        if retracted:
            fails.append(f'{REGISTRY_REL} {cid}：tasks 不得撤回既有 TASK_ID：{", ".join(retracted)}')
        if pc.get('confirmed') is True and cc.get('confirmed') is not True:
            fails.append(f'{REGISTRY_REL} {cid}：confirmed 不得由 true 退回為 {cc.get("confirmed")!r}')
        prior_rv = pc.get('reverseVerification')
        cur_rv = cc.get('reverseVerification')
        if prior_rv is not None:
            if cur_rv is None:
                fails.append(f'{REGISTRY_REL} {cid}：reverseVerification 已建立，不得刪除或撤回（只增不減）')
            elif (
                isinstance(prior_rv, dict)
                and isinstance(cur_rv, dict)
                and prior_rv.get('injectable') is True
                and cur_rv.get('injectable') is not True
            ):
                fails.append(
                    f'{REGISTRY_REL} {cid}：reverseVerification.injectable 不得由 true 退回為 {cur_rv.get("injectable")!r}'
                )
            if isinstance(prior_rv, dict) and isinstance(cur_rv, dict):
                prior_tests = prior_rv.get('regressionTests')
                if isinstance(prior_tests, list) and prior_tests:
                    cur_tests = cur_rv.get('regressionTests') if isinstance(cur_rv.get('regressionTests'), list) else []
                    removed_tests = sorted(set(prior_tests) - set(cur_tests))
                    if removed_tests:
                        fails.append(
                            f'{REGISTRY_REL} {cid}：reverseVerification.regressionTests 不得縮減既有項目：{", ".join(removed_tests)}'
                        )
            re_fixing = cc.get('status') == 'fixed' and (pc.get('status') != 'fixed' or pc.get('fixedIn') != cc.get('fixedIn'))
            if isinstance(prior_rv, dict) and isinstance(cur_rv, dict) and not re_fixing:
                prior_ft = prior_rv.get('fixTask')
                if _is_nonempty_str(prior_ft) and cur_rv.get('fixTask') != prior_ft:
                    fails.append(
                        f'{REGISTRY_REL} {cid}：reverseVerification.fixTask 已建立為 {prior_ft!r}，不得變更為 {cur_rv.get("fixTask")!r}'
                    )
                for sha_key in ('oldOutputSha256', 'newOutputSha256', 'mutantOutputSha256'):
                    prior_sha = prior_rv.get(sha_key)
                    if _is_nonempty_str(prior_sha) and cur_rv.get(sha_key) != prior_sha:
                        fails.append(
                            f'{REGISTRY_REL} {cid}：reverseVerification.{sha_key} 已記錄，不得變更（若需重驗請新增欄位或另立紀錄）'
                        )

    # B2: Any fix event (new cause as fixed, non-fixed -> fixed, or fixed -> fixed with changed fixedIn)
    # must carry reverseVerification with fixTask == fixedIn.
    for cc in cur_causes:
        cid = cc['id']
        if cc.get('status') != 'fixed':
            continue
        pc = prior_by_id.get(cid)
        if pc is not None and pc.get('status') == 'fixed' and pc.get('fixedIn') == cc.get('fixedIn'):
            continue
        cur_rv = cc.get('reverseVerification')
        if not isinstance(cur_rv, dict):
            fails.append(f'{REGISTRY_REL} {cid}：依 D4 規則，由非 fixed、新增原因或 fixedIn 變更轉為新一輪 fixed 時必須附帶合法 reverseVerification')
            continue
        fixed_in = cc.get('fixedIn')
        fix_task = cur_rv.get('fixTask')
        if not _is_nonempty_str(fixed_in) or fix_task != fixed_in:
            fails.append(
                f'{REGISTRY_REL} {cid}：reverseVerification.fixTask（{fix_task!r}）必須等於 fixedIn（{fixed_in!r}）'
            )

    return fails


def check(root_dir: str) -> tuple:
    """Entry point for CHECK 31 & `s1_registry.py check`."""
    fails = []
    infos = []
    try:
        doc = parse_json_lf(root_dir, REGISTRY_REL)
        ledger_ids = load_ledger_td_ids(root_dir)
    except RegistryError as exc:
        return [str(exc)], infos

    fails.extend(validate_doc(doc, ledger_ids, root_dir=root_dir))

    try:
        checkpoint_oid = read_checkpoint_oid(root_dir)
        prior_doc, status_note = read_checkpoint_registry(root_dir, checkpoint_oid)
    except RegistryError as exc:
        fails.append(str(exc))
        return fails, infos

    if prior_doc is None:
        infos.append(f'checkpoint {checkpoint_oid[:7]} 尚無 {REGISTRY_REL}（{status_note}：略過歷史遞增比對）')
    else:
        mono_fails = check_monotonic(prior_doc, doc)
        fails.extend(mono_fails)
        infos.append(f'只增不減比對完成（{status_note}，prior_causes={len(prior_doc.get("causes", []))}）')

    causes = doc.get('causes') if isinstance(doc.get('causes'), list) else []
    conf_true = sum(1 for c in causes if isinstance(c, dict) and c.get('confirmed') is True)
    conf_false = sum(1 for c in causes if isinstance(c, dict) and c.get('confirmed') is False)
    uncls = sum(1 for c in causes if isinstance(c, dict) and c.get('class') == 'UNCLASSIFIED')
    infos.append(
        f'{REGISTRY_REL} schema={doc.get("schema")} causes={len(causes)} '
        f'confirmed={conf_true}/{len(causes)} unconfirmed={conf_false} unclassified={uncls}'
    )
    return fails, infos


def summary(root_dir: str, as_of: str = None, compare_checkpoint: bool = True) -> dict:
    """Compute class counts (excluding UNCLASSIFIED from recurring), class changes vs checkpoint,
    and non-blocking >7d stale unfixed verification warnings."""
    doc = parse_json_lf(root_dir, REGISTRY_REL)
    ledger_ids = load_ledger_td_ids(root_dir)
    schema_fails = validate_doc(doc, ledger_ids, root_dir=root_dir)
    if schema_fails:
        raise RegistryError(schema_fails[0])

    as_of_date = _parse_iso_date(as_of, '--as-of') if as_of is not None else datetime.date.today()
    causes = doc['causes']

    by_status = {st: 0 for st in VALID_STATUSES}
    by_class = {cls: {'causes': 0, 'incidents': 0, 'ids': []} for cls in RECURRING_CLASSES}
    unclassified_ids = []
    stale_unfixed_7d = []

    for c in causes:
        by_status[c['status']] += 1
        cls = c['class']
        if cls == 'UNCLASSIFIED':
            unclassified_ids.append(c['id'])
        else:
            by_class[cls]['causes'] += 1
            by_class[cls]['incidents'] += len(c['tasks'])
            by_class[cls]['ids'].append(c['id'])

        if c['status'] not in ('fixed', 'accepted'):
            vdate = _parse_iso_date(c['verified']['date'], f'{c["id"]} verified.date')
            age = (as_of_date - vdate).days
            if age > STALE_DAYS:
                stale_unfixed_7d.append({
                    'id': c['id'],
                    'status': c['status'],
                    'verified_date': c['verified']['date'],
                    'age_days': age,
                })

    recurring = [
        cls for cls in RECURRING_CLASSES
        if by_class[cls]['causes'] >= 2 or by_class[cls]['incidents'] >= 2
    ]

    checkpoint_compared = False
    checkpoint_oid = None
    class_changes = []
    if compare_checkpoint:
        checkpoint_oid = read_checkpoint_oid(root_dir)
        prior_doc, _ = read_checkpoint_registry(root_dir, checkpoint_oid)
        if prior_doc is not None:
            checkpoint_compared = True
            prior_classes = {
                pc['id']: pc.get('class')
                for pc in prior_doc.get('causes', [])
                if isinstance(pc, dict) and isinstance(pc.get('id'), str)
            }
            for c in causes:
                cid = c['id']
                if cid in prior_classes and prior_classes[cid] != c['class']:
                    class_changes.append({'id': cid, 'from': prior_classes[cid], 'to': c['class']})

    return {
        'schema': doc['schema'],
        'updated': doc['updated'],
        'as_of': as_of_date.isoformat(),
        'total': len(causes),
        'confirmed_true': sum(1 for c in causes if c['confirmed'] is True),
        'confirmed_false': sum(1 for c in causes if c['confirmed'] is False),
        'by_status': by_status,
        'by_class': by_class,
        'unclassified': {'count': len(unclassified_ids), 'ids': unclassified_ids},
        'recurring_classes': recurring,
        'checkpoint_compared': checkpoint_compared,
        'checkpoint_oid': checkpoint_oid,
        'class_changes': class_changes,
        'stale_unfixed_7d': stale_unfixed_7d,
    }


def format_summary_lines(data: dict) -> list:
    cls_str = ','.join(f'{k}:{data["by_class"][k]["causes"]}' for k in RECURRING_CLASSES)
    rec_str = ','.join(data['recurring_classes']) or 'NONE'
    lines = [
        'S1_REGISTRY_SUMMARY total=%d confirmed=%d/%d classes=%s unclassified=%d '
        'recurring=%s class_changes=%d stale_7d=%d' % (
            data['total'],
            data['confirmed_true'],
            data['total'],
            cls_str,
            data['unclassified']['count'],
            rec_str,
            len(data['class_changes']),
            len(data['stale_unfixed_7d']),
        )
    ]
    for item in data['class_changes']:
        lines.append(f'S1_CLASS_CHANGE id={item["id"]} from={item["from"]} to={item["to"]}')
    for item in data['stale_unfixed_7d']:
        lines.append(
            f'S1_STALE_7D id={item["id"]} status={item["status"]} '
            f'verified={item["verified_date"]} age_days={item["age_days"]}'
        )
    return lines


def _parse_cmd_argv(raw: str, label: str) -> list:
    if not isinstance(raw, str) or not raw.strip():
        raise RegistryError(f'{label}_MISSING')
    try:
        argv = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RegistryError(f'{label}_INVALID_JSON') from exc
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
        raise RegistryError(f'{label}_INVALID_ARGV')
    return argv


def _run_bounded_rv_cmd(root_dir: str, argv: list, timeout: int, label: str) -> tuple:
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    added = False
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
        added = True
    try:
        from bounded_process import run_bounded
    finally:
        if added and sys.path and sys.path[0] == scripts_dir:
            sys.path.pop(0)

    res = run_bounded(argv, root_dir, timeout, merge_stderr=True)
    if getattr(res, 'launch_error', None):
        raise RegistryError(f'{label}_LAUNCH_ERROR')
    if getattr(res, 'timed_out', False):
        raise RegistryError(f'{label}_TIMEOUT')
    out_raw = res.stdout
    if isinstance(out_raw, str):
        out_bytes = out_raw.encode('utf-8', 'replace')
    elif isinstance(out_raw, (bytes, bytearray)):
        out_bytes = bytes(out_raw)
    else:
        out_bytes = b''
    return res.returncode, hashlib.sha256(out_bytes).hexdigest()


def _create_once_json_lf(out_path: str, payload: dict) -> None:
    if not os.path.isabs(out_path):
        out_abs = os.path.abspath(out_path)
    else:
        out_abs = out_path
    parent = os.path.dirname(out_abs)
    if parent:
        os.makedirs(parent, exist_ok=True)
    reparse_flag = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
    try:
        st = os.lstat(out_abs)
        is_reparse = bool(reparse_flag and (getattr(st, 'st_file_attributes', 0) & reparse_flag))
        if stat.S_ISLNK(st.st_mode) or is_reparse:
            raise RegistryError('OUT_SYMLINK_UNSAFE')
        raise RegistryError('OUT_EXISTS')
    except FileNotFoundError:
        pass
    except RegistryError:
        raise
    except OSError as exc:
        raise RegistryError('OUT_STAT_FAILED') from exc

    raw = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0)
    try:
        fd = os.open(out_abs, flags, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise RegistryError('OUT_EXISTS') from exc
    except OSError as exc:
        raise RegistryError('OUT_WRITE_FAILED') from exc


def reverse_verify(
    root_dir: str,
    *,
    fix_task: str,
    regression_tests: list,
    not_injectable: bool = False,
    reason: str | None = None,
    injection_method: str | None = None,
    old_cmd: str | None = None,
    new_cmd: str | None = None,
    mutant_cmd: str | None = None,
    timeout: int = 300,
    out_path: str | None = None,
) -> dict:
    """Execute or record D4 reverse verification mechanically and fail closed."""
    if not os.path.isdir(root_dir):
        raise RegistryError('REPO_MISSING')
    if not isinstance(fix_task, str) or not TASK_ID_RE.match(fix_task):
        raise RegistryError('FIX_TASK_INVALID')
    if type(timeout) is not int or timeout < 1:
        raise RegistryError('TIMEOUT_INVALID')

    tests = list(regression_tests or [])
    if len(set(tests)) != len(tests):
        raise RegistryError('REGRESSION_TESTS_DUPLICATE')
    for nid in tests:
        err = verify_regression_nodeid(root_dir, nid)
        if err is not None:
            raise RegistryError('AST_NODEID_INVALID')

    if not_injectable:
        if any(x is not None for x in (injection_method, old_cmd, new_cmd, mutant_cmd)):
            raise RegistryError('CONFLICTING_MODE_FLAGS')
        if not _is_nonempty_str(reason):
            raise RegistryError('REASON_REQUIRED')
        rv = {
            'fixTask': fix_task,
            'injectable': False,
            'status': 'not_injectable',
            'notInjectableReason': reason,
        }
        if tests:
            rv['regressionTests'] = tests
    else:
        if reason is not None:
            raise RegistryError('CONFLICTING_MODE_FLAGS')
        if not tests:
            raise RegistryError('REGRESSION_TESTS_REQUIRED')
        if not _is_nonempty_str(injection_method):
            raise RegistryError('INJECTION_METHOD_REQUIRED')
        old_argv = _parse_cmd_argv(old_cmd, 'OLD_CMD')
        new_argv = _parse_cmd_argv(new_cmd, 'NEW_CMD')
        mut_argv = _parse_cmd_argv(mutant_cmd, 'MUTANT_CMD')

        old_rc, old_sha = _run_bounded_rv_cmd(root_dir, old_argv, timeout, 'OLD_CMD')
        if old_rc == 0:
            raise RegistryError('OLD_DID_NOT_FAIL')
        new_rc, new_sha = _run_bounded_rv_cmd(root_dir, new_argv, timeout, 'NEW_CMD')
        if new_rc != 0:
            raise RegistryError('NEW_FAILED')
        mut_rc, mut_sha = _run_bounded_rv_cmd(root_dir, mut_argv, timeout, 'MUTANT_CMD')
        if mut_rc == 0:
            raise RegistryError('MUTANT_SURVIVED')

        rv = {
            'fixTask': fix_task,
            'injectable': True,
            'injectionMethod': injection_method,
            'oldResult': 'FAIL',
            'oldOutputSha256': old_sha,
            'newResult': 'PASS',
            'newOutputSha256': new_sha,
            'mutantResult': 'FAIL',
            'mutantOutputSha256': mut_sha,
            'regressionTests': tests,
        }

    fails = validate_reverse_verification('CLI', rv, root_dir=root_dir)
    if fails:
        raise RegistryError('VALIDATION_FAILED')
    if out_path is not None:
        _create_once_json_lf(out_path, rv)
    return rv


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='D8 S1 root-cause registry checker, summary, and D4 reverse-verify')
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_check = sub.add_parser('check', help='validate S1 registry (same as CHECK 31)')
    p_check.add_argument('--repo', default='.')

    p_sum = sub.add_parser('summary', help='print class summary, class changes, and >7d warnings')
    p_sum.add_argument('--repo', default='.')
    p_sum.add_argument('--as-of', default=None)
    p_sum.add_argument('--no-checkpoint', action='store_true')
    p_sum.add_argument('--json', action='store_true')

    p_rv = sub.add_parser('reverse-verify', help='run bounded D4 old/new/mutant verification and emit schema-2 block')
    p_rv.add_argument('--repo', default='.')
    p_rv.add_argument('--fix-task', required=True)
    p_rv.add_argument('--regression-test', action='append', default=[])
    p_rv.add_argument('--not-injectable', action='store_true')
    p_rv.add_argument('--reason', default=None)
    p_rv.add_argument('--injection-method', default=None)
    p_rv.add_argument('--old-cmd', default=None)
    p_rv.add_argument('--new-cmd', default=None)
    p_rv.add_argument('--mutant-cmd', default=None)
    p_rv.add_argument('--timeout', type=int, default=300)
    p_rv.add_argument('--json', action='store_true')
    p_rv.add_argument('--out', default=None)

    args = parser.parse_args(argv)
    root = os.path.abspath(args.repo)
    if args.cmd == 'check':
        fails, infos = check(root)
        for info in infos:
            print(f'[INFO] {info}')
        if fails:
            print(f'S1_REGISTRY CHECK FAIL count={len(fails)}')
            for fail in fails:
                print(f'  {fail}')
            return 1
        print('S1_REGISTRY CHECK PASS')
        return 0

    if args.cmd == 'reverse-verify':
        try:
            rv = reverse_verify(
                root,
                fix_task=args.fix_task,
                regression_tests=args.regression_test,
                not_injectable=args.not_injectable,
                reason=args.reason,
                injection_method=args.injection_method,
                old_cmd=args.old_cmd,
                new_cmd=args.new_cmd,
                mutant_cmd=args.mutant_cmd,
                timeout=args.timeout,
                out_path=args.out,
            )
        except RegistryError as exc:
            print(f'S1_REVERSE_VERIFY FAIL {exc}')
            return 1
        if args.json:
            print(json.dumps(rv, ensure_ascii=False, sort_keys=True))
        elif rv['injectable']:
            print(
                f'S1_REVERSE_VERIFY PASS fix_task={rv["fixTask"]} injectable=true '
                f'old={rv["oldResult"]} new={rv["newResult"]} mutant={rv["mutantResult"]} '
                f'old_sha={rv["oldOutputSha256"]} new_sha={rv["newOutputSha256"]} '
                f'mutant_sha={rv["mutantOutputSha256"]} tests={len(rv["regressionTests"])}'
            )
        else:
            print(
                f'S1_REVERSE_VERIFY PASS fix_task={rv["fixTask"]} injectable=false '
                f'status={rv["status"]} tests={len(rv.get("regressionTests", []))}'
            )
        return 0

    try:
        data = summary(root, as_of=args.as_of, compare_checkpoint=not args.no_checkpoint)
    except RegistryError as exc:
        print(f'S1_REGISTRY SUMMARY FAIL {exc}')
        return 1
    if args.json:
        print(json.dumps(data, ensure_ascii=False, sort_keys=True))
    else:
        for line in format_summary_lines(data):
            print(line)
    return 0


if __name__ == '__main__':
    sys.exit(main())
