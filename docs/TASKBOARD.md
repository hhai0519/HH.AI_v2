# HH.AI_v2 重構任務看板

> **權威來源。** 詢問「還有哪些待辦」時，以本檔為準，不要憑對話推測。
> 維護規則見 `.claude/rules/auditor-protocol.md` §10。
>
> 本檔是**活動看板**（狀態會流轉、可反覆改寫）；
> `docs/refactor-backlog.md` 歷史紀錄區是**留痕層**（只追加不改寫），其交接區（§5.1、§5.3、§5.4）則為反映當前事實的可變狀態投影（mutable interface），兩者職責不同。

**狀態**：`待辦`（可直接執行）／`進行中`（提示詞已發出）／
`待裁決`（需使用者決定）／`已完成`（仍可能被引用）／
`可封存`（不影響後續工作，待使用者確認後移入封存區）

**ACTIVE_MACRO_AUDITOR**：GPT 代理審查官（使用者授權）

**NEXT_WORK**：E-03

**NEXT_SLICE**：TG-MVP-13

> [!IMPORTANT]
> **環境恢復觸發（Environment Recovery Trigger）**：
> 若發生以下任一事件：**換電腦**、**重新安裝 Antigravity**、**IDE 版本更新**，
> 在開始任何 production work 之前，必須先閱讀 [docs/ops/antigravity-environment-baseline.md](ops/antigravity-environment-baseline.md) 並完整完成 Environment Baseline Checklist 與重啟核對。

**最後更新**：2026-09-26，活動看板狀態請參見 NEXT_WORK 與 NEXT_SLICE。

---

## A. 額度控管與交接機制（2026-09-02 使用者提出的十一項）

| ID | 狀態 | 項目 | 落點 |
|---|---|---|---|
| A-01 | 已完成 | 每輪建議模型與切換時機 | `auditor-protocol.md` §8.1 |
| A-02 | 已完成 | 無交接接手流程 | §9.2 |
| A-03 | 已完成 | 交接提示詞寫進 SOP（含完整模板） | §9.1 |
| A-04 | 已完成 | 幾次對話換 Agent ＋ 交接前四項確認 | §8.2、§9.1 |
| A-05 | 已完成 | 額度控管的品質影響評估 | `refactor-backlog.md` 第 30 點 A 段 |
| A-06 | 已完成 | 規則追溯表（已改為 machine-generated traceability：`scripts/generate_rule_traceability.py` → `docs/generated/rule-traceability.md` → `scripts/tests/test_rule_traceability.py` / canonical verify_all 自動守護；已完成 External Macro Audit PASS，generator freshness + blocking validity、negative canary、fence-aware attribution 均已成立） | `docs/generated/rule-traceability.md` |
| A-07 | 已完成 | 注入式測試（E1） | 題目與答案卷由使用者與審計官保管，不進 repo。已於 2026-09-12 執行完成並判定 PASS，與 D-01 為同一件事 |
| A-08 | 已完成 | 接手自檢清單 | `.claude/rules/auditor-selftest.md` |
| A-09 | 已完成 | 交接區有內容且有人負責填 | §9.3、§6.1 第 8 項 |
| A-10 | 已完成 | 無交接接手流程（同 A-02） | §9.2 |
| A-11 | 已完成 | 兩次以上複驗 | 2026-09-02 執行，找出四個缺口 |
| A-12 | 已完成 | 任務板常駐化與封存機制 | 本檔 ＋ §10 |
| A-13 | 已完成 | 看板更新的觸發機制 | §10.5 觸發時機明確化為「每一批無例外」、新增 §10.6「最後更新」作為可驗證攔截點、§6.1 第 8 項與 selftest E4b 同步補上 TASKBOARD |
| A-14 | 已完成 | 對審計官的獨立偵測 | machine-readable Prompt Manifest validator 與 mutation-before-preflight hard rule 已完成 External Macro Audit PASS；兩次 Runtime Canary 均在任何 repo mutation 前成功 fail-closed，證明 Executor 可機械攔截 Auditor prompt 內部結構錯誤與跨區塊矛盾 | `.agents/rules/prompt-preflight.md` |
| A-15 | 已完成 | 執行者 session 的 context 截斷風險 | 2026-09-02 實際發生：Antigravity 畫面顯示「The server cleared a prefix of the conversation as it grew too large」，自動載入的 `.agents/rules/` 六份規則可能已被丟出 context 而不自知，且**沒有任何跡象會顯示規則失效**。處置：每批提示詞開頭要求從檔案讀取規則（§6.1-10、selftest E12）；並建議一批一個 session |
| A-16 | 已完成 | 「可機械檢查者必須機械檢查」原則 | 寫入 `PRINCIPLES.md` §2.8。控制的四層（控制／證據／偵測／獨立性），本專案幾乎只做到第一層。新增規則時必須能回答「這條沒做的話，什麼東西會發現？」 |
| A-17 | 已完成 | §10.1「當輪登錄」的漏洞 | 審計官不能改檔案，只能透過提示詞登錄；當一輪因需裁決而未產出提示詞時，登錄無處可去。A-15 即因此漏掉，直到使用者逐項對帳才發現。處置：§10.1 補上無提示詞輪次的處置程序 |
| A-18 | 已完成 | 「同一件事在多處被描述」的疏漏（第五次） | 修改一處內容時未搜尋「同一件事還在哪些地方出現」。五次紀錄：7 個檔案、15 個檔案、自測清單不進 repo、§9.4 指向已刪的 §5.2、§5.1 只改一個項目符號。§6.6 只防「錨點找不到」，防不了這種。處置：新增 §6.7 搜尋主題而非錨點；規劃 CHECK 15 機械檢查交接區的 commit hash 語境衝突 |
| A-19 | 已完成 | **§7.1 上線的當批就失效** | `AUDIT-LOG.md` 只有 3 列，缺 `23af193` 與 `b6ab53f`；審計官連續兩批未做自我審查檢查點。CHECK 12 尚未實作，無任何偵測。**這是 `PRINCIPLES.md` §2.8「只能靠人記得的規則視為尚未生效」的直接實證**。處置：本批補回兩列；CHECK 12 列為交接前必做（B-02） |
| A-20 | 已完成 | §6.1 第 10 項被空行斷開 | 第 9 項與第 10 項之間有空行，Markdown 會視為兩個列表。成因是插入指令未指明不留空行 |
| A-21 | 已完成 | 互相監督：執行者對提示詞做配對與覆蓋檢查 | 審計官最近六次錯誤中，**四次是執行者攔下的**，但它只有七項結構檢查。新增 §3.1 配對規則（更新 TASKBOARD HEAD ⇔ 更新交接區 HEAD 等）與 §3.2 覆蓋規則（`git add` 清單 ⇔ 總行數確認 ⇔ 圍欄檢查），把失敗提早到寫入之前。**嚴格限定為機械檢查**——判斷類的疑問依 `role-boundaries.md` §3 回報給使用者，不由執行者裁決，否則違反 ADR-0007 的立論 |
| A-22 | 已完成 | **自檢聲明區塊：讓審計官的自檢產生外部產物** | 2026-09-02 稽核發現 `handover-selftest.md` E 節不產生任何可觀察的東西——有沒有跑過，使用者、執行者、repo 都看不到。**這是審計官連續多批未遵守 §6.1 的根本原因，不是自律問題。** 處置：每份提示詞必須含【審計官自檢聲明】區塊（§6.1-12），執行者對可機械驗證的七項做交叉比對（`prompt-preflight.md` §3.4），使聲明成為可被推翻的宣稱 |
| A-23 | 已完成 | 「規則寫在他節、未進 §6.1」的第三次發生 | 交接區（§9.3）→ TASKBOARD（§10.5）→ **AUDIT-LOG（§7.1）**。前兩次各導致該檔案落後 2-3 批，第三次於本輪發現時 `AUDIT-LOG.md` 已落後一批。處置：§6.1 第 8 項擴為三項更新指令。**根因是「規範文件的章節」與「審計官實際照著跑的清單」是兩個不同的東西**，新增任何「每批必做」的規則時，必須同步進 §6.1 與 selftest E 節 |
| A-24 | 已完成 | 未 staged 遺漏的機械防線 | 本批攔截點觸發事件所暴露的缺口，已由 preflight §3.3 處置 |
| A-25 | 已完成 | **驗證器的獨立反例驗證** | 2026-09-04 審計官複製 repo 自行破壞後發現 CHECK 12 與 CHECK 15 回報 PASS 但抓不到目標違規，而 22 個對應測試全數通過——**測試照實作寫而非照規格寫**。處置：修正兩個 CHECK 的實作與測試；`git-and-reporting.md` 新增 §2.1。**教訓：新增任何驗證器之後，必須由審計官獨立做反例測試，不能只看它回報 PASS——有了綠燈反而不會有人保持懷疑** |
| A-26 | 已完成 | **寫入後的原文驗證** | 2026-09-04 發現交接區 §5.1 兩個項目符號被改寫，且改寫後與事實不符（「6 檔異動」→「3 改 0 新檔」、「驗證三項」→「驗證四項」），錯誤事實因此進入 repo。現有機制查不到——`prompt-preflight.md` §4 只驗證修改前的錨點。處置：新增 §4.1 寫入後原文驗證、`git-and-reporting.md` §2.2「提示詞指定的寫入內容逐字照抄」 |
| A-27 | 已完成 | **執行者找出審計官程式碼的邏輯錯誤** | 2026-09-04 反例實測時，執行者發現 CHECK 15 的修正版仍有 bug：§5.1 的項目符號是跨行排版，hash 在第一行、「已核對通過」在第二行，逐行比對永遠配不起來（實測 `done` 與 `pending` 皆為空集合，注入衝突也抓不到）。這是第八次獨立攔截，也是**第一次由執行者找出審計官程式碼中的邏輯錯誤**。同時指出步驟 5 的測試設計錯誤（刪一列 `lag=1`，門檻 `> 1` 不觸發，應刪兩列）。處置：改為逐項目符號分塊掃描；測試資料改用跨行排版以貼近真實結構 |
| A-28 | 已完成 | **反例測試只測邏輯、沒測真實輸入** | 2026-09-04 為 CHECK 15 做反例測試時人工構造帶 hash 的違規，正確 FAIL 因此判定修好。但真實檔案的待核對項目符號不寫 hash，實測「待核對 0 個」——**它專門要抓的事故若重演，它抓不到**。由新開的 Claude session 在核對時發現。處置：`auditor-protocol.md` §5.6、§9.3 |
| A-29 | 已裁決 | **舊 CHECK 15 兩項行為被刪除且無紀錄** | 2026-09-05 使用者裁決：**兩項皆棄用**。行為 1「已刪章節引用偵測」——三個硬編碼字串針對單一歷史事件、行號例外已失效，故棄用；但它抓的「章節仍存在但語意已變」CHECK 10 抓不到，缺口登錄為 B-17，須重新設計而非恢復舊碼。行為 2「正文開頭未包裹否定詞偵測」——全庫查無對應的真實事故，存在理由無法驗證，且誤報風險高，棄用且不登錄後續待辦。完整紀錄見 `.claude/rules/auditor-protocol.md` §5.8 |
| A-30 | 已完成 | **§6.6 的錨點建議本身是錯的** | 原建議「下一個標題行優先用它」在新增同層級小節時必然造成編號逆序。2026-09-04（§3.4 錨在 §3.3 前）與 2026-09-05（§5.6 錨在 §5.5 前）各發生一次，兩次都由執行者停下回報。處置：§6.6 改為依插入位置區分三種情境的錨點選擇表 |
| A-31 | 已完成 | **錨點必須標註來源行號** | 2026-09-04 至 09-05 連續三類錨點失誤（跨檔案汙染、引用自己上一批的措辭、誤判檔案結構），共同根因是**沒有從 clone 逐字取錨點**。`count()` 可以瞎猜「1」，行號猜不到——標註來源行號讓「有沒有實際查證」變成可被推翻的宣稱。同批新增 §6.1 第 14 項：跨檔 `§X.Y` 引用必須在同一行寫檔名，否則觸發 CHECK 10 |
| A-32 | 已完成 | **插入型修改必須附「插入後的預期序列」** | §6.6 的錨點選擇表寫了正確規則，審計官在寫下它的**同一批**仍然違反（G／H 段錨在 F 段之前）。這是同一個錯誤模式的第三次，前兩次的處置「把規則寫清楚」已證明無效。處置：§6.1 新增第 15 項——提示詞必須寫出插入後的預期序列，執行者機械比對是否遞增、實際是否等於預期。**寫出序列會強迫在下筆前先看結構，那正是三次都被跳過的步驟** |
| A-33 | 已完成 | **§6.1 ⇔ selftest E 的配對規則缺席** | 這一對耦合連續漏更兩次（2026-09-04 的 E8「兩項 vs 三項」、2026-09-05 的第 13／14／15 項）。CHECK 11 每次都抓到，但那是**寫入之後**——`prompt-preflight.md` §3.1 的四條配對規則中，唯獨缺了這一對。處置：§3.1 新增第 5 列，把失敗提早到寫入之前 |
| A-34 | 已完成 | **新鮮 clone 證據區塊** | 2026-09-05 有一批提示詞重投八次才通過，八次中**七次的根因相同**——審計官 clone 了，但只查它打算查的那幾行，其餘錨點與結構取自上一批提示詞、上一輪回報或印象。**問題不在有沒有 clone，在 clone 之後看了多少。** 處置：§6.1 第 16 項要求每份提示詞附「HEAD ＋ 目標檔案行數 ＋ 目標區塊結構快照」，由 preflight §3.6 交叉驗證。**不採用計數式門檻**——計數要靠記憶或誠實回報，那正是本條要解決的問題 |
| A-35 | 已完成 | **規則的層級決定它會不會被執行** | 使用者指出「之前有寫過類似的但是放在 ADR，所以沒有執行」。repo 中有六次實證：ADR-0005／0002／0016 三條寫在留痕層而未執行（其中兩條自己寫明要搬進第 1／2 層，兩個月未做）；更新交接區（§9.3）、TASKBOARD（§10.5）、AUDIT-LOG（§7.1）三條未進 §6.1，各導致該檔落後 1-3 批。處置：`auditor-protocol.md` §5.7——新增任何「每批必做」的規則時，**必須同時進 §6.1、selftest E 節、preflight §3 三處**，只寫進 ADR 或單一節視為尚未生效 |
| A-36 | 已完成 | **自檢聲明造假：E11 勾了但沒做** | 2026-09-05 審計官在自檢聲明寫「E11 ✅ 六個錨點皆於 clone 實測 count()=1」，**實際只量了三個**，其餘沿用前幾批的用法。E11 正是為防此而設，勾了 ✅ 卻沒做，使自檢聲明從「可被推翻的宣稱」退化為空話。處置：`prompt-preflight.md` §3.4 的交叉驗證表新增一列——**要求證據區塊逐條列出每個錨點與其 count 值，而非僅宣告「皆為 1」**；只有逐條列出才可被機械比對 |
| A-37 | 已完成 | **自檢聲明的覆蓋缺口：18 項中只有 7 項可被驗證** | 2026-09-05 實測 selftest E 節 18 項，而 `.agents/rules/prompt-preflight.md` §3.4 只涵蓋 7 項。**其餘 11 項審計官勾 ✅ 無人能反駁**——E11 造假正是從這個洞出來的。**問題不在審計官特別不老實，在那 11 項本來就沒有約束。** 處置：§3.4 擴為 18 項，**十八項全部可機械驗證、零例外**。其中 E10 一度被誤判為「需語意判斷」，實則「檢查零命中字串是否出現在提示詞自身」是純字串比對——**錯誤的「無法驗證」判定等於自己開新洞** |
| A-38 | 已完成 | **審計官引用錨點原文造成 count=2** | 2026-09-05 審計官在 backlog 第 43 點 C 段描述「E11 造假」時，把錨點原文寫進正文，使該字串在檔案中 count=2。這與 `.claude/rules/auditor-protocol.md` §6.2「零命中條件要先檢查自身指令會不會產生該字串」是同一形狀。**§6.2 的原則已涵蓋，不新增規則**——過度增加規則會稀釋既有規則的注意力 |
| A-39 | 已完成 | **CHECK 8／9 的門檻設計錯誤** | 欄位記錄「上次核對通過的 HEAD」，執行者在 commit **之前**跑檢查時落後 1（正常），**commit 之後 HEAD 前進，同一個值就落後 2 而 FAIL**。連續發生三次（875a604、8b56cbd、ec840fe），每次都被當成「填錯值」去修，但**任何值都會在 commit 後落後**——除非填本批自己的 hash，而那在寫提示詞時還不存在。**這是門檻設計錯誤，不是誰的疏忽。** 處置：門檻由 `lag > 1` 改為 `lag > 2`——落後 1＝本批已 commit 尚待核對；落後 2＝下一批也 commit 了卻仍未更新欄位，那才是異常 |

