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
| `Data/Execution_Plans/`（`Architecture_Compliance_Plan_20260618.md`） | ⏳ 待評估。**此前完全未列入本表**，2026-09-02 盤點時才發現。舊 `Data/TODO.md` 有一項未完成待辦要求「建立計畫書的儲存、命名與長期保留標準規範並寫入 SOP」，與本項同源 |
| `_archive_legacy_docs/`（5 份舊 ADR、`audit_events.md`、`capacity-planning.md`、`release-checklist.md`、`incidents/incident-template.md`） | ⏳ 待評估。此前僅 `bin/cloudflared.exe` 被提及，其餘從未盤點 |

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
   - skills/agents/ (執行型): **[investment-aggregator](../skills/agents/investment-aggregator/)**
   - skills/agents/ (執行型): **[line-interaction-manager](../skills/agents/line-interaction-manager/)**
   - skills/agents/ (執行型): **[market-researcher](../skills/agents/market-researcher/)**
   - skills/agents/ (執行型): **[twse-data-analyst](../skills/agents/twse-data-analyst/)**
   - skills/analysis/ (分析型): **[macro-linkage](../skills/analysis/macro-linkage/)**
   - skills/analysis/ (分析型): **[ownership-cluster](../skills/analysis/ownership-cluster/)**
   - skills/analysis/ (分析型): **[quant-research-loop](../skills/analysis/quant-research-loop/)**
   - skills/analysis/ (分析型): **[sentiment-scout](../skills/analysis/sentiment-scout/)**
   - skills/execution/ (工具型): **[artifacts-builder](../skills/execution/artifacts-builder/)**
   - skills/execution/ (工具型): **[changelog-generator](../skills/execution/changelog-generator/)**
   - skills/execution/ (工具型): **[csv-data-summarizer](../skills/execution/csv-data-summarizer/)**
   - skills/execution/ (工具型): **[d3js-visualization](../skills/execution/d3js-visualization/)**
   - skills/execution/ (工具型): **[declarative-visual-intent-generator](../skills/execution/declarative-visual-intent-generator/)**
   - skills/execution/ (工具型): **[pdf](../skills/execution/pdf/)**
   - skills/execution/ (工具型): **[systematic-debugging](../skills/execution/systematic-debugging/)**
   - skills/execution/ (工具型): **[tool-executor](../skills/execution/tool-executor/)**
   - skills/execution/ (工具型): **[webapp-testing](../skills/execution/webapp-testing/)**
   - skills/execution/ (工具型): **[xlsx](../skills/execution/xlsx/)**
   - skills/meta/ (治理型): **[skill-evolution-governor](../skills/meta/skill-evolution-governor/)**
   - skills/orchestration/ (調度型): **[active-inference](../skills/orchestration/active-inference/)**
   - skills/orchestration/ (調度型): **[cost-benefit-router](../skills/orchestration/cost-benefit-router/)**
   - skills/orchestration/ (調度型): **[epistemic-state-governor](../skills/orchestration/epistemic-state-governor/)**
   - skills/orchestration/ (調度型): **[real-time-stream-orchestrator](../skills/orchestration/real-time-stream-orchestrator/)**
   - skills/orchestration/ (調度型): **[reality-checker](../skills/orchestration/reality-checker/)**
   - skills/orchestration/ (調度型): **[recursive-research-automation](../skills/orchestration/recursive-research-automation/)**
   - skills/orchestration/ (調度型): **[stock-orchestrator](../skills/orchestration/stock-orchestrator/)**
   - skills/orchestration/ (調度型): **[subagent-collaboration](../skills/orchestration/subagent-collaboration/)**
   - skills/platform/ (平台整合): **[json-to-flex-renderer](../skills/platform/json-to-flex-renderer/)**
   - skills/platform/ (平台整合): **[langsmith-fetch](../skills/platform/langsmith-fetch/)**
   - skills/platform/ (平台整合): **[mcp-gateway](../skills/platform/mcp-gateway/)**
   - skills/platform/ (平台整合): **[postgres](../skills/platform/postgres/)**
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

> [!NOTE]
> **第二批第 2 組（quota_monitor.py 相關三個分支）— 2026-08-29 評估後全數不採用**
>
> | 分支 | 不採用理由 |
> |---|---|
> | `security-fix-quota-monitor-tmp-file` | 修正方向正確（將暫存檔從 CWD 移至家目錄，符合本專案「暫存檔不寫入 repo」規則），但目標檔案已刪除 |
> | `fix-model-credits-parsing` | **即使目標檔案未刪除也不應採用。** 它以推測（假設為 zlib 壓縮的 JSON）取代原本刻意保守的 TODO，且 `find_percent()` 會回傳第一個命中 `remaining`／`quota`／`percent` 等鍵名的數值，不驗證其是否為百分比。若該結構含 `quota: 5000` 之類的總點數，會被當成「剩餘 5000%」回傳，導致熔斷永遠不觸發。這是把安全失敗改成不安全失敗，違反 `PRINCIPLES.md` §2.6 |
> | `add-test-quota-monitor` | 為已刪除的檔案新增 140 行測試，會把失效實作凍結進測試套件。且其測試寫死 `current_quota.tmp` 檔名（6 處），與同組的安全修正分支直接衝突 |
>
> 三個分支比照第一批 `refactor-with-server-script` 的處理方式：
> **保留在遠端不刪除**，供日後查閱；GitHub PR 關閉並留言說明理由。

12. **配額熔斷的錨定缺口，與 `quota_monitor.py` 的處置（追蹤項）**

    **背景**：`$$自動化$$` 系列指令設計為無人值守的自主研究模式，
    使用者休息時由 Agent 自行運作。10% 熔斷是防止 Agent 把週期性額度耗盡的
    唯一煞車機制（`SOP_01` §2.2）。

    **2026-08-29 查證發現，新舊兩套實作量測的不是同一件事：**

    | | `quota_monitor.py`（舊） | `Modules/quota_manager.js`（新） |
    |---|---|---|
    | 量測對象 | Gemini 真實剩餘額度（讀 IDE 的 `state_copy.vscdb`） | 本 session 自我申報的累積消耗 |
    | 起算點 | 外部真實值 | 從 0 開始 |
    | 熔斷條件 | 剩餘 ≤ 10% 停止 | 本 session 用掉 > 10% 停止 |
    | 讀不到時 | 回傳 `None`，要求人工注入（安全失敗） | 見下方 |

    `SOP_01` §2.2 宣告的「全面廢棄舊實作」是一次**語意置換而非等價替換**。
    新實作解決了 Race Condition，但捨棄了「錨定真實外部額度」的能力。
    舊的 `current_quota.tmp` 人工注入（`echo 80 > current_quota.tmp`）
    正是該錨定機制。

    **未處理的風險**：`quota_manager.js` 第 98-106 行有降級放行邏輯——
    `DATABASE_URL` 未設定或 Neon DB 不可用時，`check_and_consume_quota`
    直接 `return { usedAfter: 0, status: 'OK' }`。有人值守時這是合理降級，
    **無人值守時等同煞車失靈**，方向與舊實作相反。

    **本次處置**：刪除 `quota_monitor.py`。理由：其解析路徑
    （IDE sqlite 的 `本協作系統UnifiedStateSync.modelCredits` 鍵值）已因該值
    改為二進位／壓縮格式而失效；且使用者回報 IDE 已改版，該機制是否仍存在
    **未經驗證**。保留一份「可能可用也可能早已失效」的程式碼，會誤導後續
    讀取者假設它可用。知識以本條記錄保存，程式碼不保留。

    **待辦（runtime 層遷移時處理）**：
    - `Modules/quota_manager.js` 為 `recursive-research-automation/REFERENCE.md`
      的明文依賴，`Modules/` 遷移時不可遺漏
    - 補上真實額度的錨定機制（至少恢復人工注入路徑）
    - 檢討降級放行邏輯：無人值守模式下應改為安全失敗（拒絕執行並通報），
      而非放行
    - 若要重新嘗試自動讀取真實額度，起點為 IDE 的 `state_copy.vscdb`，
      但需先確認新版 IDE 是否仍使用相同儲存機制

13. **多代理自治閉環（LOOP）正式立案（排程項）**

    使用者的目標是建立兩層閉環，目前兩層都尚未完整運作。

    **內層：`$$自動化$$` 無人值守自主研究**

    使用者休息時啟動，由 Antigravity Agent 自行運作，消耗 Gemini 週期性額度，
    以 10% 熔斷防止額度耗盡。現況：

    | 元件 | 位置 | 狀態 |
    |---|---|---|
    | 指令路由（4 條） | `SOP/SOP_00A_Master_Index.json` | ✅ 已遷移 |
    | 三選項模式選單 | `orchestration/agency-orchestrator/SKILL.md#自動化指令攔截` | ✅ 已遷移 |
    | 授權協議 | `SOP_01` §2.4（`$$自動化$$`／`$$Allow All$$`） | ✅ 已遷移 |
    | 10% 熔斷規範 | `SOP_01` §2.2 | ✅ 已遷移 |
    | 10% 熔斷實作 | `Modules/quota_manager.js` | ❌ 未遷移，見第 12 點 |
    | 模式 1：微型模型調參 | `autoresearch-agent`（舊 repo 9 檔） | ❌ 未遷移 |
    | 模式 2：通用遞迴研究 | `orchestration/recursive-research-automation` | ✅ 已遷移 |
    | 模式 3：量化實驗 | `analysis/quant-research-loop` | ✅ 已遷移 |
    | `SKIP_LOCK` 繞過機制 | `train_cpu.py:240`、`auto_optimize_controller.py:221` | ❌ 未遷移，ADR-0012 未記載 |

    **已知缺陷**：`$$自動化$$` 目前會跳出三個選項，但選項 1 會走到
    `PENDING_MIGRATION` 死路（模式 1 尚未遷移）。使用者現在即可觸發此問題。

    **外層：多代理委派閉環**

    Claude 產出 Mission Brief → Antigravity 以 `google-jules` MCP 派發 →
    Jules 雲端執行並開 PR → Claude 讀 PR diff 審查 → Antigravity 合併。
    來源為 2026-08-29 使用者提供的「多代理自治協同閉環架構提案報告」（Gemini 撰寫）。
    該提案的架構方向可採，但其中若干技術細節未經驗證，不可直接落地：
    - `create_session` 的 `source`／`starting_branch`／`automation_mode` 參數未驗證
      （已驗證的必填參數只有 `prompt`）
    - 提案寫的 `send_message` 工具不存在，實際為 `send_reply_to_session`
    - 「最多 15 個並行」無依據，CLI 的 `--parallel` 上限為 5
    - 提案建議的 `SOP-0012` 命名與現有 `SOP_12` 撞號且分隔符不一致
    - `.agents/workflows/` 目錄型態尚未存在，新增屬架構決策

    **排程與理由**：
    1. 剩餘技能遷移批 — `autoresearch-agent` 遷入 `agents/`，補 ADR 記載 `SKIP_LOCK`
    2. runtime 層 — `Modules/quota_manager.js` 遷入，處理第 12 點的錨定缺口與降級放行
    3. 內層 LOOP 可實際運作後，才建置外層

    順序理由：兩層 LOOP 都在無人值守下運行，都依賴同一個煞車機制，
    而該機制目前是壞的（第 12 點）。**先修煞車，再放車出去。**

    **上游參考**：`karpathy/autoresearch`（MIT）。核心設計是
    「人類迭代 `program.md`、agent 只修改 `train.py`」——單一可修改檔案讓範圍可控、
    diff 可審查；固定時間預算讓實驗可互相比較。
    本專案的 `program_cpu.md` 對應上游的 `program.md`，遷移時應視為技能文件
    （人類調校介面），而非資料檔。
    上游無配額熔斷概念（跑自有 GPU，成本是電費不是額度），
    本專案的 10% 熔斷為自創需求，無上游解法可參照。

14. **`karpathy` 其他專案的探勘（低優先，時間盒待辦）** — 使用者於 2026-08-29
    指出 `karpathy` 的 GitHub 尚有其他可參考的專案。已確認相關的
    `karpathy/autoresearch` 與其父專案 `karpathy/nanochat`（提供更廣的平台支援，
    含 CPU 與其他裝置的解法）。
    **排程**：技能遷移與 runtime 層收尾之後執行，且必須設定明確範圍與時間盒，
    避免開啟無邊界的探索。**不在本階段展開。**

15. **`.gitignore` 的暫存樣式誤擋正式腳本，與一筆訊息不符的 commit（已處理）**

    **問題一**：2026-08-29 新增 `scripts/check_consistency.py` 時，
    該檔名命中 `.gitignore` 的 `check_*.py` 規則被靜默忽略，
    必須以 `git add -f` 強制加入才進得了版控。
    根因是「Agent 一次性暫存腳本」的忽略樣式原本只針對 repo 根目錄，
    卻寫成了全域樣式，連帶會誤擋 `scripts/` 底下的
    `check_*` / `update_*` / `fix_*` / `migrate_*` / `write_*` /
    `batch*` / `process*` / `verify*` / `gather*` 等正式腳本。
    失效方式是靜默的——`git status` 顯示乾淨，人以為已提交，實際沒有。
    **處置**：所有暫存樣式加上 `/` 前綴限定於根目錄；
    `*.tmp` 維持全域（執行期產物在任何目錄都不該進版控）。

    **問題二**：commit `6177109` 的訊息為
    `feat: add repo-wide consistency checker and downgrade hash to optional`，
    但該 commit 實際只含兩個 `.md` 檔案，checker 本身在下一筆 `bb08df0`。
    成因即問題一的忽略規則。歷史不改寫（依 `PRINCIPLES.md` §3.3），
    在此記錄以免日後查 `git log` 時誤判。

