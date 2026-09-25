# 規則：Git 操作與回報紀律

這是一條 workspace 規則，Antigravity 在本專案內執行任何任務時都會載入。
以下規範是專案進行過程中累積出來的實務教訓，每一條都對應到實際發生過的
問題，請確實遵守。

## 1. Git 操作

- **絕對禁止 `git add -A` 或 `git add .`**：一律明確指定檔案路徑
  （例如 `git add skills/platform/postgres/SKILL.md`）。
  原因：曾發生本機殘留的 `run.js` 被 `git add -A` 夾帶進一個完全不相關的
  commit，直到後續審計才被發現。
- **絕對禁止 `git commit --amend`**：需要修正已 commit 的內容時，一律用
  新增一個 commit 的方式處理。
- **絕對禁止 `git push --force` 或 `--force-with-lease`**：不覆寫遠端歷史。
  原因：完整的歷史紀錄是回溯問題發生在哪一步的唯一依據。
- **commit 前先跑 `git status`**：確認 staged 清單只包含本次任務實際要
  修改的檔案。
- **建立 prospective commit 前確認交接區 HEAD**：若該批次包含交接區元資料更新，確認 `docs/refactor-backlog.md` §5.1 的「上次核對通過的 HEAD」等於 `docs/AUDIT-LOG.md` 中最新且屬當前歷史之 Macro PASS checkpoint。它可以是 HEAD 的較早 ancestor；存在多個 pending repair commits 本身不構成錯誤，不得以 ancestry distance 判定 audit state 過期。候選 commit 自身若未經 Macro Auditor 裁決 PASS，絕對不得自稱為 checkpoint。可使用 `python scripts/check_consistency.py --as-if-committed` 於 commit 前預演驗證，消除本地與 CI 差 1 的可預測中間紅燈（B-51）。
- **commit message 內若含 `$$` 字元，訊息要用單引號包住**，避免被 shell
  展開成進程 ID。
- **分支建立與切換操作慣例（Branch Operation Convention — B-109 M1）**：
  - 建立新分支一律使用：`git switch -c <new-branch>`
  - 切換既有分支一律使用：`git switch <existing-branch>`
  - 嚴禁正常 workflow 使用 legacy checkout-family 指令建立或切換分支（policy registry、baseline 與 REG fixture 仍可保存該 legacy command 字串作為靜態比對資料）。
  - `git switch -C` 與 `git switch --discard-changes` 具破壞性與狀態丟棄語意，列為嚴格禁止之破壞性操作（destructive Git）。
- **主要分支晉級機械守衛（Main Advancement Exact-SHA Guard）**：
  - 任何對 `refs/heads/main` 的推送更新，必須具備 `.git/` 單次 exact-SHA 授權（`MAIN_EXACT_SHA`）。
  - 推送之 new SHA 必須完全等於 `authorized_main_sha`，且 remote current SHA 等於 `expected_remote_main_sha`。
  - `refs/heads/main` 之遠端刪除永遠禁止。
- **遠端分支刪除精確集合守衛（Remote Delete Exact-Set Guard）**：
  - 任何遠端分支刪除（包含 `--delete` 與 deletion refspec）必須具備 `.git/` 單次 exact-set 授權（`REMOTE_DELETE_EXACT_SET`）。
  - 刪除分支集合必須與授權集合完全一致（不多、不少、SHA 無 drift）。
  - 嚴禁授權或執行刪除 `refs/heads/main`。
- **Hook 繞過防護（Hook Bypass Forbidden — GOV-M1-011）**：
  - 嚴禁使用 `git push --no-verify` 或 `git commit --no-verify`。
  - 嚴禁修改本地 `core.hooksPath` 以繞過守衛。
  - 嚴禁暫時更名、編輯或移除 `.githooks/` 腳本。
  - 嚴禁使用替代 Git binary 刻意繞過 hook。
  - 防護強度為 PARTIAL（repo hook 無法物理阻止刻意使用外部手段繞過之 actor）。
