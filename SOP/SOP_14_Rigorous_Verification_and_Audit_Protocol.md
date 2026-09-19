---
title: "嚴謹驗證與審計標準程序"
version: "1.1.0"
tags: ["SOP", "Audit", "Verification", "Rigorous", "Planning"]
dependencies: [".agents/rules/skill-engineering-guardrails.md", "SOP_05_System_Policies.md", "SOP_11_Task_Reflection_Protocol.md"]
---

# 嚴謹驗證與審計標準程序 (Rigorous Verification & Audit Protocol)

**核心精神**：慎始敬終。以多層審查防範漏洞，以分段驗證確保穩定。

---

## 0. 觸發條件 (Trigger Conditions)

本 SOP 的聯席審計／任務內驗證程序採**風險導向（Risk-based）**，檔案數量本身不構成風險。普通多技能重構與文件遷移走正常 `GOAL_SPEC` 與 machine gates，**僅在以下真正高風險情境**才強制觸發加強查核程序：
- 涉及破壞性或不可逆操作（Destructive / Irreversible operations，如大量物理刪除或非受控清理）
- 涉及金鑰、憑證與最高安全層級變更（Credential / Security policies）
- 涉及執行期底層與進程生命週期調整（Runtime / Process lifecycle，如 PM2、`ecosystem.config.js`、`start_line.js`、通訊 bridge 與 daemon 進程）
- 涉及生產環境部署或不可逆之對外真實副作用（Production deployment / External side effects）
- 涉及核心調度與代理人路由語意重大變更（High-risk orchestration / agents routing semantics）
- 涉及架構邊界與安全防火牆變更（Architecture boundary change）
- 使用者明確指示要求進行加強審計或 SOP14 檢核（註：此處觸發的是**任務內驗證**，非跨批次宏觀審計）

---

## 1. 風險維度審計規範 (Risk Dimension Audit Standard)

當觸發本程序時，執行者依任務涉及的領域聚焦檢查對應之客觀風險維度（Risk Dimensions），**嚴禁進行無實質效益的四角色會議文字扮演（Role-play ceremony）**：

### 1.1 資安維度 (Security)
- 檢查金鑰暴露（如 `.env` 敏感字串外洩）。
- 檢驗極端情境的 Fallback 機制（如變數未定義時的預設值安全）。
- 確認符合 WMI 精準狙擊原則（SOP_02）。

### 1.2 架構與代碼維度 (Architecture & Code)
- 靜態掃描語法與命名空間衝突。
- 檢查變數作用域、依賴邊界與非同步呼叫。
- 消除無窮迴圈與死鎖等 Anti-Pattern。

### 1.3 維運與可靠性維度 (SRE & Operations)
- 評估進程生命週期管理、優雅終止與信號處理。
- 評估外部服務呼叫之指數退避與熔斷機制。

### 1.4 相容性維度 (Compatibility)
- 評估全域副作用，確保向下相容與規範一致性。

---

## 2. 前置沙盒模擬測試 (Pre-flight Sandbox Simulation)

- **適用邊界**：常態代碼重構、規則微調與單純技能遷移**不強制要求**產出 `sandbox_test.js` 或 `SIMULATION_TEST_REPORT.md`，直接透過 disposable worktree、單元測試套件與 `verify_all.py` 驗證。唯有在涉及 PM2/runtime 進程、非受控破壞性外部副作用或高風險進程生命週期調整時，才必須在拋棄式沙盒環境中進行前置隔離測試。

### 2.1 PM2 設定檔與常駐服務的沙盒先行驗證

涉及 PM2 設定檔或常駐服務啟動路徑的變更，一律遵循以下五步驟：

1. 先建立 `sandbox_*.config.js` 副本，不直接改動正式設定檔
2. 在沙盒設定上執行修改與啟動測試
3. 確認所有進程能正常啟動、無 `MODULE_NOT_FOUND` 或 `SyntaxError`
4. 通過後才覆寫正式的 `ecosystem.config.js`
5. 覆寫後執行壓力測試驗證穩定性（可用 `x-sop14-mock` 標頭阻斷外部 API，避免測試消耗真實配額）

決策背景與 2026-08-09 的實際事故，見 `docs/adr/0014-pm2-config-pitfalls-and-sandbox-validation.md`。

---

## 3. 使用者確認防線 (User Consent Barrier)

- **任務授權界線**：使用者已明確發出任務指令，或宏觀審計官已指派明確之 `GOAL_SPEC` / `EXACT_SPEC`，即構成該 Allowed Scope 內之執行授權。正常實作與驗證過程中，**不得再要求使用者做第二次「同意執行」或「Proceed」輸入**。唯有在涉及破壞性 Git 操作、金鑰敏感變更、範圍擴張 (Scope Expansion)、未決之架構重大分歧 (S1) 或不可逆外部動作時，才需要求使用者進行 fresh authorization。
- 必須完整呈現：
  1. 聯席審計意見彙整。
  2. 模擬測試結果。
  3. 分段執行計畫。

