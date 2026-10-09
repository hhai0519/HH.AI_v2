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
import stat
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

# Scoped rule reading (B-107): every directory-scoped AGENTS.md that governs an allowed mutation path
# (root AGENTS.md excluded) must be listed in the prompt's single "動手前必讀" section, as the leading path
# list of a numbered item ("4. runtime/channel-gateway/AGENTS.md（說明）").
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCOPED_RULE_FILENAME = "AGENTS.md"
MUST_READ_TITLE = "動手前必讀"
SECTION_HEADING_RE = re.compile(r"^(?:[一二三四五六七八九十]+、|#{1,6}\s)")
MUST_READ_ITEM_RE = re.compile(r"^\s*\d+\.\s+([A-Za-z0-9_./-]+(?:、[A-Za-z0-9_./-]+)*)(?![A-Za-z0-9_./\\-])")
RUNNER_BLOCK_BEGIN_RE = re.compile(r"^<<<BEGIN ([A-Z0-9_]+)>>>$")


def _rule_file_state(path: str) -> bool:
    """True：一般檔案存在；False：確定不存在；其他（權限、I/O、非一般檔案）一律 ValueError（fail closed）。"""
    try:
        st = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError as e:
        raise ValueError(f"cannot stat {path!r}: {e.__class__.__name__}") from e
    if not stat.S_ISREG(st.st_mode):
        raise ValueError(f"rule path is not a regular file: {path!r}")
    return True


def find_governing_scoped_rules(paths: list[str], repo_root: str = REPO_ROOT) -> list[str]:
    """
    回傳治理各路徑之目錄層級 AGENTS.md（不含根目錄，repo 相對路徑、排序）。
    只有「確定不存在」才略過；根目錄缺少 AGENTS.md、查詢權限或 I/O 錯誤、非一般檔案皆 ValueError（fail closed）。
    """
    if not _rule_file_state(os.path.join(repo_root, SCOPED_RULE_FILENAME)):
        raise ValueError(f"repository root has no {SCOPED_RULE_FILENAME}: {repo_root!r}")
    found = set()
    for raw in paths:
        parts = raw.replace("\\", "/").split("/")[:-1]
        for depth in range(1, len(parts) + 1):
            rel = "/".join(parts[:depth] + [SCOPED_RULE_FILENAME])
            if _rule_file_state(os.path.join(repo_root, *rel.split("/"))):
                found.add(rel)
    return sorted(found)


def _instruction_line_mask(lines: list[str]) -> list[bool]:
    """標記指令行；程式碼圍欄、HTML 註解、manifest／contract 區塊與 runner 機器區塊（含其邊界行）皆非指令行。"""
    mask = []
    fence = None
    formal_end = None
    runner_end = None
    in_comment = False
    for line in lines:
        stripped = line.strip()
        if fence is not None:
            fence = check_code_fence(line, fence)
            mask.append(False)
            continue
        if formal_end is not None:
            mask.append(False)
            if stripped == formal_end:
                formal_end = None
            continue
        if runner_end is not None:
            mask.append(False)
            if line == runner_end:
                runner_end = None
            continue
        if in_comment:
            mask.append(False)
            if "-->" in line:
                in_comment = False
            continue
        new_fence = check_code_fence(line, None)
        if new_fence is not None:
            fence = new_fence
            mask.append(False)
            continue
        if stripped == BEGIN_MARKER:
            formal_end = END_MARKER
            mask.append(False)
            continue
        if stripped == CONTRACT_BEGIN_MARKER:
            formal_end = CONTRACT_END_MARKER
            mask.append(False)
            continue
        m = RUNNER_BLOCK_BEGIN_RE.match(line)
        if m:
            runner_end = "<<<END " + m.group(1) + ">>>"
            mask.append(False)
            continue
        if "<!--" in line:
            in_comment = "-->" not in line[line.index("<!--") + 4:]
            mask.append(False)
            continue
        mask.append(True)
    return mask


def extract_must_read_section(prompt_text: str) -> tuple[bool, str, str]:
    """取出唯一之正式「動手前必讀」章節：只認指令行中之標題；章節止於下一個標題或任何非指令區域。"""
    lines = prompt_text.replace("\r\n", "\n").split("\n")
    mask = _instruction_line_mask(lines)
    starts = [i for i, line in enumerate(lines) if mask[i] and SECTION_HEADING_RE.match(line) and MUST_READ_TITLE in line]
    if len(starts) != 1:
        return False, f"expected exactly one '{MUST_READ_TITLE}' section heading outside code fences, comments and machine blocks, found {len(starts)}", ""
    end = len(lines)
    for j in range(starts[0] + 1, len(lines)):
        if not mask[j] or SECTION_HEADING_RE.match(lines[j]):
            end = j
            break
    return True, "", "\n".join(lines[starts[0]:end])


