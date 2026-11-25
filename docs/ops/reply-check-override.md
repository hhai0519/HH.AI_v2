# `reply_check.py` FAIL 之人工對照放行暫行規則（過渡至機械化前）

> 本文件補齊 `B117-BETA2-D4-CAP-S1DRAFT-R4-261124` 晉級後之流程缺口檢討：
> 在 `reply_check.py` 轉抄漂移機械化（`TD-132`，D6（四）治理凍結期間只登錄）落地前，明確規範審查官面對
> `reply_check.py` 回傳失敗時，何種情形嚴禁放行、以及極少數純形式轉抄筆誤得採人工對照驗證之全部必要條件。

---

## 一、適用前提（Fail-Closed 原則）

1. 預設情況下，`scripts/reply_check.py` 任何非零退出碼一律視為**候選不可憑回覆放行**，不得僅憑口頭說明推定 PASS。
2. 本暫行規則**不適用於以下任一情形**（一律退回查明或停機）：
   - 出現任何 S1 代碼或缺失必要步驟／結果行；
   - `COMMIT`／`MAIN`／`MAIN_PROMOTED` 40 位元組 SHA 不符；
   - Candidate 或 Post-Main GitHub Actions Run 不存在、尚在執行、結論非 `success`、`head_sha` 不符或 `raw log` 未經審查官親讀；
   - 無法以 Git、GitHub API 與唯讀工作區產物證明實際執行無誤。

---

## 二、唯得採人工交叉對照放行之全部條件

僅當失敗原因局限於「Executor 聊天介面轉抄形式誤差」（例如分支名稱大小寫或排版字元差），且同時滿足下列五項實證條件時，審查官始得在保留逐字原件不改的前提下判定為非阻擋形式瑕疵（不屬 S1、不歸零 D6）：

1. **逐字原件留痕**：完整保存未經修改之聊天逐字回覆原件與 `reply_check.py` 原始失敗碼，不得修改原件以求通過。
2. **單點最小對照測試**：以暫存控制複本僅修正該明確筆誤字元，驗證 `scripts/reply_check.py` 其餘全部欄位回傳 `REPLY_CHECK RESULT=PASS`。
3. **來源唯讀分離鑑定**：條件允許時，以唯讀方式查核 W2 工作區 `.git/<TASK_ID>-executor-reply.txt` 與 `step-*.out` 原始檔案雜湊及字面值，區分究竟為 runner 輸出缺陷或 Executor 轉抄誤差；若確認屬 runner 本身缺陷，不得歸類為單純轉抄。
4. **獨立遠端真值雙向確認**：透過 `git ls-remote origin`、GitHub API 與 `tools/gh_actions_ro.py` 取得 Candidate／Post-Main `run_id`、`head_branch`、`head_sha`、`conclusion=success` 及雙 job 原始日誌全文，確認實際執行結果為 exact-SHA 通過。
5. **透明揭露與登錄追蹤**：於當輪驗收報告第一、二層與次批狀態列（`AUDIT-LOG`／`TODO-LEDGER`）完整揭露原件失敗碼、對照結果、來源查證 SHA-256 與後續追蹤編號（`TD-132`）。
