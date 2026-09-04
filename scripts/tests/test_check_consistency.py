import os
import sys
import pytest

# Ensure scripts dir is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from check_consistency import (
    check_8_taskboard_head,
    check_9_handover_head,
    check_10_section_refs,
    check_11_selftest_correspondence,
    check_12_audit_log_cadence,
    check_13_trailing_newline,
    check_14_simplified_chinese,
    check_15_context_conflict,
)


def test_check_8_taskboard_head_pass(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    tb.write_text("# 看板\n**最後更新**：2026-09-02，HEAD `08e6bbc` 之後\n", encoding="utf-8")
    fails, infos = check_8_taskboard_head(str(tmp_path), git_head="08e6bbc", git_prev="18af8ad")
    assert len(fails) == 0


def test_check_8_taskboard_head_prev_pass(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    tb.write_text("# 看板\n**最後更新**：2026-09-02，HEAD `18af8ad` 之後\n", encoding="utf-8")
    fails, infos = check_8_taskboard_head(str(tmp_path), git_head="08e6bbc", git_prev="18af8ad")
    assert len(fails) == 0


def test_check_8_taskboard_head_fail_lag(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    tb.write_text("# 看板\n**最後更新**：2026-09-02，HEAD `aaaaaaa` 之後\n", encoding="utf-8")
    fails, infos = check_8_taskboard_head(str(tmp_path), git_head="08e6bbc", git_prev="18af8ad")
    assert len(fails) == 1
    assert "落後超過一批" in fails[0]


def test_check_9_handover_head_pass(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    bl = docs / "refactor-backlog.md"
    bl.write_text("上次核對通過的 HEAD：08e6bbc\n", encoding="utf-8")
    fails, infos = check_9_handover_head(str(tmp_path), git_head="08e6bbc", git_prev="18af8ad")
    assert len(fails) == 0


def test_check_9_handover_head_fail_lag(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    bl = docs / "refactor-backlog.md"
    bl.write_text("上次核對通過的 HEAD：bbbbbbb\n", encoding="utf-8")
    fails, infos = check_9_handover_head(str(tmp_path), git_head="08e6bbc", git_prev="18af8ad")
    assert len(fails) == 1
    assert "落後超過一批" in fails[0]


def test_check_10_section_refs_pass(tmp_path):
    rules = tmp_path / ".agents" / "rules"
    rules.mkdir(parents=True)
    rule_file = rules / "test-rule.md"
    rule_file.write_text("# 1. 定義\n## 1.1 子項目\n見 §1.1。\n", encoding="utf-8")
    fails, infos = check_10_section_refs(str(tmp_path))
    assert len(fails) == 0


def test_check_10_section_refs_fail(tmp_path):
    rules = tmp_path / ".agents" / "rules"
    rules.mkdir(parents=True)
    rule_file = rules / "test-rule.md"
    rule_file.write_text("# 1. 定義\n## 1.1 子項目\n見 §9.9。\n", encoding="utf-8")
    fails, infos = check_10_section_refs(str(tmp_path))
    assert len(fails) == 1
    assert "找不到章節標題: §9.9" in fails[0]


def test_check_11_selftest_correspondence_pass(tmp_path):
    claude = tmp_path / ".claude" / "rules"
    claude.mkdir(parents=True)
    proto = claude / "auditor-protocol.md"
    selftest = claude / "handover-selftest.md"
    proto.write_text(
        "### 6.1 每份提示詞的必備要素\n"
        "1. 宣告\n"
        "8. **有包含「更新交接區」、「更新 `docs/TASKBOARD.md`」與「更新 `docs/AUDIT-LOG.md`」三項？**\n"
        "### 6.2 其他\n",
        encoding="utf-8"
    )
    selftest.write_text(
        "## E. 交付\n"
        "- [ ] E1 宣告（§6.1-1）\n"
        "- [ ] E8 **包含更新交接區、docs/TASKBOARD.md與docs/AUDIT-LOG.md**（§6.1-8）\n"
        "## F. 結尾\n",
        encoding="utf-8"
    )
    fails, infos = check_11_selftest_correspondence(str(tmp_path))
    assert len(fails) == 0


def test_check_11_selftest_correspondence_fail_missing_item(tmp_path):
    claude = tmp_path / ".claude" / "rules"
    claude.mkdir(parents=True)
    proto = claude / "auditor-protocol.md"
    selftest = claude / "handover-selftest.md"
    proto.write_text(
        "### 6.1 每份提示詞的必備要素\n"
        "1. 宣告\n"
        "2. 行數比對\n"
        "### 6.2 其他\n",
        encoding="utf-8"
    )
    selftest.write_text(
        "## E. 交付\n"
        "- [ ] E1 宣告（§6.1-1）\n"
        "## F. 結尾\n",
        encoding="utf-8"
    )
    fails, infos = check_11_selftest_correspondence(str(tmp_path))
    assert len(fails) == 1
    assert "§6.1 第 2 項在 handover-selftest.md E 節中無對應項目" in fails[0]


def test_check_11_selftest_correspondence_fail_audit_log_missing(tmp_path):
    # Reproduces the 6th occurrence of the defect
    claude = tmp_path / ".claude" / "rules"
    claude.mkdir(parents=True)
    proto = claude / "auditor-protocol.md"
    selftest = claude / "handover-selftest.md"
    proto.write_text(
        "### 6.1 每份提示詞的必備要素\n"
        "8. **有包含「更新交接區」、「更新 `docs/TASKBOARD.md`」與「更新 `docs/AUDIT-LOG.md`」三項？**\n"
        "### 6.2 其他\n",
        encoding="utf-8"
    )
    selftest.write_text(
        "## E. 交付\n"
        "- [ ] E8 **有包含「更新交接區」與「更新 `docs/TASKBOARD.md`」兩項？**（§6.1-8）\n"
        "## F. 結尾\n",
        encoding="utf-8"
    )
    fails, infos = check_11_selftest_correspondence(str(tmp_path))
    assert len(fails) == 1
    assert "E8 缺少 AUDIT-LOG 更新項目" in fails[0]


def test_check_12_audit_log_cadence_pass(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    al = docs / "AUDIT-LOG.md"
    al.write_text("| 08e6bbc | 2026-09-02 | §4.1-1 | 通過 | 備註 |\n", encoding="utf-8")
    fails, infos = check_12_audit_log_cadence(str(tmp_path), git_count=2)
    assert len(fails) == 0


def test_check_12_audit_log_cadence_fail(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    al = docs / "AUDIT-LOG.md"
    al.write_text("| 08e6bbc | 2026-09-02 | §4.1-1 | 通過 | 備註 |\n", encoding="utf-8")
    fails, infos = check_12_audit_log_cadence(str(tmp_path), git_count=5)
    assert len(fails) == 1
    assert "落後 HEAD 超過三批" in fails[0]


def test_check_12_audit_log_cadence_bootstrap(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    al = docs / "AUDIT-LOG.md"
    al.write_text("| BOOTSTRAP | 2026-08-25 | 初始 | 啟動 |\n", encoding="utf-8")
    fails, infos = check_12_audit_log_cadence(str(tmp_path), git_count=10)
    assert len(fails) == 0
    assert any("BOOTSTRAP" in i for i in infos)


def test_check_13_trailing_newline_pass(tmp_path):
    f = tmp_path / "test.md"
    f.write_bytes(b"# Test\n")
    fails, infos = check_13_trailing_newline(str(tmp_path), strict=True)
    assert len(fails) == 0


def test_check_13_trailing_newline_fail_strict(tmp_path):
    f = tmp_path / "test.md"
    f.write_bytes(b"# Test")
    fails, infos = check_13_trailing_newline(str(tmp_path), strict=True)
    assert len(fails) == 1
    assert "檔尾缺少換行符" in fails[0]


def test_check_13_trailing_newline_info_loose(tmp_path):
    f = tmp_path / "test.md"
    f.write_bytes(b"# Test")
    fails, infos = check_13_trailing_newline(str(tmp_path), strict=False)
    assert len(fails) == 0
    assert len(infos) == 1


def test_check_14_simplified_chinese_pass(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("這是繁體中文測試內容。\n", encoding="utf-8")
    fails, infos = check_14_simplified_chinese(str(tmp_path))
    assert len(fails) == 0


def test_check_14_simplified_chinese_fail(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("这是簡體字測試。\n", encoding="utf-8")
    fails, infos = check_14_simplified_chinese(str(tmp_path))
    assert len(fails) == 1
    assert "包含簡體字" in fails[0]


def test_check_14_simplified_chinese_allowed_exception(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    f = docs / "refactor-backlog.md"
    f.write_text("历史紀錄中的这个测试。\n", encoding="utf-8")
    fails, infos = check_14_simplified_chinese(str(tmp_path))
    assert len(fails) == 0
    assert len(infos) == 1
    assert "歷史紀錄引用例外" in infos[0]


def test_check_15_context_conflict_pass(tmp_path):
    claude = tmp_path / ".claude" / "rules"
    claude.mkdir(parents=True)
    f = claude / "auditor-protocol.md"
    f.write_text("# 規範\n\n正常指引。\n\n- 清單項目：請勿任意更動\n", encoding="utf-8")
    fails, infos = check_15_context_conflict(str(tmp_path))
    assert len(fails) == 0


def test_check_15_context_conflict_fail_deleted_section(tmp_path):
    claude = tmp_path / ".claude" / "rules"
    claude.mkdir(parents=True)
    f = claude / "auditor-protocol.md"
    f.write_text("# 規範\n\n新 Agent 依交接區 §5.2 的清單接手執行。\n", encoding="utf-8")
    fails, infos = check_15_context_conflict(str(tmp_path))
    assert len(fails) == 1
    assert "引用了已刪除的章節或清單" in fails[0]


def test_check_15_context_conflict_fail_neg_prefix(tmp_path):
    agents = tmp_path / ".agents" / "rules"
    agents.mkdir(parents=True)
    f = agents / "test-rule.md"
    f.write_text("# 規範\n\n不要做任何未經指示的操作。\n", encoding="utf-8")
    fails, infos = check_15_context_conflict(str(tmp_path))
    assert len(fails) == 1
    assert "非清單項目的正文開頭出現未包裹的否定字眼" in fails[0]
