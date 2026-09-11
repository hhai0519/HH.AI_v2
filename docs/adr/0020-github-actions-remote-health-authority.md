# ADR-0020: GitHub Actions 作為專案遠端健康單一權威 (Remote Health Authority)

- Status: Accepted
- Date: 2026-09-11

## Context

在多代理人（Human User、Claude 宏觀審計官、Antigravity IDE Agent、Google Jules、未來外部 Agent）協作環境中，過去各方針對專案健康狀態常出現資訊不對稱與「對齊死結」：
1. 某 Agent 宣稱本地已 PASS，但未考慮 push 到遠端後因環境差異（如 Python/Node 版本、Linux/Windows 跨平台換行符、Git 拓撲 HEAD 推進）導致的潛在失敗。
2. 代理人之間常透過對話文字摘要互相比對健康狀態（例如「Antigravity 說 PASS，但 Claude 懷疑可能 FAIL」），展開耗費大量 token 與溝通成本的口頭辯論，缺乏可信的客觀機器裁判。
3. 歷史失敗的 Actions workflow runs 缺乏結構化歸檔，導致使用者在 GitHub Actions 介面看到紅色失敗 run 時，無法快速辨識究竟是當前 main 存在異常，還是早已修復並落地的封存事故。

為終結文字辯論並確立無可爭議的遠端真實，必須明確劃分本地驗證與遠端健康的權威職責。

## Decision

**一、雙層權威分工 (Dual Authority Separation)**

1. **本地正確性權威 (Local Correctness Authority)**：
   專案根目錄的 `scripts/verify_all.py` 為本地、Prospective Commit、Post-commit 的唯一標準驗證入口（涵蓋 5 大 Correctness Gates：validate_skills, check_consistency, fingerprint, scripts unit_tests, webapp_tests）。本地修改必須 exit 0 才能提交與推送。
2. **遠端專案健康權威 (Remote Project Health Authority)**：
   GitHub Actions 對 exact `origin/main` HEAD 執行的 Verify workflow（`.github/workflows/verify.yml`）為全專案唯一的遠端健康單一事實來源（Single Source of Remote Truth）。
   任何 Agent（包含 Antigravity、Claude、Jules）**不得僅以自己的本地 PASS、文字摘要、使用者轉貼文字或片面宣告來斷定遠端健康**。

**二、Remote Healthy 判定標準 (Strict Criteria)**

宣告 remote healthy 的必要條件為：
1. 取得 exact `origin/main` 的 full commit OID。
2. 查詢 GitHub Actions Verify workflow runs，核對 `head_sha` 必須 **exact match**。
3. 該 run 的 `status` 必須為 `completed`，且 `conclusion` 必須為 `success`。

**三、遠端異常處理規範 (Remote Red Handling & Anti-Debate Policy)**

1. 若 GitHub Actions Verify 出現 red（failure）：
   視為具備最高優先級的 **machine-detected anomaly**。
2. **禁止長篇文字辯論**：
   嚴禁以多 Agent 間的文字比對、猜測取代 Actions 機器證據。所有 Agent 必須直接透過 GitHub API 讀取 exact run 的 `failed job`、`failed step` 與 failure logs，以客觀機器事實為準。
3. **分工與升級**：
   一般 CI 實作/環境失敗，由執行者循 M3 規範自行修復；涉及跨批次架構決策或規則邊界爭議（S1），才升級宏觀審計官。

**四、Actions UI 定位與歷史事故歸檔 (Incident Lifecycle & Cleanup)**

1. **Actions UI 的定位**：
   GitHub Actions UI 是「即時異常監控儀表板 (Remote Project Health Dashboard)」，用以展示「目前是否存在需要關注的異常」，而非永久保存所有歷史事故的倉儲。
2. **歷史知識留痕 (Historical Retention)**：
   歷史事故知識不可僅留存於 Actions run，必須先沉澱歸檔進 repository 文檔（`docs/AUDIT-LOG.md` 與 `SOP/SOP_14_Rigorous_Verification_and_Audit_Protocol.md`）。
3. **清理準則 (Cleanup Barrier)**：
   嚴禁刪除 current red run 來粉飾太平。只有滿足「Root cause 已查明」、「Fix 已在 main」、「Successor Verify 為綠」、「Prevention 機制已落地」、「事故已於文檔歸檔」等全部條件的 closed historical failed runs，經使用者明確授權後，方可自 Actions UI 清理。

## Consequences

- 確立 GitHub Actions Verify 為所有人類與 Agent 共同認可的 Remote Health Authority，終結跨 Agent 的狀態口頭辯論。
- 規範所有 Agent 在 push 後必須機械查證 GitHub Actions run 並比對 full OID，形成閉環。
- 歷史 CI 事故沉澱至 `docs/AUDIT-LOG.md`，為後續 GitHub Actions 儀表板清理提供安全可靠的稽核軌跡。
