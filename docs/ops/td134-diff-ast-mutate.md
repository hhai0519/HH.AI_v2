# TD-134／TD-144a：差異範圍確定性 AST 突變工具（`scripts/diff_ast_mutate.py`）

> 本文件定義 `scripts/diff_ast_mutate.py`（`TOOL_VERSION=1.2.0`、`SCHEMA_VERSION=1`）之操作契約、14 項確定性 AST 突變運算子、無偏移突變 ID、豁免檔 `--accept`、測試映射 `--test-map`、平行執行 `--workers`、等時限單執行緒重試（M2）、內容定址快取 `--cache-dir`（M3）、開發用 `--only-survived-from` 與退出碼及 JSON Schema v1。工具僅依賴 Python 3.14 標準函式庫與同目錄 `bounded_process.py`（`run_bounded`），不引入任何外部套件，嚴格唯讀對待呼叫端倉庫。

---

## 一、定位與 P0 #1 流程整合

依 2026-11-25 啟用之 P0 第 1 項「快→複核→完整」流程（見 `docs/ops/q2-draft-precheck.md`）：

1. 審查官作者化程式／驗證器修改後，執行 `scripts/draft_precheck.py --fast`、定向測試、4 環境輸出形式矩陣及 `scripts/diff_ast_mutate.py`（自動對本批 diff 行執行 AST 突變）。
2. 工具自動產出 `SURVIVED` 與 `ACCEPTED` 清單、`scope.touched_qualnames`／`scope.qualname_counts` 及固定格式 JSON 報告，供 D-SO 第二意見複核與後續 `scripts/dso_verify.py` 直接消費，取代每批手調整行號之手寫突變腳本。
3. 預設只對變更的**非測試 Python 檔**（排除 `tests/` 與 `test_*.py` / `*_test.py`）且**有改動之程式碼行**建立突變；若需檢查測試或特定檔案，可傳入 `--include-glob` 或 `--files`。

---

## 二、常用命令列、平行執行、快取與大型新模組處置程序

為壓縮 Windows 上逐突變執行時間，建議 `--test-cmd` 固定搭配 `-x`（首錯即停）與 `-p no:cacheprovider`，並於多檔異動時搭配 `--test-map` 只跑受影響測試：

```text
python scripts/diff_ast_mutate.py --repo <repo> --base <base_oid> --list --json-out mutants.json
python scripts/diff_ast_mutate.py --repo <repo> --files scripts/diff_ast_mutate.py --qualname _matches_qualname --qualname load_accept_file --test-cmd "{python} -m pytest -p no:cacheprovider -q -x scripts/tests/test_diff_ast_mutate.py" --json-out mutate-report.json
python scripts/diff_ast_mutate.py --repo <repo> --base <base_oid> --workers auto --cache-dir C:\hhaud\mutate_cache --test-cmd "{python} -m pytest -p no:cacheprovider -q -x" --test-map map.json --json-out mutate-report.json
python scripts/diff_ast_mutate.py --repo <repo> --base <base_oid> --only-survived-from mutate-report.json --test-cmd "{python} -m pytest -p no:cacheprovider -q -x" --json-out dev-rerun.json
```

### `--workers` 平行突變與同電腦共處規則（S2）

