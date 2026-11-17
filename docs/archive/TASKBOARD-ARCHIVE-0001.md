# 任務看板封存 0001

> 本檔由 `scripts/taskboard_archive.py apply` 產生，寫成後不得修改。清單與每列的 SHA-256 在 `TASKBOARD-ARCHIVE-MANIFEST.json`，由 CHECK 29 逐位元組核對。
> 封存不是刪除：下列各列是封存當時 `docs/TASKBOARD.md` 的原文（單行），逐字保留。
> 封存批次：B117-G7B1-ARCHIVE-MECHANISM-R2-261117；封存當時 checkpoint：`7571108385961462fcceef8fd3593b150ab85d7e`

## 封存列

### B-06

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 282 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| B-06 | 可封存 | `description` 引號寫法收斂（26 加／28 未加） | 純格式收斂，parser 支援 quoted/unquoted，無 production correctness 價值，可予封存，不得為此異動技能 |
````

### B-10

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 286 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| B-10 | 可封存 | **Jules 協作規範：USER 2026-11-01 撤回／OBSOLETE（非已實作）** | Google 官方 2026-10-29 Jules Turndown；2026-11-11 後唯讀、2026-12-31 關閉。禁止依本舊列啟用 Jules；J1／J2 退役及憑證／外部權限處置由 B-127 接續；歷史決策與證據保留。 |
````

### B-12

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 288 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| B-12 | 可封存 | **`audited-*` tag 落後偵測（CHECK 16）** | 被 AUDIT-LOG、refactor-backlog §5.1 與 GitHub Actions Remote Health Authority supersede。audited-* tag 已退役為 legacy historical markers，失去 active authority 用途，不再實作 tag-lag CHECK。 |
````

### B-16

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 292 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| B-16 | 可封存 | **全庫規則的一次性回溯稽核** | 重構至今所有規則與 backlog 的歷史宣稱，多數是審計官在對話中推算而非實測，從未被機械驗證。實測規模：規則檔 11 份共 1,939 行（含 43 處日期宣稱、8 處「第 N 次」計數宣稱），`refactor-backlog.md` 1,941 行 42 個編號項目（含 79 處日期宣稱）。**審計官已被抓到過四次數字錯誤（7 個檔案、15 個檔案、848 行、89／211 行），沒有理由相信這些未驗證的宣稱是對的。** 拆為三批：**R1** 八處「第 N 次」計數（**2026-09-06 使用者裁決改判為交接後執行**：R1 修正的是留痕層的歷史數字，不影響新 Agent 的行為判斷；該裁決原僅存於交接區 §5.4，本批搬入本列與 `docs/refactor-backlog.md` 第 53 點 B 段）、**R2** 規則檔 43 處日期（可後做）、**R3** backlog 42 點的內部一致性（可後做） |
````

### B-17

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 293 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| B-17 | 可封存 | **章節語意變更偵測** | 來自 A-29 行為 1 的缺口。CHECK 10 驗證 `§X.Y` 指向的章節是否**存在**，但抓不到「章節仍存在、語意已變」——例如交接區 §5.2 現在只剩一行指標，引用它的「優先序」已失效但章節仍在。舊實作用三個硬編碼字串處理，零通用性。**須重新設計**：可能方向是比對章節的行數或內容雜湊在批次間的變化，對引用該章節的位置提出警示。**可交接後做** |
````

### B-21

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 297 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| B-21 | 可封存 | **CHECK 16 編號被兩件事佔用** | 已由 B-60 規劃案吸收，不再作為獨立可執行待辦。 |
````

### B-26

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 302 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| B-26 | 可封存 | **攔截點缺少執行時點** | 已由 B-92 EXEC-LOG 狀態流轉與 prospective commit 驗證機制徹底解決。 |
````

### B-35

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 311 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| B-35 | 可封存 | **雙代理事實指紋與 Dashboard** | Stage 1 指紋與驗證已實作；Stage 2/3 (dashboard.html/GitHub Pages) 被 ADR-0020 與 GitHub Actions Remote Health Dashboard 完全取代。 |
````

