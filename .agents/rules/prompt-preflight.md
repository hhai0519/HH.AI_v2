# 提示詞前置檢查

> **適用對象：Antigravity IDE Agent（執行者）**
> 本規則由系統自動載入。**收到提示詞後、動手之前執行。**

---

## 1. 為什麼有這一條

`docs/adr/0007-macro-auditor-role.md` 的立論是「執行者不能審自己」。
這條原則有對稱的另一半：**審計官也不能審自己。**

2026-09-02 稽核發現，針對審計官出錯的偵測機制只有兩種：
它自己的自檢清單（自己跑），或使用者發現。同期審計官犯過多次同類錯誤，
**被獨立機制攔下的三次，都是你因為提示詞的數字或錨點與實際不符而停下回報。**

本規則把那三次的偶然，變成每批都會發生的機制。

---

## 2. 這不是叫你評價提示詞

`.agents/rules/role-boundaries.md` §2 禁止你「評價另一個 agent 的產出是否正確」。
那條仍然有效。

**本規則檢查的是「有沒有」，不是「對不對」。**

| 屬於本規則 | 不屬於本規則 |
|---|---|
| 提示詞裡有沒有出現 `git pull origin main` | 這批該不該做 |
| 錨點字串在目標檔案中出現幾次 | 那個錨點選得好不好 |
| 有沒有要求更新交接區 | 交接區該寫什麼 |

前者是機械檢查，後者是判斷。**遇到後者，依 role-boundaries §3 停下來問。**

---

## 3. 必要結構元素（缺一即停，Mode-Aware）

收到提示詞後，首先檢查批次模式宣告：
- **若未宣告 `batch_mode`**：**一律直接判定為 `PROMPT STRUCTURE ERROR`（缺少模式宣告）**，立即停機回報，嚴禁默認 EXACT_SPEC。

### 3.0A 所有模式共同必備要素（缺一即停）

| # | 元素 | 判準 |
|---|---|---|
| 1 | 執行者身分宣告 | 提示詞開頭有「你是本專案的執行者」或等義身分界定 |
| 2 | 基準與工作區確認（Base & Workspace） | 載明基準 commit full OID（如 HEAD / origin/main），並要求確認工作區乾淨（working tree clean） |
| 3 | 批次模式宣告（Batch Mode） | 明確宣告 `batch_mode: GOAL_SPEC` 或 `batch_mode: EXACT_SPEC` |
| 4 | 目標與範圍邊界（Goal & Boundaries） | 載明目標（Goal）、允許修改範圍（Allowed Scope）、禁止修改範圍（Forbidden Scope）與驗收條件（Acceptance Criteria） |
| 5 | 確定性驗證閘門（Required Machine Gates） | 載明 Canonical 驗證指令與 Gate 清單（如 `python scripts/verify_all.py`）；**不得以手寫檔案行數或衍生值作為 blocking truth** |
| 6 | `git add` 明確路徑原則 | 包含「嚴禁 `git add -A` 或 `git add .`」禁令與逐檔明確路徑提交原則。在 GOAL_SPEC 模式下，Auditor 不需要預先列出 exact file list，實際檔案清單由執行者在 commit 前透過 machine-derived `git diff --name-only` 取得並驗證在 Allowed Scope 內；EXACT_SPEC 則依 Batch Spec targets |
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

**缺任何共同必備項（或 EXACT_SPEC 缺專屬項），停下來回報缺了哪幾項，不要動手。**

**第 6 項有實際失效紀錄**：2026-09-02 的批 G 提示詞更新了 TASKBOARD
卻漏了交接區，導致交接區落後兩批、下一批的錨點對不上。
當時 `auditor-protocol.md` §6.1 已經有這條規則，審計官仍然漏了——
**這正是本規則存在的理由：它不依賴審計官記得。**

---

## 3.1 配對規則（缺一即停）

以下成對的動作，提示詞中**必須同時出現**，只出現一邊即為缺失：

| 若提示詞包含 | 就必須同時包含 |
|---|---|
| 正式提升某 commit 為 Macro PASS checkpoint | `docs/AUDIT-LOG.md`（Macro PASS 判定）與交接區 §5.1 第一行的「上次核對通過的 HEAD」指向同一 commit（TASKBOARD 只維持工作狀態，不參與 commit-verdict authority） |
| 新增 `docs/TASKBOARD.md` 的項目 | 該批的驗證步驟含看板項目數檢查 |
| 新增或修改 `.claude/rules/` 或 `.agents/rules/` 的章節 | 該批的驗證步驟含章節序列檢查 |
| 追加 `docs/refactor-backlog.md` 的編號項目 | 該批的驗證步驟含編號連續性檢查 |
| 新增 `.claude/rules/auditor-protocol.md` §6.1 的項目 | 同步新增 `.claude/rules/auditor-selftest.md` E 節的對應項（標註 `§6.1-N`） |

