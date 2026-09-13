import os
import sys
import subprocess
import pytest
from pathlib import Path
import json
import re

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import check_consistency
from check_consistency import (
    check_1_control_chars,
    check_2_markdown_fences,
    check_3_markdown_links,
    check_5_sop_routes,
    check_6_old_hierarchy_paths,
    check_9_handover_head,
    check_10_section_refs,
    check_12_audit_log_cadence,
    check_13_trailing_newline,
    format_check_13_summary,
    check_14_simplified_chinese,
    check_16_exec_log_cadence,
)


# ===========================================================================
# Defect 1: CHECK 10 Cross-File & Same-File Exact Section Identity
# ===========================================================================

def test_check_10_target_exists_section_not_found_fail(tmp_path):
    """A. target file 存在，target section 不存在 -> FAIL"""
    rules = tmp_path / ".agents" / "rules"
    rules.mkdir(parents=True)
    source_file = rules / "source-rule.md"
    target_file = rules / "target-rule.md"

    target_file.write_text("# 1. 目標標題\n## 1.1 子標題\n", encoding="utf-8")
    # Reference target-rule.md §2.0 which does not exist in target_file
    source_file.write_text("參考 `target-rule.md` §2.0 說明。\n", encoding="utf-8")

    fails, infos = check_10_section_refs(str(tmp_path))
    assert len(fails) == 1
    assert "找不到章節標題: §2.0" in fails[0]


def test_check_10_section_in_wrong_file_fail(tmp_path):
    """B. section 存在於另一個錯誤檔案，但聲明 target file 不含該 section -> FAIL"""
    rules = tmp_path / ".agents" / "rules"
    rules.mkdir(parents=True)
    source_file = rules / "source-rule.md"
    target_a = rules / "target-a.md"
    target_b = rules / "target-b.md"

    target_a.write_text("# 1. A 檔案\n## 1.1 A 子項\n", encoding="utf-8")
    target_b.write_text("# 2. B 檔案\n## 2.5 B 子項\n", encoding="utf-8")
    # source_file declares target-a.md but references §2.5 which is only in target-b.md
    source_file.write_text("見 `target-a.md` §2.5。\n", encoding="utf-8")

    fails, infos = check_10_section_refs(str(tmp_path))
    assert len(fails) == 1
    assert "找不到章節標題: §2.5" in fails[0]


def test_check_10_cannot_resolve_target_fail(tmp_path):
    """C. 無法 deterministic resolve target file -> FAIL"""
    rules = tmp_path / ".agents" / "rules"
    rules.mkdir(parents=True)
    source_file = rules / "source-rule.md"

    # Mentions a cross-file indicator without any resolvable filename
    source_file.write_text("SOP_ 流程規範見 §9.9。\n", encoding="utf-8")

    fails, infos = check_10_section_refs(str(tmp_path))
    assert len(fails) == 1
    assert "無法確定性解析跨檔案引用目標: §9.9" in fails[0]


def test_check_10_real_format_same_line_target_and_section_pass(tmp_path):
    """D. 真實格式的：`filename.md` + `§X.Y` 同一行且 section 存在 -> PASS"""
    rules = tmp_path / ".agents" / "rules"
    rules.mkdir(parents=True)
    source_file = rules / "source-rule.md"
    principles = tmp_path / "PRINCIPLES.md"

    principles.write_text("# 0. 核心角色\n## 0.5 決策標準\n", encoding="utf-8")
    # Real repo format: `PRINCIPLES.md` §0.5
    source_file.write_text("角色邊界依 `PRINCIPLES.md` §0.5 辦理。\n", encoding="utf-8")

    fails, infos = check_10_section_refs(str(tmp_path))
    assert len(fails) == 0
    assert len(infos) == 1
    assert "跨檔案引用: §0.5 -> PRINCIPLES.md" in infos[0]


