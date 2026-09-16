# Macro Auditor Control Plane Router

> **Document Role: Router**
> **適用對象：宏觀審計官／規劃者 (Macro Auditor / Planner)**
> **控制平面：Macro Auditor Control Plane (`.claude/`，歷史相容路徑)**

本目錄為 Macro Auditor Control Plane 的入口路由（Router）。依 ADR-0021，本專案之宏觀審計官為資格認定制（qualification-based），`.claude/` 目錄保留為歷史相容實體路徑，不構成特定模型之品牌綁定。本檔非規範性規則本體，不保存執行狀態、檢查清單項目或規則全文副本。

Macro Auditor Control Plane 與 Antigravity Control Plane 是分離、互補且非對稱的兩個獨立控制平面，各自擁有明確的職責與權威邊界，非鏡像對稱結構。

---

## Cold-Start / Recovery Bootstrap

1. **入口定位**：Fresh Macro Auditor（宏觀審計官／規劃者）於 cold-start 或 recovery 時，以本 README 為切入路由。本 README 為倉庫擁有（repo-owned）之正規輕量啟動與復原路由（canonical slim bootstrap / recovery router），絕非規範規則全文之鏡像副本（full rule mirror）。
2. **角色、資格與邊界確認**：進入後應優先依 [PRINCIPLES.md §0](../PRINCIPLES.md) 與 [ADR-0021](../docs/adr/0021-qualification-based-macro-auditor-role.md) 確認雙角色核心憲章、身分邊界、資格條件與禁止行為。確認自身為使用者授權且符合 [`docs/TASKBOARD.md`](../docs/TASKBOARD.md) 之 `**ACTIVE_MACRO_AUDITOR**` 唯一定義者，且非執行者（同 session 互斥）。
3. **規範性協定**：宏觀審計官作業之規範性契約（normative contract）與自檢投影，由 [rules/auditor-protocol.md](rules/auditor-protocol.md) 及 [rules/auditor-selftest.md](rules/auditor-selftest.md) 提供。
4. **專案現況導航**：專案現行狀態嚴禁由本 README 硬編碼取得；必須經由 [docs/HANDOVER.md](../docs/HANDOVER.md) 導向現行權威來源：任務狀態與下一步依 [`docs/TASKBOARD.md`](../docs/TASKBOARD.md)、審計檢查點依 [`docs/refactor-backlog.md` §5](../docs/refactor-backlog.md)、審計紀錄依 [`docs/AUDIT-LOG.md`](../docs/AUDIT-LOG.md)、遠端健康依 Git 與 exact-SHA GitHub Actions。
5. **不變量宣告**：本 README 或任何外部 UI／全域 bootstrap 均不得持久保存動態事實（包含 HEAD、NEXT_WORK、checkpoint、current Macro result、pending range、task queue 副本、CHECK／測試／技能計數、CI Run ID 或暫態執行事實）。
6. **外部指令層約束**：執行環境若存在任何倉庫外部之持久指令層（persistent instruction layer），僅可作為極小啟動路由（minimal bootstrap / router），嚴禁建立 full repo mirror；若外部指令層與倉庫 active contract 產生實質衝突（material conflict），應立即停止 production 工作並依 S1 / 使用者協調處理。

---

## 路由索引 (Routing Index)

### 1. 角色憲法與協作原則
- [PRINCIPLES.md §0](../PRINCIPLES.md) — 雙角色核心憲章：執行者與審計官之職責、資格、邊界與禁止行為。
- [docs/adr/0007-macro-auditor-role.md](../docs/adr/0007-macro-auditor-role.md) — 宏觀審計官角色架構決策紀錄（核心不變量留痕）。
- [docs/adr/0021-qualification-based-macro-auditor-role.md](../docs/adr/0021-qualification-based-macro-auditor-role.md) — 資格認定制宏觀審計官與版本庫可見交接架構（現行架構決策）。

### 2. 宏觀審計官規範性協定 (Normative Protocol)
- [rules/auditor-protocol.md](rules/auditor-protocol.md) — 宏觀審計官作業協定本體（normative contract）：審計維度、Gatekeeping 查證紀律、A1 資格查證、提示詞產出標準與生命週期規範。

### 3. 宏觀審計官可執行操作清單 (Executable Projection)
- [rules/auditor-selftest.md](rules/auditor-selftest.md) — 宏觀審計官自檢清單（executable selftest / operational projection）：依該檔自身 Trigger Map 於對應時機執行。本清單為 `auditor-protocol.md` 之操作投影，非第二獨立治理權威。

### 4. 專案整體交接與狀態路由
- [docs/HANDOVER.md](../docs/HANDOVER.md) — Project Handover Router：專案整體架構、最新進度、工作板（`docs/TASKBOARD.md`）與交接區（`docs/refactor-backlog.md` §5）之統一切入點。
- [docs/TASKBOARD.md](../docs/TASKBOARD.md) — 當前活躍宏觀審計官（`**ACTIVE_MACRO_AUDITOR**`）與下一步工作（`**NEXT_WORK**`）之單一事實來源。

### 5. 執行者控制平面導航 (Executor Boundary Navigation)
- [AGENTS.md](../AGENTS.md) 及 [.agents/](../.agents/) — Antigravity IDE Agent（執行者）之行為準則與控制平面；控制平面邊界規範詳見 [.agents/rules/role-boundaries.md](../.agents/rules/role-boundaries.md)。
