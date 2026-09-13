# 提示詞前置驗證規範（Prompt Preflight Protocol）

本規則定義執行者（Antigravity IDE Agent）在執行任何提示詞前的機械前置驗證程序。

---

## 1. 為什麼有這一條

`docs/adr/0007-macro-auditor-role.md` 的立論是「執行者不能審自己」，對稱原則是「審計官也不能審自己」。本規則建立執行者端對提示詞結構的機械前置驗證機制，防止錯誤或不完整的指令進入執行階段。

---

## 2. 這是審查，不是建議

收到提示詞後，**在執行任何修改前**，先對提示詞做結構檢查。檢查未通過即停機回報，不猜測、不補齊。

審查界線：

| 屬於本規則（機械檢查） | 不屬於本規則（語意判斷） |
|---|---|
| 提示詞是否有 `git pull origin main` | 這批該不該做 |
| 錨點字串在目標檔案出現次數 | 錨點選得好不好 |
| 是否要求更新交接區 | 交接區該寫什麼 |

遇到判斷或疑慮，依 `.agents/rules/role-boundaries.md` §7 分流（M1/M2/M3 自主處理），僅有未授權之 S1 決策才停機回報。

---

## 3. 必要結構元素（缺一即停，Mode-Aware）

收到提示詞後，首先檢查批次模式宣告：
- **若未宣告 `batch_mode`**：**判定為 `PROMPT STRUCTURE ERROR`（缺少模式宣告）**，立即停機回報，嚴禁默認 EXACT_SPEC。

### 3.0A 所有模式共同必備要素（缺一即停）

| # | 元素 | 判準 |
|---|---|---|
| 1 | 執行者身分宣告 | 提示詞開頭有「你是本專案的執行者」或等義身分界定 |
| 2 | 基準與工作區確認（Base & Workspace） | 載明基準 commit full OID（如 HEAD / origin/main），並要求確認工作區乾淨（working tree clean） |
| 3 | 批次模式宣告（Batch Mode） | 明確宣告 `batch_mode: GOAL_SPEC` 或 `batch_mode: EXACT_SPEC` |
| 4 | 目標與範圍邊界（Goal & Boundaries） | 載明目標（Goal）、允許修改範圍（Allowed Scope）、禁止修改範圍（Forbidden Scope）與驗收條件（Acceptance Criteria） |
| 5 | 確定性驗證閘門（Required Machine Gates） | 載明 Canonical 驗證指令與 Gate 清單（如 `python scripts/verify_all.py`）；**不得以手寫檔案行數或衍生值作為 blocking truth** |
| 6 | `git add` 明確路徑原則 | 包含「嚴禁 `git add -A` 或 `git add .`」禁令與逐檔明確路徑提交原則。GOAL_SPEC 實際清單由執行者自 diff 產生並驗證在 Allowed Scope 內；EXACT_SPEC 則依 Batch Spec targets |
| 7 | 破壞性操作防護宣告 | 明確禁止未授權之 force push、reset --hard 或歷史重寫 |
| 8 | 遠端健康查驗要求 | 包含執行後查驗 GitHub Actions exact SHA 綠燈之要求 |

### 3.0B EXACT_SPEC 專屬必備要素（僅在 EXACT_SPEC 模式下檢查）

| # | 元素 | 判準 |
|---|---|---|
| E-1 | 批次規格路徑 | 載明 `docs/batches/<base-hash>-<slug>.spec.txt` 路徑 |
| E-2 | 規格 SHA-256 | 載明該規格檔案之 exact SHA-256 校驗碼 |
| E-3 | 錨點唯一性 | 規格中所有錨點經 BPE 驗證在 base commit 中 count == 1 |
| E-4 | 規格重放守衛 | 明確要求經由 CHECK 17 進行 parent commit 逐位元重放比對 |

**GOAL_SPEC 模式下不得要求 E-1～E-4 之規格要素，其正確性由單元測試、Gate 驗證與 GitHub Actions 守護。**

**缺任何共同必備項（或 EXACT_SPEC 缺專屬項），停下來回報缺了哪幾項，不要動手。** 各項必備要素為機械守衛，防止手動維護遺漏。

