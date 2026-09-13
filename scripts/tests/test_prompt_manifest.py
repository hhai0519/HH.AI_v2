#!/usr/bin/env python3
"""
scripts/tests/test_prompt_manifest.py

單元測試：Prompt Manifest Validator
驗證 prompt manifest 解析、欄位檢查、語意一致性及負面金絲雀。
"""

import os
import sys
import subprocess
import pytest
from scripts.validate_prompt_manifest import (
    validate_prompt_manifest,
    parse_manifest_block,
    REQUIRED_KEYS,
)


VALID_GOAL_SPEC_PROMPT = """
你是 HH.AI_v2 專案的執行者（Antigravity IDE Agent / Executor）。

BEGIN_HHAI_PROMPT_MANIFEST
schema_version: 1
batch_mode: GOAL_SPEC
base_oid: dac592166eb1d29baba58a19dab333fbab62270f
finding_disposition: CURRENT A-14
backlog_disposition: UPDATE
taskboard_disposition: UPDATE
audit_log_disposition: UPDATE
rules_reread_required: true
fixed_signature_required: true
destructive_git_allowed: false
END_HHAI_PROMPT_MANIFEST

==================================================
【審計官自檢聲明】
E1 PASS
E2 PASS
E3 PASS
E4 PASS
E5 PASS
E6 PASS
E7 PASS
E8 PASS
E9 PASS
E10 PASS
E11 N/A
E12 PASS
E13 PASS
E14 PASS
E15 N/A
E16 PASS
E17 PASS
E18 PASS
E19 N/A
E20 N/A
E21 PASS
E22 PASS
E23 N/A
==================================================
【SUCCESS REPORT】
以上是 Antigravity IDE Agent 的回覆。
"""

VALID_EXACT_SPEC_PROMPT = """
你是 HH.AI_v2 專案的執行者（Antigravity IDE Agent / Executor）。

BEGIN_HHAI_PROMPT_MANIFEST
schema_version: 1
batch_mode: EXACT_SPEC
base_oid: dac592166eb1d29baba58a19dab333fbab62270f
finding_disposition: NONE
backlog_disposition: UPDATE
taskboard_disposition: NO_CHANGE
audit_log_disposition: NO_CHANGE
rules_reread_required: true
fixed_signature_required: true
destructive_git_allowed: false
END_HHAI_PROMPT_MANIFEST

批次規格：
docs/batches/dac5921-example-spec.spec.txt
規格 SHA-256：
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855

==================================================
【SUCCESS REPORT】
以上是 Antigravity IDE Agent 的回覆。
"""


def test_valid_goal_spec_prompt():
    ok, err, manifest = validate_prompt_manifest(VALID_GOAL_SPEC_PROMPT)
    assert ok, f"Expected valid prompt to pass, got error: {err}"
    assert manifest["batch_mode"] == "GOAL_SPEC"
    assert manifest["base_oid"] == "dac592166eb1d29baba58a19dab333fbab62270f"


def test_valid_exact_spec_prompt():
    ok, err, manifest = validate_prompt_manifest(VALID_EXACT_SPEC_PROMPT)
    assert ok, f"Expected valid EXACT_SPEC prompt to pass, got error: {err}"
    assert manifest["batch_mode"] == "EXACT_SPEC"


def test_missing_manifest():
    prompt = "你是本專案的執行者。batch_mode: GOAL_SPEC"
    ok, err, _ = validate_prompt_manifest(prompt)
    assert not ok
    assert "missing BEGIN or END marker" in err


def test_duplicate_manifest():
    prompt = (
        VALID_GOAL_SPEC_PROMPT
        + "\nBEGIN_HHAI_PROMPT_MANIFEST\nschema_version: 1\nEND_HHAI_PROMPT_MANIFEST\n"
    )
    ok, err, _ = validate_prompt_manifest(prompt)
    assert not ok
    assert "Duplicate manifest markers found" in err


def test_inverted_manifest_markers():
    prompt = "END_HHAI_PROMPT_MANIFEST\nschema_version: 1\nBEGIN_HHAI_PROMPT_MANIFEST"
    ok, err, _ = validate_prompt_manifest(prompt)
    assert not ok
    assert "END appears before BEGIN" in err


def test_missing_required_key():
    # Remove base_oid from valid manifest
    corrupted = VALID_GOAL_SPEC_PROMPT.replace(
        "base_oid: dac592166eb1d29baba58a19dab333fbab62270f\n", ""
    )
    ok, err, _ = validate_prompt_manifest(corrupted)
    assert not ok
    assert "Missing required manifest keys" in err
    assert "base_oid" in err


def test_duplicate_key():
    corrupted = VALID_GOAL_SPEC_PROMPT.replace(
        "batch_mode: GOAL_SPEC",
        "batch_mode: GOAL_SPEC\nbatch_mode: EXACT_SPEC",
    )
    ok, err, _ = validate_prompt_manifest(corrupted)
    assert not ok
    assert "Duplicate key in manifest" in err


def test_bad_schema_version():
    corrupted = VALID_GOAL_SPEC_PROMPT.replace(
        "schema_version: 1", "schema_version: 2"
    )
    ok, err, _ = validate_prompt_manifest(corrupted)
    assert not ok
    assert "Unsupported schema_version" in err


def test_bad_batch_mode():
    corrupted = VALID_GOAL_SPEC_PROMPT.replace(
        "batch_mode: GOAL_SPEC", "batch_mode: FREE_STYLE"
    )
    ok, err, _ = validate_prompt_manifest(corrupted)
    assert not ok
    assert "Invalid batch_mode" in err


