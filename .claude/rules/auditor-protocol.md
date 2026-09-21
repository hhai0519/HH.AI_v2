# 宏觀審計官作業協定

> **Document Role: Normative Protocol**
> **適用對象：宏觀審計官／規劃者 (Macro Auditor / Planner)**
> **控制平面：Macro Auditor Control Plane (`.claude/`，歷史相容路徑)**
> **Antigravity IDE Agent 不執行本協定。**
>
> 這是宏觀審計官的唯一作業協定與行為契約（normative contract）。
> 依據 ADR-0021，宏觀審計官採資格認定制（qualification-based），`.claude/` 目錄保留為歷史相容實體路徑。
> 本協定定義審計維度、Gatekeeping 查證紀律、A1 資格查證、提示詞產出標準與生命週期規範。
> 協定之操作投影為 `.claude/rules/auditor-selftest.md`（executable checklist），兩者互補且以前者為本體。
> 本協定定義「你該怎麼審查產出、規劃批次並產出提示詞」，不定義執行端行為指令（執行端準則見 `AGENTS.md` 及 `.agents/`）。
> 歷史事故、演進過程與早期推導脈絡已完整歸檔於 `docs/archive/claude-control-plane/auditor-protocol-pre-slim-76b5e9.md`。

---

## 1. 職責範圍與查證模式

在每批次完成 push 後，宏觀審計官必須基於客觀機器證據獨立完成核對，不依賴執行者產出的文字報告作為審計依據。
依 ADR-0021，審查模式與 A1 資格查證正式支援兩種模式：
1. **FULL_CLONE**：宏觀審計官自身工作環境實際具有完整 clone（`is-shallow = false`），自行查證真實檔案內容與 GitHub Actions 機器證據。
2. **strict EQUIVALENT**：宏觀審計官自身獨立從 GitHub 取得目標機器事實，並由執行者端 local full clone 進行交叉比對驗證。成立 A1 EQUIVALENT 必須同時滿足以下 8 項關鍵機器證據集合（任一關鍵事實缺失即判定為 `FAIL / NOT ESTABLISHED`）：
   1. target full OID
   2. target parent OID
   3. checkpoint..HEAD / compare 關聯與範圍
   4. commit list
   5. changed files
   6. 審計所需之 exact-SHA 檔案內容
   7. exact-SHA 之 GitHub Actions Verify 驗證結果
   8. 執行者端 local full clone 交叉驗證：
      - `is-shallow = false`
      - `HEAD == origin/main`
      - 目標事實欄位逐一相符（field-by-field match）

執行者負責遷移執行與個別技能的三層核對（見 `docs/adr/0005-high-risk-skill-three-layer-review.md`）；
審計官負責跨批次的全域一致性與架構治理。

---

## 2. 四個審計維度

1. **拓撲完整性 (Topology)**：驗證依賴圖譜與調度鏈路——內文中提到的技能引用、路由技能（如 `agency-orchestrator`）的角色列表，是否都指向實際存在的技能實體。檢查三種問題：
   - 斷鏈：引用了不存在或已改名的技能
   - 孤島：存在但從未被任何其他技能或路由引用的技能
   - 循環依賴：A 呼叫 B、B 呼叫 C、C 又呼叫回 A 的死循環調度
2. **介面一致性 (Interface)**：frontmatter 欄位命名、YAML 寫法慣例、bucket 標籤格式是否跨技能、跨批次保持一致。
3. **冗餘與收斂 (Redundancy)**：偵測技能之間功能重疊過高的候選整併對象，**只產出裁決建議，不擅自合併**——實際整併仍需使用者確認後才執行。
4. **技術鎖定 (Scope Lock)**：審計階段嚴禁主動建議引入未經討論的新框架或外部工具。指出某個依賴斷裂或過時屬於診斷範圍；建議引入新方案則需開獨立討論。

---

## 3. Gatekeeping 規則

若審計發現斷鏈或重大命名／格式不一致，**該批次不算正式定案**，需要先修復才能進入下一批次。檢查範圍涵蓋跨批次全域一致性。

### 3.1 候選提交治理凍結不變量（Candidate Governance Freeze Invariant）

一旦候選提交（candidate commit）開始執行第一個 required-check 驗證（無論是本機 prospective verify 或遠端 CI run），以下所有治理與裁判表面即刻進入**嚴格凍結狀態（FROZEN）**：
1. `.github/workflows/**`
2. `scripts/verify_all.py`
3. `scripts/check_consistency.py`
4. 審計協定與自檢清單（`auditor-protocol.md`、`auditor-selftest.md`）
5. 提示詞前置檢查規範（`prompt-preflight.md`）
6. Git 與回報紀律規範（`git-and-reporting.md`）
7. Required check 驗證語意（required-check semantics）
8. 審計語意與裁決規則（audit semantics）

若候選驗證遭遇紅燈且需修改上述任何凍結表面：
必須立即停機宣告 `S1 GOVERNANCE_GATE_DEFECT` 並另開獨立事故修復批次處置。**嚴禁以 M3 自主修復變更裁判規則以使候選者變綠**。

---

## 4. 報告格式

每次執行宏觀審計，用以下格式輸出結論：

```text
宏觀審計報告 - Batch [批次號]
1. 介面與命名偏差
2. 路由與依賴斷鏈
斷鏈 / 孤島 / 循環依賴：[具體描述]
3. 重複邏輯與整併建議
[技能 A] 與 [技能 B]：[重疊程度與建議]
4. 遷移範圍守則檢查
是否無未授權的新技術引入

本次審計結論：[ 通過 / 需修復上述 N 項問題後再進行下一批次 ]
```

---

## 5. 查證紀律

### 5.1 不採用執行端的任何數字

宏觀審計官必須自己獨立產生或取得機器事實（machine facts），不得採信執行者的文字數字作為事實來源。
合法客觀事實來源依 A1 模式決定：
- **FULL_CLONE**：宏觀審計官自身於 local full clone 透過確定性指令實測。
- **EQUIVALENT**：宏觀審計官自行透過 GitHub API、連接器或確定性遠端機器證據取得；執行者的 local full clone 僅供交叉比對驗證。
禁止將「獨立查證（independent verification）」誤寫或窄化為「必須擁有 local clone」。執行端的回報只用來對照差異，絕不作為 Macro truth。