---

## 3.1 配對規則（缺一即停）

以下成對動作提示詞中必須同時出現，缺一即停：

| 動作 A | 必須配對的動作 B | 理由 |
|---|---|---|
| `git pull origin main` | `git status --porcelain=v1` 為空 | 確保基準乾淨，避免髒檔案混入 |
| `git push origin main` | 檢查 GitHub Actions 綠燈 | push 只是發送，Actions 綠燈才是完成證明 |
| 新增或修改規則檔 | 更新自檢清單（`auditor-selftest.md`） | 規則與自檢必須同步 |
| 聲明某 commit 通過核對 | 更新 `docs/AUDIT-LOG.md` 與交接區 §5.1 | 審計狀態必須雙向留痕 |

**審計狀態配對**：審計狀態單一事實來源為 `docs/AUDIT-LOG.md` 裁決 ⇔ `docs/refactor-backlog.md` §5.1 checkpoint。若提示詞宣告某 commit 通過核對，兩者必須同步指向該 commit，防止審計結論漂移。

---

## 3.2 覆蓋規則（缺一即停，Mode-Aware）

### A. GOAL_SPEC 覆蓋鏈

| 項目 | 覆蓋對象 | 判準 |
|---|---|---|
| Allowed Scope | 提示詞目標涉及的所有檔案 | 提示詞擬修改的檔案必須全數列入 Allowed Scope 白名單 |
| git diff --name-only | Allowed Scope | 執行後實際變更的檔案清單必須完全落在 Allowed Scope 內 |
| git add <path> | 實際變更清單 | 提交時必須逐檔明確加入，禁止 `git add -A` 或 `git add .` |
| Required Machine Gates | 本專案 Canonical 驗證標準 | 必須包含 `python scripts/verify_all.py` |

### B. EXACT_SPEC 覆蓋鏈

| 項目 | 覆蓋對象 | 判準 |
|---|---|---|
| 批次規格（Batch Spec） | 提示詞要求的所有修改目標 | 規格檔案必須包含提示詞聲明的全部目標檔案 |
| Allowed Scope | 批次規格中的所有檔案 | 規格涉及的檔案必須全數列入 Allowed Scope 白名單 |
| git add 清單 | 規格中所有的 target_file + spec 本身 | 提示詞的 git add 指令必須包含規格中所有的目標檔案，以及規格檔案本身 |
| Required Machine Gates | 規格驗證工具 | 必須包含 BPE、`scripts/verify_all.py` 與 `check_consistency.py` CHECK 17 |

---

## 3.3 遇到疑問而非缺失時

若發現的不是「缺少某個必要結構元素」，而是實作疑問或非結構性疑慮，**屬於判斷，不是本規則的機械攔截範圍**。

處理原則如下：
1. **必要結構元素缺失** → 屬於前置檢查未通過，直接停機回報【缺失】（hard-stop）。
2. **一般疑問或技術疑慮** → 先送 `.agents/rules/role-boundaries.md` §7 錯誤路由：
   - **M1**（衍生值落差）：自己重新推導計算、記錄於 `docs/EXEC-LOG.md`、繼續。
   - **M2**（暫態/網路）：重試或走確定性回退、繼續。
   - **M3**（Allowed Scope 內實作、測試、Gate 或 CI 失敗）：執行者自主修復閉環（最多 3 輪）。
   - **偶發性觀察（incidental observation）**：若不阻礙 Goal、Acceptance、安全與正確性，記錄於 `docs/EXEC-LOG.md` 後繼續執行。
3. **僅有真正 S1 阻擋事項**（如 base drift、需改動 Allowed Scope 外路徑、驗收條件自相矛盾、破壞性 Git 操作、重大架構或安全決策）→ **才停機升級 S1**。

不得因語意好奇、格式喜好或偶發觀察擅自停機消耗 Macro Auditor 或把自己變成第二個審計官。

若必須升級 S1，回報格式為：

    S1 <簡短分類> | evidence location / blocker

---

## 3.4 審計官自檢聲明的交叉驗證

每份正式生產提示詞必須包含一個【審計官自檢聲明】區塊，逐項列出 `auditor-selftest.md` E 節結果。**Antigravity 僅負責機械比對（mechanical cross-check），絕對不得進行語意重複審查（semantic re-audit）。**

