import os
import sys
import pytest

# Ensure scripts dir is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from check_consistency import (
    check_3_markdown_links,
    check_8_taskboard_head,
    check_8_taskboard_metadata_purity,
    check_9_handover_head,
    check_10_section_refs,
    check_11_selftest_correspondence,
    check_12_audit_log_cadence,
    check_13_trailing_newline,
    check_14_simplified_chinese,
    check_15_context_conflict,
    check_16_exec_log_cadence,
    check_19_utf8_bom,
    check_20_markdown_table_continuity,
    check_21_secret_leak_guard,
    check_22_ci_supply_chain,
)


def _setup_check_9_env(tmp_path, checkpoint_hash, audit_rows, bl_extra=""):
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    bl = docs / "refactor-backlog.md"
    bl.write_text(
        f"### 5.1 上一批狀態\n\n上次核對通過的 HEAD：{checkpoint_hash}\n{bl_extra}\n### 5.2 待辦\n",
        encoding="utf-8",
    )

    al_lines = [
        "# 自我審查檢查點紀錄\n",
        "| 批次 commit | 日期 | 觸發條款 | 結論摘要 | 失效檢討 |",
        "|---|---|---|---|---|",
        "| BOOTSTRAP | 2026-09-02 | §4.1-1 | 初始紀錄 | — |",
    ]
    for c_hash, summary in audit_rows:
        al_lines.append(f"| {c_hash} | 2026-09-12 | §4.1-1 | {summary} | — |")
    al_lines.append("\n## CI 歷史事故歸檔專區\n")
    al = docs / "AUDIT-LOG.md"
    al.write_text("\n".join(al_lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# CHECK 8 Tests: TASKBOARD Metadata Purity
# ---------------------------------------------------------------------------

def _make_taskboard_content(
    last_updated="**最後更新**：2026-09-13，Router / Anti-Loop / State Placement Hardening",
    next_work="**NEXT_WORK**：G-90",
    active_macro_auditor="**ACTIVE_MACRO_AUDITOR**：GPT 代理審查官（使用者授權）",
    tasks=None,
):
    if tasks is None:
        tasks = [
            ("G-90", "待辦", "Synthetic active task"),
            ("G-91", "已完成", "Synthetic completed task"),
            ("G-92", "可封存", "Synthetic archivable task"),
        ]
    rows = ["# 看板", last_updated]
    if active_macro_auditor is not None:
        rows.append(active_macro_auditor)
    if next_work is not None:
        rows.append(next_work)
    rows.append("")
    rows.append("| ID | 狀態 | 項目 | 備註 |")
    rows.append("|---|---|---|---|")
    for tid, st, desc in tasks:
        rows.append(f"| {tid} | {st} | {desc} | — |")
    rows.append("")
    return "\n".join(rows)


def test_check_8_taskboard_metadata_purity_pass(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    tb.write_text(_make_taskboard_content(), encoding="utf-8")
    fails, infos = check_8_taskboard_head(str(tmp_path))
    assert len(fails) == 0
    assert any("NEXT_WORK = G-90" in i for i in infos)


def test_check_8_pass_active_status_in_progress(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    tasks = [
        ("G-90", "進行中", "Synthetic active task in progress"),
        ("G-91", "已完成", "Synthetic completed task"),
    ]
    tb.write_text(_make_taskboard_content(tasks=tasks), encoding="utf-8")
    fails, infos = check_8_taskboard_head(str(tmp_path))
    assert len(fails) == 0
    assert any("NEXT_WORK = G-90 (狀態: 進行中)" in i for i in infos)


def test_check_8_pass_active_status_pending_decision(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    tasks = [
        ("G-90", "待裁決", "Synthetic active task pending decision"),
        ("G-91", "已完成", "Synthetic completed task"),
    ]
    tb.write_text(_make_taskboard_content(tasks=tasks), encoding="utf-8")
    fails, infos = check_8_taskboard_head(str(tmp_path))
    assert len(fails) == 0
    assert any("NEXT_WORK = G-90 (狀態: 待裁決)" in i for i in infos)


def test_check_8_fail_illegal_task_namespace_even_with_matching_row(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    tasks = [
        ("X-01", "待辦", "Synthetic task with non-A-G namespace"),
    ]
    tb.write_text(
        _make_taskboard_content(next_work="**NEXT_WORK**：X-01", tasks=tasks),
        encoding="utf-8",
    )
    fails, infos = check_8_taskboard_head(str(tmp_path))
    assert len(fails) >= 1
    assert any("只能為合法 task ID" in f for f in fails)


def test_check_8_fail_unknown_status(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    tasks = [
        ("G-90", "未知狀態", "Synthetic task with invalid status"),
    ]
    tb.write_text(
        _make_taskboard_content(next_work="**NEXT_WORK**：G-90", tasks=tasks),
        encoding="utf-8",
    )
    fails, infos = check_8_taskboard_head(str(tmp_path))
    assert len(fails) >= 1
    assert any("目標任務狀態不合法" in f for f in fails)


def test_check_8_taskboard_metadata_purity_fail_sha_duplication(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    tb.write_text(
        _make_taskboard_content(last_updated="**最後更新**：2026-09-12，HEAD `08e6bbc` 之後"),
        encoding="utf-8",
    )
    fails, infos = check_8_taskboard_head(str(tmp_path))
    assert len(fails) >= 1
    assert any("HEAD 關鍵字" in f or "commit hash" in f for f in fails)


def test_check_8_taskboard_metadata_purity_fail_commit_checkpoint_range(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    tb.write_text(
        _make_taskboard_content(last_updated="**最後更新**：2026-09-12，checkpoint 34babd5..HEAD"),
        encoding="utf-8",
    )
    fails, infos = check_8_taskboard_head(str(tmp_path))
    assert len(fails) >= 1


def test_check_8_taskboard_metadata_purity_fail_missing_date(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    tb.write_text(
        _make_taskboard_content(last_updated="**最後更新**：B-58 Recovery R1 進行中"),
        encoding="utf-8",
    )
    fails, infos = check_8_taskboard_head(str(tmp_path))
    assert len(fails) == 1
    assert "缺少有效日期" in fails[0]


def test_check_8_taskboard_metadata_purity_fail_missing_desc(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    tb.write_text(
        _make_taskboard_content(last_updated="**最後更新**：2026-09-12"),
        encoding="utf-8",
    )
    fails, infos = check_8_taskboard_head(str(tmp_path))
    assert len(fails) == 1
    assert "缺少工作階段或當前狀態描述" in fails[0]


def test_check_8_fail_missing_next_work_marker(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    tb.write_text(
        _make_taskboard_content(next_work=None),
        encoding="utf-8",
    )
    fails, infos = check_8_taskboard_head(str(tmp_path))
    assert len(fails) >= 1
    assert any("未找到『NEXT_WORK』標記" in f for f in fails)


def test_check_8_fail_duplicate_next_work_marker(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    content = _make_taskboard_content(next_work="**NEXT_WORK**：G-90\n**NEXT_WORK**：G-91")
    tb.write_text(content, encoding="utf-8")
    fails, infos = check_8_taskboard_head(str(tmp_path))
    assert len(fails) >= 1
    assert any("找到多個『NEXT_WORK』標記" in f for f in fails)


def test_check_8_pass_narrative_text_mentioning_next_work(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    content = (
        "# 看板\n"
        "**最後更新**：2026-09-13，Router / Anti-Loop / State Placement Hardening\n"
        "**ACTIVE_MACRO_AUDITOR**：GPT 代理審查官（使用者授權）\n"
        "**NEXT_WORK**：G-90\n\n"
        "> 請讀 `**NEXT_WORK**` pointer\n"
        "文件說明 **NEXT_WORK**：由 TASKBOARD 管理\n\n"
        "| ID | 狀態 | 項目 | 備註 |\n"
        "|---|---|---|---|\n"
        "| G-90 | 待辦 | Synthetic active task | 說明文字包含 **NEXT_WORK**：G-90 |\n"
    )
    tb.write_text(content, encoding="utf-8")
    fails, infos = check_8_taskboard_head(str(tmp_path))
    assert len(fails) == 0
    assert any("NEXT_WORK = G-90" in i for i in infos)


def test_check_8_fail_nonexistent_task_id(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    tb.write_text(
        _make_taskboard_content(next_work="**NEXT_WORK**：G-99"),
        encoding="utf-8",
    )
    fails, infos = check_8_taskboard_head(str(tmp_path))
    assert len(fails) >= 1
    assert any("指向不存在的任務 ID" in f for f in fails)


def test_check_8_fail_points_to_completed(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    tb.write_text(
        _make_taskboard_content(next_work="**NEXT_WORK**：G-91"),
        encoding="utf-8",
    )
    fails, infos = check_8_taskboard_head(str(tmp_path))
    assert len(fails) >= 1
    assert any("目標任務狀態不合法" in f for f in fails)


def test_check_8_fail_points_to_archivable(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    tb.write_text(
        _make_taskboard_content(next_work="**NEXT_WORK**：G-92"),
        encoding="utf-8",
    )
    fails, infos = check_8_taskboard_head(str(tmp_path))
    assert len(fails) >= 1
    assert any("目標任務狀態不合法" in f for f in fails)


def test_check_8_fail_none_with_active_work(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    tb.write_text(
        _make_taskboard_content(next_work="**NEXT_WORK**：NONE"),
        encoding="utf-8",
    )
    fails, infos = check_8_taskboard_head(str(tmp_path))
    assert len(fails) >= 1
    assert any("NEXT_WORK 為 NONE 但任務看板仍存在 active work" in f for f in fails)


def test_check_8_none_without_active_work_pass(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    tasks_all_done = [
        ("G-91", "已完成", "All done"),
        ("G-92", "可封存", "All archivable"),
    ]
    tb.write_text(
        _make_taskboard_content(next_work="**NEXT_WORK**：NONE", tasks=tasks_all_done),
        encoding="utf-8",
    )
    fails, infos = check_8_taskboard_head(str(tmp_path))
    assert len(fails) == 0
    assert any("NEXT_WORK = NONE" in i for i in infos)


def test_check_8_fail_pointer_contains_git_truth(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    tb.write_text(
        _make_taskboard_content(next_work="**NEXT_WORK**：HEAD `1234567`"),
        encoding="utf-8",
    )
    fails, infos = check_8_taskboard_head(str(tmp_path))
    assert len(fails) >= 1
    assert any("HEAD" in f or "commit" in f for f in fails)


def test_check_8_active_macro_auditor_pass(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    tb.write_text(
        _make_taskboard_content(active_macro_auditor="**ACTIVE_MACRO_AUDITOR**：GPT 代理審查官（使用者授權）"),
        encoding="utf-8",
    )
    fails, infos = check_8_taskboard_head(str(tmp_path))
    assert len(fails) == 0
    assert any("ACTIVE_MACRO_AUDITOR = GPT 代理審查官（使用者授權）" in i for i in infos)


def test_check_8_fail_missing_active_macro_auditor(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    tb.write_text(
        _make_taskboard_content(active_macro_auditor=None),
        encoding="utf-8",
    )
    fails, infos = check_8_taskboard_head(str(tmp_path))
    assert len(fails) >= 1
    assert any("未找到『ACTIVE_MACRO_AUDITOR』標記" in f for f in fails)


def test_check_8_fail_duplicate_active_macro_auditor(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    dup = "**ACTIVE_MACRO_AUDITOR**：Reviewer A\n**ACTIVE_MACRO_AUDITOR**：Reviewer B"
    tb.write_text(
        _make_taskboard_content(active_macro_auditor=dup),
        encoding="utf-8",
    )
    fails, infos = check_8_taskboard_head(str(tmp_path))
    assert len(fails) >= 1
    assert any("找到多個『ACTIVE_MACRO_AUDITOR』標記" in f for f in fails)


def test_check_8_fail_empty_active_macro_auditor(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    tb.write_text(
        _make_taskboard_content(active_macro_auditor="**ACTIVE_MACRO_AUDITOR**："),
        encoding="utf-8",
    )
    fails, infos = check_8_taskboard_head(str(tmp_path))
    assert len(fails) >= 1
    assert any("『ACTIVE_MACRO_AUDITOR』標記值不得為空" in f for f in fails)


@pytest.mark.parametrize("bad_value,expected_err", [
    ("**ACTIVE_MACRO_AUDITOR**：HEAD Reviewer", "不得包含 HEAD 關鍵字"),
    ("**ACTIVE_MACRO_AUDITOR**：checkpoint reviewer", "不得包含 checkpoint/commit 關鍵字"),
    ("**ACTIVE_MACRO_AUDITOR**：commit reviewer", "不得包含 checkpoint/commit 關鍵字"),
    ("**ACTIVE_MACRO_AUDITOR**：Reviewer range 1234..5678", "不得包含 commit range (..)"),
    ("**ACTIVE_MACRO_AUDITOR**：Reviewer Run #12345", "不得包含 CI run ID"),
    ("**ACTIVE_MACRO_AUDITOR**：Reviewer `e8fdb7479311b44c2c25022aab3fdf068a7b3d4f`", "不得保存 Git commit hash"),
])
def test_check_8_fail_active_macro_auditor_git_truth_contamination(tmp_path, bad_value, expected_err):
    docs = tmp_path / "docs"
    docs.mkdir()
    tb = docs / "TASKBOARD.md"
    tb.write_text(
        _make_taskboard_content(active_macro_auditor=bad_value),
        encoding="utf-8",
    )
    fails, infos = check_8_taskboard_head(str(tmp_path))
    assert len(fails) >= 1
    assert any(expected_err in f for f in fails)


# ---------------------------------------------------------------------------
# CHECK 9 Tests: Semantic Authority & Pending Range Generalization
# ---------------------------------------------------------------------------

def test_check_9_shape_a_head_equals_checkpoint_pass(tmp_path):
    _setup_check_9_env(
        tmp_path,
        checkpoint_hash="a111111",
        audit_rows=[("a111111", "**核對通過**。Macro PASS")],
    )
    ancestry = ["a111111", "a000000"]
    fails, infos = check_9_handover_head(str(tmp_path), git_ancestry=ancestry)
    assert len(fails) == 0


def test_check_9_shape_b_one_pending_commit_pass(tmp_path):
    _setup_check_9_env(
        tmp_path,
        checkpoint_hash="a111111",
        audit_rows=[("a111111", "**核對通過**。Macro PASS")],
    )
    ancestry = ["b222222", "a111111", "a000000"]
    fails, infos = check_9_handover_head(str(tmp_path), git_ancestry=ancestry)
    assert len(fails) == 0
    assert any("pending commits in range: 1" in info for info in infos)


def test_check_9_shape_c_multi_pending_commits_pass(tmp_path):
    # Proves no fixed N threshold assumption (testing 6 pending commits)
    _setup_check_9_env(
        tmp_path,
        checkpoint_hash="a111111",
        audit_rows=[("a111111", "**核對通過**。Macro PASS")],
    )
    ancestry = [
        "p000006", "p000005", "p000004", "p000003", "p000002", "p000001",
        "a111111", "a000000"
    ]
    fails, infos = check_9_handover_head(str(tmp_path), git_ancestry=ancestry)
    assert len(fails) == 0
    assert any("pending commits in range: 6" in info for info in infos)


def test_check_9_shape_d_checkpoint_row_not_pass_fail(tmp_path):
    _setup_check_9_env(
        tmp_path,
        checkpoint_hash="d111111",
        audit_rows=[
            ("a111111", "**核對通過**。Macro PASS"),
            ("d111111", "**Machine PASS / 語意審計待微修（NEEDS MICRO-FIX）**"),
        ],
    )
    ancestry = ["d111111", "a111111", "a000000"]
    fails, infos = check_9_handover_head(str(tmp_path), git_ancestry=ancestry)
    assert len(fails) >= 1
    assert any("結論非 Macro PASS" in f for f in fails)


def test_check_9_shape_e_stale_checkpoint_when_newer_pass_exists_fail(tmp_path):
    _setup_check_9_env(
        tmp_path,
        checkpoint_hash="a111111",
        audit_rows=[
            ("a111111", "**核對通過**。Macro PASS"),
            ("e222222", "**核對通過**。Macro PASS"),
        ],
    )
    ancestry = ["p000001", "e222222", "a111111", "a000000"]
    fails, infos = check_9_handover_head(str(tmp_path), git_ancestry=ancestry)
    assert len(fails) >= 1
    assert any("已過期" in f and "e222222" in f for f in fails)


def test_check_9_shape_f_checkpoint_not_ancestor_fail(tmp_path):
    _setup_check_9_env(
        tmp_path,
        checkpoint_hash="f999999",
        audit_rows=[("f999999", "**核對通過**。Macro PASS")],
    )
    ancestry = ["p000002", "p000001", "a111111", "a000000"]
    fails, infos = check_9_handover_head(str(tmp_path), git_ancestry=ancestry)
    assert len(fails) >= 1
    assert any("不存在於當前 Git 歷史或非 HEAD 的祖先 commit" in f for f in fails)


def test_check_9_shape_g_candidate_self_without_pass_fail(tmp_path):
    _setup_check_9_env(
        tmp_path,
        checkpoint_hash="c777777",
        audit_rows=[("a111111", "**核對通過**。Macro PASS")],
    )
    ancestry = ["c777777", "a111111", "a000000"]
    fails, infos = check_9_handover_head(str(tmp_path), git_ancestry=ancestry)
    assert len(fails) >= 1
    assert any("未找到審查紀錄" in f or "未經 Macro PASS 裁決" in f for f in fails)


def test_check_9_as_if_committed_mode_pass(tmp_path):
    _setup_check_9_env(
        tmp_path,
        checkpoint_hash="a111111",
        audit_rows=[("a111111", "**核對通過**。Macro PASS")],
    )
    fails, infos = check_9_handover_head(
        str(tmp_path),
        git_head="candidate",
        git_prev="a111111",
        git_prev2="a000000",
        as_if_committed=True,
    )
    assert len(fails) == 0


def test_check_9_as_if_committed_candidate_self_fail(tmp_path):
    _setup_check_9_env(
        tmp_path,
        checkpoint_hash="candidate",
        audit_rows=[("a111111", "**核對通過**。Macro PASS")],
    )
    fails, infos = check_9_handover_head(
        str(tmp_path),
        git_head="candidate",
        git_prev="a111111",
        as_if_committed=True,
    )
    assert len(fails) >= 1
    assert any("不得為 candidate 自己" in f for f in fails)


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
    selftest = claude / "auditor-selftest.md"
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
    selftest = claude / "auditor-selftest.md"
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
    assert "§6.1 第 2 項在 auditor-selftest.md E 節中無對應項目" in fails[0]


def test_check_11_selftest_correspondence_fail_audit_log_missing(tmp_path):
    # Reproduces the 6th occurrence of the defect
    claude = tmp_path / ".claude" / "rules"
    claude.mkdir(parents=True)
    proto = claude / "auditor-protocol.md"
    selftest = claude / "auditor-selftest.md"
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


def test_check_12_audit_log_bootstrap_pass(tmp_path):
    # A. BOOTSTRAP only -> PASS
    docs = tmp_path / "docs"
    docs.mkdir()
    al = docs / "AUDIT-LOG.md"
    al.write_text("| BOOTSTRAP | 2026-08-25 | 初始 | 啟動 |\n", encoding="utf-8")
    fails, infos = check_12_audit_log_cadence(str(tmp_path), git_ancestry=["c1", "c0"])
    assert len(fails) == 0
    assert any("BOOTSTRAP" in i for i in infos)


def test_check_12_audit_log_distance_1_pass(tmp_path):
    # B. latest audit commit = HEAD ancestor, pending distance = 1 -> PASS
    docs = tmp_path / "docs"
    docs.mkdir()
    al = docs / "AUDIT-LOG.md"
    al.write_text("| 08e6bbc | 2026-09-02 | §4.1-1 | 通過 | 備註 |\n", encoding="utf-8")
    fails, infos = check_12_audit_log_cadence(str(tmp_path), git_ancestry=["head123", "08e6bbc", "root000"])
    assert len(fails) == 0
    assert any("AUDIT-LOG latest reviewed commit: 08e6bbc" in i for i in infos)
    assert any("pending commits since latest review: 1" in i for i in infos)


def test_check_12_audit_log_multi_pending_pass(tmp_path):
    # C. latest audit commit = HEAD ancestor, pending distance > 1 (e.g. 4 pending commits) -> PASS
    docs = tmp_path / "docs"
    docs.mkdir()
    al = docs / "AUDIT-LOG.md"
    al.write_text("| 08e6bbc | 2026-09-02 | §4.1-1 | 通過 | 備註 |\n", encoding="utf-8")
    # Synthetic ancestry representing 4 pending repair commits in M3 cycles
    ancestry = ["c4_repair", "c3_repair", "c2_repair", "c1_impl", "08e6bbc", "root000"]
    fails, infos = check_12_audit_log_cadence(str(tmp_path), git_ancestry=ancestry)
    assert len(fails) == 0
    assert any("pending commits since latest review: 4" in i for i in infos)


def test_check_12_audit_log_ghost_history_fail(tmp_path):
    # D. latest AUDIT-LOG hash not in HEAD ancestry -> FAIL
    docs = tmp_path / "docs"
    docs.mkdir()
    al = docs / "AUDIT-LOG.md"
    al.write_text("| 08e6bbc | 2026-09-02 | §4.1-1 | 通過 | 備註 |\n", encoding="utf-8")
    fails, infos = check_12_audit_log_cadence(str(tmp_path), git_ancestry=["c3_other", "c2_other", "c1_other"])
    assert len(fails) == 1
    assert "不存在於目前 Git HEAD 歷史" in fails[0]


def test_check_12_audit_log_missing_file_fail(tmp_path):
    # E. AUDIT-LOG 缺失 -> FAIL
    fails, infos = check_12_audit_log_cadence(str(tmp_path))
    assert len(fails) == 1
    assert "檔案不存在" in fails[0]


def test_check_12_audit_log_no_valid_row_fail(tmp_path):
    # F. AUDIT-LOG 無合法 row -> FAIL
    docs = tmp_path / "docs"
    docs.mkdir()
    al = docs / "AUDIT-LOG.md"
    al.write_text("# 僅有標題\n無任何表格列\n", encoding="utf-8")
    fails, infos = check_12_audit_log_cadence(str(tmp_path))
    assert len(fails) == 1
    assert "未找到自我審查檢查點紀錄列" in fails[0]


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
    f.write_text("簡體字歷史說明：引用原字形「这个」測試。\n", encoding="utf-8")
    fails, infos = check_14_simplified_chinese(str(tmp_path))
    assert len(fails) == 0
    assert len(infos) == 1
    assert "歷史紀錄引用例外" in infos[0]


def test_check_14_simplified_chinese_in_backlog_plain_text_fail(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    f = docs / "refactor-backlog.md"
    f.write_text("一般正文出現这个未標註說明的文字。\n", encoding="utf-8")
    fails, infos = check_14_simplified_chinese(str(tmp_path))
    assert len(fails) == 1
    assert "包含簡體字" in fails[0]
    assert "个" in fails[0] and "这" in fails[0]


def test_check_15_context_conflict_pass(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    bl = docs / "refactor-backlog.md"
    bl.write_text(
        "### 5.1 上一批狀態\n\n"
        "- `0213568`（治理機械化：擴充至 15 項、63 個測試）\n"
        "  已於 2026-09-04 由審計官核對通過：7 檔異動、零夾帶。\n"
        "- `a1b2c3d`（下一批）已執行，\n"
        "  **尚待審計官核對**，見 §5.4。\n\n"
        "### 5.2 待辦\n",
        encoding="utf-8",
    )
    fails, infos = check_15_context_conflict(str(tmp_path))
    assert len(fails) == 0
    assert any("無交集" in i for i in infos)


def test_check_15_context_conflict_fail(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    bl = docs / "refactor-backlog.md"
    bl.write_text(
        "### 5.1 上一批狀態\n\n"
        "- `0213568`（治理機械化：擴充至 15 項、63 個測試）\n"
        "  已於 2026-09-04 由審計官核對通過：7 檔異動、零夾帶。\n"
        "- `0213568`（同一批）已執行，\n"
        "  **尚待審計官核對**，見 §5.4。\n\n"
        "### 5.2 待辦\n",
        encoding="utf-8",
    )
    fails, infos = check_15_context_conflict(str(tmp_path))
    assert len(fails) == 1
    assert "同時被描述為「已核對通過」與「尚待核對」" in fails[0]


def test_check_15_context_conflict_boundary_no_section(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    bl = docs / "refactor-backlog.md"
    bl.write_text("# 標題\n\n無交接區內容\n", encoding="utf-8")
    fails, infos = check_15_context_conflict(str(tmp_path))
    assert len(fails) == 0
    assert any("找不到交接區 §5.1 區段" in i for i in infos)
def test_check_16_exec_log_cadence_pass(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    el = docs / "EXEC-LOG.md"
    el.write_text("| 08e6bbc | 2026-09-02 | §3 | 通過 | 無 |\n", encoding="utf-8")
    fails, infos = check_16_exec_log_cadence(str(tmp_path), git_count=1)
    assert len(fails) == 0


def test_check_16_exec_log_cadence_ancestor_pass(tmp_path):
    """ancestor + permitted lag -> PASS"""
    docs = tmp_path / "docs"
    docs.mkdir()
    el = docs / "EXEC-LOG.md"
    el.write_text("| 13247f8cf2b01fa9bef0d15c67dde0d91211e752 | 2026-09-19 | §3 | 通過 | 無 |\n", encoding="utf-8")
    fails, infos = check_16_exec_log_cadence(str(tmp_path), git_count=1, git_is_ancestor=True)
    assert len(fails) == 0
    assert any("lag=1" in i for i in infos)


def test_check_16_exec_log_cadence_non_ancestor_fail(tmp_path):
    """non-ancestor -> FAIL closed with merge-base failure"""
    docs = tmp_path / "docs"
    docs.mkdir()
    el = docs / "EXEC-LOG.md"
    el.write_text("| 13247f8cf2b01fa9bef0d15c67dde0d91211e752 | 2026-09-19 | §3 | 通過 | 無 |\n", encoding="utf-8")
    fails, infos = check_16_exec_log_cadence(str(tmp_path), git_count=1, git_is_ancestor=False)
    assert len(fails) >= 1
    assert "git merge-base --is-ancestor 失敗" in fails[0]


def test_check_16_exec_log_cadence_fail(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    el = docs / "EXEC-LOG.md"
    el.write_text("| 08e6bbc | 2026-09-02 | §3 | 通過 | 無 |\n", encoding="utf-8")
    fails, infos = check_16_exec_log_cadence(str(tmp_path), git_count=2)
    assert len(fails) == 1
    assert "落後 HEAD 2 個 commit" in fails[0]


def test_check_16_exec_log_cadence_malformed_hash_fail_closed(tmp_path):
    """malformed/missing hash -> fail closed"""
    docs = tmp_path / "docs"
    docs.mkdir()
    el = docs / "EXEC-LOG.md"
    # Malformed non-hex string
    el.write_text("| NOT_A_VALID_HASH | 2026-09-19 | §3 | 通過 | 無 |\n", encoding="utf-8")
    fails, infos = check_16_exec_log_cadence(str(tmp_path), git_count=1, git_is_ancestor=True)
    assert len(fails) >= 1
    assert "格式不合法或缺失" in fails[0]

    # Too short hash
    el.write_text("| 12345 | 2026-09-19 | §3 | 通過 | 無 |\n", encoding="utf-8")
    fails, infos = check_16_exec_log_cadence(str(tmp_path), git_count=1, git_is_ancestor=True)
    assert len(fails) >= 1
    assert "格式不合法或缺失" in fails[0]


def test_check_16_exec_log_cadence_bootstrap(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    el = docs / "EXEC-LOG.md"
    el.write_text("| BOOTSTRAP | 2026-09-05 | 初始 | 啟動 | 無 |\n", encoding="utf-8")
    fails, infos = check_16_exec_log_cadence(str(tmp_path), git_count=10)
    assert len(fails) == 0
    assert any("BOOTSTRAP" in i for i in infos)


def test_check_16_exec_log_cadence_synthetic_base_plus_candidate_child(tmp_path):
    """synthetic: 13247f8 base + one candidate child -> ancestor true / lag 1"""
    import subprocess
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo_dir, check=True, capture_output=True)

    f1 = repo_dir / "init.txt"
    f1.write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "init.txt"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base commit"], cwd=repo_dir, check=True, capture_output=True)
    base_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, check=True).stdout.strip()

    (repo_dir / "docs").mkdir(parents=True)
    el = repo_dir / "docs" / "EXEC-LOG.md"
    el.write_text(f"| {base_sha} | 2026-09-19 | §3 | 通過 | Candidate pending |\n", encoding="utf-8")
    subprocess.run(["git", "add", "docs/EXEC-LOG.md"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "candidate child commit"], cwd=repo_dir, check=True, capture_output=True)

    fails, infos = check_16_exec_log_cadence(str(repo_dir))
    assert len(fails) == 0
    assert any("lag=1" in i for i in infos)


def test_check_16_exec_log_cadence_merge_commits_not_hidden(tmp_path):
    """merge commits are not hidden in rev-list cadence check (no --no-merges)"""
    import subprocess
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo_dir, check=True, capture_output=True)

    f1 = repo_dir / "init.txt"
    f1.write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "init.txt"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base commit"], cwd=repo_dir, check=True, capture_output=True)
    base_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, check=True).stdout.strip()

    default_branch = subprocess.run(["git", "branch", "--show-current"], cwd=repo_dir, capture_output=True, text=True).stdout.strip()
    subprocess.run(["git", "branch", "feat"], cwd=repo_dir, check=True, capture_output=True)

    f2 = repo_dir / "f2.txt"
    f2.write_text("f2\n", encoding="utf-8")
    subprocess.run(["git", "add", "f2.txt"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "main step 2"], cwd=repo_dir, check=True, capture_output=True)

    subprocess.run(["git", "switch", "feat"], cwd=repo_dir, check=True, capture_output=True)
    f3 = repo_dir / "f3.txt"
    f3.write_text("f3\n", encoding="utf-8")
    subprocess.run(["git", "add", "f3.txt"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "feat step"], cwd=repo_dir, check=True, capture_output=True)

    subprocess.run(["git", "switch", default_branch], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "merge", "--no-ff", "feat", "-m", "merge commit"], cwd=repo_dir, check=True, capture_output=True)

    # EXEC-LOG records base_sha
    (repo_dir / "docs").mkdir(parents=True)
    el = repo_dir / "docs" / "EXEC-LOG.md"
    el.write_text(f"| {base_sha} | 2026-09-19 | §3 | 通過 | Old anchor |\n", encoding="utf-8")

    # With merge commit counted, rev-list base_sha..HEAD has >= 3 commits, so lag > 1 -> fails
    fails, infos = check_16_exec_log_cadence(str(repo_dir))
    assert len(fails) >= 1
    assert any("落後 HEAD" in f for f in fails)


def test_preflight_authority_model_contract_validation():
    valid_prompt_metadata = {
        "base_oid": "38b7c49c1ef071eb7fd78fe30fdc2680b335a4c1",
        "batch_mode": "GOAL_SPEC",
        "spec_path": "docs/batches/38b7c49-mechanical-truth-migration.spec.txt",
        "spec_sha256": "abc1234567890",
        "allowed_scope": ["docs/TASKBOARD.md", "docs/AUDIT-LOG.md"],
        "gates": ["validate_skills.py", "check_consistency.py", "fingerprint.py --verify", "pytest"]
    }
    assert bool(valid_prompt_metadata.get("base_oid"))
    assert bool(valid_prompt_metadata.get("spec_sha256"))
    assert bool(valid_prompt_metadata.get("allowed_scope"))
    assert "expected_line_count" not in valid_prompt_metadata
    assert "expected_fence_count" not in valid_prompt_metadata

    invalid_prompt_metadata = valid_prompt_metadata.copy()
    invalid_prompt_metadata.pop("spec_sha256")
    assert not bool(invalid_prompt_metadata.get("spec_sha256"))


# ---------------------------------------------------------------------------
# CHECK 3 Tests: Markdown Links & Path Portability (B-58 R6)
# ---------------------------------------------------------------------------

def test_check_3_markdown_links_pass_relative(tmp_path):
    doc1 = tmp_path / "doc1.md"
    doc2 = tmp_path / "doc2.md"
    doc2.write_text("# Target\n", encoding="utf-8")
    doc1.write_text("[Link to doc2](doc2.md)\n", encoding="utf-8")

    fails, infos = check_3_markdown_links(str(tmp_path))
    assert len(fails) == 0


def test_check_3_markdown_links_fail_file_uri(tmp_path):
    doc = tmp_path / "test.md"
    doc.write_text("[Local](file:///C:/Users/tester/doc.md)\n", encoding="utf-8")

    fails, infos = check_3_markdown_links(str(tmp_path))
    assert len(fails) == 1
    assert "不得使用本機絕對路徑連結" in fails[0]
    assert "file:///" in fails[0]


def test_check_3_markdown_links_fail_windows_drive(tmp_path):
    doc = tmp_path / "test.md"
    doc.write_text("[Local](C:/Users/tester/Desktop/doc.md)\n", encoding="utf-8")

    fails, infos = check_3_markdown_links(str(tmp_path))
    assert len(fails) == 1
    assert "不得使用本機絕對路徑連結" in fails[0]


def test_check_3_markdown_links_fail_unix_user(tmp_path):
    doc = tmp_path / "test.md"
    doc.write_text("[Local](/Users/tester/Desktop/doc.md)\n", encoding="utf-8")

    fails, infos = check_3_markdown_links(str(tmp_path))
    assert len(fails) == 1
    assert "不得使用本機絕對路徑連結" in fails[0]


def test_check_3_markdown_links_pass_exemptions(tmp_path):
    doc = tmp_path / "test.md"
    doc.write_text(
        "[Web](https://github.com/example/repo)\n"
        "[Email](mailto:user@example.com)\n"
        "[Anchor](#section-1)\n"
        "[Template](<YOUR_PROJECT_PATH>/doc.md)\n",
        encoding="utf-8",
    )

    fails, infos = check_3_markdown_links(str(tmp_path))
    assert len(fails) == 0


def test_check_3_markdown_links_fail_missing_target(tmp_path):
    doc = tmp_path / "test.md"
    doc.write_text("[Missing](nonexistent_file.md)\n", encoding="utf-8")

    fails, infos = check_3_markdown_links(str(tmp_path))
    assert len(fails) == 1
    assert "目標不存在" in fails[0]


# ---------------------------------------------------------------------------
# CHECK 14 Extended Tests: Japanese Character False-Green (B-89)
# ---------------------------------------------------------------------------

def test_check_14_japanese_hiragana_fail(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("這是包含平假名「の」的測試。\n", encoding="utf-8")
    fails, infos = check_14_simplified_chinese(str(tmp_path))
    assert len(fails) == 1
    assert "包含日文字元 [の]" in fails[0]


def test_check_14_japanese_katakana_fail(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("這是包含片假名「カ」的測試。\n", encoding="utf-8")
    fails, infos = check_14_simplified_chinese(str(tmp_path))
    assert len(fails) == 1
    assert "包含日文字元 [カ]" in fails[0]


def test_check_14_japanese_halfwidth_katakana_fail(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("這是包含半形片假名「ｶ」的測試。\n", encoding="utf-8")
    fails, infos = check_14_simplified_chinese(str(tmp_path))
    assert len(fails) == 1
    assert "包含日文字元 [ｶ]" in fails[0]


def test_check_14_japanese_shinjitai_fail(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("這是日文新字體「証」的歷史回歸測試。\n", encoding="utf-8")
    fails, infos = check_14_simplified_chinese(str(tmp_path))
    assert len(fails) == 1
    assert "包含日文字元 [証]" in fails[0]


def test_check_14_traditional_chinese_char_pass(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("這是繁體中文「證書」與「變革」與「步驟」，完全合法。\n", encoding="utf-8")
    fails, infos = check_14_simplified_chinese(str(tmp_path))
    assert len(fails) == 0


def test_check_14_japanese_in_backlog_allowed_exception(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    f = docs / "refactor-backlog.md"
    f.write_text("修正日文漢字\n「適用対象」與簡繁誤譯。\n", encoding="utf-8")
    fails, infos = check_14_simplified_chinese(str(tmp_path))
    assert len(fails) == 0
    assert len(infos) == 1
    assert "歷史紀錄引用例外" in infos[0]


# ---------------------------------------------------------------------------
# CHECK 19 Tests: UTF-8 BOM Detection (B-31 Tracked-Scope Authority)
# ---------------------------------------------------------------------------

def _init_test_git_repo(path):
    import subprocess
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(path), capture_output=True, check=True)


def test_check_19_utf8_bom_tracked_clean_text_pass(tmp_path):
    """Canary A: tracked normal text clean -> PASS"""
    import subprocess
    _init_test_git_repo(tmp_path)
    clean_file = tmp_path / "clean.md"
    clean_file.write_text("# Clean UTF-8 without BOM\nHello World\n", encoding="utf-8")
    subprocess.run(["git", "add", "clean.md"], cwd=str(tmp_path), capture_output=True, check=True)

    fails, infos = check_19_utf8_bom(str(tmp_path))
    assert len(fails) == 0
    assert any("掃描 Git tracked 檔案" in inf for inf in infos)


def test_check_19_utf8_bom_tracked_markdown_bom_fail(tmp_path):
    """Canary B: tracked Markdown BOM prefix EF BB BF -> FAIL"""
    import subprocess
    _init_test_git_repo(tmp_path)
    clean_file = tmp_path / "clean.md"
    clean_file.write_text("# Clean\n", encoding="utf-8")
    subprocess.run(["git", "add", "clean.md"], cwd=str(tmp_path), capture_output=True, check=True)

    bom_file = tmp_path / "bom.md"
    bom_file.write_bytes(b"\xef\xbb\xbf# Header with BOM\n")
    subprocess.run(["git", "add", "bom.md"], cwd=str(tmp_path), capture_output=True, check=True)

    fails, infos = check_19_utf8_bom(str(tmp_path))
    assert len(fails) == 1
    assert "bom.md:1" in fails[0]
    assert "檔案開頭包含 UTF-8 BOM (EF BB BF) 污染" in fails[0]


def test_check_19_utf8_bom_tracked_gitattributes_bom_fail(tmp_path):
    """Canary C: tracked extensionless control file .gitattributes with BOM -> FAIL"""
    import subprocess
    _init_test_git_repo(tmp_path)
    ga = tmp_path / ".gitattributes"
    ga.write_bytes(b"\xef\xbb\xbf* text=auto eol=lf\n")
    subprocess.run(["git", "add", ".gitattributes"], cwd=str(tmp_path), capture_output=True, check=True)

    fails, infos = check_19_utf8_bom(str(tmp_path))
    assert len(fails) == 1
    assert ".gitattributes:1" in fails[0]
    assert "檔案開頭包含 UTF-8 BOM (EF BB BF) 污染" in fails[0]


def test_check_19_utf8_bom_tracked_gitattributes_clean_pass(tmp_path):
    """Canary D: tracked .gitattributes clean -> PASS"""
    import subprocess
    _init_test_git_repo(tmp_path)
    ga = tmp_path / ".gitattributes"
    ga.write_bytes(b"* text=auto eol=lf\n")
    subprocess.run(["git", "add", ".gitattributes"], cwd=str(tmp_path), capture_output=True, check=True)

    fails, infos = check_19_utf8_bom(str(tmp_path))
    assert len(fails) == 0


def test_check_19_utf8_bom_untracked_bom_ignored(tmp_path):
    """Canary E: untracked BOM file not git added -> does NOT fail CHECK 19"""
    import subprocess
    _init_test_git_repo(tmp_path)
    clean_file = tmp_path / "clean.md"
    clean_file.write_text("# Clean\n", encoding="utf-8")
    subprocess.run(["git", "add", "clean.md"], cwd=str(tmp_path), capture_output=True, check=True)

    untracked = tmp_path / "untracked.md"
    untracked.write_bytes(b"\xef\xbb\xbf# Untracked BOM\n")

    fails, infos = check_19_utf8_bom(str(tmp_path))
    assert len(fails) == 0


def test_check_19_utf8_bom_gitignored_bom_ignored(tmp_path):
    """Canary F: gitignored BOM file -> does NOT fail CHECK 19"""
    import subprocess
    _init_test_git_repo(tmp_path)
    gi = tmp_path / ".gitignore"
    gi.write_text("generated/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=str(tmp_path), capture_output=True, check=True)

    gen_dir = tmp_path / "generated"
    gen_dir.mkdir()
    noise = gen_dir / "noise.md"
    noise.write_bytes(b"\xef\xbb\xbf# Noise with BOM\n")

    fails, infos = check_19_utf8_bom(str(tmp_path))
    assert len(fails) == 0


def test_check_19_utf8_bom_inventory_failure_fail_closed(tmp_path, monkeypatch):
    """Canary G: tracked read / inventory failure -> FAIL CLOSED"""
    import check_consistency
    # 1. Non-git directory
    fails, infos = check_19_utf8_bom(str(tmp_path))
    assert len(fails) == 1
    assert "不是 git repository" in fails[0]

    # 2. In git repo, but git ls-files command fails
    _init_test_git_repo(tmp_path)
    monkeypatch.setattr(check_consistency, "_git_bytes", lambda root, args: (1, b"", b"Simulated error"))
    fails, infos = check_19_utf8_bom(str(tmp_path))
    assert len(fails) == 1
    assert "無法取得 tracked files 清單" in fails[0]


def test_check_19_utf8_bom_tracked_read_failure_fail_closed(tmp_path):
    """Canary G2: tracked file reading failure -> FAIL CLOSED"""
    import subprocess
    _init_test_git_repo(tmp_path)
    tracked_file = tmp_path / "will_delete.md"
    tracked_file.write_bytes(b"some content\n")
    subprocess.run(["git", "add", "will_delete.md"], cwd=str(tmp_path), capture_output=True, check=True)
    tracked_file.unlink()

    fails, infos = check_19_utf8_bom(str(tmp_path))
    assert len(fails) == 1
    assert "檔案讀取失敗" in fails[0]


# ---------------------------------------------------------------------------
# CHECK 20 Tests: Markdown Table Continuity (B-88)
# ---------------------------------------------------------------------------

def test_check_20_markdown_table_continuity_pass(tmp_path):
    # Two independent tables, each with header + separator, separated by blank line
    doc = tmp_path / "test.md"
    doc.write_text(
        "| Header 1 | Col 2 |\n"
        "|---|---|\n"
        "| Row 1 | Val 1 |\n"
        "\n"
        "| Header 2 | Col B |\n"
        "|---|---|\n"
        "| Row 2 | Val B |\n",
        encoding="utf-8",
    )
    fails, infos = check_20_markdown_table_continuity(str(tmp_path))
    assert len(fails) == 0
    assert any("掃描 Markdown 檔案" in inf for inf in infos)


def test_check_20_markdown_table_continuity_fail_real_shape_accident(tmp_path):
    # Real accident fixture: same table broken by a blank line
    doc = tmp_path / "test.md"
    doc.write_text(
        "| header |\n"
        "|---|\n"
        "| row1 |\n"
        "\n"
        "| row2 |\n",
        encoding="utf-8",
    )
    fails, infos = check_20_markdown_table_continuity(str(tmp_path))
    assert len(fails) == 1
    assert "表格被空白行切斷" in fails[0]
    assert "row2" in fails[0]


def test_check_20_markdown_table_continuity_fenced_code_pass(tmp_path):
    doc = tmp_path / "test.md"
    doc.write_text(
        "```markdown\n"
        "| header |\n"
        "|---|\n"
        "| row1 |\n"
        "\n"
        "| row2 |\n"
        "```\n",
        encoding="utf-8",
    )
    fails, infos = check_20_markdown_table_continuity(str(tmp_path))
    assert len(fails) == 0


def test_check_20_markdown_table_continuity_paragraph_pipe_pass(tmp_path):
    doc = tmp_path / "test.md"
    doc.write_text(
        "This is an ordinary paragraph containing a | pipe character.\n"
        "\n"
        "| Valid Header |\n"
        "|---|\n"
        "| Row 1 |\n",
        encoding="utf-8",
    )
    fails, infos = check_20_markdown_table_continuity(str(tmp_path))
    assert len(fails) == 0


def test_check_20_markdown_table_continuity_archive_ignored(tmp_path):
    archive_dir = tmp_path / "docs" / "archive"
    archive_dir.mkdir(parents=True)
    doc = archive_dir / "legacy.md"
    doc.write_text(
        "| header |\n"
        "|---|\n"
        "| row1 |\n"
        "\n"
        "| row2 |\n",
        encoding="utf-8",
    )
    fails, infos = check_20_markdown_table_continuity(str(tmp_path))
    assert len(fails) == 0


def test_integration_run_checks_includes_19_and_20():
    import check_consistency
    import inspect
    source = inspect.getsource(check_consistency.run_checks)
    assert "check_19_utf8_bom" in source
    assert "check_20_markdown_table_continuity" in source
    assert "CHECK 19 - UTF-8 BOM" in source
    assert "CHECK 20 - Markdown 表格連續性" in source


def test_integration_run_checks_includes_22_and_total_checks_is_22():
    import check_consistency
    import inspect
    source = inspect.getsource(check_consistency.run_checks)
    assert "total_checks = 22" in source
    assert "check_21_secret_leak_guard" in source
    assert "CHECK 21: 機密防護與輸出安全守衛" in source
    assert "check_22_ci_supply_chain" in source
    assert "CHECK 22: CI 供應鏈可重現性守衛" in source


def test_check_21_missing_rule_file_fail(tmp_path):
    fails, infos = check_21_secret_leak_guard(str(tmp_path))
    assert any("secret-output-safety.md" in f and "不存在" in f for f in fails)


def test_check_21_missing_anchor_fail(tmp_path):
    rules_dir = tmp_path / ".agents" / "rules"
    rules_dir.mkdir(parents=True)
    rule_file = rules_dir / "secret-output-safety.md"
    rule_file.write_text("# Title\nSECRET-1\nSECRET-2\n", encoding="utf-8")
    fails, infos = check_21_secret_leak_guard(str(tmp_path))
    assert any("缺少必要錨點" in f and "SECRET-3" in f for f in fails)


def test_check_21_missing_hook_fail(tmp_path):
    rules_dir = tmp_path / ".agents" / "rules"
    rules_dir.mkdir(parents=True)
    rule_file = rules_dir / "secret-output-safety.md"
    rule_file.write_text("\n".join([f"SECRET-{i}" for i in range(1, 9)]), encoding="utf-8")
    fails, infos = check_21_secret_leak_guard(str(tmp_path))
    assert any(".githooks/pre-commit" in f and "不存在" in f for f in fails)


def test_check_21_hook_missing_staged_scanner_fail(tmp_path):
    rules_dir = tmp_path / ".agents" / "rules"
    rules_dir.mkdir(parents=True)
    rule_file = rules_dir / "secret-output-safety.md"
    rule_file.write_text("\n".join([f"SECRET-{i}" for i in range(1, 9)]), encoding="utf-8")

    hook_dir = tmp_path / ".githooks"
    hook_dir.mkdir(parents=True)
    hook_file = hook_dir / "pre-commit"
    hook_file.write_text("#!/bin/sh\necho done\n", encoding="utf-8")

    fails, infos = check_21_secret_leak_guard(str(tmp_path))
    assert any("Hook 未呼叫 scripts/secret_scan.py --staged" in f for f in fails)


def test_check_21_hook_with_no_verify_fail(tmp_path):
    rules_dir = tmp_path / ".agents" / "rules"
    rules_dir.mkdir(parents=True)
    rule_file = rules_dir / "secret-output-safety.md"
    rule_file.write_text("\n".join([f"SECRET-{i}" for i in range(1, 9)]), encoding="utf-8")

    hook_dir = tmp_path / ".githooks"
    hook_dir.mkdir(parents=True)
    hook_file = hook_dir / "pre-commit"
    hook_file.write_text("#!/bin/sh\nscripts/secret_scan.py --staged --no-verify\n", encoding="utf-8")

    fails, infos = check_21_secret_leak_guard(str(tmp_path))
    assert any("--no-verify" in f for f in fails)


def test_check_21_clean_synthetic_repo_pass(tmp_path):
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    rules_dir = tmp_path / ".agents" / "rules"
    rules_dir.mkdir(parents=True)
    rule_file = rules_dir / "secret-output-safety.md"
    rule_file.write_text("\n".join([f"SECRET-{i}" for i in range(1, 9)]), encoding="utf-8")

    hook_dir = tmp_path / ".githooks"
    hook_dir.mkdir(parents=True)
    hook_file = hook_dir / "pre-commit"
    hook_file.write_text("#!/bin/sh\npython scripts/secret_scan.py --staged\n", encoding="utf-8")

    clean_file = tmp_path / "hello.txt"
    clean_file.write_text("Hello world clean file\n", encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)

    fails, infos = check_21_secret_leak_guard(str(tmp_path))
    assert len(fails) == 0
    assert any("8 組錨點完整" in i for i in infos)
    assert any("pre-commit 存在且呼叫" in i for i in infos)
    assert any("零機敏特徵命中" in i for i in infos)


def test_check_21_tracked_secret_fail_and_no_secret_in_output(tmp_path):
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    rules_dir = tmp_path / ".agents" / "rules"
    rules_dir.mkdir(parents=True)
    rule_file = rules_dir / "secret-output-safety.md"
    rule_file.write_text("\n".join([f"SECRET-{i}" for i in range(1, 9)]), encoding="utf-8")

    hook_dir = tmp_path / ".githooks"
    hook_dir.mkdir(parents=True)
    hook_file = hook_dir / "pre-commit"
    hook_file.write_text("#!/bin/sh\npython scripts/secret_scan.py --staged\n", encoding="utf-8")

    prefix = "".join(["g", "h", "p", "_"])
    raw_synthetic_secret = prefix + "9" * 36
    secret_file = tmp_path / "leak.txt"
    secret_file.write_text(f"leaked_token = {raw_synthetic_secret}\n", encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)

    fails, infos = check_21_secret_leak_guard(str(tmp_path))
    assert len(fails) >= 1
    assert any("SECRET_SCAN BLOCK" in f for f in fails)
    assert not any(raw_synthetic_secret in f for f in fails)


# ---------------------------------------------------------------------------
# CHECK 22 — CI 供應鏈可重現性守衛測試 (Canaries 1-9)
# ---------------------------------------------------------------------------

def _setup_check_22_env(tmp_path, workflow_content=None, req_content=None):
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    wf_file = wf_dir / "verify.yml"

    if workflow_content is None:
        workflow_content = (
            "name: Verify\n\n"
            "on:\n"
            "  push:\n"
            "    branches: [ main ]\n\n"
            "permissions:\n"
            "  contents: read\n\n"
            "jobs:\n"
            "  verify:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262\n"
            "      - uses: actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020\n"
            "      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065\n"
        )
    wf_file.write_text(workflow_content, encoding="utf-8")

    req_file = tmp_path / "requirements.txt"
    if req_content is None:
        req_content = (
            "# requirements\n"
            "pytest==9.1.1\n"
            "playwright==1.63.0\n"
            "colorama==0.4.6; sys_platform == 'win32'\n"
        )
    req_file.write_text(req_content, encoding="utf-8")


def test_check_22_canary_1_exact_pass(tmp_path):
    _setup_check_22_env(tmp_path)
    fails, infos = check_22_ci_supply_chain(str(tmp_path))
    assert len(fails) == 0
    assert any("頂層權限驗證通過" in i for i in infos)
    assert any("共驗證 3 項精確鎖定" in i for i in infos)


def test_check_22_canary_2_checkout_v4_fail(tmp_path):
    wf = (
        "name: Verify\n"
        "permissions:\n"
        "  contents: read\n"
        "jobs:\n"
        "  verify:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
    )
    _setup_check_22_env(tmp_path, workflow_content=wf)
    fails, infos = check_22_ci_supply_chain(str(tmp_path))
    assert any("Action 'actions/checkout' 未固定至 40-hex commit SHA" in f for f in fails)


def test_check_22_canary_3_setup_node_v4_fail(tmp_path):
    wf = (
        "name: Verify\n"
        "permissions:\n"
        "  contents: read\n"
        "jobs:\n"
        "  verify:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/setup-node@v4\n"
    )
    _setup_check_22_env(tmp_path, workflow_content=wf)
    fails, infos = check_22_ci_supply_chain(str(tmp_path))
    assert any("Action 'actions/setup-node' 未固定至 40-hex commit SHA" in f for f in fails)


def test_check_22_canary_4_setup_python_v5_fail(tmp_path):
    wf = (
        "name: Verify\n"
        "permissions:\n"
        "  contents: read\n"
        "jobs:\n"
        "  verify:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/setup-python@v5\n"
    )
    _setup_check_22_env(tmp_path, workflow_content=wf)
    fails, infos = check_22_ci_supply_chain(str(tmp_path))
    assert any("Action 'actions/setup-python' 未固定至 40-hex commit SHA" in f for f in fails)


def test_check_22_canary_5_missing_permissions_fail(tmp_path):
    wf = (
        "name: Verify\n"
        "jobs:\n"
        "  verify:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262\n"
    )
    _setup_check_22_env(tmp_path, workflow_content=wf)
    fails, infos = check_22_ci_supply_chain(str(tmp_path))
    assert any("缺少頂層 'permissions: contents: read'" in f for f in fails)


def test_check_22_canary_6_contents_write_fail(tmp_path):
    wf = (
        "name: Verify\n"
        "permissions:\n"
        "  contents: write\n"
        "jobs:\n"
        "  verify:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262\n"
    )
    _setup_check_22_env(tmp_path, workflow_content=wf)
    fails, infos = check_22_ci_supply_chain(str(tmp_path))
    assert any("包含未授權之寫入權限: contents: write" in f for f in fails)


def test_check_22_canary_7_pytest_range_fail(tmp_path):
    req = "pytest>=9.0\nplaywright==1.63.0\n"
    _setup_check_22_env(tmp_path, req_content=req)
    fails, infos = check_22_ci_supply_chain(str(tmp_path))
    assert any("pytest>=9.0" in f for f in fails)


def test_check_22_canary_8_playwright_range_fail(tmp_path):
    req = "pytest==9.1.1\nplaywright>=1.40\n"
    _setup_check_22_env(tmp_path, req_content=req)
    fails, infos = check_22_ci_supply_chain(str(tmp_path))
    assert any("playwright>=1.40" in f for f in fails)


def test_check_22_canary_9_windows_marker_pass(tmp_path):
    req = "colorama==0.4.6; sys_platform == 'win32'\npytest==9.1.1\n"
    _setup_check_22_env(tmp_path, req_content=req)
    fails, infos = check_22_ci_supply_chain(str(tmp_path))
    assert len(fails) == 0
    assert any("共驗證 2 項精確鎖定" in i for i in infos)


# ---------------------------------------------------------------------------
# CHECK 22 Fail-Closed Negative Controls & Pipeline Grammar (Controls B-L)
# ---------------------------------------------------------------------------

def test_check_22_control_b_unsafe_tee_pipeline_fail(tmp_path):
    """Control B: python3 scripts/verify_all.py | tee output.log without pipefail -> FAIL"""
    wf = (
        "name: Verify\n"
        "permissions:\n"
        "  contents: read\n"
        "jobs:\n"
        "  verify:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262\n"
        "      - name: Run verification gates\n"
        "        run: python3 scripts/verify_all.py 2>&1 | tee /tmp/verify.log\n"
    )
    _setup_check_22_env(tmp_path, workflow_content=wf)
    fails, infos = check_22_ci_supply_chain(str(tmp_path))
    assert len(fails) >= 1
    assert any("pipeline" in f.lower() for f in fails)


def test_check_22_control_c_direct_verify_all_pass(tmp_path):
    """Control C: direct run: python3 scripts/verify_all.py -> PASS"""
    wf = (
        "name: Verify\n"
        "permissions:\n"
        "  contents: read\n"
        "jobs:\n"
        "  verify:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262\n"
        "      - name: Run verification gates\n"
        "        run: python3 scripts/verify_all.py\n"
    )
    _setup_check_22_env(tmp_path, workflow_content=wf)
    fails, infos = check_22_ci_supply_chain(str(tmp_path))
    assert len(fails) == 0


def test_check_22_control_d_required_gate_continue_on_error_fail(tmp_path):
    """Control D: required gate continue-on-error true -> FAIL"""
    wf = (
        "name: Verify\n"
        "permissions:\n"
        "  contents: read\n"
        "jobs:\n"
        "  verify:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262\n"
        "      - name: Run verification gates\n"
        "        continue-on-error: true\n"
        "        run: python3 scripts/verify_all.py\n"
    )
    _setup_check_22_env(tmp_path, workflow_content=wf)
    fails, infos = check_22_ci_supply_chain(str(tmp_path))
    assert len(fails) >= 1
    assert any("continue-on-error" in f for f in fails)


def test_check_22_control_e_required_verify_conditional_skip_fail(tmp_path):
    """Control E: required verify job/step conditional skip -> FAIL"""
    wf = (
        "name: Verify\n"
        "permissions:\n"
        "  contents: read\n"
        "jobs:\n"
        "  verify:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262\n"
        "      - name: Run verification gates\n"
        "        if: github.event_name == 'push'\n"
        "        run: python3 scripts/verify_all.py\n"
    )
    _setup_check_22_env(tmp_path, workflow_content=wf)
    fails, infos = check_22_ci_supply_chain(str(tmp_path))
    assert len(fails) >= 1
    assert any("條件式略過" in f or "if:" in f for f in fails)


def test_check_22_control_f_diagnostic_if_failure_pass(tmp_path):
    """Control F: separate diagnostic if: failure() -> PASS"""
    wf = (
        "name: Verify\n"
        "permissions:\n"
        "  contents: read\n"
        "jobs:\n"
        "  verify:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262\n"
        "      - name: Run verification gates\n"
        "        run: python3 scripts/verify_all.py\n"
        "      - name: Diagnostic output\n"
        "        if: failure()\n"
        "        run: echo 'diagnostics'\n"
    )
    _setup_check_22_env(tmp_path, workflow_content=wf)
    fails, infos = check_22_ci_supply_chain(str(tmp_path))
    assert len(fails) == 0


def test_check_22_control_g_run_pipe_block_marker_pass(tmp_path):
    """Control G: run: | with no pipeline -> PASS"""
    wf = (
        "name: Verify\n"
        "permissions:\n"
        "  contents: read\n"
        "jobs:\n"
        "  verify:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262\n"
        "      - name: Run verification gates\n"
        "        run: |\n"
        "          python3 scripts/verify_all.py\n"
        "          echo 'done'\n"
    )
    _setup_check_22_env(tmp_path, workflow_content=wf)
    fails, infos = check_22_ci_supply_chain(str(tmp_path))
    assert len(fails) == 0


def test_check_22_control_h_run_gt_block_marker_pass(tmp_path):
    """Control H: run: > with no pipeline -> PASS"""
    wf = (
        "name: Verify\n"
        "permissions:\n"
        "  contents: read\n"
        "jobs:\n"
        "  verify:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262\n"
        "      - name: Run verification gates\n"
        "        run: >\n"
        "          python3 scripts/verify_all.py\n"
    )
    _setup_check_22_env(tmp_path, workflow_content=wf)
    fails, infos = check_22_ci_supply_chain(str(tmp_path))
    assert len(fails) == 0


def test_check_22_control_i_quoted_pipe_pass(tmp_path):
    """Control I: quoted 'a|b' -> PASS"""
    wf = (
        "name: Verify\n"
        "permissions:\n"
        "  contents: read\n"
        "jobs:\n"
        "  verify:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262\n"
        "      - name: Run verification gates\n"
        "        run: python3 scripts/verify_all.py\n"
        "      - name: Quoted pipe test\n"
        "        run: echo \"option_a|option_b\"\n"
    )
    _setup_check_22_env(tmp_path, workflow_content=wf)
    fails, infos = check_22_ci_supply_chain(str(tmp_path))
    assert len(fails) == 0


def test_check_22_control_j_expression_or_not_pipeline_pass(tmp_path):
    """Control J: ${{ x || y }} -> not treated as shell pipeline"""
    wf = (
        "name: Verify\n"
        "permissions:\n"
        "  contents: read\n"
        "jobs:\n"
        "  verify:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262\n"
        "      - name: Run verification gates\n"
        "        run: python3 scripts/verify_all.py\n"
        "      - name: Expression test\n"
        "        run: echo \"${{ github.ref == 'refs/heads/main' || github.event_name == 'push' }}\"\n"
    )
    _setup_check_22_env(tmp_path, workflow_content=wf)
    fails, infos = check_22_ci_supply_chain(str(tmp_path))
    assert len(fails) == 0


def test_check_22_control_k_pipeline_with_shell_bash_pass(tmp_path):
    """Control K: actual pipeline with explicit shell: bash -> PASS"""
    wf = (
        "name: Verify\n"
        "permissions:\n"
        "  contents: read\n"
        "jobs:\n"
        "  verify:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262\n"
        "      - name: Run verification gates\n"
        "        run: python3 scripts/verify_all.py\n"
        "      - name: Pipeline with bash\n"
        "        shell: bash\n"
        "        run: echo 'hello' | tr a-z A-Z\n"
    )
    _setup_check_22_env(tmp_path, workflow_content=wf)
    fails, infos = check_22_ci_supply_chain(str(tmp_path))
    assert len(fails) == 0


def test_check_22_control_l_pipeline_with_set_pipefail_pass(tmp_path):
    """Control L: actual pipeline with set -o pipefail first -> PASS"""
    wf = (
        "name: Verify\n"
        "permissions:\n"
        "  contents: read\n"
        "jobs:\n"
        "  verify:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262\n"
        "      - name: Run verification gates\n"
        "        run: python3 scripts/verify_all.py\n"
        "      - name: Pipefail pipeline\n"
        "        run: |\n"
        "          set -o pipefail\n"
        "          echo 'hello' | tr a-z A-Z\n"
    )
    _setup_check_22_env(tmp_path, workflow_content=wf)
    fails, infos = check_22_ci_supply_chain(str(tmp_path))
    assert len(fails) == 0


def test_check_22_current_repo_workflow_pass():
    """Prove current legal repository workflow shape is not falsely rejected"""
    repo_root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    fails, infos = check_22_ci_supply_chain(repo_root_path)
    assert len(fails) == 0
