# 任務看板批次紀錄封存 0005

> 本檔由 `scripts/taskboard_archive.py records-apply` 產生，寫成後不得修改。清單與每則的 SHA-256 在 `TASKBOARD-ARCHIVE-MANIFEST.json` 的 `record_archives`，由 CHECK 29 逐位元組核對，並以 git 在封存當時 checkpoint 的 `docs/TASKBOARD.md` 逐行比對原文。
> 封存不是刪除：下列各則是封存當時 `docs/TASKBOARD.md` 批次紀錄的原文（含續行），逐字保留。
> 封存批次：B117-TAKEOVER-STATE-261121；封存當時 checkpoint：`2137065f8828fb5ef1e5f5f27c4947393f74c205`；看板保留數：5

## 封存紀錄

### B117-G7B3B1-TAKEOVER-ARCHIVE-R2-261119

- 原位置：`docs/TASKBOARD.md` 第 131 行起，共 1 行（封存前）

````text
**B-117／G7-b3a2 結案、審查官交接與 G7-b3b1 封存檢查補強登錄批（2026-11-19；本批 B117-G7B3B1-TAKEOVER-ARCHIVE-R2-261119）**：一句話：封存檢查也擋下看板列與舊紀錄被刪改，並完成審查官交接。一、前一批 B117-G7B3A2-RECORDS-MOVE2-R3-261118（5dc5105188ccd2601a6eac4b1dfbf56c282b7309）Macro PASS 與 POST-MAIN VERIFIED，依據見 AUDIT-LOG 該列。二、審查官交接：USER 2026-11-19 任命 AUD-CLAUDE-261119，等級 A；前任線索檔與第二意見補充線索逐項處置見 EXEC-LOG 本批列。三、本批變更：CHECK 29（scripts/taskboard_archive.py）新增 checkpoint 看板上的表格列須仍在看板或已封存、manifest 之 archives 只追加、user_keep 只增不減、留在看板的舊批次紀錄須與 checkpoint 逐字相同、新紀錄只能連續排在最前面；records-plan 之 MULTILINE 行加印位元組數，RECORDS_SUMMARY 加印 on_board、max、room；checkpoint 之 manifest 形狀錯誤各有訊息；檔頭註明 checkpoint 不倒退依賴 check_consistency 之「已過期」判定與 CHECK 28；協定第 10.4 節補句。四、G7-b3b 拆為三批（USER 常設決定 2026-11-17：切片拆成多批不必先徵詢，須寫明範圍與理由）：b3b1 為本批（原要項 2），b3b2 為「一句話」機制（原要項 1），b3b3 為長列拆列與紀錄大小上限（原要項 3）並含（b3b1-一）。理由：接任後首個改狀態之批須同時推進 NEXT_WORK，先做範圍最小、與上一批同一工具的要項。與第二意見 O2 原文「只有最新一則可為新」不同：允許多則新紀錄連續排在最前面，以容納 checkpoint 落後一批以上之修復批。五、新增待辦：（b3b1-一）封存批次紀錄帶走之待辦，登錄於 G7 列；（b3b1-二）G6 守衛殘餘寫法與 TREE_SIGNALLED 字串允許清單，登錄於 G6 列；（b3b1-三）TASK_ID 格式、（b3b1-五）HEAD 漂移停止時印預期與實際 HEAD，登錄於 G3 列；（b3b1-四）每批回覆固定印第 4 關秒數，登錄於 G6 列；（b3b1-六）S1 根因登記檔是否進 repo，登錄於 G7 列。六、第 4 關歷史秒數補記：G7-b3a 為 3051.516 秒（前一批紀錄第十一點漏列）；前一批第 4 關實際秒數 UNKNOWN。七、USER 常設決定 D-SO（2026-10-25）依通用版交接提示詞第十節登錄（該節轉述，非 USER 逐字原話）：會改變驗證或判定邏輯的批次（CHECK、runner、gate，以及審查官端的判定工具）一律啟用執行前第二意見；只寫狀態或純報告工具的批次一律不啟用；不再逐批詢問使用者，個案例外由審查官在五欄標註理由。八、E24 REQUIRED；E27 APPLICABLE：B117-G7B3B1-TAKEOVER-ARCHIVE-R1-261119 之第二意見複核結果為 BLOCKING 0／NON_BLOCKING 3（N1 缺 archives 一側之測試、N2 第七點寫法、N3 G7-c 前向影響），三項皆併入本批；該前一版未交 Executor 而作廢；bundle_output false。
````
