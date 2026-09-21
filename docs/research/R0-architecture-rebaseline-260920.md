# R0 Architecture Rebaseline — 2026-09-20

## 1. Purpose and Authority Boundary

本文件記錄 HH.AI_v2 在 T1-bootstrap 前完成的架構重新基準化（architecture rebaseline）。

本文件不是 runtime implementation specification，也不是 commit-level Macro Audit verdict。

權威優先序仍為：

1. current repository / Git / GitHub machine evidence；
2. 使用者正式裁決；
3. repo-visible active contracts；
4. 本研究紀錄；
5. conversation/history 僅可作 context，不是 production authority。

本文件中的 FACT、INFERENCE、UNKNOWN 必須保持分類，不得互相提升。

---

## 2. Timeline

### 2026-09-19

- B-103A replacement repair 已由 External Macro Auditor 接受。
- accepted checkpoint 推進至 `0efd5e3cf0e3147b9546fa5f72f185cdff8d6973`。
- B-103B Phase B same-SHA canary 已取得成功 machine evidence。
- B-103B Phase C GitHub Ruleset cutover 已完成。

### 2026-09-20 — Phase D1

- B-103B Phase D1 Same-SHA Transport Contract Activation Landing 已由 External Macro Auditor 接受。
- main 推進至 `cf2a2b970f9a0cd28c540e70e1afb67e182c8d6f`。
- post-main exact-SHA GitHub Actions Run `35456270854` completed/success。
- repo-visible state 宣告 new transport contract ACTIVE ON MAIN。
- accepted checkpoint 為 `cf2a2b970f9a0cd28c540e70e1afb67e182c8d6f`。

### 2026-09-20 — Phase D2 preserved candidate

- `batch/b103d2-same-sha-proof` 指向 `131a0b19cdd915d6172a750972c69fdb1afdadd9`。
- parent 為 `cf2a2b970f9a0cd28c540e70e1afb67e182c8d6f`。
- exact candidate SHA GitHub Actions Run `35457976070` completed/success。
- required jobs `verify` 與 `gateway-windows` 均成功。
- verify raw log 包含 `ALL 5 GATES PASSED`。
- D2 machine evidence 保留。
- D2 不直接 promotion，因 current-state projection 仍保留過期的 protected-PR 描述。
- D2 不 amend、不 rewrite；T1-bootstrap successor 必須成為 `131a0b1` 的 child。

### 2026-09-20 — User architecture decisions

使用者正式裁決：

- U1：Macro Auditor / User / Executor 角色與協作循環。
- U2：HH.AI_v2 採 Matt Pocock 的架構思維重構，核心原則不變，依本專案現況調整，不照抄 upstream。
- U3：治理機械化，包含 Governance Compiler、task Execution Contract、PASS/FAIL + Rule ID preflight、最多三次 plan revision、escalation、REG、DEGRADED、governance versioning 與 drift monitor。
- K1-A：Transport-Neutral Exact-SHA Invariant。
- K2-A：Phased Mechanical Governance。
- K3-A：Verified Loaded-Surface Kernel。
- K4-C：State Authority Deferred Cutover。
- K5-A：One-Time Bootstrap Authority。
- K6-A：Risk-Tiered Executor Permission Posture。
- Antigravity runtime-dependent conclusions 綁定 verified IDE version 2.5.5。
- production batch 執行途中不得更新 IDE。

### 2026-09-20 — E24 v2

- E24 v2 對 `131a0b19cdd915d6172a750972c69fdb1afdadd9` 執行 deterministic dependency discovery。
- query count = 40。
- unique matched paths = 26。
- External Macro Auditor 檢查原始 ZIP 與 raw discovery。
- raw discovery validator PASS。
- External Macro Auditor 由 raw discovery 獨立重算 dependency hit summary，結果與 bundled summary 相同。
- External Macro disposition：12 UPDATE、5 VERIFY_ONLY、9 HISTORICAL_NO_CHANGE。
- Final T1 mutation scope 為 13 paths，其中 `docs/research/R0-architecture-rebaseline-260920.md` 為 intent-created target。

---

## 3. FACT

### Repository / GitHub

- `origin/main`：`cf2a2b970f9a0cd28c540e70e1afb67e182c8d6f`。
- preserved D2 candidate：`131a0b19cdd915d6172a750972c69fdb1afdadd9`。
- D2 parent：`cf2a2b970f9a0cd28c540e70e1afb67e182c8d6f`。
- D2 可形成 pure fast-forward successor topology。
- GitHub Ruleset `21301111` 為 active。
- ruleset 保留 deletion、non_fast_forward、strict required status checks `verify` 與 `gateway-windows`。
- bypass actors 為空。
- current user cannot bypass the ruleset。

### Historical transport contract evolution

