# ADR-0015: LINE 隧道同步鏈路斷裂，與雙平台架構的失效點數量對照

- Status: Accepted
- Date: 2026-08-26

## Context

使用者回報 LINE 通道長期不穩、已實質棄用，日常僅使用 Telegram。
2026-08-25 至 08-26 對舊系統進行完整實機診斷，確認 LINE 完全不通，
並找出根因。同時對 Telegram 做了對照診斷。

### 時間軸（依實際證據重建）

- **7/26 之前**：LINE 完整可用。有截圖為證，Agent 能透過 LINE 推播
  長篇 Markdown 報告，格式轉換正確。
- **7/26**：系統因環境層級異常崩潰，採取「建立全新 OS 使用者帳號 +
  人工還原」的重建措施。同日部署 Cloudflare Worker 固定門面架構
  （見下方「7/26 部署的完整架構」）。
- **7/26 之後**：LINE 時好時壞，使用者形容「很容易掛掉」。
- **8/8、8/9**：使用者多次發送「連線測試」，皆無回應。
- **8/9 之後**：放棄 LINE，改用 Telegram。
- **8/25 22:28**：再次測試，仍無回應。

### 7/26 部署的完整架構（依當時 LINE 推播的部署報告）

1. Cloudflare Worker Edge Gateway（`line-proxy.hh-ai-19850519.workers.dev`）
   - 提供 `/admin/update-tunnel` 特權同步 API 與 17ms 極速簽收轉發
   - LINE 後台只需填固定門面網址，重開機或換 IP 都不用改
2. PM2 六大常駐進程生態 v23.0
   - `scripts/start_line_tunnel.js`：事件驅動型守護單元，即時捕獲
     最新活體隧道網址
   - `scripts/sync_tunnel_url.js`：每 15 秒自動對齊巡檢
3. `scripts/generate_keys.js` 產生三把 256-bit 金鑰
   （`CURRENT_AGENT_SECRET`、`OUTBOX_SECRET`、`INTERNAL_GATEWAY_TOKEN`）
4. 雙平台 100 筆高併發壓測，100% 成功，平均延遲 17.5ms

### 診斷發現

**1. PM2 進程狀態**
六大進程中僅 `tg-bridge-zero-delay` 存活（已運行 2 天）。
`line-bridge`、`line-daemon`、`line-tunnel`、`sync-tunnel`、`tg-daemon`
全部不存在，Port 3000 無監聽。LINE 那條線並非崩潰，是從未啟動。

**2. 記憶體環境是隱藏的失效因素**
診斷當下系統記憶體使用率 96%（16GB 僅剩 638MB 可用），主要由
Antigravity IDE（1.7GB）與 Chrome（1.6GB）佔用。關閉 Chrome 與
第二個 Antigravity 視窗後降至 75%（可用 4GB），才順利啟動 `line-bridge`。

**3. 真正的根因：隧道網址同步鏈路斷在源頭**

完整鏈路應該是：
bridge.js 啟動 Pinggy SSH 取得新網址
→ start_line_tunnel.js 捕獲網址並寫回 .env.local 的 TUNNEL_URL
→ sync_tunnel_url.js 每 15 秒讀取 TUNNEL_URL
→ 呼叫 Worker 的 /admin/update-tunnel 寫入 KV
→ Worker 依 KV 轉發 LINE 訊息到本機

實際狀態：
- `scripts/start_line_tunnel.js` **檔案不存在**（`scripts/` 目錄完整
  清單中確實沒有這支）
- `scripts/sync_tunnel_url.js` 檔案存在，但 `sync-tunnel` 進程未啟動
- `.env.local` 的四個關鍵變數（`WORKER_URL`、`INTERNAL_GATEWAY_TOKEN`、
  `CURRENT_AGENT_SECRET`、`OUTBOX_SECRET`）**都存在**，未遺失
- 手動啟動 `sync-tunnel` 後，日誌顯示：
  `[Sync Worker] HTTP 200 - 成功更新 URL: https://close-elderly-salem-oct.trycloudflare.com`

**這是最關鍵的證據**：同步機制回報成功（HTTP 200），但同步的是
`.env.local` 裡從 8/9 就沒變過的舊網址（一個早已失效的 Cloudflare
Quick Tunnel 位址）。因為源頭的 `start_line_tunnel.js` 不見了，
沒有任何機制把 Pinggy 產生的新網址寫回 `.env.local`。

**這是靜默失敗的典型案例**：每個環節都「成功」，整條鏈路卻是斷的。

**4. bridge.js 另有一套獨立的更新機制，但也沒生效**
`startPinggyDaemon()` 會監聽 SSH 輸出、用正則抓隧道網址，抓到後直接
`PUT https://api.line.me/v2/bot/channel/webhook/endpoint` 覆寫 LINE
後台設定。但診斷時日誌從未出現任何隧道網址，代表正則沒匹配成功，
這段程式碼從未執行（LINE 後台的 Webhook URL 確認仍是 Worker 網址，
未被覆寫）。

這代表系統中同時存在兩套互斥的隧道方案：
- Worker 派：LINE 後台固定填 Worker，Worker 從 KV 動態轉發
- bridge.js 派：每次隧道變更就直接改 LINE 後台網址
若後者生效，會直接破壞前者的固定門面設計。

