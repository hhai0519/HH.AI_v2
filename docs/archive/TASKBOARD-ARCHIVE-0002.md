# 任務看板封存 0002

> 本檔由 `scripts/taskboard_archive.py apply` 產生，寫成後不得修改。清單與每列的 SHA-256 在 `TASKBOARD-ARCHIVE-MANIFEST.json`，由 CHECK 29 逐位元組核對。
> 封存不是刪除：下列各列是封存當時 `docs/TASKBOARD.md` 的原文（單行），逐字保留。
> 封存批次：B117-G7B2-ARCHIVE-CHECK30-261118；封存當時 checkpoint：`012e66cfd03ec087f01cf7009c96d9d3fafb385f`

## 封存列

### TG-MVP-01A

- 原位置：`docs/TASKBOARD.md`「E. 舊 repo 遷移主線（`refactor-backlog.md` §二 A–F）」第 463 行（封存前）
- 封存時狀態：已完成
- 封存依據：MACRO_PASS_ANCESTOR（1f98818af8ed38df2b3401685deee159e11a2080）

````text
| TG-MVP-01A | 已完成 | **RECON-01 歷史待辦需求機械對帳與治理收斂**（RECON-01 Historical Pending Requirement Reconciliation）：對帳歷史待辦事項（A–S）、過期架構標記（STALE-1..3）、孤兒需求（ORPHAN-1..4）至權威落點；同步 G1 審核通過裁決與 checkpoint；建立 M-TG-POST-MVP 與橫向殘留傘狀任務；零生產程式碼修改。 | RECON-01 規格書、使用者授權 | TG-MVP-01 | commit 1f98818af8ed38df2b3401685deee159e11a2080，Actions Run 35295573430 success，External Macro PASS / ACCEPT ALL（accepted checkpoint = 1f98818af8ed38df2b3401685deee159e11a2080） |
````

### TG-MVP-03

- 原位置：`docs/TASKBOARD.md`「E. 舊 repo 遷移主線（`refactor-backlog.md` §二 A–F）」第 466 行（封存前）
- 封存時狀態：已完成
- 封存依據：MACRO_PASS_ANCESTOR（4db5d498fa035e14c8628540ce269627aa038ea1）

````text
| TG-MVP-03 | 已完成 | **R2/R3 架構決策 ADR 落地**（R2/R3 Architecture ADR）：記錄 R2（Capability-Aware Retry + Durable Outbox）與 R3（Loopback HTTP v1 127.0.0.1 HMAC；Named Pipe 延後；R2-3 Option B IDE 查看）決策。注意：僅 ADR 落地，不含程式碼實作。 | 使用者正式裁決 R2、R3、R2-3、ADR-0022 | TG-MVP-01 (G1) | commit `4db5d498fa035e14c8628540ce269627aa038ea1`，Actions Run 35306399675 success，External Macro PASS / ACCEPT ALL（TG-MVP-03-F1 RESOLVED，accepted checkpoint = `4db5d498fa035e14c8628540ce269627aa038ea1`） |
````

### TG-MVP-04

- 原位置：`docs/TASKBOARD.md`「E. 舊 repo 遷移主線（`refactor-backlog.md` §二 A–F）」第 467 行（封存前）
- 封存時狀態：已完成
- 封存依據：MACRO_PASS_ANCESTOR（18867eb5af7c4b90df8946c22977350bf7ec5086）

````text
| TG-MVP-04 | 已完成 | **F1 回覆授權身份鍵修復**（F1 Reply Authorization Identity Repair）：修正 `validateReplyAuthorization()` SQL 查詢，將單純 `channel_id + platform_msg_id` 查找改為納入 `account_id`，對齊 schema v3 `UNIQUE(account_id, platform_msg_id)` 複合鍵，避免合法回覆被誤判 ACCOUNT_MISMATCH。 | F1 Material Finding、schema v3 inbox 定義 | TG-MVP-02 (Identity ADR) | commit `18867eb5af7c4b90df8946c22977350bf7ec5086`，Actions Run 35307539503 success，External Macro PASS / ACCEPT ALL（accepted checkpoint = `18867eb5af7c4b90df8946c22977350bf7ec5086`） |
````

