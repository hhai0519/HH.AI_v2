"""
用途：受保護歷史守衛（B-116 C1；G2 第一批）。check_consistency CHECK 28 的實作。
（與 scripts/c9_local_history_guard.py 無關：後者盤點本機 git 分支歷史，本檔檢查受保護文件內容。）

比較 Base 與目標，Base 一律取自目標 execution-record 的 base_oid：

  C1a  docs/AUDIT-LOG.md、docs/ARCHIVE-INDEX.md、docs/EXEC-LOG.md 只准新增。
       Base 的每一行都必須依原順序、逐字（含 CR）出現在目標內；刪除、修改、
       重排都會 FAIL。v1 不提供任何授權例外（USER 裁決 D-G2-1 甲），
       更正只能以新增的前向列表達。

  C1b  docs/refactor-backlog.md §5.1：
       - Base 中上一批（Base execution-record 的 task_id）唯一一處
         `本批（尚未 commit）（TASK）` 必須轉成 `` `Base 完整 SHA`（TASK） ``
         或 `` `Base 完整 SHA`（TASK；附註） ``（USER 認定的兩種 ledger 格式），
         該行 placeholder 前後的文字逐字不變；placeholder 位於行首
         （`- 本批…：`）或嵌在上一列冒號之後都適用；
       - 目標（目標 execution-record 的 task_id）自己的 `本批（尚未 commit）（TASK）`
         必須在目標 §5.1 恰好出現一處（C1c，USER 2026-10-25 D-C2-3），下一批才有可轉換的列；
       - 轉換列留在原 placeholder 列的相對位置；§5.1 其他既有行（「上次核對通過的
         HEAD：」checkpoint 行除外）依原順序逐字保留，其他批次的 placeholder 也不得改動。

與 CHECK 17 的分工：Base→目標若異動 docs/batches/*.spec.txt（含尚未 stage 的新檔），
EXEC-LOG 改用 CHECK 17 的同一個狀態流轉函式（check_consistency._exec_log_transition_text，
允許「本批」回填成 Base 並追加一列）判定 Base→目標，提交前與提交後都由本守衛判定，
不委派、不略過，因此兩者對同一內容的結論相同；此時若是已 commit 狀態，目標必須是
Base 的唯一子 commit（CHECK 17 的強制範圍），否則 FAIL。AUDIT-LOG、ARCHIVE-INDEX 與
§5.1 在任何情況都用本守衛的規則。

commit 之間逐位元組比對。工作區檔案先把 CRLF 轉成 LF，再以 `git hash-object --path`
（依該路徑的 attributes 計算 commit 後的 blob）證明轉換後內容就是 commit 會存下的內容；
不相等即 FAIL。受保護檔、§5.1 帳本與紀錄檔設有 filter attribute 時，在任何工作區
diff 或 hash 之前直接 FAIL，本守衛不為核對而執行 filter。

fail-closed：不在任何 git repository（路徑上沒有 .git）才算不適用；有 .git 但 git 無法回答、路徑位於某個 repo 之內卻不是其頂層，或有 repo 但 Base、Base 的
execution-record、目標檔或 §5.1 取不到，一律 FAIL。

  C7   G4 前向狀態 lint（check_c7_state_lint）：TASKBOARD 標記 C7_STATUS_LINT_ACTIVE 後，
       檢查 TASKBOARD 最後更新、批次紀錄位置、新增文字中的暫時性用語與 AUDIT-LOG 表格外列。
       guard() 另讀 C7_READ_FILES（TASKBOARD），與 C1a 只准新增集合分開；CHECK 28 與命令列
       都經 guard() 執行，因此本 lint 在正式入口生效（B-116 G4 F-C7-01／02）。

命令列（審查官用；唯讀）：
  python scripts/history_guard.py --base <rev> --target <rev>
  python scripts/history_guard.py --base <rev> --target WORKTREE
輸出 `HISTORY_GUARD PASS|FAIL` 與逐項代碼；exit 0＝PASS、1＝FAIL。
"""