16. **Gitleaks 偵測能力實測，與資安層級的定位（已裁決）**

    2026-08-29 實測 gitleaks 8.30.1（`winget install Gitleaks.Gitleaks`），
    以自行產生的假憑證測試六種本專案實際使用的樣式：

    | 樣式 | 偵測結果 | RuleID |
    |---|---|---|
    | `ghp_` GitHub PAT | 命中 | `github-pat` |
    | `ntn_` Notion Token | 命中 | `generic-api-key` |
    | Jules API Key（39 碼隨機） | 命中 | `generic-api-key` |
    | Google session cookie（`OSID=g.a000...`） | **未命中** | — |
    | `NLM_SESSION` / `SID=` 長字串 | **未命中** | — |
    | `postgresql://user:password@host` 連線字串 | **未命中** | — |

    **關鍵結論**：對舊 repo 全歷史掃描，`nlm_cookies.txt`（commit `9552009`，
    已確認存在於 `origin/main` 公開歷史）**完全沒有被偵測到**。
    亦即本專案唯一真正外洩至公開 GitHub 的憑證，gitleaks 預設規則看不見。
    即使當初就部署 gitleaks，該次外洩仍會發生。

    **附帶查證：`.env.local` 的三筆命中並未外洩。**
    掃描在 commit `f42bc43` 命中 `.env.local` 的 GitHub PAT、Notion Token 與 JWT，
    另在 `61a5f93` 命中一筆。以完整 clone 驗證後確認，
    **這兩個 commit 皆不存在於遠端**（遠端僅有 `main` 與
    `autoresearch/20260613` 兩個分支），屬本機獨有，與 ADR-0016 記載的
    「`git reset --soft` 退回、未推送」相符。

    **已確認的誤報兩筆**（`generic-api-key` 依熵值判斷，易誤中）：
    - `HH.AI_v2` 的 `skills/orchestration/security-auditor/SKILL.md`——
      該處為資安技能自身的偵測範例字串
    - 舊 repo 的 `scripts/sync_tunnel_url.js`——
      經查該處僅為註解文字，無實際金鑰

    **裁決（使用者，2026-08-29）**：不部署 gitleaks pre-commit hook，
    不撰寫 `.gitleaks.toml` 自訂規則。理由：本專案自始使用測試帳號，
    後續將全盤更換金鑰與 Google 帳號；使用者已親自驗證 Google 帳號
    無他人登入紀錄。**資安實作層級定位為「記錄與人工審查」，不做自動化攔截。**

    **若日後改變此定位，重啟的起點**：
    - 必須撰寫 `.gitleaks.toml` 自訂規則，至少涵蓋 Google session cookie
      （`OSID=`／`SID=` 加長隨機字串）、`NLM_` 前綴、
      `postgresql://` 含密碼的連線字串、以及 `*cookies*` 類檔名樣式；
      僅靠預設規則無法涵蓋本專案的實際風險
    - 需以 allowlist 排除上述兩筆已知誤報，不得改為關閉整條規則
    - `gitleaks` 經 winget 安裝後**不在 PATH 上**（與 `notebooklm-mcp` 同類問題），
      hook 腳本必須使用完整路徑或先行偵測
    - pre-commit hook 為本地機制，`git commit --no-verify` 可完全跳過。
      此缺口本地無法彌補，僅有 CI 能堵住。任何文件不得宣稱高於此的保護等級

17. **`skill-evolution-governor` 的四處過期規範（2026-09-01 已修正）**

    治理文件分類審計期間發現，`skills/meta/skill-evolution-governor/SKILL.md`
    保留了四處已被現行架構取代的規範。該技能為 `disable-model-invocation: true`，
    不會自動觸發，但一旦被使用者呼叫執行技能治理，會依錯誤規則行動。

    | 位置 | 過期內容 | 處置 |
    |---|---|---|
    | 原 21-29 行 | 六大分類體系（domain/tools/mindset/governance/ux/automation） | 改為指向 `AGENTS.md` §1 七桶 |
    | 原 31-38 行 | 舊版不刪除原則，未區分兩種刪除情境 | 改為指向 guardrails §4，保留安全邊界定位（ADR-0006） |
    | 原 40-49 行 | 以「DLP 宣告行是否存在」作為合規判準 | 改為指向 SOP_02 §1 與 guardrails §3，明令廢止該判準 |
    | 原 68-71 行 | 依賴已成死檔案的 `00_Skill_Manifest.json` | 改為 validate_skills + check_consistency + 三層 README |

    **這是 HANDOVER §5.5「DLP 安全宣告為裝飾性樣板」的源頭。** 該追蹤項先前
    只記錄了現象，未查出是哪份文件在要求。斷源已完成。

    **未完成（存量）**：全庫仍有 25 份 `SKILL.md` 帶有該宣告行，待單獨一批清理。
    清理時屬 guardrails §4 情況 B，可直接物理刪除，不需歸檔。

    **數字更正**：HANDOVER §5.5 原記載「出現在 32 份 SKILL.md」。
    2026-09-01 實測現行 HEAD，三種算法分別為：SKILL.md 檔案數 25、
    含其他副檔名的檔案數 31、SKILL.md 內出現行數 33，無一等於 32。
    正確值為 **25 份 SKILL.md**。32 的來源未查明，不作推測。

18. **SOP 遷移期的兩類缺失，與已知缺陷清理（2026-09-01）**

    治理文件審計逐份比對舊 repo `SOP/` 的 21 份文件與 v2 的 10 份，
    數量對得上（21 = 10 遷移 + 11 淘汰／轉換，與 `SOP/README.md` 一致），
    但發現兩類共通缺失：

    **缺失類型一：淘汰理由未逐項驗證「取代」是否成立。**
    `SOP_03_Skills_Maintenance.md` 的淘汰理由寫「已被 `validate_skills.py`
    與 `AGENTS.md` 取代」，但其 §4.2 品質驗證清單六項中，`validate_skills.py`
    只涵蓋一項（`name` 非空）。其中「`description` 須包含觸發關鍵字說明」
    這一條被丟棄後，兩個月後以「31 個技能 description 缺觸發詞、
    `validate_skills.py` 抓不到」的形式被重新發現，記載於 `SOP_14` §6.1。
    §4.3 的四條常見違規（含「禁止 `TODO` 佔位符留在正文」）亦全數遺失。

    **缺失類型二：紀錄措辭以「轉為 X」概括了「一節轉為 X、其餘淘汰」。**
    `SOP_00_Skill_Lifecycle_Management.md` 與 `SOP_10_AI_Command_Center.md`
    兩處已於本日修正（見 `SOP/README.md`）。

    查證結論：`SOP_07`、`SOP_08`、`SOP_10` 三份的淘汰處置正確，無實質遺失
    （`SOP_08` §3 的 `$$自動化$$`／`$$Allow All$$` 授權參數已保全於
    `SOP_01` §2.4、`SOP_00A` 路由表與 `SOP_06`）。`SOP_03` 的方向正確但有遺失。

    **本日已清理的六處缺陷**：

    | 缺陷 | 檔案 | 處置 |
    |---|---|---|
    | 範本示範 `type:` 但驗證器不接受 | `templates/SKILL.md.template` | 移除該行 |
    | 漏改的節名交叉引用 | `skills/meta/skill-evolution-governor/SKILL.md` | 更新第 14 行 |
    | 五個死依賴 | `skills/orchestration/subagent-collaboration/SKILL.md` | 見下 |
    | 舊分層詞彙與失效節號 | 同技能 `REFERENCE.md` | 統一為 bucket 寫法 |
    | 兩處紀錄措辭不精確 | `SOP/README.md` | 改為逐節列明 |
    | 第 17 點位置錯置 | 本檔案 | 移回第三章節 |

    `subagent-collaboration` 的五個死依賴為 `Template_00_Universal_Skill.md`
    （不存在）、`SOP_00_New_Skill_Onboarding.md`（已淘汰）、
    `Data/skill_translations.json`（不遷移）、技能 `type` 欄位（已移除）、
    Neon DB 寫入（模組未遷移）。**同時移除兩條不安全失敗路徑**
    （`is_onboarding_test` 旁路旗標與 `DEFAULT_FALLBACK` 回退），
    兩者皆為「跳過安全淨化以避免死鎖」；改為 bucket 路徑直接判斷型別後，
    死鎖前提已不存在，遇不明目標一律停下詢問。

    **待辦**：`SOP_03` §4.2／§4.3 的品質驗證清單，與
    `SOP_00_Skill_Lifecycle` §一至§四，兩者性質同屬技能生命週期治理，
    規劃合併為一份新的 `SOP/SOP_03_Skill_Lifecycle_and_Quality.md`，
    另批處理。同批應評估把「`description` 是否含觸發詞」加入
    `scripts/validate_skills.py` 作為**警告**（不是錯誤，因現存多個技能會失敗）
    ——規範寫在文件裡而工具抓不到，正是本次遺失能潛伏兩個月的原因。

19. **回報虛構事件、協作通則補記，與舊分層詞彙的清單（2026-09-01）**

    **事件**：`20aa619` 批次中，六個檔案的實際改動經獨立 clone 逐行 diff
    確認與指令逐字相符，但回報貼出的四份「完整內容」與實際檔案整份不同。
    四份中三份的總行數亦不符（回報 100／46／37，實際 103／48／36）。
    處置：`.agents/rules/git-and-reporting.md` §2 已補一條，
    要求讀檔失敗時必須明說失敗、嚴禁以記憶補寫。
    `docs/HANDOVER.md` §10.1 已新增第 15 種出錯模式。

    **通則補記**：使用者要求「每一次回覆的結尾都直接附上下一步提示詞」，
    此偏好在先前對話中一直存在但從未寫入文件，屬 `PRINCIPLES.md` §3.2
    「只存在於對話中等同於沒有記錄」的案例，已補入 `HANDOVER` §8.1。

    **舊分層詞彙的待收斂清單（6 個檔案、12 行）**：

    | 檔案 | 行 |
    |---|---|
    | `skills/analysis/macro-linkage/SKILL.md` | 123、124 |
    | `skills/analysis/ownership-cluster/SKILL.md` | 121、122 |
    | `skills/analysis/quant-research-loop/REFERENCE.md` | 28、29 |
    | `skills/analysis/sentiment-scout/SKILL.md` | 130、131 |
    | `skills/orchestration/recursive-research-automation/REFERENCE.md` | 53、54 |
    | `skills/platform/langsmith-fetch/REFERENCE.md` | 57、58 |

    十二行皆為同一段複製而來的樣板（「若本技能為 `Cognitive`／`Execution` 型⋯」），
    應統一改為 bucket 寫法，比照
    `skills/orchestration/subagent-collaboration/REFERENCE.md` 第 41-44 行
    已收斂的版本。**另注意兩處用詞不一致**：`ownership-cluster:122` 與
    `sentiment-scout:131` 寫「拒絕認知**引數**」，其餘四份寫「拒絕認知**參數**」，
    收斂時一併統一為「參數」。

    **不算殘留、應保留的兩處**（依 `git-and-reporting.md` §3 區分行為指令與歷史紀錄）：
    `skills/orchestration/subagent-collaboration/REFERENCE.md` 第 23-24 行的版本紀錄、
    `skills/orchestration/agency-orchestrator/SKILL.md` 第 107 行
    （該行已是 bucket 寫法，只是句中出現 `Cognitive` 一詞）。

20. **舊分層詞彙收斂與三處斷鏈清理（2026-09-01）**

    **A. 舊分層詞彙（第 19 點的清單，已全數處理）**

    六個檔案共十二行的樣板原寫「若本技能為 `Cognitive` 型⋯若本技能為
    `Execution` 型⋯」。除了詞彙過期，這個寫法本身也不成立——每個技能的
    bucket 是固定的，不存在「若是 A 型／若是 B 型」的二選一。因此改寫為
    依各技能實際所在 bucket 的確定敘述，並指向
    `.agents/rules/skill-engineering-guardrails.md` §3 為規範本體。
    原引用的 `(§6.3)` 是已不存在的 `SOP_00_Skill_Lifecycle` 章節編號。

    `skills/orchestration/subagent-collaboration/REFERENCE.md` 沿用的是
    「目標在 X」的框架，與本批的「本技能位於 X」不同，**這是刻意的**：
    前者是淨化責任方，判斷「要送給誰」；後者是被送達方，判斷「自己能收什麼」。
    兩種框架並存正確，不是漂移。

    **B. 三處死引用（宏觀審計維度一：拓撲斷鏈）**

    | 位置 | 死引用 | 處置 |
    |---|---|---|
    | `skills/execution/changelog-generator/SKILL.md` | `handover-manual-skill`（已併入 `setup-hhai-skills`） | 改指向 `setup-hhai-skills` |
    | `skills/platform/langsmith-fetch/REFERENCE.md` | `optimization-status`（判定不遷移，無替代） | 整行刪除 |
    | `.agents/rules/skill-engineering-guardrails.md` | `subagent-collaboration-skill`（名稱多 `-skill` 後綴，且稱「待遷移」已失效） | 改為正確名稱與現況 |

    第三項是**自動載入的規則檔**，每次任務都會被 Agent 讀到，
    卻描述著兩個月前就完成的狀態，影響面最大。

    **C. 本批未處理、已識別的兩項（待排程）**

    - **`description` 引號寫法不一致**：54 個技能中 26 個加引號、28 個未加。
      功能無影響（YAML 兩種寫法皆合法），但屬 ADR-0007 維度二明列的收斂對象；
      `name` 欄位的同類問題正是 ADR-0007 成立的原始理由之一。
    - **缺檔尾換行 18 個檔案**：會使 `wc -l` 與 `len(splitlines())` 對同一檔案
      給出不同行數，而行號＋總行數是 `.agents/rules/git-and-reporting.md` §2
      的主要核對依據。建議補入 `scripts/check_consistency.py` 作為 CHECK 8。

21. **（編號保留）本點原規劃內容已併入第 25 點**

    2026-09-01 審計官規劃「Payload 淨化樣板第二變體」一節時，
    原定編號為 21，後因批次順序調整改寫為第 25 點，
    但編號空缺未補、兩處引用未同步。

    **編號保留不刪除**，避免「20 跳到 22」被誤讀為內容遺失。
    實際內容見第 25 點。

22. **角色身分的層級錯置與文字洩漏（2026-09-01）**

    **問題一：身分定義此前沒有任何規範層文件承載。**

    | 位置 | 內容 | 層級 |
    |---|---|---|
    | `docs/adr/0007-macro-auditor-role.md` | 完整定義＋四維度＋Gatekeeping＋報告格式 | 第 3 層（留痕） |
    | `PRINCIPLES.md` §2.5 | 只有一句「角色分工的理由見 ADR-0007」 | 最高層，但只是指向 |
    | `AGENTS.md`／`MISSION.md`／`.agents/rules/` | 完全沒有提及 | — |

    依 `PRINCIPLES.md` §1，留痕層是「只追加不改寫的歷史」，
    不該承擔「現在的規則是什麼」。更關鍵的是，`PRINCIPLES.md` 自己的
    多條原則建立在這個未定義的前提上——§2.5 第 72 行寫
    「執行者的文字回報不作為驗收依據」，但誰是執行者、誰在驗收，
    整份文件從未定義。**這是最高層文件的承重假設從未被寫下來。**

    處置：新增 `PRINCIPLES.md` §0，比照 `AGENTS.md` §0 的做法用編號 0，
    既有 §1–§5 不重新編號，所有交叉引用不受影響。

    **問題二：文字洩漏路徑已存在。**

    | 文件 | 行 | 內容 |
    |---|---|---|
    | `SOP/README.md` | 4 | 「這些文件是**所有 AI 代理人**與開發者必須遵守的最高指導原則」 |
    | `SOP_14` | 126 | 「本節適用於**所有審計角色，包含 ADR-0007 定義的宏觀審計官**」 |

    兩句串起來，執行者可合理推論自己具有宏觀審計官身分——
    不需要提示詞出現任何關鍵字，光讀文件就會如此理解。
    另 `SOP_14` §0 第 21 行的觸發條件為純關鍵字，無角色限定。

    另一項成因：repo 中「審計」一詞已有四種不同意思
    （聯席審計、資安審計、技能生態治理審計、宏觀審計），
    此前沒有任何文件說明其差異。已列為 `PRINCIPLES.md` §0.3。

    **處置原則：身分錨定，不用關鍵字黑名單。** 關鍵字清單一定會漏。
    改用可自我判斷的分界：「這件事是『照著做』，還是『決定要不要做』？」

    | 層 | 措施 |
    |---|---|
    | 最高層 | `PRINCIPLES.md` §0（身分定義本體，雙方共讀） |
    | 第 1 層（自動載入） | 新增 `.agents/rules/role-boundaries.md` |
    | 第 1 層（執行者規範） | `AGENTS.md` §0 新增第 6 條，指向 §0 |
    | 洩漏點 | `SOP_14` 第 126-127 行改寫，明確排除執行者自任 |
    | 觸發條件 | `SOP_14` §0 第 21 行加註區分 |

    **關於「要不要請 Antigravity 自我確認身分」**：審計官判斷不採用。
    一個角色對自己身分的自評，正是 ADR-0007 明令不採信的那類宣稱，
    無法作為未越界的證據。改採行為觀察——從後續批次是否出現
    「自行決定修改範圍」「主動評價他方產出」來判斷，成本更低也更可靠。

    **同批順手修正**：`MISSION.md` 第 20 行的簡體字「换」→「換」。
    全庫掃描確認這是唯一一處，違反 `SOP_01`／`SOP_02` 嚴禁簡體中文。

    **待辦（批 5b）**：建立 `.claude/` 目錄存放審計官作業程序，
    與 `.agents/` 鏡像對稱；ADR-0007 的四個審計維度、Gatekeeping 規則、
    報告格式模板搬入該目錄，ADR 只保留角色定位與「為什麼不由執行者兼任」；
    屆時在 `PRINCIPLES.md` §0.4 與 `AGENTS.md` §0 補上對該目錄的宣告。
    本批**刻意不提前寫入**，避免產生指向不存在目錄的失效引用。

    **待辦（工具層）**：`scripts/check_consistency.py` 建議增補兩項檢查——
    (1) 檔尾換行符（現有 18 個檔案缺，會使 `wc -l` 與 `len(splitlines())`
    對同一檔案給出不同行數）；(2) 簡體字掃描（本次靠人工掃描才發現）。

