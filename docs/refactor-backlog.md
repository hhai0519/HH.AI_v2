# HH.AI_v2 重構待辦清單與進度盤點

> [!IMPORTANT]
> 本清單為 2026-08-25 對舊專案 HH.AI_260806 與 HH.AI_v2 完整比對後的
> 查證結果，每一項都經過實際檔案存在性驗證，不是憑印象整理。
> 每完成一批遷移後，請更新對應項目的狀態，並在文末補上更新紀錄，
> 避免這份清單本身變成過時的錯誤參考。

> 產出日期：2026-08-25
> 來源：對 `hhai0519/HH.AI_260806`（舊）與 `hhai0519/HH.AI_v2`（新）的完整比對

---

## 一、目前已完成的部分

| 項目 | 數量 | 狀態 |
|---|---|---|
| 技能遷移 | 49 個（7 bucket） | ✅ |
| ADR 決策留痕 | 15 份 | ✅ |
| Workspace 規則（`.agents/rules/`） | 4 份 | ✅ |
| SOP 遷移 | 10 份 + 索引 + README | ✅ |
| `$$` 指令權威路由表 | 1 份（11 條有效路由） | ✅ |

**舊 repo 22 份 SOP 全部有明確去向**：10 遷移、3 轉 ADR/rules、8 淘汰、1 持續運作（`SOP_00A`）。

---

## 二、待重構清單

### A. 技能（skills/）— 尚未遷移

#### A-1. 確定要遷移的

| 技能 | 舊位置 | 預計去向 | 備註 |
|---|---|---|---|
| `line-bot-zero-delay` | `03_Execution/` | `skills/platform/` | 文件遷移，程式碼留給 runtime 階段 |
| `telegram-bot-cdp-bridge` | `03_Execution/` | `skills/platform/` | 同上，內含 vendored `remoat` 開源專案 |
| `ui-prototype-builder` | `03_Execution/` | `skills/execution/` | description 過長需拆 REFERENCE.md |
| `skill-creator` | `03_Execution/` | `skills/meta/` | 跟 `nuwa-skill` 職責可能重疊，需評估 |
| `workspace-migration-recovery` | `03_Execution/` | `skills/meta/` | 可用來驗證本次遷移完整性 |
| `dynamic-tool-synthesizer` | `02_Cognitive/` | `skills/meta/` | persona 呼叫鏈的關鍵環節 |
| `autoresearch-agent` | `01_Orchestrators/` | `skills/agents/` | `$$自動化_微型模型$$` 路由目標 |
| **`shared-bot-utils`** | `03_Execution/` | **待評估** | **本次新發現**：含 `textNormalizer.js`、`mediaDownloader.js`，是 LINE/TG 共用工具，可能該進 `shared/` 而非 `skills/` |

#### A-2. 確定不遷移

| 技能 | 原因 |
|---|---|
| `global-workspace` | 已被 `agency-orchestrator` 取代（標記 legacy_notice） |
| `canvas-design` | 已被 `ui-prototype-builder` 取代 |
| `optimization-status` | 動態實驗日誌偽裝成技能，非真正技能 |
| `episodic-consolidation` | 已合併進 `agency-orchestrator`（ADR-0006） |
| `reflection-module` | 已合併進 `agency-orchestrator`（ADR-0006） |
| `self-improvement` | 已合併進 `skill-evolution-governor`（ADR-0006） |
| `skill-governance-skill` | 已合併進 `skill-evolution-governor`（ADR-0006） |
| `handover-manual-skill` | 已合併進 `setup-hhai-skills` |
| `quota-monitor-skill` | 標記 `legacy_notice`，依 `AGENTS.md` §8.3 不遷入主要 bucket。2026-08-29 兩 repo 對帳時發現原清單漏列 |
| `twse-dev-sop-skill` | 已合併進 `setup-hhai-skills` |
| `temp_images` | 執行期暫存圖片，非技能 |
| `skills/Archive/**` | 舊架構封存，逐一評估後只有少數值得復活（見 A-3） |
| `scratch/gemini-notebook-mcp-cli/**/SKILL.md` | 外部套件 notebooklm-mcp-cli 的內附文件，非本專案技能；scratch/ 已列為淘汰 |

