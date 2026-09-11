# 批次規格區（Batch Spec Lifecycle）

> 本目錄存放**精確替換批次（EXACT_SPEC）的正式執行契約**。
> 正常重構與功能實作預設採用 **GOAL_SPEC**，不要求產出 Batch Spec，其正確性由單元測試、`verify_all.py` 與遠端 CI 共同守護。
>
> 規格格式的說明見 `scripts/batch_spec_example.txt`，本檔規範 Batch Spec 之生命週期。
> 規則本體在 `.claude/rules/auditor-protocol.md` §6.1 第 21 項，
> 執行者側的對應規則在 `.agents/rules/role-boundaries.md` §6，
> 機械守衛是 `scripts/check_consistency.py` 的 CHECK 17。

---

## 一、批次模式與規格定位（Mode-Aware Specification）

### 1. GOAL_SPEC（正常重構／功能遷移預設）
- **定位**：正常業務重構、模組遷移與 Bug 修復的主流模式。
- **契約**：宏觀審計官定義目標（Goal）、允許範疇（Allowed Scope）、禁止範疇（Forbidden Scope）、不變量（Invariants）與驗收準則（Acceptance Criteria）；執行者具備完整自主性，負責探索、設計、實作、測試與除錯。
- **無強制 Spec**：不要求 Batch Spec，Git commit 紀錄、測試通過輸出與 GitHub Actions 綠燈即為完成證據。
- **CHECK 17 行為**：若 commit 中未附帶規格檔案，CHECK 17 合法跳過重放（由 `verify_all.py` 其他 Gates 守護）。

### 2. EXACT_SPEC（精確字元替換／規範契約重構）
- **定位**：僅用於 byte-exact canonical 文本修改、治理規範與規則層精準調整、或涉及 mechanical replay 必須逐位元完全一致之場景。
- **契約**：批次規格為唯一的 executable artifact。審計官模擬的對象、提示詞傳遞的依據、執行者套用的內容三者共享同一份規格。
- **CHECK 17 行為**：commit 內附帶之規格檔案，CHECK 17 從 parent commit 逐位元嚴格重放比對，確保完全零漂移。

---

## 二、命名

```
docs/batches/<base-hash>-<slug>.spec.txt
```

- `<base-hash>`：本批的 base commit 短 hash（7 碼），
  必須等於規格內 `HEAD:` 欄位，也必須等於本 commit 的 parent。
  **檔名與欄位互為交叉檢查**，兩者不符即代表規格取錯基準。
- `<slug>`：小寫英數與連字號，描述本批做什麼。

---

## 三、一批一 commit

| 情形 | 規則 |
|---|---|
| EXACT_SPEC 一般批次 | 一份規格、一個 commit。規格與該批修改在同一個 commit 內。 |
| 修正批次 | **不是同一批**。開新規格，base 為前一個 commit（即被修正的那一個）。 |
| merge commit | CHECK 17 跳過（parent 數 != 1）。本專案不使用 merge，此為防禦性條款。 |
| 沒有規格的維護 commit | 允許。CHECK 17 輸出 INFO 並跳過，不強迫產生虛假規格。 |
| 一個 commit 兩份規格 | FAIL。無法判定該重放哪一份。 |

---

## 四、CI 如何知道該重放哪一份

CHECK 17 不讀 commit message、不讀任何清單，
它問 git：**本 commit 在 `docs/batches/` 底下新增或修改了哪些 `.spec.txt`**。

```
git diff --name-only <parent> HEAD -- docs/batches/
```

零份 → 跳過；一份 → 重放；兩份以上 → FAIL。
這個對應關係沒有需要人維護的中介物，因此不會過期。

---

## 五、比對範圍

CHECK 17 同時驗三件事，缺一不可：

1. **宣告的修改是否正確重放** — 每個 MOD 目標檔案，重放結果 encode UTF-8 後
   與實際 commit 的 git blob **原始位元組**直接比對。取 blob 不經文字模式，
   否則 CRLF 與 LF 兩個不同的 blob 會被 Python 正規化成同一個字串。
   base 的比對走完整 commit OID，不使用前綴或 startswith。
2. **未宣告的修改是否存在** — `parent..HEAD` 的實際異動檔案集合，
   不得超出 `{MOD 宣告的檔案} ∪ {本規格檔} ∪ 豁免集`。
3. **豁免檔是否只被追加** — 刪除行數由 `git diff --numstat` 直接取得，
   > 0 即 FAIL。不自行解析 unified diff 的行首：內容本身就是 `---` 的那一行
   會與 diff 檔頭標記混淆，靠字首判定一定會漏。

豁免集只有兩個，且理由必須成立：

| 檔案 | 為什麼不能以 MOD 表達 |
|---|---|
| `docs/EXEC-LOG.md` | 內容是執行者自己的檢查結果，審計官寫規格時還不存在 |
| `docs/fingerprints/exec-latest.json` | 由 `scripts/fingerprint.py` 產生，另由 `--verify` 守 |

**豁免是刻意保留的缺口，不是遺漏**，登錄為 `docs/TASKBOARD.md` B-92 待觀察。

---

## 六、create_file 模式與 BOOTSTRAP 例外退役

自 B-90 起，批次規格原生支援 `create_file` 模式，可完整以宣告式表達建立新檔：

### 1. `create_file` 規格語意與約束
- **MODE**：宣告 `mode: create_file`。
- **FILE**：指定 repo 相對路徑。
- **ANCHOR**：新建檔案不使用既存錨點，`--- ANCHOR ---` 區塊可省略；若存在，內容必須為空。非空錨點將被拒絕。
- **PAYLOAD**：代表新檔案的完整內容（非追加片段）。
- **基準不變量（Base Invariant）**：目標檔案在 parent / base commit 必須不存在；若已存在則 FAIL（禁止 fallback 為 replace）。
- **重放不變量（Result Invariant）**：apply 後該檔案必須存在，且 HEAD blob 位元組與 payload UTF-8 編碼逐位元相符。
- **排他約束**：同一 spec 中不得對同一路徑重複 create_file，亦不得混用不同模式。

### 2. BOOTSTRAP 歷史例外退役
隨著 `create_file` 模式上線，原針對新建檔案設立的 `-BOOTSTRAP.spec.txt` 跳過重放機制與「全庫至多一份 BOOTSTRAP」之 runtime invariant 已全面移除。
歷史檔案 `0e13c85-spec-lifecycle-BOOTSTRAP.spec.txt` 作為歷史 artifact 安全保留於版控中，不再具有任何 replay-bypass 語意。所有進入 CHECK 17 強制範圍之規格一律按正常批次執行逐位元重放。

### 3. 目標路徑安全防護（Path Confinement）
所有模式的 `FILE` 欄位均強制遵守確定性路徑邊界限制（Fail-Closed）：
- **嚴格相對路徑**：必須為相對於 repository 根目錄之 POSIX 相對路徑。
- **禁止穿透與絕對路徑**：嚴禁包含 `..` 穿透片段、絕對路徑（`/` 或 `\` 開頭）、Windows 磁碟機路徑（`C:` 等）、UNC 路徑（`\\` 或 `//`）、NUL 字元或目錄斜線結尾。
- **全生命週期防護**：`parse_spec`、錨點驗證、BPE 模擬沙盒、以及 CHECK 17 重放比對共享同一套確定性限制，確保任意惡意路徑均無法逃脫 repository 根目錄。
