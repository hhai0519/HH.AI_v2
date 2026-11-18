# 任務看板封存（docs/archive/TASKBOARD-ARCHIVE-*）

> 這是歸檔區，不是現行狀態。現行待辦與狀態以 `docs/TASKBOARD.md` 為準。

- `TASKBOARD-ARCHIVE-MANIFEST.json`：機器可讀清單。每個封存檔一筆，內含每一列的 ID、原位置、封存時狀態、封存依據、原文 SHA-256 與位元組數；另有 `user_keep`（USER 標記保留、不得封存的 ID）。
- `TASKBOARD-ARCHIVE-NNNN.md`：封存檔。由 `python scripts/taskboard_archive.py apply` 一次寫成，之後不得修改；每列是封存當時 TASKBOARD 的原文，逐字保留，放在四個反引號的 `text` 圍欄內。
- 規則見 `.claude/rules/auditor-protocol.md` 第 10.4 節；CHECK 29（`scripts/taskboard_archive.py`）逐位元組核對清單、封存檔與 SHA-256，並檢查看板、`docs/ARCHIVE-INDEX.md` 與本說明檔互相可達。
- `TASKBOARD-RECORDS-NNNN.md`：批次紀錄封存檔（B-117 G7-b3a 起）。看板「治理完成線」節以「**…（日期；本批 TASK_ID）**：」開頭的批次紀錄（含緊接其後、到空白行或下一則紀錄之前的續行，合稱一個單元）只留最新幾則，較舊的由 `python scripts/taskboard_archive.py records-apply --repo . --task-id <TASK> --checkpoint-oid <oid> --keep N --take M` 逐字搬來（`records-plan` 唯讀列出盤點數字與每則的保留或搬移；保留數不得小於 1，`--keep` 是套用當下看板上既有紀錄之保留數、不含該批新增之一則）。清單在 manifest 的 `record_archives`（每則的 TASK_ID、原行號、行數、SHA-256、位元組數）；CHECK 29 逐位元組核對封存檔，並以 git 在封存當時 checkpoint 的看板逐行比對原文。多行單元（續行內可能有仍有效的 USER 決定）預設拒絕搬移，須以 `--allow-multiline TASK_ID` 逐一點名（`records-plan` 先逐行印出前 40 個字元供複核；`--keep` 必填）。CHECK 29 另要求：checkpoint 看板上的每則批次紀錄仍在看板上或已封存、`record_archives` 相對 checkpoint 的清單只能在尾端追加、看板批次紀錄不得超過 6 則。
- 想找某個已封存的任務：先到 `TASKBOARD-ARCHIVE-MANIFEST.json` 以 ID 查封存檔，再開對應的 `TASKBOARD-ARCHIVE-NNNN.md`。
- 想找某個已封存的批次紀錄：先到 manifest 的 `record_archives` 以 TASK_ID 查封存檔，再開對應的 `TASKBOARD-RECORDS-NNNN.md`。
- 封存依據兩種：`MACRO_PASS_ANCESTOR`（列內的完整 40 位 commit 有 Macro PASS、該核對通過列點名本列 ID，且 commit 是 checkpoint 的祖先）、`USER_CONFIRMED_LEGACY`（USER 2026-11-17 確認第一次封存的舊列，沒有 commit，只此一次）。
