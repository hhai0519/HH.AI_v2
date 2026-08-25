---
title: "自動化與深度研究標準作業程序"
version: "3.1.3"
tags: ["SOP", "自動化", "深度研究", "Automation"]
dependencies: []
---

# 自動化與深度研究標準作業程序 (Automation & Deep Research SOP)

**版本**：3.1.3 ｜ **更新日期**：2026-05-04（更新於 2026-05-04）
**通訊語言**：台灣正體中文（強制規定）

---

## 1. 目的

本 SOP 規範 本協作系統 系統執行自動化任務時的標準作業流程，確保每一次深度研究任務皆具備明確授權、可追蹤性，並與現行治理架構保持一致性。

---

## 2. 核心原則 (Core Principles)

### 2.1 通訊語言原則
- **強制規定**：所有 Agent 撰寫的對話回覆、規劃文件（Dialogue）、實作計畫（Implementation Plan）、頂層 SOP 規範，以及技能描述（SKILL.md）皆須使用**台灣正體中文**。
- 工件標題與專業術語允許保留英文縮寫，但說明段落必須以正體中文撰寫，禁止使用英文或簡體中文替代。

### 2.2 配額監控原則（10% 安全法則）

> [!IMPORTANT]
> **V3.1.3 升級宣告**：配額管理機制已全面廢棄 `current_quota.tmp` 檔案系統與 `quota_monitor.py` Python 腳本，改採 **Neon PostgreSQL 原子性資料庫操作**，徹底解決多 Agent 協作時的 Race Condition。

**配額監控實作**：系統已全面採用 Neon PostgreSQL 進行狀態管理。所有 Agent 執行任務前，必須呼叫 `Modules/quota_manager.js` 中的 `check_and_consume_quota` 方法。利用資料庫的原子性操作防止併發造成的 Race Condition。一旦單一 Session 消耗超過 10%，資料庫將拒絕寫入並拋出 `QUOTA_EXCEEDED` 錯誤，強制觸發任務暫停。

**核心 SQL 機制**（位於 `check_and_consume_quota`）：
```sql
-- Step 1：取得行級鎖，防止 Phantom Read
SELECT used_pct FROM session_quota_state
  WHERE session_id = $1 FOR UPDATE;

-- Step 2：超標則 ROLLBACK；未超標則原子性累加
UPDATE session_quota_state
  SET used_pct   = used_pct + $1,
      updated_at = NOW()
  WHERE session_id = $2
  RETURNING used_pct;
```

**緊急流程**（QUOTA_EXCEEDED 觸發後）：
1. `quota_manager.js` 拋出 `err.code = 'QUOTA_EXCEEDED'`，強制中斷當前 Agent 執行
2. 呼叫端捕獲錯誤，執行快速摘要存檔
3. 更新 `task.md` 標記當前進度
4. 等待使用者確認後恢復執行


### 2.3 遞迴深化原則 (Recursive Deepening)
- 深度研究任務採用遞迴迭代策略，每一輪產出為下一輪的輸入。
- 每個研究主題建議執行 **3-5 輪深化迭代**。
- 使用 `task.md` 追蹤每輪研究進度與關鍵發現。

### 2.4 強制授權協議 (Strong Authorization Protocol)

> [!IMPORTANT]
> **授權觸發規則**：系統中任何涉及破壞性操作或批量自動化任務，必須取得使用者明確授權（透過 `$$自動化$$` 關鍵字觸發）。

| 關鍵字 | 授權範圍 | 執行限制 |
|--------|---------|---------|
| `$$自動化$$` | 啟動深度研究迴圈 | 僅允許讀取與研究操作 |
| `$$Allow All$$` | 啟動全域工具授權 | 僅活躍會話期間有效 |

- **關鍵字驗證**：未包含上述明確關鍵字時，拒絕執行批量自動化。
- **誤觸保護**：錯誤觸發時，立即終止並通報使用者。

---

## 3. 操作流程 (Operational Flow)

### 3.1 任務初始化 (Initialization)
1. **Notion 任務獲取**：從 Notion 的 Command Center 資料庫獲取任務票卡 (Ticket)，並標記 `Agent_Lock` 為處理中，防止衝突。
2. 建立任務工件：`implementation_plan.md` 與 `task.md`。
3. 確認授權關鍵字 `$$自動化$$` 已取得。
4. 確認配額監控工具與 Watchdog Hook 就緒。
   ```powershell
   # @EXECUTE
   # [A-1 修復] 已廢棄 Python 腳本，改用 Neon PostgreSQL 原子性操作
   # 配額監控已整合至 Modules/quota_manager.js，無需手動執行獨立腳本
   # 確認方式：檢查 Neon DB session_quota_state 資料表的 used_pct 欄位
   # node -e "const qm = require('./Modules/quota_manager.js'); qm.check_and_consume_quota(process.env.SESSION_ID, 0).then(r => console.log('[配額狀態]', r));"
   ```