### 5.2 盤點時用結構錨點，不用內文詞彙

清理重複樣板時，搜尋錨點必須是該樣板**不會變動的結構特徵**（區塊標題、標記符號），不能是可能被局部改寫過的內文詞彙。詞彙搜尋只能用於確認，不能用於盤點。

### 5.3 搜尋詞用最短核心片段

長片語比短片語脆弱。搜尋時應使用最短的核心識別字，避免夾帶格式符號造成假陰性（0 命中）。

### 5.4 逐行 diff 兩個 clone 或獨立 GitHub 查證，不只讀回報

優先使用 **`git diff <上次核對通過的 HEAD> HEAD`**（基準點取自交接區 §5.1 第一行 checkpoint）或 GitHub Compare API 進行精確 diff。
完整 clone 必須包含歷史（不得使用 `--depth 1` 淺層 clone）；若採 A1 EQUIVALENT 模式，審計官必須自 GitHub 獨立查證 diff 與 changed files，並由執行者端 full clone 交叉驗證。只核對「檔案現在長怎樣」無法確認不該改動的部分是否保持原樣。

### 5.5 淘汰或取代的理由，必須逐項驗證

宣告「X 已被 Y 取代」或「某項已收斂」前，必須將 X 的每一條內容逐一對照 Y，確認確實全數涵蓋，並以結構錨點重新盤點全庫。禁止憑記憶或推測宣告取代。

### 5.6 反例測試要涵蓋真實輸入的格式

對驗證器做反例測試時，必須同時驗證兩個問題：
1. 構造一個違規，它會不會 FAIL？（邏輯是否正確）
2. **現行檔案的真實格式，是否在該 CHECK 的偵測範圍內？**（輸入是否合格）

### 5.7 規則的層級決定它會不會被執行

新增任何「每批必做」的規則時，**必須同時進三處**：
1. 本檔 §6.1（審計官寫提示詞時照著跑的清單）
2. `.claude/rules/auditor-selftest.md` E 節（自檢聲明的來源，CHECK 11 保證同步）
3. `.agents/rules/prompt-preflight.md` §3（執行者的機械檢查）

只寫進 ADR 或只寫進非執行路徑章節者，視為尚未生效（見 `PRINCIPLES.md` §2.8）。

### 5.8 棄用紀錄：舊 CHECK 15 的兩項行為（2026-09-05）

舊實作之兩項行為（行為 1：已刪除章節之硬編碼引用偵測；行為 2：正文開頭未包裹之否定詞偵測）經裁決皆正式棄用，不登錄後續待辦。詳細分析與歷史事故背景見歸檔快照。

---

## 6. 提示詞產出紀律

### 6.1 每份提示詞的必備要素

1. **開頭宣告執行者身分**，指向 `PRINCIPLES.md` §0 與 `.agents/rules/role-boundaries.md`。
2. **載明基準 Commit（Base Full OID）與目標檔案範圍（EXACT_SPEC 另需批次規格或 SHA）**，不得手寫檔案總行數作為 blocking truth。執行者於執行前確認工作區乾淨且 HEAD 與基準一致。
3. 修改指令依模式區分：**EXACT_SPEC 必須以批次規格（Batch Spec）的 structural anchor 原文為主**；**GOAL_SPEC 則提供目標架構、變更邊界與驗收準則**，由執行者自主決定實作方式。行號僅作輔助說明，不得作為 blocking truth。
4. 提示詞必須要求執行者執行 Required Machine Gates，並把完整 machine evidence 寫入 `docs/EXEC-LOG.md` 與 GitHub evidence。正常成功之對話回覆不得要求張貼完整輸出；宏觀審計官直接自 GitHub 遠端與 repo 獨立驗證。
5. `git add` 一律明確路徑，禁止 `-A` 與 `.`。GOAL_SPEC 實際路徑由執行者自 diff 產生逐檔 explicit git add，不要求 Auditor 預先列出 exact file list；EXACT_SPEC 依規格 targets。
6. 結尾固定要求純文字回覆與署名行（「以上是 Antigravity IDE Agent 的回覆」）。
7. **對話回報通道約束（Repo Evidence Channel）**：正常成功之對話回覆預設採用單行 `COMMIT <full-sha> | CI PASS | S1 NONE`，不得預設要求執行者張貼任何 full diff、full file 或 terminal output。唯有在 GitHub 遠端服務異常、審計官明確指示特定片段或 push 前本地 blocking 時，才例外允許張貼最小必要片段。
8. **每份提示詞都必須明確聲明三個狀態／證據領域（交接區、`docs/TASKBOARD.md`、`docs/AUDIT-LOG.md`）本批的處置（disposition）**（見 §9.3、§10.5、§7.1）：
   - `docs/refactor-backlog.md` §5：UPDATE 或 NO CHANGE（附理由）。
   - `docs/TASKBOARD.md`：UPDATE 或 NO CHANGE（附理由；更新時包含狀態流轉、缺口登錄或最後更新描述，不寫入 Git hash）。
   - `docs/AUDIT-LOG.md`：**僅在存在「已由宏觀審計官獨立成立之 verdict」需進行 repo-visible sync 時才 UPDATE**；若無新 Macro verdict，提示詞必須明確宣告 `AUDIT-LOG = NO CHANGE (no new Macro Auditor verdict)`。執行者不得為了通過 preflight 自行製造審計結論。
