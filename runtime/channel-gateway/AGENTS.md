# Channel Gateway Scoped Rules

本文件定義在 `runtime/channel-gateway/` 目錄及其子目錄下工作時必須遵守之範圍受限規則（Directory-Scoped Rules）。
架構決策脈絡見 `docs/adr/0022-channel-gateway-architecture.md` 與 `docs/adr/0023-channel-gateway-state-store-sqlite.md`。

---

## 1. 唯一權威運作狀態來源 (Operational State Source)

- 所有 Channel Gateway 之通道控制狀態（ChannelControl）、入站收件箱（Inbox）、接收游標（Ingest Cursor）與未來出站狀態（Outbox），唯一權威持久化路線為 **SQLite / `node:sqlite`**（ADR-0023 D27）。
- 依 TG-MVP-08 / T9 架構裁決，舊版過渡性 JSON 運作模組（`durable-state-store.js`、`channel-state-recovery.js`、`channel-state-persistence.js`）已正式自版本庫退役並移除，專屬測試亦一併除役；SQLite / `node:sqlite` 仍為唯一權威運作狀態來源。
- 嚴禁重新建立 `durable-state-store.js`、`channel-state-recovery.js`、`channel-state-persistence.js` 作為運作狀態路徑，亦嚴禁新增任何新的 JSON 運作狀態寫入器、相容性 shim 或快照儲存邏輯。
- 嚴禁恢復 `channel-gateway-state.json` 之運作持久化路徑；歷史設計對照與溯源僅保留於 Git 歷史紀錄與 ADR-0023，不屬於 active runtime 表面。
- 檔案系統歸檔與附件例外（ADR-0022 D22 / D17，見 §12）維持不變。

## 2. SQLite PRAGMA 契約 (PRAGMA Contract)

未來 SQLite 儲存庫（Repository）連線初始化時，必須設定並讀回驗證以下 PRAGMA：
- `PRAGMA journal_mode = WAL;`（讀回必須為 `wal`）
- `PRAGMA synchronous = FULL;`（讀回必須為 `2`）
- `PRAGMA foreign_keys = ON;`（讀回必須為 `1`）
- `PRAGMA busy_timeout = 5000;`（讀回必須為 `5000`）

啟動時若任一項讀回值不符，必須 **FAIL-CLOSED** 立即中止啟動。
T6 階段正式採用 `busy_timeout = 5000`（5000ms），其基礎為 T1 Windows spike 經 606 秒 Defender 並行讀寫實測 0 unrecovered lock 驗證之數值。

## 3. 交易邊界強制 (Transaction Boundary)

- 通道控制接管（takeover）、訊息領取（claim）、狀態變更等任何具備狀態轉移副作用之操作，必須在 SQLite 交易 **COMMIT 成功後**，始得將 success 結果回傳給呼叫端。
- 在 SQLite 交易邊界機制（T7 階段）正式建立前，嚴禁重啟或復活舊 Wave 2H 基於 JSON 快照的協調器。

## 4. 事件去重、邏輯訊息身分與游標原子性 (Event Dedup, Message Identity & Cursor Atomicity)

- **事件去重 (Event Deduplication)**：事件層級防重之 Canonical Key 為 `(account_id, platform_event_id)`，由 `inbound_event` 資料表之 `UNIQUE(account_id, platform_event_id)` 提供硬性 DB 約束。
- **邏輯訊息身分 (Logical Message Identity)**：`inbox` 表之 `UNIQUE(account_id, platform_msg_id)` 保留為邏輯訊息身分約束，用途為邏輯訊息查詢、回覆授權（Reply Authorization）及編輯/收回關聯（Edit/Unsend Correlation），不得再視為事件去重鍵。
- **真實重複事件 (True Duplicate Event)**：相同 `(account_id, platform_event_id)` 之重放為冪等零副作用（Zero Mutation）：不新增事件、不異動收件箱、不確保/建立通道控制列、不推進或變更游標。
- **相同訊息不同事件 (Same Message ID, New Event ID)**：相同 `platform_msg_id` 但不同 `platform_event_id`（如編輯或更新事件）不得因邏輯訊息 ID 相同而直接判定為重複事件。
- **游標能力與交易邊界 (Cursor Capability & Transaction Boundary)**：
  - 具游標能力（Cursor-enabled）之平台：事件/訊息持久化結果與游標推進決策必須在同一 SQLite 交易內完成，杜絕長輪詢重啟重複拉取或斷線漏訊。
  - 無游標能力（No-cursor）之平台（如 LINE）：不得偽造游標數值或時間戳，亦不得建立偽造之 `ingest_cursor` 記錄。
