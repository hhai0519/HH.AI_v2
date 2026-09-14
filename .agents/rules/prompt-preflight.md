# 提示詞前置驗證規範（Prompt Preflight Protocol）

本規則定義執行者（Antigravity IDE Agent）在執行任何提示詞前的機械前置驗證程序。

---

## 1. 為什麼有這一條

`docs/adr/0007-macro-auditor-role.md` 立論為「執行者不能審自己」，對稱原則是「審計官也不能審自己」。本規則建立執行者端對提示詞結構的機械前置驗證機制，防止錯誤或不完整指令進入執行。

---

## 2. 這是審查，不是建議

收到提示詞後，**在執行任何修改前**，先對提示詞做結構檢查。未通過即停機回報，不猜測、不補齊。

| 本規則機械檢查 | 非本規則語意判斷 |
|---|---|
| 提示詞是否有 `git pull origin main` | 這批該不該做 |
| 錨點字串在目標檔案出現次數 | 錨點選得好不好 |
| 是否要求更新交接區與狀態領域 | 交接區該寫什麼 |

遇到疑慮依 `.agents/rules/role-boundaries.md` §7 分流（M1/M2/M3 自主處理），僅未授權之 S1 決策才停機回報。

### 2.1 最前置硬規則：Prompt Manifest 機械驗證（Hard Rule）

任何 repo mutation 前，必須執行：
1. 取得完整 incoming prompt 原文。
2. 以 ephemeral / scratch 檔案或 stdin 餵給：`python scripts/validate_prompt_manifest.py`。
3. 若 exit != 0：立即判定為 `PROMPT STRUCTURE ERROR`，停止執行並回報錯誤，**不得進行任何 repo mutation**。
4. 若 exit == 0：才進入後續既有語意與機械前置檢查流程。

本驗證器不取代現有 M1/M2/M3/S1 錯誤路由；它將第一層提示詞結構檢驗從 Agent 記憶移至確定性程式碼。


### 2.2 依賴閉包機械重放（Dependency Closure Replay Hard Rule）

若提示詞宣告 E24 = PASS 且依賴模式為 `mode = REQUIRED`，執行者在任何 repo mutation 前必須以 `python scripts/impact_scan.py --check <evidence>` 執行獨立重放比對：
1. 缺依賴證據或 JSON 格式錯誤：判定為 `PROMPT STRUCTURE ERROR`，停止執行。
2. 掃描重放比對不符（有漏掃或幽靈依賴）：停機判定為 `S1 DEPENDENCY_DRIFT`。
3. 任何依賴項未聲明 disposition：停機判定為 `S1 DEPENDENCY_DRIFT`。
4. 標註為 `UPDATE` 之依賴項未列入本批 Allowed Scope：停機判定為 `S1 DEPENDENCY_SCOPE_MISSING`。
5. 實作中證明 `VERIFY_ONLY` 依賴實際必須修改：不得擅自修改，停機判定為 `S1 DEPENDENCY_SCOPE_EXPANSION`。
執行者僅驗證確定性機器證據與 Allowed Scope 配對，絕對不得對審計官之 disposition 進行語意重複審查。

---

## 3. 必要結構元素（缺一即停，Mode-Aware）

收到提示詞後，首先檢查批次模式宣告：
- **若未宣告 `batch_mode`**：判定為 `PROMPT STRUCTURE ERROR`（缺少模式宣告），立即停機回報，嚴禁默認 EXACT_SPEC。

### 3.0A 所有模式共同必備要素（缺一即停）