#### A-3. Archive 裡值得評估復活的

`chip-logic-expert`（進階籌碼）——已完成冗餘查證：與 ownership-cluster 有中度重疊（前者偏券商借券、融資維持率等動態博弈；後者偏機構持股結構與 CI_INDEX）。Agent 建議合併為單一技能，但考量合併不可逆、且 ownership-cluster 尚未實際使用，決定先維持獨立。待實際使用後若發現需經常同時呼叫，再評估合併。

---

### B. Persona 認知顧問（15 個）

**架構決策已定：採方案 A（維持「設定檔而非技能」的原始設計）**

- 依據 `Data/personas/invocation_guide.md`，persona 明確定義為
  「Configuration Data」而非 Agent，故不放進 `skills/`
- 15 個 persona 的 `references/` 調研資料完整（1.8MB，含一手/二手來源標註），
  但 `SKILL.md` 全部停在 36 行的模板骨架，`name` 欄位全是 `updated-persona`（格式損毀）

**分兩階段處理：**

| 階段 | 內容 | 狀態 |
|---|---|---|
| 階段一 | 建立 `personas/` 目錄，遷移 15 個的 `references/` 調研資料 + `invocation_guide.md`，保全資產 | ⏳ 可立即進行 |
| 階段二 | 重建呼叫鏈（見下方斷鏈清單）、填充 `SKILL.md` | ⏳ 需另立專案 |

**目前斷掉的呼叫鏈：**
- `global-workspace`（攔截 `persona_target`）→ 已淘汰
- `persona-distiller`（蒸餾器）→ 從未存在（舊 repo 也找不到實體）
- `dynamic-tool-synthesizer`（知識編譯）→ 尚未遷移
- `Persona Knowledge MCP`（讀取工具）→ 不存在於 `mcp_config.json`
- `agency-orchestrator` 目前沒有 `persona_target` 處理邏輯

**相關工具：** `nuwa-skill`（github.com/alchaincyf/nuwa-skill，MIT）
— 官方提供 15 個 A 級完整範例（429-541 行，保真度 89-97 分），
與本專案 15 個 persona 清單完全一致，可直接採用官方版本填充。

---

### C. Runtime 執行層（尚未開始）

**核心問題：生產環境的執行程式目前住在「技能文件資料夾」裡。**

`ecosystem.config.js` 顯示 PM2 六大常駐進程的實際來源：
- `skills/03_Execution/line-bot-zero-delay/line-bot-project/bridge.js`
- `skills/03_Execution/telegram-bot-cdp-bridge/telegram-bot-project/dist/bin/cli-zero-delay.js`
- `_archive_legacy_docs/bin/cloudflared.exe` ← 從「封存舊文件」資料夾執行生產程式

**建議目標結構：**
```
HH.AI_v2/
├── skills/     ← 只放 SKILL.md 文件
├── runtime/    ← 實際常駐服務程式碼
│   ├── line-bot/
│   ├── telegram-bot/
│   └── bin/cloudflared.exe
└── shared/     ← 共用模組
```

**PM2 六大常駐進程的實際腳本位置（遷移時必須逐一對應）：**

| PM2 進程名 | 實際腳本 | 備註 |
|---|---|---|
| `line-bridge` | `skills/03_Execution/line-bot-zero-delay/line-bot-project/bridge.js` | 在 skills/ 內，需搬到 runtime/ |
| `tg-bridge-zero-delay` | `skills/03_Execution/telegram-bot-cdp-bridge/telegram-bot-project/dist/bin/cli-zero-delay.js` | 同上，且為編譯後產物（dist/） |
| `line-daemon` | `skills/03_Execution/line-bot-zero-delay/line-bot-project/start_line.js` | 同上 |
| `tg-daemon` | `scripts/tg_daemon.js`（`script: 'node'` + `args`） | **注意：script 欄位是 node，實際路徑在 args** |
| `line-tunnel` | `_archive_legacy_docs/bin/cloudflared.exe` | **從「封存舊文件」資料夾執行生產程式，最高風險** |
| `sync-tunnel` | `scripts/sync_tunnel_url.js`（`script: 'node'` + `args`） | **同 tg-daemon，路徑在 args** |

