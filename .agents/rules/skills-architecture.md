# 規則：技能架構強制規範

這是一條 workspace 規則，Antigravity 在本專案內執行任何任務前都會載入。

**核心原則：本專案所有 `skills/` 下的內容，結構必須與 `AGENTS.md` 中定義的規範一致。**

在你（agent）要做以下任何一件事之前，先讀 `AGENTS.md` 全文，不要憑記憶或猜測：

- 新增一個技能
- 修改任一技能的 frontmatter 或內容
- 把技能從別的分類搬到新分類
- 從舊架構（`01_Orchestrators` / `02_Cognitive` / `03_Execution` / `Archive`）遷移技能過來

**每次新增或修改技能後，你必須：**
1. 執行 `python3 scripts/validate_skills.py`，確認沒有錯誤
2. 更新對應 bucket 的 `README.md`
3. 更新根目錄 `README.md`
4. 若該技能是 user-reachable（會被人或其他 router 呼叫），檢查 `skills/orchestration/agency-orchestrator/SKILL.md` 是否需要同步更新路由說明

---

## 1. 技能呼叫分類準則 (Invocation Classification Rule)

依據 `AGENTS.md §5`、`§5.1` 與 ADR-0002 規範，新增、修改或遷移技能時，必須遵循「個別技能安全閘門優先於 Bucket 積極度（Per-Skill Safety Gate > Bucket Aggressiveness）」原則設定 `disable-model-invocation` 欄位與 description：

1. **普遍性個別技能安全閘門（Universal Safety Gate，第一優先）**：
   - 判定核心：「模型自己遇到這種情境時，能不能安全自主呼叫？」
   - 任何 bucket（包含 `platform/`、`execution/`、`orchestration/`、`analysis/`）之技能，若具有外部真實副作用（如對外通訊、發送郵件、修改外部系統、寫入或刪除生產資料庫、金融交易等），**一律設為 `disable-model-invocation: true`（User-invoked）**，絕不因 bucket 分類而放寬。
   - 現行 `skills/platform/` 中已存在之 User-invoked 技能（如 `connect-apps`、`postgres`、`mcp-gateway`）完全符合本規範，不得被視為違規。
2. **已核准 Model-invoked 技能之積極度指引（第二優先）**：
   - **`orchestration/`、`analysis/`、`execution/`、`platform/` 中可安全自主執行之技能**：採積極模型呼叫精神（Proactive Model Invocation）。`description` 應提供豐富且具體的任務情境與觸發詞，讓 Agent 在相關情境下主動運用，無需使用者逐次明示。
   - **`agents/`**：採嚴格保守呼叫原則（Conservative Invocation Policy）。凡涉及真實外部操作或未獲明確自治授權者，**嚴禁**因「可能有幫助」而設為自主呼叫，必須維持 `disable-model-invocation: true`。

---

## 2. 指定資料來源與工具失效防護鐵律 (Anti-Silent-Substitution Rule)

依據 ADR-0004 之全域安全原則，當任務指示、使用者明確要求或技能合約指定使用特定資料來源、研究工具、MCP、provider 或 authoritative source 時：

1. **嚴禁靜默替代（No Silent Substitution）**：
   - 若指定的資料來源或工具遇到無法連線、憑證過期（如 auth expired / stale）、服務不可用或回傳異常，**絕對禁止**在未經使用者授權的情況下，擅自改用常規網路搜尋（Web Search）、其他 LLM 猜測或其他工具靜默替代。
2. **失效即停與即時回報（Fail-Closed & Explicit Reporting）**：
   - 遇到指定來源失效時，必須**立刻停止**依賴該來源的後續動作。
   - 主動向使用者明確回報該工具/來源 unavailable 或 authentication failure 的客觀事實與錯誤訊息。
   - 只有在使用者協助修復連線/登入，或使用者明確下達替代指令（或合約允許之 explicit fallback）後，方可繼續執行。
3. **歷史分析技能遷移保留條款**：
   - 原始分析型技能（如 `financial-analyst`、`investment-researcher`、`tech-analyzer`、`pe-river-map`）若包含 NotebookLM 研究遵從指示之 WARNING 規範，於遷移時必須逐字保留其安全語意，不得作為舊架構雜訊移除。

---

## 3. 禁制清單

**不要**：
- 自行發明新的 bucket 分類（如需新增 bucket，先在 `AGENTS.md` 中提案並取得使用者確認）
- 把技能檔案直接放在 bucket 資料夾下（沒有自己的子資料夾）
- 留空 `description` 欄位
- 讓 SKILL.md 超過約 150 行還不拆出 REFERENCE.md
- 違反指定資料來源的失效即停防護原則擅自替代工具或資料來源