| # | 元素 | 判準 |
|---|---|---|
| 1 | 執行者身分宣告 | 開頭有「你是本專案的執行者」或等義身分界定 |
| 2 | 基準與工作區確認 | 載明基準 commit full OID，並要求確認工作區乾淨（working tree clean） |
| 3 | 批次模式宣告 | 明確宣告 `batch_mode: GOAL_SPEC` 或 `batch_mode: EXACT_SPEC` |
| 4 | 目標與邊界 | 載明 Goal、Allowed Scope、Forbidden Scope 與 Acceptance Criteria |
| 5 | 確定性驗證閘門 | 載明標準驗證指令與 Gate 清單（如 `verify_all.py`）；不得以手寫行數等衍生值作 blocking truth |
| 6 | `git add` 明確路徑 | 明確禁止 `git add -A` 或 `.`，採逐檔明確路徑提交。GOAL_SPEC 實際路徑由執行者自 diff 產生；EXACT_SPEC 依規格 targets |
| 7 | 破壞性操作防護 | 明確禁止未授權之 force push、reset --hard 或歷史重寫 |
| 8 | 遠端健康查驗 | 包含執行後查驗 GitHub Actions exact SHA 綠燈之要求 |
| 9 | Material Finding 處置 | 必須宣告 `FINDING_DISPOSITION`（NONE / CURRENT <ID> / EXISTING <ID> / NEW <ID>，見 §3.9） |

### 3.0B EXACT_SPEC 專屬必備要素（僅在 EXACT_SPEC 模式下檢查）

| # | 元素 | 判準 |
|---|---|---|
| E-1 | 批次規格路徑 | 載明 `docs/batches/<base-hash>-<slug>.spec.txt` 路徑 |
| E-2 | 規格 SHA-256 | 載明該規格檔案之 exact SHA-256 校驗碼 |
| E-3 | 錨點唯一性 | 規格中所有錨點經 BPE 驗證在 base commit 中 count == 1 |
| E-4 | 規格重放守衛 | 明確要求經由 CHECK 17 進行 parent commit 逐位元重放比對 |

GOAL_SPEC 模式不得要求 E-1～E-4，其正確性由單元測試、Gate 驗證與 GitHub Actions 守護。缺任何必備項，停機回報缺項。

---

## 3.1 配對規則（缺一即停）

以下成對動作提示詞中必須同時出現，缺一即停：

| 動作 A | 必須配對的動作 B | 理由 |
|---|---|---|
| `git pull origin main` | `git status --porcelain=v1` 為空 | 確保基準乾淨，避免髒檔案混入 |
| `git push origin main` | 檢查 GitHub Actions 綠燈 | push 只是發送，Actions 綠燈才是完成證明 |
| 新增或修改規則檔 | 更新自檢清單（`auditor-selftest.md`） | 規則與自檢必須同步 |
| 聲明某 commit 通過核對 | 更新 `docs/AUDIT-LOG.md` 與交接區 §5.1 | 審計狀態必須雙向留痕 |

審計狀態單一事實來源為 `docs/AUDIT-LOG.md` 裁決 ⇔ `docs/refactor-backlog.md` §5.1 checkpoint。若提示詞宣告某 commit 通過核對，兩者必須同步指向該 commit，防止審計結論漂移。

---

## 3.2 覆蓋規則（缺一即停，Mode-Aware）

### A. GOAL_SPEC 覆蓋鏈

| 項目 | 覆蓋對象 | 判準 |
|---|---|---|
| Allowed Scope | 提示詞目標涉及的所有檔案 | 擬修改檔案必須全數列入 Allowed Scope 白名單 |
| git diff --name-only | Allowed Scope | 實際變更清單必須完全落在 Allowed Scope 內 |
| git add <path> | 實際變更清單 | 提交時必須逐檔明確加入，禁止 `git add -A` 或 `git add .` |
| Required Machine Gates | 本專案 Canonical 驗證標準 | 必須包含 `python scripts/verify_all.py` |

### B. EXACT_SPEC 覆蓋鏈

| 項目 | 覆蓋對象 | 判準 |
|---|---|---|
| 批次規格（Batch Spec） | 提示詞要求的所有修改目標 | 規格檔案必須包含聲明的全部目標檔案 |
| Allowed Scope | 批次規格中的所有檔案 | 規格涉及檔案全數列入 Allowed Scope 白名單 |
| git add 清單 | 規格中 target_file + spec 本身 | git add 必須包含規格中所有目標與規格檔本身 |
| Required Machine Gates | 規格驗證工具 | 包含 BPE、`scripts/verify_all.py` 與 `check_consistency.py` CHECK 17 |