### TG-MVP-06

- 原位置：`docs/TASKBOARD.md`「E. 舊 repo 遷移主線（`refactor-backlog.md` §二 A–F）」第 469 行（封存前）
- 封存時狀態：已完成
- 封存依據：MACRO_PASS_ANCESTOR（e60fedb6fbaade0ec725d28fc83f1e47cfb13943）

````text
| TG-MVP-06 | 已完成 | **B-98 憑證與機密強化**（B-98 Secret/Credential Hardening）：在啟用真實 Telegram Bot Token 或 Local API HMAC secret 前，落實金鑰與機密存取安全邊界，防止 token 洩漏。 | 看板 B-98、安全防護原則 | TG-MVP-01 (G1) | commit e60fedb6fbaade0ec725d28fc83f1e47cfb13943，Actions Run 35331712071 success（jobs: verify = success, gateway-windows = success），External Macro PASS / ACCEPT ALL（F1-A, F1-B, F2 RESOLVED，accepted checkpoint = e60fedb6fbaade0ec725d28fc83f1e47cfb13943），B-98 CLOSED |
````

### TG-MVP-07

- 原位置：`docs/TASKBOARD.md`「E. 舊 repo 遷移主線（`refactor-backlog.md` §二 A–F）」第 471 行（封存前）
- 封存時狀態：已完成
- 封存依據：MACRO_PASS_ANCESTOR（f73a076d5ef4184735a6586a7069c66a6ba54bcc）

````text
| TG-MVP-07 | 已完成 | **B-30 + B-33 Gateway 固定通訊埠與顯式目標收斂**（Gateway fixed port / explicit target convergence）：清理舊 repo 殘留之 port 3000/3001 衝突，確立 Gateway 專屬監聽 port 與目標端點規範。 | 看板 B-30、B-33、ADR-0022 | ACCEPTED / CLOSED；commit `f73a076d5ef4184735a6586a7069c66a6ba54bcc`，candidate Run 35754936655 success，post-main Run 35802245822 success；External Macro PASS / ACCEPT ALL；accepted checkpoint = `f73a076d5ef4184735a6586a7069c66a6ba54bcc`。 | Port 配置統一，無殘留衝突硬編碼 |
````

### TG-MVP-07A

- 原位置：`docs/TASKBOARD.md`「E. 舊 repo 遷移主線（`refactor-backlog.md` §二 A–F）」第 472 行（封存前）
- 封存時狀態：已完成
- 封存依據：MACRO_PASS_ANCESTOR（6fc880947af0a65f356857f92aed606da5404505）

````text
| TG-MVP-07A | 已完成 | **D24 本機外部配置基礎建設**（D24 Repo-External Local Configuration Foundation）：實作中央本機外部設定檔載入與驗證，涵蓋 archive root、attachment temp、SQLite state path、logs、protected roots 清單、Gateway local port、Windows Known-Folder 預設值與啟動 fail-closed 防護。 | ADR-0022 D24 | ACCEPTED / CLOSED；final implementation SHA `6fc880947af0a65f356857f92aed606da5404505`；revision_count 2；candidate Run 35815942965 success；post-main Run 35816688934 success；External Macro PASS / ACCEPT ALL；accepted checkpoint = `6fc880947af0a65f356857f92aed606da5404505`；Local Config v2、gateway.localPort 3003、Windows Known-Folder defaults、startup fail closed / zero auto-create、no listener。 | Local config loader 完整測試通過 |
````

### TG-MVP-08

- 原位置：`docs/TASKBOARD.md`「E. 舊 repo 遷移主線（`refactor-backlog.md` §二 A–F）」第 473 行（封存前）
- 封存時狀態：已完成
- 封存依據：MACRO_PASS_ANCESTOR（bcc59d976dd5510108bcd15917a91249fdf35411）

