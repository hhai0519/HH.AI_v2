# D8：S1 根因登記檔（`docs/governance/s1-registry.json`）規範

> 本文件為 `docs/governance/s1-registry.json`（`schema: 2`）之倉庫內規範來源（由 `B117-BETA1-S1-REGISTRY-R2-261124` 依 USER 2026-11-20 D8 與 2026-11-23 `D-BETA-SPLIT=A`／`D-BETA-D6-SCOPE=A` 建立）。

## 一、定位與欄位契約

1. **單一事實來源（D8／TD-101）**：`docs/governance/s1-registry.json` 記錄已發生之 S1 事故事實（`id`、`title`、`tasks`、`watch`、`evidence`、`by`、`distinctFrom`／`distinctBy`、`outcomes`）、驗證紀錄（`verified`、`confirmed`）與結構化根因類別（`class`）。
2. **與 `docs/TODO-LEDGER.md` 之分工與相容過渡**：
   - `docs/TODO-LEDGER.md` 為後續改善待辦之單一追蹤來源；原因可透過選用陣列欄位 `todoIds`（由 CHECK 31 核對每個 `TD-nnn` 均存在於清冊）指向清冊條目。
   - 既有欄位（`status`、`fixedIn`、`fixedCommit`、`fixedBy`、`plannedIn`、`reason`、`followUp`、`verified`）於本次切換期維持保留，使 Dashboard「S1 追蹤」頁不中斷相容切換；不得因搬移或 commit 而將原 `confirmed: false` 一併改為 `true`。
3. **搬移初版之 21 筆 `confirmed: false` 類別判定**：既有 21 筆尚無類別之歷史列均維持 `confirmed: false`，其 `class` 係由審查官依原文記錄所作之機制判讀，並受 CHECK 31 列舉檢查與 `s1_registry.py summary` 之 `class_changes` 輸出追蹤。

## 二、根因類別列舉與優先序

分類一律依**根因機制**而非發生平台（例如在 Windows 上發生之牆鐘或行程樹競態仍歸 `A` 類、而非 `C` 類）。若一筆同時涉及多項，依固定優先序 **`A → B → D → C → E → F`** 取最高優先單一類別：

| 類別 | 名稱 | 判斷界線 |
|---|---|---|
| `A` | 測試時序、牆鐘與競態 | 固定睡眠、過短逾時門檻、背景工／行程樹競態或牆鐘／mtime 毫秒邊界誤差 |
| `B` | 第 4 關總時間預算與負載 | 第 4 關整體 `verify_all` 超出單閘門或 runner 總時限 |
| `D` | 工具輸出形式隨環境變數改變 | `CI`、`BUILD_NUMBER`、`FORCE_COLOR`、`PY_COLORS`、詳細度或 `PYTEST_ADDOPTS` 改變工具終端輸出而造成截斷或漏列 |
| `C` | Windows 與跨平台環境、換行、編碼與路徑差異 | Windows 文字模式 CRLF、stderr 換行警告、`cp950` 編碼、PATH／Python 版本／symlink 權限、Git 路徑轉義或反斜線路徑分隔 |
| `E` | 流程准入、步驟順序與狀態同步節奏 | 控制檔重入、precontrol／native_preview 與 `STEP_IN_PROGRESS` 步驟時序或前置檢查漏欄 |
| `F` | 外部網路、平台基礎設施或未明根因 | CI runner 外部連線／環境或現有證據不足以判定機制之未明根因 |
| `UNCLASSIFIED` | 暫定未分類草稿 | 僅供自動草稿暫存；不計入 `A`–`F` 同類統計，由摘要另行顯示並提醒補分類 |

## 三、CHECK 31 與非遞減守衛

`scripts/check_consistency.py` 之 **CHECK 31** 委由 `scripts/s1_registry.py` 執行，失敗即阻止過關（fail-closed）：

