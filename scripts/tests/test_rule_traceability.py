#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/tests/test_rule_traceability.py — 測試 machine-generated rule traceability。

涵蓋：
- 確定性輸出與穩定排序 (deterministic output / stable ordering)
- 顯式引用抽取 (explicit reference extraction)
- 最近 Markdown 標題歸屬 (nearest heading attribution)
- generated file 不會自我掃描 (no self-scanning)
- resolvable broken explicit target fail-closed (不得偷換 target 或 archive)
- --check 對 fresh artifact PASS
- --check 對 stale artifact FAIL
- 不從自然語言推測不存在的 semantic lineage
- repo-state traceability freshness check (整合至 canonical verify_all 第 4 Gate)
"""

import os
import sys
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import generate_rule_traceability as grt


def test_deterministic_output_and_stable_ordering():
    """驗證生成器輸出具備 100% 確定性與穩定排序。"""
    c1 = grt.generate_traceability_content(REPO_ROOT)
    c2 = grt.generate_traceability_content(REPO_ROOT)
    assert c1 == c2, "兩次生成內容位元組不一致"

    # 驗證無 CRLF
    assert "\r\n" not in c1, "輸出包含 CRLF，違反 LF canonical output 規範"
    assert "<!-- GENERATED FILE - DO NOT EDIT -->" in c1


def test_explicit_reference_extraction(tmp_path):
    """驗證 ADR、CHECK、TASK、SECTION、FILE 各類型顯式引用的抽取正確性。"""
    # 建立一個測試用 ADR
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0002-skill-invocation-aggressiveness.md").write_text("# ADR-0002", encoding="utf-8")
    (tmp_path / "PRINCIPLES.md").write_text("# Principles\n\n## 1. 原則\n", encoding="utf-8")

    sample_md = tmp_path / "sample.md"
    sample_md.write_text(
        "# Sample Document\n\n"
        "此處引用 ADR-0002 與 CHECK 10。\n"
        "任務編號 B-01 必須遵守。\n"
        "參見 PRINCIPLES.md §1 的說明。\n"
        "連結：[原則](./PRINCIPLES.md)。\n",
        encoding="utf-8",
    )

    entries = grt.extract_references_from_file("sample.md", root_dir=str(tmp_path))
    ref_types = {e["ref_type"] for e in entries}
    assert "ADR" in ref_types
    assert "CHECK" in ref_types
    assert "TASK" in ref_types
    assert "SECTION" in ref_types
    assert "FILE" in ref_types

    adr_entry = next(e for e in entries if e["ref_type"] == "ADR")
    assert adr_entry["raw_ref"] == "ADR-0002"
    assert adr_entry["status"] == "RESOLVED"
    assert "0002-skill-invocation-aggressiveness.md" in adr_entry["target"]


def test_nearest_heading_attribution(tmp_path):
    """驗證引用正確歸屬於最靠近的 Markdown 標題，檔頭無標題處歸屬為 (document root)。"""
    test_file = tmp_path / "test_heading.md"
    test_file.write_text(
        "Line 1 before heading ADR-0001\n"
        "# Section Alpha\n"
        "Line 3 under Alpha CHECK 1\n"
        "## Section Beta\n"
        "Line 5 under Beta CHECK 2\n",
        encoding="utf-8",
    )

    entries = grt.extract_references_from_file("test_heading.md", root_dir=str(tmp_path))
    assert len(entries) == 3

    e1 = next(e for e in entries if e["raw_ref"] == "ADR-0001")
    assert e1["heading"] == "(document root)"

    e2 = next(e for e in entries if e["raw_ref"] == "CHECK 1")
    assert e2["heading"] == "# Section Alpha"

    e3 = next(e for e in entries if e["raw_ref"] == "CHECK 2")
    assert e3["heading"] == "## Section Beta"


def test_fence_aware_heading_attribution_regression(tmp_path):
    """回歸測試：Markdown fenced code block (``` 與 ~~~) 及縮排註解中的 '# ' 不得污染 Nearest Heading。

    真正 heading -> fenced code 裡 # Fake -> fence 結束 -> 後續 explicit reference
    後續 reference 的 nearest heading 仍必須是真正 heading，不能是 # Fake。
    """
    test_file = tmp_path / "test_fence.md"
    test_file.write_text(
        "# Real Heading Alpha\n\n"
        "```python\n"
        "# Fake Heading in Backtick Fence\n"
        "x = 1\n"
        "```\n\n"
        "此處在圍欄之後引用 CHECK 1。\n\n"
        "## Real Heading Beta\n\n"
        "~~~\n"
        "# Fake Heading in Tilde Fence\n"
        "y = 2\n"
        "~~~\n\n"
        "此處在波浪號圍欄之後引用 CHECK 2。\n\n"
        "      # Indented Comment Not Heading\n"
        "此處在縮排註解之後引用 CHECK 3。\n",
        encoding="utf-8",
    )

    entries = grt.extract_references_from_file("test_fence.md", root_dir=str(tmp_path))
    assert len(entries) == 3

    e1 = next(e for e in entries if e["raw_ref"] == "CHECK 1")
    assert e1["heading"] == "# Real Heading Alpha", f"期望 # Real Heading Alpha，實際為 {e1['heading']}"

    e2 = next(e for e in entries if e["raw_ref"] == "CHECK 2")
    assert e2["heading"] == "## Real Heading Beta", f"期望 ## Real Heading Beta，實際為 {e2['heading']}"

    e3 = next(e for e in entries if e["raw_ref"] == "CHECK 3")
    assert e3["heading"] == "## Real Heading Beta", f"期望 ## Real Heading Beta，實際為 {e3['heading']}"


