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

批次紀錄封存（B-117 G7-b3a）：看板的「批次紀錄」（行首符合 history_guard.C7_RECORD 的行）只留最新的 N 則，
較舊的整則（紀錄行與緊接其後、到空白行或下一則紀錄之前的續行，稱為一個單元）逐字移到
`docs/archive/TASKBOARD-RECORDS-NNNN.md`，清單在 manifest 的 `record_archives`。規則在任何時點都成立：
  - 看板永遠至少留 1 則（保留數 < 1 一律拒絕；C7 要求新紀錄緊接舊首筆之前，舊首筆不可被搬走）；
  - 搬的是「最舊的 take 則」，保留的是「最新的 keep 則」，封存檔內維持看板順序（新→舊）；
  - 封存檔由本工具確定性產生（UTF-8、LF、看板順序），CHECK 29 用 git 在 checkpoint_oid 的看板逐行核對原文，
    不信任提示詞或作者端的檔案。
  - 多行單元（續行內可能有仍有效的 USER 決定或指向）預設拒絕搬移，須用 --allow-multiline TASK_ID 逐一點名，
    records-plan 先逐行印出其前 40 個字元供人工複核。
  - 只增不減：checkpoint 看板上的每一則批次紀錄，必須仍在看板上或已在某個批次紀錄封存檔；
    manifest 的 record_archives 相對於 checkpoint 的 manifest 只能在尾端追加；看板批次紀錄上限 6 則。
  - 不得改寫（G7-b3b1）：checkpoint 看板上的批次紀錄若仍留在看板，整個單元必須與 checkpoint 逐字相同；
    checkpoint 看板上沒有的紀錄（新紀錄）只能連續排在看板批次紀錄的最前面（最新在前）。
  keep 的算法：保留的是套用本工具當下看板上的既有紀錄數，不含該批自己新增的那一則。

每批「一句話」（G7-b3b2，USER 2026-11-18 要求；CHECK 29 與 CHECK 26 一併判定）：自 ONE_LINER_ANCHOR 之後，看板最新一則批次紀錄與
EXEC-LOG 的新列，說明都必須以「一句話：……。」開頭；句子 8 至 60 個字元（不含句號），單句、不含 TASK_ID、SHA、檔案路徑、
換行與直線符號。句子由 definition.json 的 one_liner 欄位經 prompt_builder 的 {ONE_LINER} 展開寫入，不靠手寫；舊紀錄與舊列不追溯。
生效判定：ONE_LINER_ANCHOR 所指的紀錄仍在看板或已在批次紀錄封存檔（CHECK 29），或其 EXEC-LOG 列存在（CHECK 26）；
兩處的錨點都受只增不減保護（CHECK 29 紀錄不得消失、CHECK 28 EXEC-LOG 只准新增），故不能靠刪錨點關掉檢查。

待辦清冊（G7-b3b3-3，CHECK 29 一併判定；規則全文在 docs/TODO-LEDGER.md 第一節）：自 LEDGER_ANCHOR 之後的批次紀錄才受管，
錨點不在看板也不在批次紀錄封存檔時規則尚未生效（錨點本身受上述只增不減保護，不能靠刪錨點關掉檢查）。生效後：
  - 清冊格式：TD 編號依序無缺號、處置只有結案／承接／開放、各欄非空；checkpoint 之後新增的「開放」列，依據欄須寫 owner；
  - 清冊只增不減：checkpoint 清冊的每一列仍在，來源、原標籤、事項不得改；處置只能維持或改為結案；已結案之列逐字不變；
  - 新增待辦宣告：受管的批次紀錄須恰有一句「新增待辦：無。」或「新增待辦：TD-nnn、TD-nnn。」，所列編號必須恰等於清冊中
    來源為該紀錄 TASK_ID 的列（雙向對帳；漏列、多列、編號不存在、重複都 FAIL）。工具只核對這個宣告，不判讀自由文字，
    因此「紀錄內文另有待辦卻宣告為無」仍須審查官判讀（本檔不宣稱能偵測）；
  - records-apply 搬移前對帳：受管的紀錄須通過上述宣告核對；錨點之前（含錨點）的舊紀錄須在清冊有來源為它的列，
    確認沒有待辦時以 --no-new-todos TASK_ID 逐則點名（點名的紀錄在清冊不得已有列）。
    對「未結案編號即拒絕」的解讀：被搬走的紀錄所帶的待辦必須全部已有清冊編號（未登錄即拒絕），不因編號尚未結案而拒絕：
    清冊的「承接」「開放」正是為了讓待辦在紀錄被搬走後仍有去處，若未結案即拒絕，帶開放待辦的紀錄將永遠無法搬走，
    看板 6 則上限會卡死。使用順序：先把清冊列寫好，再執行 records-apply。

看板列與清單的只增不減（G7-b3b1，CHECK 29 一併判定）：checkpoint 看板上的每一個表格列 ID，必須仍在看板上或
已在某個看板列封存檔；manifest 的 archives 相對於 checkpoint 的 manifest 只能在尾端追加，user_keep 只增不減。

比對基準一律是 git 在 refactor-backlog 第 5.1 節 checkpoint 的檔案。checkpoint 不倒退不由本檔檢查，而依賴
check_consistency 的「上次核對通過的 HEAD … 已過期」判定（checkpoint 必須等於 AUDIT-LOG 中最晚、且是 HEAD
祖先的核對通過 commit）與 CHECK 28（AUDIT-LOG 只准新增，核對通過列不能被刪改）；兩者任一失效，本檔的只增不減
比對就可能以較舊的 checkpoint 為基準而放行。

命令列（唯讀者標 ◎）：
  python scripts/taskboard_archive.py plan  --repo <repo>                        ◎ 列出每一列的判定
  python scripts/taskboard_archive.py check --repo <repo>                        ◎ CHECK 29 同一判定
  python scripts/taskboard_archive.py apply --repo <repo> --task-id <TASK> --checkpoint-oid <oid>
                                            --entry <ID>[:<evidence-oid>] ...    寫入工作區（不 commit）
  python scripts/taskboard_archive.py records-plan  --repo <repo> --keep N        ◎ 盤點數字與每則的保留／搬移判定
  python scripts/taskboard_archive.py records-apply --repo <repo> --task-id <TASK> --checkpoint-oid <oid>
                                            --keep N --take M [--allow-multiline TASK_ID ...]
                                            [--no-new-todos TASK_ID ...]  寫入工作區（不 commit）

