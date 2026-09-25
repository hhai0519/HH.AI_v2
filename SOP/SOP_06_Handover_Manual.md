---
title: "Runtime Handover & Service Operations Manual"
version: "3.1.4"
tags: [SOP, Handover, Operations]
dependencies: []
---

# 運行期交接與服務維運標準作業程序 (Runtime Handover & Service Operations SOP)

> **定位：Repeatable Operational Procedure**
> **適用情境**：服務運行期狀態查驗、服務重啟、操作員與代理人間之控制權交接、以及基於客觀現象之故障排除作業。

本標準作業程序（SOP）定義系統在運行環境下的常態維運程序與交接流程。

---

## 1. 目的與權威邊界 (Purpose & Boundaries)

### 1.1 本程序之職責範圍
- **涵蓋範圍**：運行期服務狀態查核（Runtime Availability）、PM2 守護程序管理、操作員與代理人交接控制點、以及基於客觀現象之基礎設施故障排除。
- **排除範圍（本程序不擁有以下事實）**：
  - **專案交接與進度導覽**：由專案總交接文件 [`docs/HANDOVER.md`](../docs/HANDOVER.md) 統籌導覽。
  - **現行進度與審計檢查點**：由交接區 [`docs/refactor-backlog.md` §5](../docs/refactor-backlog.md) 實時導出。
  - **剩餘與下一步任務**：以任務看板 [`docs/TASKBOARD.md`](../docs/TASKBOARD.md) 為唯一權威來源。
  - **核心架構與決策留痕**：由 [`PRINCIPLES.md`](../PRINCIPLES.md) 及 [`docs/adr/`](../docs/adr/) 擁有。
  - **代理人行為約束**：由 [`AGENTS.md`](../AGENTS.md) 及 [`.agents/rules/`](../.agents/rules/) 原生管轄。
  - **`$$` 觸發指令權威**：由 [`SOP/SOP_00A_Master_Index.json`](./SOP_00A_Master_Index.json) 唯一定義，本程序不重複定義指令語意。

> [!NOTE]
> **歷史快照留痕**：本文件淨化前所包含之早期 Argus v6 架構百科、技術棧宣告、視覺設計標準及未來擴充藍圖等歷史內容，已完整保存於不可變快照 [`docs/archive/sop/SOP_06_Handover_Manual-pre-purification-afb5f2.md`](../docs/archive/sop/SOP_06_Handover_Manual-pre-purification-afb5f2.md)。

---

## 2. 執行期可用性前置查驗 (Runtime Preflight Verification)

依據 [`SOP/README.md`](./README.md) 的「執行期可用性邊界（Runtime Availability Boundary）」，在執行任何維運指令前，必須進行實體存在性查驗：

1. **版本庫納管資產（Repo-managed Artifacts）**：
   - 唯有在當前 `origin/main` 根目錄中**實體存在**之檔案與腳本，方可作為現行直接執行的指令依據。
   - 若檔案尚未遷移至版本庫中（如未遷移之 bridge 啟動腳本），該段落僅屬**目標態指引（Target-State Procedure）**，嚴禁假造路徑或直接執行，應路由至 [`docs/TASKBOARD.md`](../docs/TASKBOARD.md) 對應之遷移任務。
2. **外部環境工具（External Environment Dependencies）**：
   - 使用 PM2、Node.js 等外部工具前，必須透過確定性指令（如 `Get-Command pm2`、`node -v`）探測可用性，不得假設特定本機絕對路徑為通用真理。

---

## 3. 人員與代理人操作職責 (Operator & Agent Responsibilities)

- **人類操作員（總管）職責**：
  - 負責作業系統底層設定、全域 PM2 守護程序開機自啟排程與外部網路通道（如 Pinggy/SSH）之建立。
  - AI 代理人**不得**自行安裝未經授權之作業系統服務或執行非受管之底層網路穿透指令。
- **AI 代理人職責**：
  - 負責於基礎設施就緒後進行服務狀態探測、程序可用性確認、排程工作巡檢與數據收集。
  - 涉及程序終止或敏感寫入時，必須遵守 [`SOP/SOP_01_Automation_Process.md`](./SOP_01_Automation_Process.md) 與 [`SOP/SOP_02_Security_Guidelines.md`](./SOP_02_Security_Guidelines.md) 之授權規範。

---

## 4. 服務維運與交接程序 (Service Operations & Handover Procedures)

### 4.1 PM2 守護服務查驗與重啟
PM2 基礎設施預設採系統自動啟動。若維運過程需查驗或重啟服務，依序執行以下步驟：

```powershell
# 1. 指定 PM2 家目錄
$env:PM2_HOME = "$env:USERPROFILE\.pm2"

# 2. 查驗當前受管程序清單與運行狀態
npx pm2 list

# 3. 若特定服務（如 line-bridge）異常，執行重啟
npx pm2 restart line-bridge
```

**狀態判準**：
- 程序之 `status` 欄位必須為 `online`。
- `restart` 次數未呈現異常高頻遞增（避免 crash-loop）。

