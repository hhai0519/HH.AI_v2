#!/usr/bin/env python3
"""
scripts/validate_prompt_manifest.py

用途：
  驗證 HH.AI 生產與狀態同步提示詞中的 Machine-Readable Prompt Manifest。
  作為 Executor 端最前置的確定性結構檢驗器（Hard Rule）。

支援模式：
  python scripts/validate_prompt_manifest.py --file <path>
  cat <path> | python scripts/validate_prompt_manifest.py
"""

import sys
import os
import re
import argparse

REQUIRED_KEYS = [
    "schema_version",
    "batch_mode",
    "base_oid",
    "finding_disposition",
    "backlog_disposition",
    "taskboard_disposition",
    "audit_log_disposition",
    "rules_reread_required",
    "fixed_signature_required",
    "destructive_git_allowed",
]

BEGIN_MARKER = "BEGIN_HHAI_PROMPT_MANIFEST"
END_MARKER = "END_HHAI_PROMPT_MANIFEST"

CONTRACT_BEGIN_MARKER = "BEGIN_HHAI_EXECUTION_CONTRACT"
CONTRACT_END_MARKER = "END_HHAI_EXECUTION_CONTRACT"

CONTRACT_REQUIRED_KEYS_V1 = [
    "contract_version",
    "task_id",
    "base_oid",
    "main_advancement",
    "authorized_main_sha",
    "remote_ref_deletion",
    "authorized_delete_refs",
    "local_destructive_git",
    "credential_access",
    "environment_enumeration",
    "cross_session_access",
    "browser_github_mutation",
    "raw_actions_log_access",
    "branch_creation",
    "hook_bypass",
    "goal_pressure_policy",
    "ide_ephemeral_guards_required",
]

CONTRACT_V2_EXTRA_KEYS = [
    "allowed_mutation_paths",
    "required_mutation_paths",
    "max_plan_revisions",
    "execution_record_required",
]

CONTRACT_REQUIRED_KEYS_V2 = CONTRACT_REQUIRED_KEYS_V1 + CONTRACT_V2_EXTRA_KEYS
CONTRACT_REQUIRED_KEYS = CONTRACT_REQUIRED_KEYS_V1


def parse_execution_contract_block(prompt_text: str) -> tuple[bool, str, dict]:
    """
    從 prompt_text 中抽取出唯一的 execution contract 區塊並解析為 key-value dict。
    fail-closed：缺失、重複、順序錯誤、格式錯誤、未知欄位皆立即回傳失敗。
    支援 contract_version = 1 與 contract_version = 2。
    """
    begin_count = prompt_text.count(CONTRACT_BEGIN_MARKER)
    end_count = prompt_text.count(CONTRACT_END_MARKER)

    if begin_count == 0 or end_count == 0:
        return False, "Execution contract missing BEGIN or END marker", {}

    if begin_count > 1 or end_count > 1:
        return False, f"Duplicate contract markers found (BEGIN={begin_count}, END={end_count})", {}

    begin_idx = prompt_text.find(CONTRACT_BEGIN_MARKER)
    end_idx = prompt_text.find(CONTRACT_END_MARKER)

    if begin_idx >= end_idx:
        return False, "Contract marker ordering error: END appears before BEGIN", {}

    block_text = prompt_text[begin_idx + len(CONTRACT_BEGIN_MARKER):end_idx]
    lines = block_text.splitlines()

    raw_pairs = []
    seen_keys = set()
    contract_version = "1"

    for line_no, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line:
            continue
        if ":" not in line:
            return False, f"Contract line {line_no} malformed (missing colon): {raw_line!r}", {}
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()

        if key in seen_keys:
            return False, f"Duplicate key in contract: {key!r}", {}
        seen_keys.add(key)
        raw_pairs.append((key, val))
        if key == "contract_version":
            contract_version = val

    if contract_version == "2":
        expected_keys = CONTRACT_REQUIRED_KEYS_V2
    else:
        expected_keys = CONTRACT_REQUIRED_KEYS_V1

    contract = {}
    for key, val in raw_pairs:
        if key not in expected_keys:
            return False, f"Unexpected/unsupported key in contract (version {contract_version}): {key!r}", {}
        contract[key] = val

    missing_keys = set(expected_keys) - seen_keys
    if missing_keys:
        return False, f"Missing required contract keys (version {contract_version}): {sorted(list(missing_keys))}", {}

    return True, "", contract


