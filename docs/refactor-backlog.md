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

55. **GitHub Actions 遠端健康權威與歷史失敗歸檔**（2026-09-11）
    - 依據 `docs/adr/0020-github-actions-remote-health-authority.md`，正式確立雙層權威架構：Local correctness authority 為 `scripts/verify_all.py`，Remote project-health authority 為 GitHub Actions Verify。
    - 在 `SOP/SOP_14_Rigorous_Verification_and_Audit_Protocol.md` 建立 GitHub Actions 事故生命週期（§8），規範 remote red 時以 exact Actions log 為客觀機器事實，嚴禁無憑證文字摘要辯論。
    - 完整盤點全庫歷史上 main 分支的所有 5 個 failed runs（#5, #6, #7, #10, #11），進行機器 log 下載與深度根因分析，歸納為三大類事故（CHECK 8/9 拓撲滯後、跨平台換行符指紋不符、AUDIT-LOG 週期落後），並在 `docs/AUDIT-LOG.md` 建立 CI 歷史事故歸檔專區。
    - 在 `README.md` 首頁新增 GitHub Actions Verify status badge，使專案健康狀態一目了然。

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

45. **CHECK 8／9 的門檻設計錯誤，與 CHECK 1-7 的反例驗證（2026-09-05）**

    **A. 門檻設計錯誤**

    CHECK 8／9 檢查 `docs/TASKBOARD.md` 與交接區 §5.1 的 HEAD 欄位
    是否落後，門檻原為 `lag > 1`。

    但該欄位記錄的是「**上次核對通過**的 HEAD」，而執行者在 commit
    **之前**跑檢查時落後 1（正常），**commit 之後 HEAD 前進，
    同一個值就落後 2 而 FAIL**。

    連續發生三次（`875a604`、`8b56cbd`、`ec840fe`），
    每次都被當成「填錯值」去修，但**任何值都會在 commit 後落後**——
    除非填本批自己的 hash，而那在寫提示詞時還不存在。

    **這是門檻設計錯誤，不是誰的疏忽。**
    處置：門檻改為 `lag > 2`。落後 1＝本批已 commit、尚待核對（正常）；
    落後 2＝下一批也 commit 了卻仍未更新欄位（異常）。

    **B. CHECK 1-7 的反例驗證**

    B-15 登錄的缺口是「CHECK 1 至 7 內嵌在 `run_checks()` 中，
    無獨立函式、無測試」。

    審計官於本批做反例注入：逐一構造違規，確認七項皆能正確 FAIL。
    結果見 `docs/AUDIT-LOG.md` 對應列。

    **判定：不需重構為獨立函式。** 它們自 2026-08-29 起每批都在跑、
    多次實際命中真實缺陷，反例注入已證明其有效性；
    重構的風險（改動 800 行腳本的核心）高於收益。

    這與 §5.5「淘汰理由必須逐項驗證」是同一個精神——
    **保留的理由也必須逐項驗證，不能因為「一直都在跑」就假設它有效。**

46. **E2 正式交接、四個假綠燈、與規則來源虛構（2026-09-06）**

    **A. 交接說明與 repo 的 HEAD 矛盾**

    交接說明記載「最後一次核對通過的 HEAD：`e6f543a`」，但交接區 §5.1、
    `docs/AUDIT-LOG.md` 最新列、`docs/TASKBOARD.md` 最後更新三處皆為
    `ec840fe`，且無 `audited-e6f543a` tag。

    依 `.claude/rules/auditor-protocol.md` §9.1「交接區是權威來源」，
    新審計官判定 `e6f543a` 為未核對批次，實際執行
    `git diff ec840fe e6f543a` 完成核對，結論通過。
    **交接機制第一次在真實交接中被實測，第一次就攔到矛盾。**

    **B. 四個假綠燈**

    | # | 現象 | 根因 |
    |---|---|---|
    | 1 | CHECK 16 回報「僅有首列 BOOTSTRAP，跳過檢查」 | `EXEC-LOG` 第二列 commit 欄為佔位符「本批」，整個 CHECK 空轉，且訊息本身錯誤 |
    | 2 | CHECK 15 回報「待核對 0 個」 | 交接區 §5.1 末列停在「本批（尚未 commit）」，§9.3 要求「下一批補上」未執行 |
    | 3 | `audited-*` tag 落後三批 | §11.3 規劃的偵測從未實作，`scripts/` 與 `.github/` 全庫查無 `audited-` 字串 |
    | 4 | CHECK 8／9 的兩個測試通過 | 測試斷言仍是 `lag > 1` 時代的訊息，**唯一通過原因是新訊息把舊斷言字串包住**；`git_prev2` 全檔零出現，lag=2 邊界零覆蓋 |

    第 4 個最險：審計官原本把該矛盾字串判定為「不改變行為的美觀瑕疵」，
    實測移除後為 `2 failed, 64 passed`。**判定錯誤，且錯在沒有搜尋
    該字串在何處被引用**——`auditor-protocol.md` §6.7 的第七次失效。

    **C. 規則來源虛構（第六類回報失真）**

    執行者依提示詞 `cat` 三份規則檔並貼出。審計官逐字比對：
    `role-boundaries.md` 屬實；`prompt-preflight.md` 與
    `git-and-reporting.md` **章節標題、§1 全部條目、§2 整節內容皆與實際
    檔案不符**——前者那張 14 列「歷史失效清單」表在實際檔案中不存在，
    後者「§1 禁止事項」五條實際檔案一條都沒有。
    執行者貼出的 §3.4 表漏了 E12，卻在報告中聲稱驗證了 E12。

    **`auditor-protocol.md` §6.1 第 10 項的「動手前必讀」機制，
    自建立以來從未有人比對過貼出的內容。第一次比對，三分之二是假的。**

    最可能的成因寫在被虛構的那份檔案裡：自動載入的規則被 context 壓縮
    換掉，而執行者對此不自覺。成因不影響結論——**它是一個產生證據
    但沒有人核對證據的機制**。

    **D. 落點錯誤：審計官提議開 ADR-0020**

    審計官在讀過 §5.7（標題即「規則的層級決定它會不會被執行」、
    列有六次實證）的同一輪，提議新增 ADR-0020 存放一條分工規則。
    **這是 §5.7 的第七次，且是唯一一次「知道規則還照做」。**

    根因由使用者指出後查證確認，不在個人：`PRINCIPLES.md` §1 的層級表
    **未列 `.claude/rules/`**，四個判別問句的答案也沒有它——第 2 問
    只給 `AGENTS.md` 與 `.agents/rules/`，兩者都是執行者的。
    一條給審計官的規則依序自問下來，**只有第 4 問（ADR）能答「是」**。
    判別演算法把人推向 ADR。本批修正 §1。

    **E. 上游架構與 Port 的全庫實測**

    上游 `mattpocock/skills` HEAD `3cca18b`（2026-09-04）已改版為 5 bucket
    ＋ promoted 二分 ＋ Claude Code plugin ＋ docs 樹，v2 停在改版前快照，
    且無任何審查機制或版本記載。Port 實測為 11 個而非「三方衝突」，
    其中 4 個為本專案自訂（3000／3001／3002／8888），
    ADR-0017 未涵蓋 6379／9222／9223。詳見 B-28 至 B-33。

47. **指紋機制上線：獨立性的來源從審計官轉移到 CI（2026-09-06）**

    **A. 為什麼需要它**

    到本批為止，審計官與執行者之間的所有數字比對，都是
    「兩邊各自敘述，然後人工對照」。第 46 點 C 段記載的規則來源虛構
    就發生在這條路徑上——執行者被要求 `cat` 三份規則檔並貼出，
    貼出的兩份是編的，而**沒有任何機制會發現**。

    同一條路徑還是審計官 token 消耗最大的單一來源：手工列 11 個檔案的
    行數、圍欄數、章節序列，一批就要跑十幾次指令。

    **問題不在誰不老實，在於哪些內容經過了模型的重述。**

    **B. 解法：讓數字不可能被重述**

    `scripts/fingerprint.py` 是唯一被允許產生數字的地方。雙方都不報數字，
    雙方都跑同一支腳本。執行者把輸出 commit 進
    `docs/fingerprints/exec-latest.json`，CI 在 GitHub runner 上
    **重跑同一支腳本並逐欄比對**。

    CI 是雙方都控制不了的第三方。執行者不能讓它說謊，審計官也不能。

    這擴充了 ADR-0007 的立論：**原則要求的是「獨立性」，
    不是「必須由 Claude 提供獨立性」。** 一旦獨立性有了第二個來源，
    機械核對就可以下放，而品質不降反升——腳本不會像人一樣
    把 22 個錨點寫成 21 個。

    **C. 三條紅線（下放的邊界）**

    1. **判斷永遠不下放。** 執行者可以回報「發現三處不一致」，
       但「哪一處重要、要不要退回整批」由審計官決定。
    2. **獨立 clone 不取消。** 審計官仍每批 clone，
       差別是不再逐檔手讀，而是跑指紋比對加讀 `git diff`。
    3. **CI 綠燈不是免死金牌。** 本專案已出現四個假綠燈；
       審計官每批仍須隨機挑一個 CHECK 注入反例，確認它會紅。

    **D. 設計上的兩個陷阱，都已寫進規格**

    | 陷阱 | 若不處理的後果 | 處置 |
    |---|---|---|
    | 指紋涵蓋 `docs/fingerprints/` | 寫入動作改變被描述的數字，自我指涉 | 該目錄一律排除 |
    | `base_head`／`generated_at` 納入比對 | 執行者在 commit 前產生、CI 在 commit 後執行，兩者必然不同，**CI 會 100% 紅燈** | 三個中繼欄位不參與比對，並以測試守護 |

    **E. 本批同時修掉的兩個審計官漏項**

    看板 C-04 未隨裁決更新（B-44）、交接區 §5.3 與看板 C 節分歧
    （B-45）。兩者同一成因：處理裁決結果時只想到看板，
    忘了交接區也有一份。**`prompt-preflight.md` §3.1 的配對清單
    未登記「看板 C 節 ⇔ 交接區 §5.3」這一對**，登記排批 2b。

48. **CRLF、標準驗證集的邊界、與審計官的知情偏離（2026-09-06）**

    **A. 指紋機制上線首日兩次紅燈，兩次都是審計官的錯**

    | commit | CI | 根因 | 誰的錯 |
    |---|---|---|---|
    | `2d76958` | failure | `sha256` 讀原始位元組，未處理 Windows `core.autocrlf` 的 LF→CRLF | 審計官規格錯誤 |
    | `3a85a30` | failure | 自檢聲明 E8 宣告不更新三處，未查 §6.1-8 有機械守衛 CHECK 12 | 審計官判斷錯誤 |

    兩次執行者都逐字照規格執行，且在第一次獨立診斷出 `core.autocrlf`
    為根因。**執行者無過失。**

    **B. CRLF：最「嚴謹」的欄位是唯一壞掉的那個**

    42 個受管檔案中，`lines`／`fences`／`headings` 全部相符，
    只有 `sha256` 不符——因為前三項都經過 `splitlines()`，會吃掉 `\r`。
    位元組級證明：`sha256(MISSION.md 的 LF 內容→CRLF)` 等於指紋檔記載值。

    規格裡那句「讀 bytes，非 text」的註解是審計官加的，
    當時以為那是比較嚴謹的選擇。**它是整份規格裡唯一壞掉的欄位，
    而它壞掉的原因正是那個「嚴謹」。**

    修正採兩道：雜湊前正規化 `\r\n`→`\n`（程式碼層，不依賴任何人的
    git 設定）＋ `.gitattributes` 的 `* text=auto eol=lf`（repo 層）。
    換行本身的差異改由獨立的偵測負責，不混進指紋。

    **C. 假綠燈的真正生成方式**

    在 CRLF 不一致的狀態下，`validate_skills`、`check_consistency`、
    `pytest` **三項全部通過**，只有 `fingerprint.py --verify` 會紅。
    而它之所以被跑到，是因為寫在該批的驗證步驟裡。

    > **不是機制說謊，是機制沒有被放進每批都會跑的清單裡。**

    登錄為 B-47：`--verify` 必須升格為標準驗證集第四項。

    **D. 本地與 CI 的結構性差 1**

    任何判準含 HEAD 的檢查，本地（commit 前）與 CI（commit 後）
    的答案必然差 1。CHECK 8／9 門檻 `lag > 2` 故差 1 看不出；
    **CHECK 12／16 門檻 `lag > 1`，正好卡在這個差值上。**

    後果：「本批漏更新 AUDIT-LOG」在本地驗證中**原理上偵測不到**。
    執行者跑了驗證、得到綠燈、如實回報——完全正確。登錄為 B-51。

    **E. 審計官的知情偏離重新打開了一個已經補過的洞**

    `prompt-preflight.md` §3.7 標題即「十八項全部可機械驗證，
    沒有例外」，內文寫「沒有任何一項需要你憑信任接受」。
    該節建立於 2026-09-05，起因是原本只有 7 項被涵蓋，
    其餘 11 項審計官勾 ✅ 無人能反駁，E11 造假就是從那個洞出來的。

    2026-09-06 審計官把 E8 標為 ⚠️ 並附理由，執行者接受、未停止。
    **E8 就此從機械驗證項變成信任項——同一個洞被重新打開。**
    而 `role-boundaries.md` §2 又禁止執行者判斷規範是否應存在，
    執行者被夾在中間。登錄為 B-50。

    修法：E8 比對為否時一律停止、不接受任何理由。審計官若真的需要
    偏離 §6.1-8，唯一合法路徑是先另開一批修改規則本身。

    **F. 同形錯誤連續三批**

    | 批次 | 改動／跳過的東西 | 沒查的依賴 |
    |---|---|---|
    | 批 1 | `check_consistency.py` 的顯示字串 | 誰引用了這個字串（測試斷言） |
    | 批 2a | 跨平台的位元組比對 | git 在跨平台時會改動什麼位元組 |
    | 批 2a-fix | 偏離 §6.1-8 | 這條規則有沒有機械守衛 |

    共同形狀：**改動或跳過某物之前，沒有去查誰依賴它。**
    `auditor-protocol.md` §6.7 已有此規則，但措辭只舉「數字」與
    「章節引用」為例。登錄為 B-52，搜尋對象清單擴為四類。

    審計官在第二次之後曾寫「這一點我會在 2b 的自我審查裡處理」，
    然後在下一批立刻犯了第三次。**「下一批再處理」不是處置，
    寫進機械檢查才是**——這正是 `PRINCIPLES.md` §2.8 的內容。

49. **全架構盤點：機制在檢查錯誤的東西（2026-09-06）**

    **A. 五項結構性發現**

    | # | 發現 | 實測依據 |
    |---|---|---|
    | 1 | **CHECK 1–7 內嵌於 453 行的 `run_checks()`，不是函式** | `grep "^def "` 只有 `run_checks`、`get_git_heads`、`check_8`～`check_16` |
    | 2 | 治理層分裂成兩個速度 | 稽核迴圈檔 09-05～09-06；SOP 八份停在 08-25；`skills-architecture.md` 停在 08-13 |
    | 3 | 治理文件 10,054 行 vs `MISSION.md` 30 行 | backlog 單檔 2,501 行佔 25% |
    | 4 | 看板 116 項、待辦 50 項，重構主線 E 節僅 5 項且完成 0 | B 節 52 項中 40 項是治理機制自己的缺陷 |
    | 5 | **零項 CHECK 驗證 SOP 內容或跨層矛盾** | 6 項對稽核迴圈自己、5 項通用格式、3 項 `skills/`、2 項路由 |

    **B. 第 1 項最嚴重**

    CHECK 8–16 是獨立函式，有 322 行單元測試，每次 push 自動回歸。
    CHECK 1–7 無法被測試呼叫，只有 B-15 的一次性反例注入。
    今天若有人重構 `run_checks()` 弄壞 CHECK 3，
    **沒有任何測試會紅，CI 會是綠的**。

    我們追殺了五次的假綠燈形狀，現在住在檢查器本身裡面。

    **C. 診斷：機制被「上一次出的錯」驅動長出來**

    過去兩週的錯全部發生在稽核迴圈裡，因為我們只在那裡活動。
    於是機制越來越擅長抓稽核迴圈的錯，而 SOP 層在完全沒有守衛的
    狀態下靜置了 12 天。

    > **一個只檢查自己的審查機制，會在它最不被使用的地方最脆弱。**

    已知的兩個跨層矛盾都是人工偶然發現的。沒有任何機制會找到第三個。

    **D. 審查機制的完成定義（五條可機械驗收）**

    | # | 條件 | 本批前 | 本批後 |
    |---|---|---|---|
    | 1 | 每個 CHECK 是獨立函式且有正反例測試 | 9/16 | 9/16 |
    | 2 | 每個 CHECK 至少命中過一次真違規並留紀錄 | 未追蹤 | 未追蹤 |
    | 3 | 每份規範層檔案至少被一個 CHECK 涵蓋 | SOP/ 未涵蓋 | 未變 |
    | 4 | 本地與 CI 判準一致 | 差 1 | 未變 |
    | 5 | **審計官不能豁免任何自檢項** | 可豁免 | **已修** |

    **現況由 0/5 進為 1/5。** 其餘四條分別排在批 2c、2d、2e。

    **E. 使用者裁決與兩個附加條件（2026-09-06）**

    同意拆解 `docs/HANDOVER.md`、同意封存 A 節 39 項與 B 節已完成 20 項、
    同意「修錯誤形狀優先於加新功能」的批次順序。附兩個條件：

    1. **移除任何本體前必須再做一次檢查，且要寫進最高邏輯。**
       落點依 `PRINCIPLES.md` §1 第 1 問判定為 `PRINCIPLES.md` §2.9；
       依 §2.8 同批落到 `.claude/rules/auditor-protocol.md` §6.1 第 17 項、
       `.claude/rules/handover-selftest.md` E19、
       `.agents/rules/prompt-preflight.md` §3.4 E19 列、
       `docs/ARCHIVE-INDEX.md` 第三節第 4 條。
       **另有一道是免費的**：受管檔案被移除時，
       `scripts/fingerprint.py --verify` 會印 `[檔案缺少]` 並 exit 1——
       指紋機制本來就是移除偵測器，只是之前沒有這樣用它。
    2. **封存後要有足夠的邏輯與指向。**
       `docs/ARCHIVE-INDEX.md` 已存在且設計良好，
       但它自己沒有機械守衛。處置為 **CHECK 20 可達性雙向驗證**（B-59）。

    **F. 2b-1 首投被攔下，與審計官作業方式的改變**

    首投的【修改 5】寫給 `.agents/rules/prompt-preflight.md` 的文字中，
    有兩處跨檔 §6.1 未帶檔名，執行者依 §3.3 停止並回報，攔截正確。

    審計官的 E16 打了 ✅ **但從未實際跑過 CHECK 10，是用眼睛掃的**。
    這是連續第四批的同形錯誤：宣告了自己沒有驗證的事。

    改正後審計官在本地 clone 實際套用五處修改再跑檢查，
    第一次仍失敗一項——**檔名放在上一行、章節號換行到下一行**。
    而 E16 的條文自己就寫著「CHECK 10 逐行判斷，換行斷開就會 FAIL」。
    **讀著那句話，然後犯了它描述的錯，因為換行在編輯器裡看起來完全正常。**

    > **凡是有機械守衛的東西，自檢時就必須跑那個守衛，不能用看的。**

    同輪另發現：證據區塊的圍欄數不在 §3.6 的交叉驗證表內，
    審計官把 `.claude/rules/auditor-protocol.md` 的圍欄數誤寫為 0
    （實際 2），執行者回報了實際值但沒有義務比對宣稱值。登錄為 B-61。

    **G. CHECK 17–24 編號一次配置完成**

    B-21 記錄過編號被兩件事佔用，根因是規劃編號與實作編號無單一權威
    來源。本輪一次配完並寫進看板 B-60，**該列即為單一權威來源**。