### B-38

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 314 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| B-38 | 可封存 | **驗證腳本加 `--quiet` / `--json` 模式** | 原始 Claude context pollution 已由 B-36 Repo Evidence Channel 徹底消除，終端機輸出不進入對話，可予封存 |
````

### B-39

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 315 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| B-39 | 可封存 | **獨立性的來源從審計官轉移到 CI** | CI 獨立性核心已由 Canonical Entrypoint (verify_all.py) + GitHub Actions exact SHA Verify + ADR-0020 實質完成。 |
````

### B-48

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 324 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| B-48 | 可封存 | **「回報即 commit」無法容納 commit 之後才發生的事** | 被 ADR-0020 supersede（由 GitHub Actions Verify 作為遠端權威，避免雙 commit 遞歸死結）。 |
````

### B-49

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 325 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| B-49 | 可封存 | **CI 獨立查證的規則化與機械化** | 被 ADR-0020、AGENTS.md §10、git-and-reporting.md §2.5 與 README Verify badge supersede。 |
````

### B-55

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 331 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| B-55 | 可封存 | **治理層已分裂成兩個速度** | 實測最後修改日：稽核迴圈檔案 09-05～09-06；作業層 SOP_01／02／05／06／09／11／12／13 停在 2026-08-25（12 天）；**`.agents/rules/skills-architecture.md` 停在 2026-08-13（24 天，全庫最舊）——而它正是 B-01 的目標檔案**。處置：文件時效偵測（若未來實作新 CHECK，ID 必須於 implementation time machine-derive）。排批 2e |
````

### B-57

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 333 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| B-57 | 可封存 | **審查機制的完成定義（五條可機械驗收）** | 原五項 acceptance 已被後續 Governance Exit criteria 取代；仍有效的 residual risks 由現行 concrete tasks（如 B-31 / B-53 / B-54 / B-88 / B-89）各自保存。 |
````

### B-71

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 347 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| B-71 | 可封存 | **零漏網目前不達標，且存在倖存者偏差** | 「零漏網未達標」umbrella 項目；有效殘留風險已各自收納至 concrete tasks (B-31, B-53, B-54, B-87, B-88, B-89)，予以封存且不刪除具體項目 |
````

### B-76

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 352 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| B-76 | 可封存 | **審計官的核對階段未腳本化** | 原 audit_verify.py 並未實作；其核心需求已由 canonical verify_all 與 GitHub remote audit workflow 取代。 |
````

### B-80

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 356 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| B-80 | 可封存 | **BPE 的模擬只涵蓋規格中有真實 payload 的修改** | 原 check-only simulation gap 已隨 check-only/手寫 derived-truth authority 消失；現行 source mutation 均以實際 Batch Spec MOD 及 CHECK 17 replay 管理。BPE 本身仍保留。 |
````

### B-81

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 357 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| B-81 | 可封存 | **BPE 的輸出不含錨點原文** | anchor 原文不再需要由 LLM 從 BPE output 重新抄成 blocking truth；BPE 本身仍是 active parser/simulator，不是被廢除。 |
````

### B-83

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 359 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| B-83 | 可封存 | **開場動作單次載入 2,338 行** | 開場單次載入 2,338 行之 hot-path 負擔已由 targeted current-state extraction 解決，歷史 rationale 改為 on demand，非 production blocker，可予封存 |
````

### B-84

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 360 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| B-84 | 可封存 | **模擬閘門的觸發條件比它要保護的範圍窄** | 模擬閘門保護範圍已被 CHECK 17 全量 Spec Replay 逐位元比對完全覆蓋取代。 |
````

