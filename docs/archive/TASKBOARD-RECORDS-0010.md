# 任務看板批次紀錄封存 0010

> 本檔由 `scripts/taskboard_archive.py records-apply` 產生，寫成後不得修改。清單與每則的 SHA-256 在 `TASKBOARD-ARCHIVE-MANIFEST.json` 的 `record_archives`，由 CHECK 29 逐位元組核對，並以 git 在封存當時 checkpoint 的 `docs/TASKBOARD.md` 逐行比對原文。
> 封存不是刪除：下列各則是封存當時 `docs/TASKBOARD.md` 批次紀錄的原文（含續行），逐字保留。
> 封存批次：B117-ALPHA2-FAST-PRECHECK-R2-261123；封存當時 checkpoint：`3ee29c8a6abd041eaa3a76d1ee9e45d56aee49ae`；看板保留數：5

## 封存紀錄

### B117-G7B3B3-TODO-LEDGER-261120

- 原位置：`docs/TASKBOARD.md` 第 131 行起，共 1 行（封存前）

````text
**B-117／G7-b3b3 第 1 批（封存紀錄帶走之待辦盤點與清冊）與 G6 小批結案登錄批（2026-11-20；本批 B117-G7B3B3-TODO-LEDGER-261120）**：一句話：把封存紀錄帶走的待辦逐項盤點，寫成一份有編號的清冊。一、範圍與依據：G7 列（b3b1-一）；USER 2026-11-20 決定 G7-b3b3 四件全做、不受 D6 凍結限制。審查官依 USER 常設決定（2026-11-17）拆為 b3b3-1（本批）、b3b3-2（列長 CHECK 與長列拆列）、b3b3-3（清冊機械檢查）；理由：本批只動狀態與文件，不改驗證器，不需 D-SO 與 E27，且清冊是 b3b3-3 的資料來源；b3b3-2、b3b3-3 為驗證器類。3 KB 紀錄大小 CHECK 依 USER 決定於 D7 第 0 階段重做。二、內容：新增 docs/TODO-LEDGER.md，84 項（結案 23、承接 36、開放 25），編號 TD-001 至 TD-084，全 repo 唯一、不重用、只增不減；每項寫來源批次紀錄、原標籤、事項、處置與依據。範圍＝第二意見 58 項＋RECORDS-0003 之 9 個標籤＋本批搬移之 G7-b3a2 紀錄 11 項＋PRESTART 紀錄 2 項＋RECORDS-0001 之 4 組群組級待辦；審查官 14 個、第二意見 58 個、本清冊 84 個三種計數方法之範圍與判定規則並列於該檔第四節，不以其中一種取代另一種。方法 A 於 da9fdbde 重算：14 個標籤在看板現行文字出現 0 個；方法 B 以第二意見之唯讀腳本重算為定義 68 個（58＋RECORDS-0003 新增 10）。處置規則：結案寫批次與證據；承接寫承接位置；開放寫 owner 與觸發條件或複查日。FACT：「G5-c」切片在看板現行文字 0 次出現，原以其為觸發之 5 項無從觸發，owner 暫為 G5 列，是否另立由後續排程決定。三、限制：RECORDS-0001 之 27 則紀錄無全形括號標籤，只列 4 組群組級待辦，群組內逐項是否仍有對應文字未核實（UNKNOWN）；看板上仍留之 5 則舊紀錄之待辦不在本批盤點，待搬移時依清冊規則補編 TD；「承接」只核對位置與文字存在，不代表已排時程。本批沒有新增待辦（b3b3-2、b3b3-3 為 NEXT_SLICE 排程項）。四、同批搬移：records-plan keep 5 後以 records-apply 搬移最舊 1 則 B117-G7B3A2-RECORDS-MOVE2-R3-261118（單行、15953 位元組）至 docs/archive/TASKBOARD-RECORDS-0004.md（checkpoint da9fdbde）；本批之後看板批次紀錄 6 則（上限 6，已滿）。五、同批登錄：前一批 B117-G6-FIXED-WAIT-261120（da9fdbde3dc0bc6ea587324efeb5286e5e7fa80d）之 Macro PASS 與 POST-MAIN VERIFIED（candidate Run 44748195606、post-main Run 44750723161 皆 attempt 1 雙 job success）；治理凍結行連續無 S1 批數由 0 更新為 1（D6 第一個計數批）；G7 列與 NEXT_SLICE 更新。六、E24 REQUIRED（字面查詢 7 項）；E27 N/A；D4 N/A（非 S1 修復批）；focused 為 scripts/tests/test_channel_gateway_core.py；native_preview；bundle_output false。
````
