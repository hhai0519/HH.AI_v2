# 單一命令 run 與續跑協定（B117-G5B2-RUN-ONLY-R2-261116 起適用）

本文件是 Executor 命令、固定輸出行、續跑與人工處置的唯一說明；提示詞的第五節（production）或第四節（promotion）只複述其中 Executor 需要的部分。程式與測試為準，本文件與其不符時以程式為準並須修正本文件。

## 1. 命令

提示詞只列兩個命令，且兩者都只能以提示詞原文執行：

- `run`：依序執行本批所有尚未完成的步驟（含最後的 timing 與回覆），每個步驟只執行一次，用作業系統檔案鎖防止兩個 run 同時執行。步驟邏輯、紀錄、S1 處理與回覆組裝與逐步命令相同，每一步仍在獨立行程執行。
- `resume-check`：唯讀，只印一行 `RESUME_CHECK STATE=… NEXT=… DONE=… HALTED=… LOCK=…`，不建立或修改任何檔案。

逐步命令（`preflight`、`setup`、`apply` 等）仍存在，只供審查官在人工復原時明確指示使用，Executor 不得自行使用。逐步命令不檢查 run 的鎖，所以 run 執行中不得同時執行任何逐步命令。

## 2. 結果只看固定行，不看 exit code

`RUN_REFUSED` 的 exit code 是 2，與既有 `S1 USAGE` 相同，所以判斷一律以印出的固定行為準：

| 固定行 | 意義 | Executor 動作 |
| --- | --- | --- |
| `RUN_END STATE=COMPLETE TIMING_RC=<rc>` | 所有步驟完成並已呼叫 timing（不含 PASS 字樣，結果以回覆區塊的 `REPLY_SELF_CHECK` 為準） | 依提示詞回覆節回覆，結束 |
| `RUN_STOPPED CODE=RUNNER_UPDATED NEXT=<步驟>` | 本批更新了 runner，正常停點 | 再執行一次相同的 run（只准一次） |
| `RUN_STOPPED STEP=<步驟> RC=<rc>` | 步驟失敗，該步驟已自行印出 S1 與回覆 | 停止，依回覆節回覆 |
| `RUN_STOPPED CODE=GIT_IDLE_CHANGED` 或 `GIT_IDLE_CHECK_FAILED` | 第 5 節的閒置檢查未通過，尚未建立 control，未做任何修改 | 停止並回報，不重跑 |
| 其他任何 `RUN_STOPPED`、`RUN_REFUSED`、`RUN_INTERRUPTED`、`S1` 行 | 需要人處理 | 停止並回報原始輸出，不重跑 |

`RUN_STOPPED STATE=COMPLETE|HALTED … CODE=REPLY_NOT_REPEATED` 表示任務在這次 run 開始時就已結束，回覆（TIMING 或 EXECUTOR_REPLY_UNAVAILABLE）在先前的輸出中，timing 是一次性的，不會再印。

## 3. 續跑（命令中斷時）

只有在命令沒有印出第 2 節任何固定行就結束或被中斷（逾時、斷線、視窗關閉），或已執行約 4 小時仍沒有印出其中任何一行時（IDE 可能把已結束的命令一直顯示為執行中，見第 7 節），Executor 才執行一次 `resume-check`，依 STATE：

| STATE | 意義 | 動作 |
| --- | --- | --- |
| `NOT_STARTED`、`RESUMABLE` | 沒有 run 在執行，下一個步驟尚未開始 | 再執行一次 run（這種情形只准一次） |
| `RUNNING` | 有 run 持有鎖（執行滿約 4 小時的情形，可能是本命令自己仍在執行） | 停止並回報，不得中止該 run |
| `INTERRUPTED` | 下一個步驟已開始卻沒有完成標記，可能已改動工作區或遠端，也可能仍在執行 | 停止並回報，絕不自動重做 |
| `PREVIOUS_STEP_UNCONFIRMED` | 最後一個已完成步驟的紀錄不以 result=0 的完成標記結尾 | 停止並回報 |
| `COMPLETE`、`HALTED` | 任務已結束，回覆應已在先前輸出 | 停止並回報原始輸出；若已擷取的輸出中沒有回覆（IDE 輸出遺失），由 USER 以唯讀方式讀取 `.git/<TASK_ID>-executor-reply.txt`（只在回覆自檢通過後才寫出，不存在表示走了 `EXECUTOR_REPLY_UNAVAILABLE` 備援）貼給審查官，或請審查官人工處置 |
| 其他（`BINDING_DRIFT`、`CONTROL_INCONSISTENT`、`UNKNOWN_LOCK`、`UNAVAILABLE`） | 綁定或紀錄不一致 | 停止並回報 |

## 4. 審查官與 USER 的人工處置注意事項

這些來自第二意見對 run 的觀察（G5-b1 紀錄 O-1 至 O-9），審查官處置如下：