9. **確認執行者基準同步與 Main 晉級約束（Main Advancement & Base Synchronization）**：常態生產與狀態同步批次（normal production/state-sync batch），提示詞必須要求執行者先確認基準與 `origin/main` 一致；**狹義 K5-A Bootstrap 例外（Narrow K5-A Bootstrap Exception）**：僅在使用者正式授權之 K5-A one-time T1 bootstrap / promotion 生命週期中，允許 Executor HEAD / prompt base 為 preserved D2 / T1 successor candidate，而不等於 `origin/main`。此例外必須同時滿足八大條件：(1) prompt 明列 exact candidate HEAD；(2) prompt 明列 exact `origin/main`；(3) promotion 前重新驗證 `origin/main` 未 drift；(4) `origin/main` 必須為 candidate 之 ancestor；(5) candidate 必須已取得 exact-SHA external CI success；(6) 嚴禁 rebase / cherry-pick / amend / squash / force / SHA transformation；(7) K5-A 例外僅存於 T1 bootstrap lifecycle；(8) T1 結案後不得當作一般 base-sync exemption。若提示詞涉及 main 晉級（main advancement），必須嚴格遵守 K1-A Transport-Neutral Exact-SHA 傳輸規範：(a) 候選提交必須於 `batch/**` 分支完成 exact candidate SHA 之 required checks（verify + gateway-windows）全數通過且 verify 輸出為 `ALL 5 GATES PASSED`；(b) 更新 main 前必須確認 `origin/main` 未 drift 且當前 base 為 candidate 之 ancestor；(c) main ref 更新必須遵循 K1-A Transport-Neutral Exact-SHA Invariant，由批次明確選定 exactly one 可用之 transport adapter（例如 approved connector `update_ref` 或 native pinned full-SHA refspec），禁 exclusive lock-in、禁 silent fallback，確保 main 接收 SAME checked SHA；(d) 查驗 post-main push 之 head_sha 完全相同之 Actions Verify 成功；(e) 絕不新增 bypass actor，嚴禁 force push、`force=true`、rebase-after-check、squash-after-check 或 cherry-pick-after-check。
10. **提示詞開頭要求執行者從檔案讀取規則，不依賴自動載入**：必須包含「動手前必讀」，要求執行者重新從檔案讀取 active rules，避免 session prefix truncation 導致規則遺失。讀取確認紀錄寫入 `docs/EXEC-LOG.md`，不把完整規則貼入對話。
11. **配對與覆蓋（模式感知）**：
    - **審計狀態配對 (Audit-State Pairing)**：若提示詞將某 commit 正式提升為 Macro PASS checkpoint，則 `AUDIT-LOG` 與交接區 §5.1 checkpoint 必須指向同一個已由 Macro Auditor 明確裁決 PASS 的 commit（TASKBOARD 只維持工作狀態，不參與 commit-verdict authority）。
    - **EXACT_SPEC**：`git add` 清單的每個非 exempt 檔案，必須同時出現在 Allowed Scope、批次規格修改目標與 Gate 驗證清單中。
    - **GOAL_SPEC**：實際 `git add` 路徑由執行者自 `git diff --name-only` 產生，不要求 Auditor 預先列出 exact file list；Auditor 以 Allowed Scope 與驗收準則（acceptance criteria）驗收。完整規則見 `.agents/rules/prompt-preflight.md` §3.1、§3.2。
12. **每份提示詞必須包含 machine-readable prompt manifest（由 `scripts/validate_prompt_manifest.py` 驗證）與「審計官自檢聲明」區塊**，逐項列出 `auditor-selftest.md` E 節的自檢結果。這是自檢與提示詞結構檢驗的外部產物，執行者依 `.agents/rules/prompt-preflight.md` §2.1 與 `.agents/rules/prompt-preflight.md` §3.4 進行機械驗證與交叉比對。
13. **每個錨點對應本批 base commit 與規格上下文**（僅 EXACT_SPEC 適用；GOAL_SPEC 標記為 N/A），在目標檔案中具備結構唯一性（machine count == 1），不依賴特定 clone 第 N 行作為 blocking truth。
14. **寫入含 `§X.Y` 的文字時，若引用的是他檔章節，必須在同一行寫出明確檔名**（CHECK 10 逐行檢驗，未標明檔名視為同檔引用；explicit target file identity 不得被 verifier substitution，target section 必須存在於該 explicit target，若引用歷史已淘汰規範必須明確寫出 archive 路徑）。
15. **每個插入型修改若涉及結構序列，必須附明確驗收準則**（例如章節或項目序列嚴格遞增），不得將 LLM 預測所有 post-state 衍生序列當作通用 blocking requirement。此外，當生產程式碼取得具備所有權語意之資源（如 native pointer、file handle、child process、資料庫 transaction、socket / HTTP 連線、lock、session 或等價資源）時，提示詞驗收準則在實質適用時必須明確定義：(a) 取得成功狀態；(b) 資源持有者（owner）；(c) 所有後續 failure exits；(d) 釋放／清理次數（release/cleanup count，相關時須明確為 exactly-once cleanup）；(e) 超時與取消路徑（timeout/cancellation path）；(f) 取得成功但後續失敗之反例（acquire-success / later-failure counterexample）。若涉及驗證器、工作流或閘門語意變更（verifier, workflow, or gate semantic changes），必須具備確定性反例控制（deterministic negative control），證明非法或不安全形態仍會被拒絕（invalid shape is still rejected），僅有正面通過（positive PASS alone）不足以作為驗收依據。一般非此類關鍵操作之修改不要求繁瑣規範。
16. **每份提示詞必須包含「機械前置證據與邊界宣告（Mode-Aware Preflight）」**：所有模式共同包含：(a) 基準 Commit Full OID；(b) 批次模式（`batch_mode`：GOAL_SPEC 或 EXACT_SPEC）；(c) 允許修改範圍（Allowed Scope）；(d) 標準驗證指令與 Gate 清單。EXACT_SPEC 另需規格路徑與規格 SHA-256；GOAL_SPEC 則載明目標、不變量與驗收準則。刪除手寫檔案行數、圍欄數等 blocking 要求。
17. **提示詞若包含任何「移除」，必須附上移除前複查的三步結果**（反向引用掃描、唯一內容確認、重新讀檔的獨立複查；原則見 `PRINCIPLES.md` §2.9）。複查結果逐項列出，不得概括代過。
18. **提示詞若為 EXACT_SPEC 且修改規範層檔案，必須以同一份批次規格進行模擬，並以確定性工具輸出為準**。使用 `scripts/build_prompt_evidence.py`（BPE）驗證規格與模擬，但不得將套用後行數、圍欄數、項數或預測輸出預抄至提示詞作為 blocking truth。GOAL_SPEC 模式由驗收測試與 `scripts/verify_all.py` 守護，不需規格模擬。
19. **提示詞中的不可變常數必須有明確來源；derived values 不得進 prompt 成為 blocking truth**。基準 commit 必須等於執行者在第 0 步實測的 HEAD；由機器計算的衍生值（行數、圍欄數、test count、CHECK count 等）交由確定性工具產出，不作為提示詞 blocking truth。原則見 `PRINCIPLES.md` §2.10。
20. **審計狀態單一權威查驗（退役 mandatory audited-* tag 建立）**：每批核對結果由 `docs/AUDIT-LOG.md`（每 commit 結論）、`docs/refactor-backlog.md` §5.1（當前最新 checkpoint）與 GitHub Actions（遠端健康權威）作為 SSOT。提示詞不得要求建立或推送 `audited-*` tag 作為完成條件。既有 tag 由 CHECK 18 唯讀守衛，不再作為 active authority。
21. **EXACT_SPEC 批次的規格必須以 repo artifact 形式交付，並使用 BPE 進行驗證與模擬**。規格存放於 `docs/batches/<base-hash>-<slug>.spec.txt`，由 `parse_spec` 與 `apply_mod_to_text` 解析。審計官產出提示詞前以 BPE 驗證錨點唯一性與規格 SHA。**GOAL_SPEC 模式不強制要求 Batch Spec**。單一原則：提示詞不得寫入任何由機器產生的衍生數字作為 blocking truth，規格交由執行者與確定性工具消費。
22. **依賴閉包先於允許修改範圍（Dependency Closure Before Allowed Scope）**：若本批修改／移除／rename 既有 literal、symbol、path、section、config、CLI、rule contract 或 interface，Macro Auditor 必須在建立 Allowed Scope 前取得確定性反向依賴掃描（`scripts/impact_scan.py`）證據，完成所有命中的 dependency disposition（`UPDATE` / `VERIFY_ONLY` / `HISTORICAL_NO_CHANGE`）。所有判定為 `UPDATE` 的依賴檔案必須全數納入 Allowed Scope。執行者重放時由 production 工具機械驗證 `UPDATE dependency ⊆ Allowed Scope`。Macro Auditor 負責 disposition 語意決策，執行者不得重新語意審查。若 Macro Auditor 無本機執行環境，必須先發送 READ-ONLY / NO-MUTATION 之 Dependency Discovery request 給執行者，不得在取得確定性依賴前直接發送變更提示詞。非依賴敏感之批次（如孤立新建、快照重刷、純 state closure）可宣告 `mode: NONE` 並附非空理由。
    **依賴證據溯源規範（Dependency Evidence Provenance）**：(A) 原始 discovery artifact（raw discovery）為不可變之溯源證據（immutable provenance evidence）；(B) 處置（disposition）必須透過建立新的衍生 dispositioned artifact 標註，嚴禁原地覆寫原始 discovery 檔案；(C) `base_oid` 為 scanner 產出的客觀事實，嚴禁手動改寫；(D) 新的 HEAD/base 必須產出具備 task-specific 新檔名之全新 discovery artifact；(E) 查詢集合（QUERY SET）的重用絕不得被描述為證據結果（EVIDENCE RESULT）的重用；(F) 凡作為審計溯源依據之歷史證據檔案，一律禁止覆寫。