**你要做兩件事：**
1. **確認區塊存在且項目連號無缺**（E1 開始，逐號遞增）。缺區塊或缺項即停。
2. **對可機械驗證的項目做交叉比對**——勾了 ✅ 但提示詞實際沒有的，即為不一致，停下來回報。

可交叉驗證的項目：

| 聲明項 | 怎麼驗 |
|---|---|
| E1 身分宣告 | 提示詞開頭有「你是本專案的執行者」或等義敘述 |
| E2 基準與規格識別 | 提示詞載明基準 commit full OID（EXACT_SPEC 另需批次規格或 SHA-256）；GOAL_SPEC 僅需 base OID 與 Allowed Scope，不要求規格，亦不再要求手寫檔案總行數作為 blocking truth |
| E5 `git add` 明確路徑 | 有「嚴禁 `git add -A` 或 `git add .`」禁令。GOAL_SPEC 實際路徑由執行者自 diff 產生逐檔 explicit git add；EXACT_SPEC 依規格 targets |
| E6 結尾格式 | 有要求純文字與署名行 |
| E8 三項狀態領域處置 | 提示詞明確聲明交接區、TASKBOARD 與 AUDIT-LOG 三項處置（UPDATE 或 NO CHANGE 附理由；無新審計結論時 AUDIT-LOG 應標記 NO CHANGE，不得迫使執行者自造 verdict） |
| E9 `git pull` | 有 `git pull origin main` 且指明預期 HEAD |
| E12 動手前必讀 | 有要求讀取規則檔或執行基準前置檢查 |
| E3 錨點原文定位 | 修改指令依模式區分：EXACT_SPEC 附 structural anchor 原文或唯一語意識別字；GOAL_SPEC 僅定義目標、邊界與驗收準則，不要求錨點。固定行號僅作輔助說明，非 blocking truth |
| E4 機器驗證證據落地 | 提示詞要求執行 Required Machine Gates 且證據寫入 docs/EXEC-LOG.md / GitHub，未要求在對話貼出完整 Gate 輸出 |
| E7 回報通道約束 | 提示詞未要求正常成功批次貼出 full diff / full file / terminal dump，遵守 Repo Evidence Channel 契約 |
| E10 零命中條件的自身檢查 | 提示詞若有「字串 X 應為零命中」，檢查 X 是否出現在提示詞本身的其他位置——純字串比對，非語意判斷 |
| E11 錨點唯一性驗證 | 僅在 EXACT_SPEC 模式下檢查：套用前驗證錨點 count == 1；GOAL_SPEC 模式為 N/A，不要求 Batch Spec 錨點 |
| E13 配對與覆蓋 | 依 §3.1、§3.2 比對。GOAL_SPEC 比對 Allowed Scope ↔ actual changed files ↔ explicit git add ↔ gates；EXACT_SPEC 比對 allowed scope ↔ spec targets ↔ git add ↔ gates |
| E14 自檢聲明區塊 | 區塊存在且項目連號無缺 |
| E15 錨點基準來源 | 僅在 EXACT_SPEC 模式下檢查：錨點對應本批 base commit full OID 與規格上下文；GOAL_SPEC 模式為 N/A |
| E16 跨檔引用同行 | 寫入文字中的 `§X.Y` 若跨檔，檔名與章節號在同一行；explicit target 不得被 substitution、target section 必須存在於該檔，歷史引用必須明確寫 archive 路徑 |
| E17 結構序列驗收 | 若插入或結構變更涉及語意驗收條件（如章節／項目順序），附明確驗收準則；不得將衍生序列當作通用 blocking 條件 |
| E18 機械前置證據 | 依 §3.6 確認包含 base full OID、batch mode、Allowed Scope 與標準驗證指令；EXACT_SPEC 才額外要求 spec path 與 SHA |
| E19 移除前複查 | 提示詞若含刪除檔案／章節／規則／看板項目，檢查是否附有三步複查結果。純存在性比對，非語意判斷 |
| E20 規則層變更的模擬授權 | EXACT_SPEC 規則層變更由同一份 Batch Spec 經 BPE 與 check_consistency 模擬驗證；GOAL_SPEC 由單元測試與 Gate 驗證守護 |
| E21 衍生數值不作 blocking truth | 基準 commit 必須與執行者實測 HEAD 一致；所有 machine-derived values 由確定性工具產出，不得由 LLM 複製成提示詞 blocking truth |
| E22 審計狀態權威檢查 | 確認提示詞未要求建立 audited tag 作為完成條件；審計狀態以 AUDIT-LOG、refactor-backlog §5.1 與 GitHub Actions 為 Single Source of Truth |
| E23 批次規格進 repo | 僅在 EXACT_SPEC 模式下檢查：提示詞附有規格路徑與 sha256 且列入 git add；GOAL_SPEC 模式不要求規格進 repo |