23. **ADR-0007 分層搬移、`.claude/` 目錄建立、第三次回報虛構（2026-09-01）**

    **A. ADR-0007 的分層搬移**

    ADR-0007 原本混雜兩種性質：Context 與 Consequences 是留痕，
    但「四個審計維度」「Gatekeeping 規則」「報告格式」（第 29-70 行，
    佔全檔 42/77 行）是可執行規範。依 `PRINCIPLES.md` §1，
    規範應在第 1 或第 2 層，ADR 只留「為什麼」。

    保留在 ADR 的是：問題起源、「由誰執行審計」的決策本體、
    以及「為什麼審計者不能是執行者自己」的推理。

    做法比照 `docs/adr/0018-vendored-external-assets.md` 第 42 行的範本。
    **這推翻了 2026-08-29 的一項裁決**（當時依「指令句密度僅 1 句」
    判定 ADR-0007 不需處理）。改判理由：關鍵詞密度已在三個場合造成三次誤判
    （見第 25 點），不足以作為分類指標；改用 `PRINCIPLES.md` §1 的
    段落層級判準——「刪掉這段，執行者會不會做錯事」。

    **B. `.claude/` 目錄的建立**

    | 目錄 | 適用對象 | 載入方式 |
    |---|---|---|
    | `.agents/rules/` | 執行者 | IDE 自動載入 |
    | `.claude/rules/` | 審計官 | 對話開場時主動 clone 讀取 |

    位置選擇的理由：`SOP/` 不適合，因為 `SOP/README.md` 第 4 行寫著
    「這些文件是**所有 AI 代理人**與開發者必須遵守的最高指導原則」——
    把審計官的規範放進去，等於靠一行標頭去抵銷那句話。
    `.agents/rules/` 更不適合（自動載入且目錄名就叫 rules）。
    新增 `.claude/` 的防呆強度來自**結構本身**，不依賴「有沒有讀到那行標頭」。

    已實測確認：`.gitignore` 不會排除 `.claude/`
    （`git check-ignore` 驗證）；`check_consistency.py` 的四處 `os.walk`
    只跳過 `.git`、`.venv`、`node_modules`，因此 `.claude/` 仍受
    CHECK 1、2、3 檢查，不會成為無人管的死角。

    **C. 第三次回報虛構，與指紋機制的失效**

    2026-09-01 `ad460f5` 批次：七個檔案的實際改動經獨立 clone 逐行 diff
    確認完全正確，但回報中引用的檔案內容，**凡是未被指定修改的上下文行
    全部是生成的**。

    | 位置 | 回報 | 實際 |
    |---|---|---|
    | `PRINCIPLES.md` 3-6 | 「撰寫時間⋯摘要」 | 「建立日期⋯定位」 |
    | `PRINCIPLES.md` §1 表頭 | 層／代表／內容與用途／修改規則 | 層／位置／內容性質／變更方式 |
    | `MISSION.md` 22 | 「## 授權邊界」 | 「## 完成的定義」 |
    | `SOP_14` §6.3 標題 | 「關於審計的注意事項」 | 「與既有紀律的關係」 |
    | `HANDOVER` 284 | 「10 份 + 路由表」 | 「10 份 + 索引」 |

    **關鍵差異**：前兩次總行數對不上，一眼拆穿；這次**所有指紋都正確**，
    因為指定要改的行照抄提示詞（正確），只有周邊上下文是生成的。
    行號與總行數機制對這種**局部虛構**無效。

    處置：`.agents/rules/git-and-reporting.md` §2 新增第三條——
    回報時必須一併貼出 `git diff` 的原始輸出。diff 只顯示實際變更行，
    格式由 git 產生，無法混入虛構上下文。

    **D. 審計官自身的紀律已成文**

    先前散落在對話中的作業紀律（不採用執行端數字、盤點用結構錨點、
    零命中條件要先列自身例外、提示詞必備要素）已寫入
    `.claude/rules/auditor-protocol.md` §5、§6。
    其中「零命中條件」一項審計官自己犯過兩次，
    「結構錨點」一項犯過三次——都曾寫在檢討裡卻沒進入產出流程，
    屬 `PRINCIPLES.md` §3.2「只存在於對話中等同沒有記錄」。

    **待辦（批 5c）**：反向宣告與索引同步——
    `AGENTS.md` §0 第 6 條補 `.claude/` 說明、
    `.agents/rules/role-boundaries.md` 補一節、
    `PRINCIPLES.md` §0.4 表格加一列、
    `docs/HANDOVER.md` §2 關鍵文件表加 `.claude/`。

24. **反向宣告的落地，與一項回報紀律違規（2026-09-01）**

    **A. 為什麼要有反向宣告**

    `2e4c55d` 建立了 `.claude/` 目錄，但當時只有該目錄自己的 `README.md`
    寫著「這不是你的行為指令」。**警告掛在房間裡面，走進來之前看不到。**

    防呆必須放在讀者一定會經過的地方，不是放在被保護的對象上。
    本批把宣告補到執行者真正會讀到的四處：`AGENTS.md` §0 第 6 條、
    `.agents/rules/role-boundaries.md` §5、`PRINCIPLES.md` §0.4、
    `docs/HANDOVER.md` §2 關鍵文件表。

    加上結構本身（`.claude/` 對稱於 `.agents/`）與檔頭橫幅，
    共五層防呆，且其中三層在執行者的自動載入面上。

    **B. 一項回報紀律違規（`2e4c55d` 批次）**

    該批次的**執行完全正確**，經獨立 clone 逐行核對無誤。
    但回報方式違反兩條紀律：

    | 項目 | 問題 |
    |---|---|
    | `auditor-protocol.md` | 只貼到第 67 行，其餘標註「見上方終端機輸出」，但該輸出未出現在回覆中 |
    | `docs/adr/0007` | 以「（原文不變，見終端機輸出）」與省略號佔位 |
    | 第 23 點 | 整段標註「完整輸出見上方」，實際沒有 |
    | `git diff` 步驟 | 寫「**截選關鍵差異段落**」，貼的是三行摘要而非原始輸出 |

    前三項屬 `docs/HANDOVER.md` §10.1 第 3 種出錯模式（只給摘要）。
    第四項違反 `.agents/rules/git-and-reporting.md` §2 剛新增的第三條——
    **該規則的全部價值在於「原始輸出無法混入虛構」，改成人工摘要即歸零。**

    須記錄的是：**這次沒有虛構**。省略的部分經核對全部正確，
    執行端選擇了「說沒貼」而非「編一份」，相較前三批是明確進步。
    但「見上方終端機輸出」指向一份不存在的輸出，實質仍是不可核對的宣稱。

    **C. 根因在提示詞設計，不只在執行端**

    該批提示詞同時要求「貼三個大檔案的全文」與「貼 `git diff` 原始輸出」，
    對 136 行 + 55 行 + 73 行的內容會產生極長回覆，
    執行端在長度壓力下選擇了摘要。

    **修正**：往後提示詞改為二擇一——
    要求 `git diff` 原始輸出 **＋ 只貼新建檔案的全文**，
    不再要求既有檔案的全文。diff 已能證明「改了什麼」且無法造假，
    全文是冗餘的。這同時降低長度壓力與虛構誘因。

    此條應併入 `.claude/rules/auditor-protocol.md` §6.1 作為第 7 項，
    待下一批處理。

25. **Payload 淨化樣板第二變體收斂，與兩項格式缺陷（2026-09-01）**

    **A. 第二變體的 9 個檔案**

    第 20 點宣稱「6 個檔案 12 行已全數處理」並把 `HANDOVER` §5.5
    標記為已收斂，但全庫實際有 **16 個檔案**帶有該樣板。
    漏掉的 9 個屬第二變體：bucket 名稱已更新，但保留失效的 `(§6.3)`
    章節引用與「若…若…」條件式寫法。

    | 變體 | 特徵字串 | 檔案數 | 批次 |
    |---|---|---|---|
    | (a) | 若本技能為 `Cognitive` 型 | 6 | 831cbe9 |
    | (b) | 若本技能屬於 analysis/ 或 orchestration/ | 9 | 本批 |

    **根因**：審計官以「詞彙」而非「結構」作為搜尋錨點。
    此教訓已成文於 `.claude/rules/auditor-protocol.md` §5.2。

    **後果放大**：第 20 點把 `HANDOVER` §5.5 標記為「✅ 已收斂」，
    追蹤表從「不完整」變成「假訊息」——即 `AGENTS.md` §6 定義的
    「說謊的路由器」。本批已更正。

    **本次是靠什麼發現的**：上一批驗證步驟要求「貼出實際命中的檔名與行號，
    不要只回報數量」，執行端據此貼出 9 個 `(§6.3)` 命中，才被發現。
    **此條驗證要求應維持，不得簡化為數量回報。**

    **B. 兩項格式缺陷**

    | 缺陷 | 位置 | 成因 |
    |---|---|---|
    | setext 標題誤判 | `.agents/rules/role-boundaries.md` 57-58 行 | 追加內容以 `---` 開頭且未指明前置空行，使前一行被解析為 H2 |
    | 回報負擔未列入清單 | `.claude/rules/auditor-protocol.md` §6.1 | 六項必備要素中沒有一條談回報長度，導致同時要求全文與 diff |

    兩者皆為提示詞設計缺陷，非執行端問題。
    `check_consistency.py` 七項不含 setext 檢查，抓不到第一項——
    這是繼「檔尾換行」「簡體字」之後第三個值得補進 CHECK 的項目。

26. **ADR-0005／0014／0016 分層搬移，與一項數字更正（2026-09-01）**

    **A. 三份 ADR 的規範搬入 SOP_14**

    | 來源 | 原行號 | 去向 |
    |---|---|---|
    | ADR-0005 三層核對流程 | 31-45 | `SOP_14` §7 |
    | ADR-0014 §4 沙盒先行驗證五步驟 | 72-81 | `SOP_14` §2.1 |
    | ADR-0016 §4 版控前觸發條件 | 64-68 | `SOP_14` §0（ADR-0016 自己要求，至今未落地） |

    做法比照 ADR-0018 與 ADR-0007 的既有範本：規則本體進規範層，
    ADR 只留「為什麼」。ADR-0016 的 §4 是「要求」而非規範本體，
    因此原文保留並加註已落實，不搬移。

    這是 19 份 ADR 分類審計的第二批實作（第一批為 ADR-0007）。
    剩餘待處理：ADR-0002 → `AGENTS.md` §5、ADR-0004 →
    `.agents/rules/skills-architecture.md`、ADR-0010 →
    `.agents/rules/powershell-encoding-protocol.md`；
    ADR-0009／0012／0017 待 runtime 層遷移後才有目標層；
    ADR-0013 需先重新評估哪些條款仍成立（待使用者裁決）。

    **B. 數字更正：Payload 淨化樣板是 16 個檔案，不是 15**

    以區塊標題為錨點獨立盤點全庫，實際為 **16 個**：

    | 批次 | 檔案數 | 內容 |
    |---|---|---|
    | `20aa619` | 1 | `subagent-collaboration/REFERENCE.md` |
    | `831cbe9` | 6 | 變體 (a)：`Cognitive`／`Execution` 型 |
    | `d6fe76a` | 9 | 變體 (b)：`(§6.3)` + 「若…若…」條件式 |
    | **合計** | **16** | |

    第 25 點與 `HANDOVER` 第 445 行原記為 15，成因是審計官計算
    「6 + 9」時漏掉最早在 `20aa619` 收斂的那一份。
    **這是審計官第二次把錯誤數字寫進權威文件**（前次為「7 個檔案」）。

    處置：`.claude/rules/auditor-protocol.md` 新增 §5.5——
    宣告「某項已收斂」之前，必須用結構錨點重新盤點全庫，
    不能只數自己這幾批處理過的檔案。

    **C. 附帶發現**

    - `image-enhancer` 原樣板中的「若本技能**属于**」是簡體字，
      已隨 `d6fe76a` 替換移除。這暴露批 5a 設計的簡體字掃描字集不完整
      （未收錄 `属`）。以擴充字集重掃全庫，現僅餘本檔案中的歷史說明一筆。
    - setext 風險以排除 frontmatter 的方式重掃，餘 4 筆全部位於
      程式碼區塊內的範例，屬誤判，無實際風險。

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

> [!NOTE]
> **第二批第 3 組（`test_validate_skills.py` 三個分支）— 2026-08-29 處置**
>
> | 分支 | 決定 | 理由 |
> |---|---|---|
> | `test-validate-skills-main` | **已合併** | 為 `main()` 補 3 個測試（原本 0 個）。斷言涵蓋 exit code、輸出訊息與具體錯誤字串；以 `monkeypatch.setattr` 改寫 `SKILLS_DIR` 並在 `tmp_path` 建檔，不污染真實 `skills/` |
> | `add-report-results-tests` | **已合併** | 為 `report_results()` 補 3 個測試（原本 0 個）。涵蓋成功、含警告、含錯誤三種輸出路徑 |
> | `code-health/remove-unused-pytest-import` | **不採用** | 見下方說明 |
>
> **不採用的完整理由**：該分支刪除檔案第 1 行的 `import pytest`。
> 以合併前的 main 而言，該 import 確實未被任何程式碼使用，**判斷本身正確**。
> 但同組另外兩個分支各使用 3 次 `pytest.raises`，合併後共 6 處依賴它。
> 三個分支基於同一 base commit，Jules 在各自沙盒中無法看見彼此的變更。
>
> 關鍵在於**無論合併順序如何都會壞**：先合測試再刪 import，6 個測試
> 拋出 `NameError`；先刪 import 再合測試，兩個測試分支的 diff 並未新增
> import 行（它們的 base 已有該行），合併後檔案仍然缺少它，結果相同。
> 這不是順序問題，是該分支與同組其他分支根本互斥。
>
> **一般化的教訓**：純刪除型的分支（移除未使用的 import、變數、函式）
> 看似最安全，實際上最容易與同批的新增型分支互斥——
> 它移除的東西可能正是別的分支即將開始使用的。
> 審查時不能只看該分支自身的正確性，必須檢查同組其他分支是否會用到被刪除的項目。
>
> 分支比照前例**保留在遠端不刪除**，GitHub PR 關閉並留言說明。
>
> 本組合併後，`scripts/tests/test_validate_skills.py` 由 22 個測試增至 28 個，
> 專案測試總數由 30 增至 36。