def validate_execution_contract(
    prompt_text_or_contract: str | dict,
    manifest: dict | None = None,
    manifest_base_oid: str | None = None,
) -> tuple[bool, str, dict]:
    """
    驗證 Execution Contract：
    1. 唯一合法 contract 區塊且無缺漏或多餘欄位
    2. contract_version in ('1', '2')
    3. task_id 非空
    4. base_oid 為 40-char hex，且若傳入 manifest 則與 manifest['base_oid'] 完全一致
    5. main_advancement: FORBIDDEN 或 EXACT_SHA
       - FORBIDDEN -> authorized_main_sha == 'NONE'
       - EXACT_SHA -> authorized_main_sha 為 40-char hex SHA
    6. remote_ref_deletion: FORBIDDEN 或 EXACT_SET
       - FORBIDDEN -> authorized_delete_refs == 'NONE'
       - EXACT_SET -> refs/heads/<branch>@<FULL40_SHA> (semicolon-separated, unique, 禁 main)
    7. 安全防護欄位固定約束：
       - local_destructive_git == 'FORBIDDEN'
       - credential_access == 'FORBIDDEN'
       - environment_enumeration == 'FORBIDDEN'
       - cross_session_access == 'FORBIDDEN'
       - browser_github_mutation == 'FORBIDDEN'
       - raw_actions_log_access == 'EXTERNAL_MACRO_ONLY'
       - branch_creation == 'GIT_SWITCH_C'
       - hook_bypass == 'FORBIDDEN'
       - goal_pressure_policy == 'SAFETY_BOUNDARY_WINS'
       - ide_ephemeral_guards_required == 'false'
    8. 若 contract_version == '2'：
       - allowed_mutation_paths (NONE 或分號分隔之 exact paths，禁 wildcard/glob/絕對路徑/..)
       - required_mutation_paths (NONE 或分號分隔之 exact paths，必須 required ⊆ allowed)
       - max_plan_revisions == '3'
       - execution_record_required ('true' 若 allowed!=NONE，否則 'false')
    """
    if isinstance(prompt_text_or_contract, dict):
        contract = dict(prompt_text_or_contract)
    else:
        ok, err, parsed = parse_execution_contract_block(prompt_text_or_contract)
        if not ok:
            return False, err, {}
        contract = parsed

    # 1. contract_version
    c_ver = contract.get("contract_version")
    if c_ver not in ("1", "2"):
        return False, f"Unsupported contract_version: {c_ver!r} (expected '1' or '2')", {}

    # 2. task_id
    if not contract.get("task_id"):
        return False, "Contract task_id cannot be empty", {}

    # 3. base_oid
    raw_base = contract.get("base_oid", "")
    base_oid = raw_base.strip().lower()
    if not re.match(r"^[0-9a-f]{40}$", base_oid):
        return False, f"Invalid contract base_oid: {raw_base!r} (expected 40-char hex string)", {}

    expected_base = None
    if manifest_base_oid:
        expected_base = manifest_base_oid.strip().lower()
    elif manifest and "base_oid" in manifest:
        expected_base = manifest["base_oid"].strip().lower()

    if expected_base and base_oid != expected_base:
        return False, f"Contract base_oid mismatch with manifest: contract={base_oid} vs manifest={expected_base}", {}

    # 4. main_advancement
    ma = contract["main_advancement"]
    if ma not in ("FORBIDDEN", "EXACT_SHA"):
        return False, f"Invalid main_advancement: {ma!r} (expected FORBIDDEN or EXACT_SHA)", {}

    auth_main_sha = contract["authorized_main_sha"].strip()
    if ma == "FORBIDDEN":
        if auth_main_sha != "NONE":
            return False, f"When main_advancement is FORBIDDEN, authorized_main_sha must be NONE (got {auth_main_sha!r})", {}
    elif ma == "EXACT_SHA":
        if not re.match(r"^[0-9a-f]{40}$", auth_main_sha.lower()):
            return False, f"When main_advancement is EXACT_SHA, authorized_main_sha must be a 40-char hex SHA (got {auth_main_sha!r})", {}

    # 5. remote_ref_deletion
    rd = contract["remote_ref_deletion"]
    if rd not in ("FORBIDDEN", "EXACT_SET"):
        return False, f"Invalid remote_ref_deletion: {rd!r} (expected FORBIDDEN or EXACT_SET)", {}

    auth_del_refs = contract["authorized_delete_refs"].strip()
    if rd == "FORBIDDEN":
        if auth_del_refs != "NONE":
            return False, f"When remote_ref_deletion is FORBIDDEN, authorized_delete_refs must be NONE (got {auth_del_refs!r})", {}
    elif rd == "EXACT_SET":
        if not auth_del_refs or auth_del_refs == "NONE":
            return False, "When remote_ref_deletion is EXACT_SET, authorized_delete_refs cannot be empty or NONE", {}
        entries = auth_del_refs.split(";")
        seen_refs = set()
        normalized_entries = []
        for raw_entry in entries:
            entry = raw_entry.strip()
            if not entry:
                return False, f"Empty entry in authorized_delete_refs: {auth_del_refs!r}", {}
            if "@" not in entry:
                return False, f"Malformed delete ref entry (missing '@'): {entry!r}", {}
            ref_name, expected_sha = entry.split("@", 1)
            ref_name = ref_name.strip()
            expected_sha = expected_sha.strip().lower()

            if not ref_name.startswith("refs/heads/") or len(ref_name) <= len("refs/heads/"):
                return False, f"Malformed delete ref name (must start with 'refs/heads/<branch>'): {ref_name!r}", {}
            if ref_name == "refs/heads/main":
                return False, "refs/heads/main is permanently forbidden from deletion authorization", {}
            if not re.match(r"^[0-9a-f]{40}$", expected_sha):
                return False, f"Malformed expected SHA for delete ref {ref_name!r}: {expected_sha!r}", {}
            if ref_name in seen_refs:
                return False, f"Duplicate delete ref in authorization: {ref_name!r}", {}
            seen_refs.add(ref_name)
            normalized_entries.append(f"{ref_name}@{expected_sha}")
        contract["authorized_delete_refs"] = ";".join(sorted(normalized_entries))

    # 6. Safety invariant fields
    if contract["local_destructive_git"] != "FORBIDDEN":
        return False, f"local_destructive_git must be 'FORBIDDEN' (got {contract['local_destructive_git']!r})", {}

    if contract["credential_access"] != "FORBIDDEN":
        return False, f"credential_access must be 'FORBIDDEN' (got {contract['credential_access']!r})", {}

    if contract["environment_enumeration"] != "FORBIDDEN":
        return False, f"environment_enumeration must be 'FORBIDDEN' (got {contract['environment_enumeration']!r})", {}

    if contract["cross_session_access"] != "FORBIDDEN":
        return False, f"cross_session_access must be 'FORBIDDEN' (got {contract['cross_session_access']!r})", {}

    if contract["browser_github_mutation"] != "FORBIDDEN":
        return False, f"browser_github_mutation must be 'FORBIDDEN' (got {contract['browser_github_mutation']!r})", {}

    if contract["raw_actions_log_access"] != "EXTERNAL_MACRO_ONLY":
        return False, f"raw_actions_log_access must be 'EXTERNAL_MACRO_ONLY' (got {contract['raw_actions_log_access']!r})", {}

    if contract["branch_creation"] != "GIT_SWITCH_C":
        return False, f"branch_creation must be 'GIT_SWITCH_C' (got {contract['branch_creation']!r})", {}

    if contract["hook_bypass"] != "FORBIDDEN":
        return False, f"hook_bypass must be 'FORBIDDEN' (got {contract['hook_bypass']!r})", {}

    if contract["goal_pressure_policy"] != "SAFETY_BOUNDARY_WINS":
        return False, f"goal_pressure_policy must be 'SAFETY_BOUNDARY_WINS' (got {contract['goal_pressure_policy']!r})", {}

    if contract["ide_ephemeral_guards_required"] != "false":
        return False, f"ide_ephemeral_guards_required must be 'false' (got {contract['ide_ephemeral_guards_required']!r})", {}

    # 8. Contract v2 specific fields validation
    if c_ver == "2":
        # max_plan_revisions
        max_rev = contract.get("max_plan_revisions", "").strip()
        if max_rev != "3":
            return False, f"Contract v2 max_plan_revisions must be '3' (got {max_rev!r})", {}

        # execution_record_required
        rec_req = contract.get("execution_record_required", "").strip()
        if rec_req not in ("true", "false"):
            return False, f"Contract v2 execution_record_required must be 'true' or 'false' (got {rec_req!r})", {}

        # allowed_mutation_paths & required_mutation_paths
        raw_allowed = contract.get("allowed_mutation_paths", "").strip()
        raw_required = contract.get("required_mutation_paths", "").strip()

        if raw_allowed == "NONE":
            if raw_required != "NONE":
                return False, f"When allowed_mutation_paths is NONE, required_mutation_paths must be NONE (got {raw_required!r})", {}
            if rec_req != "false":
                return False, f"When allowed_mutation_paths is NONE, execution_record_required must be 'false' (got {rec_req!r})", {}
            contract["allowed_mutation_paths"] = "NONE"
            contract["required_mutation_paths"] = "NONE"
        else:
            if rec_req != "true":
                return False, f"When allowed_mutation_paths is not NONE, execution_record_required must be 'true' (got {rec_req!r})", {}

            allowed_entries = raw_allowed.split(";")
            seen_allowed = set()
            normalized_allowed = []
            for raw_p in allowed_entries:
                p = raw_p.strip()
                if not p:
                    return False, f"Empty entry in allowed_mutation_paths: {raw_allowed!r}", {}
                p_norm = p.replace("\\", "/")
                if p_norm.startswith("/") or re.match(r"^[a-zA-Z]:", p_norm):
                    return False, f"Absolute path forbidden in allowed_mutation_paths: {p!r}", {}
                if ".." in p_norm.split("/"):
                    return False, f"Path traversal '..' forbidden in allowed_mutation_paths: {p!r}", {}
                if any(c in p_norm for c in ("*", "?", "[", "]")):
                    return False, f"Wildcard forbidden in allowed_mutation_paths: {p!r}", {}
                if p_norm in seen_allowed:
                    return False, f"Duplicate path in allowed_mutation_paths: {p!r}", {}
                seen_allowed.add(p_norm)
                normalized_allowed.append(p_norm)

            contract["allowed_mutation_paths"] = ";".join(sorted(normalized_allowed))

            if raw_required == "NONE":
                contract["required_mutation_paths"] = "NONE"
            else:
                req_entries = raw_required.split(";")
                seen_req = set()
                normalized_req = []
                for raw_p in req_entries:
                    p = raw_p.strip()
                    if not p:
                        return False, f"Empty entry in required_mutation_paths: {raw_required!r}", {}
                    p_norm = p.replace("\\", "/")
                    if p_norm.startswith("/") or re.match(r"^[a-zA-Z]:", p_norm):
                        return False, f"Absolute path forbidden in required_mutation_paths: {p!r}", {}
                    if ".." in p_norm.split("/"):
                        return False, f"Path traversal '..' forbidden in required_mutation_paths: {p!r}", {}
                    if any(c in p_norm for c in ("*", "?", "[", "]")):
                        return False, f"Wildcard forbidden in required_mutation_paths: {p!r}", {}
                    if p_norm in seen_req:
                        return False, f"Duplicate path in required_mutation_paths: {p!r}", {}
                    if p_norm not in seen_allowed:
                        return False, f"required_mutation_paths must be a subset of allowed_mutation_paths (not in allowed: {p!r})", {}
                    seen_req.add(p_norm)
                    normalized_req.append(p_norm)

                contract["required_mutation_paths"] = ";".join(sorted(normalized_req))

    return True, "", contract