> 遷移 `ecosystem.config.js` 時，不能只看 `script` 欄位——有兩個進程的實際腳本路徑寫在 `args` 裡。
> 另外所有進程的 `out_file`/`error_file` 都指向 `Data/logs/`，該目錄必須一併遷移。

**待遷移項目：**

| 項目 | 舊位置 | 檔案數 |
|---|---|---|
| `Modules/` | 根目錄 | 18 |
| `scripts/` | 根目錄 | 16 |
| `ecosystem.config.js` | 根目錄 | 1 |
| `00_Master_Menu.ps1` | 根目錄 | 1（`$$LINE連線$$` 一鍵啟動的關鍵） |
| `start_line.ps1`、`start_telegram.ps1` | 根目錄 | 2 |
| `啟動系統.bat`、`00_雙擊啟動_萬能總管.bat` | 根目錄 | 2 |
| `package.json`、`package-lock.json` | 根目錄 | 2 |
| `.env.example` | 根目錄 | 1 |
| `Templates/` | 根目錄 | 1 |
| `.githooks/`、`.system/`、`.state/` | 根目錄 | 6 |

**已識別的共用模組候選（`shared/`）：**
- `Modules/shared/dlpSanitizer.js`（已存在，註解明寫「同時服務 LINE Bot 與 Telegram Bot」）
- `Modules/shared/workspaceLoader.js`（已存在）
- `skills/03_Execution/shared-bot-utils/`（本次新發現：`textNormalizer.js`、`mediaDownloader.js`）
- `writeStateAtomic()`（`reply.js` 與 `reply_tg.js` 重複實作，應抽出）
- Redlock/AGENT_TRANSFER 控制權邏輯（`db_state_manager.js`，見 ADR-0012）

---

### D. `$$` 指令定義收斂（待處理）

`$$LINE連線$$`/`$$TG連線$$` 目前散落在 3 個檔案，且內容互相矛盾：
- `agency-orchestrator-skill`：呼叫 `00_Master_Menu.ps1 -Panel LINE橋接`（基建啟動層）
- `line-bot-zero-delay`：執行 `start_line.js ... true`（控制權接管層）
- `telegram-bot-cdp-bridge`：PM2 重啟 + `start_tg.js` + `poll_tg.js`（兩層都做）

**已確認的正確資料流：**
```
$$LINE連線$$ → agency-orchestrator 辨識
→ 00_Master_Menu.ps1 -Panel LINE橋接（啟動 cloudflared + bridge.js）
→ 委派 line-bot-zero-delay
→ start_line.js（搶控制權）→ poll_inbox.js（常駐監聽）
```
**必須維持「單一 Task 串接」約束（ADR-0009），不可拆成多個獨立 Task。**

處理時機：等 `line-bot-zero-delay`、`telegram-bot-cdp-bridge` 遷移後一次收斂。

---

### E. Data/ 資料層（部分處理）

