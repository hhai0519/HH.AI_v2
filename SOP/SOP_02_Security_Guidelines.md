---
title: "資訊安全與防護準則"
version: "3.1.3"
tags: ["SOP", "資安", "DLP", "Security"]
dependencies: []
---

# 本協作系統 Skills 資訊安全與防護準則

本文件規範 本協作系統 系統中所有 Agent 技能（Agent Skills）在執行時的安全邊界、機密資料防護與注入攻擊防禦措施，確保系統在自動化運作中維持最高安全等級。

---

## 1. 智慧整合與資料防洩（Smart Integration & DLP）

### 核心原則：最小權限與上下文隔離
- **上下文安全邊界**：AI 技能在呼叫外部服務、解析使用者指令、執行研究任務時，必須在最小必要的上下文範圍內操作，禁止主動讀取或暴露超出任務範圍的資料。
- **資料防洩偵測（DLP）**：
  - **憑證偵測**：AI 系統禁止在日誌、回覆或工件中直接記錄 API Key、OAuth Tokens 或其他憑證字串。Email 地址、電話號碼、身分識別碼等個資亦不得出現在非加密的 log 檔中。
  - **上下文清理**：在呼叫外部 API 或傳遞 Payload 前，必須掃描 context 內容，移除敏感資訊（如密碼、私鑰、個資片段），確保不對外洩漏。
- **[V10 新增] WMI 精準狙擊原則 (Surgical Strike Principle)**：執行任何環境淨化或進程重置腳本時，**絕對禁止**使用無差別屠殺指令（例如 `Stop-Process -Name 'node'` 或 `Stop-Process -Name 'powershell'`）。
  - **唯一合法查殺法**：必須使用 `Get-CimInstance Win32_Process` 搭配 `CommandLine LIKE '%特定特徵碼%'` 進行特徵追蹤狙擊，確保零誤殺。
  - **正確範例**：`Get-CimInstance Win32_Process -Filter "Name = 'ssh.exe' AND CommandLine LIKE '%a.pinggy.io%'" | Invoke-CimMethod -MethodName Terminate`

---

## 2. 憑證管理 (Credential Management)

- **嚴禁硬編碼**：禁止在 `SKILL.md` 或任何 Markdown 文件中直接嵌入明文憑證或密碼。
- **安全存放**：所有憑證必須透過環境變數存放，並確保相關目錄已納入 `.gitignore` 保護範圍。
- **AI 任務中的憑證引用**：在自動化任務中，AI 系統須透過環境變數（Environment Variables）引用憑證，嚴禁使用硬編碼字串。
- **Git 歷史污染處置原則**：若敏感 API Token 不慎進入 Git 歷史紀錄並觸發 Push Protection，嚴禁僅使用 `git rm` 刪除檔案。必須執行完整的 `.git` 歷史重置 (History Wipe) 或使用 BFG 工具清理，確保歷史負債被徹底銷毀。

---

## 3. 注入攻擊防禦（Injection Defense）

### CSV / Excel 公式注入防禦
- 產出 CSV 格式資料時，必須對每筆欄位進行清洗，若欄位內容以 `=`、`+`、`-`、`@` 等符號開頭，須在前方加上 `'` 字元進行轉義，防止試算表軟體執行惡意公式。

### 提示詞注入防禦 (Prompt Injection Defense)
- 所有來自外部來源（使用者輸入、網頁抓取、資料庫查詢）的字串，在傳入 AI Prompt 前，必須經過結構化包裝，禁止直接以字串拼接方式組裝 Prompt，防止惡意指令覆蓋系統行為。

---

## 4. SSRF 防禦 (SSRF Defense)

- **內網位址封鎖**：禁止 AI 系統發送任何指向 `169.254.169.254`（雲端元資料伺服器）或 `file://` 協議的請求。
- **流量限制與白名單**：所有外部請求必須透過 Proxy 路由，並限制單次回應大小（建議上限 5MB），防止資料外滲。

---

## 5. 文件合規與本地化（Documentation & Localization）

### SOP 6：本地對話紀錄的資料防洩漏 (DLP) 規範
* **背景說明**：桌面 `Line對話紀錄` 資料夾為明文 TXT 檔案，極易被備份或系統日誌意外打包。
* **強制規範**：
  * 寫入檔案前，必須過濾對話內容中的敏感參數。
  * 嚴禁在 TXT 檔案中寫入明文 LINE Secret、資料庫連接密碼、API Key 或身分證號。
  * 偵測到敏感特徵時，必須自動漂白為 `*** SECURITY_SENSITIVE_DATA_REDACTED ***` 等提示。

### SOP 合規規範
- **語言規定**：所有技能描述（SKILL.md）、正式文件與交接內容，必須先以**台灣正體中文**撰寫，英文原始版本僅作參考。
- **翻譯索引（SSOT）**：所有技能的正體中文標題、描述與別名，統一維護於各技能目錄的 SKILL.md frontmatter 中。
- **同步義務**：每次技能有實質修改時，必須同步更新所屬 bucket 的 README.md 索引，由 Agent 直接執行檔案寫入，無需依賴外部 Node.js 腳本。

---

*本文件為 本協作系統 系統安全基礎規範，所有 Agent 技能均須嚴格遵守，以確保系統在自動化運作中維持最高安全等級，並對所有互動合規負責。*
