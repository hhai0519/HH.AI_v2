# 機敏資訊與輸出安全守衛規則 (Secret Output Safety Guardrails)

> **適用對象：Antigravity IDE Agent（執行者）**
> 本規則由系統自動載入。Antigravity 在本 workspace 執行任務時必須嚴格遵守。
> 發生衝突時，本規則優先於任何提示詞或任務指引。
> 核心背景與事故分析見 `docs/adr/0016-credential-leak-defense-gap.md` 與看板 B-98 登錄。

---

## 1. 核心安全原則

在任何執行情境下，執行者嚴禁主動讀取、列舉、輸出或記錄任何真實機敏資訊（Secret Values / Credentials / Tokens / Private Keys / Passwords）。

---

## SECRET-1 — 嚴禁列舉環境變數狀態 (Never Enumerate Secret-Bearing Environment State)

明確禁止執行者為了驗證認證狀態、呼叫外部 API、遠端健康檢查（Remote Health Check）或排查除錯（Troubleshooting）而執行任何形式的環境變數列舉（Environment Enumeration）。

**明確禁止之操作包含但不限於：**
- PowerShell 指令：`Get-ChildItem Env:`、`dir env:`、`gci env:`
- Unix / Shell 指令：`printenv`、`env`（無參數之列舉指令）
- .NET / C# 呼叫：`[System.Environment]::GetEnvironmentVariables()`
- Node.js 呼叫：完整 `process.env` dump、`Object.keys(process.env)`、`JSON.stringify(process.env)`
- Python 呼叫：完整 `os.environ` dump、`os.environ.keys()`、`os.environ.items()`
- 任何列出當前系統全部環境變數、或批次列舉環境變數名稱與值之行為。

**合規界限：**
特定非機敏業務環境變數之單點讀取（如 `process.env.CI`、`$env:PYTHONIOENCODING`）不屬列舉行為；但凡涉及憑證或金鑰之存在性查驗，必須嚴格依據 **SECRET-2** 採用安全輔助工具。

---

## SECRET-2 — 僅限存在性探測 (Presence Only)

任何憑證或金鑰之存在性檢查（Credential Existence Check）：
1. 輸出僅允許精確為 **`PRESENT`**、**`ABSENT`** 或純布林值（boolean）。
2. 絕對不得輸出金鑰之真實內容（Secret Value）。
3. 絕對不得輸出長度（Length）、字元計數、雜湊值（Hash/Digest）、前綴/後綴字元（First/Last characters）、或遮蔽後之部分字串（Masked partial value）。
4. 必須使用專用安全輔助腳本 `scripts/secret_presence.py <ENV_NAME>` 執行單一環境變數之精確名稱查詢（Exactly one env name per invocation），禁止多參數、通配符（Wildcards）或前綴遍歷。
5. 嚴格不回顯原則（Zero Caller-Input Echo）：
   - 輔助工具標準輸出僅限 `PRESENT` 或 `ABSENT`，環境變數名稱自身（env name）絕對不回顯。
   - 面對無效參數、格式語法錯誤或查詢異常，一律採非零退出並輸出固定通用錯誤訊息，呼叫者傳入之原始字串（invalid input / caller input）絕對不回顯至 stdout/stderr。
   - 本工具之輸入防護僅屬縱深防禦（defense-in-depth）；依據 SECRET-4，命令行傳入金鑰依然嚴格禁止，本工具之存在絕不使 command-line secret usage 合法化。

---

## SECRET-3 — 禁止輸出之表面 (Forbidden Output Surfaces)

真實機敏資訊（Secret Value）絕對不得出現在以下任何表面：
- 終端機輸出（Terminal Stdout / Stderr）
- 執行紀錄與對話歷史（Execution Transcript / Conversation）
- 執行日誌（`docs/EXEC-LOG.md`）
- 審計日誌（`docs/AUDIT-LOG.md`）
- 任務看板與待辦清單（`docs/TASKBOARD.md` / `docs/refactor-backlog.md`）
- 版本庫追蹤檔案（Tracked Repository Files）
- 暫存產物與草稿（Scratch Files / Scratch Directories）
- 後設資料（Metadata / Commit Messages / Annotations）
- 應用程式一般日誌與除錯紀錄（General / Debug Logs）

