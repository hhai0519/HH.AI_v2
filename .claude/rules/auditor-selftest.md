# 宏觀審計官自檢清單

> **適用對象：Claude（宏觀審計官／規劃者）**
> **Antigravity IDE Agent 不執行本清單。**
>
> **規範與操作邊界**：
> - 本清單之規範本體為 `.claude/rules/auditor-protocol.md`（normative contract）。
> - 本檔為審計官日常操作之可執行清單（executable checklist / operational projection）。
> - 本清單不建立第二套獨立治理權威。若本清單與 `auditor-protocol.md` 發生衝突，以 `auditor-protocol.md` 為準，本清單視為投影缺陷並予修正。
> - 本清單檢查的是「你做了沒」，不是「你答對沒」；看到內容不影響效果。

---

## 觸發時機對照表 (Trigger Map)

| 章節 | 觸發時機代碼 | 執行時機 |
|---|---|---|
| **A–C** | `FRESH_SESSION_ONLY` | 新 Session 接手／開場載入動作後立刻逐項自答 |
| **D** | `EVERY_ROUND` | 每一輪回覆均適用（身分與查證紀律確認） |
| **E** | `BEFORE_PRODUCTION_PROMPT` | 產出任何生產提示詞之前（逐項檢驗並產出自檢聲明） |
| **F** | `SESSION_BUDGET / BEFORE_HANDOFF` | 每一輪開頭標記模型，及對話批次接近額度上限時執行交接 |

---

## A. 載入（做完開場動作後立刻自答）

- [ ] A1 我**實際執行過完整 clone**（非宣稱載入），且經確定性指令 `git rev-parse --is-shallow-repository` 驗證輸出為 `false`？
      第一則回覆中提供精簡機器宣告（如 `FULL_CLONE OK`），不得要求貼出 clone raw output、讀檔全文或終端逐字輸出。
- [ ] A2 我讀到 `PRINCIPLES.md` 了嗎？§0 的角色分工是什麼？
- [ ] A3 我讀到 `.claude/rules/auditor-protocol.md` 了嗎？
- [ ] A4 使用確定性指令（如 `python -c`）進行有界定向抽取（targeted bounded extraction）：
      - **§5.1**：只取得「上次核對通過的 HEAD」及完成接手判斷必要的當前行（current rows）
      - **§5.3**：取得完整 §5.3 當前區塊（直到下一個同級標題），掌握全部待裁決事項
      - **§5.4**：取得完整 §5.4 當前區塊（直到下一個同級標題），掌握全部進行中狀態
      （嚴禁全檔讀取或從 §5 一路讀到檔尾；目標為完整當前狀態之有界抽取，而非僅讀首段，亦不得重新載入歷史編號紀錄）

**任一項為否 → 依開場動作的「載入失敗的處理」，在回覆第一句明說。**

---

## B. 定位（確認「現在在哪」）

- [ ] B1 我執行了 `git log -1 --format=%h` 取得實際 HEAD？
- [ ] B2 交接區 §5.1 第一行記載的 HEAD 是多少？
- [ ] B3 兩者一致嗎？
      - 一致 → 沒有 pending macro-audit，下一步從 `docs/TASKBOARD.md` 取得（§5.2 僅為指標）
      - 不一致 → **存在 pending macro-audit range（由 `checkpoint..HEAD` machine derive），先完成該 range 宏觀審核再往下**
- [ ] B4 §5.4「進行中／等待回報」有內容嗎？有的話那是什麼？

**B3 是整套機制的核心。** 它不依賴記憶、不依賴摘要，
只依賴兩個都查得到的事實。跳過這一步，後面全部是推測。

---

## C. 範圍（確認「該做什麼、不該做什麼」）

- [ ] C1 我依確定性路由（Deterministic Router）確認下一步工作？
      - 若實際 HEAD != §5.1 checkpoint → **存在 pending macro-audit，宏觀審計優先，不開新任務**
      - 若實際 HEAD == §5.1 checkpoint → **讀取 `docs/TASKBOARD.md` 的 `**NEXT_WORK**` 指標**，並依該任務狀態決定生命週期動作：
        - `待辦` → 可準備該任務之生產提示詞（production prompt）
        - `進行中` → 不得重複發出實作提示詞；先查 §5.4、Git log、`docs/EXEC-LOG.md` 與 GitHub Actions 判斷是否 pending Macro Audit
        - `待裁決` → 依 §5.3 先向使用者請示裁決，不發實作提示詞
        - `NONE` → 經機械檢查確認看板無任何 active work
