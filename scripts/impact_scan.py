#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/impact_scan.py

B-68 Phase 1: 確定性反向依賴掃描與證據重放工具 (Deterministic Impact Scanner & Evidence Replay)
依據 AGENTS.md, PRINCIPLES.md 及 B-68 架構規範：
1. 僅使用 Python 標準庫 (Python stdlib only)。
2. 倉庫清單權威：git ls-files -z（僅掃描 Git tracked regular files，嚴禁使用 os.walk 作為權威）。
3. 未追蹤 (untracked) 與被忽略 (gitignored) 檔案絕不影響掃描結果。
4. 查詢 (query) 為精確 UTF-8 位元組序列 / exact text，Phase 1 不做模糊或語意推論。
5. 支援 query kind: literal, symbol, path, section, contract（作為審計中繼資料，比對一律為 exact matching）。
6. 確定性輸出：query 排序與路徑排序皆確定，同輸入與同 HEAD 保證產生完全相同之 dependency set。
7. 讀取或 Git 清單失敗時一律 FAIL CLOSED（嚴禁 silent skip 或 fallback）。
8. 支援兩大模式：
   - DISCOVER: 輸入查詢清單，輸出機器可讀的 JSON 依賴探索結果（不含語意裁決）。
   - CHECK / REPLAY: 輸入經 Macro Auditor 標註 dispositions 的證據 JSON，
     驗證 HEAD 一致、依賴集合完全相符（無遺漏、無幽靈依賴）且每筆依賴皆有合法處置。