def test_check_10_cross_file_dotted_subsection_parent_fallback_fail(tmp_path):
    """Fix 1: target 只有 # 6. Root，引用 target.md §6.999 時必須 FAIL，不得 parent-heading fallback 假綠燈"""
    rules = tmp_path / ".agents" / "rules"
    rules.mkdir(parents=True)
    source_file = rules / "source-rule.md"
    target_file = rules / "target-rule.md"

    target_file.write_text("# 6. 目標根標題\n正文說明\n", encoding="utf-8")
    source_file.write_text("參考 `target-rule.md` §6.999 說明。\n", encoding="utf-8")

    fails, infos = check_10_section_refs(str(tmp_path))
    assert len(fails) == 1
    assert "目標檔案 (.agents/rules/target-rule.md) 找不到章節標題: §6.999" in fails[0]


def test_check_10_same_file_dotted_subsection_parent_fallback_fail(tmp_path):
    """Fix 1: same-file 只有 # 6. Root，正文出現 §6.999 時必須 FAIL，不得 parent-heading fallback 假綠燈"""
    rules = tmp_path / ".agents" / "rules"
    rules.mkdir(parents=True)
    rule_file = rules / "single-rule.md"

    rule_file.write_text("# 6. 目標根標題\n正文見 §6.999 說明。\n", encoding="utf-8")

    fails, infos = check_10_section_refs(str(tmp_path))
    assert len(fails) == 1
    assert "找不到章節標題: §6.999" in fails[0]


def test_check_10_exact_valid_subsection_pass(tmp_path):
    """Fix 1: target 有 # 6. Root 與 ## 6.1 Valid，引用 target.md §6.1 -> PASS"""
    rules = tmp_path / ".agents" / "rules"
    rules.mkdir(parents=True)
    source_file = rules / "source-rule.md"
    target_file = rules / "target-rule.md"

    target_file.write_text("# 6. 目標根標題\n## 6.1 Valid 子標題\n正文說明\n", encoding="utf-8")
    source_file.write_text("參考 `target-rule.md` §6.1 說明。\n", encoding="utf-8")

    fails, infos = check_10_section_refs(str(tmp_path))
    assert len(fails) == 0
    assert any("跨檔案引用: §6.1 -> .agents/rules/target-rule.md" in i for i in infos)


def test_check_10_refactor_backlog_root_5_special_case_pass(tmp_path):
    """Fix 1: docs/refactor-backlog.md 對 root §5 特殊案例合法保留，但非存在子節 §5.999 仍必須 FAIL"""
    docs = tmp_path / "docs"
    docs.mkdir()
    bl = docs / "refactor-backlog.md"
    bl.write_text("### 5.1 上一批狀態\n### 5.4 進行中\n", encoding="utf-8")

    rules = tmp_path / ".agents" / "rules"
    rules.mkdir(parents=True)
    source_file = rules / "source-rule.md"
    source_file.write_text("見 `docs/refactor-backlog.md` §5 交接區。\n見 `docs/refactor-backlog.md` §5.1。\n", encoding="utf-8")

    fails, infos = check_10_section_refs(str(tmp_path))
    assert len(fails) == 0
    assert len(infos) == 2

    # But non-existent §5.999 must FAIL:
    source_file.write_text("見 `docs/refactor-backlog.md` §5.999。\n", encoding="utf-8")
    fails, infos = check_10_section_refs(str(tmp_path))
    assert len(fails) == 1
    assert "目標檔案 (docs/refactor-backlog.md) 找不到章節標題: §5.999" in fails[0]


# ===========================================================================
# Defect 2: Fail-Closed on Read/Decode Errors (Direct Production Helper Calls)
# ===========================================================================

def test_check_1_read_error_fail(tmp_path):
    """CHECK 1: 非法 UTF-8 或讀取失敗時判定 FAIL，直接呼叫 production helper"""
    bad_file = tmp_path / "corrupt.md"
    bad_file.write_bytes(b"\xff\xfe\x00\x00\xaa\xbb\xcc")
    fails, infos = check_1_control_chars(str(tmp_path))
    assert len(fails) == 1
    assert "檔案讀取失敗" in fails[0]


def test_check_2_read_error_fail(tmp_path):
    """CHECK 2: markdown 檔案解碼/讀取失敗時判定 FAIL，直接呼叫 production helper"""
    bad_file = tmp_path / "bad.md"
    bad_file.write_bytes(b"\x80\x81\x82\xff")
    fails, infos = check_2_markdown_fences(str(tmp_path))
    assert len(fails) == 1
    assert "檔案讀取失敗" in fails[0]