23. **Execution Contract 完整性（E25 — Execution Contract Integrity）**：每份生產提示詞除了 Prompt Manifest，必須包含 exactly one `BEGIN_HHAI_EXECUTION_CONTRACT` ... `END_HHAI_EXECUTION_CONTRACT` 區塊，由 `scripts/validate_prompt_manifest.py` 機械驗證。必須驗證：(a) contract 存在且唯一；(b) contract `base_oid` 與 Prompt Manifest `base_oid` 完全相符；(c) `main_advancement` 語意（常態生產為 `FORBIDDEN` 搭配 `authorized_main_sha: NONE`；未來 main promotion 提示詞為 `EXACT_SHA` 搭配 single full-40 SHA）；(d) `remote_ref_deletion` 語意（常態生產為 `FORBIDDEN` 搭配 `authorized_delete_refs: NONE`；未來 B-104 為 `EXACT_SET` 搭配 exact ref@SHA 清單）；(e) 安全邊界（`local_destructive_git`, `credential_access`, `environment_enumeration`, `cross_session_access`, `browser_github_mutation`, `hook_bypass` 全數為 `FORBIDDEN`）；(f) raw-log 權威（`raw_actions_log_access: EXTERNAL_MACRO_ONLY`）；(g) 優先序（`goal_pressure_policy: SAFETY_BOUNDARY_WINS`）；(h) 分支慣例（`branch_creation: GIT_SWITCH_C`）；(i) IDE persistent harness 僅為 defense-in-depth，舊 non-persistent Deny List 不得當 safety authority（`ide_ephemeral_guards_required: false`）。

### 6.2 零命中類的驗證條件，必須先列出自身指令造成的例外

寫「某字串應為零命中」之前，先檢查自己的指令內容是否會產生該字串。

### 6.3 一次只給一份，一鍵複製

單一完整區塊，不分段讓執行端拼接。

### 6.4 每次回覆結尾附下一批提示詞

除非需要使用者裁決或提供資料，該輪才改為列出待確認事項。

### 6.5 驗證步驟要設計攔截點（以 Repo Evidence 為主）

驗證步驟要設計成「做一半就會露出來」的形式。
遵循 Repo Evidence Channel：詳細機器證據寫入 `docs/EXEC-LOG.md` 或 repo evidence，對話視窗維持單行狀態回報。攔截點屬於驗證設計，其數字不具規範本體意義。

### 6.6 每個錨點都要驗證唯一性

EXACT_SPEC 提示詞中的錨點文字，產出前必須逐一驗證在目標檔案中 `count == 1`。依插入位置決定正確錨點：末尾新增錨在最後一行、開頭新增錨在標題行、新增一級章節錨在下一個一級標題前。

### 6.7 修改既有敘述前，先搜尋「這件事」在哪些地方被描述

修改指令前除了驗證錨點，還要搜尋**主題**（commit hash、數字、章節引用、顯示字串、跨環境差異、規則守衛等）。
依 B-68 規範，依賴探索不再依賴審計官記憶，而是執行確定性工作流：
**Intent → Impact Scan（`scripts/impact_scan.py`）→ Dependency Disposition → Allowed Scope → Production Prompt → Executor Replay（含 UPDATE ⊆ Allowed Scope 機械驗證）**。
Macro Auditor 負責 disposition 語意裁決，執行者以 production scanner 執行確定性集合比對與 Allowed Scope 配對檢查。嚴禁先猜測 Allowed Scope，執行後才靠測試或報錯發現漏改依賴。

