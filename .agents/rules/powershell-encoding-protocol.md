# 規則：跨平台編碼安全協定 (Cross-Platform Encoding Protocol)

這是一條 workspace 規則，Antigravity 在本專案內執行任何 PowerShell 相關任務或文字檔操作時都會載入。
本協定為系統終極防線，所有涉及文字檔操作的腳本，無論新建或維護，皆須無條件遵守。

*(由 V3.0.0 審計修復流程中的 Hex 拼湊血淚教訓總結)*

## 1. 物理寫入最高標準：PowerShell Here-String

根據過去的災難反思，處理多行 Markdown 或 JSON 寫入時，**強制使用 PowerShell 單引號 Here-String (`@' ... '@`)** 以免疫跳脫字元與轉義崩潰。Node.js 僅限用於不涉及大篇幅文件生成的單純邏輯運算或 BOM 清洗。

```powershell
# PowerShell Here-String 強制範例：多行 Markdown 寫入
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$content = @'
# 標題
多行內容，不需要任何跳脫字元
包含反引號與「特殊符號」均安全
'@
[System.IO.File]::WriteAllText('output.md', $content, $utf8NoBom)
```

**適用情境**：
- 多行 Markdown 文件生成（SOP、SKILL.md、README）
- 含 CJK（中日韓）字元的 JSON 結構寫入
- 任何含換行符、引號、特殊符號的文字寫入

## 2. 禁止使用 Hex 拼湊法 (No Char-Code Concatenation)

**嚴禁**在腳本中使用 `[char]0xXXXX` 十六進位陣列來拼湊人類可讀字串。
此做法雖可繞過 PowerShell 編碼問題，但：
- ❌ **完全喪失人類可讀性**，維護成本極高
- ❌ **難以 Code Review**，隱藏潛在安全風險
- ❌ **不具可移植性**，跨平台遷移時會引入新問題

**正確替代方案**：改用本文件規範的 Node.js 或 Python 腳本，以原生字串處理 CJK 內容。

## 3. PowerShell 強制 UTF-8 宣告 (PowerShell UTF-8 Lock)

若因特殊工程需求（如 CI/CD Pipeline、系統整合腳本）**必須**使用 PowerShell 處理含 CJK 字元的檔案，腳本開頭**必須強制加入**以下宣告，鎖死執行緒編碼：

```powershell
# 強制 UTF-8 宣告 — 置於腳本第一行，禁止省略
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
```

*(註：本問題與命令列環境執行 Python 腳本遇到的編碼異常為同類問題。正如 `.agents/rules/git-and-reporting.md` 所規範，執行驗證腳本前必須設定 `$env:PYTHONIOENCODING = "utf-8"`。)*

## 4. 腳本選用決策樹 (Decision Tree)

```
需要操作含 CJK 字元的檔案？
├─ YES → 優先使用 Node.js 或 Python ✅
│         └─ 若環境不允許 → PowerShell + 強制 UTF-8 宣告 (見第3節)
└─ NO  → 任意語言皆可，但仍建議 UTF-8 宣告
```

## 5. 命令列參數與多行文字傳遞協定 (Parameter Passing & Payload Protocol)

*(由 ADR-0010 巢狀 Shell 參數傳遞陷阱與回覆腳本實戰事故總結)*

在跨進程、巢狀 Shell 或命令列呼叫時，必須遵守以下操作原則：

1. **巢狀與字串插值環境下不得假設環境變數能安全傳遞多行內容 (Nested Shell Boundary)**：
   - 在 Nested PowerShell、`powershell -Command "..."`、shell-within-shell、外層字串插值 (string interpolation) 或其他存在前層解析的呼叫情境下，**不得假設 `$env:*` 能可靠承載多行文字或使用者生成之動態 payload**。
   - 前層 Shell 或外層呼叫者可能在 payload 抵達目標 PowerShell 直譯器之前提前展開、改寫、截斷或破壞 quoting（視具體呼叫鏈與跳脫語境而定），導致命令語法解析損毀（例如在事故中被提早展開為無效的 `= @'...'`）。
   - 本條規範並非宣稱環境變數在所有情境皆不可用，而是針對巢狀/插值邊界之非確定性展開風險實施防護。
2. **多行與動態文字優先採「先寫 UTF-8 實體檔，再傳檔案路徑」模式 (Preferred File Transport)**：
   - 凡涉及多行回覆、使用者生成內容或含 CJK 字元之大型 payload 傳遞，優先使用可確認 UTF-8 編碼之檔案寫入機制將內容寫入實體檔案，再將該檔案路徑作為命令列參數傳遞給目標腳本。
   - 此模式能有效規避 Shell 前層提前展開風險與 Windows 命令列參數 CJK 編碼損壞問題。
3. **路徑參數必須使用解析後之完整絕對路徑 (Fully Resolved Absolute Path)**：
   - 傳遞給消費檔案之腳本（如 reply 腳本或資料處理工具）的路徑參數，必須使用完整絕對路徑，嚴禁依賴 caller 當前工作目錄之相對路徑（避免呼叫端位於根目錄而檔案位於子目錄時解析不一致）。
   - **可攜性邊界警語**：「必須使用絕對路徑」是指執行時以當前環境動態解析後的完整絕對路徑傳遞，**絕對禁止**把特定開發機路徑（例如包含使用者名稱之本機路徑）硬編碼進版本控制文件或程式碼中。
4. **下游 Stdin Fallback 的卡死風險排查 (Process Hang via Stdin Fallback)**：
   - 若下游腳本設計為「找不到指定檔案時退回 stdin 輸入」，當路徑傳遞錯誤時，進程不會立即報錯退出，而是會無限期等待 stdin 輸入，表現為 Task 長時間停滯在 RUNNING 且零輸出。
   - 遇此類進程卡死排查時，優先檢查檔案路徑是否正確解析並存在，不得誤判為網路或權限問題；未來新實作之腳本應優先設計為檔案缺失時立即報錯退出 (Fail-Closed)，避免無聲退回 stdin。