import argparse
import datetime
import difflib
import json
import os
import re
import subprocess
import sys

PROTECTED_FILES = ("docs/AUDIT-LOG.md", "docs/ARCHIVE-INDEX.md", "docs/EXEC-LOG.md")
# B-116 G4 F-C7-01: read-only inputs of the C7 state lint. Kept separate from PROTECTED_FILES so
# TASKBOARD is read (with the same filter refusal and commit-equivalence proof) but never append-only.
C7_READ_FILES = ("docs/TASKBOARD.md",)
LEDGER_FILE = "docs/refactor-backlog.md"
RECORD_FILE = "docs/governance/execution-record.json"
SPEC_DIR = "docs/batches"
EXEC_LOG = "docs/EXEC-LOG.md"
WORKTREE = "WORKTREE"

HEX40 = re.compile(r"[0-9a-f]{40}")
LEDGER_HEADING = re.compile(r"### 5\.1(?:\s.*)?")
SECTION_END = re.compile(r"#{1,3} .*")
CHECKPOINT_PREFIX = "上次核對通過的 HEAD："
ANY_PLACEHOLDER = re.compile(r"本批（尚未 commit）（([^（）\n]+)）")


def placeholder(task):
    return f"本批（尚未 commit）（{task}）"


class Finding:
    __slots__ = ("code", "detail")

    def __init__(self, code, detail):
        self.code = code
        self.detail = detail

    def __repr__(self):
        return f"{self.code} {self.detail}"


# ---------------------------------------------------------------------------
# 純文字規則
# ---------------------------------------------------------------------------

def split_lines(text):
    """以 '\\n' 切行；CR 留在行內，不使用 splitlines（它也會切 \\x0b、\\u2028 等）。"""
    return text.split("\n")


def first_unmatched(base_lines, target_lines):
    """
    Base 是否為目標的子序列（依序、逐字）。回傳第一個無法對上的 Base 行索引，
    全部對上回傳 None。貪婪比對在「子序列是否存在」上是正確的。
    """
    j = 0
    n = len(target_lines)
    for i, line in enumerate(base_lines):
        while j < n and target_lines[j] != line:
            j += 1
        if j == n:
            return i
        j += 1
    return None


def check_insert_only(path, base_text, target_text):
    if target_text is None:
        return [Finding("HISTORY_PROTECTED_FILE_REMOVED", path)]
    base_lines = split_lines(base_text)
    idx = first_unmatched(base_lines, split_lines(target_text))
    if idx is None:
        return []
    shown = base_lines[idx][:80]
    return [Finding("HISTORY_PROTECTED_LINE_CHANGED", f"{path}:{idx + 1} {shown!r}")]


def ledger_section(lines):
    """§5.1 的 (起, 迄) 行索引（不含標題）；找不到或有兩個 §5.1 標題時回傳 None。"""
    heads = [i for i, line in enumerate(lines) if LEDGER_HEADING.fullmatch(line)]
    if len(heads) != 1:
        return None
    start = heads[0] + 1
    end = len(lines)
    for k in range(start, len(lines)):
        if SECTION_END.fullmatch(lines[k]):
            end = k
            break
    return start, end


def conversion_pattern(prefix, suffix, base_oid, task):
    return re.compile(re.escape(prefix) + "`" + re.escape(base_oid) + "`（" + re.escape(task)
                      + r"(?:；[^（）\n]+)?）" + re.escape(suffix))


