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
                "verification_status": "PENDING_EXTERNAL",
                "source_kind": "EXTERNAL_ARTIFACT",
                "external_artifact": {
                    "task_id": "B-109-M2",
                    "path": ".git/B-109-M2-user-doc.json",
                    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                },
            },
            {
                "id": "EV_RAW_UNVERIFIED",
                "origin": "MACHINE_CAPTURED_RAW",
                "verification_status": "UNVERIFIED",
                "source_kind": "EXTERNAL_ARTIFACT",
                "external_artifact": {
                    "task_id": "B-109-M2",
                    "path": ".git/B-109-M2-raw-unverified.json",
                    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                },
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


def test_positive_p_a_user_provided_external_artifact_pending_external(tmp_path):
    """P-A: USER_PROVIDED + EXTERNAL_ARTIFACT + PENDING_EXTERNAL + valid task/source/hash => PASS."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_file = scripts_dir / "execution_record.py"
    script_file.write_text("# dummy script", encoding="utf-8")

    dot_git = tmp_path / ".git"
    dot_git.mkdir(parents=True, exist_ok=True)
    art_file = dot_git / "B-109-M2-user-doc.json"
    content = b'{"notes": "external user evidence"}'
    art_file.write_bytes(content)
    import hashlib
    art_sha = hashlib.sha256(content).hexdigest()

    rec = make_valid_record(str(tmp_path))
    ev_user = [e for e in rec["evidence"] if e["id"] == "EV_USER_DOC"][0]
    ev_user["origin"] = "USER_PROVIDED"
    ev_user["verification_status"] = "PENDING_EXTERNAL"
    ev_user["source_kind"] = "EXTERNAL_ARTIFACT"
    ev_user["external_artifact"] = {
        "task_id": "B-109-M2",
        "path": ".git/B-109-M2-user-doc.json",
        "sha256": art_sha,
    }

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is True, f"Expected PASS but got error: {err}"


def test_positive_p_b_machine_captured_raw_external_artifact_unverified(tmp_path):
    """P-B: MACHINE_CAPTURED_RAW + EXTERNAL_ARTIFACT + UNVERIFIED + valid identity => PASS."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_file = scripts_dir / "execution_record.py"
    script_file.write_text("# dummy script", encoding="utf-8")

    rec = make_valid_record(str(tmp_path))
    ev_raw = [e for e in rec["evidence"] if e["id"] == "EV_RAW_UNVERIFIED"][0]
    ev_raw["origin"] = "MACHINE_CAPTURED_RAW"
    ev_raw["verification_status"] = "UNVERIFIED"
    ev_raw["source_kind"] = "EXTERNAL_ARTIFACT"
    ev_raw["external_artifact"] = {
        "task_id": "B-109-M2",
        "path": ".git/B-109-M2-raw-unverified.json",
        "sha256": "0" * 64,
    }

    # Even if file doesn't exist locally, identity structure is valid and status is UNVERIFIED
    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is True, f"Expected PASS but got error: {err}"


def test_positive_p_c_user_provided_repo_path_verified(tmp_path):
    """P-C: USER_PROVIDED + REPO_PATH + VERIFIED + existing repo path => PASS, proving origin/status axes remain independent."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_file = scripts_dir / "execution_record.py"
    script_file.write_text("# dummy script", encoding="utf-8")

    rec = make_valid_record(str(tmp_path))
    ev_repo = [e for e in rec["evidence"] if e["id"] == "EV_REPO_FILE"][0]
    ev_repo["origin"] = "USER_PROVIDED"
    ev_repo["verification_status"] = "VERIFIED"
    ev_repo["source_kind"] = "REPO_PATH"
    ev_repo["path"] = "scripts/execution_record.py"

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is True, f"Expected PASS for USER_PROVIDED + REPO_PATH + VERIFIED but got error: {err}"


def test_legacy_external_verified_now_fails(tmp_path):
    """LEGACY_EXTERNAL_VERIFIED_NOW_FAILS: USER_PROVIDED + VERIFIED + EXTERNAL_ARTIFACT must FAIL."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_file = scripts_dir / "execution_record.py"
    script_file.write_text("# dummy script", encoding="utf-8")

    rec = make_valid_record(str(tmp_path))
    ev_user = [e for e in rec["evidence"] if e["id"] == "EV_USER_DOC"][0]
    ev_user["origin"] = "USER_PROVIDED"
    ev_user["verification_status"] = "VERIFIED"
    ev_user["source_kind"] = "EXTERNAL_ARTIFACT"

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is False, "Expected legacy USER_PROVIDED + VERIFIED + EXTERNAL_ARTIFACT to FAIL"
    assert "EXTERNAL_ARTIFACT cannot have verification_status VERIFIED" in err


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


# ---------------------------------------------------------------------------
# Negative Tests: EXTERNAL_ARTIFACT constraints (N1 - N10)
# ---------------------------------------------------------------------------

def test_negative_n1_missing_external_artifact_block(tmp_path):
    """N1: missing external_artifact block => FAIL."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "execution_record.py").write_text("# dummy", encoding="utf-8")

    rec = make_valid_record(str(tmp_path))
    ev_user = [e for e in rec["evidence"] if e["id"] == "EV_USER_DOC"][0]
    del ev_user["external_artifact"]

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is False
    assert "missing 'external_artifact' block" in err


def test_negative_n2_missing_keys_in_external_artifact(tmp_path):
    """N2: missing task_id/path/sha256 任一 => FAIL."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "execution_record.py").write_text("# dummy", encoding="utf-8")

    for missing_key in ("task_id", "path", "sha256"):
        rec = make_valid_record(str(tmp_path))
        ev_user = [e for e in rec["evidence"] if e["id"] == "EV_USER_DOC"][0]
        del ev_user["external_artifact"][missing_key]
        ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
        assert ok is False, f"Expected FAIL when {missing_key} is missing"
        assert f"missing or empty '{missing_key}'" in err


def test_negative_n3_wrong_task(tmp_path):
    """N3: wrong task => FAIL."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "execution_record.py").write_text("# dummy", encoding="utf-8")

    rec = make_valid_record(str(tmp_path))
    ev_user = [e for e in rec["evidence"] if e["id"] == "EV_USER_DOC"][0]
    ev_user["external_artifact"]["task_id"] = "OTHER-TASK-999"

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is False
    assert "external_artifact task_id mismatch" in err


def test_negative_n4_path_not_task_prefixed(tmp_path):
    """N4: path 非 .git/<record.task_id>-* => FAIL."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "execution_record.py").write_text("# dummy", encoding="utf-8")

    rec = make_valid_record(str(tmp_path))
    ev_user = [e for e in rec["evidence"] if e["id"] == "EV_USER_DOC"][0]
    ev_user["external_artifact"]["path"] = ".git/other-prefix-artifact.json"

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is False
    assert "must start with" in err


def test_negative_n5_traversal_absolute_wildcard(tmp_path):
    """N5: traversal/absolute/wildcard => FAIL."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "execution_record.py").write_text("# dummy", encoding="utf-8")

    bad_paths = [
        ".git/B-109-M2-../traversal.json",
        ".git/B-109-M2-subdir/raw.json",
        "/etc/B-109-M2-abs.json",
        ".git/B-109-M2-*.json",
        ".git/WRONG-TASK-raw.json",
        ".git/B-109-M2-",
    ]
    for bp in bad_paths:
        rec = make_valid_record(str(tmp_path))
        ev_user = [e for e in rec["evidence"] if e["id"] == "EV_USER_DOC"][0]
        ev_user["external_artifact"]["path"] = bp
        ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
        assert ok is False, f"Expected FAIL for path {bp}"
        if bp == ".git/B-109-M2-../traversal.json":
            assert "VIOLATES_EXTERNAL_TASK_ARTIFACT_DIRECT_CHILD_CONTRACT" in err


def test_negative_n6_local_source_symlink_or_reparse(tmp_path, monkeypatch):
    """N6: local source symlink/reparse => FAIL."""
    import stat
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "execution_record.py").write_text("# dummy", encoding="utf-8")

    dot_git = tmp_path / ".git"
    dot_git.mkdir(parents=True, exist_ok=True)
    real_file = dot_git / "B-109-M2-real.json"
    real_file.write_text("content", encoding="utf-8")
    import hashlib
    sha = hashlib.sha256(b"content").hexdigest()

    rec = make_valid_record(str(tmp_path))
    ev_user = [e for e in rec["evidence"] if e["id"] == "EV_USER_DOC"][0]
    ev_user["external_artifact"]["path"] = ".git/B-109-M2-real.json"
    ev_user["external_artifact"]["sha256"] = sha

    orig_lstat = os.lstat
    class FakeStatResult:
        st_mode = stat.S_IFLNK | 0o777
    monkeypatch.setattr(os, "lstat", lambda path: FakeStatResult() if "B-109-M2-real.json" in str(path) else orig_lstat(path))

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is False
    assert "cannot be a symlink" in err


def test_negative_n7_wrong_fresh_hash(tmp_path):
    """N7: wrong fresh hash => FAIL."""
    import hashlib
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "execution_record.py").write_text("# dummy", encoding="utf-8")

    dot_git = tmp_path / ".git"
    dot_git.mkdir(parents=True, exist_ok=True)
    real_file = dot_git / "B-109-M2-user-doc.json"
    real_file.write_text("actual content", encoding="utf-8")

    rec = make_valid_record(str(tmp_path))
    ev_user = [e for e in rec["evidence"] if e["id"] == "EV_USER_DOC"][0]
    ev_user["external_artifact"]["path"] = ".git/B-109-M2-user-doc.json"
    ev_user["external_artifact"]["sha256"] = hashlib.sha256(b"different content").hexdigest()

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is False
    assert "fresh SHA-256 mismatch" in err


def test_negative_n8_noncanonical_sha256(tmp_path):
    """N8: noncanonical SHA-256 => FAIL."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "execution_record.py").write_text("# dummy", encoding="utf-8")

    noncanonical_hashes = [
        "A" * 64,
        "0" * 63,
        "0" * 65,
        "g" * 64,
    ]
    for h in noncanonical_hashes:
        rec = make_valid_record(str(tmp_path))
        ev_user = [e for e in rec["evidence"] if e["id"] == "EV_USER_DOC"][0]
        ev_user["external_artifact"]["sha256"] = h
        ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
        assert ok is False, f"Expected FAIL for noncanonical hash {h!r}"
        assert "canonical lowercase 64-hex" in err


def test_negative_n9_valid_source_task_hash_but_status_verified(tmp_path):
    """N9: valid source/task/hash 但 status=VERIFIED => FAIL."""
    import hashlib
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "execution_record.py").write_text("# dummy", encoding="utf-8")

    dot_git = tmp_path / ".git"
    dot_git.mkdir(parents=True, exist_ok=True)
    real_file = dot_git / "B-109-M2-user-doc.json"
    content = b"valid content"
    real_file.write_bytes(content)
    real_sha = hashlib.sha256(content).hexdigest()

    rec = make_valid_record(str(tmp_path))
    ev_user = [e for e in rec["evidence"] if e["id"] == "EV_USER_DOC"][0]
    ev_user["external_artifact"]["path"] = ".git/B-109-M2-user-doc.json"
    ev_user["external_artifact"]["sha256"] = real_sha
    ev_user["verification_status"] = "VERIFIED"

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is False
    assert "EXTERNAL_ARTIFACT cannot have verification_status VERIFIED" in err


