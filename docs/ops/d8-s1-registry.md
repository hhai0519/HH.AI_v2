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