- 帳號切換（Account Switch）與 Bot 身分切換之游標與去重，亦必須納入交易邊界處理。

## 5. SQL 查詢安全 (SQL Safety)

- 所有資料庫查詢與更新必須一律使用 **Prepared Statements 與 Parameter Binding**。
- 嚴禁使用字串拼接（String Concatenation）或樣板字串（Template Literals）組裝 SQL 數值。

## 6. 資料庫綱要遷移與生命週期排序 (Schema Migration & Lifecycle Ordering)

- 資料庫綱要必須版本化（Versioned Schema，如 `schema_version` 表格）。
- 綱要變更僅允許向前遷移（Forward-only migrations）；TG-MVP-10 綱要版本為 **v5**（`ingest_cursor` 引入 `updated_at_ms` 支援跨週重置）。
- 執行任何綱要遷移前，必須具備經驗證之備份。
- **程序關閉順序契約 (Shutdown Ordering Contract — M2)**：
  1. 優先呼叫 `TelegramInboundAdapter.stop()` 中止長輪詢與重試定時器。
  2. 確保背景 fetch 與重試定時器完全靜止（quiesced）。
  3. 始得呼叫 `BackupRuntimeOwner.stop()` 或關閉底層 SQLite 儲存庫（`repo.close()`）。
  4. Telegram 配接器嚴禁自行關閉儲存庫（Adapter must not close repository）。

## 7. 備份機制與衛生治理 (Backup & Hygiene — TG-MVP-09 / TG-MVP-09A)

