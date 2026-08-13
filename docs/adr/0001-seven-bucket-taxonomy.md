# ADR-0001: 用 7 個 bucket 取代原本的三層數字資料夾

- Status: Accepted
- Date: 2026-08-06

## Context

舊架構是 `01_Orchestrators / 02_Cognitive / 03_Execution / Archive`，且 Archive
內部又是另一套完全不同的分類法（`01_Orchestration / 02_Memory / 03_Integration /
05_Actions / 06_Stock_Analysis`），兩邊大量重名技能。`02_Cognitive` 裡混了「純分析型」
跟「RARV 執行型（會實際呼叫工具）」兩種性質不同的技能，光看資料夾分類猜不出這個
技能會不會有副作用。

## Decision

改用 7 個依「性質」劃分的 bucket：`orchestration / analysis / agents / execution /
platform / meta / deprecated`。判斷一個技能屬於哪個 bucket，不是看它現在放在舊架構
的哪裡，是看它「實際做什麼」——尤其 `analysis`（純分析，無副作用）跟 `agents`
（會實際執行動作）必須嚴格分開，因為 `agents` 底下的技能需要額外的
`authorized_mcp_tools` 白名單機制，這是安全邊界，不是命名喜好。

## Consequences

- 遷移時每個技能都要重新判斷歸類，不能直接照舊路徑對應，增加遷移期的分析工作量。
- 換來的好處：之後新增技能時，只要問「這個技能會不會實際執行外部動作」就能決定
  放 `agents/` 還是 `analysis/`，判斷標準明確，不會像舊架構一樣越堆越亂。
