# HH.AI Skills 總覽 (Skills Overview)

本文件提供 `skills/` 目錄下的所有技能 (Skills) 的索引與分類，方便開發者閱讀、維護與管理。

## 目錄結構與快速導覽

根據各 Skill 的用途，本目錄分為以下主要類別：

- [**`skills/agents/`** (執行型)](#skillsagents-執行型)：RARV 執行型 agent（會實際呼叫工具、寫檔案、發送訊息等）。
- [**`skills/analysis/`** (分析型)](#skillsanalysis-分析型)：台股分析、財務模型、技術分析（純分析型，不直接執行外部動作）。
- [**`skills/execution/`** (工具型)](#skillsexecution-工具型)：通用工具型技能（PDF/XLSX/D3/Playwright 等）。
- [**`skills/meta/`** (治理型)](#skillsmeta-治理型)：造技能的技能、治理類（skill-creator、setup-hhai-skills 等）。
- [**`skills/orchestration/`** (調度型)](#skillsorchestration-調度型)：流程調度、任務路由、狀態機控制。
- [**`skills/platform/`** (平台整合)](#skillsplatform-平台整合)：平台整合（LINE/Telegram/MCP/Postgres 等外部串接）。
- [**`skills/deprecated/`** (已棄用)](#skillsdeprecated-已棄用)：已棄用，保留供參考，不再維護，不會被自動觸發。

### skills/agents/ (執行型)

| 技能名稱 (Skill ID) | 核心功能簡述 | 適用場景 / 觸發時機 |
|---------------------|-------------|--------------------|
| **[bot-account-switcher](./agents/bot-account-switcher/)** | LINE 與 Telegram 官方帳號的雙平台切換工具 | 透過 $$Line帳號$$ 與 $$TG帳號$$ 觸發，會覆寫 .env 並重啟 PM2，需明確要求才會執行 |
| **[investment-aggregator](./agents/investment-aggregator/)** | Loki Swarm 決策統整專家。彙整 twse-data-analyst (量化) 與 market-researcher (質化) 的數據，產出最終投資報告與風險評估。 | - |
| **[jules-integration](./agents/jules-integration/)** | 將耗時長、Token 消耗大的重構/修復任務委派給雲端 Google Jules 代理人。每日額度僅 5 次，需明確要求才會觸發。 | 需明確要求才會觸發 |
| **[line-interaction-manager](./agents/line-interaction-manager/)** | Loki Swarm: 第一線溝通總管。專門處理 LINE Bot 介面互動，確保回覆符合品牌語氣，並保護底層金融邏輯不外洩。 | - |
| **[market-researcher](./agents/market-researcher/)** | Loki Swarm 基本面研究員。專職閱讀財報、解析 PDF、收集市場新聞情緒，取代舊版脆弱的自動爬蟲腳本。 | - |
| **[twse-data-analyst](./agents/twse-data-analyst/)** | Loki Swarm 量化運算專家。專責處理 TWSE 歷史資料、技術指標與量化運算，嚴格受限於財務資料庫環境。 | - |

### skills/analysis/ (分析型)

| 技能名稱 (Skill ID) | 核心功能簡述 | 適用場景 / 觸發時機 |
|---------------------|-------------|--------------------|
| **[backend-architect](./analysis/backend-architect/)** | 後端架構師，負責 API 設計、資料庫 Schema 與資料流最佳化 | 當需要 api design、database schema 或 data flow 時觸發 |
| **[data-engineer](./analysis/data-engineer/)** | 資料工程師，負責 ETL 流程、資料清洗與標準化 | 當需要 etl、data cleaning、normalization 或 market data 時觸發 |
| **[devops-engineer](./analysis/devops-engineer/)** | 運維工程師，負責環境配置、CI/CD、部署策略與系統監控 | 當需要 deploy、environment setup、ci/cd 或 monitoring 時觸發 |
| **[evidence-collector](./analysis/evidence-collector/)** | 證據收集官，負責為所有決策提供事實支撐、鏈接與原始數據 | 當需要 find evidence、verify stats、source check 或 market research 時觸發 |
| **[financial-analyst](./analysis/financial-analyst/)** | 財務分析師，負責估值建模、比率分析與財務風險評估 | 當需要 valuation (估值)、financial statement (財報分析)、ratio analysis (比率分析) 或 risk assessment (風險評估) 時觸發 |
| **[investment-researcher](./analysis/investment-researcher/)** | 投資研究員，負責台股產業研究、個股基本面與量化趨勢分析 | 當需要 sector analysis (產業分析)、company research (個股研究) 或 market trend (市場趨勢) 時觸發 |
| **[macro-linkage](./analysis/macro-linkage/)** | 總體經濟數據與台股大盤聯動分析。 | - |
| **[ownership-cluster](./analysis/ownership-cluster/)** | 機構持股與籌碼集中度指數（CI_INDEX）分析。 | - |
| **[pe-river-map](./analysis/pe-river-map/)** | 用於長期投資評估的互動式本益比河流圖（PE Band）估值視覺化 | 當詢問股票貴不貴、本益比河流圖、估值區間、或評估長線買點與目標價時觸發 |
| **[quant-research-loop](./analysis/quant-research-loop/)** | 自動化金融實驗與策略驗證迴圈。 | - |
| **[sentiment-scout](./analysis/sentiment-scout/)** | 透過新聞、論壇和機構報告對市場情緒進行非結構化資料分析。 | - |
| **[software-architect](./analysis/software-architect/)** | 軟體架構師，負責系統高層設計、模式定義與技術選型 | 當需要 architecture design、design pattern 或 system structure 時觸發 |
| **[tech-analyzer](./analysis/tech-analyzer/)** | 專家級的價格形態、量能結構和趨勢指標技術分析 | 當需要分析技術走勢、支撐壓力位、K線型態、找買賣點、或進行量價背離分析時觸發 |
| **[twse-market-logic](./analysis/twse-market-logic/)** | 臺股市場分析深度邏輯。包含恐慌指數 (VIX/VIXTWN) 閾值、分層確認模型 (Hierarchical Confirmation)、MSTL 網絡預測、以及籌碼面分析 (法人、融資維持率、大戶持股)。用於規劃分析功能、設定警報閾值、以及開發投資決策支援系統 | Triggers on: '恐慌指數', 'Panic Index', '市場邏輯', '籌碼分析', '融資維持率', '千張大戶', '八大行庫'. |

### skills/execution/ (工具型)

| 技能名稱 (Skill ID) | 核心功能簡述 | 適用場景 / 觸發時機 |
|---------------------|-------------|--------------------|
| **[artifacts-builder](./execution/artifacts-builder/)** | 使用現代前端技術（React、Tailwind CSS、shadcn/ui）建立精細、多組件 HTML 互動原型。 | - |
| **[changelog-generator](./execution/changelog-generator/)** | 從 Git 提交紀錄自動生成面向使用者的版本日誌，將技術性 commit 訊息轉換為清晰的發佈說明。 | - |
| **[csv-data-summarizer](./execution/csv-data-summarizer/)** | 全自動解析 CSV 或 TSV 資料並產出統計報告與視覺化圖表，支援離群值偵測、相關性熱力圖與時間序列分析。 | - |
| **[d3js-visualization](./execution/d3js-visualization/)** | 使用 d3.js 建立互動式資料視覺化。適用於客製化圖表、網路圖、地理視覺化，或任何需要對視覺元素、過渡或互動進行精細控制的複雜 SVG 資料視覺化。 | - |
| **[declarative-visual-intent-generator](./execution/declarative-visual-intent-generator/)** | 宣告式視覺意圖生成器。透過 A2UI 協定，將 Agent 的複雜推演結果轉換成結構化的宣告式 UI 意圖 (Intent)，而非生硬的 HTML/CSS。具備 Generative UI 能力，能根據使用者需求動態呼叫圖片或圖表生成工具來組合混合式介面。 | - |
| **[frontend-developer](./execution/frontend-developer/)** | 前端開發工程師，負責 UI/UX 邏輯、元件實作與互動設計 | 當需要 ui design、frontend implementation 或 component build 時觸發 |
| **[gemma-4-api](./execution/gemma-4-api/)** | 提供存取 Gemma 4 API 的標準作業流程、模型設定與防錯指南 | 當使用者要求『串接 Gemma 4 服務』、『建立 AI 助理』、『實作 Function Calling』或『處理 API Rate Limit (429) 錯誤』時使用 |
| **[image-enhancer](./execution/image-enhancer/)** | 提升影像（特別是截圖）的解析度、銳利度與清晰度 | 當使用者要求『圖片增強』、『截圖變清晰』、『圖片放大』、『去除雜訊』，或需要為簡報、文件、社群貼文準備圖像時使用 |
| **[mcp-engineer](./execution/mcp-engineer/)** | MCP 開發與環境配置完整生命週期工程師。整合 mcp-builder（建立高品質 MCP 伺服器的標準流程）與 mcp-setup（本地環境設定與排錯）為單一職責技能 | 觸發關鍵字：建立MCP、MCP伺服器、MCP配置、MCP環境、mcp-builder、mcp-setup |
| **[pdf](./execution/pdf/)** | PDF 文件操作一站式工具箱，涵蓋文字提取、合併拆分、浮水印、加密、表單填寫、圖片提取與掃描 OCR。 | - |
| **[playwright-automation](./execution/playwright-automation/)** | 使用 Playwright 建立完整的瀏覽器自動化測試框架。自動偵測開發伺服器、撰寫測試腳本、驗證響應式設計、填寫表單、測試登入流程、檢查連結並產出測試報告 | 當使用者要求『寫 E2E 測試』、『Playwright 測試腳本』、『跨瀏覽器測試』、『響應式設計測試』時使用。若只需快速截圖或查看瀏覽器日誌而不必建立測試套件，改用 webapp-testing |
| **[systematic-debugging](./execution/systematic-debugging/)** | 強制執行「先找根本原因、再提修正」的四階段除錯流程。適用於 MCP 連接失敗、工具載入錯誤、npm/pip 安裝失敗等本地環境問題。 | - |
| **[theme-factory](./execution/theme-factory/)** | 為成品套用主題風格，適用於投影片、文件、報告、HTML 登陸頁面。內含 10 組預設主題色彩與字體，也可即時生成新主題 | 當使用者要求『套用主題』、『配色方案』、『設計 Token』、『統一視覺風格』時使用 |
| **[tool-executor](./execution/tool-executor/)** | 萬用工具執行器。作為大腦層 (System 2) 與外部環境之間的唯一橋樑。將自然語言意圖轉換為嚴謹的 JSON-RPC 工具呼叫，並提供完整的 Audit Log 追蹤。 | - |
| **[webapp-testing](./execution/webapp-testing/)** | 使用 Playwright 互動和測試本地 Web 應用程式的工具包。支援驗證前端功能、偵錯 UI 行為、擷取瀏覽器螢幕截圖以及查看瀏覽器日誌。 | - |
| **[xlsx](./execution/xlsx/)** | 提供 Excel (XLSX) 檔案讀寫、多 Sheet 整合與格式化報表生成。 | - |

### skills/meta/ (治理型)

| 技能名稱 (Skill ID) | 核心功能簡述 | 適用場景 / 觸發時機 |
|---------------------|-------------|--------------------|
| **[setup-hhai-skills](./meta/setup-hhai-skills/)** | 一次性的專案初始化與交接設定指南 | 當接手現有專案、需要了解專案技術棧與目錄結構、或準備開始開發臺股網站功能時手動觸發閱讀 |
| **[skill-evolution-governor](./meta/skill-evolution-governor/)** | 負責技能生態系統的生命週期管理、DLP 合規審計與系統自我進化。包含自動覆寫技能規範的修復能力。此技能涉及實體檔案變更，必須由使用者明確要求時才可觸發執行。 | - |

### skills/orchestration/ (調度型)

| 技能名稱 (Skill ID) | 核心功能簡述 | 適用場景 / 觸發時機 |
|---------------------|-------------|--------------------|
| **[active-inference](./orchestration/active-inference/)** | 系統的 System 2 大腦。負責將使用者的自然語言意圖轉化為決定論的狀態機 (SDLC/EARS 語法)，並執行主動推論 (Active Inference) 來預測並最小化專案失敗的風險 (Surprise)。 | - |
| **[agency-orchestrator](./orchestration/agency-orchestrator/)** | 萬能總管模式（Agency-Agents 最高總管），負責通用意圖解析與全局任務拆解，並執行 4-Phase 狀態機工作流 | 當遇到複雜任務 (complex task)、新專案建立、系統架構設計、複雜除錯，或發生連續工具錯誤需進行反思 (reflection)、專案告一段落需進行記憶歸檔 (consolidation) 時觸發 |
| **[cost-benefit-router](./orchestration/cost-benefit-router/)** | 在動態實驗或複雜研究中評估預算與成本，判斷是否繼續深入。 | - |
| **[epistemic-state-governor](./orchestration/epistemic-state-governor/)** | 認知狀態管制官，監控推演健康度並在幻覺時強制介入。 | - |
| **[real-time-stream-orchestrator](./orchestration/real-time-stream-orchestrator/)** | 即時串流總指揮。實作 Interactive ReAct 架構，支援非同步「邊想邊說、邊聽邊想」，透過 AG-UI 協定將推演過程即時投影至前端介面（目前為設計願景，尚未有對應實作程式碼）。 | - |
| **[reality-checker](./orchestration/reality-checker/)** | 品質保證與幻覺過濾器，負責審核計畫、架構與代碼的技術可行性。 | - |
| **[recursive-research-automation](./orchestration/recursive-research-automation/)** | 執行遞迴式深度研究，涵蓋廣度掃描與深度收斂。 | - |
| **[security-auditor](./orchestration/security-auditor/)** | 資訊安全與弱點掃描總監。在程式碼合併、API 串接或外部資料處理前，自動執行安全審查。掃描 SQL Injection、XSS、API 密鑰外洩、路徑穿越等高危漏洞 | 觸發關鍵字：安全掃描、資安審計、弱點掃描、密碼外洩、secret外洩、SQL注入、XSS |
| **[stock-orchestrator](./orchestration/stock-orchestrator/)** | 股票與量化領域總管，負責拆解金融任務並調度 06 層級的子模組。 | - |
| **[subagent-collaboration](./orchestration/subagent-collaboration/)** | 調用子代理人（Sub-Agent）協助完成專業領域分析或創作。 | - |

### skills/platform/ (平台整合)

| 技能名稱 (Skill ID) | 核心功能簡述 | 適用場景 / 觸發時機 |
|---------------------|-------------|--------------------|
| **[connect-apps](./platform/connect-apps/)** | 操控 Gmail、Slack、GitHub、Notion 等外部服務執行自動化任務 | 當使用者要求『在 Slack 發通知』、『建立 GitHub Issue』、『更新 Notion 頁面』、『發送郵件』或『跨系統資料同步』時使用 |
| **[json-to-flex-renderer](./platform/json-to-flex-renderer/)** | 將 JSON 分析報告純程式化轉換為 LINE Flex Message。 | - |
| **[langsmith-fetch](./platform/langsmith-fetch/)** | 從 LangSmith 獲取執行追蹤以偵錯 Agent 行為。 | - |
| **[mcp-gateway](./platform/mcp-gateway/)** | Zero-Trust 萬用執行閘道器。負責啟動並連接所有的 MCP 伺服器，目前為未實作的設計草案。 | - |
| **[notebooklm-mcp](./platform/notebooklm-mcp/)** | 操控 NotebookLM 建立知識庫、進行深度研究與生成報告音頻 | 當使用者要求『建立 NotebookLM 筆記本』、『製作 Podcast/Audio Overview』、『跨筆記本知識查詢』或『從 URL/PDF 建立知識庫』時使用 |
| **[postgres](./platform/postgres/)** | 對多個 PostgreSQL 資料庫執行唯讀 SQL 查詢。支援結構探索、資料分析和品質檢查。為確保安全，封鎖所有寫入操作。 | - |

### skills/deprecated/ (已棄用)

_(尚無技能)_


## 快速指引

### 如何呼叫與使用 Skill？

1. **User-invoked (使用者觸發)**：部分 Skill 需要使用者明確輸入特定的關鍵字或要求才會啟動（例如 `jules-integration`、`bot-account-switcher`）。你可以直接在對話中提及這些關鍵字來呼叫。
2. **Model-invoked (模型自主觸發)**：大部分的 Skill 由系統（Model）根據當下對話的意圖與需求自主判斷並觸發（例如 `active-inference`、各類分析與執行工具）。
3. **組合使用**：你可以描述一個複雜的任務，總管代理人（如 `agency-orchestrator` 或 `stock-orchestrator`）會自動拆解任務並路由至對應的子 Skill 進行處理。

### 如何配置 Skill？

- 每個 Skill 的核心邏輯與設定通常定義在其目錄下的 `SKILL.md`（說明與提示詞）以及 `skill.json` / `package.json`（設定檔）中。
- 若需新增或修改 Skill，請遵守 `AGENTS.md` 的規範，並使用 `python3 scripts/validate_skills.py` 驗證設定是否合法。
- 如果某個技能涉及系統全域的參數或依賴環境變數，請確認專案根目錄的 `.env` 已正確設定。
