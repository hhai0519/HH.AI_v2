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