def test_check_3_read_error_fail(tmp_path):
    """CHECK 3: markdown 檔案無法讀取時判定 FAIL"""
    bad_file = tmp_path / "bad.md"
    bad_file.write_bytes(b"\x80\x81\x82\xff")
    fails, infos = check_3_markdown_links(str(tmp_path))
    assert len(fails) >= 1
    assert any("檔案讀取失敗" in f for f in fails)


def test_check_10_read_error_fail(tmp_path):
    """CHECK 10: 規則檔案無法以 utf-8 解碼時判定 FAIL"""
    rules = tmp_path / ".agents" / "rules"
    rules.mkdir(parents=True)
    bad_rule = rules / "corrupt-rule.md"
    bad_rule.write_bytes(b"\xff\xfe\x80\x90")
    fails, infos = check_10_section_refs(str(tmp_path))
    assert len(fails) >= 1
    assert any("檔案讀取失敗" in f for f in fails)


def test_check_13_read_error_fail(tmp_path, monkeypatch):
    """CHECK 13: 檔案二進位讀取失敗時判定 FAIL"""
    f = tmp_path / "test.md"
    f.write_text("Hello\n", encoding="utf-8")
    
    orig_open = open
    def mock_open(path, *args, **kwargs):
        if str(path).endswith("test.md") and "rb" in args:
            raise IOError("Simulated IO failure")
        return orig_open(path, *args, **kwargs)
    
    monkeypatch.setattr("builtins.open", mock_open)
    fails, infos = check_13_trailing_newline(str(tmp_path))
    assert len(fails) == 1
    assert "檔案讀取失敗: Simulated IO failure" in fails[0]


def test_check_14_read_error_fail(tmp_path):
    """CHECK 14: markdown 檔案解碼失敗時判定 FAIL"""
    bad_file = tmp_path / "corrupt.md"
    bad_file.write_bytes(b"\xff\xfe\xaa\xbb")
    fails, infos = check_14_simplified_chinese(str(tmp_path))
    assert len(fails) >= 1
    assert any("檔案讀取失敗" in f for f in fails)


# ===========================================================================
# Defect 3: Git Fact Fail-Closed
# ===========================================================================

def test_check_9_git_ancestry_unavailable_fail(tmp_path):
    """CHECK 9: 無法取得 git 歷史資訊 (ancestry) 時判定 FAIL"""
    docs = tmp_path / "docs"
    docs.mkdir()
    bl = docs / "refactor-backlog.md"
    bl.write_text("上次核對通過的 HEAD：`369c61a`\n", encoding="utf-8")
    al = docs / "AUDIT-LOG.md"
    al.write_text("| 369c61ad6dea6e289d113b1a4119ae25911e93d2 | 2026-09-13 | §5.1 | 通過 | PASS |\n", encoding="utf-8")

    # git_ancestry is empty list
    fails, infos = check_9_handover_head(str(tmp_path), git_ancestry=[])
    assert len(fails) == 1
    assert "無法取得 git 歷史資訊" in fails[0]


def test_check_12_git_ancestry_unavailable_fail(tmp_path):
    """CHECK 12: git_ancestry 為空清單時判定 FAIL"""
    docs = tmp_path / "docs"
    docs.mkdir()
    al = docs / "AUDIT-LOG.md"
    al.write_text("| 369c61a | 2026-09-13 | §5.1 | 通過 | 備註 |\n", encoding="utf-8")

    fails, infos = check_12_audit_log_cadence(str(tmp_path), git_ancestry=[])
    assert len(fails) == 1
    assert "提供之 git_ancestry 為空" in fails[0]


def test_check_12_pending_range_still_passes(tmp_path):
    """CHECK 12 Contract: 合法 pending range (如落後 5 個 commit) 仍應 PASS"""
    docs = tmp_path / "docs"
    docs.mkdir()
    al = docs / "AUDIT-LOG.md"
    al.write_text("| 369c61a | 2026-09-13 | §5.1 | 通過 | 備註 |\n", encoding="utf-8")

    ancestry = ["head_c", "c4", "c3", "c2", "c1", "369c61a"]
    fails, infos = check_12_audit_log_cadence(str(tmp_path), git_ancestry=ancestry)
    assert len(fails) == 0
    assert any("pending commits since latest review: 5" in i for i in infos)


