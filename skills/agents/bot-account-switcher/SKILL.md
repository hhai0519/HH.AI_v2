---
name: bot-account-switcher
description: LINE & Telegram 官方帳號雙平台切換工具。當使用者要求切換帳號或輸入 $$Line帳號$$、$$TG帳號$$ 時使用，具備實時訊息額度查詢，會覆寫 env 並重啟 PM2。
disable-model-invocation: true
authorized_mcp_tools: []
semantic_firewall: "/Domain/System/Configuration/"
---

# 雙平台帳號自動切換指令

> **關於 `authorized_mcp_tools` 白名單的說明**：
> 本技能透過 Agent 內建的終端機工具（如 PowerShell）直接執行腳本，不經過 MCP 伺服器授權層，因此授權白名單為空陣列（`[]`）是正確的設定狀態，並非遺漏。

當總管輸入 `$$Line帳號$$` 或 `$$TG帳號$$` 時，請依序執行以下步驟：

1. **偵測觸發平台與額度查詢**：
   - 若為 `$$Line帳號$$`：
     - 執行 `node scripts/get_line_quotas.js`（尚未遷移至 HH.AI_v2，路徑為預計位置）取得各帳號實時剩餘額度。
     - 根據回傳之 `options` 陣列文字，發起 `ask_question` 呈現「依剩餘額度由高至低自動排序」之動態選單供總管點選。
   - 若為 `$$TG帳號$$`：
     - 解析 `.env.local` 中的 `TELEGRAM_BOT_DESC_<suffix>` 動態生成選單。

2. **切換帳號與寫入**：
   - 根據總管點選之 `suffix`，執行 `node scripts/switch_bot_env.js <platform> <suffix>`（尚未遷移至 HH.AI_v2，路徑為預計位置）。
   - 若為 `line`，執行以下指令以防進程不存在（其中 `start_line.ps1` 尚未遷移至 HH.AI_v2，路徑為預計位置）：
     ```powershell
     try { npx pm2 restart line-bridge 2>$null; if ($LASTEXITCODE -ne 0) { throw "restart failed" } } catch { powershell -ExecutionPolicy Bypass -File start_line.ps1 -Start }
     ```
   - 若為 `tg`，執行以下指令以防進程不存在（其中 `start_telegram.ps1` 尚未遷移至 HH.AI_v2，路徑為預計位置）：
     ```powershell
     try { npx pm2 restart tg-bridge-zero-delay 2>$null; if ($LASTEXITCODE -ne 0) { throw "restart failed" } } catch { powershell -ExecutionPolicy Bypass -File start_telegram.ps1 -Start }
     ```

   > **注意（引用 ADR-0014）**：
   > (a) 在 Windows 環境下使用 PM2 時要注意 npm 與 `.cmd` 的相容性問題。
   > (b) 若重啟後觀察到 `line-daemon` 處於 Stopped 狀態，這是其等待 `bridge.js` 綁定 port 的預期設計行為，並非故障，請勿誤判。

3. **喚醒監聽器與接管控制權**：
   重啟完成後，Agent 必須根據平台執行以下動作以啟動背景長輪詢監聽器（請將指令放入背景執行）：
   
   > **注意（引用 ADR-0009）**：
   > 啟動基建與取得控制權的操作必須在「單一 Task 內」連續串接執行，絕不可拆分成多個獨立的 Task。否則當前 Task 結束時，關聯的 PM2 子進程會被 Windows Job Object 強制回收導致服務中斷。

   - 若為 `line`：
     執行以下指令（腳本尚未遷移至 HH.AI_v2，路徑為預計位置）：
     `node skills/platform/line-bot-zero-delay/line-bot-project/start_line.js Antigravity-Master "AI_Master" true` 
   - 若為 `tg`：
     先執行以下指令（腳本尚未遷移至 HH.AI_v2，路徑為預計位置）：
     `node skills/platform/telegram-bot-cdp-bridge/telegram-bot-project/start_tg.js Antigravity-Master`
     再執行以下指令（腳本尚未遷移至 HH.AI_v2，路徑為預計位置）：
     `node skills/platform/telegram-bot-cdp-bridge/telegram-bot-project/poll_tg.js Antigravity-Master`

4. **確認與回報**：確認服務與監聽器皆成功啟動，並回報總管切換完成。
