# ADR-0025: Outbound Delivery Reliability and Loopback Local API Security

- Status: Accepted
- Date: 2026-09-18

## Context

在 Channel Gateway 架構（ADR-0022）、SQLite 運作狀態儲存庫（ADR-0023）與入站事件身分規範（ADR-0024）確立後，Channel Gateway 的出站配送（Outbound Delivery）可靠性與本機服務通訊（Local API）安全成為核心架構瓶頸：

1. **出站重試盲目性風險（R2）**：分散式網路環境下，出站請求逾時或連線中斷可能發生於「請求未送達伺服器」或「伺服器已接受處理但回應未回傳」等不同傳輸階段。若在結果未知（Unknown outcome）時進行無差別盲目重送（Blind Resend），將對使用者造成嚴重重複扣款、重複發訊或重複操作等破壞性副作用。
2. **通訊平台能力差異**：Telegram HTTP Bot API 的 `sendMessage` 端點未提供客戶端指定之冪等鍵（Idempotency Key）參數；而 LINE Messaging API 僅在特定端點（push、multicast、narrowcast、broadcast）支援 `X-Line-Retry-Key`，且對回覆端點（reply message）帶入該標頭會直接回傳 HTTP 400 錯誤。跨平台出站重試無法依賴單一抽象假設。
3. **配送不確定性之維運體驗（R2-3）**：當出站結果無法安全判定時，若向使用者手機反覆推播配送不確定警報，將嚴重干擾正常通訊；使用者已正式裁決採 Option B（持久化於 Gateway，供 Agent 於 IDE 檢視，手機不推播）。
4. **本機 API 形式與安全邊界（R3）**：Gateway 與本地 Agent 需具備低延遲、高安全之通訊通道。Windows 具名管道（Named Pipe）在權限控制與防搶佔上尚存實測盲區；而傳統本機 HTTP 伺服器若缺乏嚴格認證與防護，易受惡意網頁跨來源請求（CORS/Origin）、DNS 重新綁定（DNS Rebinding）或同機未授權行程之偽造攻擊。

本 ADR 旨在正式確立出站能力感知安全重試（R2）、持久化 SQLite Outbox、配送不確定處置（R2-3）與本機迴路 API（R3 Loopback HTTP v1）之規範性架構契約。

---

## Decision

### 1. R2 核心決策：能力感知安全重試與持久化 SQLite Outbox

本架構正式採行 **能力感知安全重試（Capability-Aware Safe Retry）** 搭配 **持久化 SQLite Outbox（Durable SQLite Outbox）**：

- **核心不變式：嚴禁盲目重送（NO BLIND RESEND）**。
- 請求是否允許自動重試，絕不單憑「發生錯誤」決定，而必須依據以下六大維度進行機械判定：
  1. 通訊平台（Platform：Telegram vs. LINE）；
  2. 目標端點（Target Endpoint：如 LINE push vs. LINE reply vs. Telegram sendMessage）；
  3. 傳輸階段（Transport Phase：NOT_SENT vs. MAY_HAVE_BEEN_SENT）；
  4. 平台顯式回應（Explicit Platform Response：如 HTTP 狀態碼、錯誤原因或 flood control 提示）；
  5. 端點冪等能力（Endpoint Idempotency Capability：是否具備官方支援之客戶端去重憑證）；
  6. 持久化重試識別碼（Persisted Retry Identity：是否已在發送前持久化重試鍵）。

---

### 2. 持久化 Outbox 擁有權契約 (Durable Outbox Ownership)

1. **擁有權轉移**：一旦出站指令成功提交（COMMIT）至持久化 SQLite Outbox 資料表，Channel Gateway 即正式取得該訊息之配送擁有權（Delivery Ownership）。
2. **生命週期隔離**：Outbox 指令一旦持久化，其生命週期完全獨立於呼叫端 Agent。後續發生之 Agent 連線中斷、Agent 會話切換、通道接管（Takeover）、Fencing Token 遞增或 IDE 重啟，**均不得**使已 COMMIT 的 Outbox 指令消失、遺失或被靜默取消。
3. **權限邊界**：Fencing Token 與 Holder 授權僅用於檢驗「是否允許建立新的出站指令」；嚴禁溯及既往取消已經合法 COMMIT 的出站指令。
4. **實作排定**：Outbox 資料庫表結構、工作者與排程實作排定於 `TG-MVP-12`。

---

### 3. 內部請求冪等性與正規載荷雜湊 (Internal Request Idempotency)

為保障 Agent 重送出站指令時之內部冪等性，本架構建立與外部平台重試完全分層之內部機制：

1. **用戶端請求識別碼（`client_request_id`）**：每個透過 Local API 送出之出站請求必須包含由呼叫端提供之唯一、穩定的 `client_request_id`。
2. **正規載荷雜湊（Canonical Payload Hash）**：
   - 採 SHA-256 演算法計算出站載荷之確定性雜湊值。
   - 雜湊範圍必須包含所有與配送相關之核心欄位：協定版本、平台、account_id、端點操作、收件人身分、邏輯回覆目標、訊息類型與完整出站內文。
   - 雜湊範圍嚴格排除暫態傳輸與認證欄位：HMAC 標頭、簽章、時間戳記、nonce、重試排程時間或平台伺服器產生的暫態識別碼。