- T1 以前 active transport contract 曾排他性綁定 approved connector `update_ref`。
- transport mechanism 不應作 correctness authority。
- server-side ruleset、exact-SHA external CI 與 same-SHA fast-forward invariant 才是 K1 的 correctness boundary。
- T1 已正式改為 K1-A Transport-Neutral Exact-SHA Invariant，native pinned full-SHA adapter 已透過 `e8ee1edc45b26984fd737ffeb7d3283c744dbb4d` production proof 驗證成功（PRODUCTION-PROVEN / ACCEPTED）。

### IDE 2.5.5 evidence

下列 runtime-dependent 結論只綁定 verified version `IDE 2.5.5`：

- `.agents/rules/*.md` 搭配 `trigger: always_on` 已實測會載入並計入 customization token usage。
- 無 frontmatter 的 rule 不得視為已驗證載入。
- `.agents/skills.json` 宣告的非標準技能路徑沒有在已完成 probe 中載入。
- Hooks 狀態為 `DOCUMENTED_YES / RUNTIME_NO / CAUSE_UNKNOWN`。
- production batch 中途禁止更新 IDE。
- IDE 更新後只做 About version、Rules/token usage、permission/Deny retention 的 UI revalidation；異常時停止 production work。

### E24 evidence

`t1_e24_dependency_discovery_bundle.zip`

- bytes：`17337`
- SHA-256：`37c46b68483192b4b1045676a5f4f56ce5c87c5878e03c4b28e2520e3270b989`

`t1_e24_raw_discovery.json`

- bytes：`33344`
- SHA-256：`edfe3a42d638056fa4a1639a67ef3f5bd23e56a5a9e51301773243b8d106aed4`

raw dependency evidence 經 External Macro 驗證可用。

但 E24 review bundle 的 traceability 並非完全 clean：

- `t1_e24_hit_summary.json` 的 manifest 宣告 generator 為 `generate_hit_summary.py`，但 generator 沒有包含於 ZIP。
- `pre_post_invariant.json` 同時包含 raw captures 與 derived comparisons，卻整體標為 `MACHINE_CAPTURED_RAW`。
- External Macro 已直接從 raw discovery 重新計算 summary 並取得相同結果。

上述 finding 路由至既有 B-107，不另建立 duplicate task。

---

## 4. USER DECISIONS

### U1

ACTIVE_MACRO_AUDITOR、User、Executor 為不同角色。

Executor 不得自行做 Macro semantic disposition 或 Macro acceptance。

### U2

HH.AI_v2 重構採 Matt Pocock 的 architectural thinking，而不是逐檔照抄其 repository。

此決策重新開啟 B-28 與 B-29。

### U3

治理方向：

Plan
→ Mechanical Governance Comparison
→ Execute
→ bounded Plan Revision
→ Escalation。

`MAX_AUTO_PLAN_REVISIONS = 3`。

長期目標包括：

- Governance Compiler
- task-specific Execution Contract
- PASS/FAIL + Rule ID Preflight
- REG regression suite
- DEGRADED state
- governance versioning
- drift monitoring

---

## 5. K1-A — Transport-Neutral Exact-SHA Invariant

Correctness invariant：

1. candidate exact SHA 先取得 required external CI success；
2. origin/main base 未 drift；
3. main advancement 必須為 pure fast-forward；
4. main 接收與已檢查 candidate 完全相同的 SHA；
5. 禁 force 與 SHA transformation；
6. post-main 再驗證同一 exact SHA；
7. transport 只是 adapter；
8. 每一 batch 只能明確選擇一個 adapter；
9. adapter unavailable 或 rejected 時必須停止；
10. 禁止 silent fallback。

T1 的 candidate adapter 是 native pinned full-40-char SHA refspec：

`<FULL40_SHA>:refs/heads/main`

禁止：

- `+` refspec
- `--force`
- `--force-with-lease`
- symbolic source
- rebase-after-check
- cherry-pick-after-check
- squash-after-check

此 adapter 已透過 e8ee1edc45b26984fd737ffeb7d3283c744dbb4d production proof 驗證成功（PRODUCTION-PROVEN / ACCEPTED）。

---

## 6. K2-A — Phased Mechanical Governance

### M1

- minimal Rule Registry
- task-specific Execution Contract
- PASS/FAIL + Rule ID Preflight
- incident-derived REG
- K6
- transport guard
- active-state projection guard

### M2

- plan-vs-actual
- CI diff replay
- B-107 evidence-integrity hardening

### M3

- actual loaded-surface governance
- B-106
- state convergence
- K4 cutover decision

### M4

- skill exploration
- Jules
- capability semantics

完成 T1 後依序進行 M1 → M2 → M3。
M4 必須在 Jules enablement 前完成。

---

## 7. K3-A — Verified Loaded-Surface Kernel

