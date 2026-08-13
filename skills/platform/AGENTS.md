<!-- Parent: ../../AGENTS.md -->

# skills/platform

## Purpose

平台整合（LINE/Telegram/MCP/Postgres 等外部串接）。這裡的技能負責跟外部
服務「打交道」，通常涉及認證資訊、連線設定。

## For AI Agents

### 這個資料夾工作時要注意

- 遷移或修改時，注意是否有硬編碼的 API key、connection string、channel token
  混在 SKILL.md 或 scripts/ 裡——這些應該用環境變數，不該進版本控制。
- 這類技能常被 `skills/agents/` 底下的執行型技能呼叫（例如「分析完後發送
  LINE 訊息」），改動介面前先確認有哪些技能依賴它。

### 常見錯誤

- 把「連線設定」跟「業務邏輯」寫在同一個技能裡，導致換一個平台（例如
  LINE 換 Telegram）要動到不該動的分析邏輯。
