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

## Consequences

1. **治理分層明確化**：本決策確立了持久化技術路線的重大轉變。相關規則同步落地於 `runtime/channel-gateway/AGENTS.md`，根目錄 `AGENTS.md` 僅保留通用的目錄範圍規則擴充，維持漸進式揭露。
2. **Node.js 版本依賴升級**：`node:sqlite` 要求 Node.js v22.5.0+（正式免 flag 需 v22.x 晚期或 v24.x）。後續必須透過 T3 階段落實版本釘選（`.nvmrc`、`package.json` engines、CI 環境配置與 Windows CI 驗證），方可開展正式程式碼實作。
3. **已知風險與緩解**：
   - **node:sqlite 成熟度**：`node:sqlite` 雖已進入 Node.js 核心且無 experimental warning，仍需透過端到端測試持續觀察。
   - **同步 API 對 Event Loop 之影響**：目前 `DatabaseSync` 為同步呼叫，在 SQLite WAL 模式下單次寫入約 1～3 ms，對 Gateway 預期負載（數筆/秒）影響極低，但實作時需注意避免在單一交易中執行耗時之外部操作。
   - **防毒軟體與檔案鎖定**：已由 V5（10 分鐘測試）證實 Defender 即時防護下無鎖定異常，未來上線需保持此項健全性監控。
   - **路徑防護**：強制在資料庫連線前執行路徑守衛，杜絕在同步目錄或網路掛載點建立 SQLite 資料庫。