"""

import argparse
import json
import os
import subprocess
import sys


SCHEMA_VERSION = 1
VALID_KINDS = {"literal", "symbol", "path", "section", "contract"}
VALID_DISPOSITIONS = {"UPDATE", "VERIFY_ONLY", "HISTORICAL_NO_CHANGE"}
VALID_MODES = {"REQUIRED", "NONE"}


class ImpactScanError(Exception):
    """Base error for impact scan failures (fail-closed)."""
    pass


def get_tracked_files(repo_root: str) -> list[str]:
    """
    透過 git ls-files -z 取得當前倉庫所有被 Git 追蹤的檔案清單。
    回傳正規化 POSIX 相對路徑之確定性排序清單。
    若失敗（如非 Git 倉庫或指令異常），一律拋出 ImpactScanError (FAIL CLOSED)。
    """
    cmd = ["git", "ls-files", "-z"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=repo_root,
            capture_output=True,
            check=False
        )
    except Exception as e:
        raise ImpactScanError(f"無法執行 git ls-files: {e}") from e

    if proc.returncode != 0:
        err_msg = proc.stderr.decode("utf-8", errors="replace").strip()
        raise ImpactScanError(f"git ls-files 執行失敗 (code {proc.returncode}): {err_msg}")

    raw_bytes = proc.stdout
    if not raw_bytes:
        return []

    parts = raw_bytes.split(b"\0")
    tracked = []
    for p in parts:
        if not p:
            continue
        try:
            rel_path = p.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ImpactScanError(f"無法以 UTF-8 解碼 tracked 檔案路徑: {e}") from e
        norm_path = rel_path.replace("\\", "/")
        tracked.append(norm_path)

    tracked.sort()
    return tracked


def get_head_oid(repo_root: str) -> str:
    """
    取得當前倉庫 HEAD 之 full 40-hex commit OID。
    失敗則拋出 ImpactScanError (FAIL CLOSED)。
    """
    cmd = ["git", "rev-parse", "--verify", "HEAD^{commit}"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=repo_root,
            capture_output=True,
            check=False
        )
    except Exception as e:
        raise ImpactScanError(f"無法執行 git rev-parse: {e}") from e

    if proc.returncode != 0:
        err_msg = proc.stderr.decode("utf-8", errors="replace").strip()
        raise ImpactScanError(f"git rev-parse 取得 HEAD 失敗 (code {proc.returncode}): {err_msg}")

    oid = proc.stdout.decode("utf-8", errors="replace").strip()
    if len(oid) != 40:
        raise ImpactScanError(f"HEAD OID 長度非 40 碼 hex: '{oid}'")
    return oid


def scan_file_for_query(abs_file_path: str, query_bytes: bytes) -> list[int]:
    """
    以二進位讀取單一檔案內容，搜尋 query_bytes 精確出現位置。
    以位元組 newline (b'\\n') 確定性推導 1-indexed 行號。
    回傳該檔案內所有命中之排序不重複行號清單。
    若讀取失敗（如 permission error 或 I/O 錯誤），一律拋出 ImpactScanError (FAIL CLOSED)。
    """
    try:
        with open(abs_file_path, "rb") as f:
            content = f.read()
    except Exception as e:
        raise ImpactScanError(f"讀取追蹤檔案失敗 '{abs_file_path}': {e}") from e

    if not query_bytes:
        return []

    line_numbers = []
    start = 0
    q_len = len(query_bytes)
    while True:
        idx = content.find(query_bytes, start)
        if idx == -1:
            break
        # 1-indexed 行號：前段出現的 \n 個數 + 1
        line_no = content[:idx].count(b"\n") + 1
        if not line_numbers or line_numbers[-1] != line_no:
            line_numbers.append(line_no)
        start = idx + max(q_len, 1)

    return line_numbers


def validate_queries(raw_queries: list) -> list[dict]:
    """
    驗證查詢規格清單：
    - 必須為 list
    - 每個元素必須為 dict，包含 id, kind, value
    - query ID 不得重複且非空
    - query kind 必須在 VALID_KINDS 內
    - query value 必須為非空字串
    回傳經排序與正規化後之 queries 清單。
    """
    if not isinstance(raw_queries, list):
        raise ImpactScanError(f"queries 必須為 JSON array/list，實際為: {type(raw_queries).__name__}")

    seen_ids = set()
    validated = []
    for idx, q in enumerate(raw_queries):
        if not isinstance(q, dict):
            raise ImpactScanError(f"第 {idx} 項 query 必須為物件，實際為: {q}")
        qid = q.get("id")
        kind = q.get("kind")
        val = q.get("value")

        if not qid or not isinstance(qid, str):
            raise ImpactScanError(f"第 {idx} 項 query 缺少合法 'id' 字串: {q}")
        if qid in seen_ids:
            raise ImpactScanError(f"重複的 query ID: '{qid}'")
        seen_ids.add(qid)

        if not kind or not isinstance(kind, str) or kind not in VALID_KINDS:
            raise ImpactScanError(f"query '{qid}' 之 kind 非法: '{kind}'（合法值: {sorted(list(VALID_KINDS))}）")

        if val is None or not isinstance(val, str) or val == "":
            raise ImpactScanError(f"query '{qid}' 之 value 必須為非空字串")

        validated.append({
            "id": qid,
            "kind": kind,
            "value": val
        })

    # 依 id 排序，保證輸出確定性
    validated.sort(key=lambda x: x["id"])
    return validated


def run_discovery(repo_root: str, queries: list[dict]) -> dict:
    """
    執行 DISCOVER 階段：
    針對 tracked regular files 掃描各 query 之 exact sequence。
    回傳符合 evidence contract 之 discovery dict。
    """
    validated_queries = validate_queries(queries)
    head_oid = get_head_oid(repo_root)
    tracked_files = get_tracked_files(repo_root)

    results = []
    for q in validated_queries:
        qid = q["id"]
        qkind = q["kind"]
        qval = q["value"]
        q_bytes = qval.encode("utf-8")

        matched_paths = []
        matches = []

        for rel_path in tracked_files:
            abs_path = os.path.join(repo_root, rel_path)
            # 只掃描 regular file（若為目錄或符號連結則跳過）
            if os.path.islink(abs_path) or not os.path.isfile(abs_path):
                continue

            line_nos = scan_file_for_query(abs_path, q_bytes)
            if line_nos:
                matched_paths.append(rel_path)
                matches.append({
                    "path": rel_path,
                    "lines": line_nos
                })

        results.append({
            "query_id": qid,
            "query_kind": qkind,
            "query_value": qval,
            "matched_paths": matched_paths,
            "matches": matches
        })

    # results 依 query_id 排序保證確定性
    results.sort(key=lambda x: x["query_id"])

    evidence = {
        "schema_version": SCHEMA_VERSION,
        "base_oid": head_oid,
        "mode": "REQUIRED",
        "queries": validated_queries,
        "results": results
    }
    return evidence


def load_and_validate_allowed_scope(scope_file: str) -> set[str]:
    """
    載入並嚴格驗證 Allowed Scope JSON 檔案 (B-68 Phase 1)。
    Fail-closed 規則：
    - 檔案必須存在且可讀
    - 合法 JSON 格式
    - 頂層必須為物件且 schema_version == 1
    - 必須包含 'allowed_scope' 陣列
    - 項目必須為非空字串
    - 不得包含重複路徑
    - 不得為絕對路徑
    - 不得包含路徑遍歷 ('..')
    回傳以 POSIX slash 正規化之 repo-relative paths set。
    """
    if not os.path.isfile(scope_file):
        raise ImpactScanError(f"Allowed Scope 檔案不存在: {scope_file}")

    try:
        with open(scope_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise ImpactScanError(f"Allowed Scope JSON 解析失敗: {e}")

    if not isinstance(data, dict):
        raise ImpactScanError("Allowed Scope 頂層必須為 JSON 物件")

    if data.get("schema_version") != 1:
        raise ImpactScanError(f"不支援的 Allowed Scope schema_version: {data.get('schema_version')}（必須為 1）")

    scope_list = data.get("allowed_scope")
    if not isinstance(scope_list, list):
        raise ImpactScanError("Allowed Scope 必須包含 'allowed_scope' 陣列")

    normalized_scope = set()
    seen = set()
    for idx, item in enumerate(scope_list):
        if not isinstance(item, str):
            raise ImpactScanError(f"Allowed Scope 索引 {idx} 項目必須為字串: {type(item)}")
        raw_p = item.strip()
        if not raw_p:
            raise ImpactScanError(f"Allowed Scope 索引 {idx} 不得為空字串")
        if item in seen:
            raise ImpactScanError(f"Allowed Scope 包含重複路徑: '{item}'")
        seen.add(item)

        # 絕對路徑檢查
        if os.path.isabs(raw_p) or (len(raw_p) >= 2 and raw_p[1] == ":") or raw_p.startswith("/") or raw_p.startswith("\\"):
            raise ImpactScanError(f"Allowed Scope 不得包含絕對路徑: '{item}'")

        norm_p = raw_p.replace("\\", "/")
        parts = norm_p.split("/")
        if ".." in parts:
            raise ImpactScanError(f"Allowed Scope 不得包含路徑遍歷 ('..'): '{item}'")

        clean_p = "/".join(p for p in parts if p and p != ".")
        normalized_scope.add(clean_p)

    return normalized_scope


def run_check_replay(repo_root: str, evidence: dict, allowed_scope: set[str] | list[str] | None = None) -> tuple[bool, list[str]]:
    """
    執行 CHECK / REPLAY 階段：
    輸入帶有 dispositions 的 evidence JSON，重新掃描 repo 並嚴格驗證：
    1. schema_version == 1
    2. base_oid 完全符合 current HEAD
    3. mode 檢驗（支援 NONE 與 REQUIRED）
    4. queries 與 results 完整一對一 closure（無整筆缺失、無重複 result、無未定義 query_id）
    5. actual hit set 與 evidence dependency set 完全相符（無 missing、無 phantom）
    6. 每筆 dependency 都具有合法 disposition (UPDATE, VERIFY_ONLY, HISTORICAL_NO_CHANGE)
    7. mode=REQUIRED 時，machine-check 所有 disposition=UPDATE dependencies ⊆ Allowed Scope
    回傳 (is_pass, list_of_errors)。
    """
    errors = []

    if not isinstance(evidence, dict):
        return False, ["Evidence 必須為 JSON 物件"]

    schema_ver = evidence.get("schema_version")
    if schema_ver != SCHEMA_VERSION:
        return False, [f"Evidence schema_version 不符: 預期 {SCHEMA_VERSION}，實際為 {schema_ver}"]

    ev_base = evidence.get("base_oid") or evidence.get("base_full_oid")
    if not ev_base:
        return False, ["Evidence 缺少 'base_oid' 欄位"]

    try:
        current_head = get_head_oid(repo_root)
    except ImpactScanError as e:
        return False, [f"無法取得 current HEAD: {e}"]

    if ev_base != current_head:
        return False, [f"Base OID mismatch: evidence base={ev_base}, current repo HEAD={current_head}"]

    mode = evidence.get("mode", "REQUIRED")
    if mode not in VALID_MODES:
        return False, [f"非法 evidence mode: '{mode}'（合法值: {sorted(list(VALID_MODES))}）"]

    if mode == "NONE":
        reason = evidence.get("reason")
        if not reason or not isinstance(reason, str) or not reason.strip():
            return False, ["mode=NONE 必須附帶非空之 reason 理由說明"]
        return True, []

    # mode == REQUIRED
    norm_allowed_scope = None
    if allowed_scope is not None:
        norm_allowed_scope = {p.replace("\\", "/").strip("/") for p in allowed_scope}
    else:
        errors.append("mode=REQUIRED 必須提供 Allowed Scope 驗證 (allowed_scope is None)")

    raw_queries = evidence.get("queries")
    if raw_queries is None:
        # 嘗試由 results 反向提取
        results_sec = evidence.get("results", [])
        raw_queries = [
            {"id": r.get("query_id"), "kind": r.get("query_kind"), "value": r.get("query_value")}
            for r in results_sec
        ]

    try:
        queries = validate_queries(raw_queries)
    except ImpactScanError as e:
        return False, [f"Evidence queries 格式驗證失敗: {e}"]

    expected_qids = {q["id"] for q in queries}

    # 執行新鮮掃描
    try:
        fresh_evidence = run_discovery(repo_root, queries)
    except ImpactScanError as e:
        return False, [f"Replay 執行反向掃描失敗: {e}"]

    fresh_results_by_id = {r["query_id"]: r for r in fresh_evidence["results"]}

    ev_results = evidence.get("results")
    if not isinstance(ev_results, list):
        return False, ["Evidence 缺少 'results' 陣列"]

    seen_result_qids = set()

    # 提取 evidence 中的 dependencies 與 dispositions
    for ev_res in ev_results:
        if not isinstance(ev_res, dict):
            errors.append(f"Evidence result 不是物件: {ev_res}")
            continue

        qid = ev_res.get("query_id")
        if not qid:
            errors.append(f"Evidence result 缺少 query_id: {ev_res}")
            continue

        if qid in seen_result_qids:
            errors.append(f"Evidence 包含重複的 result query_id: '{qid}'")
            continue
        seen_result_qids.add(qid)

        if qid not in expected_qids:
            errors.append(f"Evidence 包含未定義之 query_id: '{qid}'")
            continue

        fresh_res = fresh_results_by_id[qid]
        actual_paths = set(fresh_res["matched_paths"])

        # 彙整 evidence 中宣稱的 dependencies 及其 disposition
        ev_dispositions = {}

        # 來源 1: "dispositions" dict
        if isinstance(ev_res.get("dispositions"), dict):
            for p, disp in ev_res["dispositions"].items():
                ev_dispositions[p.replace("\\", "/")] = disp

        # 來源 2: "dependencies" list
        if isinstance(ev_res.get("dependencies"), list):
            for item in ev_res["dependencies"]:
                if isinstance(item, dict) and "path" in item:
                    p = item["path"].replace("\\", "/")
                    disp = item.get("disposition")
                    ev_dispositions[p] = disp

        # 來源 3: "matches" list
        if isinstance(ev_res.get("matches"), list):
            for item in ev_res["matches"]:
                if isinstance(item, dict) and "path" in item:
                    p = item["path"].replace("\\", "/")
                    if "disposition" in item:
                        ev_dispositions[p] = item.get("disposition")

        # 來源 4: "matched_paths" list
        if isinstance(ev_res.get("matched_paths"), list):
            for p_raw in ev_res["matched_paths"]:
                p = p_raw.replace("\\", "/")
                if p not in ev_dispositions:
                    ev_dispositions[p] = None

        evidence_paths = set(ev_dispositions.keys())

        # 檢查缺失依賴 (Missing dependency: in repo but missing from evidence)
        missing = sorted(list(actual_paths - evidence_paths))
        for m in missing:
            errors.append(f"Query '{qid}' 遺漏實際依賴路徑: '{m}'（實際存在於追蹤庫中，但 evidence 未列入）")

        # 檢查幽靈依賴 (Phantom dependency: in evidence but not found in repo)
        phantom = sorted(list(evidence_paths - actual_paths))
        for ph in phantom:
            errors.append(f"Query '{qid}' 包含幽靈依賴路徑: '{ph}'（evidence 列出但實際追蹤庫中未命中）")

        # 檢查每筆命中之 disposition 是否合法，並對 UPDATE 做 Allowed Scope 檢驗
        for p in sorted(list(actual_paths & evidence_paths)):
            disp = ev_dispositions.get(p)
            if disp is None:
                errors.append(f"Query '{qid}' 之依賴路徑 '{p}' 缺少 disposition 處置宣告")
            elif disp not in VALID_DISPOSITIONS:
                errors.append(f"Query '{qid}' 之依賴路徑 '{p}' 具有非法 disposition: '{disp}'（合法值: {sorted(list(VALID_DISPOSITIONS))}）")
            elif disp == "UPDATE" and norm_allowed_scope is not None:
                p_clean = p.replace("\\", "/").strip("/")
                if p_clean not in norm_allowed_scope:
                    errors.append(f"Query '{qid}' 之 UPDATE 依賴路徑 '{p}' 未包含於 Allowed Scope 中")

    # 檢查是否整筆 query result 缺失
    missing_result_qids = expected_qids - seen_result_qids
    for mqid in sorted(list(missing_result_qids)):
        errors.append(f"Query '{mqid}' 遺漏對應之 result（整筆 query result 缺失）")

    if errors:
        return False, errors
    return True, []


def parse_query_spec(query_spec_str: str) -> dict:
    """
    從字串解析 inline query: 'id:kind:value'
    例如: 'q1:literal:OLD DISPLAY STRING'
    """
    parts = query_spec_str.split(":", 2)
    if len(parts) != 3:
        raise ImpactScanError(f"Inline query 格式錯誤: '{query_spec_str}'（應為 'id:kind:value'）")
    qid, kind, val = parts
    return {"id": qid.strip(), "kind": kind.strip(), "value": val}


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(description="Deterministic Impact Scanner & Evidence Replay (B-68)")
    parser.add_argument("mode", nargs="?", choices=["discover", "check", "replay"], default=None,
                        help="執行模式: discover 或 check/replay")
    parser.add_argument("--discover", action="store_true", help="執行 DISCOVER 模式")
    parser.add_argument("--check", action="store_true", help="執行 CHECK / REPLAY 模式")
    parser.add_argument("--replay", action="store_true", help="執行 CHECK / REPLAY 模式 (同 --check)")
    parser.add_argument("--repo-root", default=None, help="Repository 根目錄（預設自動推算）")
    parser.add_argument("--queries-file", "-qf", default=None, help="查詢定義 JSON 檔案路徑")
    parser.add_argument("--query", "-q", action="append", default=[], help="單一查詢定義 'id:kind:value'（可重複指定）")
    parser.add_argument("--evidence-file", "-ef", default=None, help="Evidence JSON 檔案路徑（用於 check/replay）")
    parser.add_argument("--allowed-scope-file", "-asf", default=None, help="Allowed Scope JSON 檔案路徑（用於 check/replay）")
    parser.add_argument("--output", "-o", default=None, help="輸出檔案路徑（預設標準輸出）")

    args = parser.parse_args(argv)

    # 決定 mode
    selected_mode = args.mode
    if args.discover:
        selected_mode = "discover"
    elif args.check or args.replay:
        selected_mode = "check"

    if not selected_mode:
        if args.evidence_file:
            selected_mode = "check"
        elif args.queries_file or args.query:
            selected_mode = "discover"
        else:
            parser.print_help()
            sys.exit(2)

    # 決定 repo_root
    if args.repo_root:
        repo_root = os.path.abspath(args.repo_root)
    else:
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    try:
        if selected_mode == "discover":
            raw_queries = []
            if args.queries_file:
                if not os.path.isfile(args.queries_file):
                    raise ImpactScanError(f"查詢檔案不存在: {args.queries_file}")
                with open(args.queries_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        raw_queries.extend(data)
                    elif isinstance(data, dict) and "queries" in data:
                        raw_queries.extend(data["queries"])
                    else:
                        raise ImpactScanError(f"查詢檔案格式不符: {args.queries_file}")

            for q_str in args.query:
                raw_queries.append(parse_query_spec(q_str))

            if not raw_queries:
                raise ImpactScanError("DISCOVER 模式需要至少一項 query（透過 --queries-file 或 --query 指定）")

            evidence = run_discovery(repo_root, raw_queries)
            out_str = json.dumps(evidence, ensure_ascii=False, indent=2)

            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(out_str + "\n")
            else:
                print(out_str)
            return 0

        elif selected_mode in ("check", "replay"):
            if not args.evidence_file:
                raise ImpactScanError(f"{selected_mode} 模式需要指定 --evidence-file")
            if not os.path.isfile(args.evidence_file):
                raise ImpactScanError(f"Evidence 檔案不存在: {args.evidence_file}")

            with open(args.evidence_file, "r", encoding="utf-8") as f:
                evidence = json.load(f)

            allowed_scope = None
            if args.allowed_scope_file:
                allowed_scope = load_and_validate_allowed_scope(args.allowed_scope_file)
            elif evidence.get("mode", "REQUIRED") == "REQUIRED":
                raise ImpactScanError("mode=REQUIRED 必須指定 --allowed-scope-file")

            is_pass, errors = run_check_replay(repo_root, evidence, allowed_scope=allowed_scope)
            if is_pass:
                print("[PASS] Impact evidence replay verified: exact dependency closure matched.")
                return 0
            else:
                print(f"[FAIL] Impact evidence replay mismatch ({len(errors)} errors):", file=sys.stderr)
                for err in errors:
                    print(f"  - {err}", file=sys.stderr)
                return 1

    except ImpactScanError as e:
        print(f"[FAIL CLOSED] {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"[FAIL CLOSED UNEXPECTED] {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
