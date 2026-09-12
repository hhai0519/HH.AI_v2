# Claude Control Plane Router

> **Document Role: Router**
> **適用對象：Claude（宏觀審計官／規劃者）**
> **控制平面：Claude Control Plane (`.claude/`)**

本目錄為 Claude Control Plane 的入口路由（Router）。本檔非規範性規則本體，不保存執行狀態、檢查清單項目或規則全文副本。

Claude Control Plane 與 Antigravity Control Plane 是分離、互補且非對稱的兩個獨立控制平面，各自擁有明確的職責與權威邊界，非鏡像對稱結構。

---

## 路由索引 (Routing Index)

### 1. 角色憲法與協作原則
- [PRINCIPLES.md §0](../PRINCIPLES.md) — 雙角色核心憲章：執行者與審計官之職責、邊界與禁止行為。
- [docs/adr/0007-macro-auditor-role.md](../docs/adr/0007-macro-auditor-role.md) — 宏觀審計官角色架構決策紀錄。

### 2. Claude 規範性協定 (Normative Protocol)
- [rules/auditor-protocol.md](rules/auditor-protocol.md) — 宏觀審計官作業協定本體（normative contract）：審計維度、Gatekeeping 查證紀律、提示詞產出標準與生命週期規範。

### 3. Claude 可執行操作清單 (Executable Projection)
- [rules/auditor-selftest.md](rules/auditor-selftest.md) — 宏觀審計官自檢清單（executable selftest / operational projection）：依該檔自身 Trigger Map 於對應時機執行。本清單為 `auditor-protocol.md` 之操作投影，非第二獨立治理權威。

### 4. 專案整體交接與狀態路由
- [docs/HANDOVER.md](../docs/HANDOVER.md) — Project Handover Router：專案整體架構、最新進度、工作板（`docs/TASKBOARD.md`）與交接區（`docs/refactor-backlog.md` §5）之統一切入點。

### 5. 執行者控制平面導航 (Executor Boundary Navigation)
- [AGENTS.md](../AGENTS.md) 及 [.agents/](../.agents/) — Antigravity IDE Agent（執行者）之行為準則與控制平面；控制平面邊界規範詳見 [.agents/rules/role-boundaries.md](../.agents/rules/role-boundaries.md)。
