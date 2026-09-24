# ADR-0026: Gateway 機密提供者與 Windows 認證管理員架構契約 (Gateway Secret Provider & Windows Credential Manager)

- Status: Accepted Architecture Decision / Implementation Candidate Pending External Macro Audit
- Date: 2026-09-18
- Decision Owner: External Macro Auditor & 使用者 HH

## Context

在 Channel Gateway 架構（ADR-0022）、本機外部設定檔規範（D24）、非機敏帳號登錄模型（D26）、入站事件身分規範（ADR-0024）與出站可靠度及本機迴路 Local API 安全規範（ADR-0025）確立後，Channel Gateway 進入具備真實金鑰連線能力（Telegram Bot Token、LINE Channel Access Token、LINE Channel Secret、Local API HMAC Secret）之關鍵前置階段（B-101 / TG-MVP-06A）：

1. **零金鑰入庫與非明文設定約束**：ADR-0016、ADR-0022 D26 與 `.agents/rules/secret-output-safety.md` 嚴格禁止將真實 Token 或機密明文寫入版本庫，亦嚴格禁止以純文字形式存放於版本庫外之本機設定檔（Local Config）。
2. **AccountRegistry 領域模型純粹性**：`runtime/channel-gateway/core/account-registry.js` 為純非機敏領域模型，強制拒絕 `token`、`secret`、`password` 等機敏欄位。為支援多帳號熱切換（Hot Switching，D26），執行期必須能在不重啟 Gateway 進程的前提下，為當下活躍帳號取得對應之憑證。
3. **Local API HMAC 金鑰安全邊界**：ADR-0025 §15 確立 Agent 呼叫 Local API 時必須透過本機包裝程式（Client Wrapper CLI）在記憶體中讀取金鑰並計算簽章，Agent 僅傳入與檢視無機敏之業務參數。Gateway 與包裝程式均需具備統一且安全的機密取得機制。
4. **現行機密提供者缺口**：在 TG-MVP-06 discovery 中已確認 Gateway SecretProvider 為 `ABSENT`，具體提供者為 `UNDECIDED`；且 `docs/mcp-environment-guide.md` 之 Windows User 環境變數指引不治理 Channel Gateway。因此必須在任何真實金鑰消費者實作前，正式選定並落地具體之作業系統級機密提供者架構。

---

## Decision

專案正式採行 **Windows Credential Manager（Windows 認證管理員）** 之 **`CRED_TYPE_GENERIC`** 作為 Channel Gateway v1 之具體機密提供者，並確立以下核心架構契約：

### 1. 提供者型態與持久化層級 (Credential Type & Persistence)

- **憑證型態**：採用 Windows 認證管理員泛型憑證（`CRED_TYPE_GENERIC = 1`）。
- **持久化層級**：採用本機持久化（`CRED_PERSIST_LOCAL_MACHINE = 2`）。
- **語意範疇**：`CRED_PERSIST_LOCAL_MACHINE` 代表同一台實體電腦上同一具名 Windows 使用者在跨次登入（logon sessions）與重開機間之持久化保存；**絕不授權跨使用者（cross-user）機密存取**，亦不啟用企業漫遊憑證（`CRED_PERSIST_ENTERPRISE`）。

### 2. 確定性非機敏 TargetName 命名空間 (Deterministic Target Namespace)

憑證 TargetName 採確定性路徑生成，不依賴 `AccountRegistry` 存放可變之 secretRef 欄位，杜絕目錄遍歷與分隔符注入：

- **根命名空間前綴**：`HH.AI_v2/channel-gateway/v1`
- **Telegram 帳號 Bot Token**：
  `HH.AI_v2/channel-gateway/v1/telegram/<encoded-account-id>/bot-token`
- **LINE 帳號 Channel Access Token**：
  `HH.AI_v2/channel-gateway/v1/line/<encoded-account-id>/channel-access-token`
- **LINE 帳號 Channel Secret**：
  `HH.AI_v2/channel-gateway/v1/line/<encoded-account-id>/channel-secret`
- **Local API 全域 HMAC Secret**：
  `HH.AI_v2/channel-gateway/v1/local-api/hmac`