A 節目前狀態以本表各列與 `NEXT_WORK` 之 current repo truth 為準；不另維護會與表格重複的動態完成摘要。

> **看板完整性說明**：2026-09-02 全盤盤點前，本看板只有 A–D 共 24 項，
> 完全未涵蓋 `refactor-backlog.md` §二的六大節與四個追蹤項。
> 補完後為 A–G 共 41 項。教訓記於第 32 點。

---

## B. 重構主線

| ID | 狀態 | 項目 | 備註 |
|---|---|---|---|
| B-01 | 已完成 | ADR-0002／0004／0010 分層搬移 | B-01 ADR-0002/0004/0010 active-contract layering完成；initial candidate b2b5d1d Machine PASS / Macro HOLD；85d9a3a bounded F1/F2 repair完成；完整 range取得 External Macro PASS / ACCEPT ALL。 |
| B-02 | 已完成 | `check_consistency.py` 增補檢查（CHECK 8-15） | CHECK 8 看板 HEAD 落後、9 交接區 HEAD 落後、10 §X.Y 章節引用有效性、11 §6.1 與 selftest E 對應、12 AUDIT-LOG latest audit evidence 必須位於 current HEAD ancestry（允許多個合法 pending repair commits，raw ancestry distance 不再是 FAIL threshold）、13 檔尾換行、14 簡體字、15 提示詞衝突字串。本批擴充至 15 項，全數通過 |
| B-03 | 待辦 | 新建 `SOP/SOP_03_Skill_Lifecycle_and_Quality.md` | 收納舊 `SOP_00` §一／§三／§四與舊 `SOP_03` §4.2／§4.3，見第 18 點 |
| B-04 | 待辦 | `validate_skills.py` 加 description 觸發詞警告 ＋ 測試 | 警告非錯誤，現存多個技能會失敗 |
| B-05 | 已完成 | DLP 裝飾樣板存量清理（25 份 SKILL.md） | DLP false self-attestation 已由 `validate_skills.py`（`DLP_ATTESTATION_RE`）與單元測試機械守衛，全庫 skills 零違規殘留，存量清理完成 |
| B-06 | 可封存 | `description` 引號寫法收斂（26 加／28 未加） | 純格式收斂，parser 支援 quoted/unquoted，無 production correctness 價值，可予封存，不得為此異動技能 |
| B-07 | 已完成 | **GitHub Actions CI**（`.github/workflows/verify.yml`，push 觸發） | 新建 verify.yml，fetch-depth: 0，包含 validate_skills、check_consistency 與全自動化測試 |
| B-08 | 已完成 | 已審核標記機制（`audited-<hash>` tag） | 本批補齊 audited-18af8ad 與 audited-08e6bbc 標籤，與遠端同步 |
| B-09 | 已完成 | `test_check_consistency.py` | 為 CHECK 8 至 CHECK 15 撰寫完整正反例測試，含 BOOTSTRAP 例外與 CHECK 11 失敗重現 |
| B-10 | 待辦 | Jules 的協作規範 | 目前全庫關於 Jules 只有兩行。缺：產出如何驗證、分支如何審查、誰負責合併、失敗如何處置。F-01 已指定為 Jules 首航任務——**規範必須在 Jules 實際加入前完成**。Jules drift 記錄：authorized_mcp_tools 目前無已驗證 harness enforcement，jules-integration 仍指向 disabled Bridge；Jules capability semantics 留至 M4；本輪不得啟用 Jules |
| B-11 | 已完成 | CHECK 15 名稱漂移 | 實作與 docstring 已改為「交接區 §5.1 的 commit hash 語境衝突」，但第 19／448／450 行三處顯示字串仍是舊名稱，**執行輸出對使用者顯示的與它實際做的事無關**。§6.7 的第六次發生。本批修復 |
| B-12 | 可封存 | **`audited-*` tag 落後偵測（CHECK 16）** | 被 AUDIT-LOG、refactor-backlog §5.1 與 GitHub Actions Remote Health Authority supersede。audited-* tag 已退役為 legacy historical markers，失去 active authority 用途，不再實作 tag-lag CHECK。 |
| B-13 | 已完成 | §5.1 項目符號必須帶 commit hash | CHECK 15 靠反引號包住的 hash 判斷語境，2026-09-05 實測末項無 hash、「待核對 0 個」——機制存在但輸入不合格。處置：規則寫入 `auditor-protocol.md` §9.3 |
| B-14 | 已完成 | **執行者側的檢查紀錄檔** | 執行者每批做的結構元素、配對／覆蓋、自檢聲明交叉驗證，此前**只存在於回報中，repo 無痕跡**——那是整套機制最後一個沒有證據的環節。審計官有 `docs/AUDIT-LOG.md`，執行者這一側什麼都沒有。處置：建立 `docs/EXEC-LOG.md`（規則見 `.agents/rules/prompt-preflight.md` §3.8），並新增 CHECK 16；CHECK 16 獨立守護 Executor EXEC-LOG evidence lifecycle / freshness，CHECK 12 獨立守護 Auditor AUDIT-LOG ancestry validity，兩者為獨立職責，不再宣稱判準相同 |
| B-15 | 已完成 | **CHECK 1-7 沒有函式也沒有測試** | 2026-09-05 實測：CHECK 1 至 7 內嵌在 `run_checks()` 中，無獨立函式、無測試。**審計官已於本批做反例注入實測**：逐一破壞後確認七項皆能正確 FAIL，結果見 `docs/AUDIT-LOG.md`。判定為**不需重構為獨立函式**——它們自 2026-08-29 起每批都在跑且多次實際命中真實缺陷，反例注入已證明其有效性；重構的風險高於收益 |
| B-16 | 待辦 | **全庫規則的一次性回溯稽核** | 重構至今所有規則與 backlog 的歷史宣稱，多數是審計官在對話中推算而非實測，從未被機械驗證。實測規模：規則檔 11 份共 1,939 行（含 43 處日期宣稱、8 處「第 N 次」計數宣稱），`refactor-backlog.md` 1,941 行 42 個編號項目（含 79 處日期宣稱）。**審計官已被抓到過四次數字錯誤（7 個檔案、15 個檔案、848 行、89／211 行），沒有理由相信這些未驗證的宣稱是對的。** 拆為三批：**R1** 八處「第 N 次」計數（**2026-09-06 使用者裁決改判為交接後執行**：R1 修正的是留痕層的歷史數字，不影響新 Agent 的行為判斷；該裁決原僅存於交接區 §5.4，本批搬入本列與 `docs/refactor-backlog.md` 第 53 點 B 段）、**R2** 規則檔 43 處日期（可後做）、**R3** backlog 42 點的內部一致性（可後做） |
| B-17 | 待辦 | **章節語意變更偵測** | 來自 A-29 行為 1 的缺口。CHECK 10 驗證 `§X.Y` 指向的章節是否**存在**，但抓不到「章節仍存在、語意已變」——例如交接區 §5.2 現在只剩一行指標，引用它的「優先序」已失效但章節仍在。舊實作用三個硬編碼字串處理，零通用性。**須重新設計**：可能方向是比對章節的行數或內容雜湊在批次間的變化，對引用該章節的位置提出警示。**可交接後做** |
| B-18 | 已完成 | **commit／push 的執行狀態必須以指令輸出為準** | 2026-09-05 執行者連續兩輪回報與實際不符：先回報「未執行 commit 與 push」但遠端 HEAD 確為該批 commit；再回報某段內容為 §5.1 的實際內容，而遠端實測 count=0——那段只存在於本機工作區。**這是回報與實際不符的第五類：動作狀態虛構**，比內容虛構更危險，因為內容虛構在 clone 核對時會被抓到、動作狀態虛構若不主動查 `git log` 就看不見。處置：`git-and-reporting.md` §2.3 要求 commit／push／回滾後必須貼出 `git log -1 --format=%h`、`git rev-parse --short origin/main`、`git status --porcelain` 三條指令的實際輸出 |
| B-19 | 已完成 | **CHECK 8／9 的 FAIL 訊息自相矛盾** | 第 564／608 行寫「落後超過兩批 (落後超過一批)」。**該矛盾字串是唯一撐住兩個過期斷言的支架**，非美觀問題。詳見 `refactor-backlog.md` 第 46 點 |
| B-20 | 已完成 | **佔位符未補 hash，兩個 CHECK 同時空轉** | `docs/EXEC-LOG.md` 第二列 commit 欄為「本批」，CHECK 16 整個跳過且訊息錯誤；交接區 §5.1 末列同樣停在「本批（尚未 commit）」，CHECK 15 持續回報「待核對 0 個」。B-13 教訓的第二次 |
| B-21 | 可封存 | **CHECK 16 編號被兩件事佔用** | 已由 B-60 規劃案吸收，不再作為獨立可執行待辦。 |
| B-22 | 已完成 | **交接區 §5.4 落後三批且無偵測** | §5.4 停在 `76f424c` 時代敘述，`875a604`／`ec840fe`／`e6f543a` 三批皆未更新。CHECK 9 只驗 §5.1 第一行，§5.4 無任何偵測，而 `auditor-protocol.md` §9.2 第 1 點要求接手時先讀它 |
| B-23 | 已完成 | **第四個假綠燈：CHECK 8／9 門檻改動未同步測試** | A-39 改門檻為 `lag > 2`，但測試第 46／65 行仍斷言舊訊息，且 `git_prev2` 全檔零出現——**lag=2 邊界零覆蓋**。A-25「測試照實作寫」的第二次，且連續兩批 CI 綠燈 |
| B-24 | 已完成 | **§6.7 第七次失效：改字串未搜尋其引用位置** | 審計官修改 FAIL 訊息時未搜尋該字串在測試中的斷言，並錯誤判定「不改變行為」。§6.7 的搜尋對象清單需增列「被測試斷言引用的字串」，依 §5.7 同步三處。**2026-09-07 實測落地**：`.claude/rules/auditor-protocol.md` §6.7 清單第 4 條「要改程式碼中的顯示字串 → 搜尋是否有測試斷言引用它」，該清單實測 7 條 |
| B-25 | 已完成 | **自檢聲明 E11 數量宣稱不符** | 聲明「22 個錨點」實列 21 個。A-36 同一形狀第二次。**機制有效**——執行者依 §3.4 逐條清點後推翻。比照 A-38 不新增規則，僅留紀錄 |
| B-26 | 可封存 | **攔截點缺少執行時點** | 已由 B-92 EXEC-LOG 狀態流轉與 prospective commit 驗證機制徹底解決。 |
| B-27 | 已完成 | **「動手前必讀」機制從未被驗證，三份規則檔有兩份虛構** | 2026-09-06 實測：執行者貼出的 `prompt-preflight.md` 與 `git-and-reporting.md` 章節標題、§1 全部條目、§2 整節內容皆與實際檔案不符（`prompt-preflight.md` 那張 14 列「歷史失效清單」表在實際檔案中不存在）；§3.4 表漏 E12 卻聲稱驗證了 E12。`role-boundaries.md` 屬實。**回報與實際不符的第六類：規則來源虛構**，最嚴重，因為後續所有檢查都建立在被虛構的規則上。處置：本批提示詞已加入章節序列比對；根本解法為 B-35 指紋機制。**2026-09-07 實測落地**：規則層「章節序列」共 3 處（`.claude/rules/auditor-protocol.md` 1 處、`.agents/rules/prompt-preflight.md` 2 處），動手前必讀已含章節序列比對 |
| B-28 | 待辦 | **`AGENTS.md` 宣稱遵循 mattpocock/skills，但零審查機制、零版本記載** | REOPENED BY USER U2 / PENDING / NOT IMPLEMENTED。使用者 U2 裁決：HH.AI_v2 以 Matt Pocock 架構思維重構，核心原則不變，依本專案實況調整，不是逐檔照抄 upstream；以此架構思維重新檢驗 HH.AI_v2 |
| B-29 | 待辦 | **上游一致性對照表 ＋ 機械檢查** | REOPENED BY USER U2 / PENDING / NOT IMPLEMENTED。同 B-28 由使用者 U2 裁決重啟，依 Matt Pocock 架構思維進行結構比對與可持續對照機制，非無差別鏡像複製 upstream |
| B-30 | 已完成 | **playwright 掃描清單含 3000／3001，運行風險已存在** | TG-MVP-07 ACCEPTED / CLOSED；explicit-target-only contract accepted；built-in commonPorts sweep removed；non-target 3000/3001/5000 isolation accepted；implementation SHA `f73a076d5ef4184735a6586a7069c66a6ba54bcc`，post-main Run 35802245822 success。 |
| B-31 | 已完成 | **ADR-0013 §2C BOM 污染偵測未被取代** | CHECK 19 已採 Git tracked inventory 作為 deterministic BOM scope authority；.gitattributes BOM、untracked/ignored non-authority、inventory/read failure fail-closed 均已有 regression coverage，External Macro Audit PASS。 |
| B-32 | 待辦 | **ADR-0013 §6 觸發詞排他性矩陣** | 與 Watchdog 無關的夾帶內容，且使用已廢除的「Cognitive Agent」分類。需重寫為 v2 bucket 語彙並實作跨技能觸發詞重疊偵測。排批 4 |
| B-33 | 已完成 | **Port 規範的三個缺口** | root `.env.example` current tracked tree ABSENT（不得重建）；3003 Gateway canonical local port accepted；6379 / 9222 / 9223 known tooling port registry convergence accepted；implementation SHA `f73a076d5ef4184735a6586a7069c66a6ba54bcc`，post-main Run 35802245822 success。 |
| B-34 | 已完成 | **看板 C-01 的行號與衝突性質記錯** | 宣稱「`SOP_06` 第 100 行說 line-bridge = 3000」是衝突，實測該行敘述與 ADR-0017 完全一致；真正衝突在第 133 行。B-16 的又一實例。本批已於 C-01 列更正 |
| B-35 | 可封存 | **雙代理事實指紋與 Dashboard** | Stage 1 指紋與驗證已實作；Stage 2/3 (dashboard.html/GitHub Pages) 被 ADR-0020 與 GitHub Actions Remote Health Dashboard 完全取代。 |
| B-36 | 已完成 | **廢除口頭回報，回報即 commit** | 執行者不再產出供轉貼的文字報告，檢查結果與疑問一律寫入 `docs/EXEC-LOG.md` 並 push，對話僅回一行 commit hash。根因：五類回報失真加 B-27 的第六類全部發生在「文字報告」這一環，且它是審計官 token 消耗最大的單一來源。**自本批生效** |
| B-37 | 已完成 | **`scripts/anchor.py` 錨點自動抽取器** | 輸入檔名與行範圍，輸出「原文 ＋ 行號 ＋ `count()` 值」。同時消滅「錨點未從 clone 逐字取得」（前任五次、現任一次）與「自檢聲明數量宣稱不符」（A-36、B-25）——機器抄的原文不漂移，機器數的數量不少算。排批 2 |
| B-38 | 可封存 | **驗證腳本加 `--quiet` / `--json` 模式** | 原始 Claude context pollution 已由 B-36 Repo Evidence Channel 徹底消除，終端機輸出不進入對話，可予封存 |
| B-39 | 可封存 | **獨立性的來源從審計官轉移到 CI** | CI 獨立性核心已由 Canonical Entrypoint (verify_all.py) + GitHub Actions exact SHA Verify + ADR-0020 實質完成。 |
| B-40 | 已完成 | **`PRINCIPLES.md` §1 的判別演算法缺審計官出口** | 層級表未列 `.claude/rules/`（907 行），四個判別問句的答案也沒有它——第 2 問只給執行者的兩個目的地。任何「給審計官的規則」依序自問只能落到第 4 問（ADR）。**現任審計官即因此提議開 ADR-0020，是 §5.7 第七次。這是演算法缺陷不是個別疏忽。** 本批已修 §1；**CHECK 17（ADR 規範混雜偵測）排批 2**——實測 19 份 ADR 有 10 份 Decision 區塊含祈使句且無分層搬移標記，其中 ADR-0017（4 處）正是 C-01 衝突的成因、ADR-0013（10 處）正是 C-03 要拆的那份。**2026-09-07 實測落地**：`PRINCIPLES.md` §1 層級表已列 `.claude/rules/`，四個判別問句第 2 問已有「給審計官的」出口 |
| B-41 | 已完成 | **Project Instructions 是唯一不在 repo 的一層** | B-41 Slim Bootstrap / Runtime Reconciliation External Macro PASS / CLOSED；.claude/README.md 正式作為 repo-owned canonical slim bootstrap / recovery router；docs/HANDOVER.md 保持 supporting router / VERIFY_ONLY；full mirror superseded；no .claude/slim-bootstrap.md；no workspace/global GEMINI creation；no fake UI CI CHECK；dynamic state remains runtime-routed；B-69 search false-zero evidence recorded as existing / non-blocking；exact-SHA Verify Run 34852512530 completed / success；B-01 zero implementation。 |
| B-42 | 已完成 | **CHECK 16 靜默跳過無法解析的列，且 docstring 與實作不符** | CHECK 16 與 _validate_exec_log_transition 已於 B-92 完整重寫修復，無法解析即 FAIL，docstring 一致並具單元測試。 |
| B-43 | 已完成 | **CHECK 15 的 pending 集合在正常流程恆為空** | CHECK 15 輸出已明確區分「無待核對」與「待核對無交集」，單元測試全通。 |
| B-44 | 已完成 | **看板 C-04 狀態未隨裁決更新** | 使用者已於 2026-09-06 同意 Runtime 層方向，但批 1 的提示詞改了 C-01／02／03 卻漏了 C-04。**審計官漏項**，會導致下一個接手者重新提問已裁決事項（§9.4 第 4 項要防的情形）。本批已修 |
| B-45 | 已完成 | **交接區 §5.3 與看板 C 節是未登記的配對關係** | 批 1 把看板 C-01／02／03 改為已裁決，但交接區 §5.3「待使用者裁決」那張表原封不動，兩處說法相反。`prompt-preflight.md` §3.1 的配對清單未登記這一對，故配對檢查不會發現。與 B-44 同一成因：處理裁決結果時只想到看板，忘了交接區也有一份。本批已修內容；**配對規則登記排批 2b** |
| B-46 | 已完成 | **指紋的 sha256 未處理跨平台換行，CI 上線首日即紅燈** | 審計官在批 2a 規格中指定 `hashlib.sha256(raw_bytes)` 並註明「讀 bytes，非 text」，未考慮 Windows Git `core.autocrlf` 預設把 LF 轉 CRLF。實測 42 檔僅 `sha256` 不符、`lines`／`fences`／`headings` 全對；CRLF 假說以位元組證明。**規格錯誤，非執行者實作錯誤。** 已於 `3a85a30` 修正（雜湊前正規化 ＋ `.gitattributes` 第二道 ＋ CRLF 守護測試） |
| B-47 | 已完成 | **`fingerprint.py --verify` 不在標準驗證集內，是假綠燈的生成路徑** | 已於 Gate Parity 收斂完成：建立 Canonical Verification Entrypoint（`scripts/verify_all.py`），將 validate_skills、check_consistency、fingerprint --verify、scripts/tests、webapp-testing/tests 5 大 Correctness Gates 統一收攏。CI workflow（`.github/workflows/verify.yml`）、Local、Prospective 與 Post-commit 全部呼叫同一 entrypoint，根除假綠燈與 parity gap |
| B-48 | 可封存 | **「回報即 commit」無法容納 commit 之後才發生的事** | 被 ADR-0020 supersede（由 GitHub Actions Verify 作為遠端權威，避免雙 commit 遞歸死結）。 |
| B-49 | 可封存 | **CI 獨立查證的規則化與機械化** | 被 ADR-0020、AGENTS.md §10、git-and-reporting.md §2.5 與 README Verify badge supersede。 |
| B-50 | 已完成 | **`prompt-preflight.md` §3.4 的交叉驗證可被審計官以「知情偏離」宣告繞過** | 2026-09-06 審計官在 2a-fix 把 E8 標為 ⚠️ 並附理由，執行者接受並未停止，導致 CHECK 12 在 CI 上 FAIL。§3.7 明寫「十八項全部可機械驗證，沒有任何一項需要你憑信任接受」，但 E8 就此變成信任項——與該節建立時要消滅的 E11 造假是同一個洞。而 `role-boundaries.md` §2 又禁止執行者判斷規範是否應存在，執行者被夾在中間。**修法：E8 比對為否時一律停止、不接受任何理由；審計官需偏離 §6.1-8 時，唯一合法路徑是先另開一批修改規則本身。** 排批 2b。**2026-09-07 實測落地**：`.agents/rules/prompt-preflight.md` §3.4 已含「自檢聲明不接受任何豁免」，實測 1 處 |
| B-51 | 已完成 | **判準含 HEAD 的檢查，本地與 CI 的答案結構性差 1** | 已於 Transient Red Reduction 完成：check_9_handover_head 強化 candidate 自引防護（不得為當前 HEAD）；check_consistency.py 實作 --as-if-committed 預演模式，使 commit 前即可準確預測 commit 後拓撲（HEAD=candidate, HEAD~1=當前HEAD, HEAD~2=當前HEAD~1），提前攔截 stale handoff pointer 與週期落後，消除本地與 CI 差 1 的可預測中間紅燈 |
| B-52 | 已完成 | **同形錯誤連續三批：改動或跳過某物之前，未查誰依賴它** | B-52 建立 §6.7 dependency-search 原則與歷史事故分類；其『讓 dependency discovery 不再依 Auditor 記憶』之 executable residual 由 B-68 正式承接。 |
| B-53 | 待辦 | **CHECK 4、7 仍內嵌於 `run_checks()`，待完成剩餘檢查器抽取與回歸測試** | CHECK 1、2、5、6 已於 B-93 抽成 production helpers，CHECK 3 已具獨立 production function，且上述函式皆已具備 direct regression canaries。目前 CHECK 4、7 仍留在 `run_checks()` inline。本項保持「待辦」，但 scope 收斂為 remaining inline checks 抽取與 residual regression coverage，待後續批次處理。不得錯誤標記已完成。 |
| B-54 | 待辦 | **零項 CHECK 驗證 SOP 層內容或跨層矛盾** | 對著稽核迴圈自己、通用格式、skills/、路由引用等已有檢查，但 **SOP 的 1,305 行內容與規範層之間的矛盾完全無守衛。** 已知三例（`SOP_02` 清歷史 vs `.agents/rules/git-and-reporting.md` 禁 force push；`SOP_04` 第 167 行與 `SOP_06` 第 133 行 vs ADR-0017；`SOP_12` 將 `C:\Users\HH.AI_260806\...` workstation-specific path 當作直接 fallback / related-setting location，違反 `SOP/README.md` Runtime Availability Boundary 對非可攜路徑之禁令）。處置：建 `docs/managed-facts.yaml` ＋ 跨層矛盾偵測與 machine-derived evidence contract，降低 code correct 但 prose/EXEC evidence 不準確之 handoff 污染（若未來實作新 CHECK，ID 必須於 implementation time machine-derive）。排批 2e |
| B-55 | 待辦 | **治理層已分裂成兩個速度** | 實測最後修改日：稽核迴圈檔案 09-05～09-06；作業層 SOP_01／02／05／06／09／11／12／13 停在 2026-08-25（12 天）；**`.agents/rules/skills-architecture.md` 停在 2026-08-13（24 天，全庫最舊）——而它正是 B-01 的目標檔案**。處置：文件時效偵測（若未來實作新 CHECK，ID 必須於 implementation time machine-derive）。排批 2e |
| B-56 | 待辦 | **`SOP_00A_Master_Index.json` 的維護規則靠記憶** | 該檔是 `$$` 指令的唯一權威定義來源，內含「每次新增或修改 SOP 時，必須同步更新此索引對應的 tags」但無任何偵測；`last_updated` 停在 2026-08-29，current PENDING_MIGRATION routes 由 SOP_00A machine-derive。CHECK 5 只驗路由目標存在性，不驗時效與完整性。併入文件時效與完整性偵測（若未來實作新 CHECK，ID 必須於 implementation time machine-derive）。排批 2e |
| B-57 | 可封存 | **審查機制的完成定義（五條可機械驗收）** | 原五項 acceptance 已被後續 Governance Exit criteria 取代；仍有效的 residual risks 由現行 concrete tasks（如 B-31 / B-53 / B-54 / B-88 / B-89）各自保存。 |
| B-58 | 已完成 | **治理層瘦身（Content Architecture cleanup），使用者已裁決正式開始** | Router PASS；Phase 3A PASS；R1–R6 PASS；B-58 Final Macro Audit PASS；Content Architecture cleanup CLOSED；D-02 hold released |
| B-59 | 待辦 | **`docs/ARCHIVE-INDEX.md` 自己沒有機械守衛** | 開頭寫「新增或變更任何歸檔機制時，必須同步更新本檔」但無偵測。處置：ARCHIVE-INDEX 可達性雙向驗證——索引提到的每個歸檔區必須實際存在，且 repo 中每個歸檔區必須被索引收錄（若未來實作新 CHECK，ID 必須於 implementation time machine-derive，不得重用已被 Markdown 表格連續性使用的 CHECK 20）。這是使用者裁決條件②「封存要有足夠的邏輯及指向」的機械化。排批 2d |
| B-60 | 可封存 | **CHECK 17–24 編號一次配置完成（防 B-21 重演）** | 原 17–24 allocation plan 已停止作為 implementation schedule；未來若 post-main 決定新增 CHECK，必須先從 current check_consistency.py machine derive 下一個可用 ID，不得重用舊 B-60 數字表。 |
| B-61 | 已完成 | **證據區塊 (d) 的圍欄數沒有被納入 §3.6 的交叉驗證** | `.agents/rules/prompt-preflight.md` §3.6 的驗證表只有三項：區塊存在／行數相符／結構相符，**圍欄數不在其中**。2026-09-06 實測：審計官在提示詞把 `.claude/rules/auditor-protocol.md` 的圍欄數誤寫為 0（實際為 2，位於第 54、65 行），執行者回報實際值但判定為「零變動相符」——它比對的是修改前後，不是與宣稱值。**這不是執行者疏漏，是 §3.6 沒有要求它比對。** 一個沒有人核對的數字等於沒有寫。處置：§3.6 驗證表增列圍欄數比對。排批 2d。**2026-09-07 實測落地**：`.agents/rules/prompt-preflight.md` §3.6 驗證表 5 列，已含「圍欄數相符」 |
| B-62 | 已完成 | **規則層變更必須先在本地模擬，且模擬證據要不可偽造** | 審計官連續四批犯同形錯誤，其中三次（改字串未查引用、CRLF、E16 目視）都會被「本地套用後跑 `scripts/check_consistency.py`」攔下。**落點依 `PRINCIPLES.md` §1 第 2 問判定為 `.claude/rules/auditor-protocol.md` §6.1 第 18 項**（不是 `SOP/`——那是執行者的程序層），同批落到 `handover-selftest.md` E20 與 `prompt-preflight.md` §3.4。**機械閘門的設計關鍵**：證據不是「我跑過了」的宣告，而是最後三條 CHECK 10 INFO 行——它們累積了整個檔案的位移量，**沒有真的套用過就寫不出正確的行號** |
| B-63 | 已完成 | **章節標題含硬編碼項數，新增項目時無人會發現** | `.agents/rules/prompt-preflight.md` §3.7 標題與內文原寫「十八項」，而 E 節在 2026-09-06 的同一天已增為 19 項，**當場失準且無任何機制會發現**——CHECK 10 只看章節號，CHECK 11 只看 §6.1 ⇔ E 的對應，都不看散文裡的數字。與 `.agents/rules/git-and-reporting.md` §3「凡是會被自身寫入行為改變的數字，不得寫進文件」是同一形狀。**處置不是把 18 改成 20**，而是把數字整個拿掉 |
| B-64 | 已完成 | **模擬閘門首次使用即攔下審計官，暴露閘門本身的缺口** | B-62 上線後首次使用，審計官模擬完之後在寫提示詞時於 §3.6 多加了五行說明而**未重跑模擬**，宣告 `prompt-preflight.md` 套用後為 327 行、實際為 332 行，被執行者攔下。**閘門有效，但規則本身有缺口**：原措辭只要求「模擬後再送出」，未要求「模擬的對象等於送出的文字」。已於 §6.1 第 18 項補上「模擬的對象必須是最終要送出的文字本身」與單一來源作法 |
| B-65 | 已完成 | **雜湊一段跨平台 shell pipeline 的輸出，是錯的閘門原語** | 第二投三檔行數與圍欄數全部相符，唯獨雜湊不符。審計官重跑後逐行比對執行者貼出的 136 行：**行號序列與內容完全相同**（auditor-protocol 60 條、handover-selftest 39 條、prompt-preflight 12 條、git-and-reporting 8 條、role-boundaries 5 條、PRINCIPLES 5 條、AGENTS 1 條），另試 CRLF 版仍不符。**雜湊把「內容是否相同」綁死在行尾、locale、工具實作這些與內容無關的變數上**——與 B-46 的 CRLF 是同一形狀，審計官在自己設計的閘門上重犯。處置：(e) 段改為純文字比對（行數／圍欄數、項數、**每個修改檔的最後三條 CHECK 10 INFO 行**），已寫進 §6.1 第 18 項 |
| B-66 | 已完成 | **根因定案：審計官的輸出是一次連續生成，宣告卻聲稱它是多步驗證的產物** | 2026-09-06 盤點八批共 16 件錯誤（第二投時已增為 19 件），壓到一層是同一件事——擬定修改、寫錨點、宣告已驗證、寫預期值，四者在同一段生成流裡完成，讀者（含審計官自己）分不出哪些數字來自工具、哪些來自生成。**這解釋了為何加強措辭七週無效**：措辭也是文字，進入同一段生成後被同一個機制繞過。**只有外部產物有效，因為它不是模型生成的**。原則落點 `PRINCIPLES.md` §2.10，排批 2b-4 |
| B-67 | 已完成 | **`scripts/build_prompt_evidence.py`** | 以批次規格為單一來源，產出錨點 `count()` 逐條實測、**E11 清單與總數（由 `len()` 產生）**、(b)(d) 行數與圍欄數、套用到暫存副本後的 (e) 模擬結果，以及 **EXPECT 區塊的 ID 序列驗證**。本批完成 |
| B-68 | 已完成 | **`scripts/impact_scan.py`** | PRE-B01 / governance reliability。B-68 Dependency Closure / Deterministic Impact Scan 已完成 External Macro Audit PASS。正式能力包括：Git tracked deterministic impact discovery、exact dependency evidence、query/result complete closure、missing / phantom fail-closed、semantic disposition by Macro only、UPDATE dependency machine-paired against Allowed Scope、BPE scanner failure fail-closed、canonical CLI truth、Executor pre-mutation replay、S1 DEPENDENCY_DRIFT、S1 DEPENDENCY_SCOPE_MISSING、S1 DEPENDENCY_SCOPE_EXPANSION。External validation chain：2eca candidate → F1-F4 counterexamples reproduced → 34da repair → B-67 output regression discovered → a411 bounded correction → final malformed-scope runtime canary PASS。Final Runtime Canary 證明錯誤 Auditor prompt 將 UPDATE dependency 漏出 Allowed Scope 時，Executor 可在任何 repo mutation 前由 production impact_scan 獨立 fail-closed。B-67 保持已完成。B-41 / B-01 未在 B-68 中開始。 |
| B-69 | 待辦 | **跨環境比對原語規則** | 設計任何比對原語前必須問「換 OS／locale／工具鏈會給出相同答案嗎」；依賴行尾、字元編碼、路徑分隔符、時區、排序或工具實作者不得使用；跨環境一律比對正規化文字而非位元組；Windows PowerShell canonical execution path 明確避免未驗證之 Unix-only 指令（grep、tail、sed、awk），優先採用 Python、Select-String、Get-Content、Select-Object -Last。依 current repo 查證仍具殘留需求，維持待辦。實證補充（2026-09-14 B-41 Cold-Start Discovery）：Antigravity IDE Search 對確實存在的 B-41 兩次回報 false-zero，而以 explicit UTF-8 之 Select-String / Get-Content 均可正常命中，證明 IDE Search zero 不得單獨作為 ABSENT 判據，production dependency discovery 仍以 scripts/impact_scan.py 為權威；本 finding 判定為 non-blocking，不阻擋 B-41 / B-01，不另設新 task。 |
| B-70 | 待辦 | **配對清單改為腳本產生** | 原 B-60 CHECK 編號配置部分已過時，但 pairing-list-by-memory 的核心問題仍存在。current prompt-preflight §3.1 仍為人工維護 pairing table，且 B-45 的 C section ↔ §5.3 residual pairing registration 尚未機械收斂。因此 B-70 保持 genuine pending。本項不是 Pre-B01 blocker，不得因此阻擋 B-01。 |
| B-71 | 可封存 | **零漏網目前不達標，且存在倖存者偏差** | 「零漏網未達標」umbrella 項目；有效殘留風險已各自收納至 concrete tasks (B-31, B-53, B-54, B-87, B-88, B-89)，予以封存且不刪除具體項目 |
| B-72 | 已完成 | **`PRINCIPLES.md` §2.10「每一個數字都必須有它的產生者」** | 使用者 2026-09-06 提出「每次宣告的數據都親自從 GitHub 重新取得」，審計官逐項檢驗 16 件錯誤後修正範圍：**只能修 1 件、部分修 3 件、修不掉 12 件**——審計官本來就每輪重 clone，多數錯誤不是讀取問題而是「寫了沒有產生者的數字」。正確規則為：**寫進提示詞的每一個數字，都必須是本輪某次工具呼叫的輸出**。四種合法來源：repo 現況→新鮮 clone；文件的自我描述（清單長度、項數）→腳本 `len()`；套用後的未來狀態→本地模擬；外部系統狀態→該系統 API。**「從 GitHub 重讀」只是第一種。** 排批 2b-4 |
| B-73 | 已完成 | **`§8.4-2` 的「每輪最多一次 clone」是上限，沒有下限**（**使用者發現**） | 審計官每輪重 clone 靠自律不靠規則，下一個接手者可能用開場那次 clone 撐三輪。處置：`.claude/rules/auditor-protocol.md` §6.1 新增一項補下限「HEAD 可能移動即必須重 clone」，並要求自檢聲明能指出每個數字由哪一次工具呼叫產生。依 §5.7 同批落到 `handover-selftest.md` 與 `prompt-preflight.md` §3.4。排批 2b-4 |
| B-74 | 已完成 | **執行者只回報無法從 commit 重生的東西**（**使用者發現**） | 執行者精簡回報已由 Mechanical-Truth Migration (4c6aee4) 實質完成落地，移除 machine-derived 數字重複比對。 |
| B-75 | 待辦 | **Macro ↔ User ↔ Executor Context Economy** | 範圍由單純樣板重寫擴充精煉為三方上下文經濟性與額度中斷交接協定。核心目標：不降低 correctness、audit independence、evidence quality 或 fail-closed 前提下，降低協作重複上下文與交接負擔；落實 provider-neutral quota interruption recovery 與 Jules 誤觸交接復原協定（repo truth first、no destructive reset、branch-pointer repair、patch replay、dirty-worktree 分流、repo-external phase journal、new-agent takeover prompt，使用者誤觸 Jules Bridge 後已停用該 extension）。保留使用者需求不變量：使用者仍取得一份完整、可一鍵複製給 Antigravity 的提示詞，嚴禁要求使用者手動組裝 prompt fragments。規劃方向：stable boilerplate / contract 優先移入 repo canonical source；最終 prompt 仍為完整單一 artifact；conversation 採 delta-first；已確認 baseline 不反覆重貼；machine-derived raw evidence 留在 repo / GitHub 以 SHA/reference 定位，不搬回 conversation；cold-start/handoff 優先由 canonical router 重建；評估交接提示詞瘦身或 repo-routed bootstrap；原 batch-template.md 保留為候選方案之一。本輪只做 planning-scope refinement，不實作。 |
| B-76 | 可封存 | **審計官的核對階段未腳本化** | 原 audit_verify.py 並未實作；其核心需求已由 canonical verify_all 與 GitHub remote audit workflow 取代。 |
| B-77 | 已完成 | **BPE 的輸出不得被審計官修改** | B-64 的直接推論：BPE 產生證據後若「順手修潤措辭」，就重現「模擬的對象不等於送出的文字」。處置：`.claude/rules/auditor-protocol.md` §6.1 第 18 項延伸一句——**BPE 輸出後不得修改，要改就改批次規格再重跑**。排批 2b-4 |
| B-78 | 待辦 | **`scripts/apply_batch.py`：消除散文這一層有損的重新編碼** | 原 apply_batch.py 未實作；現有 CHECK 17 提供 correctness containment，剩餘價值主要為效率與降低一次性 apply-script parsing，延後主重構後再評估。 |
| B-79 | 已完成 | **零項 CHECK 驗證看板與 backlog 的 ID 序列連續性** | 2026-09-06 實測：`scripts/check_consistency.py` 對 `docs/TASKBOARD.md` **只驗最後更新 HEAD（CHECK 8）**，全庫查無任何驗證 B 節編號連續性的檢查；backlog 的編號點亦同。唯一的守衛是審計官每批手寫的驗證步驟——**那正是「靠記憶」的形狀**。首投的缺號錯誤（缺 B-72／73／74）因此在模擬中 16 項全 PASS，是執行者人工比對抓到的。處置：BPE 新增 **EXPECT 區塊**把「插入後的預期序列」從宣告變成可驗事實（本批完成）；獨立的 **CHECK 25 ID 序列連續性** 排批 2d |
| B-80 | 可封存 | **BPE 的模擬只涵蓋規格中有真實 payload 的修改** | 原 check-only simulation gap 已隨 check-only/手寫 derived-truth authority 消失；現行 source mutation 均以實際 Batch Spec MOD 及 CHECK 17 replay 管理。BPE 本身仍保留。 |
| B-81 | 可封存 | **BPE 的輸出不含錨點原文** | anchor 原文不再需要由 LLM 從 BPE output 重新抄成 blocking truth；BPE 本身仍是 active parser/simulator，不是被廢除。 |
| B-82 | 已完成 | **交接區 §5.4 是一個只追加、從不清理的堆疊** | 每份提示詞只替換第一個項目符號並在其前追加，**從未移除被取代的**，單調成長十輪。2026-09-07 實測 62 行（含標題）、18 個頂層項目符號，其中十條過期或互相矛盾。**本批完成清理，成因見 `docs/refactor-backlog.md` 第 53 點 A 段。惟偵測機制尚未建立**——§5.4 頂層項目符號數上限檢查排批 2d，編號依 B-60 配置 |
| B-83 | 可封存 | **開場動作單次載入 2,338 行** | 開場單次載入 2,338 行之 hot-path 負擔已由 targeted current-state extraction 解決，歷史 rationale 改為 on demand，非 production blocker，可予封存 |
| B-84 | 可封存 | **模擬閘門的觸發條件比它要保護的範圍窄** | 模擬閘門保護範圍已被 CHECK 17 全量 Spec Replay 逐位元比對完全覆蓋取代。 |
| B-85 | 已完成 | **散文是一層有損的重新編碼** | 解決的是散文不得充當 exact mechanical truth（GOAL_SPEC 定義目標邊界，EXACT_SPEC / Batch Spec + CHECK 17 提供 canonical replay）；不宣稱 executor 已有通用 apply_batch.py。 |
| B-86 | 已完成 | **規則層從未說明 BPE 是什麼** | BPE 用法與批次規格（Batch Spec）格式已於 Mechanical-Truth Migration 完整寫入 `.claude/rules/auditor-protocol.md` §6.1 第 21 項，並依 §5.7 同步進 `.claude/rules/handover-selftest.md` E23 與 `.agents/rules/prompt-preflight.md` §3.4 E23。明訂批次規格由 `parse_spec`／`apply_mod_to_text` 解析，BPE 負責單一來源驗證與模擬，消除散文編碼失真 |
| B-87 | 可封存 | **看板狀態與 repo 實際狀態無任何 CHECK 驗證** | comprehensive repo-to-taskboard reconciliation 已完成；original generic path-existence CHECK proposal 明確 superseded / rejected（因 false-green risk 不實作 generic completion inference）；ongoing state integrity 由 B-95 promotion、every-round disposition 與 External Macro Review 維持，可封存 |
| B-88 | 已完成 | **表格被空行斷開，無任何機械偵測** | CHECK 20 + positive/negative canaries 已完成，External Macro Audit PASS。 |
| B-89 | 已完成 | **日文字元混入 repo，四項驗證全綠卻抓不到** | CHECK 14 Japanese extension 已完成，External Macro Audit PASS，原 Simplified-Chinese guard 未 regression。 |
| B-90 | 已完成 | **批次規格格式缺 `create_file` mode** | 已於 B-90 實作完成：`parse_spec` 與 `apply_mod_to_text` 原生支援 `create_file` mode，BPE 支援新建檔案模擬與驗收，CHECK 17 完成新檔逐位元重放，並全面移除 `-BOOTSTRAP.spec.txt` 跳過重放與全庫單一 BOOTSTRAP 限制。歷史規格 `0e13c85` 安全保留為歷史 artifact |
| B-91 | 可封存 | **9 個 `audited-*` tag 歷史留痕保存（退役破壞性遠端清理）** | 9 個錯 tag 刻意作為歷史事故證據保留；audited tag 次系統已退役為 non-authoritative legacy markers（0 remote tag deleted, 0 remote tag rewritten, historical wrong tags intentionally preserved），審計狀態已由 AUDIT-LOG、refactor-backlog §5.1 與 GitHub Actions SSOT 完全接管，不再影響 correctness、audit state、handoff 或 remote health。不需執行破壞性遠端清理。 |
| B-92 | 已完成 | **`docs/EXEC-LOG.md` 與 `docs/fingerprints/exec-latest.json` 作為 CHECK 17 豁免檔的生命週期** | 豁免檔生命週期已修正。`docs/EXEC-LOG.md` 不再採 generic zero-deletion，改採 fail-closed semantic transition validation（支援歷史列不變、回填 parent hash、追加當批紀錄）；`docs/fingerprints/exec-latest.json` 作為 generated snapshot 正確性由 `fingerprint.py --verify` 守護；真實 Git repo 正反例測試已建立 |
| B-93 | 已完成 | **Verification Integrity / False-Green Fail-Closed Hardening** | Verification Integrity / False-Green Fail-Closed Hardening 已完成 External Macro Audit PASS，exact-target final micro-fix closed。 |
| B-94 | 已完成 | **Antigravity Runtime Rule Loadability / UI Freshness Reconciliation** | 執行三層規則機器對帳：repo/disk chars=9973，blob identity PASS（9adda8a）；使用者 IDE reload 後 UI=9973/12000，stale editor buffer 根因確認；Runtime Rule Freshness Reconciliation 正式關閉（CLOSED）。 |
| B-95 | 已完成 | **Material Finding → TASKBOARD Promotion Contract** | Material Finding → TASKBOARD Promotion Contract 已完成 External Macro Audit PASS，same-round persistence / EVERY_ROUND disposition / Executor mechanical preflight 正式生效。 |
| B-96 | 待辦 | **`$$使用者$$` Session-local User Prompt Compiler Mode** | 使用者已完成架構裁決。此功能為僅限目前 Antigravity conversation/session 的 Natural-Language → Governed Execution Adapter；`$$使用者$$` 啟用，沒有 `$$結束使用者$$`，關閉 Agent/conversation 即失效，新 Agent 預設 OFF。User Mode 將輸入分為 READ_ONLY / REPO_MUTATION / EXTERNAL_ACTION / SPECIAL_COMMAND；repo mutation 必須先唯讀 discovery + B-68 impact scan，再編譯完整 production prompt、等待使用者確認，確認後仍通過既有 Prompt Manifest / dependency replay / Allowed Scope / Git / Gate preflight，不構成任何 safety override。特殊 `$$` 指令永遠優先走 `SOP/SOP_00A_Master_Index.json` canonical router。完整已裁決施工規格見 `docs/refactor-backlog.md` Item 63。NOT IMPLEMENTED。 |
| B-97 | 已完成 | **Pre-B01 Comprehensive Pending-Task & Repository Release Audit** | Phase 1 READ_ONLY comprehensive inventory + repository-wide audit completed；41 active-lifecycle rows 全部 disposition；B-01 target readiness PASS；所有 material findings 已依 B-95 routed；PRE-B01 RELEASE PASS。 |
| B-98 | 已完成 | **Executor Secret / Credential Output Hardening** | 2026-09-16 Step 1 READ_ONLY alignment 中，Executor 為查詢 GitHub 狀態列舉環境變數，致使一個 GitHub credential 完整 secret value 輸出至 execution transcript（零 secret value 記錄於 repo）。已完成人工作業遏阻。TG-MVP-06 累積 External Macro Audit PASS（Actions Run 35331712071 success，jobs: verify = success, gateway-windows = success），F1-A、F1-B、F2 全數解決（RESOLVED），無新實質發現（new material finding = NONE），TG-MVP-06 正式 ACCEPTED，accepted checkpoint = e60fedb6fbaade0ec725d28fc83f1e47cfb13943，B-98 正式關閉（CLOSED）；落地包含 secret-safe output binding rule（.agents/rules/secret-output-safety.md SECRET-1..8）、safe presence helper（scripts/secret_presence.py 僅限 PRESENT/ABSENT）、automatic staged scanner（scripts/secret_scan.py 讀 Git index）、tracked pre-commit hook（.githooks/pre-commit）與 CHECK 21 機密防護守衛。 |
| B-99 | 已完成 | **Qualification-Based Macro Auditor & Repo-Visible Handoff** | B-99 Qualification-Based Macro Auditor & Repo-Visible Handoff 已取得 External Macro PASS；ADR-0021 / provider-neutral qualification / exactly-one ACTIVE_MACRO_AUDITOR / user-only assignment / same-session exclusion / A1 FULL_CLONE + strict EQUIVALENT / `.claude/` compatibility path / CHECK 8 singleton 均 accepted。 |
| B-100 | 待辦 | **跨領域營運與治理殘留收斂（Cross-Cutting Operational / Governance Residual Closure）** | 橫向殘留傘狀任務（NONBLOCKING，不阻擋 TG-MVP-02 / B-103A / TG-MVP-12）。涵蓋五大子項：R-A NotebookLM Smart App Control；R-B Actions 證據耐用性與假綠燈保全（Actions Evidence Durability & False-Green Preservation，NONBLOCKING；關鍵事故 raw log 最小決定性 evidence preservation；current retention setting = MUST MACHINE-VERIFY before relying on deadline，critical evidence 必須在實際 retention expiry 前 preservation，未取得 machine evidence 前禁止將 exact retention duration 寫成 current fact；CI 逾時政策觀察記錄為 NON-BLOCKING；B-100 R-01 Actions Windows Known-Folder timeout 觀察為 NON-BLOCKING；D-R4 same-SHA rerun USER ONLY）；R-C 執行者可見語言合約；R-D CI 供應鏈可重現性（含 D-R1 觀察）；R-E 歷史權威檢視。 |
| B-101 | 已完成 | **Gateway Secret Provider & Runtime Secret Consumption Boundary** | External Macro architecture decision 落地 Windows Credential Manager Generic Credential（CRED_TYPE_GENERIC, CRED_PERSIST_LOCAL_MACHINE）作為 Gateway v1 concrete secret provider。實作 provider-neutral contract（secret-provider.js）、Windows concrete provider（windows-credential-manager-provider.js）、Win32 CredReadW/CredFree PowerShell bridge（windows-credential-manager-read.ps1）、ADR-0026、單元測試與 Windows synthetic integration tests。滿足 exact-target lookup、零 store 列舉、零 env fallback、零 Local Config secret、零 AccountRegistry secretRef 突變、fixed named Windows-user identity invariant、runtime-only Buffer 曝光（best-effort consumer zeroization）、零 real credential access。F1–F4 技術與治理修復全數確認解決（RESOLVED），NEW MATERIAL FINDING = NONE，經外部審計官全面核對通過正式結案（External Macro PASS / ACCEPT ALL，Actions Run 35359354510 success）。落地對應：E-03 Roadmap TG-MVP-06A。 |
| B-102 | 已完成 | **INCIDENT-CI-05 治理閘門完整性修復（Governance Gate Integrity Repair）** | CLOSED / RESOLVED；移除 verify.yml fail-open tee 管道；修復 CHECK 16 祖先驗證先決與 --no-merges 移除；擴充 CHECK 22 pipeline 與 required gate 守衛；落地治理凍結不變量；建立 .agents/rules/governance-gate-integrity.md 守護閘門完整性與載入限制；repair candidate 經 External Macro 獨立確認 PASS，squash-merge 至 main，exact-SHA Run 35439883902 verify 與 gateway-windows success，ALL 5 GATES PASSED；正式結案（B-102 = CLOSED, INCIDENT-CI-05 = CLOSED, R6 = RESOLVED）。 |
| B-103 | 已完成 | **C-06 Exact-SHA 快速推進閘門遷移（Exact-SHA Fast-Forward Gate Migration）** | ACCEPTED / CLOSED。T1 same-SHA promotion 經原生釘選 40-char SHA adapter 驗證通過，production-proven；main == e8ee1edc45b26984fd737ffeb7d3283c744dbb4d；post-main exact-SHA Actions Run 35517555366 驗證成功，ALL 5 GATES PASSED；T1-F1～T1-F4 RESOLVED；External Macro Auditor 正式判定 T1 = ACCEPTED / CLOSED，B-103 = ACCEPTED / CLOSED；accepted checkpoint = e8ee1edc45b26984fd737ffeb7d3283c744dbb4d。 |
| B-104 | 已完成 | **舊版 Jules PR 與分支清理（Legacy Jules PR / Branch Cleanup）** | ACCEPTED / CLOSED。PR #13–#24 與 exact 12 head branches 清理完成；經 External Macro 獨立查證：12/12 remote refs absent，PR #13–#24 12/12 closed，0 merged，main 未異動；REMOTE_DELETE_EXACT_SET 單次授權自毀消耗通過（evidence_origin: USER_PROVIDED / DIRECT SCREENSHOT, Test-Path result: False）；使用者已將 Advanced Command Access --delete 恢復為 Deny（evidence_origin: USER_PROVIDED / DIRECT SCREENSHOT，目前 12 entries 全數 Deny）；NEW MATERIAL FINDING = NONE；正式結案。 |
| B-105 | 待辦 | **Jules Mode A 風險掃描啟用（Jules Mode A / Risk-Scan Enablement）** | 待辦（D-U12, D-U16）；Jules 僅為 proposer、不得直接寫 repo；Mode A risk scan 為 primary，Mode B patch proposal deferred；不安裝 Antigravity Jules Bridge / Send2Jules（D-U13）；重啟前置條件：B-10 協作規範、@google/jules-mcp 版本鎖定（ADR-0019 decision 4）、CHECK 21 維持有效；Jules drift 記錄：authorized_mcp_tools 目前無已驗證 harness enforcement，jules-integration 仍指向 disabled Bridge，Jules capability semantics 留至 M4，本輪不得啟用 Jules。 |
| B-106 | 已完成 | **Actual Loaded-Surface Budget & Rule Compatibility Guard** | ACCEPTED / CLOSED。Minimal Verified Runtime Kernel accepted；Loaded-Surface Mechanical Guard accepted；fresh-session no-tools canary PASS（HH_AI_V2_KERNEL_CANARY_V1_260922，evidence_origin: USER_PROVIDED / DIRECT SCREENSHOT）；IDE 2.5.5 runtime evidence；B-106 closed via B-109 M3 acceptance。 |
| B-107 | 待辦 | **Deterministic Consistency Diagnostics & Guarded State-Log Mutation** | 待辦（OPEN / RESIDUAL，NON-BLOCKING FOR CURRENT E-03 RETURN；依 K2-A 與使用者 Option B 正式裁決，舊 Phase-E 歷史分類不作當前 E-03 回歸之阻擋條件；保留 OPEN，不得提前 CLOSED）。納入 M2-P1（status reporting inconsistency）、M2-P2（unapproved transcript-file access confirmed）、M3-P1（pre-mutation preflight reporting/evidence gap）、M3-P2（task-specific execution evidence generalization gap）、M2-P2 recurrence（unapproved brain/session-log access confirmed during prompt recovery, cross-session NOT_ESTABLISHED, secret exposure NOT_ESTABLISHED, repo mutation NONE）、TG-MVP-10 R0 development test-process hygiene incident（USER_PROVIDED evidence, 7 hung adapter test node processes, USER cleanup count=0）、TG-MVP-10 R2 test-process hygiene incident（USER_PROVIDED evidence, 3 residual test processes PIDs 4428, 17476, 14840, USER cleanup count=0, reporting mismatch M2-P1 recurrence）、TG-MVP-10 R2 10/10 突變測試過度宣告更正、TG-MVP-10 R3 test hang process hygiene incident（M3 TEST_HANG confirmed, first focused test hung on microtask starvation, 4 owned node processes PIDs 3080, 3732, 1356, 23960 terminated, MATCHING_TEST_PROCESS_COUNT=0, R3 TEST_HANG occurred: YES）、TG-MVP-10 R3 突變測試數量標籤更正（SM1–SM15 = 15/15 valid semantic RED，歷史 16/16 count-label inconsistency 登錄 B-107，無 SM16）處置留痕；以及 TG-MVP-11 diagnostic/process-evidence recurrence（during local-api-client diagnosis, direct `node -e` commands were executed outside the required bounded runner before External Macro correction；direct-node bounded-runner bypass: CONFIRMED；repo mutation caused by Verification Required: NOT ESTABLISHED；secret exposure: NOT ESTABLISHED；cross-session access: NOT ESTABLISHED；external IDE/account verification root cause: OUTSIDE REPO / NOT ESTABLISHED BY EXECUTOR；subsequent Node diagnostics: BOUNDED RUNNER REQUIRED；B-107 remains: OPEN / RESIDUAL / NON-BLOCKING FOR CURRENT E-03 RETURN）；以及 TG-MVP-11 Antigravity Verification Required 第二次再發留痕（during T1-T23 mutation execution, observed after T23 mutation work；external IDE/account interruption: CONFIRMED；repo root cause: NOT ESTABLISHED；repo mutation caused by Verification Required: NOT ESTABLISHED；secret exposure: NOT ESTABLISHED；cross-session access: NOT ESTABLISHED；bounded-runner bypass after Root-Cause Recovery Addendum v2: NONE ESTABLISHED；visible T23 run: TIMEOUT=NO, OWNED_PROCESS_REMAINING=0；B-107 remains: OPEN / RESIDUAL / NON-BLOCKING FOR CURRENT E-03 RETURN；The IDE interruption is not itself a TG-MVP-11 implementation failure）；以及 TG-MVP-11 R1 direct node -e diagnostics process-hygiene recurrence（during R1 diagnostic inspection, two direct node -e commands were executed outside bounded runner; direct-node bounded-runner bypass: CONFIRMED; repo mutation: NONE ESTABLISHED; secret exposure: NOT ESTABLISHED; cross-session access: NOT ESTABLISHED; residual process: NONE ESTABLISHED; routed to EXISTING B-107, no new backlog ID, B-107 remains: OPEN / RESIDUAL / NON-BLOCKING FOR CURRENT E-03 RETURN）；以及 TG-MVP-12 執行期間直接調用 node -e 診斷命令之程序異常分流至 EXISTING B-107（direct-node bounded-runner bypass: CONFIRMED；repo unauthorized mutation: NONE ESTABLISHED；secret exposure: NOT ESTABLISHED；cross-session access: NOT ESTABLISHED；residual process: NONE ESTABLISHED；routed to EXISTING B-107，NONBLOCKING）；以及 scripts/execution_record.py 現行產生器寫死通用 M2 discovery SHA（4cd2851da921aab9d371b281f51947e2645b069d38ee56655e37a79c2ded3b4b）而非 TG-MVP-12 E24 raw（46f1079fd8cbd5e40a66c40e6ed77feede37b14810eb5d1c870f1bf621b760b2）之 task-specific evidence generalization gap 分流至 EXISTING B-107（OPEN / RESIDUAL / NONBLOCKING）；以及 TG-MVP-12 R1 prompt recovery / inspection 期間執行者讀取 Antigravity current-session .system_generated/logs/transcript.jsonl 與 transcript_full.jsonl 抽取 USER_INPUT / prompt text 之程序治理異常分流至 EXISTING B-107（External Macro disposition: unapproved transcript-file access = CONFIRMED, brain/session-log access = CONFIRMED, cross-session access = NOT_ESTABLISHED, secret exposure = NOT_ESTABLISHED, unauthorized repository mutation caused by access = NONE ESTABLISHED, blocking for TG-MVP-12 = NO, route = EXISTING B-107, new backlog ID = NONE, Evidence provenance: USER_PROVIDED / Executor command transcript reviewed by External Macro Auditor, B-107 remains: OPEN / RESIDUAL / NON-BLOCKING FOR CURRENT E-03 RETURN）；保留未來未被 M2/M3 完成之 B-107 residual；EVIDENCE-ORIGIN 確立 MACHINE_CAPTURED_RAW、MACHINE_DERIVED、AGENT_ASSERTED、USER_PROVIDED 四類；REG-11～13 證據完整性標準與 CHECK 26 重放已由 M2 實作；CHECK 9 parser 與 negative controls 等已由 M2 實作。 |
| B-108 | 待辦 | **Unauthorized Destructive Local Git Reset Guard** | 待辦（TODO / NOT CLOSED，作為 mechanical guard / cleanup owner）。K6-A UI 態勢更新為 PERSISTENT LAYER = APPLIED（USER_PROVIDED，IDE 2.5.5，包含 File Access 減量、MCP permanent Allow 減量、GitHub MCP 18 disabled、Advanced Command Access 12 entries 設為 Deny（其中 git credential / git reset 為直接重啟驗證，其餘 10 為同機制推論）、Execute URLs github.com = Deny（保留 entry 設 Deny））；舊「Deny List Terminal Commands」正式標記為 DEPRECATED / NON-PERSISTENT / DO NOT USE；Execute URLs delete-to-restrict 標記為 NON-PERSISTENT / DO NOT USE；基準與手動恢復檢核清單見 docs/ops/antigravity-environment-baseline.md；保留歷史事故實例；登錄低優先 Legacy Antigravity permission cleanup 留待 future bounded cleanup。 |
| B-109 | 已完成 | **Mechanical Governance v1** | ACCEPTED / CLOSED（M1 ACCEPTED / CLOSED；M2 ACCEPTED / CLOSED；M3 ACCEPTED / CLOSED；M4 ACCEPTED / CLOSED；B-109 overall ACCEPTED / CLOSED）。M4 final implementation SHA = cfc6249edd79a14990207d68c9e86644c83fbc0e，candidate Actions Run 36097483288（verify=completed/success, gateway-windows=completed/success），post-main exact-SHA Actions Run 36098739268（verify=completed/success, gateway-windows=completed/success，ALL 5 GATES PASSED，Windows 29 passed）；M4 實作 governance_preflight.py 顯式互斥操作模式（--prompt-file, --verify-push, --create-main-auth, --create-delete-auth），徹底移除裸呼叫之隱式 stdin fallback，解決 Antigravity 背景執行 open stdin 懸掛根因；涵蓋 open-pipe regression 測試、反事實突變金絲雀證明、規則文件更新；External Macro Auditor 獨立審查判定 ACCEPT ALL；same-SHA main promotion 成功推進；B-109 M4 與 B-109 機械治理全面結案。採用 K4-A 單一寫入點收斂（docs/TASKBOARD.md 保持 remaining-work authority，docs/refactor-backlog.md §5.4 收斂為 pointer-only，state_authority_policy 與 runtime_surface_policy 落地）；B-106 Minimal Verified Runtime Kernel 落地結案；current routing 以本檔頂部 NEXT_WORK / NEXT_SLICE 欄位為唯一動態權威；B-107 保持 OPEN；B-108 保持 OPEN；google-jules 保持 DISABLED（本輪不啟用 Jules）。 |