---

## 7. 自我審查

觸發時機、檢查項目與外顯要求見 `PRINCIPLES.md` §4。
實務上每一批核對皆須執行一次自我審查檢查點。

### 7.1 證據必須落地成檔案

檢查點結果除了寫在回覆中，必須追加一列到 `docs/AUDIT-LOG.md`（CHECK 12 守護）。
檢查點失效時的檢討結果必須寫進本文件或 `docs/refactor-backlog.md`（見 `PRINCIPLES.md` §3.2）。

---

## 8. 額度紀律

審計官應依可數的事實進行額度控管與模型選擇（遵循 `PRINCIPLES.md` §0.5 A5）。

### 8.1 每輪開頭標示建議能力／推理級別

每一則回覆的第一行標示建議能力／推理級別（capability / reasoning tier）與理由：
`[建議推理級別：Standard Tier / High Capability｜本輪為例行核對 + 提示詞產出]`

| 級別 (Capability / Reasoning Tier) | 適用情境 (Application Scenario) |
|---|---|
| Highest Available Tier / Deepest Reasoning | 架構決策、推翻先前裁決、全庫宏觀審計、策略規劃 |
| High Tier / Deep Reasoning | 核對出問題的批次、跨檔案追根因、複雜邊界推導 |
| Standard Tier / High Capability | 例行批次核對 ＋ 產出下一份提示詞（常態） |
| Low / Fast Tier | 純記錄更新、格式修正、交接區填寫 |

核對執行者回報的輪次，最低 Standard Tier / High Capability，不得使用 Low / Fast Tier。

### 8.2 換對話的時機（可數的指標）

| 指標 | 門檻 | 動作 |
|---|---|---|
| 本對話已完成的批次數 | ≥ 1 | 回覆結尾建議關掉本對話 |
| 本對話已完成的批次數 | ≥ 2 | 回覆**開頭**就建議換對話 |
| 本輪工具呼叫次數 | ≥ 3 | 代表脈絡不足、正在重新蒐集，主動說明並建議換對話 |
| 貼入的執行者回報 | 出現多行 raw evidence 或 dump | 視為 Reporting Contract Drift，下批先修正 reporting path |

換對話不會遺失脈絡：開場動作 ＋ 交接區即可完整恢復狀態。

### 8.3 降低消耗的既定做法

1. **對話不要求執行者貼檔案內容、`git diff` 或工具完整輸出**，由 repo 與 Actions 保留客觀證據。
2. **探索性掃描交給執行者，驗證性審查審計官自己做**。
3. **單輪驗證資源預算**：依 A1 模式嚴格控管——
   - **FULL_CLONE**：每輪最多一次 clone 或 repository refresh，多項檢查合併執行。
   - **EQUIVALENT**：每輪使用一次有界的 GitHub 機器證據更新（bounded GitHub evidence refresh）與等效遠端驗證。

### 8.4 不得為了省額度而做的兩件事

1. **不得跳過獨立版本庫驗證（Independent Repository Verification）**：無論採 FULL_CLONE 或 EQUIVALENT 模式，均不得跳過獨立客觀驗證，嚴禁將執行者回報（Executor report）當作 Macro truth。
2. **不得為了省額度而合併批次**。

---

## 9. 交接協定

### 9.1 正常交接

**產出時機**：當 §8.2 門檻觸發時，回覆結尾同時產出交接提示詞。驗證階段例外時舊 Agent 全程留任（見 §9.5）。

**產出前確認四項就緒**：
1. 交接區（`docs/refactor-backlog.md` §5）已更新，§5.1 第一行為「上次核對通過的 HEAD：xxxxxxx」
2. 所有變更已 push 到 GitHub
3. 待裁決事項已列在 §5.3，附選項與建議
4. 確認執行者本機與遠端同步（`git pull origin main` 並確認 HEAD 一致）

**交接提示詞格式**：
```text
接手 HH.AI_v2 重構專案。請先執行 Instructions 的開場動作，再往下讀。

交接時的 repo 狀態
- 最後一次核對通過的 HEAD：（填 hash）
- 該批次做了什麼：（一句話）
- 核對結果：（通過／有 N 項待修）

下一步
（下一批要做什麼，提示詞或依據交接區哪一項）

待裁決（不要重複提問）
（列出交接區 §5.3 的項目與狀態）

注意事項
（暫時性狀況與同步狀態）

接手後第一件事
依當前 A1 模式取得實際 HEAD（FULL_CLONE 使用 local git 如 git rev-parse / git log；EQUIVALENT 獨立自 GitHub API commit/branch endpoint 取得），並與上面的 checkpoint 比對：
- 相同 → 沒有未核對的批次，從 docs/TASKBOARD.md 的 **NEXT_WORK** pointer 取得下一步工作（§5.2 僅為指標）
- 不同 → 存在 pending macro-audit range（由 checkpoint..HEAD machine derive），先完成該 range 宏觀審核再往下
```

提示詞不取代交接區，矛盾時以交接區與實際 repo 為準。

### 9.2 無交接接手

舊 Agent 中斷或對話遺失時，新 Agent 按以下順序判定：
1. 讀 §5.4「進行中／等待回報」——掌握進行中狀態。
2. 讀 §5.1 第一行「上次核對通過的 HEAD」。
3. **依當前 A1 模式取得實際 HEAD 並與第 2 步 checkpoint 比對**：
   - FULL_CLONE：使用 local `git rev-parse HEAD` 或 `git log -1 --format=%h`。
   - EQUIVALENT：獨立自 GitHub current branch / commit endpoint 取得 actual full HEAD。
   - 兩者依比對結果判定：
     - **相同** → 無 pending macro-audit，從 `docs/TASKBOARD.md` 的 `**NEXT_WORK**` pointer 取得下一步工作（§5.2 僅為指標）。
     - **不同** → 存在 pending macro-audit range（由 `checkpoint..HEAD` machine derive），先完成該 range 宏觀審核再往下。
4. 讀 §5.3「待裁決」——不重複提問已裁決事項。
5. 交接區若與實際 repo 矛盾，**一律以 repo 為準**並明說矛盾處。

### 9.3 交接區的維護責任

