# ADR-0023: Channel Gateway 採用 node:sqlite 作為唯一運作狀態來源 (Channel Gateway SQLite State Store)

- Status: Accepted
- Date: 2026-09-17
- Decision Owner: 使用者 HH

## Context

在 ADR-0022 確立 Channel Gateway 架構與 Wave 2E～2G 施工過程中，專案原規劃採用基於檔案系統的單一 JSON 快照封套儲存原語（`channel-gateway-state.json` 搭配 `atomicFs.js` 原子更名寫入）。隨後在實施多通道快照橋接（Wave 2G）與規劃通道狀態轉換提邊界（Wave 2H）時，揭示了純 JSON 快照持久化路線的結構性限制：

1. **交易邊界與狀態原子性**：JSON 快照在每次狀態異動時需對整個多通道集合進行全量序列化與磁碟寫入；隨著通道訊息與狀態擴展，無法提供細粒度的行級鎖定與原子交易（ACID）。
2. **重啟復原與當機一致性**：當進程在寫入中途遭強制終止時，即使原子更名能避免檔案損毀，未提交與已提交狀態難以在單一檔案內達成精確的 Rollback / Commit 分離。
3. **訊息防重與去重約束**：在接收訊息時，JSON 陣列需手動以 JavaScript 集合檢查去重，缺乏資料庫原生 `UNIQUE(account_id, platform_msg_id)` 約束之硬性保障。（架構補充：該 constraint 仍保留為收件箱邏輯訊息身分；事件層級去重語意已由後續 ADR-0024 supersede，正規事件去重鍵為 `(account_id, platform_event_id)`，runtime landing 由 TG-MVP-05 schema v4 `inbound_event` 完成）。
4. **游標與訊息攝取原子性**：長輪詢（Long-Polling）或 Webhook 接收時之接收游標（Ingest Cursor）更新必須與訊息寫入同一交易邊界，否則面臨重啟重複拉取或漏訊風險。
5. **未來發送隊列（Outbox）**：未來出站訊息之發送狀態機需要可靠的行級狀態流轉，非全量快照所能高效承載。

2026-09-17，專案擁有者（使用者 HH）做出正式裁決 **D27～D30**，決定將 Channel Gateway 運作狀態持久化改採 Node.js 內建之 `node:sqlite` 作為唯一權威狀態來源，暫停 Wave 2H，並在正式實作前完成 Windows 實機技術驗證（Spike）。

## Decision

### 1. 唯一權威運作狀態來源 (D27)

確立以 Node.js built-in **`node:sqlite`** 作為 Channel Gateway 運作與控制狀態（Operational & Control State）的唯一權威持久化來源（Authoritative State Source）。
其涵蓋範疇包括：通道控制狀態（ChannelControl）、入站收件箱（Inbox）、接收游標（Ingest Cursor）、以及未來的出站投遞狀態（Outbox）。

### 2. 檔案系統歸檔邊界排除 (D22 Exclusion)

依 ADR-0022 D22 決策，對話歷史歸檔（Conversation Archive）與多媒體附件（Attachments）仍屬檔案系統資產（Filesystem Artifacts），繼續由磁碟檔案管理，**不屬於** SQLite 運作狀態資料庫之範疇。嚴禁將二進位大型附件或歸檔日誌塞入 SQLite。

### 3. Windows 實機驗證滿足 (D28 & T1 Spike Results)

依 D28「正式實作前必須完成 Windows 實機 Spike」之裁決，專案於 Windows 11 實機（搭載 SSD、Windows Defender 即時防護開啟）完成了 T1 技術 Spike。測試結果如下，**必要技術門檻（V1～V6、V8）全數通過（TECHNICAL GATE = GO）**：

- **V1（Node 24 與 node:sqlite 原生相容性）**：使用官方可攜式 Node.js（v24.21.0，經官方 SHA256 雜湊精確驗證）成功載入 `node:sqlite`（內建 SQLite 版本為 3.53.4），**零 ExperimentalWarning**，且主機全域 Node（v24.18.0）與命令位置完全未受影響。
- **V2（SQLite 基本契約）**：`journal_mode = WAL`、`synchronous = FULL (2)`、`foreign_keys = ON (1)`、`busy_timeout = 5000` 逐項讀回驗證通過；`UNIQUE` 條件防重約束、狀態 `CHECK` 約束、`BEGIN IMMEDIATE`、`COMMIT` 與 `ROLLBACK` 狀態隔離全數驗證通過。
- **V3（NTFS 寫入效能）**：
  - 單筆交易提交延遲（1,000 次）：p50 = 0.9803 ms，p95 = 2.5585 ms（遠低於 20 ms 門檻），p99 = 3.4391 ms。
  - 批量領取 50 筆訊息延遲（100 輪）：p50 = 1.2640 ms，p95 = 3.7847 ms（遠低於 50 ms 門檻），p99 = 7.1767 ms。
