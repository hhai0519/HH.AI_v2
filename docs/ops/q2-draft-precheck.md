# Q2 審查官草稿預查（含 α-2 快速模式與純狀態處置）

> 本工具僅供 Auditor 使用。Q2 R3 已於 2026-10-17 通過 exact-SHA Macro 審查，α-2（`B117-ALPHA2-FAST-PRECHECK-R2-261123`）新增 `--fast` 快速預查模式（D3／TD-115）、純狀態 `focused: null` 明確不適用（TD-028）與工具指紋納入 `taskboard_archive.py`（TD-055）；β-1（`B117-BETA1-S1-REGISTRY-R2-261124`）將 `s1_registry.py` 納入工具指紋清冊並於存在 `docs/governance/s1-registry.json` 時輸出 `S1_REGISTRY_SUMMARY` 摘要提醒；β-2（`B117-BETA2-D4-CAP-S1DRAFT-R4-261124`）將 `s1_draft.py` 與 `cap_count.py` 納入工具指紋清冊並於存在 `docs/TASKBOARD.md` 與 `docs/AUDIT-LOG.md` 時輸出非阻擋 `CAP_COUNT_D6`／`CAP_COUNT_CAP2` 摘要與寫入 `CAP_COUNT_SUMMARY`；b3b3-2（`B117-G7B3B3-ROWLEN-LEDGER-R3-261125`）於存在 `docs/TODO-LEDGER.md` 與 `scripts/taskboard_archive.py` 時新增非阻擋 `TODO_LEDGER_REVIEW`（及逾期／近期到期／缺日期提示）摘要與寫入 `TODO_LEDGER_REVIEW` 欄位；`TD-134`（`B117-TD134-DIFF-AST-MUTATE-R2-261125`）將差異行確定性 AST 突變工具 `diff_ast_mutate.py` 納入 `FINGERPRINT_TOOLS`（詳見 `docs/ops/td134-diff-ast-mutate.md`）；原始 `9191cb4` 文件逐位元組快照見 `docs/archive/RETENTION-S5-Q2-DRAFT-PRE-9191cb4.md`；本工具不得以此替代 Windows 原生驗證、GitHub CI、Macro verdict 或 canonical runner 的 MINISIM。

```text
python scripts/draft_precheck.py --fast --source <exact-clean-full-base-clone> --patch <reviewed-author.patch> --plan <exact-plan.json> --definition <canonical-definition.json> --prompt <canonical-prompt.txt> --workdir <new-empty-disposable-directory>
python scripts/draft_precheck.py --source <exact-clean-full-base-clone> --patch <reviewed-author.patch> --plan <exact-plan.json> --definition <canonical-definition.json> --prompt <canonical-prompt.txt> --workdir <new-empty-disposable-directory>
python scripts/draft_precheck.py --source <same-base> --patch <same-patch> --plan <same-plan> --definition <same-definition> --prompt <same-prompt> --workdir <same-disposable-directory> --resume
```

## 快速模式（`--fast`，D3／TD-115）

快速模式定位為「60 秒內預檢閘」，供作者化與改版期間先篩除可預期失敗，**絕不取代**完整六步預查、D-SO 複核或 `batch_sim`／MINISIM：

- 事前防護與完整預查完全一致：單一隔離 `candclone`、`validate_author_targets`（套用前後）、`git apply --check --whitespace=error`、`lint_added_sha_labels`、`AUTHOR_SCOPE_MISMATCH` 與 `lint_python_newlines`（以唯讀 `source` 為基線）。
- 五個快速階段依序為：`generate`、`as_if`、`traceability`、`check20`、`fast_validate`；省略 `base_diff_verify_all` 與 `winemu_base_diff`。其中 `fast_validate` 在真實倉庫執行 `scripts/validate_skills.py`、共用之 `validate_focused_binding`（含 `TD-028` 純狀態與程式／workflow 必帶 `focused` 檢查）及 `pytest -p no:cacheprovider --color=no --collect-only -q` 確認每個聚焦測試檔皆收集 ≥ 1 項。
- 防替代保證：禁止 `--fast --resume`（固定失敗代碼 `FAST_RESUME_NOT_ALLOWED`）；絕不產生 `draft-result.json` 或 `draft-state.json`；僅輸出 `fast-result.json`（含 `"mode": "FAST_ONLY_NOT_FULL_PRECHECK"`、`"replaces_full_precheck": false`、`"overall": "FAST_PRECHECK_PASS"`、`"skipped_full_stages": ["base_diff_verify_all", "winemu_base_diff"]`）；標準輸出為 `FAST_PRECHECK STEP ...`、`FAST_PRECHECK PASS`／`FAST_PRECHECK FAIL <CODE>`、`FAST_RESULT_JSON_SHA256=...`、`FAST_ELAPSED_SEC=...`，絕不印出 `SIX_STEPS_PASS`。

