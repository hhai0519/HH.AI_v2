# 任務看板封存（docs/archive/TASKBOARD-ARCHIVE-*）

> 這是歸檔區，不是現行狀態。現行待辦與狀態以 `docs/TASKBOARD.md` 為準。

- `TASKBOARD-ARCHIVE-MANIFEST.json`：機器可讀清單。每個封存檔一筆，內含每一列的 ID、原位置、封存時狀態、封存依據、原文 SHA-256 與位元組數；另有 `user_keep`（USER 標記保留、不得封存的 ID）。
- `TASKBOARD-ARCHIVE-NNNN.md`：封存檔。由 `python scripts/taskboard_archive.py apply` 一次寫成，之後不得修改；每列是封存當時 TASKBOARD 的原文，逐字保留，放在四個反引號的 `text` 圍欄內。
- 規則見 `.claude/rules/auditor-protocol.md` 第 10.4 節；CHECK 29（`scripts/taskboard_archive.py`）逐位元組核對清單、封存檔與 SHA-256，並檢查看板、`docs/ARCHIVE-INDEX.md` 與本說明檔互相可達。
- 想找某個已封存的任務：先到 `TASKBOARD-ARCHIVE-MANIFEST.json` 以 ID 查封存檔，再開對應的 `TASKBOARD-ARCHIVE-NNNN.md`。
- 封存依據兩種：`MACRO_PASS_ANCESTOR`（列內的完整 40 位 commit 有 Macro PASS、該核對通過列點名本列 ID，且 commit 是 checkpoint 的祖先）、`USER_CONFIRMED_LEGACY`（USER 2026-11-17 確認第一次封存的舊列，沒有 commit，只此一次）。
