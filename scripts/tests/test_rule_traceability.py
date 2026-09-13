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
    """Repo-state gate：當前 repository 的 docs/generated/rule-traceability.md 必須完全 fresh。

    未重新產生 artifact 或 active rules 漂移時，本測試在 verify_all 第 4 Gate 中必須 FAIL。
    """
    exit_code = grt.check_rule_traceability(REPO_ROOT)
    assert exit_code == 0, (
        "docs/generated/rule-traceability.md is stale! "
        "Run `python scripts/generate_rule_traceability.py --write` to update."
    )
