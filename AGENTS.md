# HH.AI 專案技能架構規範

本專案的技能（skills）架構參考並遵循 [mattpocock/skills](https://github.com/mattpocock/skills) 的組織方式。
**任何 agent（包含 Antigravity）在新增、修改、遷移技能時，必須遵守本文件的規則，不得自行發明其他結構。**

使命與優先序見 [MISSION.md](./MISSION.md)。

---

## 0. 工程紀律規則（最高優先）

這幾條規則優先於本文件其他所有章節，發生衝突時以這裡為準：

1. **審計階段不動檔案**：盤點/分析類的任務（列清單、diff 重名技能、畫依賴圖）進行時，
   禁止同時修改、搬移、刪除任何技能檔案。先完全搞懂現狀，再開始動手。
2. **發現重複知識，立刻停下來處理**：如果在遷移或新增技能的過程中，發現同一段邏輯、
   同一份觸發詞判斷、同一個檢查清單在別的技能裡也有——先停止手上的實作，把它抽成
   共用內容（放進被多個技能依賴的那個技能的 REFERENCE.md，其他技能改成呼叫它），
   確認引用更新完成後，才繼續原本的任務。不要邊做邊留著重複的內容之後再說。
3. **職責過廣就拆分**：一個技能如果承擔了不只一種能力（例如同時做「抓資料」又做
   「產生圖表」又做「發送 LINE 訊息」），要拆成多個各自單一職責的技能，而不是靠拉長
   SKILL.md 或加更多條件分支撐住。這跟「SKILL.md 超過 150 行拆 REFERENCE.md」是
   兩件事：行數過長是漸進式揭露的問題，職責過廣是邊界設計的問題，兩者都要處理，
   但診斷方式不同。
4. **已驗證的計算邏輯，搬移不重寫**：技術指標公式、財務計算、資料清洗邏輯這類已經
   在生產環境跑過、正確性已被驗證的程式碼，遷移時原封不動搬進對應技能的 `scripts/`，
   **不要**因為「順便重構」就重寫演算法本身。重構的對象是檔案組織方式、觸發詞、
   文件格式，不是已經正確的計算邏輯。
5. **品質優先於速度**：批次遷移時，寧可少搬幾個、每個都驗證過，也不要求快而讓
   `validate_skills.py` 掃出一堆錯誤堆積。

---

## 1. 目錄結構

技能全部放在 `skills/` 下，依「桶」（bucket）分類，桶內是扁平的技能資料夾：

```
skills/
├── orchestration/   # 流程調度、任務路由、狀態機控制
├── analysis/        # 台股分析、財務模型、技術分析（純分析型，不直接執行外部動作）
├── agents/          # RARV 執行型 agent（會實際呼叫工具、寫檔案、下單等）
├── execution/       # 通用工具型技能（PDF/XLSX/D3/Playwright 等）
├── platform/        # 平台整合（LINE/Telegram/MCP/Postgres 等外部串接）
├── meta/            # 造技能的技能、治理類（skill-creator、setup 等）
└── deprecated/      # 已棄用，保留供參考，不再維護
```

**每個技能一個資料夾**，路徑固定為 `skills/<bucket>/<skill-name>/SKILL.md`：

```
skills/<bucket>/<skill-name>/
├── SKILL.md              # 必要。YAML frontmatter + 指令本體
├── REFERENCE.md           # 選用。細節文件過長時抽出
├── EXAMPLES.md             # 選用。使用範例
├── agents/openai.yaml      # 選用。跨工具中繼資料（若要相容 Codex/其他 harness）
└── scripts/                # 選用。決定性/重複性操作寫成腳本，不要每次靠 LLM 重算
```

嚴禁：
- 技能檔案散落在資料夾外（每個技能都必須有自己的資料夾）
- 同一個技能名稱在超過一個 bucket 出現
- `SKILL.md` 內容超過約 150 行還不拆 `REFERENCE.md`（漸進式揭露原則，見下方第 3 節）

---

## 2. SKILL.md 格式

Frontmatter 只有 `name`（必要）與 `description`（必要）是標準欄位：

```yaml
---
name: skill-name
description: 一句話說明「什麼情境下要用這個技能」，包含觸發詞。這是 agent 唯一用來判斷要不要載入本技能的依據。
---
```

**description 撰寫規則：**
- 用「情境 + 觸發詞」寫，不要只寫功能敘述。例如不要寫「本益比河流圖生成工具」，要寫「產生台股個股本益比河流圖。當使用者要求『本益比河流圖』、『估值區間』、『歷史本益比分佈』時使用」
- 絕對不能空白——空白等於這個技能永遠不會被自動觸發
- 一行寫完，不要換行斷開（YAML 多行寫法容易在解析時出錯，本專案曾發生過 5 個技能因此失效）

**本專案自訂擴充欄位**（mattpocock 架構沒有，但本專案沿用，因為涉及金融操作安全）：
```yaml
authorized_mcp_tools: [...]            # 白名單機制，action 型技能必須列出
semantic_firewall: true 或 "路徑字串"　　# 語意防火牆，見下方說明
```
這兩個欄位只用在 `skills/agents/`（RARV 執行型）與部分 `skills/platform/` 技能，其餘 bucket 不需要。

type 欄位已於 2026-08-24 全面移除，副作用判斷改由 bucket 分類（agents/ 代表有真實副作用）與 disable-model-invocation 欄位表達。

### semantic_firewall 有兩種寫法

第一種，`semantic_firewall: true`，這是簡單開關，代表這個技能啟用語意防火牆檢查，但不限定具體範圍。
第二種，`semantic_firewall: "/Domain/XXX/"` 這種字串路徑形式，明確限定這個技能的工作記憶／操作範圍只能存取該路徑對應的領域，例如 `"/Domain/Finance/TWSE/"` 代表只能存取台股財務相關 Schema，不能碰使用者個資或其他無關資料。這種寫法資訊量比純布林值更完整，優先使用這種寫法，只有在技能本身沒有明確可限定的領域範圍時，才用簡單的 `true`。

---

## 3. 漸進式揭露（Progressive Disclosure）

SKILL.md 本體只放：
1. 什麼時候用（重申 description 的情境）
2. 最小可行範例 / 主流程
3. 連結到 REFERENCE.md（如果有）

詳細參數表、API schema、大量 edge case、完整觸發詞清單 → 全部移到 `REFERENCE.md`，SKILL.md 用一句話連結過去。目的是讓 agent 平常只讀精簡版，需要細節才展開，節省 context token。

---

## 4. 技能之間的依賴

技能之間互相呼叫，用**自然語言指向**（例如「先執行 `execution/pdf` 技能」），**不要用跨資料夾的深層檔案引用**（例如不要寫 `../other-skill/REFERENCE.md`）。共用的參考資料放在擁有它的技能資料夾內，其他技能透過「呼叫該技能」取用，而不是直接讀它的檔案。

---

## 5. User-invoked vs Model-invoked

每個技能分成兩種可被誰觸發：

- **User-invoked（只能人類手動觸發）**：frontmatter 加 `disable-model-invocation: true`。description 寫成給人看的一句話摘要，不需要塞觸發詞列表。用於：一次性設定類（如 `meta/setup-hhai-skills`）、有風險的操作類技能。
- **Model-invoked（模型可自主呼叫，預設）**：不加上面那個欄位。description 要包含豐富的觸發詞，讓模型能自主判斷何時呼叫。

判斷標準：「模型自己遇到這種情境時，能不能安全地自主呼叫這個技能？」能 → model-invoked；不能（例如會實際下單、刪除資料、發送對外訊息）→ user-invoked。

---

## 6. Router 技能

`orchestration/agency-orchestrator` 是總路由技能，扮演 mattpocock 架構裡 `ask-matt` 的角色：對應所有 user-reachable 技能，並說明彼此如何配合。

**規則：任何時候新增、改名、刪除、或改變一個 user-reachable 技能的行為，都必須同步更新 `agency-orchestrator` 的 SKILL.md**，讓路由圖保持準確。一個路由技能如果指向不存在的技能，或漏掉新技能，就是「說謊的路由器」——這是本規範最容易被忽略但最重要的一條。

---

## 6a. 資料夾層級的範圍受限規則

每個 `skills/<bucket>/` 底下，除了 `README.md`（給人看的索引），還有一份
`AGENTS.md`（給 agent 看的範圍受限規則），內容包含這個 bucket 的定位、
在這裡工作要注意什麼、常見錯誤。Antigravity 進到某個 bucket 資料夾工作時，
應該優先讀那個資料夾自己的 `AGENTS.md`，而不是只依賴根目錄這份。

**這是刻意的設計選擇**：與其把所有規則塞進一份越來越大的根目錄文件（那樣會違反
本文件強調的「避免大型文件」原則），不如把 bucket 專屬的規則放在 bucket 自己的
資料夾裡，各自保持精簡。新增 bucket 專屬規則時，改對應的 `skills/<bucket>/AGENTS.md`，
不要往根目錄這份塞。

重要的架構決策（例如「為什麼是這 7 個 bucket」、「為什麼某類邏輯遷移時不重寫」）
留痕在 `docs/adr/`，用 ADR（Architecture Decision Record）格式記錄，模板見
`docs/adr/0000-adr-template.md`。這樣根目錄 `AGENTS.md` 只需要寫「現在的規則是什麼」，
不用同時解釋「為什麼」，文件才能保持精簡好讀。

---

## 7. README 同步規則

- 每個 bucket 資料夾（`skills/orchestration/`、`skills/analysis/`...）都要有一個 `README.md`，條列該 bucket 內所有技能 + 一行描述，技能名稱要連結到它的 `SKILL.md`，並依 User-invoked / Model-invoked 分組。
- 專案根目錄的 `README.md` 也要同步收錄所有技能的索引。
- `skills/deprecated/` 只需要一份扁平清單，不用分組。

**新增/修改技能時，這兩層 README 必須同步更新，不能只改 SKILL.md。**

---

## 8. 遷移舊技能時的規則

從舊架構（`01_Orchestrators / 02_Cognitive / 03_Execution / Archive`）搬技能過來時：
1. 先確認新舊是否重名（`csv-data-summarizer`、`pdf`、`xlsx`、`playwright-automation`、`financial-analyst`、`tech-analyzer`、`postgres` 等已知有重複），只保留較新/較完整的版本
2. description 空白的技能，遷移時必須先補齊，不可原樣搬過來
3. 標記 `legacy_notice` 的技能一律進 `skills/deprecated/`，不遷移進主要 bucket
4. 遷移完成的技能，才能從舊資料夾刪除；遷移中請保留舊資料夾作為備份，直到全部驗證完成

---

## 9. 驗證

每次新增/修改技能後，執行：

```bash
python3 scripts/validate_skills.py
```

這個腳本會檢查：frontmatter 是否合法、description 是否為空、是否有重複技能名稱、README 索引是否跟實際技能資料夾一致、SKILL.md 是否過長未拆分。**驗證沒過不要視為完成。**