def check_ledger(base_text, target_text, base_oid, base_task):
    if target_text is None:
        return [Finding("HISTORY_LEDGER_FILE_REMOVED", LEDGER_FILE)]
    base_lines = split_lines(base_text)
    target_lines = split_lines(target_text)
    base_range = ledger_section(base_lines)
    target_range = ledger_section(target_lines)
    if base_range is None or target_range is None:
        side = "Base" if base_range is None else "目標"
        return [Finding("HISTORY_LEDGER_SECTION_MISSING", f"{LEDGER_FILE} {side} 沒有唯一的 ### 5.1")]
    base_sec = base_lines[base_range[0]:base_range[1]]
    target_sec = target_lines[target_range[0]:target_range[1]]

    findings = []
    ph = placeholder(base_task)
    hits = [i for i, line in enumerate(base_sec) if ph in line]
    converted_index = None
    matched = []
    if not hits:
        pass
    elif len(hits) > 1 or base_sec[hits[0]].count(ph) > 1:
        findings.append(Finding("HISTORY_PLACEHOLDER_AMBIGUOUS",
                                f"Base §5.1 有 {sum(l.count(ph) for l in base_sec)} 處 {ph}"))
    else:
        converted_index = hits[0]
        prefix, suffix = base_sec[converted_index].split(ph, 1)
        if any(ph in line for line in target_sec):
            findings.append(Finding("HISTORY_PLACEHOLDER_NOT_CONVERTED", f"目標 §5.1 仍有 {ph}"))
        pattern = conversion_pattern(prefix, suffix, base_oid, base_task)
        matched = [line for line in target_sec if pattern.fullmatch(line)]
        if not matched:
            findings.append(Finding("HISTORY_PLACEHOLDER_CONVERSION_MISSING",
                                    f"目標 §5.1 沒有 `{base_oid}`（{base_task}） 且前後原文不變的轉換列"))
        elif len(matched) > 1:
            findings.append(Finding("HISTORY_PLACEHOLDER_CONVERSION_DUPLICATED",
                                    f"目標 §5.1 有 {len(matched)} 列轉換列"))

    # 其他既有行依序保留；唯一的轉換列也必須留在原 placeholder 列的位置（相對於其他既有行）。
    converted = matched[0] if len(matched) == 1 else None
    kept = []
    for i, line in enumerate(base_sec):
        if line.startswith(CHECKPOINT_PREFIX):
            continue
        if i == converted_index:
            if converted is not None:
                kept.append(converted)
            continue
        kept.append(line)
    idx = first_unmatched(kept, target_sec)
    if idx is not None:
        line = kept[idx]
        if converted is not None and first_unmatched([k for k in kept if k is not converted], target_sec) is None:
            line, code = converted, "HISTORY_PLACEHOLDER_CONVERSION_MOVED"
        elif ANY_PLACEHOLDER.search(line):
            code = "HISTORY_OTHER_PLACEHOLDER_CHANGED"
        else:
            code = "HISTORY_LEDGER_LINE_CHANGED"
        findings.append(Finding(code, f"{LEDGER_FILE} §5.1 {line[:80]!r}"))
    return findings


def check_exec_log_transition(base_text, target_text, base_oid, exec_log_rule):
    """spec 批次：EXEC-LOG 用 CHECK 17 的狀態流轉規則判定 Base→目標。"""
    if target_text is None:
        return [Finding("HISTORY_PROTECTED_FILE_REMOVED", EXEC_LOG)]
    if target_text == base_text:
        return []
    return [Finding("HISTORY_EXEC_LOG_TRANSITION_INVALID", f) for f in exec_log_rule(base_text, target_text, base_oid)]


def check_own_placeholder(target_text, target_task):
    """C1c：目標 §5.1 必須恰好有一處目標自己的 placeholder。"""
    if target_text is None:
        return []                                    # 缺檔已由 check_ledger 判定
    lines = split_lines(target_text)
    section = ledger_section(lines)
    if section is None:
        return []                                    # 缺 §5.1 已由 check_ledger 判定
    ph = placeholder(target_task)
    count = sum(line.count(ph) for line in lines[section[0]:section[1]])
    if count == 0:
        return [Finding("HISTORY_OWN_PLACEHOLDER_MISSING", f"目標 §5.1 沒有 {ph}")]
    if count > 1:
        return [Finding("HISTORY_OWN_PLACEHOLDER_DUPLICATED", f"目標 §5.1 有 {count} 處 {ph}")]
    return []