---

## 4. 分段執行與階段簽章審計 (Phased Execution & Intermediate Audit)

1. **結構化管理**：依據任務複雜度，由專案既有之 TASKBOARD、EXEC-LOG、Git commit 與 Batch/Goal 契約管理狀態，**不得強制每個任務額外建立重複的 `task.md`**；僅在複雜 implementation 專案本身確有需要時才建立。
2. **漸進式執行**：每次聚焦處理單一明確範疇，確保可追蹤性。
3. **階段審計**：任務完成後由審計官依客觀驗證入口查核。詳細 changed paths、machine gate results、M1-M3 歷程與 remote health 完整寫入 `docs/EXEC-LOG.md`、Git commit 與 GitHub Actions；對話視窗正常成功僅回報 `COMMIT <full-sha> | CI PASS | S1 NONE`。審計官直接自 GitHub 遠端讀取 diff、實體檔案與 Actions 綠燈證據，對話視窗不預設要求張貼任何詳細內容或 raw diff。
4. **風險導向壓力測試**：若修改涉及底層資料持久化 (DB/檔案寫入) 或主要 Web API，應依 acceptance criteria、實際併發語意與 SRE 風險設計對應之測試，不得以無條件固定 50 次之 magic number 取代工程風險判斷。
5. **失敗處置**：若驗證失敗，依循 M1/M2/M3 本地修復流程處理；重大原則分歧則依 S1 升級回報。

---

## 5. 結案紀錄與可追蹤性 (Closing & Traceability)

- **結案紀錄標準**：正常重構與開發任務以 Git commit、`docs/EXEC-LOG.md` 與 GitHub Actions 綠燈作為完整結案憑證。
- **Walkthrough 適用情境**：`walkthrough.md` **不得作為所有任務之必備工件**；僅在正式部署（Deployment）、安全事故歸檔（Incident）、使用者交付物（User Deliverable）或高複雜度手動切換（Manual cutover）確有留痕需要時才產出。


---

## 6. 發現錯誤時的判斷順序 (Root-Cause Handling Order)

§1 到 §5 規範的是「動手之前怎麼審」。本節規範的是「審計中發現錯誤之後，
判斷與處置的順序」。兩者互補，不可互相取代。

### 6.1 事件背景

2026-08-29，外部代理（Gemini）協助使用者學習 Jules 時產出一份
`skills/README.md` 索引草案。初次審視列出多項缺陷——31 個欄位填 `-`、
連結格式與 `AGENTS.md` §7 不符、且寫著已被修正的「每日額度僅 5 次」——
判斷傾向不採納。

使用者要求先查明「為什麼會出現這個錯誤」，逐項查證後結論完全相反：

- 那 31 個 `-`，是因為對應的 31 個技能 `description` 確實沒有觸發詞，
  違反 `AGENTS.md` §2。三欄表格意外成為一份違規清單，
  而 `validate_skills.py` 抓不到這類問題。
- 「5 次」不是外部代理捏造，是逐字抄自本專案的
  `skills/agents/README.md`——該檔案在兩個月前的額度修正中被漏改。
- 順著同一條線索全庫搜尋，又發現 `skills/orchestration/README.md`
  與根目錄 `README.md` 各有一處「06 層級」舊分層編號殘留，
  同樣是先前修正只改了 `SKILL.md` 而漏掉索引層。

該草案的結構其實完全正確（54/54 技能齊備、連結路徑無誤）。
若依初次判斷否決，不僅丟掉一份可用產出，三個真實缺陷也會繼續潛伏。

### 6.2 四步判斷順序（不得跳過）

1. **不預先否決**：先假設該產出可能有價值、缺陷可能有原因。
   完整評估後才下判斷，不因表面缺陷否決整份產出。
2. **先問為什麼**：追問這個錯誤是怎麼產生的。
   外部產出的錯誤，往往忠實反映本專案自身的狀態。
3. **親自驗證**：不以推測解釋錯誤成因。實際讀檔、實際搜尋、實際比對，
   取得證據後才下結論。
4. **從根本剷除**：修正錯誤的來源，不只修正顯現處。
   只修下游，下一個讀取者仍會複製到同一個錯誤。

### 6.3 與既有紀律的關係

- 第 3、4 點與 `.agents/rules/git-and-reporting.md` §3 查證紀律同源。
  差別在於那份規則規範「修改時要搜遍全庫」，本節規範「發現錯誤時的判斷順序」。
  前者防漏改，後者防誤判與治標。
