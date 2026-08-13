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

**不要**：
- 自行發明新的 bucket 分類（如需新增 bucket，先在 `AGENTS.md` 中提案並取得使用者確認）
- 把技能檔案直接放在 bucket 資料夾下（沒有自己的子資料夾）
- 留空 `description` 欄位
- 讓 SKILL.md 超過約 150 行還不拆出 REFERENCE.md