def parse_manifest_block(prompt_text: str) -> tuple[bool, str, dict]:
    """
    從 prompt_text 中抽取出唯一的 manifest 區塊並解析為 key-value dict。
    fail-closed：缺失、重複、順序錯誤、格式錯誤皆立即回傳失敗。
    """
    begin_count = prompt_text.count(BEGIN_MARKER)
    end_count = prompt_text.count(END_MARKER)

    if begin_count == 0 or end_count == 0:
        return False, "Prompt manifest missing BEGIN or END marker", {}

    if begin_count > 1 or end_count > 1:
        return False, f"Duplicate manifest markers found (BEGIN={begin_count}, END={end_count})", {}

    begin_idx = prompt_text.find(BEGIN_MARKER)
    end_idx = prompt_text.find(END_MARKER)

    if begin_idx >= end_idx:
        return False, "Manifest marker ordering error: END appears before BEGIN", {}

    block_text = prompt_text[begin_idx + len(BEGIN_MARKER):end_idx]
    lines = block_text.splitlines()

    manifest = {}
    seen_keys = set()

    for line_no, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line:
            continue
        if ":" not in line:
            return False, f"Manifest line {line_no} malformed (missing colon): {raw_line!r}", {}
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()

        if key in seen_keys:
            return False, f"Duplicate key in manifest: {key!r}", {}
        if key not in REQUIRED_KEYS:
            return False, f"Unexpected/unsupported key in manifest: {key!r}", {}

        seen_keys.add(key)
        manifest[key] = val

    missing_keys = set(REQUIRED_KEYS) - seen_keys
    if missing_keys:
        return False, f"Missing required manifest keys: {sorted(list(missing_keys))}", {}

    return True, "", manifest