- `--workers <1..8|auto>`（預設 `"1"`）：`"auto"` 解析為 `min(4, max(1, (os.cpu_count() or 2) // 2))`；非 `"auto"` 且超出 `1..8` 或為空即回傳退出碼 `2`（`INVALID_ARGS`）。
- 平行池於先在乾淨 `work_w0` 通過基線後建立 `W = min(workers, len(selected_mutants))` 份各自獨立隔離複本 `work_w{0..W-1}` 與暫存目錄 `tmp_w{0..W-1}`；每個子行程強制設定 `TEMP=TMP=tmp_w{slot}`、`PYTHONDONTWRITEBYTECODE=1`，並於 pytest 命令未自帶 `--basetemp` 時自動插入 `--basetemp <tmp_w{slot}/bt>`。
- 回報結果嚴格依原決定性收集順序 `0..N-1` 組裝，`unnecessary_accepted` 嚴格排序，故 `workers=1` 與 `workers=N` 之突變清單順序與 `dso_verify` `canonical_sha256` 完全一致。
- **防 Canonical 漂移之等時限單執行緒重試（M2）**：平行池結束、所有並行工作靜止後，對平行階段回報 `timed_out == True` 之突變於單執行緒 `work_w0` 重驗，並**嚴格維持相同的 `per_mutant_timeout`（絕不放寬倍率）**，避免高負載假超時同時保證與 `--workers 1` 逾時邊界語意完全等價；仍逾時者維持 `CAUGHT_TIMEOUT`（重測項目記 `retried_single_threaded: true`）。
- **同電腦資源守衛（S2）**：於本機（例如同主機執行 W2）當 Executor `scripts/batch_runner.py` 正在執行中（可於 Dashboard 狀態確認），審查官**嚴禁使用 `--workers > 1`**，避免與第 4 關搶奪 CPU 導致誤逾時。

### `--only-survived-from` 開發迭代與 `full_run=true` 交付鐵律（S5）

- `--only-survived-from <report.json>` 僅限本機開發除錯重跑上次 `SURVIVED` 之突變；不得與 `--list` 或 `--cache-dir` 併用（併用一律 exit `2` `INVALID_ARGS`）。
- 載入來源報告時強制執行 **S5 全量核對**：必須為 `mode="run"`、`tool_sha256` 一致、`scope.kind`／`scope.base_oid`／`sorted(scope.changed_files)`／`sorted(scope.qualname_filter)` 全同且來源全體 mutant ID 均存在於本次收集目錄，任一不符即以退出碼 `2`（`SURVIVED_SOURCE_INVALID`）中止；無 `SURVIVED` 可跑則回 `PASS_NO_MUTANTS`（exit `0`）。
- `--only-survived-from` 執行時報告頂層與 `summary` 固定標註 `"full_run": false`（且 CLI 摘要列印 `full_run=false`）；未使用時固定為 `"full_run": true`。正式審查與 D-SO 交付**嚴禁**使用 `--only-survived-from`，`dso_verify.py` 遇 `full_run is not True` 直接判 `FAIL`（`PARTIAL_MUTATION_RUN_FORBIDDEN`）。

### `--cache-dir` 內容定址快取契約（M3）

- `--cache-dir <dir>` 預設關閉；啟用時 `<dir>` **必須位於 `--repo` 與 `--work-parent`／W2／D-SO PACK 目錄之外**（若位於 `--repo` 內或為檔案，立即以 exit `2` `INVALID_ARGS` 中止），且快取目錄內容**嚴禁**納入任何 D-SO PACK。
- 快取鍵 `cache_key` 為確定性 JSON 之 SHA-256，強制納入：`schema_version`、`scope_kind`、解析後 `base_oid`、範圍內全部作者檔 LF SHA-256、全部關聯測試檔／`conftest.py`／diff 其他 `.py` 檔 LF SHA-256（含 `--patch` 套用後內容）、`sorted(qualnames)`、`--test-map` 與 `--accept` LF SHA-256、正規化 `test_cmd` 模板、`max_mutants`、`per_mutant_timeout`、`include_glob`/`exclude_glob`、`diff_ast_mutate.py` 自身 LF SHA-256、選用 `--caller-tool-sha256`、`python_version`、`sys_platform`、**（M3(a)）依賴指紋（`uv.lock`/`requirements.txt`/`pyproject.toml` SHA-256 及 `importlib.metadata` 全部已安裝套件名稱與版本 SHA-256，涵蓋 `pytest` 與外掛）**，以及 **（M3(b)）編碼與環境設定（`PYTHONUTF8`、`PYTHONIOENCODING`、`PYTHONHASHSEED`、`PYTEST_ADDOPTS`、`locale.getpreferredencoding(False)`、`sys.getfilesystemencoding()`）**。
- 僅於 `full_run=true`、`exit_code in (0, 1)` 且非 `--list` 時以暫存檔＋`os.replace` 原子寫入 `<cache_dir>/<cache_key>.json`（含 `source_report_sha256`）；命中時須通過鍵值與 `source_report_sha256` 雙重驗證，任一異常視為 miss 並覆寫。

