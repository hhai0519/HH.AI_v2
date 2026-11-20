# 待辦清冊（TODO-LEDGER）

> 本檔是 repo 內唯一的待辦清冊，由 B-117 G7-b3b3 第一批（B117-G7B3B3-TODO-LEDGER-261120）建立。
> 批次紀錄是敘事文字，會被搬到封存檔；寫在批次紀錄裡的「新增待辦」從本批起，必須在本檔有一個 TD 編號，
> 否則紀錄一搬走，待辦就只剩封存檔裡的一句話（本次盤點即因此找回 84 項）。

## 一、規則

1. 編號 `TD-nnn`：全 repo 唯一、不重用、只增不減；既有列不得刪除，處置欄可由「開放」或「承接」改為「結案」，並在依據欄寫明結案的批次與證據。
2. 新增待辦：取下一個編號，寫來源 TASK_ID、事項、處置與依據；「開放」的列必須在依據欄寫 owner 與觸發條件或複查日。批次紀錄只引用 TD 編號，不再另編（一）（二）或 b1- 這類每批重編的標籤。
3. 目前這些規則由審查官人工核對；機械檢查（新增待辦須帶 TD 編號且唯一、records-apply 遇未結案編號即拒絕）預定為 G7-b3b3 第三批，落地前以本檔為準。
4. 本檔不取代 `docs/TASKBOARD.md` 的列：列仍是任務與切片的 owner；本檔只記「從批次紀錄帶走、尚需有人負責或已結案」的事項。看板「現行待辦表」併入 G7-d 之表格工具時，以本檔為資料來源。

## 二、處置定義

| 處置 | 意義 | 依據欄寫什麼 |
|---|---|---|
| 結案 | 事項已完成、被取代或對象消失 | 結案的批次、commit 或檔案證據；指標性項目寫指向哪個編號 |
| 承接 | 事項仍待做，但看板現行位置（列、NEXT_SLICE 排程項或決定行）已承接 | 承接的位置 |
| 開放 | 事項仍待做，看板沒有承接；本檔是它現在的位置 | owner 與觸發條件或複查日 |

## 三、統計（B117-G7B3B3-TODO-LEDGER-261120，Base da9fdbde）

| 範圍 | 項數 | 處置分布 |
|---|---|---|
| 全部 | 84 | 結案 23、承接 36、開放 25 |
| 第二意見 58 項（RECORDS-0002 之 8 則紀錄） | 58 | 結案 15、承接 22、開放 21 |
| 方法 A 帶前綴 14 項（b1-、x-；為上列 58 項之子集） | 14 | 結案 5、承接 5、開放 4 |
| RECORDS-0003 之 b2-、b3a- 標籤（9 個不同標籤） | 9 | 結案 5、承接 3、開放 1 |
| 本批搬移之 G7-b3a2 紀錄（b3a2- 九個標籤，加第十點（一）（二）；（三）併入 b3a2-九） | 11 | 結案 3、承接 6、開放 2 |
| RECORDS-0002 內 G5-DELIVERY-PRESTART 紀錄無「新增」標記之待辦 | 2 | 結案 0、承接 1、開放 1 |
| RECORDS-0001 之無標籤待辦（4 組，群組級） | 4 | 結案 0、承接 4、開放 0 |

## 四、盤點範圍與方法

三種計數方法的範圍與判定規則不同，數字不能互相對照；本檔把三種都列出，不以其中一種取代另一種。

1. 方法 A（審查官，2026-11-18）：`docs/archive/TASKBOARD-RECORDS-0002.md` 內帶前綴之待辦標籤（b1-、x-）共 14 個。原登錄為「其中 8 個看板查無，RC-4 只在封存檔」；Base da9fdbde 重算：14 個標籤在 `docs/TASKBOARD.md` 現行文字中出現 0 個（FACT；先前 6 個仍在看板，是因為相關批次紀錄當時尚留在看板，現已搬入封存檔）。
2. 方法 B（第二意見，2026-11-19，非權威）：RECORDS-0002 之 8 則紀錄，取「新增」之後、以全形括號標示之待辦標籤共 58 個；原數字為看板找得到同一標籤 6、完全找不到 13、無前綴而機械上無法判定 39，其人工判讀 25 個在看板無對應（INFERENCE）。Base da9fdbde 以同一唯讀腳本重算：定義 68 個（無前綴 39、只在封存檔 26、仍在看板 3）；68＝58＋RECORDS-0003 新增之 10 個定義（b2-一至五、b3a-一至四，b2-二於兩則紀錄各定義一次）。腳本為第二意見環境之原型，不在 repo。
3. 方法 C（本清冊，2026-11-20）：範圍＝方法 B 之 58 個＋RECORDS-0003 之 9 個不同標籤＋本批搬移之 G7-b3a2 紀錄之 11 項＋RECORDS-0002 內 G5-DELIVERY-PRESTART 紀錄無「新增」標記之 2 項＋RECORDS-0001 之 4 組無標籤待辦，共 84 項；逐項對 Base da9fdbde 之 `docs/TASKBOARD.md`、批次紀錄封存檔與 repo 實況核對後給處置。方法 B 之「看板無對應 25 個」在本清冊的對應是「開放」：58 項中開放 21 項、承接 22 項、結案 15 項；差異來自本清冊把「看板某處已有承接文字」的項目列為「承接」，而不是「無對應」。