3. **衝突與冪等判定契約**：
   - 相同 `client_request_id` + 相同載荷雜湊值：判定為冪等重放（Idempotent Replay），回傳既有指令之身分與狀態，不建立第二筆 Outbox 指令。
   - 相同 `client_request_id` + 不同載荷雜湊值：判定為嚴重衝突（FAIL CLOSED / IDEMPOTENCY_CONFLICT），拒絕處理且絕不覆寫既有指令。
4. **分層獨立性**：內部 `client_request_id` 與平台外部重試鍵（如 LINE retry key）分屬不同系統層級，嚴禁混為同一識別碼。

---

### 4. 最小 Outbox 狀態模型 (Minimal Outbox State Model)

Outbox 核心狀態模型僅定義以下五個概念狀態（Conceptual States）：

1. **`QUEUED`**：指令已持久化寫入資料庫，等待工作者進行傳輸嘗試。
2. **`IN_FLIGHT`**：出站工作者已取出指令並開始進行傳輸嘗試，尚未確認最終結果。
3. **`ACCEPTED_BY_PLATFORM`**：平台 API 已明確回傳成功接受該請求（如 HTTP 2xx 或 LINE 409 同 key 已接受）。此狀態代表平台端已受理，絕不代表收件人終端已實際送達或已讀。
4. **`UNCERTAIN`**：請求傳輸結果無法安全確定，且自動重試存在引發重複操作之風險。在此狀態下，嚴禁任何自動盲目重送。
5. **`FAILED_TERMINAL`**：不可復原之終態失敗（如認證失敗、收件人不存在、參數違法或非重試區間之 4xx 錯誤），不再進行重試。

> 說明：重試排程參數（如 `next_attempt_at`、`attempt_count`）作為資料表欄位屬性維護，不另立額外狀態列舉。

---

### 5. IN_FLIGHT 當機復原契約 (IN_FLIGHT Crash Recovery Contract)

Gateway 行程意外中斷或重啟時，資料庫中殘留之 `IN_FLIGHT` 指令依以下嚴格契約復原：

1. **嚴禁無條件回退**：重啟後發現 `IN_FLIGHT` 指令，嚴禁無條件重置為 `QUEUED`。
2. **具官方冪等憑證之安全恢復**：若該指令在首次發送前已持久化官方支援之外部冪等憑證（如 LINE retry key），且仍在有效期限內，可依端點能力重用該憑證與相同載荷，安全轉回可重試佇列。
3. **無冪等憑證之保守防護**：若目標端點缺乏官方冪等機制（如 Telegram），或外部重試憑證未先持久化，由於無法排除該請求已送達伺服器之可能性，重啟時一律將該 `IN_FLIGHT` 指令轉為 **`UNCERTAIN`**，嚴禁盲目重送。

---

### 6. 傳輸階段劃分 (Transport Phase Classification)

出站嘗試之失敗分析依傳輸階段劃分：

1. **`NOT_SENT`（確定未送出）**：
   - 僅在有客觀機器證據證明請求未曾離開本機傳輸層時成立（例如本地 DNS 解析失敗、建立連線前拒絕、或請求序列化前拋錯）。
   - 此類失敗可依一般指數退避策略安全重新嘗試。
2. **`MAY_HAVE_BEEN_SENT`（可能已送出）**：
   - 包含：Socket 寫入後逾時、資料傳輸開始後連線中斷、傳送過程中本機行程當機、或伺服器處理完畢但回應於網路遺失。
   - 若端點缺乏官方驗證之冪等能力，此類失敗之結果屬於未知，一律判定為 **`UNCERTAIN`**，嚴禁自動盲目重試。

---

### 7. LINE 出站重試契約 (LINE Outbound Retry Contract)

依據 2026-09-18 獨立查證之 LINE Messaging API 官方規範：

1. **支援端點範圍**：`X-Line-Retry-Key` 標頭僅支援以下端點：
   - Push Message (`/v2/bot/message/push`)
   - Multicast Message (`/v2/bot/message/multicast`)
   - Narrowcast Message (`/v2/bot/message/narrowcast`)
   - Broadcast Message (`/v2/bot/message/broadcast`)
2. **不支援端點嚴格限制**：**Reply Message 端點不支援重試鍵**。若在 reply message 請求中附加 `X-Line-Retry-Key`，LINE 官方將直接回傳 HTTP 400 Bad Request。因此，對 LINE 回覆端點嚴禁傳送此標頭。
3. **重試鍵生命週期與格式**：
   - 必須使用 128 位元十六進位 UUID 字串。
   - **重試鍵必須在發起第一次 HTTP 請求前持久化儲存**。
   - 重試時必須完全保持相同的重試鍵、相同的請求內文與相同的收件人。
   - 官方有效期限為 24 小時。
