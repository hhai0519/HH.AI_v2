# Agents

RARV 執行型 agent（會實際呼叫工具、寫檔案、發送訊息等）。
這些技能會用到 `type: "action"` / `authorized_mcp_tools` / `semantic_firewall` 擴充欄位，見 AGENTS.md 第 2 節。

## User-invoked

- **[jules-integration](./jules-integration/SKILL.md)** — 將耗時長、Token 消耗大的重構/修復任務委派給雲端 Google Jules 代理人。每日額度僅 5 次，需明確要求才會觸發。

## Model-invoked

_(尚無技能)_
