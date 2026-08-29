# Execution

通用工具型技能（PDF/XLSX/D3/Playwright 等）。

## User-invoked

_(尚無技能)_

## Model-invoked

- **[tool-executor](./tool-executor/SKILL.md)** — 萬用工具執行器。作為大腦層 (System 2) 與外部環境之間的唯一橋樑。將自然語言意圖轉換為嚴謹的 JSON-RPC 工具呼叫，並提供完整的 Audit Log 追蹤。
- **[frontend-developer](./frontend-developer/SKILL.md)** — 前端開發工程師，負責 UI/UX 邏輯、元件實作與互動設計。當需要 ui design、frontend implementation 或 component build 時觸發。
- **[declarative-visual-intent-generator](./declarative-visual-intent-generator/SKILL.md)** — 宣告式視覺意圖生成器。透過 A2UI 協定，將 Agent 的複雜推演結果轉換成結構化的宣告式 UI 意圖 (Intent)，而非生硬的 HTML/CSS。具備 Generative UI 能力，能根據使用者需求動態呼叫圖片或圖表生成工具來組合混合式介面。
- **[gemma-4-api](./gemma-4-api/SKILL.md)** — 提供存取 Gemma 4 API 的標準作業流程、模型設定與防錯指南。當使用者要求『串接 Gemma 4 服務』、『建立 AI 助理』、『實作 Function Calling』或『處理 API Rate Limit (429) 錯誤』時使用。

- **[d3js-visualization](./d3js-visualization/SKILL.md)** — 使用 d3.js 建立互動式資料視覺化。適用於客製化圖表、網路圖、地理視覺化，或任何需要對視覺元素、過渡或互動進行精細控制的複雜 SVG 資料視覺化。
- **[webapp-testing](./webapp-testing/SKILL.md)** — 使用 Playwright 互動和測試本地 Web 應用程式的工具包。支援驗證前端功能、偵錯 UI 行為、擷取瀏覽器螢幕截圖以及查看瀏覽器日誌。
- **[mcp-engineer](./mcp-engineer/SKILL.md)** — MCP 開發與環境配置完整生命週期工程師。整合 mcp-builder（建立高品質 MCP 伺服器的標準流程）與 mcp-setup（本地環境設定與排錯）為單一職責技能。觸發關鍵字：建立MCP、MCP伺服器、MCP配置、MCP環境、mcp-builder、mcp-setup。
- **[pdf](./pdf/SKILL.md)** — PDF 文件操作一站式工具箱，涵蓋文字提取、合併拆分、浮水印、加密、表單填寫、圖片提取與掃描 OCR。
- **[xlsx](./xlsx/SKILL.md)** — 提供 Excel (XLSX) 檔案讀寫、多 Sheet 整合與格式化報表生成。
- **[csv-data-summarizer](./csv-data-summarizer/SKILL.md)** — 全自動解析 CSV 或 TSV 資料並產出統計報告與視覺化圖表，支援離群值偵測、相關性熱力圖與時間序列分析。
- **[artifacts-builder](./artifacts-builder/SKILL.md)** — 使用現代前端技術（React、Tailwind CSS、shadcn/ui）建立精細、多組件 HTML 互動原型。
- **[changelog-generator](./changelog-generator/SKILL.md)** — 從 Git 提交紀錄自動生成面向使用者的版本日誌，將技術性 commit 訊息轉換為清晰的發佈說明。
- **[systematic-debugging](./systematic-debugging/SKILL.md)** — 強制執行「先找根本原因、再提修正」的四階段除錯流程。適用於 MCP 連接失敗、工具載入錯誤、npm/pip 安裝失敗等本地環境問題。
- **[image-enhancer](./image-enhancer/SKILL.md)** — 提升影像（特別是截圖）的解析度、銳利度與清晰度。當使用者要求『圖片增強』、『截圖變清晰』、『圖片放大』、『去除雜訊』，或需要為簡報、文件、社群貼文準備圖像時使用。
- **[theme-factory](./theme-factory/SKILL.md)** — 為成品套用主題風格，適用於投影片、文件、報告、HTML 登陸頁面。內含 10 組預設主題色彩與字體，也可即時生成新主題。當使用者要求『套用主題』、『配色方案』、『設計 Token』、『統一視覺風格』時使用。
- **[playwright-automation](./playwright-automation/SKILL.md)** — 使用 Playwright 建立完整的瀏覽器自動化測試框架。自動偵測開發伺服器、撰寫測試腳本、驗證響應式設計、填寫表單、測試登入流程、檢查連結並產出測試報告。當使用者要求『寫 E2E 測試』、『Playwright 測試腳本』、『跨瀏覽器測試』、『響應式設計測試』時使用。若只需快速截圖或查看瀏覽器日誌而不必建立測試套件，改用 webapp-testing。
