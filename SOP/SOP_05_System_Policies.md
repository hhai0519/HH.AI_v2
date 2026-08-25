---
title: "系統核心治理政策"
version: "3.2.0"
tags: ["SOP", "系統政策", "治理", "Watchdog", "Governance"]
dependencies: [".agents/rules/skill-engineering-guardrails.md", "Modules/db_state_manager.js"]
---

# 本協作系統 系統核心治理政策 (System Governance Policies)

本文件規範 本協作系統 系統最頂層的核心治理規則，所有 Agent 技能與自動化流程均須無條件遵守。

---

### 🚫 絕對禁止事項 (Anti-Patterns) [HARD CONSTRAINTS]

> [!CAUTION]
> **觸犯以下禁止事項，系統將立即判定任務失敗 (Task Failed)，並啟動斷路器強行中斷 Session。**

1. **PM2 官方特許清單與背景進程治理 (V3)**
   - PM2 僅可用於管理以下 **6 個** 官方認可的常駐進程：
     1. `line-bridge` (LINE Webhook 接收與駐留)
     2. `tg-bridge-zero-delay` (TG 橋接伺服器)
     3. `line-daemon` (LINE 背景自主監聽守護者)
     4. `tg-daemon` (TG 背景自主監聽守護者)
     5. `line-tunnel` (Cloudflare 活體隧道)
     6. `sync-tunnel` (隧道網址自動同步器)
   - **嚴禁**在 PM2 中新增上述清單以外的任何 App。
   - **輪詢與計時器規範**：嚴禁 Agent 在任務腳本中使用 `setInterval` 或 `setTimeout` 建立私有的背景常駐輪詢。
     - **豁免條款**：屬 PM2 官方特許進程 (如 `sync-tunnel`) 內部運作所需的 `setInterval` 定時邏輯，不受此限。
2. **禁止破壞性 Git 指令 (Destructive Commands)**
   - **嚴禁**在腳本內寫死或執行 `git checkout .`、`git reset --hard`、`rm -rf` 等具有歷史抹除與物理破壞性的暴力還原指令。
3. **禁止終端機越權寫入 (Unsafe File Writing)**
   - **嚴禁**在終端機使用 PowerShell 的 `Out-File`、`Set-Content` 或 `>` 重導向來寫入程式碼或檔案。
   - 所有寫入操作強制使用專用 API 工具 (`write_to_file`)，並確保為 **無 BOM 的標準 UTF-8** 編碼。
4. **禁止檔案型跨進程通訊 (No File-Based IPC)**
   - **嚴禁**以「寫入暫存 `.txt` 或 `.json` 再由另一個程式讀取」的方式進行跨進程資料傳遞。
   - **唯一合法作法**：強制使用記憶體串流 `stdio: ['pipe', 'pipe', 'pipe']`，或透過本機 HTTP API / WebSocket 進行傳遞。

5. **嚴禁 PowerShell 隱形母體 (No Hidden PowerShell Daemons)**
   - **嚴禁**使用 PowerShell 的 `-WindowStyle Hidden` 啟動任何需要長期常駐的背景服務。
   - **唯一合法作法**：背景隱藏進程必須統一由 Node.js 發動 `child_process.spawn()` 並強制帶入 `{ windowsHide: true }` 旗標。

6. **強制實作進程連坐法 (Process Synergy — Full Signal Coverage)**
   - 任何由 Node.js 衍生的子進程，**強制要求**同時掛載以下三個信號監聽器：
   - `process.on('exit', fn)` — 正常退出清理
   - `process.on('SIGINT', fn)` — 使用者 Ctrl+C 中斷清理
   - `process.on('SIGTERM', fn)` — 系統終止信號清理

### 🔒 工具呼叫狀態綁定 (Slot-filling Verification)
Agent 在調用任何檔案寫入或終端指令前，**必須**動態填充並核對以下狀態插槽 (Slots)。狀態不符者立即中斷操作：
- `[Current Workspace Root]`: 確認目標路徑是否在預期且合法的技能目錄內。
- `[Intended Write Encoding]`: 寫入前強制確認預期編碼為 UTF-8 (無 BOM)。

---

## 1. Watchdog 非同步巡檢機制 [HIGHEST_PERMISSION]

> [!IMPORTANT]
> **V3.2.0 架構宣告**：系統已全面採用**非同步 Watchdog Hook 機制與 Neon DB 佇列**。
> 詳細機制與優先級處置規則，請參閱：`docs/adr/0013-watchdog-async-buffer-neon-db.md`。

