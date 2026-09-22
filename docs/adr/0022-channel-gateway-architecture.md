# ADR-0022: Channel Gateway 單一通訊閘道架構與 Omni-Channel 演進 (Channel Gateway Architecture)

- Status: Accepted
- Date: 2026-09-16
- Decision Owner: 使用者 HH

## Context

專案在歷史演進中（參照 ADR-0011、ADR-0014、ADR-0015、ADR-0017），為了實現 LINE 與 Telegram 雙平台遠端控制，分別建立了兩套獨立的橋接進程：
1. **LINE 橋接**：位於 `skills/03_Execution/line-bot-zero-delay/line-bot-project/`，使用 Node.js / Express、Port 3000、依賴 cloudflared / Pinggy 穿透隧道與 PM2 常駐守護；
2. **Telegram 橋接**：位於 `skills/03_Execution/telegram-bot-cdp-bridge/telegram-bot-project/`，使用 TypeScript / grammy / Remoat，Port 3001、Long-Polling 模式與另一組 PM2 進程。

在 E-03 Runtime 執行層之 Phase 1/1B/1B2 依賴調研中，揭露了雙生橋接架構的多項結構性缺陷：
- 兩套進程各自管理生命週期，Agent 需透過腳本主動啟停 PM2 進程，並在切換帳號時覆寫 `.env` 檔案造成狀態污染；
- 依賴邊界不清（例如 `textNormalizer.js` 與 `mediaDownloader.js` 跨專案路徑穿透、undeclared `axios` 與 `opencc-js` 依賴漂移）；
- LINE 依賴之穿透隧道存在靜默斷線與 Webhook 失效風險（ADR-0015）；
- 原先規劃之 `runtime/telegram-bot/` 獨立遷移路徑若單獨推行，將迫使 LINE 保持舊有架構或日後重複建設第二套閘道。

2026-09-16，專案擁有者（使用者 HH）針對通訊架構做出 D1～D26 全面架構裁決。本 ADR 正式將該二十六項決策收錄為版本庫之單一權威架構紀錄（Canonical Architecture Record）。外部諮詢意見不具備專案架構與審計權威，本架構之唯一決策依據為使用者親自裁決之定案。

## Decision

確立以 **單一 Channel Gateway 架構** 全面取代舊有 LINE 與 Telegram 雙生獨立橋接，並確立以下 D1 至 D26 核心規範：

### 1. 核心定位與生命週期 (Core & Lifecycle, D1–D4)

- **D1（單一 Channel Gateway 取代雙橋接）**：建立單一 Channel Gateway 服務，核心（Gateway Core）為多通道（multi-channel）抽象，Telegram 與 LINE 均為其下之通道適配器（Channel Adapters）。目標存放路徑為 `runtime/channel-gateway/`，原先暫訂之 `runtime/telegram-bot/` 正式廢棄。
- **D2（維持 Agent-in-the-Loop 與官方合規原則）**：堅持人類或排程喚醒之 Agent-in-the-Loop 模式。不採用 CDP 注入（CDP injection），亦不採用 agy CLI wrapper 或 ACP bridge 驅動使用者個人 Antigravity 帳號。決策理由：Google Antigravity 官方條款明文禁止第三方軟體、工具或服務存取該服務，否則可能構成帳號停權或服務終止之事由（本條款以官方條款規範為依據，不宣稱已證實之實際停權案例）。
- **D3（單一活躍帳號原則）**：各平台允許登錄多個 Bot 帳號，但同一時間每個平台僅允許 exactly one 活躍帳號（Active Account）。Gateway 為該活躍帳號之唯一接收端（sole receiver）。
- **D4（作業系統託管生命週期）**：Gateway 由作業系統啟動管理（如 Windows Startup / 排程服務 / 系統服務託管），Agent 不得也不再負責啟動或重啟基礎設施進程。ADR-0009 記載之 Task / Job Object 啟動繞道不再作為新架構之現行啟動規則（ADR-0009 歷史原文予以保留）。

### 2. 控制權接管與狀態管理 (Channel Control & Takeover, D5–D10)

- **D5（通道級鎖定單元）**：鎖定與職責單元（Lock / Duty Unit）為「通道（Channel）」。Telegram 與 LINE 彼此獨立互不干擾。每個通道同一時間僅允許一個 Agent 持有鎖，不實施交談層級（conversation-level）派發。
- **D6（接管意圖限定）**：僅以下特權指令具備控制權接管意圖（Takeover Intent）：
  - `$$TG連線$$`
  - `$$LINE連線$$`
  - `$$LINE連線: <自訂名稱>$$`
  - `$$TG帳號$$`
  - `$$Line帳號$$`
  常態輪詢（poll）、心跳（heartbeat）與訊息回覆（reply）嚴禁觸發接管。
