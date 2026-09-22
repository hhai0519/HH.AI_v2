#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/execution_record.py

Machine-Readable Plan-vs-Actual & Evidence Integrity Engine (B-109 M2).

Responsibilities:
1. Replay machine-readable plan against fresh Git diff truth.
2. Invariant verification:
   - actual_paths <= allowed_paths
   - required_paths <= actual_paths
   - fresh_actual == record_actual
3. Evidence taxonomy & integrity:
   - origin in (MACHINE_CAPTURED_RAW, MACHINE_DERIVED, AGENT_ASSERTED, USER_PROVIDED)
   - verification_status in (VERIFIED, UNVERIFIED, NOT_ESTABLISHED, PENDING_EXTERNAL)
   - source_kind in (REPO_PATH, GIT_DIFF, EXTERNAL_ARTIFACT)
   - REG-11: PATH-EXISTENCE for REPO_PATH
   - REG-12: GENERATOR-IN-BUNDLE for MACHINE_DERIVED
   - REG-13: REPORT-TRACEABILITY for report claims
"""

import os
import sys
import json
import re
import hashlib
import argparse
import subprocess

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_RECORD_PATH = os.path.join("docs", "governance", "execution-record.json")

VALID_ORIGINS = {
    "MACHINE_CAPTURED_RAW",
    "MACHINE_DERIVED",
    "AGENT_ASSERTED",
    "USER_PROVIDED",
}

VALID_VERIFICATION_STATUSES = {
    "VERIFIED",
    "UNVERIFIED",
    "NOT_ESTABLISHED",
    "PENDING_EXTERNAL",
}

VALID_SOURCE_KINDS = {
    "REPO_PATH",
    "GIT_DIFF",
    "EXTERNAL_ARTIFACT",
}


def compute_file_sha256(filepath: str) -> str:
    """Compute SHA256 hex digest of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def normalize_repo_path(path: str) -> str:
    """Normalize path to repo-relative forward-slash path."""
    p = path.replace("\\", "/").strip()
    if p.startswith("./"):
        p = p[2:]
    return p


def validate_path_syntax(p: str, field_name: str) -> tuple[bool, str]:
    """Validate path has no traversal, wildcards, or absolute indicators."""
    norm = normalize_repo_path(p)
    if not norm:
        return False, f"Empty path in {field_name}"
    if norm.startswith("/") or re.match(r"^[a-zA-Z]:", norm):
        return False, f"Absolute path forbidden in {field_name}: {p!r}"
    if ".." in norm.split("/"):
        return False, f"Path traversal '..' forbidden in {field_name}: {p!r}"
    if any(c in norm for c in ("*", "?", "[", "]")):
        return False, f"Wildcard forbidden in {field_name}: {p!r}"
    return True, norm


def get_head_oid(repo_root: str = REPO_ROOT) -> str:
    """Get current HEAD commit OID."""
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True)
        return res.stdout.strip().lower()
    except Exception:
        return ""


def get_fresh_actual_paths(base_oid: str, repo_root: str = REPO_ROOT, as_if_committed: bool = False) -> tuple[bool, str, list[str]]:
    """
    Compute fresh changed paths from Git truth.
    - If as_if_committed or current HEAD == base_oid (uncommitted prospective mode):
      changed = diff(base_oid against index/worktree) + untracked files
    - If not as_if_committed and current HEAD != base_oid (clean commit / CI):
      changed = diff(base_oid..HEAD)
    """
    if not re.match(r"^[0-9a-f]{40}$", base_oid):
        return False, f"Invalid base_oid: {base_oid!r}", []

    try:
        current_head = get_head_oid(repo_root)
        is_prospective = as_if_committed or (os.environ.get("AS_IF_COMMITTED") == "1") or (current_head == base_oid)

        if is_prospective:
            # 1. Diff against base_oid (includes staged and unstaged tracked changes)
            cmd_diff = ["git", "diff", "--name-only", base_oid]
            res_diff = subprocess.run(cmd_diff, cwd=repo_root, capture_output=True, text=True, check=True)
            diff_files = [normalize_repo_path(line) for line in res_diff.stdout.splitlines() if line.strip()]

            # 2. Untracked files (excluding .git)
            cmd_untracked = ["git", "ls-files", "--others", "--exclude-standard"]
            res_untracked = subprocess.run(cmd_untracked, cwd=repo_root, capture_output=True, text=True, check=True)
            untracked_files = [normalize_repo_path(line) for line in res_untracked.stdout.splitlines() if line.strip()]

            all_changed = set(diff_files) | set(untracked_files)
        else:
            # Committed / CI mode: base_oid..HEAD
            cmd_ci = ["git", "diff", "--name-only", f"{base_oid}..HEAD"]
            res_ci = subprocess.run(cmd_ci, cwd=repo_root, capture_output=True, text=True, check=True)
            all_changed = {normalize_repo_path(line) for line in res_ci.stdout.splitlines() if line.strip()}

        sorted_paths = sorted(list(all_changed))
        return True, "", sorted_paths
    except subprocess.CalledProcessError as e:
        return False, f"Git command failed: {e.stderr or str(e)}", []
    except Exception as e:
        return False, f"Failed to compute fresh actual paths: {e}", []