---

## 3.3 遇到疑問而非缺失時

若發現的是實作疑問或非結構性疑慮，屬於判斷，依 `.agents/rules/role-boundaries.md` §7 分流：
1. **M1**（衍生值落差）：自己重新計算、記錄於 `docs/EXEC-LOG.md`、繼續。
2. **M2**（暫態/網路）：重試或確定性回退、繼續。
3. **M3**（Allowed Scope 內實作、測試、Gate/CI 失敗）：自主修復閉環（最多 3 輪）。
4. **偶發性觀察**：不阻礙目標與正確性者，記錄於 `docs/EXEC-LOG.md` 後繼續。
5. **僅有真正 S1 阻擋事項**（base drift、需改 Scope 外路徑、驗收矛盾、破壞性操作、重大決策）→ **停機升級 S1**。格式：`S1 <分類> | evidence / blocker`。

不得因語意好奇、格式喜好或偶發觀察擅自停機消耗 Macro Auditor。

---

## 3.4 審計官自檢聲明的交叉驗證

每份正式生產提示詞必須包含【審計官自檢聲明】區塊，逐項列出 `auditor-selftest.md` E 節結果。**Antigravity 僅負責機械交叉比對，絕對不得進行語意重複審查（semantic re-audit）。**

**執行兩件事：**
1. **確認區塊存在且項目連號無缺**（E1 起遞增）。缺區塊或缺項即停。
2. **對可機械驗證項目做交叉比對**——勾了 ✅ 但實際沒有的，即停機回報。

| 聲明項 | 機械比對方法 |
|---|---|
| E1 身分宣告 | 提示詞開頭有「你是本專案的執行者」或等義敘述 |
| E2 基準與規格識別 | 載明基準 commit full OID（EXACT_SPEC 另需規格/SHA）；GOAL_SPEC 需 base OID 與 Allowed Scope，不要求規格與手寫行數 |
| E3 錨點原文定位 | EXACT_SPEC 附 structural anchor 原文；GOAL_SPEC 僅定義目標、邊界與驗收準則，不要求錨點 |
| E4 機器驗證證據落地 | 要求執行 Required Machine Gates 且證據寫入 docs/EXEC-LOG.md / GitHub，未要求對話貼完整 Gate 輸出 |
| E5 `git add` 明確路徑 | 有禁止 `git add -A` / `.` 禁令。GOAL_SPEC 依 diff 逐檔 add；EXACT_SPEC 依規格 targets |
| E6 結尾格式 | 要求純文字回覆與固定署名行 |
| E7 回報通道約束 | 未要求正常成功批次貼出 full diff / full file / terminal dump，遵守 Repo Evidence Channel |
| E8 三項狀態領域處置 | 明確聲明交接區、TASKBOARD 與 AUDIT-LOG 三項處置（UPDATE 或 NO CHANGE 附理由；無新結論時 AUDIT-LOG 宣告 NO CHANGE） |
| E9 `git pull` | 有 `git pull origin main` 且指明預期 HEAD |
| E10 零命中自身檢查 | 若有「字串 X 應為零命中」，檢查 X 是否出現在提示詞自身其他位置——純字串比對 |
| E11 錨點唯一性驗證 | EXACT_SPEC 檢查：套用前驗證錨點 count == 1；GOAL_SPEC 為 N/A |
| E12 動手前必讀 | 要求讀取規則檔或執行基準前置檢查 |
| E13 配對與覆蓋 | 依 §3.1、§3.2 比對。GOAL_SPEC 比對 Allowed Scope ↔ actual diff ↔ explicit git add ↔ gates；EXACT_SPEC 比對 spec ↔ git add |
| E14 自檢聲明區塊 | 區塊存在且項目連號無缺 |
| E15 錨點基準來源 | EXACT_SPEC 檢查錨點對應 base commit 與規格上下文；GOAL_SPEC 為 N/A |
| E16 跨檔引用同行 | 寫入文字中跨檔 `§X.Y` 檔名與章節號在同一行；target 存在且未被 substitution，歷史引用寫 archive 路徑 |
| E17 結構序列驗收 | 涉及結構變更附明確驗收準則；不得將衍生序列當作通用 blocking 條件 |
| E18 機械前置證據 | 包含 base full OID、batch mode、Allowed Scope 與標準驗證指令；EXACT_SPEC 額外要求 spec path 與 SHA |
| E19 移除前複查 | 若含刪除檔案／章節／規則／看板項目，檢查是否附三步複查結果（純存在性比對） |
| E20 規則層模擬授權 | EXACT_SPEC 規則層變更經 BPE 與 check_consistency 模擬；GOAL_SPEC 由測試與 Gate 守護 |
| E21 衍生數值不作 blocking truth | 基準 commit 與實測一致；machine-derived values 由工具產出，不得抄為 blocking truth |
| E22 審計狀態權威檢查 | 未要求建立 audited tag；審計狀態以 AUDIT-LOG、refactor-backlog §5.1 與 GitHub Actions 為 SSOT |
| E23 批次規格進 repo | EXACT_SPEC 附規格路徑與 sha256 且列入 git add；GOAL_SPEC 不要求規格進 repo |
| E24 依賴閉包檢驗 | 若宣告 E24 = PASS 且 mode=REQUIRED，mutation 前重跑 impact_scan replay 比對；缺證據或格式錯為 PROMPT STRUCTURE ERROR；replay 不符／缺處置／UPDATE 未進 Allowed Scope 為 S1 DEPENDENCY_* |