已驗證 kernel：

- `AGENTS.md`
- 實測成立的 `.agents/rules/*.md` + `trigger: always_on`

沒有 frontmatter 的 rule 不算已驗證載入。

`model_decision` runtime behavior 仍為 UNKNOWN。

任務專屬規則長期應由 task Execution Contract 提供。

B-106 負責 actual loaded-surface token budget、compatibility 與 truncation。

---

## 8. K4-C — State Authority Deferred Cutover

M1 不更換 `docs/TASKBOARD.md` 的 remaining-work authority。

先建立 drift regression coverage。

machine-readable dynamic state + derived views 的 authority cutover 留到 M3 決策。

---

## 9. K5-A — One-Time Bootstrap Authority

具備能力的 Executor 可在 T1 使用 K1 candidate adapter進行一次 bootstrap promotion。

promotion 前提：

- candidate exact-SHA external CI PASS；
- main base 未 drift；
- K6 已生效；
- 只有 External Macro 在 Macro PASS 後發出的 unique full-40-char SHA promotion prompt 授權 main advancement，其他 prompt 一律禁止 main advancement；
- ancestry 與 ruleset 保持 active；
- 禁 force；
- 禁 silent fallback；
- same-SHA advancement；
- post-main 同一 SHA external CI PASS；
- External Macro final audit。

Macro Auditor 永不執行 repository / GitHub mutation。

T1 完成以前，emergency rollback 僅能由使用者本人 break-glass。

### 2026-09-20 USER DECISION UPDATE

使用者正式修改 K5-A：
- 撤銷舊條件「main push 必須經使用者明確批准」。
- promotion authorization 改由 External Macro 發出之 unique full-40-char SHA promotion prompt + server-side ruleset + same-SHA verification + External Macro final audit 共同承擔。
- mechanical promotion authorization verification 列入 B-109 M1。

---

## 10. K6-A — Risk-Tiered Executor Permission Posture

保留：

- Full access
- Always Proceed

但：

- destructive / main-push command 應進 Deny list；
- GitHub MCP write tools 應移除 permanent Allow；
- 舊 repo `.env.local` write allow 應移除；
- 不存在 `.gemini\antigravity\skills` 路徑的 read allow 應移除；
- browser GitHub mutation 不得 unconditional allow。

History 與 Knowledge 可保留。

但是跨對話資料只屬 context，不是 production authority。

production-impact facts 必須由 current repo / Git / GitHub 重新驗證。

---

## 11. Evidence Governance Direction

B-107 承接：

### EVIDENCE-ORIGIN

- `MACHINE_CAPTURED_RAW`
- `MACHINE_DERIVED`
- `AGENT_ASSERTED`
- `USER_PROVIDED`

`verification_status` 必須與 evidence origin 分離。

### Integrity requirements

- PATH-EXISTENCE
- GENERATOR-IN-BUNDLE
- REPORT-TRACEABILITY

### Regression routing

REG-11～REG-13 承接已發生的 evidence provenance / report truth drift 類型。

---

## 12. Historical Evidence Hash Registry

以下為交接中保留的 historical evidence identities。

除了本文件明確標為 current-session External Macro verified 的 E24 artifacts 外，其他項目屬 historical handoff evidence identity；本文件不把它們提升為本 session 重新取得的 machine evidence。

| Evidence | Bytes | SHA-256 |
|---|---:|---|
| `t0_g0_evidence_bundle.zip` | 104178 | `9006303889e2a1e5afbb75526d6d7cbff547643a7c2348a6c18e1ecb75297466` |
| `generate_t0_g0.py` | not recorded here | `b4c85268e65ac1f9c15ad24cdf13dd86b1e5d9e57862c9720bdf9543579bf926` |
| `t0_g0_k1k5_supplement_bundle.zip` | 126473 | `4a3fd7047b573dc41e5663833ee0d712db1300b9b2efc840052dbdd60ab9c0a9` |
| `hook_probe_v4_review_bundle.zip` | 6784 | `f27a65a00b65a857304ecfe908530a5582f23190224a5dc6100e0ab9d0f29605` |
| `agy_customization_discovery_bundle.zip` | 35060 | `fa228d970de83094655df57da53831fb80bd4487026909c3ffc12a1e90bf978f` |
| `agy_final_customization_probe_review_bundle.zip` | 9902 | `57c7ca47dfc245f37dc7a34881622e03237558635276d190eff539c7b736cb7d` |
| `t1_e24_dependency_discovery_bundle.zip` | 17337 | `37c46b68483192b4b1045676a5f4f56ce5c87c5878e03c4b28e2520e3270b989` |

E24 bundle 與 raw discovery 已由 current External Macro session 重新驗證。

其他 raw originals 由使用者在 repo-external / local evidence custody 保管。

