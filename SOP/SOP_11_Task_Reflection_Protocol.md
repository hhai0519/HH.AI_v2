---
title: "Task Reflection Protocol"
version: "3.1.3"
tags: [SOP, Orchestration, Reflection, Multi-Agent]
dependencies: ["orchestration/agency-orchestrator"]
---
# 任務反思標準作業程序 (Task Reflection Protocol V2.0.0)

**核心準則**：凡執行必留痕，凡錯誤必反思。防範於未然 (Prospective) 優先於事後補救 (Retrospective)。

本 SOP 規範了所有 AI 代理人在高風險決策前，或執行複雜任務結束後的反思、自我修正與經驗總結。反思機制已整併至 orchestration/agency-orchestrator 的「錯誤修正與反思迴圈」章節，詳見 docs/adr/0006-merge-orchestration-skills.md，並透過啟動 Multi-Agent Generator-Critic 架構，建立具備前瞻性與深度的反思迴圈。

## 1. 觸發時機 (When to Reflect)

**事前防範 (Prospective Reflection - PreFlect)**：
- 準備覆寫重要配置檔、發動不可逆指令或執行大範圍刪除前。
- 需要在採取行動前，從記憶庫提取「歷史教訓 (Gotchas)」來檢查當前計畫是否存在重疊風險。

**事後檢討 (Retrospective Reflection)**：
- **異常中斷時**：遇到執行瓶頸、工具調用持續失敗、無法解決的 Bug。
- **過度迴圈時**：發現同一操作邏輯陷入死胡同超過 3 次。
- **成功結案時**：任務圓滿達成，需要提煉可重用的腳本或最佳實踐。

## 2. 5 步執行程序 (The 5-Step Reflexion Loop)

一旦觸發，代理人必須中斷常規思考，遵循 `orchestration/agency-orchestrator` 中定義的反思機制，並依序執行以下 5 個步驟：

1. **初始生成 (Initial Draft)**：
   - Actor 角色基於上下文或歷史記憶提出初版計畫、動作或程式碼。

2. **執行與評估 (Execution & Evaluation)**：
   - 轉為 Critic 角色。嚴謹邏輯家 (Strict Logician) 檢查合規性；懷疑論者 (Skeptic) 檢查安全漏洞與邊界條件。

3. **反思與批判 (Reflection & Critique)**：
   - 轉為 Judge 角色。統整 Evaluator 的意見，產生 **具體且可執行 (Actionable and Specific)** 的建設性批評 (Sour)，並點出應保留的優點 (Sweet)。

4. **策略提煉與修正 (Refinement)**：
   - 回到 Actor 角色，基於 Judge 的回饋生成修正版。
   - 驗證「狀態改變 (State Change)」，確保修改確實解決了報錯或通過了前瞻性檢查。

5. **退出與記憶寫入 (Exit & Memory Logging)**：
   - **硬性約束**：最多循環 3-5 次。若仍失敗，則拋出異常並終止。
   - **長期記憶寫入**：提取最重要的「Lessons Learned」，開啟 `Data/Agent_Reflections.md` 並分類追加寫入（Patterns, Gotchas, Style, or Learnings）。

## 3. 記憶庫提取 (Memory Retrieval)

所有代理人在制定全新任務計畫（Planning Mode）時，**必須**第一時間閱讀 `Data/Agent_Reflections.md`。

此記憶庫等同於系統的「免疫系統」，避免在相同的坑跌倒兩次。