def test_check_16_git_rev_list_unavailable_fail(tmp_path, monkeypatch):
    """CHECK 16: git rev-list 失敗時判定 FAIL，不得保留 lag=0 假綠燈"""
    docs = tmp_path / "docs"
    docs.mkdir()
    el = docs / "EXEC-LOG.md"
    el.write_text("| 369c61a | 2026-09-13 | §3 | 通過 | 無 |\n", encoding="utf-8")

    # Mock subprocess.run returning non-zero returncode
    class MockProcess:
        returncode = 128
        stdout = ""
        stderr = "fatal: not a git repository"

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: MockProcess())
    fails, infos = check_16_exec_log_cadence(str(tmp_path))
    assert len(fails) == 1
    assert "無法取得 git rev-list" in fails[0]


# ===========================================================================
# Defect 4: Narrow Exemptions (CHECK 6 & CHECK 14)
# ===========================================================================

def test_check_6_json_to_flex_historical_exemption_pass(tmp_path):
    """CHECK 6: json-to-flex-renderer 原有歷史 runtime migration 說明通過 (直接呼叫 production helper)"""
    skills = tmp_path / "skills" / "platform" / "json-to-flex-renderer"
    skills.mkdir(parents=True)
    skill_file = skills / "SKILL.md"
    skill_file.write_text(
        "本技能負責將結構化 JSON 分析報告轉換為 LINE Flex Message。\n"
        "（註：`markdown_to_flex.js` 位於舊專案的\n"
        "`skills/03_Execution/line-bot-zero-delay/line-bot-project/`，\n"
        "屬 runtime 層程式碼，尚未遷移至 HH.AI_v2。）\n",
        encoding="utf-8",
    )
    fails, infos = check_6_old_hierarchy_paths(str(tmp_path))
    assert len(fails) == 0
    assert len(infos) == 1
    assert "略過已知殘留" in infos[0]


def test_check_6_json_to_flex_new_insertion_fail(tmp_path):
    """CHECK 6: 在 json-to-flex-renderer 插入新的舊分層路徑 -> FAIL (直接呼叫 production helper)"""
    skills = tmp_path / "skills" / "platform" / "json-to-flex-renderer"
    skills.mkdir(parents=True)
    skill_file = skills / "SKILL.md"
    skill_file.write_text(
        "本技能負責將結構化 JSON 分析報告轉換為 LINE Flex Message。\n"
        "新加入不合法路徑：`skills/01_Orchestrators/router/`。\n"
        "（註：`markdown_to_flex.js` 位於舊專案的\n"
        "`skills/03_Execution/line-bot-zero-delay/line-bot-project/`，\n"
        "屬 runtime 層程式碼，尚未遷移至 HH.AI_v2。）\n",
        encoding="utf-8",
    )
    fails, infos = check_6_old_hierarchy_paths(str(tmp_path))
    assert len(fails) == 1
    assert "殘留舊路徑: 01_Orchestrators" in fails[0]


def test_check_14_audit_log_historical_exemption_pass(tmp_path):
    """CHECK 14: AUDIT-LOG 內含簡體字且標註歷史說明 -> PASS (INFO)"""
    docs = tmp_path / "docs"
    docs.mkdir()
    al = docs / "AUDIT-LOG.md"
    al.write_text("歷史事故紀錄引用原簡體字形「时说」說明。\n", encoding="utf-8")
    fails, infos = check_14_simplified_chinese(str(tmp_path))
    assert len(fails) == 0
    assert len(infos) == 1
    assert "歷史紀錄引用例外" in infos[0]


def test_check_14_audit_log_plain_text_simplified_fail(tmp_path):
    """CHECK 14: AUDIT-LOG 內含普通正文簡體字（無歷史標註） -> FAIL"""
    docs = tmp_path / "docs"
    docs.mkdir()
    al = docs / "AUDIT-LOG.md"
    al.write_text("這是一個包含时说的一般正文描述。\n", encoding="utf-8")
    fails, infos = check_14_simplified_chinese(str(tmp_path))
    assert len(fails) == 1
    assert "包含簡體字" in fails[0]


# ===========================================================================
# Defect 5: PENDING_MIGRATION Exact Registry in CHECK 5
# ===========================================================================