# G4 C7 forward-only lint. The marker is introduced by the first C7 batch; prior
# historical commits remain covered by C1/CHECK28 but are not retroactively linted.
C7_MARKER = "C7_STATUS_LINT_ACTIVE"
C7_RECORD = re.compile(r"^\*\*.+[（(]\d{4}-\d{2}-\d{2}；本批 ([A-Za-z0-9_-]+)[）)]\*\*[：:]")
C7_DATE = re.compile(r"(?<!\d)(20\d{2}-\d{2}-\d{2})(?!\d)")
C7_TRANSIENT = (
    "未經本批 Executor 執行前", "E27 尚須", "E27仍為待完成",
    "E27 仍為待完成", "本批 E27 執行前第二意見仍為待完成",
    "須先完成 E27 再進 Executor", "尚須對最終作者包成立",
)


# Expanded synonyms and word-order variants of known pre-execution claims.
C7_TRANSIENT_RE = (
    re.compile(r"未經.{0,6}Executor.{0,6}執行前"),
    re.compile(r"(?:尚待|仍待|待)E27"),
    re.compile(r"E27(?:尚待|仍待|尚未|未完成)"),
    re.compile(r"本批僅作者提案"),
)
C7_NOISE = re.compile(r"[\s`*]")


def c7_last_update(text):
    lines = [line for line in split_lines(text) if line.startswith("**最後更新**：")]
    return lines[0] if len(lines) == 1 else None


def c7_added_lines(before, after):
    # Only inspect added/replaced prospective text, never rewrite historical rows.
    a, b = split_lines(before), split_lines(after)
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for kind, _, _, j1, j2 in matcher.get_opcodes():
        if kind in ("insert", "replace"):
            yield from b[j1:j2]


def c7_unattached_audit_rows(text):
    lines = split_lines(text)
    count = 0
    for i, line in enumerate(lines):
        if not line.startswith("|"):
            continue
        # A newly introduced table header immediately followed by a Markdown
        # separator is not an unattached record, even at a section boundary.
        next_line = lines[i + 1] if i + 1 < len(lines) else ""
        if re.fullmatch(r"\|(?:\s*:?-{3,}:?\s*\|)+\s*", next_line):
            continue
        previous = lines[i-1] if i else ""
        if not previous.startswith("|") and not previous.lstrip().startswith("|-"):
            count += 1
    return count