- **D7（接管通知邊界）**：控制權接管通知僅在 IDE 端呈現：新 holder 取得前任 holder 身分與被捨棄訊息清單（discarded-message list）；舊 holder 於輪詢時盡力接收接管通知，不干擾手機端。
- **D8（防過期回覆防護）**：過期或失效 holder 之回覆（stale reply）必須由 Fencing Token / Versioning 機制嚴格拒絕，防止狀態競爭。
- **D9（訊息過渡與捨棄語意）**：接管發生時，已被舊 holder 取走但未及回覆之訊息予以捨棄（discard）；佇列中尚未取走之訊息則轉交新 holder。心跳逾期（heartbeat expiry）亦依同規則處理。
- **D10（無值守隊列與積壓通知）**：無 Agent 處於活躍鎖定時，進線訊息由 Gateway 持久化暫存，手機端不發送任何未值守提示；下一位 Agent 建立連線時，於 IDE 端回報積壓訊息總數（backlog count）。

### 3. LINE 架構與 Telegram 平滑過渡 (LINE & Transition, D11–D14)

- **D11（LINE 未來信箱目標態）**：LINE 通道未來目標架構採：Cloudflare Worker Mailbox → 簽章驗證（Signature Verify）→ 訊息去重（Dedupe）→ SQLite Durable Object 暫存 → 本地 Gateway 主動拉取（Pull Model）。全面廢除本地隧道（Cloudflare Tunnel / Pinggy / cloudflared）與動態 URL 同步機制。
- **D12（LINE 施工順位延後）**：LINE 適配器實作排在最後順位，或待使用者未來發出明確指示時才啟動。本決策不將 LINE 實作列為立即待辦。
- **D13（Gateway 核心預留 LINE 約束）**：Gateway Core 在設計階段即預先考量 LINE 平台特性：Reply Token 短生命週期與單次使用限制、Push Message 配額監控、userId / groupId / roomId 識別、非秒級輪詢拉取模式（採 Long-Poll 或 WebSocket 類機制），以及多 LINE 官方帳號之獨立 Webhook Path / Secret / Mailbox Partition。
- **D14（Telegram 平滑過渡）**：開發期間，舊版 `HH.AI_260806` 正式 Telegram Bot 保持正常服務；新 Gateway 一律使用 Test Bot 進行測試與驗證。正式上線切換（Cutover）時，停止舊橋接並將 Gateway 切換至正式 Token，屆時 E-04 才將 `$$TG連線$$` 路由導向新 Gateway。全程保留回滾路徑，嚴禁修改舊版版本庫。

### 4. 套件邊界與附件管理 (Packages & Attachments, D15–D18)

- **D15（獨立極小依賴閉包）**：`runtime/channel-gateway/` 擁有專屬之 `package.json`，僅宣告實際運行閉包所需之依賴（生產安裝採 `npm ci --omit=dev`），嚴禁沿用 Remoat 完整套件清單。實作時應評估 Node 原生能力是否可取代 `axios`、`dotenv`、`express`、`helmet`（此為評估義務，非預先刪除宣告）。
- **D16（語音功能排除）**：新架構不支援語音訊息，不得引入 Whisper 或 ffmpeg 等重量級外部資產。
- **D17（進線附件處理分工）**：使用者傳送至 Agent 之附件（照片、PDF、Office 檔案等），Gateway 僅負責安全下載、正規化檔名並將本機絕對路徑與 MIME Type 交付 Agent。檔案解析與實質處理交由既有技能模組，Gateway 不安裝文件解析套件。
- **D18（外發附件安全傳輸）**：Agent 傳送至使用者之附件：Telegram 支援原生直接上傳；LINE 因缺乏通用檔案訊息類型，未來 LINE 適配器將採用不可猜測（unguessable）、具時效性（expiring）之 HTTPS 下載連結（依 D12 延後實作）。並且：每次送出該下載連結均屬 LINE push message，因此會消耗該 LINE Official Account 的 push quota。這亦是 D26 中 LINE 帳號 remaining push quota 展示與排序之架構輸入依據之一。

### 5. 外發檔案授權防線 (Outbound File Authorization, D19–D21)