### Telegram 對照診斷（實機執行 $$TG連線$$ 完整流程）

執行結果：三個步驟全部成功，無錯誤、無警告。

| 指標 | 數值 | 判讀 |
|---|---|---|
| 狀態 | online | 正常 |
| 重啟次數 | 1（本次診斷手動觸發） | 正常 |
| 記憶體 | 122.5MB（上限設定 300MB） | 安全 |
| Heap Usage | **96.94%** | **偏高，見下方說明** |
| Event Loop Latency | 12.27ms（p95 15.46ms） | 優良 |
| HTTP Mean Latency | 215ms（p95 415ms） | 正常 |

**歷史錯誤**：8/25 19:34 曾出現 `getaddrinfo ENOTFOUND api.telegram.org`
（DNS 解析失敗，屬外部網路中斷），grammY runner 自行重試撐過，
未崩潰、未需重啟，隔日恢復正常。**這證明其錯誤處理是健全的。**

**Heap Usage 96.94% 值得留意**：V8 堆積使用率接近滿載會造成頻繁 GC，
可能導致間歇性卡頓。目前總記憶體用量仍在安全範圍，且已穩定運行 2 天，
不是立即危險，但應在遷移後持續觀察。

## Decision

**本次不修復舊系統**，將診斷結果留痕，待 runtime 層遷移至 HH.AI_v2 時
在新架構中重新設計。理由：Telegram 通道目前穩定運作，貿然修改
`bridge.js` 有波及的風險，而 LINE 已實質棄用，不具急迫性。

### 核心洞察：失效點數量決定穩定度

| | Telegram | LINE |
|---|---|---|
| 連線方式 | Long Polling（主動拉取） | Webhook（被動接收） |
| 需要對外公開網址 | 否 | **是** |
| 需要隧道 | 否 | **是** |
| 動態環節數 | **1**（直連 api.telegram.org） | **4**（bridge→寫 env→sync→KV→隧道） |
| 網路中斷時 | 自動重試，恢復後繼續 | 隧道網址變更即永久斷線 |
| 實際穩定度 | 穩定運行 2 天 | 失效一個月 |

**Telegram 穩定不是因為程式寫得比較好，是因為架構上只有一個失效點。**
這個對照是本次診斷最有價值的發現。

### 遷移 runtime 層時的架構選擇

**不要照搬現有的四環鏈路。** 應優先考慮減少動態環節：

**選項一（推薦）：改用固定網址的隧道服務**
使用 Cloudflare Named Tunnel（需自有網域）或其他提供固定網址的方案。
網址不變 → 不需要 Worker、不需要 KV、不需要同步機制，四個環節縮成一個。
缺點：需要自有網域或付費方案。

**選項二：完成 Worker 方案**
重寫遺失的 `start_line_tunnel.js`，補上「捕獲網址並寫回設定」的環節，
並移除 `bridge.js` 中直接覆寫 LINE Webhook 的邏輯（兩套方案擇一）。
缺點：仍有四個環節，任一環斷掉就是靜默失敗。

**選項三：重新評估 LINE 是否仍需要**
若使用者的實際需求已由 Telegram 完全滿足，可考慮不遷移 LINE 通道，
減少一整條高失效率的鏈路。

**此決策須由使用者在 runtime 遷移前明確拍板，不可預設。**

## Consequences

- 遷移 runtime 前必須先做出上述架構選擇。照搬現有架構等於把
  「四環鏈路 + 兩套互斥方案 + 靜默失敗」的狀態帶進新系統。
- **靜默失敗是這個架構最危險的特性**：`sync-tunnel` 回報 HTTP 200
  成功、`line-bridge` 正常啟動、Pinggy SSH 進程存活——每個環節單獨看
  都是健康的，但訊息就是送不到。新架構必須有端對端的健康檢查機制
  （例如定期自我發送測試訊息並確認收到），而不是只檢查各元件是否存活。
- 記憶體是被低估的因素：16GB 環境下同時執行 Antigravity IDE、Chrome、
  Docker 與多個 Node 常駐進程，餘裕不足 1GB。應記錄各進程的記憶體
  需求（`line-bridge` 約 132MB、`tg-bridge-zero-delay` 約 122MB、
  `sync-tunnel` 約 65MB），並在部署文件中標註最低記憶體需求。
- `tg-daemon` 與 `line-daemon` 兩個 PM2 進程目前都沒有在跑。診斷確認
  `$$TG連線$$` 的流程完全沒用到 `tg-daemon`，其不存在不影響現行運作。
  遷移時應確認這兩個進程是否仍有必要，或已被 `start_*.js` +
  `poll_*.js` 的組合取代。
- `remoat`（telegram-bot-project 內嵌的開源專案）的 Heap Usage 偏高
  （96.94%），遷移後應持續觀察是否有記憶體增長趨勢。
- 本 ADR 與 ADR-0009（Windows Job Object）、ADR-0010（PowerShell 參數
  傳遞）、ADR-0011（雙平台架構演進）、ADR-0014（PM2 設定檔地雷）
  同屬雙平台連線的實戰知識，遷移 runtime 時應五份一起參照。