- 運行中的 SQLite 資料庫嚴禁使用作業系統檔案複製（`fs.copyFile` / `Copy-Item`）作為標準備份手段。
- 備份必須使用 SQLite 原生支援之 **`VACUUM INTO`** 或經嚴格驗證之線上備份 API。
- **唯一備份原語不變量**：T11A `SqliteStateRepository.createVerifiedBackup()` 為唯一生產備份操作原語，嚴禁改寫內部驗證核心或建立第二套備份實作。
- **固定常數與排程週期**：保鮮度門檻固定為 24 小時（`BACKUP_FRESHNESS_THRESHOLD_MS = 86_400_000`），檢查間隔固定為 1 小時（`BACKUP_CHECK_INTERVAL_MS = 3_600_000`），嚴禁由環境變數、Local Config 或 CLI 覆寫。
- **單一驗證備份目錄**：備份檔案唯一合法存放路徑為 `stateRoot/backups/` 子目錄。僅允許在已通過安全驗證之 canonical `stateRoot` 底下，由 Gateway 自行建立並維護 `backups/` 子目錄（`ensureBackupsDirectory`）；除此以外維持 Zero Directory Auto-Create 原則。
- **舊版備份平滑過渡**：啟動與排程時自動偵測 `stateRoot` 根目錄殘留之歷史正規備份檔案（`channel-gateway-state.backup-*.sqlite3`），透過 `fs.renameSync` 平滑遷移至 `stateRoot/backups/` 並納入統一保留管理。
- **啟動與關閉語義**：啟動時僅執行保鮮度檢查，無合規備份或最新備份已逾期（age >= 24h）時方建立一份備份，嚴禁無條件啟動備份；進程關閉時不觸發關閉備份。
- **耐久保鮮度證據**：僅以 `stateRoot/backups/` 下合規命名之備份檔案（`channel-gateway-state.backup-v{N}-{uuid}.sqlite3`）的正規非符號連結最大有效 `mtimeMs`（<= nowMs）作為保鮮度判準。
- **容量保留與最少數量下限**：Local Config schemaVersion 3 新增 `backup` 區塊（單位為十進位精確位元組 exact decimal bytes，預設 `maxTotalBytes: 1_000_000_000` 即 1,000,000,000 位元組，嚴禁宣告為 1 GiB，`minKeepCount: 3`），維持 v2 雙向相容。`totalBytes` 嚴格定義為受管正規備份之總位元組數（managed canonical backup bytes），不計入 `backups/` 內未受管之非正規檔案。實施容量驅動保留（無天數年齡限制），嚴格保障最少保留最新 3 份合規備份（Floor of 3）。
- **決定性清理**：清理時機嚴格限制於「新備份成功驗證寫入後」，備份失敗時嚴禁刪除任何既有備份。超額清理依 `mtimeMs` 由舊至新排序，平局時以檔名字典順序打破。
- **剩餘空間雙倍安全檢查**：執行備份前必須檢查磁碟剩餘空間（`bavail * bsize` >= `2 * dbSize`）；空間不足時安全跳過備份，不呼叫 `VACUUM INTO`，記錄 `INSUFFICIENT_FREE_SPACE` 診斷，進程維持正常服務。
- **備份健康狀態原子寫入**：備份健康狀態動態評估（`OK`、`WARN`、`ALERT`）並以非敏感格式寫入 `stateRoot/backup-health.json`（非 `backups/` 子目錄內），嚴格透過 Channel Gateway 專屬 task-local bounded atomic JSON writer 確保原子性（不採用 `shared/atomicFs.js`，保持 09A 零修改）。ALERT 包含 `NO_SUCCESSFUL_BACKUP_48H`、`CONSECUTIVE_BACKUP_FAILURES`、`SINGLE_BACKUP_EXCEEDS_CAPACITY`、`INSUFFICIENT_FREE_SPACE`、`FREE_SPACE_CHECK_FAILED`、`BACKUP_DIRECTORY_UNAVAILABLE`、`BACKUP_INVENTORY_UNAVAILABLE`。
- **隱私與機敏資訊安全防護**：備份健康狀態與所有排程日誌絕對不得包含任何本機路徑、資料庫完整路徑、原始例外訊息、Token 或訊息內容；診斷日誌僅輸出受控枚舉名稱。
- **重入與重疊防護**：單一實例保持 in-flight 旗標，重入或重疊 tick 一律略過（skip），不佇列排隊、不並行備份。
- **非致命失敗處理**：定期掃描或備份失敗時僅記錄邊界明確且不含機密之診斷，服務保持運作（不 process.exit、不立即重試、不指數退避），留待下一個正常 1 小時 tick 重新評估。
- **過渡期進程內執行擁有者**：`BackupRuntimeOwner` 僅負責最小進程內生命週期配對（open repo -> start scheduler; stop scheduler -> close repo），不是 daemon、不是 OS 服務、不安裝訊號處理器、不決定最終 Gateway 生命週期排序（留待 TG-MVP-10/11 組合），嚴格禁止建立第二個背景守護行程。
- **靜態加密與 Node 監控點**：TG-MVP-09A 狀態資料庫與備份清理衛生規範（實作候選中，等待外部審查 / implementation candidate / awaiting External Macro audit）。備份維持 SQLite 原生格式，不引入應用層加密；磁碟靜態資料加密為使用者作業系統層級責任（USER_RESPONSIBILITY BitLocker on Windows）。持續監控 Node 內建 `node:sqlite` 版本穩定性。
- **同步事件迴圈特性**：`node:sqlite DatabaseSync` 與 `VACUUM INTO` 為同步操作，執行期間可能短暫阻塞 Event Loop；本階段接受 pre-go-live 小規模資料庫之每日單次備份前提。

