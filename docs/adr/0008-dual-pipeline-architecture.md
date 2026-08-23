# ADR-0008: 技能庫存在兩條平行系統，命名相近不代表職責重複

- Status: Accepted
- Date: 2026-08-20

## Context

在 Batch 5 之後進行的宏觀冗餘掃描（ADR-0007 定義的維度三）中，找出 3 組
名稱或 description 相近、疑似重複的技能候選對：

1. twse-data-analyst（agents/）vs tech-analyzer（analysis/）——都處理
   技術指標
2. market-researcher（agents/）vs investment-researcher（analysis/）——
   名稱極相近，都做「研究」
3. financial-analyst（analysis/）vs investment-aggregator（agents/）——
   description 都提到「投資報告」與「風險評估」

逐一查證後（透過完整讀取 SKILL.md 全文、查證舊專案 SOP 與
agency-orchestrator 的 Phase 角色分派、比對 dependencies 欄位），三組
候選的結論都是 (A) 職責清楚分工，沒有重複邏輯。查證過程中發現一個貫穿
三組候選的共同規律：技能庫裡實際並存著兩條互不隸屬的系統。

## Decision

正式記錄技能庫目前存在的兩條平行系統，供之後審計或新增技能時參考：

**系統一：Loki Swarm 自動化管線**（主要落在 `skills/agents/`）
- 組成：market-researcher（蒐集質化資料）→ twse-data-analyst（計算量化
  指標）→ investment-aggregator（交叉驗證、彙整成最終報告）→
  line-interaction-manager（回覆使用者，尚未遷移）
- 特性：全自動、無人工介入、每個環節都有 `authorized_mcp_tools` 白名單
  與 `disable-model-invocation` 保護（除 market-researcher 外）

**系統二：總管直接呼叫的深度研究工具組**（主要落在 `skills/analysis/`）
- 組成：investment-researcher（產業與趨勢分析）+ financial-analyst
  （估值建模與財務指標計算），兩者搭配使用，由 agency-orchestrator 在
  4-Phase State Machine 的 Phase 1 (Planning) 主動調度
- 特性：互動式、供使用者或總管直接呼叫做深度研究，不是自動化管線的一環

這兩條系統**互不交接資料、互不隸屬**，即使技能名稱或 description 看起來
相近（例如「研究」「分析」「投資報告」「風險評估」這類詞彙重複出現），
也不代表功能重複，不需要合併。

## Consequences

- 往後審計技能時，遇到名稱或功能敘述相近的候選，**先假設可能是這兩條
  平行系統各自的一員，不要預設是重複**，查證方式比照本次：讀完整內文、
  查舊專案 SOP 與 agency-orchestrator 的角色分派、比對 dependencies。
- market-researcher 與 investment-researcher 的 SKILL.md 內文已經各自
  加上「協同邊界」說明，互相標註分工與所屬系統；financial-analyst 與
  investment-aggregator、twse-data-analyst 與 tech-analyzer 這兩組
  目前沒有加類似的內文說明，如果之後發現有人（或 agent）因為名稱相近
  而誤用，可以比照同樣的做法補上邊界說明，但目前判斷不加也不影響理解，
  不強制處理。
- 這個雙系統架構本身沒有寫在任何單一技能文件裡，只存在於這份 ADR，
  如果之後 agency-orchestrator 或 investment-aggregator 的職責有變化，
  記得回來更新這份文件，避免它變成過時的錯誤參考。

## 更新紀錄
- 2026-08-24：本文件 Decision 章節提到 line-interaction-manager「尚未遷移」，
  該技能後續已遷移至 skills/agents/line-interaction-manager/，
  Loki Swarm 管線的四個環節目前狀態為：market-researcher（已遷移）、
  twse-data-analyst（已遷移）、investment-aggregator（已遷移）、
  line-interaction-manager（已遷移）。本註記僅更新事實狀態，
  原始決策內容不變。
