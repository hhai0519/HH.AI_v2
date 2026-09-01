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

以下任一情況發生時，**強制觸發**本 SOP 聯席審計程序，不得省略：
- 修改超過 **2 個以上** SOP 或 SKILL 文件的任務
- 任何涉及 `start_line.js`、`bridge.js`、`poll_inbox.js`、`skills/platform/telegram-bot-cdp-bridge` 或 `Start-TelegramBot.ps1` 的修改（註：telegram-bot-cdp-bridge 尚未遷移至 HH.AI_v2，路徑為預計位置）
- 新增或刪除技能目錄
- 在生產環境執行首次部署或架構重組
- 使用者明確輸入「請進行審計」或「SOP14」關鍵字（註：此處觸發的是本 SOP 的**聯席審計／任務內驗證**程序，不是宏觀審計。兩者的區分見 `PRINCIPLES.md` §0.3）

---

## 1. 聯席審計規範 (Joint Audit Standard)

當觸發本程序時，Orchestrator 必須模擬並召集以下四個角色的聯席會議，產出獨立的審查意見：

### 1.1 資安稽核官 (Security Auditor)
- 檢查金鑰暴露（如 `.env.local` 密碼洩漏）。
- 檢驗極端情境的 Fallback 機制（如變數未定義時的預設值安全）。
- 檢查是否符合 WMI 精準狙擊原則（SOP_02）。

### 1.2 代碼與架構審查官 (Code Reviewer & Architect)
- 靜態掃描是否有語法衝突（如重複宣告 `const path`）。
- 掃描參數傳遞的精準性與變數作用域。
- 確認無窮迴圈等 Anti-Pattern。

### 1.3 顧問團 (Advisory Board)
- **Node.js 顧問**：評估非同步與事件驅動效能。
- **DevOps 顧問**：評估環境變數與容器化對接。
- **SRE 顧問**：評估進程生命週期與重試退避機制（Backoff）。

### 1.4 總架構師 (Chief Architect)
- 執行最後的「全域副作用與相容性評估」，給予最終核發。

---

## 2. 前置沙盒模擬測試 (Pre-flight Sandbox Simulation)

- **強約束**：禁止直接在工作區實際代碼上進行測試。
- **執行方式**：建立獨立的模擬測試腳本（如 `sandbox_test.js`），在隔離的控制台環境運行參數解析與邏輯邊界測試，並將結果輸出為 `SIMULATION_TEST_REPORT.md`。

---

## 3. 使用者確認防線 (User Consent Barrier)

- **強約束**：在使用者未輸入「同意執行」或「Proceed」前，代理人必須凍結工作區修改權限。
- 必須完整呈現：
  1. 聯席審計意見彙整。
  2. 模擬測試結果。
  3. 分段執行計畫。

---

## 4. 分段執行與階段簽章審計 (Phased Execution & Intermediate Audit)

1. **清單化管理**：建立 `task.md` 並拆分為 `Phase A, B, C...`。
2. **階段解凍**：每完成一個 Phase 的變更，必須執行該 Phase 的單元測試。
3. **階段審計**：由相關 Agent 進行階段查核。只有在上一階段 100% 審計通過且在 `task.md` 標記為 `[x]` 後，下一個 Phase 才能解凍執行。
4. **強制併發與壓測要求**：若修改涉及底層資料持久化 (DB/檔案寫入) 或主要 Web API (如 Express API 路由)，在 Phase 3 (驗證) 期間，必須強制執行最少 50 次併發或高負載壓力測試，驗證鎖定與流水號遞增之安全性，錯誤率必須為 0。
5. **失敗退回**：若任一階段審計失敗，必須立即退回 Stage 1，啟動反思程序（SOP_11）。

---

## 5. Walkthrough 與結案報告 (Closing & Traceability)

- 任務成功後，產出純 UTF-8 (無 BOM) 的 `walkthrough.md`。
- 必須詳列修改的檔案路徑與行號連結，並附上最終功能驗證成功的終端機日誌。


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
  但**「宏觀審計官」是獨立於執行者的角色，只有 Claude 擔任**——
  定義見 `PRINCIPLES.md` §0，理由見 `docs/adr/0007-macro-auditor-role.md`。
  Antigravity IDE Agent 不得自任該角色，也不得以本節為據宣稱自己
  完成了宏觀審計。**本節規範「發現錯誤之後怎麼判斷」，不授予任何人身分。**
