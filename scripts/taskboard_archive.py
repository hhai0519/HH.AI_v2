"""
用途：任務看板封存工具與 check_consistency CHECK 29 的實作（B-117 G7-b1）。

封存不是刪除：`docs/TASKBOARD.md` 的表格列經 USER 確認後，逐字移到 `docs/archive/TASKBOARD-ARCHIVE-NNNN.md`
的封存檔（一個封存檔由一個批次一次寫成，之後不改），清單與每列的 SHA-256 在
`docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json`。規則見 `.claude/rules/auditor-protocol.md` 第 10.4 節。

封存條件（USER 2026-11-16 決定）：
  1. 狀態為「已完成」或「可封存」；
  2. 依據二擇一：
     MACRO_PASS_ANCESTOR  列內出現的完整 40 位 commit 在 AUDIT-LOG 有「核對通過」列（短碼經 rev-parse
                          解析成完整 OID 才比對），該列須點名本列 ID（B-122 或 B122 皆可），且 commit 是
                          refactor-backlog 第 5.1 節 checkpoint 的祖先（或等於 checkpoint）；
     USER_CONFIRMED_LEGACY 本批 USER 逐列確認之舊列（USER-2026-11-17-G7B-D1；只此一次，
                          ID 清單固定在本檔 LEGACY_IDS，之後不得新增）；
  3. 沒有「待辦／進行中／待裁決／OPEN」的表格列引用該 ID；
  4. 不在 manifest 的 user_keep（USER 標記保留）內。

條件 3、4 與「USER 確認」在 plan／apply 當下判定；CHECK 29 事後核對清單、原文位元組、封存依據與指向。
第一個封存檔（含全部 USER_CONFIRMED_LEGACY 條目）寫成後固定：批次、SHA-256 與筆數釘在本檔常數，
USER_CONFIRMED_LEGACY 只能出現在第一個封存檔。

命令列（唯讀者標 ◎）：
  python scripts/taskboard_archive.py plan  --repo <repo>                        ◎ 列出每一列的判定
  python scripts/taskboard_archive.py check --repo <repo>                        ◎ CHECK 29 同一判定
  python scripts/taskboard_archive.py apply --repo <repo> --task-id <TASK> --checkpoint-oid <oid>
                                            --entry <ID>[:<evidence-oid>] ...    寫入工作區（不 commit）

fail-closed：manifest、封存檔、AUDIT-LOG、checkpoint 讀不到或格式不符，git 回答不出來，
一律 FAIL；不適用的只有「沒有任何需要 git 的條目」。
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

TASKBOARD_REL = 'docs/TASKBOARD.md'
ARCHIVE_DIR_REL = 'docs/archive'
ARCHIVE_PREFIX = ARCHIVE_DIR_REL + '/TASKBOARD-ARCHIVE-'
MANIFEST_REL = ARCHIVE_PREFIX + 'MANIFEST.json'
README_REL = ARCHIVE_PREFIX + 'README.md'
ARCHIVE_INDEX_REL = 'docs/ARCHIVE-INDEX.md'
AUDIT_LOG_REL = 'docs/AUDIT-LOG.md'
BACKLOG_REL = 'docs/refactor-backlog.md'

SCHEMA_VERSION = 1
BASIS_EVIDENCE = 'MACRO_PASS_ANCESTOR'
BASIS_LEGACY = 'USER_CONFIRMED_LEGACY'
LEGACY_DECISION = 'USER-2026-11-17-G7B-D1'
# 第一個封存檔（USER 一次性確認）寫成後即固定：批次、位元組與筆數釘在這裡，之後改封存檔或清單都會 FAIL。
LEGACY_BATCH = 'B117-G7B1-ARCHIVE-MECHANISM-R2-261117'
FIRST_ARCHIVE_SHA256 = 'c0d538caee3aba8e995b3ea1b9bf0bbdee32781a78c5dbadbb48d30089e6b5d1'  # 測試以 None 表示「尚未寫成」
FIRST_ARCHIVE_ENTRIES = 36
LEGACY_IDS = frozenset({
    'B-06', 'B-10', 'B-12', 'B-16', 'B-17', 'B-21', 'B-26', 'B-35', 'B-38', 'B-39',
    'B-48', 'B-49', 'B-55', 'B-57', 'B-71', 'B-76', 'B-80', 'B-81', 'B-83', 'B-84',
    'B-87', 'B-91', 'B-105', 'D-03', 'E-02', 'F-02', 'F-04', 'G-01', 'G-02', 'G-03', 'G-04',
})
ARCHIVABLE_STATUSES = ('已完成', '可封存')
ACTIVE_PREFIXES = ('待辦', '進行中', '待裁決', 'OPEN')

ROW_RE = re.compile(r'^\| ([A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*) \| ([^|]*?) \|')
OID_RE = re.compile(r'^[0-9a-f]{40}$')
HEX_TOKEN_RE = re.compile(r'\b[0-9a-f]{40}\b')
SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
CHECKPOINT_RE = re.compile(r'^上次核對通過的 HEAD：([0-9a-f]{40})\s*$', re.M)
FENCE = '````text'
FENCE_END = '````'
ENTRY_KEYS = ('id', 'section', 'source_line', 'status_at_archive', 'basis', 'evidence_commit',
              'user_decision', 'row_sha256', 'row_bytes')


class Fail(Exception):
    pass


def sha256_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def read_text(root, rel):
    path = os.path.join(root, *rel.split('/'))
    try:
        with open(path, 'rb') as handle:
            raw = handle.read()
    except OSError as exc:
        raise Fail('%s 無法讀取（%s）' % (rel, type(exc).__name__))
    if raw.startswith(b'\xef\xbb\xbf'):
        raise Fail('%s 含 BOM' % rel)
    if b'\r' in raw:
        raise Fail('%s 含 CR（必須是 LF）' % rel)
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        raise Fail('%s 不是合法 UTF-8' % rel)


def parse_rows(text):
    """表格列（含來源行號與所在的 ## 章節）。"""
    rows, section = [], ''
    for number, line in enumerate(text.split('\n'), 1):
        if line.startswith('## '):
            section = line[3:].strip()
        match = ROW_RE.match(line)
        if match:
            rows.append({'line': number, 'id': match.group(1), 'status': match.group(2).strip(),
                         'text': line, 'section': section})
    return rows