4. **回應語意判定**：
   - HTTP 2xx：成功接受，標記 `ACCEPTED_BY_PLATFORM`，停止重試。
   - HTTP 409（相同 key 已被接受）：平台已在先前請求處理完成，標記 `ACCEPTED_BY_PLATFORM`，視為成功受理。
   - HTTP 500 或傳輸逾時：在 24 小時有效期限內，允許使用原重試鍵與相同載荷進行有界指數退避重試。
   - 其他 HTTP 4xx：客戶端錯誤，標記 `FAILED_TERMINAL`，不得重試。
5. **逾期防護**：若重試鍵超過 24 小時有效期且結果仍未確定，嚴禁更換新重試鍵重送原訊息，該指令轉為 `UNCERTAIN`。

---

### 8. Telegram 出站重試契約 (Telegram Outbound Contract)

依據 2026-09-18 獨立查證之 Telegram Bot API 官方規範：

1. **無客戶端冪等鍵**：Telegram HTTP Bot API 的 `sendMessage` 目前未提供任何由客戶端指定之冪等鍵或重試鍵參數（不得將 MTProto 之 `random_id` 混為 Bot API 能力）。
2. **重試判定規範**：
   - 僅在 `NOT_SENT` 階段之失敗允許一般重試。
   - 若收到包含 `retry_after` 之 flood control 錯誤回應，允許在指定等待秒數後進行受控重試。
   - 凡發生於 `MAY_HAVE_BEEN_SENT` 階段且結果未知者，因缺乏官方去重保證，一律標記為 **`UNCERTAIN`**，嚴禁盲目重送。

---

### 9. 平台受理與最終送達之語意分離

本架構嚴格分離通訊狀態：平台回傳 HTTP 2xx 或 LINE 409 僅能標記為 `ACCEPTED_BY_PLATFORM`，絕不等於收件人終端已接收或已讀（DELIVERED_TO_RECIPIENT）。在平台未提供可驗證之收件送達回報前，禁止虛構 `DELIVERED` 狀態。

---

### 10. R2-3 UNCERTAIN 使用者體驗規範 (Option B)

依使用者正式裁決之 Option B 規範：

1. **本地持久化記錄**：`UNCERTAIN` 指令由 Gateway 完整持久化於資料庫中。
2. **IDE 面向操作者檢視**：當前或接手之 Agent 在 IDE attach、通道接管或狀態查詢時，可檢視未決指令之摘要：包含未決計數、指令識別碼、平台、帳號、目標對話識別碼與時間戳記。預設在狀態輸出中不得傾印完整訊息內文。
3. **禁止手機干擾推播**：嚴禁自動向使用者通訊軟體發送「訊息配送不確定」通知。
4. **禁止接管自動重發**：新 Agent 接管通道時，嚴禁自動重發既有之 `UNCERTAIN` 指令。

---

### 11. R3 核心決策：Loopback HTTP v1

本機通訊協定正式採行 **Loopback HTTP v1**：

- **監聽介面限制**：僅嚴格監聽字面值 `127.0.0.1`。嚴禁綁定 `0.0.0.0`、IPv6 `::`、`localhost` 主機名稱、區域網路介面或公開網路介面。
- **具名管道方案處置**：Windows 具名管道（Named Pipe）因在非特權環境下之 ACL 防護與遠端連線行為缺乏充分驗證，正式列為 **延後／未獲選（DEFERRED / NOT SELECTED）**。

---

### 12. R3 威脅模型與防護邊界

Local API v1 必須機械防護以下威脅：

1. 本機瀏覽器跨來源請求（Cross-Origin Request / CORS 穿透）；
2. DNS 重新綁定攻擊（DNS Rebinding）；
3. 本機其他低權限非相關行程之未授權存取；
4. 通訊埠搶佔與偽冒伺服器（Port Squatting / Server Spoofing）；
5. 已簽名請求之過期重放與竊聽；
6. 請求與回應內文之惡意篡改；
7. 機密金鑰於對話視窗或日誌中之外洩。

> 邊界宣告：若同一 OS 使用者權限下的惡意軟體已完全竊取 Local API 金鑰本身，此類深度受害場景不在 R3 v1 之防護宣稱內；但其他縱深防禦措施不得因而削弱。

---

### 13. 通訊埠綁定與 Windows 安全邊界

1. **Winsock SO_EXCLUSIVEADDRUSE 事實**：Windows 雖提供 `SO_EXCLUSIVEADDRUSE` 作為通訊埠獨佔選項，但 Node.js / libuv 在 Windows TCP 實作中並未啟用該選項；`server.listen({exclusive: true})` 僅為內部叢集隔離，不得視為作業系統級的獨佔防護保證。
2. **通訊安全重心**：本機通訊安全完全依賴 HMAC 雙向認證協定，而非底層 Socket 綁定。
3. **通訊埠衝突處置**：若 Gateway 配置之 Local Port 已被其他行程佔用，啟動時必須立即 **Fail-Closed 終止**，嚴禁自動尋找下一可用通訊埠，嚴禁靜默降級。
4. **偽冒伺服器防禦**：客戶端透過驗證伺服器回應的 HMAC 簽章，確認通訊對象為真正持有金鑰之 Gateway。

---

### 14. 通訊埠配置來源與相依性邊界

