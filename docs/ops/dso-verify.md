# TD-136b／TD-139／TD-144a：D-SO 一鍵複核工具（`scripts/dso_verify.py`）

> 本文件定義 `scripts/dso_verify.py`（`TOOL_VERSION=1.1.0`、`SCHEMA_VERSION=1`）之規格、三態退出碼、禁止自我驗證（驗證工具版本＝Base 版本，M1）、`DSO-REQ` 最終 `PACK.zip` 打包契約（`4a`）、安全解壓契約（`TD-139`）、明確契約質名清單 `CONTRACT_QUALNAMES_BY_FILE`、白名單 `canonical_sha256` 與 `content_canonical_sha256`、依 Windows 實測乘 2 校準之步驟逾時預算，以及與 `scripts/diff_ast_mutate.py`（`TD-134`／`TD-144a`）相依之輸出 JSON Schema v1。工具嚴格僅依賴 Python 3.14 標準函式庫與同目錄 `bounded_process.py`，全程對呼叫端 `--repo` 嚴格唯讀。

---

## 一、定位、驗證工具版本與使用方式（`4a`／M1／S2／M3）

審查官送件 D-SO 前，與第二意見收到 `DSO-PACK-*.zip` 後，皆對**最終成品 `PACK.zip`** 執行同一套確定性複核，並比對白名單規範雜湊 `canonical_sha256`（`4a`）：

- **`4a` 交付規定**：審查官產出 `DSO-REQ` 前**必須先打包最終 `PACK.zip`**，再對該 `<DSO-PACK.zip>` 路徑執行 `--pack <DSO-PACK.zip>`，不得先對未壓縮目錄跑 `dso_verify` 後才壓縮 `PACK.zip`。報告亦額外提供非 canonical 之 `pack_mode`（`"zip" | "dir"`）與 `content_canonical_sha256`（排除 `inputs["pack_sha256"]`），供跨封裝格式對照。
- **M1 禁止自我驗證（驗證工具版本＝Base 版本）**：`dso_verify.py` 第 9 步呼叫審查端自身所屬版本庫目錄下之 `diff_ast_mutate.py`（未存在時退回 `work_base/scripts/diff_ast_mutate.py`），**嚴禁執行候選 `work_patched/scripts/diff_ast_mutate.py`**。若當批修改對象正是 `scripts/dso_verify.py` 或 `scripts/diff_ast_mutate.py` 本身，審查官預檢與第二意見 D-SO **必須以 Base（`main`）上既有工具驗證該批 `PACK.zip`**；候選新版工具結果僅得列為附加參考證據，絕不得作為唯一放行依據。
- **M3 快取邊界**：選用 `--mutate-cache-dir <dir>`（預設關閉）必須位於 `--repo`、W2 與 `--pack` 目錄之外（否則 exit `2` `INVALID_ARGS`），且嚴禁放進 `DSO-PACK-*.zip`；第二意見獨立重跑預設維持冷執行。
- **S2 同電腦資源避讓**：當 Executor `scripts/batch_runner.py` 正在本機執行時，審查官嚴禁對本機同電腦使用 `--mutate-workers > 1`。

```text
python scripts/dso_verify.py --repo <clean-base-clone> --pack <DSO-PACK.zip> --json-out dso-verify-report.json
python scripts/dso_verify.py --repo <clean-base-clone> --pack <DSO-PACK.zip> --mutate-workers 4 --mutate-cache-dir C:\hhaud\mutate_cache --json-out dso-verify-report.json
python scripts/dso_verify.py --repo <clean-base-clone> --pack <DSO-PACK.zip> --skip-fast --json-out partial-report.json
python scripts/dso_verify.py --repo <clean-base-clone> --pack <DSO-PACK.zip> --qualname fn_a --qualname fn_b --json-out partial-mut.json
```

---

## 二、三態退出碼與總狀態（M4(a) 成功路徑與 CHECK 名稱不變）

