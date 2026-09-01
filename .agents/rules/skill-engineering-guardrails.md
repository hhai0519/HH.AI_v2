# 規則：技能架構防禦與工程規範 (Skill Engineering Guardrails)

這是一條 workspace 規則，Antigravity 在本專案內執行任何任務時都會載入。
任何違反以下條款的技能操作或開發行為，**禁止存檔**，並強制要求退回修正。

## 1. 反死鎖與單向依賴協定 (Anti-Deadlock & Uni-directional Flow)

**規則**：嚴禁同層級技能產生「循環互相依賴」，尤其是負責分析推理的 `analysis/` 層。
**定義**：若技能 A 宣告依賴技能 B，而技能 B 同時也宣告依賴技能 A，則構成循環依賴死鎖，一律違規。

**強制處置**：
- 若兩個 `analysis/` 領域的技能需要共用邏輯或資料，必須將共用部分「向下抽取 (Extract-Down)」，於 `execution/` 或 `platform/` 層建立獨立的中轉工具。
- 兩個技能各自單向依賴該中轉工具，禁止互相引用。
- 違者必須解耦後才允許存檔。

## 2. 嚴格命名空間映射 (Strict Namespace Binding)

**規則**：技能的實體目錄名稱（Folder Name）必須與 `SKILL.md` 的 YAML frontmatter 中的 `name:` 欄位**完全一致（1:1 Exact Match）**。
- 區分大小寫、無前後空白、且不得添加冗餘前綴。
- 本條例由 `scripts/validate_skills.py` 嚴格把關。目錄名與 `name:` 不符將直接判定驗證失敗。

## 3. 分層 Payload 淨化機制 (Payload Tiering Protocol)

**規則**：Orchestrator（或任務派發節點）在派發 Payload 時，必須根據目標技能的 bucket 層級進行「型別淨化」，嚴禁將錯誤型別的參數發送給不匹配的層級。

**強制型別矩陣**：
| 目標層級 | 允許的 Payload 內容 | 嚴禁包含 |
|---|---|---|
| `analysis/` 認知型技能 | 戰略目標、語氣設定、情緒變數、自然語言約束 | SQL 語句、DOM 路徑、raw URL、純技術指令 |
| `execution/` 或 `platform/` 技術型技能 | URL、DOM Selector、SQL Query、JSON Schema、檔案絕對路徑 | 認知參數、語氣描述、角色設定、情緒變數 |

*(註：淨化責任方為 `skills/orchestration/subagent-collaboration`，其 `SKILL.md` 的「分層 Payload 淨化機制」一節載有執行流程。由人工或其他 Agent 直接發送 Payload 時，同樣須遵守本節的淨化分層原則，不得因為未經該技能轉發而略過。)*

## 4. 統一歸檔與差異化刪除政策 (Unified Archive Policy)

對於「刪除」操作，必須嚴格區分以下兩種不同性質的情境，不可混淆：

### 情況 A：刪除「整個技能」 (停用/下架)
**規則**：嚴禁對整個技能目錄執行物理刪除（如 `rm -rf`）。
**理由**：為了避免誤刪有價值的分析邏輯或發展歷程，停止維護的技能必須被妥善留存。
**處置步驟**：
1. 將該技能的整個目錄移至 `skills/deprecated/` 資料夾中。
2. 從原先所屬 bucket 的 `README.md` 索引清單中移除該技能。
3. 將該技能新增至 `skills/deprecated/README.md` 的停用清單中。

### 情況 B：刪除技能內部的「錯誤/失效內容」 (內容清理)
**規則**：若僅是為了清理技能內部的幽靈引用、已廢棄政策殘留、或失效的舊架構路徑，**不受上述歸檔限制，可直接將其從檔案中物理刪除**。
**理由**：此類操作的本質是「清理錯誤與毒性內容」以防止 Agent 被誤導。留著錯誤資訊只會帶來負面影響，不需要為錯誤的文字段落執行歸檔。
