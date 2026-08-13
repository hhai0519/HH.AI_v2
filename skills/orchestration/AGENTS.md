<!-- Parent: ../../AGENTS.md -->

# skills/orchestration

## Purpose

流程調度、任務路由、狀態機控制。這裡的技能決定「該呼叫誰」，不實作具體能力。

## For AI Agents

### 這個資料夾工作時要注意

- 這裡的技能通常會被其他技能依賴（尤其 `agency-orchestrator`），改動前先確認
  有沒有其他技能的 SKILL.md 引用了它的行為描述。
- `agency-orchestrator` 是總路由技能：任何時候新增/改名/刪除一個
  user-reachable 技能，都要回來同步更新它的路由說明（見根目錄 AGENTS.md 第 6 節）。
- 這裡的技能一般不直接呼叫外部工具/API，如果你發現某個技能其實會發送訊息、
  寫檔案、下單，它可能該搬去 `skills/agents/`，不該留在這裡。

### 常見錯誤

- 把「調度邏輯」跟「實際執行邏輯」寫在同一個技能裡——調度歸這裡，執行歸
  `skills/agents/` 或 `skills/execution/`。