def test_negative_n10_non_external_source_kind_with_external_artifact_block(tmp_path):
    """N10: non-external source_kind 夾帶 external_artifact block => FAIL."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "execution_record.py").write_text("# dummy", encoding="utf-8")

    rec = make_valid_record(str(tmp_path))
    ev_repo = [e for e in rec["evidence"] if e["id"] == "EV_REPO_FILE"][0]
    ev_repo["external_artifact"] = {
        "task_id": "B-109-M2",
        "path": ".git/B-109-M2-test.json",
        "sha256": "0" * 64,
    }

    ok, err = execution_record.validate_execution_record(rec, repo_root=str(tmp_path), check_git=False)
    assert ok is False
    assert "non-EXTERNAL_ARTIFACT source_kind cannot contain 'external_artifact' block" in err


# ---------------------------------------------------------------------------
# Writer tests: WRITER-N1 and WRITER-P1
# ---------------------------------------------------------------------------

def test_writer_n1_no_stale_m2_discovery_evidence(tmp_path):
    """WRITER-N1: writer output 不再生成 stale M2 evidence/claim/fixed hash."""
    import subprocess
    import shutil
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    prod_script = os.path.join(SCRIPTS_DIR, "execution_record.py")
    shutil.copy(prod_script, str(scripts_dir / "execution_record.py"))

    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    base_oid = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(tmp_path), capture_output=True, text=True, check=True).stdout.strip().lower()

    out_file = "docs/governance/execution-record.json"
    plan_data = {
        "task_id": "B-107-TEST",
        "base_oid": base_oid,
        "allowed_paths": [out_file],
        "required_paths": [out_file],
        "max_plan_revisions": 3,
        "revision_count": 0,
        "plan_origin": "EXTERNAL_MACRO_PROMPT",
    }
    task_id = "B-107-TEST"
    dot_git = tmp_path / ".git"
    dot_git.mkdir(parents=True, exist_ok=True)
    plan_file = dot_git / f"{task_id}-writer-test-plan.json"
    plan_file.write_text(json.dumps(plan_data), encoding="utf-8")

    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=str(tmp_path), capture_output=True, text=True, check=True).stdout
    assert str(plan_file.name) not in untracked

    ok, msg = execution_record.write_execution_record(str(plan_file), output_path=out_file, repo_root=str(tmp_path))
    assert ok is True, f"write_execution_record failed: {msg}"

    written_content = (tmp_path / out_file).read_text(encoding="utf-8")
    assert "M2_DISCOVERY_RAW" not in written_content
    assert "CLAIM_DISCOVERY_PROVENANCE_VERIFIED" not in written_content
    assert "4cd2851da921aab9d371b281f51947e2645b069d38ee56655e37a79c2ded3b4b" not in written_content


def test_writer_p1_writer_output_validates(tmp_path):
    """WRITER-P1: writer output 通過 production validate_execution_record."""
    import subprocess
    import shutil
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    prod_script = os.path.join(SCRIPTS_DIR, "execution_record.py")
    shutil.copy(prod_script, str(scripts_dir / "execution_record.py"))

    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    base_oid = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(tmp_path), capture_output=True, text=True, check=True).stdout.strip().lower()

    out_file = "docs/governance/execution-record.json"
    plan_data = {
        "task_id": "B-107-TEST",
        "base_oid": base_oid,
        "allowed_paths": [out_file],
        "required_paths": [out_file],
        "max_plan_revisions": 3,
        "revision_count": 0,
        "plan_origin": "EXTERNAL_MACRO_PROMPT",
    }
    task_id = "B-107-TEST"
    dot_git = tmp_path / ".git"
    dot_git.mkdir(parents=True, exist_ok=True)
    plan_file = dot_git / f"{task_id}-writer-test-plan.json"
    plan_file.write_text(json.dumps(plan_data), encoding="utf-8")

    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=str(tmp_path), capture_output=True, text=True, check=True).stdout
    assert str(plan_file.name) not in untracked

    ok, msg = execution_record.write_execution_record(str(plan_file), output_path=out_file, repo_root=str(tmp_path))
    assert ok is True, f"write_execution_record failed: {msg}"

    written_data = json.loads((tmp_path / out_file).read_text(encoding="utf-8"))
    ok_val, err_val = execution_record.validate_execution_record(written_data, repo_root=str(tmp_path), check_git=False)
    assert ok_val is True, f"Generated record failed validation: {err_val}"
