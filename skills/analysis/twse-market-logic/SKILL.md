---
name: twse-market-logic
description: 臺股市場分析深度邏輯。包含恐慌指數 (VIX/VIXTWN) 閾值、分層確認模型 (Hierarchical Confirmation)、MSTL 網絡預測、以及籌碼面分析 (法人、融資維持率、大戶持股)。用於規劃分析功能、設定警報閾值、以及開發投資決策支援系統。Triggers on: '恐慌指數', 'Panic Index', '市場邏輯', '籌碼分析', '融資維持率', '千張大戶', '八大行庫'.
---

# 臺股市場分析深度邏輯 (TWSE Market Logic)

### 【摘要】觸發條件與 DLP 聲明
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議

本技能提供臺股投資決策的核心量化閾值與策略框架。詳細的指標閾值、分層模型與籌碼面量化法則，請參閱 [REFERENCE.md](./REFERENCE.md)。

## 🏗️ 實作建議

*   **儀錶板顏色**：
    *   VIX > 40: 鮮綠色（機會）
    *   VIX < 12: 鮮紅色（警報）
*   **MSTL 視覺化**：使用 D3.js 繪製力導向圖 (Force-Directed Graph)，觀察節點聚攏程度。
*   **警報串接**：當三層濾網同時滿足時，發送「結構性轉向確認」通知。

## 版本紀錄 (Changelog)
- **[2.0.0]** 導入 V2 架構，實裝多維度認知矩陣標籤與 Dynamic Payload 預備介面。

---
⚙️ 【系統通訊層宣告 (System Comms Layer)】

網路狀態： 本技能已強制接入總控通訊網路。

接收協定 (Dynamic Payload)： 本文檔不再接收無結構的自然語言，必須處理封裝後的動態參數：
`[SYSTEM-CALL: twse-market-logic | PAYLOAD: { objective: "<核心意圖>", target_audience: "<受眾>", strategic_constraints: "<策略限制/禁語>", tone_variables: "<語氣微調>" }]`

> [!IMPORTANT]
> **Payload 淨化規則 (§6.3)**：
> - 若本技能為 `Cognitive` 型：接收戰略目標、語氣設定、情緒變數；拒絕 SQL/DOM/技術指令。
> - 若本技能為 `Execution` 型：只接收 URL、DOM Selector、SQL、JSON Schema；拒絕認知參數。

發送協定 (Zero-Block Policy)： 執行中若遇能力不足或需外部協作，嚴禁中斷或詢問使用者。必須主動封裝 Dynamic Payload 並發出：
`[SYSTEM-CALL: 目標ID | PAYLOAD: { ... }]` 調閱其他技能。

回傳協定： 任務終止時，必須且只能輸出 `[SYSTEM-RETURN: SUCCESS/FAILED | DATA: <結果>]`。