- **K1-A / C-06 Transport-Neutral Exact-SHA Contract（Protected Main Invariant）**：
  在 GitHub Gate 保護下，生產作業採行 Transport-Neutral Exact-SHA 傳輸架構，絕對禁止未經 exact-SHA 驗證之直推或 force push。
  K1 main advancement 核心不變量如下：
  1. candidate 為完整 exact 40-char commit SHA，以 exact base 開設 `batch/**` 分支，change commit 必須存在於 `batch/**` 分支。
  2. push batch branch 後取得 candidate exact SHA 之 push Actions runs，required contexts（`verify`、`gateway-windows`）兩者皆 completed/success，且 verify raw log 須為 `ALL 5 GATES PASSED`。
  3. 更新 main 前重新確認 `origin/main` 等於 base SHA 且為 candidate 之 ancestor；若 main drift 立即 STOP，進位必須為 pure fast-forward，禁 rebase 沿用舊 checks。
  4. 每批必須明確宣告並選擇 exactly one 可用之 transport adapter（例如 approved connector `update_ref`，或經授權之 native pinned full-40-char SHA refspec `<FULL40_SHA>:refs/heads/main`）。adapter 僅為傳輸機制而非正確性權威；選定 adapter 不可用或被拒絕時一律 STOP / S1，禁止 silent fallback。
  5. 嚴禁 force push、`--force-with-lease`、`force=true`、`+` refspec、rebase/cherry-pick/squash after check，確保 main 接收 SAME SHA。
  6. main 更新後 `origin/main` 精確等於 candidate checked SHA。
  7. 等候 post-main `event = push, head_branch = main, head_sha = same candidate SHA` 之 Actions runs，`verify` 與 `gateway-windows` 必須再次成功。
  8. 絕不繞過保護規則（Never bypass protection），嚴禁新增 bypass actor。
  9. 遠端健康權威始終為：exact origin/main SHA ＋ exact-SHA GitHub Actions Verify 成功。
- **實際變更機械重放與執行紀錄（Plan-vs-Actual & Exact Diff Replay — B-109 M2）**：
  - commit 前由 `scripts/execution_record.py verify` 機械驗證 fresh git diff 嚴格落入 allowed scope 且必改路徑無缺漏。
  - 完成前將執行紀錄落地至 `docs/governance/execution-record.json`；CI CHECK 26 依 `base_oid..HEAD` 機械重放 diff 查驗一致性。
- **候選提交治理凍結不變量**：候選提交開始執行 required check 後裁判表面嚴格凍結，詳見 [.agents/rules/governance-gate-integrity.md](./governance-gate-integrity.md)。

## 2. 回報紀律

- **正式回報通道為 Repo，非對話視窗（B-36 唯一現行規範）**：
  版本庫（Git commit、`docs/EXEC-LOG.md` 與 GitHub Actions）為本專案單一事實來源與客觀證據通道（Evidence Channel），對話視窗僅作為狀態通知與決策通道（Notification / Decision Channel）。

  **正常成功批次（Default Success Reporting）**：
  所有詳細的機器證據——包括前置檢查（preflight）、實際變更檔案（changed paths）、測試與驗證結果（`verify_all.py` 各 Gate 輸出）、M1-M3 自主修復歷程、遠端 CI 查核結果與任何例外說明——**一律完整寫入 `docs/EXEC-LOG.md`**，並由 Git commit 與 GitHub Actions 永久保留。
  **對話回覆預設採用單行格式**：
  `COMMIT <full-sha> | CI PASS | S1 NONE`
  （最多再附加一行非常短的必要例外摘要）。
  **嚴禁在對話中預設貼出**：完整終端機輸出、完整檔案內容、逐行行號 dump、檔案總行數 dump、raw git diff、長篇 walkthrough 或大型 completion report，杜絕 context 膨脹與 token 浪費。

  **S1 升級回報格式**：
  若遇到真正需要審計官或使用者決策的 S1 阻擋事項，對話回覆僅需提供：
  `S1 <簡短分類> | evidence location / blocker`
  並附加最小必要的 consolidated S1 report。

  **貼出原始片段的特許例外**（僅在以下情況才允許於對話貼出片段）：
  1. GitHub 遠端服務異常導致 remote evidence 不可取得。
  2. 宏觀審計官於提示詞明確要求特定 raw evidence。
  3. 尚未執行 push 且處於本地阻塞狀態。
  即使例外，亦僅貼最小必要片段，不得恢復全檔或 raw diff。

- **「等我核對後再 commit」就是真的不要 commit**：使用者明確要求停下來
  等核對時，不得先行執行 commit 或 push。
- **回報的狀態必須與實際執行的動作一致**：如果因任何原因已經執行了不該
  執行的動作，必須在回報的**第一句話**明確說明實際狀態，不得在結尾才補述，
  更不得同時聲稱「等待核准」。
- **未查證的事實不得推測或填補，不得編造沒有根據的內容**（例如工具名稱、檔案路徑、設定值）。
- **面對不確定性（uncertainty）先經 `.agents/rules/role-boundaries.md` §7 錯誤路由**：能由機器重新推導（M1）、環境暫態重試/回退（M2）、或 Allowed Scope 內自主修復（M3）的，一律自主閉環處理，不得隨意要求宏觀審計官或使用者確認。
- **只有真正遇到未授權之 S1 阻擋事項時才停機回報**：格式嚴格採用 `S1 <簡短分類> | evidence location / blocker`。

