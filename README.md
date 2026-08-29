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

- **[jules-integration](./skills/agents/jules-integration/SKILL.md)** (`agents`) — 將耗時長的重構/修復任務委派給雲端 Google Jules 代理人，每日額度 100 次，user-invoked。
- **[d3js-visualization](./skills/execution/d3js-visualization/SKILL.md)** (`execution`) — 使用 d3.js 建立互動式資料視覺化。適用於客製化圖表、網路圖、地理視覺化，或任何需要對視覺元素、過渡或互動進行精細控制的複雜 SVG 資料視覺化。
- **[webapp-testing](./skills/execution/webapp-testing/SKILL.md)** (`execution`) — 使用 Playwright 互動和測試本地 Web 應用程式的工具包。支援驗證前端功能、偵錯 UI 行為、擷取瀏覽器螢幕截圖以及查看瀏覽器日誌。
- **[mcp-engineer](./skills/execution/mcp-engineer/SKILL.md)** (`execution`) — MCP 開發與環境配置完整生命週期工程師。整合 mcp-builder（建立高品質 MCP 伺服器的標準流程）與 mcp-setup（本地環境設定與排錯）為單一職責技能。觸發關鍵字：建立MCP、MCP伺服器、MCP配置、MCP環境、mcp-builder、mcp-setup。
- **[active-inference](./skills/orchestration/active-inference/SKILL.md)** (`orchestration`) — 系統的 System 2 大腦。負責將使用者的自然語言意圖轉化為決定論的狀態機 (SDLC/EARS 語法)，並執行主動推論 (Active Inference) 來預測並最小化專案失敗的風險 (Surprise)。
- **[agency-orchestrator](./skills/orchestration/agency-orchestrator/SKILL.md)** (`orchestration`) — 萬能總管模式（Agency-Agents 最高總管），負責通用意圖解析與全局任務拆解，並執行 4-Phase 狀態機工作流。當遇到複雜任務 (complex task)、新專案建立、系統架構設計、複雜除錯，或發生連續工具錯誤需進行反思 (reflection)、專案告一段落需進行記憶歸檔 (consolidation) 時觸發。
- **[cost-benefit-router](./skills/orchestration/cost-benefit-router/SKILL.md)** (`orchestration`) — 在動態實驗或複雜研究中評估預算與成本，判斷是否繼續深入。
- **[epistemic-state-governor](./skills/orchestration/epistemic-state-governor/SKILL.md)** (`orchestration`) — 認知狀態管制官，監控推演健康度並在幻覺時強制介入。
- **[recursive-research-automation](./skills/orchestration/recursive-research-automation/SKILL.md)** (`orchestration`) — 執行遞迴式深度研究，涵蓋廣度掃描與深度收斂。
- **[subagent-collaboration](./skills/orchestration/subagent-collaboration/SKILL.md)** (`orchestration`) — 調用子代理人（Sub-Agent）協助完成專業領域分析或創作。
- **[security-auditor](./skills/orchestration/security-auditor/SKILL.md)** (`orchestration`) — 資訊安全與弱點掃描總監。在程式碼合併、API 串接或外部資料處理前，自動執行安全審查。掃描 SQL Injection、XSS、API 密鑰外洩、路徑穿越等高危漏洞。觸發關鍵字：安全掃描、資安審計、弱點掃描、密碼外洩、secret外洩、SQL注入、XSS。
- **[stock-orchestrator](./skills/orchestration/stock-orchestrator/SKILL.md)** (`orchestration`) — 股票與量化領域總管，負責拆解金融任務並調度 analysis/ 層的專業技能。
- **[reality-checker](./skills/orchestration/reality-checker/SKILL.md)** (`orchestration`) — 品質保證與幻覺過濾器，負責審核計畫、架構與代碼的技術可行性。
- **[skill-evolution-governor](./skills/meta/skill-evolution-governor/SKILL.md)** (`meta`) — 負責技能生態系統的生命週期管理、DLP 合規審計與系統自我進化。包含自動覆寫技能規範的修復能力。此技能涉及實體檔案變更，必須由使用者明確要求時才可觸發執行。
- **[setup-hhai-skills](./skills/meta/setup-hhai-skills/SKILL.md)** (`meta`) — 一次性的專案初始化與交接設定指南。當接手現有專案、需要了解專案技術棧與目錄結構、或準備開始開發臺股網站功能時手動觸發閱讀。user-invoked。