def check_c7_state_lint(base_files, target_files, base_task, target_task):
    before = base_files.get("docs/TASKBOARD.md") or ""
    after = target_files.get("docs/TASKBOARD.md") or ""
    armed_before = C7_MARKER in before
    armed_after = C7_MARKER in after
    if not (armed_before or armed_after):
        return []  # No backdated failures on archived commits before activation.
    bad = []
    if not armed_after:
        bad.append(Finding("C7_GUARD_DISABLED", C7_MARKER))
    if base_task == target_task:
        return bad  # A same-task observation is not a new production batch.
    old_updated = c7_last_update(before)
    new_updated = c7_last_update(after)
    if (old_updated is None or new_updated is None or old_updated == new_updated
            or C7_DATE.sub("", old_updated) == C7_DATE.sub("", new_updated)):
        bad.append(Finding("C7_LAST_UPDATE_STALE", "TASKBOARD 最後更新必須與 Base 不同且唯一"))
    else:
        dm = re.search(r"(?<!\d)(\d{2})(\d{2})(\d{2})$", target_task)
        expected = f"20{dm[1]}-{dm[2]}-{dm[3]}" if dm else None
        dates = C7_DATE.findall(new_updated)
        if expected is None or dates != [expected]:
            bad.append(Finding("C7_LAST_UPDATE_DATE", "TASKBOARD 最後更新日期必須等於本批 TASK_ID 日期"))
    for path in ("docs/TASKBOARD.md", "docs/AUDIT-LOG.md", "docs/EXEC-LOG.md", LEDGER_FILE):
        for line in c7_added_lines(base_files.get(path) or "", target_files.get(path) or ""):
            normalized = C7_NOISE.sub("", line)
            if (any(C7_NOISE.sub("", needle) in normalized for needle in C7_TRANSIENT)
                    or any(rx.search(normalized) for rx in C7_TRANSIENT_RE)):
                bad.append(Finding("C7_TRANSIENT_TEXT", path))
                break
    # Taskboard new batch record must occur immediately before the prior first record;
    # a header or top-of-board inserted batch record is not accepted.
    old_recs = [(i, m.group(1)) for i, line in enumerate(split_lines(before))
                if (m := C7_RECORD.match(line))]
    new_recs = [(i, m.group(1)) for i, line in enumerate(split_lines(after))
                if (m := C7_RECORD.match(line))]
    if old_recs:
        if not new_recs or new_recs[0][1] != target_task or len(new_recs) < 2 or new_recs[1][1] != old_recs[0][1]:
            bad.append(Finding("C7_RECORD_ORDER", "TASKBOARD 新批次須為批次紀錄區第一筆，緊接舊首筆之前"))
        else:
            lines = split_lines(after)
            if any(lines[i].strip() for i in range(new_recs[0][0]+1, new_recs[1][0])):
                bad.append(Finding("C7_RECORD_ADJACENCY", "新舊紀錄之間只允許空白行"))
    b_aud, t_aud = base_files.get("docs/AUDIT-LOG.md") or "", target_files.get("docs/AUDIT-LOG.md") or ""
    if c7_unattached_audit_rows(t_aud) > c7_unattached_audit_rows(b_aud):
        bad.append(Finding("C7_AUDIT_TABLE_ESCAPE", "AUDIT-LOG 表格外列數不得增加"))
    return bad


def evaluate(base_files, target_files, base_oid, base_task, exec_log_rule=None, target_task=None):
    """
    base_files／target_files：路徑 → 文字（目標缺檔為 None）。
    exec_log_rule 不為 None（spec 批次）時，EXEC-LOG 改用該規則判定。
    target_task 不為 None 時檢查 C1c（目標自己的 placeholder）。
    """
    findings = []
    for path in PROTECTED_FILES:
        if base_files.get(path) is None:
            continue
        if path == EXEC_LOG and exec_log_rule is not None:
            findings.extend(check_exec_log_transition(base_files[path], target_files.get(path), base_oid, exec_log_rule))
            continue
        findings.extend(check_insert_only(path, base_files[path], target_files.get(path)))
    if base_files.get(LEDGER_FILE) is None:
        findings.append(Finding("HISTORY_LEDGER_SECTION_MISSING", f"Base 沒有 {LEDGER_FILE}"))
    else:
        findings.extend(check_ledger(base_files[LEDGER_FILE], target_files.get(LEDGER_FILE),
                                     base_oid, base_task))
    if target_task is not None:
        findings.extend(check_own_placeholder(target_files.get(LEDGER_FILE), target_task))
    return findings


# ---------------------------------------------------------------------------
# git 層
# ---------------------------------------------------------------------------

class GuardFailure(Exception):
    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code = code
        self.detail = detail


def _git(root, *args, stdin=None):
    proc = subprocess.run(["git", *args], cwd=root, capture_output=True, input=stdin)
    return proc.returncode, proc.stdout


def _has_git_marker(root):
    path = os.path.abspath(root)
    while True:
        if os.path.exists(os.path.join(path, ".git")):
            return True
        parent = os.path.dirname(path)
        if parent == path:
            return False
        path = parent