已知限制：

- RECORDS-0001（27 則紀錄）沒有全形括號標籤；其待辦以「類別待辦」「前向收斂（owner）」寫成，本檔只列 4 組（TD-001 至 TD-004），群組內逐項是否仍有對應文字未核實（UNKNOWN）。
- 看板上仍留 5 則批次紀錄（B117-G6-FIXED-WAIT-261120、B117-R1INT1-WAIT-261120、B117-G7B3B2-ONE-LINER-R3-261120、B117-BACKUP-TEST-CLOCK-R2-261120、B117-G7B3B1-TAKEOVER-ARCHIVE-R2-261119）之待辦不在本批盤點：它們尚在看板，待搬移時依本檔規則補編 TD 編號（G7B3B1 紀錄之 b3b1-一至六皆寫「登錄於 G3、G6、G7 列」，由各列承接）。本批自己的紀錄沒有新增待辦（b3b3-2、b3b3-3 為 NEXT_SLICE 排程項）。
- 「承接」只核對承接位置存在且文字相符，不代表該位置的工作已排定時程。

## 五、清冊

| 編號 | 來源批次紀錄 | 原標籤 | 事項 | 處置 | 依據或去處 |
|---|---|---|---|---|---|
| TD-001 | B123A-SIM-GIT-PROFILE-R4-261030 | 類別待辦（無標籤） | 交付檔名唯一性：同 TASK_ID 交付後位元組改變，機械化前一律換新 TASK_ID | 承接 | G3 列（交付檔名唯一性，現未落地）；NEXT_SLICE 排程（三）審查工具批第一批含 G3 D 交付唯一性 |
| TD-002 | B116-G4-C7-ENTRY-CHECK20-R2-261030 | 類別待辦（無標籤） | 同上，同類第二次（交付後位元組改變仍沿用同一 TASK_ID） | 承接 | 同 TD-001 |
| TD-003 | B116-AUD-TAKEOVER-STATE-R2-261030 | 接任對話待辦前向收斂 | 十餘項接任對話待辦分派到 B-117 G5、B-115 G3、B-123 G6、B-111、B-116、B-124、G10、B-126 等既有 owner | 承接 | 各 owner 列仍在看板；逐項是否仍有對應文字未核實（UNKNOWN，群組級登錄） |
| TD-004 | B119-AUD-TAKEOVER-STATE-R1-261022 | 類別待辦①至④ | ①Windows 換行與 CI 涵蓋 scripts/tests→B-123（G6）；②S1 恢復機械化→B-119 G1；③環境統一→B-117；④repo 契約補正→B-116／B-117／B-118 | 承接 | 各 owner 列仍在看板；逐項是否仍有對應文字未核實（UNKNOWN，群組級登錄） |
| TD-005 | B117-G5-DELIVERY-PRESTART-R2-261114 | （五）前半 | STEP_IN_PROGRESS 在 Windows 原生環境之行為：第一次真實觸發時取證 | 承接 | G5 列「STEP_IN_PROGRESS 在 Windows 原生環境的行為（第一次真實觸發時取證）」（FACT：G5 列現行文字） |
| TD-006 | B117-G5-DELIVERY-PRESTART-R2-261114 | （五）後半 | 第二意見後續建議（需 E27）：區塊 B-R 改用 switch --quiet --detach；區塊 A 檢查 $Host.Name 為 ConsoleHost 以拒絕 ISE；IDE 路徑改為參數；FILES_READY 由 delivery_pack 同時產生並由 verify-reply 檢查 | 開放 | FILES_READY 現由 files_ready.py 產生（FACT：審查官端工具），其餘三小項未見落地（INFERENCE）；逐項核實未做。owner：審查工具批；觸發：下一個修改 delivery_pack.py 之批 |
| TD-007 | B117-G5-BRANCH-MATCH-R4-261115 | （一） | 准入階段 S1 留下不與正式 control 競爭的紀錄檔（併入 G5 單一命令 run 切片） | 承接 | G5 列完成條件仍載此項（FACT：G5 列現行文字） |
| TD-008 | B117-G5-BRANCH-MATCH-R4-261115 | （二） | cap_count.py 唯讀計數工具（觸發：TG-MVP-15 開工前完成）；亦為 D6 計數工具（β 批） | 承接 | 看板治理完成線節「NOT IMPLEMENTED」；scripts/cap_count.py 不存在（FACT）；D6 決定行「與封頂條件②共用之唯讀計數工具」 |
| TD-009 | B117-G5-BRANCH-MATCH-R4-261115 | （三） | EXEC-LOG 首句與關閉新增句之機械 lint，含「新增列禁止引用外部角色文件之版本號與章節」 | 開放 | 首句形式已由 G7-b3b2 之「一句話」檢查落地（B117-G7B3B2-ONE-LINER-R3-261120）；殘餘：關閉新增句 lint 與禁止引用外部角色文件版本號與章節。owner：G7-b3b3 第三批（待辦格式 CHECK）一併評估；觸發：該批作者化 |
| TD-010 | B117-G5-BRANCH-MATCH-R4-261115 | （四） | TASKBOARD 新增待辦須帶觸發條件或複查日之 lint | 承接 | G7-b3b3 第三批（待辦格式 CHECK，含觸發條件或複查日欄位）；本批於 NEXT_SLICE 登錄 |
| TD-011 | B117-G5-BRANCH-MATCH-R4-261115 | （五） | USER 待辦處置表逐項核實與登錄 | 結案 | 看板「USER 待辦處置表」節已登錄（FACT：docs/TASKBOARD.md 該節，B117-STATE-HANDOVER-R1-261115 登錄） |
| TD-012 | B117-G5-BRANCH-MATCH-R4-261115 | （六） | PRESTART 區塊 C 對一般目錄之完整 lstat 比對與來源快照不一致之殘餘 | 結案 | 對象消失：區塊 C 已併入 runner 之 Git 閒置檢查（FACT：scripts/delivery_pack.py「原區塊 C 已併入 Executor 的 run 命令」）；G5 列內該句為殘文，不另立項 |
| TD-013 | B117-G5-BRANCH-MATCH-R4-261115 | （七） | USER 回報區塊 C 之實際輸出與 IDE git.autorefresh、git.autofetch 設定（複查日 2026-11-22，屆時未回報即放棄並維持 UNKNOWN） | 開放 | 複查日 2026-11-22 未到（清冊建立日 2026-11-20）；區塊 C 已併入 runner，證據價值降低。owner：審查官，複查日當天決定放棄或沿用 |
| TD-014 | B117-G5-BRANCH-MATCH-R4-261115 | （八） | native_preview finally 比對之 exact-byte 回歸測試（只改 tracked 檔內容、保留 size 與 mtime 須 FAIL） | 開放 | scripts/tests/test_native_preview.py 之測試名稱未見對應（FACT：名稱清單）；觸發：下一個變更 native_preview.py 之批 |
| TD-015 | B117-STATE-HANDOVER-R1-261115 | （一） | STEP_IN_PROGRESS 類別根除為 G5 單一命令 run，並以 resume-check 取代手寫守衛、續跑協定寫入 repo | 結案 | G5-b1（B117-G5B1-RUN-RESUME-R2-261116）與 G5-b2（B117-G5B2-RUN-ONLY-R2-261116）已落地；scripts/batch_runner.py 有 run 與 resume-check，續跑協定在 docs/ops/g5-run-protocol.md（FACT） |
| TD-016 | B117-STATE-HANDOVER-R1-261115 | （二） | RC-2 回覆組裝競態（REPLY_STEP_OUTPUT_TRUNCATED／REPLY_STEP_OUTPUT_MISSING） | 結案 | G5-a（B117-G5A-RC2-DURATIONS-R2-261116）第四點（甲）根除，附帶之 REPLY_STEP_OUTPUT_MISSING 移入 G5-b2；scripts/batch_runner.py 有 REPLY_CONTROL_STALE 與 REPLY_STEP_IN_PROGRESS、EXECUTOR_REPLY_UNAVAILABLE（FACT）；REPLY_STEP_OUTPUT_MISSING 隨單一命令消失屬 INFERENCE（G5-b2 紀錄第五點已標示） |
| TD-017 | B117-STATE-HANDOVER-R1-261115 | （三） | RC-3 IDE 使用者層級 Git 自動刷新與自動 fetch 設定由工具讀取實值判定 | 開放 | 現況只請 USER 目視確認（FACT：scripts/delivery_pack.py PRESTART 文字）。owner：G5；原觸發「G5-c」在現行看板無此切片（見第五節註） |
| TD-018 | B117-STATE-HANDOVER-R1-261115 | （四） | RC-4 USER 端 PowerShell 合併為 repo 內 USER 端工具（區塊 C 移入 preflight） | 開放 | 區塊 C 已併入 run（FACT）；區塊 A、B、B-R 仍為手貼 PowerShell。owner：G5；原觸發「G5-c」見第五節註 |
| TD-019 | B117-STATE-HANDOVER-R1-261115 | （五） | RC-5 去除 focused 與第 4 關之零損失重疊（第 4 關預算選 A） | 開放 | G5-a 紀錄第三點（USER 2026-11-16「先量再砍」）把觸發改為「累積兩批第 4 關耗時資料後依資料另開切片」；量測外掛 scripts/gate_durations.py 已落地（FACT），去重切片尚未另開（INFERENCE：無對應紀錄）。owner：第 4 關降載（D1、D9）評估時併入判定 |
| TD-020 | B117-STATE-HANDOVER-R1-261115 | （六） | RC-6 TIMING 另輸出各步耗時與總運算時間，EXEC-LOG 與看板改用運算時間 | 開放 | 現行 TIMING 只輸出起訖與總耗時（FACT：scripts/batch_runner.py _timing_lines）；G5-a 只落地第 4 關逐測試耗時量測，未做各步耗時與運算時間。owner：G5；原觸發「G5-c」見第五節註 |
| TD-021 | B117-STATE-HANDOVER-R1-261115 | （七） | 自檢聲明交叉比對機械化（可由程式判定之項目進 runner preflight） | 承接 | NEXT_SLICE 排程（五）「自檢聲明交叉比對機械化與 B-111」（FACT） |
| TD-022 | B117-STATE-HANDOVER-R1-261115 | （八） | 額度不足時 runner 在任何修改前停止並列出重置時間 | 開放 | 現況只在提示詞文字要求 Executor 自行判斷（FACT：scripts/prompt_builder.py 啟動前額度文字）；runner 無對應機制。owner：G5 |
| TD-023 | B117-STATE-HANDOVER-R1-261115 | （九） | 看板審查官等級與 production 提示詞 bundle_output 之一致性由 prompt_builder 機械檢查 | 開放 | scripts/prompt_builder.py 只依 definition 之 bundle_output 組裝，不讀看板等級（FACT）；觸發：G3 D 開工時併入。owner：審查工具批 |
| TD-024 | B117-STATE-HANDOVER-R1-261115 | （十） | repo 契約補正（過渡期權威、環境分級、bundle、回覆首行等寫入 repo 協定與自檢） | 結案 | G7-a（B117-G7A-CONTRACT-STATE-R2-261117）部分關閉並處置餘項：已寫入協定第 13 節、自檢清單 F1 與 A2、role-boundaries S1 段落；餘項屬 USER 角色文件不登錄，無機械檢查者由 USER 與第二意見核對（FACT：該紀錄第八點） |
| TD-025 | B117-STATE-HANDOVER-R1-261115 | （十一） | 「准入階段順序錯誤寫入 halted」加註 STEP_IN_PROGRESS 除外 | 結案 | G5 列已加註（2026-11-17；FACT：G5 列現行文字） |
| TD-026 | B117-STATE-HANDOVER-R1-261115 | （十二） | 使用者指引加一句：IDE 自動刷新關閉時 Source Control 不更新屬預期，勿按 Commit 或同步 | 開放 | PRESTART 現有文字只含「約 4 分鐘內不要…開啟原始檔控制面板」（FACT：scripts/delivery_pack.py），無該句。owner：審查工具批（delivery_pack）；優先度低 |
| TD-027 | B117-STATE-HANDOVER-R1-261115 | （十三） | 第二節規劃（一個 runner 兩種啟動、三類批次、IDE 或 App 擔任審查官之條件） | 承接 | 看板「USER 待辦處置表」之「做（規劃待辦）第二節規劃」列（FACT：docs/TASKBOARD.md）；觸發（G5 單一命令 run 落地）已滿足，待排程 |
| TD-028 | B117-STATE-HANDOVER-R1-261115 | （十四） | draft_precheck 第 6 階段對 focused 為 null 之純狀態批停在 WINEMU_FOCUSED_DRIFT（應明示不適用並附負例） | 開放 | 同類第二次見 B117-G7A-CONTRACT-STATE-R2-261117 紀錄第八點（FACT）；scripts/draft_precheck.py 仍要求 focused 為 dict（FACT）。觸發：下一個修改 draft_precheck.py 之批，或 G3 D 開工時併入。owner：審查工具批 |
| TD-029 | B117-G5A-RC2-DURATIONS-R2-261116 | （一） | 純狀態批快速通道（runner 依實際 diff 判定資格） | 承接 | NEXT_SLICE 末句「純狀態批快速通道延到 TG-MVP-15 之後」（FACT） |
| TD-030 | B117-G5A-RC2-DURATIONS-R2-261116 | （二） | CI 防假綠燈強化 | 承接 | 已併入合併切片（B117-G5B1-RUN-RESUME-R2-261116 紀錄）；NEXT_SLICE 排程（三）審查工具批第二批之「CI workflow 規則檢查」（FACT） |
| TD-031 | B117-G5A-RC2-DURATIONS-R2-261116 | （三） | 晉級審查包機械化（含 USER 2026-11-16 決定之 post-main 機械比對） | 承接 | NEXT_SLICE 排程（三）第二批「證據工具（同 SHA post-main 固定結果、audit_packet）」（FACT）；工具落地前仍由審查官人工比對 post-main Run |
| TD-032 | B117-G5A-RC2-DURATIONS-R2-261116 | （四） | Windows 測試加速評估 C、I | 承接 | NEXT_SLICE 排程（四）降低版 G6 之 pytest-xdist 試驗與 D9（FACT）；C、I 之原義見該批紀錄 |
| TD-033 | B117-G5A-RC2-DURATIONS-R2-261116 | （五） | 治理切片上限待 USER 裁決（複查日 2026-11-29） | 結案 | B117-G5B1-RUN-RESUME-R2-261116 紀錄「關閉：前一批新增（五）治理切片上限待裁決（USER 決定 7）」（FACT） |
| TD-034 | B117-G5B1-RUN-RESUME-R2-261116 | （一） | 合併切片「CI 防假綠燈強化＋證據工具」 | 承接 | NEXT_SLICE 排程（三）審查工具批（拆二批；範圍與名稱以該排程為準） |
| TD-035 | B117-G5B1-RUN-RESUME-R2-261116 | （二） | 接任重驗模式與 repo 接任段落配合修改（併入（一）之工具） | 開放 | NEXT_SLICE 排程（三）未逐字列出此項；owner：審查工具批，作者化該批時須納入範圍 |
| TD-036 | B117-G5B1-RUN-RESUME-R2-261116 | （三） | 回覆兩層與固定段落由工具產生（併入（一）） | 開放 | 部分：FILES_READY 與 SHA 由 files_ready.py 產生；兩層與固定五欄仍由審查官手寫並以 reply_check 檢查（FACT）。owner：審查工具批，作者化該批時須納入範圍 |
| TD-037 | B117-G5B1-RUN-RESUME-R2-261116 | （四） | 第二意見抽查與完整重跑兩模式（角色文件由 USER 修訂） | 承接 | USER D5（第二意見只做語意複核、工具結果以雜湊抽驗，審查官證據 ZIP 附 EVIDENCE_MANIFEST.json；FACT：NEXT_SLICE 後之 D1 至 D9 決定行） |
| TD-038 | B117-G5B1-RUN-RESUME-R2-261116 | （五） | 看板表格由工具產生與表格 CHECK | 承接 | G7-d（FACT：NEXT_SLICE 與 G7 列） |
| TD-039 | B117-G5B1-RUN-RESUME-R2-261116 | （六） | docs/USER-DECISIONS.md 與 CHECK | 承接 | G7-c（FACT：NEXT_SLICE 與 G7 列） |
| TD-040 | B117-G5B1-RUN-RESUME-R2-261116 | （七） | G7 封存區改獨立檔案、協定第 10.4 節修改、封存條件與清單 | 結案 | G7-b1（B117-G7B1-ARCHIVE-MECHANISM-R2-261117，main 710cf3bb9f2e52384bfb7ffdebbfc97f2d4d5b6a，Macro PASS 與 POST-MAIN VERIFIED；FACT：G7 列） |
| TD-041 | B117-G5B1-RUN-RESUME-R2-261116 | （八） | Windows 測試 fixture 重複建立暫存 git repo 之共用可行性評估（不得犧牲測試隔離） | 開放 | 觸發條件已滿足（B117-G5B2-RUN-ONLY-R2-261116 紀錄「待 USER 排程」）；與 TD-047 同類。owner：USER 排程，可併 D9 xdist 規劃 |
| TD-042 | B117-G5B2-RUN-ONLY-R2-261116 | （一） | 第一個以 run 執行之真實批次回報 IDE 對長命令之行為，審查官據以更新協定 | 結案 | B117-G7A-CONTRACT-STATE-R2-261117 為第一個以 run 執行之 production 批，觀察已寫入 docs/ops/g5-run-protocol.md 第 7 節（FACT）；超過約 2 小時單一命令之行為仍 UNKNOWN，由該節持續登記 |
| TD-043 | B117-G5B2-RUN-ONLY-R2-261116 | （二） | 自檢聲明交叉比對併入合併切片證據工具 | 承接 | 同 TD-021；NEXT_SLICE 排程（五） |
| TD-044 | B117-G7A-CONTRACT-STATE-R2-261117 | （一） | resume-check 納入 index、工作樹、遠端分支與 main 四項核對（第二意見 B-1；觸發 G5-c，併入 USER 端工具說明） | 開放 | owner：G5；原觸發「G5-c」在現行看板無此切片（見第五節註） |
| TD-045 | B117-G7A-CONTRACT-STATE-R2-261117 | （二） | ADR-0021 第 2 點 F 項之過渡期補充說明或新 ADR（第二意見 B-2） | 開放 | 觸發：合併切片之接任重驗與 repo 接任段落配合修改開工時（TD-035）。owner：審查工具批 |
| TD-046 | B117-G7A-CONTRACT-STATE-R2-261117 | （三） | 預演改為快速檢查（X 案；E27） | 結案 | B117-XPREVIEW-QUICK-R2-261118 落地（NEXT_SLICE 載「X 案批已完成」；scripts/tests/test_native_preview.py 有 test_x_* 測試；FACT） |
| TD-047 | B117-G7A-CONTRACT-STATE-R2-261117 | （四） | git 子行程次數降低評估：(1) Windows 改直呼 mingw64 git.exe；(2) 必讀檔改單次 git cat-file --batch；(3) 測試共用 fixture | 開放 | 三小項均未見落地（INFERENCE）；(1) 須 USER 先量測；(2) 原觸發 G5-c（見第五節註）；(3) 同 TD-041。owner：USER 排程 |
| TD-048 | B117-G7A-CONTRACT-STATE-R2-261117 | （五） | 平行測試參考（xdist -n 2 --dist loadfile；runner 設 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1，外掛須以 -p 明確載入；觸發 G6 開工） | 承接 | NEXT_SLICE 排程（四）降低版 G6 與本機第 4 關 xdist 試驗、D9（FACT） |
| TD-049 | B117-G7A-CONTRACT-STATE-R2-261117 | （六） | 合併切片補充：同 SHA post-main 固定結果、CI workflow 規則檢查細項、提示詞模板殘留句（第二意見 O-2） | 承接 | NEXT_SLICE 排程（三）第二批含前兩者（FACT）；「提示詞模板殘留句（O-2）」未見明文列入，作者化該批時須納入 |
| TD-050 | B117-G7A-CONTRACT-STATE-R2-261117 | （七） | 14 個在 Linux 略過、CI 之 Windows job 不執行之測試（test_bundle_after_push 5、test_delivery_pack 9），目前只在 Executor 之 Windows 第 4 關執行 | 承接 | B-117 列「規劃 Windows CI 至少執行 scripts/tests/test_bundle_after_push.py…維持 OPEN」與 NEXT_SLICE 排程（四）降低版 G6（Windows CI 執行全部 scripts/tests）（FACT） |
| TD-051 | B117-G7B1-ARCHIVE-MECHANISM-R2-261117 | b1-一 | 11 列交 USER 看清單（交前以當時規則重新判定） | 結案 | G7-b2 第二次封存 11 列已完成（FACT：G7 列） |
| TD-052 | B117-G7B1-ARCHIVE-MECHANISM-R2-261117 | b1-二 | 批次紀錄封存、保留則數與第一次搬移；B-100／B-115 拆列、列長 CHECK 上限與既有超長列過渡例外；B-107 引用整理後封存 | 承接 | 批次紀錄封存部分已由 G7-b3a／b3a2 完成；其餘為 G7-b3b3（NEXT_SLICE） |
| TD-053 | B117-G7B1-ARCHIVE-MECHANISM-R2-261117 | b1-三 | USER_CONFIRMED_LEGACY 完整版防護（Base 已存在之封存檔不得改、清單只准尾端新增、評估清單雜湊移入 CHECK 28） | 開放 | 觸發：G7-c 與 docs/USER-DECISIONS.md 同批評估（原「G7-b2 或 G7-c」，G7-b2 已過）。owner：G7-c |
| TD-054 | B117-G7B1-ARCHIVE-MECHANISM-R2-261117 | b1-四 | CHECK 29 驗證封存依據需要完整 git 歷史，淺層 clone 會 FAIL（fail-closed） | 開放 | 常設條件；觸發：新增或變更任何淺層 checkout 之批。owner：審查官核對 workflow 變更時檢視 |
| TD-055 | B117-G7B1-ARCHIVE-MECHANISM-R2-261117 | b1-五 | scripts/draft_precheck.py 之工具指紋清單未納入 scripts/taskboard_archive.py | 開放 | scripts/draft_precheck.py 內無 taskboard_archive 字樣（FACT）；觸發：下一個修改 draft_precheck.py 之批（與 TD-028 同觸發）。owner：審查工具批 |
| TD-056 | B117-G7B1-ARCHIVE-MECHANISM-R2-261117 | b1-六 | 封存依據只認列內完整 40 位 commit，AUDIT-LOG 核對通過列須點名本列 ID（寫法提醒） | 結案 | 規則已寫在 scripts/taskboard_archive.py 檔頭封存條件第 2 點（FACT）；提醒性質，不再追蹤 |
| TD-057 | B117-G7B1-ARCHIVE-MECHANISM-R2-261117 | b1-七 | NEXT_WORK、NEXT_SLICE 欄位存在性 CHECK | 結案 | CHECK 30（B117-G7B2-ARCHIVE-CHECK30-261118）判定 NEXT_WORK、NEXT_SLICE、最後更新各恰一行且不空白（FACT：scripts/check_consistency.py check_30）；表格欄位 CHECK 屬 G7-d（TD-038） |
| TD-058 | B117-G7B1-ARCHIVE-MECHANISM-R2-261117 | b1-八 | B-125 之處置（狀態維持「可封存」，封存須 USER 另行決定或由 G7-b2 依新規則判定） | 結案 | USER-2026-11-18-G7B2-D2 已決定，封存列入 G7-c 完成條件（TD-065） |
| TD-059 | B117-XPREVIEW-QUICK-R2-261118 | x-一 | 預演第 4 關預算推估需 repo 內耗時資料契約（觸發：證據工具批） | 承接 | NEXT_SLICE 排程（三）第二批（證據工具批；B117-G7B2-ARCHIVE-CHECK30-261118 之 b2-二 與其同批） |
| TD-060 | B117-XPREVIEW-QUICK-R2-261118 | x-二 | CHECK 29 之 Windows git 成本 UNKNOWN（Linux：check 12 次、plan 52 次），併入排程（四） | 承接 | NEXT_SLICE 排程（四）降低版 G6 |
| TD-061 | B117-XPREVIEW-QUICK-R2-261118 | x-三 | plan 之「被引用」判定列印命名處前後各 30 字元 | 結案 | scripts/taskboard_archive.py 之 ref_context 與 REF_CONTEXT_WIDTH＝30 已落地（FACT） |
| TD-062 | B117-XPREVIEW-QUICK-R2-261118 | x-四 | 欄位 CHECK 與每則批次紀錄約 3 KB 上限 CHECK | 承接 | 欄位 CHECK 已為 CHECK 30（TD-057）；3 KB 上限 CHECK 為 G7-b3b3 第二批（D7 第 0 階段一併重做） |
| TD-063 | B117-XPREVIEW-QUICK-R2-261118 | x-五 | backlog、EXEC-LOG、AUDIT-LOG 之封存與瘦身須先設計（CHECK 28 使其 insert-only） | 承接 | NEXT_SLICE 排程（八）（FACT） |
| TD-064 | B117-XPREVIEW-QUICK-R2-261118 | x-六 | 協定第 8.1、13.8 節把回覆第二行定為推理級別，USER 現行角色文件定為本輪基準，依協定第 13 節以 USER 為準 | 開放 | 觸發：下一份修改協定之批。角色文件起草權屬 USER 指定者，本項只列條號供其處理（Project Instructions 共同邊界） |
| TD-065 | B117-G7B2-ARCHIVE-CHECK30-261118 | b2-一 | G7-c 同批以 USER-2026-11-18-G7B2-D2 封存 B-125，列入 G7-c 完成條件 | 承接 | G7 列 G7-c 完成條件（FACT） |
| TD-066 | B117-G7B2-ARCHIVE-CHECK30-261118 | b2-二 | 第 4 關近四批耗時使 70% 預警每批觸發：增設第二門檻機械信號與最慢測試清單（與 x-一 同批）；在此之前審查官每批核對第 4 關耗時，達 3240 秒向 USER 提議提前 xdist 試驗 | 承接 | NEXT_SLICE 排程（三）第二批；「觸發線仍為 3240 秒」見 NEXT_SLICE（FACT） |
| TD-067 | B117-G7B2-ARCHIVE-CHECK30-261118 | b2-三 | 動到快速模式常數（QUICK_GATE4_ARG、PREVIEW_QUICK_MARKER、gate_runner 閘門標頭）之批，審查官須先以 Base 工具做 --quick-gate4 模擬 | 開放 | 審查官常設程序；觸發：動到上列常數之批。owner：審查官 |
| TD-068 | B117-G7B2-ARCHIVE-CHECK30-261118 | b2-四 | 每則批次紀錄約 3 KB 上限 CHECK，須含既有超限紀錄之過渡處理 | 承接 | G7-b3b3 第二批（NEXT_SLICE；D7 第 0 階段一併重做） |
| TD-069 | B117-G7B2-ARCHIVE-CHECK30-261118 | b2-五 | 快速模式之真實環境證明在本批，失敗為保守 S1 一次 | 結案 | B117-G7B3A-RECORDS-ARCHIVE-261118 紀錄「（b2-五）結案」（FACT） |
| TD-070 | B117-G7B3A-RECORDS-ARCHIVE-261118 | b3a-一 | G7-b3a2：第二次搬移、則數上限 CHECK、RECORD_ARCHIVES_MIN 升為 2、協定第 10.4 節補批次紀錄封存規則、搬前確認兩個多行單元 | 結案 | B117-G7B3A2-RECORDS-MOVE2-R3-261118 紀錄「（b3a-一）已由本批完成」（FACT）；RECORD_ARCHIVES_MIN＝2 為 scripts/taskboard_archive.py 現行常數（FACT） |
| TD-071 | B117-G7B3A-RECORDS-ARCHIVE-261118 | b3a-二 | G7-b3b 範圍見 NEXT_SLICE | 結案 | 指標：G7-b3b 已拆 b3b1（完成）、b3b2（完成）、b3b3（NEXT_SLICE） |
| TD-072 | B117-G7B3A-RECORDS-ARCHIVE-261118 | b3a-三 | G7-b2 第 4 關實際秒數仍 UNKNOWN，審查官可請 USER 唯讀查 Executor 本機 local-gates.txt | 結案 | 審查官決定不追：不影響任何判定，之後各批 runner 已印第 4 關秒數；UNKNOWN 保持 |
| TD-073 | B117-G7B3A-RECORDS-ARCHIVE-261118 | b3a-四 | （b2-五）結案；（b2-二）以上界續追 | 結案 | 指標：見 TD-069、TD-066 |
| TD-074 | B117-G7B3A2-RECORDS-MOVE2-R3-261118 | b3a2-一 | G7-b3b 範圍見 NEXT_SLICE（含 b3a 與本批紀錄超過 3 KB 之過渡規則） | 承接 | 3 KB 過渡規則為 G7-b3b3 第二批（TD-068） |
| TD-075 | B117-G7B3A2-RECORDS-MOVE2-R3-261118 | b3a2-二 | G7-b3a 紀錄第六點之（b3a-一）已由本批完成，其餘仍依該紀錄第六點辦理 | 結案 | 指標：該紀錄第六點之 b3a-二至四分見 TD-071 至 TD-073 |
| TD-076 | B117-G7B3A2-RECORDS-MOVE2-R3-261118 | b3a2-三 | 第 4 關秒數 3051.516 秒續追（b2-二） | 承接 | 同 TD-066 |
| TD-077 | B117-G7B3A2-RECORDS-MOVE2-R3-261118 | b3a2-四 | G7-c 收攏 USER 決定時須含本批寫回之 POSTRUN 方案甲 | 承接 | G7 列 G7-c「含 B117-G7B3A2-RECORDS-MOVE2-R3-261118 寫回之 POSTRUN 方案甲」（FACT） |
| TD-078 | B117-G7B3A2-RECORDS-MOVE2-R3-261118 | （一） | 2026-11-18 USER 要求每批須有「一句話：解決了什麼」且機械化（於 G7-b3b 實作） | 結案 | G7-b3b2（B117-G7B3B2-ONE-LINER-R3-261120）落地：prompt_builder 之 one_liner 與 CHECK 29、CHECK 26 之一句話檢查（FACT：Macro PASS 與 POST-MAIN VERIFIED） |
| TD-079 | B117-G7B3A2-RECORDS-MOVE2-R3-261118 | （二） | Defender 設定不變；本機第 4 關有界 pytest-xdist 試驗改排在 G7-b3b 之後（經第二意見轉達之使用者確認） | 承接 | NEXT_SLICE 排程（二）本機第 4 關有界 pytest-xdist 試驗；D1「不改任何設定」（FACT：NEXT_SLICE 與 D1 至 D9 決定行） |
| TD-080 | B117-G7B3A2-RECORDS-MOVE2-R3-261118 | b3a2-五 | G7-b3b 範圍見 NEXT_SLICE（要項 1 至 3） | 結案 | 指標：同 TD-071 |
| TD-081 | B117-G7B3A2-RECORDS-MOVE2-R3-261118 | b3a2-六 | G6 類別待辦已登錄於 G6 列（短期限真實進程樹逾時測試） | 承接 | G6 列現行文字（FACT） |
| TD-082 | B117-G7B3A2-RECORDS-MOVE2-R3-261118 | b3a2-七 | W2 之 .git 現存 49 份歷來各批 PRECOMMIT 第 4 關原始紀錄，本測試之歷史結果未逐份核對（UNKNOWN） | 開放 | 觸發：G6 lint 或 D1／D9 需要歷史失敗率時。owner：G6 |
| TD-083 | B117-G7B3A2-RECORDS-MOVE2-R3-261118 | b3a2-八 | G7-b3b 之後之 xdist 試驗 | 承接 | NEXT_SLICE 排程（二）本機第 4 關有界 pytest-xdist 試驗（FACT） |
| TD-084 | B117-G7B3A2-RECORDS-MOVE2-R3-261118 | b3a2-九、（三） | 審查工具批登錄 EXECUTOR-START.txt（delivery_pack 另輸出，避免區塊 3 手抄錯誤；同紀錄第十點（三）建議） | 開放 | 看板現只在 B117-G7B3A2-RECORDS-MOVE2-R3-261118 紀錄登錄此建議，該紀錄本批搬入封存檔，不是承接位置，故列開放。owner：審查工具批；觸發：該批作者化 |

註：多項待辦以「G5-c」為觸發，但 `docs/TASKBOARD.md` 現行文字沒有「G5-c」這個切片（FACT：全檔 0 次出現）；其觸發因此無從滿足。這些項目（TD-017、TD-018、TD-020、TD-044、TD-047 之 (2)）現在的 owner 是 G5 列（OPEN），是否另立 G5-c 或併入其他切片，由後續排程決定。
