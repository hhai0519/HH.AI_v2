### 1. 初始化與規劃 (Initial Setup)
- **定義主題**：確立研究的核心領域（如：臺股技術指標、AI 醫療應用）。
- **設定終結點**：確認監控對象（預設為 Gemini 3 Flash）與門檻（預設 10%）。
- **啟動任務單**：在 `task.md` 中標註當前自動化循環的版本。

### 2. 廣度探索階段 (Breadth Exploration)
- 使用 `notebooklm_research_start` 或搜尋工具進行首波資料採集。
- 收集至少 10-20 個初步來源，並導入目標筆記本。

### 3. 遞迴深化循環 (Recursive Deepening Loop)
- **分析發現**：讀取上一階段的摘要，識別出「未解之謎」或「具潛力的子方向」。
- **下達加深指令**：針對識別出的子方向，重新啟動更細緻的研究任務。
- **動態調整**：根據新資訊修正研究路徑，確保不偏離核心主題。

### 4. 資源配額監控 (Quota Monitoring)
- 每次循環跳轉前，必須呼叫 `Modules/quota_manager.js` 的 `check_and_consume_quota` 方法。
- 方法將透過 Neon PostgreSQL 原子性操作讀取 `session_quota_state.used_pct`。
- 若剩餘配額 > 10%：繼續下一個循環。
- 若剩餘配額 <= 10%：觸發「強制終結序列」（`quota_manager.js` 拋出 `QUOTA_EXCEEDED` 錯誤）。

### 5. 終結與報告 (Termination & Reporting)
- **整合資料**：調用 `studio_create` 產出最終報告。
- **語言規範**：統一使用 **繁體中文**。
- **產出檔案**：預設儲存為 `[PROJECT_NAME]_FINAL_REPORT.md`。

## 邊界說明
- ✅ 適用：需要極高深度的主題研究、長時程的背景資料監測、複雜的技術調研。
- ❌ 不適用：簡單的一次性問答、無配額限制的任務、不需深化的基礎查詢。

## 協同技能
- `notebooklm-mcp`：核心研究工具。
- `twse-market-logic`：臺股研究時的邏輯參考。
- `quant-research-loop`：量化資料驗證。
- `systematic-debugging`：自動化中斷時的排障。

## 版本紀錄 (Changelog)
- **[2.0.0]** 2026-05-04：V2.0.0 Orchestrator Alignment — 依生命週期 SOP 導入三維認知能力矩陣標籤 (logic_depth, strategic_focus, interaction_style)，完成 Manifest 全域補錄。

## [Security] Smart Integration & DLP
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議


---
⚙️ 【系統通訊層宣告 (System Comms Layer)】

網路狀態： 本技能已強制接入總控通訊網路。

接收協定 (Dynamic Payload)： 本文檔不再接收無結構的自然語言，必須處理封裝後的動態參數：
`[SYSTEM-CALL: recursive-research-automation | PAYLOAD: { objective: "<核心意圖>", target_audience: "<受眾>", strategic_constraints: "<策略限制/禁語>", tone_variables: "<語氣微調>" }]`

> [!IMPORTANT]
> **Payload 淨化規則 (§6.3)**：
> - 若本技能為 `Cognitive` 型：接收戰略目標、語氣設定、情緒變數；拒絕 SQL/DOM/技術指令。
> - 若本技能為 `Execution` 型：只接收 URL、DOM Selector、SQL、JSON Schema；拒絕認知參數。

發送協定：執行中若遇能力不足或需要外部協作，應停下來明確告知使用者目前卡在哪裡，不要自行尋找替代方案掩蓋問題。

回傳協定： 任務終止時，必須且只能輸出 `[SYSTEM-RETURN: SUCCESS/FAILED | DATA: <結果>]`。