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
    check_23_transport_exclusivity_guard,
    check_24_active_state_projection_guard,
    verify_check_consistency_inventory,
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


def test_check_10_handover_router_missing_section_fails_without_substitution(tmp_path):
    """Fix 4A: docs/HANDOVER.md 無 §10.4 時必須 FAIL，不得自動換檔替換成 archive 快照判 PASS"""
    docs = tmp_path / "docs"
    docs.mkdir()
    handover = docs / "HANDOVER.md"
    handover.write_text("### 10. 歸檔與歷史資料\n### 11. 規範驗證入口\n", encoding="utf-8")

    archive_dir = docs / "archive" / "handover"
    archive_dir.mkdir(parents=True)
    archive_file = archive_dir / "HANDOVER-pre-router-568209e.md"
    archive_file.write_text("### 10.4 核對時的重點檢查項\n## 11. Claude 自身的已知失誤\n", encoding="utf-8")

    rules = tmp_path / ".agents" / "rules"
    rules.mkdir(parents=True)
    source_file = rules / "test-rule.md"
    source_file.write_text("此規則原本記在 `docs/HANDOVER.md` §10.4 與 §11。\n", encoding="utf-8")

    fails, infos = check_10_section_refs(str(tmp_path))
    # §10.4 must fail against docs/HANDOVER.md, even though archive has §10.4!
    assert len(fails) == 1
    assert "目標檔案 (docs/HANDOVER.md) 找不到章節標題: §10.4" in fails[0]
    assert any("跨檔案引用: §11 -> docs/HANDOVER.md" in i for i in infos)


def test_check_10_explicit_archive_target_with_existing_section_passes(tmp_path):
    """Fix 4B: 明確引用 docs/archive/handover/HANDOVER-pre-router-568209e.md §10.4 且存在時 PASS"""
    docs = tmp_path / "docs"
    docs.mkdir()
    archive_dir = docs / "archive" / "handover"
    archive_dir.mkdir(parents=True)
    archive_file = archive_dir / "HANDOVER-pre-router-568209e.md"
    archive_file.write_text("### 10.4 核對時的重點檢查項\n## 11. Claude 自身的已知失誤\n", encoding="utf-8")

    rules = tmp_path / ".agents" / "rules"
    rules.mkdir(parents=True)
    source_file = rules / "test-rule.md"
    source_file.write_text("此規則原本記在 `docs/archive/handover/HANDOVER-pre-router-568209e.md` §10.4 與 §11。\n", encoding="utf-8")

    fails, infos = check_10_section_refs(str(tmp_path))
    assert len(fails) == 0
    assert any("跨檔案引用: §10.4 -> docs/archive/handover/HANDOVER-pre-router-568209e.md" in i for i in infos)
    assert any("跨檔案引用: §11 -> docs/archive/handover/HANDOVER-pre-router-568209e.md" in i for i in infos)


def test_check_10_current_handover_existing_section_passes(tmp_path):
    """Fix 4C: 明確引用 docs/HANDOVER.md 且該 current router 確實有該 section 時 PASS"""
    docs = tmp_path / "docs"
    docs.mkdir()
    handover = docs / "HANDOVER.md"
    handover.write_text("### 10. 歸檔與歷史資料\n### 11. 規範驗證入口\n", encoding="utf-8")

    rules = tmp_path / ".agents" / "rules"
    rules.mkdir(parents=True)
    source_file = rules / "test-rule.md"
    source_file.write_text("驗證入口見 `docs/HANDOVER.md` §11。\n", encoding="utf-8")

    fails, infos = check_10_section_refs(str(tmp_path))
    assert len(fails) == 0
    assert any("跨檔案引用: §11 -> docs/HANDOVER.md" in i for i in infos)


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
    al.write_text("| 369c61ad6dea6e289d113b1a4119ae25911e93d2 | 2026-09-13 | §5.1 | **核對通過** | PASS |\n", encoding="utf-8")

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
# Meta-test: Active CHECK Inventory Integrity (1..24)
# ===========================================================================

def extract_active_check_ids_from_source(source_text: str):
    """Extract check IDs from run_checks source lines matching print(... CHECK <N> [-:] ...)."""
    check_ids = []
    for line in source_text.splitlines():
        line_s = line.strip()
        if "print(" in line_s and "CHECK" in line_s:
            m = re.search(r'print\(.*?CHECK\s+(\d+)\s*[-:]', line_s)
            if m:
                check_ids.append(int(m.group(1)))
    return check_ids