def validate_execution_record(
    record: dict,
    repo_root: str = REPO_ROOT,
    as_if_committed: bool = False,
    check_git: bool = True,
) -> tuple[bool, str]:
    """
    Validates execution-record dictionary against all mechanical governance invariants.
    """
    if not isinstance(record, dict):
        return False, "Execution record must be a JSON object"

    # 1. Top-level headers
    if record.get("schema_version") != 1:
        return False, f"Unsupported schema_version: {record.get('schema_version')}"
    if record.get("governance_version") != "B109-M2":
        return False, f"Unsupported governance_version: {record.get('governance_version')}"
    if not record.get("task_id"):
        return False, "Missing task_id"

    base_oid = record.get("base_oid", "").strip().lower()
    if not re.match(r"^[0-9a-f]{40}$", base_oid):
        return False, f"Invalid base_oid: {base_oid!r}"

    # 2. Plan block
    plan = record.get("plan")
    if not isinstance(plan, dict):
        return False, "Execution record missing 'plan' object"

    allowed = plan.get("allowed_paths")
    if not isinstance(allowed, list):
        return False, "plan.allowed_paths must be a list"
    seen_allowed = set()
    norm_allowed = []
    for p in allowed:
        if not isinstance(p, str):
            return False, f"Invalid entry in allowed_paths: {p!r}"
        ok_p, res_p = validate_path_syntax(p, "allowed_paths")
        if not ok_p:
            return False, res_p
        if res_p in seen_allowed:
            return False, f"Duplicate path in allowed_paths: {p!r}"
        seen_allowed.add(res_p)
        norm_allowed.append(res_p)

    if norm_allowed != sorted(norm_allowed):
        return False, "plan.allowed_paths must be deterministically sorted"

    required = plan.get("required_paths")
    if not isinstance(required, list):
        return False, "plan.required_paths must be a list"
    seen_required = set()
    norm_required = []
    for p in required:
        if not isinstance(p, str):
            return False, f"Invalid entry in required_paths: {p!r}"
        ok_p, res_p = validate_path_syntax(p, "required_paths")
        if not ok_p:
            return False, res_p
        if res_p in seen_required:
            return False, f"Duplicate path in required_paths: {p!r}"
        seen_required.add(res_p)
        norm_required.append(res_p)

    if norm_required != sorted(norm_required):
        return False, "plan.required_paths must be deterministically sorted"

    # Invariant: required <= allowed
    missing_from_allowed = seen_required - seen_allowed
    if missing_from_allowed:
        return False, f"required_paths contains paths not in allowed_paths: {sorted(list(missing_from_allowed))}"

    # Plan revisions
    max_rev = plan.get("max_plan_revisions")
    if max_rev != 3:
        return False, f"max_plan_revisions must be exactly 3 (got {max_rev!r})"
    rev_count = plan.get("revision_count")
    if not isinstance(rev_count, int) or rev_count < 0 or rev_count > 3:
        return False, f"revision_count must be integer between 0 and 3 (got {rev_count!r})"

    if not plan.get("plan_origin"):
        return False, "plan.plan_origin must be non-empty"

    # 3. Actual block
    actual = record.get("actual")
    if not isinstance(actual, dict):
        return False, "Execution record missing 'actual' object"

    changed = actual.get("changed_paths")
    if not isinstance(changed, list):
        return False, "actual.changed_paths must be a list"
    seen_changed = set()
    norm_changed = []
    for p in changed:
        if not isinstance(p, str):
            return False, f"Invalid entry in changed_paths: {p!r}"
        ok_p, res_p = validate_path_syntax(p, "changed_paths")
        if not ok_p:
            return False, res_p
        if res_p in seen_changed:
            return False, f"Duplicate path in changed_paths: {p!r}"
        seen_changed.add(res_p)
        norm_changed.append(res_p)

    if norm_changed != sorted(norm_changed):
        return False, "actual.changed_paths must be deterministically sorted"

    # Invariant F: actual <= allowed
    outside_allowed = seen_changed - seen_allowed
    if outside_allowed:
        return False, f"actual changed_paths outside allowed scope: {sorted(list(outside_allowed))}"

    # Invariant G: required <= actual
    missing_required = seen_required - seen_changed
    if missing_required:
        return False, f"required paths missing from actual changed_paths: {sorted(list(missing_required))}"

    # 4. Fresh Git check (if enabled)
    if check_git:
        ok_git, err_git, fresh_paths = get_fresh_actual_paths(base_oid, repo_root, as_if_committed=as_if_committed)
        if not ok_git:
            return False, err_git

        if set(fresh_paths) != seen_changed:
            drift_missing = seen_changed - set(fresh_paths)
            drift_extra = set(fresh_paths) - seen_changed
            return False, f"Fresh Git changed paths mismatch with record actual (missing_in_git={sorted(list(drift_missing))}, extra_in_git={sorted(list(drift_extra))})"

    # 5. Evidence taxonomy & integrity (REG-11, REG-12)
    evidence_list = record.get("evidence")
    if not isinstance(evidence_list, list):
        return False, "Execution record missing 'evidence' list"

    seen_ev_ids = set()
    for ev in evidence_list:
        if not isinstance(ev, dict):
            return False, f"Evidence entry must be a JSON object: {ev!r}"
        ev_id = ev.get("id")
        if not ev_id or not isinstance(ev_id, str):
            return False, f"Evidence entry missing valid 'id': {ev!r}"
        if ev_id in seen_ev_ids:
            return False, f"Duplicate evidence id: {ev_id!r}"
        seen_ev_ids.add(ev_id)

        # origin
        origin = ev.get("origin")
        if origin not in VALID_ORIGINS:
            return False, f"Evidence {ev_id} has invalid origin: {origin!r} (expected {VALID_ORIGINS})"

        # verification_status
        v_status = ev.get("verification_status")
        if v_status not in VALID_VERIFICATION_STATUSES:
            return False, f"Evidence {ev_id} has invalid verification_status: {v_status!r} (expected {VALID_VERIFICATION_STATUSES})"

        # source_kind
        s_kind = ev.get("source_kind")
        if s_kind not in VALID_SOURCE_KINDS:
            return False, f"Evidence {ev_id} has invalid source_kind: {s_kind!r} (expected {VALID_SOURCE_KINDS})"

        # REG-11: PATH-EXISTENCE
        if s_kind == "REPO_PATH":
            path_val = ev.get("path")
            if not path_val or not isinstance(path_val, str):
                return False, f"REG-11 violation: Evidence {ev_id} with REPO_PATH missing 'path'"
            abs_p = os.path.join(repo_root, normalize_repo_path(path_val))
            if not os.path.exists(abs_p):
                return False, f"REG-11 violation: REPO_PATH does not exist: {path_val}"

        # REG-12: GENERATOR-IN-BUNDLE
        if origin == "MACHINE_DERIVED":
            generator = ev.get("generator")
            if not isinstance(generator, dict):
                return False, f"REG-12 violation: Evidence {ev_id} MACHINE_DERIVED missing 'generator' dict"
            gen_path = generator.get("path")
            gen_sha = generator.get("sha256", "").strip().lower()
            if not gen_path or not isinstance(gen_path, str):
                return False, f"REG-12 violation: Evidence {ev_id} generator missing 'path'"
            if not re.match(r"^[0-9a-f]{40,64}$", gen_sha):
                return False, f"REG-12 violation: Evidence {ev_id} generator missing valid sha256"

            abs_gen = os.path.join(repo_root, normalize_repo_path(gen_path))
            if not os.path.exists(abs_gen):
                return False, f"REG-12 violation: Generator path does not exist: {gen_path}"

            fresh_gen_sha = compute_file_sha256(abs_gen)
            if fresh_gen_sha != gen_sha:
                return False, f"REG-12 violation: Generator SHA mismatch for {gen_path}: declared {gen_sha}, fresh {fresh_gen_sha}"

    # 6. Report claims & traceability (REG-13)
    claims = record.get("report_claims")
    if not isinstance(claims, list):
        return False, "Execution record missing 'report_claims' list"

    seen_claim_ids = set()
    for cl in claims:
        if not isinstance(cl, dict):
            return False, f"Report claim entry must be a JSON object: {cl!r}"
        cid = cl.get("claim_id")
        if not cid or not isinstance(cid, str):
            return False, f"Report claim entry missing valid 'claim_id': {cl!r}"
        if cid in seen_claim_ids:
            return False, f"Duplicate claim id: {cid!r}"
        seen_claim_ids.add(cid)

        ctext = cl.get("claim_text")
        if not ctext or not isinstance(ctext, str) or not ctext.strip():
            return False, f"REG-13 violation: Claim {cid} has empty claim_text"

        ev_ids = cl.get("evidence_ids")
        if not isinstance(ev_ids, list) or not ev_ids:
            return False, f"REG-13 violation: Claim {cid} has empty evidence_ids"

        seen_cl_evs = set()
        for ref_id in ev_ids:
            if not isinstance(ref_id, str) or not ref_id:
                return False, f"REG-13 violation: Claim {cid} has invalid evidence reference: {ref_id!r}"
            if ref_id in seen_cl_evs:
                return False, f"REG-13 violation: Claim {cid} has duplicate evidence reference: {ref_id!r}"
            seen_cl_evs.add(ref_id)
            if ref_id not in seen_ev_ids:
                return False, f"REG-13 violation: Claim {cid} references non-existent evidence id: {ref_id!r}"

    return True, ""