**審計狀態配對 (Audit-State Pairing)**：2026-09-12 治理重構（B-58 Recovery R1）
明確將 TASKBOARD 的 Git HEAD truth 移除，退役舊有的 TASKBOARD HEAD ⇔ §5.1 HEAD 配對。
真正的審計狀態單一事實來源為：`AUDIT-LOG` 裁決 ⇔ §5.1 checkpoint。
若提示詞宣告某 commit 通過核對，兩者必須同步指向該 commit，防止審計結論漂移。

## 3.2 覆蓋規則（缺一即停，Mode-Aware）

### A. GOAL_SPEC 覆蓋驗證
在 GOAL_SPEC 模式下，提示詞中 `git add` 清單與實際變更檔案必須滿足：
1. **Allowed Scope ↔ actual changed files**：實際異動之檔案必須全數落在允許修改範圍內，零越權、零夾帶。
2. **actual changed files ↔ explicit git add**：實際異動檔案必須與 `git add` 清單完全一致。
3. **Acceptance Criteria ↔ Required Gates**：驗證步驟與 Gates 必須完整涵蓋驗收準則。
> ⚠️ **GOAL_SPEC 模式下不得要求 Allowed Scope ↔ spec targets**（因 GOAL_SPEC 無 mandatory Batch Spec）。

### B. EXACT_SPEC 覆蓋驗證
在 EXACT_SPEC 模式下，提示詞中 `git add` 清單的**每一個非 exempt 檔案**，都必須同時出現在：
1. 允許修改範圍（Allowed Scope）
2. 批次規格（Batch Spec）的修改目標檔案中
3. 本批驗證步驟所涵蓋的檢查範圍中
反之亦然——出現在規格修改目標卻不在 `git add` 清單中的檔案，代表提示詞漏了提交指令。

覆蓋驗證**不得再依賴「手寫檔案總行數清單」或「手寫圍欄數清單」作為 blocking 條件**。

**這兩節檢查的是「有沒有」，不是「對不對」**，與 §2 的分界一致。
你不需要判斷提示詞的內容是否正確，只需要比對清單是否齊全。

## 3.3 遇到疑問而非缺失時

若你發現的不是「缺少某個必要元素」，而是「這樣做好像不太對」，
**那屬於判斷，不是本規則的範圍**。依 `role-boundaries.md` §3 處理：
停下來把疑問告訴使用者，不要自行修正，也不要當成缺失回報。

回報時明確區分：

    【缺失】第 N 項：<機械檢查未通過的項目>
    【疑問】<你的觀察，交由審計官判斷>

## 3.4 審計官自檢聲明的交叉驗證

每份提示詞必須包含一個【審計官自檢聲明】區塊，
逐項列出 `auditor-selftest.md` E 節的結果。

**你要做兩件事：**

1. **確認區塊存在且項目連號無缺**（E1 開始，逐號遞增）。
   缺區塊或缺項即停。
2. **對可機械驗證的項目做交叉比對**——勾了 ✅ 但提示詞實際沒有的，
   即為不一致，停下來回報。

可交叉驗證的項目：

