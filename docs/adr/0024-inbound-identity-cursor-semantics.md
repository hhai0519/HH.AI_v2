# ADR-0024: Inbound Event Identity and Cursor Semantics

- Status: Accepted
- Date: 2026-09-18

## Context

在 Channel Gateway 架構（ADR-0022）與 SQLite 運作狀態儲存庫（ADR-0023）推進至 Phase 2 時，發現既有狀態綱要（Schema v3）與入站攝取邏輯存在以下關鍵架構缺口（C1、C2、C3 與 F1）：

1. **事件身份與訊息身份混淆（C3）**：現行 `inbox` 僅以 `(account_id, platform_msg_id)` 作為去重鍵。然而不同傳輸事件（例如新訊息、訊息編輯、訊息收回、重新配送）可能指向同一個平台訊息 ID（`platform_msg_id`），若將 `platform_msg_id` 兼作事件去重鍵，會導致編輯（EDIT）或收回（UNSEND）事件被誤判為重複訊息而丟棄。
2. **重複路徑游標行為未決（C1）**：在目前 `ingestMessage()` 實作中，重複進線（Duplicate path）保持嚴格零突變（Zero-Mutation）且不推進游標。但對於長輪詢（Long Polling）適配器而言，若無法識別重複事件與更新訊息，可能導致游標卡滯或事件漏失。
3. **無條件覆寫游標缺陷（C2）**：現行 `ingest_cursor` 的 upsert 邏輯對 `cursor_value` 採無條件覆寫（`ON CONFLICT(account_id) DO UPDATE SET cursor_value = excluded.cursor_value`），通用資料庫層缺乏游標比較器（Comparator），可能接受較小或亂序之游標數值而引發游標倒退。
4. **跨平台通訊契約相異**：Telegram 採長輪詢（getUpdates）拉取模型，具有數值型 `update_id` 與 offset 確認機制；LINE 採 Webhook 推播模型，具有 `webhookEventId`、重送旗標（`isRedelivery`）且完全不具備傳輸游標能力。兩者傳輸語意截然不同，無法套用單一抽象。
5. **回覆授權鍵不一致（F1）**：`validateReplyAuthorization()` 查詢原始訊息時僅以 `channel_id + platform_msg_id` 查找，未將 `account_id` 納入 SQL 過濾條件，與多帳號複合鍵邊界不符。

本 ADR 旨在確立通用入站事件身份模型、Telegram 與 LINE 之平台規範，並正式判定 C3、C1、C2 架構處置。

---

## Decision

### 1. 核心實體模型分離 (Core Entity Separation)

本架構明確區分以下四個核心概念，嚴禁混為單一欄位：

1. **`account_id`（帳號邊界）**：
   - HH.AI 內部對已配置之平台機器人帳號（Bot Account）的穩定、非機敏識別碼。
   - 所有入站事件、收件箱、游標與出站回覆之命名空間邊界（Namespace Boundary）。
   - 金鑰、Token 與 Secret 絕不作為身分鍵值。
2. **`platform_event_id`（平台事件身分）**：
   - 平台傳送之單一「事件／更新」自身的唯一識別碼。
   - 用於傳輸層冪等去重（Delivery Idempotency）、重送去重（Redelivery Deduplication）、重放防護（Replay Protection）。
   - **正規事件去重鍵（Canonical Event Deduplication Key）**：`(account_id, platform_event_id)`。
3. **`platform_msg_id`（邏輯訊息身分）**：
   - 聊天平台中的「邏輯訊息」識別碼。
   - 用於原始訊息檢索、編輯關聯（Edit Correlation）、收回關聯（Unsend Correlation）、回覆授權（Reply Authorization）與對話歸檔。
   - 多個不同事件（如新訊息與後續編輯）可合法指向相同之 `platform_msg_id`。相同 `platform_msg_id` 絕不等於重複事件（Same platform_msg_id != duplicate event）。
4. **`cursor_value`（傳輸游標狀態）**：
   - 僅代表傳輸層拉取／攝取之延續標記（Continuation State）。
   - 絕不代表訊息身分、事件身分、時間戳記或跨平台序列。
   - 游標能力依適配器平台特性定義；對不具備游標之平台（如 LINE）禁止偽造游標。

---

### 2. 概念入站事件封套 (Conceptual Inbound Event Envelope)

定義通用概念入站封套結構（架構契約，非本批程式碼結構）：