- 目前 `data-location-config.js` 與 `local-config-loader.js` 僅負責資料目錄路徑，未包含網路通訊埠。
- 通訊埠配置屬 ADR-0022 D24 之本機外部設定檔範疇，其正式實作排定於 `TG-MVP-07A`（D24 本機外部配置基礎建設）。
- 因此，`TG-MVP-11`（Loopback Local API v1 實作）的前置相依鏈正式擴充為包含 `TG-MVP-07A`。

---

### 15. 機密安全與操作管線邊界 (Secret Boundary)

1. **零金鑰入庫與零金鑰暴露**：Local API HMAC Secret 絕對不得存在於版本庫、ADR 範本、TASKBOARD、對話歷史（Transcript）、指令列參數、URL、Cookie、JSON 載荷內文或一般日誌中。
2. **客戶端封裝呼叫**：Agent 呼叫 Local API 時，必須透過本機包裝程序（Client Wrapper CLI）執行。由包裝程序在記憶體中讀取金鑰並計算簽章，Agent 僅傳入與檢視無機敏之業務參數與消毒後之回應結果。

---

### 16. Local API 協定版本與安全標頭編碼契約 (Protocol Version & Header Encoding Contract)

Local API 正式定義協定版本與標頭格式：

1. **協定版本**：
   - Local API 協定版本正式標記為 `HHAI-LOCAL-API-V1`。
   - 所有已認證 HTTP 請求與回應必須攜帶標頭：`X-HHAI-Version: 1`。
   - 收到任何其他版本或未攜帶版本標頭者，伺服器一律 Fail-Closed 拒絕。
   - 簽章正規化網域前綴（Domain Separation Prefixes）固定為：
     - 請求簽章：`HHAI-REQ-V1`
     - 回應簽章：`HHAI-RESP-V1`
     - 兩者絕對不可互換。
2. **時間戳記（Timestamp）**：
   - 標頭：`X-HHAI-Timestamp`。
   - 格式：ASCII 十進位 Unix Epoch 整數秒（如 `1773835200`）。
   - 嚴禁正負號（`+`、`-`）、空白字元、小數點或替代進位表示法。
3. **單次隨機數（Nonce）**：
   - 標頭：`X-HHAI-Nonce`。
   - 格式：128 位元密碼學安全隨機數（CSPRNG），嚴格編碼為恰好 32 個小寫十六進位 ASCII 字元（`[0-9a-f]{32}`）。
4. **會話識別碼（Session ID）**：
   - 標頭：`X-HHAI-Session-Id`。
   - 格式：於正式會話中，由 Gateway 產生的 128 位元密碼學隨機數，嚴格編碼為恰好 32 個小寫十六進位 ASCII 字元（`[0-9a-f]{32}`）。
   - 權限邊界：會話識別碼本質非機密金鑰（Not a secret），其本身不能單獨授權任何請求；合法授權永遠僅來自有效的 HMAC-SHA-256 簽章以及與目前底層 TCP 連線之實體綁定。
5. **簽章（Signature）**：
   - 標頭：`X-HHAI-Signature`。
   - 格式：以共用 Local API HMAC 金鑰計算之 HMAC-SHA-256 摘要，嚴格編碼為恰好 64 個小寫十六進位 ASCII 字元（`[0-9a-f]{64}`）。
6. **內文雜湊（Body Hash）**：
   - 格式：實體內文 bytes 之 SHA-256 摘要，嚴格編碼為恰好 64 個小寫十六進位 ASCII 字元（`[0-9a-f]{64}`）。
7. **標頭唯一性與無重複保證**：
   - 標頭 `X-HHAI-Version`、`X-HHAI-Timestamp`、`X-HHAI-Nonce`、`X-HHAI-Session-Id`、`X-HHAI-Signature` 在同一 HTTP 請求或回應中絕對不得重複出現。
   - 標頭名稱依 HTTP 規範採大小寫不敏感（Case-insensitive）解析，但實作必須解析出唯一語意值；凡偵測到重複之安全性標頭，一律 Fail-Closed 拒絕請求。

---

### 17. 正規化位元組編碼與封框安全契約 (Canonical Byte Encoding & Framing Safety)

所有 HMAC-SHA-256 簽章之輸入 bytes 必須依循以下確定性規範：

1. **正規化字串組裝與編碼**：
   - 先依據精確欄位順序組裝成正規化 ASCII/UTF-8 字串，再以 UTF-8 編碼轉換為二進位 bytes 作為 HMAC 運算之輸入資料。
2. **欄位分隔字元（Field Separator）**：
   - 欄位之間嚴格使用單一 LF 字元（`\n`，位元組 `0x0A`）進行分隔。
   - 嚴禁使用 CRLF（`\r\n`）、CR（`0x0D`）或任何作業系統特定換行符號。
   - **最後一個欄位之後嚴禁包含結尾 LF（No Terminal LF）**。
3. **欄位值限制與無歧義性**：
   - 所有詮釋資料欄位必須為單行純 ASCII 字串，嚴禁包含 LF（`0x0A`）、CR（`0x0D`）或 NUL（`0x00`）。
   - 由於所有可變欄位均具備嚴格格式白名單或定長限制，單一 LF 封框不具任何分隔字元注入歧義。
