---
name: skill-evolution-governor
description: "負責技能生態系統的生命週期檢查與有界修復。當使用者明確要求審計技能分類、檢查技能一致性或修復具體技能缺陷時手動觸發執行。"
disable-model-invocation: true
---

# 技能治理與有界修復 (Skill Evolution Governor)

## 職責概述
本技能是技能庫的**健康檢查與有界修復工具**，負責兩大核心工作：
1. **靜態生態治理**：檢查技能分類邏輯、維持整體生態系統的命名與架構一致性、執行技能歸檔與失效清理紀律。
2. **有界缺陷修復 (Bounded Skill Repair)**：在使用者明確指示下，針對已知報錯或過期結構，對特定技能進行有界限的修復與格式更新。

> [!CAUTION]
> 本技能**不具備無限制的自我進化或全庫改寫特權**。所有修改必須在明確授權的任務範圍（Allowed Scope）內進行，嚴格遵守 Git 安全紀律，並通過全庫權威驗證。

---

## 🏗️ 技能生態治理規範

### 技能分類體系
本專案的技能分類嚴格遵守 [AGENTS.md](../../../AGENTS.md) §1 定義的七個 bucket：
- `orchestration` / `analysis` / `agents` / `execution` / `platform` / `meta` / `deprecated`

歸屬判斷的依據是「這個技能實際做什麼」。其中 `analysis`（純分析、無副作用）與 `agents`（會實際執行動作）必須嚴格分開，後者需要 `authorized_mcp_tools` 白名單以維護安全邊界（決策依據見 `docs/adr/0001-seven-bucket-taxonomy.md`）。

### 🔴 技能的刪除與歸檔（強制安全邊界）
刪除與歸檔一律遵守 [.agents/rules/skill-engineering-guardrails.md](../../../.agents/rules/skill-engineering-guardrails.md) §4「統一歸檔與差異化刪除政策」：

- **情況 A — 下架整個技能**：嚴禁物理刪除技能目錄。必須移入 `skills/deprecated/`，從原 bucket 的 README.md 移除，並加入 `skills/deprecated/README.md`。
- **情況 B — 清理技能內部的錯誤／失效內容**：幽靈引用、已廢棄政策殘留、失效的舊架構路徑，不受歸檔限制，可直接物理刪除。

### 🛡️ 資料安全與防洩規範 (DLP Compliance)
技能的資料安全規範以下列文件為準：
- [SOP/SOP_02_Security_Guidelines.md](../../../SOP/SOP_02_Security_Guidelines.md) §1「智慧整合與資料防洩」
- [.agents/rules/skill-engineering-guardrails.md](../../../.agents/rules/skill-engineering-guardrails.md) §3「分層 Payload 淨化機制」

審計資料安全時，檢查的是技能是否實際遵守上述文件的行為規範與安全邊界。

> [!WARNING]
> 舊版規範曾要求每個技能在 SKILL.md 中加上一行「✓ DLP 資料安全驗證已通過 …」的宣告，並以該行是否存在作為合規判準。
> **該做法已廢止**：那行文字不對應任何實際驗證行為，屬假性合規。不得要求新技能加上該宣告，也不得以該宣告的有無判定合規。

### 🌐 語言合規性 (Language Compliance)
所有技能的 `SKILL.md` 描述、工具說明及 UI 翻譯必須符合繁體中文標準。無簡體中文術語，專案名詞對應台灣習慣。

---

## 🧬 有界技能修復作業 (Bounded Skill Repair)

當使用者指示修復特定技能的結構錯誤或過期參照時，執行以下有界流程：
1. **定位缺陷**：根據測試報錯或檢查報告，精確定位問題所在的檔案與行數。
2. **最小有界修改**：在授權範圍內更新對應技能的 `SKILL.md` 或 `REFERENCE.md`，不擴大變更範圍。
3. **路徑動態確認**：尋找與修改技能檔案時，必須動態確認目前環境的技能路徑，禁止使用寫死的過期路徑。

---

## ⚙️ 技能異動後的驗證

每次新增或修改技能後，必須執行驗證並同步索引：

1. `python3 scripts/validate_skills.py` — 單一技能 frontmatter 與格式快速檢查。
2. `python3 scripts/check_consistency.py --as-if-committed` — 跨檔案一致性檢查。
3. 確認三層 README 已同步（`AGENTS.md` §7）：所屬 bucket 的 `README.md`、`skills/README.md`、根目錄 `README.md`。
4. `python3 scripts/verify_all.py` — **全專案單一權威完成驗證**（涵蓋技能架構、一致性、指紋校驗與單元測試）。
