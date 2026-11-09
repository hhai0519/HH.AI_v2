# Q2 審查官草稿預查（R3 已完成 exact-SHA 驗收）

> 本工具僅供 Auditor 使用。Q2 R3 已於 2026-10-17 通過 exact-SHA Macro 審查；原始 `9191cb4` 文件逐位元組快照見 `docs/archive/RETENTION-S5-Q2-DRAFT-PRE-9191cb4.md`；本工具不得以此替代 Windows 原生驗證、GitHub CI、Macro verdict 或 canonical runner 的 MINISIM。

```text
python scripts/draft_precheck.py --source <exact-clean-full-base-clone> --patch <reviewed-author.patch> --plan <exact-plan.json> --definition <canonical-definition.json> --prompt <canonical-prompt.txt> --workdir <new-empty-disposable-directory>
python scripts/draft_precheck.py --source <same-base> --patch <same-patch> --plan <same-plan> --definition <same-definition> --prompt <same-prompt> --workdir <same-disposable-directory> --resume
```

本命令六步依序為 canonical fingerprint／execution-record generate、as-if check_consistency（現行 28 項 CHECK，含 CHECK 28 受保護歷史守衛）＋record verify、完整 Base 和候選 verify_all 同環境比對、rule traceability --check、重用 CHECK20 欄數邏輯（含唯一歷史列例外）。任何階段結束才將結果、日誌雜湊與 candidate diff SHA 儲存於 workdir，必要輸出 `draft-result.json` 及獨立的 SHA256 欄位；失敗時不會跳過當前失敗階段。第六步 `winemu_base_diff`：在隔離 Base／候選 clone 使用同一份 canonical focused 定義（R1 起必含 `-rs`，變更的 `scripts/tests/*.py` 均要列入）及 Windows Git profile／`sim_windows_emulation`，藉由可解析的 JUnit XML 取得失敗及錯誤 node ID；只容許候選失敗集合減去 Base 失敗集合為空。每端 rc=0 必須 XML tests>0 且 failures+errors=0；rc=1 必須 failures+errors>=1 且每項有唯一 ID，其他 rc fail-closed。Base 僅剔除 Base 不存在、但在候選 definition／plan／prompt 三方證明為新增的測試路徑；只剩合法新增測試時標 `AUTHORIZED_EMPTY_NEW_FILES_ONLY`，不對空 Base 呼叫 pytest；候選每一份本批變更測試檔必須至少實際執行一項。測試輸出附 `EMULATION_SCOPE`，目前不模擬 `os.name`、`os.symlink`、`os.mkfifo`，不可代替 Windows native D-10。測試新增或變更的 Python 文字寫入先經差異行 AST newline lint；`os.open` 為 fd API 不判 text mode、`io.open`／builtins `open` mode 在第二參數，Path.open 在第一參數。

非 production 的合成測試 fixture 若合法略過第六步，結果 JSON 必須標示 `STAGE6=SYNTHETIC`，不得拿它宣稱真正的六步 Windows 模擬已通過。

完成本命令後仍需另外使用 canonical `batch_sim.py production` 或 runner MINISIM 驗證 stage／commit／postcommit；兩者不互相替代。

續跑重用條件：Base 完整 Git commit、原作者 patch SHA256、plan SHA256、工具組 SHA256、OS／Python／Git／Node／路徑長度／UID 指紋、候選 Git diff、生成檔 SHA、已完成階段日誌 SHA **全部相同**。任一不同，立即 `RESUME_*` STOP，不沿用舊結果；使用新空工作目錄重跑。未完成階段從頭執行，不偽稱已完成。

Gate 4 非零只有在 Base 和候選返回碼一致、失敗 gate 類別完全相同、候選未新增 test failure ID 且 Base 本來存在明確失敗 ID 才標 `BASE_EQUIVALENT_NONZERO`，**不是 verify_all PASS**。無法辨識失敗 ID、測試逾時／啟動失敗（124/125/127）、非 pytest 閘門失敗、無完整 ALL 5 GATES PASSED 標記、工具或依賴漂移一律停機。只有 unit_tests 或 webapp_tests 的單一 pytest 閘門且具有真實 node ID 時才可比對等價；多閘門無法逐一歸屬者亦拒絕。

E24 規則衍生依賴：`impact_scan --query q:path:.agents/rules/one.md` 若該檔被 Git 追蹤，必定把 `docs/generated/rule-traceability.md` 列為衍生依賴（matched lines [0] 表示 derived edge，而非真實文字行號）。在 allowed scope 及 E24 dispositions 裡漏列此生成物會 fail-closed。

SHA 格式 lint：只掃作者 patch **新增的四份狀態文件行**；`SHA256` 等明確 label 之 token 必須 64 hex，`main=`、`BASE_OID=` 等 Git OID 欄位必須 40 hex。舊歷史不可追溯列不改寫，不以全庫歷史例子濫報。負例包含 62 碼的 Jules bundle SHA。此規則並非獨立攔截所有自由文體 SHA 的全域檢查，後續可依 E27 建議擴充。新增狀態列不得縮寫 SHA；標示 SHA-256 的數值須 64 hex、Git OID 須 40 hex，支援半形／全形冒號、空白及引號或反引號。

隔離限制：只接受本機 full、clean Base clone，不接收遠端 URL；不在來源工作樹寫入、不 commit、不 push、不刪遠端 ref。此工具不具 OS 層網路或沙箱權限隔離；執行的 repo tests 需視為受信任的 reviewed code。日誌可能含測試機敏輸出，不直接刊載原始 stdout 到聊天；附件應先遵守 secret-output safety。

後續待辦（E27 N2–N6，NON_BLOCKING／NOT IMPLEMENTED）：N2 E24 衍生來源直接取用 `generate_rule_traceability.SCAN_SCOPE_PATTERNS`；N3 workdir 排他鎖；N4 環境指紋加 pytest／套件版本；N5 canonical MINISIM 可選 `--minisim` 階段；N6 CHECK20 `_c20_column_failures` 公開穩定 API。以上不得在本批報作已完成。
