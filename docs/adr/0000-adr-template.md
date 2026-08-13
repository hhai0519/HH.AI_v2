# ADR-NNNN: 決策標題（一行）

- Status: Proposed | Accepted | Superseded by ADR-XXXX
- Date: YYYY-MM-DD

## Context

要解決什麼問題？當時有什麼限制或已知資訊？（3-5 句話，不要寫成論文）

## Decision

實際做了什麼決定。用肯定句寫，不要模稜兩可。

## Consequences

這個決定帶來什麼影響——包含犧牲了什麼、之後可能要注意什麼。

---

使用方式：每次對 HH.AI_v2 架構做出「以後很難回頭」的重要決定時（例如新增/刪除
bucket 分類、改變技能依賴方式、決定某類邏輯要不要重寫），複製這份模板到
`docs/adr/000N-短標題.md`，簡短填完即可，不用追求完整。
比起把決策塞進 AGENTS.md 讓文件越改越大，ADR 是「決策留痕、AGENTS.md 保持精簡」
的做法——AGENTS.md 只寫「現在的規則是什麼」，ADR 才寫「為什麼是這樣、當初怎麼決定的」。
