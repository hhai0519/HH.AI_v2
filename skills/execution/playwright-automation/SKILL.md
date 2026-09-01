---
name: playwright-automation
description: 使用 Playwright 建立完整的瀏覽器自動化測試框架。自動偵測開發伺服器、撰寫測試腳本、驗證響應式設計、填寫表單、測試登入流程、檢查連結並產出測試報告。當使用者要求『寫 E2E 測試』、『Playwright 測試腳本』、『跨瀏覽器測試』、『響應式設計測試』時使用。若只需快速截圖或查看瀏覽器日誌而不必建立測試套件，改用 webapp-testing。
---

# Playwright 瀏覽器自動化 (Playwright Automation)

### 【摘要】觸發條件與 DLP 聲明
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議

本技能使用 **Playwright** 實現完整的瀏覽器端到端自動化，包含 E2E 測試腳本撰寫、表單填寫、截圖擷取、響應式驗證、登入流程測試、連結檢查與跨瀏覽器相容性驗證。

---

## 🎯 觸發條件

- 需要撰寫 E2E 測試腳本
- 自動化填寫表單或執行重複性 UI 操作
- 驗證頁面在不同裝置的響應式表現
- 測試登入/認證流程
- 批量截圖（多頁面/多裝置）
- 監控頁面是否有死連結或 JS 錯誤

---

## 🛠️ 初始化與環境

```bash
# 安裝
npm install -D @playwright/test
npx playwright install  # 安裝所有瀏覽器（chromium, firefox, webkit）

# 只安裝 chromium（最快）
npx playwright install chromium
```

完整測試腳本模板與報告配置見 [REFERENCE.md](./REFERENCE.md)。

---

## 🤝 協同技能

- `webapp-testing`：快速即時調試（截圖+日誌）
- `systematic-debugging`：深層問題排障
- `chrome-devtools-mcp`：實時現場勘查與 Selector 除錯工具

---

## 🔍 實時現場勘查與 Selector 除錯流程 (新支援)

在執行複雜的 Playwright 測試過程中，若遇到 CSS 選擇器找不到或點擊超時等問題，可配合 `chrome-devtools-mcp` 進行即時調試：
1. **定位故障頁面**：呼叫 `list_pages` 列出當前測試中開啟的所有瀏覽器分頁。
2. **進入上下文**：使用 `select_page(page_id)` 連接至發生錯誤的特定分頁。
3. **實時 DOM 檢驗**：使用 `evaluate_script` 原生工具，在該分頁中實時測試你的 CSS 選擇器（例如 `document.querySelector('...')`），確認 DOM 是否已載入。
4. **防範 Session 污染**：若測試涉及敏感帳號 Cookie，呼叫 `new_page` 時請務必帶入 `isolatedContext: "debug_session"` 參數，將除錯環境與主要環境隔離。
5. **確認修復後寫入代碼**：在 MCP 實時調試成功後，再將正確的 Selector 或等待邏輯更新至 E2E 測試腳本中，避免盲目重試。

---

## 版本紀錄 (Changelog)
- **[2.0.0]** 2026-05-04：V2.0.0 Polymorphic Labeling Migration — 依生命週期 SOP 導入多態功能性技術標籤 (tool_category, execution_env, io_format)，建立執行層 Manifest 路由能力。

## [Security] Smart Integration & DLP
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議


---
⚙️ 【系統通訊層宣告 (System Comms Layer)】

網路狀態： 本技能已強制接入總控通訊網路。

接收協定 (Dynamic Payload)： 本文檔不再接收無結構的自然語言，必須處理封裝後的動態參數：
`[SYSTEM-CALL: playwright-automation | PAYLOAD: { objective: "<核心意圖>", target_audience: "<受眾>", strategic_constraints: "<策略限制/禁語>", tone_variables: "<語氣微調>" }]`

> [!IMPORTANT]
> **Payload 淨化規則**（規範本體見 `.agents/rules/skill-engineering-guardrails.md` §3）：
> 本技能位於 `execution/`，屬技術型技能，因此：
> - 接收：URL、API Endpoint、SQL Query、JSON Schema、檔案絕對路徑
> - 拒絕：認知參數、語氣描述、角色設定、情緒變數

發送協定：執行中若遇能力不足或需要外部協作，應停下來明確告知使用者目前卡在哪裡，不要自行尋找替代方案掩蓋問題。必須主動封裝 Dynamic Payload 並發出：
`[SYSTEM-CALL: 目標ID | PAYLOAD: { ... }]` 調閱其他技能。

回傳協定： 任務終止時，必須且只能輸出 `[SYSTEM-RETURN: SUCCESS/FAILED | DATA: <結果>]`。