### 4.2 訊息橋接服務狀態與通訊埠收斂 (Bridge Services State & Port Convergence)
依據 [`docs/adr/0017-port-allocation.md`](../docs/adr/0017-port-allocation.md) 及 [`docs/adr/0022-channel-gateway-architecture.md`](../docs/adr/0022-channel-gateway-architecture.md) 之收斂規範：
- **歷史雙生橋接留痕（Historical / Superseded Context）**：舊架構之 LINE Bridge 歷史使用 Port `3000`、Telegram Bridge 歷史使用 Port `3001`。雙生架構已被 ADR-0022 單一 Channel Gateway 全面取代，3000/3001 不再作為現行單一 Gateway runtime 之固定常駐通訊埠。
- **現行 Channel Gateway v1 規範通訊埠（Canonical Target）**：依 TG-MVP-07 收斂定為 Port `3003`；已由 TG-MVP-11 實作本機迴路 Local API v1，嚴格僅監聽本機 `127.0.0.1`，提供狀態查詢、心跳、輪詢與回覆通道，配套本機客戶端 CLI 工具 `node runtime/channel-gateway/bin/local-api-client.js <subcommand>`（支援 `status`, `takeover`, `poll`, `heartbeat`, `reply`）。若服務啟動中，可透過 `http://127.0.0.1:3003` 或客戶端工具進行健康探測。
- **本地 Web 開發伺服器預留（Reserved）**：未來 Next.js 應用程式預留於 Port `3002`（啟動範例：`npm run dev -- -p 3002`），不得依賴 3000 預設值。

> [!IMPORTANT]
> **目標態標記（TARGET_STATE / 尚未遷移）**：
> 早期手冊提及之 Agent 本地接管指令（如 `start_line.js` 與 `start_tg.js`），其對應之技能目錄（`skills/platform/line-bot-zero-delay/` 及 `skills/platform/telegram-bot-cdp-bridge/`）尚未遷移至當前版本庫。
> 依執行期邊界規範，目前**不得直接執行該指令**；相關遷移進度以 [`docs/TASKBOARD.md`](../docs/TASKBOARD.md) Section E/F 為準。當 Channel Gateway 執行時，本地維運一律使用 `runtime/channel-gateway/bin/local-api-client.js`。

### 4.3 每日交接檢查清單 (Daily Handover Checklist)
操作員或代理人於交接班次時，依序確認以下項目：
- [ ] 執行 `npx pm2 list`，確認所有常駐服務皆為 `online`。
- [ ] 執行 TCP 連線探測（僅限當前實際已部署之活躍服務；若 Channel Gateway 正在執行中，可驗證 `127.0.0.1:3003` 監聽狀態，不得探測外部未授權之通訊埠如 Port 5000）：
  ```powershell
  # 僅在對應服務實體已部署啟動時查驗
  Get-NetTCPConnection -LocalPort 3003 -State Listen -ErrorAction SilentlyContinue
  ```
- [ ] 確認後端服務所需之環境變數（如 API Key）已於執行環境就緒。
- [ ] 確認無未受管之孤兒程序佔用系統資源（參照 [`SOP/SOP_04_Data_Cleanup.md`](./SOP_04_Data_Cleanup.md)）。

---

## 5. 基於客觀現象之故障排除 (Evidence-Based Troubleshooting)

故障排除遵循「可觀察現象 → 確定性檢驗 → 安全處置 → 升級路由」原則：

| 觀察現象 | 確定性檢驗方法 | 安全處置步驟 | 升級與路由 |
|---|---|---|---|
| **PM2 服務狀態顯示 `errored` 或 `stopped`** | 執行 `npx pm2 logs <app-name> --lines 20` 檢視崩潰堆疊 | 檢查相依模組與環境變數，執行 `npx pm2 restart <app-name>` | 若重啟後仍持續崩潰，通知操作員並記錄錯誤訊息 |
| **通訊 Port 衝突（3000 或 3001 被非預期程序佔用）** | `Get-Process -Id (Get-NetTCPConnection -LocalPort 3000).OwningProcess` | 確認程序名稱；若為舊殘留程序，依 [`SOP/SOP_02_Security_Guidelines.md`](./SOP_02_Security_Guidelines.md) 規範安全終止 | 若佔用程序非專案相關，通知操作員協調 Port 衝突 |
| **API 請求遭遇 Rate Limit (HTTP 429)** | 檢視請求錯誤標頭中之 Retry-After 或配額狀態 | 依指數退避策略（Exponential Backoff）等待冷卻時間，暫停高頻請求 | 若配額完全耗盡，通知操作員更新憑證或切換後備路由 |
| **檔案或模組路徑查無實體** | 使用 `Test-Path <path>` 查驗路徑是否存在 | 查閱 [`SOP/README.md`](./README.md) 確認是否屬於尚未遷移之資產 | 路由至 [`docs/TASKBOARD.md`](../docs/TASKBOARD.md) 對應任務，不得憑空發明路徑 |

---

## 6. 維運紀錄與證據 (Operations Evidence)

維運操作與交接動作應保留客觀紀錄：
- 服務啟動與例行重啟狀態保留於 PM2 日誌目錄中。
- 專案層次之程式碼異動與審查狀態，一律記錄於版本庫客觀證據通道（`docs/EXEC-LOG.md`、`docs/AUDIT-LOG.md`、Git commit 與 GitHub Actions）。
- 本程序不建立第二套獨立之審計日誌或任務看板。