5. 確認研究方向與關鍵問題清單。
6. **GitHub 分支建立**：針對該任務建立對應的 GitHub Feature Branch，準備後續作業。

### 3.2 研究執行迴圈 (Execution Loop)
1. **收集**：透過 NotebookLM 與網頁搜尋取得原始資料。
2. **分析**：呼叫認知層技能進行深度解讀。
3. **驗證**：與現有知識庫交叉核對，消除矛盾。
4. **評分**：記錄置信度，標記 0-100% 可信度分級。
5. **決策**：若置信度不足，自動觸發下一輪深化研究。

### 3.3 成果輸出 (Reporting)
- 輸出格式依研究類型分為：摘要報告、完整分析報告、策略建議書。
- 報告命名規範：`TAIWAN_STOCK_REPORT_YYYYMMDD_vFinal.md`
- 報告存放路徑：`./docs/reports/`

---

## 4. 例外處理 (Exception Handling)

| 例外類型 | 觸發條件 | 建議處置 |
|---------|---------|---------|
| API 限流 | 請求回傳 429 錯誤 | 啟用指數退讓策略（見 §2.2 流程） |
| 配額超標 | 單會話消耗超過 10% | 立即暫停並等待使用者確認 |
| 研究死鎖 | 任務無法產出有效輸出 | 深度研究方向改以備用知識庫替補 |
| 工具失效 | 瀏覽器 / MCP 連線中斷 | 切換至無頭模式（headless: true） |

---

## 5. 可信工具與環境 (Trusted Tools & Environments)

### 5.1 工具授權管理
- **長效授權快取**：若工具需要 `$$Allow All$$` 授權，在「設定 → Always allow」中永久存檔。
- **授權步驟**：
  1. 出現 `Opening URL in browser` 提示時點選「Configure」。
  2. 勾選 `Always allow ... to open localhost:XXXX`。
  3. **重要提醒**：啟用 `$$Allow All$$` 後，所有工具授權詢問將自動通過。

### 5.2 自動化執行模式 (Headless Mode)
- **原則**：有人監督的正式工作流程中，瀏覽器需顯示介面以確認操作正確性。
- **例外**：Playwright 測試腳本執行 `headless: true`，除非需要除錯時切換為 `false`。

---

## 6. Skills 資料夾路徑對照

### 6.1 路徑設定（v260503 版）
| 名稱 | 路徑 | 備註 |
|------|------|------|
| 本協作系統 官方技能庫 | `<USER_HOME>\.gemini\本協作系統\skills\` | 系統核心技能（不可隨意修改） |
| 專案本地技能目錄 | `HH.AI_v2/skills/` | 本地擴充技能 |

### 6.2 核心技能清單 (Core Skills Inventory)

目前系統技能數量動態維護於各 bucket 下的 README.md 索引，以下為關鍵技能摘要：

| Skill | 功能說明 |
|-------|---------|
| `autoresearch-agent` | 自動化研究代理人：負責 CPU/GPU 超參數調優（尚未遷移至 HH.AI_v2，此為預計名稱） |
| `meta/skill-creator` | 女媧造人：自動深度調研並生成新 Skill 技能框架（尚未遷移至 HH.AI_v2，此為預計路徑） |
| `recursive-research-automation` | 遞迴深度研究自動化執行器（尚未遷移至 HH.AI_v2） |
| `orchestration/cost-benefit-router` | API 配額與成本監控路由（尚未遷移至 HH.AI_v2，此為預計路徑） |
| `execution/mcp-engineer` | MCP 伺服器配置與排錯 |
| `execution/webapp-testing` | Web App 自動化測試 |
| `platform/notebooklm-mcp` | NotebookLM MCP 整合操作指南 |

### 6.3 合規要求
- **DLP 防護**：`SKILL.md` 禁止直接嵌入任何 API Key 或敏感憑證。
- **語言合規**：所有 SOP 說明必須確認語言設定，嚴格使用**台灣正體中文**。

---

*本 SOP 建立於 2026-04 ｜ v3.1.3 更新於 2026-05-04（更新於 2026-05-04）*