- **D19（免授權特區與嚴格拒絕清單）**：對話歸檔根目錄（Conversation Archive Root）為唯一免授權外發目錄。除此以外之所有本機路徑（包含 `HH.AI_v2`、`HH.AI_260806`、使用者個人文件夾、其他磁碟槽）外發檔案均須經使用者顯式授權。全域套用硬性拒絕清單（Hard Deny List）。
- **D20（手機端使用者雙向授權）**：檔案外發授權由 Gateway 於手機端主動向使用者發起確認提示（檔名、大小、來源路徑、Allow / Reject）。授權由使用者手機帳號直接回傳 Gateway（Agent 無權自行核准），具備內容雜湊綁定（Content Hash Bound）、單次使用（Single-Use）、逾時即拒絕（Timeout=Deny）與完整安全審計留痕。
- **D21（三道深度安全補強）**：
  1. **真實路徑檢驗 (Realpath Enforcement)**：符號連結（Symlink）、目錄聯結（Junction）與路徑遍歷（`..`）強制要求授權；檢驗與傳送必須使用記憶體內同一份內容。
  2. **副本偵測 (Duplicate-Copy Detection)**：防範將受保護檔案複製至暫存區規避檢查。
  3. **硬性拒絕清單 (Hard Deny List)**：包含高敏感檔名特徵與內容指紋；無法掃描之二進位封裝檔強制要求授權，但若命中 Hard Deny 即使使用者點選 Allow 亦絕對禁止發送。Hard Deny List 僅能經由版本庫工程治理流程修改。
  *(已知殘留風險：金鑰若遭惡意混淆改寫為普通文字可能逃避掃描，使用者已知悉此限制)*。在授權機制驗收完成前，Agent → User 檔案傳輸預設關閉（Fail-Closed）。

### 6. 對話歸檔與主題管理 (Conversation Archive & Topics, D22–D23)

- **D22（歸檔結構與單一寫入權限）**：對話歸檔預設路徑為 `C:\Users\HH.AI_260806\Desktop\HH.AI_v2_對話紀錄`（僅於本地設定檔指定，不得硬編碼於生產原始碼中；桌面路徑需以系統 Known-Folder API 解析）。目錄階層採 `TG_<account-label>/Q001_<topic>/001_<summary>_<time>.md` 與 `附件/`（LINE 結構對齊）。所有內容（提問、回覆、附件中繼）強制通過 Wave 1A DLP 淨化（`shared/dlpSanitizer.js`）。流水序號採三位數起算（`Q001`，無上限）。舊版 `Desktop\Line對話紀錄` 視為唯讀歷史資產。對話紀錄僅允許 Gateway 單一權威寫入。
- **D23（主題清單與模糊比對廢除）**：Gateway 維護並提供既有主題清單。Agent 由清單選取既有主題，確認新主題時才建立。全面廢除不可靠之模糊子字串比對（Fuzzy Substring Matching）；建立新主題前以正規化名稱查重。

### 7. 本機配置、代碼分層與熱切換 (Local Config, Layout & Account Switch, D24–D26)

- **D24（本機配置中心化與啟動路徑檢查）**：所有資料與執行期路徑（歸檔目錄、暫存目錄、狀態資料預設 `%LOCALAPPDATA%`、日誌目錄、受保護根目錄清單）集中於版本庫外之本機設定檔（Local Config），版本庫僅收錄設定範本。啟動時執行路徑有效性驗證，若異常則 Fail-Closed。路徑遷移需變更設定並重啟，舊資料搬移必須經使用者手動確認。
- **D25（清晰三層架構邊界）**：版本庫通訊與執行層劃分為三層：
  1. `runtime/channel-gateway/`：具備獨立 `package.json`，內含 `core/`、`adapters/`、`bin/`、`tests/`；不得在 `runtime/` 下建立 `telegram-bot/` 或 `line-bot/` 作為頂層架構；未來 LINE Worker 程式碼亦不設於 repo 根目錄；
  2. `shared/`：保留 Wave 1A 已驗證之純共享原語資產（`shared/dlpSanitizer.js`、`shared/dlpSanitizer.d.ts`、`shared/atomicFs.js`）；
  3. `skills/platform/`：僅存放技能合約、說明文件與呼叫界面，不包含通訊服務常駐實體。