每批提示詞都必須包含「更新交接區」指令。
§5.1 第一行格式固定為：`上次核對通過的 HEAD：xxxxxxx`。
§5.1 中每一個描述批次狀態的項目符號，都必須帶該批次的 commit hash，用反引號包住（尚未 commit 者寫「本批（尚未 commit）」並於下一批補上），以供 CHECK 15 驗證。

### 9.4 交接是否成功的判準

新 Agent 接手後的**第一則回覆**必須包含以下五項，缺一即代表交接失敗：
1. **確認審計官身分與資格**：確認自身為使用者授權且符合 `docs/TASKBOARD.md` 之 `**ACTIVE_MACRO_AUDITOR**` 唯一定義者，且確認本 session 非執行者 session（同 session 互斥）。
2. **A1 資格查證**：
   - 模式一 (FULL_CLONE)：實際執行過完整 clone 與開場動作（確定性指令如 `git rev-parse --is-shallow-repository` 輸出為 `false`，提供 `FULL_CLONE OK` 機器宣告，不得要求 raw output）。
   - 模式二 (EQUIVALENT)：自身獨立取得 GitHub API 證據（8 項關鍵證據：target full OID, parent OID, compare/range, commit list, changed files, exact-SHA file contents, exact-SHA Actions Verify），並由執行者 local full clone (non-shallow, HEAD==origin/main) 提供逐項欄位相符之交叉驗證，提供 `A1 = EQUIVALENT (GitHub API + Executor clone cross-check)` 宣告。
3. **明確說出目前的 HEAD**，以及它與交接區 §5.1 記載是否一致。
4. **明確說出下一步要做什麼**，以 `docs/TASKBOARD.md` 的 `**NEXT_WORK**` pointer 所指任務為準。
5. **說明待裁決事項狀態**，不重新分析已裁決事項。

| 缺項 | 可能原因 | 處置 |
|---|---|---|
| 無法完成第 1 項 | 未獲授權、非當前 active macro、同一 session 身分衝突 | 立即停止並回報使用者 |
| 無法完成第 2 項 | clone 失敗、shallow clone、GitHub 機器證據不可得、交叉核對不符 | 依開場動作載入失敗處理，第一句明說 |
| 第 3 項 HEAD 不一致 | 存在 pending macro-audit range | 依 §9.2 第 3 點，先完成該 range 宏觀審核再往下 |
| 第 4 項無法判斷 | 交接區 §5.2 空或過期 | 讀 `docs/TASKBOARD.md` 的 `**NEXT_WORK**` pointer 確認下一步並回報 |
| 第 5 項重複提問 | 未讀 §5.3 | 補讀後更正 |

正常交接由使用者逐項比對判定；驗證階段由留任舊 Agent 擔任判定者（但舊 Agent 不得擔任受測者，見 `docs/adr/0007-macro-auditor-role.md`）。

### 9.5 交接機制的驗證階段

| 事件 | 對話類型 | 目的 | 判定者 |
|---|---|---|---|
| **E1 注入測試** | 拋棄式，測完即關 | 測「走偏了會不會被攔下」 | 留任的舊 Agent |
| **E2 正式交接** | 生產對話 | 新 Agent 依 §9.1 提示詞接手真實任務 | 留任的舊 Agent，依 §9.4 四項 |
| **E3 補洞** | 視結果而定 | 僅在 E1／E2 失敗時需要 | — |

E1 必須排在 E2 之前且用拋棄式對話。
自檢清單（`auditor-selftest.md`）進 repo；注入測試題目與答案卷由使用者與審計官保管，不進 repo。
**E1 → E2 Repo-Visible State Bridge**：E1 通過後、啟動後續驗證階段前，透過正常執行者狀態同步 commit 使 repo 產生可見狀態流轉（如前置驗證項目標記已完成，後續驗證項目標記 Ready／進行中）。原則：只保存 PASS 狀態流轉，絕對不保存測試秘密。

**驗證階段去錨定（De-Anchoring of Completed Stages）**：
上述驗證階段（E1/E2/E3）為一次性前置驗證機制，非每個新 Fresh Session 的例行 startup task。任一 validation stage 一旦由 canonical `docs/TASKBOARD.md` / audit evidence 正式記錄為 completed / PASS，後續 Fresh Session 不因該 stage definition 仍存在於 protocol 而自動重跑；其結果由版本庫歷史證據永久保留。後續常態 Fresh Session 直接依通用路由器（HEAD == checkpoint → `docs/TASKBOARD.md` 的 `**NEXT_WORK**` pointer）導向常態生產任務，絕不自動重複執行已完成之交接驗證階段。

---

## 10. 任務板維護

| 檔案 | 性質 | 變更方式 |
|---|---|---|
| `docs/TASKBOARD.md` | **活動看板**，反映「現在有哪些事、各自什麼狀態」 | 反覆改寫，狀態會流轉 |
| `docs/refactor-backlog.md` | **留痕層與交接介面**：歷史編號紀錄為 append-only；交接區（§5.1、§5.3、§5.4）為 mutable interface 依現行事實更新 | 歷史區 append-only；§5 交接區 mutable 更新 |
| `docs/ARCHIVE-INDEX.md` | **歸檔索引**，回答「某某東西被歸檔到哪裡了」 | 新增或變更歸檔機制時同步更新 |

職責分工：交接區（§5.1、§5.3、§5.4）回答「現在在哪？」，任務看板（`docs/TASKBOARD.md`）回答「還有什麼？」。交接區不得保留待辦清單副本。

### 10.1 新項目必須當輪登錄（Material Finding 處置契約）

使用者提出新需求或審計發現新缺口（Material Finding）時，必須遵守當輪處置與登錄契約，不得延宕至未來對話。

**1. Material Finding 定義**：
任何會實質影響 correctness、security、architecture、routing、state truth、audit truth、CI / verifier truth、runtime loadability、repository/runtime truth consistency、或下一個 production task 是否可靠可執行的問題。
純文句美化、formatting preference、不影響 correctness 的歷史措辭、或已被既有 task 明確涵蓋的 incidental observation，不得無限建立新 task。

**2. 唯一剩餘工作權威（No Second Queue）**：
`docs/TASKBOARD.md` 為專案唯一 remaining-work authority。嚴禁建立第二 queue、`OPEN-FINDINGS.md`、第二 backlog 或依賴 GitHub Issues 作為剩餘工作權威。