| 項目 | 決定 |
|---|---|
| `Data/personas/`（15 個 persona） | 遷移（見 B 節） |
| `Data/00_Skill_Manifest.json` | ❌ 不遷移（已查證為無人讀取的死檔案。引用者為 `skills/Archive/dev-scripts/sync_manifest.js`、`massive_optimization_loop.js` 與 `scratch/update_skill.js`，皆屬已淘汰範圍） |
| `Data/skill_translations.json` | ❌ 不遷移（同上。引用者為 `skills/Archive/dev-scripts/` 底下的一次性腳本與 `scratch/update_skill.js`，兩者皆屬已淘汰範圍） |
| `Data/telegram_remoat.db`(+shm/wal) | ❌ 不遷移（使用者確認歷史紀錄不需保留） |
| `Data/logs/` | ⚠️ **必須遷移**：PM2 六大進程的 `out_file`/`error_file` 全部指向此目錄，是活躍寫入路徑，不是歷史資料 |
| `Data/reports/`、各種 `*_audit_report.md` | ⏳ 只留有價值的，需逐一評估 |
| `Data/Agent_Reflections.md` | ⏳ 待評估（`SOP_11` 有引用） |
| `Data/TODO.md`、`Summary_History.md`、`Optimized_History.md` | ⏳ 待評估 |

---

### F. 確定淘汰、不遷移的項目

| 項目 | 原因 |
|---|---|
| `patch.js`、`patch2.js`、`patch_bridge.js` | 一次性臨時修補腳本，用完應刪 |
| `nlm_cookies.txt` | 憑證檔案，不該進版控 |
| `pm2_before.json`、`stress_test_result.json` | 執行期產物 |
| `00_Master_Menu.ps1.bak` | 備份檔 |
| `sandbox_ecosystem.config.js` | 沙盒測試設定 |
| `scratch/` | 暫存目錄 |
| `_archive_legacy_docs/` | 封存文件（但 `bin/cloudflared.exe` 要救出來） |
| `.gemini/`、`.vscode/` | IDE 個人設定 |
| `Data/reports/skills_categorization_report.md` | 過時快照（列出的技能名稱已不存在） |
| `Data/workspace_audit_report.md` | 過時（2026-06-21，8/6 重建前的狀態） |

---

## 三、本次討論的重要發現

1. **`Data/personas/` 的 15 個 persona 不是空殼** — 調研資料完整（1.7MB），
   只有 `SKILL.md` 停在模板狀態未填充。先前判斷為「空殼」是錯的，已更正。

2. **persona 是「設定檔」不是「技能」** — `invocation_guide.md` 明確定義為
   Configuration Data，放在 `Data/` 而非 `skills/` 是刻意的架構決策，不是失誤。

3. **`Persona Knowledge MCP` 的用途查明** — 多個技能 frontmatter 裡的
   `authorized_mcp_tools: ["Persona Knowledge MCP"]`，原來是為了接收編譯後的
   persona 知識。該 MCP 目前不存在於 `mcp_config.json`，先前判斷「不補回」正確。

4. **`shared-bot-utils` 是本次新發現** — LINE/TG 共用工具（`textNormalizer.js`、
   `mediaDownloader.js`），從未在任何遷移清單中出現過，可能該進 `shared/`。

5. **`nuwa-skill` 官方 15 個範例與本專案清單完全一致** — 代表當初是直接
   複製清單但沒帶內容。官方版本是 A 級品質（89-97 分），可直接採用。

6. **全域 SKILL.md 掃描已完成** — 2026-08-26 執行全域搜尋確認，舊專案的技能只存在於以下位置：`skills/01_Orchestrators`、`02_Cognitive`、`03_Execution`、`Archive`、`.agents/skills/`（bot-account-switcher）、`Data/personas/`（15 個 persona），以及 `scratch/` 底下一個外部套件的內附文件（不遷移）。除此之外沒有其他藏在非標準位置的技能，遷移範圍已確定完整。

7. **theme-factory 的 legacy 標記是誤貼，已更正** — 該技能原有
   `legacy_notice: "[LEGACY - 請改用 ui-prototype-builder]"`，與 A-1「確定遷移」
   衝突。2026-08-29 逐檔查證後推翻該標記：`ui-prototype-builder` 全文 693 行中
   「主題」只出現 1 次且為無關語境，其 22 份 `references/` 內沒有任何具名主題
   色板，並不具備 theme-factory 的 10 組預設主題與 CSS Design Token 生成器功能，
   兩者定位也不同（前者從零做原型，後者為既有成品套主題）。該 legacy 字串與
   `canvas-design` 的 frontmatter 一字不差，可判定為整批誤貼。此外新 repo 已有
   三個已遷移技能依賴 theme-factory（`frontend-developer`、`artifacts-builder`、
   `d3js-visualization`），進 `deprecated/` 會造成現役技能依賴棄用技能。
   依 `.agents/rules/git-and-reporting.md` §3「文件自己的宣告不等於事實」，
   移除 legacy_notice 並遷入 `skills/execution/`。`AGENTS.md` §8.3 規則本身維持不變。

