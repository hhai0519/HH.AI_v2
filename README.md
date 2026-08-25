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
- **[active-inference](./skills/orchestration/active-inference/SKILL.md)** (`orchestration`) — 系統的 System 2 大腦。負責將使用者的自然語言意圖轉化為決定論的狀態機 (SDLC/EARS 語法)，並執行主動推論 (Active Inference) 來預測並最小化專案失敗的風險 (Surprise)。
- **[agency-orchestrator](./skills/orchestration/agency-orchestrator/SKILL.md)** (`orchestration`) — 萬能總管模式（Agency-Agents 最高總管），負責通用意圖解析與全局任務拆解，並執行 4-Phase 狀態機工作流。當遇到複雜任務 (complex task)、新專案建立、系統架構設計、複雜除錯，或發生連續工具錯誤需進行反思 (reflection)、專案告一段落需進行記憶歸檔 (consolidation) 時觸發。
- **[security-auditor](./skills/orchestration/security-auditor/SKILL.md)** (`orchestration`) — 資訊安全與弱點掃描總監。在程式碼合併、API 串接或外部資料處理前，自動執行安全審查。掃描 SQL Injection、XSS、API 密鑰外洩、路徑穿越等高危漏洞。觸發關鍵字：安全掃描、資安審計、弱點掃描、密碼外洩、secret外洩、SQL注入、XSS。
- **[stock-orchestrator](./skills/orchestration/stock-orchestrator/SKILL.md)** (`orchestration`) — 股票與量化領域總管，負責拆解金融任務並調度 06 層級的子模組。
- **[reality-checker](./skills/orchestration/reality-checker/SKILL.md)** (`orchestration`) — 品質保證與幻覺過濾器，負責審核計畫、架構與代碼的技術可行性。
- **[skill-evolution-governor](./skills/meta/skill-evolution-governor/SKILL.md)** (`meta`) — 負責技能生態系統的生命週期管理、DLP 合規審計與系統自我進化。包含自動覆寫技能規範的修復能力。此技能涉及實體檔案變更，必須由使用者明確要求時才可觸發執行。
- **[setup-hhai-skills](./skills/meta/setup-hhai-skills/SKILL.md)** (`meta`) — 一次性的專案初始化與交接設定指南。當接手現有專案、需要了解專案技術棧與目錄結構、或準備開始開發臺股網站功能時手動觸發閱讀。user-invoked。

- **[connect-apps](./skills/platform/connect-apps/SKILL.md)** (`platform`) — 操控 Gmail、Slack、GitHub、Notion 等外部服務執行自動化任務。當使用者要求『在 Slack 發通知』、『建立 GitHub Issue』、『更新 Notion 頁面』、『發送郵件』或『跨系統資料同步』時使用。user-invoked。
- **[postgres](./skills/platform/postgres/SKILL.md)** (`platform`) — 對多個 PostgreSQL 資料庫執行唯讀 SQL 查詢。支援結構探索、資料分析和品質檢查。為確保安全，封鎖所有寫入操作。user-invoked。
- **[mcp-gateway](./skills/platform/mcp-gateway/SKILL.md)** (`platform`) — Zero-Trust 萬用執行閘道器。負責啟動並連接所有的 MCP 伺服器，目前為未實作的設計草案。user-invoked。
- **[notebooklm-mcp](./skills/platform/notebooklm-mcp/SKILL.md)** (`platform`) — 操控 NotebookLM 建立知識庫、進行深度研究與生成報告音頻。當使用者要求『建立 NotebookLM 筆記本』、『製作 Podcast/Audio Overview』、『跨筆記本知識查詢』或『從 URL/PDF 建立知識庫』時使用。

