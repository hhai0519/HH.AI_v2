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

### 16. 請求認證協定 (Request Authentication Protocol)

Local API 採 HMAC-SHA-256 認證協定：

1. **標頭傳遞**：所有認證參數僅透過 HTTP 標頭（Headers）傳遞，嚴禁透過 Query String、Cookie 或 Body 傳遞憑證。
2. **簽章綁定欄位**：請求簽章必須確定性綁定以下欄位：
   - 協定版本（如 `HHAI-HMAC-SHA256`）
   - 大寫 HTTP 方法（`METHOD`）
   - 精確路徑（`PATH`）
   - 時間戳記（`X-HHAI-Timestamp`，整數秒）
   - 單次隨機數（`X-HHAI-Nonce`）
   - 請求內文雜湊（`SHA-256(Body)`，十六進位字串）
   - 會話識別碼（`X-HHAI-Session-Id`）
3. **禁止 Query String**：機敏端點一律不使用 Query String，避免記錄或洩漏。

---

### 17. 時間戳記新鮮度與重放防護 (Freshness & Nonce Cache)

1. **新鮮度視窗**：伺服器檢驗請求時間戳記，超出固定安全視窗（如 ±30 秒，由 TG-MVP-11 鎖定為常數）者立即拒絕。
2. **Nonce 唯一性**：在有效時間視窗與會話內，伺服器維護已使用 Nonce 快取；重複 Nonce 立即拒絕。

---

### 18. 認證握手與同連線會話綁定 (Authenticated Hello & Same TCP Connection)

為防禦通訊埠劫持與未授權探測，協定要求連線層與應用層雙重綁定：

1. **握手流程**：
   - 客戶端與 `127.0.0.1:<port>` 建立 TCP 連線；
   - 客戶端發送簽名之握手請求至 `/v1/hello`；
   - Gateway 驗證金鑰後，產生隨機會話識別碼（Session Challenge），回傳已簽章之握手回應；
   - 客戶端驗證回應簽章確認 Gateway 身分。
2. **同連線會話綁定**：後續所有機敏請求必須在 **同一條已驗證之 TCP 連線** 上執行，且簽章需綁定該會話識別碼。
3. **斷線重置**：TCP 連線一旦中斷、重置或關閉，該會話立即失效。重新連線後必須重新發起握手認證。嚴禁將會話挑戰碼作為跨連線的通用權杖。

---

### 19. 回應雙向認證 (Response Authentication)

所有 Local API 回應均由 Gateway 產生 HMAC-SHA-256 簽章標頭：

- 簽章綁定：協定版本、HTTP 狀態碼、原始請求 Nonce、會話識別碼、回應時間戳記與回應內文 SHA-256 雜湊。
- 客戶端包裝程式必須先驗證回應簽章，成功後始得將資料交付 Agent，杜絕偽冒伺服器之回應注入。

---

### 20. 主機名稱、來源標頭與路徑白名單

1. **Host 標頭嚴格比對**：HTTP 請求之 `Host` 標頭必須精確等於 `127.0.0.1:<configured-port>`，其餘主機名稱一律拒絕（防止 DNS Rebinding）。
2. **嚴格拒絕 Origin 標頭**：凡帶有 `Origin` 標頭之請求一律直接拒絕（防止瀏覽器跨來源存取）；Local API 不提供 CORS 標頭。
3. **顯式方法與路徑白名單**：僅開放明確定義之業務端點，未知方法或路徑立即拒絕；嚴禁實作通用代理（Generic Proxy）或任意檔案/指令執行端點。

---

### 21. 內文安全與常數時間比對

1. **內文限制**：機敏請求僅接受預期之 Content-Type（如 `application/json`），伺服器在解析前強制限制最大位元組大小，超限立即 Fail-Closed。
2. **常數時間比對**：所有 HMAC 簽章比對必須採用常數時間比對演算法（如 `crypto.timingSafeEqual`），嚴禁使用普通字串 `==` 比較，防止計時側信道攻擊（Timing Attacks）。

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
