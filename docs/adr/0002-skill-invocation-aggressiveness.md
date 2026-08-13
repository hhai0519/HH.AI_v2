# ADR-0002: 技能自動觸發的積極程度，依 bucket 風險分級

- Status: Accepted
- Date: 2026-08-09

## Context

參考 [obra/superpowers](https://github.com/obra/superpowers) 的 `using-superpowers`
技能，它的核心規則是「只要有 1% 可能技能相關，agent 就必須主動觸發，不能自己判斷
要不要用」。這對一般軟體開發流程是合理的紀律（避免 agent 憑印象亂做，跳過已有的
最佳實踐）。

但 HH.AI_v2 的 `skills/agents/` bucket 底下是會實際執行動作的技能（下單、發送
LINE 訊息、寫入生產資料庫），如果套用「機率極低也要觸發」的邏輯，等於降低了
高風險技能被誤觸發的門檻。

## Decision

依 bucket 風險程度採用不同的觸發積極度：

- `orchestration/` `analysis/` `execution/` `platform/`：可以參考 superpowers 的
  積極觸發精神——技能相關就該用，不用等使用者明確要求。
- `agents/`：維持根目錄 `AGENTS.md` 第 5 節原本的保守標準，`disable-model-invocation`
  的判斷依據是「模型自主呼叫是否安全」，不因為「可能有幫助」就放寬。

## Consequences

- 兩種積極度並存，需要在根目錄 `AGENTS.md` 第 5 節明確寫清楚這個差異，避免
  之後有人（或 agent 自己）誤以為所有技能都該套用同一套觸發標準。
- 好處：低風險 bucket 保持高召回率（該用的技能都會被用到），高風險 bucket
  保持保守，兩者不互相犧牲。
