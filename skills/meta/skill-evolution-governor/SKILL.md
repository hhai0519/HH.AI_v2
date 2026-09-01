---
name: skill-evolution-governor
description: "負責技能生態系統的生命週期管理、DLP 合規審計與系統自我進化。包含自動覆寫技能規範的修復能力。此技能涉及實體檔案變更，必須由使用者明確要求時才可觸發執行。"
disable-model-invocation: true
---

# 技能治理與自我進化 (Skill Evolution Governor)

### 【摘要】觸發條件與 DLP 聲明
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議

## 職責概述
本技能是技能樹的**健康監控與進化中樞**，負責兩大核心工作：
1. **靜態治理**：審計分類邏輯、追蹤 DLP 合規狀態、維持整體生態系統的邏輯一致性與刪除歸檔紀律。
2. **動態進化 (Self-Improvement)**：透過反向追蹤失敗紀錄，自動為底層的程式碼與技能規範（Procedural Memory）打補丁，讓系統具備長期適應性。

---

## 🏗️ 技能生態治理規範

### 技能分類體系

本專案的技能分類為 `AGENTS.md` §1 定義的七個 bucket：
`orchestration` / `analysis` / `agents` / `execution` / `platform` / `meta` / `deprecated`。

歸屬判斷的依據是「這個技能實際做什麼」，不是它原本放在哪裡。
其中 `analysis`（純分析、無副作用）與 `agents`（會實際執行動作）必須嚴格分開，
因為後者需要 `authorized_mcp_tools` 白名單，這是安全邊界。
決策理由見 `docs/adr/0001-seven-bucket-taxonomy.md`。

治理技能樹時一律以 `AGENTS.md` §1 為準，不得使用其他分類法。

### 🔴 技能的刪除與歸檔（強制安全邊界）

> [!CAUTION]
> 刪除與歸檔一律遵守 `.agents/rules/skill-engineering-guardrails.md` §4
> 「統一歸檔與差異化刪除政策」。該政策區分兩種性質不同的情境，不可混淆：
>
> **情況 A — 下架整個技能**：嚴禁物理刪除技能目錄。必須移入 `skills/deprecated/`，
> 從原 bucket 的 README.md 移除，並加入 `skills/deprecated/README.md`。
>
> **情況 B — 清理技能內部的錯誤／失效內容**：幽靈引用、已廢棄政策殘留、
> 失效的舊架構路徑，不受歸檔限制，可直接物理刪除。

執行「自我進化與修復」時，本節為強制安全邊界，不得繞過。
此定位見 `docs/adr/0006-merge-orchestration-skills.md`。

### 🛡️ DLP 合規（強制安全邊界）

技能的資料防洩規範，以下列兩份文件為準：
- `SOP/SOP_02_Security_Guidelines.md` §1「智慧整合與資料防洩」
- `.agents/rules/skill-engineering-guardrails.md` §3「分層 Payload 淨化機制」

審計 DLP 合規時，檢查的是技能是否實際遵守上述兩份文件的行為規範。

> [!WARNING]
> 舊版規範曾要求每個技能在 SKILL.md 中加上一行
> 「✓ DLP 資料安全驗證已通過 …」的宣告，並以該行是否存在作為合規判準。
> **該做法已廢止**：那行文字不對應任何實際驗證行為，屬假性合規。
> 不得要求新技能加上該宣告，也不得以該宣告的有無判定合規。
> 既有技能中的殘留宣告另批清理，追蹤見 `docs/refactor-backlog.md`。

### 🌐 語言合規性 (Language Compliance)
所有技能的 `SKILL.md` 描述、工具說明及 UI 翻譯必須符合繁體中文標準。無簡體中文術語，專案名詞對應台灣習慣。

---

## 🧬 自我進化與修復 (Auto-Patching)

當定期掃描日誌或發現特定流程形成死胡同、API 過期時，本模組可對技能執行自動補丁：
1. **Textual Backpropagation**: 將失敗紀錄或編譯器報錯當作「損失函數」，反向追蹤是哪個 Agent、哪段 Prompt 或哪個技能造成的問題。
2. **自動打補丁**: 改寫導致錯誤的 `.skill.md`（程序記憶），永久更新系統知識。
3. **回歸測試**: 在應用補丁前，應發起小型沙盒驗證確保沒有破壞既有功能。

> [!IMPORTANT]
> **進化邊界**：任何覆寫行為必須嚴格遵守上方的「技能的刪除與歸檔」與「DLP 合規」兩節。此外，尋找與覆寫技能檔案時，**必須動態確認目前環境的技能路徑，不可使用舊版寫死的絕對路徑。**

---

## ⚙️ 技能異動後的驗證

每次新增或修改技能後，必須執行以下三項，全部通過才算完成：

1. `python3 scripts/validate_skills.py` — 單一技能的 frontmatter 與格式
2. `python3 scripts/check_consistency.py` — 七項跨檔案一致性
3. 確認三層 README 已同步（`AGENTS.md` §7）：所屬 bucket 的 `README.md`、
   `skills/README.md`、根目錄 `README.md`

舊版的 Manifest 更新流程已廢止：其依賴的 `Data/00_Skill_Manifest.json`
已確認為無人讀取的死檔案，見 `SOP/SOP_00A_Master_Index.json` 的維護註記。

---

## 系統通訊層宣告 (System Comms Layer)

網路狀態： 本技能已強制接入總控通訊網路。

接收協定 (Dynamic Payload)： 本文檔不再接收無結構的自然語言，必須處理封裝後的動態參數：
`[SYSTEM-CALL: skill-evolution-governor | PAYLOAD: { objective: "<核心意圖>", target_audience: "<受眾>", strategic_constraints: "<策略限制/禁語>", tone_variables: "<語氣微調>" }]`

發送協定： 執行中若遇能力不足或需要外部協作，應停下來明確告知使用者目前卡在哪裡，不要自行尋找替代方案掩蓋問題。必須主動封裝 Dynamic Payload 並發出：
`[SYSTEM-CALL: 目標ID | PAYLOAD: { ... }]` 調閱其他技能。

回傳協定： 任務終止時，必須且只能輸出 `[SYSTEM-RETURN: SUCCESS/FAILED | DATA: <結果>]`。
