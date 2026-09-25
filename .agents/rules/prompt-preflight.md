# 提示詞前置驗證規範（Prompt Preflight Protocol）

本規則定義執行者（Antigravity IDE Agent）在執行任何提示詞前的機械前置驗證程序。

---

## 1. 目的

依 `docs/adr/0007-macro-auditor-role.md` 對稱原則建立提示詞結構機械驗證機制，防止錯誤指令進入執行。

---

## 2. 這是審查，不是建議

收到提示詞後，**在執行任何修改前**先對提示詞做結構檢查（如 `git pull`、錨點出現次數、交接區與狀態處置）。未通過即停機回報，不猜測、不補齊。遇到疑慮依 `.agents/rules/role-boundaries.md` §7 分流（M1/M2/M3 自主處理），僅未授權之 S1 決策才停機回報。

### 2.1 最前置硬規則：Prompt Manifest 與 Execution Contract 機械驗證（Hard Rule）

任何 repo mutation 前必須執行：
1. 取得完整 incoming prompt 原文。
2. 以 scratch 檔或 stdin 餵給 `python scripts/validate_prompt_manifest.py --require-contract`，或以顯式模式執行 `scripts/governance_preflight.py`（指定 `--prompt-file <path>` 或 `--prompt-file -`；嚴格要求顯式模式，裸呼叫立即 fail-fast，絕不於無模式下等待 stdin）。
3. Production prompt 必須同時具備 Prompt Manifest 與 `BEGIN_HHAI_EXECUTION_CONTRACT` ... `END_HHAI_EXECUTION_CONTRACT` 區塊；缺任一立即判定為 `PROMPT STRUCTURE ERROR` 停機，**不得進行任何 repo mutation**。
4. Execution Contract 為確定性治理邊界，不得自行放寬。若 task goal、pressure 或 acceptance 與 FORBIDDEN 衝突：升級 `S1 GOVERNANCE_CONTRACT_CONFLICT`，原則為 `SAFETY_BOUNDARY_WINS`。
5. IDE settings 屬 defense-in-depth 不能取代 Execution Contract。通過後才進入後續檢查。
6. **Execution Contract v2 規範（B-109 M2）**：
   - 欄位包含：`contract_version: 2`、`allowed_mutation_paths`、`required_mutation_paths`、`max_plan_revisions`（<= 3）、`execution_record_required`。
   - 約束：若 `allowed_mutation_paths == NONE`，則 required 為 `NONE` 且 record 為 `false`；非 NONE 則 `required_mutation_paths ⊆ allowed_mutation_paths` 且 record 為 `true`。超出 scope 或 revision > 3 即刻停機升級 S1。
   - 計畫與紀錄：變更批次維護 `.git/<task-id>-plan.json`；commit 前由 `scripts/execution_record.py` 輸出並驗證 `docs/governance/execution-record.json`；CI CHECK 26 依 `base_oid..HEAD` 重放 git diff 查驗。
   - 證據來源與狀態分離：Origin 包含 `MACHINE_CAPTURED_RAW`、`MACHINE_DERIVED`、`AGENT_ASSERTED`、`USER_PROVIDED`；Verification Status 包含 `VERIFIED`、`UNVERIFIED`、`NOT_ESTABLISHED`、`PENDING_EXTERNAL` 且獨立於 origin。
   - 完整性標準：REG-11（PATH-EXISTENCE，REPO_PATH 必存在）、REG-12（GENERATOR-IN-BUNDLE，MACHINE_DERIVED 生成器存在且 fresh SHA-256 一致）、REG-13（REPORT-TRACEABILITY，報告宣稱必關聯非空合法證據 ID）。

本驗證器不取代 M1/M2/M3/S1 錯誤路由，將第一層結構與契約檢驗移至確定性程式碼。


### 2.2 依賴閉包機械重放與證據溯源規範（Dependency Closure Replay & Evidence Provenance）

證據溯源：原始 discovery artifact 為不可變證據禁原地覆寫；處置以新衍生 artifact 標註；`base_oid` 禁手動改寫；新 base 產出 task-specific 新檔；QUERY SET 禁宣稱為 EVIDENCE RESULT；歷史證據檔禁覆寫。

宣告 E24 = PASS 且依賴模式 `mode = REQUIRED` 時，mutation 前須重放比對：
1. 依賴證據與 Allowed Scope 寫入 scratch JSON。
2. 執行 `python scripts/impact_scan.py check --evidence-file <evidence.json> --allowed-scope-file <allowed_scope.json>`。
3. 若 exit != 0 禁 mutation：缺證據/格式錯為 `PROMPT STRUCTURE ERROR`；依賴不符為 `S1 DEPENDENCY_DRIFT`；UPDATE 漏列為 `S1 DEPENDENCY_SCOPE_MISSING`。
4. 實作後 `VERIFY_ONLY` 須改時禁擅改，升級 `S1 DEPENDENCY_SCOPE_EXPANSION`。僅驗證證據配對，不重複語意審查。