| 退出碼 | `overall_status` | 條件與語意 |
|---|---|---|
| `0` | `VERIFIED` | 全部檢核為 `PASS`（不含任何 `FAIL`、`ERROR` 或 `SKIPPED`）且未使用 `--skip-fast`（成功路徑 `DSO_CHECK` 名稱與 `reason_code` 與 v1.0.0 完全不變） |
| `1` | `BLOCKING` | 至少一項檢核為 `FAIL`（如 `SHA256_MISMATCH`、`PATCH_APPLY_FAILED`、`AUTHOR_SHA_MISMATCH`、`ADDED_LINES_VIOLATION`、`FAST_PRECHECK_FAILED`、`MUTANTS_SURVIVED` 或 `PARTIAL_MUTATION_RUN_FORBIDDEN`） |
| `2` | `INCOMPLETE` | 無 `FAIL` 但存在 `ERROR`、`SKIPPED` 或傳入 `--skip-fast`（如 `UNSAFE_ARCHIVE`、`CONTRACT_QUALNAME_STALE`、`FAST_SKIPPED`、`INVALID_ARGS`、`INVALID_TIMEOUT_BUDGET`、`OVERALL_BUDGET_EXCEEDED`、`MUTANT_CAP_EXCEEDED` 等 fail-closed 條件） |

註：`diff_ast_mutate` 檢查強制驗證 `m_doc.get("full_run") is True` 且 `m_doc["summary"].get("full_run") is True`；若不符，於既有 `diff_ast_mutate` 檢查項回 `FAIL` / `PARTIAL_MUTATION_RUN_FORBIDDEN`，不新增或改名任何 `DSO_CHECK`。

---

## 三、安全解壓與路徑衛生（`UNSAFE_ARCHIVE`／`TD-139`）

依第二意見 2026-11-26 與 2026-11-27 定案要求，`validate_archive_entry_name`、`_dir_prefixes_for_casefold` 與 `safe_extract_zip` 強制套用下列上限與拒絕條件（任一成立立即 exit `2`）：