8. **Payload 淨化規則的詞彙全庫不一致（追蹤項）** — `[!IMPORTANT]` 區塊的
   淨化規則有兩種寫法：舊分層詞彙（「若本技能為 `Cognitive` 型／`Execution` 型」）
   與 bucket 詞彙（「若本技能屬於 analysis/ 或 orchestration/」）。2026-08-29
   全庫掃描確認舊寫法尚存於 7 個檔案：`analysis/macro-linkage/SKILL.md`、
   `analysis/ownership-cluster/SKILL.md`、`analysis/quant-research-loop/REFERENCE.md`、
   `analysis/sentiment-scout/SKILL.md`、`orchestration/recursive-research-automation/REFERENCE.md`、
   `orchestration/subagent-collaboration/REFERENCE.md`、`platform/langsmith-fetch/REFERENCE.md`。
   本批只統一了新遷移的三個技能，其餘留待單獨一批收斂。

9. **31 個技能的 description 缺少觸發詞（追蹤項）** — `AGENTS.md` §2 規定
   description 要用「情境 + 觸發詞」撰寫，並明訂這是 agent 判斷是否載入技能的
   唯一依據。2026-08-29 建立 `skills/README.md` 三欄索引時發現，54 個技能中有
   31 個只有功能敘述、沒有觸發詞。`validate_skills.py` 只檢查 description 是否
   為空，抓不到「有寫但沒觸發詞」，因此長期隱形。影響：這些技能可能永遠不會被
   模型自主觸發。清單如下：
   - skills/agents/ (執行型): **[investment-aggregator](./agents/investment-aggregator/)**
   - skills/agents/ (執行型): **[line-interaction-manager](./agents/line-interaction-manager/)**
   - skills/agents/ (執行型): **[market-researcher](./agents/market-researcher/)**
   - skills/agents/ (執行型): **[twse-data-analyst](./agents/twse-data-analyst/)**
   - skills/analysis/ (分析型): **[macro-linkage](./analysis/macro-linkage/)**
   - skills/analysis/ (分析型): **[ownership-cluster](./analysis/ownership-cluster/)**
   - skills/analysis/ (分析型): **[quant-research-loop](./analysis/quant-research-loop/)**
   - skills/analysis/ (分析型): **[sentiment-scout](./analysis/sentiment-scout/)**
   - skills/execution/ (工具型): **[artifacts-builder](./execution/artifacts-builder/)**
   - skills/execution/ (工具型): **[changelog-generator](./execution/changelog-generator/)**
   - skills/execution/ (工具型): **[csv-data-summarizer](./execution/csv-data-summarizer/)**
   - skills/execution/ (工具型): **[d3js-visualization](./execution/d3js-visualization/)**
   - skills/execution/ (工具型): **[declarative-visual-intent-generator](./execution/declarative-visual-intent-generator/)**
   - skills/execution/ (工具型): **[pdf](./execution/pdf/)**
   - skills/execution/ (工具型): **[systematic-debugging](./execution/systematic-debugging/)**
   - skills/execution/ (工具型): **[tool-executor](./execution/tool-executor/)**
   - skills/execution/ (工具型): **[webapp-testing](./execution/webapp-testing/)**
   - skills/execution/ (工具型): **[xlsx](./execution/xlsx/)**
   - skills/meta/ (治理型): **[skill-evolution-governor](./meta/skill-evolution-governor/)**
   - skills/orchestration/ (調度型): **[active-inference](./orchestration/active-inference/)**
   - skills/orchestration/ (調度型): **[cost-benefit-router](./orchestration/cost-benefit-router/)**
   - skills/orchestration/ (調度型): **[epistemic-state-governor](./orchestration/epistemic-state-governor/)**
   - skills/orchestration/ (調度型): **[real-time-stream-orchestrator](./orchestration/real-time-stream-orchestrator/)**
   - skills/orchestration/ (調度型): **[reality-checker](./orchestration/reality-checker/)**
   - skills/orchestration/ (調度型): **[recursive-research-automation](./orchestration/recursive-research-automation/)**
   - skills/orchestration/ (調度型): **[stock-orchestrator](./orchestration/stock-orchestrator/)**
   - skills/orchestration/ (調度型): **[subagent-collaboration](./orchestration/subagent-collaboration/)**
   - skills/platform/ (平台整合): **[json-to-flex-renderer](./platform/json-to-flex-renderer/)**
   - skills/platform/ (平台整合): **[langsmith-fetch](./platform/langsmith-fetch/)**
   - skills/platform/ (平台整合): **[mcp-gateway](./platform/mcp-gateway/)**
   - skills/platform/ (平台整合): **[postgres](./platform/postgres/)**
   處理方式：修正上游各技能 `SKILL.md` 的 description，不可在索引檔手動填格。

