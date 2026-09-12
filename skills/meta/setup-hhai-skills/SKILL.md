---
name: setup-hhai-skills
description: "HH.AI 技能工作區初始化與維護導引。當使用者需要新增、修改、遷移技能、接手技能工作區或確認技能架構時手動觸發執行。"
disable-model-invocation: true
---

# 技能工作區維護與導引 (Skill Maintenance & Onboarding)

本技能提供 **HH.AI 技能工作區的維護與接手標準作業程序**。
當需要新增技能、修改既有技能、遷移舊技能或確認技能庫架構規範時，遵循本流程以確保符合專案架構規範。

> [!NOTE]
> 本技能為**可重複呼叫的維護能力**，不保存專案即時狀態。若需查詢專案進行中任務或交接狀態，請查閱 [docs/HANDOVER.md](file:///c:/Users/HH.AI_260806/Desktop/HH.AI_v2/docs/HANDOVER.md)、[docs/TASKBOARD.md](file:///c:/Users/HH.AI_260806/Desktop/HH.AI_v2/docs/TASKBOARD.md) 與 [docs/refactor-backlog.md](file:///c:/Users/HH.AI_260806/Desktop/HH.AI_v2/docs/refactor-backlog.md) §5。

---

## 🛠️ 技能維護五步標準流程 (Skill Maintenance Loop)

```text
1. 閱讀規範  →  2. 決定分類  →  3. 建立/修改結構  →  4. 漸進揭露撰寫  →  5. 標準驗證
(Read Rules)    (Select Bucket)   (Create Structure)     (Author Content)     (Verify All)
```

### Step 1: 閱讀專案規範 (Read Rules)
動手前務必閱讀專案核心架構規範：
- 專案架構原則：[AGENTS.md](file:///c:/Users/HH.AI_260806/Desktop/HH.AI_v2/AGENTS.md)（含 §0 工程紀律與 §1 目錄結構）
- 技能工程護欄：[.agents/rules/skill-engineering-guardrails.md](file:///c:/Users/HH.AI_260806/Desktop/HH.AI_v2/.agents/rules/skill-engineering-guardrails.md)
- 目標 Bucket 規則：`skills/<bucket>/AGENTS.md` 與 `skills/<bucket>/README.md`

### Step 2: 決定分類桶 (Select Bucket)
依職責特性決定歸屬桶（7 Buckets，嚴禁同名技能跨桶存在）：
- `orchestration/`：流程調度、狀態機控制、多技能協同
- `analysis/`：台股分析、財務模型、技術分析（純分析型，無副作用）
- `agents/`：RARV 執行型代理人（呼叫外部工具、寫檔案、下單；需 `authorized_mcp_tools`）
- `execution/`：通用工具型技能（Playwright、D3.js、PDF 等）
- `platform/`：外部平台串接（LINE、Telegram、Postgres、MCP 等）
- `meta/`：造技能的技能、生態治理類（skill-creator、setup 等）
- `deprecated/`：已棄用技能目錄，保留供參考

### Step 3: 建立與核對結構 (Create Structure)
- 資料夾路徑：`skills/<bucket>/<skill-name>/`
- 目錄名稱必須與 frontmatter 中的 `name` 完全一致。
- 必備檔案：`SKILL.md`（YAML frontmatter + Markdown 指令本體）。
- 選用檔案：`REFERENCE.md`、`EXAMPLES.md`、`scripts/`。

### Step 4: 漸進式揭露撰寫 (Author Content)
- **Frontmatter**：
  - `name`（必要）：全域唯一英數技能識別碼。
  - `description`（必要）：單行撰寫（嚴禁換行），包含使用情境與豐富觸發詞。
  - `disable-model-invocation: true`：若涉及實體修改、下單或一次性維護等風險操作，設為 true。
- **SKILL.md 本體**：保持精簡（約 150 行以內），只保留使用情境、核心操作流程與最小範例。
- **細節拆分**：大量參數表、API Schema、範例代碼移至 `REFERENCE.md`。

### Step 5: 全面驗證與同步 (Verify All)
每次異動技能後，必須執行以下檢查並同步索引：
1. 單一技能格式檢查：`python scripts/validate_skills.py`
2. 跨檔案一致性檢查：`python scripts/check_consistency.py --as-if-committed`
3. 同步三層 README（`AGENTS.md` §7）：
   - 所屬 Bucket README：`skills/<bucket>/README.md`
   - 全技能總覽：`skills/README.md`
   - 專案根目錄索引：`README.md`
4. 全庫單一權威閘門驗證：`python scripts/verify_all.py`

---

## 📚 參考範本與欄位規範
詳細的 YAML Frontmatter 欄位說明、技能模板與各 Bucket 特殊限制，請參閱：
👉 **[REFERENCE.md](./REFERENCE.md)**