### B-87

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 363 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| B-87 | 可封存 | **看板狀態與 repo 實際狀態無任何 CHECK 驗證** | comprehensive repo-to-taskboard reconciliation 已完成；original generic path-existence CHECK proposal 明確 superseded / rejected（因 false-green risk 不實作 generic completion inference）；ongoing state integrity 由 B-95 promotion、every-round disposition 與 External Macro Review 維持，可封存 |
````

### B-91

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 367 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| B-91 | 可封存 | **9 個 `audited-*` tag 歷史留痕保存（退役破壞性遠端清理）** | 9 個錯 tag 刻意作為歷史事故證據保留；audited tag 次系統已退役為 non-authoritative legacy markers（0 remote tag deleted, 0 remote tag rewritten, historical wrong tags intentionally preserved），審計狀態已由 AUDIT-LOG、refactor-backlog §5.1 與 GitHub Actions SSOT 完全接管，不再影響 correctness、audit state、handoff 或 remote health。不需執行破壞性遠端清理。 |
````

### B-105

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 381 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| B-105 | 可封存 | **Jules Mode A 啟用：USER 2026-11-01 撤回／OBSOLETE（非已執行）** | 原模式不得啟動；新退役 owner B-127／J1、J2；D-U12／13／15／16 之現行規劃在 J1 正式前向標記 SUPERSEDED，歷史證據不更改；本批只登錄，不執行 API／GitHub App 清理。 |
````

### D-03

- 原位置：`docs/TASKBOARD.md`「D. 驗證階段（§9.5）」第 430 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| D-03 | 可封存 | **E3 補洞**——僅在前置 validation 失敗時需要；前置驗證已 PASS，予以可封存建議；未來若重啟驗證須由 TASKBOARD routing 明確指定 |
````

### E-02

- 原位置：`docs/TASKBOARD.md`「E. 舊 repo 遷移主線（`refactor-backlog.md` §二 A–F）」第 441 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| E-02 | 可封存 | Persona 認知顧問 15 個（§二 B 節） | 架構已定為方案 A（設定檔非技能，不放 `skills/`），遷移未執行。 USER 2026-11-14 決定：不遷移，資料留在舊 repo，日後重建；本列撤回為可封存，不再列為遷移待辦。 |
````

### F-02

- 原位置：`docs/TASKBOARD.md`「F. 追蹤項（`refactor-backlog.md` 三、各點）」第 557 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| F-02 | 可封存 | 配額熔斷的錨定缺口與 `quota_monitor.py` 處置 | 併入 B-75 額度監控與熔斷機制（追蹤：F-02 → B-75；E-03 Roadmap LINE-04 依據更新為 B-75） |
````

### F-04

- 原位置：`docs/TASKBOARD.md`「F. 追蹤項（`refactor-backlog.md` 三、各點）」第 559 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| F-04 | 可封存 | `karpathy` 其他專案探勘 | 第 14 點。**低優先、需時間盒**，技能遷移與 runtime 收尾後才執行 |
````

### G-01

- 原位置：`docs/TASKBOARD.md`「G. 舊 repo 未盤點區塊（2026-09-02 新發現）」第 571 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| G-01 | 可封存 | `Data/TODO.md` 的 10 項未完成待辦 | absorbed by E-05；內容仍作為 E-05 acceptance inventory，不是刪除需求。不得刪除其原始歷史內容。不得建立第二 Data migration queue |
````

### G-02

- 原位置：`docs/TASKBOARD.md`「G. 舊 repo 未盤點區塊（2026-09-02 新發現）」第 572 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| G-02 | 可封存 | 計畫書（Execution Plans）保留規範 | absorbed by E-05；內容仍作為 E-05 acceptance inventory，不是刪除需求。不得刪除其原始歷史內容。不得建立第二 Data migration queue |
````

### G-03

- 原位置：`docs/TASKBOARD.md`「G. 舊 repo 未盤點區塊（2026-09-02 新發現）」第 573 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| G-03 | 可封存 | `_archive_legacy_docs/adr/` 五份舊 ADR 的內容評估 | absorbed by E-05；內容仍作為 E-05 acceptance inventory，不是刪除需求。不得刪除其原始歷史內容。不得建立第二 Data migration queue |
````