**自檢聲明不接受任何豁免。** 比對為「否」時一律停止回報，標為 ⚠️ 或「刻意不做」均不構成豁免。偏離規則之唯一合法路徑為先行開批修改規則本身。

---

## 3.5 執行者檢查證據持久化（已落地）

執行者前置檢查證據已由 §3.8 規範並落地至 `docs/EXEC-LOG.md`，由 CHECK 16 機械守護；本節保留標題序號。

---

## 3.6 機械前置證據（Machine Evidence / Execution Preflight）的交叉驗證

每份提示詞必須包含【機械前置證據】（Preflight Evidence）區塊，內容包含：
1. (a) 基準 Commit Full OID
2. (b) 批次模式（`batch_mode`：`EXACT_SPEC` 或 `GOAL_SPEC`）
3. (c) 批次規格路徑與 SHA-256（僅 EXACT_SPEC 必備；GOAL_SPEC 不要求）
4. (d) 允許修改範圍（Allowed Scope 白名單）
5. (e) 標準驗證指令與 Gate 清單（canonical validation commands）

五項機械比對：
- **證據區塊存在**：缺區塊或缺任一必備元素即停
- **基準 OID 一致**：實測第 0 步 HEAD 等於宣告之 base OID
- **批次模式合法**：確認 `batch_mode` 宣告且符合契約
- **規格 SHA 一致**：僅 EXACT_SPEC 檢查規格 sha256 與宣稱值一致；GOAL_SPEC 為 N/A
- **範圍與驗證指令齊備**：修改目標完全落在 Allowed Scope 內，且包含標準驗證指令

**核心原則（Machine Truth）**：
行數、圍欄數、測試數、CHECK 數皆為工具產出之衍生診斷值（derived diagnostic truth）。**提示詞不得將衍生數值抄寫為 blocking truth，執行者亦不得因衍生數值不符而停機。** 變更安全由 Batch Spec 與 machine tools 守護。