### 2.0 歷史教訓與已退役之舊回報機制（Historical Rationale / Retired Reporting Mechanism）

以下條目為早期針對虛構回報設計之過渡手段。**這些機制（口頭貼全文、行號、總行數、raw diff、指令輸出等）已全面由 B-36（Repo Evidence Channel ＋ Actions 遠端健康權威）正式取代，退役為歷史留痕，不得作現行對話回報要求**。保留其背景用以說明現代架構建立版本庫機器證據鏈之必要：

- **[已退役] 不接受只回報「已完成」**：早期曾因缺乏客觀機器證據要求口頭貼出內容與 staged 清單；現行由 `docs/EXEC-LOG.md`、Git commit 與 GitHub Actions 自動化保留客觀證據。
- **[已退役] 回報檔案內容附行號與總行數**：早期曾為防範虛構回報（如 2026-08-29 `PRINCIPLES.md` §4.2 事件與 2026-09-01 重整版本事件）要求腳本讀檔附行號與總行數；現行已全面由版本庫客觀證據與自動化閘門接管。
- **[已退役] 貼出原始 git diff**：早期曾用於防止局部虛構，現已由 GitHub CI 與標準驗證流程接管。讀檔或 diff 失敗時誠實回報，嚴禁憑記憶填補。

## 2.1 撰寫測試時，依規格而非依實作

寫測試時，斷言的依據是**提示詞或規格所描述的行為**，
不是「現有程式碼實際做了什麼」。

若測試跑起來失敗，先確認是實作錯還是規格錯，**回報給審計官判斷**，
不要為了讓測試通過而修改斷言。

**失效紀錄**：2026-09-04 為 `check_consistency.py` 的 CHECK 8-15
新增 22 個測試，全部通過。但審計官獨立做反例測試後發現
**CHECK 12 與 CHECK 15 抓不到它們本來要抓的違規**——
測試是照著錯誤的實作寫的，因此驗證了「程式做了它做的事」，
而非「程式做了它該做的事」。

這是測試最典型的失效模式，且比沒有測試更危險：
**沒有測試時大家會保持懷疑，有了綠燈就不會了。**

## 2.2 提示詞指定的寫入內容，逐字照抄

「整段替換為」「插入以下內容」的文字是**逐字指定**的，不是參考範例。
不得改寫、潤飾、補充、精簡。

若你認為內容有誤或與事實不符，依
`.agents/rules/prompt-preflight.md` §3.3 當成【疑問】回報，
**不要自行修正後寫入**。

**失效紀錄**：2026-09-04 交接區 §5.1 的兩個項目符號被改寫，
且改寫後與事實不符——把「6 檔異動」寫成「3 改 0 新檔」、
把「驗證三項」寫成「驗證四項」。
錯誤的事實因此進入 repo，會被未來的接手者當成紀錄讀。

**寫入後必須驗證**：每完成一個替換或插入，
立刻用 `t.count(指定的新內容)` 確認為 1。為 0 即代表寫入內容與指令不符。
規則見 `prompt-preflight.md` §4.1。

## 2.3 [已退役] commit 與 push 的狀態，早期以指令輸出為準

> **現行規範**：本機制已由 B-36 與 §2.5 正式取代。遠端狀態一律由 exact origin/main OID 與 Actions 狀態為客觀憑證並記錄於 `docs/EXEC-LOG.md`，禁止對話貼指令輸出或文字摘要辯論。

以下保留 2026-09-05 歷史事故記錄：

回報 commit 或 push 是否執行時，早期曾要求不得以敘述代替，必須貼出三條指令的實際輸出：

    git log -1 --format=%h
    git rev-parse --short origin/main
    git status --porcelain

判準：

- 兩個 hash **相同** → 已 commit 且已 push
- 本機 hash **超前** → 已 commit 但未 push
- 兩者相同但 `git status --porcelain` **有輸出** → 工作區有未提交的修改

**同樣適用於「我回滾了」的宣告**：執行 `git restore` 或 `git checkout --`
之後，必須貼出 `git status --porcelain` 證明工作區真的乾淨。

**失效紀錄**：2026-09-05 連續兩輪發生。第一輪回報「本批次未執行 commit 與 push」，
但遠端 HEAD 確為該批 commit、訊息完全相同、五項修改全數進版控。
第二輪回報某段文字是交接區 §5.1 的實際內容，
而審計官於遠端 clone 實測該字串 `count=0`——那段只存在於本機工作區。