1. UTF-8、無 BOM、僅 LF 換行，且符合 `schema: 2` 頂層與每筆原因必填欄位、狀態相依欄位（`fixed` 必含 `fixedIn`／`fixedCommit`、`planned` 必含 `plannedIn`、`unplanned` 必含 `followUp` 物件（含非空 `plannedIn` 與 `note`）、`accepted` 必含 `reason`）、`watch` 正規式、`fixedBy`／`outcomes` 鍵值對齊 `tasks`、`distinctFrom`／`distinctBy` 一致性、`class` 屬於 `A`–`F`／`UNCLASSIFIED`，以及 `todoIds` 全部存在於 `docs/TODO-LEDGER.md`。
2. **只增不減比對**：讀取 `docs/refactor-backlog.md` 第 5.1 節 `上次核對通過的 HEAD：<40 hex>` 指向之 Git 提交；當該提交已存在 `docs/governance/s1-registry.json` 時，禁止刪除既有 `S1C-nnn`、禁止從 `tasks` 撤回既有 `TASK_ID`，並禁止將已確認之 `confirmed: true` 退回為 `false`。若 checkpoint 提交尚無本檔（例如首次建立本檔之批次），只輸出 INFO 並略過歷史差集。
3. **不在 CI 以日期判失敗**：依與 `TODO-LEDGER` 過期提醒相同之決定性原則，CHECK 31 不讀取目前日曆時間。超過 7 天未重核之未結案（非 `fixed` 且非 `accepted`）項目僅由 `scripts/s1_registry.py summary` 與 `scripts/draft_precheck.py` 以資訊行提醒。

## 四、雙源切換規則（β-1 晉級前後）

1. **β-1 尚未 `POST-MAIN VERIFIED` 之前**：新發生之 S1 事故仍依既有方式暫記於本機 Dashboard 檔案（例如 `S1C-026+`），於後續狀態批或 β-2 一併併入 `docs/governance/s1-registry.json`。
2. **β-1 通過 `POST-MAIN VERIFIED` 之後**：Dashboard 切換為唯讀讀取 GitHub `main` 上之權威檔案（`raw.githubusercontent.com/hhai0519/HH.AI_v2/main/docs/governance/s1-registry.json`），本機舊檔案退為唯讀備援鏡像；兩處不得互相覆寫或遺漏編號。
3. **工具命令列（唯讀）**：
   - `python scripts/s1_registry.py check --repo <repo>`：執行與 CHECK 31 相同之完整驗證。
   - `python scripts/s1_registry.py summary --repo <repo> [--as-of YYYY-MM-DD] [--json]`：輸出各類分布（`UNCLASSIFIED` 另計）、高頻重複類別、相較 checkpoint 之 `class_changes` 變更清單與非阻擋之 7 天未重核提醒。
   - `python scripts/s1_registry.py reverse-verify --repo <repo> --fix-task <TASK_ID> [--regression-test <NODEID> ...] [--not-injectable --reason <TEXT> | --injection-method <TEXT> --old-cmd <JSON_ARGV> --new-cmd <JSON_ARGV> --mutant-cmd <JSON_ARGV>] [--timeout 300] [--out <PATH>] [--json]`：執行或登錄 D4 反向驗證，於驗證前先透過 AST 確認所有 `regressionTests` nodeid 存在於目標倉庫且為無 BOM／LF 合法 Python。

## 五、D4 反向驗證（`reverseVerification`）契約（β-2 擴充）

由 `B117-BETA2-D4-CAP-S1DRAFT-R4-261124` 新增於 `CAUSE_ALLOWED_KEYS` 與 CHECK 31：

1. **可注入模式（`injectable: true`，恰含下列 10 個欄位）**：
   - `fixTask`（`str`，`^[A-Za-z0-9_-]+$`）：對應修正批次之 `TASK_ID`。
   - `injectable`（`bool`，必須為 `true`）。
   - `injectionMethod`（非空 `str`）：失敗或故障注入方法說明。
   - `oldResult`（固定字面 `"FAIL"`）、`newResult`（固定字面 `"PASS"`）、`mutantResult`（固定字面 `"FAIL"`）。
   - `oldOutputSha256`、`newOutputSha256`、`mutantOutputSha256`（皆為 64 碼小寫 hex `str`）：由 `reverse-verify` 以 `bounded_process.run_bounded(..., merge_stderr=True)` 擷取原始輸出位元組計算。
   - `regressionTests`（非空不重複 `list[str]`）：pytest nodeid（`path.py::fn` 或 `path.py::Cls::meth`）；CHECK 31 檢查路徑安全、無 symlink、UTF-8／無 BOM／LF 與 AST 符號存在性。
2. **不可注入模式（`injectable: false`，必填前 4 欄，`regressionTests` 選用）**：
   - `fixTask`（`str`）、`injectable`（`false`）、`status`（固定字面 `"not_injectable"`）、`notInjectableReason`（非空 `str`）、選用 `regressionTests`（不重複 `list[str]`，若存在亦經 AST 驗證）。