### `--qualname` 精準子集過濾（`TD-136a`）與大型新模組處置程序（R1 D-SO N1）

預設 `--max-mutants 120` 與 `--total-timeout 900` 係針對增量 diff 批設計，超限一律 fail-closed（exit 2，`MUTANT_CAP_EXCEEDED`／`TOTAL_TIMEOUT_EXCEEDED`）。對新增大型獨立模組幾乎必觸及預設上限，應依下列固定程序與 `--qualname` 子集介面處置：

1. **先 `--list`**：執行 `--list` 取得總突變數與 `scope.touched_qualnames`／`qualname_counts`（依全量突變統計，不受 `--qualname` 抹除），並確認 `invalid=0`。
2. **以 `--include-glob`／`--qualname`／`--test-map` 拆分執行**：可重複傳入 `--qualname PATTERN`（使用大小寫敏感之 `fnmatch.fnmatchcase` 比對 `MutantCandidate.qualname`，多樣式取聯集），將多檔或單一大檔拆為高風險函式受控子集。過濾發生於完整 AST 掃描與 `_next_occ` 計數**之後**且在 `--max-mutants` 上限與 `--test-map` 解析**之前**。
3. **Fail-Closed 空白與零匹配契約**：傳入空字串／純空白 `--qualname` 回傳退出碼 `2`（`INVALID_ARGS`）；有傳 `--qualname` 但過濾後候選數為 `0`（即使原始 diff 本身為 0 突變）一律強制回傳退出碼 `2`（`QUALNAME_UNMATCHED`）。
4. **提高上限／估算總逾時**：若確實需要調高 `--max-mutants` 或 `--total-timeout`，須於當批交付／複核報告明確記錄實際設定數值與理由。

### 時鐘抽象與可注入性（`TD-137`）

`execute_mutation_run(...)` 透過模組預設 `_DEFAULT_MONOTONIC`（預設指向 `time.monotonic`）或可選參數 `monotonic_fn` 計時；除 `_DEFAULT_MONOTONIC = time.monotonic` 一處綁定外，全檔不直接呼叫 `time.monotonic()`，測試端得以區域 `FakeClock` 驗證逾時契約而無 `StopIteration` 風險或污染全域 `time.monotonic`。

---

## 三、14 項確定性 AST 突變運算子與雜訊過濾

### 3.1 運算子清冊

