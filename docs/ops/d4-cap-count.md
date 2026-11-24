# D6 治理凍結與封頂條件②唯讀計數（`scripts/cap_count.py`／TD-008）

> 本文件定義 `scripts/cap_count.py` 之唯讀計數規則，由 `B117-BETA2-D4-CAP-S1DRAFT-R4-261124` 建立。

## 一、設計原則（嚴格唯讀、Fail-Closed 結構檢查、不以未入庫 S1 判 CI FAIL）

1. **只讀不寫不鎖**：所有 Git 查詢使用 `git --no-optional-locks -c core.fsmonitor=false`，隔離使用者全域與系統 Git 設定；預設（`--ref HEAD`）自工作樹讀取 `docs/TASKBOARD.md`、`docs/AUDIT-LOG.md`、`docs/EXEC-LOG.md`、`docs/governance/s1-registry.json` 以支援 `draft_precheck` 候選套用檢查，指定非 `HEAD` ref 或 `--from-git` 時則自 `git show <ref>:<rel>` 讀取；所有讀取拒絕 UTF-8 BOM 與 CR 換行。
2. **`source=repo` 與 Dashboard 邊界**：repo 僅能讀取已寫入 `docs/governance/s1-registry.json` 與 `docs/AUDIT-LOG.md` 之 S1；尚未寫進 repo 的 S1（例如剛在 W2 發生、暫存 Dashboard 之草稿或推定 S1）會使 `count_d6` 與 Dashboard 出現暫時差異。該差異由 Dashboard 並排比對提醒使用者與審查官，本工具於計算正確時**恆回傳 exit 0**，不在 CI 對合理雙源差異判 FAIL。
3. **Fail-Closed 條件**：僅於缺少或無法解析凍結行、`AUDIT-LOG.md` 主表欄位損壞或出現非 `--first-parent` 提交、`start_after` 或 `CAP2_ANCHOR_TASK` 無法確定錨定、或文件編碼含 BOM／CR 時，印出 `CAP_COUNT FAIL <CODE>` 並回傳 exit 1。

## 二、D6 治理凍結連勝計數（`count_d6`）

1. **解析凍結宣告**：逐字匹配 `docs/TASKBOARD.md` 唯一一行 `**治理凍結**：USER 2026-11-20 決定；連續無 S1 批數 n/20；最後歸零：<TASK_ID>（<REASON>）；起算：<START_AFTER>（不含）`；格式維持完全不變，確保 Dashboard 解析相容。
2. **確定性三段起算錨定**：自 `docs/AUDIT-LOG.md` 主檢查表（`## CI 歷史事故歸檔專區` 之前）定位 `start_after`：
   - 若 `start_after` 見於 `AUDIT-LOG` 某列 `i` 的目標批次，自下一列 `i + 1`（不含起算點）起算；
   - 否則於 `docs/governance/s1-registry.json` 查詢 `start_after` 對應修復提交 `fixedCommit` 所在列 `j`，自該修復批 `j`（含，即歸零後首個乾淨批）起算；若修正晚數批才落地，中間之乾淨批會保守略過；
   - 再否則於 `docs/EXEC-LOG.md` 查得最早提及 `start_after` 之列與其 `base_oid`，找出 parent 等於該 `base_oid` 之 `AUDIT-LOG` 列 `k` 起算；三者皆無則以 `START_AFTER_UNRESOLVED` fail-closed。
3. **系列歸併、未進 `main` S1 與計數（`B1`）**：只計非只讀批；除比較本列 `TASK_ID`（或其 `PROMOTE-` 變體）與列內 `CAP_RESET=S1:<TASK_ID>` 外，計數窗內每列皆比對該提交與其 parent 之 `s1-registry.json` `tasks` 差集，另比對最後稽核列至目標 ref／工作樹之未進 `main` 新登記 S1（不含已入主表者與 `start_after`）；當 parent 尚無登記檔（首次匯入點如 `4a401422`）時，僅計入順序／日期嚴格晚於 `start_after` 者，歷史既有 25 筆不誤判歸零。凡於該列新增未進 `main` S1 者，於計數該列前先將連勝歸零，使登記該 S1 之乾淨批從 `1` 起算；否則僅 `POST-MAIN VERIFIED` 列加一（未完成者不計），並查驗所有計數列皆在目標 ref 的 `--first-parent` 鏈上。若計數窗內最後一次歸零 `TASK_ID` 與凍結行「最後歸零」不同，`match` 維持 `NO` 並附 `reset_mismatch=declared:<X>,observed:<Y>`（仍回傳 exit 0）。

## 三、封頂條件②產品批連勝計數（`count_cap2`）

1. **起點與產品批定義**：自 `CAP2_ANCHOR_TASK`（`B117-G5-BRANCH-MATCH-R4-261115`）所在提交之後，沿目標 ref 的 `git rev-list --first-parent --reverse <anchor>..<ref>` 逐個單親提交檢查 `git diff --name-only --no-renames <parent> <commit>`；僅當異動路徑包含 `runtime/`、`skills/`、`SOP/`、`shared/` 或 `templates/` 前綴之一時認定為產品批（並由該提交之 `docs/governance/execution-record.json` 或 `AUDIT-LOG.md` 解析 `task_id`）。
2. **`CAP_RESET` 標記**：掃描 `docs/AUDIT-LOG.md` 錨點列之後主表列的 `CAP_RESET=(ERROR_INTO_MAIN|S1|MANUAL_REMEDIATION|PATCH_BATCH):<TASK_ID>`；若目標為非產品批，記錄於 `resets_ignored_non_product` 且不影響連勝數；若目標為產品批（含 `PATCH_BATCH` 補丁批本身），該批將連勝歸零且不計入新一輪。

## 四、命令列與固定輸出行

```text
python scripts/cap_count.py --repo <repo> [--ref HEAD] [--mode all|d6|cap2] [--from-git] [--json]
```

標準文字輸出固定為：

- `CAP_COUNT_D6 source=repo count=<n> target=<N> declared=<d> match=<YES|NO> last_reset=<TASK_ID> start_after=<TASK_ID>[ reset_mismatch=declared:<X>,observed:<Y>]`
- `CAP_COUNT_CAP2 source=repo count=<n> target=20 anchor=<40-hex> product_batches=<k> resets=<r>`