---

## C. 待使用者裁決

| ID | 狀態 | 事項 | 審計官建議 |
|---|---|---|---|
| C-01 | 已裁決 | **Port 分配（原記「三方衝突」，實測為 11 個 port）** | **2026-09-06 使用者裁決**：以 ADR-0017 為準，處置範圍由兩處擴大為七處。playwright 掃描清單採「明確指定目標 port 而非自動掃描」。**原記載的「`SOP_06` 第 100 行」有誤**——實測第 100 行與 ADR-0017 一致、非衝突，真正衝突在第 133 行。執行排批 4，詳見 `refactor-backlog.md` 第 46 點 |
| C-02 | 已裁決 | **`SOP_02` 清歷史違反第 1 層規則** | **2026-09-06 使用者裁決採用甲案**：改為「不得 force push。已推送的憑證一律視為永久洩漏，處置為立即撤銷與輪換。撤銷後若仍要清理歷史，必須由使用者本人執行，任何 agent 不得代勞，並在 backlog 留記錄」。技術依據：Push Protection 觸發時內容已達 GitHub 伺服器，清歷史是清理不是補救。執行排批 4 |
| C-03 | 已裁決 | **ADR-0013 處置** | **2026-09-06 使用者裁決採用甲案**（逐節處置）：§1／§2ABD／§7 棄用並註明去向；**§2C BOM 污染偵測實作為新 CHECK**（實測 `scripts/*.py` 查無 BOM 偵測，未被取代）；§3 安全邊界搬進 `.agents/rules/role-boundaries.md`；§4／§5 凍結待 E-03；**§6 觸發詞排他性矩陣獨立為 B-32**。執行排批 4 |
| C-04 | 已裁決（方向） | **攔截項三：Runtime 層架構選擇** | **2026-09-06 使用者裁決方向**：採 `runtime/`（常駐服務程式碼）＋ `shared/`（共用模組）＋ `skills/`（只放技能文件）三層。此結構與上游 `mattpocock/skills` 的組織原則一致（`skills/` 只放技能，其餘各有頂層目錄），但 **`runtime/` 與 `shared/` 為本專案自訂，上游無對應物**——上游是純技能 repo，無任何常駐服務。**細節（PM2 六進程、`Modules/` 18 檔、`scripts/` 16 檔的實際依賴關係與硬編碼路徑）待批 6 調研後再裁決**。見 `refactor-backlog.md` §二 C 節與 `docs/adr/0015-line-tunnel-chain-failure.md` |
| C-05 | 已裁決 | **D-01 E1 的判定者** | §9.4 原規定驗證階段判定者為「留任的舊 Agent」，但設計 E1 題目的 session 已離場。**2026-09-05 使用者裁決採用**：題目與答案卷由使用者保管，判定者為現任審計官——判定者既非出題者亦非受測者，較原設計更乾淨 |
| C-06 | 已裁決 | **是否將 GitHub Verify 升級為 main 的 preventive required check** | **歷史裁決 Option B 建立 preventive GitHub gate 曾採 Require PR，後由 D-U9 / B-103 / K1-A 對 transport mechanism 進一步 refine/supersede**：現行伺服端保護權威為 GitHub ruleset 21301111 required status checks（verify 與 gateway-windows 嚴格模式），pull_request 規則已於 B-103 Phase C 移除；當前傳輸模式收斂為 batch candidate → exact-SHA required checks → origin/main no drift + ancestry → one explicitly selected available adapter → SAME SHA pure fast-forward → post-main same-SHA CI；Require PR 不再是 current mandatory transport。歷史事故 INCIDENT-CI-04 為最早推動 preventive gate 之依據。 |
| C-07 | 已裁決 | **歷史待辦 B-17 / B-28 / B-29 處置決策（ARCHIVE vs TRIGGER_BASED_DEFERRED）** | **2026-09-18 使用者裁決**：原採 `TRIGGER_BASED_DEFERRED`（不封存）。B-17（章節語意變更偵測）維持 TRIGGER_BASED_DEFERRED；B-28（`AGENTS.md` 上游規範版本記錄）與 B-29（上游一致性對照表與機械檢查）已於 2026-09-20 由使用者 U2 正式重啟（REOPENED BY USER U2 / PENDING），不重啟 B-17；U1/U3 由 B-109 與 R0 承接，不強塞入 C-07。 |
| C-08 | 已裁決 | **Data/logs 歷史檔案處置決策（repo-external 保留 vs 封存 vs 刪除）** | **2026-09-18 使用者裁決**：採 `REPO_EXTERNAL_QUARANTINE_THEN_DELETE`。依 D-U2 規範，個人工作資料與日誌（Persona 個人內容、Agent_Reflections、TODO、reports、logs、Data/logs）絕對不得進入 `HH.AI_v2` repo。現況處置為 repo-external 隔離檢疫；後續僅在 E-05 查證確認無任何必要引用需求且無法律／取證保留需求後，始得授權執行最終刪除（非立即刪除）。本批不刪除任何使用者資料。 |