---

## 2. 通訊授權管理政策

### 2.1 語言規定
- 所有 Agent 輸出的對話回覆、規劃文件與正式報告，必須使用**台灣正體中文**撰寫。
- 允許保留英文技術術語縮寫（如 API、SOP、YAML），但說明性段落須以正體中文撰寫。

---

## 3. 嚴格配額監控政策

- 本系統所有自動化任務皆須遵守 10% 配額安全熔斷機制。
- 超出警戒線時，Agent 必須立即暫停任務並通知使用者，禁止自行決策繼續執行。
- 配額監控相關規範詳見 `SOP_01_Automation_Process.md §2.2`。

---

## 4. 跨平台編碼與檔案規範 (Cross-Platform Encoding Protocol)

### 4.1 零容忍編碼政策
- **唯一合法編碼**：系統內所有的文字檔案（包含 `*.md`, `*.json`, `*.py`, `*.js`, `*.ps1` 等）**強制使用 UTF-8 (無 BOM)** 格式儲存。唯一特許例外：主選單 `00_Master_Menu.ps1` 為了相容 Windows PowerShell 5.1 的解釋器限制，強制採用 UTF-8 with BOM 格式儲存。
- **BOM 字元防範**：嚴禁檔案中出現 `\uFEFF` (BOM) 字元。任何因工具（如 Windows 記事本）自動附加 BOM 所導致的損壞，系統一旦發現必須立即進行無 BOM 清洗作業。
- **跨平台相容**：行尾符號（Line Endings）應盡量保持標準化（如預設 LF 或相容 CRLF），但在任何修改與寫入操作中，絕對禁止引入非標準或混合編碼。

---

## 5. 技能目錄與命名空間治理 (Namespace Governance)

### 5.1 架構層級劃分
- 所有技能實體必須存放於 `skills/` 目錄，並嚴格歸類於以下主目錄：
  - `orchestration/`
  - `analysis/`
  - `agents/`
  - `execution/`
  - `platform/`
  - `meta/`
  - `deprecated/`

### 5.2 嚴格 1:1 映射原則（無前綴）

> [!CAUTION]
> **V3.1.3 架構宣告：強制前綴政策（`sys-*`, `finance-*`, `tool-*`, `persona-*`）已正式廢除。**
> 任何文件中仍保留相關前綴規定者，視為過期條文，一律忽略。

- **命名規則**：技能實體目錄名稱必須與該技能 `SKILL.md` YAML 標頭的 `name` 欄位**完全一致（1:1 映射）**，不得加入任何前綴、後綴或縮寫。唯一歷史遺留特許：`skills/execution/tool-executor（尚未遷移至 HH.AI_v2，此為預計路徑）` 為了避免協作鏈中斷，保留其原有名稱不進行強制變更。
- **技能分類管理**：所有技能的分類、標籤與所屬層級，統一由各 bucket 的 README.md 集中管理。SOP 文件中禁止重複維護靜態分類列表。
- **合規驗證**：新增或更名技能後，必須確認該技能已正確列入所屬 bucket 的 README.md 索引，且連結路徑與實體目錄一致，否則視為架構違規。

### 5.3 索引絕對同步原則
- 各 bucket 的 README.md 必須與物理檔案系統 (`skills/`) 維持 100% 的絕對同步。
- 若發生目錄重命名、移動或新增，必須在同一操作週期內更新所屬 bucket 的 README.md 與根目錄 README.md 的技能總索引，否則將觸發系統中斷與 Watchdog 錯誤。

---

## 6. 系統備份與版本控制規範 (System Backup Protocol)

### 6.1 GitHub 遠端備份政策
- **常態性版控**：工作區內的所有原始碼、設定檔及 SOP 文件，必須全面納入 Git 版本控制，並定期執行 `git commit`。
- **單一真實來源**：所有變更應定期推送 (Push) 至指定的 GitHub 專案（如 origin main），確保系統環境、知識庫及架構資產具備異地備援與可溯源性。
- **執行要求**：進行系統更新或大規模架構重構前，必須強制執行備份推送至遠端，並確認提交流程順利（無卡在 `COMMIT_EDITMSG` 等中斷狀態）。

---

## 7. 技能不刪除原則 (No-Delete Policy) [HIGHEST_PERMISSION]

> [!CAUTION]
> 關於技能的刪除、修改與歸檔，請一律遵守 `.agents/rules/skill-engineering-guardrails.md` 中的「統一歸檔與差異化刪除政策」。本節舊有規範已廢除。