- **D26（Gateway 控管之非重啟熱切換）**：保留 `$$TG帳號$$` 與 `$$Line帳號$$` 特權指令，但實作改由 Gateway 集中管控之熱切換（Hot Switching），完整涵蓋以下已裁決細節：
  1. **帳號登錄邊界**：非敏感帳號標籤（non-secret account label）與說明（description）存於版本庫外之本機設定檔（Local Config）；Token 與 Channel Secret 絕對不得以純文字存於本機設定檔，嚴禁進入版本庫，版本庫僅收錄設定範本。
  2. **帳號選擇流程**：Agent 發出 `$$TG帳號$$` 或 `$$Line帳號$$` 後，由 Gateway 列出該平台已登錄帳號清單，使用者於 IDE 端選擇目標帳號。
  3. **LINE 額度顯示與排序**：LINE 帳號清單必須顯示剩餘推播額度（remaining push quota），並依剩餘額度由高至低自動排序；額度資料由 Gateway 直接呼叫 LINE quota API 取得，不再依賴舊有 `get_line_quotas.js` 腳本。
  4. **非重啟熱切換 (Hot Switch)**：Gateway 停止舊活躍帳號（active account）之接收並啟用新帳號接收，整個 Gateway 進程絕對不得重啟（no process restart）；Agent 嚴禁覆寫 `.env`，亦嚴禁重啟 PM2。
  5. **切換即接管 (Switch = Takeover)**：帳號切換完成時同時取得該通道之控制權，接管通知嚴格遵守 D7 規範。
  6. **訊息與接收帳號嚴格綁定**：進線訊息與其接收帳號（receiving account）強綁定，訊息僅能由當初接收該訊息之帳號回覆，嚴禁由不同帳號代回。
  7. **預設未決訊息處理**：切換時舊活躍帳號尚未處理之訊息（包含佇列中與處理中 pending messages），於 IDE 端完整列出後予以捨棄（discard）；使用者可選擇重新傳送至新活躍帳號。
  8. **獨立白名單**：各帳號配置各自獨立之授權白名單（Allowlist per account）。
  9. **外發授權帳號綁定**：D20 之外發檔案授權由當下活躍帳號發出，授權審計紀錄（Authorization Audit Record）必須明確記錄帳號身分（account identity）。
  10. **獨立對話歸檔**：各帳號歸檔目錄依帳號標籤完全獨立隔離（Archive per account）。
  11. **測試帳號地位平等**：Test Bot 視為一般已登錄帳號（ordinary registered account），不建立特殊架構分支。
  12. **正式 Telegram 帳號過渡防護**：正式 Telegram 帳號在正式 Cutover 前預設處於停用狀態（default disabled）；Gateway 在切換前絕對不得啟用舊 bridge 正在使用之正式 Token，杜絕 Telegram 409 Conflict。

---

## 歷史憑證處置政策 (Legacy Hardcoded Credentials)

在舊專案 `scripts/cloudflare_worker_line_proxy.js` 與 `scripts/line_daemon.js` 等歷史檔案中發現之硬編碼 fallback 憑證，版本庫一律視為永久洩漏（Exposed）。該等憑證絕對不得遷移至新架構；新架構凡遇金鑰缺失一律嚴格 Fail-Closed。

---

## Relationship to Existing ADRs

本 ADR 保留既有 ADR 之歷史背景與決策留痕，並界定與新 Channel Gateway 架構之關聯：

1. **與 ADR-0009（Windows Job Object 與進程生命週期）之關係**：
   ADR-0009 記錄了在 Windows Job Object 環境下進程被整組終止的事故分析與 Task-Exit Loop 歷史繞道。新架構採 D4 由作業系統（OS）直接託管 Gateway 服務，Agent 不再啟動通訊進程，因此 ADR-0009 之「強制由 Agent 串接 Task 啟動」規則在新架構中由 D4 正式取代（superseded），但其歷史事故分析維持有效。
2. **與 ADR-0011（Omni-Channel 雙生遙控通訊架構）之關係**：
   ADR-0011 記錄了雙生通訊協定演進至 V4 之歷史階段。本 ADR（ADR-0022）正式取代 ADR-0011 關於「LINE 與 TG 獨立雙進程運行」、「依賴 CDP 注入操作」、「PM2 Agent 自行重啟守護」與「Task-Exit 輪詢常駐進程」之後續架構約束。雙生架構由單一 Channel Gateway 與通道適配器架構全面繼承並演進。
3. **與 ADR-0015（LINE 穿透隧道鏈路失敗）之關係**：
   ADR-0015 詳盡分析了四環隧道依賴鏈之脆弱性與靜默失敗現象。本 ADR 之 D11 決策正是基於 ADR-0015 的歷史證據，徹底廢除本地隧道與動態 Webhook URL 同步，改採 Cloudflare Worker Mailbox + Pull 模式以根治該問題。