def validate_prompt_manifest(prompt_text: str) -> tuple[bool, str, dict]:
    """
    完整檢驗 prompt text 與 manifest：
    1. manifest block 存在且 key 完整無重複
    2. schema_version == 1
    3. batch_mode 為 GOAL_SPEC 或 EXACT_SPEC
    4. base_oid 為 40-hex
    5. finding_disposition 符合規範
    6. 三項 state disposition 只能 UPDATE 或 NO_CHANGE
    7. rules_reread_required == true
    8. fixed_signature_required == true
    9. destructive_git_allowed == false
    10. EXACT_SPEC 必須包含 Batch Spec path 與 SHA markers
    11. NEW <ID> 必須搭配 taskboard_disposition: UPDATE
    12. 宣稱 MACRO PASS / 核對通過 時 audit_log_disposition 不得為 NO_CHANGE
    """
    ok, err, manifest = parse_manifest_block(prompt_text)
    if not ok:
        return False, err, {}

    # 1. schema_version
    if manifest["schema_version"] != "1":
        return False, f"Unsupported schema_version: {manifest['schema_version']!r} (expected '1')", {}

    # 2. batch_mode
    if manifest["batch_mode"] not in ("GOAL_SPEC", "EXACT_SPEC"):
        return False, f"Invalid batch_mode: {manifest['batch_mode']!r} (expected GOAL_SPEC or EXACT_SPEC)", {}

    # 3. base_oid
    base_oid = manifest["base_oid"].strip().lower()
    if not re.match(r"^[0-9a-f]{40}$", base_oid):
        return False, f"Invalid base_oid: {manifest['base_oid']!r} (expected 40-char hex string)", {}

    # 4. finding_disposition
    fd = manifest["finding_disposition"]
    fd_match = re.match(r"^(NONE|(?:CURRENT|EXISTING|NEW)\s+([A-G]-[0-9]{2,}))$", fd)
    if not fd_match:
        return False, f"Invalid finding_disposition: {fd!r} (expected NONE or CURRENT/EXISTING/NEW <A-G>-<digits>)", {}

    # 5. state dispositions
    for disp_key in ("backlog_disposition", "taskboard_disposition", "audit_log_disposition"):
        val = manifest[disp_key]
        if val not in ("UPDATE", "NO_CHANGE"):
            return False, f"Invalid {disp_key}: {val!r} (expected UPDATE or NO_CHANGE)", {}

    # 6. rules_reread_required
    if manifest["rules_reread_required"] != "true":
        return False, f"rules_reread_required must be 'true' (got {manifest['rules_reread_required']!r})", {}

    # 7. fixed_signature_required
    if manifest["fixed_signature_required"] != "true":
        return False, f"fixed_signature_required must be 'true' (got {manifest['fixed_signature_required']!r})", {}

    # 8. destructive_git_allowed
    if manifest["destructive_git_allowed"] != "false":
        return False, (
            f"destructive_git_allowed must be 'false' (got {manifest['destructive_git_allowed']!r}); "
            "destructive Git operations require S1 escalation and cannot be authorized in production prompt"
        ), {}

    # 9. Cross-field: NEW <ID> requires taskboard_disposition = UPDATE
    if fd.startswith("NEW "):
        if manifest["taskboard_disposition"] != "UPDATE":
            return False, f"finding_disposition {fd!r} requires taskboard_disposition: UPDATE", {}

    # 10. EXACT_SPEC consistency checks
    if manifest["batch_mode"] == "EXACT_SPEC":
        has_spec_path = bool(re.search(r"docs/batches/[^\s`\'\"]+\.spec\.txt", prompt_text))
        has_sha_marker = bool(re.search(r"(?:SHA-256|sha256|spec\s+SHA)", prompt_text, re.IGNORECASE))
        if not has_spec_path:
            return False, "EXACT_SPEC prompt must specify Batch Spec path (docs/batches/*.spec.txt)", {}
        if not has_sha_marker:
            return False, "EXACT_SPEC prompt must specify Batch Spec SHA-256 marker", {}

    # 11. Cross-field: Claiming MACRO PASS while audit_log_disposition = NO_CHANGE
    macro_pass_patterns = [
        r"(?:正式裁決|Verdict|裁決)[^\n]*?(?:MACRO\s+(?:AUDIT\s+)?PASS|核對通過)",
        r"(?:^|\n)[^\n]*?=\s*MACRO\s+(?:AUDIT\s+)?PASS",
        r"(?:[0-9a-fA-F]{7,40}|\b[A-G]-\d+\b)[^\n]*?(?:宣稱|宣告|判定|裁定|裁決|視為)[^\n]*?(?:MACRO\s+(?:AUDIT\s+)?PASS|核對通過)",
        r"(?:MACRO\s+(?:AUDIT\s+)?PASS|核對通過)[^\n]*?(?:closure|checkpoint|結案)",
    ]
    claims_macro_pass = any(re.search(p, prompt_text, re.IGNORECASE) for p in macro_pass_patterns)
    if claims_macro_pass and manifest["audit_log_disposition"] == "NO_CHANGE":
        return False, (
            "Contradiction: prompt asserts MACRO PASS / 核對通過 verdict "
            "but audit_log_disposition is declared as NO_CHANGE"
        ), {}

    return True, "", manifest