- **[financial-analyst](./skills/analysis/financial-analyst/SKILL.md)** (`analysis`) — 財務分析師，負責估值建模、比率分析與財務風險評估。當需要 valuation (估值)、financial statement (財報分析)、ratio analysis (比率分析) 或 risk assessment (風險評估) 時觸發。
- **[investment-researcher](./skills/analysis/investment-researcher/SKILL.md)** (`analysis`) — 投資研究員，負責台股產業研究、個股基本面與量化趨勢分析。當需要 sector analysis (產業分析)、company research (個股研究) 或 market trend (市場趨勢) 時觸發。
- **[tech-analyzer](./skills/analysis/tech-analyzer/SKILL.md)** (`analysis`) — 專家級的價格形態、量能結構和趨勢指標技術分析。當需要分析技術走勢、支撐壓力位、K線型態、找買賣點、或進行量價背離分析時觸發。
- **[pe-river-map](./skills/analysis/pe-river-map/SKILL.md)** (`analysis`) — 用於長期投資評估的互動式本益比河流圖（PE Band）估值視覺化。當詢問股票貴不貴、本益比河流圖、估值區間、或評估長線買點與目標價時觸發。
- **[bot-account-switcher](./skills/agents/bot-account-switcher/SKILL.md)** (`agents`) — LINE & Telegram 官方帳號雙平台切換工具。user-invoked。
- **[investment-aggregator](./skills/agents/investment-aggregator/SKILL.md)** (`agents`) — Loki Swarm 決策統整專家。彙整 twse-data-analyst (量化) 與 market-researcher (質化) 的數據，產出最終投資報告與風險評估。user-invoked。
- **[twse-data-analyst](./skills/agents/twse-data-analyst/SKILL.md)** (`agents`) — Loki Swarm 量化運算專家。專責處理 TWSE 歷史資料、技術指標與量化運算，嚴格受限於財務資料庫環境。user-invoked。
- **[line-interaction-manager](./skills/agents/line-interaction-manager/SKILL.md)** (`agents`) — Loki Swarm: 第一線溝通總管。專門處理 LINE Bot 介面互動，確保回覆符合品牌語氣，並保護底層金融邏輯不外洩。user-invoked。
- **[market-researcher](./skills/agents/market-researcher/SKILL.md)** (`agents`) — Loki Swarm 基本面研究員。專職閱讀財報、解析 PDF、收集市場新聞情緒，取代舊版脆弱的自動爬蟲腳本。
- **[real-time-stream-orchestrator](./skills/orchestration/real-time-stream-orchestrator/SKILL.md)** (`orchestration`) — 即時串流總指揮。實作 Interactive ReAct 架構，支援非同步「邊想邊說、邊聽邊想」，透過 AG-UI 協定將推演過程即時投影至前端介面（目前為設計願景，尚未有對應實作）。
- **[pdf](./skills/execution/pdf/SKILL.md)** (`execution`) — PDF 文件操作一站式工具箱，涵蓋文字提取、合併拆分、浮水印、加密、表單填寫、圖片提取與掃描 OCR。
- **[xlsx](./skills/execution/xlsx/SKILL.md)** (`execution`) — 提供 Excel (XLSX) 檔案讀寫、多 Sheet 整合與格式化報表生成。
- **[csv-data-summarizer](./skills/execution/csv-data-summarizer/SKILL.md)** (`execution`) — 全自動解析 CSV 或 TSV 資料並產出統計報告與視覺化圖表，支援離群值偵測、相關性熱力圖與時間序列分析。
- **[artifacts-builder](./skills/execution/artifacts-builder/SKILL.md)** (`execution`) — 使用現代前端技術（React、Tailwind CSS、shadcn/ui）建立精細、多組件 HTML 互動原型。
- **[changelog-generator](./skills/execution/changelog-generator/SKILL.md)** (`execution`) — 從 Git 提交紀錄自動生成面向使用者的版本日誌，將技術性 commit 訊息轉換為清晰的發佈說明。
- **[systematic-debugging](./skills/execution/systematic-debugging/SKILL.md)** (`execution`) — 強制執行「先找根本原因、再提修正」的四階段除錯流程。適用於 MCP 連接失敗、工具載入錯誤、npm/pip 安裝失敗等本地環境問題。
