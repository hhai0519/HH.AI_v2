# ADR-0017: Port 分配規範，為未來重建的網頁應用預留

- Status: Accepted
- Date: 2026-08-26

## Context

使用者詢問 LINE 連線、TG 連線與股市分析網頁是否會有 port 衝突。
查證後確認：

**目前實際運行中的服務**

| 服務 | Port | 來源 |
|---|---|---|
| LINE bridge | 3000 | `ecosystem.config.js` 的 `env: { PORT: 3000 }` |
| TG bridge | 3001 | `env: { PORT: 3001 }`，`start_tg.js` 註解明寫「與 LINE 的 PORT=3000 絕對隔離」 |
| cloudflared 隧道 | 指向 3000 | `tunnel --url http://localhost:3000` |

LINE 與 TG 之間沒有衝突，當初設計時就刻意隔離，程式碼註解可證。

**已消失但文件仍記載的服務**

SOP_04、SOP_06、SOP_08 記載了兩個網頁應用：
- `tw-stock-web`：Next.js 15.2+ (App Router)，Port 3000
- `taiwan-stock`：靜態分析頁面與 Skills Dashboard，Port 8888

2026-08-26 全域查證確認，這兩個資料夾在舊專案與使用者桌面**均已不存在**，
連 `NEXT_PUBLIC_` 字串都搜尋不到。`.env.example` 早期版本的
`NEXT_PUBLIC_APP_URL=http://localhost:3000` 屬過期殘留設定。

**為什麼仍需規範**

使用者明確表示股市分析功能未來會重新啟用，且會與 LINE/TG 通道交疊使用。
兩個功能過去沒有衝突，並非設計正確，而是「開發時間相隔太久、從未同時
運行過」。一旦重建 `tw-stock-web`，Next.js 預設 port 就是 3000，
重建者若沿用預設值，將直接與運行中的 LINE bridge 衝突。

**衝突的後果不會是明顯報錯**

若 Next.js 先啟動佔走 3000，LINE bridge 會啟動失敗（EADDRINUSE，
明顯可見）；但若 LINE bridge 先掛掉、Next.js 佔走 3000，
cloudflared 隧道會把 LINE webhook 轉發到網頁應用，
**訊息靜默消失、不報錯**。這與 ADR-0015 記錄的隧道靜默失敗屬同一類問題。

## Decision

確立以下 port 分配，未來重建網頁應用時必須遵守：

| Port | 分配對象 | 狀態 |
|---|---|---|
| 3000 | LINE bridge | 運行中，**不得變更** |
| 3001 | TG bridge | 運行中，**不得變更** |
| 3002 | 保留給未來的 Next.js 網頁應用 | 預留 |
| 8888 | 保留給靜態分析頁面 / Skills Dashboard | 預留 |

**3000 與 3001 不得變更的理由**：LINE bridge 的 port 與 cloudflared
隧道設定、Cloudflare Worker 的轉發目標綁定，變更需同步修改整條鏈路
（見 ADR-0015 的四環鏈路分析），改動成本與風險遠高於改網頁應用的
啟動參數。

**重建 Next.js 應用時的具體做法**：
在 `package.json` 的 scripts 明確指定 port，不要依賴預設值：
`"dev": "next dev -p 3002"`

## Consequences

- 遷移 runtime 層時，`ecosystem.config.js` 的 port 設定必須原樣保留，
  不可為了「整理」而變更 3000/3001。
- `skills/execution/playwright-automation`（尚未遷移）的
  `lib/helpers.js` 內建自動掃描清單
  `[3000, 3001, 3002, 5173, 8080, 8000, 4200, 5000, 9000, 1234]`，
  會主動探測這些 port 尋找開發伺服器。這代表：
  1. 在 LINE/TG bridge 運行時執行 webapp 測試，playwright 可能誤將
     bridge 當成待測網頁並發送測試請求
  2. 未來的 Next.js 若放在 3002，同樣在掃描範圍內
  遷移 `playwright-automation` 時，應評估是否要排除 3000/3001，
  或改為明確指定目標 port 而非自動掃描。
- SOP_04、SOP_06、SOP_08 中關於 `tw-stock-web` 與 `taiwan-stock` 的
  記載，描述的是已不存在的資料夾。這些 SOP 已遷移至 HH.AI_v2，
  其內容應在重建網頁應用時一併更新，或加註「該資料夾已不存在，
  待重建」的說明。
