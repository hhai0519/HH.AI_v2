# G5 Windows 原生預演

- 一般受影響的 production 批依序執行 preflight → native_preview → setup。缺失、超時、非零退出或證據不完整即 S1 STOP。後續正式 production 原有檢查照跑。
- 預演讀取 exact Base，僅在 %TEMP% 建立隔離 clone 與本批日誌。W2 只留下 task-local runner 證據。預演前後比對符號 HEAD、refs、packed refs、FETCH_HEAD、index、tracked 位元組與整樹 lstat（包含 ignored 路徑）。比對器的 Git 子程序關閉 optional locks，Python 禁止寫 bytecode。
- 首批由 USER 在 Windows PowerShell 5.1 執行 repo 工具產生的 bootstrap。工具以最終 patch 與 prompt 雜湊綁定輸入，在隔離 clone 完成 production 模擬與 G5 定向測試。以 ONE_TIME_BOOTSTRAP_PASS、receipt 雜湊及兩份原始日誌接受獨立審查。

## S1 BASE_NOT_IN_SOURCE

此停止碼屬環境前置不足，發生於 setup 前。若來源快照比對另有漂移，優先報來源變更，不使用此分類。

Executor 立即停止，保留本批 .git 證據和 %TEMP% 目錄，將 runner 原始停止輸出交給 USER 轉交審查官。不得在 W2 fetch 或重試。審查官重新查證遠端 exact Base，核對本次來源與證據。若需重建來源，由 USER 在新的獨立路徑準備完整 clone 並核對 Base 物件與 SHA。審查官確認可重建後，才為新工作區交付重新綁定的開始方式。現有 W2 與已停止 control 保留供追查。

## S1 NATIVE_PREVIEW_UV_CACHE_INVALID／NATIVE_PREVIEW_UV_CACHE_INCOMPLETE

前者表示核准快取路徑不存在、不是目錄、不是絕對路徑或與 W2 重疊；後者表示快取不足以離線滿足 Base 的 lock（缺套件、uv 不可用、逾時）。兩者在 preflight 或預演開頭停止，尚未建立 TEMP 證據目錄，W2 與 Base 皆未被模擬。Executor 立即停止，不得自行尋找、建立、複製或補齊快取，不得改用預設快取或其他路徑，回報原始停止輸出給 USER 轉交審查官。審查官唯讀確認快取，由 USER 依審查官指示修復快取（USER-only），再由審查官交付重新綁定的開始方式。

## 首批 bootstrap 執行方式（R2／R3 補充）

- 必須在 powershell.exe（Windows PowerShell 5.1）主控台執行，不可用 ISE。ISE 會把 git 的 stderr 當成錯誤，在 Stop 模式下中止。
- Windows 用戶端的預設 ExecutionPolicy 不允許直接執行 `.\*.ps1`，且不得為此修改 ExecutionPolicy。審查官交付時附 inline 啟動區塊：先核對 ps1 的 SHA-256（轉小寫比對），再以 `& ([ScriptBlock]::Create([IO.File]::ReadAllText($ps1))) -W2 <W2> -InputDir <InputDir>` 執行，不需更動 policy。核准的 uv 快取路徑由工具內建（見下方 uv 離線快取），USER 不需輸入；目錄不存在即 BOOTSTRAP_UV_CACHE_MISSING。成功時另印出 `BOOTSTRAP_SIM_PYTHON home=… version_info=…`（模擬 venv 實際使用的 Python，讀自其 pyvenv.cfg，並收入 evidence ZIP 的 sim-pyvenv.cfg），作為 B-117 的觀察證據。
- 預演與 bootstrap 期間，W2 不得有其他 git 程序。請關閉開著 W2 的 IDE 視窗，或關閉 IDE 對 W2 的 git 自動刷新。一般 `git status` 會刷新 index，使快照比對以 NATIVE_PREVIEW_SOURCE_MODIFIED 停止（fail-closed，W2 未被修改，但浪費一輪）。
- uv 離線快取：模擬隔離 HOME，且以 `--offline` 執行 `uv sync`，只使用核准快取、不下載。uv 會把自己的中繼資料（例如 interpreter 資訊與 `.lock`）寫入該快取，實測一次 dry-run 即新增一項；這項寫入尚未在 contract 宣告，已登記為 N-1（第一次由 Executor 執行預演之前必須處理：contract 宣告、模擬的 uv sync 加 UV_LINK_MODE=copy）。預演不使用 Windows 預設快取 `%LOCALAPPDATA%\uv\cache`：它不是核准快取，可能缺少 lock 所需的 wheel，離線時模擬在準備 uv 時以 UV_SIM_SYNC_FAILED 停止（R2 首次原生執行即因未傳核准快取，約 16 秒後以 NATIVE_PREVIEW_NONZERO 停止）。核准快取只記錄在 `scripts/native_preview.py` 的常數 `APPROVED_UV_CACHE_DIR`（本機為 `C:\Users\HH.AI_260806\hhai-toolchain\uv-cache`，即 TASKBOARD 記載的 USER S4 `--cache-dir`）。不使用環境變數，也不沿用 UV_CACHE_DIR：USER 常設規定 Antigravity IDE 只以 `C:\Users\HH.AI_260806\AppData\Local\Programs\Antigravity IDE\Antigravity IDE.exe` 開啟，不經 `hhai-toolchain\start-antigravity-hhai.cmd`，launcher 設定的變數不會進入 Executor。更換機器或路徑須以經審查的程式批修改該常數。
- 快取檢查（runner 在 preflight 檢查，預演開頭再檢查一次，皆在建立任何 TEMP 證據目錄之前）：路徑必須是存在的絕對目錄，不得等於、包含或位於 W2 之內，否則 NATIVE_PREVIEW_UV_CACHE_INVALID；再於拋棄式暫存目錄放入 Base 的 pyproject.toml、uv.lock、.python-version，以 `uv --no-config sync --locked --offline --no-python-downloads --python <pin> --dry-run` 對該快取試算。dry-run 即使缺套件也回傳 0，所以輸出含 `Would download` 一行，或 uv 缺席、非零、逾時，皆為 NATIVE_PREVIEW_UV_CACHE_INCOMPLETE。W2 本身不交給 uv，只以 git blob 讀取三個檔案。
- 啟動方式：`hhai-toolchain\start-antigravity-hhai.cmd` 不是 Executor 的啟動方式，不得引用；該檔維持原狀，刪除前須與 USER 討論。
- 每個修改程式的 production 都會先完整跑一次原生模擬。Executor 回報實測耗時，審查官登錄於 TASKBOARD B-117 觀察。
- 內層遞迴略過的端到端驗證：本批 Base 尚無 native_preview，模擬內層不走預演路徑。下一個程式批（Base 已含 G5，prompt 為 native_preview=true）的 E27 須在 Linux D2 log 看到 `BATCH_SIM STEP native_preview rc=0`。