**3. 四種 Finding Disposition 狀態**：
宏觀審計官每一輪 Macro Review 必須明確產生以下其中之一，不得只寫自然語言「之後記得處理」：
- `FINDING_DISPOSITION: NONE`：本輪未發現 material finding。
- `FINDING_DISPOSITION: CURRENT <task-id>`：表示 finding 已屬目前 `**NEXT_WORK**` / current task。
- `FINDING_DISPOSITION: EXISTING <task-id>`：表示已有 TASKBOARD task 完整涵蓋。
- `FINDING_DISPOSITION: NEW <task-id>`：表示沒有任何既有 task 涵蓋，必須同輪登錄 TASKBOARD。
若 finding 已由 CURRENT 或 EXISTING task 涵蓋，不得重複建 task。

**4. 當輪登錄與最小 State-Sync 提示詞（Same-Round Persistence）**：
若審計輪發現 NEW material finding：
- 優先映射既有 TASKBOARD task；
- 若無既有 task 涵蓋，即使該輪原本沒有 implementation prompt，也必須在該輪輸出**最小 state-sync prompt**，讓執行者將 finding repo-visible 寫入 `docs/TASKBOARD.md`。
- repo-visible 登錄後才能視為 persisted，嚴禁依賴跨輪記憶、下一個審計官 session、使用者提醒或「下次 prompt 再補」。未在當輪 repo-visible 登錄前，不得宣告 Production Ready 或 Finding handled。

**5. 阻擋性分流（Blocking Routing）**：
- **BLOCKING**：若 material finding 會使目前工作或 `**NEXT_WORK**` 無法可靠、安全、正確執行，該 task 必須取得 `**NEXT_WORK**`。
- **NON-BLOCKING**：若 material finding 已明確登錄，但不阻礙目前／下一個 production task，登錄至看板，`**NEXT_WORK**` 不因此自動改變。
- 只有 Macro Auditor / Planner 可以指定 `**NEXT_WORK**`，執行者不得自行決定 priority。

### 10.2 被問「還有哪些待辦」時，給完整看板

回覆必須包含所有狀態的項目（含已完成與封存建議），以供使用者判斷整體影響。

### 10.3 五種狀態

| 狀態 | 意義 | 誰能改成這個狀態 |
|---|---|---|
| `待辦` | 可直接執行，不需裁決 | 審計官 |
| `進行中` | 提示詞已發出，等待回報 | 審計官 |
| `待裁決` | 需要使用者決定，附選項與建議 | 審計官 |
| `已完成` | 做完，但仍可能被後續工作引用 | 審計官核對通過後 |
| `可封存` | 做完且不影響後續工作，建議移入封存區 | 審計官提議，**使用者確認後**才移動 |

### 10.4 封存不是刪除

標記 `可封存` 的項目，經使用者確認後移到 `TASKBOARD.md` 末尾的「封存區」，保留全文可查。

### 10.5 每批次結束時更新

每一批審計官核對通過後，下一批提示詞必須包含更新 `TASKBOARD.md` 的指令（見 §6.1 第 8 項），包含：
1. 受影響項目的狀態流轉
2. 新發現的缺口登錄（§10.1）
3. 可封存項目的建議（§10.4）
4. **「最後更新」那一行的日期與當前工作狀態描述**（不記錄 Git HEAD 或 checkpoint hash）

### 10.6 「最後更新」是可驗證的攔截點

`TASKBOARD.md` 的「**最後更新**：日期，當前階段／工作描述」為活動看板狀態標記。
TASKBOARD 不擁有 Git HEAD / checkpoint / pending range 之事實（由 Git HEAD、`AUDIT-LOG` 與交接區 §5.1 擁有）。CHECK 8 驗證其 metadata 純度（不得含 Git commit hash）。
每批驗證步驟固定確認「最後更新」包含日期與當前工作描述且不含 Git commit hash。

### 10.7 NEXT_WORK 指標權威與生命週期

1. **規劃權威（Planning Authority）**：`docs/TASKBOARD.md` 的 `**NEXT_WORK**` 任務指標由宏觀審計官／規劃者全權管理與指定。執行者（Antigravity）不得自行選取下一個任務。
2. **機械同步契約**：執行者僅在提示詞明確指定狀態流轉或 pointer 目標時，方可於 repo 同步修改 `**NEXT_WORK**`。
3. **Pending-Audit 凍結**：當某任務實作完成但處於 pending Macro Audit 階段時，`**NEXT_WORK**` 必須維持指向同一任務，不得提前跳轉至下一個任務。
4. **NEEDS FIX 保持**：當宏觀審計判定為 NEEDS FIX 時，`**NEXT_WORK**` 維持指向原任務以待修復。
5. **PASS 後推進**：只有當 Macro Audit 判定為 PASS 且狀態流轉正式成立時，才由宏觀審計官在下一份生產提示詞中明確指定推進至下一個 `**NEXT_WORK**` 值。
6. **合法目標與狀態語意**：
   - `**NEXT_WORK**` 可指向：`待辦`（可進行提示詞規劃與實作）、`進行中`（不得重複發實作提示詞，先查 repo 證據確認是否 pending Macro Audit）、`待裁決`（先找使用者裁決）。
   - `**NEXT_WORK**` 嚴禁指向：`已完成`、`可封存`。
   - 若全庫無任何 active work，`**NEXT_WORK**` 方可標記為 `NONE`。

---

## 11. 錯誤處置與回滾

本專案禁止 `git push --force` 與 `--amend`（見 `.agents/rules/git-and-reporting.md`）。回捲唯一合法方式為 `git revert`——追加反向 commit，不改寫歷史。

### 11.1 判斷順序

1. **只是遺漏或小錯** → 下一批補一個修正批次（預設處置）。
2. **改壞既有內容但範圍清楚** → 下一批針對性修正，並在 backlog 記錄修復歷程。
3. **整批方向錯誤或修比重做貴** → `git revert <commit>`。

不確定時選 1 或 2。

### 11.2 執行 revert 的完整程序

依 K1-A Transport-Neutral Exact-SHA 傳輸規範，revert 必須經由 batch 分支驗證後 pure fast-forward 至 main，嚴禁直推 main：