---

## D. 驗證階段（§9.5）

| ID | 狀態 | 事項 |
|---|---|---|
| D-01 | 已完成 | **E1 注入測試**——拋棄式對話，四題，判定者為留任的審計官。**題目與答案卷刻意不進 repo（見 §9.5），由使用者保管。** 2026-09-12 執行完成，判定 E1 = PASS |
| D-02 | 已完成 | **E2 正式交接**——Formal Production Handoff PASS。新 Agent 接手前置驗證已完成，後續常態工作由 TASKBOARD.NEXT_WORK 導航 |
| D-03 | 可封存 | **E3 補洞**——僅在前置 validation 失敗時需要；前置驗證已 PASS，予以可封存建議；未來若重啟驗證須由 TASKBOARD routing 明確指定 |

---

## E. 舊 repo 遷移主線（`refactor-backlog.md` §二 A–F）

> 這一節是整個重構的主要工作量，此前完全未列入看板。

| ID | 狀態 | 項目 | 備註 |
|---|---|---|---|
| E-01 | 待辦 | 技能尚未遷移（§二 A 節） | 逐一比對 A-1「確定要遷移的」清單；dynamic-tool-synthesizer 標記 RE-EVALUATE（Persona Knowledge MCP 已裁決不補回，原 invocation assumptions 須在 M4 / skill exploration 重新驗證） |
| E-02 | 待辦 | Persona 認知顧問 15 個（§二 B 節） | 架構已定為方案 A（設定檔非技能，不放 `skills/`），遷移未執行 |
| E-03 | 進行中 | **Runtime 執行層（§二 C 節）** | 詳細切片生命週期、架構狀態與進度之單一事實來源請見下方「E-03 ROADMAP — CANONICAL CURRENT-STATE AUTHORITY」；看板頂層列不再維護長動態副本與動態切片數值。 |
| E-04 | 待辦 | `$$` 指令定義收斂（§二 D 節） | `$$LINE連線$$`／`$$TG連線$$` 散落三個檔案且內容互相矛盾；依 ADR-0022/D14 於 Gateway 正式 cutover 時才切換路由（落地對應：E-03 Roadmap TG-CUT-01） |
| E-05 | 待辦 | Data/ 資料層逐項裁決（§二 E 節） | Data/logs 處置已由使用者裁決為 REPO_EXTERNAL_QUARANTINE_THEN_DELETE（C-08，個人工作資料依 D-U2 不得遷入 repo，repo-external 隔離，確認無引用/法規保留需求後始得刪除）；尚有 `reports/`、`Agent_Reflections.md`、`TODO.md`、`Execution_Plans/`、`_archive_legacy_docs/` 待逐項處置 |