def repo_state(root):
    """
    'none'＝不在任何 git repository；'top'＝root 就是 repository 頂層；'nested'＝root 在別的 repo 裡；
    'broken'＝路徑上有 .git 但 git 回答不出來（例如 dubious ownership），不得當成不適用。
    """
    rc, out = _git(root, "rev-parse", "--show-toplevel")
    if rc != 0:
        return "broken" if _has_git_marker(root) else "none"
    top = out.decode("utf-8", "replace").strip()
    try:
        return "top" if os.path.samefile(top, root) else "nested"
    except OSError:
        return "nested"


def resolve_commit(root, rev, code):
    rc, out = _git(root, "rev-parse", "--verify", "--quiet", rev + "^{commit}")
    oid = out.decode("ascii", "replace").strip()
    if rc != 0 or not HEX40.fullmatch(oid):
        raise GuardFailure(code, rev)
    return oid


def _decode(raw, where):
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise GuardFailure("HISTORY_NOT_UTF8", where)


def read_blob(root, oid, path):
    """commit 中的檔案文字；路徑不存在回傳 None，其他 git 錯誤即 FAIL。"""
    rc, out = _git(root, "ls-tree", "-z", oid, "--", path)
    if rc != 0:
        raise GuardFailure("HISTORY_TREE_UNREADABLE", f"{oid[:12]}:{path}")
    if not out:
        return None
    rc, raw = _git(root, "cat-file", "blob", f"{oid}:{path}")
    if rc != 0:
        raise GuardFailure("HISTORY_TREE_UNREADABLE", f"{oid[:12]}:{path}")
    return _decode(raw, f"{oid[:12]}:{path}")


def refuse_filter(root, path):
    """路徑設有 filter attribute 即 FAIL（check-attr 只讀 attributes，不執行 filter）。"""
    rc, out = _git(root, "check-attr", "-z", "filter", "--", path)
    fields = out.split(b"\0")
    if rc != 0 or len(fields) < 3:
        raise GuardFailure("HISTORY_ATTRIBUTES_UNREADABLE", path)
    if fields[2] not in (b"unspecified", b"unset"):
        raise GuardFailure("HISTORY_ATTRIBUTES_UNSUPPORTED", f"{path} filter={fields[2].decode('utf-8', 'replace')}")


def read_worktree(root, path):
    """
    工作區檔案文字，必須可證明等於 commit 後會存下的內容：CRLF 先轉成 LF（單獨的 CR 保留），
    再與 `git hash-object --path` 依該路徑 attributes 算出的 blob id 比對，不同即 FAIL
    （例如該路徑設了 -text 而工作區是 CRLF）。設有 filter attribute 的路徑不執行 filter，直接 FAIL。
    """
    full = os.path.join(root, *path.split("/"))
    if not os.path.isfile(full):
        return None
    with open(full, "rb") as fh:
        raw = fh.read()
    refuse_filter(root, path)
    normalized = raw.replace(b"\r\n", b"\n")
    rc1, stored = _git(root, "hash-object", "--path=" + path, "--", full)
    rc2, ours = _git(root, "hash-object", "--no-filters", "--stdin", stdin=normalized)
    if rc1 != 0 or rc2 != 0 or not stored.strip() or stored.strip() != ours.strip():
        raise GuardFailure("HISTORY_WORKTREE_NOT_COMMIT_EQUIVALENT", path)
    return _decode(normalized, path)


def record_fields(text, where):
    if text is None:
        raise GuardFailure("HISTORY_RECORD_MISSING", where)
    try:
        data = json.loads(text)
        task = data["task_id"]
        base = data["base_oid"]
    except (ValueError, KeyError, TypeError):
        raise GuardFailure("HISTORY_RECORD_INVALID", where)
    if not isinstance(task, str) or not task or not isinstance(base, str) or not HEX40.fullmatch(base):
        raise GuardFailure("HISTORY_RECORD_INVALID", where)
    return task, base