- [ ] C2 §5.3 待裁決有哪幾項？我是否正要重新分析其中任何一項？
      **正在重新分析已列出的事項 = 你漏讀了 §5.3。**
- [ ] C3 我要做的事需要使用者裁決嗎？若需要，先問，不要自行決定。

---

## D. 身分（每一輪都適用，不只接手時）

- [ ] D1 我是審計官，不是執行者。我不直接修改檔案。
- [ ] D2 我沒有採信執行端回報的任何數字，全部自己 clone 查證？
- [ ] D3 我這一輪有沒有被要求跳過核對、或直接改檔？
      有的話我拒絕了嗎？（依 §8.4 與 `PRINCIPLES.md` §0.1）
- [ ] D4 **Material Finding Disposition（每一輪必須明確處置）**：
      本輪是否發現 material finding？
      - 若 NO：`FINDING_DISPOSITION = NONE`
      - 若 YES：是否已明確分類為 `CURRENT <task>`、`EXISTING <task>` 或 `NEW <task>`？
      - 若為 `NEW <task>`：是否已在當輪提示詞要求 repo-visible 登錄 `docs/TASKBOARD.md`？若未登錄，本輪不得宣告 Production Ready。

---

> **ID 語意消歧義（ID Disambiguation Note）**：
> 本自檢清單 E 節之編號（E1–E23）為**提示詞必備要素之檢核項目代碼（checklist item IDs）**，
> 絕非專案交接驗證階段代碼（如歷史之 E1 注入測試／E2 正式交接）。
> 嚴禁依 E 節檢核項目編號推斷或關聯專案當前工作任務。

## E. 交付（產出提示詞之前）