```text
InboundEventEnvelope {
  platform: 'telegram' | 'line',
  account_id: string,
  channel_id: string,
  event_type: 'MESSAGE' | 'EDIT' | 'UNSEND' | 'IGNORED',
  platform_event_id: string,
  platform_msg_id: string | null,
  content: string | null,
  cursor_value: string | null,
  occurred_at: number | null,
  redelivery_indicator: boolean
}
```

---

### 3. Telegram 身分與游標契約 (Telegram Contract)

Telegram 通道（TG-MVP）採用長輪詢（Long Polling / `getUpdates`）模型：

1. **事件身分（Event Identity）**：
   - `platform_event_id = String(update.update_id)`（十進位字串）。
   - 相同 `update_id` 再次進線視為重複事件（Duplicate Event）。
2. **邏輯訊息身分（Logical Message Identity）**：
   - Telegram Bot API 之 `message_id` 僅在該 chat 內唯一，不同 chat 可能出現相同之 raw `message_id`。
   - 因此 Telegram 之 `platform_msg_id` 必須結合 chat 身分，採確定性字串格式：`tg:<chat_id>:<message_id>`。
   - 保證相同 chat 相同 message_id 指向同邏輯訊息，不同 chat 互不碰撞。
3. **訊息編輯（Edit Semantics）**：
   - `edited_message` 為新 Update，具有新之 `update_id`（新 `platform_event_id`），但指向既有之 `platform_msg_id`。
   - 編輯事件不得因 `platform_msg_id` 已存在而被視為重複事件。
4. **訊息收回／刪除（Unsend Semantics）**：
   - **官方事實**：現行標準 Telegram Bot API 之 Update 契約中，**不存在**一般聊天訊息之收回／刪除事件（`deleted_business_messages` 僅限商業帳號）。
   - **契約判定**：`TELEGRAM_GENERIC_UNSEND = NOT OBSERVABLE IN CURRENT STANDARD BOT API CONTRACT`。
   - 本架構嚴禁虛構不存在之 Telegram 一般收回輪詢機制；未來若引入商業帳號再行擴充。
5. **游標語意（Cursor Semantics）**：
   - `cursor_value = String(update_id + 1)`（代表下一次 `getUpdates` 應使用之 offset）。
   - **持久化確認邊界（Confirmation Boundary）**：Telegram 在收到的 offset 大於某 `update_id` 時會將該 update 標記為確認並從伺服器佇列移除。因此游標推進必須嚴格置於事件持久化完成之後（Cursor advance must follow durable event outcome）。
   - **游標比較器（Comparator）**：
     - `candidate > stored`：推進游標（ADVANCE）。
     - `candidate == stored`：無操作（NOOP）。
     - `candidate < stored`：游標倒退，拒絕並中斷（REGRESSION / FAIL-CLOSED）。
   - **一週隨機 update_id 官方限制**：官方契約註明若超過一週無新 update，下一個 identifier 可能隨機指定而非單調遞增。通用資料庫層維持嚴格防倒退；跨週重置／rebase 屬 Telegram 適配器職責，排定於 TG-MVP-10 實作中加入顯式重置機制，不假設永久單調。
6. **不支援事件處理（Unsupported Updates）**：
   - 對於非文字之 Update，明確分類為 `IGNORED`，持久化記錄終態處置後始得推進游標，杜絕輪詢毒藥迴圈（Poison Loop）。

---

### 4. LINE 身分與游標契約 (LINE Contract)

LINE 通道採用 Webhook 模型：

1. **事件身分（Event Identity）**：
   - `platform_event_id = event.webhookEventId`（全域唯一事件識別碼）。
   - 正規去重鍵：`(account_id, webhookEventId)`。
   - `deliveryContext.isRedelivery` 僅為中繼資訊，不得取代事件身分。重送事件具有相同之 `webhookEventId`，依事件去重處理。
2. **邏輯訊息身分（Logical Message Identity）**：
   - 訊息事件之 `platform_msg_id = String(event.message.id)`，由 `account_id` 隔絕。
   - 編輯事件具有新之 `webhookEventId`，但 `message.id` 與原訊息相同，不得誤判為重複事件。