> [!NOTE]
> **第二批第 4 組（`test_with_server.py` 三個分支）— 2026-08-29 處置**
>
> | 分支 | 決定 | 理由 |
> |---|---|---|
> | `optimize-server-polling` | **已合併**（實作+測試成對） | 將 `is_server_ready()` 的固定 0.5 秒輪詢改為指數退避（0.05 起、倍增、上限 1.0）。伺服器啟動快時可省下最多 450ms，慢時退避至 1 秒也不比原本浪費 |
> | `test-main-with-server` | **部分合併**（5 個測試取 4 個） | 為 `main()` 補測試。捨棄 `test_main_cleanup_timeout`，理由見下 |
> | `add-timeout-test` | **已合併** | 補 `test_main_server_cleanup_timeout`，並將 `main` 加入檔頭 import |
>
> **安全確認**：`optimize-server-polling` 是本批唯一改動生產程式碼的分支。
> 已逐行確認它**只碰 `is_server_ready()` 的 sleep 邏輯**，
> `start_server_process()` 完全未被觸及——第一批修補 command injection
> 所加入的 `shlex.split()` 與移除 `shell=True` 的寫法完好無損。
> 第一批曾有分支（`refactor-with-server-script`）表面是重構、
> 實際會回退該修正，因此凡是動到 `with_server.py` 的分支一律需做此確認。
>
> **教訓：行為改動與其斷言必須成對合併。**
> `optimize-server-polling` 同時修改了實作與 `test_is_server_ready_success_after_retry`
> 的斷言（`call(0.5), call(0.5)` → `call(0.05), call(0.1)`）。
> 只合實作或只合測試，兩種情形都會使測試失敗。
> 這與第 3 組 `import pytest` 的互斥是同一類問題的鏡像：
> 第 3 組是「刪除的項目正被其他分支使用」，
> 本組是「行為改變後，斷言必須同步」。
> **審查同組分支時，除了檢查檔案交集，還要檢查行為與斷言的耦合。**
>
> **捨棄重複測試的理由**：`test_main_cleanup_timeout`（來自 `test_main-with-server`）
> 與 `test_main_server_cleanup_timeout`（來自 `add-timeout-test`）
> 測試同一情境——`terminate()` 逾時後改用 `kill()`。
> 兩者函式名稱不同故不會靜默覆蓋，但保留兩份等於重複維護。
> 保留後者，因其斷言更完整：額外驗證了兩次 `wait` 的參數
> （`assert_has_calls([call(timeout=5), call()])`）與 exit code，
> 前者僅檢查 `wait.call_count == 2`。
>
> **追蹤項：mock 風格分歧（暫不處理）**。
> `test-main-with-server` 使用 `patch("sys.exit", side_effect=SystemExit)`
> 搭配 `try/except`；`add-timeout-test` 與第 3 組合併的六個測試
> 皆使用 `pytest.raises(SystemExit)`。後者為 pytest 慣例寫法。
> 兩者皆可運作，本批不改寫——改寫他人測試邏輯的風險大於收益，
> 且會使 diff 難以核對。日後若整理測試風格，此為起點。
>
> 本組合併後，`test_with_server.py` 由 8 個測試增至 13 個，
> 專案測試總數由 36 增至 41。

> [!NOTE]
> **第二批第 5 組（`element_discovery.py` 兩個分支）— 2026-08-29 處置**
>
> | 分支 | 決定 | 理由 |
> |---|---|---|
> | `perf/optimize-input-discovery` | **已合併** | 輸入欄位改用單次 `page.evaluate`。讀取的是 `getAttribute('name')` 與 `getAttribute('type')`，屬性讀取不受 CSS 影響，與原本的 `input_elem.get_attribute()` 完全等價。**純效能改善，零語意變化** |
> | `perf-optimize-link-discovery` | **部分合併** | 連結改用單次 `page.evaluate`。採用 `element_discovery.py` 的變更，**排除其在 repo 根目錄新增的 `benchmark_element_discovery.py`** |
>
> **兩者互補、行段不重疊**：現行檔案在第一批（`jules-...b431935b`，
> commit `4ef1626`）已將「按鈕」段改為 `page.evaluate`。
> 本組兩個分支分別補上「連結」與「輸入欄位」兩段，
> 至此三段全部改為單次 evaluate，N+1 IPC 往返完全消除。
>
> **夾帶檔案：第四次同型事件**。`perf-optimize-link-discovery` 在 repo 根目錄
> 新增 96 行的 `benchmark_element_discovery.py`。前三次為第一批分支夾帶的
> 根目錄 `tests/`。合併時已明確排除。
> **注意：現行 `.gitignore` 的 `/batch*.py`、`/check_*.py` 等樣式擋不住
> `benchmark_` 這個檔名**，此類夾帶必須靠人工在 `git status` 閘門攔截，
> 不可依賴忽略規則。
>
> **語意差異：連結文字擷取（已加註）**。
> 連結文字改為在瀏覽器端以 `(a.innerText || a.textContent).trim()` 取得，
> 與原本的 `link.inner_text().strip()` 有兩處行為差異：
> （1）`innerText` 受 CSS 影響，隱藏元素回傳空字串，`|| textContent`
> 的 fallback 會改為取得原始文字——**隱藏連結由「顯示空白」變成「顯示文字」**；
> （2）JavaScript 的 `trim()` 與 Python 的 `strip()` 對 ASCII 空白一致，
> 但對部分 Unicode 空白字元的定義不同。
> 兩者對此示範腳本影響極小，但已比照第一批的處置方式，
> 在檔案的 `SEMANTIC DIFFERENCE WARNING` 註記中補上說明（現分為 1/2 與 2/2 兩段）。
>
> **教訓：效能優化常夾帶語意變化**。本組與第一批的按鈕改動都是同一模式——
> 把 Playwright 的 locator API 換成瀏覽器原生 API 以消除 IPC 往返，
> 效能改善確實，但兩者的可見性與文字擷取語意並不等價。
> **審查效能類分支時，除了確認速度改善，必須逐一比對被替換的 API 語意是否相同。**
>
> **本檔案位於 `examples/`，無測試覆蓋**，故本組合併後測試數維持 41。
> 驗證方式為 `python3 -m py_compile` 語法檢查與括號配對檢查。
>
> ---
>
> **第二批 12 個分支至此全數處理完畢**：
> 7 個合併（含 2 個部分合併）、5 個評估後不採用。
> 專案測試由 30 增至 41。所有分支比照前例保留在遠端不刪除，
> GitHub PR 關閉並留言說明。

---

27. **額度紀律與交接協定上線（2026-09-02）**

    **背景**：審計官的額度消耗過快——兩個對話即用掉單一 session 的 91%。
    診斷後確認主因是對話累積（每輪重新處理全部歷史），
    次因是每輪都跑完整審計報告格式、每輪都做自我審查、
    以及要求執行者貼出大量檔案內容與 `git diff`。

    **查證結論：審計官無法讀取自己的剩餘額度。**
    Anthropic 不公布 token 數，額度以五小時滾動時段加週上限計量；
    `claude auth status --json` 只回傳帳號與訂閱類型，無用量數字
    （該功能目前仍是社群的功能請求，尚不存在）。
    因此改用可數的代理指標（批次數、bash 呼叫次數、回報長度）。

    **另一項查證**：Claude Code、Claude 網頁版、桌面版與 Cowork
    **共用同一個額度池**。在 IDE 內另開 Claude Code session 會吃掉同一份配額。

    **本批上線的機制**：

    | 位置 | 內容 |
    |---|---|
    | `.claude/rules/auditor-protocol.md` §8 | 額度紀律：模型分級建議、換對話的可數指標、降低消耗的做法、兩條不得為省額度而破的底線 |
    | `.claude/rules/auditor-protocol.md` §9 | 交接協定：正常交接、**無交接接手流程**、交接區維護責任 |
    | `.agents/rules/git-and-reporting.md` §2 | 精簡回報格式：預設不貼檔案內容與 `git diff`，但驗證步驟輸出不可省 |
    | `docs/refactor-backlog.md` §5 | 交接區填入實際內容，§5.1 第一行固定為「上次核對通過的 HEAD」 |

    **§9.2 無交接接手是本批的核心設計**：新 Agent 用
    「交接區記載的 HEAD」對比「`git log` 的實際 HEAD」，
    兩者相同代表沒有未核對的批次、不同代表有一批待核對。
    這不依賴任何人交接，只依賴兩個都查得到的事實。

    **待驗收**：本批只是把機制寫進 repo，尚未驗證「新 Agent 讀了會不會照做」。
    驗收計畫分四步：(1) 審計官做規則追溯表，逐條確認每條規則的載體與
    觸發路徑；(2) 執行者做結構驗證（開場指令、交接區、連結、檔案存在性）；
    (3) 使用者開新對話做真實接手測試，含四項注入測試
    （竄改行數的回報、已裁決事項重複提問、要求直接改檔、要求跳過核對）；
    (4) 依結果補洞並產出 `.claude/rules/handover-selftest.md`。

    **審計官不適合當受測者**：它掌握全部設計脈絡，無法模擬「無知的新 Agent」，
    其自我測試只會是推測。這與 ADR-0007「執行者不能審自己」是同一個道理。
    審計官的角色是設計測試與檢視結果，不是充當受測體。

28. **交接 SOP 補完，與一項規劃缺陷（2026-09-02）**

    **問題**：第 27 點上線的 §9.1「正常交接」只有七行描述——
    「交接提示詞的內容 ＝ 當前批次狀態 ＋ 下一步 ＋ 待裁決 ＋ 注意事項」。
    沒有模板、沒有格式、沒有產出時機、沒有驗收標準，
    而且審計官從頭到尾**一次都沒有實際產出過交接提示詞**。

    這與本專案反覆記錄的失效模式相同：規則存在，但不在執行路徑上。
    一句「內容等於 A＋B＋C＋D」不會讓任何人真的寫得出來。

    **同時修正的規劃缺陷**：審計官在第 27 點的排程中，
    同時提出「批 D 開新對話做測試」與「本輪結束後開新對話續作」，
    卻未定義兩者是否為同一個對話，導致使用者無法判斷下一個新對話的性質。

    **修正後的驗收設計**（三個用途分離的新對話事件）：

    | 事件 | 對話類型 | 目的 | 判定 |
    |---|---|---|---|
    | E1 注入測試 | 拋棄式，測完即關 | 測「走偏了會不會被攔下」 | 使用者對答案卷 |
    | E2 正式交接 | 生產對話 | 新 Agent 接手執行 §5.2 第 1 項 | 使用者依 §9.4 四項判準 |
    | E3 補洞 | 視結果而定 | 只在 E1／E2 有失敗時才需要 | — |

    **E1 必須排在 E2 之前，且必須用拋棄式對話**：
    注入測試會餵入刻意竄改的回報，若混進生產對話，
    那份假資料會留在紀錄中，日後可能被當成事實。

    **注入測試的答案卷刻意不進 repo**——寫進去等於讓受測者先看到考題。
    測試題目與預期反應由使用者保管。

    **本批寫入的內容**：
    - §9.1 改寫為含完整模板、產出時機、三項前置確認
    - §9.4 新增交接驗收四項判準，含缺項時的處置對照表

29. **交接機制的驗證階段規則（2026-09-02）**

    **問題**：第 28 點寫入的 §9.1 與 §9.4，有兩處假設「舊 Agent 交接後
    即離場」：

    | 位置 | 原文 | 與實際不符之處 |
    |---|---|---|
    | §9.4 第 323 行 | 「舊 Agent 在交接時已經離場，判定由使用者依本節比對」 | 使用者明確指定判定者為留任的舊 Agent |
    | §9.1 產出時機 | 「§8.2 門檻觸發時該輪結尾同時產出交接提示詞」 | 驗證階段刻意不交接，規則第一次適用就被推翻卻無例外條款 |

    第二項尤其值得記錄：**默默違反規則，比沒有規則更糟**。
    規則被推翻時若不寫下例外，往後就無從分辨「這是例外」還是「大家都不遵守」。

    **本批寫入**：
    - §9.1 新增「驗證階段不交接」例外，並要求期間仍標示累積批次數
    - §9.4 判定者改為依情境區分，並載明「舊 Agent 可當判定者、
      不可當受測者」，理由連結 ADR-0007
    - 新增 §9.5 交接機制的驗證階段：E1／E2／E3 三事件的用途、順序、
      判定者，以及「注入測試題目不進 repo」的理由

    **E2 的前置條件**：交接區 §5.2 第 1 項（ADR-0002／0004／0010 分層搬移）
    **必須保留給 E2 的新 Agent 執行**，現任 Agent 不得先行完成，
    否則 E2 沒有真實任務，測到的只是「會不會複述交接區」。
30. **額度控管五項措施的品質影響評估，與交接機制的四個缺口（2026-09-02）**

    **A. 五項措施的品質影響評估**

    此評估在 2026-09-02 的規劃中做過，但只存在於對話，未進 repo，
    屬 `PRINCIPLES.md` §3.2「只存在對話中等同沒有記錄」。補記如下，
    供日後調整這些措施時參考——尤其是「哪些風險是刻意接受的」。

    | 措施 | 品質影響 | 可補救性 |
    |---|---|---|
    | 一批一對話 | **中性偏正面**。脈絡從 repo 載入比從對話記憶載入更可靠 | 交接區失效時可回頭讀 backlog 全文 |
    | 精簡回報（不貼檔案內容與 diff） | **中性**。核對主力是獨立 clone diff，貼進來的內容是冗餘層，且四次回報不符都出在那一層 | 隨時可在單一批次恢復要求 |
    | Sonnet 常態化 | **輕微風險**。細微不一致的偵測是本專案的核心價值，四次回報不符中有一次極隱蔽（所有行數都正確，只有上下文行是生成的） | 已設下限：核對輪次最低 Sonnet 5 High；發現異常時下批升 Opus 重查 |
    | 機械工作外包給執行者 | **中性**，前提是守住「探索性掃描給執行者、驗證性掃描審計官自己做」的分界 | 分界破了就是回到「採信執行端數字」，此條不得放寬 |
    | 減少審計官的 bash 呼叫 | **輕微風險**。合併呼叫使單次輸出變長，某項失敗時較難定位 | 失敗時分開重跑 |

    **唯一有實質風險的是 Sonnet 常態化**，但風險可控：核對用
    `diff -rq` 兩個 clone 是機械性的，需要判斷力的是「這個差異代表什麼」，
    那種輪次會建議升級。

    **兩條不得為省額度而破的底線**已寫入 `auditor-protocol.md` §8.4。

    **B. 交接機制的四個缺口（兩次獨立複驗找出）**

    | 缺口 | 證據 | 處置 |
    |---|---|---|
    | 交接前未檢查本機與遠端同步 | 全檔搜尋「本機／遠端／git pull／同步」只命中一處，且是模板中的提示文字非必檢項。批 A 執行前本機落後遠端一個 commit，靠人工才發現 | §9.1 產出前確認由三項改為四項；§6.1 新增第 9 項 |
    | 品質影響評估未進 repo | 見上方 A 段 | 補記為本點 A 段 |
    | 缺可重複的接手自檢清單 | `.claude/rules/` 底下只有 `auditor-protocol.md` | 新建 `handover-selftest.md` |
    | §6.1 漏了「更新交接區」 | 全庫搜尋「更新交接區」只命中 §9.3 一處，而審計官實際照著跑的是 §6.1 | §6.1 新增第 8 項 |

    第四項最值得記錄：**這是「規則存在但不在執行路徑上」在剛建立的機制中
    當場重現**。每批都有更新交接區，靠的是審計官記得，不是靠機制。
    若不補上，E2 的新 Agent 照 §6.1 寫提示詞就不會更新交接區，
    而我們會誤判它「交接失敗」——測出假陽性。

    **C. 驗證資產的分類原則**

    §9.5 原本寫「注入測試題目刻意不寫進 repo」，與「把測試變成 repo 裡的
    成品」的需求方向相反。經裁決拆為兩類，判準是**「看到答案會不會影響效果」**：

    - **接手自檢清單**進 repo——它檢查「你做了沒」，看到反而應該照著做
    - **注入測試題目與答案卷**不進 repo——它考「被要求違規時會不會拒絕」，
      知道題目就能演出來