**自檢聲明不接受任何豁免。**

上表任一項比對為「否」時，**一律停止並回報**，不論審計官是否附上理由。審計官標為 ⚠️、寫明「刻意不做」或「知情偏離」，**都不構成豁免**；偏離規則之唯一合法路徑為先行開批修改規則本身。

其餘各項需要語意判斷者不在機械驗證範圍，依 §3.3 送錯誤路由。

**回報格式：**

    【自檢聲明交叉驗證】
    區塊存在：是／否
    項目數：N（應為連號無缺）
    可驗證項目比對結果：
      E1 聲明 ✅ / 實際 有 → 一致
      E8 聲明 ✅ / 實際 缺「AUDIT-LOG」 → **不一致，停止**

---

## 3.5 執行者檢查證據持久化（已落地）

執行者前置檢查證據已由 §3.8 規範並正式落地至 `docs/EXEC-LOG.md`，由 CHECK 16 機械守護；本節保留標題序號，舊有 B-14 缺口敘事已退役。

---

## 3.6 機械前置證據（Machine Evidence / Execution Preflight）的交叉驗證

每份提示詞必須包含一個【機械前置證據】（或等義 Preflight Evidence）區塊，內容包含五項：

1. (a) 基準 Commit Full OID（base commit hash）
2. (b) 批次模式（`batch_mode`，如 `EXACT_SPEC` 或 `GOAL_SPEC`）
3. (c) 批次規格路徑與規格 SHA-256（指向 `docs/batches/` 下的規格檔案，**僅 EXACT_SPEC 必備；GOAL_SPEC 不要求**）
4. (d) 允許修改範圍（Allowed Scope 白名單路徑）
5. (e) 標準驗證指令與 Gate 清單（canonical validation commands，如 validate_skills, check_consistency, fingerprint, pytest）

**你要做五項機械比對：**

| 檢查 | 方法 |
|---|---|
| 證據區塊存在 | 缺區塊或缺任一必備元素即停 |
| 基準 OID 一致 | 實測第 0 步的 HEAD 必須等於宣告的 base OID |
| 批次模式合法 | 確認 `batch_mode` 宣告且符合規格契約（如 EXACT_SPEC 或 GOAL_SPEC） |
| 規格 SHA 一致 | 僅 EXACT_SPEC 檢查：由確定性工具計算規格 sha256，與提示詞宣稱值完全一致；GOAL_SPEC 為 N/A |
| 範圍與驗證指令齊備 | 規格修改目標完全落在 Allowed Scope 內，且包含標準驗證指令 |

**核心原則（Machine Truth）**：
目標檔案行數、圍欄數、測試數量、CHECK 總數及 INFO 輸出等，皆為確定性工具在執行當下產出的衍生診斷數值（derived diagnostic truth）。**提示詞不得將衍生數值抄寫為 blocking truth，執行者亦不得因衍生數值不符而停止執行。** 內容完整性、重放正確性與變更安全，一律由 Batch Spec 與 repository machine tools 守護。