def test_generated_file_does_not_self_scan():
    """驗證 generated artifact 絕不掃描自身，排除 docs/generated/。"""
    scan_files = grt.get_scan_files(REPO_ROOT)
    for f in scan_files:
        assert not f.startswith("docs/generated/"), f"掃描清單包含 generated 檔案: {f}"
        assert f != grt.OUTPUT_REL_PATH


def test_resolvable_broken_explicit_target_fail_closed(tmp_path):
    """驗證顯式目標若不存在，嚴格標示 FAIL_CLOSED，不得悄悄換 archive 或猜測另一 target。"""
    broken_file = tmp_path / "broken.md"
    broken_file.write_text(
        "# Broken Target File\n"
        "此處顯式指向不存在檔案：[missing](non_existent_target.md)\n"
        "此處顯式指向不存在 ADR：ADR-9999\n",
        encoding="utf-8",
    )

    entries = grt.extract_references_from_file("broken.md", root_dir=str(tmp_path))
    file_entry = next(e for e in entries if e["ref_type"] == "FILE")
    assert file_entry["status"] == "FAIL_CLOSED"
    assert "FILE NOT FOUND" in file_entry["target"]

    adr_entry = next(e for e in entries if e["ref_type"] == "ADR")
    assert adr_entry["status"] == "FAIL_CLOSED"
    assert "NOT FOUND" in adr_entry["target"]


def test_check_mode_fresh_and_stale(tmp_path, monkeypatch):
    """驗證 --check 對 fresh artifact 回傳 0 (PASS)，對 stale 或缺檔回傳 1 (FAIL)。"""
    # 建立最小 control-plane repo 結構
    (tmp_path / "MISSION.md").write_text("# Mission\n", encoding="utf-8")
    (tmp_path / "PRINCIPLES.md").write_text("# Principles\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")

    # 1. 尚未產生檔案 -> --check 回傳 1
    assert grt.check_rule_traceability(root_dir=str(tmp_path)) == 1

    # 2. 寫入最新內容 -> --check 回傳 0
    assert grt.write_rule_traceability(root_dir=str(tmp_path)) == 0
    assert grt.check_rule_traceability(root_dir=str(tmp_path)) == 0

    # 3. 故意破壞檔案內容使之 stale -> --check 回傳 1
    out_file = tmp_path / grt.OUTPUT_REL_PATH
    out_file.write_text("STALE ARTIFACT CONTENT", encoding="utf-8")
    assert grt.check_rule_traceability(root_dir=str(tmp_path)) == 1


def test_negative_canary_fresh_artifact_with_blocking_fail_closed_fails_check(tmp_path):
    """核心負向金絲雀 (Negative Canary)：fresh != valid。

    建立最小 active control-plane source，其中顯式指向不存在的檔案或 ADR。
    1. --write 產生 fresh artifact
    2. 驗證 artifact bytes 與 expected 100% 完全一致
    3. --check 必須仍回傳 non-zero (1)，阻擋 false-green。
    """
    (tmp_path / "MISSION.md").write_text(
        "# Mission\n\n"
        "顯式指向不存在的目標檔案：[missing](non_existent_file.md)\n"
        "顯式指向不存在的 ADR：ADR-9999\n",
        encoding="utf-8",
    )
    (tmp_path / "PRINCIPLES.md").write_text("# Principles\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")

    # 1. 寫入 fresh artifact
    assert grt.write_rule_traceability(root_dir=str(tmp_path)) == 0

    # 2. 驗證 artifact bytes 與 expected 完全一致 (100% fresh)
    out_path = tmp_path / grt.OUTPUT_REL_PATH
    actual_bytes = out_path.read_bytes()
    expected_bytes = grt.generate_traceability_content(root_dir=str(tmp_path)).encode("utf-8")
    assert actual_bytes == expected_bytes, "artifact 必須與 expected 完全一致"

    # 3. --check 必須仍回傳 non-zero (1)，證明 fresh != valid
    check_exit = grt.check_rule_traceability(root_dir=str(tmp_path))
    assert check_exit != 0, f"期望 --check 回傳 non-zero，實際為 {check_exit}"


def test_valid_fixture_passes_check(tmp_path):
    """驗證有效 fixture：explicit target 真實存在 -> --check PASS。"""
    (tmp_path / "PRINCIPLES.md").write_text("# Principles\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    (tmp_path / "MISSION.md").write_text(
        "# Mission\n\n"
        "顯式指向存在的目標檔案：[principles](PRINCIPLES.md)\n",
        encoding="utf-8",
    )

    assert grt.write_rule_traceability(root_dir=str(tmp_path)) == 0
    assert grt.check_rule_traceability(root_dir=str(tmp_path)) == 0