- **V4（當機一致性）**：連續執行 200 次強殺測試（200 iterations），每輪均在收到交易開啟（未 COMMIT）之機械標記後立即強殺；重啟後資料庫完整性檢驗全數通過（`integrity_ok = 200/200`），已提交控制列完整保留（200/200），未提交列全數消失（200/200），重複鍵計數為 0。
- **V5（10 分鐘 Defender / 並行鎖定壓力測試）**：在 Windows Defender 防毒即時防護開啟下連續運行 606.02 秒（超過 600 秒要求）；Writer 執行 2,326 次交易，Reader 執行 19,406 次查詢；未復原之 SQLITE_BUSY 為 0，其他鎖定錯誤為 0；`wal_checkpoint(TRUNCATE)` 成功；連線關閉後確認無殘留 handle lock。
- **V6（同動目錄與網路路徑防護偵測）**：OneDrive 個人與商業帳號根目錄精確識別；Desktop 未重定向至 OneDrive；UNC 網路路徑精確阻擋（`NETWORK_FORBIDDEN`）；本機資料夾精確允許（`LOCAL_ALLOWED`）。
- **V8（線上熱備份）**：在主資料庫保持連線開啟狀態下，執行 `VACUUM INTO` 備份成功，備份檔案 `integrity_check = ok` 且邏輯列數（500/500）完全一致。

### 4. 與 ADR-0022 之關係 (Relationship with ADR-0022)

ADR-0022 仍保留為 Channel Gateway 之歷史與總體架構權威（Historical Architecture Authority）。
本 ADR 僅取代（supersedes）ADR-0022 關於 Gateway 運作狀態持久化採用「JSON 快照（JSON snapshot persistence layer）」之實作選型，不修改 ADR-0022 歷史本文。

### 5. 既有 JSON 持久化模組之退役 (Legacy JSON Modules Retirement — TG-MVP-08 / T9)

歷史上三個過渡性 JSON 持久化模組：
- `runtime/channel-gateway/core/durable-state-store.js`
- `runtime/channel-gateway/core/channel-state-recovery.js`
- `runtime/channel-gateway/core/channel-state-persistence.js`

在 T9 執行前曾作為過渡中／凍結資產（TRANSITIONAL / FROZEN）暫留版本庫以供對照。後續經 TG-MVP-08（T9 階段）正式驗證後，上述三個模組與其專屬測試（`durable-state-store.test.js`、`channel-state-recovery.test.js`、`channel-state-persistence.test.js`）已全數自 active 版本庫中正式退役並移除。

- **唯一權威來源**：SQLite / `node:sqlite` 儲存庫（`sqlite-state-repository.js`）為 Channel Gateway 唯一權威運作狀態來源。
- **零相容性表面**：不保留相容性 shim、不建立 deprecated wrapper、不提供 JSON fallback、不抽取或建立新的替代快照模組。
- **歷史脈絡留痕**：歷史架構設計、演進背景與程式碼留痕完整保留於 Git 歷史紀錄與本 ADR 中，不影響 active runtime 潔淨度。
- **共享原語保留**：`shared/atomicFs.js` 屬跨專案共享檔案原子寫入原語，不屬本三個已退役之 Gateway 專屬 JSON 運作模組，本 T9 階段予以保留不予刪除。
- **檔案系統例外維持**：ADR-0022 D22 對話歸檔與 D17 附件之檔案系統儲存邊界維持不變。

### 6. Wave 2H 之處置 (D29 Cancellation)

原定之「Wave 2H: Durable Channel Transition Commit Boundary（基於 JSON 快照的交易提交包裝器）」依 D29 裁決 **正式取消（SUPERSEDED / CANCELLED）**。
禁止新增 `durable-channel-controller.js`。其原定之交易提交邊界目標改由未來 SQLite 交易機制（T7 階段）實現。

### 7. 待決議事項現況 (Pending Decisions: R2 & R3)