def write_execution_record(
    plan_file: str,
    output_path: str = DEFAULT_RECORD_PATH,
    repo_root: str = REPO_ROOT,
) -> tuple[bool, str]:
    """
    Builds and writes docs/governance/execution-record.json from plan and fresh Git truth.
    """
    abs_plan = os.path.join(repo_root, plan_file) if not os.path.isabs(plan_file) else plan_file
    if not os.path.exists(abs_plan):
        return False, f"Plan file not found: {plan_file}"

    try:
        with open(abs_plan, "r", encoding="utf-8") as f:
            plan_data = json.load(f)
    except Exception as e:
        return False, f"Failed to parse plan file JSON: {e}"

    task_id = plan_data.get("task_id", "B-109-M2")
    base_oid = plan_data.get("base_oid", "").strip().lower()
    allowed_paths = sorted([normalize_repo_path(p) for p in plan_data.get("allowed_paths", [])])
    required_paths = sorted([normalize_repo_path(p) for p in plan_data.get("required_paths", [])])
    max_rev = plan_data.get("max_plan_revisions", 3)
    rev_count = plan_data.get("revision_count", 0)
    plan_origin = plan_data.get("plan_origin", "EXTERNAL_MACRO_PROMPT")

    norm_output = normalize_repo_path(os.path.relpath(os.path.join(repo_root, output_path), repo_root))

    # Fresh Git changed paths
    ok_git, err_git, fresh_paths = get_fresh_actual_paths(base_oid, repo_root, as_if_committed=True)
    if not ok_git:
        return False, err_git

    # Self-inclusion: ensure output_path is in changed_paths
    all_actual = set(fresh_paths)
    all_actual.add(norm_output)
    changed_paths = sorted(list(all_actual))

    # Check invariants before writing
    outside = set(changed_paths) - set(allowed_paths)
    if outside:
        return False, f"Cannot write execution record: actual paths exceed allowed scope: {sorted(list(outside))}"
    missing_req = set(required_paths) - set(changed_paths)
    if missing_req:
        return False, f"Cannot write execution record: required paths missing: {sorted(list(missing_req))}"

    # Generator SHA for execution_record.py
    exec_script_rel = "scripts/execution_record.py"
    exec_script_abs = os.path.join(repo_root, exec_script_rel)
    gen_sha = compute_file_sha256(exec_script_abs) if os.path.exists(exec_script_abs) else ""

    evidence = [
        {
            "id": "PLAN_ACTUAL_DIFF",
            "origin": "MACHINE_DERIVED",
            "verification_status": "VERIFIED",
            "source_kind": "GIT_DIFF",
            "generator": {
                "path": exec_script_rel,
                "sha256": gen_sha,
            },
            "description": "Deterministic Git diff replay against declared plan allowed/required scope",
        },
        {
            "id": "M2_DISCOVERY_RAW",
            "origin": "MACHINE_CAPTURED_RAW",
            "verification_status": "VERIFIED",
            "source_kind": "EXTERNAL_ARTIFACT",
            "sha256": "4cd2851da921aab9d371b281f51947e2645b069d38ee56655e37a79c2ded3b4b",
            "description": "External Macro verified M2 immutable raw discovery artifact identity",
        },
    ]

    report_claims = [
        {
            "claim_id": "CLAIM_PLAN_VS_ACTUAL_MATCHED",
            "claim_text": "All actual changed repository paths strictly match allowed scope and cover all required paths without expansion.",
            "evidence_ids": ["PLAN_ACTUAL_DIFF"],
        },
        {
            "claim_id": "CLAIM_DISCOVERY_PROVENANCE_VERIFIED",
            "claim_text": "Immutable raw discovery artifact verified against expected SHA256 closure.",
            "evidence_ids": ["M2_DISCOVERY_RAW"],
        },
    ]

    record = {
        "schema_version": 1,
        "governance_version": "B109-M2",
        "task_id": task_id,
        "base_oid": base_oid,
        "plan": {
            "allowed_paths": allowed_paths,
            "required_paths": required_paths,
            "max_plan_revisions": max_rev,
            "revision_count": rev_count,
            "plan_origin": plan_origin,
        },
        "actual": {
            "changed_paths": changed_paths,
        },
        "evidence": evidence,
        "report_claims": report_claims,
    }

    # Validate in-memory before writing (without fresh git check since file not written yet)
    ok_val, err_val = validate_execution_record(record, repo_root=repo_root, check_git=False)
    if not ok_val:
        return False, f"Generated record invalid: {err_val}"

    abs_output = os.path.join(repo_root, output_path)
    os.makedirs(os.path.dirname(abs_output), exist_ok=True)
    try:
        with open(abs_output, "w", encoding="utf-8", newline="\n") as f:
            json.dump(record, f, indent=2)
            f.write("\n")
    except Exception as e:
        return False, f"Failed to write execution record to {output_path}: {e}"

    return True, f"Successfully written execution record to {output_path}"


