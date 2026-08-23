---
name: webapp-testing
description: "使用 Playwright 互動和測試本地 Web 應用程式的工具包。支援驗證前端功能、偵錯 UI 行為、擷取瀏覽器螢幕截圖以及查看瀏覽器日誌。"
type: execution
---


# Web 應用快速測試 (WebApp Testing)

### 【摘要】觸發條件與 DLP 聲明
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議

本技能透過 **Playwright** 對本地 Web 應用進行即時互動測試：一鍵截圖存證、捕獲 JS 錯誤、驗證元素狀態、模擬使用者操作，提供比完整 E2E 框架更快速的即時調試循環。

> **與 `playwright-automation` 的區別**：本技能用於**快速即時調試**，無需建立測試套件；`playwright-automation` 用於建立**完整自動化測試框架**。

---

## 🎯 觸發條件

- 提到「截圖」「測試這個頁面」「UI 有沒有問題」
- 需要快速驗證頁面渲染是否正確
- 需要捕獲 JavaScript 錯誤或控制臺日誌
- 需要驗證某個功能按鈕是否可點擊
- 需要測試 localhost 本地服務

---

## 🛠️ 輕量 MCP 直接測試模式 (新支援)

當只需快速驗證頁面渲染、檢查控制台錯誤，或進行簡單互動時，優先使用 `chrome-devtools-mcp` 提供之原生工具，避免編寫與執行實體腳本：

1. **載入網頁分頁**：
   - 呼叫 `new_page(url="http://localhost:3000", timeout=15000)` 建立並載入頁面。**請注意：`url` 為必要參數。**
2. **截圖驗證外觀**：
   - 呼叫 `take_screenshot` 取得渲染結果。
3. **檢查控制台錯誤**：
   - 呼叫 `list_console_messages` 檢查有無 JS 報錯。
4. **點擊與輸入互動 (關鍵規範)**：
   > [!IMPORTANT]
   > `chrome-devtools-mcp` 的 `click` 與 `fill` 工具**不接受** CSS 選擇器 (Selector)，僅接受 a11y 樹的 `uid`。請依以下兩種方式進行互動：
   > - **方式一 (原生 MCP)**：先呼叫 `take_snapshot` 取得頁面節點的 `uid`，再將 `uid` 帶入 `click(uid="...")` 或 `fill(uid="...", value="...")`。
   > - **方式二 (JS 注入)**：呼叫 `evaluate_script` 注入執行，例如：`function: "() => document.querySelector('#search-input').click()"`。
5. **釋放資源**：
   - 任務結束時，務必呼叫 `close_page` 關閉分頁以防止記憶體溢出。

---

需要複雜斷言或自訂邏輯時，參見 [REFERENCE.md](./REFERENCE.md) 的完整 QuickWebTester Python 類別範例。