fail-closed：manifest、封存檔、AUDIT-LOG、checkpoint 讀不到或格式不符，git 回答不出來，
一律 FAIL；只增不減的比對每次都需要 git，沒有不適用的情形。
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

try:
    from scripts.history_guard import C7_RECORD  # 批次紀錄的判定與 C7 守衛共用同一個正規式，不複製
except ImportError:
    from history_guard import C7_RECORD

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

# 批次紀錄封存（G7-b3a）
RECORDS_PREFIX = ARCHIVE_DIR_REL + '/TASKBOARD-RECORDS-'
RECORD_ARCHIVES_MIN = 2  # 已寫成的批次紀錄封存檔不得移除（下限；實際只增不減由 checkpoint 的 manifest 比對）；測試以 0 表示「尚未寫成」
RECORDS_ON_BOARD_MAX = 6  # 看板上批次紀錄的上限：超過就必須在同批 records-apply 搬走較舊的
MULTILINE_PREVIEW = 40  # records-plan 對多行單元逐行印出的字元數
RECORD_ARCHIVE_KEYS = ('file', 'batch', 'checkpoint_oid', 'file_sha256', 'keep', 'entries')
RECORD_ENTRY_KEYS = ('task_id', 'source_line', 'line_count', 'unit_sha256', 'unit_bytes')
RECORD_BIG_BYTES = 3072  # 盤點「超過 3,072 位元組」的門檻（盤點數字由工具印出，不人工計數）
ONE_LINER_PREFIX = '一句話：'
ONE_LINER_ANCHOR = 'B117-G7B3B1-TAKEOVER-ARCHIVE-R2-261119'  # 此批起的紀錄與 EXEC-LOG 列才受「一句話」規則管（它自己已符合）
ONE_LINER_MIN = 8
ONE_LINER_MAX = 60  # 句子字元數上限，不含句號
ONE_LINER_FORBIDDEN_CHARS = ('。', '\n', '\r', '\t', '|', '{', '}')
ONE_LINER_TASK_ID_RE = re.compile(r'[A-Z][A-Z0-9]*(?:-[A-Z0-9]+){2,}')
ONE_LINER_SHA_RE = re.compile(r'(?<![0-9A-Za-z])[0-9a-fA-F]{7,64}(?![0-9A-Za-z])')
ONE_LINER_PATH_RE = re.compile(r'[/\\]|\.(?:md|py|json|txt|ya?ml|zip|js|ts|ps1)(?![0-9A-Za-z])', re.I)
LEDGER_REL = 'docs/TODO-LEDGER.md'
LEDGER_ANCHOR = 'B117-TAKEOVER-STATE-261121'  # 此批之後的批次紀錄才受「新增待辦」宣告規則管；清冊規則的生效錨點
LEDGER_DISPOSITIONS = ('結案', '承接', '開放')
LEDGER_CELLS = 6  # 編號、來源批次紀錄、原標籤、事項、處置、依據或去處
LEDGER_ROW_RE = re.compile(r'^\| (TD-[0-9]{3}) \|')
LEDGER_ROW_CANDIDATE_RE = re.compile(r'^\s*\|\s*TD')  # 格式變體（管線後無空格、行首有空白）也視為清冊列，交由 LEDGER_ROW_RE 判定，不得被靜默略過
TD_ID_RE = re.compile(r'^TD-[0-9]{3}$')
TODO_CLAUSE_RE = re.compile(r'新增待辦：([^。\n]*)。')
TODO_NONE = '無'
EXEC_LOG_REL = 'docs/EXEC-LOG.md'
EXEC_LOG_CELL_RE = re.compile(r'([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)：(.*)', re.S)


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
    fails.extend(check_rows_append_only(root, manifest, taskboard, seen_ids, backlog_text))
    record_fails, record_archives, record_total = check_records(root, manifest, taskboard, backlog_text)
    fails.extend(record_fails)
    section = taskboard.split('\n## 封存區', 1)
    if len(section) != 2 or ARCHIVE_PREFIX not in section[1]:
        fails.append('%s 的「## 封存區」必須指向 %s*' % (TASKBOARD_REL, ARCHIVE_PREFIX))
    if ARCHIVE_PREFIX not in index_text:
        fails.append('%s 必須指向 %s*' % (ARCHIVE_INDEX_REL, ARCHIVE_PREFIX))
    if not os.path.isfile(os.path.join(root, *README_REL.split('/'))):
        fails.append('%s 不存在' % README_REL)
    infos.append('封存檔 %d 個、封存列 %d 列、USER 保留 %d 列；批次紀錄封存檔 %d 個、封存 %d 則' % (len(manifest['archives']), total, len(keep), record_archives, record_total))
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


def record_units(text):
    """批次紀錄單元：[{task_id, start（1 起算）, lines}]，依看板順序。
    單元 = 紀錄行 + 其後的續行，止於空白行（僅空白字元也算）或下一則紀錄行之前。"""
    lines = text.split('\n')
    starts = [i for i, line in enumerate(lines) if C7_RECORD.match(line)]
    units = []
    for position, start in enumerate(starts):
        limit = starts[position + 1] if position + 1 < len(starts) else len(lines)
        end = start + 1
        while end < limit and lines[end].strip() != '':
            end += 1
        units.append({'task_id': C7_RECORD.match(lines[start]).group(1), 'start': start + 1, 'lines': lines[start:end]})
    return units


def unit_text(lines):
    return '\n'.join(lines)


def unit_bytes(lines):
    return len(unit_text(lines).encode('utf-8'))