10. **三層索引的描述各有手工副本，已漂移 12 處（追蹤項）** — 同一份技能描述
    存在於根目錄 `README.md`、bucket `README.md`、`skills/README.md` 三處，
    共 54 × 3 = 162 條手維護字串，無任何一致性機制。2026-08-29 比對 bucket
    README 與 `SKILL.md` 的 description，54 條中有 12 條前 12 字即不一致。
    其中兩條是實質錯誤，已於本批修正：`agents/README.md` 的
    「每日額度僅 5 次」（正確為 100 次，且被外部代理抄進新索引）、
    `orchestration/README.md` 的「06 層級」（舊分層編號殘留）。
    其餘 10 條為改寫差異，暫不處理。
    **根本解法**：由 `SKILL.md` 的 frontmatter 產生下兩層索引，取消手工副本。
    此任務機械性高、範圍明確、可平行，列為多代理委派（Jules）的候選首航任務。

11. **治理文件分類混雜，已排程專批審計（追蹤項）** — 2026-08-29 掃描
    20 份 ADR 的行為指令密度（必須／嚴禁／一律／不得／禁止），發現多份 ADR
    混雜了「決策留痕」與「可執行規範」兩種性質：ADR-0013（78 行 13 句指令）、
    ADR-0016（81 行 6 句）、ADR-0012（39 行 5 句）、ADR-0017（81 行 5 句，
    其「Next.js 應使用 3002」實為規範而非決策）。
    ADR 應只記錄「為什麼這樣決定」，可執行的規範應放在 `.agents/rules/`
    或 `SOP/`。
    **排程**：於第二批 Jules 分支處理完畢後、剩餘技能遷移之前執行。
    理由：Jules 分支有 rebase 時效性須優先；runtime 層將產生多份新 ADR，
    須在該階段開始前立好分類慣例。
    **執行方式**：先做純讀取的分類盤點（依 `AGENTS.md` §0.1 審計階段不動檔案），
    逐份標記「純決策／純規範／混雜」，提清單交使用者裁決後才搬移，
    並產出 ADR-0020 記錄分類標準。
    分類判準採用 `PRINCIPLES.md` §1 的四個判別問句；
    審計過程若發現該判準不足以分類，回頭修訂 `PRINCIPLES.md`。


