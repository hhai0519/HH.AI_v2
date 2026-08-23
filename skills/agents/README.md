# Agents

RARV 執行型 agent（會實際呼叫工具、寫檔案、發送訊息等）。
這些技能會用到 `type: "action"` / `authorized_mcp_tools` / `semantic_firewall` 擴充欄位，見 AGENTS.md 第 2 節。

## User-invoked

- **[jules-integration](./jules-integration/SKILL.md)** — 將耗時長、Token 消耗大的重構/修復任務委派給雲端 Google Jules 代理人。每日額度僅 5 次，需明確要求才會觸發。
- **[investment-aggregator](./investment-aggregator/SKILL.md)** — Loki Swarm 決策統整專家。彙整 twse-data-analyst (量化) 與 market-researcher (質化) 的數據，產出最終投資報告與風險評估。
- **[twse-data-analyst](./twse-data-analyst/SKILL.md)** — Loki Swarm 量化運算專家。專責處理 TWSE 歷史資料、技術指標與量化運算，嚴格受限於財務資料庫環境。
- **[line-interaction-manager](./line-interaction-manager/SKILL.md)** — Loki Swarm: 第一線溝通總管。專門處理 LINE Bot 介面互動，確保回覆符合品牌語氣，並保護底層金融邏輯不外洩。

## Model-invoked

- **[market-researcher](./market-researcher/SKILL.md)** — Loki Swarm 基本面研究員。專職閱讀財報、解析 PDF、收集市場新聞情緒，取代舊版脆弱的自動爬蟲腳本。
