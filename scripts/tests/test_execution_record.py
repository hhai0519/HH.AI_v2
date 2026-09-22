# -*- coding: utf-8 -*-
"""
scripts/tests/test_execution_record.py

Comprehensive tests for B-109 M2 Execution Record:
- Positive controls:
  - Valid plan & actual invariant checks (actual <= allowed, required <= actual)
  - Origin and verification_status independence (e.g. USER_PROVIDED + VERIFIED, MACHINE_CAPTURED_RAW + UNVERIFIED)
  - REG-11: REPO_PATH exists
  - REG-12: MACHINE_DERIVED valid generator path & SHA256
  - REG-13: Report traceability (claims -> valid evidence IDs)
- Negative controls:
  - actual outside allowed
  - required missing from actual
  - revision_count > 3
  - duplicate path in plan/actual
  - absolute path / path traversal / wildcard in paths
  - REG-11 violation: REPO_PATH missing
  - REG-12 violation: generator path missing or SHA256 mismatch
  - REG-13 violation: claim referencing missing evidence ID, duplicate evidence ID in claim, claim with empty evidence_ids
  - Invalid origin or missing verification_status
"""

import os
import sys
import json
import pytest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import execution_record

BASE_OID = "d7a091de9111178ff1017d64f4608cc446b5bd1a"


def make_valid_record(repo_root: str):
    script_rel = "scripts/execution_record.py"
    script_abs = os.path.join(repo_root, script_rel)
    gen_sha = execution_record.compute_file_sha256(script_abs)

    return {
        "schema_version": 1,
        "governance_version": "B109-M2",
        "task_id": "B-109-M2",
        "base_oid": BASE_OID,
        "plan": {
            "allowed_paths": [
                "docs/governance/execution-record.json",
                "scripts/execution_record.py",
            ],
            "required_paths": [
                "docs/governance/execution-record.json",
                "scripts/execution_record.py",
            ],
            "max_plan_revisions": 3,
            "revision_count": 0,
            "plan_origin": "EXTERNAL_MACRO_PROMPT",
        },
        "actual": {
            "changed_paths": [
                "docs/governance/execution-record.json",
                "scripts/execution_record.py",
            ],
        },
        "evidence": [
            {
                "id": "EV_DIFF",
                "origin": "MACHINE_DERIVED",
                "verification_status": "VERIFIED",
                "source_kind": "GIT_DIFF",
                "generator": {
                    "path": script_rel,
                    "sha256": gen_sha,
                },
            },
            {
                "id": "EV_USER_DOC",
                "origin": "USER_PROVIDED",
                "verification_status": "VERIFIED",
                "source_kind": "EXTERNAL_ARTIFACT",
            },
            {
                "id": "EV_RAW_UNVERIFIED",
                "origin": "MACHINE_CAPTURED_RAW",
                "verification_status": "UNVERIFIED",
                "source_kind": "EXTERNAL_ARTIFACT",
            },
            {
                "id": "EV_REPO_FILE",
                "origin": "AGENT_ASSERTED",
                "verification_status": "VERIFIED",
                "source_kind": "REPO_PATH",
                "path": script_rel,
            },
        ],
        "report_claims": [
            {
                "claim_id": "CLAIM_1",
                "claim_text": "Diff verified against allowed plan",
                "evidence_ids": ["EV_DIFF", "EV_USER_DOC"],
            },
            {
                "claim_id": "CLAIM_2",
                "claim_text": "Repo path verified",
                "evidence_ids": ["EV_REPO_FILE"],
            },
        ],
    }


# ---------------------------------------------------------------------------
# Positive Tests
# ---------------------------------------------------------------------------

def test_valid_record(tmp_path):
    # Setup minimal repo structure
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_file = scripts_dir / "execution_record.py"
    script_file.write_text("# dummy script", encoding="utf-8")

    rec = make_valid_record(str(tmp_path))
    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is True, f"Expected valid record but got error: {err}"