- **帳號識別碼領域對齊、正規 Unicode 與確定性百分比編碼 (Account-ID Domain Alignment, Unicode Well-Formedness & Percent Encoding)**：`AccountRegistry` 與 `SecretRef` 共享完全一致之帳號識別碼正規化領域：
  - 帳號識別碼必須為正規 Unicode 純量序列（Well-formed UTF-16 sequence / Unicode scalar representation）。於任何 trim 正規化與百分比編碼前，強制拒絕所有 raw ASCII 控制字元（`U+0000..U+001F`）、`DEL`（`U+007F`）以及孤立代理字元（lone surrogate code units: `U+D800..U+DBFF` 與 `U+DC00..U+DFFF`），杜絕以先行 strip 隱匿非法字元。
  - 嚴禁使用 `toWellFormed()` 等靜默替換機制（silent replacement）將損毀代理字元替換為 `U+FFFD`，身分識別正規化絕不容許將相異之損毀輸入別名化為同一合法帳號；不合規輸入一律 Fail-Closed 拒絕。
  - 合法領域接受所有內部可列印字符，包含一般空白、反斜線 `\`、問號 `?`、井字號 `#`、單雙引號 `'` `"`、合法 Unicode 字符以及合法輔助平面代理對（如 Emoji，例如 `😀` 編碼為 `%F0%9F%98%80`）。
  - TargetName 路徑元件採決定性百分比編碼：以 `encodeURIComponent` 為基底，並強制將單引號 `'` 規範化編碼為 `%27`。
  - 字面 `%` 視為資料本身而非預編碼權威，編碼為 `%25`，防止路徑別名攻擊（如 `alpha%20beta` 與 `alpha beta` 映射至不同 TargetName）。
  - 斜線字元編碼為 `%2F`，杜絕路徑段注入。TargetName 本身為完全非機敏之後設資料。
- **SecretRef 封閉不可變領域模型與規範重導 (SecretRef Immutability & Re-derivation)**：`SecretRef` 為封閉領域模型，建構後即透過 `Object.freeze(this)` 凍結不可變。提供者絕對不以呼叫端傳入之 `secretRef.getTargetName()` 為權威，而是自已驗證之語意欄位（`channel`, `purpose`, `accountId`）在內部重新推導規範目標，杜絕子類別覆寫與原型篡改。
- **最終規範語法硬性斷言 (Final Target Grammar Assertion)**：提供者在調用 PowerShell 橋接前，必須硬性斷言目標符合 `HH.AI_v2/channel-gateway/v1/(telegram/...|line/...|local-api/hmac)` 規範語法，任何額外路徑段、未知後綴、空白、引號或非法百分比編碼立即 Fail-Closed 拋出 `INVALID_SECRET_REFERENCE`。
- **PowerShell 橋接縱深防禦目標檢查 (Bridge Defense-in-Depth Target Validation)**：PowerShell 橋接腳本內部亦以正則表達式嚴格拒絕非規範命名空間 TargetName，杜絕作為任意憑證庫讀取器。

### 3. 精確查找與零列舉原則 (Exact Lookup & Zero Enumeration)

- **精確查找**：SecretProvider 僅支援透過上述確定性 TargetName 進行單一精確查詢（`CredReadW`）。
- **嚴禁枚舉**：嚴格禁止呼叫 `CredEnumerate`、`cmdkey /list` 或列出 Windows 認證管理員內之任何憑證清單。
- **無備援與無回退原則 (No Fallback Provider)**：
  - 專案不實施「若認證管理員找不到則改查環境變數／.env／檔案」之回退鏈。
  - 凡遇憑證缺失、權限不足或系統錯誤，一律 **Fail-Closed** 中止並拋出穩定之 `SecretProviderError`。

### 4. 固定具名 Windows 使用者身分契約 (Fixed Named Windows-User Identity Contract)

- **固定身分**：Channel Gateway 執行真實金鑰時，必須運行於固定具名 Windows 使用者安全身分（Fixed Named Windows-User context）下；配置憑證的使用者與運行 Gateway 之行程身分必須完全相同。
- **禁止環境**：嚴禁以 `LocalSystem`、`LocalService`、`NetworkService` 或 `S4U`（Service-for-User）無使用者環境執行真實金鑰 Gateway，因認證管理員與 DPAPI 金鑰綁定於具體使用者設定檔。
- **託管相容性**：Gateway 生命週期維持 ADR-0022 D4 由作業系統託管（Windows Startup、工作排程器或使用者身分服務），但設定必須綁定具名使用者。架構不硬編碼特定使用者名稱或 SID。

### 5. 行程與記憶體安全邊界 (IPC, Process & Memory Safety Boundary)