4. **HTTP 方法與路徑正規化**：
   - `METHOD`：使用大寫且位於白名單之 HTTP 方法（如 `POST`、`GET`）。
   - `PATH`：使用原樣路徑（origin-form，如 `/v1/hello`、`/v1/reply`），嚴禁帶有 scheme、authority、fragment 或 query string。
   - 任何已認證端點之請求目標若包含問號字元（`?`），伺服器必須立即拒絕，嚴禁在去除 query 後再行驗證。
5. **原始實體內文雜湊契約（Raw Entity-Body Hash Contract）**：
   - 內文雜湊必須針對伺服器於 HTTP 封框解碼後、JSON 反序列化（parse）前實際接收到的精確實體位元組序列（exact entity-body bytes）計算 SHA-256。
   - 客戶端在發送前，必須先建立單一外發 body Buffer，對該 Buffer 計算雜湊並發送該完全相同之 Buffer；嚴禁對一份 JSON 運算雜湊卻送出重新序列化的 bytes。
   - 伺服器接收到原始 bytes 後，先驗證大小上限、計算 SHA-256 雜湊並驗證 HMAC 簽章，全數通過後始得進行業務 JSON 解析。
   - 注意：此傳輸層實體內文雜湊僅保護當前 HTTP 請求內容之完整性，與 R2 業務去重之規範載荷雜湊（Canonical Payload Hash）為完全獨立機制，兩者不得混淆。
6. **HTTP 內文封框安全（Framing Safety）**：
   - 凡請求帶有 `Transfer-Encoding` 標頭者一律拒絕，嚴禁接受 chunked 傳輸內文（防範 HTTP Request Smuggling 攻擊）。
   - 任何帶有內文之端點，請求標頭中必須恰好包含一個合法且相符之 `Content-Length`，長度不符或衝突者立即拒絕。
   - 握手請求 `POST /v1/hello` 強制要求 `Content-Length: 0` 且內文為 0 位元組；其內文雜湊固定為空位元組序列之 SHA-256 摘要。

---

### 18. 握手請求正規格式與開機矛盾修復 (Canonical HELLO Request & Replay Domain)

本節正式解決會話尚未建立時之握手開機矛盾（Bootstrap Contradiction）：

1. **無會話識別碼原則（No Session ID in Hello）**：
   - 握手請求 `POST /v1/hello` 發生於會話識別碼產生之前，因此 **HELLO 請求絕對不得攜帶 `X-HHAI-Session-Id` 標頭**。
   - 凡發送至 `/v1/hello` 卻攜帶 `X-HHAI-Session-Id` 標頭之請求，伺服器一律直接拒絕。
   - 握手請求仍必須透過共用 Local API HMAC 金鑰完成認證。
2. **Canonical HELLO 請求精確欄位順序（7 項欄位）**：
   ```text
   HHAI-REQ-V1
   HELLO
   POST
   /v1/hello
   <TIMESTAMP>
   <NONCE>
   <BODY_SHA256>
   ```
   - 依序以單一 LF（`0x0A`）連接以上 7 項字串，尾部無換行。
   - 絕對不存在虛構 session、空白占位符（placeholder）或全零識別碼。
   - 簽章運算：`HMAC-SHA-256(secret, UTF8(canonical_hello_request))`。
3. **HELLO 獨立重放快取網域（HELLO Replay Domain）**：
   - 由於握手時尚無會話，HELLO Nonce 重放防護不可依賴會話內快取。
   - 伺服器維護全域有界之 HELLO 重放快取，以 Nonce 為鍵，快取存活時間不短於時間戳記有效視窗。
   - **快取防毒與驗證流水線**：伺服器依序執行：
     1. 標頭語法與結構檢查；
     2. `Host`、`Origin` 與路徑檢查；
     3. 時間戳記語法與新鮮度驗證；
     4. 內文封框與內文雜湊驗證；
     5. HMAC 簽章驗證；
     6. HELLO Nonce 重放檢驗；
     7. 簽章與重放檢驗全數通過後，始在底層連線上建立新會話。
   - 凡 HMAC 驗證失敗之請求，絕對不得寫入重放快取，防止惡意攻擊者透過無效簽章請求投毒佔用合法 Nonce。

---

### 19. 會話建立、同連線綁定與正規會話請求 (Session Creation & Canonical SESSION Request)

1. **會話建立與 Socket 實體綁定**：
   - 僅在通過合法 HELLO 驗證後，Gateway 始產生 128 位元隨機會話識別碼（32 個小寫十六進位字元）。
   - 該會話授權狀態必須與伺服器端目前承載該連線之底層 Socket / TCP 連線物件嚴格綁定。
   - 判定連線身分不得僅依賴客戶端 IP、客戶端 Port、Host 標頭或 Session ID 本身。
   - 底層 TCP 連線一旦中斷（close）、重置（reset）、發生傳輸錯誤或重新建立連線，該會話立即失效。重新連線後必須重新執行握手認證。