3. **「修正事件」轉 `fixed` 強制與只增不減守衛（`B2`／`N2`）**：
   - 定義「修正事件」為：以 checkpoint 為基準，本版 `status == "fixed"` 且符合下列任一項：(a) 新增原因；(b) 前版非 `fixed`（例如 `planned` 轉 `fixed` 或重新開啟後再修正）；(c) 前版雖為 `fixed` 但 `fixedIn` 與本版不同（同批復發再修正，例如 `S1C-020` 模式）。
   - **修正事件強制驗證（`B2`）**：凡屬「修正事件」皆必須附帶合法 `reverseVerification`（`injectable` 或 `not_injectable`），且 `reverseVerification.fixTask` 必須等於該原因之 `fixedIn`；於 checkpoint 原即為 `fixed` 且 `fixedIn` 未變更之歷史原因（例如既已入庫且未復發改碼之原因）不追溯。
   - **只增不減不可變鎖定（`N2`）**：既有 `reverseVerification` 不得刪除、`injectable: true` 不得降級為 `false`、既有 `regressionTests` 必須維持為新版之子集合（只准追加、不得縮減，全程適用）；非「修正事件」（包含 `fixedIn` 未變更之 `fixed → fixed` 及重新開啟等非 `fixed` 狀態）時，已記錄之 `fixTask` 與三個輸出 SHA-256（`oldOutputSha256`／`newOutputSha256`／`mutantOutputSha256`）不得變更；僅於屬前述「修正事件」（前版非 `fixed` 轉為 `fixed`，或維持 `fixed` 但 `fixedIn` 改變）時，依 B2 視為新一輪驗證，可並須換為 `fixTask` 等於新 `fixedIn` 之合法 `reverseVerification`。

4. **52 列狀態轉移窮舉矩陣與規格前置要求（`TD-133`）**：
   - `scripts/tests/test_s1_registry_transitions.py` 以 `itertools.product` 窮舉 `PRIORS × CUR_STATUSES × CUR_RVS` 全部 52 個合法狀態轉移組合（0 mismatches）並涵蓋 6 個關鍵回歸情境，機械鎖定前述 D4／`N2` `check_monotonic` 規則。
   - 日後任何修改狀態轉移規則之驗證器批，開工寫程式前須先送 `SPEC_TABLES`（規格表）給第二意見短複核（見 `docs/ops/q2-draft-precheck.md`），並於該批同步更新規格表與窮舉測試。

## 六、runner S1 自動草稿契約（`scripts/s1_draft.py`／TD-101，β-2 擴充）

1. **只寫 `.git/` 未追蹤工作檔**：`batch_runner._execute_step` 於原 S1 落盤且印完 `S1_FULL_CAPTURE` 後，呼叫 `report_s1_draft`（委由 `s1_draft.create_s1_draft` 複用 `s1_evidence._create_once` 與 `_guarded_bytes`）寫入 `.git/<TASK_ID>-s1-draft.json`（create-once `O_EXCL`，拒絕覆寫或 symlink），絕不改動受追蹤檔案（含 `docs/governance/s1-registry.json`）。
2. **標準輸出與 `reply_check`**：成功寫入印 `S1_DRAFT_FILE=.git/<TASK_ID>-s1-draft.json sha256=<64-hex> bytes=<n>`；任何次要異常只印 `S1_DRAFT_STATUS=UNAVAILABLE`，絕不掩蓋原 S1。`reply_check.py` 只在步驟內已落盤 halted 回覆放行該兩者之一（0 或 1 筆），於成功或步驟前中止一律禁止。
3. **草稿 JSON 結構（`schema: 2` 候選）**：`schema=2`、`kind="S1_REGISTRY_DRAFT"`、`candidateOnly=true`、`id=null`、`title=null`、`status=null`（保留至審查官寫狀態批正式編 `S1C-nnn` 並補必填欄位，避免與 Dashboard 暫記撞號）、`tasks=[TASK_ID]`、`watch=["<step>:<CODE>"]`、`class="UNCLASSIFIED"`、`confirmed=false`、`by="runner"`、`verified={"by":"runner","date":"YYYY-MM-DD","basis":...}`、`evidence` 與 `evidenceDetail`。