| 編號 | 運算子代碼 | 目標 AST 節點 | 突變轉換 | 備註 |
|---|---|---|---|---|
| 1 | `CMP_EQ_NE` | `ast.Compare` (`==`, `!=`) | `==` ↔ `!=` | 使用 `ast` byte-span 間隙精準替換 |
| 2 | `CMP_BOUNDARY` | `ast.Compare` (`<`, `<=`, `>`, `>=`) | `<` ↔ `<=`、`>` ↔ `>=` | 捕捉邊界 off-by-one |
| 3 | `CMP_IN_NOTIN` | `ast.Compare` (`in`, `not in`) | `in` ↔ `not in` | — |
| 4 | `CMP_IS_ISNOT` | `ast.Compare` (`is`, `is not`) | `is` ↔ `is not` | — |
| 5 | `BOOL_AND_OR` | `ast.BoolOp` | `and` ↔ `or` | 視外層需要加上括號維持優先序 |
| 6 | `BOOL_DROP_OPERAND` | `ast.BoolOp` | `And` 各運算元單獨換為 `True`；`Or` 各運算元單獨換為 `False` | 精準抓出未被測試覆蓋的子條件 |
| 7 | `UNARY_DROP_NOT` | `ast.UnaryOp(Not)` | `not x` → `x`（複合式保留括號） | — |
| 8 | `IF_COND_FALSE` | `ast.If.test`, `IfExp.test`, `While.test` | 直接替換為 `False` | 必改涵蓋單一條件守衛（如 `if x == 0:`）；絕不將 `While.test` 改為 `True` |
| 9 | `IF_NEGATE_COND` | `ast.If.test`, `IfExp.test` | 改寫為 `not (<test>)` | 對非 `Compare`／非 `Not`／非布林常數條件提供反向測試（絕不套用於 `While.test`） |
| 10 | `CONST_BOOL_FLIP` | `ast.Constant(bool)` | `True` ↔ `False` | 避開已由 `IF_COND_FALSE` 處理之頂層條件與 `While.test` `False→True` |
| 11 | `CONST_INT_DELTA` | `ast.Constant(int)`（不含 `bool`） | `0→1`、`1→0`、其餘 `n→n+1` | — |
| 12 | `RET_NONE_OR_EMPTY` | `ast.Return(value!=None)` | 改寫為 `return None` | 跳過本即 `return` 或 `return None` |
| 13 | `AUG_OR_BIN_ARITH` | `ast.BinOp`／`AugAssign` (`+`, `-`, `+=`, `-=`) | `+` ↔ `-`、`+=` ↔ `-=` | 跳過含字串、`bytes` 或 `JoinedStr` 運算元之加法 |
| 14 | `STMT_CALL_DELETE` | 獨立 `ast.Expr(Call)` 敘述 | 替換為 `pass`（保留縮排） | 捕捉「已檢查條件卻漏寫記錄呼叫」；跳過 `print`／`logging`／`logger`／`warnings.warn` |

### 3.2 雜訊過濾與範圍精準度

- **跳過雜訊節點（計入 `skipped_nodes`）**：模組／類別／函式文件字串（docstring）、型別註記（annotation）與 `if TYPE_CHECKING:` 區塊、`if __name__ == "__main__":` 區塊、`raise ...` 引數、`print`／`logging.*`／`logger.*`／`log.*`／`warnings.warn` 呼叫。
- **不改動外層未變更 `if` 條件**：條件突變（`IF_COND_FALSE`／`IF_NEGATE_COND`）僅比對 `test.lineno..test.end_lineno`，即使 `if` 區塊內文有變更行，只要條件表頭行本身未變即不突變。
- **預設排除字串／正規式常數（INFO）**：字串與正規表示式常數預設不納入突變清單以避免高雜訊與等價假警報；涉及正規式或格式驗證器之批次，仍應以針對性單元正反例測試補齊。
- **上限 fail-closed**：預設 `--max-mutants 120`；超過上限立即以退出碼 `2`（`MUTANT_CAP_EXCEEDED`）中止，**絕不靜默截斷**。

---

## 四、無偏移穩定突變 ID、隔離複本與豁免／映射檔

### 4.1 無偏移穩定 ID（Offset-Free Mutant ID）

- 嚴禁納入行號或位元組偏移，避免前文增刪空白、註解或輔助函式時 ID 漂移。
- 掃描整份檔案 AST 時，在同一個 `(rel_path, qualname)` 作用域內依固定前序遍歷對每個 `(op, ast.unparse(orig))` 累計 1-based 出現序號 `occ_idx`，並以 `ast.unparse` 正規化原式與突變式：
  - `id = "M-" + sha256(f"{rel_path}\n{qualname}\n{op}\n{norm_orig}\n{norm_mut}\n{occ_idx}")[:10]`
  - `display_id = f"{rel_path}::{qualname}::{op}#{occ_idx}"`

### 4.2 保留 `.git` 隔離複本與先跑基線（Fail-Closed）