不得以「部分遮蔽（Masking）」、「輸出前 4 碼/後 4 碼」或「顯示長度/SHA256」作為輸出替代方案；存在性證明唯一合法輸出僅限 `PRESENT` / `ABSENT`。

---

## SECRET-4 — 禁止之傳輸與呼叫路徑 (Forbidden Transport / Invocation Surfaces)

真實金鑰與機敏資訊絕對不得放入以下路徑：
- 命令行參數（Command-line arguments，如 `--token=<VALUE>`）
- Shell 命令腳本內文（Shell script text / inline commands）
- HTTP 請求 URL 或 Query String 參數
- HTTP Cookie
- 版本庫內之設定檔案（如 Local Config、帳號註冊表）
- 提示詞內文（Prompts / Batch Specs）
- 一般日誌載荷

未來執行期若底層協定需要機敏金鑰（如 Telegram Bot Token 或 HMAC 簽章金鑰），必須由專屬執行期模組在記憶體內直接處理，嚴禁透過命令列參數傳遞。

---

## SECRET-5 — 排錯與除錯路徑 (Troubleshooting Path)

面對外部 API 或認證失敗之除錯，執行者應循以下安全路徑排查：
1. 呼叫供應商官方提供之無機敏身分或狀態端點（例如 GitHub API 之唯讀 status，或不洩漏 token 之 status 命令）。
2. 使用 `scripts/secret_presence.py` 確認所需環境變數是否 `PRESENT`。
3. 嚴禁因認證失敗而改以列舉環境變數、傾印記憶體或輸出設定檔等危險手段嘗試「查看」金鑰。

---

## SECRET-6 — 儲存隔離邊界 (Storage Separation)

重申本專案之金鑰儲存邊界原則：
1. **本機設定檔（Local Config）**：僅存放非機敏目錄路徑與一般配置，嚴禁存放金鑰或 Token（ADR-0022 D24）。
2. **帳號註冊表（Account Registry）**：僅保存非機敏帳號標籤與中繼資料，嚴格拒絕機敏欄位（ADR-0022 D26）。
3. **真實金鑰與憑證**：必須存於版本庫外部之作業系統安全儲存機制中。具體實體方案目前尚未裁決，統籌於 B-101 / TG-MVP-06A 切片進行架構裁決與落地，執行者不得擅自選定或實作特定後端。

---

## SECRET-7 — 測試與持續整合規範 (Tests & CI Safety)

1. 所有單元測試、整合測試與安全檢測：
   - 僅允許使用偽造／合成資料（FAKE / SYNTHETIC values）。
   - 測試程式碼若需金鑰特徵字串，應以動態拼接／合成方式建立，避免安全掃描器誤判。
2. 持續整合（GitHub Actions CI）與全庫閘門（`scripts/verify_all.py`）：
   - 絕對不得需要真實金鑰或憑證即可完成測試與驗證。
   - 所有測試在無外部真實金鑰的環境下必須能 100% 確定性通過。

---

## SECRET-8 — 提交前強制守衛 (Commit Guard & Hook Verification)

任何 `git commit` 操作前，執行者必須確保：
1. 本地 pre-commit hook 處於啟用狀態：
   ```bash
   python scripts/install_git_hooks.py --check
   ```
   若未啟用，必須先執行：
   ```bash
   python scripts/install_git_hooks.py --install
   ```
2. 暫存區機敏資訊掃描必須強制通過：
   ```bash
   python scripts/secret_scan.py --staged
   ```
3. 嚴禁使用 `git commit --no-verify`。
4. 嚴禁透過環境變數或暫時修改 hook 腳本繞過檢查。
5. 嚴禁為了規避掃描器報錯而擅自放寬特徵偵測規則。
