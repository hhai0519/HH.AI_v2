# Orchestration

流程調度、任務路由、狀態機控制。

## User-invoked

只能人類手動觸發（SKILL.md 有 `disable-model-invocation: true`）。

_(尚無技能)_
## Model-invoked

模型可自主判斷觸發。

- **[active-inference](./active-inference/SKILL.md)** — 系統的 System 2 大腦。負責將使用者的自然語言意圖轉化為決定論的狀態機 (SDLC/EARS 語法)，並執行主動推論 (Active Inference) 來預測並最小化專案失敗的風險 (Surprise)。
- **[agency-orchestrator](./agency-orchestrator/SKILL.md)** — 萬能總管模式（Agency-Agents 最高總管），負責通用意圖解析與全局任務拆解，並執行 4-Phase 狀態機工作流。當遇到複雜任務 (complex task)、新專案建立、系統架構設計、複雜除錯，或發生連續工具錯誤需進行反思 (reflection)、專案告一段落需進行記憶歸檔 (consolidation) 時觸發。
- **[security-auditor](./security-auditor/SKILL.md)** — 資訊安全與弱點掃描總監。在程式碼合併、API 串接或外部資料處理前，自動執行安全審查。掃描 SQL Injection、XSS、API 密鑰外洩、路徑穿越等高危漏洞。觸發關鍵字：安全掃描、資安審計、弱點掃描、密碼外洩、secret外洩、SQL注入、XSS。
- **[stock-orchestrator](./stock-orchestrator/SKILL.md)** — 股票與量化領域總管，負責拆解金融任務並調度 analysis/ 層的專業技能。
- **[reality-checker](./reality-checker/SKILL.md)** — 品質保證與幻覺過濾器，負責審核計畫、架構與代碼的技術可行性。
- **[real-time-stream-orchestrator](./real-time-stream-orchestrator/SKILL.md)** — 即時串流總指揮。實作 Interactive ReAct 架構，支援非同步「邊想邊說、邊聽邊想」，透過 AG-UI 協定將推演過程即時投影至前端介面（目前為設計願景，尚未有對應實作程式碼）。

- **[cost-benefit-router](./cost-benefit-router/SKILL.md)**：在動態實驗或複雜研究中評估預算與成本，判斷是否繼續深入。
- **[epistemic-state-governor](./epistemic-state-governor/SKILL.md)**：認知狀態管制官，監控推演健康度並在幻覺時強制介入。
- **[recursive-research-automation](./recursive-research-automation/SKILL.md)**：執行遞迴式深度研究，涵蓋廣度掃描與深度收斂。
- **[subagent-collaboration](./subagent-collaboration/SKILL.md)**：調用子代理人（Sub-Agent）協助完成專業領域分析或創作。