---

## 3. 必要結構元素（缺一即停，Mode-Aware）

收到提示詞後，首先檢查批次模式宣告：
- **若未宣告 `batch_mode`**：判定為 `PROMPT STRUCTURE ERROR`（缺少模式宣告），立即停機回報，嚴禁默認 EXACT_SPEC。
- **Tier-M 分類注意**：Tier-M 為風險／修復分類而非新 `batch_mode`，維持 `batch_mode: GOAL_SPEC`，不擴充 parser 枚舉。證據必須對應當前基準（current base），若 `base_oid` 不符不得重用，嚴禁手動改寫。

### 3.0A 所有模式共同必備要素（缺一即停）

| # | 元素 | 判準 |
|---|---|---|
| 1 | 執行者身分宣告 | 含執行者身分界定 |
| 2 | 基準與工作區確認 | 載明基準 commit full OID 且要求 working tree clean |
| 3 | 批次模式宣告 | 宣告 batch_mode 為 GOAL_SPEC 或 EXACT_SPEC |
| 4 | 目標與邊界 | 載明 Goal、Allowed Scope、Forbidden Scope 與 Acceptance |
| 5 | 確定性驗證閘門 | 載明標準驗證指令（如 `verify_all.py`）；不以衍生值作 blocking truth |
| 6 | `git add` 明確路徑 | 禁 `git add -A` 或 `.`；GOAL_SPEC 逐檔加入，EXACT_SPEC 依規格 |
| 7 | 破壞性操作防護 | 禁未授權 force push、reset --hard 或歷史重寫 |
| 8 | 遠端健康查驗 | 含執行後查驗 Actions exact SHA 綠燈之要求 |
| 9 | Material Finding 處置 | 宣告 `FINDING_DISPOSITION`（見 §3.9） |

### 3.0B EXACT_SPEC 專屬必備要素（僅在 EXACT_SPEC 模式下檢查）

| # | 元素 | 判準 |
|---|---|---|
| E-1 | 批次規格路徑 | 載明 `docs/batches/<base-hash>-<slug>.spec.txt` 路徑 |
| E-2 | 規格 SHA-256 | 載明該規格檔案之 exact SHA-256 校驗碼 |
| E-3 | 錨點唯一性 | 規格中所有錨點經 BPE 驗證在 base commit 中 count == 1 |
| E-4 | 規格重放守衛 | 明確要求經由 CHECK 17 進行 parent commit 逐位元重放比對 |

GOAL_SPEC 模式不得要求 E-1～E-4，其正確性由測試與 Gate 守護。缺必備項即停機回報。

---

## 3.1 配對規則（缺一即停）

以下成對動作提示詞中必須同時出現，缺一即停：

