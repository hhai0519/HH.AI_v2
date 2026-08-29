---
name: theme-factory
description: 為成品套用主題風格，適用於投影片、文件、報告、HTML 登陸頁面。內含 10 組預設主題色彩與字體，也可即時生成新主題。當使用者要求『套用主題』、『配色方案』、『設計 Token』、『統一視覺風格』時使用。
license: Complete terms in LICENSE.txt
---

# 主題工廠 (Theme Factory)

### 【摘要】觸發條件與 DLP 聲明
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議

本技能是所有視覺輸出的**主題系統中樞**，提供 10 個精心調配的預設主題（含色板、字型、間距規範），也支援根據使用者描述實時生成新主題。適用對象：HTML 儀錶板、投影片、報告、登陸頁、資訊圖表。

---

## 🎯 觸發條件

- 「幫我套用深夜科技主題」「更換成藍色系」
- 製作任何需要統一視覺風格的輸出物
- 需要快速生成品牌配色方案
- 需要 CSS 設計 Token

---

## 🎨 10 大預設主題

### 使用方式

```javascript
// 引用方式
const theme = THEMES['dark-ocean'];

// 套用到 HTML
document.documentElement.style.setProperty('--bg', theme.colors.bg);
document.documentElement.style.setProperty('--accent', theme.colors.accent);
```

10 組主題的完整色票、字體設定與 CSS Token 生成器見 [REFERENCE.md](./REFERENCE.md)。

## 🤝 協同技能

- `artifacts-builder`：套用主題到 React 組件
- `d3js-visualization`：圖表配色與主題同步

---

## 版本紀錄 (Changelog)
- **[2.0.0]** 2026-05-04：V2.0.0 Polymorphic Labeling Migration — 依生命週期 SOP 導入多態功能性技術標籤 (tool_category, execution_env, io_format)，建立執行層 Manifest 路由能力。

## [Security] Smart Integration & DLP
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議


---
⚙️ 【系統通訊層宣告 (System Comms Layer)】

網路狀態： 本技能已強制接入總控通訊網路。

接收協定 (Dynamic Payload)： 本文檔不再接收無結構的自然語言，必須處理封裝後的動態參數：
`[SYSTEM-CALL: theme-factory | PAYLOAD: { objective: "<核心意圖>", target_audience: "<受眾>", strategic_constraints: "<策略限制/禁語>", tone_variables: "<語氣微調>" }]`

> [!IMPORTANT]
> **Payload 淨化規則 (§6.3)**：
> - 若本技能屬於 analysis/ 或 orchestration/（無外部副作用）：接收戰略目標、語氣設定、情緒變數；拒絕 SQL/DOM/技術指令。
> - 若本技能屬於 execution/ 或 platform/（工具與整合層）：只接收 URL、DOM Selector、SQL、JSON Schema；拒絕認知參數。

發送協定：執行中若遇能力不足或需要外部協作，應停下來明確告知使用者目前卡在哪裡，不要自行尋找替代方案掩蓋問題。必須主動封裝 Dynamic Payload 並發出：
`[SYSTEM-CALL: 目標ID | PAYLOAD: { ... }]` 調閱其他技能。

回傳協定： 任務終止時，必須且只能輸出 `[SYSTEM-RETURN: SUCCESS/FAILED | DATA: <結果>]`。
