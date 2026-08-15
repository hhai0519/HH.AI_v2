# ADR-0006: 核心總管與自我進化技能的整併決策

- Status: Accepted
- Date: 2026-08-16

## Context

在第四批·第二小批遷移作業中，系統面臨 4 個舊有 `01_Orchestrators/` bucket 技能的重整：`episodic-consolidation`、`reflection-module`、`self-improvement` 與 `skill-governance-skill`。
經評估，這 4 個技能的設計有過度分散、職責重疊、以及帶有不合時宜（舊版）絕對路徑與危險宣告的問題。

具體發現如下：
1. `reflection-module` 內含多角色批判（Actor/Evaluator/Judge）機制，與現有 `agency-orchestrator` 在 Phase 3 (Dev-QA) 透過實體代理人執行的職責高度重疊。
2. `episodic-consolidation` 負責記憶分類，但原始設計完全缺乏實體儲存路徑的具體指示。
3. `self-improvement` 具有自動覆寫底層技能規範（Procedural Memory）的能力，這是一個極高風險的副作用操作，卻缺乏與 `skill-governance-skill` 中「DLP 與不刪除原則」的強制掛鉤，且沒有限制模型的自主呼叫權限。

## Decision

為解決上述問題，做出了以下整併決策：

1. **合併組一：整併反思與記憶歸檔至 `agency-orchestrator`**
   - **拿掉多角色虛擬批判機制**：直接由總管執行單一角色的「錯誤修正與反思迴圈」，保留 "Sweet & Sour Feedback" 與 "狀態改變評估" 精神，以避免與 Phase 3 的實體代理人疊床架屋並節省 Token。
   - **明確標示路徑風險**：將 `episodic-consolidation` 轉換為 Phase 4 之後的「記憶歸檔機制」，並明確標註「需動態確認當前工作區的知識庫結構，不可使用舊版寫死的絕對路徑」，補足原本缺乏的實體儲存指示。

2. **合併組二：建立 `skill-evolution-governor`**
   - 將 `self-improvement` 與 `skill-governance-skill` 合併為單一技能 `skill-evolution-governor`，並放置於 `skills/meta/` 底下（該路徑負責架構治理與造技能）。
   - **限制自主觸發 (disable-model-invocation: true)**：因為包含真實覆寫其他技能檔案的副作用能力，故在 frontmatter 中強制關閉模型自主觸發，必須由使用者明確要求才能執行。
   - 將 DLP 合規審計標準與不刪除原則，轉變為自我進化修復時的「強制安全邊界」。

## Consequences

- `agency-orchestrator` 的工作流將更加完整，涵蓋了出錯時的閉環修正以及專案結束時的記憶鞏固，而不再需要仰賴外部容易被遺忘的單一技能。
- 透過建立 `skill-evolution-governor` 且限制只能手動觸發，大幅降低了系統因「自動修復」而意外破壞現有良好技能檔案的風險，同時確立了 `skills/meta/` 作為架構治理核心的定位。
- 移除了舊版寫死的模型版本號、系統暫存路徑與違背原則的「Zero-Block Policy」，降低了新系統環境下執行錯誤的機率。