- O-1：Windows 在行程被終止後釋放鎖可能延遲數秒。看到 `RUNNING` 或 `RUN_ALREADY_ACTIVE` 時，人工處置前先等約 30 秒再查一次，不得僅憑第一次的結果就判定另有 run 在執行或沒有。
- O-2：父行程被終止、子步驟仍在執行時，`resume-check` 會報 `INTERRUPTED` 且 `LOCK=FREE`。`INTERRUPTED` 的意義是「步驟已開始、沒有完成標記」，不是「已停止」；任何人工處置前必須先確認沒有 runner 行程存活（Windows 以工作管理員或 `Get-Process` 查 python 行程）。
- O-3：`resume-check` 探測鎖時會短暫取鎖（POSIX 為整檔鎖，Windows 鎖檔案尾端之後的一個位元組），該瞬間同時啟動的 run 會被拒絕，這是安全方向；Executor 看到被拒絕時依第 2 節停止並回報即可。
- O-5：逐步命令不檢查 run 的鎖，所以只有審查官明確指示時才可使用，且須先確認沒有 run 在執行。
- O-8：前景 Ctrl+C 時子步驟比逐步執行更快被強制結束，判定結果仍是 `INTERRUPTED`。
- O-9：模板以固定行判斷，不以 exit code 判斷（第 2 節）。
- O-4：更新 runner 的批次（`runner_update`）在 apply 階段替換 runner 檔，父行程仍是舊版程式，所以 run 在替換 runner 檔的步驟之後以 `RUN_STOPPED CODE=RUNNER_UPDATED` 停止，再執行一次相同的 run 即由新版 runner 續跑；這個停止只在 `runner_update` 為 true 的批次出現，且 runner 檔位元組必須真的改變。
- O-6、O-7：子行程在 UTF-8 模式沒有行為差異；`batch_sim` 的 S1 允許字彙隨 runner 新增常數變寬，不影響判定。

## 5. Git 閒置檢查（原 PRESTART 區塊 C）

宣告 `native_preview` 為 true 的 production，`run` 在第一個步驟之前（任務尚未開始時）取得鎖、印出 `RUN_IDLE_CHECK seconds=210`，等 210 秒後比對工作區所有檔案與目錄（包含 `.git`，不含本任務自己的 `.git/<TASK_ID>-` 檔案）的模式、大小與時間戳記，無變動才印 `GIT_IDLE_OK` 並繼續；有變動印 `GIT_IDLE_CHANGED`、無法讀取印 `GIT_IDLE_CHECK_FAILED`，並以 `RUN_STOPPED CODE=…` 停止（exit code 6），此時尚未建立 control，也沒有任何修改。批次模擬（`HHAI_BATCH_SIM_ROOT` 的模擬工作樹）不等待。已開始的任務（control 已存在）續跑時不再等待。`delivery_pack` 的 PRESTART 不再含區塊 C。

說明（G5-b2 第二意見 O-1 至 O-4）：

- 「不含本任務自己的檔案」只對原地改寫有效；建立或刪除檔案仍會改變 `.git` 目錄本身的時間戳記。run 在 210 秒內不建立任何檔案（鎖檔在快照之前已建立），所以不影響判定。
- 一般 `git status`（會更新 index）、存檔、切換分支或開啟原始檔控制面板，在這 210 秒內都會造成 `GIT_IDLE_CHANGED`（安全方向：停止、未改任何檔）。舊區塊 C 同樣如此，但當時 Executor 尚未啟動；現在檢查發生在 Executor 啟動之後，所以 PRESTART 要求 USER 在 Executor 啟動後約 4 分鐘內不要操作 IDE。
- Windows 上 Python 3.14 的 `st_ctime_ns` 仍是建立時間（官方文件說明未來會改為中繼資料變更時間），只抓得到檔案重建，抓不到純屬性變更；舊區塊 C 相同，沒有放寬。
- UNKNOWN：Antigravity 的原始檔控制整合是否在這段時間自行執行一般 git 命令，待第一個以 run 執行的真實批次觀察。

## 6. 額度

啟動第一個命令之前，若 IDE 顯示額度或權限不足以完成一次命令與回覆，不要啟動，直接回報（此時尚未修改任何檔案）。run 啟動後，額度消耗只剩這一次命令與回覆，不得為省額度而中途停止或另行補救，一律依第 2、3 節處理。

## 7. UNKNOWN 與備援

- UNKNOWN：Antigravity IDE 對長達約兩小時的單一命令的行為（逾時、輸出擷取、是否在 IDE 逾時後殺掉行程）尚未實測。備援是第 3 節的 `resume-check` 加再執行一次 `run`：命令被中斷時，若 run 與其子步驟都被終止，`resume-check` 報 `INTERRUPTED`（步驟已開始）或 `RESUMABLE`（在兩個步驟之間）；前者需審查官處置，後者可續跑。審查官在第一個以 run 執行的真實批次完成後，依 Executor 回報的實際行為更新本節。
- 已知的 IDE 問題（第二意見 N-4，Antigravity 論壇）：已結束的命令，`command_status` 可能一直顯示 RUNNING，終端機輸出也讀不到。處置見第 3 節：約 4 小時仍沒有印出任何固定行才執行一次 `resume-check`；`RUNNING` 就停止並回報，不得中止 run；`COMPLETE` 而回覆不在已擷取的輸出中時，由 USER 讀取 `executor-reply.txt`。本批預期 production 約 95 分鐘，遠低於 4 小時。
- 第 4 關（PRECOMMIT）耗時約 38 至 53 分鐘（實測 2262 至 3176 秒），是 run 內最長的單一步驟，其逾時由 runner 自己的 bounded process 管理，與 IDE 的命令逾時無關。

## 8. 測試與證據

位置判定、續跑、鎖、符號連結、中斷、主程式分派與 RUNNER_UPDATED、閒置檢查的測試在 `scripts/tests/test_batch_runner.py`（名稱含 `test_g5b_` 與 `test_g5b2_`）；以 run 演練的批次模擬與日誌格式在 `scripts/tests/test_batch_sim.py`、`scripts/tests/test_native_preview.py`；命令清單與固定文字在 `scripts/tests/test_prompt_builder.py`；PRESTART 在 `scripts/tests/test_delivery_pack.py`。