不得把 ZIP、base64 evidence、conversation transcript 或本機 absolute path 放進 repo。

---

## 13. Withdrawn or Downgraded Conclusions

以下結論不得再作 current authoritative fact：

### 389 heuristic classifications

狀態：

`UNVERIFIED EXECUTOR-DERIVED`

不得作正式 inventory truth。

### Missing test-file coverage claims

先前 REG coverage 曾引用不存在的測試檔。

不得以不存在檔案宣稱 regression coverage。

### PROJECT_OVERRIDES_GLOBAL = true

缺乏來源。

撤回。

### 773123 chars

不得稱為 total customization budget。

若保留該歷史量測概念，只能稱：

`MEASURED_GOVERNANCE_SURFACE`

不能推導為 runtime loaded surface。

### Matt lifecycle phrasing claim

撤回。

### Matt generated README claim

撤回。

---

## 14. INFERENCE

以下不是已 production-proven fact：

- native pinned full-40-char SHA push 是目前 T1 candidate transport adapter；
- 它符合 K1 invariant 的設計條件；
- 它是否能在 current server-side ruleset 下真正 production fast-forward main，仍需 T1 promotion proof。

不得把 inference 提升為 FACT。

---

## 15. UNKNOWN

以下維持 UNKNOWN：

- native pinned SHA adapter 的 production acceptance 已於 e8ee1ed 驗證通過（PRODUCTION-PROVEN / ACCEPTED）；
- `model_decision` runtime behavior；
- standard `.agents/skills/<name>/` loadability；
- Hooks runtime ineffective 的根因；
- MCP configuration precedence / source；
- MCP token / permission scope 的完整語意；
- current GitHub Actions retention exact setting，直到 machine-read 後才能引用。

UNKNOWN 不得被 Executor 自行補答案。

---

## 16. T1 Scope

T1-bootstrap successor 只處理：

- transport-neutral K1 contract；
- rollback K1 contract；
- stale active-state projection；
- U1/U2/U3 與 K1-K6 repo registration；
- B-106/B-107/B-108 scope correction；
- B-109 Mechanical Governance v1 registration；
- E24 evidence-integrity instance routing；
- two minimal mechanical guards；
- research record；
- EXEC evidence / generated artifacts。

T1 不開始：

- full Governance Compiler；
- full M1-M4 implementation；
- product runtime implementation；
- Jules enablement；
- skill migration；
- main promotion。

---

## 17. Post-T1 Direction

T1 candidate 必須先：

1. batch exact-SHA external CI PASS；
2. External Macro pre-promotion audit；
3. 使用者完成 K6 UI posture；
4. 另行授權 T1 promotion；
5. same-SHA main push；
6. post-main same-SHA CI；
7. External Macro final closure。

T1 完成後：

M1
→ M2
→ M3
→ 回到 E-03 product runtime mainline。

M4 必須在 Jules enablement 前完成。

---

## 18. Security and Process Incident Disposition Note

本批 promotion execution 發生憑證邊界與流程違規（Security / Process Incident = CONFIRMED）：

- **舊 GCM OAuth credential exposure = CONFIRMED**：Executor 執行 `git credential fill` 取得 GitHub OAuth credential 並進入 transcript/command text。嚴禁將任何 credential value、前綴、後綴、長度或 hash 寫入 repo。
- **使用者端圍堵完成（USER_PROVIDED Containment = COMPLETED）**：
  - 使用者已於 GitHub Authorized OAuth Apps 撤銷 Git Credential Manager 授權。
  - 使用者已從 Windows Credential Manager 移除 `git:https://github.com`。
  - 使用者本人隨後於本機 PowerShell 透過 `git credential-manager github login`（GCM 2.9.0）以瀏覽器重新登入成功。
- **GITHUB_PERSONAL_ACCESS_TOKEN unauthorized read/use = CONFIRMED**：PAT value exposure = NOT_ESTABLISHED（無洩漏證據）。
- **cross-session transcript access = CONFIRMED**：Executor 讀取另一 session 之 transcript.jsonl 作為證據來源。
- **git checkout <path> rollback instance = CONFIRMED**：destructive local rollback coverage gap。
- **Remote evidence ownership 確立**：raw GitHub Actions job log 由 External Macro Auditor 負責驗證；Executor 僅限透過安全、匿名或已授權中繼管道回報 metadata；若無安全管道取得，回報 `UNKNOWN / DEFER_TO_EXTERNAL_MACRO`，禁止突破 credential 邊界。
- **K6-A UI posture**：APPLIED（USER_PROVIDED，IDE 2.5.5，before closure batch）；復原基準見 `docs/ops/antigravity-environment-baseline.md`。
- **治理防護路由**：B-108、B-109 M1 與 B-107 where applicable。
