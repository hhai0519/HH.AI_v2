# 技能維護與規範參考 (Skill Maintenance Reference)

本文件提供技能開發者與維護者所需的詳細規格、Schema 規範與檢核清單。

---

## 1. YAML Frontmatter 欄位規格

標準技能 frontmatter 範例如下：

```yaml
---
name: example-skill
description: "簡明敘述情境與觸發詞。例如：分析台股技術線圖與指標。當使用者要求『技術分析』、『K 線圖』時使用。"
disable-model-invocation: false
---
```

### 欄位說明

| 欄位名稱 | 類型 | 必要性 | 說明 |
| :--- | :--- | :--- | :--- |
| `name` | string | **必要** | 技能名稱，必須為全小寫英數與破折號，且與所在資料夾名稱完全一致。 |
| `description` | string | **必要** | 觸發描述。**必須一行寫完，嚴禁換行**。應包含明確使用情境與關鍵觸發詞。 |
| `disable-model-invocation` | boolean | 選用 | 預設為 false。若為 true 則僅限人類手動觸發，模型不可自主呼叫。適用於有副作用、下單或一次性維護技能。 |
| `authorized_mcp_tools` | array | 條件必要 | 限用在 `skills/agents/` 與特定 `skills/platform/`。明確列出授權使用的 MCP 工具清單。 |
| `semantic_firewall` | string/bool | 條件必要 | 限用在 `skills/agents/`。建議使用領域字串如 `"/Domain/Finance/TWSE/"`，限定工作記憶存取範圍。 |

---

## 2. 技能撰寫檢核清單 (Authoring Checklist)

在提交或修改技能前，請逐一檢查：

- [ ] **單一職責**：一個技能只做一件事，不混合資料擷取、圖表繪製與對外通知。
- [ ] **漸進式揭露**：`SKILL.md` 本體控制在 150 行以內，細節移至 `REFERENCE.md`。
- [ ] **非狀態保存庫**：技能不得保存特定工作階段的任務狀態、進度或檢查點（狀態屬 `docs/`）。
- [ ] **無假性合規**：不得手寫「✓ DLP 資料安全驗證已通過」等無機器的自我宣告。安全規範以 `SOP_02` 與 guardrails 為準。
- [ ] **相對路徑**：不使用已廢棄的舊路徑（如 `00_Master_Menu`、`Data/`、`reply.js`）。
- [ ] **命名一致**：目錄名稱、`SKILL.md` 內的 `name` 欄位與各層 README 連結完全一致。
- [ ] **三層 README 同步**：
  1. `skills/<bucket>/README.md`（按 User-invoked / Model-invoked 分組）
  2. `skills/README.md`（依 Bucket 分類清單）
  3. `README.md`（專案根目錄索引）

---

## 3. 本地驗證指令

```bash
# 1. 快速技能結構與 frontmatter 驗證
python scripts/validate_skills.py

# 2. 跨檔案規格一致性驗證
python scripts/check_consistency.py --as-if-committed

# 3. 指紋檔校驗與全庫權威驗證
python scripts/fingerprint.py --verify
python scripts/verify_all.py
```
