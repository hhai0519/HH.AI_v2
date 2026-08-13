# 貼給 Antigravity 的遷移啟動指令

> 這份不是文件，是「腳本」——把下面整段貼進 Antigravity 的對話框，
> 它會先讀 `AGENTS.md` 和 `MISSION.md`，再開始逐一遷移。不要一次貼完整個舊 repo
> 要求「全部重構」，那樣 agent 沒有 checkpoint，出錯很難回溯。照下面分批次進行。

## 整體分成 4 個階段，每個階段做完才進下一個

1. **階段一：審計**（對應下面第一、二批）——盤點現狀、找出重名技能、修復空白
   description。**這階段禁止搬移或修改任何檔案**，只做分析與回報。
2. **階段二：骨架驗證**（對應下面第三批）——先遷移 3 個示範技能，確認新格式跑得通。
3. **階段三：逐批遷移**（對應下面第四批）——依 bucket 分批把剩下的技能搬過去。
4. **階段四：驗證與收尾**——全部搬完後跑驗證、產出對照表，確認沒有技能遺漏。

每個階段的「完成定義」：`python3 scripts/validate_skills.py` 沒有錯誤 + 對應的
bucket README 和根目錄 README 都已同步更新。沒達成這兩點，不算階段完成。

## 兩種角色，你自己在 prompt 開頭指定給 Antigravity

不需要拆成七八個獨立 agent 角色，實務上用兩種模式切換就夠：

- **規劃模式**：只分析、只回報，不動任何檔案（用在階段一、以及每個新階段開始前）
- **實作模式**：照已經確認過的計畫動手搬移/改寫檔案（用在階段二、三）

下面每一批 prompt 開頭我都會註明是哪種模式，貼的時候可以直接照抄這個框架，
不用另外建立角色設定文件。

## 每一批 prompt 的固定結尾要求

從這裡開始，之後每一段要貼給 Antigravity 的 prompt，結尾都固定加這段話
（下面各批次的 prompt 內文已經照這個規則更新過）：

```
請將完整回覆整理成一份可以直接複製的純文字內容（不要用只能在你這裡展開查看的
折疊區塊），並在回覆的最後加上一行：「以上是 Antigravity IDE Agent 的回覆」。
```

這樣使用者可以一鍵複製整段回覆貼回來，而且看得出來這段內容是 Antigravity IDE
的 Agent 產出的，不是使用者自己寫的。

## 長流程要維護 task artifact(Antigravity 沒有原生 todo 工具)

Antigravity 沒有內建的待辦清單工具，對話一長容易忘記進度。**從階段三開始**（尤其
階段四批次遷移剩下的技能，一次要處理十幾個技能），請 Antigravity 額外維護一份
task artifact：

```
在開始這批遷移前，請先用 write_to_file 建立一份任務清單 artifact
（IsArtifact: true, ArtifactType: "task"），列出這批要遷移的每個技能路徑。
每完成一個技能的遷移，就用 replace_file_content 把對應項目標記完成（- [x]）。
如果中途發現計畫要調整，也更新這份清單。這份清單是這一批工作的進度依據，
如果對話變長、你不確定進度到哪，先重讀這份清單再繼續。
```

這段可以直接接在階段三、四的 prompt 後面一起貼。

## 「Careful Mode」——每一批的通用互動方式

不管哪個階段，都遵守同一個互動節奏：**Agent 先列出完整計畫給你看 → 你看過確認 →
明確說「可以開始」或「go」，它才真的動手**。不要讓 Agent 自己邊想邊做、你事後才
發現方向錯了。下面每一批 prompt 最後那句「先不要搬檔案／先回報結果給我確認」，
就是在啟動這個模式。

---

## 前置：把舊 repo 放進來當參考

在 `HH.AI_v2/` 旁邊，保留一份舊 repo 的唯讀複本（例如 `HH.AI_260806_legacy/`），
Antigravity 遷移時要能讀到舊技能的原始內容。不要把新舊混在同一個資料夾。

---

## 第一批：修復 5 個空白 description（優先，且風險最低）— 規劃模式

```
請讀 HH.AI_v2/AGENTS.md，理解本專案的技能架構規範。

接著打開 HH.AI_260806_legacy/skills/03_Execution/ 底下這 5 個技能的 SKILL.md：
connect-apps、csv-data-summarizer、gemma-4-api、notebooklm-mcp、xlsx

它們的 description 欄位目前是空的或格式錯誤。請你：
1. 讀懂每個技能的 SKILL.md 本體內容，理解它實際在做什麼
2. 依照 AGENTS.md 第 2 節的規則，寫出正確的 description（情境 + 觸發詞，單行，不要留空）
3. 先不要搬檔案，只在這裡把你打算寫的 5 個 description 列出來給我看，我確認後你再繼續
```

看過 Antigravity 給的 description 草稿，確認寫得對再放行。