> **架構更新宣告**：本節原待決議事項（R2 & R3）已由使用者正式裁決，並由 **ADR-0025（Outbound Delivery Reliability and Loopback Local API Security）** 正式承接與取代（`ADR-0025 supersedes ADR-0023 §7` 對 R2/R3「仍待使用者裁決」之狀態描述）。本處保留歷史決策脈絡，最新權威規範以 ADR-0025 為準。

- **R2（回覆結果不明時的處理 / Reply Result Uncertainty Handling）**：使用者已正式裁決，規範已於 **ADR-0025** 正式落地（`USER DECIDED / CANONICAL ARCHITECTURE LANDED IN ADR-0025 / NOT IMPLEMENTED`）。採能力感知安全重試（Capability-Aware Safe Retry）與持久化 SQLite Outbox；嚴禁無差別盲目重送（NO BLIND RESEND）。
- **R2-3（配送不確定性之維運體驗 / Delivery Uncertainty Notification）**：使用者已正式裁決採 **Option B**，規範已於 **ADR-0025** 正式落地（`USER DECIDED OPTION B / CANONICAL DETAILS IN ADR-0025`）。由 Gateway 持久化 UNCERTAIN 狀態供 Agent 於 IDE 檢視，嚴禁向使用者手機發送干擾推播。
- **R3（本機 API 形式 / Local API Form）**：使用者已正式裁決，規範已於 **ADR-0025** 正式落地（`USER DECIDED / CANONICAL ARCHITECTURE LANDED IN ADR-0025 / NOT IMPLEMENTED`）。採本機迴路 API（Loopback HTTP v1，僅監聽字面值 `127.0.0.1`，具備 HMAC 雙向認證、authenticated hello 握手與同連線會話綁定）；Windows 具名管道（Named Pipe）方案正式延後／未獲選（DEFERRED / NOT SELECTED）。

### 8. 線上驗證備份排程整合與維運策略 (Periodic Verified Backup Integration — TG-MVP-09 / T11-main)

2026-09-23，專案擁有者（使用者 HH）明確核准「同意 TG-MVP-09 修正版裁決」，確立 T11-main 正式線上備份整合規範：

1. **T11A 備份原語不變量 (T11A Primitive Unchanged)**：
   - 既有 `SqliteStateRepository.createVerifiedBackup()` 為全系統唯一備份操作原語。
   - 不改寫 T11A `executeVerifiedBackup(...)` 與驗證核心（包含路徑約束、零覆蓋、`VACUUM INTO` 參數綁定、`integrity_check`、資料表/綱要/版本基準比對、`data_version` 漂移偵測與安全清理）。
   - 不另行建立第二套 SQLite 備份實作。
2. **排程週期與保鮮度判準 (Freshness Threshold & Check Tick)**：
   - **保鮮度門檻（Freshness Threshold）**：固定 24 小時（`86_400_000 ms`），語義為「最近一份合規驗證備份檔案距今是否已逾期」，非進程運行時長。
   - **檢查頻率（Check Tick）**：固定 1 小時（`3_600_000 ms`）。進程啟動時立即執行一次過期檢查，其後每 1 小時 tick 重新評估。禁止使用單一 24h setInterval 取代保鮮度排程語義。
3. **啟動與關閉語義 (Startup & Shutdown Semantics)**：
   - **啟動檢查**：啟動時僅執行保鮮度檢查，不做無條件啟動備份。無合規備份或最新備份年齡 >= 24h 時補做備份；若最新備份年齡 < 24h 則不觸發備份。
   - **關閉語義**：進程關閉（Shutdown）時不執行關閉備份。
4. **耐久保鮮度來源與零綱要擴充 (Durable Freshness Source & Zero Schema Expansion)**：
   - 以 canonical `stateRoot` 目錄下直接子檔案之檔案系統 `mtime` 作為保鮮度判定依據。
   - 僅採納符合 T11A 命名約定之正規非符號連結檔案：`channel-gateway-state.backup-v{N}-{uuid}.sqlite3`。
   - 取所有有效備份檔案中之最大 `mtimeMs`。未來時間戳記（future-dated）或無效 mtime 不得抑制備份，一律忽略。
   - 不新增 `last_backup_at` 資料庫欄位、不升級 Local Config schema（維持 schemaVersion 2）、不建立備份中繼資料表。
5. **並行與重入防護 (Overlap / In-Flight Guard)**：
   - 單一排程器實例最多僅允許一個備份檢查或備份操作執行中（in-flight）。
   - 若發生重入或重疊觸發，直接跳過（skip），不佇列排隊、不並行建立多份備份。
