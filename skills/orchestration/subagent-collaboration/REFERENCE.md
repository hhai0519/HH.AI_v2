## Red Flags（自我檢查清單）

- [ ] (Recipe) Payload 是否足夠精準？有無遺漏關鍵的策略限制？
- [ ] (Subagent) 指令是否包含完整背景？
- [ ] 成功標準是否可驗證？

**絕不允許：**
- 傳遞無結構、模糊的自然語言給 Cognitive Persona。
- 跳過規格審查直接進行品質審查。
- 接受「差不多就好」的結果。

---

## Integration with Other Skills

- **mcp-setup-skill** — 當子代理人任務涉及 MCP 設定時，參考設定格式
- **notebooklm-mcp** — 當任務涉及 NotebookLM 操作時，參考 nlm CLI 指令
- **systematic-debugging-skill** — 當子代理人回報 BLOCKED 超過 2 次時，切換至系統化除錯模式

---

## 版本紀錄 (Changelog)
- **[3.1.0]** 2026-05-04：依 SOP_00_New_Skill_Onboarding §5.2 實裝 `is_onboarding_test` CI/CD 旁路旗標邏輯，徹底解除新技能報到死鎖。PENDING_TYPE 回退機制啟用。
- **[3.0.0]** 2026-05-04：依 SOP §6.3 新增「分層 Payload 淨化機制」說明，實裝型別矩陣與淨化執行流程。版本躍升至 V3.0.0。
- **[1.1.0]** 2026-05-XX：依據 SOP_00 升級，導入 Recipe Mixer 職責，支援 Dynamic Payload 參數裝配與精準 Persona 調度。
- **[1.0.0]** 初始版本，基礎子代理人隔離機制。

## [Security] Smart Integration & DLP
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議


---
⚙️ 【系統通訊層宣告 (System Comms Layer)】

網路狀態： 本技能已強制接入總控通訊網路。

接收協定 (Dynamic Payload)： 本文檔不再接收無結構的自然語言，必須處理封裝後的動態參數：
`[SYSTEM-CALL: subagent-collaboration | PAYLOAD: { objective: "<核心意圖>", target_audience: "<受眾>", strategic_constraints: "<策略限制/禁語>", tone_variables: "<語氣微調>" }]`

> [!IMPORTANT]
> **Payload 淨化規則 (§6.3)**：
> - 若本技能為 `Cognitive` 型：接收戰略目標、語氣設定、情緒變數；拒絕 SQL/DOM/技術指令。
> - 若本技能為 `Execution` 型：只接收 URL、DOM Selector、SQL、JSON Schema；拒絕認知參數。

發送協定：執行中若遇能力不足或需要外部協作，應停下來明確告知使用者目前卡在哪裡，不要自行尋找替代方案掩蓋問題。

回傳協定： 任務終止時，必須且只能輸出 `[SYSTEM-RETURN: SUCCESS/FAILED | DATA: <結果>]`。