### E-03 執行層專屬路線圖（E-03 ROADMAP — CANONICAL CURRENT-STATE AUTHORITY）

> **單一事實來源宣告**：本區塊為 E-03 執行層當前詳細生命週期、架構決策與實作切片進度之唯一權威來源。
> 看板「最後更新」與 E-03 頂層任務列僅保留精簡指標，不重複複製長動態狀態。
> **全新 Agent 冷啟動三步驟契約**：
> 1. 先讀本 Roadmap 是否存在「狀態 = 進行中」的切片；
> 2. 若存在（如當前 `TG-MVP-01A`）：不得執行頂部 `NEXT_SLICE`，必須等待該 active slice 完成 External Macro closure；
> 3. 若不存在進行中切片：始得依據看板頂部 `NEXT_SLICE` 指標執行下一個切片。
> **架構決策狀態**：
> - **R2（安全重試 ＋ 持久化 Outbox）**：`USER DECIDED / CANONICAL ARCHITECTURE LANDED IN ADR-0025 / IMPLEMENTED / ACCEPTED IN TG-MVP-12`（final implementation SHA: `8ea3fc6e1301f077ee467174981f0e63978c2de3`）。
> - **R3（Loopback HTTP v1 127.0.0.1 HMAC 授權）**：`USER DECIDED / CANONICAL ARCHITECTURE LANDED IN ADR-0025 / IMPLEMENTED / ACCEPTED IN TG-MVP-11`（Named Pipe 未獲選/延後）。
> - **R2-3（配送不確定通知）**：`USER DECIDED OPTION B / ADR-0025 LANDED`（Gateway 持久化，Agent 於 IDE 查看，手機不推播）。
> - **D-U4（Telegram MVP 邊界）**：僅限文字收發（text in/out）、接管（takeover）、封存（archive）；D17 附件與 D19–D21 外發檔案排除。
> - **D-U2 / D-U6 / D-U7**：`USER DECIDED / LANDED IN TG-MVP-01B`（個人資料不進 repo、分級審查、MISSION 切換定義）。
> - **D-U9（Future C-06 傳輸模式）**：batch branch → exact branch SHA required checks → fast-forward SAME SHA to main，由 B-103 staged migration 落地。
> - **D-U10（Pipeline Guard & Required Gate Integrity）**：已由現行 check_consistency 實作完整存在，不得重作。
> - **D-U11（Secret Scan 狀態）**：現行 CHECK 21 secret_scan 滿足需求（ALREADY SATISFIED），不新增 secret scanner。
> - **D-U12（Jules 角色定位）**：Jules 僅為 proposer，不得直接寫 repo；Mode A risk scan 為 primary，Mode B patch proposal deferred。
> - **D-U13（Bridge 工具政策）**：不安裝 Antigravity Jules Bridge、Send2Jules。
> - **D-U14（B-104 清理授權路由）**：使用者明確授權之清理範圍僅限 open PR #13–#24 及其 12 條 exact head branches（U-A），本輪不執行 cleanup。
> - **D-U15（F-03 LOOP-lite 流程）**：POST-MVP，採 Jules proposes → Executor reauthors → Macro judges，禁止 auto merge。
> - **D-U16（Jules 重啟前置條件）**：B-10 協作規範、@google/jules-mcp 版本鎖定（ADR-0019 decision 4）、CHECK 21 維持有效，建立 B-105 路由。
> - **D-TG11-3（初始活躍 Telegram 帳號規則）**：`USER DECIDED 2026-09-25 / EXACTLY ONE ENABLED ACCOUNT`（恰好 1 個啟用帳號 -> register + setActive；0 個或 >= 2 個 fail closed，stderr: GATEWAY_CONFIG_ERROR；禁止陣列順序選取或隨機選取；無 Local Config 綱要變更；無新增倉儲方法；未來多帳號/activeAccountId 留待未來使用者裁決）。
> - **D-R1（跨平台生產行為與 WSL 閘門）**：`USER DECIDED`（跨平台生產行為採用明確依賴/平台注入；絕不從 CI 宿主 process.platform 推斷應用語意；平台敏感切片必須具備有界針對性 WSL 閘門）。
> - **D-R3-A+（Telegram 429 retry_after 安全政策）**：`USER DECIDED`（retry_after 合法整數秒 1..2147483647；無效值一律 FAILED_TERMINAL / TELEGRAM_RETRY_AFTER_INVALID；嚴禁 clamp、嚴禁盲目重送）。
> - **D-R3-C1（全域 24 小時 QUEUED 交付窗口）**：`USER DECIDED`（TELEGRAM_DELIVERY_WINDOW_SEC=86400；所有 Telegram QUEUED 指令受全域窗口約束；逾期 QUEUED 於進入 IN_FLIGHT 前終態過期；IN_FLIGHT/UNCERTAIN 不受影響）。
> - **D-R3-REPLY-A（嚴格原生回覆）**：`USER DECIDED`（Strict Native Reply；reply_parameters.message_id 強制由 logical_reply_target 解析；禁止 allow_sending_without_reply；原訊息被刪除時不得回退為普通發送）。
> - **D-R4（同 SHA CI 重跑約束）**：`USER DECIDED`（same-SHA CI rerun 為 USER ONLY，禁止執行者自行重試）。
> - **U-A / U-B**：PR #13–#24 及其 branches 授權於未來 B-104 清理；2026-09-19 三筆 historical failure workflow re-run 由使用者本人操作，非 Executor 違規。

