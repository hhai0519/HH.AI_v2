# ADR-0017: Port 分配規範與通訊通訊埠收斂 (Port Allocation & Convergence)

- Status: Accepted (Updated via TG-MVP-07 / 2026-09-22)
- Date: 2026-08-26 (Original), 2026-09-22 (TG-MVP-07 Convergence)

## Context

使用者詢問 LINE 連線、TG 連線與股市分析網頁是否會有 port 衝突。
經歷史查證與 TG-MVP-07 依賴探索，界定歷史背景與現行架構之差異：

### 歷史背景與雙生橋接配置 (Historical Legacy Context)

在早期雙生橋接架構中：
- LINE bridge：使用 Port 3000（`ecosystem.config.js` 的 `env: { PORT: 3000 }`）
- TG bridge：使用 Port 3001（`env: { PORT: 3001 }`，`start_tg.js` 註解標註與 LINE 隔離）
- cloudflared 隧道：歷史上指向 3000

歷史文件（SOP_04、SOP_06、SOP_08）曾記載兩個網頁應用：
- `tw-stock-web`：Next.js 15.2+ (App Router)，Port 3000
- `taiwan-stock`：靜態分析頁面與 Skills Dashboard，Port 8888

2026-08-26 全域查證與 2026-09-22 TG-MVP-07 E24 查證確認：這兩個資料夾在版本庫均已不存在。舊 `.env.example` 早期版本殘留之 `NEXT_PUBLIC_APP_URL=http://localhost:3000` 經 `git ls-files` 確認在 current tracked tree 已完全 ABSENT（tracked env-like paths = NONE）。

### 現行架構與通訊通訊埠衝突收斂需求 (Current v2 Convergence Need)

依據 ADR-0022，Channel Gateway 採單一服務架構，徹底廢除雙生橋接與本機隧道。在確立 Gateway 與後續服務時，必須確立通訊埠單一權威配置，杜絕潛在衝突。

此外，使用者本機工作站存在 repo-external 之「HH.AI_v2 專案進度即時戰情儀表板」，佔用本機 Port 5000（`USER_PROVIDED / NOT_NETWORK_PROBED / REPO_EXTERNAL`）。Playwright 過去內建之常用通訊埠自動掃描曾涵蓋 3000、3001、5000 等，存在非目標探測之潛在風險（B-30）。

## Decision

確立以下通訊埠分配架構，明確區分歷史留痕與現行 v2 收斂規範：

### A. 歷史保留留痕 (Historical Legacy Allocations — Superseded)

| Port | 歷史分配對象 | 現況與定位 |
|---|---|---|
| 3000 | 舊 LINE bridge | 歷史雙生架構留痕；已被 ADR-0022 單一 Gateway 取代，非現行常駐 port |
| 3001 | 舊 TG bridge | 歷史雙生架構留痕；已被 ADR-0022 單一 Gateway 取代，非現行常駐 port |

### B. 現行 v2 通訊埠分配與預留 (Current v2 Convergence)

| Port | 分配對象 | 狀態與約束 |
|---|---|---|
| 3002 | 未來 Next.js 網頁應用 | **預留 (Reserved)**。未來重建網頁應用時於 `package.json` 明確指定 `"dev": "next dev -p 3002"`，不得依賴 3000 預設值 |
| 3003 | Channel Gateway v1 規範通訊埠 (Canonical Local Port) | **已確立分配 (Canonical / Explicit Target)**。Gateway 專屬本地通訊埠。不允許自動回退（no auto fallback）；若發生 collision 必須 fail closed。**本批（TG-MVP-07）不實作 listener**；其 listener 實作與 D24 Local Config 載入分屬 TG-MVP-11 與 TG-MVP-07A |
| 8888 | 靜態分析頁面 / Skills Dashboard | **預留 (Reserved)** |
| 6379 | Redis 工具通訊埠 (Tooling Port) | **已知工具通訊埠 (Known Tooling)**（源自 B-33）。不得分配給 Gateway，本輪不宣稱已部署 |
| 9222 / 9223 | Chrome CDP 工具通訊埠 (Tooling Ports) | **已知工具通訊埠 (Known Tooling)**（源自 B-33）。不得分配給 Gateway，本輪不宣稱已部署 |
| 5000 | 使用者本機儀表板佔用 (Local Occupant) | **使用者本機環境事實 (USER_PROVIDED / NOT_NETWORK_PROBED / REPO_EXTERNAL)**。使用者回報其工作站 Dashboard 佔用本機 port 5000。Gateway 嚴禁選用 5000。此項為目前工作站環境事實，不得擴大描述為可移植之全專案通用預留（not a portable universal reservation） |

### C. Playwright 自動掃描安全收斂 (B-30 Explicit Target Contract)

- `skills/execution/playwright-automation/lib/helpers.js` 的 `detectDevServers` 全面廢除 `commonPorts` 內建掃描清單。
- 呼叫端必須明確傳入 `targetPorts` 陣列；省略、非陣列或空陣列直接 Fail-Closed 拒絕，不發送任何網路探測。
- 僅探測呼叫端顯式指定之通訊埠，嚴禁自主掃描 3000、3001、3002、5000 或任何預設通訊埠。

## Consequences

1. **Gateway Port 規範確立**：Channel Gateway v1 唯一規範通訊埠定為 3003，徹底終結 port 未決狀態（ADR-0022 相關未決文字同步收斂）。
2. **通訊埠衝突隔離**：Gateway (3003)、未來 Next.js (3002)、Dashboard (5000)、Redis (6379)、Chrome CDP (9222/9223) 與歷史 bridge (3000/3001) 各自獨立，互不重疊。
3. **無盲目探測**：Playwright 測試收斂為顯式目標模式，消除對外部運行服務（如 Port 5000 儀表板）造成非預期 probe 的風險。
4. **實作分工邊界**：本 ADR 僅確立規範分配與安全契約；3003 listener 與 D24 Local Config 載入維持由 TG-MVP-11 與 TG-MVP-07A 負責實作，不提前建立網路 socket。