def test_active_check_inventory_continuous_1_to_26():
    """現行 active CHECK IDs 必須為 1..26 連續、無重複、無缺號"""
    import check_consistency
    import inspect
    source = inspect.getsource(check_consistency.run_checks)
    check_ids = extract_active_check_ids_from_source(source)
    expected = list(range(1, 27))
    assert len(check_ids) == 26, f"Expected 26 checks, found {len(check_ids)}: {check_ids}"
    assert check_ids == expected, f"Check IDs drift: {check_ids} != {expected}"


def test_active_check_inventory_negative_controls():
    """
    Negative controls for check inventory validation (B-109 M2 repair):
    Must deterministically prove that missing or duplicate check IDs fail,
    docstring or run_checks inventory omissions fail, and both punctuation styles
    ('CHECK N -' and 'CHECK N:') are supported, while current real source passes.
    """
    cc_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "check_consistency.py"))
    with open(cc_path, "r", encoding="utf-8") as f:
        real_content = f.read()

    # Positive control: current real source 1..26 exactly once -> PASS
    ok, err, metadata = verify_check_consistency_inventory(real_content)
    assert ok is True, f"Positive control failed: {err}"
    assert metadata["total_checks"] == 26
    assert metadata["docstring_ids"] == list(range(1, 27))
    assert metadata["run_checks_ids"] == list(range(1, 27))

    # A. Active CHECK 26 removed -> full inventory validation FAIL
    tampered_a = real_content.replace('print("\\nCHECK 26: M2 計畫與執行重放暨證據完整性守衛")', '# removed check 26')
    ok_a, err_a, _ = verify_check_consistency_inventory(tampered_a)
    assert ok_a is False
    assert "run_checks() inventory mismatch" in err_a
    assert "26" in err_a

    # B. Active CHECK 26 duplicate -> FAIL
    # B1. Duplicate in run_checks
    tampered_b1 = real_content.replace(
        'print("\\nCHECK 26: M2 計畫與執行重放暨證據完整性守衛")',
        'print("\\nCHECK 26: M2 計畫與執行重放暨證據完整性守衛")\n    print("\\nCHECK 26 - M2 計畫與執行重放暨證據完整性守衛")'
    )
    ok_b1, err_b1, _ = verify_check_consistency_inventory(tampered_b1)
    assert ok_b1 is False
    assert "Duplicate CHECK 26 in run_checks()" in err_b1

    # B2. Duplicate in docstring
    tampered_b2 = real_content.replace(
        'CHECK 26 — M2 計畫與執行重放暨證據完整性守衛',
        'CHECK 26 — M2 計畫與執行重放暨證據完整性守衛\n  CHECK 26 — M2 計畫與執行重放暨證據完整性守衛'
    )
    ok_b2, err_b2, _ = verify_check_consistency_inventory(tampered_b2)
    assert ok_b2 is False
    assert "Duplicate CHECK 26 in docstring inventory" in err_b2

    # C. Docstring inventory omits CHECK 20 or CHECK 26 -> FAIL
    # C1. Docstring omits CHECK 20
    tampered_c1 = re.sub(r'CHECK 20\s*—.*?\n', '', real_content)
    ok_c1, err_c1, _ = verify_check_consistency_inventory(tampered_c1)
    assert ok_c1 is False
    assert "Docstring inventory mismatch" in err_c1
    assert "20" in err_c1

    # C2. Docstring omits CHECK 26
    tampered_c2 = re.sub(r'CHECK 26\s*—.*?\n', '', real_content)
    ok_c2, err_c2, _ = verify_check_consistency_inventory(tampered_c2)
    assert ok_c2 is False
    assert "Docstring inventory mismatch" in err_c2
    assert "26" in err_c2

    # D. run_checks inventory omits an active ID -> FAIL
    tampered_d = real_content.replace('print("CHECK 1 - 控制字元")', '# removed check 1')
    ok_d, err_d, _ = verify_check_consistency_inventory(tampered_d)
    assert ok_d is False
    assert "run_checks() inventory mismatch" in err_d
    assert "1" in err_d

    # E. Supports both 'CHECK N -' and 'CHECK N:' punctuations
    tampered_e = real_content.replace('print("\\nCHECK 4 - 三層 README 完整性")', 'print("\\nCHECK 4: 三層 README 完整性")')
    tampered_e = tampered_e.replace('print("\\nCHECK 26: M2 計畫與執行重放暨證據完整性守衛")', 'print("\\nCHECK 26 - M2 計畫與執行重放暨證據完整性守衛")')
    ok_e, err_e, meta_e = verify_check_consistency_inventory(tampered_e)
    assert ok_e is True, f"Expected punctuation tolerance but got: {err_e}"
    assert meta_e["run_checks_ids"] == list(range(1, 27))