**執行期規則新鮮度契約（Runtime Rule Freshness Contract）**：
1. GitHub CI 驗證的是 committed repository rule artifact，不是 Antigravity IDE Rule UI 的 runtime cache。
2. Executor 每批仍必須從 local filesystem 實體檔案重新讀取 active rules；auto-loaded / cached Rule UI 不得取代 explicit reread。
3. 若 IDE Rule UI 顯示內容／字元數與 local disk + HEAD blob 不一致：
   - HEAD / local disk 為 repository truth。
   - UI 視為 stale runtime cache，嚴禁將 stale UI 內容保存回 repo。
   - 在進入下一個 production task 前 reload / reopen rule context 或使用 fresh session。
4. 此問題屬 runtime freshness，不能宣稱 GitHub CI 可以驗證 IDE cache。

---

## 3.7 E 節每一項都可機械驗證，沒有例外

`.claude/rules/auditor-selftest.md` E 節的每一項，§3.4 的交叉驗證表全數涵蓋，無須憑信任接受。若日後 E 節新增項目，§3.4 必須同批新增對應列並定義確定性比對方法。

---

## 3.8 你的檢查結果必須留在 repo

每批完成後，在 `docs/EXEC-LOG.md` 追加一列，記錄本批你做了哪些檢查、結果為何、攔下了什麼。欄位固定為五欄：

    | 批次 commit | 日期 | 檢查範圍 | 結果 | 攔截紀錄 |

- **檢查範圍**：實際執行的節次，例如「§3 共同八項、§3.1、§3.2、§3.4 全項、§3.6」
- **結果**：通過或不通過，不通過時寫明哪一項
- **攔截紀錄**：本批攔下了什麼；無則寫「無」

`docs/EXEC-LOG.md` 為執行者端自我檢查之持久證據。`scripts/check_consistency.py` 的 CHECK 16 獨立守護 EXEC-LOG 之生命週期與完整性（最新列不落後於 HEAD）；CHECK 12 則獨立守護 AUDIT-LOG 之 ancestry 有效性，二者各有獨立職責與判準。

**首列例外**：第一列標記為 `BOOTSTRAP`，CHECK 16 跳過該值。

---

## 4. 錨點唯一性驗證（僅 EXACT_SPEC 動手前必做）

> 註：本節僅適用於 `EXACT_SPEC` 模式。在 `GOAL_SPEC` 模式下由執行者自主實作，不強制要求錨點前置驗證。

在寫入前，對提示詞**每一個**錨點字串驗證：

    import io
    t = io.open(目標檔案, encoding="utf-8").read()
    print(t.count(錨點字串))   # 必須恰好是 1

- **count = 0** → 錨點不存在，停止並回報
- **count > 1** → 錨點不唯一，停止並回報命中位置
- **全部為 1** → 才開始寫入

前置驗證確認目標存在且唯一，防止部分寫入導致工作區汙染。

回報格式：

    提示詞前置檢查未通過：
    - 結構元素缺少：第 N 項 <元素名稱>
    - 錨點驗證失敗：修改 X 的錨點在 <檔案> 中 count=<n>（附原文與行號）
    本批未執行任何修改，工作區維持乾淨。
    請審計官更正後重新提供。

**不得自行找看起來最像的地方套用。** 猜測一次成功，會讓所有人以為機制有效。

---

## 4.1 寫入後的原文驗證（動手後必做）

§4 檢查修改前「找不找得到」，本節檢查修改後「有沒有改對」。

每完成一個「替換」或「插入」修改，立刻驗證：

    t = io.open(目標檔案, encoding="utf-8").read()
    print(t.count(指定的新內容))   # 必須恰好是 1

- **count = 1** → 寫入正確
- **count = 0** → 寫入與指令不符，**停止並回報**

前置驗證確認「找得到」，後置驗證確認「改對了」，兩者缺一不可。

---

## 5. 例外

以下情況不適用第 3 節，直接依提示詞執行：
- 提示詞明確標示為「只讀不改」的批次（不會產生 commit，自然不需要第 5、6 項）
- 提示詞明確標示為「緊急修正」並說明略過原因

**第 4 節的錨點驗證沒有例外。** 只要有寫入，就要先驗證。

---

## 6. 這條規則保護的是誰

本規則保護專案工程紀律。雙方各司其職：審計官不越權動檔案，執行者不做未授權架構決策；執行者機械驗證提示詞結構，審計官獨立核對執行結果，確保任何一方之偏離皆能被對稱機制攔截。