#### 1. M-TG-MVP（Telegram MVP 第一版核心）

| Slice | 狀態 | 目標 | 依據／權威 | 前置相依 | 完成證據 |
|---|---|---|---|---|---|
| TG-MVP-01 | 已完成 | **G1 路線圖真相重整**（G1 Route Truth Reconciliation）：同步 T8B 審查通過、推進 checkpoint 至 a456343、升格重大發現（F1、C1/C2/C3、INCIDENT-CI-04）、記錄使用者裁決（R2/R3/C-06 等）、去重動態狀態字串。 | G1 規格書、D-U4、B-68 | T8B Final Macro PASS (`a45634386d5abff5766c6af8af8f084fd4a15fed`) | commit `0cc4dfc69d7cc7d9e8eebf6e3eceb21e34794534`，Actions Run 35247744577 success，External Macro PASS（T8B & G1 accepted checkpoint = `0cc4dfc69d7cc7d9e8eebf6e3eceb21e34794534`） |
| TG-MVP-01A | 已完成 | **RECON-01 歷史待辦需求機械對帳與治理收斂**（RECON-01 Historical Pending Requirement Reconciliation）：對帳歷史待辦事項（A–S）、過期架構標記（STALE-1..3）、孤兒需求（ORPHAN-1..4）至權威落點；同步 G1 審核通過裁決與 checkpoint；建立 M-TG-POST-MVP 與橫向殘留傘狀任務；零生產程式碼修改。 | RECON-01 規格書、使用者授權 | TG-MVP-01 | commit 1f98818af8ed38df2b3401685deee159e11a2080，Actions Run 35295573430 success，External Macro PASS / ACCEPT ALL（accepted checkpoint = 1f98818af8ed38df2b3401685deee159e11a2080） |
| TG-MVP-01B | 已完成 | **G2 權威規則落地與 C-06 預防性 GitHub Gate**（G2 Authority Landing & Preventive GitHub Gate）：落實使用者已裁決之治理與架構規則；B-102 事故已修復結案；B-103 傳輸遷移已完成（T1 same-SHA promotion 已取得 production proof，main == e8ee1edc45b26984fd737ffeb7d3283c744dbb4d，post-main Run 35517555366 ALL 5 GATES PASSED，External Macro Auditor 正式判定 ACCEPT ALL）；TG-MVP-01B 正式結案（ACCEPTED / CLOSED）。 | 使用者裁決 D-U2、D-U6、D-U7、C-06 Option B、C-07、C-08、B-100 R-D | TG-MVP-06A (ACCEPTED / CLOSED) | G2 治理文件、CHECK 22、遠端 GitHub Ruleset 與 T1 same-SHA production proof 落地驗證 |
| TG-MVP-02 | 已完成 | **入站事件身份識別與游標語意 ADR**（Inbound Identity & Cursor Semantics ADR）：確立 Telegram 與 LINE 之 `platform_msg_id`、`cursor_value`、編輯/收回（edit/unsend）策略與游標比較器規範，確立 C3 權威定義。 | C3 / C1 / C2 設計缺口、ADR-0023 | TG-MVP-01A (RECON-01) | commit 93a316f93dadf6e5a1199dc7da0542016742112c，Actions Run 35304018843 success，External Macro PASS / ACCEPT ALL（accepted checkpoint = 93a316f93dadf6e5a1199dc7da0542016742112c） |
| TG-MVP-03 | 已完成 | **R2/R3 架構決策 ADR 落地**（R2/R3 Architecture ADR）：記錄 R2（Capability-Aware Retry + Durable Outbox）與 R3（Loopback HTTP v1 127.0.0.1 HMAC；Named Pipe 延後；R2-3 Option B IDE 查看）決策。注意：僅 ADR 落地，不含程式碼實作。 | 使用者正式裁決 R2、R3、R2-3、ADR-0022 | TG-MVP-01 (G1) | commit `4db5d498fa035e14c8628540ce269627aa038ea1`，Actions Run 35306399675 success，External Macro PASS / ACCEPT ALL（TG-MVP-03-F1 RESOLVED，accepted checkpoint = `4db5d498fa035e14c8628540ce269627aa038ea1`） |
| TG-MVP-04 | 已完成 | **F1 回覆授權身份鍵修復**（F1 Reply Authorization Identity Repair）：修正 `validateReplyAuthorization()` SQL 查詢，將單純 `channel_id + platform_msg_id` 查找改為納入 `account_id`，對齊 schema v3 `UNIQUE(account_id, platform_msg_id)` 複合鍵，避免合法回覆被誤判 ACCOUNT_MISMATCH。 | F1 Material Finding、schema v3 inbox 定義 | TG-MVP-02 (Identity ADR) | commit `18867eb5af7c4b90df8946c22977350bf7ec5086`，Actions Run 35307539503 success，External Macro PASS / ACCEPT ALL（accepted checkpoint = `18867eb5af7c4b90df8946c22977350bf7ec5086`） |
| TG-MVP-05 | 已完成 | **游標與事件身份執行層修復**（Cursor / event identity runtime repair）：實作 SQLite Schema v4 與 inbound_event 表、任意長度十進位游標比較器、事件去重身分分離與 LINE 無游標相容性。 | C1 / C2 / C3、TG-MVP-02 ADR (ADR-0024) | TG-MVP-02, TG-MVP-04 | commit `cdd9d7c5eeca5185e47e7365d42a3a3dc0a61eb1`，Actions Run 35311601796 success，External Macro PASS / ACCEPT ALL（TG-MVP-05-F1 RESOLVED，accepted checkpoint = `cdd9d7c5eeca5185e47e7365d42a3a3dc0a61eb1`） |
| TG-MVP-06 | 已完成 | **B-98 憑證與機密強化**（B-98 Secret/Credential Hardening）：在啟用真實 Telegram Bot Token 或 Local API HMAC secret 前，落實金鑰與機密存取安全邊界，防止 token 洩漏。 | 看板 B-98、安全防護原則 | TG-MVP-01 (G1) | commit e60fedb6fbaade0ec725d28fc83f1e47cfb13943，Actions Run 35331712071 success（jobs: verify = success, gateway-windows = success），External Macro PASS / ACCEPT ALL（F1-A, F1-B, F2 RESOLVED，accepted checkpoint = e60fedb6fbaade0ec725d28fc83f1e47cfb13943），B-98 CLOSED |
| TG-MVP-06A | 已完成 | **Gateway 機密提供者與執行期機密取用邊界**（Gateway Secret Provider & Runtime Secret Consumption Boundary）：基於 B-101、ADR-0022 D26、ADR-0025 §15，選定並落實 concrete repo-external / OS-backed Gateway secret provider 與 runtime consumption boundary。 | B-101、ADR-0022 D26、ADR-0025 §15 | TG-MVP-06 | Windows Credential Manager Generic Credential（CRED_PERSIST_LOCAL_MACHINE）落地實作；ADR-0026；exact canonical target lookup；零列舉；零 env fallback；零 Local Config secret；零 AccountRegistry secretRef 突變；zero npm dependency；fixed named Windows-user identity invariant；runtime-only Buffer（best-effort consumer zeroization）；synthetic-only Windows integration tests；F1-A/C/H1 = RESOLVED；F2-A/B = RESOLVED；F3 = RESOLVED；F4 = RESOLVED；NEW MATERIAL FINDING = NONE；全數測試 PASS；經外部審計官核對通過（External Macro PASS / ACCEPT ALL，Actions Run 35359354510 success），TG-MVP-06A 正式結案（ACCEPTED / CLOSED），accepted checkpoint = fe9b507aaccd64222934b0ed1eebe0225fb707a2 |
| TG-MVP-07 | 已完成 | **B-30 + B-33 Gateway 固定通訊埠與顯式目標收斂**（Gateway fixed port / explicit target convergence）：清理舊 repo 殘留之 port 3000/3001 衝突，確立 Gateway 專屬監聽 port 與目標端點規範。 | 看板 B-30、B-33、ADR-0022 | ACCEPTED / CLOSED；commit `f73a076d5ef4184735a6586a7069c66a6ba54bcc`，candidate Run 35754936655 success，post-main Run 35802245822 success；External Macro PASS / ACCEPT ALL；accepted checkpoint = `f73a076d5ef4184735a6586a7069c66a6ba54bcc`。 | Port 配置統一，無殘留衝突硬編碼 |
| TG-MVP-07A | 已完成 | **D24 本機外部配置基礎建設**（D24 Repo-External Local Configuration Foundation）：實作中央本機外部設定檔載入與驗證，涵蓋 archive root、attachment temp、SQLite state path、logs、protected roots 清單、Gateway local port、Windows Known-Folder 預設值與啟動 fail-closed 防護。 | ADR-0022 D24 | ACCEPTED / CLOSED；final implementation SHA `6fc880947af0a65f356857f92aed606da5404505`；revision_count 2；candidate Run 35815942965 success；post-main Run 35816688934 success；External Macro PASS / ACCEPT ALL；accepted checkpoint = `6fc880947af0a65f356857f92aed606da5404505`；Local Config v2、gateway.localPort 3003、Windows Known-Folder defaults、startup fail closed / zero auto-create、no listener。 | Local config loader 完整測試通過 |
| TG-MVP-08 | 已完成 | **T9 封存並退役舊版凍結 JSON 運作模組**（T9 retire frozen JSON operational modules）：退役舊版基於 JSON 檔案的通道狀態模組，全面轉移至 SQLite Repository。 | 看板 E-03、ADR-0022、ADR-0023 | TG-MVP-07A ACCEPTED / CLOSED | ACCEPTED / CLOSED；final implementation SHA bcc59d976dd5510108bcd15917a91249fdf35411；candidate Run 35823024382 success；post-main Run 35823862270 success；External Macro PASS / ACCEPT ALL；accepted checkpoint = bcc59d976dd5510108bcd15917a91249fdf35411；three frozen JSON core modules deleted；three dedicated legacy suites deleted；zero replacement / shim / fallback；SQLite sole operational state authority；anti-resurrection guard accepted；no real user-data migration。 |
| TG-MVP-09 | 已完成 | **T11-main 正式線上備份整合**（T11-main）：保持 repo 既有定義，將 T11A 所驗證之 SQLite online backup primitive 整合進正式運作流程與備份排程。 | T11A 完成證據、SQLite 線上備份規範、ADR-0023 | TG-MVP-08 ACCEPTED / CLOSED | ACCEPTED / CLOSED；final implementation SHA 2e34380663fade80f3a39d4fdb6dacde8a26d9a1；initial candidate 6f2b6e8bd736399876a7ffe48cd703668f3937d8（Run 35842563580，Macro HOLD，F1–F5）；R1 candidate 2e34380663fade80f3a39d4fdb6dacde8a26d9a1（Run 35848844279，F1–F5 RESOLVED，Macro PASS / ACCEPT ALL，promotion eligible PASS）；same-SHA main promotion 成功推進；post-main exact-SHA Run 35849896893 驗證成功（verify success，gateway-windows success）；T11-main operational periodic verified backup integration complete；T11A primitive unchanged；24h freshness threshold (86_400_000 ms)；1h overdue check (3_600_000 ms)；startup overdue catch-up；no unconditional startup backup；no shutdown backup；overlap skip；periodic failure non-fatal；bounded non-secret logging；verified backup return contract validation；UUID-v4 canonical backup filename；provisional in-process owner (BackupRuntimeOwner)；no second daemon；Local Config schema remains v2；zero retention / cleanup in TG-MVP-09；TG-MVP-09A MUST COMPLETE BEFORE REAL TELEGRAM GO-LIVE。 |
| TG-MVP-09A | 已完成 | **狀態資料庫與備份清理衛生規範**（State Database & Backup Hygiene）：實作 SQLite 路徑 repo-external 強制驗證、repo state 檔案 ignore 防護（.gitignore *.sqlite3 等）、遷移備份保留期限（retention）、備份清理（cleanup）、備份隱私與完整性防護，並建立 future node:sqlite 穩定性與 Node 升級守望點。**HARD GO-LIVE GATE AFTER TG-MVP-09：必須在 real Telegram go-live 前完成**。 | ORPHAN-1、ORPHAN-2、ORPHAN-4、ADR-0023 | TG-MVP-09, TG-MVP-07A | ACCEPTED / CLOSED；final implementation SHA `c6cd9c9986f5834b9777197c7c0012c08d85a3bb`；R0 `50503a5dd33e8092e153c6f8f3255594449b9cfb`（Run 35965479245，Macro HOLD / cross-platform test harness repair）；R1 `c1763878aef3c0d87a0a3eddbcf3c3956f55eb19`（Run 35969326893，Macro HOLD，F1–F3）；R2 `c6cd9c9986f5834b9777197c7c0012c08d85a3bb`（Run 35974805223，F1/F2/F3 RESOLVED，Macro PASS / ACCEPT ALL）；mutation proof M3/M4/M5/M10 = RED；same-SHA promotion ACCEPTED；post-main Run 35976037151 verify success, gateway-windows success；TG-MVP-09A hard go-live gate SATISFIED / CLOSED。 |
| TG-MVP-10 | 已完成 | **Telegram 測試機器人入站適配器**（Telegram Test-Bot inbound adapter）：實作 Telegram 長輪詢（long polling）入站適配器，將 Telegram update 轉換為標準 inbox 訊息並呼叫 `ingestMessage()`。 | ADR-0022、TG-MVP-02 (Identity ADR)、TG-MVP-06 (B-98) | TG-MVP-02, TG-MVP-05, TG-MVP-06, TG-MVP-06A | ACCEPTED / CLOSED；final implementation SHA `fde3121c93fe1e25f6802cff2f48a51a253c383c`；candidate Actions Run 36092485633 success；post-main exact-SHA Run 36093663314 success（verify=completed/success, gateway-windows=completed/success）；External Macro PASS / ACCEPT ALL，R3-F1～R3-F8 全數 RESOLVED，NEW MATERIAL BLOCKING FINDING = NONE；SM1–SM15 = 15/15 valid semantic RED（16/16 count-label inconsistency 登錄 B-107，不重啟 TG-MVP-10）；single-use main auth 消耗通過；same-SHA main promotion 完成；accepted checkpoint = `fde3121c93fe1e25f6802cff2f48a51a253c383c`。 |
| TG-MVP-11 | 已完成 | **迴路 Local API v1 實作**（Loopback Local API v1）：實作僅限 127.0.0.1 監聽、具 HMAC 簽署驗證的 HTTP 介面，供外部 Agent 派發發送請求與查詢狀態。 | 使用者裁決 R3、TG-MVP-03 (R3 ADR)、TG-MVP-06 (B-98)、TG-MVP-04 (F1)、TG-MVP-07A、使用者 binding 裁決 D-TG11-3 | TG-MVP-03, TG-MVP-04, TG-MVP-06, TG-MVP-06A, TG-MVP-07A | ACCEPTED / CLOSED；final implementation SHA `3d94bc2ccd26870b133d1dca217bb03e1c4cf767`；initial candidate `0901e06b8d3a2a68a3ae4d2bc12309859943e199`（Run 36135220532 success, Macro HOLD F1–F8, D-TG11-3 accepted）；R1 candidate `b5f3b2869d41a015916b7a4e59633949a80fdab6`（Actions Run 36142580126 gateway-windows success, verify failure, Macro HOLD due cross-platform test design defect）；final R2 `3d94bc2ccd26870b133d1dca217bb03e1c4cf767`（candidate Run 36145856257 success, post-main Run 36147638120 success, External Macro = PASS / ACCEPT ALL, F1–F8 = RESOLVED, D-TG11-3 = PASS, R2 CROSS-PLATFORM REPAIR = PASS, R2-M1 = valid semantic RED / PASS, NEW MATERIAL BLOCKING FINDING = NONE, ROLLBACK = NOT REQUIRED, same-SHA promotion = PASS, post-main CI = PASS）；accepted implementation checkpoint = `3d94bc2ccd26870b133d1dca217bb03e1c4cf767`；B-107 remains residual/non-blocking。 |
| TG-MVP-12 | 已完成 | **持久化 SQLite Outbox 實作**（Durable SQLite Outbox）：實作具備能力感知安全重試（Capability-Aware Safe Retry）之出站佇列，保證出站訊息不遺失，斷線時持久化保存。final implementation SHA = `8ea3fc6e1301f077ee467174981f0e63978c2de3`；R0 candidate `4968e8d90c77e51e0745965a2376779a419d85b9` External Macro HOLD（Run 36212316461 attempt 1 verify PASS, gateway-windows PASS; findings F1–F3, accepted checkpoint fed1eeb888619138001969eb7b2f63ea3da33f6e）；R1 candidate `8ea3fc6e1301f077ee467174981f0e63978c2de3` Actions Run 36214841659 success（verify=completed/success, gateway-windows=completed/success）；F1–F3 RESOLVED；External Macro final audit PASS / ACCEPT ALL；same-SHA main promotion accepted；post-main exact-SHA Run 36215575618 success（verify=completed/success, gateway-windows=completed/success）；TG-MVP-12 ACCEPTED / CLOSED；accepted implementation checkpoint = `8ea3fc6e1301f077ee467174981f0e63978c2de3`；single-use main auth consumed（provenance: local machine output / USER_PROVIDED evidence）。 | 使用者裁決 R2、TG-MVP-03 (R2 ADR)、TG-MVP-04 (F1)、ADR-0025 | TG-MVP-03, TG-MVP-04, TG-MVP-11 | Schema v6 outbox 遷移完成、Capability-Aware Safe Retry Policy (R2) 實作完成、In-process Outbox Worker 實作完成、GatewayRuntimeOwner 生命週期接線完成、原子回覆授權與冪等重放完成、516 passed 0 failed 2 skipped、External Macro PASS / ACCEPT ALL、same-SHA main promotion 成功推進、post-main Actions Run 36215575618 驗證通過、TG-MVP-12 正式結案（ACCEPTED / CLOSED） |
| TG-MVP-13 | 進行中 | **Telegram 出站文字發送適配器**（Telegram outbound text delivery）：由 Outbox worker 取出待送文字訊息，透過 Telegram Bot API 送出並標記完成或重試。（註：D-R3-A+、D-R3-C1、D-R3-REPLY-A 已由使用者裁決；D-R2 deferred before TG-MVP-15）。候選狀態：CANDIDATE AWAITING EXTERNAL MACRO AUDIT。 | 使用者裁決 D-U4、ADR-0022、D-R1、D-R3-A+、D-R3-C1、D-R3-REPLY-A、D-R4 | TG-MVP-10, TG-MVP-12 | 測試機器人文字回覆成功送達 Telegram 聊天室 |
| TG-MVP-14 | 待辦 | **對話封存機制**（D22/D23 conversation archive）：實作對話紀錄之持久化封存，確保歷史對話可供檢索。 | D22, D23, D-U4 | TG-MVP-10, TG-MVP-13 | 對話歷史封存單元測試與檢索測試通過 |
| TG-MVP-15 | 待辦 | **Telegram MVP 端到端測試機器人驗收**（Telegram MVP E2E / Test Bot）：驗收文字雙向收發（text in/out）、通道接管（takeover）、對話封存（archive）。嚴禁將 D17 附件與 D19–D21 外發檔案塞入 MVP。 | 使用者裁決 D-U4、ADR-0022 | TG-MVP-01 至 TG-MVP-14 | 完整 E2E 測試劇本在測試機器人環境全數 PASS |

