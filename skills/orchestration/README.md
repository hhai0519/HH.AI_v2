# Orchestration

流程調度、任務路由、狀態機控制。

## User-invoked

只能人類手動觸發（SKILL.md 有 `disable-model-invocation: true`）。

_(尚無技能，遷移時依 AGENTS.md 規則填入，格式：`- **[skill-name](./skill-name/SKILL.md)** — 一行描述`)_

## Model-invoked

模型可自主判斷觸發。

- **[active-inference](./active-inference/SKILL.md)** — 系統的 System 2 大腦。負責將使用者的自然語言意圖轉化為決定論的狀態機 (SDLC/EARS 語法)，並執行主動推論 (Active Inference) 來預測並最小化專案失敗的風險 (Surprise)。
- **[agency-orchestrator](./agency-orchestrator/SKILL.md)** — 萬能總管模式（Agency-Agents 最高總管），負責通用意圖解析與全局任務拆解，並執行 4-Phase 狀態機工作流。
- **[security-auditor](./security-auditor/SKILL.md)** — 資訊安全與弱點掃描總監。在程式碼合併、API 串接或外部資料處理前，自動執行安全審查。掃描 SQL Injection、XSS、API 密鑰外洩、路徑穿越等高危漏洞。觸發關鍵字：安全掃描、資安審計、弱點掃描、密碼外洩、secret外洩、SQL注入、XSS。
- **[stock-orchestrator](./stock-orchestrator/SKILL.md)** — 股票與量化領域總管，負責拆解金融任務並調度 06 層級的子模組。
- **[reality-checker](./reality-checker/SKILL.md)** — 品質保證與幻覺過濾器，負責審核計畫、架構與代碼的技術可行性。