### G-04

- 原位置：`docs/TASKBOARD.md`「G. 舊 repo 未盤點區塊（2026-09-02 新發現）」第 574 行（封存前）
- 封存時狀態：可封存
- 封存依據：USER_CONFIRMED_LEGACY（USER-2026-11-17-G7B-D1）

````text
| G-04 | 可封存 | `_archive_legacy_docs/` 其餘四份文件評估 | absorbed by E-05；內容仍作為 E-05 acceptance inventory，不是刪除需求。不得刪除其原始歷史內容。不得建立第二 Data migration queue |
````

### B-30

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 306 行（封存前）
- 封存時狀態：已完成
- 封存依據：MACRO_PASS_ANCESTOR（f73a076d5ef4184735a6586a7069c66a6ba54bcc）

````text
| B-30 | 已完成 | **playwright 掃描清單含 3000／3001，運行風險已存在** | TG-MVP-07 ACCEPTED / CLOSED；explicit-target-only contract accepted；built-in commonPorts sweep removed；non-target 3000/3001/5000 isolation accepted；implementation SHA `f73a076d5ef4184735a6586a7069c66a6ba54bcc`，post-main Run 35802245822 success。 |
````

### B-33

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 309 行（封存前）
- 封存時狀態：已完成
- 封存依據：MACRO_PASS_ANCESTOR（f73a076d5ef4184735a6586a7069c66a6ba54bcc）

````text
| B-33 | 已完成 | **Port 規範的三個缺口** | root `.env.example` current tracked tree ABSENT（不得重建）；3003 Gateway canonical local port accepted；6379 / 9222 / 9223 known tooling port registry convergence accepted；implementation SHA `f73a076d5ef4184735a6586a7069c66a6ba54bcc`，post-main Run 35802245822 success。 |
````

### B-113

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 389 行（封存前）
- 封存時狀態：已完成
- 封存依據：MACRO_PASS_ANCESTOR（103ef21358cb1f4d97cadaea6d1685d81a19c59c）

````text
| B-113 | 已完成 | **Secret Scanner Fail-Open Paths & Placeholder Exemption Breadth（金鑰掃描器失效開放路徑與 placeholder 豁免過寬）** | 已完成（B113-FAILCLOSED-261006 = ACCEPTED，已晉級 main 至 103ef21358cb1f4d97cadaea6d1685d81a19c59c：scripts/secret_scan.py 之 tracked 與 staged 模式遇應掃描而無法讀取之內容改以 SCAN_READ_ERROR 判定失敗，staged 模式改依 index 項目讀取 blob，gitlink、工作樹已刪除檔案與暫存區刪除為僅有之略過情形；placeholder 字樣僅以獨立片段出現時豁免，並移除同行標記之豁免；新增 scripts/tests/test_secret_scan_fail_closed.py 負向控制。原登錄內容：OPEN / NON-BLOCKING；NEW B-ID，由 External Macro AUD-CLAUDE-1 於 SEC-01 INC-2 登錄；第二意見以隔離合成資料重現，審計官獨立核對程式碼確認）。FACT：scripts/secret_scan.py 之 tracked 模式讀檔遇 OSError 即略過該檔，staged 模式取 index blob 失敗亦略過，最終仍可輸出 SECRET_SCAN PASS（失效開放，與 .agents/rules/governance-gate-integrity.md 之必要閘門 fail-closed 原則不一致）；placeholder 豁免以子字串比對，格式完整之合成 token 只要含 TEST 等字樣即不被回報。風險：CI 乾淨檢出下前者不易觸發，但本機與特殊檔案權限情境可能假綠；後者使少數真實 token 可能漏報。SEC-01 INC-2 之覆蓋結論以此為限（已載於 docs/governance/secret-detection-matrix.json 之 scope_note）。修正涉及裁判語意（CHECK 21 與 pre-commit hook 所依賴之 scanner），須另批以獨立 E24 與負向控制實施，排程於 SEC-01 INC-3 後由 External Macro 規劃；執行者不得自行擴 scope 處理。 |
````