6. **非致命失敗處理 (Non-Fatal Failure Policy)**：
   - 定期檢查或備份失敗時，記錄邊界明確、不含機密之分類診斷日誌，保持 Gateway 運行，不終止進程（no process.exit）、不立即重試、不指數退避。留待下一個正常 1 小時 tick 重新評估嘗試。
7. **過渡期已知風險視窗與硬性守門 (F2 USER-Accepted Temporary Window & Hard Gate)**：
   - 使用者正式採納選項 (b)：TG-MVP-09 備份排程器預設啟用。
   - 在 TG-MVP-09 完成、TG-MVP-09A 尚未完成前，備份檔案會持續產生完整 SQLite 副本，尚無 retention（保留期清理）與 09A 隱私衛生防護。此為正式上線前（pre-go-live）之已知暫時性風險。
   - **硬性守門要求**：`TG-MVP-09A MUST COMPLETE BEFORE ANY REAL TELEGRAM GO-LIVE`。在任何真實 Telegram 上線前，TG-MVP-09A 必須全數完工驗收。
8. **進程與生命週期範圍定性 (Provisional In-Process Runtime Ownership)**：
   - 建立 `BackupScheduler` 與最小過渡期進程內執行擁有者 `BackupRuntimeOwner`（負責 repository open -> scheduler start -> scheduler stop -> repository close 之生命週期配對）。
   - 擁有者純屬進程內整合元件，**不是 daemon、不是作業系統服務定義、不註冊訊號處理器（process.on / SIGINT / SIGTERM）、不決定最終 Gateway 程序生命週期順序、不提供 CLI / PM2 配置**。
   - 嚴格禁止建立第二個背景守護行程（no second daemon）。最終 Gateway 程序生命週期整合權限保留予 TG-MVP-10 / TG-MVP-11。
9. **同步操作特性紀錄 (Synchronous Event-Loop Characteristic)**：
   - `node:sqlite DatabaseSync` 與 `VACUUM INTO` 為同步操作，執行期間可能短暫阻塞 Node 單一事件迴圈（Event Loop）。
   - TG-MVP-09 接受此已知特性（前題為 pre-go-live、資料庫規模小、每日最多一份成功備份）。若未來資料庫規模擴大導致阻塞不可接受，演進方向為 Worker Thread 或等效隔離機制，不在本輪實作。

### 9. 狀態資料庫與備份衛生治理 (State Database & Backup Hygiene — TG-MVP-09A)

2026-09-24，TG-MVP-09A 狀態資料庫與備份清理衛生規範（實作候選中，等待外部審查 / implementation candidate / awaiting External Macro audit），解決 TG-MVP-09 暫留之過渡期無清理與衛生缺口，達成 real Telegram go-live 前之 hard gate：

1. **SQLite stateRoot 位置守衛 (stateRoot Location Guard)**：
   - 延續 ADR-0022 D24 與 ADR-0023 §8，`assertSafeStateRootLocation` 嚴格限制 `stateRoot` 必須為本機目錄。
   - 嚴格禁止系統關鍵路徑（如 Windows、Program Files、System32 等）、Git 版本庫根目錄、網路 UNC 掛載點（包含標準 UNC `\\server\share` 與擴充 UNC `\\?\UNC\...`）、以及 OneDrive / 同步軟體受管目錄。
   - 守衛僅限於 `stateRoot`，不誤判位於 redirected Desktop 之 `archiveRoot`。
2. **單一備份目錄收斂 (Single Verified-Backup Location)**：
   - 備份檔案唯一合法存放路徑為 `stateRoot/backups/` 子目錄。
   - 建立唯一的目錄自動建立例外：僅允許在已通過安全驗證之 canonical `stateRoot` 底下，由 Gateway 自行建立並維護 `backups/` 子目錄（`ensureBackupsDirectory`）；除此以外維持 Zero Directory Auto-Create 原則。
   - 嚴禁於 `stateRoot` 根目錄直接產出備份。
3. **舊版根目錄備份平滑過渡 (Legacy Backup Transition & Migration)**：
   - 啟動與掃描時，自動偵測殘留於 `stateRoot` 根目錄之歷史正規備份檔案（`channel-gateway-state.backup-*.sqlite3`）。
   - 採用原子重新命名（`fs.renameSync`）平滑搬移至 `stateRoot/backups/`，搬移後納入同一衛生保留管理，確保向後相容。