4. **與 ADR-0017（Port 分配規範）之關係**：
   ADR-0017 記錄了歷史上為了避免與網頁應用衝突而對 LINE (3000) 與 TG (3001) 進行之固定配置。在 D1 單一 Gateway 與 D11 LINE 郵箱拉取模型下，原本「3000 與 3001 永久不得變更」之技術前提已不存在。後續經 TG-MVP-07（B-30 + B-33 收斂）正式確立 Channel Gateway v1 canonical local port = 3003（不再處於未決狀態，且無自動回退）。但需明確說明：Gateway 本地 listener 實作與 D24 Local Config 載入尚未由 TG-MVP-07 實作，分別保留由後續 TG-MVP-11 與 TG-MVP-07A 負責。

---

## 外部審計發現處置路由 (Macro Finding Routing M2–M8)

為避免建立重複任務（duplicate tasks），宏觀審計發現 M2 至 M8 之處置路由正式確立如下：
- **M2（line-interaction-manager 繞過 Gateway 直接呼叫 LINE API）**：路由至 `CURRENT E-03` + `EXISTING E-04`。最終架構要求所有外發訊息必須統一經由 Gateway 發送並通過 DLP 與授權；本批不更動該 skill。
- **M3（ADR-0017 固定 Port 前提過期）**：路由至 `EXISTING B-30` + `EXISTING B-33`。後續經 TG-MVP-07 收斂確立 Gateway 規範通訊埠為 3003，並廢除 Playwright 常用通訊埠自動掃描；實作細節由 TG-MVP-07A / TG-MVP-11 接續。
- **M4（SOP_02 記載舊版 Line對話紀錄 路徑）**：路由至 `CURRENT E-03` 文件收斂工作；本批不修改 SOP_02。
- **M5（副本偵測索引無法覆蓋全機）**：路由至 `CURRENT E-03 SECURITY ACCEPTANCE`。D24 之受保護根目錄清單至少涵蓋 `HH.AI_v2`、`HH.AI_260806`、使用者設定與憑證路徑。
- **M6（Agent 篡改對話歸檔風險）**：路由至 `CURRENT E-03`。由 Gateway 獨佔對話歸檔寫入權，Agent 生成之外發檔案存放於專屬待傳區。
- **M7（多 Agent 並行編輯與資源鎖缺口）**：路由至 `CURRENT E-03` + `EXISTING F-05`。在 Telegram 與 LINE 能夠正式同時值守前，ADR-0012 分散式悲觀鎖與 F-05 缺口必須完成必要處理。
- **M8（舊腳本與舊路徑相依性收斂）**：
  - `SOP/SOP_00A_Master_Index.json` 特權指令路由更新 → `EXISTING E-04`
  - `skills/agents/bot-account-switcher/` 依 D26 重寫 → `CURRENT E-03`
  - `SOP/SOP_06_Handover_Manual.md` 舊啟動路徑更新 → `CURRENT E-03`
  - `skills/platform/json-to-flex-renderer/` 舊路徑註記 → `EXISTING F-06`
  - `line-interaction-manager` 原生發送修正 → M2 / `CURRENT E-03` + `EXISTING E-04`

---

## 上線前既有任務交會相依 (Pre-Live Existing Task Intersections)

既有任務狀態維持原樣，確立以下相依關係：
- **B-98**：在首次涉及真實金鑰之測試 Bot 連線前必須完成外部輸出安全硬化。
- **B-30**：在 live Gateway 與網頁功能整合前，必須解決 Playwright 自動掃描危險。
- **B-33**：新 Port 分配與環境變數文件殘留需與 Gateway 實作同步解決。
- **F-02**：於適當之前置檢查點評估配額熔斷錨定。
- **F-05**：資源鎖缺口處理為雙平台同時並行值守前之必要前提。
- **F-06**：LINE 適配器相依性收斂留待後續；LINE 實作維持使用者明確觸發或最後順位。
- **E-04**：特權指令路由切換僅於正式 Cutover 時執行，開發期間不切換。

## Consequences

- **架構集中與維護簡化**：由單一 `runtime/channel-gateway/` 統一處理多通道通訊，徹底消滅雙橋接重疊依賴與維護負擔。
- **執行期責任脫鉤**：Agent 專注於任務推理解題，不再介入作業系統基礎設施的啟停、監聽與 PM2 管理。
- **資安防線大幅提升**：嚴格的本機檔案外發授權機制、手機端確認流程與 DLP 淨化，杜絕專案與機敏個資未經授權外洩。
- **平滑遷移與零停機切換**：Telegram 開發階段採 Test Bot，現役正式服務不受干擾；LINE 延後實作不阻礙 Telegram 核心閘道推進。
