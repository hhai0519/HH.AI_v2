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
- **[d3js-visualization](./skills/execution/d3js-visualization/SKILL.md)** (`execution`) — 使用 d3.js 建立互動式資料視覺化。適用於客製化圖表、網路圖、地理視覺化，或任何需要對視覺元素、過渡或互動進行精細控制的複雜 SVG 資料視覺化。
- **[webapp-testing](./skills/execution/webapp-testing/SKILL.md)** (`execution`) — 使用 Playwright 互動和測試本地 Web 應用程式的工具包。支援驗證前端功能、偵錯 UI 行為、擷取瀏覽器螢幕截圖以及查看瀏覽器日誌。
- **[mcp-engineer](./skills/execution/mcp-engineer/SKILL.md)** (`execution`) — MCP 開發與環境配置完整生命週期工程師。整合 mcp-builder（建立高品質 MCP 伺服器的標準流程）與 mcp-setup（本地環境設定與排錯）為單一職責技能。觸發關鍵字：建立MCP、MCP伺服器、MCP配置、MCP環境、mcp-builder、mcp-setup。
- **[active-inference](./skills/orchestration/active-inference/SKILL.md)** (orchestration) — 系統的 System 2 大腦。負責將使用者的自然語言意圖轉化為決定論的狀態機 (SDLC/EARS 語法)，並執行主動推論 (Active Inference) 來預測並最小化專案失敗的風險 (Surprise)。
- **[agency-orchestrator](./skills/orchestration/agency-orchestrator/SKILL.md)** (orchestration) — 萬能總管模式（Agency-Agents 最高總管），負責通用意圖解析與全局任務拆解，並執行 4-Phase 狀態機工作流。
- **[security-auditor](./skills/orchestration/security-auditor/SKILL.md)** (orchestration) — 資訊安全與弱點掃描總監。在程式碼合併、API 串接或外部資料處理前，自動執行安全審查。掃描 SQL Injection、XSS、API 密鑰外洩、路徑穿越等高危漏洞。觸發關鍵字：安全掃描、資安審計、弱點掃描、密碼外洩、secret外洩、SQL注入、XSS。
- **[stock-orchestrator](./skills/orchestration/stock-orchestrator/SKILL.md)** (orchestration) — 股票與量化領域總管，負責拆解金融任務並調度 06 層級的子模組。
- **[reality-checker](./skills/orchestration/reality-checker/SKILL.md)** (orchestration) — 品質保證與幻覺過濾器，負責審核計畫、架構與代碼的技術可行性。