- **[connect-apps](./skills/platform/connect-apps/SKILL.md)** (`platform`) — 操控 Gmail、Slack、GitHub、Notion 等外部服務執行自動化任務。當使用者要求『在 Slack 發通知』、『建立 GitHub Issue』、『更新 Notion 頁面』、『發送郵件』或『跨系統資料同步』時使用。user-invoked。
- **[postgres](./skills/platform/postgres/SKILL.md)** (`platform`) — 對多個 PostgreSQL 資料庫執行唯讀 SQL 查詢。支援結構探索、資料分析和品質檢查。為確保安全，封鎖所有寫入操作。user-invoked。
- **[mcp-gateway](./skills/platform/mcp-gateway/SKILL.md)** (`platform`) — Zero-Trust 萬用執行閘道器。負責啟動並連接所有的 MCP 伺服器，目前為未實作的設計草案。user-invoked。
- **[notebooklm-mcp](./skills/platform/notebooklm-mcp/SKILL.md)** (`platform`) — 操控 NotebookLM 建立知識庫、進行深度研究與生成報告音頻。當使用者要求『建立 NotebookLM 筆記本』、『製作 Podcast/Audio Overview』、『跨筆記本知識查詢』或『從 URL/PDF 建立知識庫』時使用。
- **[langsmith-fetch](./skills/platform/langsmith-fetch/SKILL.md)** (`platform`) — 從 LangSmith 獲取執行追蹤以偵錯 Agent 行為。
- **[json-to-flex-renderer](./skills/platform/json-to-flex-renderer/SKILL.md)** (`platform`) — 將 JSON 分析報告純程式化轉換為 LINE Flex Message。

