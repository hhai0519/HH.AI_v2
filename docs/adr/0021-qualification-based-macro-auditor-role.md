# ADR-0021: 資格認定制宏觀審計官與版本庫可見交接架構 (Qualification-Based Macro Auditor & Repo-Visible Handoff)

- Status: Accepted
- Date: 2026-09-16

## Context

專案在 ADR-0007 確立雙角色分工與「執行者不能審自己」之核心不變量時，歷史實作指定由 Claude 擔任宏觀審計官（Macro Auditor）。
然而隨專案演進，實際運作已出現經使用者明確授權、能獨立取得 GitHub 機器證據並完成 Macro Audit 判定之其他代理人（如 GPT 代理審查官）。同時，現行專案規範存在四項結構性缺口：
1. 缺乏顯式契約保證任一時點全庫只能有且恰好有一個活躍宏觀審計官（single active Macro）；
2. 缺乏版本庫可見（repo-visible）之當前審計官指派與交接單一事實來源；
3. 審計官資格綁定於模型品牌而非客觀查證能力；
4. A1 上線自檢要求僅認可審計官自身工作區之本地 full clone，未將「獨立 GitHub API 查證 ＋ 執行者 full clone 交叉核對」正式規格化。

為使宏觀審計官架構轉型為基於資格與授權之供應商中立（provider-neutral）體系，且在不破壞核心安全防線與既有工具鏈的前提下實現平滑交接，需建立統一之架構決策。

## Decision

1. **資格認定制宏觀審計官 (Qualification-Based Macro Auditor)**：
   宏觀審計官為專案之工程治理角色，而非特定模型品牌。模型自我宣稱（如「我是 Claude」、「我是 GPT」或「我是 Gemini」）均不構成身分依據。取得 Macro Auditor 資格必須同時具備：
   - A. 使用者明確授權；
   - B. 與執行者（Antigravity IDE Agent）實質獨立；
   - C. 完成宏觀審計官冷啟動與自檢清單（auditor-selftest）；
   - D. 通過 A1 資格查證（FULL_CLONE 或嚴格 EQUIVALENT）；
   - E. 具備獨立取得 GitHub exact-SHA 遠端機器證據能力；
   - F. 版本庫 `docs/TASKBOARD.md` 之 `**ACTIVE_MACRO_AUDITOR**` 指派指向該審查者。
   本決定正式取代（supersede）ADR-0007 當時指定 Claude 擔任審查官之歷史實作選擇。
2. **單一活躍審計官不變量 (Exactly One Active Macro Auditor Invariant)**：
   在任一版本庫可見之當前狀態，全庫只能存在 exactly one `ACTIVE_MACRO_AUDITOR`。只有專案擁有者（使用者）具備指派 (assign)、替換 (replace)、交接 (handoff) 與撤銷 (revoke) 審計官身分之權限。任何 Agent、session 或提示詞均不得自行搶占或變更該角色。
3. **執行者與審計官同 Agent / Session 永久互斥 (Executor / Macro Same-Agent & Same-Session Mutual Exclusion)**：
   永久保留 ADR-0007 最核心之決策不變量：**執行者不能審自己 (Executor cannot audit itself)**。同一 Agent / conversation / session 若為執行者，嚴禁在該 session 切換為宏觀審計官；審計官 session 亦嚴禁切換為執行者。提示詞或對話宣告絕不能改變此分工邊界。
4. **`.claude/` 目錄保留為歷史相容控制平面 (Compatibility Path Retained)**：
   鑑於現行驗證腳本 (`scripts/check_consistency.py`)、指紋工具 (`scripts/fingerprint.py`)、規則追蹤器 (`scripts/generate_rule_traceability.py`) 與測試套件均已對 `.claude/` 形成確定性機械依賴，嚴禁對該目錄進行全庫更名，亦不得建立鏡像目錄（如 `.gpt/` 或 `.auditor/`）。`.claude/` 實體路徑永久保留，其語意正式定義為「宏觀審計官控制平面（Macro Auditor Control Plane）之歷史相容路徑」。目錄名稱不構成審計官之特定資格限制。
5. **A1 雙軌資格模式 (A1 Dual Qualification Modes)**：
   正式支援兩種確定性 A1 資格模式：
   - **A1 FULL_CLONE**：宏觀審計官自身工作環境實際具有完整 clone（`git rev-parse --is-shallow-repository` 為 `false`），自行查證歷史與 exact-SHA GitHub 證據。
   - **A1 EQUIVALENT**：宏觀審計官必須自行從 GitHub 取得目標 full OID、parent OID、compare 範圍、changed files 與 exact-SHA Actions Verify 機器證據，並由執行者端 local full clone（non-shallow, HEAD==origin/main）提供交叉驗證，兩者關鍵事實完全一致方可成立。A1 EQUIVALENT 絕非單純信任執行者口頭報告，任一關鍵事實無法獨立取得即判定為 `FAIL / NOT ESTABLISHED`。
6. **版本庫可見之審計官單一事實來源 (Repo-Visible ACTIVE_MACRO_AUDITOR)**：
   於現行活動任務看板 `docs/TASKBOARD.md` 頂層設立唯一的 `**ACTIVE_MACRO_AUDITOR**` 標記，作為當前活躍審計官指派之單一事實來源（SSOT）。該標記受 CHECK 8 機械守衛，嚴禁夾帶任何 Git truth（HEAD、commit hash、range、CI run ID），路由文件僅能導航至該標記，不得複製其值。

## Consequences

- **正面影響**：
  - 解除了專案治理對單一 AI 供應商之硬編碼依賴，實現供應商中立之代理人協作架構。
  - 確立了單一活躍審計官與版本庫可見交接機制，避免並行審查與身分漂移。
  - 透過 A1 EQUIVALENT 規格化，使具備 GitHub 存取能力之遠端代理人在嚴格交叉比對下亦能合法履行審查職責。
  - 完整保留 ADR-0007 之權力分立與安全互斥防線，未降低任何審計嚴謹性。
  - 避免了更名 `.claude/` 所引發的大規模機械中斷與假綠燈風險。
- **限制與代價**：
  - ADR-0007 原文依「只追加不改寫」原則保留其歷史實作文字，其決策演進由本 ADR 承接並正式 supersede 其實作選擇。
  - 每次更換審計官必須由使用者授權並發動專門治理批次更新看板標記，流程嚴密但增加單次操作成本。
  - A1 EQUIVALENT 需同時滿足獨立 GitHub 證據與執行者交叉核對，驗收標準與 FULL_CLONE 具備等同之剛性約束。