**這是回報與實際不符的第五類：動作狀態虛構。**
前四類虛構的是檔案內容、行數與上下文行，會在審計官 clone 核對時被抓到；
**動作狀態虛構若不主動查 `git log` 就看不見**。

## 2.4 提交前機密檢查與 Git Hook 守衛規範 (Secret Commit Guard & Hook Protocol)

所有 Agent 在執行 `git commit` 前，必須落實機密資訊提交前防護：
1. **禁止繞過 Hook 驗證**：嚴禁使用 `git commit --no-verify`，嚴禁暫時移除或繞過 Hook，嚴禁因掃描報錯而擅自弱化偵測器。
2. **Hook 安裝狀態查驗**：提交前必須確保本地 Git hook 處於啟用狀態：
   ```bash
   python scripts/install_git_hooks.py --check
   ```
   若未啟用，必須先執行 `python scripts/install_git_hooks.py --install`。
3. **暫存區機密掃描 (Mandatory Staged Scan)**：提交前必須執行全暫存區掃描：
   ```bash
   python scripts/secret_scan.py --staged
   ```
   若掃描發現任何機敏特徵（Fail-Closed），必須立即停止提交並排查。
4. **掃描輸出安全紀律**：
   - 掃描器與執行者回報中，**絕對不得**印出或記錄比對到的原始機敏數值（Raw Matched Secret Value）或上下文整行文字。
   - 違規回報僅允許記錄：偵測器 ID（Detector ID）、檔案路徑（Path）與行號（Line Number）。
5. **正常提交自動執行**：直接進行 `git commit` 時，必須讓追蹤中的 `.githooks/pre-commit` 自動觸發並執行上述檢查，未經 Hook 驗證之提交不得宣告成功。

## 2.5 遠端健康查證與 GitHub Actions 閉環規範 (Remote Health Verification)

所有 Agent 在推送到遠端、main 快速進位或受保護 PR 合併後，必須落實遠端健康查證閉環：
1. **取得 exact origin/main OID**：確認本地當前 commit、main 快速進位或 PR 合併已正確被 remote main 接收（Checked Batch 快速進位後確認 exact SAME SHA，受保護 PR 合併後確認 exact merged main SHA）。
2. **查證 GitHub Actions Verify（Exact-SHA 閉環）**：
   - **必備五要素**：必須同時證明 (1) remote main 接收目標 commit；(2) workflow 名稱為 `Verify`；(3) `head_sha` 與目標 commit full SHA 完全一致；(4) `status == completed`；(5) `conclusion == success`。
   - **主要查證途徑 (Primary Channel)**：GitHub API / exact-SHA workflow run query（例如查詢 `/actions/runs?head_sha=<exact_sha>`）。
   - **暫態重試與替代途徑 (M2 Fallback)**：若主要查詢管道遭遇速率限制或網路逾時等 M2 暫態，允許重試或使用其他可綁定 exact SHA 的確定性管道（如 `gh` CLI 查詢 exact commit、commit status / check runs API 等）。具體可用途徑依當下環境決定，不建立單一工具硬相依。
   - **嚴禁使用非 exact-SHA 替代品 (Strictly Forbidden)**：嚴禁使用 branch badge、README badge、branch general green state、僅本地 PASS 或 Executor 口頭聲稱代替 exact-SHA 遠端證據。Branch badge 僅能反映分支一般狀態，無法證明特定 commit 已通過驗證。
   - **不可取得之升級 (S1 Escalation)**：經合理 M2 重試後，若所有 exact-SHA-capable 遠端管道均無法取得必要遠端健康證據，此時已非一般暫態，必須升級 S1 停止（`required remote evidence unavailable`），交由審計官或使用者仲裁。
3. **禁止文字摘要辯論 (Anti-Debate Policy)**：不得僅以本地 PASS 或 Agent 間文字對談斷定遠端健康。若 Actions 出現 failure，直接引用 run ID、failed job 與 failed step 客觀 log，禁止憑空猜測或口頭辯論。
4. **遠端中繼資料查詢安全收斂（Remote Metadata Safety & Secret Boundary — B-109 M2）**：
   - 查詢 candidate CI 狀態以匿名／公開 exact-SHA 中繼資料（public metadata）為主要途徑。
   - 嚴禁觸發 credential extraction、讀取 PAT/金鑰、組裝 Authorization header、列舉環境變數或跨 session 搜索；authenticated CLI 不得作為 public metadata 的必要 fallback。
   - 若 safe metadata 不可取得，一律回報 `UNKNOWN / DEFER_TO_EXTERNAL_MACRO`，嚴禁憑證繞道。raw Actions logs 存取嚴格維持 `EXTERNAL_MACRO_ONLY`。