def test_check_5_known_pending_migration_routes_pass(tmp_path):
    """CHECK 5: 已註冊的 PENDING_MIGRATION 路由正常略過並輸出 INFO (直接呼叫 production helper)"""
    sop = tmp_path / "SOP"
    sop.mkdir()
    idx_file = sop / "SOP_00A_Master_Index.json"
    idx_file.write_text(
        json.dumps({
            "special_trigger_routes": {
                "$$自動化_微型模型$$": "PENDING_MIGRATION:skills/agents/autoresearch-agent/SKILL.md",
                "$$LINE連線$$": "PENDING_MIGRATION:skills/platform/line-bot-zero-delay/SKILL.md"
            },
            "tags": {}
        }, ensure_ascii=False),
        encoding="utf-8"
    )
    fails, infos = check_5_sop_routes(str(tmp_path))
    assert len(fails) == 0
    assert len(infos) == 2
    assert any("略過已知未遷移路由: $$自動化_微型模型$$" in i for i in infos)
    assert any("略過已知未遷移路由: $$LINE連線$$" in i for i in infos)


def test_check_5_unknown_pending_migration_route_fail(tmp_path):
    """CHECK 5: 未註冊的任意 PENDING_MIGRATION:bypass -> FAIL (直接呼叫 production helper)"""
    sop = tmp_path / "SOP"
    sop.mkdir()
    idx_file = sop / "SOP_00A_Master_Index.json"
    idx_file.write_text(
        json.dumps({
            "special_trigger_routes": {
                "$$未授權路由$$": "PENDING_MIGRATION:skills/agents/malicious-bypass/SKILL.md"
            },
            "tags": {}
        }, ensure_ascii=False),
        encoding="utf-8"
    )
    fails, infos = check_5_sop_routes(str(tmp_path))
    assert len(fails) == 1
    assert "未註冊的 PENDING_MIGRATION 路由: $$未授權路由$$" in fails[0]


# ===========================================================================
# Defect 6: CHECK 13 Advisory Output Behavior (Direct Production Rendering Path)
# ===========================================================================

def test_check_13_advisory_output_behavior(tmp_path):
    """CHECK 13: 當存在 observations 時，production rendering path 必須輸出 [ADVISORY] 且不得輸出 [PASS] 0 命中"""
    # Create file missing trailing newline in tmp_path
    f1 = tmp_path / "test1.md"
    f1.write_bytes(b"line without newline")
    f2 = tmp_path / "test2.py"
    f2.write_bytes(b"x = 1")

    fails, infos = check_13_trailing_newline(str(tmp_path), strict=False)
    assert len(fails) == 0
    assert len(infos) == 2

    # Execute real production rendering path
    lines = format_check_13_summary(fails, infos)
    rendered = "\n".join(lines)
    assert "[ADVISORY] 2 observations (non-blocking by design)" in rendered
    assert "[PASS] 0 命中" not in rendered

    # Counterexample: when 0 observations, production rendering path must output [PASS] 0 命中
    f1.write_bytes(b"line with newline\n")
    f2.write_bytes(b"x = 1\n")
    fails_clean, infos_clean = check_13_trailing_newline(str(tmp_path), strict=False)
    assert len(fails_clean) == 0
    assert len(infos_clean) == 0
    lines_clean = format_check_13_summary(fails_clean, infos_clean)
    rendered_clean = "\n".join(lines_clean)
    assert "[PASS] 0 命中" in rendered_clean
    assert "[ADVISORY]" not in rendered_clean


# ===========================================================================
# Meta-test: Active CHECK Inventory Integrity (1..18)
# ===========================================================================

def test_active_check_inventory_continuous_1_to_18():
    """現行 active CHECK IDs 必須為 1..18 連續、無重複、無缺號"""
    script_path = os.path.join(REPO_ROOT, "scripts", "check_consistency.py")
    with open(script_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Find all "CHECK <N> -" in execution run_checks
    check_ids = [int(m) for m in re.findall(r"CHECK\s+(\d+)\s+-\s+", content)]
    assert len(check_ids) == 18, f"Expected 18 checks, found {len(check_ids)}: {check_ids}"
    expected = list(range(1, 19))
    assert check_ids == expected, f"Check IDs drift: {check_ids} != {expected}"
