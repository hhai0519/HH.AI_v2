# ADR-0009: Windows Job Object 進程回收機制，雙平台啟動必須在單一常駐 Task 內串接

- Status: Accepted
- Date: 2026-08-24

## Context

2026-08-09 執行 $$LINE連線$$ 與 $$TG連線$$ 時，兩個平台各自獨立踩到同一個
根因，各試了 3 到 4 次才排除。這個問題的表徵極具誤導性：啟動腳本明確回報
成功（`[OK] LINE Bridge successfully started on Port 3000!`），但下一個
指令立刻拿到 `ECONNREFUSED`。

LINE 側的失敗序列：
1. 執行 `00_Master_Menu.ps1 -Panel LINE橋接`，PM2 拉起 line-bridge
   (PID 1872)，Port 3000 成功綁定
2. 隨後執行 `start_line.js`，回報「Bridge 連線失敗，請確認 bridge.js
   是否運作中」
3. 二度執行，依然失敗
4. `http GET 127.0.0.1:3000` 得到 ECONNREFUSED，`netstat -ano | findstr 3000`
   回傳 Exit Code 1，證實進程已死亡

Telegram 側的失敗序列（獨立發生，同樣根因）：
1. task-29：`00_Master_Menu.ps1 -Panel TG橋接` → PM2 啟動成功，隨 Task
   結束遭清理
2. task-69：`npx pm2 start ecosystem.telegram.config.js` → 同樣遭清理
3. task-139：加上 `$env:PM2_HOME` 再試 → PID 36792 依然被收回
4. task-158：改採獨立 long-running 背景 Task 直接啟動 → 成功常駐

## Decision

**根因**：Antigravity IDE 的 `run_command` 工具在 Windows 下會建立獨立的
Console Process，並將其附屬在專屬的 Windows Job Object 中，該 Job Object
帶有 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` 標記。當 Task 的主腳本執行到
最後一行退出時，作業系統會對該 Task 的 Job Object 發動全面清理，**將屬於
該 Job 的所有子進程（包含背景運行的 PM2 Daemon、node bridge.js、
ssh.exe 隧道）全數強制殺死**。

**因此，啟動基建與取得控制權這兩件事，絕對不能拆成兩個獨立的 Task 執行。**

正確做法：把「PM2 Bridge 點火指令」與「控制權鎖定指令」寫進同一個
`run_command` 背景任務，並確保最後執行的指令是一個永不退出的長輪詢
（`poll_inbox.js` / `poll_tg.js`），用它的常駐特性把整個 Job Object
維持住。

LINE 側的正確指令形式：
powershell -ExecutionPolicy Bypass -Command "& '<絕對路徑>\Modules\Start-LineBot.ps1' -Start; node <路徑>\start_line.js <AGENT_ID> '<AGENT_LABEL>' true"

Telegram 側的正確指令形式：
powershell -NoProfile -ExecutionPolicy Bypass -Command "Set-Location '<telegram-bot-project 路徑>'; node dist\bin\cli-zero-delay.js"

## Consequences

- 任何未來重寫啟動流程的人，都必須維持「單一 Task 串接」這個約束，
  不能為了「流程清晰」把啟動拆成多個步驟分別執行——那樣一定會重現這個問題，
  而且錯誤訊息（ECONNREFUSED）完全不會指向真正的根因。
- 這也解釋了為什麼 `poll_inbox.js` / `poll_tg.js` 內部的無限輪詢迴圈
  不能被「優化」掉：它們的常駐特性正是維持 Job Object 存活的關鍵，
  而不只是為了接收訊息。
- 遷移到 HH.AI_v2 的 runtime 層時，這個約束必須原樣保留，並在對應的
  SKILL.md 或啟動腳本註解中明確標示，避免後人誤改。
