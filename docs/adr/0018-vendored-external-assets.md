# ADR-0018: vendored 外部資產保留 fork，並以三層方式標示

- Status: Accepted
- Date: 2026-08-29

## Context

本專案有數個技能的實體內容並非自行撰寫，而是外部開源專案的完整副本（vendored）。
2026-08-29 逐檔查證確認：

| 技能 | 上游來源 | 授權 | 狀態 |
|---|---|---|---|
| `theme-factory` | Anthropic 官方範例技能 | Apache-2.0（`LICENSE.txt` 未填 copyright holder） | 中文化 fork，含 10 份 `themes/*.md` 與 `theme-showcase.pdf` |
| `playwright-automation` | `lackeyjb/playwright-skill` v4.1.0 | MIT（Copyright (c) 2025 lackeyjb） | 完整 vendored，含 `package.json`、`run.js`、`lib/helpers.js`、`.claude-plugin/` |
| `telegram-bot-cdp-bridge` 內的 `telegram-bot-project` | `optimistengineer/remoat` v0.2.14 | 見上游 repo | 完整 vendored（179 檔）+ 使用者自製橋接腳本 |

問題有兩個：

1. `AGENTS.md` 完全沒有規範這類資產該如何標示，遷移後看不出哪些技能是外部副本。
2. 沒有留下「為什麼保留 fork 而不改用上游套件」的紀錄，日後接手者可能自行「優化」
   而破壞可追溯性，或誤以為可以直接用 npm／pip 安裝取代。

## Decision

**一、保留 fork，不改用上游套件安裝。**

- `theme-factory` 已完成中文化，改用官方英文版會使輸出語言與本專案不一致。
- `playwright-automation` 為 v4.1.0 定版，上游後續變更未經本專案驗證。
- `remoat` 內含使用者自製的 `reply_tg.js` 等橋接腳本，直接改用 npm 安裝會遺失這些
  修改，故不能以套件安裝取代 vendored 副本。

**二、以三層方式標示，各司其職：**

1. 技能資料夾內必須保留上游原始的 `LICENSE` / `LICENSE.txt` 檔案，遷移時一併搬入，
   不可省略。Apache-2.0 與 MIT 都要求保留授權聲明，這是授權義務不是選配。
2. `SKILL.md` frontmatter 補 `license` 欄位。`theme-factory` 沿用官方寫法
   `license: Complete terms in LICENSE.txt`；`playwright-automation` 為 `license: MIT`。
   此欄位已列在 `scripts/validate_skills.py` 的 `OFFICIAL_ALLOWED_KEYS` 內，
   不需修改驗證器。
3. 上游 repo 網址與採用版本記在該技能 `REFERENCE.md` 開頭，明確標示它是外部副本。

**三、規則本體寫進 `AGENTS.md` 第 8 節，本 ADR 只留「為什麼」。**

## Consequences

- 接手者一眼可辨識哪些技能不該自行重寫或「順手重構」。
- 上游若有安全性更新，有明確版本號可供比對。
- 代價：上游更新不會自動流入，需人工比對。`theme-factory` 因已中文化，
  回頭 rebase 上游的成本更高。
- 需注意：本規則只解決「標示」，不解決「同步」。日後若要追上游，應另立任務逐檔
  比對，不可直接覆蓋——會沖掉中文化內容與使用者自製腳本。
- `telegram-bot-cdp-bridge` 尚未遷移，遷移時一併套用本規則。