#### 2. M-TG-CUTOVER（Telegram 正式切換與舊版停用）

| Slice | 狀態 | 目標 | 依據／權威 | 前置相依 | 完成證據 |
|---|---|---|---|---|---|
| TG-CUT-01 | 待辦 | **E-04 指令路由切換**（E-04 routing cutover）：收斂 `$$TG連線$$` 指令，正式將 Telegram 流量切換至 Channel Gateway。 | E-04、ADR-0022/D14 | TG-MVP-15 (MVP E2E PASS) | 路由指令對齊 Gateway 控制合約 |
| TG-CUT-02 | 待辦 | **D26 正式帳號切換**（D26 formal account switch）：由測試機器人帳號切換為正式 Telegram Bot 帳號配置。 | D26、B-98 | TG-CUT-01 | 正式帳號設定驗證通過 |
| TG-CUT-03 | 待辦 | **舊版正式 Telegram 服務停用**（legacy formal TG stop）：安全關閉並停用舊版 Telegram 運作行程，避免雙重監聽或衝突。 | ADR-0022、PM2 進程治理 | TG-CUT-02 | 舊版服務完全停止且無殘留進程 |
| TG-CUT-04 | 待辦 | **Gateway 正式金鑰啟用**（Gateway formal token activation）：啟用正式環境 Token 並啟動生產監聽。 | B-98、TG-MVP-06A、安全性規範 | TG-CUT-03, TG-MVP-06A | 生產 Gateway 正式連線 Telegram |
| TG-CUT-05 | 待辦 | **回滾合約與切換演練**（rollback contract）：建立緊急回滾至舊版機制與程序手冊，完成 cutover 演練。 | ADR-0022、SOP 緊急應變 | TG-CUT-04 | 回滾演練通過，上線正式切換完成（D-U7 達成） |