| 動作 A | 必須配對的動作 B | 理由 |
|---|---|---|
| `git pull origin main` | `git status --porcelain=v1` 為空 | 確保基準乾淨，避免髒檔案混入 |
| `git push`（batch/**） | 需查驗 Actions 成功 | Actions 成功才是 proof；authorized batch/** push → checks 成功 → fast-forward main (SAME SHA) → main push 成功。普通分支禁升 main |
| 新增或修改規則檔 | 更新自檢清單（`auditor-selftest.md`） | 規則與自檢必須同步 |
| 聲明某 commit 通過核對 | 更新 `docs/AUDIT-LOG.md` 與交接區 §5.1 | 審計狀態必須雙向留痕 |

審計狀態單一事實來源為 `docs/AUDIT-LOG.md` 裁決 ⇔ `docs/refactor-backlog.md` §5.1 checkpoint。若宣告某 commit 通過核對，兩者須同步指向該 commit。

---

## 3.2 覆蓋規則（缺一即停，Mode-Aware）

### A. GOAL_SPEC 覆蓋鏈

| 項目 | 覆蓋對象 | 判準 |
|---|---|---|
| Allowed Scope | 涉及檔案 | 目標檔案全數列入 Allowed Scope 白名單 |
| git diff --name-only | Allowed Scope | 實際變更清單完全落在 Allowed Scope 內 |
| git add <path> | 實際變更 | 逐檔明確加入，禁 `git add -A` 或 `.` |
| Required Machine Gates | Canonical 標準 | 必須包含 `python scripts/verify_all.py` |

### B. EXACT_SPEC 覆蓋鏈

| 項目 | 覆蓋對象 | 判準 |
|---|---|---|
| 批次規格（Batch Spec） | 修改目標 | 規格檔案包含聲明的全部目標檔案 |
| Allowed Scope | 規格檔案 | 規格涉及檔案全數列入 Allowed Scope 白名單 |
| git add 清單 | targets + spec | git add 包含規格中所有目標與規格檔本身 |
| Required Machine Gates | 規格驗證工具 | 包含 BPE、`verify_all.py` 與 `check_consistency.py` CHECK 17 |

---

## 3.3 遇到疑問而非缺失時

實作疑問或非結構性疑慮屬判斷，依 `.agents/rules/role-boundaries.md` §7 分流：
1. **M1**（衍生值落差）：自行重算、記於 `docs/EXEC-LOG.md`、繼續。
2. **M2**（暫態/網路）：重試或確定性回退、繼續。
3. **M3**（Scope 內實作/測試/Gate/CI 失敗）：自主修復閉環（最多 3 輪）。
4. **偶發性觀察**：不阻礙目標與正確性者，記於 `docs/EXEC-LOG.md` 繼續。
5. **僅真正 S1 阻擋**（base drift、超 Scope、驗收矛盾、破壞性操作、重大決策）→ **停機升級 S1**：`S1 <分類> | evidence / blocker`。

禁因語意好奇、格式喜好或偶發觀察擅自停機。

---

## 3.4 審計官自檢聲明的交叉驗證

每份正式生產提示詞須含【審計官自檢聲明】區塊，列出 `auditor-selftest.md` E 節結果。**Antigravity 僅負責機械交叉比對，絕不重複語意審查。**

**執行兩項：**
1. **確認區塊存在且項目連號無缺**（E1 起遞增），缺即停。
2. **對可機械驗證項目交叉比對**——勾選 ✅ 但實無者停機回報。

| 聲明項 | 機械比對方法 |
|---|---|
| E1 身分宣告 | 提示詞含執行者身分界定 |
| E2 基準與規格識別 | 載明基準 commit full OID；GOAL_SPEC 需 base OID 與 Allowed Scope；EXACT_SPEC 另需規格與 SHA |
| E3 錨點原文定位 | EXACT_SPEC 附 structural anchor；GOAL_SPEC 僅需目標與邊界，不需錨點 |
| E4 機器驗證證據落地 | 要求執行 Required Machine Gates 且證據記於 docs/EXEC-LOG.md / Actions |
| E5 `git add` 明確路徑 | 禁 `git add -A` / `.`。GOAL_SPEC 逐檔加入；EXACT_SPEC 依規格 |
| E6 結尾格式 | 要求純文字回覆與固定署名行 |
| E7 回報通道約束 | 正常成功批次未要求貼 full diff/file/terminal dump，遵守 Repo Evidence Channel |
| E8 三項狀態領域處置 | 聲明交接區、TASKBOARD 與 AUDIT-LOG 處置（UPDATE / NO CHANGE 附理由） |
| E9 `git pull` | 含 `git pull origin main` 且指明預期 HEAD |
| E10 零命中自身檢查 | 若有「字串 X 應為零命中」，檢查 X 是否出現於提示詞自身其他處 |
| E11 錨點唯一性驗證 | EXACT_SPEC 套用前驗證錨點 count == 1；GOAL_SPEC 為 N/A |
| E12 動手前必讀 | 要求讀取規則檔或執行基準前置檢查 |
| E13 配對與覆蓋 | 依 §3.1 與 §3.2 比對範圍、diff、git add 與 gates |
| E14 自檢聲明區塊 | 區塊存在且項目連號無缺 |
| E15 錨點基準來源 | EXACT_SPEC 錨點對應 base commit；GOAL_SPEC 為 N/A |
| E16 跨檔引用同行 | 跨檔 `§X.Y` 檔名與章節號同行且 target 存在 |
| E17 結構序列與失敗路徑驗收 | 結構變更附驗收準則；資源取得依 failure-path 定義狀態、owner、exits、exactly-once 清理與反例 |
| E18 機械前置證據 | 含 base full OID、batch mode、Allowed Scope 與標準驗證指令 |
| E19 移除前複查 | 刪除檔案/章節/規則/看板附三步複查結果 |
| E20 規則層模擬授權 | EXACT_SPEC 規則變更經 BPE 與 check 模擬；GOAL_SPEC 由測試與 Gate 守護 |
| E21 衍生數值不作 blocking truth | 基準 commit 與實測一致；衍生值不得抄為 blocking truth |
| E22 審計狀態權威檢查 | 未要求 audited tag；審計狀態以 AUDIT-LOG、refactor-backlog §5.1 與 Actions 為 SSOT |
| E23 批次規格進 repo | EXACT_SPEC 附規格路徑與 sha256 且 add；GOAL_SPEC 不要求規格進 repo |
| E24 依賴閉包檢驗 | 宣告 E24 且 mode=REQUIRED 時重放 impact_scan replay 比對 |
| E25 Execution Contract 完整性 | 含唯一合法 Execution Contract 區塊，base_oid 一致，安全邊界全 FORBIDDEN |
| E26 Plan-vs-Actual / 證據完整性重放 | 契約 v2（allowed/required paths, revisions <= 3, record required），計畫/紀錄與 origin 及 CI diff 重放標準 |

**自檢聲明不接受豁免。** 比對為「否」一律停機回報，標為 ⚠️ 或「刻意不做」不構成豁免。偏離規則唯一合法路徑為開批修改規則本身。

---

## 3.5 執行者檢查證據持久化（已落地）

執行者前置檢查證據已由 §3.8 規範並落地至 `docs/EXEC-LOG.md`，由 CHECK 16 機械守護；本節保留標題序號。

---

## 3.6 機械前置證據（Machine Evidence / Execution Preflight）的交叉驗證

每份提示詞必須包含【機械前置證據】（Preflight Evidence）區塊：(a) 基準 Commit Full OID；(b) 批次模式；(c) 批次規格路徑與 SHA-256（僅 EXACT_SPEC）；(d) Allowed Scope；(e) 標準驗證指令。比對存在、HEAD == base、模式合法、SHA 一致與範圍齊備，缺一即停。

**核心原則（Machine Truth）**：行數、測試數等為衍生診斷值，**不得抄為 blocking truth，不得因衍生值不符停機**。

**執行期規則新鮮度契約（Runtime Rule Freshness Contract）**：CI 驗證 committed rule artifact。Executor 每批從 local disk 重讀 active rules，UI 快取不得取代 reread；若與 disk 不一致以 disk 為準。

---

## 3.7 E 節每一項都可機械驗證，沒有例外

`.claude/rules/auditor-selftest.md` E 節的每一項，§3.4 交叉驗證表全數涵蓋。若日後 E 節新增項目，§3.4 必須同批新增對應列並定義確定性比對方法。

---

## 3.8 你的檢查結果必須留在 repo

每批完成後，在 `docs/EXEC-LOG.md` 追加一列五欄：`| 批次 commit | 日期 | 檢查範圍 | 結果 | 攔截紀錄 |`。
`docs/EXEC-LOG.md` 為執行者自我檢查之持久證據，由 CHECK 16 獨立守護其新鮮度與完整性。首列 `BOOTSTRAP` 為唯一例外。

---

## 3.9 FINDING_DISPOSITION 機械檢查契約

每份正式 production / state-sync prompt 必須宣告 `FINDING_DISPOSITION`（格式：NONE / CURRENT <ID> / EXISTING <ID> / NEW <ID>）。

執行者僅執行機械交叉比對，不做語意重新審計：
1. **宣告 `NEW <ID>`**：須同時滿足 TASKBOARD=UPDATE、Allowed Scope 含 `docs/TASKBOARD.md`、本文明確要求建立 `<ID>`。缺一即 `PROMPT STRUCTURE ERROR`。
2. **宣告 `CURRENT <ID>` 或 `EXISTING <ID>`**：若更新 TASKBOARD，不得建立同 `<ID>` 之重複列。
3. **宣告 `NONE`**：代表無新 material finding；不臆測。

---

## 4. 錨點唯一性驗證（僅 EXACT_SPEC 動手前必做）

> 註：僅適用於 `EXACT_SPEC` 模式。`GOAL_SPEC` 由執行者自主實作，不強制要求錨點前置驗證。

寫入前驗證每個錨點在目標檔案中 `count == 1`：
- **count = 0** → 錨點不存在，停止並回報
- **count > 1** → 錨點不唯一，停止並回報命中位置
- **全部為 1** → 才開始寫入；不得自行找位置套用。

---

## 4.1 寫入後的原文驗證（動手後必做）

修改後立刻驗證指定新內容在目標中 `count == 1`（0 則寫入不符，停機回報）。前置確認找得到，後置確認改對了。

---

## 5. 例外

以下情況不適用第 3 節：
- 標示為「只讀不改」批次（不產生 commit）
- 標示為「緊急修正」並說明略過原因

第 4 節的錨點驗證沒有例外。

---

## 6. 這條規則保護的是誰

本規則保護工程紀律：審計官不越權動檔，執行者不做未授權架構決策；雙向機械驗證確保偏離被對稱攔截。
