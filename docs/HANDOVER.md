# HH.AI_v2 Project Handover Router

> **Document Role: Router**
>
> 本文件不擁有規則、狀態或歷史真實內容。
> 本文件只負責導向各領域的權威來源（canonical source）。
> 若本文件與權威來源衝突，以權威來源為準。

---

## 導覽索引 (Navigation Directory)

### 1. 專案使命與核心原則 (Mission & Principles)
- **專案使命與核心三誡律**：[`MISSION.md`](../MISSION.md)
- **決策與協作原則、文件角色與權威層級**：[`PRINCIPLES.md`](../PRINCIPLES.md)

### 2. 宏觀審計官接手導引 (Macro Auditor / Claude Control Plane)
- **Claude 控制平面總覽**：[`.claude/README.md`](../.claude/README.md)
- **審計官工作協議與核對規範**：[`.claude/rules/auditor-protocol.md`](../.claude/rules/auditor-protocol.md)
- **宏觀審計官自檢清單**：[`.claude/rules/auditor-selftest.md`](../.claude/rules/auditor-selftest.md)

### 3. 執行者接手導引 (Executor / Antigravity Control Plane)
- **專案技能與工程架構規範、統一驗證入口說明**：[`AGENTS.md`](../AGENTS.md)
- **角色分工邊界與最高優先紀律**：[`.agents/rules/role-boundaries.md`](../.agents/rules/role-boundaries.md)
- **提示詞前置檢查規範**：[`.agents/rules/prompt-preflight.md`](../.agents/rules/prompt-preflight.md)
- **Git 操作與版本庫證據通道**：[`.agents/rules/git-and-reporting.md`](../.agents/rules/git-and-reporting.md)
- **執行者規則庫目錄**：[`.agents/rules/`](../.agents/rules/)

### 4. 下一步工作與待辦 (Next Work & Tasks)
- **重構任務看板（唯一的剩餘與下一步工作權威來源）**：[`docs/TASKBOARD.md`](./TASKBOARD.md)
  > 說明：本 Router 不保存待辦清單副本與動態任務值。Fresh Claude 接手尋找下一步工作，一律導航至 `docs/TASKBOARD.md` 讀取 `**NEXT_WORK**` 指標。

### 5. 目前進度與審計狀態 (Current Progress & Audited Checkpoint)
- **交接區與重構紀錄（上次核對通過 checkpoint、Pending-Audit 機械導出方式）**：[`docs/refactor-backlog.md` §5](./refactor-backlog.md)
  > 說明：本 Router 不保存動態 commit hash、pending 範圍或暫態狀態。現行進度與審計檢查點一律即時由 `docs/refactor-backlog.md` §5 導出。

### 6. 作業程序 (Operational SOP)
- **作業程序總索引與執行期邊界**：[`SOP/README.md`](../SOP/README.md)
- **作業程序目錄**：[`SOP/`](../SOP/)

### 7. 技能與能力庫 (Skills & Capabilities)
- **技能架構與總索引**：[`skills/README.md`](../skills/README.md)
- **技能庫目錄**：[`skills/`](../skills/)

### 8. 架構決策紀錄 (Architecture Decision Records)
- **架構決策紀錄目錄**：[`docs/adr/`](./adr/)

### 9. 執行證據與審計紀錄 (Execution Evidence & Audit)
- **執行者本地檢查紀錄**：[`docs/EXEC-LOG.md`](./EXEC-LOG.md)
- **宏觀審計紀錄**：[`docs/AUDIT-LOG.md`](./AUDIT-LOG.md)
- **遠端專案健康權威**：GitHub Actions exact-SHA Verify workflow（見 `docs/adr/0020-github-actions-remote-health-authority.md`）

### 10. 歸檔與歷史資料 (Archive & Historical Material)
- **歸檔總索引**：[`docs/ARCHIVE-INDEX.md`](./ARCHIVE-INDEX.md)
- **歷史交接文件歸檔目錄導覽**：[`docs/archive/handover/README.md`](./archive/handover/README.md)
- **舊版完整交接手冊不可變快照（非現行權威）**：[`docs/archive/handover/HANDOVER-pre-router-568209e.md`](./archive/handover/HANDOVER-pre-router-568209e.md)
  > 警告：歸檔快照僅供追溯歷史脈絡與既有設計依據，不具備現行權威，嚴禁直接依其舊指令操作。

### 11. 規範驗證入口 (Canonical Verification)
- **統一規範驗證入口**：[`scripts/verify_all.py`](../scripts/verify_all.py)
