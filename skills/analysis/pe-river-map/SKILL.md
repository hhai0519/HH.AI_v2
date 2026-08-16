---
name: pe-river-map
description: "用於長期投資評估的互動式本益比河流圖（PE Band）估值視覺化。當詢問股票貴不貴、本益比河流圖、估值區間、或評估長線買點與目標價時觸發。"
---

# PE 河流圖分析 (PE River Map)

### 【摘要】觸發條件與 DLP 聲明
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議

本技能生成個股**歷史本益比（P/E）河流圖**，以 8x / 12x / 16x / 20x / 25x 估值區間為基準，視覺化股價與合理估值的相對位置，提供長線布局的安全邊際判斷。

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
- 詢問「這股票現在貴不貴」「本益比河流圖」「估值區間」
- 需要評估長線買點（股價接近歷史低估區）
- 需要設定長期目標價（以合理 P/E 推算）
- 進行價值投資評估或巴菲特式安全邊際分析

## 📊 估值區間判讀
| PE 位置 | 市場涵義 | 長線操作建議 |
|---|---|---|
| **< 8x** | 極度低估（景氣谷底/恐慌） | 🟢 強力建倉區 |
| **8x ~ 12x** | 低估（悲觀預期） | 🟢 積極買入 |
| **12x ~ 16x** | 合理估值 | 🟡 持倉觀望 |
| **16x ~ 20x** | 輕微高估 | 🟡 減少加碼 |
| **> 20x** | 高估（泡沫風險） | 🔴 考慮減持 |
| **> 25x** | 嚴重高估 | 🔴 大幅減持 |

## 🛠️ 核心計算邏輯與程式碼
包含「河流圖核心計算 Python 腳本」與「EPS 趨勢分析滾動預測演算法」，請參考並呼叫以下文件：
👉 **[REFERENCE.md](./REFERENCE.md)**

## 🤝 協同技能
- `tech-analyzer`：PE 低估 + 技術底部確認 = 最佳長線進場
- `ownership-cluster`（註：此技能目前僅存在於 Archive，尚未在 HH.AI_v2 中復活，暫時僅供邏輯參考，實際呼叫前需確認該技能是否已遷移或重新建立）：主力籌碼是否配合估值低點吸籌
- `quant-research-loop`：PE 策略的回測驗證

---
⚙️ 【系統通訊層宣告 (System Comms Layer)】

網路狀態： 本技能已強制接入總控通訊網路。

接收協定 (Dynamic Payload)：
`[SYSTEM-CALL: pe-river-map | PAYLOAD: { objective: "<核心意圖>", target_audience: "<受眾>", strategic_constraints: "<策略限制/禁語>", tone_variables: "<語氣微調>" }]`

發送協定： 執行中若遇能力不足或需外部協作，應停下來明確告知使用者目前卡在哪裡，不要自行尋找替代方案掩蓋問題。必須主動封裝 Dynamic Payload 並發出調閱其他技能。

回傳協定： 任務終止時，必須且只能輸出 `[SYSTEM-RETURN: SUCCESS/FAILED | DATA: <結果>]`。

## 版本紀錄 (Changelog)
- **[4.0.0]** 2026-08-16：遷移至 V2 架構，修復 Zero-Block Policy 問題，將細節拆分至 REFERENCE.md，補回 NotebookLM 全域鐵律。
- **[3.0.0]** 2026-05-04：V2.0.0 Polymorphic Labeling Migration。