3. **訊息收回（Unsend Semantics）**：
   - 收回事件具有獨立之 `webhookEventId`，其目標訊息由 `event.unsend.messageId` 識別。
   - 經簽章驗證之收回事件，實作必須尊重使用者收回意圖：被收回訊息之原始內文（content）必須變更為無法再被 Agent、收件箱、歸檔日誌或下游功能正常檢視與顯示。
   - 未來實作僅允許保留極小非內文墓碑標記（Minimal non-content tombstone）以維護狀態一致性與去重審計。
4. **游標語意（Cursor Semantics）**：
   - LINE Webhook 無傳輸拉取游標，故 **LINE cursor capability = NONE**。
   - LINE 攝取之 `cursor_value = NOT APPLICABLE`（存儲可為 null 或不要求游標）。
   - 嚴禁以 `timestamp`、`message.id` 或 `webhookEventId` 偽造高水位游標。
   - 官方契約明載重送可能導致接收順序與發生順序不同，系統不得因 timestamp 較小而丟棄有效事件。

---

### 5. C1 / C2 / C3 架構裁決與處置

1. **C3（事件身分與游標權威定義）**：
   - **裁決**：`RESOLVED BY ADR-0024`。Telegram 與 LINE 之身分、編輯、收回與游標規範已正式確立。
2. **C1（重複路徑游標行為）**：
   - **裁決**：`RESOLVED BY ARCHITECTURE`。真正重複事件為 `(account_id, platform_event_id)` 重複，此時維持冪等無操作（Idempotent No-Op）且零游標變更。因編輯／收回已具備獨立 `platform_event_id`，原訊息 ID 重複不再阻擋游標推進。
   - **執行狀態**：程式碼實作排定於 `TG-MVP-05` 進行。
3. **C2（游標無條件覆寫缺口）**：
   - **裁決**：`RESOLVED BY ARCHITECTURE`。Telegram 游標必須具備比較器保護防範倒退；LINE 適配器則不要求游標。
   - **執行狀態**：程式碼實作排定於 `TG-MVP-05` 進行。

---

### 6. 現行綱要與後續邊界 (Schema Baseline & Follow-Up Routing)

1. **歷史基準與動態狀態（Historical Baseline vs Runtime State）**：ADR adoption 時之 runtime baseline 為 `schema v3`（`inbox` 具備 `UNIQUE(account_id, platform_msg_id)`，`ingest_cursor` 無條件覆寫）。該 baseline 不是永久 schema-version pin，current runtime implementation state 由 repository code 與 TASKBOARD 判定。
2. **執行層修復（TG-MVP-05 Runtime Landing）**：`TG-MVP-05` 作為事件身分帳本（event identity ledger）、游標比較器（cursor comparator）、LINE 無游標存儲相容（LINE no-cursor repository compatibility）與不支援事件終態處置（IGNORED durable terminal handling）之 runtime landing。
3. **EDIT / UNSEND 業務邊界（LINE-03 Routing）**：`TG-MVP-05` 僅建立 event identity storage foundation；LINE platform-specific 之 EDIT / UNSEND application effect、重送行為與 Webhook 整合正式由後續 `LINE-03` 落地，且 `LINE-03` 依賴 `TG-MVP-05`。本架構不偽稱 `TG-MVP-05` 已完成 LINE adapter。
4. **回覆授權修復（F1 Timeless Routing）**：F1（`validateReplyAuthorization()` 查找邏輯修復）為獨立 implementation slice，已由 `TG-MVP-04` 處理完畢；current lifecycle evidence 以 TASKBOARD 與 AUDIT-LOG 為準。
5. **明確非目標（Explicit Non-Goals）**：本 ADR 本身不包含任何 SQLite 遷移、程式碼修改、適配器實作、F1 修復、R2 Outbox、R3 Local API 或密鑰配置。

---

### 7. 平台官方查證事實 (Independently Verified Platform Facts)

以下外部平台事實由 External Macro Auditor 於 2026-09-18 獨立查證確立：

- **Telegram Bot API**：
  - `update_id` 為 Update 之唯一識別碼，常態下循序遞增。
  - 若超過一週無新 update，下一個 identifier 可能隨機挑選。
  - `getUpdates` 之 offset 大於某 `update_id` 時，Telegram 伺服器即將該 update 視為確認。
  - `edited_message` 為獨立 Update 形式。
  - `message_id` 僅在 chat 內唯一。
  - 標準 Bot API 更新中無一般訊息刪除／收回事件。