def changed_paths(root, base_oid, target_oid):
    """Base→目標的異動路徑。target_oid 為 None 代表工作區（含未追蹤檔）。"""
    if target_oid is None:
        rc1, out1 = _git(root, "diff", "--name-only", "-z", base_oid)
        rc2, out2 = _git(root, "ls-files", "-z", "--others", "--exclude-standard")
        if rc1 != 0 or rc2 != 0:
            raise GuardFailure("HISTORY_DIFF_UNREADABLE", base_oid[:12])
        raw = out1 + out2
    else:
        rc, raw = _git(root, "diff", "--name-only", "-z", base_oid, target_oid)
        if rc != 0:
            raise GuardFailure("HISTORY_DIFF_UNREADABLE", f"{base_oid[:12]}..{target_oid[:12]}")
    return {p for p in raw.decode("utf-8", "replace").split("\0") if p}


def touches_spec(paths):
    return any(p.startswith(SPEC_DIR + "/") and p.endswith(".spec.txt") for p in paths)


def default_exec_log_rule(root):
    """載入 check_consistency 的 EXEC-LOG 狀態流轉規則（只在 spec 批次需要時載入）。"""
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import check_consistency as cc
    return lambda p_text, c_text, base_oid: cc._exec_log_transition_text(
        p_text, c_text, lambda c_hash: cc._resolve_commit(root, c_hash) == base_oid, base_oid[:7])[0]


def guard(root, base_rev, target_rev, exec_log_rule=None):
    """
    回傳 (findings, infos)。target_rev 為 WORKTREE 時讀工作區檔案（尚未 commit 的狀態）。
    exec_log_rule：spec 批次判定 EXEC-LOG 的規則；None 時於需要時載入 check_consistency 的規則。
    """
    infos = []
    base_oid = resolve_commit(root, base_rev, "HISTORY_BASE_UNAVAILABLE")
    if target_rev == WORKTREE:
        target_oid = None
        head = resolve_commit(root, "HEAD", "HISTORY_TARGET_UNAVAILABLE")
        read_target = lambda p: read_worktree(root, p)
        anchor = head
    else:
        target_oid = resolve_commit(root, target_rev, "HISTORY_TARGET_UNAVAILABLE")
        read_target = lambda p: read_blob(root, target_oid, p)
        anchor = target_oid
    if _git(root, "merge-base", "--is-ancestor", base_oid, anchor)[0] != 0:
        raise GuardFailure("HISTORY_BASE_NOT_ANCESTOR", f"{base_oid[:12]} 不是 {anchor[:12]} 的祖先")

    base_task, _ = record_fields(read_blob(root, base_oid, RECORD_FILE), f"Base {RECORD_FILE}")
    paths = PROTECTED_FILES + (LEDGER_FILE,) + C7_READ_FILES
    if target_oid is None:
        for p in paths:                     # 在任何工作區 diff 或 hash 之前先拒絕 filter
            refuse_filter(root, p)

    spec_rule = None
    if touches_spec(changed_paths(root, base_oid, target_oid)):
        if target_oid is not None:
            rc, out = _git(root, "rev-list", "--parents", "-n", "1", target_oid)
            parts = out.decode("ascii", "replace").split()
            if rc != 0 or parts[1:] != [base_oid]:
                raise GuardFailure("HISTORY_SPEC_SCOPE_UNENFORCED",
                                   "異動 spec.txt 的目標不是 Base 的唯一子 commit，與 CHECK 17 的強制範圍不一致")
        spec_rule = exec_log_rule or default_exec_log_rule(root)
        infos.append("Base→目標異動 docs/batches/*.spec.txt：EXEC-LOG 以 CHECK 17 的狀態流轉規則判定")

    base_files = {p: read_blob(root, base_oid, p) for p in paths}
    target_files = {p: read_target(p) for p in paths}
    target_task, _ = record_fields(read_target(RECORD_FILE), f"目標 {RECORD_FILE}")
    findings = evaluate(base_files, target_files, base_oid, base_task, spec_rule, target_task)
    findings.extend(check_c7_state_lint(base_files, target_files, base_task, target_task))
    if base_files.get(LEDGER_FILE) is not None and placeholder(base_task) not in base_files[LEDGER_FILE]:
        infos.append(f"Base 沒有上一批 {placeholder(base_task)}：C1b 轉換不適用，§5.1 其他既有行仍受保護")
    infos.append(f"Base {base_oid[:12]}（上一批 {base_task}）→ 本批 {target_task} "
                 f"{'工作區' if target_oid is None else target_oid[:12]}")
    return findings, infos


