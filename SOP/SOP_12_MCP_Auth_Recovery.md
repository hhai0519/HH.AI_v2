---
title: "外部 MCP 服務認證修復標準作業程序"
version: "1.0.0"
tags: ["SOP", "MCP", "認證修復", "NotebookLM", "外部服務"]
dependencies: [".agents/rules/skill-engineering-guardrails.md", "SOP_05_System_Policies.md"]
---

# SOP_12 外部 MCP 服務認證修復 SOP (External MCP Auth Recovery)

> [!IMPORTANT]
> 本 SOP 適用於所有透過 Cookie/Session 認證的外部 MCP 服務（如 NotebookLM、Notion 等）。
> 當 MCP 工具回傳認證錯誤或 `auth_status: stale` 時，必須依本 SOP 執行，**不得跳過任何步驟**。

---

## 1. 觸發條件

- MCP `server_info` 回傳 `auth_status: stale | not_configured | error`
- 任何 MCP 工具回傳 `Authentication expired` 或類似訊息
- `nlm login --check` 顯示失敗

---

## 2. 診斷流程

### 步驟 2.1：確認伺服器狀態
```python
server_info()  # 查看 auth_status 欄位
```

| auth_status | 意義 | 對應動作 |
|-------------|------|---------|
| `stale` | 憑證已過期 | 執行第 3 節完整修復流程 |
| `not_configured` | 從未設定 | 執行第 3 節完整修復流程 |
| `unverified` | 網路問題 | 先確認網路，再重試 |
| `configured` | 正常 | 無需修復 |

---

## 3. NotebookLM MCP 認證修復標準流程

> [!CAUTION]
> **步驟順序絕對不可顛倒。** 若直接執行 `nlm login` 而未先完成步驟 3.1，Cookie 將無效，修復會失敗。

### 步驟 3.1：執行自動或引導式預檢 (Chrome DevTools MCP)
Agent 優先使用 `chrome-devtools-mcp` 進行自動預檢，降低人工介入頻率。此過程必須包覆於 `try-catch` 異常處理中：

1. **自動導航與預檢**：
   - 呼叫 `chrome-devtools-mcp` 的 `new_page` 工具，並帶入參數 `url: "https://notebooklm.google.com"` 與 `timeout: 15000` (15 秒)。
2. **登入狀態判定與 SRE 處置**：
   - 呼叫 `take_screenshot` 工具擷取當前頁面，並判斷登入狀態：
     - **情況 A（已自動登入）**：若截圖中已直接顯示筆記本列表，代表 Cookie 已自動刷新並就緒。此時請呼叫 `close_page` 關閉分頁，並直接前進至 **步驟 3.2**。
     - **情況 B（未登入 / 需人工介入）**：若截圖顯示 Google 登入或選擇帳號畫面，請將截圖呈送給使用者，並告知：「已為您開啟瀏覽器登入頁面，請在彈出的視窗中完成 Google 登入。」
       > [!SECURITY]
       > **資安防線**：Agent 嚴禁嘗試使用 `type_text` 或 `fill` 自動填寫使用者的密碼，亦不得將含有敏感 OAuth Token 參數的 URL 或密碼輸入畫面記錄至 any walkthrough 或日誌中。
     - **情況 C（MCP 異常 / 無頭模式不可互動）**：若 MCP 工具呼叫超時或回傳錯誤，立即啟動軟性降級，執行傳統手動引導（請使用者手動開啟 Chrome 瀏覽器訪問該網址）。
3. 確認進入筆記本列表後，再次呼叫 `close_page` 釋放資源，隨後執行步驟 3.2。

### 步驟 3.2：執行認證指令
```powershell
# 優先嘗試全域指令
nlm login

# 若遇到 PATH 環境變數遺失或指令無法辨識，請改用絕對路徑強制喚醒：
C:\Users\HH.AI_260806\.local\bin\nlm.exe login
```

### 步驟 3.3：判斷成功標準（關鍵！）

| 輸出訊息 | 代表 | 動作 |
|---------|------|------|
| `✓ Authentication valid! Notebooks found: N` | ✅ 成功 | 繼續步驟 3.4 |
| `✓ Successfully authenticated! Cookies: N extracted` | ❌ 失敗 | 重新從步驟 3.1 開始 |

### 步驟 3.4：更新 MCP 伺服器快取
```python
refresh_auth()  # 等待回傳 status: success
```

### 步驟 3.5：驗證修復完成
```python
notebook_list()  # 確認可正常列出筆記本
```

---

## 4. 根本原因說明

NotebookLM 需要特定的認證 Cookie（`OSID`、`__Secure-OSID`）才能通過 API 驗證。這些 Cookie 只有在 Chrome 瀏覽器**實際訪問** `notebooklm.google.com` 後才會存在。

若未先訪問 NotebookLM 頁面就執行 `nlm login`，工具只會提取 Google 帳號的通用 Cookie，缺少 NotebookLM 特定的憑證，導致 HTTP 302 重定向至登入頁面。

---

## 5. 常見錯誤速查

| 症狀 | 原因 | 解法 |
|------|------|------|
| `auth_status: stale`，`nlm login` 顯示「Cookie 提取成功」但仍失敗 | 未先訪問 NotebookLM | 重新執行步驟 3.1 |
| `refresh_auth` 回傳 `status: expired` | `nlm login` 未成功完成 | 重新從步驟 3.1 開始 |
| `notebook_list` 回傳認證錯誤 | MCP 快取未更新 | 等待 30 秒後再次呼叫 `refresh_auth` |
| Chrome 未彈出 | 瀏覽器衝突 | 手動關閉 Chrome 再執行 `nlm login` |
| `nlm : The term 'nlm' is not recognized` | 新環境 PATH 變數遺失 | 改用絕對路徑 `C:\Users\HH.AI_260806\.local\bin\nlm.exe login` |

---

## 6. 相關設定檔位置

| 項目 | 路徑 |
|------|------|
| MCP 指示文件 | `C:\Users\HH.AI_260806\.gemini\antigravity-ide\mcp\notebooklm\instructions.md` |
| Antigravity Skill | `C:\Users\HH.AI_260806\.gemini\antigravity\skills\nlm-skill\` |
| Knowledge Item | `C:\Users\HH.AI_260806\.gemini\antigravity-ide\knowledge\notebooklm-auth-sop\` |
| 認證憑證儲存 | `C:\Users\HH.AI_260806\.notebooklm-mcp-cli\profiles\default\` |

---

*本 SOP 建立於 2026-06-13 | v1.0.0 | 基於實際修復案例（Conversation: da924ec9）建立*