**執行期規則新鮮度契約（Runtime Rule Freshness Contract）**：
1. GitHub CI 驗證 committed repo rule artifact，非 IDE Rule UI runtime cache。
2. Executor 每批必須從 local disk 實體檔案重讀 active rules；UI 快取不得取代 explicit reread。
3. 若 IDE Rule UI 與 local disk / HEAD 不一致：以 local disk 為準，UI 視為 stale cache 嚴禁存回 repo；進入下個 task 前 reload context。
4. 此屬 runtime freshness，不能宣稱 CI 可驗證 IDE cache。

---

## 3.7 E 節每一項都可機械驗證，沒有例外

`.claude/rules/auditor-selftest.md` E 節的每一項，§3.4 交叉驗證表全數涵蓋。若日後 E 節新增項目，§3.4 必須同批新增對應列並定義確定性比對方法。

---

## 3.8 你的檢查結果必須留在 repo

每批完成後，在 `docs/EXEC-LOG.md` 追加一列五欄：`| 批次 commit | 日期 | 檢查範圍 | 結果 | 攔截紀錄 |`。
- **檢查範圍**：實際執行的節次，如「§3 共同九項、§3.1、§3.2、§3.4 全項、§3.6、§3.9」
- **結果**：通過或不通過
- **攔截紀錄**：本批攔截項目；無則寫「無」

`docs/EXEC-LOG.md` 為執行者端自我檢查之持久證據。CHECK 16 獨立守護其新鮮度與完整性。首列 `BOOTSTRAP` 為唯一例外。

---

## 3.9 FINDING_DISPOSITION 機械檢查契約

每份正式 production / state-sync prompt 必須包含 `FINDING_DISPOSITION` 宣告，合法格式：
- `FINDING_DISPOSITION: NONE`
- `FINDING_DISPOSITION: CURRENT <ID>`
- `FINDING_DISPOSITION: EXISTING <ID>`
- `FINDING_DISPOSITION: NEW <ID>`

執行者（Antigravity）僅執行以下機械交叉比對，不做語意重新審計（semantic re-audit）：
1. **宣告為 `NEW <ID>` 時**：提示詞必須同時滿足三項要素：
   - 狀態領域處置聲明 `TASKBOARD = UPDATE`（或含 TASKBOARD 更新指令）
   - Allowed Scope 包含 `docs/TASKBOARD.md`
   - 提示詞本文明確要求建立該 `<ID>`
   缺任一項即判定為 `PROMPT STRUCTURE ERROR`，立即停機回報。
2. **宣告為 `CURRENT <ID>` 或 `EXISTING <ID>` 時**：若提示詞同時要求更新 TASKBOARD，不得建立同 `<ID>` 之 duplicate row。
3. **宣告為 `NONE` 時**：僅代表審計官宣稱本輪無新 material finding。執行者不得自行判斷審計官是否漏看 finding。

---

## 4. 錨點唯一性驗證（僅 EXACT_SPEC 動手前必做）

> 註：僅適用於 `EXACT_SPEC` 模式。`GOAL_SPEC` 由執行者自主實作，不強制要求錨點前置驗證。

在寫入前，對提示詞每個錨點字串驗證在目標檔案中 `count == 1`：
- **count = 0** → 錨點不存在，停止並回報
- **count > 1** → 錨點不唯一，停止並回報命中位置
- **全部為 1** → 才開始寫入；不得自行找位置套用。

---

## 4.1 寫入後的原文驗證（動手後必做）

完成「替換」或「插入」修改後，立刻驗證指定新內容在目標檔案中 `count == 1`（0 則寫入不符，停止並回報）。前置確認「找得到」，後置確認「改對了」。

---

## 5. 例外

以下情況不適用第 3 節，直接依提示詞執行：
- 提示詞明確標示為「只讀不改」的批次（不產生 commit）
- 提示詞明確標示為「緊急修正」並說明略過原因

第 4 節的錨點驗證沒有例外。

---

## 6. 這條規則保護的是誰

本規則保護專案工程紀律：審計官不越權動檔，執行者不做未授權架構決策；執行者機械驗證提示詞結構，審計官獨立核對結果，確保偏離皆被對稱攔截。
