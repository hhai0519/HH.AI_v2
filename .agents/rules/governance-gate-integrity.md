# 治理閘門完整性與候選提交凍結守衛 (Governance Gate Integrity & Candidate Freeze)

> 本規範為執行者（Executor / Antigravity）必備之第一層操作紀律，定義候選提交治理凍結不變量、必要閘門失敗語意與負向控制要求。

---

## 1. 候選提交治理凍結不變量 (Candidate Governance Freeze Invariant)

一旦候選提交（candidate commit）開始執行第一個 required check 驗證（無論是本機 prospective verify 或遠端 CI run），以下所有治理與裁判表面即刻進入**嚴格凍結狀態（FROZEN）**：

1. 工作流定義：`.github/workflows/**`
2. 統一驗證入口：`scripts/verify_all.py`
3. 規範一致性檢查器：`scripts/check_consistency.py`
4. Required-check 驗證語意（required-check semantics）
5. 決定上述檢查之執行者治理規則（Executor governance rules）
6. 決定候選驗收之審計協定與語意（audit semantics、`auditor-protocol.md`、`auditor-selftest.md`）

### 嚴禁紅燈修改裁判 (No Red-Driven Referee Mutation)

**受測候選者絕不得修改自身裁判（A failing candidate must not modify its own referee）**。
若候選提交在執行 required check 過程中遭遇紅燈，且修復該紅燈需要修改上述任何一項已被凍結的治理表面：
1. **立即停機（STOP）**。
2. 升級回報 `S1 GOVERNANCE_GATE_DEFECT`。
3. 嚴禁使用 M3 自主修復變更裁判規則以使候選者變綠。
4. 必須由 External Macro Auditor 授權並建立獨立的事故修復批次（Incident Batch）進行處置。

---

## 2. 必要閘門失敗與拒絕語意 (Required Gate Failure Semantics)

受保護分支（如 `main`）之必要閘門（Required Gate，包含 `verify`、`gateway-windows` 等）必須具備真實之 Fail-Closed 特性：

1. **真實失敗拒絕（Reject by Actual Failure）**：
   - 驗證失敗時必須以非零退出碼（non-zero exit code）真實標記該步驟與作業為 `failure`。
   - 嚴禁在必要閘門上使用 `skip`、`neutral`、`continue-on-error: true` 或管道屏蔽（如 `| tee`、`|| exit 0`）等語意將失敗轉化為跳過或偽裝成功。
2. **診斷步驟限制（Diagnostic Step Boundaries）**：
   - 失敗後的診斷記錄步驟僅允許使用 `if: failure()` 條件。
   - 該診斷步驟絕不得覆寫或消除前置步驟之失敗狀態，亦不得將整體作業（job）之結論由 failure 轉回 success。

---

## 3. 閘門變更確定性負向控制 (Deterministic Negative Controls)

凡涉及以下任何項目的語意變更或架構重構：
- CI 工作流定義（`.github/workflows/**`）
- 驗證器實作（`scripts/verify_all.py`、`scripts/check_consistency.py`）
- 閘門規則與守衛語意（gate semantics）

**必須同時具備確定性負向控制（Deterministic Negative Control）**：
1. 單純的正面通過測試（positive PASS alone）不足以作為驗收依據。
2. 必須撰寫自動化負向測試或反例金絲雀（counterexample canary），實證該閘門遇到非法、畸形、fail-open 或不合規形態時，必定確定性攔截並回傳失敗（invalid shape is still rejected）。
3. 負向測試必須納入標準驗證套件（如 `scripts/tests/test_check_consistency.py`），防止未來發生假綠燈（false green）退化。

---

## 4. 變更重放與證據完整性守衛 (Diff Replay & Evidence Integrity Guard — B-109 M2 / CHECK 26)

為確保執行期所有變更真實落於授權範圍，且證據具備可驗證之單一事實來源，本專案建立 CHECK 26 作為第三方 CI 與本地一致性檢查之最高重放權威：

1. **CHECK 26 變更重放不變量（Diff Replay Invariant）**：
   - 於 CI 與本地環境中，CHECK 26 透過 `git diff --name-only <base_oid>..<candidate_sha>` 獨立提取候選提交的真實變更集合。
   - 讀取 `docs/governance/execution-record.json`，比對以下三項一致性：
     - `base_oid` 與 `candidate_sha`（或 HEAD）精確相符。
     - 實際異動檔案清單完全等於 `execution-record.json` 中的 `actual_changed_paths`。
     - 實際異動檔案清單嚴格落於 `allowed_mutation_paths` 白名單，且包含全部 `required_mutation_paths`。
   - 任何路徑漂移、未宣告異動、多改或漏改，CHECK 26 立即 Fail-Closed 判定失敗。

2. **證據完整性三項標準（REG-11～13 Integrity Standards）**：
   - **REG-11（PATH-EXISTENCE）**：所有宣告為 `REPO_PATH` 類型之證據來源，其路徑必須於版本庫中實際存在且有效。
   - **REG-12（GENERATOR-IN-BUNDLE）**：所有宣告為 `MACHINE_DERIVED` 之衍生證據，其生成器路徑必須存在於版本庫中，且即時計算之 SHA-256 必須與宣告雜湊值完全一致。
   - **REG-13（REPORT-TRACEABILITY）**：所有報告宣稱（report claims）必須附帶非空之 `evidence_ids`，且引用的證據 ID 必須存在於證據集合中，嚴禁無溯源證據之口頭宣稱。

