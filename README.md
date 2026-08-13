# HH.AI Skills

台股分析 + LINE Bot 系統的 agent 技能集合。架構規範見 [AGENTS.md](./AGENTS.md)。

技能分成以下幾個 bucket，每個 bucket 有自己的 README 列出完整清單：

- [`skills/orchestration/`](./skills/orchestration/README.md) — 流程調度、任務路由
- [`skills/analysis/`](./skills/analysis/README.md) — 台股分析、財務模型
- [`skills/agents/`](./skills/agents/README.md) — RARV 執行型 agent
- [`skills/execution/`](./skills/execution/README.md) — 通用工具型技能
- [`skills/platform/`](./skills/platform/README.md) — 平台整合（LINE/Telegram/MCP/DB）
- [`skills/meta/`](./skills/meta/README.md) — 造技能的技能、治理類
- [`skills/deprecated/`](./skills/deprecated/README.md) — 已棄用，僅供參考

## 開發規則

新增或修改任何技能前，先讀 [AGENTS.md](./AGENTS.md)。Antigravity 會在本專案內自動載入這份規則，
但如果你是人類直接編輯檔案，也請務必遵守，並在完成後執行：

```bash
python3 scripts/validate_skills.py
```

## 技能總索引

<!--
遷移或新增技能時，在這裡也要同步加一行，格式：
- **[skill-name](./skills/<bucket>/skill-name/SKILL.md)** (`<bucket>`) — 一行描述
-->

- **[jules-integration](./skills/agents/jules-integration/SKILL.md)** (`agents`) — 將耗時長的重構/修復任務委派給雲端 Google Jules 代理人，每日額度 5 次，user-invoked。

### Execution Skills
- [d3js-visualization](./skills/execution/d3js-visualization/SKILL.md) - Migrated
- [webapp-testing](./skills/execution/webapp-testing/SKILL.md) - Migrated
- [mcp-engineer](./skills/execution/mcp-engineer/SKILL.md) - Migrated