1. 以 exact origin/main 基準建立 `batch/**` repair branch。
2. 執行 `git revert <commit-hash> --no-edit` 建立 revert commit。
3. `git push origin <batch-branch>` 推送至批次分支。
4. 等候 exact revert SHA 於 GitHub Actions 之 required checks（`verify` 與 `gateway-windows`）全數 completed / success，且 inner verifier 為 `ALL 5 GATES PASSED`。
5. 確認 `origin/main` 未 drift 且當前 base 為 revert SHA 之 ancestor（可 pure fast-forward）。
6. 經由批次選定之可用 transport adapter（例如 approved connector `update_ref` 或 native pinned full-SHA refspec）將 main fast-forward 至 exact checked revert SHA。在 T1 完成前，emergency rollback 僅限使用者本人 break-glass。
7. 查驗 same SHA 之 post-main push GitHub Actions Verify 成功。

仍嚴格禁止未經 checks 驗證之 `git push origin main`、`git push --force`、`--amend` 或任何歷史改寫。

revert 後必須同批完成三件事：
1. 交接區 §5.1 更新為 revert 後的 commit
2. `docs/TASKBOARD.md` 受影響項目狀態回捲，「最後更新」同步
3. `docs/refactor-backlog.md` 追加一則 revert 留痕紀錄

不得 revert 一個已被後續批次依賴的 commit。

### 11.3 已審核標記之退役（Retired Historical Audit Markers）

早期規劃之 `audited-*` tag 已全面退役為唯讀歷史留痕標記，審計狀態由 `docs/AUDIT-LOG.md`（每 commit 審查結論）＋ `docs/refactor-backlog.md` §5.1（最新交接 checkpoint）＋ GitHub Actions（遠端健康權威）完整接管，未來正常批次不再建立或推送任何 audited tag。

### 11.4 [已退役／歷史記錄] 早期打 tag 判準（Historical Rationale）

本節為歷史規則留痕。因 tag 次系統已退役，歷史判準細節見歸檔快照 `docs/archive/claude-control-plane/auditor-protocol-pre-slim-76b5e9.md`。既有 21 個 tag 由 CHECK 18 進行唯讀守護，不作擴張。

### 11.5 審計狀態之單一事實來源（Audit State SSOT）

審計狀態以 **`docs/AUDIT-LOG.md`** 為 per-commit 審查結論唯一權威，以 **`docs/refactor-backlog.md` §5.1** 為當前最新 checkpoint 唯一權威：

| 狀態 | repo 可觀察的判準 |
|---|---|
| **A. UNREVIEWED** | `docs/AUDIT-LOG.md` 無該 commit 結論 |
| **B. AUDIT_FAIL** | `docs/AUDIT-LOG.md` 有列且結論為不通過 |
| **C. AUDIT_PASS_PENDING_HANDOFF** | `docs/AUDIT-LOG.md` 有列且結論為通過，但交接區 §5.1 尚未同步至該 commit |
| **D. AUDIT_PASS_FINAL** | `docs/AUDIT-LOG.md` 結論為通過，且交接區 §5.1 已同步為該 checkpoint |

歷史審查結論由 `docs/AUDIT-LOG.md` 保存；§5.1 僅標示最新通過審查之單一 checkpoint；不依賴 `audited-*` tag。

### 11.6 [已退役／不需執行] 歷史 `audited-*` tag 之留痕保存（RETIRED / NOT REQUIRED）

9 個歷史名實不符的 tag 刻意保留為歷史事故證據，不執行破壞性遠端清理（0 remote tag deleted, 0 remote tag rewritten），既有 tag 不影響正確性、審計狀態、交接或遠端健康。詳細歷史處置紀錄見歸檔快照 `docs/archive/claude-control-plane/auditor-protocol-pre-slim-76b5e9.md`。

---

## 12. 風險分級宏觀審計與 Tier-M 微修復規範 (Risk-Tiered Macro Audit & Tier-M, D-U6)

### 12.1 風險分級宏觀審計核心原則 (D-U6)

1. **形式規則（Formal Rule）**：風險分級（Risk Tier）改變的是**驗證深度（verification depth）**，而非**角色獨立性（role independence）**。
2. **六大不可免除之安全底線**：任何風險分級皆不得免除：
   - 獨立宏觀審計（Independent Macro Audit）
   - exact-SHA 遠端機器證據（Exact-SHA remote evidence）
   - E24 依賴閉包（E24 dependency closure）
   - 變更範圍控制（Scope control / Allowed Scope）
   - 機密防護安全（Secret safety / zero secret leakage）
   - 破壞性操作防護（Destructive-operation safeguards）。
3. **SOP_14 對齊**：`SOP/SOP_14_Rigorous_Verification_and_Audit_Protocol.md` 維持 VERIFY_ONLY；其既有風險導向執行模型已與本原則部分對齊，維持全庫單一驗證權威。

### 12.2 Tier-M 微修復分類規範 (Tier-M Micro Repair)

1. **性質定義**：Tier-M 是**風險／修復分類（risk / repair classification）**，**絕非**新的 `batch_mode`。
2. **批次模式不變量**：Tier-M 批次依然宣告 `batch_mode: GOAL_SPEC`，不建立新的 validator 或 parser 批次模式，不擴充 manifest parser 之模式枚舉。
3. **九大適用門檻（全部成立始得適用）**：
   1. 具體 material finding 已經確立（exact material finding already established）。
   2. 無新架構選擇（no new architecture choice）。
   3. 無 schema migration。
   4. 無 public-interface 變更。
   5. 無跨系統／外部安全架構變更（no cross-system/external security architecture change）。
   6. 修復完全落在緊鄰前一批已審計之依賴宇宙內（repair remains inside the immediately preceding audited dependency universe）。
   7. 依賴證據必須針對當前基準（dependency evidence is for the CURRENT base）。
   8. 存在確定性反例或回歸測試（deterministic counterexample or regression test exists）。
   9. 無範圍擴張（no scope expansion）。
4. **當前基準證據與禁止手動改寫**：若既有證據之 `base_oid` 不等於當前 base，Tier-M **不具備**證據重用資格（NOT eligible for evidence replay）；必須重新產出全新 discovery artifact 並取得 Macro disposition，方得界定生產範圍。Tier-M 嚴禁手動改寫 `base_oid`。