- **LINE Messaging API**：
  - `webhookEventId` 為 Webhook 事件之全域唯一識別碼。
  - 同事件重送時 `webhookEventId` 維持相同，`deliveryContext.isRedelivery` 為 true。
  - Webhook 重送可能使到達順序與發生時間不一致。
  - `timestamp` 為事件發生時間而非重送時間。
  - 編輯事件與原訊息具相同之 `message.id`。
  - 收回事件由 `unsend.messageId` 指向原訊息，官方建議尊重收回意圖使內文不可見。

---

---

### 8. TG-MVP-10 Telegram 落地語意與游標重置機制 (TG-MVP-10 Telegram Inbound & Cursor Semantics)

在 TG-MVP-10 正式落地 Telegram 測試 Bot 入站適配器與 SQLite v5 游標管理機制：

1. **Telegram 身分識別規格 (M9)**：
   - `TELEGRAM_CHANNEL_ID = 'telegram'`
   - `platform_event_id = String(update.update_id)`，必須為安全整數且 >= 0。
   - `platform_msg_id = tg:<chat_id>:<message_id>`，以複合鍵杜絕跨聊天室 message_id 碰撞。
   - 下一游標值：`cursor_value = String(update_id + 1)`。
2. **編輯入站語意 (`ingestEdit` — M6)**：
   - 真正重複事件：`(account_id, platform_event_id)` 相同且為 EDIT 類型，保持零突變（Zero Mutation）。
   - 事件衝突：相同 event_id 但型態或通道不一致，觸發 `EVENT_IDENTITY_CONFLICT` 失敗關閉並完整 rollback。
   - 目標訊息存在：更新 `inbox.content`，保留現有 status 與領取狀態，寫入 `inbound_event`（EDIT）並原子推進游標。
   - 目標訊息不存在：**不偽造新訊息、不寫入 inbox**，寫入耐久 `inbound_event`（EDIT）並推進游標，回傳 `applied = false, reason = 'EDIT_TARGET_NOT_FOUND'`，防止毒藥重送迴圈。
3. **跨週隨機 Update ID 重置機制 (Week-Rebase — M8)**：
   - Telegram 官方更新於伺服器保留 <= 24 小時，且超過一週無更新時下一 `update_id` 可能隨機重置。
   - 固化常數 `TELEGRAM_WEEK_REBASE_MS = 604_800_000`（7 天）。
   - 每次 `getUpdates` 請求前檢驗游標存儲時間戳：若 `nowMs - updatedAtMs >= 604_800_000`，透過 `resetIngestCursorForTransportRebase` 執行**精確條件刪除**（存儲值與時間戳必須完全相符，不接受萬用字元），隨後省略 `offset` 參數重新拉取。
   - 嚴禁負數 offset、嚴禁任意倒退游標、嚴禁 `drop_pending_updates`。

## Consequences

1. **架構健全性**：徹底解耦「傳輸事件冪等（Event Deduplication）」與「邏輯訊息關聯（Message Correlation）」，為後續 Telegram 與 LINE 適配器奠定確定性基礎。
2. **解決核心缺口**：正式裁決 C3、C1 與 C2，打通 TG-MVP-05 執行層修復之單一依據。
3. **強制驗收金絲雀（Mandatory Architecture Canaries）**：
   - **CANARY A**：Telegram 同一 `update_id` 重送僅產生單次事件效果。
   - **CANARY B**：Telegram 同一訊息被 `edited_message` 更新，新 `update_id` 視為 EDIT 事件，不被訊息去重吞掉。
   - **CANARY C**：Telegram 不同 chat 出現相同 raw `message_id`，解析為不同邏輯訊息。
   - **CANARY D**：Telegram 游標候選值小於目前存儲值時，嚴禁無條件覆寫。
   - **CANARY E**：Telegram 不支援事件經持久化 IGNORE 後始得推進 offset，不產生毒藥迴圈。
   - **CANARY F**：LINE 相同 `webhookEventId` 重送判定為冪等重複事件。
   - **CANARY G**：LINE 編輯事件（新 `webhookEventId` + 相同 `message.id`）視為 EDIT 而非重複。
   - **CANARY H**：LINE 收回事件使目標訊息內文不可正常檢視或取用。
   - **CANARY I**：LINE 亂序重送不得因 timestamp 較小而拋棄合法事件。
   - **CANARY J**：LINE 適配器不被強迫產生虛假 `cursor_value`。