- 工具於 `TEMP`／`--work-parent` 建立唯一隔離目錄，透過 `git clone --no-local --template=` 完整保留 `.git` 後套用工作樹變更／`--target`／`--patch`，呼叫端倉庫全程完全唯讀。
- 執行基線與每個突變子行程均強制設定 `PYTHONDONTWRITEBYTECODE=1`，防止相同長度與同秒 `mtime` 之快速突變讀取過期 `.pyc` 快取（stale bytecode）。
- 執行突變前**先跑 `--test-cmd` 基線測試**；若基線非零退出、逾時或啟動失敗，立即以退出碼 `2`（`BASELINE_FAILED`）失敗，執行 `0` 個突變，絕不把基礎環境壞掉（例如缺 `.git`）誤算為 `CAUGHT`。
- 每個突變寫入後均在 `try...finally` 還原原位元組並以 SHA-256 雙重核對一致。

### 4.3 豁免檔（`--accept FILE`）

```json
{
  "schema_version": 1,
  "accepted": [
    {
      "id": "M-1234567890",
      "reason": "Equivalent mutant: short-circuit preserves invariant",
      "batch": "B117-EXAMPLE-R1-261125"
    }
  ]
}
```

- 命中 `--accept` 之 `SURVIVED` 突變分類為 `ACCEPTED`（單獨計數與列印），不導致退出碼 `1`。
- **過期項 fail-closed（`ACCEPT_STALE_ENTRIES`）**：若 `--accept` 中出現任何於**過濾前完整 diff 收集清冊**皆找不到的無效 ID，無論 `--list` 或正式執行一律以退出碼 `2`（`ACCEPT_STALE_ENTRIES`）失敗，並列出 `stale_accepted`。
- **`--qualname` 子集外豁免（`out_of_scope_accepted`）**：搭配 `--qualname` 執行時，存在於過濾前完整 diff 清冊、但落於本次 `--qualname` 子集之外的合法 `--accept` ID 不會誤判為 `ACCEPT_STALE_ENTRIES`，而是獨立記於 `out_of_scope_accepted` 並於 CLI 輸出 `OUT_OF_SCOPE_ACCEPTED`；若混含真正無效之 ID，仍以 `ACCEPT_STALE_ENTRIES` 退出碼 `2` fail-closed（同時保留 `out_of_scope_accepted` 明細）。
- 若已列於 `--accept` 之突變實測已被既有測試殺死（`CAUGHT` 或 `CAUGHT_TIMEOUT`），仍如實歸類為 `CAUGHT`／`CAUGHT_TIMEOUT`，其 ID 列於 `unnecessary_accepted` 供清理，且 `accept_reason`／`accept_batch` 維持 `null`。

### 4.4 測試映射檔（`--test-map FILE`）

```json
{
  "schema_version": 1,
  "map": {
    "scripts/foo.py": ["scripts/tests/test_foo.py"],
    "scripts/sub_*.py": ["scripts/tests/test_sub.py"]
  },
  "default": ["scripts/tests/test_fallback.py"]
}
```

- 基線執行範圍內所有對應測試之聯集；每個突變僅執行所屬檔案對應測試（可透過 `{tests}` 佔位符插入 `--test-cmd`，未寫則附於命令尾端）。未命中 `map` 且未設 `default` 時立即以退出碼 `2`（`TEST_MAP_UNMAPPED`）失敗。

---

## 五、退出碼與 JSON Schema v1（`TD-136` 相依契約）

| 退出碼 | 狀態 | 典型 `reason` |
|---|---|---|
| `0` | 通過或 dry-run | `OK`、`NO_MUTANTS`、`LIST_OK` |
| `1` | 有未豁免之 `SURVIVED` 突變 | `MUTANTS_SURVIVED` |
| `2` | Fail-Closed 錯誤 | `BASELINE_FAILED`、`MUTANT_CAP_EXCEEDED`、`ACCEPT_FILE_INVALID`、`ACCEPT_STALE_ENTRIES`、`TEST_MAP_INVALID`、`TEST_MAP_UNMAPPED`、`QUALNAME_UNMATCHED`、`SURVIVED_SOURCE_INVALID`、`TOTAL_TIMEOUT_EXCEEDED`、`MUTANT_SYNTAX_INVALID`、`RESTORE_FAILED`、`INVALID_ARGS`、`GIT_ERROR`、`PATCH_ERROR`、`TEST_LAUNCH_ERROR`、`TARGET_PARSE_ERROR` |

