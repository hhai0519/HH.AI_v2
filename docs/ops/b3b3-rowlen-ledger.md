# G7-b3b3 第二批規範（看板列長守衛、機械逐字拆列與待辦清冊進階檢查）

> 本文件說明 `B-117` `G7-b3b3` 第二批（`B117-G7B3B3-ROWLEN-LEDGER-R3-261125`）落地之機械守衛：`TD-106`（承接位置有效性）、`TD-107`（開放列複查日與到期提醒）、`TD-108`（開放列依據欄只准追加）、`CHECK 32`（任務看板列長上限與過渡例外），以及 `split-row`（機械逐字拆列工具）。

---

## 一、任務看板列長守衛（CHECK 32）與機械逐字拆列（`split-row`）

1. **單列上限**：`docs/TASKBOARD.md` 所有表格資料列（含 `scripts/taskboard_archive.py` 之 `_table_data_rows` 所得標準列，以及其餘以 `|` 開頭之非分隔／非表頭資料列與續行）皆不得超過 `ROW_MAX_CHARS = 2500` 字元。
2. **既有超長列過渡例外**：`ROW_LEN_LEGACY_CAPS` 列管 `b3b3-2` 上線當下仍超過 `2500` 字元且尚未封存或拆分的既有歷史列（`G6`、`G5`、`G7`、`B-118`、`B-123`、`B-112`、`B-116`、`B-111`、`B-119`，共 9 列；其中 `G7` 依 Dashboard 每 G 一列與不刪除原則逐字保留於 `2,793` 字元）。
   - 該清單之每筆上界必須大於 `2500`，且檢查時與 `docs/refactor-backlog.md` 第 5.1 節 `checkpoint` 當時的該列長度取較小值，確保既有超長列**只減不增**；若縮減至 `2500` 以下，之後重新膨脹超過 `2500` 一樣失敗。
   - 任何新列或拆列（例如 `B-100*`、`B-115*`）一律不得進入白名單。
3. **機械逐字拆列（`split-row`）與串接不變量**：
   - `python scripts/taskboard_archive.py split-row --repo <repo> --id <ID> [--max-chars 2500] [--apply]` 將超長列內文依序於「`。`」「`；`」句界（避免段首或段尾空白）切成每段 `<= 2500` 字元之連續子列（`<ID>-1..N`，標題標註 `（續段 k/N）`），主列保留索引與切分當下原文長度及 `SHA-256`。
   - 子列第四欄內文依序串接（`verify_split_concat`）須與拆列前內文逐位元組相等（`B-100` 與 `B-115` 僅於拆列前套用 `B-107` 引用整理與 `B-100` 唯一短碼補全，其餘字元 100% 逐字不變）。
4. **Dashboard 相容規範**：拆分 `B-100`、`B-115` 等表格列時，第一欄須採完整大寫 ID（符合 `^[A-Z][A-Z0-9]*(-[A-Z0-9]+)*$`，例如 `B-100-1`、`B-115-5`），表內不得使用第一欄空白之續行。
5. **指令介面**：`python scripts/taskboard_archive.py row-length-check --repo <repo>` 與 `scripts/check_consistency.py` 第 32 項（`total_checks = 32`）共用 `check_row_lengths(root)`，遇缺檔、BOM、CR、重複 ID 或 Git checkpoint 無法解析時一律 fail-closed。

---

## 二、待辦清冊承接位置有效性（TD-106）

1. 自錨點 `LEDGER_V2_ANCHOR = B117-BETA2-D4-CAP-S1DRAFT-R4-261124` 出現於看板或批次紀錄封存檔起，`docs/TODO-LEDGER.md` 所有處置為 `承接` 之列，其依據欄須包含至少一個結構化標記（全形冒號）：
   - `承接位置：ROW:<ID>` 或 `承接位置：ROW:<ID>「<錨點>」`（`<錨點>` 至少 2 字元）：`<ID>` 須存在於現行 `docs/TASKBOARD.md`、狀態不得為 `已完成`／`可封存`／`CLOSED*`，且若指定錨點，該列原文須逐字包含該錨點。
   - `承接位置：BOARD「<錨點>」`（`<錨點>` 至少 4 字元）：`<錨點>` 須逐字存在於排除批次紀錄單元與「封存區」後之現行看板本文。
2. 任一 `承接位置` 標記缺漏、改用半形冒號或指向已封存／已結案／不存在之目標，CHECK 29 即回傳 FAIL。

---

## 三、開放列複查日與只准追加守衛（TD-107、TD-108）

1. **格式與單調性（CHECK 29；CI 決定性）**：
   - 每一「開放」列依據欄皆須含 `owner：…`（或 `owner:…`）與至少一個合法「`複查日 YYYY-MM-DD`」（單一半形空白後接 ISO 日期）。
   - 依據 TD-108，維持「開放」之既有列其依據欄須嚴格保留 `checkpoint` 原文字作為字首，僅得於尾端追加文字（`row['basis'].startswith(old['basis'])`），不得刪除 `owner` 或改寫舊文。
   - **改期設計**：欲延長複查日時，於依據欄尾端追加新的「`複查日 YYYY-MM-DD`」；舊日期保留為歷史。CHECK 29 僅檢查所有出現之複查日皆合法且**新日期不早於舊日期**，絕不於 CI 讀取系統時鐘判失敗。
2. **作者端與 Dashboard 到期提醒**：
   - 作者端唯讀工具 `python scripts/taskboard_archive.py ledger-review --repo <repo> [--as-of YYYY-MM-DD] [--warn-days 7] [--json]` 一律以該列**最後一個**複查日判定逾期（`review_date < as_of`）或近期到期（`0 <= days_until <= warn_days`），並整合於 `records-plan` 與 `scripts/draft_precheck.py`（`--fast` 與完整預查）之非阻擋摘要 `TODO_LEDGER_REVIEW`。
   - 本機 Dashboard 以相同規則解析最後一個「`複查日 YYYY-MM-DD`」顯示逾期或即將到期提醒，只顯示不阻擋。