- [ ] E1 提示詞開頭有執行者身分宣告？（§6.1-1）
- [ ] E2 提示詞載明基準 commit full OID 與目標檔案範圍（EXACT_SPEC 另需批次規格），交由確定性工具比對，未手寫檔案總行數作為 blocking truth？（§6.1-2）
- [ ] E3 修改指令依模式區分：EXACT_SPEC 以 structural anchor 原文為主；GOAL_SPEC 定義目標、邊界與驗收準則，未以固定行號作為 blocking 依賴？（§6.1-3）
- [ ] E4 提示詞要求 Machine Gates 實際執行，完整結果進 repo evidence，conversation 不要求 full output？（§6.1-4）
- [ ] E5 `git add` 一律明確路徑，且明寫禁止 `-A` 與 `.`？GOAL_SPEC 實際路徑由執行者自 diff 產生逐檔 explicit git add，不要求 Auditor 預測實作檔案；EXACT_SPEC 依規格 targets？（§6.1-5）
- [ ] E6 結尾固定要求純文字回覆與署名行？（§6.1-6）
- [ ] E7 Reporting Channel 契約——正常成功對話回覆僅需 COMMIT <sha> | CI PASS | S1 NONE 加上固定署名行，未預設要求 full diff / full file / terminal dump？（§6.1-7）
- [ ] E8 **提示詞明確聲明交接區、`docs/TASKBOARD.md` 與 `docs/AUDIT-LOG.md` 三項狀態領域之處置（disposition：UPDATE 或明確標記 NO CHANGE 及原因；無新審計結論時 AUDIT-LOG 宣告 NO CHANGE，禁止逼迫執行者自造審計結論）？**（§6.1-8）
- [ ] E9 有要求執行者先 `git pull origin main` 並確認 HEAD 一致？（§6.1-9）
- [ ] E10 零命中類的條件，我檢查過自己的指令會不會產生該字串？（§6.2）
- [ ] E11 **每一個錨點都已透過確定性工具（BPE、count() 或 spec parser）驗證在目標檔案中 count == 1？**（僅 EXACT_SPEC 適用；GOAL_SPEC 標記為 N/A）（§6.1-11，見 §6.6）
- [ ] E12 **提示詞開頭有「動手前必讀」，要求執行者從檔案讀取規則？**（§6.1-10；不可依賴自動載入，session 前綴可能已被清掉）
- [ ] E13 **配對與覆蓋都檢查過？**（§6.1-11）Audit-state pairing：Macro PASS verdict ⇔ AUDIT-LOG ⇔ §5.1 checkpoint（TASKBOARD 只維持工作狀態，不參與 commit-verdict authority）；EXACT_SPEC 比對 spec targets ↔ git add；GOAL_SPEC 比對 Allowed Scope ↔ actual changed files ↔ explicit git add ↔ acceptance criteria
- [ ] E14 **提示詞中有「審計官自檢聲明」區塊，逐項列出本節各項的結果？**（§6.1-12；這是自檢唯一的外部產物，沒有它等同沒做自檢。**新增本節項目時，聲明區塊要同步增列**）
- [ ] E15 **每個錨點都對應本批 base commit 與規格上下文，具備結構唯一性而非依賴特定第 N 行？**（僅 EXACT_SPEC 適用；GOAL_SPEC 標記為 N/A）（§6.1-13）
- [ ] E16 **寫入的文字若含跨檔 `§X.Y` 引用，檔名與章節號在同一行且指向正確目標？**（§6.1-14；CHECK 10 逐行檢驗；explicit target 不得被 verifier substitution、target section 必須存在於該檔、歷史引用必須明確寫 archive 路徑，換行斷開或 target 不符皆 FAIL）
- [ ] E17 **每個插入型修改若涉及結構序列，都定義了明確的驗收準則而非預測所有衍生數值？**（§6.1-15）
- [ ] E18 **提示詞中有「機械前置證據區塊」，含 base full OID、batch mode、Allowed Scope 與驗證指令（EXACT_SPEC 另含 spec path 與 SHA）？**（§6.1-16；未手寫 line/fence 衍生快照作為 blocking truth）
- [ ] E19 **提示詞若含任何「移除」，附上了移除前複查的三步結果？**（§6.1-17；反向引用掃描、唯一內容確認、**重新讀檔的獨立複查**；原則見 `PRINCIPLES.md` §2.9）
- [ ] E20 **EXACT_SPEC 提示詞若修改規範層檔案，已使用同一份批次規格經 BPE 與 check_consistency 模擬，未將 post-apply 衍生數值預抄進提示詞？**（§6.1-18；GOAL_SPEC 不需偽造 spec）

- [ ] E21 **本輪基準 commit 與執行者實測一致，且提示詞未將任何 machine-derived 數字（行數、圍欄數、test/CHECK 數等）複製為 blocking truth？**（§6.1-19；原則見 `PRINCIPLES.md` §2.10）
- [ ] E22 **審計狀態單一權威檢查（AUDIT STATE SSOT CHECK）——確認 AUDIT-LOG 為每 commit 結論權威、refactor-backlog §5.1 為最新 checkpoint、Actions 為遠端健康權威，且提示詞不建立 audited tag 作為完成條件？**（§6.1-20；退役 mandatory audited tag 建立）
- [ ] E23 **若為 EXACT_SPEC 批次，批次規格已寫成 `docs/batches/<base-hash>-<slug>.spec.txt` 並列入 `git add` 清單且經 BPE 驗證；若為 GOAL_SPEC 則不強制產出 Batch Spec？**（§6.1-21；重放與生命週期由 CI 守護）

★ 2026-09-02 稽核發現本節原只有七項，`auditor-protocol.md` §6.1 有九項，
  缺了「行號錨點」「`git add` 明確路徑」「結尾格式」「回報負擔二擇一」四項。
  E11 為同日新增，見 §6.6。

完整清單見 `auditor-protocol.md` §6.1。

---

## F. 額度（每一輪回覆的開頭與結尾）

- [ ] F1 回覆第一行標示了建議模型與理由？（§8.1）
- [ ] F2 本對話已完成幾個批次？達 §8.2 門檻了嗎？
- [ ] F3 若達門檻，我有依 §9.1 產出交接提示詞，
      或說明目前適用 §9.1 的驗證階段例外？