# ===========================================================================
# Defect 7: CHECK 23 Transport Exclusivity Guard
# ===========================================================================

def test_check_23_positive_control_optional_adapter(tmp_path):
    """CHECK 23 Positive Control: 包含 update_ref 作為 optional adapter 時 PASS"""
    agents = tmp_path / ".agents" / "rules"
    agents.mkdir(parents=True)
    rule_file = agents / "git-and-reporting.md"
    rule_file.write_text(
        "# Transport Rules\nupdate_ref may be one optional adapter when available and explicitly selected; it is not the only transport.\n",
        encoding="utf-8"
    )
    fails, infos = check_23_transport_exclusivity_guard(str(tmp_path))
    assert len(fails) == 0
    assert any("零排他性 transport lock-in" in i for i in infos)


def test_check_23_negative_control_exclusive_binding_fail(tmp_path):
    """CHECK 23 Negative Control: 排他性 update_ref 描述必須 fail-closed"""
    agents = tmp_path / ".agents" / "rules"
    agents.mkdir(parents=True)
    rule_file = agents / "git-and-reporting.md"
    rule_file.write_text(
        "# Transport Rules\nmain ref update only allowed through update_ref\n",
        encoding="utf-8"
    )
    fails, infos = check_23_transport_exclusivity_guard(str(tmp_path))
    assert len(fails) >= 1
    assert any("exclusive update_ref binding" in f for f in fails)


def test_check_23_negative_control_sole_transport_fail(tmp_path):
    """CHECK 23 Negative Control: 將 update_ref 描述為唯一傳輸機制時判定 FAIL"""
    claude_rules = tmp_path / ".claude" / "rules"
    claude_rules.mkdir(parents=True)
    selftest_file = claude_rules / "auditor-selftest.md"
    selftest_file.write_text(
        "# Selftest\napproved force=false update_ref 是唯一 production transport\n",
        encoding="utf-8"
    )
    fails, infos = check_23_transport_exclusivity_guard(str(tmp_path))
    assert len(fails) >= 1
    assert any("update_ref 被描述為唯一傳輸機制" in f for f in fails)


# ===========================================================================
# Defect 8: CHECK 24 Active State Projection Drift Guard
# ===========================================================================

def test_check_24_positive_control_current_projection(tmp_path):
    """CHECK 24 Positive Control: 正確更正之活動狀態投影 PASS"""
    docs = tmp_path / "docs"
    docs.mkdir()
    tb_file = docs / "TASKBOARD.md"
    tb_file.write_text(
        "| TG-MVP-01B | 進行中 | G2 權威規則落地：D1 transport contract 已 active on main，現正由 T1 bootstrap 轉為 transport-neutral K1 invariant |\n",
        encoding="utf-8"
    )
    rb_file = docs / "refactor-backlog.md"
    rb_file.write_text(
        "## 五、交接與當前狀態\n§5.4 當前狀態：new transport contract ACTIVE ON MAIN\n",
        encoding="utf-8"
    )
    fails, infos = check_24_active_state_projection_guard(str(tmp_path))
    assert len(fails) == 0
    assert any("活動狀態投影一致" in i for i in infos)
    assert any("可變狀態投影一致" in i for i in infos)