def is_active(status):
    return status.startswith(ACTIVE_PREFIXES)


def ref_pattern(row_id):
    return re.compile(r'(?<![A-Za-z0-9-])' + re.escape(row_id) + r'(?![0-9A-Za-z])')


REF_CONTEXT_WIDTH = 30


def ref_context(text, row_id, width=REF_CONTEXT_WIDTH):
    """被引用處（第一個命中）前後各 width 個字元，供審查官判斷是不是真的引用。"""
    match = ref_pattern(row_id).search(text)
    if not match:
        return ''
    return text[max(0, match.start() - width):min(len(text), match.end() + width)]


def git(root, *args):
    try:
        proc = subprocess.run(['git', '-C', root] + list(args), capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Fail('git 無法執行（%s）' % type(exc).__name__)
    return proc.returncode, proc.stdout.decode('utf-8', 'replace').strip()


def resolve_commit(root, rev):
    code, out = git(root, 'rev-parse', '--verify', '-q', rev + '^{commit}')
    return out if code == 0 and OID_RE.match(out) else None


def is_ancestor(root, older, newer):
    code, _ = git(root, 'merge-base', '--is-ancestor', older, newer)
    if code == 0:
        return True
    if code == 1:
        return False
    raise Fail('git merge-base 無法回答（%s 與 %s）' % (older[:7], newer[:7]))


def audit_pass_rows(audit_text):
    """AUDIT-LOG 的「核對通過」列：[(列首的 7 至 40 位 hex, 該列原文)]。不呼叫 git。"""
    rows = []
    for line in audit_text.split('\n'):
        match = re.match(r'^\| ([0-9a-f]{7,40}) \|', line)
        if match and '核對通過' in line:
            rows.append((match.group(1), line))
    return rows


def pass_text_for(root, oid, pass_rows):
    """指向 oid 的核對通過列原文（空字串＝沒有）。完整 40 位直接比字串；短碼只在它是 oid 的前綴時，
    才以 rev-parse 確認解析結果等於 oid（有歧義或解析不到就不算），所以不是用字串前綴下結論。"""
    found = []
    for token, line in pass_rows:
        if token == oid:
            found.append(line)
        elif len(token) < 40 and oid.startswith(token) and resolve_commit(root, token) == oid:
            found.append(line)
    return '\n'.join(found)


def id_named(row_id, text):
    names = sorted({row_id, row_id.replace('-', '')}, key=len, reverse=True)
    pattern = r'(?<![A-Za-z0-9-])(?:' + '|'.join(re.escape(n) for n in names) + r')(?![0-9A-Za-z])'
    return re.search(pattern, text) is not None


def read_checkpoint(backlog_text):
    found = CHECKPOINT_RE.findall(backlog_text)
    if len(found) != 1:
        raise Fail('%s 的「上次核對通過的 HEAD：」必須恰好一行（找到 %d）' % (BACKLOG_REL, len(found)))
    return found[0]


def evidence_ok(root, oid, row_text, row_id, pass_rows, checkpoint):
    """回傳違反條件的原因（空字串＝符合）。先做不需要 git 的比對，最後才問 git。"""
    if not OID_RE.match(oid or ''):
        return 'EVIDENCE_NOT_FULL_OID'
    if oid not in row_text:
        return 'EVIDENCE_NOT_IN_ROW'
    pass_text = pass_text_for(root, oid, pass_rows)
    if not pass_text:
        return 'EVIDENCE_NO_MACRO_PASS'
    if not id_named(row_id, pass_text):
        return 'EVIDENCE_PASS_ROW_DOES_NOT_NAME_ROW'
    if resolve_commit(root, oid) != oid:
        return 'EVIDENCE_NOT_RESOLVABLE'
    if not is_ancestor(root, oid, checkpoint):
        return 'EVIDENCE_NOT_CHECKPOINT_ANCESTOR'
    return ''


def find_evidence(root, row_text, row_id, pass_rows, checkpoint):
    seen = []
    for token in HEX_TOKEN_RE.findall(row_text):
        if token in seen:
            continue
        seen.append(token)
        if not evidence_ok(root, token, row_text, row_id, pass_rows, checkpoint):
            return token
    return None


def load_manifest(root):
    raw = read_text(root, MANIFEST_REL)
    try:
        doc = json.loads(raw)
    except ValueError:
        raise Fail('%s 不是合法 JSON' % MANIFEST_REL)
    if not isinstance(doc, dict) or doc.get('schema_version') != SCHEMA_VERSION:
        raise Fail('%s schema_version 必須是 %d' % (MANIFEST_REL, SCHEMA_VERSION))
    if not isinstance(doc.get('user_keep'), list) or not isinstance(doc.get('archives'), list):
        raise Fail('%s 必須有 user_keep 與 archives 陣列' % MANIFEST_REL)
    return doc


def dump_manifest(doc):
    return json.dumps(doc, ensure_ascii=False, indent=1) + '\n'


def render_archive(number, archive, rows_by_id):
    lines = [
        '# 任務看板封存 %04d' % number, '',
        '> 本檔由 `scripts/taskboard_archive.py apply` 產生，寫成後不得修改。清單與每列的 SHA-256 在 `TASKBOARD-ARCHIVE-MANIFEST.json`，由 CHECK 29 逐位元組核對。',
        '> 封存不是刪除：下列各列是封存當時 `docs/TASKBOARD.md` 的原文（單行），逐字保留。',
        '> 封存批次：%s；封存當時 checkpoint：`%s`' % (archive['batch'], archive['checkpoint_oid']), '',
        '## 封存列', '']
    for entry in archive['entries']:
        why = entry['user_decision'] if entry['basis'] == BASIS_LEGACY else entry['evidence_commit']
        lines += ['### ' + entry['id'], '',
                  '- 原位置：`%s`「%s」第 %d 行（封存前）' % (TASKBOARD_REL, entry['section'], entry['source_line']),
                  '- 封存時狀態：' + entry['status_at_archive'],
                  '- 封存依據：%s（%s）' % (entry['basis'], why), '',
                  FENCE, rows_by_id[entry['id']], FENCE_END, '']
    return '\n'.join(lines).rstrip('\n') + '\n'


def parse_archive_rows(text):
    lines = text.split('\n')
    rows = []
    for index, line in enumerate(lines):
        if line == FENCE:
            if index + 2 >= len(lines) or lines[index + 2] != FENCE_END or lines[index + 1] == FENCE_END:
                raise Fail('封存檔圍欄結構錯誤（第 %d 行）' % (index + 1))
            rows.append(lines[index + 1])
    return rows


def _is_text(value):
    return isinstance(value, str) and value != ''


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def check_entry_fields(entry, where, fails):
    if not isinstance(entry, dict) or sorted(entry) != sorted(ENTRY_KEYS):
        fails.append('%s 欄位必須恰為 %s' % (where, '、'.join(ENTRY_KEYS)))
        return False
    good = (_is_text(entry['id']) and _is_text(entry['section']) and _is_int(entry['source_line'])
            and _is_text(entry['status_at_archive']) and _is_text(entry['basis'])
            and (entry['evidence_commit'] is None or (isinstance(entry['evidence_commit'], str) and OID_RE.match(entry['evidence_commit'])))
            and (entry['user_decision'] is None or _is_text(entry['user_decision']))
            and isinstance(entry['row_sha256'], str) and SHA256_RE.match(entry['row_sha256'])
            and _is_int(entry['row_bytes']))
    if not good:
        fails.append('%s 欄位型別不符（字串、整數、null 或 40 位 hex 之一）' % where)
        return False
    return True


def on_board(taskboard, row_id):
    """寬鬆偵測：首格為該 ID 的表格列（容許空白數量不同），不依賴 ROW_RE。"""
    return re.search(r'^\|\s*' + re.escape(row_id) + r'\s*\|', taskboard, re.M) is not None


def check(root):
    """CHECK 29 的判定。回傳 (fails, infos)；任何未預期的例外也轉成 FAIL。"""
    try:
        return _check(root)
    except Exception as exc:  # fail-closed：不讓例外變成 traceback 或 PASS
        return ['CHECK 29 內部錯誤（%s）' % type(exc).__name__], []


def _check(root):
    fails, infos = [], []
    try:
        manifest = load_manifest(root)
        taskboard = read_text(root, TASKBOARD_REL)
        index_text = read_text(root, ARCHIVE_INDEX_REL)
        audit_text = read_text(root, AUDIT_LOG_REL)
        backlog_text = read_text(root, BACKLOG_REL)
    except Fail as exc:
        return ['%s' % exc], infos
    keep = manifest['user_keep']
    if not all(isinstance(k, str) for k in keep):
        fails.append('%s user_keep 必須是 ID 字串陣列' % MANIFEST_REL)
        keep = []
    seen_ids, needs_git, total = set(), False, 0
    if FIRST_ARCHIVE_SHA256 is not None and not manifest['archives']:
        fails.append('%s 沒有任何封存檔：第一個封存檔已固定，不得移除或清空' % MANIFEST_REL)
    pass_rows = audit_pass_rows(audit_text)
    checkpoint = None
    for position, archive in enumerate(manifest['archives'], 1):
        where = '%s archives[%d]' % (MANIFEST_REL, position - 1)
        expected_rel = '%s%04d.md' % (ARCHIVE_PREFIX, position)
        keys = ('file', 'batch', 'checkpoint_oid', 'file_sha256', 'entries')
        if not isinstance(archive, dict) or sorted(archive) != sorted(keys):
            fails.append('%s 欄位必須恰為 %s' % (where, '、'.join(keys)))
            continue
        if archive['file'] != expected_rel:
            fails.append('%s file 必須是 %s' % (where, expected_rel))
            continue
        if (not isinstance(archive['checkpoint_oid'], str) or not OID_RE.match(archive['checkpoint_oid'])
                or not _is_text(archive['batch']) or not isinstance(archive['file_sha256'], str)
                or not SHA256_RE.match(archive['file_sha256'])):
            fails.append('%s batch、checkpoint_oid 或 file_sha256 格式不符' % where)
            continue
        entries = archive['entries']
        if not isinstance(entries, list) or not entries:
            fails.append('%s entries 必須是非空陣列' % where)
            continue
        try:
            text = read_text(root, archive['file'])
            file_rows = parse_archive_rows(text)
        except Fail as exc:
            fails.append('%s' % exc)
            continue
        if sha256_text(text) != archive['file_sha256']:
            fails.append('%s file_sha256 與封存檔不符' % where)
        if position == 1 and (archive['batch'] != LEGACY_BATCH or archive['file_sha256'] != FIRST_ARCHIVE_SHA256
                              or len(entries) != FIRST_ARCHIVE_ENTRIES):
            fails.append('%s 第一個封存檔已固定（批次、SHA-256、筆數），不得修改' % where)
        if len(file_rows) != len(entries):
            fails.append('%s 封存檔列數 %d 與清單 %d 不符' % (where, len(file_rows), len(entries)))
            continue
        rows_by_id, entries_ok = {}, True
        for entry, row_text in zip(entries, file_rows):
            if not check_entry_fields(entry, where + ' entry', fails):
                entries_ok = False
                continue
            rid = entry['id']
            total += 1
            if rid in seen_ids:
                fails.append('%s 重複封存 %s' % (where, rid))
            seen_ids.add(rid)
            rows_by_id[rid] = row_text
            parsed = ROW_RE.match(row_text)
            if not parsed or parsed.group(1) != rid or parsed.group(2).strip() != entry['status_at_archive']:
                fails.append('%s %s：原文列的 ID 或狀態與清單不符' % (where, rid))
            if sha256_text(row_text) != entry['row_sha256'] or len(row_text.encode('utf-8')) != entry['row_bytes']:
                fails.append('%s %s：原文與清單的 SHA-256 或位元組數不符' % (where, rid))
            if entry['status_at_archive'] not in ARCHIVABLE_STATUSES:
                fails.append('%s %s：封存時狀態必須是 %s' % (where, rid, '／'.join(ARCHIVABLE_STATUSES)))
            if on_board(taskboard, rid):
                fails.append('%s %s：看板仍有同 ID 的列（封存必須是移動）' % (where, rid))
            if rid in keep:
                fails.append('%s %s：USER 標記保留，不得封存' % (where, rid))
            if entry['basis'] == BASIS_LEGACY:
                if position != 1:
                    fails.append('%s %s：USER_CONFIRMED_LEGACY 只能出現在第一個封存檔' % (where, rid))
                if rid not in LEGACY_IDS or entry['user_decision'] != LEGACY_DECISION or entry['evidence_commit'] is not None:
                    fails.append('%s %s：USER_CONFIRMED_LEGACY 只限固定清單、決定編號 %s、且不得附 evidence_commit' % (where, rid, LEGACY_DECISION))
            elif entry['basis'] == BASIS_EVIDENCE:
                if entry['user_decision'] is not None:
                    fails.append('%s %s：MACRO_PASS_ANCESTOR 不得附 user_decision' % (where, rid))
                needs_git = True
            else:
                fails.append('%s %s：basis 必須是 %s 或 %s' % (where, rid, BASIS_EVIDENCE, BASIS_LEGACY))
        if not entries_ok:
            continue
        if render_archive(position, archive, rows_by_id) != text:
            fails.append('%s 封存檔內容與清單重新產生的結果不一致' % where)
        if needs_git:
            try:
                if checkpoint is None:
                    checkpoint = read_checkpoint(backlog_text)
                    if resolve_commit(root, checkpoint) != checkpoint:
                        raise Fail('checkpoint %s 無法解析' % checkpoint[:7])
                if not is_ancestor(root, archive['checkpoint_oid'], checkpoint):
                    fails.append('%s checkpoint_oid 不是目前 checkpoint 的祖先' % where)
                for entry in entries:
                    if entry['basis'] != BASIS_EVIDENCE:
                        continue
                    reason = evidence_ok(root, str(entry['evidence_commit']), rows_by_id[entry['id']], entry['id'], pass_rows, checkpoint)
                    if reason:
                        fails.append('%s %s：%s' % (where, entry['id'], reason))
            except Fail as exc:
                fails.append('%s' % exc)
    section = taskboard.split('\n## 封存區', 1)
    if len(section) != 2 or ARCHIVE_PREFIX not in section[1]:
        fails.append('%s 的「## 封存區」必須指向 %s*' % (TASKBOARD_REL, ARCHIVE_PREFIX))
    if ARCHIVE_PREFIX not in index_text:
        fails.append('%s 必須指向 %s*' % (ARCHIVE_INDEX_REL, ARCHIVE_PREFIX))
    if not os.path.isfile(os.path.join(root, *README_REL.split('/'))):
        fails.append('%s 不存在' % README_REL)
    infos.append('封存檔 %d 個、封存列 %d 列、USER 保留 %d 列' % (len(manifest['archives']), total, len(keep)))
    return fails, infos


def evaluate(root, taskboard_rows, manifest, pass_rows, checkpoint):
    """逐列判定。回傳 [{row, holds, evidence, basis}]。"""
    keep = set(manifest['user_keep'])
    counts = {}
    for row in taskboard_rows:
        counts[row['id']] = counts.get(row['id'], 0) + 1
    out = []
    for row in taskboard_rows:
        if row['status'] not in ARCHIVABLE_STATUSES:
            continue
        holds = []
        if counts[row['id']] != 1:
            holds.append('AMBIGUOUS_ID')
        if row['id'] in keep:
            holds.append('USER_KEEP')
        pattern = ref_pattern(row['id'])
        referrers = sorted({o['id'] for o in taskboard_rows
                            if o['line'] != row['line'] and is_active(o['status']) and pattern.search(o['text'])})
        if referrers:
            holds.append('ACTIVE_REF:' + ','.join(referrers))
        evidence = find_evidence(root, row['text'], row['id'], pass_rows, checkpoint)
        legacy_open = row['id'] in LEGACY_IDS and not manifest['archives']
        basis = BASIS_EVIDENCE if evidence else (BASIS_LEGACY if legacy_open else None)
        if basis is None:
            holds.append('NO_EVIDENCE')
        out.append({'row': row, 'holds': holds, 'evidence': evidence, 'basis': basis})
    return out


def plan(root, out):
    try:
        manifest = load_manifest(root)
        taskboard = read_text(root, TASKBOARD_REL)
        audit_text = read_text(root, AUDIT_LOG_REL)
        checkpoint = read_checkpoint(read_text(root, BACKLOG_REL))
        pass_rows = audit_pass_rows(audit_text)
        items = evaluate(root, parse_rows(taskboard), manifest, pass_rows, checkpoint)
    except Exception as exc:  # Fail 與其他例外皆不得留下 traceback
        out.write('TASKBOARD_ARCHIVE PLAN FAIL %s\n' % (exc if isinstance(exc, Fail) else type(exc).__name__))
        return 1
    for item in items:
        row = item['row']
        state = 'HOLD ' + ' '.join(item['holds']) if item['holds'] else 'ELIGIBLE ' + item['basis']
        out.write('PLAN %s line=%d bytes=%d %s\n' % (row['id'], row['line'], len(row['text'].encode('utf-8')), state))
    rows = parse_rows(taskboard)
    for item in items:
        row = item['row']
        pattern = ref_pattern(row['id'])
        for other in rows:
            if is_active(other['status']) and pattern.search(other['text']):  # 本列狀態必為已完成或可封存，不會是自己
                out.write('REF_CONTEXT %s<-%s line=%d …%s…\n' % (row['id'], other['id'], other['line'], ref_context(other['text'], row['id'])))
    return 0


def apply(root, task_id, checkpoint_oid, entry_args, out):
    try:
        manifest = load_manifest(root)
        taskboard = read_text(root, TASKBOARD_REL)
        audit_text = read_text(root, AUDIT_LOG_REL)
        checkpoint = read_checkpoint(read_text(root, BACKLOG_REL))
        if not OID_RE.match(checkpoint_oid) or resolve_commit(root, checkpoint_oid) != checkpoint_oid:
            raise Fail('--checkpoint-oid 必須是可解析的完整 commit')
        if not task_id or not entry_args:
            raise Fail('--task-id 與至少一個 --entry 為必填')
        rows = parse_rows(taskboard)
        pass_rows = audit_pass_rows(audit_text)
        judged = {item['row']['id']: item for item in evaluate(root, rows, manifest, pass_rows, checkpoint)}
        entries, seen = [], set()
        for arg in entry_args:
            rid, _, given = arg.partition(':')
            if rid in seen or rid not in judged:
                raise Fail('%s：重複或不是可封存狀態的列' % rid)
            seen.add(rid)
            item = judged[rid]
            if item['holds']:
                raise Fail('%s：不符合封存條件（%s）' % (rid, ' '.join(item['holds'])))
            if given and given != item['evidence']:
                raise Fail('%s：指定的 evidence 與工具判定不同' % rid)
            row = item['row']
            legacy = item['basis'] == BASIS_LEGACY
            entries.append({'id': rid, 'section': row['section'], 'source_line': row['line'],
                            'status_at_archive': row['status'], 'basis': item['basis'],
                            'evidence_commit': None if legacy else item['evidence'],
                            'user_decision': LEGACY_DECISION if legacy else None,
                            'row_sha256': sha256_text(row['text']), 'row_bytes': len(row['text'].encode('utf-8'))})
        number = len(manifest['archives']) + 1
        archive = {'file': '%s%04d.md' % (ARCHIVE_PREFIX, number), 'batch': task_id,
                   'checkpoint_oid': checkpoint_oid, 'file_sha256': '', 'entries': entries}
        by_id = {row['id']: row['text'] for row in rows if row['id'] in seen}
        for rid, text in by_id.items():
            if FENCE_END in text:
                raise Fail('%s：原文含四個反引號，無法安全封存' % rid)
        text = render_archive(number, archive, by_id)
        archive['file_sha256'] = sha256_text(text)
        manifest['archives'].append(archive)
        kept = [line for line in taskboard.split('\n') if not (ROW_RE.match(line) and ROW_RE.match(line).group(1) in seen)]
        with open(os.path.join(root, *archive['file'].split('/')), 'wb') as handle:
            handle.write(text.encode('utf-8'))
        with open(os.path.join(root, *MANIFEST_REL.split('/')), 'wb') as handle:
            handle.write(dump_manifest(manifest).encode('utf-8'))
        with open(os.path.join(root, *TASKBOARD_REL.split('/')), 'wb') as handle:
            handle.write('\n'.join(kept).encode('utf-8'))
    except Exception as exc:
        out.write('TASKBOARD_ARCHIVE APPLY FAIL %s\n' % (exc if isinstance(exc, (Fail, OSError)) else type(exc).__name__))
        return 1
    out.write('TASKBOARD_ARCHIVE APPLY PASS entries=%d file=%s\n' % (len(entries), archive['file']))
    return 0


def main(argv=None, out=None):
    out = out or sys.stdout
    parser = argparse.ArgumentParser(description='任務看板封存工具')
    sub = parser.add_subparsers(dest='cmd', required=True)
    for name in ('plan', 'check', 'apply'):
        item = sub.add_parser(name)
        item.add_argument('--repo', required=True)
        if name == 'apply':
            item.add_argument('--task-id', default='')
            item.add_argument('--checkpoint-oid', default='')
            item.add_argument('--entry', action='append', default=[])
    args = parser.parse_args(argv)
    root = os.path.abspath(args.repo)
    if args.cmd == 'plan':
        return plan(root, out)
    if args.cmd == 'apply':
        return apply(root, args.task_id, args.checkpoint_oid, args.entry, out)
    fails, infos = check(root)
    for info in infos:
        out.write('INFO %s\n' % info)
    for fail in fails:
        out.write('FAIL %s\n' % fail)
    out.write('TASKBOARD_ARCHIVE CHECK %s\n' % ('FAIL' if fails else 'PASS'))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
