"""
scripts/history_guard.py（check_consistency CHECK 28；B-116 C1）的測試。

真實輸入：
- 近五個已晉級 commit 與兩種舊 ledger 格式的真實 commit，直接以本 repo 的 git 物件判定；
- B3（INCIDENT-CI-01 R3）：0859541 只存在於保留分支，測試以 main 祖先 c9e2436 的
  AUDIT-LOG 加上 0859541 的真實兩處差異重建，並以 git blob id 證明與真實物件逐位元相同；
- B1（B122-S5-STATIC-ARCHIVE R1 帳本）：R1 原件未保存。USER 提供的證據
  LEDGER_5_1_COMPARE.txt 每行截在 220 位元組，測試以 c9e2436 原文＋該證據前綴「重建」，
  判定只依賴「舊 placeholder 消失且沒有轉換列」，與被截斷的部分無關；
- main 歷史中同類的真實負例 8f5375e（placeholder 刪除未轉換）與 eedc84d（未轉換）。
所有 git 物件都是 main 的祖先；取不到即 FAIL，不 skip。
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import check_consistency as cc  # noqa: E402
import history_guard as hg  # noqa: E402

PH = hg.placeholder


def codes(findings):
    return sorted(f.code for f in findings)


# ---------------------------------------------------------------------------
# C1a：只准新增
# ---------------------------------------------------------------------------

BASE_LOG = "# log\n| a | 1 |\n| b | 2 |\n| c | 3 |\n"


@pytest.mark.parametrize("target", [
    BASE_LOG,
    BASE_LOG + "| d | 4 |\n",
    "# log\n| a | 1 |\n| new | 0 |\n| b | 2 |\n| c | 3 |\n",
    "# preface\n" + BASE_LOG,
])
def test_insert_only_accepts_pure_insertions(target):
    assert hg.check_insert_only("docs/AUDIT-LOG.md", BASE_LOG, target) == []


@pytest.mark.parametrize("target,line", [
    ("# log\n| a | 1 |\n| c | 3 |\n", 3),                    # 刪除
    ("# log\n| a | 1 |\n| b | 9 |\n| c | 3 |\n", 3),         # 修改
    ("# log\n| a | 1 |\n| c | 3 |\n| b | 2 |\n", 4),         # 重排（b 先對上，c 找不到）
    ("# log\n| a | 1 |\n| b | 2 |\r\n| c | 3 |\n", 3),       # 只改行尾 CR
    ("# log\n| a | 1 |\n| b | 2 |\n| c | 3 |", 5),           # 刪除檔尾換行
    ("# log\n| a | 1 |\n| b | 2 |\n| c | 3 | \n", 4),        # 行尾多一個空白
])
def test_insert_only_rejects_delete_modify_reorder(target, line):
    findings = hg.check_insert_only("docs/AUDIT-LOG.md", BASE_LOG, target)
    assert codes(findings) == ["HISTORY_PROTECTED_LINE_CHANGED"]
    assert findings[0].detail.startswith(f"docs/AUDIT-LOG.md:{line} ")


def test_insert_only_rejects_removed_file():
    assert codes(hg.check_insert_only("docs/EXEC-LOG.md", BASE_LOG, None)) == ["HISTORY_PROTECTED_FILE_REMOVED"]


def test_insert_only_does_not_split_on_unicode_line_separators():
    # str.splitlines 會把   當換行，讓「把一行拆成兩行」看起來像只是插入。
    base = "| a b |\n"
    assert codes(hg.check_insert_only("docs/AUDIT-LOG.md", base, "| a\n| a b |\n")) == []
    assert codes(hg.check_insert_only("docs/AUDIT-LOG.md", base, "| a \nb |\n")) == ["HISTORY_PROTECTED_LINE_CHANGED"]


# ---------------------------------------------------------------------------
# C1b：§5.1 placeholder 轉換
# ---------------------------------------------------------------------------

B = "b" * 40
P = "a" * 40


def ledger(*rows, head="上次核對通過的 HEAD：" + P):
    return "\n".join(["# backlog", "### 5.1 上一批狀態", head, *rows, "### 5.2 待辦", "- keep", ""])


EMBED_BASE = ledger(f"- `{P}`（T0，AUD PASS）：{PH('T1')}新增 X；NEXT 改為 Y。",
                    "- `cccccccccccccccccccccccccccccccccccccccc`（T-1）：舊列。")
EMBED_OK = ledger(f"- `{B}`（T1，AUD PASS）：{PH('T2')}新增 Z。",
                  f"- `{P}`（T0，AUD PASS）：`{B}`（T1）新增 X；NEXT 改為 Y。",
                  "- `cccccccccccccccccccccccccccccccccccccccc`（T-1）：舊列。", head="上次核對通過的 HEAD：" + B)

ROWSTART_BASE = ledger(f"- {PH('T1')}：本文 A。", "- `" + P + "`（T0）：前批。")


def test_current_embedded_format_passes():
    assert hg.check_ledger(EMBED_BASE, EMBED_OK, B, "T1") == []


@pytest.mark.parametrize("converted", [f"- `{B}`（T1）：本文 A。", f"- `{B}`（T1；AUD-X independent Macro PASS，Run 1）：本文 A。"])
def test_both_ledger_formats_pass_at_row_start(converted):
    target = ledger(f"- {PH('T2')}：新批。", converted, "- `" + P + "`（T0）：前批。")
    assert hg.check_ledger(ROWSTART_BASE, target, B, "T1") == []


def _rowstart(*rows):
    return ledger(f"- {PH('T2')}：新批。", *rows, "- `" + P + "`（T0）：前批。")


@pytest.mark.parametrize("target,expected", [
    (_rowstart(f"- {PH('T1')}：本文 A。"), ["HISTORY_PLACEHOLDER_CONVERSION_MISSING", "HISTORY_PLACEHOLDER_NOT_CONVERTED"]),
    (_rowstart(), ["HISTORY_PLACEHOLDER_CONVERSION_MISSING"]),
    (_rowstart(f"- `{B[:7]}`（T1）：本文 A。"), ["HISTORY_PLACEHOLDER_CONVERSION_MISSING"]),
    (_rowstart(f"- `{P}`（T1）：本文 A。"), ["HISTORY_PLACEHOLDER_CONVERSION_MISSING"]),
    (_rowstart(f"- `{B.upper()}`（T1）：本文 A。"), ["HISTORY_PLACEHOLDER_CONVERSION_MISSING"]),
    (_rowstart(f"- `{B}`（T1）：本文 B。"), ["HISTORY_PLACEHOLDER_CONVERSION_MISSING"]),
    (_rowstart(f"- `{B}`（T1）：本文 A"), ["HISTORY_PLACEHOLDER_CONVERSION_MISSING"]),
    (_rowstart(f"* `{B}`（T1）：本文 A。"), ["HISTORY_PLACEHOLDER_CONVERSION_MISSING"]),
    (_rowstart(f"- `{B}`（T1x）：本文 A。"), ["HISTORY_PLACEHOLDER_CONVERSION_MISSING"]),
    (_rowstart(f"- `{B}`（T1，附註）：本文 A。"), ["HISTORY_PLACEHOLDER_CONVERSION_MISSING"]),
    (_rowstart(f"- `{B}`（T1；）：本文 A。"), ["HISTORY_PLACEHOLDER_CONVERSION_MISSING"]),
    (_rowstart(f"- `{B}`（T1；附（註））：本文 A。"), ["HISTORY_PLACEHOLDER_CONVERSION_MISSING"]),
    (_rowstart(f"- `{B}`（T1）：本文 A。", f"- `{B}`（T1）：本文 A。"), ["HISTORY_PLACEHOLDER_CONVERSION_DUPLICATED"]),
    (_rowstart(f"- `{B}`（T1）：本文 A。 {PH('T1')}"), ["HISTORY_PLACEHOLDER_CONVERSION_MISSING", "HISTORY_PLACEHOLDER_NOT_CONVERTED"]),
])
def test_placeholder_conversion_errors_fail(target, expected):
    assert codes(hg.check_ledger(ROWSTART_BASE, target, B, "T1")) == expected


def test_conversion_must_stay_in_place():
    base = ledger(f"- {PH('T1')}：A。", "- `" + P + "`（T0）：前批。")
    moved = ledger("- `" + P + "`（T0）：前批。", f"- `{B}`（T1）：A。")
    assert codes(hg.check_ledger(base, moved, B, "T1")) == ["HISTORY_PLACEHOLDER_CONVERSION_MOVED"]
    assert hg.check_ledger(base, ledger(f"- {PH('T2')}：新。", f"- `{B}`（T1）：A。", "- 插入列。",
                                        "- `" + P + "`（T0）：前批。"), B, "T1") == []


@pytest.mark.parametrize("rows,code", [
    ([], "HISTORY_OWN_PLACEHOLDER_MISSING"),
    ([f"- {PH('T2')}：新批。", f"- {PH('T2')}：又一列。"], "HISTORY_OWN_PLACEHOLDER_DUPLICATED"),
    ([f"- {PH('T2')}：新批。{PH('T2')}"], "HISTORY_OWN_PLACEHOLDER_DUPLICATED"),
    ([f"- {PH('T3')}：別的 task。"], "HISTORY_OWN_PLACEHOLDER_MISSING"),
])
def test_c1c_own_placeholder_must_appear_exactly_once(rows, code):
    target = ledger(*rows, f"- `{B}`（T1）：本文 A。", "- `" + P + "`（T0）：前批。")
    findings = hg.evaluate({hg.LEDGER_FILE: ROWSTART_BASE}, {hg.LEDGER_FILE: target}, B, "T1", None, "T2")
    assert codes(findings) == [code]
    outside = ledger(f"- `{B}`（T1）：本文 A。", "- `" + P + "`（T0）：前批。") + f"- {PH('T2')}：在 §5.1 之外。\n"
    assert codes(hg.evaluate({hg.LEDGER_FILE: ROWSTART_BASE}, {hg.LEDGER_FILE: outside}, B, "T1", None, "T2")) == \
        ["HISTORY_OWN_PLACEHOLDER_MISSING"]
    ok = ledger(f"- {PH('T2')}：新批。", f"- `{B}`（T1）：本文 A。", "- `" + P + "`（T0）：前批。")
    assert hg.evaluate({hg.LEDGER_FILE: ROWSTART_BASE}, {hg.LEDGER_FILE: ok}, B, "T1", None, "T2") == []


def test_c1c_applies_before_and_after_commit(repo):
    repo.next_batch()
    _write(repo.root, hg.LEDGER_FILE, ledger(f"- `{repo.base}`（T0）：初始。", head="上次核對通過的 HEAD：" + repo.base))
    assert [f.split()[0] for f in hg.check_repo(repo.root, as_if_committed=True)[0]] == ["HISTORY_OWN_PLACEHOLDER_MISSING"]
    repo.commit("c1")
    assert [f.split()[0] for f in hg.check_repo(repo.root)[0]] == ["HISTORY_OWN_PLACEHOLDER_MISSING"]


def test_conversion_outside_section_does_not_count():
    target = ledger(f"- {PH('T2')}：新批。", "- `" + P + "`（T0）：前批。") + f"- `{B}`（T1）：本文 A。\n"
    assert codes(hg.check_ledger(ROWSTART_BASE, target, B, "T1")) == ["HISTORY_PLACEHOLDER_CONVERSION_MISSING"]


def test_embedded_prefix_must_stay_verbatim():
    target = EMBED_OK.replace(f"- `{P}`（T0，AUD PASS）：`{B}`", f"- `{P}`（T0，AUD FAIL）：`{B}`")
    assert codes(hg.check_ledger(EMBED_BASE, target, B, "T1")) == ["HISTORY_PLACEHOLDER_CONVERSION_MISSING"]


def test_ambiguous_base_placeholder_fails():
    base = ledger(f"- {PH('T1')}：A。", f"- {PH('T1')}：B。")
    assert codes(hg.check_ledger(base, base, B, "T1")) == ["HISTORY_PLACEHOLDER_AMBIGUOUS"]
    base2 = ledger(f"- {PH('T1')}：A。{PH('T1')}")
    assert "HISTORY_PLACEHOLDER_AMBIGUOUS" in codes(hg.check_ledger(base2, base2, B, "T1"))


def test_base_without_previous_placeholder_only_protects_other_lines():
    base = ledger("- `" + P + "`（T0）：前批。")
    assert hg.check_ledger(base, ledger(f"- {PH('T2')}：新。", "- `" + P + "`（T0）：前批。"), B, "T1") == []
    assert codes(hg.check_ledger(base, ledger("- `" + P + "`（T0）：前批改。"), B, "T1")) == ["HISTORY_LEDGER_LINE_CHANGED"]


def test_other_section_lines_and_placeholders_are_protected():
    base = ledger(f"- {PH('T1')}：A。", f"- {PH('OTHER')}：別批。", "- `" + P + "`（T0）：前批。")
    good = ledger(f"- `{B}`（T1）：A。", f"- {PH('OTHER')}：別批。", "- `" + P + "`（T0）：前批。")
    assert hg.check_ledger(base, good, B, "T1") == []
    changed = ledger(f"- `{B}`（T1）：A。", f"- {PH('OTHER')}：別批改。", "- `" + P + "`（T0）：前批。")
    assert codes(hg.check_ledger(base, changed, B, "T1")) == ["HISTORY_OTHER_PLACEHOLDER_CHANGED"]
    reordered = ledger(f"- `{B}`（T1）：A。", "- `" + P + "`（T0）：前批。", f"- {PH('OTHER')}：別批。")
    assert codes(hg.check_ledger(base, reordered, B, "T1")) == ["HISTORY_LEDGER_LINE_CHANGED"]
    dropped_old = ledger(f"- `{B}`（T1）：A。", f"- {PH('OTHER')}：別批。")
    assert codes(hg.check_ledger(base, dropped_old, B, "T1")) == ["HISTORY_LEDGER_LINE_CHANGED"]


def test_checkpoint_line_is_the_only_free_line():
    target = EMBED_OK.replace("上次核對通過的 HEAD：" + B, "上次核對通過的 HEAD：" + "d" * 40)
    assert hg.check_ledger(EMBED_BASE, target, B, "T1") == []


@pytest.mark.parametrize("base,target,side", [
    ("# x\n", EMBED_OK, "Base"),
    (EMBED_BASE, "# x\n", "目標"),
    (EMBED_BASE + "### 5.1 again\n", EMBED_OK, "Base"),
])
def test_missing_or_duplicated_section_fails(base, target, side):
    findings = hg.check_ledger(base, target, B, "T1")
    assert codes(findings) == ["HISTORY_LEDGER_SECTION_MISSING"] and side in findings[0].detail


def test_removed_ledger_file_fails():
    assert codes(hg.check_ledger(EMBED_BASE, None, B, "T1")) == ["HISTORY_LEDGER_FILE_REMOVED"]


def test_base_without_ledger_file_fails_closed():
    findings = hg.evaluate({}, {hg.LEDGER_FILE: EMBED_OK}, B, "T1", False)
    assert codes(findings) == ["HISTORY_LEDGER_SECTION_MISSING"] and "Base" in findings[0].detail


# ---------------------------------------------------------------------------
# 真實 git 物件
# ---------------------------------------------------------------------------

def _git(*args):
    proc = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True)
    assert proc.returncode == 0, f"git {args} 失敗（本測試需要完整 clone）: {proc.stderr!r}"
    return proc.stdout


def _blob(rev, path):
    return _git("cat-file", "blob", f"{rev}:{path}").decode("utf-8")


def _blob_id(text):
    data = text.encode("utf-8")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


RECENT_FIVE = [
    ("1d9f22e041df181e9f4805223b8838ab65952af5", "411f1b11c50862d17a8baa9dbe4a470858533275"),
    ("8320b0d4dc385c5ea1ffe367eea8ce0e46428ceb", "1d9f22e041df181e9f4805223b8838ab65952af5"),
    ("b51d6cb1813d64789ff144c215825b58acb5cc1f", "8320b0d4dc385c5ea1ffe367eea8ce0e46428ceb"),
    ("f3e3e68c7d5b22a6bf64438d05edb69ac99f3e24", "b51d6cb1813d64789ff144c215825b58acb5cc1f"),
    ("cdde0c663cb9b801262e2c8fe904419ac011422c", "f3e3e68c7d5b22a6bf64438d05edb69ac99f3e24"),
]
OLDER_FORMATS = [
    ("c9e2436a7c67dc9a70ba3bf4706355dd8c01ce83", "e1e6824e87c1be1bba18f39fc37579cb8aa69faa"),  # （T；附註）
    ("ff6d2d7edc316fcb9511da0811971634431f6274", "7f7878d5c9300e523af26eb051fc9e23d6bff3d2"),  # 行首（T）：
]


@pytest.mark.parametrize("base,target", RECENT_FIVE + OLDER_FORMATS)
def test_real_promoted_commits_pass(base, target):
    record = json.loads(_blob(target, hg.RECORD_FILE))
    assert record["base_oid"] == base
    findings, infos = hg.guard(REPO_ROOT, base, target)
    assert findings == [], findings
    assert any(base[:12] in i for i in infos)


@pytest.mark.parametrize("base,target,expected", [
    ("3aa8504ff6b0e7d7218eb5bc72e56975f55cfda6", "8f5375ef751ed57f4bbb4f179ddb0d9914afa58b",
     ["HISTORY_PLACEHOLDER_CONVERSION_MISSING"]),
    ("f5e1bb17c1f29fa06a522bd958bbf3148578a0b0", "eedc84d910716e300c7758c6470ee6197d8ef967",
     ["HISTORY_OWN_PLACEHOLDER_MISSING", "HISTORY_PLACEHOLDER_CONVERSION_MISSING", "HISTORY_PLACEHOLDER_NOT_CONVERTED"]),
])
def test_real_main_history_ledger_negatives_fail(base, target, expected):
    findings, _ = hg.guard(REPO_ROOT, base, target)
    assert codes(findings) == expected


B3_BASE = "c9e2436a7c67dc9a70ba3bf4706355dd8c01ce83"
B3_TARGET_AUDIT_LOG_BLOB = "428590a9568f4cfd0fa4f6107cb261df6ebb835e"   # 08595410e7f1751fc3dd5339311f0935a277a483:docs/AUDIT-LOG.md
B3_INSERTED_ROW = (
    "| c9e2436a7c67dc9a70ba3bf4706355dd8c01ce83 | 2026-10-17 | §4.1-1、§4.1-3、USER 常設決定（2026-10-17） | "
    "**核對通過（B122-S5-STATIC-ARCHIVE-R3-261017 前置已確認的 Q2 接任晉級事實）**："
    "`9191cb4d072ec9b05d10d9a5204982ad329de0c0` Q2 R3 post-main Run 38999121844 verify 1472 passed／1 skipped＋13 passed、"
    "Windows 57 passed；`c9e2436a7c67dc9a70ba3bf4706355dd8c01ce83` AUD-TAKEOVER-Q2-STATE-R1-261017 same-SHA main，"
    "candidate Run 39007086229、post-main Run 39008616440 verify 1472 passed／1 skipped＋13 passed、ALL 5 GATES PASSED、"
    "Windows 57 passed；Executor 實測 Q2 R3 245.1 秒、接任 production 2019.6 秒（33 分）、promotion 274.6 秒（4 分），"
    "均 USER_PROVIDED；N1 外部文件版號引用已前向更正可變 TASKBOARD，保護歷史不改寫；N2 B-122 對齊兩 NEXT；"
    "N3 時間補登、N4 B-116 刪除兩階段與角色中文檔名補登；N5 bundle_output 之後 production 啟用、N6 以 33 分為同類狀態批估時、"
    "N7/N8 B-119 CI_RUN 與交接卡改良，均 OPEN／NOT IMPLEMENTED。 | "
    "**本批 B122-S5-STATIC-ARCHIVE-R3-261017 尚未 commit**：只在 USER 允許下新增三靜態檔及必要正規索引／狀態，"
    "禁止刪除與移動；E24/E27 PENDING，manifest 無跨批守衛，B-115 umbrella OPEN。 |"
)


def test_b3_incident_ci_01_rewrite_fails_on_byte_identical_reconstruction():
    base = _blob(B3_BASE, "docs/AUDIT-LOG.md")
    lines = base.split("\n")
    lines.insert(319, B3_INSERTED_ROW)
    assert lines[330].startswith("| **INCIDENT-CI-01** |") and lines[330].count("Run #7 (33972533555)") == 1
    lines[330] = lines[330].replace("Run #7 (33972533555)", "Run #7 (33974613555)")
    target = "\n".join(lines)
    assert _blob_id(target) == B3_TARGET_AUDIT_LOG_BLOB
    findings = hg.check_insert_only("docs/AUDIT-LOG.md", base, target)
    assert codes(findings) == ["HISTORY_PROTECTED_LINE_CHANGED"]
    assert findings[0].detail.startswith("docs/AUDIT-LOG.md:330 '| **INCIDENT-CI-01** |")
    # 對照：只保留新增列（不改寫 Run #7）即 PASS
    lines[330] = lines[330].replace("Run #7 (33974613555)", "Run #7 (33972533555)")
    assert hg.check_insert_only("docs/AUDIT-LOG.md", base, "\n".join(lines)) == []


B1_TASK = "AUD-TAKEOVER-Q2-STATE-R1-261017"
# USER 提供之 LEDGER_5_1_COMPARE.txt「R1 作者包 §5.1 頭部」第一列（證據本身截在 220 位元組）
B1_R1_EVIDENCE_PREFIX = ("- 本批（尚未 commit）（B122-S5-STATIC-ARCHIVE-R1-261017）：已獨立查核 "
                         "`c9e2436a7c67dc9a70ba3bf4706355dd8c01ce83`（AUD-TAKEOVER-Q2-STATE-R1-261017）"
                         "same-SHA 晉級 main，post-main Run 39008616440 verify 1")
B1_R2_NOTE = "；AUD-GPT-261017 independent Macro PASS，same-SHA post-main Run 39008616440 verify／gateway-windows success"


def _b1_base_and_index():
    base = _blob(B3_BASE, hg.LEDGER_FILE)
    lines = base.split("\n")
    hits = [i for i, line in enumerate(lines) if PH(B1_TASK) in line]
    assert len(hits) == 1 and lines[hits[0] - 1] == "上次核對通過的 HEAD：9191cb4d072ec9b05d10d9a5204982ad329de0c0"
    return base, lines, hits[0]


def test_b1_r1_ledger_reconstruction_fails():
    """重建（非原件）：R1 以新 placeholder 取代上一批 placeholder，沒有 c9e2436a 錨定列。"""
    assert len(B1_R1_EVIDENCE_PREFIX.encode("utf-8")) == 220
    base, lines, i = _b1_base_and_index()
    lines[i - 1] = "上次核對通過的 HEAD：" + B3_BASE
    lines[i] = B1_R1_EVIDENCE_PREFIX
    findings = hg.check_ledger(base, "\n".join(lines), B3_BASE, B1_TASK)
    # 新列雖然提到 `c9e2436a…`（TASK），但不是轉換列，不能被當成轉換
    assert codes(findings) == ["HISTORY_PLACEHOLDER_CONVERSION_MISSING"]


def test_b1_r2_style_conversion_passes():
    base, lines, i = _b1_base_and_index()
    prefix, suffix = lines[i].split(PH(B1_TASK), 1)
    converted = prefix + f"`{B3_BASE}`（{B1_TASK}{B1_R2_NOTE}）" + suffix
    lines[i - 1] = "上次核對通過的 HEAD：" + B3_BASE
    lines[i:i + 1] = [B1_R1_EVIDENCE_PREFIX.replace("R1-261017", "R2-261017", 1), converted]
    assert hg.check_ledger(base, "\n".join(lines), B3_BASE, B1_TASK) == []


# ---------------------------------------------------------------------------
# check_repo（CHECK 28 入口）：臨時 repo
# ---------------------------------------------------------------------------

def _run(cwd, *args, env=None):
    proc = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, env=env)
    assert proc.returncode == 0, f"{args}: {proc.stderr}"
    return proc.stdout.strip()


def _write(root, rel, text):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _record(task, base):
    return json.dumps({"task_id": task, "base_oid": base}) + "\n"


EXEC_HEADER = "| 批次 commit | 日期 | 檢查範圍 | 結果 | 攔截紀錄 |\n|---|---|---|---|---|\n"


class Repo:
    def __init__(self, root):
        self.root = root
        _run(root, "git", "init", "-q", "-b", "main")
        _run(root, "git", "config", "user.email", "t@t")
        _run(root, "git", "config", "user.name", "t")
        _write(root, ".gitattributes", "* text=auto eol=lf\n")          # 與本 repo 相同
        _write(root, "docs/AUDIT-LOG.md", "# audit\n| a | 1 |\n")
        _write(root, "docs/ARCHIVE-INDEX.md", "# archive\n- one\n")
        _write(root, "docs/EXEC-LOG.md", EXEC_HEADER + "| 本批 | d | r | 通過 | 無 |\n")
        _write(root, hg.LEDGER_FILE, ledger(f"- {PH('T0')}：初始。"))
        _write(root, hg.RECORD_FILE, _record("T0", "0" * 40))
        self.base = self.commit("c0")

    def commit(self, msg):
        _run(self.root, "git", "add", "-A")
        _run(self.root, "git", "commit", "-q", "-m", msg)
        return _run(self.root, "git", "rev-parse", "HEAD")

    def next_batch(self, task="T1", audit_extra="| b | 2 |\n"):
        """寫出一份合法的下一批（工作區，尚未 commit）。"""
        base = _run(self.root, "git", "rev-parse", "HEAD")
        _write(self.root, "docs/AUDIT-LOG.md", "# audit\n| a | 1 |\n" + audit_extra)
        _write(self.root, hg.LEDGER_FILE, ledger(f"- {PH(task)}：新批。", f"- `{base}`（T0）：初始。",
                                                 head="上次核對通過的 HEAD：" + base))
        _write(self.root, hg.RECORD_FILE, _record(task, base))
        return base


@pytest.fixture
def repo():
    with tempfile.TemporaryDirectory() as d:
        yield Repo(d)


def test_check_repo_prospective_and_committed_pass(repo):
    base = repo.next_batch()
    fails, infos = hg.check_repo(repo.root, as_if_committed=True)
    assert fails == [] and any("工作區" in i for i in infos)
    fails, infos = hg.check_repo(repo.root)           # HEAD == base_oid：同樣視為工作區
    assert fails == [] and any("工作區" in i for i in infos)
    head = repo.commit("c1")
    fails, infos = hg.check_repo(repo.root)
    assert fails == [] and any(head[:12] in i and base[:12] in i for i in infos)
    assert cc.check_28_history_anchor_guard(repo.root) == (fails, infos)


def test_worktree_crlf_is_compared_as_committed_lf(repo):
    repo.next_batch()
    for rel in ("docs/AUDIT-LOG.md", hg.LEDGER_FILE):
        path = os.path.join(repo.root, *rel.split("/"))
        with open(path, "rb") as fh:
            data = fh.read()
        with open(path, "wb") as fh:
            fh.write(data.replace(b"\n", b"\r\n"))
    assert hg.check_repo(repo.root, as_if_committed=True)[0] == []
    with open(os.path.join(repo.root, "docs", "AUDIT-LOG.md"), "wb") as fh:
        fh.write(b"# audit\n| a | 1 |\r| b | 2 |\n")          # 單獨 CR 不是換行
    assert [f.split()[0] for f in hg.check_repo(repo.root, as_if_committed=True)[0]] == ["HISTORY_PROTECTED_LINE_CHANGED"]


def test_n01_worktree_must_equal_what_git_would_store(repo):
    """第二意見 N01：路徑設 -text 時 CRLF 會原樣存入，提交前即 FAIL，不再提交前 PASS、提交後 FAIL。"""
    repo.next_batch()
    _write(repo.root, ".gitattributes", "* text=auto eol=lf\ndocs/AUDIT-LOG.md -text\n")
    path = os.path.join(repo.root, "docs", "AUDIT-LOG.md")
    with open(path, "rb") as fh:
        data = fh.read()
    with open(path, "wb") as fh:
        fh.write(data.replace(b"\n", b"\r\n"))
    assert [f.split()[0] for f in hg.check_repo(repo.root, as_if_committed=True)[0]] == ["HISTORY_WORKTREE_NOT_COMMIT_EQUIVALENT"]
    repo.commit("c1")
    assert [f.split()[0] for f in hg.check_repo(repo.root)[0]] == ["HISTORY_PROTECTED_LINE_CHANGED"]


def test_filter_attribute_is_refused_without_running_the_filter(repo):
    marker = os.path.join(repo.root, "filter-ran")
    _run(repo.root, "git", "config", "filter.probe.clean", f"{sys.executable} -c \"open(r'{marker}', 'w').close(); import sys; sys.stdout.write(sys.stdin.read())\"")
    repo.next_batch()
    _write(repo.root, ".gitattributes", "* text=auto eol=lf\ndocs/AUDIT-LOG.md filter=probe\n")
    fails = hg.check_repo(repo.root, as_if_committed=True)[0]
    assert [f.split()[0] for f in fails] == ["HISTORY_ATTRIBUTES_UNSUPPORTED"] and "filter=probe" in fails[0]
    assert not os.path.exists(marker)


def test_check_repo_committed_mode_reads_head_not_worktree(repo):
    repo.next_batch()
    repo.commit("c1")
    _write(repo.root, "docs/AUDIT-LOG.md", "# audit\n")       # 工作區髒，但 HEAD 合法
    assert hg.check_repo(repo.root)[0] == []
    fails, _ = hg.check_repo(repo.root, as_if_committed=True)  # as-if 指向工作區：以 HEAD 的紀錄為 Base 就不成立
    assert fails


def test_check_repo_as_if_env_selects_worktree(repo, monkeypatch):
    repo.next_batch()
    repo.commit("c1")
    _write(repo.root, "docs/ARCHIVE-INDEX.md", "# archive\n")
    assert hg.check_repo(repo.root)[0] == []
    monkeypatch.setenv("AS_IF_COMMITTED", "1")
    assert any(f.startswith("HISTORY_") for f in hg.check_repo(repo.root)[0])


@pytest.mark.parametrize("path,content,code", [
    ("docs/AUDIT-LOG.md", "# audit\n| a | 9 |\n| b | 2 |\n", "HISTORY_PROTECTED_LINE_CHANGED"),
    ("docs/ARCHIVE-INDEX.md", "# archive\n", "HISTORY_PROTECTED_LINE_CHANGED"),
    ("docs/EXEC-LOG.md", EXEC_HEADER + "| abc1234 | d | r | 通過 | 無 |\n", "HISTORY_PROTECTED_LINE_CHANGED"),
    ("docs/EXEC-LOG.md", None, "HISTORY_PROTECTED_FILE_REMOVED"),
    ("docs/ARCHIVE-INDEX.md", None, "HISTORY_PROTECTED_FILE_REMOVED"),
    (hg.LEDGER_FILE, ledger(f"- {PH('T1')}：新批。"), "HISTORY_PLACEHOLDER_CONVERSION_MISSING"),
    (hg.LEDGER_FILE, None, "HISTORY_LEDGER_FILE_REMOVED"),
])
def test_check_repo_violations_fail_in_both_modes(repo, path, content, code):
    repo.next_batch()
    if content is None:
        os.remove(os.path.join(repo.root, *path.split("/")))
    else:
        _write(repo.root, path, content)
    fails, _ = hg.check_repo(repo.root, as_if_committed=True)
    assert [f.split()[0] for f in fails] == [code]
    repo.commit("c1")
    fails, _ = hg.check_repo(repo.root)
    assert [f.split()[0] for f in fails] == [code]


def test_missing_previous_placeholder_is_reported(repo):
    _write(repo.root, hg.LEDGER_FILE, ledger("- `" + P + "`（T0）：初始。"))
    repo.commit("no placeholder")
    base = _run(repo.root, "git", "rev-parse", "HEAD")
    _write(repo.root, hg.RECORD_FILE, _record("T1", base))
    _write(repo.root, hg.LEDGER_FILE, ledger(f"- {PH('T1')}：新批。", "- `" + P + "`（T0）：初始。"))
    fails, infos = hg.check_repo(repo.root, as_if_committed=True)
    assert fails == [] and any("C1b 轉換不適用" in i for i in infos)


def test_new_protected_file_has_no_history_to_protect(repo):
    os.remove(os.path.join(repo.root, "docs", "ARCHIVE-INDEX.md"))
    repo.commit("drop")
    _write(repo.root, hg.RECORD_FILE, _record("T0", "0" * 40))
    repo.next_batch()
    _write(repo.root, "docs/ARCHIVE-INDEX.md", "# new\n")
    assert hg.check_repo(repo.root, as_if_committed=True)[0] == []


@pytest.mark.parametrize("record,code", [
    (None, "HISTORY_RECORD_MISSING"),
    ("{not json\n", "HISTORY_RECORD_INVALID"),
    (json.dumps({"task_id": "T1"}) + "\n", "HISTORY_RECORD_INVALID"),
    (_record("T1", "B" * 40), "HISTORY_RECORD_INVALID"),
    (_record("", "b" * 40), "HISTORY_RECORD_INVALID"),
    (_record("T1", "f" * 40), "HISTORY_BASE_NOT_HEAD"),
])
def test_target_record_problems_fail_closed(repo, record, code):
    repo.next_batch()
    path = os.path.join(repo.root, *hg.RECORD_FILE.split("/"))
    if record is None:
        os.remove(path)
    else:
        _write(repo.root, hg.RECORD_FILE, record)
    fails, infos = hg.check_repo(repo.root, as_if_committed=True)
    assert [f.split()[0] for f in fails] == [code] and infos == []


def test_base_record_missing_or_invalid_fails_closed(repo):
    os.remove(os.path.join(repo.root, *hg.RECORD_FILE.split("/")))
    repo.commit("no record")
    repo.next_batch()
    assert [f.split()[0] for f in hg.check_repo(repo.root, as_if_committed=True)[0]] == ["HISTORY_RECORD_MISSING"]
    _write(repo.root, hg.RECORD_FILE, "[]\n")
    repo.commit("bad record")
    repo.next_batch()
    assert [f.split()[0] for f in hg.check_repo(repo.root, as_if_committed=True)[0]] == ["HISTORY_RECORD_INVALID"]


def test_record_cannot_choose_an_older_base(repo):
    """上一批新增的列，下一批不能藉由把紀錄的 base 指向更早的 commit 而刪掉。"""
    older = repo.base
    repo.next_batch(audit_extra="| b | 2 |\n")
    middle = repo.commit("c1")
    _write(repo.root, "docs/AUDIT-LOG.md", "# audit\n| a | 1 |\n")          # 刪掉 c1 新增的列
    _write(repo.root, hg.LEDGER_FILE, ledger(f"- {PH('T2')}：再一批。", f"- `{middle}`（T1）：新批。",
                                             f"- `{older}`（T0）：初始。"))
    _write(repo.root, hg.RECORD_FILE, _record("T2", older))
    assert [f.split()[0] for f in hg.check_repo(repo.root, as_if_committed=True)[0]] == ["HISTORY_BASE_NOT_HEAD"]
    repo.commit("c2")
    assert [f.split()[0] for f in hg.check_repo(repo.root)[0]] == ["HISTORY_BASE_NOT_PARENT"]


def test_base_not_ancestor_fails(repo):
    _run(repo.root, "git", "checkout", "-q", "--orphan", "other")
    _run(repo.root, "git", "commit", "-q", "-m", "orphan")
    orphan = _run(repo.root, "git", "rev-parse", "HEAD")
    _run(repo.root, "git", "checkout", "-q", "main")
    repo.next_batch()
    _write(repo.root, hg.RECORD_FILE, _record("T1", orphan))
    assert [f.split()[0] for f in hg.check_repo(repo.root, as_if_committed=True)[0]] == ["HISTORY_BASE_NOT_HEAD"]
    with pytest.raises(hg.GuardFailure) as exc:                    # 命令列路徑：任意 Base 仍須是祖先
        hg.guard(repo.root, orphan, hg.WORKTREE)
    assert exc.value.code == "HISTORY_BASE_NOT_ANCESTOR"
    with pytest.raises(hg.GuardFailure) as exc:
        hg.guard(repo.root, "f" * 40, hg.WORKTREE)
    assert exc.value.code == "HISTORY_BASE_UNAVAILABLE"


def test_non_utf8_protected_file_fails(repo):
    repo.next_batch()
    with open(os.path.join(repo.root, "docs", "AUDIT-LOG.md"), "ab") as fh:
        fh.write(b"\xff\n")
    assert [f.split()[0] for f in hg.check_repo(repo.root, as_if_committed=True)[0]] == ["HISTORY_NOT_UTF8"]


def test_not_a_git_repository_is_not_applicable():
    with tempfile.TemporaryDirectory() as d:
        assert hg.check_repo(d) == ([], ["此路徑不是 git repository，本檢查不適用"])


def test_subdirectory_of_a_repository_is_not_treated_as_not_applicable(repo):
    sub = os.path.join(repo.root, "docs")
    assert [f.split()[0] for f in hg.check_repo(sub)[0]] == ["HISTORY_ROOT_NOT_TOPLEVEL"]


def test_git_that_cannot_answer_inside_a_repository_fails_closed(repo, monkeypatch):
    # 例如 dubious ownership：git rev-parse 失敗，但路徑上有 .git，不得當成「不適用」
    real = hg._git
    monkeypatch.setattr(hg, "_git", lambda root, *a, **kw: (128, b"") if a[:1] == ("rev-parse",) else real(root, *a, **kw))
    assert [f.split()[0] for f in hg.check_repo(repo.root)[0]] == ["HISTORY_GIT_UNAVAILABLE"]
    assert hg.check_repo(os.path.join(repo.root, "docs"))[0][0].startswith("HISTORY_GIT_UNAVAILABLE")
    with tempfile.TemporaryDirectory() as d:
        assert hg.check_repo(d) == ([], ["此路徑不是 git repository，本檢查不適用"])


def test_git_errors_inside_a_repository_fail_closed(repo, monkeypatch):
    repo.next_batch()
    real = hg._git

    def broken(root, *args, **kw):
        if args[:1] == ("ls-tree",):
            return 128, b""
        return real(root, *args, **kw)

    monkeypatch.setattr(hg, "_git", broken)
    assert [f.split()[0] for f in hg.check_repo(repo.root, as_if_committed=True)[0]] == ["HISTORY_TREE_UNREADABLE"]


# ---------------------------------------------------------------------------
# 與 CHECK 17 的分工：同一 commit 不會得到相反結論
# ---------------------------------------------------------------------------

def _spec(base, mods):
    body = [f"HEAD: {base[:7]}", ""]
    for n, (path, anchor, payload) in enumerate(mods, 1):
        body += [f"=== MOD {n} ===", f"file: {path}", "mode: replace", "--- ANCHOR ---", anchor,
                 "--- PAYLOAD ---", payload, "--- END MOD ---", ""]
    return "\n".join(body)


def _legal_backfill(base):
    return EXEC_HEADER + f"| {base[:7]} | d | r | 通過 | 無 |\n| 本批 | d | r2 | 通過 | 無 |\n"


@pytest.fixture
def spec_repo(repo):
    """舊 spec 路徑：Base §5.1 沒有上一批 placeholder，spec 以 MOD 宣告每個異動檔。"""
    _write(repo.root, "docs/T.md", "A\nB\nC\n")
    _write(repo.root, hg.LEDGER_FILE, ledger("- `" + P + "`（T0）：初始。"))
    _write(repo.root, hg.RECORD_FILE, _record("T0", "0" * 40))
    repo.commit("t")
    return repo


def _spec_batch(repo, extra_mods=()):
    base = _run(repo.root, "git", "rev-parse", "HEAD")
    old_record, new_record = _record("T0", "0" * 40), _record("T1", base)
    _write(repo.root, "docs/T.md", "A\nZ\nC\n")
    _write(repo.root, hg.RECORD_FILE, new_record)
    _write(repo.root, "docs/EXEC-LOG.md", _legal_backfill(base))
    old_row, own_row = "- `" + P + "`（T0）：初始。", f"- {PH('T1')}：新批。"   # C1c：本批自己的 placeholder
    _write(repo.root, hg.LEDGER_FILE, ledger(own_row, old_row))
    mods = [("docs/T.md", "B", "Z"), (hg.RECORD_FILE, old_record.strip(), new_record.strip()),
            (hg.LEDGER_FILE, old_row, own_row + "\n" + old_row), *extra_mods]
    _write(repo.root, f"docs/batches/{base[:7]}-x.spec.txt", _spec(base, mods))
    return base


def test_spec_batch_exec_log_backfill_uses_check_17_rule_before_and_after_commit(spec_repo):
    _spec_batch(spec_repo)
    for fn in (lambda: hg.check_repo(spec_repo.root, as_if_committed=True),
               lambda: cc.check_28_history_anchor_guard(spec_repo.root, as_if_committed=True)):
        fails, infos = fn()
        assert fails == [] and any("CHECK 17 的狀態流轉規則" in i for i in infos)
    spec_repo.commit("c1")
    c17_fails, c17_infos = cc.check_17_spec_replay(spec_repo.root)
    assert c17_fails == [] and any("狀態流轉驗證通過" in i for i in c17_infos)
    fails, infos = cc.check_28_history_anchor_guard(spec_repo.root)
    assert fails == [] and any("CHECK 17 的狀態流轉規則" in i for i in infos)


def _altered_backfill(base):
    return EXEC_HEADER + f"| {base[:7]} | d | ALTERED | 通過 | 無 |\n| 本批 | d | r2 | 通過 | 無 |\n"


@pytest.mark.parametrize("stage_spec", [False, True])
def test_b01_spec_batch_exec_log_edit_fails_before_commit_too(spec_repo, stage_spec):
    """第二意見 B01：提交前 CHECK 28 不再委派給讀舊 HEAD 的 CHECK 17；spec 未 stage 或已 stage 都判定。"""
    base = _spec_batch(spec_repo)
    _write(spec_repo.root, "docs/EXEC-LOG.md", _altered_backfill(base))
    if stage_spec:
        _run(spec_repo.root, "git", "add", "-A")
    expected = "HISTORY_EXEC_LOG_TRANSITION_INVALID docs/EXEC-LOG.md:0  回填列除第一欄 commit identity 外之其餘內容遭修改"
    assert cc.check_17_spec_replay(spec_repo.root)[0] == []           # CHECK 17 提交前看的是舊 HEAD
    assert hg.check_repo(spec_repo.root, as_if_committed=True)[0] == [expected]
    assert cc.check_28_history_anchor_guard(spec_repo.root, as_if_committed=True)[0] == [expected]
    spec_repo.commit("c1")
    assert cc.check_17_spec_replay(spec_repo.root)[0] == ["docs/EXEC-LOG.md:0  回填列除第一欄 commit identity 外之其餘內容遭修改"]
    assert cc.check_28_history_anchor_guard(spec_repo.root)[0] == [expected]


EXEC_VARIANTS = {
    "legal_backfill": _legal_backfill,
    "altered_backfill": _altered_backfill,
    "wrong_identity": lambda b: EXEC_HEADER + "| deadbee | d | r | 通過 | 無 |\n| 本批 | d | r2 | 通過 | 無 |\n",
    "deleted_row": lambda b: EXEC_HEADER + "| 本批 | d | r2 | 通過 | 無 |\n",
    "no_new_row": lambda b: EXEC_HEADER + f"| {b[:7]} | d | r | 通過 | 無 |\n",
    "header_edit": lambda b: EXEC_HEADER.replace("檢查範圍", "範圍") + f"| {b[:7]} | d | r | 通過 | 無 |\n| 本批 | d | r2 | 通過 | 無 |\n",
}


@pytest.mark.parametrize("variant", sorted(EXEC_VARIANTS))
def test_spec_batch_check_28_agrees_with_check_17_before_and_after_commit(spec_repo, variant):
    base = _spec_batch(spec_repo)
    _write(spec_repo.root, "docs/EXEC-LOG.md", EXEC_VARIANTS[variant](base))
    before = cc.check_28_history_anchor_guard(spec_repo.root, as_if_committed=True)[0]
    spec_repo.commit("c1")
    c17 = cc.check_17_spec_replay(spec_repo.root)[0]
    after = cc.check_28_history_anchor_guard(spec_repo.root)[0]
    assert before == after
    assert [f.split(" ", 1)[1] for f in after] == c17
    assert (variant == "legal_backfill") == (after == [])


def test_same_exec_log_backfill_without_spec_is_judged_only_by_check_28(repo):
    base = repo.next_batch()
    _write(repo.root, "docs/EXEC-LOG.md", _legal_backfill(base))
    repo.commit("c1")
    c17_fails, c17_infos = cc.check_17_spec_replay(repo.root)
    assert c17_fails == [] and any("不在 CHECK 17 強制範圍內" in i for i in c17_infos)
    fails, _ = cc.check_28_history_anchor_guard(repo.root)
    assert [f.split()[0] for f in fails] == ["HISTORY_PROTECTED_LINE_CHANGED"]


def test_spec_batch_still_protects_audit_log(spec_repo):
    """spec 宣告了 AUDIT-LOG 的修改，CHECK 17 放行；v1 不提供授權例外，CHECK 28 仍 FAIL。"""
    _spec_batch(spec_repo, [("docs/AUDIT-LOG.md", "| a | 1 |", "| a | 9 |")])
    _write(spec_repo.root, "docs/AUDIT-LOG.md", "# audit\n| a | 9 |\n")
    spec_repo.commit("c1")
    assert cc.check_17_spec_replay(spec_repo.root)[0] == []
    assert [f.split()[0] for f in cc.check_28_history_anchor_guard(spec_repo.root)[0]] == ["HISTORY_PROTECTED_LINE_CHANGED"]


def test_spec_batch_beyond_check_17_scope_fails(spec_repo):
    base = _spec_batch(spec_repo)
    spec_repo.commit("c1")
    _write(spec_repo.root, "docs/T.md", "A\nZ\nC\nD\n")
    head = spec_repo.commit("c2 without new record")    # HEAD 的 record base 不再是 HEAD 的 parent
    with pytest.raises(hg.GuardFailure) as exc:
        hg.guard(spec_repo.root, base, head)
    assert exc.value.code == "HISTORY_SPEC_SCOPE_UNENFORCED"
    assert [f.split()[0] for f in hg.check_repo(spec_repo.root)[0]] == ["HISTORY_BASE_NOT_PARENT"]


# ---------------------------------------------------------------------------
# 接線與命令列
# ---------------------------------------------------------------------------

def test_run_checks_reports_check_28_failure(monkeypatch, capsys):
    monkeypatch.setattr(cc, "check_28_history_anchor_guard", lambda *a, **k: (["HISTORY_X injected"], []))
    with pytest.raises(SystemExit) as exc:
        cc.run_checks([])
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "CHECK 28: 受保護歷史與 §5.1 帳本錨定守衛" in out and "HISTORY_X injected" in out


def test_run_checks_passes_as_if_flag_to_check_28(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(cc, "check_28_history_anchor_guard",
                        lambda root, as_if_committed=False: seen.append(as_if_committed) or ([], []))
    with pytest.raises(SystemExit):
        cc.run_checks(["--as-if-committed"])
    capsys.readouterr()
    assert seen == [True]


def test_cli_reports_fixed_lines_and_exit_codes(repo):
    base = repo.next_batch()
    head = repo.commit("c1")
    script = os.path.join(REPO_ROOT, "scripts", "history_guard.py")
    ok = subprocess.run([sys.executable, script, "--repo", repo.root, "--base", base, "--target", head],
                        capture_output=True, text=True, encoding="utf-8")
    assert ok.returncode == 0 and ok.stdout.splitlines()[-1] == "HISTORY_GUARD PASS"
    bad = subprocess.run([sys.executable, script, "--repo", repo.root, "--base", head, "--target", base],
                         capture_output=True, text=True, encoding="utf-8")
    assert bad.returncode == 1 and bad.stdout.splitlines()[-1] == "HISTORY_GUARD FAIL"
    assert any(line.startswith("FAIL HISTORY_BASE_NOT_ANCESTOR") for line in bad.stdout.splitlines())
    with tempfile.TemporaryDirectory() as d:
        none = subprocess.run([sys.executable, script, "--repo", d, "--base", "x", "--target", "y"],
                              capture_output=True, text=True, encoding="utf-8")
    assert none.returncode == 1 and "FAIL HISTORY_NOT_GIT_REPO" in none.stdout
    nested = subprocess.run([sys.executable, script, "--repo", os.path.join(repo.root, "docs"), "--base", base,
                             "--target", head], capture_output=True, text=True, encoding="utf-8")
    assert nested.returncode == 1 and "FAIL HISTORY_ROOT_NOT_TOPLEVEL" in nested.stdout