## 3. 查證紀律

- **文件自己的宣告不等於事實**：曾發生 `mcp-gateway` 的 SKILL.md 宣稱
  「本技能取代了 connect-apps」，實際查證後發現完全沒有對應實作。
  凡是「某某已被取代 / 已廢棄 / 已整合」這類陳述，都要用實際程式碼或
  檔案存在性驗證，不能只依據文件描述。
- **改名、刪除引用、或移除違規規則時，要搜尋整個 repo**：不能只改當下看到的那個檔案。這個坑已經踩過三次：
  1. `d3-viz-skill` 的引用在 SKILL.md 刪掉了、REFERENCE.md 卻還留著
  2. `systematic-debugging-skill` 改名後，另外兩個技能的引用沒同步更新
  3. 「Zero-Block Policy」在 agency-orchestrator 的 SKILL.md 修掉了，但同技能的 REFERENCE.md、以及另外四個技能都還留著
  4. `jules-integration` 的額度資訊修正時搜尋「額度 5 次」，
     但實際字串是「額度**僅** 5 次」，多一個字就漏掉，錯誤留在
     `skills/agents/README.md` 直到 2026-08-29 被外部代理抄走才發現

- **搜尋詞要用最短的核心片段，不要用完整句子**：驗證某個錯誤事實是否清除時，
  搜尋「5 次」而不是「額度 5 次」，搜尋「06 層級」與 `0[1-9]_` 兩種形式而不是
  只搜其中一種。搜尋詞越長，假陰性機率越高。命中太多再人工篩，
  比漏掉一處好。**回報時要貼出實際命中的檔名與行號，不能只回報數量**——
  數量為 0 可能代表已清除，也可能代表搜錯字串。

- **計數必須指定演算法，回報必須附上演算法**：同一份文件用不同算法會得到
  不同數字。特別是 Markdown 的 ``` 圍欄數，**一律使用「以 ``` 開頭的行數」**：
  `sum(1 for l in text.splitlines() if l.strip().startswith('```'))`。
  **禁止使用 `text.count('```')`** ——該算法會把文件內文中提到的 ``` 一併計入，
  本專案的 `docs/HANDOVER.md` 就有兩行說明文字含有 ``` ，
  用 `count()` 會多算 2。此規則原本只記在歸檔快照 `docs/archive/handover/HANDOVER-pre-router-568209e.md` §10.4 與 §11，
  現行規則權威已完整移入本規則檔（現行 `docs/HANDOVER.md` 為 Router，不再保留舊規則）。

  更極端的實例：`PRINCIPLES.md` 與本規則檔兩份文件**完全沒有 code block**
  （以 ``` 開頭的行數皆為 0），但因內文大量引用 ``` 作說明，
  `count('```')` 的結果皆大於 0。若以 `count()` 判斷圍欄配對，
  會把這兩份沒有任何 code block 的文件誤判成含有數個 code block。
  **兩種算法的差距不固定，不可用差距大小當作判斷依據**，
  必須直接使用正確算法。
  此處不寫出具體數值，避免寫入改變自身描述之計數。**凡會被自身寫入改變之數字，不得寫入。**

- **回報數字不符時不得並存**：發現出入須立刻查明正確算法並說明，答案只有一個。

- **一個技能有多個檔案**：`SKILL.md`、`REFERENCE.md`、`EXAMPLES.md`、`scripts/` 都要一起檢查，不要只改 SKILL.md 就當作處理完。
- **區分「行為指令」與「歷史紀錄」**：Changelog 與 ADR 裡提到已廢除的規則是歷史留痕應保留；只有 agent 執行的行為指令才需清除。清理前先判斷屬於哪一種，不一律刪除。
- **執行 `python3 scripts/validate_skills.py` 前先設定編碼**：
  `$env:PYTHONIOENCODING = "utf-8"`，避免 Windows cp950 終端機無法輸出
  emoji 而報錯。
- **機械治理預檢與 Push Hook 模式邊界**：手動治理提示詞預檢必須使用顯式 --prompt-file 模式（例如 `--prompt-file <path>` 或 `--prompt-file -`）。Git pre-push hook 使用 `--verify-push` 且為唯一合法的 Git push stdin 引用更新模式。嚴禁手動裸呼叫 governance_preflight.py 作為 pre-push 驗證步驟；裸呼叫直接 fail-fast，絕不於無模式下等待 stdin。