def test_bad_base_oid():
    corrupted = VALID_GOAL_SPEC_PROMPT.replace(
        "base_oid: dac592166eb1d29baba58a19dab333fbab62270f",
        "base_oid: dac5921",
    )
    ok, err, _ = validate_prompt_manifest(corrupted)
    assert not ok
    assert "Invalid base_oid" in err


def test_bad_finding_disposition():
    # Test invalid format
    for bad_fd in [
        "finding_disposition: INVALID",
        "finding_disposition: CURRENT A-1",  # needs at least 2 digits
        "finding_disposition: NEW H-01",     # H is outside A-G
        "finding_disposition: EXISTING",     # missing task id
    ]:
        corrupted = VALID_GOAL_SPEC_PROMPT.replace(
            "finding_disposition: CURRENT A-14", bad_fd
        )
        ok, err, _ = validate_prompt_manifest(corrupted)
        assert not ok, f"Expected {bad_fd} to fail"
        assert "Invalid finding_disposition" in err


def test_rules_reread_required_must_be_true():
    corrupted = VALID_GOAL_SPEC_PROMPT.replace(
        "rules_reread_required: true", "rules_reread_required: false"
    )
    ok, err, _ = validate_prompt_manifest(corrupted)
    assert not ok
    assert "rules_reread_required must be 'true'" in err


def test_fixed_signature_required_must_be_true():
    corrupted = VALID_GOAL_SPEC_PROMPT.replace(
        "fixed_signature_required: true", "fixed_signature_required: false"
    )
    ok, err, _ = validate_prompt_manifest(corrupted)
    assert not ok
    assert "fixed_signature_required must be 'true'" in err


def test_destructive_git_allowed_must_be_false():
    corrupted = VALID_GOAL_SPEC_PROMPT.replace(
        "destructive_git_allowed: false", "destructive_git_allowed: true"
    )
    ok, err, _ = validate_prompt_manifest(corrupted)
    assert not ok
    assert "destructive_git_allowed must be 'false'" in err


def test_new_task_requires_taskboard_update():
    corrupted = VALID_GOAL_SPEC_PROMPT.replace(
        "finding_disposition: CURRENT A-14", "finding_disposition: NEW B-99"
    ).replace(
        "taskboard_disposition: UPDATE", "taskboard_disposition: NO_CHANGE"
    )
    ok, err, _ = validate_prompt_manifest(corrupted)
    assert not ok
    assert "requires taskboard_disposition: UPDATE" in err


def test_exact_spec_missing_batch_spec_path():
    corrupted = VALID_EXACT_SPEC_PROMPT.replace(
        "docs/batches/dac5921-example-spec.spec.txt", "some/other/path.txt"
    )
    ok, err, _ = validate_prompt_manifest(corrupted)
    assert not ok
    assert "EXACT_SPEC prompt must specify Batch Spec path" in err


def test_exact_spec_missing_sha_marker():
    corrupted = VALID_EXACT_SPEC_PROMPT.replace(
        "規格 SHA-256：", "規格檢驗碼："
    )
    ok, err, _ = validate_prompt_manifest(corrupted)
    assert not ok
    assert "EXACT_SPEC prompt must specify Batch Spec SHA-256 marker" in err


def test_macro_pass_assertion_with_audit_log_no_change_fails():
    prompt_with_verdict = VALID_GOAL_SPEC_PROMPT.replace(
        "audit_log_disposition: UPDATE", "audit_log_disposition: NO_CHANGE"
    ) + "\n正式裁決：\nA-06 = MACRO AUDIT PASS\n"
    ok, err, _ = validate_prompt_manifest(prompt_with_verdict)
    assert not ok
    assert "Contradiction: prompt asserts MACRO PASS" in err


def test_regression_fixture_2026_09_13_bad_prompt():
    """
    重現 2026-09-13 實際漏過的 A-06 瑕疵提示詞：
    缺少 batch_mode、FINDING_DISPOSITION、selftest/manifest、rules reread contract、fixed signature。
    驗證 production validator 能機械性直接擋下。
    """
    bad_prompt_2026_09_13 = """
你是 Antigravity IDE Agent（Executor）。

本批不是 B-01。
不得開始 ADR-0002 / ADR-0004 / ADR-0010 的正式分層搬移。
不得修改 B-01 的三個正式 target：
- AGENTS.md
- .agents/rules/skills-architecture.md
- .agents/rules/powershell-encoding-protocol.md

本批目標只有兩件：
A. A-06：將「規則追溯表」由人工維護改成 machine-generated traceability。
B. 將外部 Macro Reviewer 已完成的「B-01 targeted upstream comparison」事實寫入 repo state。

Base Full OID：5cf8467267327078400ad7f89cff28ac0a6a7b7a

請執行相關檔案修改與驗證。
"""
    ok, err, _ = validate_prompt_manifest(bad_prompt_2026_09_13)
    assert not ok
    assert "missing BEGIN or END marker" in err


def test_cli_file_mode(tmp_path):
    prompt_file = tmp_path / "test_prompt.txt"
    prompt_file.write_text(VALID_GOAL_SPEC_PROMPT, encoding="utf-8")

    res = subprocess.run(
        [sys.executable, "scripts/validate_prompt_manifest.py", "--file", str(prompt_file)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "[PASS]" in res.stdout


def test_cli_stdin_mode():
    res = subprocess.run(
        [sys.executable, "scripts/validate_prompt_manifest.py"],
        input=VALID_GOAL_SPEC_PROMPT,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "[PASS]" in res.stdout


def test_cli_fail_closed_mode(tmp_path):
    bad_file = tmp_path / "bad.txt"
    bad_file.write_text("Hello world without manifest", encoding="utf-8")

    res = subprocess.run(
        [sys.executable, "scripts/validate_prompt_manifest.py", "--file", str(bad_file)],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "[FAIL]" in res.stderr