## 8. 資料庫存放位置防護 (Database Location Guard)

- 資料庫存放路徑僅能來自 ADR-0022 D24 所定之外部本機設定（Repo-External Local Config）。
- 嚴禁將資料庫建立於 OneDrive、同步資料夾、UNC 網路掛載路徑（包含標準 UNC 與擴充 UNC `\\?\UNC\`）、系統關鍵目錄或 Git 版本庫根目錄。
- 路徑保護守衛（`assertSafeStateRootLocation`）必須由程式機械式強制檢驗；守衛僅限於 `stateRoot`，不誤判位於 redirected Desktop 之 `archiveRoot`。


## 9. Node.js 版本與測試治理契約 (Node Prerequisite & Test Governance)

- `.nvmrc`（`24.21.0`）為版本庫測試與 CI 釘選之 Canonical Node 版本；`package.json` engines（`>=24.15.0 <25`）為本機相容性下限。
- Ubuntu Canonical Verify 與 Windows Gateway CI 均必須透過 `.nvmrc` 釘選 Node 24 執行。
- **Windows PowerShell 本機 npm 指令規則**：當 Windows PowerShell ExecutionPolicy 阻擋 `npm.ps1` 腳本執行時，本機命令一律改用 `npm.cmd`（例如 `npm.cmd --prefix runtime/channel-gateway test`）。**嚴禁** 透過 `Set-ExecutionPolicy` 削弱作業系統安全原則僅為執行測試；CI 與工作流行為維持不變。
- Gateway Node 測試一律由 `tests/*.test.js` 自動探索（Automatic Discovery），嚴禁回到手工登錄測試檔名。
- 測試跳過政策採 **零未註冊跳過（Zero Unregistered Skips）**：
  - Linux / Ubuntu 環境之核准跳過清單為 EMPTY（任何 skip 一律 FAIL）。
  - Windows 環境僅允許 `test-policy.json` 精確列出之平台能力限制跳過（Capability Skips）；清單項目代表許可（Permission）而非強制計數（Expected Count）。
  - 任何未註冊之 skip 或未完成之 TODO 一律視為 FAIL-CLOSED。
  - 新增任何 skip 許可必須經過有邊界之架構治理變更（Bounded Governance Change），執行者嚴禁自行擴充白名單。

## 10. 資料保留與清理邊界 (Retention & Cleanup)

- 訊息保留期過期清理必須與 ADR-0022 D22 之對話歸檔完成契約（Archive Completion Contract）協調，嚴禁在確認歸檔成功前先行刪除資料庫狀態。

## 11. 機敏資訊防護與機密提供者契約 (Secrets Protection & SecretProvider Contract)

- SQLite 資料庫嚴禁儲存 Telegram Token、LINE Secret、GitHub Credential 或任何明文密碼與私鑰。
- 帳號非機敏後設資料與金鑰儲存必須嚴格遵循 ADR-0022 D26、ADR-0026 及外部憑證契約。
- **SecretProvider 擁有權**：SecretProvider 為 Gateway 獨佔擁有之執行期基礎設施（Gateway-owned），禁止洩漏給 Agent。
- **v1 具體提供者**：v1 唯一核准具體提供者為 **Windows Credential Manager（`CRED_TYPE_GENERIC`）**。
- **精確 TargetName 查找**：僅允許精確正規化 TargetName 查找（`HH.AI_v2/channel-gateway/v1/...`），嚴禁列舉（no enumeration）憑證庫。
- **零備援提供者與零回退**：嚴禁環境變數回退（no env fallback）、嚴禁 Local Config 明文機密、嚴禁 AccountRegistry 機密值、嚴禁 DPAPI 檔案回退；憑證缺失一律 Fail-Closed。
- **零第三方依賴**：不引入 npm 機密管理套件或原生 Node 模組，由 Windows 內建 API 與受管橋接執行。
- **固定具名 Windows 使用者身分不變式**：生產 Gateway 與憑證配置必須運行於同一固定具名 Windows 使用者身分（fixed named Windows-user context），嚴禁以 S4U 或 LocalSystem/NetworkService 無使用者環境執行真實金鑰。
- **執行期專用 Buffer 暴露**：SecretProvider 輸出嚴格為二進位 `Buffer`，僅限執行期內部消費，禁止序列化為 JSON，禁止轉為字串印出。
- **消費者最佳努力歸零**：取用機密之 Consumer 在使用完畢後，應以最佳努力原則立即執行 `buf.fill(0)` 抹除，不宣稱完美記憶體抹除保證。
- **SecretRef 封閉不可變領域模型**：`SecretRef` 為封閉領域模型，建構後即透過 `Object.freeze` 深層凍結不可變；嚴格拒絕子類別（subclass）與原型覆寫。
- **提供者權威推導與目標語法斷言**：提供者嚴禁信任呼叫端傳入之 `getTargetName()`，必須自已驗證之語意欄位（channel, purpose, accountId）在內部重新推導規範 TargetName，並於啟動橋接前硬性斷言符合 `HH.AI_v2/channel-gateway/v1/...` 規範語法。
- **同步橋接有限逾時與熱路徑禁止 (F2-A)**：PowerShell 同步橋接必須設定有界逾時（預設 60000ms，上限 60000ms，Windows live 整合測試必須使用生產預設），逾時失敗一律 Fail-Closed 映射為 `PROVIDER_UNAVAILABLE`；SecretProvider 解析僅允許於生命週期受控點（帳號啟用、帳號切換、消費者初始化、明確憑證重新整理）執行，**嚴禁於熱路徑（hot path）訊息處理中作為每訊息同步查詢**。
- **原生指標單一擁有權與暫存位元組清理**：PowerShell 橋接腳本對 `CredRead` 取得之原生指標 `$pCred` 採 `finally` 單一擁有權釋放（`CredFree` 恰好一次）且立即歸零（`$pCred = [IntPtr]::Zero`）；其複製之受管機密位元組陣列 `$blob` 於輸出後在 `finally` 區塊以最佳努力原則立即執行 `[Array]::Clear` 歸零。
- **帳號識別碼領域對齊、正規 Unicode 與安全百分比編碼 (F2-B / F3)**：`AccountRegistry` 與 `SecretRef` 共享一致之帳號識別碼領域；於 trim 之前嚴格拒絕 ASCII 控制字元（`U+0000..U+001F`）、`DEL`（`U+007F`）與不合法 UTF-16 孤立代理字元（lone surrogates，一律 Fail-Closed 拒絕，嚴禁使用 `toWellFormed()` 替換為 `U+FFFD` 造成身分別名）；合法領域支援一般空白、反斜線、問號、井字號、引號、合法 Unicode 及輔助平面合法代理對（如 Emoji）；TargetName 路徑元件採決定性百分比編碼（單引號一律編碼為 `%27`，字面 `%` 編碼為 `%25` 防別名，斜線編碼為 `%2F` 防路徑注入）；嚴禁呼叫端提供預先編碼之 TargetName 權威。
- **測試純合成性**：自動化測試一律使用動態合成金鑰，測試完成立即清理刪除；嚴禁在 CI 或測試中使用真實生產機密。
- **真實金鑰配置邊界**：真實 Telegram/LINE/HMAC 憑證配置為管理員於 Agent 對話外部之手動操作，嚴禁將真實金鑰作為 CLI 參數、環境變數或提示詞文字傳入 Agent。

## 12. 檔案系統歸檔例外 (Filesystem Exception)

- ADR-0022 D22 之對話歷史歸檔（Conversation Archive）與 D17 媒體附件（Attachments）為檔案系統資產，**不屬於** SQLite 運作狀態。
- 嚴禁因採用 SQLite 而將二進位大型附件或對話歸檔日誌塞入資料庫。