def test_evidence_origin_verification_separation(tmp_path):
    """Test that origin and verification status are independent axes."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_file = scripts_dir / "execution_record.py"
    script_file.write_text("# dummy script", encoding="utf-8")

    rec = make_valid_record(str(tmp_path))
    # USER_PROVIDED + VERIFIED
    ev_user = [e for e in rec["evidence"] if e["id"] == "EV_USER_DOC"][0]
    assert ev_user["origin"] == "USER_PROVIDED"
    assert ev_user["verification_status"] == "VERIFIED"

    # MACHINE_CAPTURED_RAW + UNVERIFIED
    ev_raw = [e for e in rec["evidence"] if e["id"] == "EV_RAW_UNVERIFIED"][0]
    assert ev_raw["origin"] == "MACHINE_CAPTURED_RAW"
    assert ev_raw["verification_status"] == "UNVERIFIED"

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is True


# ---------------------------------------------------------------------------
# Negative Tests: Plan & Actual Invariants
# ---------------------------------------------------------------------------

def test_negative_actual_outside_allowed(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_file = scripts_dir / "execution_record.py"
    script_file.write_text("# dummy script", encoding="utf-8")

    rec = make_valid_record(str(tmp_path))
    rec["actual"]["changed_paths"].append("scripts/unauthorized.py")
    rec["actual"]["changed_paths"].sort()

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is False
    assert "outside allowed scope" in err


def test_negative_required_missing(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_file = scripts_dir / "execution_record.py"
    script_file.write_text("# dummy script", encoding="utf-8")

    rec = make_valid_record(str(tmp_path))
    rec["plan"]["required_paths"].append("scripts/extra_required.py")
    rec["plan"]["allowed_paths"].append("scripts/extra_required.py")
    rec["plan"]["required_paths"].sort()
    rec["plan"]["allowed_paths"].sort()

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is False
    assert "required paths missing from actual" in err


def test_negative_revision_count_exceeded(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_file = scripts_dir / "execution_record.py"
    script_file.write_text("# dummy script", encoding="utf-8")

    rec = make_valid_record(str(tmp_path))
    rec["plan"]["revision_count"] = 4

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is False
    assert "revision_count" in err


def test_negative_duplicate_path(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_file = scripts_dir / "execution_record.py"
    script_file.write_text("# dummy script", encoding="utf-8")

    rec = make_valid_record(str(tmp_path))
    rec["plan"]["allowed_paths"] = ["scripts/execution_record.py", "scripts/execution_record.py"]

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is False
    assert "Duplicate path" in err


def test_negative_path_traversal(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_file = scripts_dir / "execution_record.py"
    script_file.write_text("# dummy script", encoding="utf-8")

    rec = make_valid_record(str(tmp_path))
    rec["plan"]["allowed_paths"] = ["../secret.txt"]

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is False
    assert "Path traversal" in err


def test_negative_absolute_path(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_file = scripts_dir / "execution_record.py"
    script_file.write_text("# dummy script", encoding="utf-8")

    rec = make_valid_record(str(tmp_path))
    rec["plan"]["allowed_paths"] = ["/etc/passwd"]

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is False
    assert "Absolute path forbidden" in err


# ---------------------------------------------------------------------------
# Negative Tests: REG-11, REG-12, REG-13
# ---------------------------------------------------------------------------

def test_reg11_repo_path_missing(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_file = scripts_dir / "execution_record.py"
    script_file.write_text("# dummy script", encoding="utf-8")

    rec = make_valid_record(str(tmp_path))
    # Point REPO_PATH evidence to non-existent file
    for ev in rec["evidence"]:
        if ev["source_kind"] == "REPO_PATH":
            ev["path"] = "scripts/non_existent.py"

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is False
    assert "REG-11 violation" in err


def test_reg12_generator_missing(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_file = scripts_dir / "execution_record.py"
    script_file.write_text("# dummy script", encoding="utf-8")

    rec = make_valid_record(str(tmp_path))
    for ev in rec["evidence"]:
        if ev["origin"] == "MACHINE_DERIVED":
            ev["generator"]["path"] = "scripts/phantom_generator.py"

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is False
    assert "REG-12 violation: Generator path does not exist" in err


def test_reg12_generator_sha_mismatch(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_file = scripts_dir / "execution_record.py"
    script_file.write_text("# dummy script", encoding="utf-8")

    rec = make_valid_record(str(tmp_path))
    for ev in rec["evidence"]:
        if ev["origin"] == "MACHINE_DERIVED":
            ev["generator"]["sha256"] = "0" * 64

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is False
    assert "REG-12 violation: Generator SHA mismatch" in err


def test_reg13_claim_references_missing_evidence_id(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_file = scripts_dir / "execution_record.py"
    script_file.write_text("# dummy script", encoding="utf-8")

    rec = make_valid_record(str(tmp_path))
    rec["report_claims"][0]["evidence_ids"].append("NON_EXISTENT_EV_ID")

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is False
    assert "REG-13 violation" in err
    assert "NON_EXISTENT_EV_ID" in err


def test_reg13_claim_duplicate_evidence_id(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_file = scripts_dir / "execution_record.py"
    script_file.write_text("# dummy script", encoding="utf-8")

    rec = make_valid_record(str(tmp_path))
    rec["report_claims"][0]["evidence_ids"] = ["EV_DIFF", "EV_DIFF"]

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is False
    assert "duplicate evidence reference" in err


def test_reg13_claim_without_evidence(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_file = scripts_dir / "execution_record.py"
    script_file.write_text("# dummy script", encoding="utf-8")

    rec = make_valid_record(str(tmp_path))
    rec["report_claims"][0]["evidence_ids"] = []

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is False
    assert "empty evidence_ids" in err


def test_invalid_evidence_origin(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_file = scripts_dir / "execution_record.py"
    script_file.write_text("# dummy script", encoding="utf-8")

    rec = make_valid_record(str(tmp_path))
    rec["evidence"][0]["origin"] = "MAGIC_ORIGIN"

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is False
    assert "invalid origin" in err


def test_missing_verification_status(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_file = scripts_dir / "execution_record.py"
    script_file.write_text("# dummy script", encoding="utf-8")

    rec = make_valid_record(str(tmp_path))
    del rec["evidence"][0]["verification_status"]

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is False
    assert "invalid verification_status" in err
