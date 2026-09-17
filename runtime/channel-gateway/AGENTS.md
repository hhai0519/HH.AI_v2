# Channel Gateway Scoped Rules

本文件定義在 `runtime/channel-gateway/` 目錄及其子目錄下工作時必須遵守之範圍受限規則（Directory-Scoped Rules）。
架構決策脈絡見 `docs/adr/0022-channel-gateway-architecture.md` 與 `docs/adr/0023-channel-gateway-state-store-sqlite.md`。

---

## 1. 唯一權威運作狀態來源 (Operational State Source)

- 所有 Channel Gateway 之通道控制狀態（ChannelControl）、入站收件箱（Inbox）、接收游標（Ingest Cursor）與未來出站狀態（Outbox），唯一權威持久化路線為 **SQLite / `node:sqlite`**（ADR-0023 D27）。
- 嚴禁新增任何新的 JSON 運作狀態寫入器或快照儲存邏輯。
- 現存之 JSON 持久化模組（`durable-state-store.js`、`channel-state-recovery.js`、`channel-state-persistence.js`）為過渡中／凍結資產（Transitional / Frozen），除相容性驗證或退役清理外，不得擴充功能。

## 2. SQLite PRAGMA 契約 (PRAGMA Contract)

未來 SQLite 儲存庫（Repository）連線初始化時，必須設定並讀回驗證以下 PRAGMA：
- `PRAGMA journal_mode = WAL;`（讀回必須為 `wal`）
- `PRAGMA synchronous = FULL;`（讀回必須為 `2`）
- `PRAGMA foreign_keys = ON;`（讀回必須為 `1`）
- `PRAGMA busy_timeout = <repo-defined value>;`

啟動時若任一項讀回值不符，必須 **FAIL-CLOSED** 立即中止啟動。
具體之 `busy_timeout` 數值由 T6 階段之實作規格決定（T1 Spike 實測 5000ms 僅為實驗證據，非永久魔法數值）。

## 3. 交易邊界強制 (Transaction Boundary)

- 通道控制接管（takeover）、訊息領取（claim）、狀態變更等任何具備狀態轉移副作用之操作，必須在 SQLite 交易 **COMMIT 成功後**，始得將 success 結果回傳給呼叫端。
- 在 SQLite 交易邊界機制（T7 階段）正式建立前，嚴禁重啟或復活舊 Wave 2H 基於 JSON 快照的協調器。

## 4. 冪等攝取與游標原子性 (Idempotent Ingest & Cursor Atomicity)

- 收件防重以 `UNIQUE(account_id, platform_msg_id)` 為硬性約束。
- 訊息攝取與接收游標（Ingest Cursor）推進必須置於同一 SQLite 交易內完成，杜絕長輪詢重啟重複拉取或斷線漏訊。
- 帳號切換（Account Switch）與 Bot 身分切換之游標與去重，亦必須納入交易邊界處理。

## 5. SQL 查詢安全 (SQL Safety)

- 所有資料庫查詢與更新必須一律使用 **Prepared Statements 與 Parameter Binding**。
- 嚴禁使用字串拼接（String Concatenation）或樣板字串（Template Literals）組裝 SQL 數值。

## 6. 資料庫綱要遷移 (Schema Migration)

- 資料庫綱要必須版本化（Versioned Schema，如 `schema_version` 表格）。
- 綱要變更僅允許向前遷移（Forward-only migrations）。
- 執行任何綱要遷移前，必須具備經驗證之備份。

## 7. 備份機制 (Backup)

- 運行中的 SQLite 資料庫嚴禁使用作業系統檔案複製（`fs.copyFile` / `Copy-Item`）作為標準備份手段。
- 備份必須使用 SQLite 原生支援之 **`VACUUM INTO`** 或經嚴格驗證之線上備份 API。

## 8. 資料庫存放位置防護 (Database Location Guard)

- 資料庫存放路徑僅能來自 ADR-0022 D24 所定之外部本機設定（Repo-External Local Config）。
- 嚴禁將資料庫建立於 OneDrive、同步資料夾、或 UNC 網路掛載路徑上。
- 路徑保護守衛（Path Guard）必須由程式機械式強制檢驗（如偵測 UNC 路徑與已知同步根目錄）。

## 9. Node.js 版本前置條件 (Node Prerequisite)

- 在 T3 階段（版本釘選與 CI 支援）完成前，SQLite 正式實作受 Node.js 版本與 Windows CI 前置條件阻擋，不得擅自新增 production 程式碼。
- T3 落地後，版本庫釘選之 Node 版本（`.nvmrc`、`package.json` engines、CI 設定）即為權威依據。

## 10. 資料保留與清理邊界 (Retention & Cleanup)

- 訊息保留期過期清理必須與 ADR-0022 D22 之對話歸檔完成契約（Archive Completion Contract）協調，嚴禁在確認歸檔成功前先行刪除資料庫狀態。

## 11. 機敏資訊防護 (Secrets Protection)

- SQLite 資料庫嚴禁儲存 Telegram Token、LINE Secret、GitHub Credential 或任何明文密碼與私鑰。
- 帳號非機敏後設資料與金鑰儲存必須嚴格遵循 ADR-0022 D26 及未來外部憑證契約。

## 12. 檔案系統歸檔例外 (Filesystem Exception)

- ADR-0022 D22 之對話歷史歸檔（Conversation Archive）與 D17 媒體附件（Attachments）為檔案系統資產，**不屬於** SQLite 運作狀態。
- 嚴禁因採用 SQLite 而將二進位大型附件或對話歸檔日誌塞入資料庫。