2. **會話請求攜帶要求**：
   - 握手完成後的所有後續機敏業務請求，必須攜帶標頭：`X-HHAI-Session-Id`。
   - 請求所帶之會話識別碼必須與目前 TCP 連線上已完成認證之會話完全一致；若在未認證連線使用、或嘗試跨 TCP 連線重用已存在之 Session ID，一律直接拒絕（Session ID 絕非可跨連線重用之 Bearer Token）。
3. **Canonical SESSION 請求精確欄位順序（8 項欄位）**：
   ```text
   HHAI-REQ-V1
   SESSION
   <METHOD>
   <PATH>
   <TIMESTAMP>
   <NONCE>
   <SESSION_ID>
   <BODY_SHA256>
   ```
   - 依序以單一 LF（`0x0A`）連接以上 8 項字串，尾部無換行。
   - 簽章運算：`HMAC-SHA-256(secret, UTF8(canonical_session_request))`。
4. **SESSION 重放快取網域（Session Replay Domain）**：
   - 會話請求之 Nonce 命名空間嚴格局限於目前會話，正規重放鍵為 `(session_id, nonce)`。
   - 同一會話內若出現重複 Nonce 立即拒絕；不同會話間允許獨立之 Nonce 空間。
   - 會話關閉時，其會話專屬之 Nonce 狀態可隨會話一同銷毀，但在快取清理時不得允許存活會話在新鮮度視窗內重複接受舊 Nonce。

---

### 20. 回應雙向認證與正規回應格式 (Canonical Response Authentication)

所有已認證之 Local API 回應（包含握手回應、會話回應及可安全形成認證之錯誤回應）均必須由 Gateway 產生 HMAC-SHA-256 簽章標頭：

1. **Canonical RESPONSE 精確欄位順序（9 項欄位）**：
   ```text
   HHAI-RESP-V1
   <MODE>
   <STATUS_CODE>
   <REQUEST_METHOD>
   <REQUEST_PATH>
   <REQUEST_NONCE>
   <RESPONSE_TIMESTAMP>
   <SESSION_ID>
   <BODY_SHA256>
   ```
   - `MODE`：固定為 `HELLO` 或 `SESSION`。
   - `STATUS_CODE`：十進位 ASCII HTTP 狀態碼（如 `200`、`400`）。
   - `REQUEST_METHOD` / `REQUEST_PATH` / `REQUEST_NONCE`：對應原始請求經結構驗證後之規範值。
   - `RESPONSE_TIMESTAMP`：伺服器產生回應時之獨立時間戳記（整數秒）。
   - `SESSION_ID`：
     - HELLO 成功回應：填入剛剛產生之新會話識別碼；
     - SESSION 回應：填入當前連線之會話識別碼；
     - 若為尚未建立會話前之早期失敗（Early Failure），因無會話識別碼存在，伺服器不得偽造會話，應回傳最小未認證錯誤並中斷連線，且客戶端絕不得將其視為有效之 Gateway 成功回應。
   - `BODY_SHA256`：回應實體內文 bytes 之 SHA-256 摘要（小寫 64-hex）。
   - 依序以單一 LF 連接以上 9 項字串，尾部無換行。
   - 簽章運算：`HMAC-SHA-256(secret, UTF8(canonical_response))`，置於回應標頭 `X-HHAI-Signature`。
2. **成功 HELLO 回應規格**：
   - 回應標頭至少包含：`X-HHAI-Version: 1`、`X-HHAI-Timestamp`、`X-HHAI-Session-Id`、`X-HHAI-Signature`。
   - 內文可為 0 位元組（`Content-Length: 0`）。
   - 回應簽章已將剛產生的新 Session ID 納入 HMAC 覆蓋範圍；客戶端必須先驗證回應簽章成功後，始得接受該 Session ID 並將連線標記為已認證。
   - 此機制確保即使惡意行程搶先佔用通訊埠並假造 Session ID，在沒有 shared HMAC secret 的情況下，客戶端亦能立即識別偽冒伺服器並中斷連線。
3. **SESSION 業務回應驗證**：
   - 客戶端包裝程式在將業務回應交付 Agent 前，必須先驗證協定版本、會話一致性、請求關聯（Nonce/Method/Path）、回應時間戳記新鮮度與回應 HMAC 簽章，全數合法後始得輸出結果。

---

### 21. 驗證流水線、錯誤處理與測試向量 (Pipeline, Errors & Test Vectors)

1. **嚴格無副作用邊界（Side-Effect Boundary）**：
   - 任何機敏業務操作，在以下所有安全性前置檢驗全數通過前，絕對不得產生任何業務副作用：
     1. 方法與路徑白名單比對；
     2. `Host` 標頭嚴格比對；
     3. `Origin` 標頭絕對排除；
     4. 傳輸封框（無 chunked、單一 Content-Length）；
     5. 內文大小上限檢驗；
     6. 安全標頭語法與無重複檢驗；
     7. 協定版本相符性；
     8. 時間戳記新鮮度；
     9. 實體內文雜湊比對；
     10. HMAC-SHA-256 簽章驗證；
     11. Nonce 重放防護檢驗；
     12. 會話與底層 TCP Socket 綁定驗證（SESSION 模式）。
   - 只有在全部檢驗通過後，伺服器始得將內文 parse 為業務指令並交由業務模組處理。