def listed_must_read_paths(section: str) -> set[str]:
    """章節中編號項目開頭之路徑清單（以「、」分隔）；項目內其他位置之路徑不算列出。"""
    listed = set()
    for line in section.split("\n"):
        m = MUST_READ_ITEM_RE.match(line)
        if m:
            listed.update(m.group(1).split("、"))
    return listed


def validate_scoped_rule_reading(prompt_text: str, paths: list[str], repo_root: str = REPO_ROOT) -> tuple[bool, str]:
    """
    驗證治理 allowed_mutation_paths 之 scoped AGENTS.md 全數列於「動手前必讀」章節之編號項目開頭路徑清單。
    探索失敗、章節缺漏或重複、任一檔未列出，皆回傳失敗。
    """
    try:
        required = find_governing_scoped_rules(paths, repo_root)
    except ValueError as e:
        return False, f"Scoped rule discovery failed: {e}"
    if not required:
        return True, ""
    ok, err, section = extract_must_read_section(prompt_text)
    if not ok:
        return False, f"Scoped rule files {required} govern allowed_mutation_paths, but {err}"
    listed = listed_must_read_paths(section)
    missing = [rel for rel in required if rel not in listed]
    if missing:
        return False, f"'{MUST_READ_TITLE}' section does not list (as the leading path of a numbered item) scoped rule files governing allowed_mutation_paths: {missing}"
    return True, ""


def check_code_fence(line: str, active_fence: tuple[str, int] | None) -> tuple[str, int] | None:
    """
    Track markdown fenced code block state according to CommonMark.
    A code fence opens with 0-3 leading spaces followed by 3+ backticks or tildes.
    It closes with 0-3 leading spaces, the same fence char, at least the same length,
    and only trailing spaces.
    """
    stripped_leading = line.lstrip(" ")
    indent = len(line) - len(stripped_leading)
    if indent > 3:
        return active_fence

    if active_fence is not None:
        char, min_len = active_fence
        if char == "`" and stripped_leading.startswith("`" * min_len):
            rest = stripped_leading.lstrip("`")
            if rest.strip() == "":
                return None
        elif char == "~" and stripped_leading.startswith("~" * min_len):
            rest = stripped_leading.lstrip("~")
            if rest.strip() == "":
                return None
        return active_fence

    # Outside fence: check if opening
    if stripped_leading.startswith("```"):
        fence_len = len(stripped_leading) - len(stripped_leading.lstrip("`"))
        info = stripped_leading[fence_len:]
        if "`" not in info:
            return ("`", fence_len)
    elif stripped_leading.startswith("~~~"):
        fence_len = len(stripped_leading) - len(stripped_leading.lstrip("~"))
        return ("~", fence_len)

    return None