- **資源上限（防 zip bomb）**：最多 `MAX_ZIP_FILES = 200` 項、單檔解壓上限 `MAX_ZIP_SINGLE_BYTES = 10 MiB`（`10,485,760` bytes）、總解壓上限 `MAX_ZIP_TOTAL_BYTES = 50 MiB`（`52,428,800` bytes）；同時檢查標頭宣告大小與串流解壓實際讀出位元組。
- **路徑與檔名禁用規則**：拒絕空字串、控制字元（`< 0x20` 含 NUL）、反斜線 `\`、前導 `/`、任何冒號 `:`（含磁碟代號與 NTFS ADS）、`.`／`..`／空路徑段、重複路徑、大小寫折疊衝突（`casefold()`）、以及**任一路徑段或檔名以空白 `' '` 或句點 `'.'` 結尾**。
- **Windows 保留裝置名（不分大小寫、比對完整段名及第一個句點前主幹）**：`CON`、`PRN`、`AUX`、`NUL`、`COM1`–`COM9`、`LPT1`–`LPT9`、上標保留名 `COM¹`（`\u00b9`）／`COM²`（`\u00b2`）／`COM³`（`\u00b3`）／`LPT¹`／`LPT²`／`LPT³`、`CONIN$`、`CONOUT$`。
- **符號連結與特殊檔**：拒絕 `S_ISLNK`、FIFO／裝置檔等非常規檔案。
- **有界上層目錄前綴與衝突檢查（`TD-139`／R2 N1）**：`_dir_prefixes_for_casefold(cf)` 以 `parts = cf.split("/")` 迭代 `range(1, len(parts))` 枚舉全部非空上層目錄前綴（取代無界 `while parent` 之 `rpartition` 迴圈以根除 `M-57c79f236c`），先檢後寫比對 `file_cfs & dir_prefix_cfs`，命中衝突（如 `a` 與 `a/b`、`A` 與 `a/b`）直接回 exit `2` `UNSAFE_ARCHIVE`；建目錄與開檔過程之 `OSError` 亦一律轉為 `UNSAFE_ARCHIVE`（exit `2`）並寫出報告。

---

## 四、明確契約函式清單（`CONTRACT_QUALNAMES_BY_FILE`）

工具禁止以啟發式推斷關鍵函式，僅查閱明確字典 `CONTRACT_QUALNAMES_BY_FILE`（目前涵蓋 `scripts/dso_verify.py`、`scripts/diff_ast_mutate.py`、`scripts/draft_precheck.py`、`scripts/s1_registry.py`、`scripts/taskboard_archive.py`、`scripts/cap_count.py`、`scripts/audit_packet.py`、`scripts/delivery_pack.py`、`scripts/reply_check.py`）：

1. **過期偵測（`CONTRACT_QUALNAME_STALE`，exit `2`）**：呼叫突變步驟前，`validate_contract_qualnames` 先以 `ast.parse` 掃描該批變更檔；凡存在於 `CONTRACT_QUALNAMES_BY_FILE` 且任一列名質名（qualname）不存在於目標檔案 AST 者，立即以 exit `2` `CONTRACT_QUALNAME_STALE` 中止，不因部分樣式尚可匹配而靜默放行。
2. **`--qualname` 傳遞邊界（#2）**：`dso_verify.py` 僅於(a) 呼叫端明確傳入 `--qualname` 或(b) 本批變更之非測試 Python 檔包含 `scripts/diff_ast_mutate.py` 本身時，才向 `diff_ast_mutate.py` 傳遞 `--qualname`；其餘批次皆跑全量變更行差異突變。

---

## 五、白名單 `canonical_sha256` 與 `content_canonical_sha256`（`4a`）

為使審查官（Windows）與第二意見（Linux）對同一 D-SO 包產出完全相同的規範雜湊，`compute_canonical_sha256` 維持嚴格 **13 欄白名單**（列於 `CANONICAL_INCLUDED_FIELDS`），不納入 `pack_mode`、`content_canonical_sha256`、`mutation.cache`、`elapsed_sec` 與本地路徑：

- 頂層純量：`schema_version`、`tool`、`tool_version`、`base_oid`、`task_id`、`overall_status`、`exit_code`、`skip_fast`、`sorted(qualname_filter)`。
- `inputs`：僅 `*_sha256` 雜湊鍵，不含任何本機路徑。
- `author_manifest`：依 `path` 排序之 `[{"path", "sha256", "match"}]`。
- `checks`：`[{"name", "status", "reason_code"}]`（不含 `elapsed_sec` 與平台計數 `details`）。
- `mutation`：若為 `null` 則維持 `null`；否則僅含 `summary` 之 `total/caught/caught_timeout/survived/accepted/invalid/exit_code/verdict/reason`、`mutants[*]` 之 `{"id", "status"}`（依 `id` 排序），以及排序後之 `stale_accepted`／`unnecessary_accepted`／`out_of_scope_accepted`。
- **`content_canonical_sha256`**：同上述白名單但移除 `inputs["pack_sha256"]`，使目錄模式之 `canonical_sha256 == dir_report["content_canonical_sha256"] == zip_report["content_canonical_sha256"]`。

---

## 六、步驟逾時預算與校準依據（Windows 實測 × 2）

依 `B117-TD136A-MUTATE-QUALNAME-R1-261126` 在原生 Windows 上之實測紀錄：

| 步驟／參數 | Windows 實測基準 | 預設預算 | 設定依據 |
|---|---|---|---|
| `git_clone` | 本地無工作樹 clone＋checkout < 15s | `120s` | 含 Defender／IO 波動裕度 |
| `patch_apply` | `git apply --check --whitespace=error` < 5s | `60s` | 同 `diff_ast_mutate.py` 預設 |
| `fast_precheck` | `30.97s`（`FAST_PRECHECK_PASS`） | `300s` | `> 2 × 30.97s` 並預留 `collect-only` 擴張空間 |
| `diff_ast_mutate_baseline` | `38.8s–42.5s`（單檔）／~`70s`（多檔） | `180s` | `> 2 × 42.5s`（及多檔聚焦基準 × 2）以免誤判 `BASELINE_FAILED` |
| `diff_ast_mutate_per_mutant` | 單突變最大 `41.4s`（`test_diff_ast_mutate` 全組 `-x`） | `180s` | `> 2 × 41.4s` 並涵蓋較慢測試組，避免假性 `CAUGHT_TIMEOUT` |
| `diff_ast_mutate_total` | `TD-136a` 實跑 60 突變約 `280–306s`／高負載預留 `3600s` | `3600s` | 對齊 `TD-136a` 與第 4 關總上限 `3600s` |
| `overall_budget_sec` | 循序四步加總 = `120 + 60 + 300 + 3600 = 4080s` | `4500s` | 強制 invariant：`overall_budget > sum(sequential_steps)`（裕度 `+420s`） |

`verify_pack` 啟動即檢核所有逾時大於 0 且 `overall_budget > git_clone + patch_apply + fast_precheck + diff_ast_mutate_total`，不符即以 exit `2`（`INVALID_TIMEOUT_BUDGET`） fail-closed 中止；並於 `evidence_manifest.runs[*]` 寫入每步實際 `elapsed_sec`。