2. **錯誤處理與防洩漏邊界**：
   - 未通過認證之失敗請求，對外僅回傳有界之通用錯誤訊息（如 HTTP 400 Bad Request 或 HTTP 401 Unauthorized）。
   - 嚴禁向外回傳任何機密衍生資料、預期之 MAC 摘要、正規化簽章字串、重放快取狀態、會話內部結構或金鑰存在性資訊。
   - 伺服器內部日誌僅記錄經過消毒（Sanitized）之診斷原因，嚴禁記錄金鑰或原始簽章素材。
3. **明確簽章測試向量（Explicit Test Vectors）**：
   - `TG-MVP-11` 在實作生產伺服器前，必須先建立確定性之單元測試向量，使用 **確定性虛構測試金鑰（FAKE TEST SECRET ONLY）** 鎖定以下位元組層級規格：
     - HELLO 請求正規化字串位元組與預期 HMAC 摘要；
     - SESSION 請求正規化字串位元組與預期 HMAC 摘要；
     - HELLO 回應正規化字串位元組與預期 HMAC 摘要；
     - SESSION 回應正規化字串位元組與預期 HMAC 摘要；
     - 任何簽章欄位篡改（如改動方法、路徑、時間戳、Nonce 或內文）均導致驗證失敗；
     - 以 CRLF 取代 LF 換行導致驗證失敗；
     - 傳輸內文字元微調但 JSON 語意相同時，因原始 bytes 雜湊變更導致簽章驗證失敗；
     - 相同 Session ID 於另一 TCP 連線發起請求時立即遭拒絕。
   - ADR 規範本體不硬編碼特定衍生數值，由未來實作測試確定性產生並鎖定。

---

### 22. 主機名稱、來源標頭與常數時間比對 (Host, Origin & Constant-Time Verification)

1. **Host 標頭嚴格比對**：HTTP 請求之 `Host` 標頭必須精確等於 `127.0.0.1:<configured-port>`，其餘主機名稱一律拒絕（防止 DNS Rebinding）。
2. **嚴格拒絕 Origin 標頭**：凡帶有 `Origin` 標頭之請求一律直接拒絕（防止瀏覽器跨來源存取）；Local API 不提供 CORS 標頭。
3. **顯式方法與路徑白名單**：僅開放明確定義之業務端點，未知方法或路徑立即拒絕；嚴禁實作通用代理（Generic Proxy）或任意檔案/指令執行端點。
4. **內文限制**：機敏請求僅接受預期之 Content-Type（如 `application/json`），伺服器在解析前強制限制最大位元組大小，超限立即 Fail-Closed。
5. **常數時間比對**：所有 HMAC 簽章比對必須採用常數時間比對演算法（如 `crypto.timingSafeEqual`），嚴禁使用普通字串 `==` 比較，防止計時側信道攻擊（Timing Attacks）。

---

## Architecture Relationships

- **ADR-0022（Channel Gateway Architecture）**：維持整體架構與外發總則權威。本 ADR 承接並細化其出站可靠性與本機 API 規範。
- **ADR-0023（Channel Gateway SQLite State Store）**：維持 SQLite 運作狀態權威。**本 ADR 正式取代（SUPERSEDE）ADR-0023 第 7 節** 關於 R2 與 R3「待使用者裁決」之歷史描述；ADR-0023 之資料庫架構主體保持不變。
- **ADR-0024（Inbound Event Identity and Cursor Semantics）**：維持入站事件身分與游標權威。本 ADR 專注於出站可靠性與本機安全，不重新定義入站模型。

---

## Explicit Non-Goals

本架構 ADR 落地不包含以下項目之程式碼實作：

- SQLite Outbox 資料表遷移與 Schema 變更；
- Outbox 工作者與輪詢排程實作；
- Telegram `sendMessage` 適配器實作；
- LINE `push` 與 `reply` 適配器實作；
- Local API HTTP 伺服器與監聽器實作；
- HMAC 簽章與驗證程式碼；
- Nonce 快取儲存庫；
- 金鑰與設定載入實作；
- F1 回覆授權 SQL 修復（排定於 TG-MVP-04）；
- 手機端不確定通知機制。

---

## Architecture Acceptance Canaries

未來實作階段必須通過以下驗收金絲雀：