def test_check_24_negative_control_stale_taskboard_projection_fail(tmp_path):
    """CHECK 24 Negative Control: TASKBOARD 包含過期 protected PR 模式宣告時判定 FAIL"""
    docs = tmp_path / "docs"
    docs.mkdir()
    tb_file = docs / "TASKBOARD.md"
    tb_file.write_text(
        "| TG-MVP-01B | 進行中 | G2 權威規則落地；現行維持 protected PR 生產傳輸模式；待 B-103 完成 |\n",
        encoding="utf-8"
    )
    fails, infos = check_24_active_state_projection_guard(str(tmp_path))
    assert len(fails) >= 1
    assert any("過期活動狀態投影 (現行維持 protected PR 生產傳輸模式)" in f for f in fails)


def test_check_24_negative_control_stale_backlog_sec5_projection_fail(tmp_path):
    """CHECK 24 Negative Control: refactor-backlog §5 包含過期維持 protected PR 宣告時判定 FAIL"""
    docs = tmp_path / "docs"
    docs.mkdir()
    rb_file = docs / "refactor-backlog.md"
    rb_file.write_text(
        "## 五、交接與當前狀態\n§5.4 當前狀態：維持 protected PR 生產傳輸\n",
        encoding="utf-8"
    )
    fails, infos = check_24_active_state_projection_guard(str(tmp_path))
    assert len(fails) >= 1
    assert any("過期活動狀態投影 (維持 protected PR 生產傳輸)" in f for f in fails)


def test_check_24_positive_control_historical_c06_with_k1_transport_neutral_pass(tmp_path):
    """CHECK 24 Positive Control: C-06 說明歷史原 Option B 曾採 Require PR，但 current K1 transport-neutral 判定 PASS"""
    docs = tmp_path / "docs"
    docs.mkdir()
    tb_file = docs / "TASKBOARD.md"
    tb_file.write_text(
        "| C-06 | 已裁決 | 歷史裁決 Option B 建立 preventive GitHub gate 曾採 Require PR，後由 D-U9 / B-103 / K1-A 對 transport mechanism 進一步 refine/supersede：現行伺服端保護權威為 GitHub ruleset required checks，當前傳輸模式收斂為 batch candidate -> exact-SHA checks -> SAME SHA fast-forward；Require PR 不再是 current mandatory transport |\n",
        encoding="utf-8"
    )
    rb_file = docs / "refactor-backlog.md"
    rb_file.write_text(
        "### 5.3 待使用者裁決\n| 4 | 事項 | 歷史原 Option B 曾採 Require PR，後由 D-U9 / K1-A 進一步 refine/supersede；現行 K1-A 傳輸真相為 batch branch -> exact SHA checks -> SAME SHA fast-forward |\n",
        encoding="utf-8"
    )
    fails, infos = check_24_active_state_projection_guard(str(tmp_path))
    assert len(fails) == 0
    assert any("活動狀態投影一致" in i for i in infos)
    assert any("可變狀態投影一致" in i for i in infos)


def test_check_24_negative_control_c06_mandatory_pr_fail(tmp_path):
    """CHECK 24 Negative Control: C-06 current row 重新宣告 main 未來必須 Require PR 時判定 FAIL"""
    docs = tmp_path / "docs"
    docs.mkdir()
    tb_file = docs / "TASKBOARD.md"
    tb_file.write_text(
        "| C-06 | 已裁決 | 是否將 GitHub Verify 升級為 main 的 preventive required check | 使用者已裁決採 Option B：main 未來必須由 preventive GitHub gate 保護（Require PR + Verify success before merge to main） |\n",
        encoding="utf-8"
    )
    fails, infos = check_24_active_state_projection_guard(str(tmp_path))
    assert len(fails) >= 1
    assert any("過期活動狀態投影 (main 未來必須 Require PR)" in f for f in fails)


def test_check_24_negative_control_backlog_sec53_du9_stale_pr_mode_fail(tmp_path):
    """CHECK 24 Negative Control: refactor-backlog §5.3 D-U9 重新宣告本批維持現行 PR 模式時判定 FAIL"""
    docs = tmp_path / "docs"
    docs.mkdir()
    rb_file = docs / "refactor-backlog.md"
    rb_file.write_text(
        "### 5.3 待使用者裁決\n| 4 | 事項 | 裁決結果見 C-06；本批維持現行 PR 模式，零工作流與 ruleset 異動 |\n",
        encoding="utf-8"
    )
    fails, infos = check_24_active_state_projection_guard(str(tmp_path))
    assert len(fails) >= 1
    assert any("過期活動狀態投影 (本批維持現行 PR 模式)" in f for f in fails)