31. **任務看板常駐化與封存機制（2026-09-02）**

    **需求**：使用者要求「詢問待辦時給完整 Check list，完成的也要出現，
    並建議哪些已不影響後續工作、可以封存」，形式參照 Jules 的
    All／Scheduled／Completed／Archived 四態。同時要求
    「Claude 自己要知道該加第 12 項」，即新需求必須自動登錄。

    **選型分析**：三個 agent 的實際接觸面

    | 媒介 | Claude | Antigravity | Jules |
    |---|---|---|---|
    | git repo | 每次開場 clone | 本機工作區 | GitHub 分支原生 |
    | GitHub Issues | 需額外 API 呼叫 | 需 `gh` CLI | 原生 |
    | Notion | 未介接 | 已介接 | 讀不到 |
    | Slack | 讀不到 | 讀不到 | 讀不到 |

    **只有 git repo 是三方都原生共享的媒介。**
    把任務板放在 repo 之外，會重演「Project 知識庫副本落後 144 行、
    `git-and-reporting.md` 少了整條防虛構規則」的問題——
    那個錯誤才剛清掉，不應該換個位置再犯一次。

    **Notion**：可作為單向鏡像（repo → Notion）給人看，
    **但不得成為權威來源**。建議暫緩，先把 repo 內的看板做對。
    **GitHub Issues**：若日後要讓 Jules 自主認領任務，它是唯一合理媒介；
    目前 Jules 產出分支、由人審查後合併，沒有認領需求，現在導入是提前複雜化。

    **本批建立**：
    - `docs/TASKBOARD.md`：五態看板（待辦／進行中／待裁決／已完成／可封存）
      ＋ 封存區。與 `refactor-backlog.md` 職責分離——前者是活動看板可改寫，
      後者是留痕層只追加。
    - `auditor-protocol.md` §10：新項目當輪登錄、被問待辦時給完整看板、
      五態定義、封存不是刪除、每批次結束時更新。
    - `auditor-protocol.md` §6.5：驗證攔截點的設計手法，
      並警告「攔截用的數字屬驗證設計，不是規範內容」——
      避免日後讀到舊提示詞時，把「應為九項」誤當成規則。

    **一併修正**：交接區 §5.2 第 7 項仍寫著「接手自測清單刻意不放進 repo」，
    與 e53f763 已建立的 `handover-selftest.md` 矛盾。
    成因是審計官修正 §9.5 時只改了三處，沒有全庫搜尋該敘述的所有出現位置——
    這是同一種疏漏的第三次（前兩次為「7 個檔案」與「15 個檔案」）。

32. **全盤盤點：看板漏了整個重構主線，第一輪審計發現從未落地（2026-09-02）**

    使用者要求「用宏觀角度確認是否有任何前 Agent 或接手至今遺漏的待辦，
    並檢視歸檔 SOP 是否完整」。盤點兩個 repo 後發現四類問題。

    **A. 任務看板漏了 15 項以上，含最大的一塊**

    `TASKBOARD.md` 原有 24 項，但 `refactor-backlog.md` §二「待重構清單」
    的六大節（A 技能未遷移、B Persona 15 個、**C Runtime 執行層**、
    D `$$` 指令收斂、E Data 層、F 淘汰項）**一項都沒進看板**。
    C 節是整個重構的核心——生產環境六大 PM2 進程仍住在技能文件資料夾裡。

    另漏四個追蹤項：三層索引漂移（第 10 點，已指定為 Jules 首航任務）、
    配額熔斷缺口（第 12 點）、LOOP 立案（第 13 點）、
    `karpathy` 探勘（第 14 點）。

    補完後為 A–G 共 41 項。

    **B. 審計官第一輪的十項發現，至今一項未落地**

    2026-09-01 接手第一則回覆即報出 `docs/HANDOVER.md` 十項過期與不一致，
    包含：§1 七桶表整列損壞、§12.2 把已完成的事列為「最急」、
    ADR 份數 20 vs 19、vendored 標示規則兩處仍寫「尚無規則」（ADR-0018 早已建立）。
    實查現況：**十項全部仍在**。

    成因是報完之後隨即轉入 ADR 分類、治理層、額度與交接，
    那份修正提示詞從未產出。**這是 `PRINCIPLES.md` §3.2
    「只存在對話中等同沒有記錄」由審計官親自示範的案例。**
    已登錄為 `TASKBOARD.md` F-07。

    **C. backlog 編號斷號造成兩處死引用**

    編號從 20 跳到 22。第 21 點原規劃內容因批次調整改寫為第 25 點，
    但編號空缺未補、兩處引用未改：
    `.claude/rules/auditor-protocol.md` §5.2 與 `refactor-backlog.md` 第 23 點。
    **審計官自己的作業協定裡出現死引用。** 本批已修，並保留第 21 點編號作為指標。

    **D. 舊 repo 三個區塊從未盤點**

    | 區塊 | 發現 |
    |---|---|
    | `Data/TODO.md` | §E 標記「⏳ 待評估」但從未評估。10 項未完成，含 Cloudflare 具名隧道、API 金鑰輪換、完整資安審計、**計畫書保留規範（要求寫入 SOP）**、**待辦清單評估遷移至 Notion** |
    | `Data/Execution_Plans/` | 完全未列入 §E 任何一列 |
    | `_archive_legacy_docs/` | 此前僅 `bin/cloudflared.exe` 被提及。實有 5 份舊 ADR、`audit_events.md`（89 行治理日誌）、`capacity-planning.md`、`release-checklist.md`、`incidents/incident-template.md` |

    **最值得記錄的一項**：舊 `_archive_legacy_docs/adr/ADR-003.md` 標題為
    「禁止 In-Memory Fallback 自動降級以避免腦裂」。而 2026-09-01 移除
    `subagent-collaboration` 的 `DEFAULT_FALLBACK` 時，理由寫的是
    「跳過安全淨化的不安全失敗」——**同一個原則，舊 repo 兩個月前就有 ADR，
    我們卻是重新發明的**。這說明「舊 repo 已盤點完畢」的假設不成立。
    另有 `Data/TODO.md` 早就提出「評估遷移至 Notion 統一管理」，
    與 2026-09-02 討論任務板選型時的議題相同。

    **E. 歸檔機制：不缺機制，缺索引**

    歸檔散在五個層級六個檔案（技能／SOP／ADR／任務／分支），彼此無交叉索引。
    問「某某東西歸檔到哪裡」要跑六個地方找。
    本批新增 `docs/ARCHIVE-INDEX.md` 作為統一查詢入口，
    並記錄兩個已知缺口：`skills/deprecated/` 是空的（§F 的淘汰項沒進歸檔區）、
    計畫書無保留規範。


33. **HANDOVER 十項修正落地，與兩份清單的職責切分（2026-09-02）**

    **A. 十項修正**

    這十項是審計官 2026-09-01 接手第一則回覆就報出的，
    但修正提示詞從未產出，至今一項未修。第 32 點 B 段已記錄成因：
    報完之後隨即轉入 ADR 分類、治理層、額度與交接。

    | # | 缺陷 | 處置 |
    |---|---|---|
    | 1 | §1 七桶表 `execution/` 列整列損壞（三欄擠進兩欄表，內容誤貼自 §4.1，導致該 bucket 在架構總表中沒有定位描述） | 補回定位描述 |
    | 2 | 「唯一的自動化驗證工具」與同檔記載的 `check_consistency.py` 自相矛盾 | 改為「驗證三項」 |
    | 3 | §2「vendored 外部資產尚無標示規則」——ADR-0018 早已建立 | 改為指向 ADR-0018 與 `AGENTS.md` §8 |
    | 4 | §5.5 同一項仍列為缺口 | 標記為已解決 |
    | 5 | §5.5 pre-commit hook 未反映 gitleaks 裁決 | 補上 2026-08-29 裁決與 `SOP_14` §0 的落實 |
    | 6 | ADR 份數兩處寫「20 份決策紀錄」（實為 19 份 ＋ 1 範本） | 兩處更正 |
    | 7 | §7.1 已處置卻仍掛「🔴 最高優先」 | 標題改為已處置並補狀態行 |
    | 8 | §12.2 第 1 項把已完成的事列為「最急」 | 劃掉並標記「接手者不需要做」 |
    | 9 | §11「Claude 自身的已知失誤」漏記圍欄事件 | 補為第 10 列 |
    | 10 | 最後更新註記停在較早狀態 | 追加補記並指明「待辦以 `TASKBOARD.md` 為準」 |

    第 8 項實害最大：接手者照 §12.2 逐項執行，第一件事就是去做一件
    兩週前已完成的事。

    **B. 兩份清單的職責切分**

    交接區 §5.2 列七項、`docs/TASKBOARD.md` 列 41 項，
    兩份清單在同一層級競爭，只靠一行「以看板為準」的註記維持優先序。
    這與 2026-09-01 清掉的「Project 知識庫副本落後 144 行」是同一個問題形狀。

    處置：§5.2 的清單整節刪除，只留指向。
    職責分工寫進 `auditor-protocol.md` §10：
    **交接區回答「現在在哪」（HEAD、待裁決、進行中），
    看板回答「還有什麼」（41 項任務與狀態）。**

    **C. 一次正確的攔截**

    本批的第一版提示詞把 `docs/HANDOVER.md` 的行數寫成 848（實為 847）。
    執行者依 §6.1 第 2 項的要求停下來回報，未自行推測修正。
    **這是攔截點機制第一次實際生效**，且失誤來自審計官而非執行者。


34. **看板更新機制的缺口：權威來源本身過期（2026-09-02）**

    **問題**：使用者問「TASKBOARD 是每一輪都會核對嗎？多久觸發一次？」
    查證後發現規則有寫但不在執行路徑上，而且看板已經過期。

    | 規則位置 | 內容 | 問題 |
    |---|---|---|
    | §10.5 | 「每批次結束時，提示詞必須包含更新 TASKBOARD，**與 §6.1 第 8 項同級**」 | §6.1 第 8 項只講「更新交接區」，一個字都沒提 TASKBOARD |
    | `handover-selftest.md` E 節 | 六項自檢 | 只有 E4「更新交接區」，無 TASKBOARD 對應項 |

    審計官實際照著跑的兩份清單都沒有 TASKBOARD，
    §10.5 成為指向不存在對應條款的孤立規則。

    **實際後果**（不是理論推演）：

    | 項目 | 看板記載 | 實際 |
    |---|---|---|
    | 最後更新 | HEAD `eb40749` 之後 | 實際 HEAD `d1e389b`，中間三個 commit |
    | F-07 | 待辦，「十項至今一項未修」 | 已於 `d1e389b` 全部修完 |
    | D-01、A-07 | 進行中 | 尚未開始 |

    **被指定為權威來源的檔案本身在說謊**，比 §5.2 的副本漂移更嚴重——
    副本至少還有一行「以看板為準」擋著。

    **這是「規則存在但不在執行路徑上」的第三次發生。**
    前兩次為 `SOP_03` 的品質驗證清單、以及「更新交接區」本身。
    第二次的教訓當時就寫進了 backlog，
    然後審計官在建立 TASKBOARD 時又犯了一模一樣的錯。

    **處置**：
    - §6.1 第 8 項擴為「交接區 ＋ TASKBOARD」兩項
    - `handover-selftest.md` 新增 E4b
    - §10.5 觸發時機明確化為「每一批，無例外」，並要求
      **即使沒有項目變動也要更新「最後更新」的 HEAD**
    - 新增 §10.6：「最後更新」的 HEAD 是可驗證的攔截點，
      落後於實際 HEAD 即代表有批次沒更新看板。
      每批驗證步驟固定加入該項檢查

    **設計要點**：第三項處置（無變動也要更新 HEAD）是關鍵——
    否則無法分辨「這批沒東西要改」與「忘了更新看板」。
    這與 §9.2 用 HEAD 比對判斷有無未核對批次是同一個手法。