### R2 Outbox & Safe Retry Canaries
- **CANARY R2-A**：相同 `client_request_id` + 相同載荷，僅產生單一持久化 Outbox 指令。
- **CANARY R2-B**：相同 `client_request_id` + 不同載荷，判定為 IDEMPOTENCY_CONFLICT 並嚴格拒絕。
- **CANARY R2-C**：Outbox 指令 COMMIT 後呼叫端中斷連線，該指令仍穩定持久化且繼續由工作者處理。
- **CANARY R2-D**：指令 COMMIT 後通道發生接管（Takeover），既有指令不被刪除或取消。
- **CANARY R2-E**：LINE push 逾時重試，重用原先持久化之相同重試鍵與相同載荷。
- **CANARY R2-F**：LINE 回傳 409（相同 key 已接受），系統判定為 `ACCEPTED_BY_PLATFORM` 且不再重試。
- **CANARY R2-G**：對 LINE reply 端點發送請求時，保證絕不夾帶 `X-Line-Retry-Key` 標頭。
- **CANARY R2-H**：LINE reply 請求若發生於 `MAY_HAVE_BEEN_SENT` 階段且結果未知，指令轉為 `UNCERTAIN`，不進行盲目重試。
- **CANARY R2-I**：Telegram `sendMessage` 於 `MAY_HAVE_BEEN_SENT` 階段逾時或中斷且結果未知，轉為 `UNCERTAIN`，不進行盲目重試。
- **CANARY R2-J**：Telegram 回傳包含 `retry_after` 之 flood control，依指示秒數延後重試。
- **CANARY R2-K**：Gateway 重啟復原 `IN_FLIGHT` 指令，若端點缺乏官方冪等機制，自動轉為 `UNCERTAIN`。
- **CANARY R2-L**：`ACCEPTED_BY_PLATFORM` 狀態絕不向外虛報為收件人已送達（DELIVERED）。

### R3 Loopback Local API Canaries
- **CANARY R3-A**：伺服器監聽僅綁定字面值 `127.0.0.1`。
- **CANARY R3-B**：嘗試綁定 `0.0.0.0`、`::` 或非 loopback 介面時啟動失敗。
- **CANARY R3-C**：請求之 `Host` 標頭不符 `127.0.0.1:<port>` 時直接拒絕。
- **CANARY R3-D**：請求帶有 `Origin` 標頭時直接拒絕。
- **CANARY R3-E**：請求 HMAC 簽章不符時在執行業務前直接拒絕。
- **CANARY R3-F**：過期時間戳記之請求直接拒絕。
- **CANARY R3-G**：重放之 Nonce 直接拒絕。
- **CANARY R3-H**：於 TCP 連線 A 完成握手，但於連線 B 發送機敏請求，直接拒絕。
- **CANARY R3-I**：伺服器回應之 HMAC 簽章若無效，客戶端包裝程式直接拒絕接受。
- **CANARY R3-J**：配置之通訊埠已被佔用時，啟動 Fail-Closed，禁止自動尋找下一個埠號。
- **CANARY R3-K**：通訊埠被無金鑰之惡意程式搶佔時，客戶端因回應簽章驗證失敗而安全中斷。
- **CANARY R3-L**：金鑰絕對不出現於一般日誌、錯誤訊息或 Agent 可見之輸出中。
- **CANARY R3-M**：HELLO 請求若帶有 `X-HHAI-Session-Id` 標頭，伺服器直接拒絕。
- **CANARY R3-N**：請求若帶有 `Transfer-Encoding` 標頭，伺服器直接拒絕。
- **CANARY R3-O**：存在重複之安全標頭時，伺服器一律 Fail-Closed 拒絕。
- **CANARY R3-P**：無效 HMAC 之 HELLO 請求不得寫入重放快取造成合法 Nonce 遭阻斷。
- **CANARY R3-Q**：成功 HELLO 回應之簽章完整覆蓋新產生之 Session ID，客戶端驗證成功後始接受。
- **CANARY R3-R**：正規化字串換行採 CRLF 取代 LF 時，簽章比對立即失敗。

---

## External Platform & Runtime Facts

本 ADR 依據 2026-09-18 由 External Macro Auditor 獨立複驗之官方外部事實撰寫：

1. **LINE 官方規範事實**：
   - `X-Line-Retry-Key` 僅支援 push、multicast、narrowcast、broadcast 端點。
   - 不支援之 API 若附帶 `X-Line-Retry-Key` 會回傳 HTTP 400 Bad Request。
   - 重試鍵必須在初次發送時即存在，有效期限為 24 小時。
   - 重試請求必須維持相同之內文與收件人。
   - 2xx 代表成功受理；409 代表相同 key 已被受理；兩者皆不可再重試。
   - 500 或逾時在 24 小時內為可重試候選；其餘 4xx 不得重試。
   - 重試請求仍計算於平台頻率限制（Rate Limits）中。
2. **Telegram 官方規範事實**：
   - HTTP Bot API `sendMessage` 目前未提供官方文件規範之客戶端指定冪等鍵或重試鍵參數。
   - 成功呼叫回傳 result 物件；失敗回應可能包含 ResponseParameters；flood control 可能包含 `retry_after`。
   - 不宣稱 Telegram 內部無去重機制，僅確認官方 Bot API 未提供客戶端冪等鍵介面。
3. **Windows 與 Node.js 執行期事實**：
   - Windows `SO_EXCLUSIVEADDRUSE` 為作業系統級之 socket 獨佔選項。
   - libuv 在 Windows TCP 實作中未設置 `SO_REUSEADDR`，亦刻意未在一般綁定路徑設置 `SO_EXCLUSIVEADDRUSE`。
   - Node.js `server.listen({exclusive: true})` 不足以作為 `SO_EXCLUSIVEADDRUSE` 已啟用之安全保證。
   - 因此 Local API 必須強制以 HMAC 雙向認證協定作為核心安全防線。