- 本節的「根因處理順序」適用於任何發現錯誤的角色，包括執行者。
  但**「宏觀審計官」是獨立於執行者的角色，採資格認定與使用者授權制**——
  定義見 `PRINCIPLES.md` §0，理由見 `docs/adr/0007-macro-auditor-role.md` 與 `docs/adr/0021-qualification-based-macro-auditor-role.md`。
  Antigravity IDE Agent 不得自任該角色，也不得以本節為據宣稱自己
  完成了宏觀審計。**本節規範「發現錯誤之後怎麼判斷」，不授予任何人身分。**

---

## 7. 高風險技能遷移的三層核對 (Three-Layer Review)

§1 到 §5 規範一般任務的審計流程，本節規範「技能遷移」這個特定情境。

### 7.1 適用範圍

`orchestration/` 或 `agents/` bucket 底下的技能，尤其是總管／路由類、
會被其他技能依賴的核心技能，一律套用本節流程。

行數較短、無外部呼叫、無 legacy 特殊語法的單純技能，不需要套用，
維持一般批次流程即可。

### 7.2 三層核對

1. 詳細 changed paths、驗證結果與 remote health 狀態一律寫入 `docs/EXEC-LOG.md` 與 Git commit；對話回覆正常成功維持單行 `COMMIT <full-sha> | CI PASS | S1 NONE`。宏觀審計官直接自 GitHub 遠端取得 exact diff 與實體檔案證據（或採 A1 EQUIVALENT 交叉驗證），**嚴禁預設要求執行者在對話貼出修改後完整檔案內容或 raw diff**（僅在遠端不可得時例外提供最小必要片段）。
2. 審計官獨立查核是否有：
   - 牴觸本專案核心原則的規則（尤其「遇到不確定情況要不要問人」這類）
   - 尚未處理的硬編碼符號／觸發詞
   - 檔案內部自相矛盾或重複的區塊
   - 遷移後失效的絕對路徑、外部引用
3. 回報 push 完成後，直接自遠端 repo / GitHub Actions 核對實體檔案內容與狀態，不依賴執行者口頭宣稱。

### 7.3 與既有紀律的關係

第 3 點的執行者是宏觀審計官（見 `PRINCIPLES.md` §0），不是執行遷移的
Agent 自己。決策背景與 2026-08-13 的三輪來回事件，見
`docs/adr/0005-high-risk-skill-three-layer-review.md`。

---

## 8. GitHub Actions 事故生命週期 (GitHub Actions Incident Lifecycle)

本節規範 GitHub Actions CI Verify workflow 出現紅燈（failure）時的標準處理與處置閉環程序，確保遠端健康單一權威的嚴謹性。

### 8.1 標準生命週期流程 (Incident Lifecycle)

當 GitHub Actions Verify 出現 red 時，所有角色必須遵循以下固定狀態流轉：

```
RED（遠端異常）
  ↓
1. Read exact Actions failure（讀取 run ID、failed job、failed step 與原始 log）
  ↓
2. Classify & Root-cause（分類並找出根本原因，禁止展開無憑證猜測或文字辯論）
  ↓
3. Reproduce & Fix（於本地重現問題並編寫修復程式碼/規格）
  ↓
4. Local verify_all.py PASS（執行標準權威入口驗證全數通過，exit 0）
  ↓
5. Prospective PASS（透過 disposable prospective commit 或 --as-if-committed 預演通過）
  ↓
6. Push exact repair SHA to batch/**（推送修復 commit 至批次分支）
  ↓
7. Batch exact-SHA required checks PASS（確認 verify + gateway-windows 全數成功且 ALL 5 GATES PASSED）
  ↓
8. Confirm origin/main unchanged + ancestry（確認 main 未 drift 且可 fast-forward）
  ↓
9. Approved force=false update_ref main to SAME SHA（經 approved connector 更新 main，嚴禁直推 main 或 force push）
  ↓
10. Exact same-SHA main push Actions PASS（查證 post-main GitHub Actions Verify 且 head_sha 完全相符、completed/success）
  ↓
11. Archive incident knowledge（將事故成因、修復 commit 與預防措施歸檔至 docs/AUDIT-LOG.md）
  ↓
12. Eligible for historical-run cleanup（標記為可清理候選，待使用者授權後執行）
```

### 8.2 歷史清理紅線 (Cleanup Invariants)

1. **嚴禁刪除 current red run**：不得以刪除 Actions 執行紀錄來粉飾太平或製造綠色畫面。
2. **五大結案清理門檻 (Closure Criteria)**：
   只有同時滿足以下全部條件的歷史失敗 run，才能標記為 `safe_to_delete = YES`：
   - Root cause 已明確查明並有機器證據記錄
   - Fixing commit 已合併入 main
   - 繼任（Successor）的 Verify workflow 實測為綠燈（completed / success）
   - Preventive control（預防機制與守衛）已於程式碼或規範中落地生效
   - 完整事故知識已沉澱歸檔於 `docs/AUDIT-LOG.md`
3. **使用者授權防線**：
   符合清理條件之 run 清單必須先呈報使用者，取得明確授權後方可調用 API 執行清理。
