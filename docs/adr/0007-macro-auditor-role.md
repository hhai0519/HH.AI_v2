# ADR-0007: 宏觀審計官角色定位

- Status: Accepted
- Date: 2026-08-17

## Context

隨著遷移批次增加（目前已完成 14 個技能），開始出現單一批次內部核對不到、
但跨批次累積後才顯現的問題，例如：`agency-orchestrator` 的路由說明沒有
同步新增的 `agents/` bucket 技能（拓撲斷鏈的一種）、新舊批次之間
frontmatter 的 `name` 欄位引號寫法不一致（介面不一致）。這些問題單看
一個批次看不出來，需要有一個獨立於「執行遷移」之外的角色，定期對整個
技能庫做全域性的健康檢查。

使用者參考社群上一份「Antigravity Macro Auditor」規劃書，提出四個審計
維度（拓撲完整性、介面一致性、冗餘與收斂、技術鎖定 Scope Lock）與標準化
報告格式，要求正式定義這個角色。

## Decision

### 由誰執行審計

**宏觀審計官由使用者對話中的 Claude 擔任，不由執行遷移的 Antigravity Agent
自己兼任。** 這是核心決策，理由見下方 Consequences 第一點。Antigravity
負責遷移執行與初步的個別技能核對（三層核對，見 ADR-0005），宏觀審計官
在每批次完成 push 後，**獨立 clone 實際 GitHub repo**，核對真實檔案內容，
不依賴 Antigravity 自己產出的文字報告作為審計依據。


### 這個角色怎麼做

四個審計維度、Gatekeeping 規則與標準化報告格式，
規範本體已移至 `.claude/rules/auditor-protocol.md`，本 ADR 只留「為什麼」。


## Consequences

- 為什麼審計者不能是執行者自己：本專案從 ADR-0004（觸發詞/依賴資訊無聲遺失）到 ADR-0005（Zero-Block Policy、硬編碼符號、失效路徑等多輪才抓完的問題）的實際經驗證明，執行遷移的 Agent 自我核對的可信度，跟它願意給出的細節完整程度成正比，而且經常在第一輪回報已完成時遺漏重大問題。讓同一個 Agent 兼任審計官，等於讓自我認證的風險重新滲透回一個原本刻意設計成有獨立查核點的流程。
- 宏觀審計會增加每批次收尾的時間成本（多一輪全域掃描），但避免問題跨批次累積到難以追溯根因的規模。
- 審計報告的合併候選建議不會自動執行，避免宏觀審計官的判斷本身又變成一個需要被審計的黑盒決策來源。
- Scope Lock 原則明確排除了技能適用性與新技術研究，維持這件事是遷移主線之外、需要另外討論才啟動的獨立活動。

## 2026-09-01 分層搬移

依 `PRINCIPLES.md` §1，原 Decision 章節中的「四個審計維度」
「Gatekeeping 規則」「報告格式」（原第 29-70 行）屬可執行規範，
已移至 `.claude/rules/auditor-protocol.md`。

保留在本 ADR 的是：Context 記錄的問題起源、
「由誰執行審計」的決策本體、以及 Consequences 中
「為什麼審計者不能是執行者自己」的推理。

做法比照 `docs/adr/0018-vendored-external-assets.md`——
規則本體放規範層，ADR 只留為什麼。
Context 與 Consequences 原文未變動。
