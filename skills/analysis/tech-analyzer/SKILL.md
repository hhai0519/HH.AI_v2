---
name: tech-analyzer
description: "專家級的價格形態、量能結構和趨勢指標技術分析。當需要分析技術走勢、支撐壓力位、K線型態、找買賣點、或進行量價背離分析時觸發。"
---

# 技術分析引擎 (Technical Analyzer)

### 【摘要】觸發條件與 DLP 聲明
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議

本技能提供**機構級技術分析能力**，涵蓋 K 線型態識別、量價結構分析、多重均線系統與動能指標解讀，支援日線＋週線＋月線三層次交叉驗證，辨識主力操盤軌跡。

> [!WARNING]
> **全域鐵律：NotebookLM 研究遵從指示**
> 1. 當任務指示「透過 NotebookLM 進行研究/查詢」時，必須嚴格呼叫
>    `notebooklm` 相關 MCP 工具。
> 2. 若遇到無法連線、憑證過期（`auth_status: stale` 或
>    `Authentication expired`）等錯誤時，**絕對禁止**未經同意自行改用
>    常規網路搜尋（Web Search）或其他工具替代。
> 3. 遇到錯誤時，請**立刻中斷動作並主動告知使用者**，請使用者協助登入
>    或修復連線後，再繼續研究任務。

## 🎯 觸發條件
- 需要分析個股的技術走勢、支撐壓力位
- 詢問「這個型態是什麼」「RSI 超買了嗎」「MACD 黃金交叉嗎」
- 需要找股票的切入點（買點）或出場點（賣點）
- 需要進行量價背離分析

## 🛠️ 核心技術框架與細節
由於技術分析涉及大量指標公式與型態判定，包含「均線系統」、「量價分析矩陣」、「經典型態識別程式碼」、「RSI/MACD 動能指標解讀」與「機構級買點識別 3+1 確認法」，請參考並呼叫以下文件：
👉 **[REFERENCE.md](./REFERENCE.md)**

## 🤝 協同技能
- `ownership-cluster`（註：此技能目前僅存在於 Archive，尚未在 HH.AI_v2 中復活，暫時僅供邏輯參考，實際呼叫前需確認該技能是否已遷移或重新建立）：籌碼確認（主力是否真的進場）
- `macro-linkage`（註：此技能目前僅存在於 Archive，尚未在 HH.AI_v2 中復活，暫時僅供邏輯參考，實際呼叫前需確認該技能是否已遷移或重新建立）：確認大環境方向一致
- `pe-river-map`：評估估值安全邊際

---
⚙️ 【系統通訊層宣告 (System Comms Layer)】

網路狀態： 本技能已強制接入總控通訊網路。

接收協定 (Dynamic Payload)： 
`[SYSTEM-CALL: tech-analyzer | PAYLOAD: { objective: "<核心意圖>", target_audience: "<受眾>", strategic_constraints: "<策略限制/禁語>", tone_variables: "<語氣微調>" }]`

發送協定： 執行中若遇能力不足或需外部協作，應停下來明確告知使用者目前卡在哪裡，不要自行尋找替代方案掩蓋問題。必須主動封裝 Dynamic Payload 並發出調閱其他技能。

回傳協定： 任務終止時，必須且只能輸出 `[SYSTEM-RETURN: SUCCESS/FAILED | DATA: <結果>]`。

## 版本紀錄 (Changelog)
- **[4.0.0]** 2026-08-16：遷移至 V2 架構，修復 Zero-Block Policy 問題，將細節拆分至 REFERENCE.md，補回 NotebookLM 全域鐵律。
- **[2.0.0]** 導入 V2 架構，實裝多維度認知矩陣標籤與 Dynamic Payload 預備介面。