## 完整六步預查

本命令六步依序為 canonical fingerprint／execution-record generate、as-if check_consistency（現行 32 項 CHECK，含 CHECK 28 受保護歷史守衛、CHECK 29 任務看板封存守衛、CHECK 30 任務看板指標單行守衛、CHECK 31 S1 根因登記檔守衛、CHECK 32 任務看板列長守衛）＋record verify、完整 Base 和候選 verify_all 同環境比對、rule traceability --check、重用 CHECK20 欄數邏輯（含唯一歷史列例外）。任何階段結束才將結果、日誌雜湊與 candidate diff SHA 儲存於 workdir，必要輸出 `draft-result.json` 及獨立的 SHA256 欄位；失敗時不會跳過當前失敗階段。第六步 `winemu_base_diff`：在隔離 Base／候選 clone 使用同一份 canonical focused 定義（B-123b-lite 起必含 `-rs`，變更的 `scripts/tests/*.py` 均要列入）及 Windows Git profile／`sim_windows_emulation`，藉由可解析的 JUnit XML 取得失敗及錯誤 node ID；只容許候選失敗集合減去 Base 失敗集合為空。純狀態／文件批採用 Fail-Closed 白名單：僅當 `allowed_paths` 全部位於 `docs/` 之下且副檔名為 `.md`、`.json` 或 `.txt`（`PURE_STATE_PREFIX='docs/'`、`PURE_STATE_SUFFIXES=('.md', '.json', '.txt')`），並設 `canonical_focused` 為 `null` 時，明示回傳 `NOT_APPLICABLE_NO_FOCUSED` 且 `STAGE6=NOT_APPLICABLE`，不對 Base／候選呼叫 `winemu_collect`；任何白名單外路徑卻為 `focused: null` 一律以 `WINEMU_FOCUSED_REQUIRED_FOR_CODE` 拒絕（TD-028）。每端 rc=0 必須 XML tests>0 且 failures+errors=0；rc=1 必須 failures+errors>=1 且每項有唯一 ID，其他 rc fail-closed。Base 僅剔除 Base 不存在、但在候選 definition／plan／prompt 三方證明為新增的測試路徑；只剩合法新增測試時標 `AUTHORIZED_EMPTY_NEW_FILES_ONLY`，不對空 Base 呼叫 pytest；候選每一份本批變更測試檔必須至少實際執行一項。測試輸出附 `EMULATION_SCOPE`，目前不模擬 `os.name`、`os.symlink`、`os.mkfifo`，不可代替 Windows native D-10。測試新增或變更的 Python 文字寫入先經差異行 AST newline lint；`os.open` 為 fd API 不判 text mode、`io.open`／builtins `open` mode 在第二參數，Path.open 在第一參數。

非 production 的合成測試 fixture 若合法略過第六步，結果 JSON 必須標示 `STAGE6=SYNTHETIC`，不得拿它宣稱真正的六步 Windows 模擬已通過。

完成本命令後仍需另外使用 canonical `batch_sim.py production` 或 runner MINISIM 驗證 stage／commit／postcommit；兩者不互相替代。

續跑重用條件：Base 完整 Git commit、原作者 patch SHA256、plan SHA256、工具組 SHA256（`FINGERPRINT_TOOLS`，含 `taskboard_archive.py`、`s1_registry.py`、`s1_draft.py`、`cap_count.py` 與 `diff_ast_mutate.py`）、OS／Python／Git／Node／路徑長度／UID 指紋、候選 Git diff、生成檔 SHA、已完成階段日誌 SHA **全部相同**。任一不同，立即 `RESUME_*` STOP，不沿用舊結果；使用新空工作目錄重跑。未完成階段從頭執行，不偽稱已完成。

Gate 4 非零只有在 Base 和候選返回碼一致、失敗 gate 類別完全相同、候選未新增 test failure ID 且 Base 本來存在明確失敗 ID 才標 `BASE_EQUIVALENT_NONZERO`，**不是 verify_all PASS**。無法辨識失敗 ID、測試逾時／啟動失敗（124/125/127）、非 pytest 閘門失敗、無完整 ALL 5 GATES PASSED 標記、工具或依賴漂移一律停機。只有 unit_tests 或 webapp_tests 的單一 pytest 閘門且具有真實 node ID 時才可比對等價；多閘門無法逐一歸屬者亦拒絕。

