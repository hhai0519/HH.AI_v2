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

    print(f"[PASS] Prompt manifest valid (mode={manifest['batch_mode']}, base={manifest['base_oid'][:7]}).")
    sys.exit(0)


if __name__ == "__main__":
    main()