def locate_structural_block(
    prompt_text: str,
    begin_marker: str,
    end_marker: str,
    block_name: str,
    display_name: str,
) -> tuple[bool, str, list[str]]:
    """
    Locates and extracts the unique formal structural block (manifest or execution contract).
    Ensures:
    1. Standalone logical line boundary outside markdown code fences (line.strip() == marker).
    2. No prefix/suffix prose on marker line.
    3. Exactly one BEGIN and one END marker.
    4. END appears after BEGIN.
    5. No duplicate, missing, reversed, or nested/repeated structural markers.
    Returns (ok, err_msg, inner_lines).
    """
    lines = prompt_text.splitlines()
    active_fence: tuple[str, int] | None = None

    boundary_events = []

    for line_idx, line in enumerate(lines):
        new_fence = check_code_fence(line, active_fence)
        if active_fence is not None:
            active_fence = new_fence
            continue
        if new_fence is not None:
            active_fence = new_fence
            continue

        stripped = line.strip()
        if stripped in (begin_marker, end_marker):
            boundary_events.append((line_idx, stripped))

    begins = [idx for idx, m in boundary_events if m == begin_marker]
    ends = [idx for idx, m in boundary_events if m == end_marker]

    if len(begins) == 0 and len(ends) == 0:
        return False, f"{display_name} missing BEGIN or END marker", []
    if len(begins) == 0:
        return False, f"{display_name} missing BEGIN marker", []
    if len(ends) == 0:
        return False, f"{display_name} missing END marker", []

    if len(begins) > 1 or len(ends) > 1:
        return False, f"Duplicate {block_name} markers found (BEGIN={len(begins)}, END={len(ends)})", []

    begin_idx = begins[0]
    end_idx = ends[0]

    if begin_idx >= end_idx:
        if block_name == "manifest":
            return False, "Manifest marker ordering error: END appears before BEGIN", []
        else:
            return False, "Contract marker ordering error: END appears before BEGIN", []

    inner_lines = []
    fence_in_block: tuple[str, int] | None = None
    all_structural = (BEGIN_MARKER, END_MARKER, CONTRACT_BEGIN_MARKER, CONTRACT_END_MARKER)

    for curr_idx in range(begin_idx + 1, end_idx):
        raw_line = lines[curr_idx]
        new_fence = check_code_fence(raw_line, fence_in_block)
        if fence_in_block is not None:
            fence_in_block = new_fence
            inner_lines.append(raw_line)
            continue
        if new_fence is not None:
            fence_in_block = new_fence
            inner_lines.append(raw_line)
            continue

        stripped = raw_line.strip()
        if stripped in all_structural:
            return False, f"Nested or repeated structural marker inside {display_name}: {stripped}", []
        inner_lines.append(raw_line)

    return True, "", inner_lines


def has_formal_contract_markers(prompt_text: str) -> bool:
    """Check if formal standalone contract markers exist outside markdown code fences."""
    lines = prompt_text.splitlines()
    active_fence: tuple[str, int] | None = None
    for line in lines:
        new_fence = check_code_fence(line, active_fence)
        if active_fence is not None:
            active_fence = new_fence
            continue
        if new_fence is not None:
            active_fence = new_fence
            continue
        if line.strip() in (CONTRACT_BEGIN_MARKER, CONTRACT_END_MARKER):
            return True
    return False


def parse_execution_contract_block(prompt_text: str) -> tuple[bool, str, dict]:
    """
    從 prompt_text 中抽取出唯一的 execution contract 區塊並解析為 key-value dict。
    fail-closed：缺失、重複、順序錯誤、格式錯誤、未知欄位皆立即回傳失敗。
    支援 contract_version = 1 與 contract_version = 2。
    """
    ok, err, inner_lines = locate_structural_block(
        prompt_text,
        begin_marker=CONTRACT_BEGIN_MARKER,
        end_marker=CONTRACT_END_MARKER,
        block_name="contract",
        display_name="Execution contract",
    )
    if not ok:
        return False, err, {}

    raw_pairs = []
    seen_keys = set()
    contract_version = "1"

    for line_no, raw_line in enumerate(inner_lines, 1):
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
       - 輸入為完整提示詞時，治理 allowed_mutation_paths 之 scoped AGENTS.md（不含根目錄）
         必須列於唯一之正式「動手前必讀」章節之編號項目開頭路徑清單（validate_scoped_rule_reading）
    """
    prompt_text = None
    if isinstance(prompt_text_or_contract, dict):
        contract = dict(prompt_text_or_contract)
    else:
        prompt_text = prompt_text_or_contract
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

            # Scoped rule reading (B-107): only checkable when the full prompt text is available.
            if prompt_text is not None:
                scoped_ok, scoped_err = validate_scoped_rule_reading(prompt_text, normalized_allowed)
                if not scoped_ok:
                    return False, scoped_err, {}

    return True, "", contract


def parse_manifest_block(prompt_text: str) -> tuple[bool, str, dict]:
    """
    從 prompt_text 中抽取出唯一的 manifest 區塊並解析為 key-value dict。
    fail-closed：缺失、重複、順序錯誤、格式錯誤皆立即回傳失敗。
    """
    ok, err, inner_lines = locate_structural_block(
        prompt_text,
        begin_marker=BEGIN_MARKER,
        end_marker=END_MARKER,
        block_name="manifest",
        display_name="Prompt manifest",
    )
    if not ok:
        return False, err, {}

    manifest = {}
    seen_keys = set()

    for line_no, raw_line in enumerate(inner_lines, 1):
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

    if args.require_contract or has_formal_contract_markers(prompt_text):
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