---

## 第二批：處理重名技能的 diff — 規劃模式

```
以下技能在 HH.AI_260806_legacy/skills/ 現行版本和 HH.AI_260806_legacy/skills/Archive/
都存在同名版本，請逐一 diff 兩邊內容差異，並回報：
- pdf、xlsx、csv-data-summarizer、playwright-automation、financial-analyst、
  investment-researcher、tech-analyzer、twse-data-analyst、postgres、
  connect-apps、pe-river-map

對每一組，列出兩個版本的檔案修改時間、frontmatter 差異、內容差異摘要，
並給出你認為「應該保留哪一版」的建議與理由。先不要刪除或搬移任何檔案，
只回報分析結果給我確認。
```

確認每組保留哪一版之後，才進入下一步。

---

## 第三批：示範遷移 3 個技能（驗證流程可行）— 實作模式

先挑 3 個「格式完整、無重名、無需合併」的技能，實際跑一次完整遷移流程，
確認新格式在 Antigravity 底下運作正常，再批次做剩下的。

```
請把以下 3 個技能，從 HH.AI_260806_legacy/skills/03_Execution/ 遷移到 HH.AI_v2/skills/execution/：
d3js-visualization、webapp-testing、mcp-engineer（原路徑可能在 03_Execution 下，如有整合過先確認）

遷移時嚴格按照 HH.AI_v2/AGENTS.md 的規則：
1. 每個技能建立獨立資料夾 HH.AI_v2/skills/execution/<skill-name>/
2. SKILL.md frontmatter 只保留 name / description（若有 type/authorized_mcp_tools 等擴充欄位才保留）
3. 如果原本的 SKILL.md 超過 150 行，把細節部分（參數表、完整 API、大量範例）
   拆到同資料夾的 REFERENCE.md，SKILL.md 只留主流程 + 一句連結
4. 保留原本已有的 scripts/ examples/ references/ 子目錄內容，路徑對應過去即可
5. 遷移完成後，更新 HH.AI_v2/skills/execution/README.md，加入這 3 個技能的條目
6. 更新 HH.AI_v2/README.md 的技能總索引
7. 執行 python3 HH.AI_v2/scripts/validate_skills.py，把結果貼給我看

完成後停下來，不要繼續遷移其他技能，等我確認這 3 個沒問題。
```

---

## 待補事項清單（階段一審計中發現，正式遷移時要記得處理）

- `financial-analyst`、`investment-researcher`、`tech-analyzer`、`pe-river-map`
  這 4 個技能，遷移時要把 Archive 版裡的「NotebookLM 研究遵從指示」WARNING
  規則段落補回最終版本（現行版遺失了這段）。完整原文與決策理由見
  `docs/adr/0004-notebooklm-fallback-rule-recovery.md`。

## 第四批之後：批次遷移 — 實作模式

驗證上面 3 個沒問題後，比照同樣的 prompt 格式，依照 bucket 分批進行，
每批建議 5-8 個技能，跑完就執行一次 `validate_skills.py`：

1. `orchestration/`（先處理不需要合併的技能：`active-inference`、`agency-orchestrator-skill`、
   `security-auditor`、`stock-orchestrator-skill`、`reality-checker` 等）
2. 需要合併的技能單獨一批處理（`episodic-consolidation` + `reflection-module` 併入
   `agency-orchestrator`；`self-improvement` + `skill-governance-skill` 合併）
3. `analysis/`（純分析型）
4. `agents/`（RARV 執行型，注意保留 `authorized_mcp_tools` 白名單機制）
5. `execution/` 剩餘技能
6. `platform/`
7. 建立 `meta/setup-hhai-skills`（整併 `handover-manual-skill` + `twse-dev-sop-skill`）
8. 建立/改寫 `orchestration/agency-orchestrator` 作為總路由技能，確保它提到所有 user-reachable 技能
9. `deprecated/`（`global-workspace`、`canvas-design`、`quota-monitor-skill` 等已標記 legacy_notice 的技能）

每一批的 prompt 都比照第三批的格式：**明確列出要遷移的技能名稱、目標路徑、
完成後要更新哪些 README、要求跑驗證腳本、完成後停下來等確認**——不要讓 agent
自己決定範圍，範圍永遠由你在 prompt 裡明確給定。

---

## 全部遷移完成後

```
所有技能都已遷移到 HH.AI_v2/skills/ 下。請執行 python3 scripts/validate_skills.py
確認沒有錯誤，並比對 HH.AI_v2/skills/ 底下的技能總數，跟舊 repo（不含 Archive）
的 69 個技能數量是否吻合（扣除已合併、已歸檔的部分，說明每一個舊技能最終去了哪裡）。
產出一份對照表給我。
```

拿到這份對照表，跟我們稍早在對話中給你的遷移清單核對一次，確認沒有技能遺漏或重複。