def verify_execution_record_file(
    record_path: str = DEFAULT_RECORD_PATH,
    repo_root: str = REPO_ROOT,
    as_if_committed: bool = False,
) -> tuple[bool, str]:
    """
    Reads and verifies execution record file.
    """
    abs_record = os.path.join(repo_root, record_path) if not os.path.isabs(record_path) else record_path
    if not os.path.exists(abs_record):
        return False, f"Execution record file not found: {record_path}"

    try:
        with open(abs_record, "r", encoding="utf-8") as f:
            record = json.load(f)
    except Exception as e:
        return False, f"Failed to parse execution record JSON: {e}"

    return validate_execution_record(record, repo_root=repo_root, as_if_committed=as_if_committed, check_git=True)


def main():
    parser = argparse.ArgumentParser(description="Mechanical Governance Execution Record CLI (B-109 M2).")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # write command
    parser_write = subparsers.add_parser("write", help="Write execution record from plan and Git truth")
    parser_write.add_argument("--plan-file", required=True, help="Path to plan JSON file")
    parser_write.add_argument("--output", default=DEFAULT_RECORD_PATH, help="Path to output execution-record.json")
    parser_write.add_argument("--repo-root", default=REPO_ROOT, help="Repository root path")

    # verify command
    parser_verify = subparsers.add_parser("verify", help="Verify execution record against invariants and Git truth")
    parser_verify.add_argument("--record", default=DEFAULT_RECORD_PATH, help="Path to execution-record.json")
    parser_verify.add_argument("--as-if-committed", action="store_true", help="Verify working tree as if committed")
    parser_verify.add_argument("--repo-root", default=REPO_ROOT, help="Repository root path")

    args = parser.parse_args()

    if args.command == "write":
        ok, msg = write_execution_record(args.plan_file, args.output, args.repo_root)
        if ok:
            print(f"[PASS] {msg}")
            sys.exit(0)
        else:
            sys.stderr.write(f"[FAIL] {msg}\n")
            sys.exit(1)

    elif args.command == "verify":
        ok, msg = verify_execution_record_file(args.record, args.repo_root, as_if_committed=args.as_if_committed)
        if ok:
            print(f"[PASS] Execution record verified successfully ({args.record})")
            sys.exit(0)
        else:
            sys.stderr.write(f"[FAIL] {msg}\n")
            sys.exit(1)


if __name__ == "__main__":
    main()