> [!IMPORTANT]
> **2026-08-29 更新：本節以下記載的是第一批 12 個分支。第二批 12 個分支已產出，
> 尚未處理。** 第二批全部基於 `82ef1f7`。**落後量會隨 main 的每次 commit 增加，
> 合併前務必以 `git rev-list --count $(git merge-base main origin/<branch>)..main`
> 重新實測，不要引用本文件記載的數字。**
> （2026-08-29 記錄當下為 1 個 commit，同日稍後即已增為 6 個。）
> 依檔案交集分為五組，同組內必須依序合併，不可平行：
>
> | 組 | 目標檔案 | 分支 |
> |---|---|---|
> | 1 | `skills/README.md` | `feat/skills-readme-overview`（本批已合併） |
> | 2 | `.../recursive-research-automation/scripts/quota_monitor.py` 及其測試 | `security-fix-quota-monitor-tmp-file`、`fix-model-credits-parsing`、`add-test-quota-monitor` |
> | 3 | `scripts/tests/test_validate_skills.py` | `test-validate-skills-main`、`add-report-results-tests`、`code-health/remove-unused-pytest-import` |
> | 4 | `.../webapp-testing/tests/test_with_server.py`、`scripts/with_server.py` | `test-main-with-server`、`add-timeout-test`、`optimize-server-polling` |
> | 5 | `.../webapp-testing/examples/element_discovery.py` | `perf/optimize-input-discovery`、`perf-optimize-link-discovery` |
>
> **已知須攔截**：`perf-optimize-link-discovery` 在 repo 根目錄新增
> `benchmark_element_discovery.py`，屬夾帶檔案，合併時不得納入。

## 三之二、Jules 自動化修正分支處理狀態

Jules（Google 雲端 AI 代理）於 2026-08-26 對 HH.AI_v2 產出 12 個修正
分支，全部基於 commit 9615558（ADR-0012 那次）。處理狀態如下：

### 已合併

| 分支 | 內容 | 合併 commit |
|---|---|---|
| `fix/security-with-server-cmd-injection-...` | 修正 `with_server.py` 的 command injection 漏洞（移除 `shell=True`），附 5 個單元測試 | 886d891 |
| `perf/parallelize-server-startup-...` | `with_server.py` 改為全部啟動後再統一等待，多 server 場景啟動時間由相加變為取較長者 | 97dafd6 |
| `fix-xss-d3js-tooltip-...` | 修正 `interactive-template.jsx` tooltip 的 XSS 漏洞（HTML entity escaping） | b38e255 |
| `refactor-validate-skills-main-...` | 將 `validate_skills.py` 的 `main()` 拆解為 `validate_bucket_structure`、`validate_skill`、`report_results` 三個函式，並附 5 個單元測試 | e9a382f |
| `perf/optimize-line-counting-...` | 行數計算改用 `count("\n")` 取代 `splitlines()`，避免建立中間 list。**未經 rebase，因重構已將該行移至 `validate_skill()`，改為手動套用該行變更** | 499c98a |
| `test-parse-frontmatter-...`、`test-validate-name-function-...`、`test-validate-description-...` | 三個分支的測試整合進 `scripts/tests/test_validate_skills.py`，測試數由 5 個擴充至 22 個。**未經 rebase，因三個分支寫入同一檔案必然衝突且目標路徑已變更，改為手動整合並統一為 pytest 函式風格** | 3bb9b11 |
| `test-is-server-ready-...` | 補上 `is_server_ready` 的 3 個測試（已合併版本完全未涵蓋此函式），並確認 socket 已正確 mock（實測執行 0.7 秒，若 mock 失效會等待 30 秒 timeout） | 7ce86a4 |
| `remove-unused-usestate-import-...` | 移除 `chart-template.jsx` 未使用的 `useState` import | 7a08678 |
| `jules-...b431935b` | `element_discovery.py` 改用單次 `page.evaluate` 取代 N+1 IPC 往返。**合併時額外加註語意差異說明**：該寫法用 `checkVisibility({checkOpacity: false})`，`opacity: 0` 的元素會被視為可見，與 Playwright `is_visible()` 語意不同 | 4ef1626 |

### 已評估，決定不採用