- **非 Shell 原生引數執行**：Node.js 與 PowerShell 橋接（`windows-credential-manager-read.ps1`）透過 `child_process.spawnSync` 陣列傳遞，強制 `shell: false`，杜絕任何 shell 命令字串插值注入。
- **純管道 stdout 傳輸**：機密二進位資料僅透過管道 stdout 由 PowerShell 直傳 Node 記憶體；標準輸出禁止輸出任何說明文字或版權標語（使用 `-NoLogo`）。
- **同步橋接有限逾時、生產契約與 Fail-Closed (Bounded Bridge Timeout & Parity)**：`child_process.spawnSync` 強制配置有限逾時，上限 60000ms。歷史上過去 F2-A 曾由 10000ms 提升至 30000ms 建立 production/live parity（消除測試覆寫與生產之契約漂移）；2026-09-19 CI Run 35447317701 再次出現 Test J production-default timeout recurrence，因此現行有界生產契約將生產預設進一步提升至 **60000ms**（上限維持 60000ms）。60 秒預設為生產環境與 Live 整合測試之統一契約；Windows Live 整合測試必須直接調用生產預設建構子，不得使用測試覆寫。逾時失敗一律 Fail-Closed 映射為穩定之 `PROVIDER_UNAVAILABLE`，絕不將原始錯誤物件、超時堆疊、子進程輸出拼接進錯誤訊息。
- **同步提供者解析之生命週期邊界 (Synchronous Provider Resolution Boundary)**：由於 `spawnSync` 阻塞 Node.js 事件迴圈，SecretProvider 解析僅允許於受控之生命週期邊界點（帳號啟用、帳號切換、消費者初始化、明確憑證重新整理）執行；**嚴禁設計為熱路徑（hot-path）訊息處理中之每訊息/每事件同步查詢**。v1 提供者內部不維護長效快取，取用機密之 Consumer 生命週期負責管理其合理 Buffer 存續期間。
- **原生指標單一擁有權契約 (Single Native Ownership Contract)**：PowerShell 橋接腳本對 `CredRead` 取得之原生指標 `$pCred` 採單一擁有權模型；所有釋放操作集中於 `finally` 區塊執行（`CredFree` 恰好調用一次），釋放後指標立即重置為 Zero（`$pCred = [IntPtr]::Zero`），正常成功路徑與各 catch 分支皆不重複釋放，杜絕 double-free。
- **PowerShell 受管機密位元組暫存抹除 (PowerShell Secret Byte[] Clearing)**：PowerShell 於複製原生指標資料至受管位元組陣列 `$blob` 後，在同一 `finally` 清理區塊以最佳努力原則調用 `[Array]::Clear($blob, 0, $blob.Length)` 抹除暫存記憶體，不宣稱不可能之完美 GC 抹除保證。
- **環境變數淨化**：子行程環境僅傳入啟動 PowerShell 必需之非機敏系統變數（`SystemRoot`、`PATH`、`TEMP` 等），嚴禁將 Gateway 記憶體中任何憑證或環境變數向下傳遞。
- **執行期二進位 Buffer 暴露**：SecretProvider 回傳型態嚴格為 `Buffer`，禁止轉為字串或 JSON 序列化。
- **消費者最佳努力歸零**：取用機密之 Consumer 擁有 Buffer 生命週期，於使用完畢後應以最佳努力原則（Best-effort）呼叫 `buf.fill(0)` 抹除，不宣稱不可能之完美垃圾回收抹除保證。
- **零提供者內部快取**：SecretProvider v1 內部不維護持久快取，各消費者依架構授權管理生命週期。

### 6. 自動化測試與 CI 合成規範 (Synthetic Testing & CI Contract)

- **零真實金鑰測試**：本地與 CI 自動化測試絕對不讀取、不建立、不依賴真實生產金鑰。
- **動態合成整合測試**：Windows 平台整合測試一律於執行時動態產生隨機 GUID 之合成泛型憑證，讀取驗證後於 `finally` 區塊立即執行 `CredDeleteW` 清理並驗證刪除後 Fail-Closed。
- **非 Windows 平台相容**：非 Windows 環境（如 Linux CI）下，Provider 驗證 `UNSUPPORTED_PLATFORM` 拒絕路徑，保證零未註冊測試跳過（Zero Unregistered Skips）。

---

## Alternatives Considered

1. **Windows User 層級環境變數（Windows User Environment Variables）**：
   - *優點*：Node 原生 `process.env` 即可讀取，無須外部行程。
   - *否決理由*：環境變數在 Windows 登錄檔（`HKCU\Environment`）中以純文字儲存；子行程易意外繼承；且專案規則 `.agents/rules/secret-output-safety.md` 對環境變數枚舉採取高度警戒防護，容易誘發資訊洩漏事故。故不選為 v1 核心機密儲存。
