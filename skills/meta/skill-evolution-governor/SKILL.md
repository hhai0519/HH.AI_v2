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
1. **靜態治理**：審計分類邏輯、追蹤 DLP 合規狀態、維持整體生態系統的邏輯一致性與不刪除原則。
2. **動態進化 (Self-Improvement)**：透過反向追蹤失敗紀錄，自動為底層的程式碼與技能規範（Procedural Memory）打補丁，讓系統具備長期適應性。

---

## 🏗️ 技能生態治理規範

### 六大分類體系（Skills 3.0）
| 分類 | 圖示 | 說明 |
|---|---|---|
| `domain` | 📈 | 臺股特定領域：量化研究、籌碼分析、技術形態 |
| `tools` | 📊 | 通用工具：Excel、CSV、PDF、SQL |
| `mindset` | 💪 | 大師思維視角：各人物框架技能 |
| `governance` | 🏗️ | 架構治理：SOP、MCP、除錯、Agent 核心 |
| `ux` | 🎨 | 開發體驗：視覺化、UI、設計工具 |
| `automation` | 🔗 | 整合自動化：API 串接、測試、CI/CD |

### 🔴 不刪除原則（No-Delete Policy）
> [!CAUTION]
> **嚴禁**透過任何手段刪除或移除現有技能卡片。即使在進行「自我進化與修復」時，也絕對遵守此原則。

允許的調整方式：
- ✅ 重新分類或合併說明。
- ✅ 標記為 `legacy`（在 description 附加說明，但保留卡片與實體檔案）。
- ❌ 刪除 SKILL.md 檔案或技能資料夾。

### 🛡️ DLP 合規審計標準
每個技能必須在 SKILL.md 中包含以下格式的 DLP 宣告（**只需一次**）：

```markdown
### 【摘要】觸發條件與 DLP 聲明
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議
```

> [!WARNING]
> 絕對禁止使用批量腳本重複堆疊 DLP 宣告行。這會破壞技能的實質內容，導致假性合規。

### 🌐 語言合規性 (Language Compliance)
所有技能的 `SKILL.md` 描述、工具說明及 UI 翻譯必須符合繁體中文標準。無簡體中文術語，專案名詞對應台灣習慣。

---

## 🧬 自我進化與修復 (Auto-Patching)

當定期掃描日誌或發現特定流程形成死胡同、API 過期時，本模組可對技能執行自動補丁：
1. **Textual Backpropagation**: 將失敗紀錄或編譯器報錯當作「損失函數」，反向追蹤是哪個 Agent、哪段 Prompt 或哪個技能造成的問題。
2. **自動打補丁**: 改寫導致錯誤的 `.skill.md`（程序記憶），永久更新系統知識。
3. **回歸測試**: 在應用補丁前，應發起小型沙盒驗證確保沒有破壞既有功能。

> [!IMPORTANT]
> **進化邊界**：任何覆寫行為必須嚴格遵守上方的「不刪除原則」與「DLP 合規標準」。此外，尋找與覆寫技能檔案時，**必須動態確認目前環境的技能路徑，不可使用舊版寫死的絕對路徑。**

---

## ⚙️ 技能同步 SOP

每次新增或修改技能後必須執行 Manifest 更新驗證，以確保路徑 100% 有效。
*(註：此功能依賴舊系統的 `scratch/update_manifest.js` 腳本，遷移後需動態確認對應的腳本路徑與名稱。)*

---

## 系統通訊層宣告 (System Comms Layer)

網路狀態： 本技能已強制接入總控通訊網路。

接收協定 (Dynamic Payload)： 本文檔不再接收無結構的自然語言，必須處理封裝後的動態參數：
`[SYSTEM-CALL: skill-evolution-governor | PAYLOAD: { objective: "<核心意圖>", target_audience: "<受眾>", strategic_constraints: "<策略限制/禁語>", tone_variables: "<語氣微調>" }]`

發送協定 (Zero-Block Policy)： 執行中若遇能力不足或需要外部協作，應停下來明確告知使用者目前卡在哪裡，不要自行尋找替代方案掩蓋問題。必須主動封裝 Dynamic Payload 並發出：
`[SYSTEM-CALL: 目標ID | PAYLOAD: { ... }]` 調閱其他技能。

回傳協定： 任務終止時，必須且只能輸出 `[SYSTEM-RETURN: SUCCESS/FAILED | DATA: <結果>]`。