def record_inventory(units):
    """盤點數字。回傳 (筆數, 總位元組, 超過門檻的筆數, 最大位元組, 最大者的 task_id)。"""
    sizes = [(unit_bytes(u['lines']), u['task_id']) for u in units]
    biggest = max(sizes) if sizes else (0, '')
    return len(sizes), sum(s for s, _ in sizes), sum(1 for s, _ in sizes if s > RECORD_BIG_BYTES), biggest[0], biggest[1]


def one_liner_sentence_problem(sentence):
    """句子本身（不含「一句話：」與句號）的問題；沒有問題回傳 None。"""
    if not isinstance(sentence, str):
        return '一句話必須是字串'
    if sentence != sentence.strip():
        return '一句話前後不得有空白'
    if len(sentence) < ONE_LINER_MIN:
        return '一句話只有 %d 個字元，少於下限 %d' % (len(sentence), ONE_LINER_MIN)
    if len(sentence) > ONE_LINER_MAX:
        return '一句話 %d 個字元，超過上限 %d' % (len(sentence), ONE_LINER_MAX)
    for ch in ONE_LINER_FORBIDDEN_CHARS:
        if ch in sentence:
            return '一句話必須是單句、單行，不得含 %r' % ch
    if ONE_LINER_TASK_ID_RE.search(sentence):
        return '一句話不得含 TASK_ID'
    if ONE_LINER_SHA_RE.search(sentence):
        return '一句話不得含 SHA'
    if ONE_LINER_PATH_RE.search(sentence):
        return '一句話不得含檔案路徑或檔名'
    return None


def one_liner_lead_problem(text):
    """從批次紀錄「：」之後、或 EXEC-LOG 的「TASK_ID：」之後算起的文字；須以「一句話：……。」開頭。"""
    if not text.startswith(ONE_LINER_PREFIX):
        return '須以「%s」開頭' % ONE_LINER_PREFIX
    body = text[len(ONE_LINER_PREFIX):]
    end = body.find('。')
    if end < 0:
        return '一句話沒有以「。」結尾'
    return one_liner_sentence_problem(body[:end])


def board_one_liner_problems(board_units, anchor_seen):
    """看板最新一則批次紀錄的「一句話」問題。anchor_seen 為假時規則尚未生效。"""
    if not anchor_seen or not board_units:
        return []
    first = board_units[0]['lines'][0]
    problem = one_liner_lead_problem(first[C7_RECORD.match(first).end():])
    if problem:
        return ['%s 最新一則批次紀錄 %s：%s' % (TASKBOARD_REL, board_units[0]['task_id'], problem)]
    return []


def table_cells(line):
    """GFM 表格列的儲存格（去前後空白）；與 check_consistency 的 _c20_table_cells 同一套規則（反斜線跳脫的直線不分欄、結尾直線可省略），非表格列回 None。

    EXEC-LOG 的一句話檢查、CHECK 26 的最新列 TASK_ID 判定與 prompt_builder 的 EXEC-LOG 列檢查必須用同一種切法；
    儲存格前後空白（兩個空格、Tab、沒有空格）不得讓該列逃過檢查（第二意見 B1）。
    """
    s = line.strip()
    if not s.startswith('|') or len(s) < 2:
        return None
    end = len(s) - 1 if (len(s) >= 2 and s[-1] == '|' and s[-2] != '\\') else len(s)
    cells, token = [], []
    for i in range(1, end):
        c = s[i]
        if c == '|':
            n = 0
            j = i - 1
            while j >= 0 and s[j] == '\\':
                n += 1
                j -= 1
            if n == 0:
                cells.append(''.join(token).strip())
                token = []
                continue
        token.append(c)
    cells.append(''.join(token).strip())
    return cells


def exec_log_rows(text):
    """EXEC-LOG 內「第三欄（去前後空白後）以 TASK_ID＋全形冒號開頭」的列：[(行號, TASK_ID, 冒號之後的文字)]。"""
    rows = []
    for number, line in enumerate(text.split('\n'), 1):
        cells = table_cells(line)
        if cells is None or len(cells) < 3:
            continue
        match = EXEC_LOG_CELL_RE.fullmatch(cells[2])
        if match:
            rows.append((number, match.group(1), match.group(2)))
    return rows


def exec_log_one_liner_problems(text):
    """EXEC-LOG 中錨點之後每一列的「一句話」問題；錨點列不存在表示規則尚未生效。"""
    rows = exec_log_rows(text)
    ids = [tid for _, tid, _ in rows]
    if ONE_LINER_ANCHOR not in ids:
        return []
    problems = []
    for number, tid, rest in rows[ids.index(ONE_LINER_ANCHOR) + 1:]:
        problem = one_liner_lead_problem(rest)
        if problem:
            problems.append('%s:%d %s：%s' % (EXEC_LOG_REL, number, tid, problem))
    return problems


def render_records_archive(number, archive, units_by_id):
    lines = [
        '# 任務看板批次紀錄封存 %04d' % number, '',
        '> 本檔由 `scripts/taskboard_archive.py records-apply` 產生，寫成後不得修改。清單與每則的 SHA-256 在 `TASKBOARD-ARCHIVE-MANIFEST.json` 的 `record_archives`，由 CHECK 29 逐位元組核對，並以 git 在封存當時 checkpoint 的 `docs/TASKBOARD.md` 逐行比對原文。',
        '> 封存不是刪除：下列各則是封存當時 `docs/TASKBOARD.md` 批次紀錄的原文（含續行），逐字保留。',
        '> 封存批次：%s；封存當時 checkpoint：`%s`；看板保留數：%d' % (archive['batch'], archive['checkpoint_oid'], archive['keep']), '',
        '## 封存紀錄', '']
    for entry in archive['entries']:
        lines += ['### ' + entry['task_id'], '',
                  '- 原位置：`%s` 第 %d 行起，共 %d 行（封存前）' % (TASKBOARD_REL, entry['source_line'], entry['line_count']), '',
                  FENCE, unit_text(units_by_id[entry['task_id']]), FENCE_END, '']
    return '\n'.join(lines).rstrip('\n') + '\n'