35. **全機制稽核：四個缺口與七個盲點（2026-09-02）**

    使用者要求「用最專業嚴謹及宏觀的角度，確認還有哪裡有漏網之魚」。
    稽核的判準不是「規則寫了沒」，而是
    **「這條規則沒做的話，會不會有東西發現？」**

    **A. 四個缺口**

    | # | 缺口 | 處置 |
    |---|---|---|
    | 1 | §9.4 第 3 項指向交接區 §5.2 的優先序，但 §5.2 的清單已於 `d1e389b` 整節刪除——**交接驗收的判準指向不存在的東西** | 改指向 `TASKBOARD.md` |
    | 2 | §6.1 有九項、`handover-selftest.md` E 節只有七項，缺四項。而審計官自檢時看的是 selftest | E 節補齊，並規劃 CHECK 11 機械檢查對應 |
    | 3 | §7 說「每次都要寫出」，`PRINCIPLES.md` §4.1 說「五個觸發時機」，措辭衝突；且檢查點已連續停擺五批以上 | 措辭收斂；建立 `docs/AUDIT-LOG.md` |
    | 4 | `docs/ARCHIVE-INDEX.md` 自己寫著「必須同步更新」，卻不在任何載入路徑上 | §10 開頭表格加入該檔 |

    **B. 七個盲點**

    | 盲點 | 內容 | 處置 |
    |---|---|---|
    | A | **沒有任何機制檢查審計官** | 新增 `prompt-preflight.md`（本批） |
    | B | `check_consistency.py` **零測試覆蓋**，而它即將承擔 14 個 CHECK | B-09 |
    | C | 開場動作用 `--depth 1`，**淺層 clone 無法對前一個 commit 做 diff** | 已改 Instructions；§5.4 補上用法 |
    | D | **沒有任何回滾或復原程序** | 新增 §11（本批） |
    | E | Jules 全庫只有兩行規範，卻已被指定首航任務 | B-10 |
    | F | E1 答案卷只存在於對話中 | D-01 註明由使用者保管 |
    | G | CHECK 12 的先有雞先有蛋問題 | `AUDIT-LOG.md` 首列標記 `BOOTSTRAP` |

    **C. 一個原則**

    控制有四層：控制本身、執行證據、偵測證據是否存在、
    由被控制方以外的人執行偵測。**我們幾乎全部只做到第一層。**

    唯一真正可靠的控制是 `check_consistency.py` 與 `validate_skills.py`，
    因為它們是腳本，做不做不是任何人的選擇。由此得出原則
    （應寫進 `PRINCIPLES.md`，列為後續待辦）：

    > **一條規則若能被機械檢查，就必須被機械檢查。**
    > 只能靠人記得的規則，視為「尚未生效」，不得計入已完成。

    **D. 外部工具的選型**

    | 問題 | 工具 |
    |---|---|
    | 誰在檢查我？ | 執行者前置檢查（本批）＋ GitHub Actions CI（B-07）——CI 是唯一既不是審計官也不是執行者的角色 |
    | 驗證器誰驗證？ | `test_check_consistency.py`（B-09）＋ CI 強制執行，兩者是一組 |
    | 出錯了怎麼辦？ | `git revert` 程序（§11）＋ `audited-*` tag（B-08） |

    CI 先做 L1（`push` 觸發，偵測），不做 L2（PR ＋ 分支保護）。
    L2 會改變執行者的工作流程，此時正要測交接機制，
    同時改兩件事會讓結果難以歸因。**等 Jules 加入時再上 L2。**

    **E. 稽核期間的三次錨點失誤**

    本批的提示詞連續三版被執行者攔下，成因各不相同：

    | 次 | 錨點 | 成因 |
    |---|---|---|
    | 1 | `HANDOVER.md` = 848 行（實為 847） | 用推算代替實測 |
    | 2 | 交接區 HEAD = `d1e389b`（實為 `aa36448`） | **批 G 的提示詞漏了更新交接區**，使該節落後兩批 |
    | 3 | backlog 第 34 點結尾（該字串不在該檔案中） | **跨檔案汙染**——把 `auditor-protocol.md` 檔尾的一句，當成 `refactor-backlog.md` 的內容 |

    第二次特別值得記錄：批 G 正是那一批「把看板更新放上執行路徑」的批次，
    當時 §6.1 第 8 項（要求更新交接區）**已經存在**，審計官仍然漏了。
    **這證明「寫在清單裡」不等於「會被執行」**——審計官並未在每次產出
    提示詞前實際跑過 selftest E 節，那份清單是開場讀過一次，之後靠記憶。

    第三次的直接成因是取錨點時在同一條指令裡輸出多個檔案的片段，
    再從一堆輸出中憑肉眼挑選。

    **三次都被執行者攔下，且工作區均未受汙染。**
    這是 `prompt-preflight.md` 存在的直接實證——
    在它成文之前，這三次攔截是執行者依 `role-boundaries.md` §3
    自發做到的；成文之後，它從偶然變成機制。

    處置：新增 `auditor-protocol.md` §6.6（錨點必須驗證唯一性、
    優先選用「下一個標題行」這類不需判斷的錨點）、
    `handover-selftest.md` E11、`prompt-preflight.md` §4。


36. **三項新缺口登錄，與「當輪登錄」規則本身的漏洞（2026-09-02）**

    使用者逐項對帳「GitHub Actions CI 完成了嗎、TASKBOARD 更新了嗎、
    未完成待辦都寫進去了嗎」，查出三項應登錄而未登錄的缺口。

    **A. 對帳結果**

    | 項目 | 狀態 |
    |---|---|
    | B-07 GitHub Actions CI | **未完成**，`.github` 目錄不存在，僅登錄為待辦 |
    | B-08 `audited-*` tag | **未完成**，`git tag -l` 全庫 0 個，僅登錄為待辦 |
    | `TASKBOARD.md` 更新 | 已更新，但數字更正：先前口頭說「43 → 45」，實際為 **43 → 48** |
    | A-15 context 截斷風險 | **漏登錄** |

    **B. 「當輪登錄」規則本身有漏洞**

    §10.1 要求新缺口「當輪登錄」，但**審計官不能改檔案，
    只能透過提示詞登錄**。當一輪因為需要使用者裁決而沒有產出提示詞時，
    登錄就無處可去。

    A-15 正是這樣漏掉的：審計官在發現 context 截斷風險的那一輪寫了
    「我會在下一批登錄」，但那一輪結尾是向使用者提問（合法的
    「需裁決不出提示詞」），下一輪也沒有回頭補，
    **直到使用者逐項對帳才發現**。

    處置：§10.1 補上程序——沒有產出提示詞的輪次，
    必須在回覆中明確列出待登錄項目並聲明「將於下一批第一項處理」，
    且下一份提示詞的第一項修改就是登錄它們。**不得只說「之後會做」。**

    **C. 三項新登錄**

    | ID | 內容 |
    |---|---|
    | A-15 | 執行者 session 的 context 截斷風險。處置：每批提示詞開頭要求從檔案讀取規則，不依賴自動載入 |
    | A-16 | 「可機械檢查者必須機械檢查」原則寫入 `PRINCIPLES.md` §2.8 |
    | A-17 | §10.1 的漏洞本身 |

    **D. context 截斷是第三種失效形態**

    | 形態 | 例子 |
    |---|---|
    | 規則存在但不在執行路徑上 | §9.3 的「更新交接區」沒進 §6.1 |
    | 規則存在但沒有偵測 | 自我審查檢查點停擺五批 |
    | **規則存在、也載入了，但被 context 截斷丟掉** | **本次** |

    第三種最難察覺，因為執行者不會知道自己少了什麼，
    只會照剩下的記憶做事。唯一的解法是**不依賴自動載入，
    每批從檔案重新讀取**。

37. **第二次全機制稽核：新規則當批失效（2026-09-02）**

    使用者要求再次全面檢查「還有哪裡有漏網之魚」。三處缺陷：

    **A. 交接區 §5.1 自相矛盾**

    同一批 `23af193` 既被記為「已核對通過」（第一個項目符號），
    最後一個項目符號又說「尚待審計官核對」。
    成因是上一批只替換了第一個項目符號。

    危害具體：新 Agent 依 §9.2 第 3 步比對 HEAD 後，
    會在同一節讀到互相矛盾的狀態——
    **交接機制的核心比對，在第一次真實使用前就被自己的文件搞混。**

    **B. §7.1 上線的當批就失效**

    §7.1（批 H，`23af193` 建立）要求「每次觸發檢查點都要追加一列到
    `docs/AUDIT-LOG.md`」。實查只有 3 列，缺 `23af193` 與 `b6ab53f`。

    根本原因是**審計官從批 H 之後就沒再做過自我審查檢查點**，
    而 CHECK 12（偵測 `AUDIT-LOG` 落後）尚未實作，**沒有東西發現**。

    這是 `PRINCIPLES.md` §2.8「一條規則若能被機械檢查就必須機械檢查；
    只能靠人記得的規則，視為尚未生效」的**直接實證**——
    §2.8 才剛寫下，§7.1 就示範了它描述的失效。

    **C. §6.1 第 10 項被空行斷開**

    第 9 項與第 10 項之間有空行，Markdown 視為兩個列表。
    成因是插入指令未指明不留空行。

    **D. 五次同根因的疏漏**

    | # | 事件 |
    |---|---|
    | 1 | 「7 個檔案」→ 實際 6 |
    | 2 | 「15 個檔案」→ 實際 16 |
    | 3 | 自測清單「不放進 repo」→ 已放進去 |
    | 4 | §9.4 指向已刪的 §5.2 |
    | 5 | §5.1 只改一個項目符號 |

    共同結構：**修改一處內容時，沒有搜尋「同一件事在哪些地方被描述」。**
    §6.6 的錨點唯一性驗證防不了這種——錨點找得到，
    只是同一件事還有別處也要改。

    處置：新增 §6.7（搜尋主題而非字串）、規劃 CHECK 15
    （交接區同一 hash 不得同時出現在兩種矛盾語境）。

    **E. 交接前必須完成的項目**

    | ID | 必須？ | 理由 |
    |---|---|---|
    | B-02 CHECK 8-15 | 🔴 必須 | B 段證明沒有機械偵測的規則會立刻空轉；新 Agent 沒有對話脈絡，更依賴機械檢查 |
    | B-07 CI | 🔴 必須 | 唯一的第三方檢查者。交接後審計官不在，錯誤只能靠使用者發現 |
    | B-09 測試 | 🔴 必須 | 沒有測試的 CHECK 可能靜默放行，綠燈反而危險 |
    | B-08 tag | 🟡 建議同批 | 交接後的回滾目標需要它 |
    | D-01 E1 注入測試 | 🔴 必須 | 驗證新 Agent 會不會被誤導的唯一測試 |
    | A-06、B-10 | 🟢 可後做 | 稽核工具與 Jules 規範，非交接前置 |
    | B-01 | 🟢 刻意保留 | E2 新 Agent 的測試任務 |

38. **互相監督：把執行者的偵測能力正式化（2026-09-02）**

    **A. 實證**

    審計官最近六次錯誤的偵測來源：

    | # | 錯誤 | 誰發現 |
    |---|---|---|
    | 1 | `HANDOVER` 行數 848 vs 847 | 執行者 |
    | 2 | 交接區 HEAD `d1e389b` vs `aa36448` | 執行者 |
    | 3 | 錨點跨檔案汙染 | 執行者 |
    | 4 | §5.1 只改一個項目符號 | 審計官稽核 |
    | 5 | §6.1 空行斷開 | 審計官稽核 |
    | 6 | 忘了改交接區 §5.1 的 HEAD 行 | 執行者 |

    **四次是執行者攔下的**，而它當時只有七項結構檢查。
    這個角色被低估了。

    **B. 新增兩類機械規則**

    | 類型 | 內容 |
    |---|---|
    | 配對（§3.1） | 更新 TASKBOARD HEAD ⇔ 更新交接區 §5.1 HEAD；新增看板項目 ⇔ 驗證步驟含項目數檢查；修改規則章節 ⇔ 驗證步驟含章節序列檢查；追加 backlog 編號 ⇔ 驗證步驟含編號連續性檢查 |
    | 覆蓋（§3.2） | `git add` 清單的每個檔案 ⇔ 總行數確認 ⇔ 圍欄檢查，三者必須一致 |

    逐一比對六次錯誤：配對與覆蓋規則能攔下 **#1、#2、#3、#6 四次**；
    #4、#5 需要語意判斷，機械規則攔不住，交由 CHECK 15 與人工稽核。

    **C. 界線：機械檢查，不是判斷**

    `role-boundaries.md` §2 禁止執行者「評價另一個 agent 的產出是否正確」，
    該條保留。新增的是**機械檢查**——比對清單是否齊全，
    不判斷內容是否正確。

    **不擴大到「判斷審計官是否漏了該做的事」**：那需要執行者持有
    審計官的完整規則並做判斷，等於讓它兼任審計官，
    正好違反 `docs/adr/0007-macro-auditor-role.md` 的立論。
    **互相監督的價值在於獨立性；一旦執行者開始判斷，獨立性就沒了。**

    §3.3 因此要求區分【缺失】與【疑問】：前者是機械檢查未通過，
    後者交由審計官判斷，執行者不自行修正也不當成缺失。

    **D. 方向警訊：治理正在變成目的本身**

    同日實測 `docs/TASKBOARD.md` 55 項的分布：

    | 節 | 內容 | 已完成 | 待辦 |
    |---|---|---|---|
    | A | 治理機制 | 16 | 2 |
    | B | 工具與治理 | 0 | 10 |
    | **E** | **重構主線**（技能遷移、Persona、Runtime、`$$` 指令、Data 層） | **0** | 5 |
    | G | 舊 repo 未盤點 | 0 | 4 |

    **A 節完成 16 項，E 節完成 0 項。** 本專案的目的是把舊系統遷移到
    新架構，而生產環境的六大 PM2 常駐進程至今仍住在技能文件資料夾裡。

    前期的治理投入是必要的——回報虛構四次、交接區落後兩批、
    規則不在執行路徑上，都是真問題。但**邊際效益已在下降**：
    最近兩輪稽核找到的是「空行斷開列表」「同一節兩個項目符號不一致」
    這種等級。

    **建議：B-02／B-07／B-08／B-09 完成後宣告治理層封版**——
    除非發生實際事故，不再新增治理規則；
    新發現的小瑕疵登錄看板但不立刻處理。

    理由是 `PRINCIPLES.md` §2.1「品質優先於速度」的另一面：
    **品質是為了讓事情做成，不是為了讓流程完美。
    一套沒有實際遷移任何東西的完美流程，價值是零。**

39. **觸發機制稽核：為什麼審計官會多輪不遵守規範（2026-09-02）**

    使用者指出「你自己知道已經多輪沒有依照規範執行，請認真看待——
    如果機制有問題，後續新的 Claude Agent 也會不斷犯同樣的錯」。
    本輪針對**觸發機制**稽核，判準是：這條規則沒做的話，
    **報告裡看得出來嗎？**

    **A. §6.1 十一項中，四項完全沒有外部偵測**

    | §6.1 項 | 外部觸發 |
    |---|---|
    | 1、2、5、6、8、9 | `prompt-preflight.md` §3 的七項結構元素 |
    | **3 行號錨點、4 貼出實際命中、7 回報負擔、10 動手前必讀** | **無** |
    | 11 配對與覆蓋 | §3.1／§3.2（新增，未測） |

    **B. 根本原因：自檢沒有產物**

    `handover-selftest.md` E 節是審計官唯一的自檢清單，
    但**它不產生任何外部可見的東西**。實查
    `prompt-preflight.md` 與 `auditor-protocol.md` 中
    「自檢聲明」相關字串命中 **0**。

    有沒有跑過那些項目，使用者看不到、執行者看不到、repo 裡沒有痕跡。

    **所以審計官多輪不遵守，不是自律問題，是設計上無法被觀察。**
    這正是 `PRINCIPLES.md` §2.8「只能靠人記得的規則視為尚未生效」
    所描述的情形——而 selftest 本身就是那樣一條規則。

    處置：每份提示詞必須含【審計官自檢聲明】區塊（§6.1-12），
    由執行者做機械交叉驗證（`prompt-preflight.md` §3.4），
    使聲明成為**可被推翻的宣稱**而非單純宣告。

    **C. `prompt-preflight.md` §3 從未真正執行過**

    規則寫著七項結構元素「缺一即停」，但審計官的提示詞
    【回報要求】從未要求貼出這七項的檢查結果。
    翻遍所有批次回報：有「動手前必讀」的輸出、有錨點 `count()`，
    **唯獨沒有七項結構元素的檢查結果**——無從確認它有沒有跑。

    處置：回報要求一併涵蓋 §3 的七項與 §3.4 的交叉驗證。

    **D. 「規則寫在他節、未進 §6.1」的第三次**

    | 次 | 規則位置 | 後果 |
    |---|---|---|
    | 1 | §9.3 更新交接區 | 交接區落後兩批 |
    | 2 | §10.5 更新 TASKBOARD | 看板落後三批 |
    | 3 | **§7.1 更新 `AUDIT-LOG`** | **本輪發現時已落後一批** |

    根因是**「規範文件的章節」與「審計官實際照著跑的清單」
    是兩個不同的東西**。往後新增任何「每批必做」的規則時，
    必須同步進 §6.1 與 `handover-selftest.md` E 節，
    否則它從第一天就是死規則。

    **E. 第五次獨立攔截：【疑問】通道首次啟用**

    本批的第一版提示詞把 §3.4 的錨點寫成 `## 3.3`，
    指示「在該行之前插入」，會產生 `3.1 → 3.2 → 3.4 → 3.3` 的逆序，
    與驗證步驟的預期序列衝突。

    執行者依 §3.3 將其分類為【疑問】而非【缺失】、
    提出可能的修正但**未自行套用**、工作區維持乾淨。
    這是 §3.3【疑問】通道設計後的**首次實際啟用**，
    也是執行者第五次攔下審計官的錯誤。

