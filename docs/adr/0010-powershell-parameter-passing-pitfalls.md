# ADR-0010: PowerShell 參數傳遞的兩個陷阱，回覆腳本必須用絕對路徑

- Status: Accepted
- Date: 2026-08-24

## Context

2026-08-09 的 $$TG連線$$ 實戰過程中，光是「把一段中文回覆傳給
reply_tg.js」這件事就失敗了兩次，各自是不同的原因，兩次都跟 PowerShell
的參數傳遞行為有關。

**第一次失敗（task-182 之前）：環境變數在傳入前就被展開**

執行以下形式的指令：
$env:REPLY_TEXT = @"...多行文字..."@; node reply_tg.js ...

錯誤輸出：
= : The term '=' is not recognized as the name of a cmdlet...
[ERROR] 找不到任何回覆文字輸入來源！

根因：在外部 `powershell -Command "..."` 的雙引號字串中，`$env:REPLY_TEXT`
會在傳入 PowerShell 之前，就被前端 Shell 提前展開為空值，導致實際執行的
命令變成 `= @'...'` 這種無效語法。

**第二次失敗（task-182）：相對路徑導致進程卡在 stdin**

改用「先寫檔、再讀檔」的方式，執行：
node reply_tg.js 8810338764 reply.txt ...

錯誤輸出：
[WARNING] Specified file "reply.txt" does not exist. Falling back to env/stdin...

進程沒有報錯退出，而是**進入等待 stdin 輸入的卡住狀態**，導致 Task 182
永遠停留在 RUNNING，必須手動用 manage_task kill 終止。

根因：`reply_tg.js` 收到的是相對路徑 `reply.txt`，而執行指令時的工作目錄
是專案根目錄，實際檔案卻建立在
`skills/03_Execution/telegram-bot-cdp-bridge/telegram-bot-project/reply.txt`，
兩者不匹配。找不到檔案時腳本會退回讀 stdin，而不是直接失敗。

## Decision

1. **不要透過環境變數傳遞回覆文字**：在 `powershell -Command "..."` 形式的
   指令中設定並讀取環境變數，會遭遇前端 Shell 提前展開的問題。改用
   「先用 write_to_file 工具把內容寫入實體檔案，再把檔案路徑傳給腳本」
   的模式。

2. **傳給 reply 腳本的檔案路徑，一律使用完整絕對路徑**，不使用相對路徑。
   正確形式：
   node <絕對路徑>\reply_tg.js "<userId>" "<回覆檔案的完整絕對路徑>" "<AGENT_LABEL>" "<TopicCategory>" "<摘要>"

3. **注意 reply 腳本「找不到檔案時退回 stdin」的行為**：這個 fallback
   設計會讓路徑錯誤表現為「Task 卡住不動」而不是「明確報錯」，排查時
   容易誤判成網路或權限問題。如果發現某個 Task 長時間停在 RUNNING 且
   沒有輸出，優先檢查是不是路徑沒對上而卡在等 stdin。

## Consequences

- 遷移到 HH.AI_v2 的 runtime 層後，reply 腳本的呼叫範例（不論寫在
  SKILL.md、SOP 或啟動腳本裡）都必須使用絕對路徑形式，不能為了「看起來
  簡潔」改成相對路徑。
- 如果未來要重寫 reply 腳本，建議把「找不到指定檔案時退回 stdin」這個
  fallback 改成直接報錯退出——目前這個設計會把一個明確的路徑錯誤，
  偽裝成一個難以診斷的卡死狀態。這個改動屬於行為變更，不在遷移範圍內，
  需要另外評估後執行。
- 中文內容透過命令列參數傳遞在 Windows 環境有編碼風險，「寫檔再讀檔」
  的模式同時也規避了這個問題，不只是為了解決展開問題。