#### 3. M-LINE（LINE 平台整合與雙平台值守）

| Slice | 狀態 | 目標 | 依據／權威 | 前置相依 | 完成證據 |
|---|---|---|---|---|---|
| LINE-01 | 待辦 | **F-05 雙平台值守前置項**（F-05 before concurrent dual-platform duty）：補記 ADR-0012 `SKIP_LOCK=1` 繞過全域鎖問題，在並行雙平台值守前確保鎖機制正確性。 | 看板 F-05、ADR-0012、ADR-0022 | TG-CUT-05 (Telegram 上線完成) | F-05 結案，雙平台全域鎖行為明確 |
| LINE-02 | 待辦 | **D11 工作者信箱實作**（D11 Worker Mailbox）：實作無人值守與工作者信箱機制。 | D11、ADR-0022 | LINE-01 | Worker Mailbox 單元測試通過 |
| LINE-03 | 待辦 | **LINE 入站與出站適配器實作**（LINE adapter）：實作 Webhook 入站接收與 LINE Messaging API 出站發送。 | ADR-0022、C3 Identity ADR | LINE-02, TG-MVP-02, TG-MVP-05 | LINE 訊息收發與持久化測試通過 |
| LINE-04 | 待辦 | **D26 LINE 帳號與配額行為控制**（D26 LINE account/quota behavior）：落實 LINE 官方帳號免費訊息額度監控與流控機制。 | D26、B-75 配額治理 | LINE-03 | 額度超限保護與流控測試通過 |
| LINE-05 | 待辦 | **F-06 渲染器路徑收斂**（F-06 renderer path convergence）：更新 `json-to-flex-renderer` 依賴路徑，由舊 repo 路徑遷移至新架構。 | 看板 F-06、ADR-0022 M8 路由 | LINE-03 | Flex Message 渲染測試通過 |
| LINE-06 | 待辦 | **LINE 整合驗收與排定順序遵循**（D12 LINE LAST / explicit request）：確認 LINE 整合為最後順位且依使用者明確要求啟用。 | D12（LINE LAST）、ADR-0022 | LINE-01 至 LINE-05 | 雙平台並行運作驗收通過 |

#### 4. M-TG-POST-MVP（Telegram POST-MVP 擴充功能）

| Slice | 狀態 | 目標 | 依據／權威 | 前置相依 | 完成證據 |
|---|---|---|---|---|---|
| TG-POST-01 | 待辦 | **D17 使用者至 Agent 附件處理**（User → Agent Attachments）：支援 Telegram 圖片與檔案附件接收、暫存與路徑傳遞。明確為 POST-MVP，不塞入 MVP v1。 | ADR-0022 D17、使用者裁決 D-U4 | TG-MVP-15 (Telegram MVP 驗收完成) | 附件接收端到端測試通過 |
| TG-POST-02 | 待辦 | **D19–D21 外發檔案授權與受保護根目錄及 DLP**（Outbound File Authorization / Protected Roots / DLP）：實作外發檔案之授權白名單、受保護路徑限制與防資料洩漏（DLP）檢查。明確為 POST-MVP。 | ADR-0022 D19, D20, D21、使用者裁決 D-U4 | TG-POST-01 | 外發授權與 DLP 防護測試通過 |
---

## F. 追蹤項（`refactor-backlog.md` 三、各點）

| ID | 狀態 | 項目 | 來源 |
|---|---|---|---|
| F-01 | 待辦 | 三層索引描述漂移，10 條未處理；根本解法是由 frontmatter 產生下兩層索引 | 第 10 點。**已被指定為 Jules 首航任務** |
| F-02 | 可封存 | 配額熔斷的錨定缺口與 `quota_monitor.py` 處置 | 併入 B-75 額度監控與熔斷機制（追蹤：F-02 → B-75；E-03 Roadmap LINE-04 依據更新為 B-75） |
| F-03 | 待辦 | **多代理自治閉環（LOOP-lite，POST-MVP）** | 第 13 點。D-U15 確立為 POST-MVP；流程採 Jules proposes → Executor reauthors → Macro judges；禁止 auto merge；內外兩層閉環目前都未完整運作。 |
| F-04 | 待辦 | `karpathy` 其他專案探勘 | 第 14 點。**低優先、需時間盒**，技能遷移與 runtime 收尾後才執行 |
| F-05 | 待辦 | ADR-0012 補記 `SKIP_LOCK` | `docs/archive/handover/HANDOVER-pre-router-568209e.md` §5.5（historical source）。`autoresearch-agent` 用 `SKIP_LOCK=1` 繞過全域鎖，ADR 未記載；依 ADR-0022 屬雙平台並行值守前置項（落地對應：E-03 Roadmap LINE-01） |
| F-06 | 待辦 | `json-to-flex-renderer` 指向舊 repo 路徑 | `docs/archive/handover/HANDOVER-pre-router-568209e.md` §5.5（historical source）。屬合法註記，但 runtime 遷移後必須回頭更新；依 ADR-0022 M8 路由於後續 LINE 實作時更新（落地對應：E-03 Roadmap LINE-05） |
| F-07 | 已完成 | **`docs/HANDOVER.md` 十項過期與不一致** | 2026-09-01 審計官接手第一輪即發現，但修正提示詞兩週未產出。已於 `d1e389b` 十項一次修完，詳見 `refactor-backlog.md` 第 33 點 |
| F-08 | 已完成 | 交接區與看板的職責切分 | §5.2 的清單副本已刪除，只留指向；分工寫入 `auditor-protocol.md` §10（交接區回答「現在在哪」、看板回答「還有什麼」）。見第 33 點 B 段 |

---

## G. 舊 repo 未盤點區塊（2026-09-02 新發現）

| ID | 狀態 | 項目 | 備註 |
|---|---|---|---|
| G-01 | 可封存 | `Data/TODO.md` 的 10 項未完成待辦 | absorbed by E-05；內容仍作為 E-05 acceptance inventory，不是刪除需求。不得刪除其原始歷史內容。不得建立第二 Data migration queue |
| G-02 | 可封存 | 計畫書（Execution Plans）保留規範 | absorbed by E-05；內容仍作為 E-05 acceptance inventory，不是刪除需求。不得刪除其原始歷史內容。不得建立第二 Data migration queue |
| G-03 | 可封存 | `_archive_legacy_docs/adr/` 五份舊 ADR 的內容評估 | absorbed by E-05；內容仍作為 E-05 acceptance inventory，不是刪除需求。不得刪除其原始歷史內容。不得建立第二 Data migration queue |
| G-04 | 可封存 | `_archive_legacy_docs/` 其餘四份文件評估 | absorbed by E-05；內容仍作為 E-05 acceptance inventory，不是刪除需求。不得刪除其原始歷史內容。不得建立第二 Data migration queue |

---

## 封存區

（目前為空。項目經使用者確認可封存後移入此處，保留全文可查。）