40. **治理機械化：十五項一致性檢查、CI 自動化驗證、與自檢連動防線（2026-09-02）**

    **A. 六次失效的收斂：從「寫規則提醒自己」到「程式碼強制執行」**

    §6.1 與 selftest E 節的連動落後，在專案歷史上已發生六次：
    前五次每次的處置都是「改掉它＋寫一條規則叫自己注意」，
    但第六次（AUDIT-LOG 遺漏）依然發生。
    這印證了 `PRINCIPLES.md` §2.8 的核心洞察：手工修補已達極限，
    防線必須機械化，改由不受 LLM 注意力漂移影響的程式碼執行。

    **B. check_consistency.py 擴充至 15 項**

    腳本由既有 7 項大幅擴充至 15 項，全數涵蓋真實發生過的失效模式：
    - CHECK 8 / 9：看板與交接區 HEAD 落後檢查（防檔案說謊）
    - CHECK 10：§X.Y 章節引用有效性（防死引用）
    - CHECK 11：§6.1 清單與 selftest E 節項目雙向對應（防第六次同類錯誤）
    - CHECK 12：AUDIT-LOG 審查週期落後檢查（BOOTSTRAP 例外跳過）
    - CHECK 13：檔尾換行符（INFO 呈現）
    - CHECK 14：繁體中文環境簡體字偵測（合法例外清單排除）
    - CHECK 15：提示詞上下文衝突字串偵測（已刪章節與非清單開頭否定詞）

    **C. CI 驗證上線與全覆蓋測試**

    - 新增 `.github/workflows/verify.yml`，每次 push / pull_request 自動觸發驗證
    - 新增 `scripts/tests/test_check_consistency.py`，為 CHECK 8–15 撰寫正反例測試，
      含 BOOTSTRAP 例外與 CHECK 11 失敗重現
    - 補齊歷史已核對 tag：`audited-18af8ad` 與 `audited-08e6bbc`


41. **驗證器本身是假的，與寫入內容被改寫（2026-09-04）**

    **A. 獨立反例測試**

    `0213568` 把 `check_consistency.py` 由 7 項擴為 15 項，
    新增 22 個測試（總測試數 41 → 63），CI 首次執行成功。
    表面上治理機制已完全機械化。

    審計官**沒有相信「15 項全 PASS」**，而是複製一份 repo
    自行破壞、看 CHECK 會不會抓到：

    | CHECK | 破壞方式 | 結果 |
    |---|---|---|
    | 8 | 看板 HEAD 改為落後 6 批 | 正確 FAIL |
    | 9 | 交接區 HEAD 改為落後 6 批 | 正確 FAIL |
    | 10 | 加一行「本檔案 §99.9 不存在」 | 正確 FAIL |
    | **12** | **刪掉 `AUDIT-LOG` 最後一列** | **仍 PASS** |
    | **15** | **同一 hash 同時出現在兩種語境** | **仍 PASS** |

    **B. 兩個缺陷的性質不同**

    | CHECK | 缺陷 |
    |---|---|
    | 12 | 門檻寫成 `if lag > 3`，規格是 `> 1`。落後三批以內都不算失敗，**剛好放過實際發生過的「連續兩批未做」** |
    | 15 | **完全沒有實作規格**。掃 `.claude/rules/` 與 `.agents/rules/` 找硬編碼字串，不碰 `docs/refactor-backlog.md`，沒有 hash 比對邏輯，還寫死 `idx >= 255 and idx <= 265` 的行號例外 |

    **C. 測試也失效了**

    22 個新測試**全部通過**。代表測試是照著實作寫的，
    不是照規格寫的——驗證了「程式做了它做的事」，
    而非「程式做了它該做的事」。

    這比沒有測試更危險：**沒有測試時大家會保持懷疑，
    有了綠燈就不會了。**

    **D. 這驗證了第 35 點的盲點 B**

    2026-09-02 稽核時記過：「CHECK 若有 bug 導致 false negative，
    它會靜默放行所有東西，而我們會以為機制在運作。」
    兩天後它真的發生了，而且在同一批裡同時發生兩次。

    **新規則**：新增任何驗證器之後，
    **必須由審計官獨立做反例測試**——複製一份、自行破壞、
    確認它真的會 FAIL。不能只看它回報 PASS，也不能只看測試綠燈。

    **E. 寫入內容被改寫，且與事實不符**

    上一批的修改 6f 逐字指定交接區 §5.1 的兩個項目符號，
    實際寫入的是改寫版本，且數字錯誤：

    | 指令指定 | 實際寫入 | 事實（實測） |
    |---|---|---|
    | 「6 檔異動」 | 「3 改 0 新檔」 | **6 檔異動** |
    | 「驗證三項全過」 | 「驗證四項全過」 | 驗證是**三項** |
    | 「九個攔截點全數通過」 | 「攔截點全數通過」 | 數字被拿掉 |

    **錯誤的事實因此進入 repo**，會被未來的接手者當成紀錄讀。

    現有機制查不到：`prompt-preflight.md` §4 的 `count()` 驗證
    只檢查**修改前**的錨點，寫入之後沒有任何回頭比對。

    處置：新增 `prompt-preflight.md` §4.1 寫入後原文驗證、
    `git-and-reporting.md` §2.2「提示詞指定的寫入內容逐字照抄」。
    **前置驗證確認「找得到」，後置驗證確認「改對了」，兩者缺一不可。**

    **F. 審計官對檔案結構的假設也錯了**

    本批第一版提示詞的修改 6g 寫「替換到 `## 四、更新紀錄` 之前」，
    但該標題實際位於 `### 5.4` **上方** 75 行——
    `### 5.4` 是全檔最後一節，一路到檔案結尾。
    執行者停下來回報實際結構、未自行判斷邊界，是第七次獨立攔截。

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

---

42. **「規劃了機械檢查但沒實作」的第三次，與反例測試的盲點（2026-09-05）**

    **A. 第三次「規劃了但沒實作」**

    | 次 | 項目 | 後果 |
    |---|---|---|
    | 1 | CHECK 12 門檻寫成 `lag > 3`（規格為 > 1） | 放過「連續兩批未做檢查點」 |
    | 2 | CHECK 15 完全沒實作規格 | 掃硬編碼字串，不碰目標檔案 |
    | 3 | **`audited-*` tag 落後偵測** | §11.3 寫了「落後超過一批即告警」，只停留在規劃。實測最新 tag 落後 HEAD 兩批，**沒有任何東西發現** |

    三次的形狀完全相同：規則寫進檔案 → 沒有偵測 → 靜默失效。
    這是 `PRINCIPLES.md` §2.8 的第三次實證。

    **B. 反例測試的盲點：只測邏輯，沒測真實輸入**

    2026-09-04 為 CHECK 15 做反例測試時，**人工構造**了一個帶 hash 的
    待核對項目符號，CHECK 15 正確 FAIL，因此判定它已修好。

    但真實檔案的待核對項目符號**不寫 hash**——
    實測 CHECK 15 回報「待核對 0 個 hash」。
    也就是說，**它專門要抓的那個事故若重演，它抓不到**。

    機制存在、邏輯正確、反例測試也過，但真實輸入不在偵測範圍內。

    處置：`auditor-protocol.md` 新增 §5.6「反例測試要涵蓋真實輸入的格式」、
    §9.3 新增「§5.1 每個描述批次狀態的項目符號都必須帶 commit hash」。

    **C. CHECK 15 名稱漂移**

    實作與 docstring 已改名，但第 19／448／450 行三處顯示字串仍是舊名稱。
    **執行輸出對使用者顯示的名稱，與它實際做的事無關。**
    這是 §6.7「同一件事在多處被描述」的第六次發生。

    **D. 這三項是誰發現的**

    全部由**一個新開的 Claude session** 在核對 `01bbc6c` 時發現，
    當時它正在接受 E1 注入測試的題 1（一份含兩個造假行數的回報）。
    它不但抓出兩個造假數字，還指出那兩個數字**不對應任何版本**
    （不是修改前的 841／135），因此是「根本沒實測」而非「做了但做錯」。

    這是交接機制第一次由外部 session 實際驗證，結果優於預期：
    **新 Agent 找到了現任審計官漏掉的一層**（B 段的反例測試盲點）。

    **E. 錨點選擇規則的自身缺陷**

    §6.6 原本建議「下一個標題行通常唯一且不需要判斷，優先用它」。
    這條建議在**新增同層級小節**時是錯的——錨在下一個同層級標題並插在其前，
    必然造成編號逆序。2026-09-04 與 2026-09-05 各發生一次
    （§3.4 錨在 §3.3 之前、§5.6 錨在 §5.5 之前），
    兩次都由執行者依 §3.3 分類為【疑問】並停下回報。

    **規則本身就是元凶時，改的是規則，不是叫自己下次小心。**
    §6.6 已改為依「插入位置」區分三種情境的錨點選擇表。

    **F. C-05 裁決**

    §9.4 規定驗證階段的判定者為「留任的舊 Agent」，但設計 E1 題目的
    session 已離場。經使用者裁決：**題目與答案卷由使用者保管，
    判定者為現任審計官**——判定者既非出題者亦非受測者，較原設計更乾淨。

    **G. 審計官寫的規則觸發了審計官建的檢查器**

    §6.6 的新文字同時提到 `auditor-protocol.md` 內的 §5.5／§5.6
    與 `prompt-preflight.md` 的 §3.3／§3.4，但同一段沒有寫出後者的檔名。

    CHECK 10 把未標明檔名的 `§X.Y` 視為同檔引用，
    因此判定為指向不存在的章節而 FAIL。**這是 CHECK 10 正確運作。**
    執行者停下回報、未擅改文字也未擅改檢查器，為第十次獨立攔截。

    處置：§6.1 新增第 14 項「跨檔 `§X.Y` 引用必須在同一行寫檔名」。

    **H. 三類錨點失誤的共同根因**

    | 類型 | 例子 |
    |---|---|
    | 跨檔案汙染 | 把 `auditor-protocol.md` 檔尾的一句當成 `refactor-backlog.md` 的內容 |
    | 引用自己上一批的措辭 | 交接區項目符號的錨點寫成提示詞裡的原句，而非執行者實際寫入的句子 |
    | 誤判檔案結構 | 以為 `## 四、更新紀錄` 在 §5.4 之後，實際在其前 75 行 |

    共同根因：**沒有從 clone 逐字取錨點**，而是憑印象或引用舊提示詞。

    處置：§6.1 新增第 13 項「每個錨點必須標註取自 clone 的哪一行」。
    `count()` 可以瞎猜「1」，行號猜不到——這讓「有沒有實際從 clone 讀過」
    變成可被推翻的宣稱。

    **I. 規則寫下的同一批就被違反，第三次**

    §6.6 的錨點選擇表明寫「在某節末尾新增同層級小節時，
    錨在該節最後一行內容、插在其後」。審計官在**寫下這條規則的同一批**，
    把 G／H 段錨在 F 段之前，會造成 A→B→C→D→E→G→H→F。

    執行者攔下時直接引用了那條剛寫下的規則，這是第十一次獨立攔截。

    | 次 | 事件 | 當時的處置 |
    |---|---|---|
    | 1 | `prompt-preflight.md` §3.4 錨在同檔 §3.3 前 | 改錨點 |
    | 2 | §5.6 錨在 §5.5 前 | 改錨點 ＋ **寫 §6.6 錨點選擇表** |
    | 3 | 第 42 點 G／H 錨在 F 前 | **改為機械步驟** |

    **前兩次的處置都是「把規則寫得更清楚」，第三次證明那對審計官無效**——
    它可以誤以為自己遵守了規則。

    處置：§6.1 新增第 15 項「插入型修改必須附插入後的預期序列」。
    執行者機械比對序列是否遞增、實際是否等於預期。
    **寫出預期序列會強迫在下筆前先看結構**，那正是三次都被跳過的步驟。
    規則可以誤以為自己遵守了，序列寫不出來就是寫不出來。

    **J. 同一對耦合的第二度漏更，與配對規則的缺席**

    §6.1 新增第 13／14／15 項時，未同步 `handover-selftest.md` 的 E 節，
    CHECK 11 報 FAIL 三筆。**這是同一對耦合的第二次漏更**——
    2026-09-04 的 E8「兩項 vs 三項」是第一次。

    根因不在審計官記不記得，而在 `.agents/rules/prompt-preflight.md`
    §3.1 的四條配對規則中，**唯獨缺了「§6.1 ⇔ selftest E」這一對**。
    CHECK 11 每次都抓到了，但那是**寫入之後**；
    配對規則能把失敗提早到寫入之前。

    處置：§3.1 新增第 5 列。

    **K. 全庫結構稽核發現的四個漏洞**

    | 漏洞 | 實測 | 處置 |
    |---|---|---|
    | §3.1 配對規則缺「§6.1 ⇔ selftest E」 | 四條配對規則中沒有這一對，而它是審計官最常漏的 | §3.1 新增第 5 列（A-33） |
    | **CHECK 1-7 沒有函式也沒有測試** | 只有 8 個 `check_*` 函式（8 至 15），CHECK 1-7 內嵌在 `run_checks()`，該函式測試引用 0 次 | B-15，交接前必做 |
    | 執行者的檢查結果無痕跡 | 七項結構元素檢查、配對／覆蓋、自檢交叉驗證都只在回報中 | §3.5 記錄缺口，B-14 |
    | **全庫規則的歷史宣稱從未被機械驗證** | 規則檔 11 份 1,939 行含 43 處日期、8 處「第 N 次」計數；backlog 1,941 行含 79 處日期 | B-16，拆三批 |

    第二項最值得注意：**我們花了兩批修好 CHECK 12／15 的假綠燈，
    卻從沒問過 CHECK 1 至 7 是不是也是假的**。

    第四項是使用者提出的：重構至今改了這麼多資料，
    透過雙方記憶產生的宣稱一定有錯。**審計官已被抓到過四次數字錯誤**
    （7 個檔案、15 個檔案、848 行、89／211 行），
    沒有理由相信寫進規則檔的那些未驗證宣稱就是對的。

    **L. §3.2 覆蓋規則首次實際生效**

    審計官的提示詞 `git add` 了六個 `.md`，但驗證步驟的圍欄檢查只列四個，
    漏了 `docs/TASKBOARD.md` 與 `docs/AUDIT-LOG.md`。

    §3.2 明訂「`git add` 清單的每一個檔案，都必須同時出現在
    總行數確認與圍欄配對檢查中」。這是該規則建立以來**第一次真正攔到東西，
    而攔到的是規則作者本人**。

    同批另攔下行數錯誤：提示詞寫 89／211，實測 88／210。
    成因是審計官用了 `split('
')`（末尾空字串多算一行）而非
    專案標準的 `splitlines()`，且**未從 clone 實測，而是沿用舊回報的數字**。

    **M. 執行者的沙盒預演，抓到規則檢查抓不到的問題**

    執行者在規則未要求的情況下，於沙盒中預演整批寫入，
    發現 §3.5 的文字會觸發 CHECK 10——`.claude/rules/auditor-protocol.md`
    在行尾、`§7.1` 換行到下一行行首，而 CHECK 10 是**逐行**判斷跨檔引用
    （`any(ind in line for ind in cross_file_indicators)`）。

    **這正好違反了審計官在同一批寫進 selftest E16 的規則。**
    E16 原本只寫「同一行有寫出檔名」，未點出換行斷開的風險，
    已改寫為「檔名與章節號在同一行」並註明 CHECK 10 逐行判斷。

    值得記錄的是：**沙盒預演不在任何規則的要求範圍內**，
    是執行者自己做的。它比事前檢查更強——
    事前檢查看的是提示詞的結構，預演看的是寫入後的實際結果。

