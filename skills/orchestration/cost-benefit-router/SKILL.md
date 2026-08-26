---
name: cost-benefit-router
description: "智慧成本效益路由器。取代舊有的配額監控技能。攔截 A2A Envelope 進行預算分析，並根據任務難度演算法 (AdCo/UCB) 動態決定將任務派發給便宜的本地模型或昂貴的頂尖雲端模型。"
---
# Cost Benefit Router

## 功能概述
本技能解決多 Agent 系統最常遇到的「破產危機」，並確保簡單任務不浪費 SOTA (State-of-the-Art) 模型的運算資源。

## 實作邏輯 (Implementation Logic)
1. **A2A Envelope 檢查**: 每次任務派發前，強制攔截檢查 Envelope 內的 `Budget` 欄位與 `Identity`，確保該次執行在預算內且被授權。
2. **啟發式難度判定 (Heuristic Routing)**: 分析 Prompt 複雜度。如果是單純的文字總結或既有 API 呼叫，強制導向 Local/Small 模型；如果是架構級的推演，才導向 SOTA 雲端模型。
3. **Verifiable Reward (反制懶惰)**: 評估每個回覆的因果貢獻 (Causal Influence)。如果某個子 Agent 只會給出「我同意」或沒有實質貢獻的文字，即判為「懶惰 Agent」並阻斷其後續代幣配額。