````text
| TG-MVP-08 | 已完成 | **T9 封存並退役舊版凍結 JSON 運作模組**（T9 retire frozen JSON operational modules）：退役舊版基於 JSON 檔案的通道狀態模組，全面轉移至 SQLite Repository。 | 看板 E-03、ADR-0022、ADR-0023 | TG-MVP-07A ACCEPTED / CLOSED | ACCEPTED / CLOSED；final implementation SHA bcc59d976dd5510108bcd15917a91249fdf35411；candidate Run 35823024382 success；post-main Run 35823862270 success；External Macro PASS / ACCEPT ALL；accepted checkpoint = bcc59d976dd5510108bcd15917a91249fdf35411；three frozen JSON core modules deleted；three dedicated legacy suites deleted；zero replacement / shim / fallback；SQLite sole operational state authority；anti-resurrection guard accepted；no real user-data migration。 |
````

### TG-MVP-09

- 原位置：`docs/TASKBOARD.md`「E. 舊 repo 遷移主線（`refactor-backlog.md` §二 A–F）」第 474 行（封存前）
- 封存時狀態：已完成
- 封存依據：MACRO_PASS_ANCESTOR（2e34380663fade80f3a39d4fdb6dacde8a26d9a1）

````text
| TG-MVP-09 | 已完成 | **T11-main 正式線上備份整合**（T11-main）：保持 repo 既有定義，將 T11A 所驗證之 SQLite online backup primitive 整合進正式運作流程與備份排程。 | T11A 完成證據、SQLite 線上備份規範、ADR-0023 | TG-MVP-08 ACCEPTED / CLOSED | ACCEPTED / CLOSED；final implementation SHA 2e34380663fade80f3a39d4fdb6dacde8a26d9a1；initial candidate 6f2b6e8bd736399876a7ffe48cd703668f3937d8（Run 35842563580，Macro HOLD，F1–F5）；R1 candidate 2e34380663fade80f3a39d4fdb6dacde8a26d9a1（Run 35848844279，F1–F5 RESOLVED，Macro PASS / ACCEPT ALL，promotion eligible PASS）；same-SHA main promotion 成功推進；post-main exact-SHA Run 35849896893 驗證成功（verify success，gateway-windows success）；T11-main operational periodic verified backup integration complete；T11A primitive unchanged；24h freshness threshold (86_400_000 ms)；1h overdue check (3_600_000 ms)；startup overdue catch-up；no unconditional startup backup；no shutdown backup；overlap skip；periodic failure non-fatal；bounded non-secret logging；verified backup return contract validation；UUID-v4 canonical backup filename；provisional in-process owner (BackupRuntimeOwner)；no second daemon；Local Config schema remains v2；zero retention / cleanup in TG-MVP-09；TG-MVP-09A MUST COMPLETE BEFORE REAL TELEGRAM GO-LIVE。 |
````

### TG-MVP-09A

- 原位置：`docs/TASKBOARD.md`「E. 舊 repo 遷移主線（`refactor-backlog.md` §二 A–F）」第 475 行（封存前）
- 封存時狀態：已完成
- 封存依據：MACRO_PASS_ANCESTOR（c6cd9c9986f5834b9777197c7c0012c08d85a3bb）

````text
| TG-MVP-09A | 已完成 | **狀態資料庫與備份清理衛生規範**（State Database & Backup Hygiene）：實作 SQLite 路徑 repo-external 強制驗證、repo state 檔案 ignore 防護（.gitignore *.sqlite3 等）、遷移備份保留期限（retention）、備份清理（cleanup）、備份隱私與完整性防護，並建立 future node:sqlite 穩定性與 Node 升級守望點。**HARD GO-LIVE GATE AFTER TG-MVP-09：必須在 real Telegram go-live 前完成**。 | ORPHAN-1、ORPHAN-2、ORPHAN-4、ADR-0023 | TG-MVP-09, TG-MVP-07A | ACCEPTED / CLOSED；final implementation SHA `c6cd9c9986f5834b9777197c7c0012c08d85a3bb`；R0 `50503a5dd33e8092e153c6f8f3255594449b9cfb`（Run 35965479245，Macro HOLD / cross-platform test harness repair）；R1 `c1763878aef3c0d87a0a3eddbcf3c3956f55eb19`（Run 35969326893，Macro HOLD，F1–F3）；R2 `c6cd9c9986f5834b9777197c7c0012c08d85a3bb`（Run 35974805223，F1/F2/F3 RESOLVED，Macro PASS / ACCEPT ALL）；mutation proof M3/M4/M5/M10 = RED；same-SHA promotion ACCEPTED；post-main Run 35976037151 verify success, gateway-windows success；TG-MVP-09A hard go-live gate SATISFIED / CLOSED。 |
````