E24 規則衍生依賴：`impact_scan --query q:path:.agents/rules/one.md` 若該檔被 Git 追蹤，必定把 `docs/generated/rule-traceability.md` 列為衍生依賴（matched lines [0] 表示 derived edge，而非真實文字行號）。在 allowed scope 及 E24 dispositions 裡漏列此生成物會 fail-closed。

SHA 格式 lint：只掃作者 patch **新增的四份狀態文件行**；`SHA256` 等明確 label 之 token 必須 64 hex，`main=`、`BASE_OID=` 等 Git OID 欄位必須 40 hex。舊歷史不可追溯列不改寫，不以全庫歷史例子濫報。負例包含 62 碼的 Jules bundle SHA。此規則並非獨立攔截所有自由文體 SHA 的全域檢查，後續可依 E27 建議擴充。新增狀態列不得縮寫 SHA；標示 SHA-256 的數值須 64 hex、Git OID 須 40 hex，支援半形／全形冒號、空白及引號或反引號。

隔離限制：只接受本機 full、clean Base clone，不接收遠端 URL；不在來源工作樹寫入、不 commit、不 push、不刪遠端 ref。此工具不具 OS 層網路或沙箱權限隔離；執行的 repo tests 需視為受信任的 reviewed code。日誌可能含測試機敏輸出，不直接刊載原始 stdout 到聊天；附件應先遵守 secret-output safety。

待辦清冊複查提醒（G7-b3b3-2 / TD-107）：當 `docs/TODO-LEDGER.md` 與 `scripts/taskboard_archive.py` 存在時，`draft_precheck.py`（含 `--fast` 與完整六步）於最後一併呼叫唯讀 `ledger-review --json`，摘要輸出非阻擋之 `TODO_LEDGER_REVIEW as_of=... open=... overdue=... due_soon=... missing=...` 及 `TODO_LEDGER_OVERDUE`／`TODO_LEDGER_DUE_SOON`／`TODO_LEDGER_MISSING_DATE` 列，提醒作者或審查官於當批處置逾期或即將到期之開放待辦；此摘要絕不阻塞預查 PASS 或 CI。

## 送件與預查順序（P0 流程與規格前置，2026-11-25 起適用）

依 USER 2026-11-25 澄清之目標導向準則（降低審查官額度、機械化推進、不放寬驗收）與第二意見宏觀建議（P0 第 1、2 點），自 2026-11-25 起適用下列流程規定：

1. **預查順序改為「快→複核→完整」（P0 第 1 點）**：審查官作者化後先執行 `scripts/draft_precheck.py --fast`、相關測試與 `scripts/diff_ast_mutate.py` 差異行突變檢查（詳見 `docs/ops/td134-diff-ast-mutate.md`），即送第二意見進行 D-SO 複核；待第二意見回報 `BLOCKING 0 / NON_BLOCKING 0` 後，審查官才對同一份未變動作者位元組執行完整六步預查（`SIX_STEPS_PASS`），通過後交付 Executor。完整六步預查仍為交付 Executor 之必要條件，不放寬任何驗收；`docs/refactor-backlog.md` §5.3 第 21 項之條件式交付同步更新為「SO 0/0 → 審查官完整 6 步 PASS → 交付」。
2. **驗證器類批作者化前先送規格表 `SPEC_TABLES`（P0 第 2 點）**：凡涉及驗證器規則、狀態轉移或結構拆解之批次，作者化寫程式前先送決策表／狀態轉移表（`SPEC_TABLES`）給第二意見做一次短複核，確認無設計層缺口後才寫程式；若修改狀態轉移規則，須依 `TD-133` 於當批檢附規格表與確定性 `itertools` 窮舉測試。
3. **改版閉環複核與使用者最終裁量權（USER 常設決定，2026-11-25）**：因執行前複核發現而換新 `TASK_ID` 改版重送（R2 以上）時，後續複核聚焦前輪發現之閉環驗證與回歸檢核，避免無止境新開討論輪次；且是否啟用第二意見或閉環複核，USER 保留最終裁量權（D-SO 任何情況下皆不成為不可取消之強制關卡；USER 明示某批不啟用時，依其決定辦理並於交付紀錄註明）。

後續待辦（E27 N2–N6，NON_BLOCKING／NOT IMPLEMENTED）：N2 E24 衍生來源直接取用 `generate_rule_traceability.SCAN_SCOPE_PATTERNS`；N3 workdir 排他鎖；N4 環境指紋加 pytest／套件版本；N5 canonical MINISIM 可選 `--minisim` 階段；N6 CHECK20 `_c20_column_failures` 公開穩定 API。以上不得在本批報作已完成。