- **[financial-analyst](./skills/analysis/financial-analyst/SKILL.md)** (`analysis`) — 財務分析師，負責估值建模、比率分析與財務風險評估。當需要 valuation (估值)、financial statement (財報分析)、ratio analysis (比率分析) 或 risk assessment (風險評估) 時觸發。
- **[investment-researcher](./skills/analysis/investment-researcher/SKILL.md)** (`analysis`) — 投資研究員，負責台股產業研究、個股基本面與量化趨勢分析。當需要 sector analysis (產業分析)、company research (個股研究) 或 market trend (市場趨勢) 時觸發。
- **[tech-analyzer](./skills/analysis/tech-analyzer/SKILL.md)** (`analysis`) — 專家級的價格形態、量能結構和趨勢指標技術分析。當需要分析技術走勢、支撐壓力位、K線型態、找買賣點、或進行量價背離分析時觸發。
- **[pe-river-map](./skills/analysis/pe-river-map/SKILL.md)** (`analysis`) — 用於長期投資評估的互動式本益比河流圖（PE Band）估值視覺化。當詢問股票貴不貴、本益比河流圖、估值區間、或評估長線買點與目標價時觸發。
- **[evidence-collector](./skills/analysis/evidence-collector/SKILL.md)** (`analysis`) — 證據收集官，負責為所有決策提供事實支撐、鏈接與原始數據。當需要 find evidence、verify stats、source check 或 market research 時觸發。
- **[software-architect](./skills/analysis/software-architect/SKILL.md)** (`analysis`) — 軟體架構師，負責系統高層設計、模式定義與技術選型。當需要 architecture design、design pattern 或 system structure 時觸發。
- **[backend-architect](./skills/analysis/backend-architect/SKILL.md)** (`analysis`) — 後端架構師，負責 API 設計、資料庫 Schema 與資料流最佳化。當需要 api design、database schema 或 data flow 時觸發。
- **[data-engineer](./skills/analysis/data-engineer/SKILL.md)** (`analysis`) — 資料工程師，負責 ETL 流程、資料清洗與標準化。當需要 etl、data cleaning、normalization 或 market data 時觸發。
- **[devops-engineer](./skills/analysis/devops-engineer/SKILL.md)** (`analysis`) — 運維工程師，負責環境配置、CI/CD、部署策略與系統監控。當需要 deploy、environment setup、ci/cd 或 monitoring 時觸發。
- **[sentiment-scout](./skills/analysis/sentiment-scout/SKILL.md)** (`analysis`) — 透過新聞、論壇和機構報告對市場情緒進行非結構化資料分析。
- **[quant-research-loop](./skills/analysis/quant-research-loop/SKILL.md)** (`analysis`) — 自動化金融實驗與策略驗證迴圈。
- **[ownership-cluster](./skills/analysis/ownership-cluster/SKILL.md)** (`analysis`) — 機構持股與籌碼集中度指數（CI_INDEX）分析。
- **[macro-linkage](./skills/analysis/macro-linkage/SKILL.md)** (`analysis`) — 總體經濟數據與台股大盤聯動分析。
- **[twse-market-logic](./skills/analysis/twse-market-logic/SKILL.md)** (`analysis`) — 臺股市場分析深度邏輯。包含恐慌指數 (VIX/VIXTWN) 閾值、分層確認模型 (Hierarchical Confirmation)、MSTL 網絡預測、以及籌碼面分析 (法人、融資維持率、大戶持股)。用於規劃分析功能、設定警報閾值、以及開發投資決策支援系統。Triggers on: '恐慌指數', 'Panic Index', '市場邏輯', '籌碼分析', '融資維持率', '千張大戶', '八大行庫'.
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
- **[tool-executor](./skills/execution/tool-executor/SKILL.md)** (`execution`) — 萬用工具執行器。作為大腦層 (System 2) 與外部環境之間的唯一橋樑。將自然語言意圖轉換為嚴謹的 JSON-RPC 工具呼叫，並提供完整的 Audit Log 追蹤。
- **[frontend-developer](./skills/execution/frontend-developer/SKILL.md)** (`execution`) — 前端開發工程師，負責 UI/UX 邏輯、元件實作與互動設計。當需要 ui design、frontend implementation 或 component build 時觸發。
- **[declarative-visual-intent-generator](./skills/execution/declarative-visual-intent-generator/SKILL.md)** (`execution`) — 宣告式視覺意圖生成器。透過 A2UI 協定，將 Agent 的複雜推演結果轉換成結構化的宣告式 UI 意圖 (Intent)，而非生硬的 HTML/CSS。具備 Generative UI 能力，能根據使用者需求動態呼叫圖片或圖表生成工具來組合混合式介面。
- **[gemma-4-api](./skills/execution/gemma-4-api/SKILL.md)** (`execution`) — 提供存取 Gemma 4 API 的標準作業流程、模型設定與防錯指南。當使用者要求『串接 Gemma 4 服務』、『建立 AI 助理』、『實作 Function Calling』或『處理 API Rate Limit (429) 錯誤』時使用。
- **[image-enhancer](./skills/execution/image-enhancer/SKILL.md)** (`execution`) — 提升影像（特別是截圖）的解析度、銳利度與清晰度。當使用者要求『圖片增強』、『截圖變清晰』、『圖片放大』、『去除雜訊』，或需要為簡報、文件、社群貼文準備圖像時使用。
- **[theme-factory](./skills/execution/theme-factory/SKILL.md)** (`execution`) — 為成品套用主題風格，適用於投影片、文件、報告、HTML 登陸頁面。內含 10 組預設主題色彩與字體，也可即時生成新主題。當使用者要求『套用主題』、『配色方案』、『設計 Token』、『統一視覺風格』時使用。
- **[playwright-automation](./skills/execution/playwright-automation/SKILL.md)** (`execution`) — 使用 Playwright 建立完整的瀏覽器自動化測試框架。自動偵測開發伺服器、撰寫測試腳本、驗證響應式設計、填寫表單、測試登入流程、檢查連結並產出測試報告。當使用者要求『寫 E2E 測試』、『Playwright 測試腳本』、『跨瀏覽器測試』、『響應式設計測試』時使用。若只需快速截圖或查看瀏覽器日誌而不必建立測試套件，改用 webapp-testing。