| 聲明項 | 怎麼驗 |
|---|---|
| E1 身分宣告 | 提示詞開頭有「你是本專案的執行者」或等義敘述 |
| E2 基準與規格識別 | 提示詞載明基準 commit full OID（EXACT_SPEC 另需批次規格或 SHA-256），交由確定性工具比對；GOAL_SPEC 僅需 base OID 與 Allowed Scope，不要求規格，**亦不再要求手寫檔案總行數作為 blocking truth** |
| E5 `git add` 明確路徑 | 有「嚴禁 `git add -A` 或 `git add .`」禁令。GOAL_SPEC 實際路徑由執行者自 diff 產生逐檔 explicit git add，不要求 Auditor 預測實作檔案；EXACT_SPEC 依規格 targets |
| E6 結尾格式 | 有要求純文字與署名行 |
| E8 三項更新 | 修改指令中有「交接區」「TASKBOARD」「AUDIT-LOG」三者（或明確說明本批無核對事實例外） |
| E9 `git pull` | 有 `git pull origin main` 且指明預期 HEAD |
| E12 動手前必讀 | 有要求讀取規則檔或執行基準前置檢查 |
| E3 錨點原文定位 | 修改指令依模式區分：EXACT_SPEC 附 structural anchor 原文或唯一語意識別字；GOAL_SPEC 僅定義目標、邊界與驗收準則，不要求錨點。**固定行號僅作輔助說明，非 blocking truth** |
| E4 機器驗證證據落地 | 提示詞要求執行 Required Machine Gates 且證據寫入 docs/EXEC-LOG.md / GitHub，未要求在對話貼出完整 Gate 輸出 |
| E7 回報通道約束 | 提示詞未要求正常成功批次貼出 full diff / full file / terminal dump，遵守 Repo Evidence Channel 契約 |
| E10 零命中條件的自身檢查 | 提示詞若有「字串 X 應為零命中」，檢查 X 是否出現在提示詞本身的其他位置——**純字串比對，非語意判斷** |
| E11 錨點唯一性驗證 | **僅在 EXACT_SPEC 模式下檢查**：執行者以確定性工具（BPE、`count()` 或 spec parser）於套用前驗證錨點在目標檔 count == 1；**GOAL_SPEC 模式為 N/A，不要求 Batch Spec 錨點** |
| E13 配對與覆蓋 | 依 §3.1、§3.2 比對。GOAL_SPEC 比對 Allowed Scope ↔ actual changed files ↔ explicit git add ↔ gates；EXACT_SPEC 比對 allowed scope ↔ spec targets ↔ git add ↔ gates，不依賴手寫行數／圍欄清單 |
| E14 自檢聲明區塊 | 區塊存在且項目連號無缺 |
| E15 錨點基準來源 | **僅在 EXACT_SPEC 模式下檢查**：錨點對應本批 base commit full OID 與規格上下文，不依賴特定第 N 行；**GOAL_SPEC 模式為 N/A** |
| E16 跨檔引用同行 | 寫入文字中的 `§X.Y` 若跨檔，檔名與章節號在同一行 |
| E17 結構序列驗收 | 若插入或結構變更涉及語意驗收條件（如章節／項目順序），附明確驗收準則；**不得將 LLM 預測所有 post-state 衍生序列當作通用 blocking 條件** |
| E18 機械前置證據 | 依 §3.6 確認包含 base full OID、batch mode、Allowed Scope 與標準驗證指令；EXACT_SPEC 才額外要求 spec path 與 SHA；**不得要求手寫 line/fence snapshot** |
| E19 移除前複查 | 提示詞若含刪除檔案／章節／規則／看板項目，檢查是否附有三步複查結果（反向引用掃描、唯一內容確認、獨立複查）。**純存在性比對，非語意判斷**——不必判斷複查做得對不對，只判斷有沒有 |
| E20 規則層變更的模擬授權 | EXACT_SPEC 規則層變更由同一份 Batch Spec 經 BPE 與 check_consistency 模擬驗證；GOAL_SPEC 由單元測試與 Gate 驗證守護，不需規格模擬；**Auditor 不得預抄套用後行數、圍欄數、項數或 INFO 輸出作為 blocking truth** |
| E21 衍生數值不作 blocking truth | 基準 commit 必須與執行者實測 HEAD 一致；**所有 machine-derived values（行數、圍欄數、test count、CHECK count、INFO 輸出等）由確定性工具產出，不得由 LLM 複製成提示詞 blocking truth** |
| E22 審計狀態權威檢查 | 確認提示詞未要求建立 audited tag 作為完成條件；審計狀態以 AUDIT-LOG、refactor-backlog §5.1 與 GitHub Actions 為 Single Source of Truth |
| E23 批次規格進 repo | **僅在 EXACT_SPEC 模式下檢查**：提示詞附有 `docs/batches/<base-hash>-<slug>.spec.txt` 的路徑與該規格的 sha256，且出現在本批的 `git add` 清單中。**GOAL_SPEC 模式不要求規格進 repo，不得因缺規格而判缺失** |

**自檢聲明不接受任何豁免。**

上表任一項比對為「否」時，**一律停止並回報**，不論審計官是否附上理由。
審計官在提示詞中把某項標為 ⚠️、寫明「本批刻意不做」、
或宣稱「知情偏離」，**都不構成豁免**。