def test_unresolved_historical_is_non_blocking_advisory(tmp_path):
    """驗證 UNRESOLVED_HISTORICAL 屬於 non-blocking advisory，不導致 --check 失敗。"""
    (tmp_path / "MISSION.md").write_text(
        "# Mission\n\n"
        "歷史語境提及 §999 但無明確檔案關聯。\n",
        encoding="utf-8",
    )
    (tmp_path / "PRINCIPLES.md").write_text("# Principles\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")

    entries = grt.extract_references_from_file("MISSION.md", root_dir=str(tmp_path))
    assert any(e["status"] == "UNRESOLVED_HISTORICAL" for e in entries)
    assert grt.write_rule_traceability(root_dir=str(tmp_path)) == 0
    assert grt.check_rule_traceability(root_dir=str(tmp_path)) == 0


def test_no_semantic_lineage_guessing(tmp_path):
    """驗證不從自然語言臆測不存在的 semantic lineage（例如未寫 ADR 編號的通篇散文）。"""
    vague_file = tmp_path / "vague.md"
    vague_file.write_text(
        "# Vague Rules\n\n"
        "這條規範應該源自之前的某個架構決策，主要是原則上的考量。\n"
        "我們遵循上游專案的哲學，但沒有給出具體的檔案路徑。\n",
        encoding="utf-8",
    )

    entries = grt.extract_references_from_file("vague.md", root_dir=str(tmp_path))
    assert len(entries) == 0, "不應從無明確路徑/編號的自然語言中臆測引用"


def test_repo_state_traceability_freshness():
    """Repo-state gate：當前 repository 的 docs/generated/rule-traceability.md 必須完全 fresh 且零 blocking 條目。

    未重新產生 artifact、active rules 漂移或存在 blocking FAIL_CLOSED 條目時，本測試在 verify_all 第 4 Gate 中必須 FAIL。
    """
    exit_code = grt.check_rule_traceability(REPO_ROOT)
    assert exit_code == 0, (
        "docs/generated/rule-traceability.md is stale or contains blocking FAIL_CLOSED entries! "
        "Run `python scripts/generate_rule_traceability.py --write` to update and resolve any broken paths."
    )

    # 驗證 generated artifact 內無 blocking FAIL_CLOSED row
    out_path = os.path.join(REPO_ROOT, grt.OUTPUT_REL_PATH)
    with open(out_path, "r", encoding="utf-8") as fh:
        content = fh.read()
    assert "FAIL_CLOSED" not in content, "docs/generated/rule-traceability.md 不得存在 blocking FAIL_CLOSED 列"


def test_skills_agents_source_coverage_and_negative_guard(tmp_path, monkeypatch):
    """M3-F1: 驗證 skills/AGENTS.md 納入 active control-plane source coverage，並具備負向控制。"""
    # A. get_scan_files(...) 包含 skills/AGENTS.md
    scan_files_repo = grt.get_scan_files(REPO_ROOT)
    assert "skills/AGENTS.md" in scan_files_repo, "REPO_ROOT 掃描清單必須包含 skills/AGENTS.md"

    # B. 當 fixture skills/AGENTS.md 包含 explicit reference 時，generated traceability 必須存在 source_file = skills/AGENTS.md
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True)
    (tmp_path / "PRINCIPLES.md").write_text("# Principles\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    (tmp_path / "MISSION.md").write_text("# Mission\n", encoding="utf-8")
    (skills_dir / "AGENTS.md").write_text(
        "# Skills Agents Authority\n\n"
        "顯式參照：[Principles](PRINCIPLES.md)\n",
        encoding="utf-8",
    )

    scan_files_tmp = grt.get_scan_files(root_dir=str(tmp_path))
    assert "skills/AGENTS.md" in scan_files_tmp

    entries = grt.extract_references_from_file("skills/AGENTS.md", root_dir=str(tmp_path))
    assert len(entries) > 0
    assert any(e["source_file"] == "skills/AGENTS.md" for e in entries)

    content = grt.generate_traceability_content(root_dir=str(tmp_path))
    assert "`skills/AGENTS.md`" in content

    # C. 負向守衛：若 skills/AGENTS.md 存在但 generator 不掃描它（例如 SCAN_SCOPE_PATTERNS 缺漏），測試必須 FAIL
    stale_patterns = [p for p in grt.SCAN_SCOPE_PATTERNS if p != "skills/AGENTS.md"]
    monkeypatch.setattr(grt, "SCAN_SCOPE_PATTERNS", stale_patterns)
    scan_files_omitted = grt.get_scan_files(root_dir=str(tmp_path))
    assert "skills/AGENTS.md" not in scan_files_omitted
    omitted_content = grt.generate_traceability_content(root_dir=str(tmp_path))
    assert "`skills/AGENTS.md` |" not in omitted_content