### B-122

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 396 行（封存前）
- 封存時狀態：已完成
- 封存依據：MACRO_PASS_ANCESTOR（e1e6824e87c1be1bba18f39fc37579cb8aa69faa）

````text
| B-122 | 已完成 | **S5 Retention 靜態原文封存基礎** | USER 常設決定（2026-10-17）：只限本批於既有 `docs/archive/` 單次新增 `RETENTION-S5-` 開頭的三個靜態檔（不新增資料夾；原規劃之 docs/archive/retention/ 因 canonical runner 不建立新資料夾，依 USER 常設決定（2026-10-17）改放）： Q2 原文快照、README 索引與 SHA／Git blob 靜態 manifest 三檔（實測合計 7461 bytes）；原檔完整保留；不得刪除、移動、檢疫、管理 Downloads 或 Git objects；manifest 只保留索引，**沒有跨批不可變機械守衛**，任何後續增檔均須 USER 再決定或依未來容量政策；E24／E27 必須先完成；下一步 B-119、B-117、B-120、B-121 分別保有獨立歸屬。S5 作者包非 Executor 授權，尚未實作；B-59 archive index 守衛 OPEN。 **USER 常設決定（2026-10-17）前向結案**：B122-S5-STATIC-ARCHIVE-R5-261017 candidate/main=e1e6824e87c1be1bba18f39fc37579cb8aa69faa，候選 Run 39033386340 與 post-main Run 39035111139 同 SHA verify／gateway-windows 成功（raw verify 1472 passed、1 skipped＋13 passed、ALL 5 GATES PASSED；Windows 57 passed），三靜態檔 7461 bytes；B3 歷史事故列修復，R3 HOLD batch/b122-s5-static-archive-r3-261017 SHA=08595410e7f1751fc3dd5339311f0935a277a483 仍保留，永不晉級；R4 E27 0/2、R5 E27 本批 0/0，歷史證據不改寫。Executor R5 production 1794.5 秒、promotion 244.6 秒（USER_PROVIDED）。S5 完成不表示後續自動封存或不可變守衛已實作；後續增檔另取得 USER 授權或常設容量政策。 |
````

### B-128

- 原位置：`docs/TASKBOARD.md`「B. 重構主線」第 404 行（封存前）
- 封存時狀態：已完成
- 封存依據：MACRO_PASS_ANCESTOR（77d1eb08edf9430edb726ab9a7838614da2a9fe4）

````text
| B-128 | 已完成 | **Executor 回覆自檢的步驟名稱字元集（B117-REPLY-STEPNAME-UNDERSCORE）** | NEW（AUD-CLAUDE-261112 2026-11-12 登錄；非阻擋）：reply_check 的 STATE、STEP_PASS、S1_PRIMARY、S1 行格式不接受含底線的步驟名稱，使 native_preview 批次的正確 Executor 回覆被自檢誤擋（B117-CI-PY314-UVCACHE-R3-261112 回覆首行為 EXECUTOR_REPLY_UNAVAILABLE REPLY_SELF_CHECK_FAILED）。由 B117-REPLY-STEPNAME-R1-261112 修復並加步驟名稱交叉測試。已完成（2026-11-12）：由 B117-REPLY-STEPNAME-R1-261112 修復，候選與 main 皆 77d1eb08edf9430edb726ab9a7838614da2a9fe4，candidate Run 43225183660 與 post-main Run 43230262481 雙 job success，審查官獨立 Macro PASS 與同 SHA POST-MAIN VERIFIED；真實 native_preview S1 回覆尚未發生，S1 測試形態待對齊 runner 實際輸出（UNVERIFIED、非阻擋，下次改 test_reply_check.py 時補）。 |
````