**為什麼**：2026-09-06 審計官把 E8 標為 ⚠️ 並附理由
（「這是緊急修正，範圍壓到最小」），你接受了、沒有停止，
結果 CHECK 12 在 CI 上 FAIL——因為 `.claude/rules/auditor-protocol.md` §6.1
第 8 項有機械守衛，而審計官沒查。你當時無法判斷那個理由成不成立，
依 `.agents/rules/role-boundaries.md` §2 你也不該判斷。

**所以規則改成不需要你判斷**：比對為否就停，理由留給審計官自己處理。
審計官若真的需要偏離 `.claude/rules/auditor-protocol.md` §6.1 的任何一項，
唯一合法路徑是**先另開一批修改規則本身**，不得在提示詞裡自行豁免。

這一條同時修補了 §3.7 的破口：該節寫「沒有任何一項需要你憑信任接受」，
但在本條加入之前，只要審計官寫一句理由，任何一項都能變成信任項。

其餘各項需要語意判斷，**不在你的驗證範圍**——
依 §3.3，若你有疑問就當成【疑問】回報，不當成【缺失】。

**回報格式：**

    【自檢聲明交叉驗證】
    區塊存在：是／否
    項目數：N（應為連號無缺）
    可驗證項目比對結果：
      E1 聲明 ✅ / 實際 有 → 一致
      E8 聲明 ✅ / 實際 缺「AUDIT-LOG」 → **不一致，停止**

**為什麼要交叉驗證**：自檢聲明如果只是宣告，審計官打勾就過了，
等於沒有檢查。交叉驗證讓它變成**可被推翻的宣稱**——
這是「審計官也不能審自己」在提示詞層次的實作。

## 3.5 檢查結果只存在於回報中，這是已知缺口

你每批做的七項結構元素檢查、配對與覆蓋檢查、自檢聲明交叉驗證，
**目前只存在於你的回報裡，repo 中沒有任何痕跡**。

若某批漏做或放水，事後無從查證。這與 `.claude/rules/auditor-protocol.md` §7.1 指出的「沒有留下證據的控制等於沒有控制」是同一個問題，只是發生在執行者這一側。

**這是已知缺口，登錄為 `docs/TASKBOARD.md` B-14**，
處置方向是建立執行者側的檢查紀錄檔（對應審計官的 `docs/AUDIT-LOG.md`）。
在它建立之前，**你的回報就是唯一證據**——因此不得簡化、不得只寫「通過」，
必須逐項列出檢查了什麼、結果為何。

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
| 規格 SHA 一致 | 僅 EXACT_SPEC 檢查：由 `scripts/build_prompt_evidence.py` 或確定性工具計算規格 sha256，與提示詞宣稱值完全一致；GOAL_SPEC 為 N/A |
| 範圍與驗證指令齊備 | 規格修改目標完全落在 Allowed Scope 內，且包含標準驗證指令 |

**核心原則（Machine Truth）**：
目標檔案行數、圍欄數、測試數量、CHECK 總數、套用後行數／圍欄數及 INFO 輸出等，皆為**確定性工具在執行當下產出的衍生診斷數值（derived diagnostic truth）**。
**提示詞不得再將這些衍生數值抄寫為 expected blocking truth，執行者亦不得因手寫衍生數值不符而停止執行。**
所有內容完整性、重放正確性與變更安全，一律交由 Batch Spec 與 repository machine tools（如 BPE、`check_consistency.py` CHECK 17 規格重放、`fingerprint.py --verify` 等）嚴格守護。

## 3.7 E 節每一項都可機械驗證，沒有例外

`.claude/rules/auditor-selftest.md` E 節的**每一項**，
§3.4 的交叉驗證表全數涵蓋。**沒有任何一項需要你憑信任接受。**

**本節刻意不寫項數。** 2026-09-06 實證：本節標題與內文原寫「十八項」，
而 E 節在同日已增為 19 項，標題當場失準且無任何機制會發現。
凡是會隨內容增長而漂移的數字，不寫進散文——
需要知道實際項數時去數，不要讀一個會過期的宣稱。

**歷史**：2026-09-05 §3.4 原本只涵蓋 7 項，其餘 11 項審計官勾 ✅
無人能反駁——E11 造假（宣稱七個錨點皆實測、實際只量三個）正是從那個洞出來的。
**問題不在審計官特別不老實，在那 11 項本來就沒有約束。**

其中 E10 一度被審計官判定為「需語意判斷、無法機械驗證」，
但那是誤判：「檢查零命中條件的字串是否出現在提示詞自身」
**是純字串比對**。錯誤的「無法驗證」判定，等於自己開一個新的洞。

