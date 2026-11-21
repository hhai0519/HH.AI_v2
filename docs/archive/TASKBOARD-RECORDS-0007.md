# 任務看板批次紀錄封存 0007

> 本檔由 `scripts/taskboard_archive.py records-apply` 產生，寫成後不得修改。清單與每則的 SHA-256 在 `TASKBOARD-ARCHIVE-MANIFEST.json` 的 `record_archives`，由 CHECK 29 逐位元組核對，並以 git 在封存當時 checkpoint 的 `docs/TASKBOARD.md` 逐行比對原文。
> 封存不是刪除：下列各則是封存當時 `docs/TASKBOARD.md` 批次紀錄的原文（含續行），逐字保留。
> 封存批次：B117-G7B3B3-LEDGER-CHECK-R3-261121；封存當時 checkpoint：`608c1e61ef3e2c4f156e6eb2181c9155e3fdd069`；看板保留數：5

## 封存紀錄

### B117-G7B3B2-ONE-LINER-R3-261120

- 原位置：`docs/TASKBOARD.md` 第 131 行起，共 1 行（封存前）

````text
**B-117／備份 owner 測試修正批結案與 G7-b3b2 每批一句話機制登錄批（2026-11-20；本批 B117-G7B3B2-ONE-LINER-R3-261120）**：一句話：每批結案紀錄開頭都必須有一句白話，說明這批解決了什麼。一、前一批 B117-BACKUP-TEST-CLOCK-R2-261120（c3eb1fe575b86a363f81a8a45d8a6fbbfb600554）Macro PASS 與 POST-MAIN VERIFIED，依據見 AUDIT-LOG 該列。本批為 G7-b3b2 重出：第一次出 B117-G7B3B2-ONE-LINER-R2-261119 於 PRECOMMIT 第 4 關 S1 停止，事故與處置見前一則紀錄；本批十個作者檔位元組與該次相同，狀態文字依現況重寫，新 TASK_ID（refactor-backlog §5.3 第 21 項）。二、本批變更：prompt_builder 之 production definition 必填 one_liner（8 至 60 字元、單句單行、不含 TASK_ID、SHA、檔案路徑），並新增 ONE_LINER 占位符，展開為「一句話：……。」；該批看板紀錄（為最新一則時）與 EXEC-LOG 新列不以它開頭即拒絕。taskboard_archive 新增共用驗證器與錨點 ONE_LINER_ANCHOR（B117-G7B3B1-TAKEOVER-ARCHIVE-R2-261119，該批已符合）；CHECK 29 核對看板最新一則批次紀錄，CHECK 26 核對 EXEC-LOG 錨點之後的新列；不新增 CHECK 編號，仍為 30 項；舊紀錄與舊列不追溯；錨點之紀錄與列皆受只增不減保護，不能靠刪錨點關掉檢查。協定新增第 10.8 節並重產規則可追溯文件。三、第二意見（非權威）晉級核對函（USER 2026-11-19 轉交）要求之前向更正，審查官核實後採用：（一）G7 列 G7-c 句原寫「C-01 至 C-08、G1、G2、G11 與 B-125 等不是已完成或可封存之列」不精確：B-125 之狀態為「可封存」，卡住的原因是沒有可用的封存依據，不是狀態；C-01 至 C-08 之狀態為「已裁決」，G1、G2、G11 為 CLOSED，皆非 CHECK 29 之封存狀態；已改寫該句。（二）待辦標籤之兩種計數（第二意見 58 個、審查官 14 個）方法不同，已寫入 G7 列（b3b1-一），G7-b3b3 盤點時兩種都納入並寫明方法。四、工具只驗形式；句子是否真的白話說清「解決了什麼」，由審查官在 Macro 審查判定（協定第 10.8 節第 4 點）。五、事故追蹤與耗時（FACT）：S1 事故已登錄於 Dashboard 之 S1C-021（第二意見轉述，USER 於 2026-11-20 更新；Dashboard 不在 repo 內，審查官未讀其本體）：status 維持 planned、指向 g6-clock-1，測試部分 fixedBy 為 B117-BACKUP-TEST-CLOCK-R2-261120；PRECOMMIT 第 4 關於前一批耗時 3061.299 秒，為上限 3600 秒之 85%，runner 已印 GATE_BUDGET_WARN（第 4 關 70% 即警示）；S1 那次為 1847.479 秒；原因 UNKNOWN。今後審查官於每個 production 提示詞交付時寫明最近一次第 4 關秒數與占比，並提醒 USER 執行期間 W2 那台電腦不跑重工作；（b3b1-四）仍維持，未提前。六、紀錄上限：本批之後看板批次紀錄為 6 則（上限 6），下一個新增看板批次紀錄的批須同批搬移舊紀錄（見 NEXT_SLICE）。七、E24 REQUIRED；E27 APPLICABLE（D-SO，驗證器類）：第二意見對 B117-G7B3B2-ONE-LINER-R1-261119 的執行前複核為 BLOCKING 1／NON_BLOCKING 1，審查官核實後皆已處置於 B117-G7B3B2-ONE-LINER-R2-261119（B1：EXEC-LOG 一句話檢查與 CHECK 26 最新列判定之儲存格切法已共用同一種去空白切法；N1：協定第 10.8 節補明機械強制）；本批作者檔位元組不變，依 D-SO 不再送第二意見；bundle_output false。
````