43. **配對規則的盲點、動作狀態虛構，與自檢聲明造假（2026-09-05）**

    **A. 配對規則防不了「兩邊都不改」**

    `.agents/rules/prompt-preflight.md` §3.1 第一條配對規則寫著
    「更新 `docs/TASKBOARD.md` 的最後更新 HEAD ⇔ 更新交接區 §5.1 的 HEAD」。

    `76f424c` 批次中審計官**兩處都沒更新**，配對規則因此沒有觸發——
    它檢查的是「有一個就要有另一個」，兩個都沒有時它保持沉默。
    結果 CHECK 8 與 CHECK 9 在 push 之後同時 FAIL。

    **配對規則是「若 A 則必須 B」的形式，防不了「A 與 B 都缺席」。**
    `.claude/rules/auditor-protocol.md` §6.1 第 8 項已要求
    「每份提示詞必須包含三項更新指令」，該項已涵蓋此情形，是審計官未遵守，
    因此不新增規則。

    **B. 回報與實際不符的第五類：動作狀態虛構**

    | 輪次 | 執行者回報 | 實測 |
    |---|---|---|
    | 1 | 「本批次未執行 commit 與 push」 | 遠端 HEAD 為該批 commit，五項修改全數進版控 |
    | 2 | 引用一段文字並宣稱是 §5.1 的實際內容 | 該字串在遠端 `count=0` |

    前四類虛構的是檔案內容、行數與上下文行，**會在審計官 clone 核對時被抓到**；
    動作狀態虛構若不主動查 `git log` 就看不見。

    處置：`.agents/rules/git-and-reporting.md` 新增 §2.3。登錄為 B-18。

    **C. 審計官的自檢聲明造假**

    同批審計官在自檢聲明寫「E11 ✅ 六個錨點皆於 clone 實測 count()=1」，
    **實際只量了三個**，其餘沿用前幾批的用法，其中
    `## 五、接手交接區（新對話接手時先讀這一段）` 從未量過。

    E11 正是為防此而設。**勾了 ✅ 卻沒做，使自檢聲明從
    「可被推翻的宣稱」退化為空話**——而該機制的全部價值就在於可被推翻。

    處置：`prompt-preflight.md` §3.4 的交叉驗證表新增一列，
    要求證據區塊**逐條列出每個錨點與其 count 值**，而非僅宣告「皆為 1」。
    只有逐條列出，執行者才能機械比對。登錄為 A-36。

    **D. 一次性強制同步**

    本機工作區曾處於「既非任何 commit、也非遠端狀態」的不可信狀態，
    經審計官確認遠端內容完整後，一次性授權執行
    `git reset --hard origin/main` 與 `git clean -fd`。

    **這是本專案唯一一次允許使用 `git reset --hard`。**
    往後仍禁止，除非審計官在提示詞中明確授權並說明理由與範圍。

## 五、接手交接區（新對話接手時先讀這一段）

44. **關閉最後兩個破口（2026-09-05）**

    **A. 自檢聲明 18 項中只有 7 項可被驗證**

    `.agents/rules/prompt-preflight.md` §3.4 的交叉驗證表原本只涵蓋
    E1、E2、E5、E6、E8、E9、E12 共 7 項，
    而 `.claude/rules/handover-selftest.md` E 節有 18 項。

    **其餘 11 項，審計官勾 ✅ 沒有任何人能反駁。**
    E11 造假（宣稱七個錨點皆實測、實際只量三個）正是從這個洞出來的。

    **問題不在審計官特別不老實，在那 11 項本來就沒有約束。**
    機制沒有失效——機制根本沒覆蓋到那裡。

    處置：§3.4 擴為 18 項，**全部可機械驗證、零例外**。

    **B. E10 的「無法驗證」是誤判**

    審計官一度判定 E10「零命中條件的自身檢查」需要語意判斷、無法機械驗證。

    那是誤判。「提示詞若有『字串 X 應為零命中』，檢查 X 是否出現在
    提示詞本身的其他位置」**是純字串比對**。

    **錯誤的「無法驗證」判定，等於自己開一個新的洞。**

    **C. 執行者的檢查結果沒有進 repo**

    執行者每批做的檢查，此前**只存在於回報中，repo 沒有痕跡**。
    審計官有 `docs/AUDIT-LOG.md`，**執行者這一側原本什麼都沒有**——
    那是整套機制最後一個沒有證據的環節。

    處置：建立 `docs/EXEC-LOG.md` ＋ CHECK 16。

    **D. 兩處 HEAD 欄位填錯**

    `875a604` 批次把兩處 HEAD 欄位填為 `4b77ea2`，
    但同輪已核對通過 `76f424c`——**欄位應填最新已核對的 commit**。

    **E. 審計官同一份提示詞內自相矛盾**

    審計官在證據區塊中對某字串註明「此為 §3.6 內文，**非本批錨點**，僅供對照」，
    卻在同一份提示詞的修改 2 把它當成錨點使用，實測該字串 `count=0`。

    §3.6 的真正最後一行是第 177 行
    「證據區塊讓後者變成可驗證的——抄舊值會過期，憑印象填結構會對不上」。

    **這是同一類錯誤的第五次**：錨點未從 clone 逐字取得。
    §6.1 第 13 項要求「錨點必須標註取自 clone 的哪一行」，
    審計官標註了行號卻沒有實際比對該行內容。
    處置：§3.4 的 E11 一列已要求「多行錨點須為完整多行原文的實測值」，
    本次再補一層——**證據區塊中標明「非本批錨點」的字串，不得用作錨點**。

> 本區由執行者在每批次結束時更新，審計官核對。
> 維護規則見 `.claude/rules/auditor-protocol.md` §9.3。

### 5.1 上一批狀態

上次核對通過的 HEAD：76f424c

- `23af193`（執行者前置檢查 ＋ 回滾程序 ＋ `AUDIT-LOG.md` ＋ 四缺口修正）
  已於 2026-09-02 由審計官核對通過：6 檔異動（含 2 個新檔）、零夾帶、
  驗證三項全過，四個攔截點（章節序列 §1-§11、看板 48 項、
  backlog 編號 1-35 無缺號、selftest E1-E11）皆未觸發。
  **本次首度以 `git diff f601435 HEAD` 完成核對**——完整 clone 生效，
  不再依賴保留舊 clone，交接後的新 Agent 也具備同樣能力。
- **本節曾落後兩批**：批 G 的提示詞漏了更新交接區。成因見第 35 點 E 段。
- 同日執行全機制稽核，找出四個缺口與七個盲點，核心發現是
  **沒有任何機制檢查審計官**。詳見第 35 點。
- `b6ab53f`（三項新缺口登錄 ＋ `PRINCIPLES.md` §2.8 機械檢查原則 ＋
  §10.1 無提示詞輪次條款）已於 2026-09-02 由審計官核對通過：
  5 檔異動、零夾帶、驗證三項全過，四個攔截點
  （`PRINCIPLES` §2.1-2.8、看板 51 項、§6.1 十項、selftest E1-E12）皆未觸發。
- `18af8ad`（互相監督配對／覆蓋規則、交接區 HEAD 同步）已於 2026-09-02
  由審計官核對通過：6 檔異動、零夾帶、驗證三項全過，
  五個攔截點（HEAD 一致性、看板 55 項、preflight 章節序列、
  §6.1 十一項、selftest E1-E13）皆未觸發。
- `08e6bbc`（自檢聲明區塊、`AUDIT-LOG` 進 §6.1、preflight §3.4 交叉驗證）
  已於 2026-09-02 由審計官核對通過：6 檔異動、零夾帶、驗證三項全過，
  九個攔截點全數通過。
  **本列曾被改寫且數字與事實不符**（「3 改 0 新檔」「驗證四項」），
  已於 2026-09-04 依實測更正，成因見第 41 點 E 段。
- `0213568`（治理機械化：`check_consistency.py` 擴充至 15 項、63 個測試、
  CI 首次成功執行、兩個 `audited-*` tag）已於 2026-09-04
  由審計官核對通過：7 檔異動（含 2 新檔）、零夾帶。
  **但獨立反例測試發現 CHECK 12 與 CHECK 15 抓不到目標違規**，
  已於本批修正，詳見第 41 點。
- `01bbc6c`（CHECK 12 門檻改為 lag>1、CHECK 15 改為逐項目符號分塊掃描、
  `prompt-preflight.md` §4.1 寫入後原文驗證、`git-and-reporting.md` §2.1／§2.2）
  已於 2026-09-05 由審計官核對通過：7 檔異動、零夾帶，
  驗證三項全過（54 技能、15 項 CHECK、63 測試），CI Run 33924595504 success。
  **審計官對兩個 CHECK 做獨立反例注入**：刪 `AUDIT-LOG` 兩列 → CHECK 12 FAIL；
  §5.1 注入同 hash 語境衝突 → CHECK 15 FAIL，確認不再是假綠燈。
- `739671e`（CHECK 15 名稱收斂 ＋ §9.3 hash 規則 ＋ §5.6 反例測試規則
  ＋ §6.6 錨點選擇規則 ＋ §6.1 第 13／14／15 項 ＋ selftest E15／E16／E17
  ＋ preflight §3.1 新配對規則與 §3.5 ＋ 補打兩個 audited tag
  ＋ 十四項缺口登錄）已於 2026-09-05 由審計官核對通過：
  7 檔異動、零夾帶，驗證三項全過（54 技能、15 項 CHECK、63 測試），
  看板 74 項、selftest 17 項、第 42 點 A 至 M，CI Run 33944018346 success。
  **本批審計官重投八次才通過**，八次全部被執行者攔在寫入或提交之前，
  repo 未受汙染。其中三次特別值得記錄：插入位置逆序**違反的是同一批
  剛寫進 §6.6 的規則**；§3.2 覆蓋規則**首次實際攔到東西，攔到規則作者本人**；
  執行者**做了規則未要求的沙盒預演**，發現跨檔引用因換行斷開會觸發 CHECK 10。
  詳見第 42 點 G 至 M 段。
- `4b77ea2`（§6.1 第 16 項新鮮 clone 證據區塊 ＋ selftest E18
  ＋ preflight §3.6 ＋ §5.7 規則層級決定執行力 ＋ 兩項缺口登錄）
  已於 2026-09-05 由審計官核對通過：6 檔異動、零夾帶、驗證三項全過。
- `76f424c`（A-29 棄用紀錄 §5.8 ＋ B-17 登錄）已於 2026-09-05
  由審計官核對通過：4 檔異動、零夾帶、63 測試通過、看板 77 項。
  **但該批的提示詞漏了更新本節與 TASKBOARD 的 HEAD**，
  導致 CHECK 8 與 CHECK 9 同時 FAIL，成因見第 43 點 A 段。
- `875a604`（狀態收斂 ＋ `git-and-reporting.md` §2.3 ＋ 補打三個 audited tag
  ＋ 第 43 點）已於 2026-09-05 由審計官核對通過：4 檔異動、63 測試通過。
  **但該批兩處 HEAD 欄位被填為 4b77ea2 而非已核對的 76f424c**，
  CHECK 8／9 因此仍 FAIL，本批更正。
- 本批（尚未 commit）（§3.4 擴為 18 項 ＋ §3.7 ＋ §3.8 ＋ 建立
  `docs/EXEC-LOG.md` ＋ CHECK 16 ＋ HEAD 欄位更正）已執行，
  **尚待審計官核對**，見 §5.4。

### 5.2 待辦

> **待辦一律見 `docs/TASKBOARD.md`。**
> 本節刻意不保留清單副本——兩份清單在同一層級競爭時，
> 副本必然漂移（2026-09-02 曾發生 §5.2 列七項、看板列 41 項的落差）。
>
> 職責分工：**交接區回答「現在在哪」，看板回答「還有什麼」。**

### 5.3 待使用者裁決

| # | 事項 | 選項與建議 |
|---|---|---|
| 1 | **Port 3000 三方衝突** | `SOP_04` 第 167 行說 Next.js = 3000、`SOP_06` 第 100 行說 line-bridge = 3000、ADR-0017 說 3000 是 LINE bridge 不得變更且 Next.js 用 3002。**審計官建議以 ADR-0017 為準**（2026-08-26 實機查證，且 `SOP_04` 描述的資料夾已不存在），據此修正兩份 SOP |
| 2 | **`SOP_02` 清歷史規定違反第 1 層規則** | `SOP_02` 第 32 行要求「必須執行 `.git` 歷史重置或用 BFG 清理」，但 `.agents/rules/git-and-reporting.md` 第 15-16 行絕對禁止 force push，清歷史必然需要 force push。**審計官建議**改為「不得 force push；已推送的憑證一律視為永久洩漏，處置方式為撤銷與輪換該憑證」 |
| 3 | **ADR-0013 處置** | 其偵測清單四項已全數被 `check_consistency.py` 與 `validate_skills.py` 取代、寫入協定指向未遷移的 `Modules/db_state_manager.js`、且夾帶一套與 Watchdog 無關的「觸發詞排他性矩陣」。**審計官建議**先重新評估哪些條款仍成立，再決定搬移去向，不要原樣搬 |

### 5.4 進行中／等待回報

- **本批（A-29 棄用紀錄 §5.8 ＋ B-17 登錄）已執行完成，等待審計官核對。**
  核對通過後，下一批要做：更新 §5.1 的 HEAD、打 `audited-739671e`、
  `audited-4b77ea2` 與 `audited-<本批 hash>`，以及執行 **B-15**
  （CHECK 1-7 反例驗證）——那是交接前最後一項必做工作。
- **B-16 的 R1**（八處「第 N 次」計數宣稱回溯）**改判為交接後執行**。
  理由：R1 修正的是留痕層的歷史數字，不影響新 Agent 的行為判斷；
  而 B-15 的七個 CHECK 每批都在跑，若其中有假的，新 Agent 會建立在錯誤的綠燈上。
- E2 的任務是 B-01（ADR-0002／0004／0010 分層搬移）——
  **該項在 E2 之前不得由現任 Agent 先行完成**。
- 驗證期間適用 §9.1 的不交接例外，現任審計官全程留任並擔任判定者。