4. **容量保留與最少數量下限 (1,000,000,000 Bytes / Latest-3 Capacity Retention)**：
   - 本機設定檔 Local Config schemaVersion 3 新增 `backup` 區塊（單位為精確十進位位元組 exact decimal bytes，預設 `maxTotalBytes: 1_000_000_000` 即 1,000,000,000 位元組，嚴禁宣告為 1 GiB，`minKeepCount: 3`），維持與 schemaVersion 2 雙向相容。
   - `totalBytes` 嚴格定義為受管正規備份之總位元組數（managed canonical backup bytes），不計入 `backups/` 目錄內之非正規未受管檔案。
   - 實施容量驅動保留（Capacity-Based Retention），不設無條件天數刪除限制（no age limit）。
   - 嚴格保障最少保留最新 3 份合規備份（Floor of 3），即使總容量超出 `maxTotalBytes`，只要備份數 <= `minKeepCount` 絕對不刪除最新 3 份。
5. **決定性清理順序 (Deterministic Cleanup Order)**：
   - 清理時機嚴格限制於「新備份成功驗證寫入後」（cleanup after successful backup），備份失敗時嚴禁刪除任何既有備份。
   - 超額清理依 `mtimeMs` 由舊至新排序；若時間戳相同則以檔名字典順序打破平局（tie-breaker），杜絕非決定性刪除。
6. **剩餘磁碟空間雙倍安全檢查 (Free-Space Safety Check)**：
   - 執行 `createVerifiedBackup` 前，必須檢查備份目標磁碟之剩餘空間（`bavail * bsize`）。
   - 剩餘空間必須至少大於當前資料庫大小之 2 倍（`2 * dbSize`）；若空間不足則安全略過備份，不觸發 SQLite `VACUUM INTO`，記錄 `INSUFFICIENT_FREE_SPACE` 診斷，進程維持正常服務。
7. **備份健康狀態追蹤與原子寫入 (Backup Health State Tracking)**：
   - 備份排程器動態評估備份健康狀態（Health States: `OK` / `WARN` / `ALERT`）：
     - `ALERT`：嚴重狀況，包含最新成功備份超過 48 小時未產生（`NO_SUCCESSFUL_BACKUP_48H`）、連續失敗次數 >= 3（`CONSECUTIVE_BACKUP_FAILURES`）、單一備份超出容量上限（`SINGLE_BACKUP_EXCEEDS_CAPACITY`）、磁碟剩餘空間不足（`INSUFFICIENT_FREE_SPACE`）、空間檢查失敗（`FREE_SPACE_CHECK_FAILED`）、備份目錄無法存取（`BACKUP_DIRECTORY_UNAVAILABLE`）、或備份目錄清點存取失敗（`BACKUP_INVENTORY_UNAVAILABLE`）。
     - `WARN`：非致命警告，包含保留下限容量衝突（`MIN_KEEP_CAPACITY_CONFLICT`）、備份刪除失敗（`BACKUP_DELETE_FAILED`）、非正規檔案存在（`UNKNOWN_BACKUP_DIRECTORY_ENTRY`）、歷史備份衝突（`LEGACY_BACKUP_COLLISION`）、歷史備份遷移失敗（`LEGACY_BACKUP_MIGRATION_FAILED`）。
     - `OK`：所有檢查正常且無任何警報。
   - 健康狀態快照以非敏感格式寫入 `stateRoot/backup-health.json`（非 `stateRoot/backups/` 子目錄內），寫入嚴格透過 Channel Gateway 專屬 task-local bounded atomic JSON writer 確保原子性與抗當機損毀；不採用 `shared/atomicFs.js`（因 `shared/atomicFs.js` 現有診斷可能反射目標路徑或原始錯誤，TG-MVP-09A 維持 `shared/atomicFs.js` 零修改）。
8. **隱私與機敏資訊安全防護 (Minimal Privacy Protection)**：
   - 備份健康狀態檔案（`backup-health.json`）與所有排程日誌嚴格遵循隱私防護邊界：絕對不包含任何本機絕對路徑、資料庫完整路徑、原始例外訊息（Raw Error Message）、Token、金鑰或訊息內容。
   - 診斷日誌僅輸出受控枚舉名稱（如 `INSUFFICIENT_FREE_SPACE`、`BACKUP_DIRECTORY_UNAVAILABLE`、`BACKUP_INVENTORY_UNAVAILABLE`、`DIR_CREATE_FAILED`、`ERROR_CODE`）。
