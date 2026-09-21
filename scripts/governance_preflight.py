#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/governance_preflight.py

Mechanical Governance Preflight & Sensitive Push Guard (B-109 M1).

Responsibilities:
1. Validate incoming prompt against minimal Rule Registry (GOV-M1-001..013).
2. Fail-closed: Output per-rule '<GOV-ID> PASS | <reason>' or '<GOV-ID> FAIL | <reason>'.
3. Manage transient single-use sensitive push authorization (.git/hhai-sensitive-push-auth.json).
4. Verify Git pre-push updates (ordinary push pass, main advancement exact SHA, remote deletion exact set).
5. Single-use consumption of sensitive authorization before actual push release.
"""

import os
import sys
import json
import re
import argparse
from datetime import datetime, timezone

# Import shared execution contract parser
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from scripts.validate_prompt_manifest import (
    validate_prompt_manifest,
    validate_execution_contract,
    parse_execution_contract_block,
    CONTRACT_BEGIN_MARKER,
    CONTRACT_END_MARKER,
)

AUTH_FILE_NAME = "hhai-sensitive-push-auth.json"
RULE_REGISTRY_PATH = os.path.join("docs", "governance", "rule-registry.json")


def get_auth_file_path(root_dir: str) -> str:
    norm = os.path.normpath(root_dir)
    if os.path.basename(norm) == ".git":
        return os.path.join(norm, AUTH_FILE_NAME)
    return os.path.join(norm, ".git", AUTH_FILE_NAME)


def load_rule_registry(root_dir: str) -> tuple[bool, str, list[dict]]:
    reg_path = os.path.join(root_dir, RULE_REGISTRY_PATH)
    if not os.path.exists(reg_path):
        return False, f"Rule registry file not found: {reg_path}", []
    try:
        with open(reg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return False, f"Failed to parse rule registry JSON: {e}", []

    if not isinstance(data, dict):
        return False, "Rule registry root must be a JSON object", []
    if data.get("schema_version") != 1:
        return False, f"Unsupported rule registry schema_version: {data.get('schema_version')}", []

    rules = data.get("rules")
    if not isinstance(rules, list):
        return False, "Rule registry must contain a 'rules' array", []

    seen_ids = set()
    rule_ids = []
    for r in rules:
        if not isinstance(r, dict):
            return False, f"Rule item must be a JSON object: {r}", []
        rid = r.get("id")
        if not rid or not isinstance(rid, str):
            return False, f"Rule item missing valid 'id': {r}", []
        if rid in seen_ids:
            return False, f"Duplicate rule ID in registry: {rid}", []
        seen_ids.add(rid)
        rule_ids.append(rid)

    # Deterministically sorted
    if rule_ids != sorted(rule_ids):
        return False, "Rule registry rules must be deterministically sorted by Rule ID", []

    expected_ids = [f"GOV-M1-{i:03d}" for i in range(1, 14)]
    if rule_ids != expected_ids:
        missing = set(expected_ids) - seen_ids
        extra = seen_ids - set(expected_ids)
        return False, f"Rule registry ID mismatch (missing={sorted(list(missing))}, extra={sorted(list(extra))})", []

    return True, "", rules


def check_governance_rules(prompt_text: str, root_dir: str) -> tuple[bool, list[str]]:
    """
    Evaluates prompt against GOV-M1-001..013.
    Returns (all_passed, list_of_status_lines).
    """
    ok_reg, err_reg, rules = load_rule_registry(root_dir)
    if not ok_reg:
        return False, [f"REGISTRY FAIL | {err_reg}"]

    results = []
    overall_pass = True

    # 1. Manifest validation
    manifest_ok, manifest_err, manifest = validate_prompt_manifest(prompt_text)

    # 2. Execution Contract validation
    contract_ok, contract_err, contract = validate_execution_contract(prompt_text, manifest if manifest_ok else None)

    for r in rules:
        rid = r["id"]

        if rid == "GOV-M1-001":
            # EXECUTION_CONTRACT_REQUIRED
            if contract_ok:
                results.append(f"{rid} PASS | Execution contract valid (task={contract.get('task_id')})")
            else:
                overall_pass = False
                results.append(f"{rid} FAIL | {contract_err}")

        elif rid == "GOV-M1-002":
            # MAIN_ADVANCEMENT_EXACT_SHA
            if not contract_ok:
                overall_pass = False
                results.append(f"{rid} FAIL | Contract invalid")
            else:
                ma = contract.get("main_advancement")
                sha = contract.get("authorized_main_sha")
                if ma == "FORBIDDEN" and sha == "NONE":
                    results.append(f"{rid} PASS | Main advancement forbidden in contract")
                elif ma == "EXACT_SHA" and re.match(r"^[0-9a-f]{40}$", sha or ""):
                    results.append(f"{rid} PASS | Main advancement exact SHA authorized ({sha[:7]})")
                else:
                    overall_pass = False
                    results.append(f"{rid} FAIL | Invalid main advancement policy ({ma}, {sha})")

        elif rid == "GOV-M1-003":
            # REMOTE_REF_DELETE_EXACT_SET
            if not contract_ok:
                overall_pass = False
                results.append(f"{rid} FAIL | Contract invalid")
            else:
                rd = contract.get("remote_ref_deletion")
                del_refs = contract.get("authorized_delete_refs")
                if rd == "FORBIDDEN" and del_refs == "NONE":
                    results.append(f"{rid} PASS | Remote ref deletion forbidden in contract")
                elif rd == "EXACT_SET" and del_refs and del_refs != "NONE":
                    results.append(f"{rid} PASS | Remote ref deletion exact set authorized")
                else:
                    overall_pass = False
                    results.append(f"{rid} FAIL | Invalid remote ref deletion policy ({rd}, {del_refs})")

        elif rid == "GOV-M1-004":
            # LOCAL_DESTRUCTIVE_GIT_FORBIDDEN
            if contract_ok and contract.get("local_destructive_git") == "FORBIDDEN":
                results.append(f"{rid} PASS | Local destructive Git forbidden in contract (defense-in-depth: IDE harness persistent Deny)")
            else:
                overall_pass = False
                val = contract.get("local_destructive_git") if contract_ok else "MISSING"
                results.append(f"{rid} FAIL | local_destructive_git is {val} (expected FORBIDDEN)")

        elif rid == "GOV-M1-005":
            # CREDENTIAL_ACCESS_FORBIDDEN
            if contract_ok and contract.get("credential_access") == "FORBIDDEN":
                results.append(f"{rid} PASS | Credential access forbidden in contract (defense-in-depth: IDE harness persistent Deny on git credential)")
            else:
                overall_pass = False
                val = contract.get("credential_access") if contract_ok else "MISSING"
                results.append(f"{rid} FAIL | credential_access is {val} (expected FORBIDDEN)")

        elif rid == "GOV-M1-006":
            # ENVIRONMENT_ENUMERATION_FORBIDDEN
            if contract_ok and contract.get("environment_enumeration") == "FORBIDDEN":
                results.append(f"{rid} PASS | Environment enumeration forbidden in contract")
            else:
                overall_pass = False
                val = contract.get("environment_enumeration") if contract_ok else "MISSING"
                results.append(f"{rid} FAIL | environment_enumeration is {val} (expected FORBIDDEN)")

        elif rid == "GOV-M1-007":
            # CROSS_SESSION_ACCESS_FORBIDDEN
            if contract_ok and contract.get("cross_session_access") == "FORBIDDEN":
                results.append(f"{rid} PASS | Cross-session access forbidden in contract")
            else:
                overall_pass = False
                val = contract.get("cross_session_access") if contract_ok else "MISSING"
                results.append(f"{rid} FAIL | cross_session_access is {val} (expected FORBIDDEN)")

        elif rid == "GOV-M1-008":
            # RAW_ACTIONS_LOG_EXTERNAL_MACRO_ONLY
            if contract_ok and contract.get("raw_actions_log_access") == "EXTERNAL_MACRO_ONLY":
                results.append(f"{rid} PASS | Raw Actions log access reserved for External Macro only")
            else:
                overall_pass = False
                val = contract.get("raw_actions_log_access") if contract_ok else "MISSING"
                results.append(f"{rid} FAIL | raw_actions_log_access is {val} (expected EXTERNAL_MACRO_ONLY)")

        elif rid == "GOV-M1-009":
            # BROWSER_GITHUB_MUTATION_FORBIDDEN
            if contract_ok and contract.get("browser_github_mutation") == "FORBIDDEN":
                results.append(f"{rid} PASS | Browser GitHub mutation forbidden in contract (defense-in-depth: github.com Execute Deny)")
            else:
                overall_pass = False
                val = contract.get("browser_github_mutation") if contract_ok else "MISSING"
                results.append(f"{rid} FAIL | browser_github_mutation is {val} (expected FORBIDDEN)")

        elif rid == "GOV-M1-010":
            # GOAL_PRESSURE_SAFETY_BOUNDARY_WINS
            if contract_ok and contract.get("goal_pressure_policy") == "SAFETY_BOUNDARY_WINS":
                results.append(f"{rid} PASS | Goal pressure policy enforces SAFETY_BOUNDARY_WINS")
            else:
                overall_pass = False
                val = contract.get("goal_pressure_policy") if contract_ok else "MISSING"
                results.append(f"{rid} FAIL | goal_pressure_policy is {val} (expected SAFETY_BOUNDARY_WINS)")

        elif rid == "GOV-M1-011":
            # PRE_PUSH_HOOK_BYPASS_FORBIDDEN
            if contract_ok and contract.get("hook_bypass") == "FORBIDDEN":
                results.append(f"{rid} PASS | Hook bypass forbidden in contract and active rules")
            else:
                overall_pass = False
                val = contract.get("hook_bypass") if contract_ok else "MISSING"
                results.append(f"{rid} FAIL | hook_bypass is {val} (expected FORBIDDEN)")

        elif rid == "GOV-M1-012":
            # BRANCH_CREATION_GIT_SWITCH_C
            if contract_ok and contract.get("branch_creation") == "GIT_SWITCH_C":
                results.append(f"{rid} PASS | Branch creation convention enforces git switch -c")
            else:
                overall_pass = False
                val = contract.get("branch_creation") if contract_ok else "MISSING"
                results.append(f"{rid} FAIL | branch_creation is {val} (expected GIT_SWITCH_C)")

        elif rid == "GOV-M1-013":
            # K6_PERSISTENCE_TIER_TRUTH
            if contract_ok and contract.get("ide_ephemeral_guards_required") == "false":
                results.append(f"{rid} PASS | K6 persistence tier truth established (no reliance on ephemeral Deny List)")
            else:
                overall_pass = False
                val = contract.get("ide_ephemeral_guards_required") if contract_ok else "MISSING"
                results.append(f"{rid} FAIL | ide_ephemeral_guards_required is {val} (expected false)")

    return overall_pass, results


def create_main_advancement_auth(root_dir: str, task_id: str, authorized_main_sha: str, expected_remote_main_sha: str) -> tuple[bool, str]:
    """
    Creates single-use MAIN_EXACT_SHA authorization in .git/.
    Fail-closed: cannot overwrite unconsumed authorization.
    """
    auth_path = get_auth_file_path(root_dir)
    if os.path.exists(auth_path):
        return False, "Cannot overwrite unconsumed sensitive push authorization"

    if not re.match(r"^[0-9a-f]{40}$", authorized_main_sha.lower()):
        return False, f"Invalid authorized_main_sha: {authorized_main_sha}"
    if not re.match(r"^[0-9a-f]{40}$", expected_remote_main_sha.lower()):
        return False, f"Invalid expected_remote_main_sha: {expected_remote_main_sha}"

    auth_data = {
        "schema_version": 1,
        "mode": "MAIN_EXACT_SHA",
        "task_id": task_id,
        "authorized_main_sha": authorized_main_sha.lower(),
        "expected_remote_main_sha": expected_remote_main_sha.lower(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provenance_note": "Provenance is external / audit-dependent; repository does not cryptographically prove Macro origin."
    }

    try:
        with open(auth_path, "w", encoding="utf-8") as f:
            json.dump(auth_data, f, indent=2)
    except Exception as e:
        return False, f"Failed to write sensitive push authorization: {e}"

    return True, f"Created single-use MAIN_EXACT_SHA authorization for {authorized_main_sha[:7]}"


def create_remote_delete_auth(root_dir: str, task_id: str, delete_mapping: dict[str, str]) -> tuple[bool, str]:
    """
    Creates single-use REMOTE_DELETE_EXACT_SET authorization in .git/.
    Fail-closed: cannot overwrite unconsumed authorization.
    delete_mapping: dict of refs/heads/<branch> -> expected_current_sha (40 hex)
    """
    auth_path = get_auth_file_path(root_dir)
    if os.path.exists(auth_path):
        return False, "Cannot overwrite unconsumed sensitive push authorization"

    if not delete_mapping:
        return False, "Delete mapping cannot be empty"

    normalized_mapping = {}
    for ref_name, sha in delete_mapping.items():
        ref_clean = ref_name.strip()
        sha_clean = sha.strip().lower()
        if not ref_clean.startswith("refs/heads/") or len(ref_clean) <= len("refs/heads/"):
            return False, f"Malformed ref name: {ref_name}"
        if ref_clean == "refs/heads/main":
            return False, "refs/heads/main is permanently forbidden from deletion authorization"
        if not re.match(r"^[0-9a-f]{40}$", sha_clean):
            return False, f"Malformed expected SHA for {ref_name}: {sha}"
        normalized_mapping[ref_clean] = sha_clean

    auth_data = {
        "schema_version": 1,
        "mode": "REMOTE_DELETE_EXACT_SET",
        "task_id": task_id,
        "expected_deletions": normalized_mapping,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provenance_note": "Provenance is external / audit-dependent; repository does not cryptographically prove Macro origin."
    }

    try:
        with open(auth_path, "w", encoding="utf-8") as f:
            json.dump(auth_data, f, indent=2)
    except Exception as e:
        return False, f"Failed to write sensitive push authorization: {e}"

    return True, f"Created single-use REMOTE_DELETE_EXACT_SET authorization ({len(normalized_mapping)} refs)"


def verify_and_consume_push(root_dir: str, remote_name: str, remote_url: str, stdin_lines: list[str]) -> tuple[bool, str]:
    """
    Called by pre-push hook:
    stdin_lines: lines of '<local_ref> <local_sha> <remote_ref> <remote_sha>'
    """
    updates = []
    for raw in stdin_lines:
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 4:
            return False, f"PRE-PUSH BLOCK: Malformed pre-push line: {line!r}"
        l_ref, l_sha, r_ref, r_sha = parts
        updates.append({
            "local_ref": l_ref,
            "local_sha": l_sha.lower(),
            "remote_ref": r_ref,
            "remote_sha": r_sha.lower()
        })

    if not updates:
        # Zero updates, allow git to proceed
        return True, "PRE-PUSH PASS: No ref updates provided"

    # Identify operations
    main_updates = []
    remote_deletions = []
    ordinary_updates = []

    for up in updates:
        r_ref = up["remote_ref"]
        l_ref = up["local_ref"]
        l_sha = up["local_sha"]
        is_delete = (l_ref == "(delete)" or l_sha == "0" * 40 or not l_sha)

        if r_ref == "refs/heads/main":
            if is_delete:
                return False, "PRE-PUSH BLOCK: Remote deletion of refs/heads/main is permanently forbidden."
            main_updates.append(up)
        elif is_delete:
            remote_deletions.append(up)
        else:
            ordinary_updates.append(up)

    # 1. Ordinary push: no main update and no remote deletion
    if not main_updates and not remote_deletions:
        return True, "PRE-PUSH PASS: Ordinary batch push allowed without sensitive authorization."

    # 2. Mixed sensitive operations: main update + remote deletion in same push
    if main_updates and remote_deletions:
        return False, "PRE-PUSH BLOCK: Cannot combine main advancement and remote deletion in a single push."

    # 3. Cannot mix sensitive operation with other ordinary branches
    if main_updates and ordinary_updates:
        return False, "PRE-PUSH BLOCK: Cannot mix main advancement with other branch updates in a single push."
    if remote_deletions and ordinary_updates:
        return False, "PRE-PUSH BLOCK: Cannot mix remote branch deletion with branch updates in a single push."

    auth_path = get_auth_file_path(root_dir)
    if not os.path.exists(auth_path):
        if main_updates:
            return False, "PRE-PUSH BLOCK: Unauthorized main advancement. Missing single-use authorization (.git/hhai-sensitive-push-auth.json)."
        else:
            return False, "PRE-PUSH BLOCK: Unauthorized remote ref deletion. Missing single-use authorization (.git/hhai-sensitive-push-auth.json)."

    try:
        with open(auth_path, "r", encoding="utf-8") as f:
            auth = json.load(f)
    except Exception as e:
        return False, f"PRE-PUSH BLOCK: Failed to parse sensitive push authorization: {e}"

    # Handle Main advancement
    if main_updates:
        if auth.get("mode") != "MAIN_EXACT_SHA":
            return False, f"PRE-PUSH BLOCK: Main advancement requires MAIN_EXACT_SHA authorization (got {auth.get('mode')})"

        if len(main_updates) != 1:
            return False, f"PRE-PUSH BLOCK: Expected exactly one main update entry (got {len(main_updates)})"

        mu = main_updates[0]
        auth_sha = auth.get("authorized_main_sha", "").lower()
        expected_remote_sha = auth.get("expected_remote_main_sha", "").lower()

        if mu["local_sha"] != auth_sha:
            return False, f"PRE-PUSH BLOCK: Main advancement new SHA mismatch: push target has {mu['local_sha']}, authorized {auth_sha}"

        if mu["remote_sha"] != expected_remote_sha:
            return False, f"PRE-PUSH BLOCK: Remote main SHA drift: current remote has {mu['remote_sha']}, expected {expected_remote_sha}"

        # Consumed immediately
        try:
            os.remove(auth_path)
        except Exception as e:
            return False, f"PRE-PUSH BLOCK: Failed to consume authorization: {e}"

        return True, "PRE-PUSH PASS: Main advancement exact SHA verified and authorization consumed."

    # Handle Remote deletion
    if remote_deletions:
        if auth.get("mode") != "REMOTE_DELETE_EXACT_SET":
            return False, f"PRE-PUSH BLOCK: Remote deletion requires REMOTE_DELETE_EXACT_SET authorization (got {auth.get('mode')})"

        expected_map = {k: v.lower() for k, v in auth.get("expected_deletions", {}).items()}
        actual_map = {d["remote_ref"]: d["remote_sha"].lower() for d in remote_deletions}

        if set(actual_map.keys()) != set(expected_map.keys()):
            missing = set(expected_map.keys()) - set(actual_map.keys())
            extra = set(actual_map.keys()) - set(expected_map.keys())
            return False, f"PRE-PUSH BLOCK: Remote deletion ref set mismatch (missing={sorted(list(missing))}, extra={sorted(list(extra))})"

        for ref, cur_sha in actual_map.items():
            exp_sha = expected_map[ref]
            if cur_sha != exp_sha:
                return False, f"PRE-PUSH BLOCK: Remote SHA drift for {ref}: remote has {cur_sha}, expected {exp_sha}"

        # Consumed immediately
        try:
            os.remove(auth_path)
        except Exception as e:
            return False, f"PRE-PUSH BLOCK: Failed to consume authorization: {e}"

        return True, f"PRE-PUSH PASS: Remote deletion exact set verified ({len(actual_map)} refs) and authorization consumed."

    return False, "PRE-PUSH BLOCK: Unhandled push state."


def create_main_advancement_authorization(
    task_id: str,
    authorized_main_sha: str,
    expected_remote_main_sha: str,
    git_dir: str | None = None,
    root_dir: str | None = None,
) -> str:
    target = git_dir or root_dir or repo_root
    ok, msg = create_main_advancement_auth(target, task_id, authorized_main_sha, expected_remote_main_sha)
    if not ok:
        raise RuntimeError(msg)
    return get_auth_file_path(target)


def create_remote_deletion_authorization(
    task_id: str,
    exact_ref_sha_map: dict[str, str],
    git_dir: str | None = None,
    root_dir: str | None = None,
) -> str:
    target = git_dir or root_dir or repo_root
    ok, msg = create_remote_delete_auth(target, task_id, exact_ref_sha_map)
    if not ok:
        raise RuntimeError(msg)
    return get_auth_file_path(target)


def verify_and_consume_main_advancement(
    new_sha: str,
    remote_sha: str,
    git_dir: str | None = None,
    root_dir: str | None = None,
) -> bool:
    target = git_dir or root_dir or repo_root
    stdin_line = f"refs/heads/main {new_sha} refs/heads/main {remote_sha}"
    ok, _ = verify_and_consume_push(target, "origin", "url", [stdin_line])
    return ok


def verify_and_consume_remote_deletion(
    actual_deletions: dict[str, str],
    git_dir: str | None = None,
    root_dir: str | None = None,
) -> bool:
    target = git_dir or root_dir or repo_root
    stdin_lines = [
        f"(delete) {'0'*40} {ref} {sha}"
        for ref, sha in actual_deletions.items()
    ]
    ok, _ = verify_and_consume_push(target, "origin", "url", stdin_lines)
    return ok


def evaluate_contract_rules(
    contract_or_text: str | dict,
    base_oid: str | None = None,
    repo_root: str | None = None,
) -> int:
    target_root = repo_root or globals().get("repo_root", ".")
    if isinstance(contract_or_text, dict):
        contract_dict = contract_or_text
        lines = [CONTRACT_BEGIN_MARKER]
        for k, v in contract_dict.items():
            lines.append(f"{k}: {v}")
        lines.append(CONTRACT_END_MARKER)
        prompt_text = "\n".join(lines)
    else:
        prompt_text = contract_or_text

    overall_pass, results = check_governance_rules(prompt_text, target_root)
    for line in results:
        print(line)
    return 0 if overall_pass else 1


def main():
    parser = argparse.ArgumentParser(description="HH.AI Governance Preflight & Push Guard.")
    parser.add_argument("--prompt-file", help="Path to prompt file (or '-' for stdin)")
    parser.add_argument("--verify-push", nargs=2, metavar=("REMOTE_NAME", "REMOTE_URL"), help="Verify git push updates from stdin")
    parser.add_argument("--create-main-auth", nargs=3, metavar=("TASK_ID", "AUTH_SHA", "REMOTE_SHA"), help="Create single-use MAIN_EXACT_SHA authorization")
    parser.add_argument("--create-delete-auth", nargs=2, metavar=("TASK_ID", "REF_SHA_MAP"), help="Create single-use REMOTE_DELETE_EXACT_SET authorization (format 'ref1@sha1;ref2@sha2')")
    parser.add_argument("--repo-root", default=repo_root, help="Repository root path")

    args = parser.parse_args()

    # 1. Pre-push hook verification mode
    if args.verify_push:
        remote_name, remote_url = args.verify_push
        stdin_lines = sys.stdin.readlines()
        ok, msg = verify_and_consume_push(args.repo_root, remote_name, remote_url, stdin_lines)
        if ok:
            print(msg)
            sys.exit(0)
        else:
            sys.stderr.write(f"{msg}\n")
            sys.exit(1)

    # 2. Auth creation mode: main
    if args.create_main_auth:
        task_id, auth_sha, remote_sha = args.create_main_auth
        ok, msg = create_main_advancement_auth(args.repo_root, task_id, auth_sha, remote_sha)
        if ok:
            print(f"[PASS] {msg}")
            sys.exit(0)
        else:
            sys.stderr.write(f"[FAIL] {msg}\n")
            sys.exit(1)

    # 3. Auth creation mode: delete
    if args.create_delete_auth:
        task_id, raw_map = args.create_delete_auth
        mapping = {}
        for entry in raw_map.split(";"):
            if not entry.strip():
                continue
            if "@" not in entry:
                sys.stderr.write(f"[FAIL] Malformed delete entry: {entry}\n")
                sys.exit(1)
            ref, sha = entry.split("@", 1)
            mapping[ref.strip()] = sha.strip()
        ok, msg = create_remote_delete_auth(args.repo_root, task_id, mapping)
        if ok:
            print(f"[PASS] {msg}")
            sys.exit(0)
        else:
            sys.stderr.write(f"[FAIL] {msg}\n")
            sys.exit(1)

    # 4. Default: Governance preflight evaluation on incoming prompt
    if args.prompt_file and args.prompt_file != "-":
        if not os.path.exists(args.prompt_file):
            sys.stderr.write(f"[FAIL] Prompt file not found: {args.prompt_file}\n")
            sys.exit(1)
        with open(args.prompt_file, "r", encoding="utf-8") as f:
            prompt_text = f.read()
    else:
        if sys.stdin.isatty() and not (args.prompt_file == "-"):
            sys.stderr.write("[FAIL] No prompt provided via --prompt-file or stdin\n")
            sys.exit(1)
        prompt_text = sys.stdin.read()

    overall_pass, results = check_governance_rules(prompt_text, args.repo_root)
    for line in results:
        if "FAIL" in line:
            sys.stderr.write(f"{line}\n")
        else:
            print(line)

    if overall_pass:
        print("[GOVERNANCE PREFLIGHT PASS] All 13 governance rules verified.")
        sys.exit(0)
    else:
        sys.stderr.write("[GOVERNANCE PREFLIGHT FAIL] Governance rules violation detected.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