def main():
    parser = argparse.ArgumentParser(description="Validate HH.AI prompt manifest.")
    parser.add_argument("--file", help="Path to prompt file (or '-' for stdin)")
    parser.add_argument("--require-contract", action="store_true", help="Require valid execution contract block")
    args = parser.parse_args()

    if args.file and args.file != "-":
        if not os.path.exists(args.file):
            sys.stderr.write(f"[FAIL] File not found: {args.file}\n")
            sys.exit(1)
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                prompt_text = f.read()
        except Exception as e:
            sys.stderr.write(f"[FAIL] Could not read file: {e}\n")
            sys.exit(1)
    else:
        if sys.stdin.isatty() and not (args.file == "-"):
            sys.stderr.write("[FAIL] No prompt input provided (use --file <path> or pipe via stdin)\n")
            sys.exit(1)
        prompt_text = sys.stdin.read()

    valid, err_msg, manifest = validate_prompt_manifest(prompt_text)
    if not valid:
        sys.stderr.write(f"[FAIL] {err_msg}\n")
        sys.exit(1)

    if args.require_contract or CONTRACT_BEGIN_MARKER in prompt_text:
        c_ok, c_err, contract = validate_execution_contract(prompt_text, manifest)
        if not c_ok:
            sys.stderr.write(f"[FAIL] Execution Contract invalid: {c_err}\n")
            sys.exit(1)
        print(f"[PASS] Prompt manifest valid (mode={manifest['batch_mode']}, base={manifest['base_oid'][:7]}), Execution contract valid (task={contract['task_id']}).")
        sys.exit(0)

    print(f"[PASS] Prompt manifest valid (mode={manifest['batch_mode']}, base={manifest['base_oid'][:7]}).")
    sys.exit(0)


if __name__ == "__main__":
    main()