2. **DPAPI 外部加密檔案（DPAPI-Protected Repo-External File）**：
   - *優點*：靜態加密保護，綁定目前 Windows 使用者金鑰。
   - *否決理由*：Node.js 標準庫缺乏原生 DPAPI 綁定；且需自訂二進位/JSON 檔案封裝格式、備份與檔案鎖處理。相較之下，Windows 認證管理員為作業系統標準憑證庫，語意更精確。DPAPI 列為未來未選取之架構替代方案，**不作為 v1 回退提供者**。
3. **第三方 Keyring / Native C++ Node Addon（如 `keytar`、`ffi-napi`）**：
   - *優點*：跨平台抽象程式庫。
   - *否決理由*：引入原生編譯相依性（`node-gyp`、Visual Studio Build Tools、Python 構建鏈），極易破壞輕量化部署與 CI 可重現性；違反 ADR-0022 D15 極小依賴原則。

---

## Consequences

- **金鑰安全規格升級**：專案所有通訊金鑰全面脫離純文字檔案與環境變數，由 Windows 認證管理員保護。
- **多帳號熱切換就緒**：依據確定性 TargetName 規則，Gateway 切換帳號時可即時解析新活躍帳號金鑰，滿足 ADR-0022 D26.4 零重啟要求。
- **金鑰輪換零代碼修改**：更換 Bot Token 或 Channel Secret 時，僅需更新認證管理員對應 TargetName，版本庫程式碼與設定檔零異動。
- **身分與平台約束明確**：明確約束生產部署必須為固定具名 Windows 使用者環境，杜絕在 S4U 或 LocalSystem 下因認證管理員缺失而引發的靜默失敗。
- **零依賴閉包維持**：`runtime/channel-gateway/package.json` 維持零第三方依賴，由 Windows 原生系統能力達成安全閉環。

---

## TG-MVP-10 Telegram Bot API 協議邊界例外 (Telegram Protocol-Boundary Exception — M14)

1. **二進位 Buffer 契約不變**：
   - `SecretProvider` 介面嚴格維持回傳二進位 `Buffer`，提供者層級絕對不產生或回傳明文字串。
   - 配接器（Adapter）獨佔擁有金鑰 Buffer 之生命週期；適配器停止或終止時執行最佳努力歸零（`buf.fill(0)`）。
2. **通訊協定狹隘例外（Protocol Necessity）**：
   - 經外部宏觀審計查證，Telegram Bot API HTTP 請求路徑強制要求格式為 `https://api.telegram.org/bot<token>/METHOD`。
   - 因此，Telegram 適配器獲准僅在 HTTP 請求建構之狹隘邊界內，將金鑰 Buffer 暫時解碼為短暫存在之 UTF-8 字串。
3. **記憶體與日誌嚴格紀律**：
   - 嚴禁將 Token 字串存入物件實例欄位（No instance field caching）。
   - 嚴禁回傳、嚴禁序列化為 JSON、嚴禁寫入日誌。
   - 嚴禁在診斷訊息或例外堆疊中包含完整請求 URL 或原始錯誤。
   - 使用完畢後立即解除字串參照；適配器權威持有的二進位 Buffer 在生命週期結束時執行 `fill(0)`。
   - 明確記錄 V8 引擎不可變字串無法保證由應用層精確抹除記憶體之客觀事實，不宣稱完美記憶體抹除。
4. **Token 字元語法防禦檢驗**：
   - 在解碼與發送請求前，必須以位元組層級驗證合規之 ASCII Token 語法（`<bot_id>:<secret_token>`），強制拒絕斜線 `/`、問號 `?`、空白、C0 控制字元與 DEL，杜絕路徑或查詢參數注入。

---

## Relationship to Existing Architecture

- **與 ADR-0016（機密洩漏防線）之關係**：落實 ADR-0016 關於金鑰不入庫、不在工作目錄留存明文之規範。
- **與 ADR-0022（Channel Gateway 架構）之關係**：實現 D26 帳號金鑰外部非明文儲存與熱切換要求；保持 D15 零額外依賴。
- **與 ADR-0025（Local API 安全）之關係**：為 §15 Client Wrapper 與 Loopback HTTP 伺服器提供共用之 HMAC 金鑰安全取得基底。
- **與 E-03 路線圖之關係**：閉合 B-101，解除 `TG-MVP-10`、`TG-MVP-11`、`TG-CUT-04` 之機密提供者前置依賴。