9. **SQLite 檔案 Git 忽略防護 (SQLite Gitignore Protection)**：
   - `.gitignore` 正式收錄 `*.sqlite3`、`*.sqlite3-wal`、`*.sqlite3-shm`，杜絕執行期資料庫或備份檔案意外進入版本庫。
   - CI 設有 negative canary 確保追蹤原始碼與測試不被誤擋。
10. **無應用層備份加密（BitLocker 使用者責任）**：
    - TG-MVP-09A 備份維持 SQLite 原生資料格式，不引入自製應用層加密（no application-level encryption in 09A）。
    - 磁碟靜態資料加密（Encryption at Rest）明確定義為使用者作業系統層級責任（USER_RESPONSIBILITY BitLocker on Windows）。
11. **Node.js 內建 node:sqlite 未來升級監控點 (node:sqlite Future-Upgrade Watchpoint)**：
12. **SQLite Schema v5 演進（TG-MVP-10 / M7 / M8）**：
    - `ingest_cursor` 表格升級至 schema version 5，新增 `updated_at_ms INTEGER NOT NULL CHECK(updated_at_ms >= 0)`。
    - Migration 5 在既有 v4 升級時自動建立 v4 備份，並以 migration-time timestamp 初始化既有 cursor 作為保守寬限期基準。
    - 提供 `getIngestCursorState(accountId)` 與 `resetIngestCursorForTransportRebase({ accountId, expectedCursorValue, expectedUpdatedAtMs })` 精確狀態條件重置原語。

13. **2026-09-24 主機標準執行環境修復與取代宣告（Current Host Canonical Runtime Remediation）**：
    - 歷史事實保留：2026-09-17 T1 Spike 期間，主機全域 Node 為 v24.18.0，可攜式驗證 Node 為 v24.21.0。此歷史證據維持不變。
    - 2026-09-24 修復現況：
      - USER 已手動安裝標準 Node.js v24.21.0 x64（`C:\Program Files\nodejs\node.exe`）。
      - 當前主機全域 Node：`v24.21.0`，完全符合專案 `.nvmrc`（24.21.0）。
      - `npm.cmd`：`11.19.0`。
      - `node:sqlite`：`DatabaseSync` 煙霧測試 PASS，零 `ExperimentalWarning`。
      - 標準原語：`fetch`、`AbortController`、`AbortSignal.timeout` 全數原生可用。
      - PowerShell 執行原則：`npm.ps1` 受現行 ExecutionPolicy 限制封鎖；Windows 本機核准使用 `npm.cmd` 適配器，**未變更且未削弱** 系統 ExecutionPolicy。
      - 安裝檔雜湊／Authenticode：`NOT_REPO_VERIFIED`（因由 USER 手動安裝，安裝檔來源未經版本庫工具鏈捕獲）。
      - `.nvmrc` 維持權威：`24.21.0`。

## Consequences

1. **治理分層明確化**：本決策確立了持久化技術路線的重大轉變。相關規則同步落地於 `runtime/channel-gateway/AGENTS.md`，根目錄 `AGENTS.md` 僅保留通用的目錄範圍規則擴充，維持漸進式揭露。
2. **Node.js 版本依賴升級**：`node:sqlite` 要求 Node.js v22.5.0+（正式免 flag 需 v22.x 晚期或 v24.x）。後續必須透過 T3 階段落實版本釘選（`.nvmrc`、`package.json` engines、CI 環境配置與 Windows CI 驗證），方可開展正式程式碼實作。
3. **已知風險與緩解**：
   - **node:sqlite 成熟度**：`node:sqlite` 雖已進入 Node.js 核心且無 experimental warning，仍需透過端到端測試持續觀察。
   - **同步 API 對 Event Loop 之影響**：目前 `DatabaseSync` 為同步呼叫，在 SQLite WAL 模式下單次寫入約 1～3 ms，對 Gateway 預期負載（數筆/秒）影響極低，但實作時需注意避免在單一交易中執行耗時之外部操作。線上備份期間 VACUUM INTO 亦為同步操作，在小資料庫下為數十毫秒級，TG-MVP-09 接受該已知特性，若未來擴展則評估 Worker Thread 隔離。
   - **防毒軟體與檔案鎖定**：已由 V5（10 分鐘測試）證實 Defender 即時防護下無鎖定異常，未來上線需保持此項健全性監控。
   - **路徑防護**：強制在資料庫連線前執行路徑守衛，杜絕在同步目錄或網路掛載點建立 SQLite 資料庫。