def check_repo(root, as_if_committed=False, exec_log_rule=None):
    """
    CHECK 28 入口。與 CHECK 26 相同的判定：as_if_committed、AS_IF_COMMITTED=1，或
    工作區 execution-record 的 base_oid 等於 HEAD 時，目標為工作區，Base 取工作區紀錄，
    且 Base 必須就是 HEAD（尚未 commit 的下一批）；否則目標為 HEAD，Base 取 HEAD 這個
    commit 內紀錄的 base_oid，且 Base 必須是 HEAD 的唯一 parent。紀錄不能自選較舊的
    Base 來跳過上一批新增的列。回傳 (fails, infos)，皆為字串清單。
    """
    state = repo_state(root)
    if state == "none":
        return [], ["此路徑不是 git repository，本檢查不適用"]
    if state == "nested":
        return ["HISTORY_ROOT_NOT_TOPLEVEL " + root], []
    if state == "broken":
        return ["HISTORY_GIT_UNAVAILABLE " + root], []
    try:
        head = resolve_commit(root, "HEAD", "HISTORY_TARGET_UNAVAILABLE")
        _, base_oid = record_fields(read_worktree(root, RECORD_FILE), f"工作區 {RECORD_FILE}")
        prospective = (as_if_committed or os.environ.get("AS_IF_COMMITTED") == "1" or base_oid == head)
        if prospective:
            if base_oid != head:
                raise GuardFailure("HISTORY_BASE_NOT_HEAD", f"工作區紀錄 base {base_oid[:12]} 不是 HEAD {head[:12]}")
            findings, infos = guard(root, base_oid, WORKTREE, exec_log_rule)
        else:
            _, base_oid = record_fields(read_blob(root, head, RECORD_FILE), f"HEAD {RECORD_FILE}")
            rc, out = _git(root, "rev-list", "--parents", "-n", "1", head)
            if rc != 0 or out.decode("ascii", "replace").split()[1:] != [base_oid]:
                raise GuardFailure("HISTORY_BASE_NOT_PARENT", f"紀錄 base {base_oid[:12]} 不是 HEAD {head[:12]} 的唯一 parent")
            findings, infos = guard(root, base_oid, head, exec_log_rule)
    except GuardFailure as exc:
        return [f"{exc.code} {exc.detail}".rstrip()], []
    return [f"{f.code} {f.detail}" for f in findings], infos


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="受保護歷史守衛（唯讀）")
    parser.add_argument("--base", required=True)
    parser.add_argument("--target", required=True, help="commit 或 WORKTREE")
    parser.add_argument("--repo", default=".")
    ns = parser.parse_args(argv)
    root = os.path.abspath(ns.repo)
    state = repo_state(root)
    if state != "top":
        fails, infos = [{"none": "HISTORY_NOT_GIT_REPO", "nested": "HISTORY_ROOT_NOT_TOPLEVEL"}.get(
            state, "HISTORY_GIT_UNAVAILABLE")], []
    else:
        try:
            findings, infos = guard(root, ns.base, ns.target)
            fails = [f"{f.code} {f.detail}" for f in findings]
        except GuardFailure as exc:
            fails, infos = [f"{exc.code} {exc.detail}".rstrip()], []
    for info in infos:
        print(f"INFO {info}")
    for fail in fails:
        print(f"FAIL {fail}")
    print("HISTORY_GUARD " + ("FAIL" if fails else "PASS"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
