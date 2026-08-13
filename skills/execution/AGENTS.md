<!-- Parent: ../../AGENTS.md -->

# skills/execution

## Purpose

通用工具型技能（PDF/XLSX/D3/Playwright 等）。這些技能不特別跟「台股分析」
或「LINE Bot」綁定，是可以被其他 bucket 的技能呼叫的基礎工具。

## For AI Agents

### 這個資料夾工作時要注意

- 這裡的技能應該保持通用性，不要把 domain-specific 邏輯（例如台股特定格式）
  寫進來——那種邏輯屬於 `skills/analysis/` 或 `skills/platform/`。
- 如果技能已經有 `scripts/`、`examples/`、`references/` 子目錄，保留原本結構，
  遷移時不用刻意打散重組。

### 常見錯誤

- 通用工具技能裡混入專案特定的檔案路徑、資料庫連線字串——這些屬於環境設定，
  不該寫死在技能裡。
