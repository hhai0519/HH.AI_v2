# -*- coding: utf-8 -*-
"""
scripts/tests/test_governance_preflight.py

Comprehensive tests for B-109 M1 Mechanical Governance Preflight:
- Rule Registry structure, completeness, and negative controls (§15)
- Shared Execution Contract parser and validation negative controls (§16)
- Governance preflight output (PASS/FAIL + Rule ID) fail-closed behavior (§17)
- Single-use sensitive push authorization lifecycle (§18)
- Real synthetic local git push hook invocation (§19, §20)
  - Ordinary batch push succeeds without authorization
  - Unauthorized main push rejected; bare remote unchanged
  - Authorized exact main push succeeds
  - Wrong SHA rejected
  - Remote deletion without authorization rejected
  - Authorized exact deletion succeeds
  - Single-use authorization consumed; cannot be reused
  - Remote ref deletion via refspec or --delete styles both checked
"""

import os
import sys
import json
import shutil
import tempfile
import subprocess
import pytest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

REPO_ROOT = os.path.abspath(os.path.join(SCRIPTS_DIR, ".."))

import validate_prompt_manifest
import governance_preflight


# ---------------------------------------------------------------------------
# Section 15: Rule Registry Tests
# ---------------------------------------------------------------------------

def test_rule_registry_structure_and_inventory():
    registry_path = os.path.join(REPO_ROOT, "docs", "governance", "rule-registry.json")
    assert os.path.exists(registry_path), "rule-registry.json must exist"

    with open(registry_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("schema_version") == 1
    assert data.get("registry_version") == "B109-M1"

    rules = data.get("rules", [])
    assert len(rules) == 13

    expected_ids = [f"GOV-M1-{i:03d}" for i in range(1, 14)]
    actual_ids = [r["id"] for r in rules]
    assert actual_ids == expected_ids, "Rule IDs must be exact and deterministically sorted"

    for r in rules:
        assert "id" in r
        assert "name" in r
        assert "enforcement_layers" in r
        assert "enforcement_strength" in r
        assert "failure_semantics" in r
        assert "owner" in r

    # GOV-M1-004: destructive git
    r4 = rules[3]
    assert r4["id"] == "GOV-M1-004"
    assert "IDE_HARNESS_PERSISTENT" in r4["enforcement_layers"]
    assert "EXECUTION_CONTRACT" in r4["enforcement_layers"]
    assert "PROMPT_PREFLIGHT" in r4["enforcement_layers"]
    assert "REG" in r4["enforcement_layers"]
    assert "AUDIT" in r4["enforcement_layers"]
    assert r4["enforcement_strength"] == "PARTIAL"

    # GOV-M1-005: credential access
    r5 = rules[4]
    assert r5["id"] == "GOV-M1-005"
    assert "IDE_HARNESS_PERSISTENT" in r5["enforcement_layers"]
    assert r5["enforcement_strength"] == "PARTIAL"

    # GOV-M1-009: browser mutation
    r9 = rules[8]
    assert r9["id"] == "GOV-M1-009"
    assert "IDE_HARNESS_PERSISTENT" in r9["enforcement_layers"]
    assert r9["enforcement_strength"] == "PARTIAL"

    # GOV-M1-011: hook bypass
    r11 = rules[10]
    assert r11["id"] == "GOV-M1-011"
    assert r11["enforcement_strength"] == "PARTIAL"

    # GOV-M1-002 and GOV-M1-003: exactness STRONG with external audit-dependent note
    r2 = rules[1]
    assert r2["id"] == "GOV-M1-002"
    assert r2["enforcement_strength"] == "STRONG"
    r2_meta = " ".join(str(v) for v in r2.values()).lower()
    assert "provenance" in r2_meta
    assert "external" in r2_meta or "audit-dependent" in r2_meta
    assert "not cryptographically prove" in r2_meta or "does not cryptographically prove" in r2_meta

    r3 = rules[2]
    assert r3["id"] == "GOV-M1-003"
    assert r3["enforcement_strength"] == "STRONG"
    r3_meta = " ".join(str(v) for v in r3.values()).lower()
    assert "provenance" in r3_meta
    assert "external" in r3_meta or "audit-dependent" in r3_meta
    assert "not cryptographically prove" in r3_meta or "does not cryptographically prove" in r3_meta


# ---------------------------------------------------------------------------
# Section 16 & 17: Execution Contract Validation Negative Controls
# ---------------------------------------------------------------------------

VALID_BASE_OID = "69b4b6c72e2bf2b91a46107afb2e7e9a2e538de1"

VALID_CONTRACT_TEXT = f"""BEGIN_HHAI_EXECUTION_CONTRACT
contract_version: 1
task_id: B-109-M1
base_oid: {VALID_BASE_OID}
main_advancement: FORBIDDEN
authorized_main_sha: NONE
remote_ref_deletion: FORBIDDEN
authorized_delete_refs: NONE
local_destructive_git: FORBIDDEN
credential_access: FORBIDDEN
environment_enumeration: FORBIDDEN
cross_session_access: FORBIDDEN
browser_github_mutation: FORBIDDEN
raw_actions_log_access: EXTERNAL_MACRO_ONLY
branch_creation: GIT_SWITCH_C
hook_bypass: FORBIDDEN
goal_pressure_policy: SAFETY_BOUNDARY_WINS
ide_ephemeral_guards_required: false
END_HHAI_EXECUTION_CONTRACT"""


def test_contract_parser_valid():
    ok, err, contract = validate_prompt_manifest.parse_execution_contract_block(VALID_CONTRACT_TEXT)
    assert ok is True
    assert err == ""
    ok_v, err_v, val_contract = validate_prompt_manifest.validate_execution_contract(contract, manifest_base_oid=VALID_BASE_OID)
    assert ok_v is True
    assert err_v == ""
    assert val_contract["task_id"] == "B-109-M1"
    assert val_contract["main_advancement"] == "FORBIDDEN"


def test_contract_missing_block():
    ok, err, _ = validate_prompt_manifest.parse_execution_contract_block("some text without contract")
    assert ok is False
    assert "missing" in err.lower()


def test_contract_duplicate_block():
    text = VALID_CONTRACT_TEXT + "\n" + VALID_CONTRACT_TEXT
    ok, err, _ = validate_prompt_manifest.parse_execution_contract_block(text)
    assert ok is False
    assert "Duplicate contract markers" in err


def test_contract_missing_required_field():
    text = VALID_CONTRACT_TEXT.replace("task_id: B-109-M1\n", "")
    ok, err, _ = validate_prompt_manifest.parse_execution_contract_block(text)
    assert ok is False
    assert "Missing required contract keys" in err


def test_contract_unknown_field():
    text = VALID_CONTRACT_TEXT.replace("task_id: B-109-M1\n", "task_id: B-109-M1\nunknown_param: dangerous\n")
    ok, err, _ = validate_prompt_manifest.parse_execution_contract_block(text)
    assert ok is False
    assert "Unexpected/unsupported key" in err


def test_contract_base_mismatch():
    ok, err, _ = validate_prompt_manifest.validate_execution_contract(VALID_CONTRACT_TEXT, manifest_base_oid="0000000000000000000000000000000000000000")
    assert ok is False
    assert "base_oid mismatch" in err


def test_contract_invalid_main_advancement_enum():
    text = VALID_CONTRACT_TEXT.replace("main_advancement: FORBIDDEN", "main_advancement: ALLOW_ALL")
    ok, err, _ = validate_prompt_manifest.validate_execution_contract(text, manifest_base_oid=VALID_BASE_OID)
    assert ok is False
    assert "Invalid main_advancement" in err


def test_contract_forbidden_main_with_non_none_sha():
    text = VALID_CONTRACT_TEXT.replace("authorized_main_sha: NONE", f"authorized_main_sha: {VALID_BASE_OID}")
    ok, err, _ = validate_prompt_manifest.validate_execution_contract(text, manifest_base_oid=VALID_BASE_OID)
    assert ok is False
    assert "authorized_main_sha must be NONE" in err


def test_contract_exact_sha_main_with_invalid_sha():
    text = VALID_CONTRACT_TEXT.replace("main_advancement: FORBIDDEN", "main_advancement: EXACT_SHA").replace("authorized_main_sha: NONE", "authorized_main_sha: not_a_sha")
    ok, err, _ = validate_prompt_manifest.validate_execution_contract(text, manifest_base_oid=VALID_BASE_OID)
    assert ok is False
    assert "authorized_main_sha must be a 40-char hex SHA" in err


def test_contract_forbidden_delete_with_non_none_refs():
    text = VALID_CONTRACT_TEXT.replace("authorized_delete_refs: NONE", "authorized_delete_refs: refs/heads/branch@1111111111111111111111111111111111111111")
    ok, err, _ = validate_prompt_manifest.validate_execution_contract(text, manifest_base_oid=VALID_BASE_OID)
    assert ok is False
    assert "authorized_delete_refs must be NONE" in err


def test_contract_exact_set_delete_with_main():
    sha = "1111111111111111111111111111111111111111"
    text = VALID_CONTRACT_TEXT.replace("remote_ref_deletion: FORBIDDEN", "remote_ref_deletion: EXACT_SET").replace("authorized_delete_refs: NONE", f"authorized_delete_refs: refs/heads/main@{sha}")
    ok, err, _ = validate_prompt_manifest.validate_execution_contract(text, manifest_base_oid=VALID_BASE_OID)
    assert ok is False
    assert "refs/heads/main is permanently forbidden" in err


def test_contract_exact_set_delete_with_duplicate_ref():
    sha1 = "1111111111111111111111111111111111111111"
    sha2 = "2222222222222222222222222222222222222222"
    refspec = f"refs/heads/foo@{sha1};refs/heads/foo@{sha2}"
    text = VALID_CONTRACT_TEXT.replace("remote_ref_deletion: FORBIDDEN", "remote_ref_deletion: EXACT_SET").replace("authorized_delete_refs: NONE", f"authorized_delete_refs: {refspec}")
    ok, err, _ = validate_prompt_manifest.validate_execution_contract(text, manifest_base_oid=VALID_BASE_OID)
    assert ok is False
    assert "Duplicate delete ref" in err


def test_contract_unsafe_credential_access():
    text = VALID_CONTRACT_TEXT.replace("credential_access: FORBIDDEN", "credential_access: ALLOWED")
    ok, err, _ = validate_prompt_manifest.validate_execution_contract(text, manifest_base_oid=VALID_BASE_OID)
    assert ok is False
    assert "credential_access must be 'FORBIDDEN'" in err


def test_contract_unsafe_environment_enumeration():
    text = VALID_CONTRACT_TEXT.replace("environment_enumeration: FORBIDDEN", "environment_enumeration: ALLOWED")
    ok, err, _ = validate_prompt_manifest.validate_execution_contract(text, manifest_base_oid=VALID_BASE_OID)
    assert ok is False
    assert "environment_enumeration must be 'FORBIDDEN'" in err


def test_contract_unsafe_cross_session_access():
    text = VALID_CONTRACT_TEXT.replace("cross_session_access: FORBIDDEN", "cross_session_access: ALLOWED")
    ok, err, _ = validate_prompt_manifest.validate_execution_contract(text, manifest_base_oid=VALID_BASE_OID)
    assert ok is False
    assert "cross_session_access must be 'FORBIDDEN'" in err


def test_contract_unsafe_browser_github_mutation():
    text = VALID_CONTRACT_TEXT.replace("browser_github_mutation: FORBIDDEN", "browser_github_mutation: ALLOWED")
    ok, err, _ = validate_prompt_manifest.validate_execution_contract(text, manifest_base_oid=VALID_BASE_OID)
    assert ok is False
    assert "browser_github_mutation must be 'FORBIDDEN'" in err


def test_contract_unsafe_raw_actions_log_access():
    text = VALID_CONTRACT_TEXT.replace("raw_actions_log_access: EXTERNAL_MACRO_ONLY", "raw_actions_log_access: EXECUTOR_ALLOWED")
    ok, err, _ = validate_prompt_manifest.validate_execution_contract(text, manifest_base_oid=VALID_BASE_OID)
    assert ok is False
    assert "raw_actions_log_access must be 'EXTERNAL_MACRO_ONLY'" in err


def test_contract_unsafe_goal_pressure_policy():
    text = VALID_CONTRACT_TEXT.replace("goal_pressure_policy: SAFETY_BOUNDARY_WINS", "goal_pressure_policy: GOAL_WINS")
    ok, err, _ = validate_prompt_manifest.validate_execution_contract(text, manifest_base_oid=VALID_BASE_OID)
    assert ok is False
    assert "goal_pressure_policy must be 'SAFETY_BOUNDARY_WINS'" in err


# ---------------------------------------------------------------------------
# Section 17 & 18: Governance Preflight Output & Single-Use Authorization
# ---------------------------------------------------------------------------

def test_governance_preflight_rule_eval_output(capsys):
    ok, err, contract = validate_prompt_manifest.parse_execution_contract_block(VALID_CONTRACT_TEXT)
    assert ok is True
    rc = governance_preflight.evaluate_contract_rules(contract, VALID_BASE_OID, repo_root=REPO_ROOT)
    captured = capsys.readouterr()

    assert rc == 0
    # Every rule from GOV-M1-001 to GOV-M1-013 must be present and PASS
    for i in range(1, 14):
        rule_id = f"GOV-M1-{i:03d}"
        assert f"{rule_id} PASS" in captured.out


def test_governance_preflight_rule_eval_fails_closed(capsys):
    ok, err, contract = validate_prompt_manifest.parse_execution_contract_block(VALID_CONTRACT_TEXT)
    assert ok is True
    # Tamper contract
    contract["local_destructive_git"] = "ALLOWED"
    rc = governance_preflight.evaluate_contract_rules(contract, VALID_BASE_OID, repo_root=REPO_ROOT)
    captured = capsys.readouterr()

    assert rc != 0
    assert "GOV-M1-004 FAIL" in captured.out


def test_single_use_main_advancement_authorization_lifecycle(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    sha = "1111111111111111111111111111111111111111"
    old_sha = "0000000000000000000000000000000000000000"

    auth_path = governance_preflight.create_main_advancement_authorization(
        task_id="TEST-01",
        authorized_main_sha=sha,
        expected_remote_main_sha=old_sha,
        git_dir=str(git_dir)
    )
    assert os.path.exists(auth_path)

    # Overwrite attempt should fail
    with pytest.raises(RuntimeError, match="Cannot overwrite unconsumed sensitive push authorization"):
        governance_preflight.create_main_advancement_authorization(
            task_id="TEST-02",
            authorized_main_sha=sha,
            expected_remote_main_sha=old_sha,
            git_dir=str(git_dir)
        )

    # Valid check passes and consumes
    assert governance_preflight.verify_and_consume_main_advancement(
        new_sha=sha,
        remote_sha=old_sha,
        git_dir=str(git_dir)
    ) is True

    # File must be consumed (deleted)
    assert not os.path.exists(auth_path)

    # Re-use attempt must fail
    assert governance_preflight.verify_and_consume_main_advancement(
        new_sha=sha,
        remote_sha=old_sha,
        git_dir=str(git_dir)
    ) is False


def test_single_use_remote_deletion_authorization_lifecycle(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    sha = "2222222222222222222222222222222222222222"
    mapping = {"refs/heads/feature-old": sha}

    auth_path = governance_preflight.create_remote_deletion_authorization(
        task_id="TEST-DEL-01",
        exact_ref_sha_map=mapping,
        git_dir=str(git_dir)
    )
    assert os.path.exists(auth_path)

    # Mismatched SHA fails
    assert governance_preflight.verify_and_consume_remote_deletion(
        actual_deletions={"refs/heads/feature-old": "3333333333333333333333333333333333333333"},
        git_dir=str(git_dir)
    ) is False

    # Still unconsumed after mismatch
    assert os.path.exists(auth_path)

    # Mismatched ref set fails
    assert governance_preflight.verify_and_consume_remote_deletion(
        actual_deletions={"refs/heads/feature-old": sha, "refs/heads/extra": sha},
        git_dir=str(git_dir)
    ) is False

    # Exact match passes and consumes
    assert governance_preflight.verify_and_consume_remote_deletion(
        actual_deletions=mapping,
        git_dir=str(git_dir)
    ) is True

    assert not os.path.exists(auth_path)


# ---------------------------------------------------------------------------
# Section 20: Real Synthetic Local Git Push Hook Invocation Tests
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_git_env(tmp_path):
    """Sets up a local bare remote and a local clone/worktree with .githooks/pre-push wired."""
    bare_dir = tmp_path / "bare.git"
    work_dir = tmp_path / "work"

    # Init bare remote
    subprocess.run(["git", "init", "--bare", str(bare_dir)], check=True, capture_output=True)

    # Init work repo
    subprocess.run(["git", "init", str(work_dir)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=str(work_dir), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(work_dir), check=True)

    # Copy .githooks, scripts, and docs into work repo
    hooks_dst = work_dir / ".githooks"
    scripts_dst = work_dir / "scripts"
    docs_dst = work_dir / "docs"

    shutil.copytree(os.path.join(REPO_ROOT, ".githooks"), str(hooks_dst))
    shutil.copytree(os.path.join(REPO_ROOT, "scripts"), str(scripts_dst))
    shutil.copytree(os.path.join(REPO_ROOT, "docs"), str(docs_dst))

    # Wire hooksPath
    subprocess.run(["git", "config", "core.hooksPath", ".githooks"], cwd=str(work_dir), check=True)

    # Add remote
    subprocess.run(["git", "remote", "add", "origin", str(bare_dir)], cwd=str(work_dir), check=True)

    # Initial commit on main
    test_file = work_dir / "README.md"
    test_file.write_text("# Initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(work_dir), check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(work_dir), check=True)
    init_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(work_dir), check=True, capture_output=True, text=True).stdout.strip()

    # Create master/main branch in remote without hook interference
    subprocess.run(["git", "branch", "-M", "main"], cwd=str(work_dir), check=True)

    # First push to remote (authorized initial setup using preflight helper directly to bare repo)
    governance_preflight.create_main_advancement_authorization(
        task_id="INIT",
        authorized_main_sha=init_sha,
        expected_remote_main_sha="0000000000000000000000000000000000000000",
        git_dir=str(work_dir / ".git")
    )
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=str(work_dir), check=True, capture_output=True)

    return {
        "bare_dir": bare_dir,
        "work_dir": work_dir,
        "init_sha": init_sha,
    }


def test_synthetic_batch_push_succeeds_without_sensitive_authorization(synthetic_git_env):
    """A. Ordinary synthetic batch push without sensitive authorization succeeds."""
    work_dir = synthetic_git_env["work_dir"]

    # Create new branch
    subprocess.run(["git", "switch", "-c", "batch/test-feature"], cwd=str(work_dir), check=True)
    f = work_dir / "feature.txt"
    f.write_text("feature content\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=str(work_dir), check=True)
    subprocess.run(["git", "commit", "-m", "add feature"], cwd=str(work_dir), check=True)

    # Push ordinary batch branch - must succeed with 0 sensitive authorization
    res = subprocess.run(["git", "push", "origin", "batch/test-feature"], cwd=str(work_dir), capture_output=True, text=True)
    assert res.returncode == 0, f"Ordinary batch push should succeed: {res.stderr}"


def test_synthetic_unauthorized_main_push_rejected(synthetic_git_env):
    """B & C. Synthetic unauthorized main push is rejected, bare remote main unchanged."""
    work_dir = synthetic_git_env["work_dir"]
    bare_dir = synthetic_git_env["bare_dir"]
    init_sha = synthetic_git_env["init_sha"]

    subprocess.run(["git", "switch", "main"], cwd=str(work_dir), check=True)
    f = work_dir / "unauthorized.txt"
    f.write_text("evil main change\n", encoding="utf-8")
    subprocess.run(["git", "add", "unauthorized.txt"], cwd=str(work_dir), check=True)
    subprocess.run(["git", "commit", "-m", "unauthorized main advance"], cwd=str(work_dir), check=True)

    # Attempt to push to main without authorization
    res = subprocess.run(["git", "push", "origin", "main"], cwd=str(work_dir), capture_output=True, text=True)
    assert res.returncode != 0
    assert "PRE-PUSH BLOCK:" in res.stderr
    assert "Unauthorized main advancement" in res.stderr

    # Verify bare remote main remained at init_sha
    res_remote = subprocess.run(["git", "rev-parse", "refs/heads/main"], cwd=str(bare_dir), check=True, capture_output=True, text=True)
    assert res_remote.stdout.strip() == init_sha


def test_synthetic_authorized_exact_main_push_succeeds_and_single_use(synthetic_git_env):
    """D & E & H. Authorized exact synthetic main push succeeds, wrong SHA blocked, single use."""
    work_dir = synthetic_git_env["work_dir"]
    init_sha = synthetic_git_env["init_sha"]

    subprocess.run(["git", "switch", "main"], cwd=str(work_dir), check=True)
    f = work_dir / "valid_advance.txt"
    f.write_text("valid change\n", encoding="utf-8")
    subprocess.run(["git", "add", "valid_advance.txt"], cwd=str(work_dir), check=True)
    subprocess.run(["git", "commit", "-m", "valid advance"], cwd=str(work_dir), check=True)
    new_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(work_dir), check=True, capture_output=True, text=True).stdout.strip()

    # Wrong SHA authorization should be rejected
    governance_preflight.create_main_advancement_authorization(
        task_id="WRONG-SHA-TEST",
        authorized_main_sha="1111111111111111111111111111111111111111",
        expected_remote_main_sha=init_sha,
        git_dir=str(work_dir / ".git")
    )
    res_wrong = subprocess.run(["git", "push", "origin", "main"], cwd=str(work_dir), capture_output=True, text=True)
    assert res_wrong.returncode != 0

    # Clean up rejected auth
    auth_file = work_dir / ".git" / "hhai-sensitive-push-auth.json"
    if auth_file.exists():
        auth_file.unlink()

    # Now create exact authorized SHA
    governance_preflight.create_main_advancement_authorization(
        task_id="EXACT-MAIN-TEST",
        authorized_main_sha=new_sha,
        expected_remote_main_sha=init_sha,
        git_dir=str(work_dir / ".git")
    )

    res_good = subprocess.run(["git", "push", "origin", "main"], cwd=str(work_dir), capture_output=True, text=True)
    assert res_good.returncode == 0, f"Authorized main push failed: {res_good.stderr}"

    # Authorization file must now be consumed
    assert not auth_file.exists()

    # Immediate second push attempt on main should be rejected because authorization was consumed
    f2 = work_dir / "another.txt"
    f2.write_text("more change\n", encoding="utf-8")
    subprocess.run(["git", "add", "another.txt"], cwd=str(work_dir), check=True)
    subprocess.run(["git", "commit", "-m", "second commit"], cwd=str(work_dir), check=True)
    res_second = subprocess.run(["git", "push", "origin", "main"], cwd=str(work_dir), capture_output=True, text=True)
    assert res_second.returncode != 0


def test_synthetic_remote_branch_deletion_authorization_and_guards(synthetic_git_env):
    """F & G. Remote branch deletion without authorization rejected; authorized exact deletion succeeds."""
    work_dir = synthetic_git_env["work_dir"]
    bare_dir = synthetic_git_env["bare_dir"]

    # First create and push a remote branch
    subprocess.run(["git", "switch", "-c", "batch/to-delete"], cwd=str(work_dir), check=True)
    f = work_dir / "del.txt"
    f.write_text("del\n", encoding="utf-8")
    subprocess.run(["git", "add", "del.txt"], cwd=str(work_dir), check=True)
    subprocess.run(["git", "commit", "-m", "del branch commit"], cwd=str(work_dir), check=True)
    del_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(work_dir), check=True, capture_output=True, text=True).stdout.strip()
    subprocess.run(["git", "push", "origin", "batch/to-delete"], cwd=str(work_dir), check=True)

    # Switch back to main
    subprocess.run(["git", "switch", "main"], cwd=str(work_dir), check=True)

    # Attempt to delete remote branch WITHOUT authorization -> REJECTED
    res_unauth = subprocess.run(["git", "push", "origin", "--delete", "batch/to-delete"], cwd=str(work_dir), capture_output=True, text=True)
    assert res_unauth.returncode != 0
    assert "PRE-PUSH BLOCK:" in res_unauth.stderr
    assert "Unauthorized remote ref deletion" in res_unauth.stderr

    # Verify target remote branch still exists and target remote SHA unchanged
    res_remote_target = subprocess.run(["git", "rev-parse", "refs/heads/batch/to-delete"], cwd=str(bare_dir), check=True, capture_output=True, text=True)
    assert res_remote_target.stdout.strip() == del_sha

    # Attempt to delete main -> ALWAYS REJECTED
    res_main_del = subprocess.run(["git", "push", "origin", "--delete", "main"], cwd=str(work_dir), capture_output=True, text=True)
    assert res_main_del.returncode != 0
    assert "PRE-PUSH BLOCK:" in res_main_del.stderr
    assert "refs/heads/main" in res_main_del.stderr

    # Authorized exact deletion
    governance_preflight.create_remote_deletion_authorization(
        task_id="DELETE-TEST-01",
        exact_ref_sha_map={"refs/heads/batch/to-delete": del_sha},
        git_dir=str(work_dir / ".git")
    )

    # Push deletion with exact authorization -> SUCCEEDS
    res_auth = subprocess.run(["git", "push", "origin", "--delete", "batch/to-delete"], cwd=str(work_dir), capture_output=True, text=True)
    assert res_auth.returncode == 0, f"Authorized delete push failed: {res_auth.stderr}"

    # Verify authorization file was consumed
    auth_file = work_dir / ".git" / "hhai-sensitive-push-auth.json"
    assert not auth_file.exists()