| 分支 | 不採用理由 |
|---|---|
| `refactor-with-server-script-...` | 基於修正前的舊版做重構，其 `server_manager` 函式仍帶著 `shell=True`，合併會把已修好的 command injection 漏洞改回去。安全修正已新增 `start_server_process` 函式改善結構，不值得為進一步重構承擔風險。**分支保留在遠端，勿刪除，供日後查閱。** |

### 待處理

> 12 個分支已全數處理完畢（11 個合併、1 個評估後不採用）。

> [!NOTE]
> 所有分支均基於 `9615558`，落後 main 多個 commit，合併前需先 rebase。
> 同時修改同一檔案的分支（如 `validate_skills.py` 的兩個分支）務必依序
> 處理，不可平行合併。
> 已合併的四個分支中，有三個夾帶了未在 commit message 中說明的
> 額外檔案（根目錄 `tests/`、`.gitignore` 修改）。合併任何 Jules
> 分支前，務必執行 `git diff origin/main --stat` 確認實際異動範圍，
> 不可只依據分支名稱或 commit message 判斷。

---

## 四、更新紀錄 (Update Log)
- **2026-08-29**：新增 ADR-0018（vendored 外部資產保留 fork 與三層標示）與
  `AGENTS.md` §8.5；遷移 3 個 execution 技能（image-enhancer、theme-factory、
  playwright-automation），三份均移除重複 type/version/capabilities 欄位、
  改寫 Zero-Block Policy、拆出 REFERENCE.md、清除 canvas-design 等死引用；
  收斂 `webapp-testing` 與 `playwright-automation` 的響應式截圖重疊；
  修復根目錄 README.md 4 處 ESC 控制字元損毀。技能總數 51 → 54。
  同批統一三個新技能的 Payload 淨化規則詞彙為 bucket 寫法、修正日文漢字
  「適用対象」與簡繁誤譯「驗證已透過」，並修正根目錄 README 的 Jules
  每日額度過時資訊（5 次 → 100 次）。
- **2026-08-26**: 復活 `ownership-cluster` 與 `macro-linkage`，由 A-3 區塊移除並納入 `skills/analysis/`。
- **2026-08-26**：合併 Jules 兩個 with_server.py 修正分支（command injection 安全修正 + 啟動平行化），引入 HH.AI_v2 首批自動化測試（5 個，全數通過），並建立 requirements.txt。
- **2026-08-26**：修正 stock-orchestrator 的舊分層編號路由（6 個 SYSTEM-CALL 路徑更新為 analysis/ 格式）；合併 Jules 的 d3js tooltip XSS 修正分支。
- **2026-08-26**：合併 Jules 的 validate_skills.py 重構與行數計算優化；新增 ADR-0017（port 分配規範）；HH.AI_v2 自動化測試累積至 10 個（5 個測 with_server.py、5 個測 validate_skills.py）
- **2026-08-26**：Jules 12 個分支全數處理完畢。合併 11 個（2 個安全修正、3 個效能優化、1 個重構、4 個測試分支、1 個清理），1 個評估後不採用。HH.AI_v2 自動化測試由 0 增至 30 個。
- **2026-08-25**：`bot-account-switcher` 遷移至 `skills/agents/`
- **2026-08-26**：6 個 analysis 型技能遷移完成
  （evidence-collector、software-architect、backend-architect、data-engineer、devops-engineer、twse-market-logic）
- **2026-08-26**：4 個 execution 型技能遷移完成
  （tool-executor、frontend-developer、declarative-visual-intent-generator、gemma-4-api）
- **2026-08-26**：4 個 orchestration 型技能遷移完成
  （subagent-collaboration、recursive-research-automation、cost-benefit-router、epistemic-state-governor）
- **2026-08-26**：遷移 4 個技能 (`sentiment-scout`, `quant-research-loop`, `langsmith-fetch`, `json-to-flex-renderer`) 至 `analysis/` 與 `platform/`，修正舊版 bucket 參照並分離出 REFERENCE.md，清查 `SKIP_LOCK` 繞過機制（未於 loop 內實作，留存記錄），完成環境指南的交叉引用。