### 退出碼 2（Fail-Closed）判定優先序（`diff_ast_mutate.py 1.2.0`）

當執行期間同時滿足多個錯誤條件時，`execute_mutation_run` 依下列嚴格決定性順序回報最優先之 `reason`（由 `scripts/tests/test_diff_ast_mutate.py::test_n1_exit2_precedence_order` 表格驅動測試機械鎖定）：

`INVALID_ARGS`（`--qualname` 空白或非字串／`--workers`／`--caller-tool-sha256`／互斥參數／`--cache-dir` 位置）→ `ACCEPT_FILE_INVALID` → `TEST_MAP_INVALID` → `INVALID_ARGS`（缺 `--test-cmd`）→ `GIT_ERROR`／`PATCH_ERROR` → `TARGET_PARSE_ERROR` → `QUALNAME_UNMATCHED` → `ACCEPT_STALE_ENTRIES` → `TEST_MAP_UNMAPPED` → `MUTANT_CAP_EXCEEDED` → `MUTANT_SYNTAX_INVALID` → `SURVIVED_SOURCE_INVALID` → `BASELINE_FAILED` → 逐突變：`TOTAL_TIMEOUT_EXCEEDED` →（執行）→ `RESTORE_FAILED` → `TEST_LAUNCH_ERROR`。

`--json-out` 產出之穩定 JSON Schema v1（`schema_version: 1`）：

```json
{
  "schema_version": 1,
  "tool": "diff_ast_mutate.py",
  "tool_version": "1.2.0",
  "tool_sha256": "<64-hex>",
  "mode": "list | run",
  "full_run": true,
  "workers": 1,
  "cache": {
    "enabled": false,
    "hit": false,
    "cache_key": null,
    "source_report_sha256": null
  },
  "scope": {
    "kind": "git_diff | patch | files",
    "base": "<ref|null>",
    "base_oid": "<40-hex|null>",
    "target": "<ref|null>",
    "patch": "<path|null>",
    "files": ["..."],
    "include_glob": ["..."],
    "changed_files": ["..."],
    "qualname_filter": ["..."],
    "touched_qualnames": ["..."],
    "qualname_counts": {}
  },
  "baseline": {
    "executed": true,
    "rc": 0,
    "elapsed_sec": 0.42,
    "timed_out": false,
    "cmd": ["..."]
  },
  "summary": {
    "total": 10,
    "caught": 9,
    "caught_timeout": 0,
    "survived": 0,
    "accepted": 1,
    "invalid": 0,
    "skipped_nodes": 3,
    "stale_accepted_count": 0,
    "unnecessary_accepted_count": 0,
    "out_of_scope_accepted_count": 0,
    "full_run": true,
    "exit_code": 0,
    "verdict": "PASS | PASS_NO_MUTANTS | FAIL | ERROR",
    "reason": "OK"
  },
  "stale_accepted": [],
  "unnecessary_accepted": [],
  "out_of_scope_accepted": [],
  "mutants": [
    {
      "id": "M-0123456789",
      "display_id": "scripts/foo.py::func::CMP_EQ_NE#1",
      "file": "scripts/foo.py",
      "qualname": "func",
      "lineno": 42,
      "end_lineno": 42,
      "col_offset": 11,
      "op": "CMP_EQ_NE",
      "original": "x == 0",
      "mutated": "x != 0",
      "status": "LISTED | CAUGHT | CAUGHT_TIMEOUT | SURVIVED | ACCEPTED | NOT_RUN",
      "rc": 1,
      "elapsed_sec": 0.35,
      "retried_single_threaded": false,
      "accept_reason": null,
      "accept_batch": null
    }
  ]
}
```