### TG-MVP-10

- 原位置：`docs/TASKBOARD.md`「E. 舊 repo 遷移主線（`refactor-backlog.md` §二 A–F）」第 476 行（封存前）
- 封存時狀態：已完成
- 封存依據：MACRO_PASS_ANCESTOR（fde3121c93fe1e25f6802cff2f48a51a253c383c）

````text
| TG-MVP-10 | 已完成 | **Telegram 測試機器人入站適配器**（Telegram Test-Bot inbound adapter）：實作 Telegram 長輪詢（long polling）入站適配器，將 Telegram update 轉換為標準 inbox 訊息並呼叫 `ingestMessage()`。 | ADR-0022、TG-MVP-02 (Identity ADR)、TG-MVP-06 (B-98) | TG-MVP-02, TG-MVP-05, TG-MVP-06, TG-MVP-06A | ACCEPTED / CLOSED；final implementation SHA `fde3121c93fe1e25f6802cff2f48a51a253c383c`；candidate Actions Run 36092485633 success；post-main exact-SHA Run 36093663314 success（verify=completed/success, gateway-windows=completed/success）；External Macro PASS / ACCEPT ALL，R3-F1～R3-F8 全數 RESOLVED，NEW MATERIAL BLOCKING FINDING = NONE；SM1–SM15 = 15/15 valid semantic RED（16/16 count-label inconsistency 登錄 B-107，不重啟 TG-MVP-10）；single-use main auth 消耗通過；same-SHA main promotion 完成；accepted checkpoint = `fde3121c93fe1e25f6802cff2f48a51a253c383c`。 |
````

### TG-MVP-11

- 原位置：`docs/TASKBOARD.md`「E. 舊 repo 遷移主線（`refactor-backlog.md` §二 A–F）」第 477 行（封存前）
- 封存時狀態：已完成
- 封存依據：MACRO_PASS_ANCESTOR（3d94bc2ccd26870b133d1dca217bb03e1c4cf767）

````text
| TG-MVP-11 | 已完成 | **迴路 Local API v1 實作**（Loopback Local API v1）：實作僅限 127.0.0.1 監聽、具 HMAC 簽署驗證的 HTTP 介面，供外部 Agent 派發發送請求與查詢狀態。 | 使用者裁決 R3、TG-MVP-03 (R3 ADR)、TG-MVP-06 (B-98)、TG-MVP-04 (F1)、TG-MVP-07A、使用者 binding 裁決 D-TG11-3 | TG-MVP-03, TG-MVP-04, TG-MVP-06, TG-MVP-06A, TG-MVP-07A | ACCEPTED / CLOSED；final implementation SHA `3d94bc2ccd26870b133d1dca217bb03e1c4cf767`；initial candidate `0901e06b8d3a2a68a3ae4d2bc12309859943e199`（Run 36135220532 success, Macro HOLD F1–F8, D-TG11-3 accepted）；R1 candidate `b5f3b2869d41a015916b7a4e59633949a80fdab6`（Actions Run 36142580126 gateway-windows success, verify failure, Macro HOLD due cross-platform test design defect）；final R2 `3d94bc2ccd26870b133d1dca217bb03e1c4cf767`（candidate Run 36145856257 success, post-main Run 36147638120 success, External Macro = PASS / ACCEPT ALL, F1–F8 = RESOLVED, D-TG11-3 = PASS, R2 CROSS-PLATFORM REPAIR = PASS, R2-M1 = valid semantic RED / PASS, NEW MATERIAL BLOCKING FINDING = NONE, ROLLBACK = NOT REQUIRED, same-SHA promotion = PASS, post-main CI = PASS）；accepted implementation checkpoint = `3d94bc2ccd26870b133d1dca217bb03e1c4cf767`；B-107 remains residual/non-blocking。 |
````