def parse_records_archive(text):
    """封存檔內每個圍欄的內容（行列表）。圍欄內可有多行；結構不符就 Fail。"""
    lines = text.split('\n')
    units, index = [], 0
    while index < len(lines):
        if lines[index] == FENCE:
            end = index + 1
            while end < len(lines) and lines[end] != FENCE_END:
                end += 1
            if end >= len(lines) or end == index + 1:
                raise Fail('批次紀錄封存檔圍欄結構錯誤（第 %d 行）' % (index + 1))
            units.append(lines[index + 1:end])
            index = end
        index += 1
    return units


def git_blob_text(root, oid, rel):
    """git 在某 commit 的檔案原文（不 strip）。回答不出來就 Fail。"""
    try:
        proc = subprocess.run(['git', '-C', root, 'cat-file', 'blob', '%s:%s' % (oid, rel)], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Fail('git 無法執行（%s）' % type(exc).__name__)
    if proc.returncode != 0:
        raise Fail('git 讀不到 %s:%s' % (oid[:7], rel))
    try:
        return proc.stdout.decode('utf-8')
    except UnicodeDecodeError:
        raise Fail('%s:%s 不是合法 UTF-8' % (oid[:7], rel))


def check_record_entry_fields(entry, where, fails):
    if not isinstance(entry, dict) or sorted(entry) != sorted(RECORD_ENTRY_KEYS):
        fails.append('%s 欄位必須恰為 %s' % (where, '、'.join(RECORD_ENTRY_KEYS)))
        return False
    good = (_is_text(entry['task_id']) and _is_int(entry['source_line']) and entry['source_line'] >= 1
            and _is_int(entry['line_count']) and entry['line_count'] >= 1
            and isinstance(entry['unit_sha256'], str) and SHA256_RE.match(entry['unit_sha256'])
            and _is_int(entry['unit_bytes']))
    if not good:
        fails.append('%s 欄位型別不符' % where)
    return bool(good)


def check_records(root, manifest, taskboard, backlog_text):
    """CHECK 29 的批次紀錄部分。回傳 (fails, 批次紀錄封存檔數, 封存則數)。"""
    fails, total = [], 0
    archives = manifest.get('record_archives', [])
    if not isinstance(archives, list):
        return ['%s record_archives 必須是陣列' % MANIFEST_REL], 0, 0
    if len(archives) < RECORD_ARCHIVES_MIN:
        fails.append('%s record_archives 少於 %d 個：已寫成的批次紀錄封存檔不得移除' % (MANIFEST_REL, RECORD_ARCHIVES_MIN))
    board_units = record_units(taskboard)
    board_ids = [u['task_id'] for u in board_units]
    if archives and not board_units:
        fails.append('%s 批次紀錄區至少要保留 1 則（C7 要求新紀錄緊接舊首筆之前）' % TASKBOARD_REL)
    if len(set(board_ids)) != len(board_ids):
        fails.append('%s 批次紀錄的 TASK_ID 重複' % TASKBOARD_REL)
    if len(board_ids) > RECORDS_ON_BOARD_MAX:
        fails.append('%s 批次紀錄 %d 則，超過上限 %d 則：須在同批以 records-apply 搬走較舊的' % (TASKBOARD_REL, len(board_ids), RECORDS_ON_BOARD_MAX))
    seen, checkpoint, board_at = set(), None, {}
    for position, archive in enumerate(archives, 1):
        where = '%s record_archives[%d]' % (MANIFEST_REL, position - 1)
        if not isinstance(archive, dict) or sorted(archive) != sorted(RECORD_ARCHIVE_KEYS):
            fails.append('%s 欄位必須恰為 %s' % (where, '、'.join(RECORD_ARCHIVE_KEYS)))
            continue
        expected_rel = '%s%04d.md' % (RECORDS_PREFIX, position)
        if archive['file'] != expected_rel:
            fails.append('%s file 必須是 %s' % (where, expected_rel))
            continue
        if (not isinstance(archive['checkpoint_oid'], str) or not OID_RE.match(archive['checkpoint_oid'])
                or not _is_text(archive['batch']) or not isinstance(archive['file_sha256'], str)
                or not SHA256_RE.match(archive['file_sha256']) or not _is_int(archive['keep']) or archive['keep'] < 1):
            fails.append('%s batch、checkpoint_oid、file_sha256 或 keep（須 ≥ 1）格式不符' % where)
            continue
        entries = archive['entries']
        if not isinstance(entries, list) or not entries:
            fails.append('%s entries 必須是非空陣列' % where)
            continue
        try:
            text = read_text(root, archive['file'])
            file_units = parse_records_archive(text)
        except Fail as exc:
            fails.append('%s' % exc)
            continue
        if sha256_text(text) != archive['file_sha256']:
            fails.append('%s file_sha256 與封存檔不符' % where)
        if len(file_units) != len(entries):
            fails.append('%s 封存檔則數 %d 與清單 %d 不符' % (where, len(file_units), len(entries)))
            continue
        units_by_id, fields_ok, last_line = {}, True, 0
        for entry, lines in zip(entries, file_units):
            if not check_record_entry_fields(entry, where + ' entry', fails):
                fields_ok = False
                continue
            tid = entry['task_id']
            total += 1
            if tid in seen:
                fails.append('%s 重複封存 %s' % (where, tid))
            seen.add(tid)
            units_by_id[tid] = lines
            match = C7_RECORD.match(lines[0])
            if not match or match.group(1) != tid:
                fails.append('%s %s：封存單元的首行不是該 TASK_ID 的批次紀錄' % (where, tid))
            if (sha256_text(unit_text(lines)) != entry['unit_sha256'] or unit_bytes(lines) != entry['unit_bytes']
                    or len(lines) != entry['line_count']):
                fails.append('%s %s：原文與清單的 SHA-256、位元組數或行數不符' % (where, tid))
            if entry['source_line'] <= last_line:
                fails.append('%s %s：清單必須依看板原順序（source_line 遞增）' % (where, tid))
            last_line = entry['source_line']
            if tid in board_ids:
                fails.append('%s %s：看板仍有同一則批次紀錄（封存必須是移動）' % (where, tid))
        if not fields_ok:
            continue
        if render_records_archive(position, archive, units_by_id) != text:
            fails.append('%s 封存檔內容與清單重新產生的結果不一致' % where)
        try:
            if checkpoint is None:
                checkpoint = read_checkpoint(backlog_text)
                if resolve_commit(root, checkpoint) != checkpoint:
                    raise Fail('checkpoint %s 無法解析' % checkpoint[:7])
            oid = archive['checkpoint_oid']
            if resolve_commit(root, oid) != oid or not is_ancestor(root, oid, checkpoint):
                fails.append('%s checkpoint_oid 無法解析或不是目前 checkpoint 的祖先（或等於）' % where)
                continue
            if oid not in board_at:
                board_at[oid] = git_blob_text(root, oid, TASKBOARD_REL).split('\n')
            old_lines = board_at[oid]
            for entry in entries:
                lines = units_by_id[entry['task_id']]
                start = entry['source_line'] - 1
                if old_lines[start:start + len(lines)] != lines:
                    fails.append('%s %s：與 git 在 checkpoint %s 的看板原文不一致' % (where, entry['task_id'], oid[:7]))
        except Fail as exc:
            fails.append('%s' % exc)
    fails.extend(check_records_append_only(root, archives, board_units, seen, backlog_text))
    fails.extend(board_one_liner_problems(board_units, ONE_LINER_ANCHOR in board_ids or ONE_LINER_ANCHOR in seen))
    fails.extend(check_ledger(root, board_units, seen, backlog_text))
    return fails, len(archives), total


def checkpoint_state(root, backlog_text):
    """git 在 §5.1 checkpoint 的 (checkpoint, 看板原文, manifest 物件)。讀不到、不是合法 JSON 或不是物件就 Fail。"""
    checkpoint = read_checkpoint(backlog_text)
    if resolve_commit(root, checkpoint) != checkpoint:
        raise Fail('checkpoint %s 無法解析' % checkpoint[:7])
    old_board = git_blob_text(root, checkpoint, TASKBOARD_REL)
    try:
        old_manifest = json.loads(git_blob_text(root, checkpoint, MANIFEST_REL))
    except ValueError:
        raise Fail('checkpoint %s 的 %s 不是合法 JSON' % (checkpoint[:7], MANIFEST_REL))
    if not isinstance(old_manifest, dict):
        raise Fail('checkpoint %s 的 %s 不是 JSON 物件' % (checkpoint[:7], MANIFEST_REL))
    return checkpoint, old_board, old_manifest


def check_rows_append_only(root, manifest, taskboard, archived_ids, backlog_text):
    """看板列與清單的只增不減（fail-closed，G7-b3b1）：以 git 在 §5.1 checkpoint 的看板與 manifest 為準。
    1. checkpoint 看板上的每一個表格列 ID，必須仍在看板上或已在某個看板列封存檔；
    2. checkpoint 的 manifest 的 archives 必須是目前清單的前綴；
    3. checkpoint 的 manifest 的 user_keep 每一個 ID 仍在目前的 user_keep。"""
    fails = []
    try:
        checkpoint, old_board, old_manifest = checkpoint_state(root, backlog_text)
        short = checkpoint[:7]
        for row_id in sorted({row['id'] for row in parse_rows(old_board)}):
            if not on_board(taskboard, row_id) and row_id not in archived_ids:
                fails.append('%s：checkpoint %s 的看板有此列，目前既不在看板上也不在任何看板列封存檔（列消失）' % (row_id, short))
        old_archives, old_keep = old_manifest.get('archives'), old_manifest.get('user_keep')
        if not isinstance(old_archives, list) or not isinstance(old_keep, list):
            raise Fail('checkpoint %s 的 %s 缺少 archives 或 user_keep 陣列' % (short, MANIFEST_REL))
        archives, keep = manifest['archives'], manifest['user_keep']
        if len(archives) < len(old_archives) or archives[:len(old_archives)] != old_archives:
            fails.append('%s archives 不是 checkpoint %s 清單的追加（只增不減：不得刪除、改寫或重排既有封存檔）' % (MANIFEST_REL, short))
        for row_id in old_keep:
            if row_id not in keep:
                fails.append('%s user_keep 少了 %s：USER 標記保留只增不減（checkpoint %s）' % (MANIFEST_REL, row_id, short))
    except Fail as exc:
        fails.append('%s' % exc)
    return fails


def check_records_append_only(root, archives, board_units, archived_ids, backlog_text):
    """批次紀錄的只增不減與不得改寫（fail-closed）：以 git 在 §5.1 checkpoint 的看板與 manifest 為準。
    1. checkpoint 看板上的每一則批次紀錄，必須仍在看板上或已在某個批次紀錄封存檔；
    2. checkpoint 的 manifest 的 record_archives（缺鍵視為空陣列）必須是目前清單的前綴；
    3. 仍留在看板的舊紀錄，整個單元必須與 checkpoint 看板逐字相同（G7-b3b1）；
    4. checkpoint 看板上沒有的新紀錄只能連續排在最前面（G7-b3b1）。"""
    fails = []
    board_ids = [u['task_id'] for u in board_units]
    try:
        checkpoint, old_board, old_manifest = checkpoint_state(root, backlog_text)
        short = checkpoint[:7]
        old_units = {u['task_id']: u['lines'] for u in record_units(old_board)}
        for tid in old_units:
            if tid not in board_ids and tid not in archived_ids:
                fails.append('%s：checkpoint %s 的看板有此批次紀錄，目前既不在看板上也不在任何批次紀錄封存檔（紀錄消失）' % (tid, short))
        seen_old = False
        for unit in board_units:
            if unit['task_id'] in old_units:
                seen_old = True
                if unit['lines'] != old_units[unit['task_id']]:
                    fails.append('%s：留在看板的舊批次紀錄必須與 checkpoint %s 逐字相同（不得改寫）' % (unit['task_id'], short))
            elif seen_old:
                fails.append('%s：checkpoint %s 之後新增的批次紀錄只能排在最前面（最新在前），不得夾在舊紀錄之間或之後' % (unit['task_id'], short))
        old_archives = old_manifest.get('record_archives', [])
        if not isinstance(old_archives, list):
            raise Fail('checkpoint %s 的 %s record_archives 不是陣列' % (short, MANIFEST_REL))
        if len(archives) < len(old_archives) or archives[:len(old_archives)] != old_archives:
            fails.append('%s record_archives 不是 checkpoint %s 清單的追加（只增不減：不得刪除、改寫或重排既有封存檔）' % (MANIFEST_REL, short))
    except Fail as exc:
        fails.append('%s' % exc)
    return fails


def parse_ledger(text):
    """清冊表格列。回傳 (rows, problems)：rows 為 [{id, source, label, item, disposition, basis, line}]。
    行首（允許前置空白）為管線加 TD 的行一律視為清冊列候選；不符「| TD-nnn |」開頭、「 |」結尾或欄數不是 6 者進 problems，不進 rows，不得靜默略過。"""
    rows, problems = [], []
    for number, line in enumerate(text.split('\n'), 1):
        if not LEDGER_ROW_CANDIDATE_RE.match(line):
            continue
        if not LEDGER_ROW_RE.match(line) or not line.endswith(' |'):
            problems.append('%s 第 %d 行：清冊列須以「| TD-nnn |」開頭並以「 |」結尾' % (LEDGER_REL, number))
            continue
        cells = [cell.strip() for cell in line[1:-1].split('|')]
        if len(cells) != LEDGER_CELLS:
            problems.append('%s 第 %d 行（%s）：欄數 %d，須恰為 %d' % (LEDGER_REL, number, cells[0], len(cells), LEDGER_CELLS))
            continue
        rows.append({'id': cells[0], 'source': cells[1], 'label': cells[2], 'item': cells[3],
                     'disposition': cells[4], 'basis': cells[5], 'line': number})
    return rows, problems


def ledger_format_problems(rows, old_ids=None):
    """清冊格式。old_ids 為 checkpoint 清冊的編號集合；給了才對「新列」要求開放列寫 owner（舊列不追溯）。"""
    problems = []
    for position, row in enumerate(rows, 1):
        expected = 'TD-%03d' % position
        if row['id'] != expected:
            problems.append('%s 第 %d 行：編號須依序無缺號、不重複，這裡應為 %s 卻是 %s' % (LEDGER_REL, row['line'], expected, row['id']))
            break
        for key in ('source', 'label', 'item', 'basis'):
            if not row[key]:
                problems.append('%s %s：欄位 %s 不得為空' % (LEDGER_REL, row['id'], key))
        if row['disposition'] not in LEDGER_DISPOSITIONS:
            problems.append('%s %s：處置須為 %s 之一，現為「%s」' % (LEDGER_REL, row['id'], '、'.join(LEDGER_DISPOSITIONS), row['disposition']))
        elif old_ids is not None and row['id'] not in old_ids and row['disposition'] == '開放' and 'owner' not in row['basis']:
            problems.append('%s %s：新增的「開放」列，依據欄須寫 owner 與觸發條件或複查日' % (LEDGER_REL, row['id']))
    return problems


def ledger_append_problems(rows, old_rows):
    """清冊只增不減：checkpoint 清冊的每一列仍在；來源、原標籤、事項不得改；處置只能維持或改為結案；已結案逐字不變。"""
    problems, current = [], {row['id']: row for row in rows}
    for old in old_rows:
        row = current.get(old['id'])
        if row is None:
            problems.append('%s %s：checkpoint 清冊有此列，目前消失（清冊只增不減）' % (LEDGER_REL, old['id']))
            continue
        for key in ('source', 'label', 'item'):
            if row[key] != old[key]:
                problems.append('%s %s：欄位 %s 不得改寫' % (LEDGER_REL, old['id'], key))
        if old['disposition'] == '結案':
            if row != dict(old, line=row['line']):
                problems.append('%s %s：已結案之列須逐字不變' % (LEDGER_REL, old['id']))
        elif row['disposition'] != old['disposition'] and row['disposition'] != '結案':
            problems.append('%s %s：處置只能維持或改為結案（%s → %s）' % (LEDGER_REL, old['id'], old['disposition'], row['disposition']))
    return problems


def todo_declaration_problems(unit, rows):
    """受管批次紀錄的「新增待辦」宣告核對：恰一句，所列編號恰等於清冊中來源為該紀錄的列。"""
    task = unit['task_id']
    clauses = TODO_CLAUSE_RE.findall(unit_text(unit['lines']))
    if len(clauses) != 1:
        return ['%s %s：批次紀錄須恰有一句「新增待辦：無。」或「新增待辦：TD-nnn、TD-nnn。」，找到 %d 句' % (TASKBOARD_REL, task, len(clauses))]
    body = clauses[0]
    declared = [] if body == TODO_NONE else body.split('、')
    problems = []
    bad = [item for item in declared if not TD_ID_RE.match(item)]
    if bad:
        return ['%s %s：新增待辦宣告的編號格式不符（須為 TD-nnn，以「、」分隔）：%s' % (TASKBOARD_REL, task, '、'.join(bad))]
    if len(set(declared)) != len(declared):
        problems.append('%s %s：新增待辦宣告的編號重複' % (TASKBOARD_REL, task))
    known = {row['id'] for row in rows}
    missing = sorted(set(declared) - known)
    if missing:
        problems.append('%s %s：宣告的編號在清冊不存在：%s' % (TASKBOARD_REL, task, '、'.join(missing)))
    owned = sorted(row['id'] for row in rows if row['source'] == task)
    if sorted(set(declared) & known) != owned:
        problems.append('%s %s：宣告與清冊不一致：宣告 %s，清冊中來源為此紀錄的列 %s' % (
            TASKBOARD_REL, task, '、'.join(sorted(set(declared) & known)) or TODO_NONE, '、'.join(owned) or TODO_NONE))
    return problems


def todo_subject_units(board_units, archived_ids):
    """(受管的紀錄單元, 規則是否生效)：錨點在看板上則其前面（較新）的紀錄受管；錨點已封存則看板上全部受管；
    兩處都找不到則規則尚未生效。"""
    ids = [unit['task_id'] for unit in board_units]
    if LEDGER_ANCHOR in ids:
        return board_units[:ids.index(LEDGER_ANCHOR)], True
    if LEDGER_ANCHOR in archived_ids:
        return list(board_units), True
    return [], False


def check_ledger(root, board_units, archived_ids, backlog_text):
    """CHECK 29 的清冊部分（fail-closed）：以 git 在 §5.1 checkpoint 的清冊為準。規則未生效時回傳空陣列。"""
    subjects, active = todo_subject_units(board_units, archived_ids)
    if not active:
        return []
    try:
        rows, problems = parse_ledger(read_text(root, LEDGER_REL))
        checkpoint = read_checkpoint(backlog_text)
        if resolve_commit(root, checkpoint) != checkpoint:
            raise Fail('checkpoint %s 無法解析' % checkpoint[:7])
        old_rows, old_problems = parse_ledger(git_blob_text(root, checkpoint, LEDGER_REL))
    except Fail as exc:
        return ['%s' % exc]
    fails = list(problems)
    if old_problems:
        fails.append('checkpoint %s 的 %s 格式不符，無法作為只增不減的基準' % (checkpoint[:7], LEDGER_REL))
        return fails
    fails.extend(ledger_format_problems(rows, {row['id'] for row in old_rows}))
    fails.extend(ledger_append_problems(rows, old_rows))
    for unit in subjects:
        fails.extend(todo_declaration_problems(unit, rows))
    return fails


def archived_record_ids(manifest):
    archives = manifest.get('record_archives', [])
    if not isinstance(archives, list):
        raise Fail('record_archives 必須是陣列')
    ids = set()
    for archive in archives:
        entries = archive.get('entries') if isinstance(archive, dict) else None
        if not isinstance(entries, list) or not all(isinstance(e, dict) and _is_text(e.get('task_id')) for e in entries):
            raise Fail('record_archives 的 entries 格式不符')
        ids.update(e['task_id'] for e in entries)
    return ids


def records_todo_gate(root, manifest, units, moved, no_new_todos):
    """records-apply 搬移前的清冊對帳；不符就 Fail。規則未生效時只拒絕多餘的 --no-new-todos。"""
    named = list(no_new_todos)
    if len(set(named)) != len(named):
        raise Fail('--no-new-todos 點名重複')
    subjects, active = todo_subject_units(units, archived_record_ids(manifest))
    if not active:
        if named:
            raise Fail('--no-new-todos 只在清冊規則生效後使用（錨點 %s 尚未在看板或封存檔）' % LEDGER_ANCHOR)
        return
    rows, problems = parse_ledger(read_text(root, LEDGER_REL))
    problems = problems + ledger_format_problems(rows)
    if problems:
        raise Fail('清冊格式不符，不得搬移批次紀錄：%s' % problems[0])
    subject_ids = {unit['task_id'] for unit in subjects}
    moved_ids = {unit['task_id'] for unit in moved}
    for name in named:
        if name not in moved_ids or name in subject_ids:
            raise Fail('--no-new-todos %s 不是本次要搬的舊紀錄（錨點之前或錨點本身）' % name)
        if any(row['source'] == name for row in rows):
            raise Fail('--no-new-todos %s：清冊已有來源為它的列，不得再聲明沒有待辦' % name)
    for unit in moved:
        task = unit['task_id']
        if task in subject_ids:
            found = todo_declaration_problems(unit, rows)
            if found:
                raise Fail(found[0])
        elif task not in named and not any(row['source'] == task for row in rows):
            raise Fail('%s：清冊沒有來源為它的列；請先把它帶走的待辦編 TD 號寫進 %s，確認沒有待辦時以 --no-new-todos %s 點名' % (task, LEDGER_REL, task))


def records_plan(root, out, keep):
    try:
        if keep < 1:
            raise Fail('--keep 必須 ≥ 1（看板永遠至少留 1 則批次紀錄）')
        units = record_units(read_text(root, TASKBOARD_REL))
        count, total, big, biggest, biggest_id = record_inventory(units)
        board_bytes = len(read_text(root, TASKBOARD_REL).encode('utf-8'))
    except Exception as exc:
        out.write('TASKBOARD_RECORDS PLAN FAIL %s\n' % (exc if isinstance(exc, Fail) else type(exc).__name__))
        return 1
    out.write('RECORDS_INVENTORY count=%d total_bytes=%d over_%d=%d max_bytes=%d max_task=%s board_bytes=%d\n'
              % (count, total, RECORD_BIG_BYTES, big, biggest, biggest_id, board_bytes))
    moved = 0
    for number, unit in enumerate(units, 1):
        state = 'KEEP' if number <= keep else 'MOVE'
        size = unit_bytes(unit['lines'])
        if state == 'MOVE':
            moved += size
        out.write('RECORD %d %s line=%d lines=%d bytes=%d %s\n' % (number, unit['task_id'], unit['start'], len(unit['lines']), size, state))
        if len(unit['lines']) > 1:
            for offset, line in enumerate(unit['lines'], 1):
                out.write('  MULTILINE %s L%d/%d bytes=%d %s\n' % (unit['task_id'], offset, len(unit['lines']),
                                                                   len(line.encode('utf-8')), line[:MULTILINE_PREVIEW]))
    # room：距看板批次紀錄上限（RECORDS_ON_BOARD_MAX）的剩餘則數；負數表示已超過，必須在同批 records-apply 搬走
    out.write('RECORDS_SUMMARY keep=%d movable=%d movable_bytes=%d on_board=%d max=%d room=%d\n'
              % (keep, max(0, count - keep), moved, count, RECORDS_ON_BOARD_MAX, RECORDS_ON_BOARD_MAX - count))
    return 0


def records_apply(root, task_id, checkpoint_oid, keep, take, out, allow_multiline=(), no_new_todos=()):
    try:
        if keep < 1:
            raise Fail('--keep 必須 ≥ 1（看板永遠至少留 1 則批次紀錄）')
        if take < 1:
            raise Fail('--take 必須 ≥ 1')
        if not task_id:
            raise Fail('--task-id 為必填')
        manifest = load_manifest(root)
        taskboard = read_text(root, TASKBOARD_REL)
        checkpoint = read_checkpoint(read_text(root, BACKLOG_REL))
        if not OID_RE.match(checkpoint_oid) or resolve_commit(root, checkpoint_oid) != checkpoint_oid:
            raise Fail('--checkpoint-oid 必須是可解析的完整 commit')
        if checkpoint_oid != checkpoint and not is_ancestor(root, checkpoint_oid, checkpoint):
            raise Fail('--checkpoint-oid 必須等於或是 §5.1 checkpoint 的祖先')
        if git_blob_text(root, checkpoint_oid, TASKBOARD_REL) != taskboard:
            raise Fail('工作區的看板與 checkpoint 的看板不同：records-apply 只能在未改動看板的工作區執行')
        units = record_units(taskboard)
        ids = [u['task_id'] for u in units]
        if len(set(ids)) != len(ids):
            raise Fail('看板批次紀錄的 TASK_ID 重複')
        movable = len(units) - keep
        if movable < 1:
            raise Fail('看板批次紀錄 %d 則，保留 %d 則後沒有可搬的紀錄' % (len(units), keep))
        if take > movable:
            raise Fail('--take %d 超過可搬的 %d 則' % (take, movable))
        moved = units[len(units) - take:]
        multi = [u['task_id'] for u in moved if len(u['lines']) > 1]
        allowed = list(allow_multiline)
        if len(set(allowed)) != len(allowed):
            raise Fail('--allow-multiline 點名重複')
        for name in allowed:
            if name not in multi:
                raise Fail('--allow-multiline %s 不是本次要搬的多行單元' % name)
        for name in multi:
            if name not in allowed:
                raise Fail('%s 是多行單元（%d 行），須先以 records-plan 複核續行，再用 --allow-multiline %s 點名' % (name, len(next(u for u in moved if u['task_id'] == name)['lines']), name))
        records_todo_gate(root, manifest, units, moved, no_new_todos)
        for unit in moved:
            if FENCE_END in unit_text(unit['lines']):
                raise Fail('%s：原文含四個反引號，無法安全封存' % unit['task_id'])
        archives = manifest.setdefault('record_archives', [])
        if not isinstance(archives, list):
            raise Fail('record_archives 必須是陣列')
        number = len(archives) + 1
        entries = [{'task_id': u['task_id'], 'source_line': u['start'], 'line_count': len(u['lines']),
                    'unit_sha256': sha256_text(unit_text(u['lines'])), 'unit_bytes': unit_bytes(u['lines'])} for u in moved]
        archive = {'file': '%s%04d.md' % (RECORDS_PREFIX, number), 'batch': task_id, 'checkpoint_oid': checkpoint_oid,
                   'file_sha256': '', 'keep': keep, 'entries': entries}
        text = render_records_archive(number, archive, {u['task_id']: u['lines'] for u in moved})
        archive['file_sha256'] = sha256_text(text)
        archives.append(archive)
        lines = taskboard.split('\n')
        for unit in sorted(moved, key=lambda u: u['start'], reverse=True):
            first = unit['start'] - 1
            last = first + len(unit['lines'])
            # 前後都是空白行時多移走一個，不留連續兩個空白行；只有一側是空白行時保留它，
            # 不讓前後的內容因為搬走而黏在一起（例如標題接在紀錄行之後）。
            if first > 0 and lines[first - 1].strip() == '' and last < len(lines) and lines[last].strip() == '':
                last += 1
            del lines[first:last]
        with open(os.path.join(root, *archive['file'].split('/')), 'wb') as handle:
            handle.write(text.encode('utf-8'))
        with open(os.path.join(root, *MANIFEST_REL.split('/')), 'wb') as handle:
            handle.write(dump_manifest(manifest).encode('utf-8'))
        with open(os.path.join(root, *TASKBOARD_REL.split('/')), 'wb') as handle:
            handle.write('\n'.join(lines).encode('utf-8'))
    except Exception as exc:
        out.write('TASKBOARD_RECORDS APPLY FAIL %s\n' % (exc if isinstance(exc, (Fail, OSError)) else type(exc).__name__))
        return 1
    out.write('TASKBOARD_RECORDS APPLY PASS entries=%d file=%s file_sha256=%s\n' % (len(entries), archive['file'], archive['file_sha256']))
    return 0


def main(argv=None, out=None):
    out = out or sys.stdout
    parser = argparse.ArgumentParser(description='任務看板封存工具')
    sub = parser.add_subparsers(dest='cmd', required=True)
    for name in ('plan', 'check', 'apply', 'records-plan', 'records-apply'):
        item = sub.add_parser(name)
        item.add_argument('--repo', required=True)
        if name == 'apply':
            item.add_argument('--task-id', default='')
            item.add_argument('--checkpoint-oid', default='')
            item.add_argument('--entry', action='append', default=[])
        if name in ('records-plan', 'records-apply'):
            item.add_argument('--keep', type=int, required=True)
        if name == 'records-apply':
            item.add_argument('--task-id', default='')
            item.add_argument('--checkpoint-oid', default='')
            item.add_argument('--take', type=int, default=0)
            item.add_argument('--allow-multiline', action='append', default=[])
            item.add_argument('--no-new-todos', action='append', default=[])
    args = parser.parse_args(argv)
    root = os.path.abspath(args.repo)
    if args.cmd == 'plan':
        return plan(root, out)
    if args.cmd == 'records-plan':
        return records_plan(root, out, args.keep)
    if args.cmd == 'records-apply':
        return records_apply(root, args.task_id, args.checkpoint_oid, args.keep, args.take, out, args.allow_multiline, args.no_new_todos)
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