**若日後 E 節新增項目，§3.4 必須同批新增對應列。**
新增時先問：「這一項要怎麼用字串比對驗證？」——
答不出來就代表該項的措辭需要改寫，**不是接受它無法驗證**。

## 3.8 你的檢查結果必須留在 repo

每批完成後，在 `docs/EXEC-LOG.md` 追加一列，記錄本批你做了哪些檢查、
結果為何、攔下了什麼。欄位固定為五欄：

    | 批次 commit | 日期 | 檢查範圍 | 結果 | 攔截紀錄 |

- **檢查範圍**：實際執行的節次，例如「§3 七項、§3.1、§3.2、§3.4 全項、§3.6」
- **結果**：通過或不通過，不通過時寫明哪一項
- **攔截紀錄**：本批攔下了什麼；無則寫「無」

**為什麼**：在此之前，你每批的檢查結果**只存在於回報中，repo 沒有痕跡**。
若某批漏做或放水，事後無從查證。
審計官有 `docs/AUDIT-LOG.md` 作為自我審查的證據，
**執行者這一側原本什麼都沒有**——那是整套機制最後一個沒有證據的環節。

`scripts/check_consistency.py` 的 CHECK 16 驗證本檔不落後於 HEAD，
判準與 CHECK 12 對 `docs/AUDIT-LOG.md` 的驗證相同。

**首列例外**：本檔建立於 2026-09-05，第一列標記為 `BOOTSTRAP`，CHECK 16 跳過該值。

## 4. 錨點唯一性驗證（僅 EXACT_SPEC 動手前必做）

> 註：本節僅適用於 `EXACT_SPEC` 模式。在 `GOAL_SPEC` 模式下，由執行者自主實作，不強制要求 Batch Spec 錨點驗證。

在執行任何寫入之前，把提示詞中的**每一個**錨點字串取出，逐一驗證：

    import io
    t = io.open(目標檔案, encoding="utf-8").read()
    print(t.count(錨點字串))   # 必須恰好是 1

- **count = 0** → 錨點不存在，停止並回報實際內容為何
- **count > 1** → 錨點不唯一，會改到錯的地方，停止並回報命中位置
- **全部為 1** → 才開始寫入

**這一步的價值在於它把失敗提早到寫入之前。** 2026-09-02 的第三次錨點失誤
就是靠這個手法在動手前發現的——若等到執行時才失敗，工作區已經有部分修改，
還要回滾。

回報格式：

    提示詞前置檢查未通過：
    - 結構元素缺少：第 N 項 <元素名稱>
    - 錨點驗證失敗：修改 X 的錨點在 <檔案> 中 count=<n>
      實際最接近的內容為（附行號）：<原文>
    本批未執行任何修改，工作區維持乾淨。
    請審計官更正後重新提供。

**不得自行找看起來最像的地方套用。** 猜測一次成功，會讓所有人以為機制有效。

## 4.1 寫入後的原文驗證（動手後必做）

§4 的錨點驗證檢查的是**修改前**——「找不找得到要改的地方」。
本節檢查**修改後**——「有沒有改成指定的樣子」。

每完成一個「整段替換為」或「插入以下內容」的修改，
立刻驗證：

    t = io.open(目標檔案, encoding="utf-8").read()
    print(t.count(指定的新內容))   # 必須恰好是 1

- **count = 1** → 寫入正確
- **count = 0** → 寫入的內容與指令不符，**停止並回報**

**為什麼需要這一節**：2026-09-04 發現交接區 §5.1 的兩個項目符號
被改寫成不同措辭，且改寫後的數字與事實不符
（「6 檔異動」→「3 改 0 新檔」、「驗證三項」→「驗證四項」）。

當時的機制查不到——§4 只驗證修改前的錨點，
寫入之後沒有任何回頭比對。**前置驗證確認「找得到」，
後置驗證確認「改對了」，兩者缺一不可。**

---

## 5. 例外

以下情況不適用第 3 節，直接依提示詞執行：

- 提示詞明確標示為「只讀不改」的批次（不會產生 commit，
  自然不需要第 5、6 項）
- 提示詞明確標示為「緊急修正」並說明略過原因

**第 4 節的錨點驗證沒有例外。** 只要有寫入，就要先驗證。

---

## 6. 這條規則保護的是誰

不是保護你，也不是保護審計官，是保護專案。

雙方都放棄一部分自主：審計官不動檔案、你不做決策、
而現在**你也檢查審計官的產出格式、審計官也核對你的執行結果**。
換到的是「沒有任何一方能獨自把事情做錯而不被發現」。