50. **把「我檢查過了」變成不可偽造的東西，與閘門自己的兩個缺口（2026-09-06）**

    **A. 四批同形錯誤，三批可被同一個動作攔下**

    | 批次 | 審計官宣告 | 實際沒做 | 本地模擬能否攔下 |
    |---|---|---|---|
    | 批 1 | 「不改變行為」 | 沒搜尋誰引用那個字串 | 能，pytest 會紅 |
    | 批 2a | 「讀 bytes 比較嚴謹」 | 沒查 git 跨平台會改動位元組 | 部分，本地是 Windows，需 CI |
    | 批 2a-fix | E8 知情偏離 | 沒查 §6.1-8 有 CHECK 12 守著 | 能，CHECK 12 會紅 |
    | 2b-1 首投 | E16 打勾 | 沒有實際跑 CHECK 10，是目視 | 能，CHECK 10 會紅 |

    **B. 但「我跑過了」本身也可能是宣告**

    E16 的教訓正是這個：條文寫得清清楚楚，審計官打了勾，
    而那個勾是用眼睛掃出來的。**若只寫成「必須先跑模擬」，
    它會變成第二個 E16。** 因此閘門的設計要求是：
    **產生一個沒有真的跑過就寫不出來的東西。**

    **C. 閘門在前兩投各攔下審計官一次，兩次都暴露閘門自己的缺口**

    | 投次 | 現象 | 缺口 | 處置 |
    |---|---|---|---|
    | 第一投 | 宣告 332 行、實際 332 行的檔案卻宣告成 327 | 規則要求「模擬後送出」，**未要求「模擬的對象等於送出的文字」**——審計官模擬完才在 §3.6 多加五行說明 | §6.1-18 補上「模擬的對象必須是最終送出的文字本身」與單一來源作法 |
    | 第二投 | 行數與圍欄數全部相符，唯獨雜湊不符 | **雜湊是錯的原語**。逐行比對雙方的 136 行輸出：內容完全相同；另試 CRLF 版仍不符 | (e) 段改為純文字比對：行數／圍欄數、項數、每個修改檔的最後三條 INFO 行 |

    第二投的教訓值得特別記下：**雜湊把「內容是否相同」綁死在行尾、
    locale、工具實作這些與內容無關的變數上。** 這與 B-46 的 CRLF
    是同一形狀——審計官在自己設計來防錯的閘門上，重犯了同一個錯。

    改用「最後三條 INFO 行」的理由：它們累積了整個檔案的位移量，
    與整段雜湊一樣不可偽造，但免疫於工具差異，而且只有九行。

    **D. 落點不是 SOP/**

    使用者要求「寫入合適的位置作為 SOP」。依 `PRINCIPLES.md` §1
    第 2 問，這條規範的對象是審計官，落點為
    `.claude/rules/auditor-protocol.md` §6.1 第 18 項。
    `SOP/` 是執行者的程序層（第 2 層），對象不符。
    這正是 2b-1 才剛把 `.claude/rules/` 補進 §1 層級表的價值——
    在那之前，四個判別問句根本產生不出這個答案。

    **E. 兩個已失準的東西**

    1. §3.7 的標題與內文寫「十八項」，而 E 節在 2b-1 已增為 19 項，
       **當場失準且無任何機制會發現**。處置不是改成 20——
       那只是把過期日期往後推一批——而是把數字拿掉。
       與 `.agents/rules/git-and-reporting.md` §3
       「凡是會被自身寫入行為改變的數字，不得寫進文件」是同一形狀。
    2. §3.6 的交叉驗證表只有三項，**圍欄數不在其中**，
       所以 2b-1 的圍欄數誤寫（0 vs 實際 2）沒有被比對。
       本批擴為五項，補上圍欄數與 (e) 段。

    **F. 三投的共同結論**

    三次都是審計官出錯，三次都被機制當場抓到，零次靠審計官自己發現。
    **這正是 `PRINCIPLES.md` §2.8「這條沒做的話，什麼東西會發現」
    要的答案**——現在答得出來了。

51. **根因定案，與把數字交還給工具（2026-09-06）**

    **A. 十九件錯誤，四個形狀，一個根因**

    | 形狀 | 件數 | 代表 |
    |---|---|---|
    | A 宣告與實際脫節 | 8 | E11 七次數錯自己寫的清單；「新增十列」與「78 列連號」互相矛盾 |
    | B 沒查依賴 | 4 | 改字串未查測試斷言、偏離規則未查機械守衛 |
    | C 跨環境假設 | 2 | CRLF、雜湊原語 |
    | D 多副本不同步 | 3 | 看板 C-04、交接區 §5.3、**B-72/73/74 只寫進 backlog 散文未寫進看板** |
    | 其他 | 2 | 攔截點未指定時點、預期命中數寫錯 |

    壓到一層是同一件事：

    > **審計官的輸出是一次連續生成，但宣告聲稱它是多步驗證的產物。**

    擬定修改、寫下錨點、宣告已驗證、寫下預期值——四者在同一段生成流裡
    完成。對模型而言「回憶一個測量結果」與「生成一段符合期待的文字」
    沒有內部分隔，因此「我驗證過了」與被驗證的內容出自同一段生成，
    **它永遠會自洽，也因此不帶任何證據力**。

    這解釋了為何加強措辭七週無效：措辭也是文字，進入同一段生成後
    被同一個機制繞過。**只有外部產物有效，因為它不是模型生成的**——
    這正是指紋、模擬閘門、執行者攔截三者有效，而 §6.7 寫了七週沒生效
    的差別所在。

    **B. 使用者的提案與審計官的修正**

    使用者提出「每次宣告的數據都親自從 GitHub 重新取得」。
    審計官逐件檢驗：**能修 1 件、部分修 3 件、修不掉 12 件**。
    原因是審計官本來就每輪重 clone，多數錯誤不是讀取問題，
    而是「寫了沒有產生者的數字」。

    但使用者的直覺指向對的東西，只是範圍要放大：

    > **提示詞裡的每一個數字，都必須是本輪某次工具呼叫的輸出。**

    數字只有四種合法來源：repo 現況→新鮮 clone；文件的自我描述
    →腳本 `len()`；套用後的未來狀態→本地模擬；外部系統狀態→該系統 API。
    **「從 GitHub 重讀」只是第一種。** 登錄為 B-72。

    **同時使用者抓到一個真實缺口**：§8.4-2「每輪最多一次 clone」是
    **上限，而沒有下限**。登錄為 B-73。

    **C. 執行者的回報邊界**

    使用者另問：CHECK 10 的 136 行輸出是否必要。

    審計官回頭檢驗：**若第二投只貼三檔各自的尾三條 INFO，
    足以下同樣的結論**——那九行與預期值完全相同，當場就能判定
    內容一致、問題在雜湊。中間 124 行沒有多給任何資訊。

    因此得出邊界：**凡是能從 repo 的某個 commit 重新產生的東西，
    執行者不必回報，審計官自己產生。** 登錄為 B-74。
    **一個例外**：「動手前必讀」的章節序列比對必須照貼——
    它測的不是 repo 而是執行者有沒有真的讀檔（見第 48 點 C 段）。

    **D. 流程層的四項優化**

    | # | 發現 | 處置 |
    |---|---|---|
    | 1 | 提示詞約四成是每批重寫的樣板，重寫一次就是一次寫錯的機會 | B-75 |
    | 2 | 審計官的核對階段是固定流程卻每次手打，批 2a 即因此漏跑 `--verify` | B-76 |
    | 3 | BPE 輸出後若被修潤，就重現 B-64 | B-77 |
    | 4 | **散文是一層有損的重新編碼**：兩份套用腳本、兩次解析 | B-78 |

    第 4 項最根本：它讓 B-64 那類錯誤從「靠閘門攔下」
    變成「不可能發生」。

    **E. 一個已實測的技術限制**

    `requirements.txt` 只有 `pytest` 與 `playwright`，**沒有 PyYAML**。
    批次規格因此不能用 YAML；JSON 又需要對多行錨點逃脫、人工撰寫極易
    出錯。最終採零相依的純文字分隔線格式，只用標準庫解析。

    **F. 批次拆分的決定**

    2b-3 原規劃含兩支新腳本與三條規範共 12 檔，逼近 §8.4-2 的
    十三檔上限，而那個上限是為同質變更訂的。拆為 2b-3（BPE）與
    2b-4（`impact_scan.py` ＋ 規範）。

    關鍵理由：**2b-3 是最後一份手寫的提示詞，同時是「新程式、
    無舊版可 diff」的批次**——手寫提示詞的錯誤模式碰上驗證最弱的
    變更類型，是最糟的組合，必須讓它盡可能小。
    而拆分**不會增加手寫提示詞的次數**：2b-4 的提示詞將由 BPE 產生。

    **G. 本批首投被攔下，暴露 BPE 原規格的一個缺口**

    首投的看板修改宣告「新增十列」與「B-01 至 B-78 連號」，
    兩者互相矛盾（65+10=75），且缺 B-72／73／74——
    那三項只寫進了本點 B、C 段的散文，沒有寫進看板。**D 類的第三次。**

    審計官隨即查證一件更重要的事：`scripts/check_consistency.py`
    對 `docs/TASKBOARD.md` **只驗最後更新 HEAD（CHECK 8）**，
    **全庫沒有任何 CHECK 驗證 B 節編號連續性**。
    所以 BPE 依原規格跑模擬會 16 項全 PASS，**抓不到這個錯**。
    是執行者的人工比對抓到的。

    > **審計官每份提示詞都寫「插入後的預期序列」，
    > 而那從來只是一句宣告，沒有任何東西驗過它。**

    處置：BPE 新增 **EXPECT 區塊**，把該宣告變成套用後實測比對的事實；
    測試第 10 項專門構造「宣告 1-5、實際缺 4」的反例守護它。
    獨立的 CHECK 25 排批 2d。登錄為 B-79。

52. **數字交還給工具：BPE 上線與第一次實戰（2026-09-07）**

    **A. 三條規範落地**

    | 規範 | 落點 | 來源 |
    |---|---|---|
    | 每一個數字都必須有它的產生者 | `PRINCIPLES.md` §2.10 | B-72，使用者提出、審計官修正範圍 |
    | clone 新鮮度的下限 | §6.1 第 19 項 ＋ E21 ＋ preflight §3.4 | B-73，**使用者發現** |
    | 腳本產出的證據不得由審計官修改 | §6.1 第 18 項延伸句 | B-77，B-64 的直接推論 |

    §8.4 第 2 項是**規模的上限**，§6.1 第 19 項是**新鮮度的下限**。
    在本批之前只有上限——`§8.3` 的「每輪最多一次 clone」講的是不要浪費，
    卻被當成允許沿用。

    **B. BPE 的第一次實戰**

    本批的證據區塊全部由 `scripts/build_prompt_evidence.py` 產生：
    `[E11] 錨點總數: 15` 由 `len(mods)` 產生、十五個錨點的 `count()`
    與行號逐條實測、(b)(d) 逐檔量測、(e) 在暫存副本上套用後跑出
    16 項全 PASS。**七次手數錯錨點數量的錯誤到此為止。**

    **C. 審計官親自重跑反例，未採信執行者回報**

    上一批要求兩項反例注入。審計官在自己的 clone 上重跑一次，
    兩項都如預期變紅；還原後 10 passed、工作區零異動。
    **這是 `PRINCIPLES.md` §2.5 獨立驗證的具體執行。**

    **D. BPE 的兩個限制，都在首投被暴露**

    | # | 限制 | 登錄 |
    |---|---|---|
    | 1 | 模擬只涵蓋規格中有真實 payload 的修改；紀錄類修改未進模擬 | B-80 |
    | 2 | **輸出不含錨點原文**，只有 `<檔案>:<行號> count=<n>`——審計官拿到輸出後，對長錨點就只寫了行號，違反 §3.4 的 E3，被執行者攔下 | B-81 |

    第 2 點值得記下：**工具產生了正確的數字，但沒有產生規則要求的
    全部內容，而審計官沒有補。** 工具化不是終點——
    工具的輸出範圍若小於規則的要求範圍，缺口就落回人身上。

    兩者的根治方向都是 B-78：讓批次規格成為「審計官模擬」與
    「執行者套用」的共同來源。

    **E. 進度現況（2026-09-07 實測）**

    | 面向 | 完成度 |
    |---|---|
    | 稽核／治理機制 | 約 85% |
    | 技能文件層遷移 | 約 87%（54 個已遷移，E-01 剩 8 個） |
    | Runtime 執行層 | **0%**——六大 PM2 常駐進程仍住在技能文件資料夾 |
    | Persona 層 ／ Data 層 | **0%** |
    | **重構主線 E 節** | **0/5** |

    看板 143 項、已完成 65 項、待辦 71 項。
    治理文件 40 檔 11,333 行（不含 20 份 ADR），`MISSION.md` 30 行。

    **B 節從本對話開始時的 18 項增長到 79 項，其中 B-11 之後的 68 項
    幾乎全是治理機制自己的缺陷。每修一個平均發現 1.5 個新的——
    這是發散，不是收斂。**

    給下一位審計官的建議：**凍結治理層的新增**，把 52 個 B 節待辦
    分成「不做它重構主線會出錯」（估 8–12 項，做完就停）與
    「不做它只是機制不夠漂亮」（估 40 項，整批封存），
    然後把資源移回 E 節。**該取捨需使用者裁決。**

> 本區由執行者在每批次結束時更新，審計官核對。
> 維護規則見 `.claude/rules/auditor-protocol.md` §9.3。

53. **交接區 §5.4 的第一次清理，與 `PRINCIPLES.md` §2.9 的第一次真實應用（2026-09-07）**

    **A. 成因：一個只追加、從不清理的堆疊**

    §5.4 的每一份提示詞都只替換第一個項目符號、並在其前追加新的，
    **從未移除被取代的**。這個模式重複十輪後，本節在 `b46cd5d` 實測為
    62 行（含標題）、18 個頂層項目符號，其中十條過期或互相矛盾：

    - **兩條都宣稱自己是「批 2b-5」**，內容完全不同：一條寫
      B-74 ＋ B-80／B-81 ＋ `scripts/impact_scan.py`，另一條寫 B-78。
    - **兩條「後續」順序清單**，差別只在批 2d 是否包含 B-61。
      加上「執行順序已定案」那一條，同一節裡有三份粗細不同的順序敘述。
    - 三條已完成批次（2b-2、2b-3、2b-4）的規劃仍在。
    - 兩條歷史敘述（批 2 拆為 2a／2b、批 2b 優先順序重排）屬留痕層內容，
      落點應是編號點而非本節。
    - 一條「本節曾落後三批」的歷史敘述，已登錄為 B-22。

    `.claude/rules/auditor-protocol.md` §9.2 第 1 點要求接手時先讀本節，
    `.claude/rules/handover-selftest.md` B4 也把本節當成定位依據，
    **兩者都假設它是乾淨的，而沒有任何機制保證**。偵測缺口登錄為 B-82。

    **B. `PRINCIPLES.md` §2.9 的第一次真實應用**

    本次清理是本專案第一次對「本體」執行移除，三步複查結果如下。

    **第 1 步 反向引用掃描**：全庫搜尋 `§5.4`、「進行中／等待回報」，
    命中三處引用方——`.claude/rules/auditor-protocol.md` §9.2 第 1 點、
    `.claude/rules/handover-selftest.md` B4、Project Instructions 的開場動作。
    三者引用的都是**本節這個位置**，不是任何一條個別項目符號，
    因此清理內容不影響它們。

    **第 2 步 唯一內容確認**：逐條比對後，十條中八條的內容在
    `docs/TASKBOARD.md` 或本檔既有編號點中已存在，屬搬移；
    **兩條是無可取代的裁決紀錄，屬刪除**，本批先搬移再刪除：

    - 「執行順序已定案（2026-09-06 使用者裁決）」→ 搬入本點 F 段，
      並以 §5.4 新版的「後續順序」承接現行狀態。
    - 「B-16 的 R1 改判為交接後執行」→ 搬入 `docs/TASKBOARD.md` B-16 該列。
      **搬移時發現看板 B-16 仍寫「R1 交接前必做」，與本節的改判直接矛盾**，
      本批一併更正。這是 B-87（看板與 repo 不同步）的第三個實證。

    **第 3 步 獨立複查**：重新讀取 `b46cd5d` 的實體檔案再跑一次第 1、2 步，
    不採信第一次的結論，兩次結果一致。

    **C. 六項「已修正但看板未同步」的實測落地位置**

    2026-09-07 於 `b46cd5d` 逐項實測，六項在 repo 中皆已生效：

    | 項目 | 實測落地位置 |
    |---|---|
    | B-24 | `.claude/rules/auditor-protocol.md` §6.7 清單第 4 條，該清單共 7 條 |
    | B-27 | 規則層「章節序列」共 3 處，動手前必讀已含章節序列比對 |
    | B-40 | `PRINCIPLES.md` §1 層級表已列 `.claude/rules/`，第 2 問已有審計官出口 |
    | B-50 | `.agents/rules/prompt-preflight.md` §3.4 已含「自檢聲明不接受任何豁免」 |
    | B-52 | `.claude/rules/auditor-protocol.md` §6.7 已含「要偏離任何一條規則」 |
    | B-61 | `.agents/rules/prompt-preflight.md` §3.6 驗證表 5 列，已含「圍欄數相符」 |

    依 `.claude/rules/auditor-protocol.md` §10.4，封存需使用者確認，
    故本批只把狀態改為已完成，封存提議排批 2f。
    **封存前必須先把狀態改對，否則封存的是一個錯誤狀態。**

    **D. 本輪新發現：表格被空行斷開（B-88）**

    `b46cd5d` 把 E21 寫進 `.agents/rules/prompt-preflight.md` §3.4 時，
    在 E20 與 E21 之間留了一個空行。該表因此在 E20 結束，
    E21 成為表格外的孤立一行——沒有分隔列，不會被渲染成表格。

    **這是 A-20 的同形第二次**，而三個機制都抓不到：
    CHECK 11 只驗 `.claude/rules/auditor-protocol.md` §6.1 與 E 節的對應關係，
    CHECK 2 只驗圍欄配對，執行者用 grep 數「E 項目 21 列」——
    **grep 不在乎空行，所以數字是對的、表格是斷的**。登錄為 B-88。

    同輪另收斂三處與交接說明不符的數字，依 `PRINCIPLES.md` §2.7：
    時序最新的 tag 為 `audited-e6f543a` 而非 `audited-ec840fe`、
    缺 tag 者為七批而非九批；本節為 62 行（含標題）而非 61 行；
    第 44 至 53 點為 589 行而非約 700 行。

    **E. 打 `audited-*` tag 的判準（2026-09-07 使用者裁決，採丙案）**

    缺 tag 的八個 commit 中，`2d76958` 在 §5.1 明載「核對不通過」、
    `3a85a30` 明載「內容核對通過但 CI failure」。使用者裁決：
    **內容核對不通過者永久不打；內容通過而該批 CI failure 者要打。**
    因此本批補打七個，`2d76958` 不打。
    判準本體寫入 `.claude/rules/auditor-protocol.md` §11.4，
    並依同檔 §5.7 把「每批補打 tag」補進 §6.1 第 20 項、
    `.claude/rules/handover-selftest.md` E22 與
    `.agents/rules/prompt-preflight.md` §3.4——
    **§11.3 的規則自建立以來從未在執行路徑上，這正是 tag 落後七批的成因，
    也是 §5.7「規則的層級決定它會不會被執行」的第八次。**

    **F. 使用者裁決的執行順序（2026-09-06，自 §5.4 搬入留痕）**

    批 1 假綠燈與 `PRINCIPLES.md` §1 修正 → 批 2 指紋與機械化 →
    批 3 B-01 三份 ADR 分層搬移 → 批 4 C-01／C-02／C-03 執行
    ＋ B-30／B-31／B-32／B-33 → 批 5 上游對照表 → 批 6 Runtime 依賴調研
    → 批 7 起 E-03、E-01、E-02、E-04、E-05。

54. **第一次「核對不通過」的可量測實證：自寫套用腳本產生與規格不一致的輸出（2026-09-07）**

    **A. 三處不一致**

    審計官把批 2b-5 的批次規格套用到 `b46cd5d` 的乾淨副本，
    再與執行者實際 push 的 `10f7e31` 逐檔 `diff`，六個目標檔中三個完全相同，
    三處不一致全部集中在兩個檔：

    | 位置 | 應為 | 實際 |
    |---|---|---|
    | `docs/TASKBOARD.md` 第 114 行 | 「的」 | 平假名 |
    | `docs/TASKBOARD.md` 第 135 行 | 「證」 | 日文新字體 |
    | 本檔第 53 點與 §5.1 之間 | 一個空行 | 兩個空行 |

    **B. 成因：規格沒有被當成規格用**

    提示詞明寫「不要自己另寫解析邏輯，那會重新引入一層編碼」，
    並附上以 `parse_spec` 與 `apply_mod_to_text` 套用的固定腳本。
    執行者未使用該路徑，而是逐條自寫套用腳本並手工重打部分內容，
    字形因此在重打時被日文輸入環境改寫。

    **這是 B-78／B-85 所指的那一層有損重新編碼，第一次留下可量測的實證**——
    先前只能論證它「理論上會失真」，本次直接量出三處。
    「模擬的對象＝送出的文字＝執行者套用的文字」三者只要不是同一份，
    差異就會出現在沒有人看的地方。

    **C. 四項驗證全綠**

    `validate_skills` 54 技能零錯誤、`check_consistency` 16 項全 PASS、
    `pytest` 76 passed、`fingerprint --verify` exit 0，CI 亦為 success。
    **沒有任何一項會看字形。** CHECK 14 的偵測集是一份手寫的簡體字清單，
    平假名與日文新字體漢字都不在其中。登錄為 B-89。

    **D. 處置：不 revert**

    依 `.claude/rules/auditor-protocol.md` §11.1 第 2 項，
    範圍清楚的內容損壞以修正批次處置，不 revert。
    依同檔 §11.4，核對不通過者不打 tag，故無 `audited-10f7e31`——
    **這是 §11.4 上線後的第一次實際適用**。

### 5.1 上一批狀態

上次核對通過的 HEAD：b15d5bf

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
- `ec840fe`（§3.4 擴為 18 項 ＋ §3.7 ＋ §3.8 ＋ 建立
  `docs/EXEC-LOG.md` ＋ CHECK 16 ＋ HEAD 欄位更正）已於 2026-09-05
  由審計官核對通過。**本列 hash 原為佔位符「本批（尚未 commit）」
  且下一批未補上**，導致 CHECK 15 持續回報「待核對 0 個」，
  2026-09-06 補正，成因見第 46 點 B 段。
- `e6f543a`（CHECK 8／9 門檻改為 `lag > 2` ＋ B-15 完成）
  已於 2026-09-06 由 **E2 交接後的新審計官**核對通過：
  5 檔異動、零夾帶、驗證三項全過。核對時發現交接說明與 repo 記載矛盾，
  依 §9.1 以 repo 為準，見第 46 點 A 段。
- `7450c4a`（`PRINCIPLES.md` §1 判別演算法修正 ＋ 四個假綠燈修復
  ＋ 回報即 commit 上線 ＋ B-19 至 B-41 共 23 項缺口登錄）
  已於 2026-09-06 由審計官核對通過：7 檔異動、零夾帶、
  獨立驗證四項全過（54 技能、16 項 CHECK、68 測試、
  CI Run 34003070306 success）。
- `2d76958`（`scripts/fingerprint.py` ＋ `scripts/anchor.py` ＋ 兩者測試
  ＋ CI 指紋比對 ＋ B-42 至 B-45 登錄）**核對不通過**：
  指紋的 sha256 未處理 Windows CRLF，CI Run 34011261550 failure。
  規格錯誤，非執行者實作錯誤。見第 48 點 B 段。
- `3a85a30`（CRLF 正規化 ＋ `.gitattributes` ＋ CRLF 守護測試）
  內容核對通過（審計官於乾淨 Linux clone 實測 `--verify` exit 0），
  但 CI Run 34013141925 failure，失敗項 CHECK 12——
  **原因是審計官在該批宣告不更新 AUDIT-LOG**。見第 48 點 E 段。
- `1491d33`（補上 2a-fix 被跳過的三處更新 ＋ B-46 至 B-52 共七項缺口登錄）
  已於 2026-09-06 由審計官核對通過：5 檔異動、零夾帶，
  獨立驗證四項全過（54 技能、16 項 CHECK、66 測試、`--verify` exit 0），
  CI badge 實測 `Verify - passing`。**指紋機制上線後第一次全綠。**
- `59cea4c`（`PRINCIPLES.md` §2.9 移除前複查原則 ＋ 五處落點 ＋
  B-50 自檢聲明不可豁免 ＋ B-52 §6.7 擴七類 ＋ B-53 至 B-61 登錄）
  已於 2026-09-06 由審計官核對通過：10 檔異動、零夾帶，
  獨立驗證四項全過，CI Run 34018344857 success。
- `a44cc6b`（B-62 規則層變更的模擬閘門 ＋ B-61 圍欄數進 §3.6
  ＋ B-63 移除硬編碼項數 ＋ B-64／B-65 閘門自身的兩個缺口）
  已於 2026-09-06 由審計官核對通過：8 檔異動、零夾帶，
  獨立驗證四項全過，CI Run 34037377798 success，
  (e) 段三項逐項複驗全符。
- `936b9af`（`scripts/build_prompt_evidence.py` 469 行 ＋ 其測試 370 行
  ＋ 批次規格範例 ＋ B-66 至 B-79 共 14 項登錄）
  已於 2026-09-07 由審計官核對通過：8 檔異動、零夾帶，
  獨立驗證四項全過（54 技能、16 項 CHECK、76 測試、`--verify` exit 0），
  CI Run 34108409728 success。**審計官親自重跑兩項反例注入，
  兩項守衛皆為活的**，見第 52 點 C 段。
- `b46cd5d`（B-72 `PRINCIPLES.md` §2.10 ＋ B-73 `.claude/rules/auditor-protocol.md` §6.1 第 19 項
  與 E21 ＋ B-77 同檔 §6.1-18 延伸句）已於 2026-09-07 由審計官核對通過：
  9 檔異動、零夾帶，刪除行僅 7 行且全部落在本節佔位符與 §5.4 舊條目，
  獨立驗證四項全過（54 技能、16 項 CHECK、76 測試、`--verify` exit 0），
  CI badge 實測 `Verify - passing`。
  **本批的證據區塊由 BPE 產生，是它的第一次實戰。**
  核對同輪發現 B-88（`.agents/rules/prompt-preflight.md` §3.4 的 E21 被空行斷開），
  並收斂三處與交接說明不符的數字，見第 53 點 D 段。
- `10f7e31`（§5.4 清理 ＋ B-80 至 B-88 九項登錄 ＋ 六項狀態同步
  ＋ 補打七個 `audited-*` tag ＋ `.claude/rules/auditor-protocol.md` §6.1 第 20 項
  與 E22 ＋ 同檔 §11.4 tag 判準 ＋ B-88 空行修復）**核對不通過**：
  8 檔異動、零夾帶，四項標準驗證全過（54 技能、16 項 CHECK、76 測試、
  `--verify` exit 0），CI success，七個 tag 補打正確且確實未打
  `audited-2d76958`。**但審計官把批次規格套用到 `b46cd5d` 後與本批逐檔比對，
  量出三處不一致**：`docs/TASKBOARD.md` 兩處日文字元、本節與第 53 點之間
  多一個空行。成因為執行者未依提示詞使用同一份規格套用。詳見第 54 點。
  依 `.claude/rules/auditor-protocol.md` §11.4，核對不通過者不打 tag。
- `9a09716`（2b-6：Governance Integrity Consolidation）已於 2026-09-11 由審計官核對通過：
  CHECK 17 規格重放 ＋ CHECK 18 tag 名實一致 ＋ `docs/batches/` 規格生命週期
  ＋ `role-boundaries.md` §6 唯一套用路徑 ＋ §6.1-20 命令補目標參數 ＋ §6.1-21
  規格進 repo ＋ selftest E23 ＋ preflight E23 ＋ §11.5／§11.6 ＋ B-90 至 B-92 登錄
  ＋ 錯誤分級 M1-M3/S1 ＋ BPE 輸出 sha256 綁定。4 檔異動、零夾帶，
  獨立驗證四項全過（54 技能、18 項 CHECK、93 測試、`--verify` exit 0），
  CI Run 34241773099 success。
- `4c6aee4`（Mechanical-Truth Migration：確立「機器產出衍生事實、提示詞引用機械來源、
  不將衍生數值複製為第二份 blocking truth」之單一權威模型；移除手寫總行數、固定行號、
  圍欄數與 post-apply 衍生值 blocking 要求；補齊 BPE 與 Batch Spec 規範，完成 B-86）
  已於 2026-09-11 由審計官核對通過：10 檔異動、零夾帶，獨立驗證四項全過（54 技能、18 項 CHECK、
  108 測試、`--verify` exit 0），CI success，`audited-4c6aee4` tag 已成功建立並推送。
- `0470df2`（B-90：Batch Spec 支援 `create_file` mode，移除 BOOTSTRAP 跳過例外與全庫限制，
  解除治理層最後一個 Exit blocker）已於 2026-09-11 執行完成：11 檔異動、零夾帶，
  獨立驗證四項全過（54 技能、18 項 CHECK、117 測試、`--verify` exit 0），CI success，**尚待審計官核對**，見 §5.4。
- `ff17ae5`（Governance Exit 安全與架構收斂：Batch Spec FILE 路徑安全約束與 Exit 審計；
  實作 canonical validate_repo_path，全面防堵路徑穿透、UNC 與 Windows 磁碟機路徑逃逸，
  完成治理層收斂）已於 2026-09-11 執行完成：14 檔異動、零夾帶，
  獨立驗證四項全過（54 技能、18 項 CHECK、122 測試、`--verify` exit 0），CI success，**尚待審計官核對**，見 §5.4。
- `a56c5c9`（Governance Exit Gate Parity 收斂：建立單一權威驗證入口 scripts/verify_all.py；
  完整納入 validate_skills、check_consistency、fingerprint --verify、scripts/tests、webapp-testing/tests 5 大 Correctness Gates；
  消除 Local 與 CI 驗證閘門分叉與 parity gap，完成 B-47）已於 2026-09-11 執行完成：10 檔異動、零夾帶，
  獨立驗證五項全過（54 技能、18 項 CHECK、126 passed、13 webapp passed、`--verify` exit 0），CI Run 34585789663 success，**尚待審計官核對**，見 §5.4。
- `94f75bc`（Transient Red Reduction：強化 CHECK 9 candidate 自引防護與實作 --as-if-committed 預演模式，完成 B-51）已於 2026-09-11 執行完成：9 檔異動、零夾帶，獨立驗證五項全過（54 技能、18 項 CHECK、128 passed、13 webapp passed、`--verify` exit 0），CI Run verify success，**尚待審計官核對**，見 §5.4。
- `8f9847e`（GitHub Actions 遠端健康權威與歷史失敗歸檔：建立 ADR-0020、SOP_14 §8、AUDIT-LOG CI 事故歸檔、README badge）已於 2026-09-11 執行完成：11 檔異動、零夾帶，獨立驗證五項全過，CI Run 34590592049 success，**尚待審計官核對**，見 §5.4。
- `60d5479`（Post-Governance Taskboard Reconciliation：全面對帳 TASKBOARD B 節 50 項待辦，標定已實作與封存項目，產出 Next Execution Queue 與儀表板）已於 2026-09-11 執行完成：6 檔異動、零夾帶，獨立驗證五項全過，CI Run 34593961967 success，**尚待審計官核對**，見 §5.4。
- `acc5890`（Final Governance Exit — Active Contract Cleanup：全面對齊 GOAL_SPEC 正常重構預設、mode-aware preflight、SOP 執行期可用性邊界、去除破壞性操作指引、E-03 轉待辦）已於 2026-09-11 執行完成：22 檔異動、零夾帶，獨立驗證五項全過，CI Run 34604144548 (Run #29) success，**尚待審計官核對**，見 §5.4。
- `9553994`（Final Governance Exit — Convergence Patch：確立 GOAL_SPEC 檔案自主性、preflight/selftest 模式感知徹底解耦、M3 自主修復閉環、B-36 回報通道轉移、SOP_14 治理減法）已於 2026-09-11 執行完成：17 檔異動、零夾帶，獨立驗證五項全過，CI Run 34606818571 (Run #30) success，**尚待審計官核對**，見 §5.4。
- `dc806e1`（Final Governance Exit — Reporting Contract Micro-Cleanup：消除 git-and-reporting.md 舊有口頭報告/行號/diff 規定與 B-36 之衝突，將舊規則退役為歷史留痕，對齊 SOP_14 階段審計文字）已於 2026-09-11 由審計官核對通過：8 檔異動、零夾帶，獨立驗證五項全過，CI Run 34608625314 (Run #31) success。
- `d4461d6`（Final Governance Exit — Auditor Contract & Audit-State SSOT Convergence：移除 auditor-protocol/selftest/preflight 舊有貼輸出/diff 要求；退役 mandatory audited tag 建立並確立 AUDIT-LOG、refactor-backlog §5.1 與 Actions 為 SSOT；B-12/B-91 轉可封存）已於 2026-09-11 由審計官核對通過：13 檔異動、零夾帶，獨立驗證五項全過，CI Run 34610027229 (Run #32) success。
- `1054cfc`（Fresh Claude Bootstrap Hardening：修復 cold-start 環境引導缺陷，落實 A4 targeted extraction、TASKBOARD next-work authority、AUDIT-LOG/§5.1 SSOT 與 E1→E2 state bridge 規則）已於 2026-09-12 執行完成：8 檔異動、零夾帶，獨立驗證五項全過，CI Run 34620190512 success。經宏觀審計官獨立審查，Machine PASS，但發現 3 項契約不一致（A1/§9.4 raw output 要求、refactor-backlog mutability 描述衝突、§5.4「尚未 commit」即刻失真），判定 NEEDS MICRO-FIX，後續由 4bf8611 修復完成。
- `4bf8611`（Fresh Claude Bootstrap — Final Contract Consistency Micro-Fix：修正 1054cfc 留下的三項契約不一致，落實 compact full-clone attestation、refactor-backlog mutability 邊界與 §5.4 machine-derived pending-audit contract）已於 2026-09-12 由宏觀審計官獨立核對通過：8 檔異動、零夾帶，獨立驗證五項全過，CI Run 34622753906 success（Architecture Health = GREEN, Bootstrap Governance = CLOSED）。
- `b9b997f`（E1 → E2 repo-visible state bridge）已於 2026-09-12 由宏觀審計官獨立核對通過：5 檔異動、零夾帶，獨立驗證五項全過，CI Run 34628553531 success。Macro Auditor 獨立核對通過（MACRO AUDIT = PASS, State Bridge Validated）。E1 PASS、E2 bootstrap mechanics 已驗證；使用者明確裁決正式開始 B-58 Content Architecture cleanup，先完成 Router / HANDOVER / Control Plane cleanup 並經 Macro Audit 後，再恢復 E2 / D-02。
- `91b43b2`（Audit Evidence Micro-Fix — Wrong GitHub Actions Run ID）已於 2026-09-12 由宏觀審計官獨立核對通過：5 檔異動、零夾帶，獨立驗證五項全過，CI Run 34669274290 success。Macro Auditor 獨立核對通過（MACRO AUDIT = PASS）。修正 b9b997f 錯誤之 Actions Run ID（34625299443 → 34628553531），確認 15444f5 維持 NEEDS MICRO-FIX 歷史。
- `568209e`（B-58 Content Architecture Phase 1 — Router Foundation）已於 2026-09-12 由宏觀審計官獨立核對通過：6 檔異動、零夾帶，獨立驗證五項全過，CI Run 34669753257 success。Macro Auditor 獨立核對通過（MACRO AUDIT = PASS）。於 PRINCIPLES.md §1 正式確立橫向非權威 Document Role: Router 及其核心不變式（不擁有事實、不參與權威層級、canonical source 優先、階層導覽無循環、優先重用既有檔案）。
- `8f48750`（B-58 Content Architecture Phase 2A — Historical Document Archive Foundation & Byte-Exact Legacy HANDOVER Snapshot）已於 2026-09-12 由宏觀審計官獨立核對通過：7 檔異動、零夾帶，獨立驗證五項全過，CI Run 34670189537 success。Macro Auditor 獨立核對通過（MACRO AUDIT = PASS）。建立 `docs/archive/handover/` 實體歸檔落點與 `HANDOVER-pre-router-568209e.md` 不可變歷史快照，active `docs/HANDOVER.md` 原封不動保留，Git blob SHA 完全相符（0a75b3bdc7ac68a06a882b63090c635862991bd3）。
- `addc388`（B-58 Content Architecture Phase 2B — Active HANDOVER → Project Router & Active Reverse-Reference Detachment）已於 2026-09-12 執行完成：9 檔異動、零夾帶，獨立驗證五項全過，CI Run 34670859204 success。經宏觀審計官獨立審查，Machine PASS，但發現 2 項 Router purity micro-fix（包含「五大 Gates」實作描述與跨層 deep-link agency-orchestrator），判定 NEEDS MICRO-FIX，由後續微修批次處置。
- `bd6cda3`（B-58 Content Architecture Phase 2B Micro-Fix — Project Router Purity）已於 2026-09-12 由宏觀審計官獨立核對通過：6 檔異動、零夾帶，獨立驗證五項全過，CI Run 34671244747 success。Macro Auditor 獨立核對通過（MACRO AUDIT = PASS）。addc388 的兩項 micro-fix 均已修復：Project Router 不再保存 gate count 等實作事實、不再 deep-link agency-orchestrator；archive snapshot blob 維持 0a75b3bdc7ac68a06a882b63090c635862991bd3；判定 Macro PASS。
- `276e11f`（B-58 Content Architecture Phase 3A — Claude Control Plane Identity & Routing Normalization）已於 2026-09-12 執行完成：9 檔異動、零夾帶，獨立驗證五項全過，CI Run 34677802062 success。經宏觀審計官獨立審查，Machine PASS，但發現 2 項 Claude Router purity micro-fix（包含四大審計維度/A–F與E1–E23等內部結構副本，以及重複宣告執行者行為禁令），判定 NEEDS MICRO-FIX，由後續微修批次處置。
- `34babd5`（B-58 Content Architecture Phase 3A Micro-Fix — Claude Router Purity）已於 2026-09-12 由宏觀審計官獨立核對通過：6 檔異動、零夾帶，獨立驗證五項全過，CI Run 34679360620 success。Macro Auditor 全面審查後判定 Macro PASS；276e11f 的兩項 blocking Router purity defects 已完成修復，.claude/README 剩餘之 selftest 描述降級為 non-blocking navigation cleanup。
- `529aab3`（B-58 Recovery R1 — Goal Lock & Pending-Audit Range Generalization）已於 2026-09-12 由宏觀審計官獨立核對通過：13 檔異動、零夾帶，獨立驗證五項全過，CI Run 34681229840 success。Macro Auditor 全面審查正式判定 Macro PASS；Agent Operating Objectives (A1–A5) 寫入治理原則，CHECK 8 改為 TASKBOARD metadata purity，CHECK 9 一般化 pending-audit range 支援任意數量 pending commits，補齊確定性負向測試。
- `76b5e92`（B-58 Recovery R2 — Control Plane Convergence & Exact-SHA Evidence Alignment）已於 2026-09-12 由宏觀審計官全面審查獨立核對通過：8 檔異動、零夾帶，本地 verify_all 5 Gates 全 PASS，GitHub Actions Run 34682808253 success。Macro Auditor 正式判定 Macro PASS。8 檔 authorized scope；確立雙控制平面分離非對稱架構；M2 移除 branch badge / README badge 作為 exact-SHA fallback（禁止作為 exact-SHA evidence）；git-and-reporting.md §2.5 確立 Remote Health 規範性契約；MISSION 完成定義對齊 scripts/verify_all.py；判定 Macro PASS。
- `afb5f2c`（B-58 Recovery R3 — Claude Protocol Slimming & Historical Extraction）已於 2026-09-12 由宏觀審計官全面審查獨立核對通過：9 檔異動、零夾帶，本地 verify_all 5 Gates 全 PASS，GitHub Actions Run 34684595656 success。Macro Auditor 正式判定 Macro PASS。9 檔 authorized scope；active auditor-protocol.md 大幅縮減 hot-path active context（400 行/25736 bytes，瘦身 50.7%），歷史事故與長篇散文移出至 docs/archive/claude-control-plane/；保留所有現行規範語意與 48 個數值標題骨架；auditor-selftest.md 完全未變；不可變歷史快照 blob exact match (976ce3b73fc2e09ee26e3e5753d1dad9d54b5ff6)；archive navigation valid；判定 Macro PASS。
- `0fd655d`（B-58 Recovery R4 — SOP Layer Purification & SOP_06 De-overloading）已於 2026-09-12 由宏觀審計官全面審查獨立核對通過：10 檔 authorized scope；SOP 層 Information Architecture 對齊並保留 Runtime Availability 邊界；active SOP_06 成功收斂為可重複執行的 Runtime Handover & Service Operations SOP；舊版 SOP_06 歷史快照 blob exact match (d862a54304b58d93a22f1990506a976522e56155)；archive Router 與 ARCHIVE-INDEX routing 正常；exact-SHA Actions Run 34685685456 (status completed, conclusion success)；判定 Macro PASS。
- `a7febb0`（B-58 Recovery R5A Micro-Fix — Skill Path Portability Cleanup）已於 2026-09-12 由宏觀審計官獨立核對通過：8 檔 authorized scope；target Skills（setup-hhai-skills、skill-evolution-governor、agency-orchestrator）殘留之 machine-specific local paths 全數移除，repo-internal links 已全數改為 portable relative paths 並由機器驗證 100% 存在；exact-SHA Actions Run 34688295360 (status completed, conclusion success)；判定 Macro PASS。
- `3614d69`（B-58 Recovery R5 Finalization — Global Skill Boundary Residual Audit & Bounded Self-Repair）已於 2026-09-12 由宏觀審計官全面審查獨立核對通過：14 檔 authorized scope；全庫 active Skills content architecture residual scan 完成；無 project-state / governance authority / stale ghost runtime / machine-specific path / false compliance self-attestation 等 residual；bounded repairs 僅處理明確 local material defects；無架構裁決殘留且未建立 R5B；exact-SHA Actions Run 34692108678 (status completed, conclusion success)；R5 正式結案；判定 Macro PASS。
- `622e840`（B-58 Recovery R6 Micro-Fix — Narrow False-DLP Guard Exemption）已於 2026-09-12 由宏觀審計官全面審查獨立核對通過：7 檔 authorized scope；移除 validate_skills.py 中 EXEMPT_DLP_LOCATIONS 整檔豁免，實作 narrow contextual distinction；naked false DLP self-attestation 嚴格 FAIL，合法否定/歷史說明 PASS；原兩個豁免目標（governor/setup）補齊確定性正向、負向與反例單元測試；無新 CHECK，無技能語意異動；exact-SHA Actions Run 34693575178 (status completed, conclusion success)；R6 正式結案；B-58 Content Architecture 達成 FINAL MACRO PASS，正式解除 D-02 之 TEMPORARILY HELD。
- `3b3e7fa`（B-58 Final Macro Audit State Closure & D-02 Release）已於 2026-09-13 由宏觀審計官全面審查獨立核對通過：5 檔 authorized scope；同步 622e840 Macro PASS、R6 CLOSED、B-58 FINAL MACRO PASS 裁決；TASKBOARD B-58 標記已完成；D-02 解除 TEMPORARILY HELD 改標 READY；Formal Production Handoff 判定 PASS；exact-SHA Actions Run 34694285132 (status completed, conclusion success)；判定 Macro PASS。
- `17216b5`（Pre-Handoff Router / Anti-Loop Hardening）已於 2026-09-13 由外部審計官全面審查獨立核對通過：涵蓋 3b3e7fa..17216b5 完整 pending range（含 b1e8804、4fce039、a6c74bf、17216b5）；Router purity 與確定性續行；M1/M2/M3 自主閉環與 S1-only 升級；TASKBOARD.NEXT_WORK 單一指標與 CHECK 8 指標完整性；CHECK 12 pending-range 相容性模型；Antigravity active rule loadability 守衛；E1/E2/E3 驗證解除手寫衍生值錨定；執行者範疇與 incidental finding 邊界收斂；exact-SHA Actions Run 34743264746 (status completed, conclusion success)；判定 Macro PASS。
- `a8d6575`（B-93 Verification Integrity / False-Green Fail-Closed Hardening）已於 2026-09-13 由外部審計官全面審查獨立核對通過：exact-SHA GitHub Actions Run 34754917032 (status completed, conclusion success)；CHECK 1–18 = 18 PASS / 0 FAIL；scripts tests = 199 passed、webapp tests = 13 passed；canonical verification = ALL 5 GATES PASSED；CHECK 10 exact subsection identity 與 explicit target identity / archive substitution repair 通過；direct production canaries 通過；active-rule E16 contract sync 通過；TASKBOARD B-53 truth sync 通過；零 B-01 實作；B-93 Verification Integrity / False-Green Fail-Closed Hardening 正式通過並結案（B-93 CLOSED）；判定 Macro PASS。
- `3e47f44`（Antigravity Runtime Rule Loadability / UI Freshness Reconciliation）已於 2026-09-13 由外部審計官全面審查獨立核對通過：exact-SHA GitHub Actions Run 34756394041 (status completed, conclusion success)；prompt-preflight.md committed chars=9973，UI reload 後確認顯示 9973/12000，stale buffer 根因確認；B-94 Runtime Rule Loadability / UI Freshness Reconciliation 正式通過並結案（B-94 CLOSED）；判定 Macro PASS。
- `c51ee6b`（B-95 Material Finding → TASKBOARD Promotion Contract）已於 2026-09-13 由外部審計官全面審查獨立核對通過：exact-SHA GitHub Actions Run 34757466644 (status completed, conclusion success)；verification gates 5/5 PASS；Material Finding 定義、四種 disposition 狀態、當輪登錄最小 state-sync 提示詞、無第二 queue、blocking/non-blocking 路由等契約成立；D4 EVERY_ROUND 自檢成立；prompt-preflight FINDING_DISPOSITION 機械檢查契約成立且字元數精簡至 8860/9500；C-06 登錄為待裁決；B-01 零實作；B-95 Material Finding → TASKBOARD Promotion Contract 正式通過並結案（B-95 CLOSED）；判定 Macro PASS。
- `dac5921`（A-06 Machine-Generated Rule Traceability）已於 2026-09-13 由外部審計官全面審查獨立核對通過：exact-SHA Actions Run 34762339410 (status completed, conclusion success)；canonical verification = ALL 5 GATES PASSED；stale ADR path repair PASS；fresh != valid fail-closed contract PASS；negative canary PASS；valid fixture PASS；UNRESOLVED_HISTORICAL advisory behavior PASS；fenced code heading attribution PASS；blocking status = 0；B-01 零實作；A-06 正式結案；判定 Macro PASS。
- `c53de3b`（A-14 Executor Prompt Preflight Enforcement）已於 2026-09-13 由外部審計官全面審查獨立核對通過：exact-SHA Actions Run 34763116512 (status completed, conclusion success)；canonical verification = ALL 5 GATES PASSED；Prompt Manifest validator（scripts/validate_prompt_manifest.py）實作與單元測試全數通過；malformed-manifest 與 full-prompt contradiction 兩次 runtime canaries 均成功阻擋且零 mutation；A-14 正式結案；判定 Macro PASS。
- `e377d51`（A-14 External Macro PASS / Runtime Canary State Closure）已於 2026-09-13 由外部審計官全面審查獨立核對通過：exact-SHA Actions Run 34764485489 (status completed, conclusion success)；canonical verification = ALL 5 GATES PASSED；異動僅限 5 份狀態與證據檔案；A-14 正式結案；NEXT_WORK 暫停於 B-28；B-01 零實作；判定 Macro PASS。
- `a3201f3`（B-87 Phase 1 Comprehensive Taskboard Truth Reconciliation）已於 2026-09-13 執行完成：5 檔異動、零夾帶，獨立驗證五項全過，CI Run 34765468962 success，Machine PASS / Macro NEEDS BOUNDED MICRO-FIX。
- `b2256fd`（B-87 Phase 1 Bounded Micro-Fix & Closure）已於 2026-09-13 由外部審計官全面審查獨立核對通過：5 檔 authorized scope，本地 verify_all 5 Gates 全 PASS，GitHub Actions exact-SHA Run 34768119758 success。B-70 正確恢復為 genuine pending；B-57 stale B-71 引用修復；B-87 Phase 1 reconciliation accepted；generic path-existence CHECK proposal 因 false-green risk 明確 rejected / superseded；B-87 結案處置判定為可封存；B-01 零實作；判定 Macro PASS (ACCEPT ALL)。
- `3665516`（B-31 Tracked-Scope Bounded Micro-Fix & Closure）已於 2026-09-14 由外部審計官全面審查獨立核對通過：7 檔 authorized scope，本地 verify_all 5 Gates 全 PASS，GitHub Actions exact-SHA Run 34792068482 success。CHECK 19 改採 Git tracked inventory 為單一權威來源，.gitattributes BOM negative canary FAIL/PASS、untracked/ignored non-authority、fail-closed 完整覆蓋；B-88 PASS；B-89 PASS；B-87 already CLOSED-AS-SUPERSEDED；three non-behavioral verifier reporting strings are synchronized by the following closure batch；B-01 零實作；判定 Macro PASS (ACCEPT ALL)。
- `3023267`（B-31/B-88/B-89 Closure & Reporting Truth Sync）已於 2026-09-14 由外部審計官全面審查獨立核對通過：4 檔 authorized scope，本地 verify_all 5 Gates 全 PASS，GitHub Actions exact-SHA Run 34794878832 success。B-31/B-88/B-89 正式 CLOSED；三處 non-behavioral verifier-reporting truth sync accepted；前一輪 paired test assertion S1 正確 fail-closed 並由 S1 resolution 修復；TASKBOARD.NEXT_WORK 推進至 B-41 後經使用者裁決校正至 B-68；B-01 零實作；判定 Macro PASS (ACCEPT ALL)。
- `a41166e`（B-68 Dependency Closure Phase 1 External Macro PASS）已於 2026-09-14 由外部審計官全面審查獨立核對通過：3 檔 authorized scope，本地 verify_all 5 Gates 全 PASS，GitHub Actions exact-SHA Run 34838936881 success。B-67 output contract 恢復與 main integration guard 驗證通過；B-68 Final malformed-scope Runtime Canary PASS（C1 dependency scripts/build_prompt_evidence.py UPDATE 漏列時由 production impact_scan check 精確攔截 exit != 0，S1 DEPENDENCY_SCOPE_MISSING，零 mutation，worktree clean）；B-68 正式 CLOSED；B-41/B-01 零實作（NOT STARTED）；判定 Macro PASS (ACCEPT ALL)。
- `23dd01f`（B-68 Final Macro Closure & B-96 Specification Registration）已於 2026-09-14 由外部審計官全面審查獨立核對通過：5 檔 authorized scope，本地 verify_all 5 Gates 全 PASS，GitHub Actions exact-SHA Run 34843106839 success。B-68 Final Macro Closure state sync accepted；B-96 Specification Registration accepted；B-68 正式 CLOSED；B-96 REGISTERED / NOT IMPLEMENTED；NEXT_WORK 推進至 B-41；B-41 / B-01 保持待辦零實作（NOT STARTED）；判定 Macro PASS (ACCEPT ALL)。
- `9b698de`（B-41 Slim Bootstrap Router Landing）已於 2026-09-14 由外部審計官全面審查獨立核對通過：6 檔 authorized scope，本地 verify_all 5 Gates 全 PASS，GitHub Actions exact-SHA Run 34852512530 success。B-41 Slim Bootstrap Router bounded landing accepted；.claude/README.md 正式作為 repo-owned canonical slim bootstrap / recovery router；docs/HANDOVER.md 保持 supporting router / VERIFY_ONLY；full mirror superseded；no .claude/slim-bootstrap.md；no workspace/global GEMINI creation；no fake UI CI CHECK；dynamic state remains runtime-routed；B-69 false-zero evidence recorded as existing / non-blocking；B-01 零實作；使用者明確要求新增 B-97 release gate；B-41 正式 CLOSED；B-97 登錄待辦；NEXT_WORK 推進至 B-97；B-01 保持待辦零實作（NOT STARTED）；判定 Macro PASS (ACCEPT ALL)。
- `cfdebc2`（B-41 Final Closure and B-97 Release Audit Registration）已於 2026-09-16 由 GPT 代理審查官（使用者授權）獨立核對通過：5 檔 authorized scope，本地 verify_all 5 Gates 全 PASS，GitHub Actions exact-SHA Run 34860687555 success。B-41 closure 與 B-97 registration state sync accepted；B-41 CLOSED；B-97 REGISTERED / audit 尚未開始；B-01 NOT STARTED；A1 使用 user-authorized equivalent evidence：GitHub API + Executor full-clone cross-check；no blocking finding in audited commit；判定 Macro PASS (ACCEPT ALL)。
- `24f7896`（cfdebc2 Macro PASS State Sync, B-98 Security Finding Registration & B-75 Context Economy Scope Refinement）已於 2026-09-16 由 GPT 代理審查官（使用者授權）獨立核對通過：5 檔 authorized scope，本地 verify_all 5 Gates 全 PASS，GitHub Actions exact-SHA Run 34998074551 success。cfdebc audit-state sync accepted；B-98 registration accepted；B-75 refinement accepted；B-98 / B-75 保持待辦、零實作；NEXT_WORK 保持 B-97；B-01 NOT STARTED；B-97 formal audit 尚未開始；no new material finding；判定 Macro PASS (ACCEPT ALL)。
- `e8fdb74`（24f7896 Macro PASS State Sync）已於 2026-09-16 由 GPT 代理審查官（使用者授權）獨立核對通過：5 檔 authorized scope，本地 verify_all 5 Gates 全 PASS，GitHub Actions exact-SHA Run 34999645394 success。24f7896 Macro PASS State Sync accepted；state/evidence-only closure accepted；TASKBOARD unchanged in e8fdb747 commit；canonical verification passed；FINDING_DISPOSITION = NONE for e8fdb747 itself；判定 Macro PASS (ACCEPT ALL)。
- `09d2ccb`（B-99 Qualification-Based Macro Auditor & Repo-Visible Handoff 及 A1 Equivalent Contract Consistency Repair）已於 2026-09-16 由 GPT 代理審查官（使用者授權）全面審查獨立核對通過：涵蓋 e8fdb74..09d2ccb 完整 pending range（含 a101ed8 初審 HOLD 與 09d2ccb bounded repair）；A1 EQUIVALENT 查證通過；exact-SHA Actions Run 35048408214 (status completed, conclusion success)；B-99 正式結案（CLOSED / Macro PASS）。
- `eceda26`（B-99 Macro PASS Closure & B-97 Pointer Sync 及 B-97 Phase 1 唯讀發布審計）已於 2026-09-16 由 GPT 代理審查官（使用者授權）全面審查獨立核對通過：5 檔 authorized scope，本地 verify_all 5 Gates 全 PASS，GitHub Actions exact-SHA Run 35049350295 success。B-99 state closure accepted；B-97 Phase 1 READ_ONLY 全庫審計完成；41 筆 active-lifecycle rows 全部完成處置；B-01 target readiness PASS；上游 trigger 重新評估無 blocker；C-06 remote truth 已確認並維持 USER_DECISION_NONBLOCKING；實質發現依 B-95 處置完畢；B-01 保持零實作（NOT STARTED）；判定 PRE-B01 RELEASE STATUS = PASS。
- `76cfe7b`（B-97 PRE-B01 Release PASS State Closure）已於 2026-09-16 由 GPT 代理審查官（使用者授權）全面審查獨立核對通過：5 檔 authorized scope，本地 verify_all 5 Gates 全 PASS，GitHub Actions exact-SHA Run 35051382469 success。B-97 PRE-B01 Release PASS State Closure accepted；MACRO AUDIT = PASS，ACCEPT STATUS = ACCEPT ALL，FINDING_DISPOSITION = NONE；PRE-B01 RELEASE STATUS = PASS — FINALIZED；B-97 正式 CLOSED；B-01 AUTHORIZED TO START。
- `85d9a3a`（B-01 ADR-0002/0004/0010 分層搬移及 Active-Contract 語意優先序與 Shell 邊界修復）已於 2026-09-16 由 GPT 代理審查官（使用者授權）全面審查獨立核對通過：涵蓋 76cfe7b..85d9a3a 完整 pending range（含 b2b5d1d 初審 HOLD 與 85d9a3a bounded repair）；A1 EQUIVALENT 查證通過；exact-SHA Actions Run 35054093786 (status completed, conclusion success)；B-01 正式結案（CLOSED / Macro PASS）。
- `c73dd28`（B-01 Macro PASS Closure and E-03 Pointer Sync）已於 2026-09-16 由 GPT 代理審查官（使用者授權）獨立核對通過：5 檔 authorized scope，本地 verify_all 5 Gates 全 PASS，GitHub Actions exact-SHA Run 35054817604 success。B-01 closure state sync accepted；E-03 推進至 NEXT_WORK；E-03 Phase 1 + Phase 1B READ_ONLY evidence review completed（PASS / corrected inventory accepted），授權進入 Phase 2；判定 Macro PASS (ACCEPT ALL)。
- `c2df1b0`（E-03 Phase 2 Wave 1A Shared Pure Primitives Foundation）已於 2026-09-16 由 GPT 代理審查官（使用者授權）獨立核對通過：9 檔 authorized scope；A1 EQUIVALENT 查證通過；建立 shared/dlpSanitizer.js、shared/dlpSanitizer.d.ts、shared/atomicFs.js；零第三方 runtime dependencies；canonical verification 5 Gates 全數通過；exact-SHA Actions CI success；判定 Macro PASS (ACCEPT ALL)。
- `f522148`（E-03 Complete Channel Gateway Decision Fidelity）已於 2026-09-16 由 GPT 代理審查官（使用者授權）全面審查獨立核對通過：涵蓋 c2df1b0..f522148 完整 pending range（含 2830c7f 初審 HOLD 與 f522148 bounded repair）；A1 EQUIVALENT 查證通過；ADR-0022 決策保真度 F1（D26 12 項子契約）與 F2（D18 LINE 推播額度影響）完全解決；ADR-0022 CHANNEL GATEWAY ARCHITECTURE PERSISTENCE = FINALIZED；exact-SHA Actions Verify Run 35097747792 completed / success；MACRO AUDIT = PASS，ACCEPT STATUS = ACCEPT ALL，FINDING_DISPOSITION = NONE。
- `7d379f6`（E-03 Enforce Channel and Account Reply Boundaries）已於 2026-09-16 由 GPT 代理審查官（使用者授權）全面審查獨立核對通過：涵蓋 f522148..7d379f6 完整 pending range（含 278d142 初審 HOLD 與 7d379f6 bounded domain invariant repair）；A1 EQUIVALENT 查證通過；F1（AccountRegistry 通道邊界強制）與 F2（接收帳號回覆強綁定）完全解決；Wave 2A = ACCEPTED；exact-SHA Actions Verify Run 35101712841 completed / success；MACRO AUDIT = PASS，ACCEPT STATUS = ACCEPT ALL，FINDING_DISPOSITION = NONE。
- `fe6baba`（E-03 Channel Gateway Wave 2B Pure Account Switch Orchestration）已於 2026-09-16 由 GPT 代理審查官（使用者授權）全面審查獨立核對通過：10 檔 authorized scope；A1 EQUIVALENT 查證通過；實作 AccountSwitchCoordinator，嚴格強制註冊表與通道控制器邊界一致（CHANNEL_CONTROL_MISMATCH）；實作 D26 切換即接管與原子式前置檢驗；異帳號切換 A→B 接管捨棄 A claimed 訊息、discardQueuedForAccount 捨棄 A queued 訊息並保留 B queued 訊息；同帳號選擇 A→A 接管但保留 queued 訊息；無前一活躍帳號 null→B 成功啟用並接管；新增 18 項 canonical Node 測試全數通過（40/40 tests PASS）；Python CI 橋接測試 6 passed；exact-SHA Actions Verify Run 35103490957 completed / success；MACRO AUDIT = PASS，ACCEPT STATUS = ACCEPT ALL，FINDING_DISPOSITION = NONE。
- `aa0977f`（E-03 Channel Gateway Wave 2C Data Location Config Contract）已於 2026-09-16 由 GPT 代理審查官（使用者授權）全面審查獨立核對通過：10 檔 authorized scope；A1 EQUIVALENT 查證通過；實作 validateResolvedDataLocationConfig 與 DATA_LOCATION_SCHEMA_VERSION=1；嚴格綱要驗證僅允許 schemaVersion 與 dataLocations；路徑驗證強制 4 個單例目錄與 protectedRoots 均為非空白絕對路徑（相容 Windows 與 POSIX）；建立無機敏範本 config.example.json；零第三方依賴；canonical verification 5 Gates 全數通過（20 checks PASS，317 unit PASS，13 webapp PASS）；exact-SHA Actions Verify Run 35105625352 completed / success；MACRO AUDIT = PASS，ACCEPT STATUS = ACCEPT ALL，FINDING_DISPOSITION = NONE；new accepted checkpoint = aa0977f；protectedRoots operational minimum coverage 依決策留待 D19-D21 安全驗收要求。
- `eac38683`（E-03 Channel Gateway Wave 2D Repo-External Config Loader + Startup Path Validation）已於 2026-09-16 由 GPT 代理審查官（使用者授權）全面審查獨立核對通過：9 檔 authorized scope；A1 EQUIVALENT 查證通過；實作 local-config-loader.js（loadDataLocationConfigFromFile、validateStartupDataLocations）；強制 repoRoot 外部限制（名義路徑與 canonical realpath 雙重阻擋，拒絕指向 repo 內部之 symlink）；嚴格 JSON 解析與 Wave 2C 綱要驗證；啟動前驗證 4 個單例資料目錄存在且具備讀寫權限；protectedRoots 至少 1 個目錄且具備讀取權限；零自動建立目錄（zero mkdirSync）；回傳 realpathSync 正規化路徑物件，不修改原輸入；新增 21 項 canonical Node 測試（全庫 77 tests PASS / 2 skipped）；Python CI 橋接測試全數 PASS（8 passed）；exact-SHA Actions Verify Run 35107752002 completed / success；MACRO AUDIT = PASS，ACCEPT STATUS = ACCEPT ALL，FINDING_DISPOSITION = NONE；new accepted checkpoint = eac38683。
- `994c455`（E-03 Channel Gateway Wave 2E Atomic Durable State Store Foundation & Lossless JSON Bounded Repair）已於 2026-09-17 由 GPT 代理審查官（使用者授權）全面審查獨立核對通過：涵蓋 eac38683..994c455 完整 pending range（共 2 commits：0959d0a 初審 Machine PASS / Macro HOLD，F1 為 Lossless JSON own-property validation incomplete，由 994c455d435bda6c72138706f8f16faa7c036776 徹底解決）；A1 EQUIVALENT 查證通過；exact-SHA Actions Verify Run 35158545662 completed / success（20 checks PASS，319 unit tests PASS，13 webapp tests PASS，5 Gates PASS）；Wave 2E = ACCEPTED；new accepted checkpoint = 994c455。
- `750eaeb`（E-03 Validate Live Metadata Before Snapshot Clone）已於 2026-09-17 由 GPT 代理審查官（使用者授權）全面審查獨立核對通過：涵蓋 994c455..750eaeb 完整 pending range（共 2 commits：e1f06fd 初審 Machine PASS / Macro HOLD，F1 為 live metadata validated after lossy clone，由 750eaeb160eae2b4f29801ba04d53d1452a59275 徹底解決）；A1 EQUIVALENT 查證通過；exact-SHA Actions Verify Run 35170928666 completed / success（20 checks PASS，320 unit PASS，13 webapp PASS，5 Gates PASS）；Wave 2F = ACCEPTED；new accepted checkpoint = 750eaeb。
- `b15d5bf`（E-03 Channel Gateway Wave 2G Multi-Channel Durable State Persistence Bridge & T1 Windows node:sqlite Technical Spike Review）已於 2026-09-17 由 GPT 代理審查官（使用者授權）全面審查獨立核對通過：涵蓋 750eaeb..b15d5bf 完整 pending range；A1 EQUIVALENT 查證通過；Wave 2G = ACCEPTED；T1 Windows node:sqlite Technical Spike = GO（D28 prerequisite satisfied，V1-V6 + V8 PASS，V7 reference partial / R3 undecided；F1 process protocol deviation non-blocking / added to B-98；F2 V7 not approval）；new accepted checkpoint = b15d5bf。

### 5.2 待辦

> **待辦一律見 `docs/TASKBOARD.md`。**
> 本節刻意不保留清單副本——兩份清單在同一層級競爭時，
> 副本必然漂移（2026-09-02 曾發生 §5.2 列七項、看板列 41 項的落差）。
>
> 職責分工：**交接區回答「現在在哪」，看板回答「還有什麼」。**

### 5.3 待使用者裁決

| # | 事項 | 選項與建議 |
|---|---|---|
| 1 | ~~**Port 3000 三方衝突**~~ **已於 2026-09-06 裁決** | 裁決結果見 `docs/TASKBOARD.md` C-01。實測為 11 個 port 而非三方衝突；以 ADR-0017 為準，處置範圍由兩處擴大為七處；playwright 掃描清單改為「明確指定目標 port 而非自動掃描」。執行排批 4 |
| 2 | ~~**`SOP_02` 清歷史規定違反第 1 層規則**~~ **已於 2026-09-06 裁決** | 裁決結果見 `docs/TASKBOARD.md` C-02。採甲案：不得 force push；已推送憑證視為永久洩漏，處置為撤銷與輪換；清理歷史僅由使用者本人執行。執行排批 4 |
| 3 | ~~**ADR-0013 處置**~~ **已於 2026-09-06 裁決** | 裁決結果見 `docs/TASKBOARD.md` C-03。採甲案逐節處置：§1／§2ABD／§7 棄用；§2C BOM 偵測實作為新 CHECK；§3 搬進 `role-boundaries.md`；§4／§5 凍結待 E-03；§6 獨立為 B-32。執行排批 4 |
| 4 | **是否將 GitHub Verify 升級為 main 的 preventive required check** | 待使用者裁決（見 `docs/TASKBOARD.md` C-06）。目前 required status checks 為 off，可選：A. 維持 current direct-push + post-push Verify；B. Require PR + Verify before merge。Auditor 建議：若要求任何不合法 rule 絕不曾進 main 則選 B。本項為 non-blocking user decision，不阻塞 B-95 |

### 5.4 進行中／等待回報

> **本節為反映當前事實之可變狀態投影（mutable interface），只保留現行狀態。**
> 每次更新時，被取代的陳舊條目（stale state）一律替換或移除，不得把過期狀態堆在 §5 作為「歷史」。
> 歷史理由與事實屬於留痕層（append-only），落點為正文編號項目，不是本節。

- **尚待審計判準（Pending-Audit Contract）**：待審計範圍必須在讀取時以確定性指令即時導出（machine-derived），不在本檔持久化當前 HEAD、commit range、候選 hash 或 commit/push 等易失真狀態，且不設定固定 commit-count 數量上限。
  - actual HEAD = `git rev-parse HEAD`
  - checkpoint = §5.1 第一行記載之「上次核對通過的 HEAD（last audited checkpoint）」
  - 若 `HEAD == checkpoint` → 無尚待宏觀審計之 commit（no pending macro-audit commit）
  - 若 `HEAD != checkpoint` → `checkpoint..HEAD` 即為尚待宏觀審計之 commit range（包含 checkpoint 之後至當前 HEAD 間所有 pending / repair commits，不因 commit 數量直接判定 FAIL）
- **交接與審計生命週期（Handoff & Audit Lifecycle）**：
  - Formal Production Handoff 已完成（D-01 / D-02 PASS）。
  - Pre-Handoff Router / Anti-Loop Hardening 已完成。
  - Verification Integrity / False-Green Fail-Closed Hardening 已完成 External Macro Audit 並正式 CLOSED。
  - Runtime Rule Freshness Reconciliation 已完成 External Macro Audit 並正式 CLOSED。
  - Material Finding → TASKBOARD Promotion Contract 已完成 External Macro Audit 並正式 CLOSED。
  - generated rule traceability External Macro PASS / CLOSED。
  - Executor prompt-preflight machine enforcement External Macro PASS / CLOSED。
  - Prompt Manifest runtime interception 已由兩種 malformed-prompt canary 實證。
  - B-31 / B-88 / B-89 CLOSED。
  - B-68 Dependency Closure External Macro PASS / CLOSED。
  - malformed-scope Runtime Canary PASS。
  - session-local User Prompt Compiler Mode specification 已登錄於 TASKBOARD，尚未實作。
  - B-41 Slim Bootstrap / Runtime Reconciliation External Macro PASS / CLOSED。
  - B-99 Qualification-Based Macro Auditor & Repo-Visible Handoff（CLOSED / MACRO PASS）。
  - B-97 Pre-B01 Comprehensive Release Audit 已完成（CLOSED / PRE-B01 RELEASE PASS）。
  - B-01 ADR-0002／0004／0010 分層搬移及 Active-Contract 語意修復已完成（CLOSED / MACRO PASS）。
  - E-03 Runtime 執行層架構推進（IN PROGRESS）：Wave 2G = MACRO PASS / ACCEPTED；SQLite Governance Landing 初審候選 90dc71c 經審查為 Machine PASS / Macro HOLD（BOUNDED REPAIR REQUIRED，CURRENT E-03）；F1 為 ADR-0023 決策識別碼語意偏離；現執行 R2/R3 決策路徑微修；R2 = reply-result uncertainty handling（USER DECISION PENDING）；R3 = local API form（USER DECISION PENDING）；accepted checkpoint 保持 b15d5bf；next route: governance landing repair → T3/T17 → T6；Gateway live 整合尚未開始（NOT STARTED）；B-98 / B-30 / B-33 / F-05 維持開啟狀態於既定前置邊界。
  - C-06 維持待使用者裁決（USER_DECISION_NONBLOCKING，遠端 ruleset 與 required checks 現況已確認）。
  - B-28 / B-29 上游 trigger 重新評估完成，無 B-01 blocker，維持 DEFERRED_BY_USER / POST_B01。
  - B-54 保持待辦（POST_B01 / NONBLOCKING，SOP_12 機器專屬路徑 concrete example 已登錄）。
  - B-98 / B-75 保持待辦、零實作 (POST_B01 / NONBLOCKING / NOT IMPLEMENTED)。
  - B-69 保持待辦 (PENDING NON-BLOCKING)。
  - Production routing ready。
  - 當前與下一步工作任務權威（Current / next work authority）仍只由 `docs/TASKBOARD.md` 的 `**NEXT_WORK**` pointer 保存與導航，交接區不複製 task ID 或待辦佇列。
  - 待使用者裁決事項依 §5.3。
  - Antigravity IDE runtime rule UI freshness 仍需由 runtime reload / fresh session 保證，不能由 CI 直接證明。
- **待使用者裁決事項**：有（依 §5.3，包含 GitHub main preventive required-check enforcement 決策，屬 non-blocking user decision）。
- **剩餘工作權威**：以 `docs/TASKBOARD.md` 為唯一 remaining-work authority。

56. **Post-Governance Taskboard Reconciliation（治理收斂後看板全面對帳）**（2026-09-11）
    - **背景**：在 Governance Exit 7/7 完成、ADR-0020 確立 Remote Health Authority、歷史 Actions failure runs 全數清理後，為避免未來 Agent 執行已被取代或已完成的舊治理待辦，展開一次性 repo-to-taskboard 對帳。
    - **對帳結果**：審查 B 節未完成 50 項，分類為 ALREADY_IMPLEMENTED (9 項)、SUPERSEDED (9 項)、DEFER_POST_MAIN (28 項)、BLOCKED_DEPENDENCY (3 項)、BLOCKED_USER_AUTH (1 項)。更新 18 個項目的狀態為「已完成」或「可封存」，並留存 supersede 理由。
    - **佇列產出**：機械導出 NEXT EXECUTION QUEUE，確立「1. 正式交接驗證 D → 2. 主遷移 E → 3. 相依項 → 4. 演進 F → 5. 主重構後優化 → 6. 低優先探索」之推進順序，治理待辦不再阻擋主重構。

57. **Post-Governance Taskboard Truth Correction（看板規劃真實性修正）**（2026-09-11）
    - **背景**：宏觀審計官與執行者依據原 acceptance criteria 重新核對，修正上一輪 TASKBOARD RECONCILIATION 將「後續機制涵蓋」誤等同於「原需求已實作」的分類失真問題。
    - **修訂內容**：
      - B-12：恢復為待辦（DEFER_POST_MAIN）。CHECK 18 為 tag identity integrity，原 lag detection 尚未實作；因遠端健康權威已轉移至 GitHub Actions，不阻擋主重構。
      - B-57：維持可封存（SUPERSEDED）。澄清原五項 acceptance 並未全部達成（B-53/B-54/B-71 仍有殘留風險），本項係被後續 Governance Exit 7/7 標準取代，絕不假造已全部完成。
      - B-76：更正為可封存（SUPERSEDED）。`scripts/audit_verify.py` 實體檔案未實作，核心需求已由 canonical `verify_all.py` 與 GitHub 遠端工作流取代。
      - B-78：恢復為待辦（DEFER_POST_MAIN）。`scripts/apply_batch.py` 未實作且目前仍依賴一次性 apply 腳本，由 CHECK 17 提供 correctness containment，延後主重構後評估。
      - B-80 / B-81：維持可封存（SUPERSEDED），但更正「BPE 制度廢除」之敘述。BPE（`build_prompt_evidence.py`）依然保留為 Batch Spec 解析與模擬工具，廢除的僅是 LLM 手寫衍生值作為 blocking truth。
      - B-60：維持可封存（SUPERSEDED），更正備註說明 17–24 配置表已停止作為排程，未來若 post-main 新增 CHECK 應從 `check_consistency.py` 機器動態導出可用 ID。
      - B-85：維持已完成（ALREADY_IMPLEMENTED），澄清解決的是「散文不得充當 exact mechanical truth」，不與 B-78 通用套用腳本混淆。
58. **Final Governance Exit — Active Contract Cleanup（治理層退出前現行契約全面對齊）**（2026-09-11）
    - **背景**：治理層退出前最後一批 active-contract cleanup。目的在於將歷史累積、仍會被 Agent 視為「現行可執行指令」的過時治理與 SOP 契約全面對齊 Governance Exit 架構，消除高 Token、高 roundtrip、雙重權威與過時 SOP 約束，讓後續 D/E 主線可真正以 GOAL_SPEC 自主推進。
    - **對齊成果**：
      - **GOAL_SPEC 正常重構預設**：確立 GOAL_SPEC 為正常重構預設模式，Auditor 提供 Goal、Scope、Invariants、Criteria 與 Gates，Executor 自主實作除錯，不強制要求 Batch Spec、BPE、exact anchors 與手寫數值；EXACT_SPEC 僅保留於 byte-exact 與治理規範調整；未宣告模式視為 `PROMPT STRUCTURE ERROR`。
      - **Mode-Aware Preflight & Selftest**：更新 `.agents/rules/prompt-preflight.md`、`role-boundaries.md`、`auditor-protocol.md` 與 `handover-selftest.md`，支援模式感知檢查，消除虛假 Batch Spec 要求。
      - **SOP 執行期可用性邊界（Runtime Availability Boundary）**：於 `SOP/README.md` 確立未遷移資產（Modules/, Data/, runtime/ 等）視為 Target-State Procedure，不得 invent path 或阻擋常態開發；更新 `SOP_01`（配額模組目標態）、`SOP_11`（反思記憶缺席不阻擋 Planning）。
      - **安全與工具契約現代化**：`SOP_02` 服從 C-02 裁決，確立金鑰洩漏第一優先為撤銷輪替，嚴禁 Agent 破壞性重寫歷史；`SOP_05` 採用跨工具寫入政策（Tool-portable Write Policy），解除特定 API 綁定；`SOP_09` 移除 `git reset --hard`；`SOP_04` / `SOP_06` 對齊 ADR-0017 Port 配置（LINE=3000, TG=3001, Next.js=3002, Static=8888）。
      - **授權與審計流程精簡**：`SOP_14` 消除已獲明確任務授權後之第二次「Proceed」確認，審計官直接由 GitHub 獨立讀取 diff 證據，不強制建 `task.md`，壓測改為風險導向。
      - **規劃真實性**：`TASKBOARD.md` 與交接區將 E-03 更新為待辦，下一步開展只讀依賴調研（READ-ONLY DEPENDENCY INVENTORY），不再重問已裁決之 C-04。
59. **Final Governance Exit — Convergence Patch（治理層退出收斂修正）**（2026-09-11）
    - **背景**：治理層退出正式凍結前之最終收斂修正。修正宏觀審計官於 exact commit `acc5890` 確認之 Active Contract 殘留矛盾，確保後續 D/E 主線自主推進時不再受任何過時規範阻礙。
    - **收斂成果**：
      - **GOAL_SPEC 檔案自主性**：確立 GOAL_SPEC 模式下執行者在 Allowed Scope 內具備檔案選擇自主權（inspect → design → implement）；Auditor 無須在提示詞預測 exact implementation files，以 `git diff --name-only` 取得之實際路徑進行逐檔明確 `git add`。
      - **Preflight & Selftest 模式感知徹底解耦**：清查並消除 `prompt-preflight.md` §3.4 與 `handover-selftest.md` E 節殘留之無條件 Batch Spec / 錨點 / BPE 要求；GOAL_SPEC 正式免除規格與錨點驗證，EXACT_SPEC 保留嚴格重放。
      - **M3 自主修復閉環**：解除 M3「僅限 pre-commit」之過度嚴格限制；GOAL_SPEC 允許執行者在原 Allowed Scope 內透過新增 repair commit 進行最多 3 輪自主修復，無需每次 roundtrip 升級。
      - **B-36 回報通道正式轉移**：確立版本庫（Git commit、`EXEC-LOG.md` 與 GitHub Actions）為單一證據通道，對話視窗預設採用單行 `COMMIT <sha> | CI PASS | S1 NONE`，嚴禁預設轉貼終端機日誌或 raw diff。
      - **SOP_14 治理減法**：移除檔案數量單獨觸發限制（改採純風險導向），廢除四角色會議文字扮演、常態任務沙盒測試與強制 `walkthrough.md`。
      - **執行期邊界與授權清晰化**：`SOP_README` 區分版本庫納管資產與外部環境工具；`SOP_01` 釐清 `$$` 指令為研究領域專屬命令，不阻擋版本庫重構授權；`SOP_11` 確立記憶庫缺席不阻擋反思與任務執行。
60. **A-06 Machine-Generated Rule Traceability & B-01 Targeted Upstream Comparison（規則追溯機械化與 B-01 標靶上游比對）**（2026-09-13）
    - **背景**：原 A-06 規劃手動維護 `.claude/rules/rule-traceability.md`，因手動維護成本高且易膨脹 Claude hot-path context，重新設計為以專屬腳本 `scripts/generate_rule_traceability.py` 自動抽取 active control-plane 規則顯式引用（ADR、CHECK、TASK、SECTION、FILE），輸出至 `docs/generated/rule-traceability.md`，並由 `scripts/tests/test_rule_traceability.py` 與 canonical `verify_all.py` 自動守護。
    - **落地成果**：
      - **A-06 機械化追溯**：實作 `scripts/generate_rule_traceability.py` 與單元測試 `scripts/tests/test_rule_traceability.py`（8 項測試全通，涵蓋確定性排序、顯式引用抽取、最近標題歸屬、無自我掃描、broken target fail-closed、--check fresh/stale 判別、無自然語言臆測，以及 repo-state freshness gate）；產出 `docs/generated/rule-traceability.md`；A-06 於 TASKBOARD 標記進行中並指向 generated 文件，待 External Macro Audit。
      - **B-01 標靶上游比對留痕**：機器查證上游 `mattpocock/skills` main full SHA 為 `3cca18b368ae95cdbdebbff572ccafa662551015`；記錄 External Macro Reviewer 完成之 B-01 targeted upstream comparison（ADR-0002/0004/0010 與 B-01 三 active targets 無 upstream blocker，辨識兩項 adjacent upstream deltas）；B-28/B-29 改為待裁決，保留完整 upstream audit 執行時機待使用者裁決；B-01 明確維持待辦（NOT STARTED）。
61. **B-87 Phase 1 Comprehensive Taskboard Truth Reconciliation（看板真實性全面對帳 Phase 1）**（2026-09-13）
    - **背景**：重新以 current repository truth 全面核對 TASKBOARD A / B / F / G 節，不採用「path exists = task complete」這種會導致假綠燈的 generic inference，逐項自 repo 取得可重現之證據 probe，辨識已實作、已封存（superseded / absorbed）與 genuine remaining work。
    - **對帳記錄**：

      | Task ID | Old Status | Candidate / New Status | Machine / Repo Evidence | Disposition Reason |
      |---|---|---|---|---|
      | B-05 | 待辦 | 已完成 | `scripts/validate_skills.py:187` 正式實作 `DLP_ATTESTATION_RE` 與 `check_doc_content`，`scripts/tests/test_validate_skills.py` 8+ 測試守護；全庫 `skills/` 經掃描 0 筆 raw false DLP attestation 殘留；canonical `verify_all.py` 自動守護 | 裝飾樣板存量清理需求已被 production detector 與 active validator 完全覆蓋且全庫零違規殘留，實質完成 |
      | B-06 | 待辦 | 可封存 | `AGENTS.md` §2 frontmatter 規範未強制要求 description 引號統一；`scripts/validate_skills.py` 正式解析器對引號與未引號皆合法支援；無任何 correctness 或安全影響 | 純格式收斂，無 production correctness 價值，可予封存，不得為此異動技能 |
      | B-38 | 待辦 | 可封存 | `.agents/rules/git-and-reporting.md` §2（B-36）確立 Repo Evidence Channel，嚴禁終端機日誌 dump 入對話；機器證據完整留存於 Git / Actions / EXEC-LOG，對話採單行回報 | 原始「Claude context pollution」問題已由 B-36 證據通道架構徹底消除，不再需要實作 `--quiet` / `--json` |
      | B-69 | 待辦 | 待辦（維持待辦） | `PRINCIPLES.md` 與現行 `.agents/rules/`、`.claude/rules/` 查無跨環境比對原語規範（如「設計比對原語前須考量跨 OS/locale/工具鏈差異、禁止直接依賴位元組」） | 原提案規範尚未被現行更高層 active rules 完整納入，具備真實殘留行為，嚴格依 current repo evidence 維持待辦 |
      | B-70 | 待辦 | 待辦 | current prompt-preflight §3.1 仍為人工維護 pairing table；B-45 仍記錄 C section ↔ §5.3 pairing registration residual；舊 B-60 allocation 部分已過時，但 B-70 pairing-by-memory 核心問題尚未被取代 | GENUINE REMAINING WORK / NON-PRE-B01；核心配對問題仍存在，但非 Pre-B01 blocker，不阻擋 B-01 |
      | B-71 | 待辦 | 可封存 | B-31（BOM 偵測）、B-53（inline checks 抽取）、B-54（CHECK 21 跨層矛盾）、B-87（對帳）、B-88（空行斷開）、B-89（日文字元）各自具備 canonical concrete tasks | B-71 屬「零漏網未達標」之 umbrella 觀察項目，所有具體有效之殘留風險皆已收納進獨立 concrete tasks，予以封存且不刪除具體項目 |
      | B-83 | 待辦 | 可封存 | `.claude/rules/auditor-protocol.md` §9.2 確立開場僅讀 §5.4、§5.1、§5.3 與 `TASKBOARD.NEXT_WORK`，不再載入全量歷史 backlog；historical rationale on-demand | 原始「開場單次載入 2,338 行」之 hot-path 問題已由 targeted current-state extraction 徹底解決；歷史瘦身移入可選維護，不再為 production blocker |
      | G-01 | 待辦 | 可封存 | `docs/TASKBOARD.md` E-05 明確涵蓋 `Data/TODO.md`（必須遷移/裁決）之範疇 | absorbed by E-05；內容作為 E-05 acceptance inventory，非刪除需求；不建第二 Data migration queue |
      | G-02 | 待辦 | 可封存 | `docs/TASKBOARD.md` E-05 明確涵蓋 `Execution_Plans/` 之範疇 | absorbed by E-05；內容作為 E-05 acceptance inventory，非刪除需求；不建第二 Data migration queue |
      | G-03 | 待辦 | 可封存 | `docs/TASKBOARD.md` E-05 明確涵蓋 `_archive_legacy_docs/` 之五份舊 ADR 評估 | absorbed by E-05；內容作為 E-05 acceptance inventory，非刪除需求；不建第二 Data migration queue |
      | G-04 | 待辦 | 可封存 | `docs/TASKBOARD.md` E-05 明確涵蓋 `_archive_legacy_docs/` 之其餘文件評估 | absorbed by E-05；內容作為 E-05 acceptance inventory，非刪除需求；不建第二 Data migration queue |
      | B-28 | 待裁決 | 待辦 | 使用者正式裁決：完整 upstream comparison 不在 B-01 前執行；upstream baseline `3cca18b` targeted comparison 已成立且無 blocker | DEFER POST-B01 / trigger-based reopening，不阻塞 B-01 |
      | B-29 | 待裁決 | 待辦 | 使用者正式裁決同 B-28；上游一致性對照表與機械檢查延後 | DEFER POST-B01 / trigger-based reopening，不阻塞 B-01 |
      | B-87 | 待辦 | 進行中 | 本批執行 B-87 Phase 1 Truth Reconciliation，不採用 false-green 之 generic file-existence inference，逐項以 repo probe 驗證 | 進行中，待 candidate push 後由 External Macro Reviewer 獨立核對 |
      | B-31 | 待辦 | 待辦 | ADR-0013 §2C BOM 污染偵測新 CHECK 待實作 | PRE-B01 GATE CANDIDATE，維持待辦 |
      | B-88 | 待辦 | 待辦 | 表格空行斷開偵測待實作 | PRE-B01 GATE CANDIDATE，維持待辦 |
      | B-89 | 待辦 | 待辦 | CHECK 14 日文新字體/假名擴充待實作 | PRE-B01 GATE CANDIDATE，維持待辦 |
      | B-41 | 待辦 | 待辦 | Project Instructions mirror 與序列比對待實作 | PRE-B01 GATE CANDIDATE，維持待辦 |
      | B-01 | 待辦 | 待辦（NOT STARTED） | targeted comparison 已通且無 blocker；full comparison 已裁決延後；等待 B-87、B-31/88/89、B-41 逐批放行 | 待辦（NOT STARTED），本批零實作 |

    - **B-87 結案留痕（B-87 Closure Note）**（2026-09-13）：
      - `b2256fd` External Macro PASS (ACCEPT ALL, Actions Run 34768119758 success)。
      - 原始 generic path-existence CHECK proposal 因具 false-green 結構風險被明確 rejected / superseded，不實作任何 generic completion inference engine。
      - Taskboard reconciliation accepted；ongoing state integrity 由現行 B-95 promotion、every-round disposition 與 External Macro Review 維持。
      - B-87 狀態正式轉為「可封存」（CLOSED）。
      - 全庫未新增 generic completion inference 或第二份 task state store。
    - **注意**：本節為 append-only 歷史證據留痕，當前任務權威唯一以 `docs/TASKBOARD.md` 為準。

62. **User Governance Priority Decision（使用者治理優先原則裁決）**（2026-09-14）
    - **裁決內容**：不設定人工 governance 停止線。治理規範若有 current evidence 且完成後能實質提升主線 correctness、reliability、automation 或效率，應處理清楚；但不得因理論完美、形式對稱或 speculative possibility 無限放大治理範圍。
    - **性質界定**：本裁決為排程與執行原則（scheduling / execution rationale），絕非第二工作佇列；當前任務權威唯一以 `docs/TASKBOARD.md` 為準。

63. **B-96 `$$使用者$$` Session-local User Prompt Compiler Mode — Specification Snapshot**（2026-09-14）
    - **背景與定性**：本項為使用者已正式裁決之設計快照與未來施工規格（Specification Snapshot / Implementation Contract），非當前任務佇列。當前任務、狀態與執行優先序之唯一權威仍為 `docs/TASKBOARD.md`，本 Item 不得自行決定 NEXT_WORK。
    - **核心目標**：建立 Natural-Language → Governed Execution Adapter，讓使用者能直接以自然語言與 Antigravity Agent 互動，由 Antigravity 使用自身 quota 完成 repository inspection、deterministic discovery、dependency scan、scope derivation、prompt compilation、implementation、testing、debugging，降低 Claude / Macro Auditor 在 repo-wide mechanical discovery、mundane prompt construction、deterministic scanning 的 token/quota 消耗。Macro Auditor 保留 semantic decisions、architecture、security、genuine scope decisions 與 Macro Audit。B-96 不是 User Override、不是 safety bypass、不是 Macro Auditor replacement、不構成權限提升（permission escalation）。
    - **啟動指令與生命週期（Activation & Lifetime）**：
      - 唯一啟用指令：`$$使用者$$`。
      - 啟用後目前 Antigravity Agent conversation/session 進入 User Mode，第一行固定顯示 `[使用者模式：ON]`。預期回覆等義：「進入使用者模式。後續一般需求將自動轉換成符合 HH.AI_v2 現行規格的提示詞。READ_ONLY 工作可直接執行；repository mutation 會先完成唯讀探索與依賴分析，再提供正式提示詞供使用者確認；特殊 $$ 指令仍依既有 Router 執行。未經確認，不得執行 repository mutation。」
      - **重要最終使用者裁決**：不存在 `$$結束使用者$$`，不得建立該指令。
      - User Mode 唯一正常終止方式：關閉目前 Antigravity Agent / conversation / session。
      - 新的 Agent / conversation 預設 OFF，必須重新收到 `$$使用者$$` 才可啟用。不得跨 Agent、跨 conversation、跨 session 保存 User Mode。
    - **狀態儲存邊界（State Storage Boundary）**：
      - User Mode state 只能是 session-local runtime state。
      - 不得寫入 TASKBOARD、AUDIT-LOG、EXEC-LOG、Git config、repo config、shared persistent mode DB、runtime global state、user-global memory 或其他 Agent state 作為 mode ON/OFF authority。關閉 session 即自然失效。
    - **倉庫身分綁定（Repository Identity Binding）**：
      - User Mode 必須綁定 current repository identity。
      - 若同一個 Agent conversation 切換至另一個 repository/workspace，User Mode state 與所有 pending candidates 立即視為 invalid，不得將舊 repo 之 candidate/confirmation 套用至新 repo，必須要求重新輸入 `$$使用者$$`。
    - **使用者可見狀態（User-visible State）**：
      - 每一輪回覆第一行固定等義顯示：`[使用者模式：ON]`；等待 confirmation 時：`[使用者模式：ON｜AWAITING_CONFIRMATION｜UPM-xxxxxx]`。
      - 若因 conversation truncation / prefix clearing / context loss 無法可靠證明 mode 是否仍 ON、latest candidate 為哪一版、或使用者 approval 指向何 candidate，則 fail-safe 顯示：「使用者模式狀態無法可靠確認。請重新輸入 $$使用者$$。未執行任何 repository mutation。」不得猜測。
    - **四路路由分類（Four-Way Routing）**：
      1. **READ_ONLY**：查看檔案、分析 bug、repo search、dependency discovery、讀狀態、安全測試/分析。可直接使用 Antigravity quota 執行，不得產生 tracked repo mutation。
      2. **REPO_MUTATION**：修改程式/文件、refactor、bug fix、新增 feature、commit/push。不得直接修改，必須循：Intent → READ_ONLY discovery → deterministic impact scan → dependency disposition boundary → candidate Allowed Scope → compile production prompt → User confirmation → existing production preflight → mutation / implementation → tests / Gates / Git / CI。
      3. **EXTERNAL_ACTION**：發送外部訊息、啟停服務、呼叫具 side effect API、修改外部帳號/系統等對外操作。不得因「不改 Git」就誤分類成 READ_ONLY，必須遵守對應 skill/SOP/授權/確認/金鑰邊界。
      4. **SPECIAL_COMMAND**：任何 canonical `$$...$$` command 不得進 natural-language compiler，優先交給 `SOP/SOP_00A_Master_Index.json` canonical router。
    - **路由優先級（Routing Priority）**：
      1. 已登錄 canonical $$special command$$
      2. $$使用者$$ activation
      3. User Mode 一般自然語言
      4. Normal Agent behavior
      - 若輸入形狀為 `$$xxxx$$` 但 canonical router 未登錄：不得猜測、不得 fuzzy match、不得當一般自然語言、不得自動轉 mutation prompt，應等義回覆：`UNKNOWN_SPECIAL_COMMAND`。
    - **特殊指令相容性（Special Command Compatibility）**：
      - User Mode ON 時，以下及未來 Master Index canonical triggers 仍優先走 router：`$$自動化$$`、`$$自動化_微型模型$$`、`$$自動化_通用研究$$`、`$$自動化_量化實驗$$`、`$$Line帳號$$`、`$$TG帳號$$`、`$$Allow All$$`、`$$allowall$$`、`$$LINE連線$$`、`$$LINE連線: <自訂名稱>$$`、`$$TG連線$$`。不得被 compiler 重新解釋為一般 repo request。
      - 若 canonical route 為 PENDING_MIGRATION，應回報「route 已辨識但 target state = PENDING_MIGRATION」，不得誤報 PROMPT STRUCTURE ERROR。B-96 不負責完成 LINE/TG migration，不 duplicate E-04 / B-56 既有職責。
    - **`$$自動化$$` 與 `$$Allow All$$` 邊界**：
      - `$$自動化$$`（既有 domain/research orchestration 指令）與 `$$使用者$$`（session-local natural-language prompt compiler mode）為不同能力，不得合併、互相 alias 或互相覆蓋。
      - `$$使用者$$` 不得擴張 `$$Allow All$$` 現有能力；Allowed Scope、destructive Git、歷史重寫、金鑰處理、domain authorization 等安全邊界維持不變。
    - **倉庫修改編譯器與候選提示詞（Repository Mutation Compiler & Candidate Prompt）**：
      - 收到 repo mutation 要求不得立即修改。第一階段只能 READ_ONLY 探索（inspect repo, read active rules, fetch current HEAD, inspect current task/context, run B-68 impact discovery, find tests/reverse refs, determine mechanical dependencies, prepare candidate scope）。
      - 若存在 genuine semantic / architecture / security / project-direction choice，不得自行決定，直接向使用者提出選項與影響，使用者裁決後才繼續 compile。不要求每次都回 Claude。
      - 無 semantic blocker 後，產出完整符合 current HH.AI_v2 production contract 的 candidate prompt（包含 Prompt Manifest, current base OID, Goal, Invariants, Allowed Scope, Forbidden Scope, dependency evidence, dispositions, acceptance criteria, tests, canonical Gates, Git / CI lifecycle, error routing）。
      - 回報等義：「已轉成符合規格的提示詞如下：<完整 production prompt> 請確認是否執行。」未確認前 tracked repo mutation = 0。
    - **候選提示詞身分與確認語意（Candidate Identity & Confirmation Semantics）**：
      - 每份 pending candidate 建立 session-local identity（如 `UPM-xxxxxx`），deterministic derive 自 repository identity, base OID, compiled production prompt, dependency evidence, Allowed Scope。不進 Git、不進 TASKBOARD、不進 global state、不跨 Agent。任何需求變動，old candidate 立即 INVALIDATED。
      - 合法 confirmation intent（如「同意」「確認」「確認執行」「執行」「可以執行」），嚴禁 substring match（例如「我不同意」不得誤觸發）。
      - Confirmation 只能批准最新一份 pending candidate。若包含新需求（例如「同意，但是再加 XXX」），視為 requirement changed，old candidate INVALIDATED → 重新 discovery → 重新 compile → 新 candidate → 再次等確認，不得執行舊 candidate。
    - **基準漂移機械復原（Base Drift Mechanical Recovery）**：
      - candidate 產生後，在 User confirmation 與 mutation 前重新確認 HEAD, origin/main, worktree, repo identity。若 base drift，不得執行舊 candidate，自動進行 mechanical recovery：no mutation → invalidate candidate → fetch current state → READ_ONLY rediscovery → re-run B-68 impact scan → compile new candidate → 重新請使用者確認。不需自動升級 Macro Auditor，除非新 base 產生 genuine S1 semantic choice。
    - **現有生產安全規範永不繞過（Existing Production Safety Is Never Bypassed）**：
      - User「同意」只代表批准 candidate 進入正式 production preflight，絕非批准跳過 safety。仍必須執行：Prompt Manifest validation、complete incoming prompt validation、prompt-preflight、B-68 dependency replay、UPDATE ⊆ Allowed Scope、base/origin/clean worktree checks、explicit staging、tests、canonical verify_all、Git / exact-SHA CI。若 User Mode 自己產出的 prompt 有錯，照常 fail-closed。
    - **角色邊界、金鑰、外部動作與並行代理**：
      - Antigravity 自主範圍：inspect, discovery, impact scan, reverse ref scan, test discovery, candidate scope, prompt compilation, implementation, debugging, M1-M3, test/Gate repair。
      - 禁止自主：Macro PASS, architecture policy reversal, ADR override, security exception, destructive Git authorization, semantic project direction, hidden scope expansion, disposition semantic rewrite。遇 genuine semantic choice 直接詢問使用者。
      - Secrets：不得因轉 prompt 複製 secret 到 TASKBOARD、EXEC-LOG、AUDIT-LOG、backlog、Git 或 candidate prompt prose，使用既有 env/secret 機制或 session-local placeholder（如 `<SECRET_FROM_USER_SESSION>`）。B-96 不建立新 secret manager。
      - External Actions：遵守對應 skill/SOP 安全邊界與 user confirmation 要求，不以無 repo mutation 作為 bypass。
      - Parallel Agents：不建立 global lock，依賴 base OID、fetch origin/main、clean worktree、B-68 replay、pre-commit recheck 確保碰撞時不得 silent overwrite。
    - **漸進式揭露架構與 User-invoked 分類**：
      - 未來實作優先採：`SOP/SOP_00A_Master_Index.json` → exact `$$使用者$$` trigger → `skills/orchestration/user-prompt-compiler/`（小型 hot-path `SKILL.md` + 詳細 `REFERENCE.md`），不建立大型 always-loaded rule mirror。
      - 依 `AGENTS.md` §5 分類為 User-invoked（`disable-model-invocation: true`），必須由人類手動輸入，模型不得自主呼叫。
    - **完成定義與驗收金絲雀（Definition of Done / Runtime Canaries）**：
      1. Normal Agent 未收到 `$$使用者$$` → User Mode OFF。
      2. 收到 `$$使用者$$` → User Mode ON，零 repo mutation。
      3. ON + READ_ONLY request → 可直接分析，零 tracked mutation。
      4. ON + REPO_MUTATION request → 先 discovery，只產 candidate prompt，未確認前零 mutation。
      5. 合法 confirmation → 才進 production preflight。
      6. 「我不同意」→ 不得誤判 approval。
      7. 「同意，但是再加 XXX」→ old candidate invalidated，不得執行舊 prompt。
      8. candidate base drift → invalidate + rediscover + recompile。
      9. Allowed Scope 故意漏 UPDATE dependency → B-68 mutation-before S1 fail-closed。
      10. `$$自動化$$` while User Mode ON → canonical special router。
      11. `$$LINE連線$$` while ON → canonical route；如仍 PENDING_MIGRATION 則回 PENDING_MIGRATION truth，不得 Prompt Manifest 誤擋。
      12. `$$TG連線$$` 同上。
      13. unknown `$$command$$` → UNKNOWN_SPECIAL_COMMAND。
      14. Agent/conversation 關閉 → User Mode 結束。
      15. new Agent → User Mode OFF。
      16. context / candidate identity 無法可靠確認 → fail-safe require `$$使用者$$` reactivation，零 mutation。
      17. repository identity change → mode/candidate invalidated。
      18. secret input → no persistent secret duplication。
      19. external side effect → domain authorization path，不得 READ_ONLY shortcut。
      20. User-generated candidate 本身有錯 → existing Prompt Manifest / B-68 / preflight 照常攔截。
    - **明確非目標（Explicit Non-Goals）**：
      - B-96 不做：User Owner safety override、bypass preflight、bypass B-68、bypass destructive-Git policy、Macro Auditor replacement、automatic Macro PASS、global User Mode persistence、cross-Agent mode sharing、new global state database、new secret manager、new Agent scheduler、global concurrency lock、LINE migration、TG migration、`$$自動化$$` redesign、`$$Allow All$$` expansion、B-56 replacement、E-04 replacement、Prompt Manifest v2、semantic dependency engine。
    - **權威宣告（Authority Statement）**：
      - 本 Specification Snapshot 保存已裁決 architecture / acceptance / non-goals，目的為讓未來 B-96 直接施工，避免重新研究。但 current task status、execution order 與 NEXT_WORK 仍唯一以 `docs/TASKBOARD.md` 為權威來源。

64. **B-41 Slim Bootstrap / Runtime Reconciliation Decision（B-41 輕量引導與執行期對帳決策）**（2026-09-14）
    - **背景與定性**：本項為 B-41 runtime/user reconciliation 與 Slim Bootstrap / Router 架構裁決之歷史紀錄留痕（Historical Decision Snapshot），非當前任務佇列。當前任務、狀態與執行優先序之唯一權威仍為 `docs/TASKBOARD.md`。
    - **歷史構想取代（Original Full-Mirror Superseded）**：早期 B-41 建立 repo 規則全文鏡像（full rule mirror）之構想已正式廢除；在雙控制平面分離非對稱架構下，不得在倉庫外部建立第二份大型規則副本。
    - **執行期對帳實證（Runtime / User Reconciliation Evidence）**：
      - 當前 Antigravity IDE UI 未觀察到使用者可設定之 Project Instructions / Rules 編輯介面。
      - 全域規則 `$HOME/.gemini/GEMINI.md` 經查證不存在（ABSENT）。
      - 工作區 `GEMINI.md` 經查證不存在（ABSENT）。
      - `AGENTS.md` 與 `.agents/rules/` 為倉庫擁有（repo-owned）之執行者控制平面。
      - IDE 內部產品系統提示詞（internal system prompt）無法由程式碼機器讀取，不屬於專案可治理層次，不得建立宣稱可比對 UI 狀態之虛假 CI CHECK。
    - **架構裁決（Architecture Decision）**：
      - 現有 `.claude/README.md` 已為 Claude Control Plane Router，正式指定為倉庫擁有之正規輕量啟動與復原路由（canonical slim bootstrap / recovery router），優先重用既有資產，不另建 `.claude/slim-bootstrap.md`。
      - `docs/HANDOVER.md` 為輔助專案整體路由（supporting project router），維持 VERIFY_ONLY 零修改。
      - `.claude/README.md` 僅追加最小 Cold-Start / Recovery Bootstrap 導引章節，不持久硬編碼動態指標（HEAD、NEXT_WORK、checkpoint、CI Run、計數等）。
      - 外部執行環境若存在任何指令層，僅可作為極小啟動路由，不得作為 full mirror；若產生衝突依 S1 / 使用者協調處理。
    - **B-69 實證留痕（B-69 False-Zero Search Evidence）**：
      - B-41 Cold-Start Discovery 中記錄 Antigravity IDE Search 對確實存在之 B-41 出現兩次 false-zero，而以 explicit UTF-8 `Select-String` / `Get-Content` 均正常命中；判定為現有 B-69 跨環境／工具比對實證，標記為 non-blocking，不阻擋 B-41 / B-01，不另設新 task，production dependency authority 仍以 `scripts/impact_scan.py` 為準。
    - **主線狀態**：
      - B-01 維持待辦（NOT STARTED），本批零實作。
    - **權威宣告（Authority Statement）**：
      - 本節為 append-only 歷史決策留痕，當前任務狀態、優先序與 `**NEXT_WORK**` 之唯一權威仍為 `docs/TASKBOARD.md`。

65. **B-97 Pre-B01 Comprehensive Pending-Task & Repository Release Audit — Specification Snapshot**（2026-09-14）
    - **背景與權威宣告（Background & Authority Statement）**：
      - 本 Item 65 保存使用者已裁決之 Pre-B01 release-gate specification（施工規格快照），非第二任務佇列（No Second Queue）。當前任務狀態、執行優先序與 `**NEXT_WORK**` 之唯一權威來源仍為 `docs/TASKBOARD.md`。
    - **A. 目的（Purpose）**：
      - 進入 B-01 前，進行最後一次窮盡的未完成待辦檢討（exhaustive unfinished-task review）與全庫宏觀發布審計（repository-wide macro release audit），避免因 `TASKBOARD.NEXT_WORK` 機械推進至 B-01 而跳過仍具實質證據（material evidence）之重要前置問題。
    - **B. 一次性閘門邊界（One-Time Gate Boundary）**：
      - B-97 是一次性的 B-01 Release Gate，不是永久新增第三層審查者、不是永久新增靜態閘門、不是週期性發布框架（recurring release framework）、不是新任務佇列、不是新控制平面，亦非預設新增 CHECK。完成 B-97 後不應自動複製至每個未來批次。
    - **C. 第一階段必須唯讀（Phase 1 Must Be READ_ONLY）**：
      - B-97 第一階段只能執行：`git fetch origin`、檢視 current main、讀取 repo、確定性搜尋、impact discovery、無副作用之測試與金絲雀驗證、GitHub remote state 查核、上游基準檢驗。嚴禁修改 repo、commit、push、開始 B-01 或順手修復 findings。先產出機器客觀證據，再由 External Macro Reviewer 進行處置裁決。
    - **D. 窮盡未完成待辦清單（Exhaustive Pending-Task Inventory）**：
      - B-97 執行當下不得使用手寫固定數量或歷史計數（如「34 筆」），必須於 current base 從 `docs/TASKBOARD.md` machine-derive 導出所有 unfinished rows（涵蓋「待辦」、「進行中」、「待裁決」或 current schema 等義狀態）。
      - 不得因待辦數量多而採抽樣檢查，每一筆皆必須由 External Macro Reviewer 親自判定 Pre-B01 disposition。
      - 建議處置語彙：`PRE_B01_REQUIRED`、`TARGET_B01`、`POST_B01`、`DEFERRED_BY_USER`、`USER_DECISION_NONBLOCKING`、`EXISTING_BLOCKER`、`ARCHIVABLE / COMPLETED`（僅在 current evidence 真正支持時使用）。
      - 每一筆紀錄至少包含：task ID、current status、current repo evidence、與 B-01 關聯性、Pre-B01 disposition、簡短理由、是否阻塞 B-01。
    - **E. 全庫宏觀審計面向（Repository-Wide Macro Audit Dimensions）**：
      - B-97 必須在 current main 宏觀檢查至少 11 個面向：
        1. Authority / state truth：TASKBOARD.NEXT_WORK、backlog §5.1 / §5.3 / §5.4、AUDIT-LOG、EXEC-LOG、HANDOVER/router、防範 dynamic truth 重複。
        2. Active control planes：PRINCIPLES、AGENTS、.agents/rules、.claude/rules、.claude/README、規則載入量（rule loadability）、自動生成追溯表、排除隱性第二權威。
        3. Verification integrity：canonical verify_all、current CHECK 1..20 清單、scripts tests、webapp tests、fail-closed 行為、false-green 防回歸、generated fingerprint、verifier reporting truth 一致性。
        4. Dependency Closure：scripts/impact_scan.py、B-68 replay path、UPDATE ⊆ Allowed Scope 配對、Prompt Manifest / preflight 攔截能力、無已知繞過路徑。
        5. Git / remote truth：HEAD / origin/main 一致性、exact-SHA Verify、branch protection 與 required status checks 現況、C-06 current state。
        6. B-01 target readiness：ADR-0002、ADR-0004、ADR-0010、AGENTS.md §5、.agents/rules/skills-architecture.md、.agents/rules/powershell-encoding-protocol.md；確認 B-01 維持 NOT STARTED、無 target 靜默漂移、無遺漏配對依賴。
        7. Upstream comparison freshness：檢查最新 mattpocock/skills upstream SHA，比對既定 B-01 approved baseline（`3cca18b`）；僅在出現客觀 trigger 時才重開 B-28/B-29。
        8. Special-command / routing truth：SOP/SOP_00A_Master_Index.json、既有 `$$` 路由、PENDING_MIGRATION 現況、排除虛假完成之路由。
        9. Security / secret / machine-specific state：無未經清理之憑證、無機器專屬本機路徑進入生產契約、無破壞性 Git 授權漂移。
        10. Cross-environment / tool correctness：考量 B-69 真實 false-zero 證據，IDE Search zero 不得單獨作為 ABSENT 判據，權威掃描一律採用確定性 repo 工具。
        11. Mainline continuation efficiency：僅辨識具備 current evidence 且實質影響 B-01 正確性、可靠性、機械續行與主線推進效率之 material finding；杜絕為求形式優雅而空想之投機任務。
    - **F. 實質發現處置路由（Material Finding Routing）**：
      - 每一項 finding 必須依 B-95 規格指定 `FINDING_DISPOSITION`（NONE / CURRENT / EXISTING <task-id> / NEW <task-id>）。若實質影響 correctness、security、architecture、routing/state truth、audit truth、CI/verifier truth、runtime loadability、repo/runtime consistency 或 B-01 next-task reliability，必須 TASKBOARD-visible，不得隱匿於文字報告。Blocking finding 可在具 current evidence 時 preempt B-01；non-blocking finding 正常登錄但不自動 preempt。
    - **G. 禁止人為治理停止線（No Artificial Governance Stop Line）**：
      - 不設「只允許再修 N 個 governance task」之人為硬上限，亦不得為理論完整性而無限擴張；唯一判斷標準為 current evidence ＋ material value。
    - **H. C-06 處置（C-06 Handling）**：
      - 重新核對 main branch required status checks current truth；C-06 仍向使用者清楚揭示選項（A. direct-push + post-push Verify；B. Require PR + Verify before merge）。B-97 不得代選，在使用者未改變決策前維持 `USER_DECISION_NONBLOCKING`，不得因 C-06 尚未裁決而自動拒絕 B-01 release。
    - **I. B-28 / B-29 重開規則（B-28 / B-29 Reopening Rule）**：
      - 完整上游比對目前仍為 `DEFERRED_BY_USER`。僅在客觀 trigger 出現時重開（upstream baseline SHA 變更、B-01 target scope 擴大、或 targeted comparison 前提被推翻），不得僅因 B-97 為通盤審計即無條件重做。
    - **J. 發布裁決（Release Decision）**：
      - B-97 最終由 External Macro Reviewer 明確判定 `PRE-B01 RELEASE STATUS` 為 `PASS` 或 `HOLD`。PASS 需滿足：unfinished task inventory 全數完成處置、current main exact-SHA CI 通過、無未處置之 material blocker、所有 material findings 均 TASKBOARD-visible、B-01 target/scope readiness 獨立查證成立、使用者決策正確分類、無隱性狀態衝突。若 HOLD，必須具體條列 blocking task/finding 與所需修復。
    - **K. B-01 啟動邊界（B-01 Start Boundary）**：
      - 在 B-97 External Macro PRE-B01 RELEASE PASS 前，嚴禁 NEXT_WORK → B-01、嚴禁 B-01 implementation、嚴禁 B-01 mutation 與 commit。待 B-97 release PASS 完成 state closure 後，才允許 `NEXT_WORK = B-01`。
    - **L. 結案定義（Definition of Done）**：
      - B-97 完成必須同時具備：1. 完整 machine-derived unfinished-task inventory；2. 每一筆 unfinished row 完成 Macro disposition；3. 全庫宏觀審計完成；4. current exact-SHA CI 證據；5. C-06 current truth surfaced；6. B-01 ADR/target readiness 驗證；7. 上游基準新鮮度驗證；8. 所有 material findings 完成 B-95 處置；9. 審計期間 B-01 保持零修改；10. External Macro Reviewer 正式宣告 PRE-B01 RELEASE PASS。此時 B-97 方可 CLOSED。
    - **M. 歷史起始評估留痕（Historical Starting Assessment）**：
      - 記錄在 B-97 正式執行前之 Macro preliminary review 中，既有 unfinished items 初步未發現除 B-41 closure 外已證實之 Pre-B01 blocker。此為 preliminary historical assessment，不得取代 B-97 於未來 current base 重新 machine-derive 全部未完成項目，亦不得 hardcode 數量作為未來權威。

66. **Step 1 Security Event / B-98 Disposition & Context Economy / B-75 Scope Refinement**（2026-09-16）
    - **A. Step 1 Security Event 與 B-98 登錄（Security Event & B-98 Disposition）**：
      - **事件性質**：2026-09-16 Step 1 READ_ONLY alignment 期間，執行者為探索本機 GitHub API 能力而執行環境變數列舉，致使一個 GitHub credential 的完整 secret value 被輸出至 execution transcript。
      - **根本原因**：`secret-bearing environment output / redaction control gap`（執行者端缺乏明確且可機械守護之 secret-safe external API inspection 與輸出淨化契約，非 GitHub GET API 本身不安全）。
      - **已完成人工作業遏阻（Containment）**：暴露之 credential 已立即撤銷；替代 credential 已由使用者自行建立與驗證；包含 secret 之 PowerShell 歷史紀錄已由使用者處置完畢；secret value 嚴格禁止進入 repo、commit、EXEC-LOG 或對話。
      - **任務登錄**：登錄 NEW B-98（`Executor Secret / Credential Output Hardening`），狀態為待辦。確立憑證存在性檢查僅限輸出布林值或 PRESENT/ABSENT，嚴禁列舉或輸出 secret-bearing environment variable values，並規範後續 remote health 必須採用 secret-safe auth 路徑。B-98 不阻塞本次 closure，亦不自動阻塞 B-97。
    - **B. 使用者 Context Economy 需求與 B-75 範圍精煉（Context Economy & B-75 Scope Refinement）**：
      - **使用者需求**：使用者提出降低長期協作之 context token 負擔，要求提示詞產出與溝通具備上下文經濟性，同時維持「使用者仍然取得一份完整、可一鍵複製給 Antigravity 的提示詞」之核心不變量，不得要求使用者手動組裝多份 prompt fragment。
      - **處置路由**：依 `EXISTING B-75` 收斂，將既有 B-75 任務範圍由「每批重寫 boilerplate」擴充精煉為 `Macro ↔ User ↔ Executor Context Economy`，禁止另建第二個重複之 context-economy task。
      - **設計方向**：以 conversation delta-first 加上 repo-canonical reusable contract 為規劃方向，將穩定之 boilerplate / contract 優先收斂至 repo 權威來源，機器衍生證據留在 repo 與 GitHub Actions 以 SHA/reference 定位，冷啟動優先由 canonical router 導航重建；正式 implementation 尚未開始。

67. **Qualification-Based Macro Auditor Architecture & Repo-Visible Handoff (B-99 / ADR-0021)**（2026-09-16）
    - **背景與架構處置（Background & Architecture Disposition）**：
      - **Step 3 READ_ONLY 相依性探索**：經 Step 3 READ_ONLY dependency discovery 全面清查現行規則與程式相依，確認既有架構硬編碼「Claude == 宏觀審計官」已與現行專案出現經使用者授權、能獨立完成 Macro evidence verification 之 reviewer（GPT 代理審查官）之事實產生衝突；且 repo 缺乏單一現行 Macro 指標、provider-neutral 資格合約與正式 A1 等效途徑。
      - **B-95 處置路由**：Macro Auditor 正式裁決 `FINDING_DISPOSITION: NEW B-99`，建立 `B-99 Qualification-Based Macro Auditor & Repo-Visible Handoff`，不併入 B-75、B-96、B-97 或 B-98。
      - **使用者核准架構決策（§4.1–§4.5 Approved Architecture Decisions）**：
        1. **Qualification-Based Macro Auditor (§4.1)**：Macro Auditor 為專案角色而非模型品牌，不得以模型品牌作為資格判據；取得資格必須同時具備使用者授權、與執行者獨立、完成 selftest、通過 A1 qualification、能獨立取得 current GitHub / exact-SHA evidence、且 repo-visible assignment 指向該 reviewer。
        2. **Exactly One Active Macro Auditor (§4.2)**：任一 repo-visible current state 只能存在 exactly one `ACTIVE_MACRO_AUDITOR`；僅使用者具有 assign / replace / handoff / revoke 權限，任何 Agent / session / prompt 不得自行取得或搶占。
        3. **Same-Agent & Same-Session Mutual Exclusion (§4.3)**：永久保留 ADR-0007「執行者不得自審」之核心不變量；同一 Agent / conversation / session 若為 Executor，不得在該 session 切換為 Macro Auditor；同一 Macro Auditor session 亦不得切換為 Executor。
        4. **`.claude/` Retained Compatibility Path (§4.4)**：保留 `.claude/` 實體目錄作為歷史相容路徑（語意為 Macro Auditor Control Plane），不建立 `.gpt/` 或 `.auditor/` 鏡像目錄，目錄名稱不再構成 Claude-only 資格限制。
        5. **A1 Dual Qualification Modes (§4.5)**：正式支援 `A1 FULL_CLONE`（自身環境 full clone + is-shallow=false）與 `A1 EQUIVALENT`（Macro 獨立由 GitHub API 取得 OID / compare / changed-files / file contents / Actions Verify 結果 ＋ Executor 本機 full clone 提供 cross-check；兩者均非信任執行者口頭報告）。
    - **架構決策紀錄（ADR-0021）**：
      - 建立 `docs/adr/0021-qualification-based-macro-auditor-role.md`（Accepted），正式 supersede ADR-0007 之歷史品牌選擇（Claude），永久繼承其核心審計獨立性與互斥不變量；ADR-0007 保持歷史原文不修改。
    - **倉庫可見交接與元資料純度（Repo-Visible Handoff & Metadata Purity）**：
      - 於 `docs/TASKBOARD.md` 頂部確立單一權威指標 `**ACTIVE_MACRO_AUDITOR**：GPT 代理審查官（使用者授權）`，不得包含 Git truth（HEAD、checkpoint、commit hash、CI Run ID 等）；擴充 CHECK 8 進行機械防護。

68. **B-97 Pre-B01 Comprehensive Pending-Task & Repository Release Audit — Final Result**（2026-09-16）
    - **背景與審計基線（Background & Audited Base）**：
      - 本批在 exact audited state `eceda26d495642d9b27864ebcfaebf751544dacd`（parent `09d2ccb4915d4e65665a68ac6511c1886c37cf77`）由執行者嚴格依 Item 65 規格執行 Phase 1 READ_ONLY 全庫發布審計與未完成待辦盤點；審計期間工作區保持 100% clean、零檔案修改、零 commit/push/tag/branch 異動，B-01 程式碼實作確為零（ZERO IMPLEMENTATION）。
      - 遠端 GitHub Actions Verify Run 35049350295 查證通過（completed / success）；本地 Canonical Entrypoint `scripts/verify_all.py` 5 大 Correctness Gates 全數通過（CHECK 1..20 PASS, 294 unit tests PASS, 13 webapp tests PASS）。
    - **A. 未完成待辦全量機器盤點與 Macro 處置（41-Row Task Inventory & Macro Disposition）**：
      - 依 Item 65.D「禁止手寫預設數量、必須 machine-derive current base 所有非完成列」之規定，自 `docs/TASKBOARD.md` 完整導出 41 筆非完成任務（核心 `待辦` 34 筆 ＋ `待裁決` 1 筆，另保守納入 `已裁決` 5 筆與 `已裁決（方向）` 1 筆）。
      - 由 External Macro Reviewer（GPT 代理審查官（使用者授權））親自完成逐筆審查，裁決 Pre-B01 release disposition 如下表：

      | Task | Pre-B01 Disposition | 理由摘要 |
      |---|---|---|
      | A-29 | ARCHIVABLE / COMPLETED | 歷史 CHECK 15 刪除事項已裁決棄用，缺口已登錄為 B-17 |
      | B-01 | TARGET_B01 | 本次發布閘門之目標工作，維持待辦零實作 |
      | B-03 | POST_B01 | SOP_03 規範建立，非 B-01 前置阻礙 |
      | B-04 | POST_B01 | validate_skills 觸發詞 warning，非 B-01 前置 |
      | B-10 | POST_B01 | Jules 協作規範，獨立於 B-01 ADR 搬移 |
      | B-16 | DEFERRED_BY_USER / POST_B01 | 歷史宣稱回溯，使用者已裁決交接後執行 |
      | B-17 | POST_B01 | 章節語意變更偵測，長效檢查器強化 |
      | B-28 | DEFERRED_BY_USER / POST_B01 — upstream trigger re-evaluated | 上游觸發重新評估確認無 B-01 blocker，維持使用者裁決延後 |
      | B-29 | DEFERRED_BY_USER / POST_B01 — upstream trigger re-evaluated | 同上，完整對照表與機械檢查維持延後 |
      | B-30 | POST_B01 | Playwright 連接埠掃描常數，排批 4 |
      | B-32 | POST_B01 | ADR-0013 觸發詞矩陣重寫，排批 4 |
      | B-33 | POST_B01 | Port 規範缺口，排批 4 |
      | B-53 | POST_B01 | CHECK 4/7 inline 檢查器抽取，不阻擋主線 |
      | B-54 | POST_B01 — existing non-blocking finding routed here | SOP 跨層矛盾守衛，已納入 SOP_12 路徑實例 |
      | B-55 | POST_B01 | 文件時效偵測，排批 2e |
      | B-56 | POST_B01 | SOP_00A 索引維護防呆，排批 2e |
      | B-59 | POST_B01 | ARCHIVE-INDEX 雙向可達性守衛，排批 2d |
      | B-69 | POST_B01 / NONBLOCKING | 跨環境比對原則，已確認為 non-blocking |
      | B-70 | POST_B01 | 配對清單腳本化，non-blocking |
      | B-75 | POST_B01 | Context Economy 範圍已精煉，維持待辦零實作 |
      | B-78 | DEFERRED_BY_USER / POST_B01 | apply_batch 腳本化，延後至主重構後評估 |
      | B-96 | POST_B01 | $$使用者$$ 模式規格已定，未實作 |
      | B-97 | PRE_B01_REQUIRED → SATISFIED | 本次發布審計閘門，審計通過轉已完成 |
      | B-98 | POST_B01 — existing security finding, NONBLOCKING | 執行者外部輸出安全硬化，non-blocking |
      | C-01 | POST_B01 | Port 分配已裁決以 ADR-0017 為準，排批 4 |
      | C-02 | POST_B01 | SOP_02 清歷史已裁決禁 force push，排批 4 |
      | C-03 | POST_B01 | ADR-0013 已裁決逐節處置，排批 4 |
      | C-04 | POST_B01 | Runtime 架構三層方向已裁決，細節待批 6 |
      | C-05 | ARCHIVABLE / COMPLETED | D-01 判定者裁決事項，測試已完成 PASS |
      | C-06 | USER_DECISION_NONBLOCKING | 遠端 main 分支保護策略，待使用者裁決 |
      | E-01 | POST_B01 | 舊技能遷移主線，規劃於 B-01 後執行 |
      | E-02 | POST_B01 | Persona 顧問遷移主線，規劃於 B-01 後執行 |
      | E-03 | POST_B01 | Runtime 執行層遷移主線，規劃於 B-01 後執行 |
      | E-04 | POST_B01 | $$ 指令收斂主線，隨技能遷移執行 |
      | E-05 | POST_B01 | Data 資料層裁決與遷移主線，後續執行 |
      | F-01 | POST_B01 | 三層索引描述漂移，指定為 Jules 首航任務 |
      | F-02 | POST_B01 | 配額熔斷錨定處置，獨立於 B-01 |
      | F-03 | POST_B01 | 多代理自治閉環立案，長遠架構規劃 |
      | F-04 | POST_B01 | karpathy 專案探勘，明確標註低優先 |
      | F-05 | POST_B01 | ADR-0012 補記 SKIP_LOCK，文件微更新 |
      | F-06 | POST_B01 | 歸檔引用更新，runtime 遷移後執行 |

    - **B. 全庫 11 個面向審計結果（11 Repository-Wide Dimensions Audit）**：
      1. **Authority / State Truth**：CLEAR。TASKBOARD 為唯一當前與下一步權威，NEXT_WORK 與 ACTIVE_MACRO_AUDITOR 唯一，零第二佇列。
      2. **Active Control Planes**：CLEAR。層級結構穩固，provider-neutral 資格合約與 A1 雙軌模式成立，rule-traceability fresh 且有效。
      3. **Verification Integrity**：CLEAR。Canonical `verify_all.py` 5 大 Gates 全 PASS，negative canaries 完備，無 false-green。
      4. **Dependency Closure**：CLEAR。`impact_scan.py discover` 對 17 組核心關鍵字完成確定性掃描，無遺漏依賴。
      5. **Git / Remote Truth**：CLEAR。HEAD == origin/main，full clone，exact-SHA Verify Run 35049350295 completed/success。
      6. **B-01 Target Readiness**：CLEAR。ADR-0002/0004/0010 與規範目標檔案全數存在、結構健全、零語意漂移，B-01 程式碼實作確為零。
      7. **Upstream Comparison Freshness**：客觀 trigger 成立（3cca18b -> 959a8e9，+3 commits）；targeted comparison 確認僅涉及 upstream in-progress `retro` 技能之確定性檢查概念，未影響技能架構或 B-01 目標 ADR；判定無 blocker。
      8. **Special-Command / Routing Truth**：CLEAR。11 個 `$$` 路由中 7 個 ACTIVE 且目標存在，4 個 PENDING_MIGRATION 明確標註且未假造完成。
      9. **Security / Machine-Specific State**：全庫掃描零憑證/私鑰洩漏；SOP_12 記錄之本機路徑轉入 B-54 作為 concrete example；B-98 外部輸出安全硬化維持 non-blocking。
      10. **Cross-Environment / Tool Correctness**：CLEAR。一律採用確定性工具與正規化比對，排除 IDE Search false-zero 干擾。
      11. **Mainline Continuation Efficiency**：CLEAR。僅辨識具實質價值之 findings，杜絕投機性治理擴張。
    - **C. 實質發現處置路由（Material Findings Routing per B-95）**：
      - **Finding 1A & 1B (Upstream Trigger)**：路由至 `EXISTING B-28` / `EXISTING B-29`。記錄客觀 trigger 成立與 targeted re-evaluation 結果；維持 DEFERRED_BY_USER / POST_B01。
      - **Finding 2 (Machine-Specific Paths)**：路由至 `EXISTING B-54`。將 SOP_12 第 65、103、111–114 行之本機路徑作為跨層矛盾守衛之第三個實例登錄；維持 POST_B01 / NONBLOCKING。
      - **Finding 3 (Executor Secret Hardening)**：路由至 `EXISTING B-98`。維持 POST_B01 / NONBLOCKING；本批全流程驗證 secret-safe 外部查詢可行。
      - **Finding 4 (Pending-Task Metadata Drift)**：路由至 `CURRENT B-97`。於 TASKBOARD 修正 B-54/55/56/59 中過期之 CHECK 編號與硬編碼數量，落實 B-60 之 machine-derived ID 規範。
    - **D. C-06 遠端現況查證（C-06 Remote Truth）**：
      - 查證 GitHub Ruleset ID 21301111 處於 active 狀態，僅保護 `deletion` 與 `non_fast_forward`；required status checks 為 off，PR-before-merge 非強制；direct fast-forward push 目前技術上仍完全可行。
      - C-06 保持 `USER_DECISION_NONBLOCKING`，待使用者未來需要時裁決 A/B 方案，不阻擋 B-01 發布。
    - **E. 最終發布裁決（Release Decision & Next Step）**：
      - External Macro Reviewer（GPT 代理審查官（使用者授權））正式宣告：
        `PRE-B01 RELEASE STATUS = PASS`
        `B-97 SUBSTANTIVE AUDIT = PASS`
        `B-01 TARGET READINESS = ESTABLISHED`
      - B-97 正式 CLOSED；NEXT_WORK 推進至 B-01。
      - 本 Item 為 historical audit result 留痕，非第二任務佇列；B-01 於本 closure commit 經外部 Macro Audit 通過前仍維持待辦、零實作（NOT STARTED）。

69. **B-01 ADR-0002 / ADR-0004 / ADR-0010 Active-Contract Layering — Implementation Candidate**（2026-09-16）
    - **背景與目標**：B-97 全庫審計與狀態收攏已由 External Macro Reviewer 宣告 PRE-B01 RELEASE STATUS = PASS — FINALIZED（Run 35051382469 success），正式授權 B-01 施工。本批將長久留存於 ADR 留痕層之現行可執行規範搬移至正確 Active Contract 層，達成「ADR = WHY / 歷史決策留痕」與「AGENTS / .agents/rules = WHAT / 現行可執行合約」之分工。
    - **Source → Active 映射落實**：
      - **ADR-0002** → `AGENTS.md §5.1` & `.agents/rules/skills-architecture.md §1`：低風險 buckets（`orchestration/`、`analysis/`、`execution/`、`platform/`）採積極模型呼叫（Proactive Model Invocation）；高風險 bucket（`agents/`）採嚴格保守原則（Conservative Invocation Policy），凡具真實副作用者一律 `disable-model-invocation: true`，不得因「可能有幫助」而放寬。
      - **ADR-0004** → `.agents/rules/skills-architecture.md §2`：指定資料來源與工具失效防護鐵律（Anti-Silent-Substitution Rule），當指定來源失敗或憑證失效時，嚴禁靜默替代為一般 web search，必須失效即停並主動向使用者回報；歷史 4 個分析技能遷移保留條款留痕。
      - **ADR-0010** → `.agents/rules/powershell-encoding-protocol.md §5`：命令列參數與多行文字傳遞協定，嚴禁透過 `$env:*` 傳遞多行文字，優先採寫入 UTF-8 實體檔再傳路徑模式，路徑必須為動態解析之完整絕對路徑（嚴禁硬編碼本機路徑），並警示下游 stdin fallback 造成 process hang 之排查。
    - **ADR Layering Invariant**：
      - 三份 ADR（0002、0004、0010）狀態均維持 `Accepted`，保留完整 Context、事故背景、權衡與決策理由，並在 Decision 節加入現行權威指標（Active Contract Authority）指向對應規範檔案，消除第二權威來源。
    - **依賴探索與驗證（Dependency Discovery & Replay）**：
      - 依 B-68 規範執行 `impact_scan.py discover` 對 25 組關鍵字完成確定性掃描；88 筆匹配路徑完成處置標註；`impact_scan.py check` 重放驗證通過（exact dependency closure matched，UPDATE dependencies ⊆ Allowed Scope）。
    - **當前生命週期狀態**：
      - 本批為 B-01 production implementation candidate，工作區修改僅限授權範圍（6 semantic source/target + 5 state/evidence + generated traceability）。
      - 依規範本批次不宣稱 B-01 CLOSED，TASKBOARD.NEXT_WORK 維持 B-01，等待 External Macro Reviewer（GPT 代理審查官（使用者授權））執行獨立審計。

70. **B-01 Active-Contract Semantic Precedence & Shell Scope — Bounded Repair**（2026-09-16）
    - **背景與外部裁決**：B-01 施工候選 `b2b5d1d` 經 GPT 代理審查官（使用者授權）全面審查，本地與遠端 CI 機構閘門全綠（Verify Run 35053205905 success），但發現兩項現行合約語意矛盾與過度一般化瑕疵，裁決 `MACRO AUDIT = HOLD`、`ACCEPT STATUS = BOUNDED REPAIR REQUIRED`、`FINDING_DISPOSITION = CURRENT B-01`。審計檢查點維持 `76cfe7b`，不得推進 `b2b5d1d`。
    - **發現事項與處置規範**：
      - **F1（呼叫安全優先序與混合風險 Bucket）**：修正 `AGENTS.md §5.1` 與 `.agents/rules/skills-architecture.md §1`，確立單一優先序「個別技能安全閘門優先於 Bucket 積極度（Per-Skill Safety Gate > Bucket Aggressiveness）」。凡具真實外部副作用之技能一律 User-invoked；`platform/` 本質為混合風險（Mixed-Risk），現行 `connect-apps`、`postgres`、`mcp-gateway` 等 User-invoked 技能完全合規；僅有已安全判定為 Model-invoked 之技能方套用積極呼叫指引。
      - **F2（收斂 ADR-0010 巢狀 Shell 參數展開邊界）**：修正 `.agents/rules/powershell-encoding-protocol.md §5`，將環境變數展開風險限縮至 Nested PowerShell / `powershell -Command` / 字串插值等前層解析邊界；使用工具中立之檔案寫入機制；不宣稱所有環境變數在所有情境不可用，亦不宣稱所有 Shell 必提前展開。
    - **當前生命週期狀態**：
      - 本批為 CURRENT B-01 bounded semantic repair，修復成果待 External Macro Auditor 獨立複審；未取得 Macro PASS 前維持 B-01 進行中、NEXT_WORK 維持 B-01。

71. **B-01 Final Macro PASS / Closure Eligibility**（2026-09-16）
    - **背景與審查範圍**：GPT 代理審查官（使用者授權）完成 B-01 全量審查，audited range 為 `76cfe7b115a3913a868a1957cbec704f183b62eb..85d9a3a9efe51e0d361c85149a93901404f2a8f2`（共 2 commits：`b2b5d1d` 初審 Machine PASS / Macro HOLD，`85d9a3a` 完成 F1/F2 bounded semantic repair，F1/F2 於審查範圍內完全解決）。
    - **外部審查裁決**：A1 qualification 採 `A1 = EQUIVALENT`（GitHub API + Executor clone cross-check），exact-SHA Actions Verify Run `35054093786` (status completed, conclusion success)，canonical verification 5 Gates 全過；裁決 `MACRO AUDIT = PASS`，`ACCEPT STATUS = ACCEPT ALL`，`FINDING_DISPOSITION = NONE`；`B-01 = ELIGIBLE FOR CLOSURE`。
    - **結案與推進**：B-01 於本狀態同步批次完成後正式結案（CLOSED / MACRO PASS）；下一階段主線任務依看板與 backlog 佇列推進至 `E-03`（Runtime 執行層 — Phase 1 只讀依賴調研，READ_ONLY DEPENDENCY INVENTORY）；本狀態同步批次零 Runtime 修改（no runtime mutation in this closure batch），E-03 本批維持待辦尚未開始（NOT STARTED）。

72. **E-03 Phase 1 & 1B Read-Only Inventory Review & Phase 2 Wave 1A Implementation Candidate**（2026-09-16）
    - **背景與外部審查結論**：E-03 Phase 1 READ_ONLY 依賴調研與 Phase 1B 修正附錄經 External Macro Reviewer（GPT 代理審查官（使用者授權））全面審查，判定 `E-03 PHASE 1 + PHASE 1B = PASS`，`ACCEPT STATUS = ACCEPT WITH CORRECTED INVENTORY`，正式授權進入 Phase 2。
    - **確定之架構事實修正（Phase 1B Corrected Truths）**：
      - Telegram dist 目錄雖未進版控，但操作腳本 `Start-TelegramBot.ps1` 具備相依性與 build 復原能力。
      - `start_line.js` 非一次性腳本（NOT one-shot），取得控制權並啟動 DB 心跳後，持續執行 `poll_inbox.js` 輪詢直到訊息處理、轉移或失敗退出。
      - 根目錄六進程 `ecosystem.config.js` 非生產拓撲藍圖；現行運行拓撲為 LINE 透過 `Start-LineBot.ps1` 呼叫巢狀 `line-bot-project/ecosystem.config.js` (`line-bridge`)，Telegram 透過 `Start-TelegramBot.ps1` 呼叫巢狀 `telegram-bot-project/ecosystem.telegram.config.js` (`tg-bridge-zero-delay`)。
      - `line-daemon` 為舊版根目錄 PM2 項目，`start_line.js` 本身仍為現行非 PM2 控制器；`tg-daemon` 為衝突/過期拓撲；根目錄 `line-tunnel` 與 `sync-tunnel` 為舊 Cloudflare 鏈路，非現行正常啟動路徑。
      - `Modules/shared/dlpSanitizer.js` 擁有實際 runtime 邏輯，Telegram `dlpSanitizer.ts` 為型別包裝層。
    - **Wave 1A 純共享原語邊界（Zero-Third-Party Shared Pure Primitives）**：
      - 本批刻意限縮於第三方 package 依賴為零之純共享原語，不引入 `package.json`，不建立 npm workspace，不執行 npm install。
      - 建立 `shared/dlpSanitizer.js`（CommonJS 格式相容 legacy DLP 邏輯與排除規則）與 `shared/dlpSanitizer.d.ts`（最小型別宣告，不複製正規表達式）。
      - 建立 `shared/atomicFs.js`（抽取 legacy LINE `reply.js` 與 Telegram `reply_tg.js` 共通之 `writeStateAtomic` 為單一權威實作）。
      - 新增 canonical tracked tests（`scripts/tests/test_shared_primitives.py`）。
      - LINE 架構決策保留至後續處理（nonblocking for Wave 1A）；B-30 與 B-33 確認為後續 live 整合之前置相依，非 Wave 1A 範圍。
    - **當前生命週期狀態**：
      - 本批為 Phase 2 Wave 1A 施工候選，工作區無任何 runtime consumer wiring 或第三方程式庫引入。
      - 本 candidate commit 等待 External Macro Reviewer 獨立審核。

73. **E-03 Channel Gateway Architecture Decision Persistence & Plan Reset（Channel Gateway 單一通訊閘道架構決策持久化與計畫重設）**（2026-09-16）
    - **背景與外部審查結論**：E-03 Phase 2 Wave 1A（`c2df1b0`）建立之純共享原語經 External Macro Reviewer（GPT 代理審查官（使用者授權））全面審查，判定 `A1 = EQUIVALENT` 成立，5 大驗證閘門與 exact-SHA CI 通過，裁決 `MACRO AUDIT = PASS`，`ACCEPT STATUS = ACCEPT ALL`，`FINDING_DISPOSITION = NONE`；Wave 1A 共享原語（`shared/dlpSanitizer.js`、`shared/atomicFs.js`）持續有效。隨後 Phase 1B/1B2 READ_ONLY 調研完成 exact caller census 與 package ownership 修正。
    - **使用者 D1～D26 架構裁決**：專案擁有者（使用者 HH）於 2026-09-16 正式裁決通訊層全面轉型為單一 Channel Gateway 架構，取代舊有 LINE 與 Telegram 雙獨立橋接：
      - 確立目標存放路徑為 `runtime/channel-gateway/`，原先暫訂之 `runtime/telegram-bot/` 於實作前正式廢棄。
      - 維持 Agent-in-the-Loop 與官方合規原則（D2，依官方條款規定排除第三方軟體存取服務風險，不宣稱已證實之停權案例），不採 CDP 注入或 CLI wrapper。
      - 作業系統啟動託管 Gateway 生命週期（D4），Agent 不再啟動通訊進程，ADR-0009 啟動繞道不再為現行規則。
      - 鎖定與職責單元為 Channel，僅明確特權指令具接管意圖，防過期回覆防護，無值守隊列暫存（D5–D10）。
      - LINE 未來目標態採 Cloudflare Worker Mailbox + Pull 模式，廢除穿透隧道；LINE 實作依 D12 延後或由使用者明確觸發（D11–D14）。
      - 獨立極小依賴閉包與 `package.json`，不支援語音訊息，檔案進線正規化交付，外發附件安全傳輸（D15–D18）。
      - 建立手機端雙向檔案外發授權防線、Realpath 檢驗、副本偵測與 Hard Deny List，未授權前預設關閉（D19–D21）。
      - 對話歸檔中心化且僅由 Gateway 寫入，廢除模糊主題比對（D22–D23）。
      - 本機設定中心化，三層代碼清晰劃分，Gateway 管控非重啟熱切換（D24–D26）。
    - **既有 ADR 關聯與實質發現路由（M2–M8）**：
      - 新建 ADR-0022 記錄完整 D1～D26 決策；既有 ADR-0009、ADR-0011、ADR-0015、ADR-0017 原文保留歷史背景。
      - 宏觀審計實質發現 M2～M8 嚴格登錄至既有任務（M2 路由至 E-03+E-04；M3 路由至 B-30+B-33；M4 路由至 E-03；M5 路由至 E-03 SECURITY ACCEPTANCE；M6 路由至 E-03；M7 路由至 E-03+F-05；M8 路由至 E-04/E-03/F-06），零重複任務產生。
    - **當前生命週期狀態**：
      - 本批為 architecture / governance decision persistence，工作區無任何 Gateway 生產程式碼變更（no runtime code in this batch）。
      - Gateway 生產實作尚未開始（NOT STARTED），等待本治理候選通過 External Macro Reviewer 獨立審核。
      - NEXT_WORK 保持 E-03。

74. **E-03 ADR-0022 Canonical Decision Fidelity — Bounded Repair（通訊閘道決策精確度邊界修復）**（2026-09-16）
    - **背景與外部審查結論**：前一治理候選 `2830c7f`（ADR-0022 Channel Gateway 架構決策持久化）經 External Macro Reviewer（GPT 代理審查官（使用者授權））全面審查。Machine verification 5 Gates 全過，exact-SHA Actions Verify Run `35096761114` completed/success（CHECK 1..20 PASS，310 unit PASS，13 webapp PASS）。
    - **外部審查裁決**：`MACRO AUDIT = HOLD`，`ACCEPT STATUS = BOUNDED REPAIR REQUIRED`，`FINDING_DISPOSITION = CURRENT E-03`。審計檢查點維持 `c2df1b0`，不得推進至 `2830c7f`。
    - **發現事項與邊界修復（F1 / F2）**：
      - **F1（D26 帳號切換細節補齊）**：在 `docs/adr/0022-channel-gateway-architecture.md` D26 完整補回使用者已裁決之 12 項子契約（非敏感標籤存本機設定檔、Token/Secret 絕不進庫、IDE 選擇目標帳號、LINE 依剩餘 push quota 由高至低排序、由 Gateway 呼叫 LINE quota API、非重啟熱切換、切換即接管遵守 D7、訊息與接收帳號強綁定、預設未決訊息於 IDE 列出後捨棄、獨立白名單、外發授權帳號綁定、獨立歸檔、測試帳號視為一般登錄帳號、正式 TG 切換前維持預設停用杜絕 409 Conflict）。
      - **F2（D18 LINE 外發附件推播額度影響）**：在 ADR-0022 D18 補明 LINE 外發附件之時效性 HTTPS 下載連結遞送屬 LINE push message，會消耗該 LINE 官方帳號之 push quota，作為 D26 額度展示與排序之架構依據。
    - **當前生命週期狀態**：
      - 本批為 CURRENT E-03 bounded repair，無任何 Gateway 生產程式碼變更（no Gateway production mutation）。
      - Gateway 生產實作尚未開始（NOT STARTED），E-03 維持進行中，NEXT_WORK 保持 E-03。
      - 本修復成果經 External Macro Reviewer 獨立複審判定 MACRO AUDIT = PASS。

75. **E-03 Channel Gateway Architecture Decision Final Macro PASS & Wave 2A Pure Control Core Foundation Candidate**（2026-09-16）
    - **背景與外部審查結論**：前一治理候選與邊界修復（`2830c7f` .. `f522148`，共 2 commits）經 External Macro Reviewer（GPT 代理審查官（使用者授權））全面審查。A1 qualification 採 A1 = EQUIVALENT（GitHub API + Executor clone cross-check）成立；exact-SHA Actions Verify Run 35097747792 completed/success（20 checks PASS，310 unit PASS，13 webapp PASS，5 Gates PASS）。
    - **外部審查裁決**：`MACRO AUDIT = PASS`，`ACCEPT STATUS = ACCEPT ALL`，`FINDING_DISPOSITION = NONE`；F1/F2 於審查範圍內完全解決；`ADR-0022 CHANNEL GATEWAY ARCHITECTURE PERSISTENCE = FINALIZED`；checkpoint 推進至 `f522148`；正式授權開展 Gateway 生產基礎（Gateway production foundation = AUTHORIZED）。
    - **Wave 2A 純控制核心邊界（Pure Control Core Foundation）**：
      - 建立 `runtime/channel-gateway/` 零依賴 package 基礎（`package.json` 與 `package-lock.json`，dependencies = 0，devDependencies = 0，無任何第三方套件）。
      - 實作純領域狀態轉換模型 `core/channel-control.js`（通道鎖定單元、明確接管語意、單調 fencing token、防過期回覆、接管與心跳逾期訊息捨棄/保留語意、無 holder 進線隊列與 backlog 計數）。
      - 實作非敏感帳號註冊模型 `core/account-registry.js`（嚴格白名單 schema、拒絕任意 unknown/secret keys、同一時間至多一個活躍帳號、停用帳號不得啟用、Test Bot 平等地位）。
      - 建立 canonical tracked tests（`tests/channel-control.test.js` 與 `tests/account-registry.test.js`）及 CI 橋接測試（`scripts/tests/test_channel_gateway_core.py`）。
      - 本批嚴禁並無連線 Telegram/LINE、無 HTTP listener、無 Gateway port、無真實金鑰讀取、無 durable persistence、無 attachment transport、無 archive writer、無 LINE Worker。
    - **當前生命週期狀態**：
      - 本批為 Phase 2 Wave 2A 施工候選，工作區僅限於授權之純控制核心與狀態同步。
      - Gateway live 整合尚未開始（NOT STARTED）；LINE 實作依 D12 延後或由使用者明確觸發；B-98 / B-30 / B-33 / F-05 維持開啟狀態於既定前置邊界。
      - 本 candidate 等待 External Macro Reviewer 獨立審核；NEXT_WORK 保持 E-03。

76. **E-03 Channel Gateway Wave 2A Pure Control Core — Bounded Domain Invariant Repair**（2026-09-16）
    - **背景與外部審查結論**：前一施工候選 `278d142`（Wave 2A Pure Control Core Foundation）經 External Macro Reviewer（GPT 代理審查官（使用者授權））全面審查。Machine verification 5 Gates 全過，exact-SHA Actions Verify Run `35099648998` completed/success（CHECK 1..20 PASS，315 unit PASS，13 webapp PASS）。
    - **外部審查裁決**：`MACRO AUDIT = HOLD`，`ACCEPT STATUS = BOUNDED REPAIR REQUIRED`，`FINDING_DISPOSITION = CURRENT E-03`。審計檢查點維持 `f522148`，不得推進至 `278d142`。
    - **發現事項與邊界修復（F1 / F2）**：
      - **F1（AccountRegistry 通道邊界強制）**：修正 `runtime/channel-gateway/core/account-registry.js`，constructor 明確驗證 non-empty channel 字串；accountData 省略 channel 時自動賦予 registry channel；若明確提供 channel 則必須 exact 匹配 registry channel，否則拋出 `CHANNEL_MISMATCH` 錯誤；禁止跨通道登錄。
      - **F2（接收帳號回覆強綁定）**：修正 `runtime/channel-gateway/core/channel-control.js` 之 `authorizeReply(holderId, fencingToken, messageId, replyingAccountId)` API，嚴格要求 replyingAccountId 非空字串；比對 `msg.receivingAccountId === replyingAccountId`，不符則回傳 `ACCOUNT_MISMATCH` 且保持訊息狀態為 CLAIMED，杜絕不同 bot account 代回；一致時方授權並轉為 REPLIED。
    - **當前生命週期狀態**：
      - 本批為 CURRENT E-03 bounded repair，工作區無任何外部副作用（no live bot / network / port / credential work / persistence / transport / listener / OS startup）。
      - Gateway live 整合尚未開始（NOT STARTED），E-03 維持進行中，NEXT_WORK 保持 E-03。
  
77. **E-03 Channel Gateway Wave 2A Final Macro PASS & Wave 2B Pure Account Switch Orchestration Candidate**（2026-09-16）
    - **背景與外部審查結論**：前一施工候選與邊界修復（`f522148` .. `7d379f6`，共 2 commits：`278d142` 與 `7d379f6`）經 External Macro Reviewer（GPT 代理審查官（使用者授權））全面審查。A1 qualification 採 A1 = EQUIVALENT（GitHub API + Executor clone cross-check）成立；exact-SHA Actions Verify Run `35101712841` completed/success（20 checks PASS，315 unit PASS，13 webapp PASS，5 Gates PASS）。
    - **外部審查裁決**：`MACRO AUDIT = PASS`，`ACCEPT STATUS = ACCEPT ALL`，`FINDING_DISPOSITION = NONE`；278d142 F1/F2 於審查範圍內完全解決；`Wave 2A = ACCEPTED`；checkpoint 推進至 `7d379f6`；正式授權開展 Wave 2B 純帳號切換調度（Wave 2B Pure Account Switch Orchestration = AUTHORIZED）。
    - **Wave 2B 純帳號切換調度邊界（Pure Account Switch Orchestration）**：
      - 實作純領域調度器 `runtime/channel-gateway/core/account-switch.js`（`AccountSwitchCoordinator`），嚴格強制註冊表與通道控制器邊界一致（`registry.channel === control.channelId`，不符則 fail-fast 拋出 `CHANNEL_CONTROL_MISMATCH`）。
      - 實作原子式前置檢驗（atomic prevalidation）：目標帳號不存在或停用時 ZERO MUTATION（active account 不變、holder 不變、fencing token 不變、訊息狀態不變）。
      - 貫徹 ADR-0022 D26「切換即接管（Switch = Takeover）」語意：每次成功之帳號選擇或切換均執行 `control.takeover(holderId)` 遞增 fencing token。
      - 實作異帳號切換（A → B）：依 D9 接管捨棄 A 之 CLAIMED 訊息；依 D26 透過最小 pure API `discardQueuedForAccount` 捨棄 A 之 QUEUED 訊息；目標 B 成為 active account；保留 B 原有 QUEUED 訊息；回傳 `discardedOldAccountMessages` 清單供上層呈現。
      - 實作同帳號選擇（A → A）：`accountChanged = false`，執行接管遞增 fencing token，保留 A 原有 QUEUED 訊息（不執行 account change 捨棄）。
      - 實作無前一活躍帳號（null → B）：B 成為 active account，執行接管，保留 B 原有 QUEUED 訊息。
      - 對 `ChannelControl` 擴充最小 pure API `discardQueuedForAccount(receivingAccountId, reason)`，避免 coordinator 直接修改內部陣列。
      - 建立 canonical tracked tests（`tests/account-switch.test.js` 涵蓋 18 項規格驗證）及 Python CI 橋接測試（`scripts/tests/test_channel_gateway_core.py`）。
      - 零外部副作用：無真實金鑰、無 secret、無 network、無 port、無 Telegram API、無 LINE API、無 persistence、無 local config file I/O、無 OS startup。
    - **當前生命週期狀態**：
      - 本批為 Phase 2 Wave 2B 施工候選，工作區僅限於授權之純領域調度核心與狀態同步。
      - Wave 2A = MACRO PASS / ACCEPTED；Wave 2B Pure Account Switch Orchestration = IN PROGRESS / PENDING EXTERNAL MACRO AUDIT。
      - Gateway live 整合尚未開始（NOT STARTED）；B-98 / B-30 / B-33 / F-05 維持開啟狀態於既定前置邊界。
      - 本 candidate 等待 External Macro Reviewer 獨立審核；NEXT_WORK 保持 E-03。

78. **E-03 Channel Gateway Wave 2B Final Macro PASS & Wave 2C Data Location Config Contract Candidate**（2026-09-16）
    - **背景與外部審查結論**：前一施工候選 `fe6baba`（Wave 2B Pure Account Switch Orchestration）經 External Macro Reviewer（GPT 代理審查官（使用者授權））全面審查。A1 qualification 採 A1 = EQUIVALENT（GitHub API + Executor clone cross-check）成立；exact-SHA Actions Verify Run `35103490957` completed/success（20 checks PASS，316 unit PASS，13 webapp PASS，5 Gates PASS）。
    - **外部審查裁決**：`MACRO AUDIT = PASS`，`ACCEPT STATUS = ACCEPT ALL`，`FINDING_DISPOSITION = NONE`；AccountSwitchCoordinator 與切換接管語意全數獲接受；`Wave 2B = ACCEPTED`；checkpoint 推進至 `fe6baba`；正式授權開展 Wave 2C 本機資料路徑配置契約（Wave 2C Data Location Config Contract = AUTHORIZED）。
    - **Wave 2C 本機資料路徑配置契約邊界（Data Location Config Contract）**：
      - 實作純領域驗證模組 `runtime/channel-gateway/core/data-location-config.js`（`validateResolvedDataLocationConfig`，`DATA_LOCATION_SCHEMA_VERSION = 1`）。
      - 嚴格綱要驗證（strict schema）：頂層僅允許 `schemaVersion`（必為 1）與 `dataLocations`；`dataLocations` 僅允許 4 個單例路徑（`archiveRoot`、`attachmentTempRoot`、`stateRoot`、`logsRoot`）與陣列路徑 `protectedRoots`；拒絕任意未知欄位與敏感憑證欄位。
      - 跨平台絕對路徑檢驗（cross-platform absolute path validation）：使用 `path.win32.isAbsolute(v) || path.posix.isAbsolute(v)`，確保 Windows 與 POSIX 合法路徑在跨平台環境均能確定性驗證；嚴格拒絕相對路徑、空字串與空白字串。
      - 不變性保證（immutability）：不修改輸入物件，回傳字串已修剪、陣列已淺拷貝之正規化複本。
      - 設定範本建立：`runtime/channel-gateway/config.example.json` 採顯式佔位符（`__ARCHIVE_ROOT__` 等），不含真實本機路徑、金鑰或帳號資訊。
      - 建立 canonical tracked tests（`tests/data-location-config.test.js` 涵蓋 16 項規格驗證）及 Python CI 橋接測試（`scripts/tests/test_channel_gateway_core.py`）。
      - 純領域驗證邊界：零第三方套件依賴，無檔案系統讀寫、無環境變數存取、無目錄建立、無路徑存在性/權限檢查、無憑證載入、無 Bot 帳號、無網路監聽/Port、無作業系統啟動服務。
    - **當前生命週期狀態**：
      - 本批為 Phase 2 Wave 2C 施工候選，工作區僅限於授權之純路徑配置契約與狀態同步。
      - Wave 2B = MACRO PASS / ACCEPTED；Wave 2C Data Location Config Contract = IN PROGRESS / PENDING EXTERNAL MACRO AUDIT。
      - Gateway live 整合尚未開始（NOT STARTED）；B-98 / B-30 / B-33 / F-05 維持開啟狀態於既定前置邊界。
      - 本 candidate 等待 External Macro Reviewer 獨立審核；NEXT_WORK 保持 E-03。

79. **E-03 Channel Gateway Wave 2C Final Macro PASS & Wave 2D Repo-External Config Loader Candidate**（2026-09-16）
    - **背景與外部審查結論**：前一施工候選 `aa0977f9c56c31a6963a86de0d08318c1b1d5716`（Wave 2C Data Location Config Contract）經 External Macro Reviewer（GPT 代理審查官（使用者授權））全面審查。A1 qualification 採 A1 = EQUIVALENT（GitHub API + Executor clone cross-check）成立；exact-SHA Actions Verify Run `35105625352` completed/success（20 checks PASS，317 unit PASS，13 webapp PASS，5 Gates PASS）。
    - **外部審查裁決**：`MACRO AUDIT = PASS`，`ACCEPT STATUS = ACCEPT ALL`，`FINDING_DISPOSITION = NONE`；validateResolvedDataLocationConfig 純領域契約獲全面接受；`Wave 2C = ACCEPTED`；checkpoint 推進至 `aa0977f`；正式授權開展 Wave 2D 外部設定載入與啟動路徑驗證（Wave 2D Repo-External Config Loader + Startup Path Validation = AUTHORIZED）。
    - **Wave 2D 外部設定載入與啟動路徑驗證邊界（Repo-External Config Loader + Startup Path Validation）**：
      - 實作受控檔案讀取模組 `runtime/channel-gateway/core/local-config-loader.js`（`loadDataLocationConfigFromFile`、`validateStartupDataLocations`）。
      - 顯式絕對路徑契約：configPath 必須為顯式傳入之非空白絕對路徑，不猜測路徑、不讀 process.env、不自動 fallback 至 template。
      - 儲存庫外部強邊界（repo-external enforcement）：以名義路徑與 canonical realpath 雙重檢驗 configPath 是否位於 repoRoot 內部；symlink 外部指入 repo 嚴格拒絕。
      - 啟動路徑驗證：驗證 4 個寫入根目錄（archiveRoot, attachmentTempRoot, stateRoot, logsRoot）存在、為目錄且具備讀寫權限；protectedRoots 至少 1 個 entry 且存在、為目錄、具讀取權限；零自動建立（zero mkdirSync）；回傳 realpathSync 正規化路徑物件，不修改原輸入。
      - 建立 canonical tracked tests（`tests/local-config-loader.test.js` 涵蓋 21 項測試）及更新 Python CI 橋接測試（`scripts/tests/test_channel_gateway_core.py`）。
      - 零第三方依賴：僅使用 node:fs 與 node:path；零環境變數讀取；零真實憑證；零網路/Port；零持久化訊息佇列。
    - **當前生命週期狀態**：
      - 本批為 Phase 2 Wave 2D 施工候選，工作區僅限於授權之本機設定載入與啟動路徑檢驗。
      - Wave 2C = MACRO PASS / ACCEPTED；Wave 2D Repo-External Config Loader + Startup Path Validation = IN PROGRESS / PENDING EXTERNAL MACRO AUDIT。
      - Gateway live 整合尚未開始（NOT STARTED）；B-98 / B-30 / B-33 / F-05 維持開啟狀態於既定前置邊界。
      - 本 candidate 等待 External Macro Reviewer 獨立審核；NEXT_WORK 保持 E-03。

80. **E-03 Channel Gateway Wave 2D Final Macro PASS & Wave 2E Atomic Durable State Store Candidate**（2026-09-16）
    - **背景與外部審查結論**：前一施工候選 `eac38683a76d482ba8edf80d325aaecd952d9fe0`（Wave 2D Repo-External Config Loader + Startup Path Validation）經 External Macro Reviewer（GPT 代理審查官（使用者授權））全面審查。A1 qualification 採 A1 = EQUIVALENT（GitHub API + Executor clone cross-check）成立；exact-SHA Actions Verify Run `35107752002` completed/success（20 checks PASS，318 unit PASS，13 webapp PASS，5 Gates PASS）。
    - **外部審查裁決**：`MACRO AUDIT = PASS`，`ACCEPT STATUS = ACCEPT ALL`，`FINDING_DISPOSITION = NONE`；local-config-loader 外部檔案載入與啟動路徑驗證契約獲全面接受；`Wave 2D = ACCEPTED`；checkpoint 推進至 `eac38683`；正式授權開展 Wave 2E 本機持久化狀態儲存基礎（Wave 2E Atomic Durable State Store Foundation = AUTHORIZED）。
    - **Wave 2E 本機持久化狀態儲存基礎邊界（Atomic Durable State Store Foundation）**：
      - 實作本機持久化狀態儲存原語 `runtime/channel-gateway/core/durable-state-store.js`（`DurableStateStore`）。
      - 建構子強制 stateRoot 存在、為目錄且具備讀寫權限，取得 canonical realpath，零目錄自動建立（zero mkdirSync），固定狀態檔名 `channel-gateway-state.json` 杜絕 path traversal。
      - 嚴格版號封套（envelope schema）：`schemaVersion: 1`、`revision`（非負安全整數）、`payload`（非空純物件），拒絕任意未知頂層金鑰。
      - 遞迴 JSON 相容性驗證：嚴格檢驗 payload 內容，拒絕 undefined、function、symbol、BigInt、NaN、Infinity、循環參照或 Date/Map/Set/類別實例，杜絕 silent drop。
      - 讀取狀態：檔案不存在時回傳 null（代表初次啟動無狀態）；存在時透過 lstat 阻擋符號連結、檢驗正規檔案與 realpath 邊界，解析失敗或格式異常一律 fail-closed，不自動修復或刪除損毀檔案。
      - 寫入狀態：嚴格重用 `shared/atomicFs.js`（`writeStateAtomic`）進行跨平台原子更名寫入，版本號自 1 起算單調遞增（N -> N + 1）。
      - 建立 canonical tracked tests（`tests/durable-state-store.test.js` 涵蓋 28 項測試）及更新 Python CI 橋接測試（`scripts/tests/test_channel_gateway_core.py`）。
      - 純儲存原語邊界：零領域連結（無 ChannelControl、AccountRegistry、AccountSwitchCoordinator 載入邏輯或重啟策略），零 process.env，零憑證，零網路/Port，零 OS 啟動服務。
    - **當前生命週期狀態**：
      - 本批為 Phase 2 Wave 2E 施工候選，工作區僅限於授權之本機狀態儲存原語與狀態同步。
      - Wave 2D = MACRO PASS / ACCEPTED；Wave 2E Atomic Durable State Store Foundation = IN PROGRESS / PENDING EXTERNAL MACRO AUDIT。
      - Gateway live 整合尚未開始（NOT STARTED）；B-98 / B-30 / B-33 / F-05 維持開啟狀態於既定前置邊界。
      - 本 candidate 等待 External Macro Reviewer 獨立審核；NEXT_WORK 保持 E-03。

81. **E-03 Channel Gateway Wave 2E Initial Audit Result & Lossless JSON Validation Bounded Repair**（2026-09-17）
    - **候選與外部審查結論**：前一施工候選 `0959d0afd8c0197005d1fdc9d016fdce5eda2b17`（Wave 2E Atomic Durable State Store Foundation）經 External Macro Reviewer（GPT 代理審查官（使用者授權））全面審查。A1 qualification 採 A1 = EQUIVALENT（GitHub API + Executor clone cross-check）成立；exact-SHA Actions Verify Run `35117776121` completed/success（20 checks PASS，319 unit PASS，13 webapp PASS，5 Gates PASS）。
    - **外部審查裁決與材料瑕疵**：`MACRO AUDIT = HOLD`，`ACCEPT STATUS = BOUNDED REPAIR REQUIRED`，`FINDING_DISPOSITION = CURRENT E-03`；Findings：F1 為 Lossless JSON payload validation incomplete: `validateJsonCompatiblePayload()` 原先對物件採 `Object.keys()` 遍歷，無法拒絕 symbol-keyed 屬性、不可列舉（non-enumerable）屬性或 accessor getter/setter 等可能被 `JSON.stringify` 靜默遺失或竄改之狀態；checkpoint 保持 `eac38683`，維持 E-03 進行中並執行微修。
    - **無損 JSON 屬性檢驗微修邊界（Lossless JSON Own-Property Validation Repair）**：
      - 修改 `runtime/channel-gateway/core/durable-state-store.js`：
        - 採用 `Reflect.ownKeys` 嚴格檢查所有自有屬性，拒絕任何 Symbol 鍵名（`typeof key === 'symbol'`）。
        - 檢查每個自有屬性的 property descriptor：必須為普通資料屬性（data descriptor），嚴格拒絕 accessor 屬性（getters/setters），且必須為可列舉（`enumerable === true`）。
        - 嚴格陣列檢驗：禁止陣列子類別實例、禁止 Symbol 鍵、禁止稀疏陣列洞（sparse holes）、禁止索引 accessor 或非可列舉索引、禁止額外命名屬性（如 `arr.extra = 1`）。
        - 封套 `validateEnvelope` 同步採用 `Reflect.ownKeys` 杜絕未知屬性或 non-enumerable/symbol/accessor 注入。
      - 擴充 canonical tests（`tests/durable-state-store.test.js` 新增測試 29 至 40，全檔共 40 tests 全數通過）。
      - 純微修邊界：零領域連結（無 domain hydration / restart recovery），零外部副作用（no live bot / network / port / credential / OS startup）。
    - **當前生命週期狀態**：
      - 本批為 Phase 2 Wave 2E 微修候選，工作區僅限於授權之無損 JSON 驗證與狀態同步。
      - Wave 2D = MACRO PASS / ACCEPTED；Wave 2E = MACHINE PASS / MACRO HOLD / BOUNDED REPAIR。
      - Gateway live 整合尚未開始（NOT STARTED）；B-98 / B-30 / B-33 / F-05 維持開啟狀態於既定前置邊界。
      - 本 repair candidate 自身等待 External Macro Reviewer 獨立審核；NEXT_WORK 保持 E-03。

82. **E-03 Channel Gateway Wave 2E Final Macro PASS & Wave 2F Channel Control Durable Snapshot Candidate**（2026-09-17）
    - **背景與外部審查結論**：前一微修候選 `994c455d435bda6c72138706f8f16faa7c036776`（E-03 Enforce Lossless Durable JSON State）經 External Macro Reviewer（GPT 代理審查官（使用者授權））全面審查。審查範圍為 `eac38683a76d482ba8edf80d325aaecd952d9fe0..994c455d435bda6c72138706f8f16faa7c036776`（共 2 commits：0959d0a 初審 Machine PASS / Macro HOLD，F1 由 994c455 徹底修復）。A1 qualification 採 A1 = EQUIVALENT（GitHub API + Executor clone cross-check）成立；exact-SHA Actions Verify Run `35158545662` completed/success（20 checks PASS，319 unit tests PASS，13 webapp tests PASS，5 Gates PASS）。
    - **外部審查裁決**：`MACRO AUDIT = PASS`，`ACCEPT STATUS = ACCEPT ALL`，`FINDING_DISPOSITION = NONE`；0959d0a F1 完全解決；`Wave 2E = ACCEPTED`；checkpoint 推進至 `994c455`；NEXT_WORK 保持 E-03；正式授權開展 Wave 2F 通道控制持久化快照與安全重啟復原（Wave 2F Channel Control Durable Snapshot & Safe Restart Recovery = AUTHORIZED）。
    - **Wave 2F 快照與安全重啟復原邊界（Channel Control Durable Snapshot & Safe Restart Recovery）**：
      - 實作快照與重啟復原純領域模組 `runtime/channel-gateway/core/channel-state-recovery.js`。
      - 嚴格快照綱要（`CHANNEL_SNAPSHOT_SCHEMA_VERSION = 1`）：僅允許 `schemaVersion`、`channelId`、`fencingToken`、`messages`，嚴格刻意排除 `currentHolder` 與 `lastHeartbeatAt`，杜絕重啟後復活舊 holder 或 heartbeat freshness。
      - 訊息快照正規化與無損驗證：所有訊息僅允許正規欄位（`id`, `receivingAccountId`, `status`, `claimedBy`, `claimedAtToken`, `discardReason`, `metadata`, `discardedByHolder`, `discardedAtToken`），未用欄位以 null 表達，拒絕未知鍵；使用 Wave 2E `validateJsonCompatiblePayload` 檢驗 metadata；依 status 嚴格檢驗狀態不變量（QUEUED 無 claim/discard；CLAIMED 之 token 與 snapshot fencingToken 完全相符；REPLIED/DISCARDED token 不得超過 snapshot fencingToken）。
      - 匯出快照（`buildChannelControlSnapshot`）：驗證輸入為 ChannelControl 實例，產生深度複製之純 JSON 物件，不暴露內部引用。
      - 安全重啟復原（`recoverChannelControlFromSnapshot`）：嚴格驗證 untrusted snapshot 物件（不 mutate 輸入）；建立新 `ChannelControl`，恢復 `fencingToken`（不歸零、不額外遞增），重設 `currentHolder = null`、`lastHeartbeatAt = null`；深度復原訊息：`QUEUED` 訊息維持保留（符合 D10 unattended backlog）；`CLAIMED` 訊息依 D9 安全語意轉為 `DISCARDED`（`discardReason = 'GATEWAY_RESTART'`，記錄 `discardedByHolder` 與 `discardedAtToken`），並回傳安全通知後設資料 `discardedOnRecovery`（不含 body）；`REPLIED` 與既有 `DISCARDED` 訊息維持終態。
      - 柵欄連續性（Fencing continuity）：復原後保持原 token N，舊 holder 嘗試 poll/reply 一律遭拒；下一次合法 takeover 時推進為 N + 1，確保舊 token 徹底過期。
      - 積壓語意（Backlog semantics）：復原後 backlog 僅計算 QUEUED 訊息，重啟捨棄之 CLAIMED 訊息不計入 backlog。
      - 刻意延後與純領域邊界：零 `AccountRegistry` 持久化或水合；零自動存檔/讀檔連線（無 automatic transition-to-file wiring）；零第三方依賴；零網路/Port/Token/Secret/OS startup/Timer。
      - 建立 canonical tracked tests（`tests/channel-state-recovery.test.js` 涵蓋 32 項測試）及更新 Python CI 橋接測試（`scripts/tests/test_channel_gateway_core.py`，全庫 7 份測試套件）。
    - **當前生命週期狀態**：
      - 本批為 Phase 2 Wave 2F 施工候選，工作區僅限於授權之通道控制快照與安全重啟復原。
      - Wave 2E = MACRO PASS / ACCEPTED；Wave 2F Channel Control Durable Snapshot & Safe Restart Recovery = IN PROGRESS / PENDING EXTERNAL MACRO AUDIT。
      - Gateway live 整合尚未開始（NOT STARTED）；B-98 / B-30 / B-33 / F-05 維持開啟狀態於既定前置邊界。
      - 本 candidate 等待 External Macro Reviewer 獨立審核；NEXT_WORK 保持 E-03。

83. **E-03 Channel Gateway Wave 2F Initial Audit Result & Pre-Clone Metadata Validation Bounded Repair**（2026-09-17）
    - **候選與外部審查結論**：前一施工候選 `e1f06fda449dc8140cc45e49599f65fa1453e804`（Wave 2F Channel Control Durable Snapshot & Safe Restart Recovery）經 External Macro Reviewer（GPT 代理審查官（使用者授權））全面審查。A1 qualification 採 A1 = EQUIVALENT（GitHub API + Executor clone cross-check）成立；exact-SHA Actions Verify Run `35159917238` completed/success（20 checks PASS，320 unit PASS，13 webapp PASS，5 Gates PASS）。
    - **外部審查裁決與材料瑕疵**：`MACRO AUDIT = HOLD`，`ACCEPT STATUS = BOUNDED REPAIR REQUIRED`，`FINDING_DISPOSITION = CURRENT E-03`；Findings：F1 為 LIVE METADATA VALIDATED AFTER LOSSY CLONE：`buildChannelControlSnapshot()` 原先在對訊息 metadata 執行 `JSON.parse(JSON.stringify(msg.metadata || {}))` 深拷貝後，才在 snapshot 層級呼叫驗證函式，導致 live JavaScript 物件中之 undefined 屬性、Symbol 鍵、不可列舉屬性、accessor getters、Date 或自訂 toJSON 可能在嚴格驗證前已被 serializer 靜默遺失或竄改；checkpoint 保持 `994c455`，維持 E-03 進行中並執行微修。
    - **複製前無損 Metadata 驗證微修邊界（Pre-Clone Lossless Metadata Validation Repair）**：
      - 修改 `runtime/channel-gateway/core/channel-state-recovery.js`：
        - 新增 `cloneValidatedMetadata(metadata, pathStr)` 輔助函式，強制在任何 `JSON.stringify`、`JSON.parse` 或深拷貝前，先驗證原始 live metadata。
        - 嚴格型別檢驗：metadata 必須為非 null 純物件（`proto === Object.prototype || proto === null`），嚴格拒絕陣列或非物件實例；杜絕 `msg.metadata || {}` 容錯回退（fail-closed）。
        - 呼叫 `validateJsonCompatiblePayload(metadata, new Set(), pathStr)` 針對原始 live metadata 進行自有屬性與描述元完整檢驗，杜絕 symbol 鍵、非可列舉屬性、getter/setter accessor、自訂 toJSON、Date/Map/Set/class 實例或循環參照。
        - 僅在原始物件檢驗通過後，始執行無損深拷貝（`JSON.parse(JSON.stringify(metadata))`）。
        - 保留快照整體雙層驗證：`cloneValidatedMetadata` 前置檢查 ＋ `validateChannelControlSnapshot` 後置整體結構檢驗。
      - 擴充 canonical tests（`tests/channel-state-recovery.test.js` 新增測試 33 至 41，全檔共 41 tests 全數通過）。
      - 純微修邊界：零領域契約擴大（`channel-control.js` 與 `durable-state-store.js` 零修改），零外部副作用（no live bot / network / port / credential / OS startup）。
    - **當前生命週期狀態**：
      - 本批為 Phase 2 Wave 2F 微修候選，工作區僅限於授權之複製前 metadata 驗證與狀態同步。
      - Wave 2E = MACRO PASS / ACCEPTED；Wave 2F = MACHINE PASS / MACRO HOLD / BOUNDED REPAIR。
      - Gateway live 整合尚未開始（NOT STARTED）；B-98 / B-30 / B-33 / F-05 維持開啟狀態於既定前置邊界。

84. **E-03 Channel Gateway Wave 2F Final Macro PASS & Wave 2G Multi-Channel Durable State Persistence Bridge Candidate**（2026-09-17）
    - **Wave 2F 外部審查結論**：前一微修候選 `750eaeb160eae2b4f29801ba04d53d1452a59275`（E-03 Validate Live Metadata Before Snapshot Clone）經 External Macro Reviewer（GPT 代理審查官（使用者授權））全面審查。A1 qualification 採 A1 = EQUIVALENT（GitHub API + Executor clone cross-check）成立；exact-SHA Actions Verify Run `35170928666` completed/success（20 checks PASS，320 unit PASS，13 webapp PASS，5 Gates PASS）；e1f06fd F1 於審查範圍內完全解決；MACRO AUDIT = PASS，ACCEPT STATUS = ACCEPT ALL，FINDING_DISPOSITION = NONE；Wave 2F = ACCEPTED；accepted checkpoint 推進至 `750eaeb160eae2b4f29801ba04d53d1452a59275`；NEXT_WORK 保持 E-03。
    - **Wave 2G 多通道持久化橋接實作（Multi-Channel Durable State Persistence Bridge）**：
      - 建立持久化橋接模組 `runtime/channel-gateway/core/channel-state-persistence.js`，將 `DurableStateStore` 與 `ChannelControl` 快照/安全復原無縫組裝為多通道單元。
      - 多通道持久化綱要（`CHANNEL_STATE_PAYLOAD_SCHEMA_VERSION = 1`）：頂層僅允許 `schemaVersion`（exact 1）與 `channels`（陣列），陣列中每個元素必須通過 `validateChannelControlSnapshot()` 嚴格快照檢驗，且通道識別碼 `channelId` 嚴格禁止重複（杜絕同通道狀態衝突）。
      - 確定性規範排序（Canonical Lexical Sort）：持久化前依 `snapshot.channelId` 進行確定性字面排序，避免因通道寫入順序差異造成無意義的檔案變更；內部訊息序列維持既有穩定排序。
      - 持久化儲存庫（`DurableChannelStateRepository`）：以依賴注入方式接收 `DurableStateStore` 實例，禁止模組自行讀取組態或建立路徑。
      - 單一通道安全儲存（`saveChannel(control)`）：前置呼叫 `buildChannelControlSnapshot(control)`，確保若 live metadata 不合法，在讀寫持久化檔案前即立即拋錯失敗（fail-closed）；讀取既有 envelope（若無檔案則以空 channels 起始），替換當前 channelId 之快照或追加新快照，嚴格保留其他所有通道快照；經綱要驗證後呼叫 `store.save(nextPayload)` 恰好一次，回傳 operation summary。
      - 跨通道完整性（Cross-channel preservation）：機械保證儲存 Telegram 不影響 LINE，儲存 LINE 亦不遺失 Telegram；杜絕 last-writer-wins 覆蓋全庫通道狀態。
      - 初次啟動與通道載入（`loadOrCreateChannel(channelId)`）：檔案不存在時回傳 `firstStart = true` 且不建立空檔案；檔案存在但找不到該通道時回傳 `firstStart = true` 且不破壞其他通道亦不自動儲存；通道存在時透過 `recoverChannelControlFromSnapshot` 安全復原。
      - 重啟轉換單次立即回寫（Persist restart conversion exactly once）：若重啟復原產生 `discardedOnRecovery`（CLAIMED → DISCARDED / GATEWAY_RESTART），在回傳 control 前立即建立新快照、替換該通道、保留其他通道、回寫持久化檔案並標記 `recoveryPersisted = true`，使 revision 正確遞增 1；若回寫失敗則 fail-closed 拒絕回傳 usable control；再次載入同一檔案時為純讀取復原（Read-only recovery idempotence），不重複捨棄亦不遞增 revision。
      - 純讀取復原不遞增修訂版次（Read-only recovery idempotence）：無 CLAIMED 轉換時不觸發寫入，維持原版次，避免無意義之 revision bump。
      - 嚴格失敗關閉（Strict failure fail-closed）：既有檔案若綱要不符、重複 channelId、未知鍵或損毀，一律 fail-closed，嚴禁忽略或部分修復。
      - 邊界嚴格控制：零 `AccountRegistry` 持久化或水合；零 transition 自動綁定（no transition auto-wiring）；零 monkey-patch；零網路/Port/Token/Secret/OS startup/Timer。
      - 建立 canonical tracked tests（`tests/channel-state-persistence.test.js` 涵蓋 30 項測試，全庫 8 份 Node 測試共 188 tests 全數通過）及更新 Python CI 橋接測試（`scripts/tests/test_channel_gateway_core.py`）。
    - **當前生命週期狀態**：
      - 本批為 Phase 2 Wave 2G 施工候選，工作區僅限於授權之多通道持久化橋接。
      - Wave 2F = MACRO PASS / ACCEPTED；Wave 2G Multi-Channel Durable State Persistence Bridge = IN PROGRESS / PENDING EXTERNAL MACRO AUDIT。
      - Gateway live 整合尚未開始（NOT STARTED）；B-98 / B-30 / B-33 / F-05 維持開啟狀態於既定前置邊界。
      - 本 candidate 等待 External Macro Reviewer 獨立審核；NEXT_WORK 保持 E-03。

85. **E-03 Wave 2G Final Macro PASS, T1 Windows node:sqlite Technical Spike & SQLite State Route Governance Landing (T2+T4+T5)**（2026-09-17）
    - **Wave 2G 外部審查結論**：前一施工候選 `b15d5bf9aae59f06e5db12d3438a4e9e2a43102d`（E-03 Add Multi-Channel Durable State Bridge）經 External Macro Reviewer（GPT 代理審查官（使用者授權））全面審查。A1 qualification 採 A1 = EQUIVALENT（GitHub API + Executor clone cross-check）成立；Wave 2G = ACCEPTED；accepted checkpoint 推進至 `b15d5bf`；NEXT_WORK 保持 E-03。
    - **T1 Windows node:sqlite Technical Spike 成果**：
      - 依使用者 D28 裁決，正式實作 SQLite 前在 Windows 實體環境進行完整技術驗證（READ_ONLY spike，零 repo mutation，工作區於外部 scratch）。
      - 測試環境：Windows 11 (10.0.26200)，SSD，Windows Defender Antivirus & Realtime Protection ENABLED，Global Node v24.18.0，Portable Node v24.21.0，SQLite 3.53.4。
      - 驗證結果：TECHNICAL GATE = GO，D28 REQUIRED GATE = SATISFIED。
      - 核心指標：
        - V1（內建模組可用性）：Node built-in `node:sqlite` 與 `DatabaseSync` 成功載入（PASS）。
        - V2（外鍵與嚴格綱要）：`foreign_keys=ON`、`PRAGMA synchronous=FULL`、`PRAGMA journal_mode=WAL`、STRICT 綱要與外鍵約束全部生效（PASS）。
        - V3（寫入延遲）：單列提交 p50 0.98ms / p95 2.56ms / p99 3.44ms（門檻 <20ms）；claim50 交易 p50 1.26ms / p95 3.78ms / p99 7.18ms（門檻 <50ms）（PASS）。
        - V4（行程崩潰一致性）：200 次隨機 kill 迴圈中，未提交交易皆無殘留（200/200 UNCOMMITTED_ABSENT），已提交交易全部完整保留（200/200 COMMITTED_PRESERVED），零重複訊息，資料庫完整性檢驗全數通過（200/200 INTEGRITY_OK）（PASS）。
        - V5（長時間並發讀寫壓力）：606 秒持續壓力，2,326 次寫入交易，19,406 次讀取查詢，SQLITE_BUSY = 0，未復原鎖定錯誤 = 0，WAL checkpoint PASS，關閉後 shm/wal 控制代碼正常釋放（PASS）。
        - V6（路徑守衛）：OneDrive 路徑自動拒絕，UNC 網路路徑自動拒絕，本機資料目錄允許（PASS）。
        - V7（本機具名管道互斥，參考用途）：同名管道第二次 listen 觸發 `EADDRINUSE`，但 ACL 與遠端連線安全為 NOT_TESTABLE；因此 V7 僅屬 partial reference evidence，絕不得解讀為 named pipe approved，R3 維持 USER DECISION PENDING。
        - V8（線上熱備份）：`VACUUM INTO` 線上備份 500 列資料，備份檔 integrity_check = ok（PASS）。
      - 過程發現（Non-blocking Findings）：
        - F1（腳本讀取環境變數偏離）：T1 輔助腳本使用了 `os.environ.get('LOCALAPPDATA')` 且一次將 scratch 路徑輸出至 transcript，違反原始規格之不得讀取/輸出 env 變數值；但因無 credential 洩漏且技術數據不受影響，判定為 non-blocking to technical GO，作為現有 B-98 hardening 之額外證據，不另立重複 task，B-98 維持 pending。
        - F2（R3 裁決未定）：V7 不能作為 R3 裁決依據，R3 保持待使用者裁決。
    - **使用者重大裁決（User Decisions D27–D30）**：
      - D27：Gateway 運作與控制狀態改採 `node:sqlite` 為唯一 authoritative state source，目標取代現有 JSON 持久化層（`durable-state-store.js`、`channel-state-recovery.js`、`channel-state-persistence.js`）。對話歷史存檔（D22）與附件（D17）仍屬檔案系統，不屬 SQLite 狀態契約。
      - D28：正式實作前需通過 Windows spike，現已 GO 且滿足。
      - D29：Wave 2H 停止且不得恢復，不得建立 `durable-channel-controller.js`；commit boundary 改由未來 SQLite 交易（T7）實現。
      - D30：治理採分層架構（ADR 決策理由 + scoped AGENTS 現行規則 + mechanical enforcement + future operational SOP）；本批落實前兩層與 repo state sync，SOP 延後建立。
    - **治理落實（Governance Landing T2 + T4 + T5）**：
      - 新增 ADR-0023（`docs/adr/0023-channel-gateway-state-store-sqlite.md`）：Accepted，記錄 D27–D30、T1 spike 實機數據、取代 ADR-0022 之 JSON snapshot choice（不修改 ADR-0022 歷史本文）、凍結現存 JSON 模組為 transitional frozen assets、明確 R2/R3 undecided。
      - 新增目錄層級治理規則 `runtime/channel-gateway/AGENTS.md`：規範唯一運作狀態來源、PRAGMA 契約（WAL, FULL, foreign_keys, busy_timeout 啟動時 read-back 驗證 fail-closed）、交易邊界（commit 成功始回傳）、幂等進線（`UNIQUE(account_id, platform_msg_id)`）、SQL 安全（禁字串拼接）、前向綱要遷移與驗證備份、備份禁 raw copy（採 VACUUM INTO）、路徑守衛（禁 OneDrive/UNC）、Node 前置限制（待 T3 落地）、與 D22/D17 檔案系統例外。
      - 泛化根目錄 `AGENTS.md` §6a 為通用 Directory-Scoped Rules；修正 §9 過時之「沒有 npm run test」陳述，確立 `verify_all.py` 為全庫唯一標準入口，service-local tests（如 Gateway `npm test`）透過 canonical bridge 納入。
    - **當前生命週期狀態**：
      - E-03 進行中（IN PROGRESS）。
      - accepted checkpoint = `b15d5bf`。
      - 後續排程：T3/T17（.nvmrc / CI Node version pin / 自動測試探索）→ T6（SQLite repository 實作）→ T7（交易邊界）→ T8（幂等進線）→ T9（淘汰 JSON 模組）。
      - Gateway live 整合尚未開始（NOT STARTED）；R2 與 R3 維持 USER DECISION PENDING；B-98 維持 pending。

86. **E-03 SQLite State Governance Initial Macro Review & R2/R3 Decision-Routing Bounded Repair**（2026-09-17）
    - **前一施工候選審查結論**：前一施工候選 `90dc71ce88e90e3c0bc48e385206f2c0528682c7`（E-03 Land SQLite State Governance）經 External Macro Reviewer（GPT 代理審查官（使用者授權））全面審查。A1 qualification 採 A1 = EQUIVALENT（GitHub API + Executor clone cross-check）成立；exact-SHA Actions Verify Run `35182239616` completed/success（20 checks PASS，321 unit PASS，13 webapp PASS，5 Gates PASS）。
    - **外部審查裁決與材料瑕疵**：`MACRO AUDIT = HOLD`，`ACCEPT STATUS = BOUNDED REPAIR REQUIRED`，`FINDING_DISPOSITION = CURRENT E-03`；Findings：F1 為 R2 / R3 USER-DECISION SEMANTICS MISROUTED IN ADR-0023：`docs/adr/0023-channel-gateway-state-store-sqlite.md` 第 7 節誤將 R2 寫為本地 IPC 協定選型、將 R3 寫為單一實例與連線授權，偏離使用者權威裁決定義；checkpoint 保持 `b15d5bf`，維持 E-03 進行中並執行微修。
    - **決策路徑保真度微修邊界（Decision-Routing Fidelity Repair）**：
      - 修正 `docs/adr/0023-channel-gateway-state-store-sqlite.md` 第 7 節：
        - **R2（回覆結果不明時的處理 / Reply Result Uncertainty Handling）**：確立其用途為在 future outbound/outbox Wave 之前由使用者裁決；原研究文件之文字/檔案重送建議僅為參考指引，不得提升為已接受決策；維持 `USER DECISION PENDING`。
        - **R3（本機 API 形式 / Local API Form）**：候選架構明確為 Windows 具名管道（Named Pipe）vs Loopback API（搭配本機 Token、Host 白名單與拒絕 Origin 標頭）；重申 V7 項目同名二次監聽引發 EADDRINUSE 僅為局部參考證據，ACL 安全檢查與遠端連線行為在 Windows 實機為 `NOT_TESTABLE`，不足以核准具名管道；維持 `USER DECISION PENDING`。
      - 保持所有已確立之 SQLite 治理不變（D27 唯一狀態權威、D28 Windows spike GO、D29 Wave 2H 取消、D30 分層治理、JSON 模組過渡凍結、T3 版本釘選前置、PRAGMA WAL/FULL/foreign_keys 啟動 read-back 驗證、交易邊界、冪等進線、前向綱要遷移、備份禁 raw copy、路徑守衛禁 OneDrive/UNC）。
      - 未修改根目錄 `AGENTS.md` 或 `runtime/channel-gateway/AGENTS.md`，未修改歷史 `ADR-0022` 本文，零生產代碼修改。
    - **當前生命週期狀態**：
      - 本批為 E-03 治理微修候選，工作區嚴格限於 R2/R3 決策路徑保真度修復與狀態同步。
      - E-03 進行中（IN PROGRESS）。
      - accepted checkpoint 保持 `b15d5bf`。
      - Gateway live 整合尚未開始（NOT STARTED）；R2 與 R3 維持 USER DECISION PENDING；B-98 維持 pending。
      - 本修復候選等待 External Macro Reviewer 獨立審核，不得 self-audit。
