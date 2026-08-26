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
| 技能遷移 | 31 個（7 bucket） | ✅ || `bot-account-switcher` | 已遷移至 `skills/agents/` | ✅ || ADR 決策留痕 | 13 份 | ✅ |
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
| `tool-executor` | `03_Execution/` | `skills/execution/` | 被多個技能引用 |
| `playwright-automation` | `03_Execution/` | `skills/execution/` | |
| `theme-factory` | `03_Execution/` | `skills/execution/` | |
| `image-enhancer` | `03_Execution/` | `skills/execution/` | |
| `ui-prototype-builder` | `03_Execution/` | `skills/execution/` | description 過長需拆 REFERENCE.md |
| `langsmith-fetch` | `03_Execution/` | `skills/platform/` | |
| `gemma-4-api` | `03_Execution/` | `skills/execution/` 或 `platform/` | description 已於初期修復 |
| `skill-creator` | `03_Execution/` | `skills/meta/` | 跟 `nuwa-skill` 職責可能重疊，需評估 |
| `workspace-migration-recovery` | `03_Execution/` | `skills/meta/` | 可用來驗證本次遷移完整性 |
| `frontend-developer` | `02_Cognitive/` | `skills/execution/` | |
| `sentiment-scout` | `02_Cognitive/` | `skills/analysis/` | frontmatter 有格式錯誤需修 |
| `declarative-visual-intent-generator` | `02_Cognitive/` | `skills/execution/` | |
| `json-to-flex-renderer` | `02_Cognitive/` | `skills/platform/` | 與 `markdown_to_flex.js` 邏輯可能重疊 |
| `epistemic-state-governor` | `02_Cognitive/` | `skills/orchestration/` | |
| `dynamic-tool-synthesizer` | `02_Cognitive/` | `skills/meta/` | persona 呼叫鏈的關鍵環節 |
| `subagent-collaboration-skill` | `01_Orchestrators/` | `skills/orchestration/` | 被 `agency-orchestrator` 引用 |
| `autoresearch-agent` | `01_Orchestrators/` | `skills/agents/` | `$$自動化_微型模型$$` 路由目標 |
| `recursive-research-automation` | `01_Orchestrators/` | `skills/orchestration/` | `$$自動化_通用研究$$` 路由目標 |
| `quant-research-loop` | `01_Orchestrators/` | `skills/analysis/` | `$$自動化_量化實驗$$` 路由目標 |
| `cost-benefit-router` | `01_Orchestrators/` | `skills/orchestration/` | 取代已廢的 `quota-monitor-skill` |
| **`shared-bot-utils`** | `03_Execution/` | **待評估** | **本次新發現**：含 `textNormalizer.js`、`mediaDownloader.js`，是 LINE/TG 共用工具，可能該進 `shared/` 而非 `skills/` |

#### A-2. 確定不遷移

| 技能 | 原因 |
|---|---|
| `global-workspace` | 已被 `agency-orchestrator` 取代（標記 legacy_notice） |
| `quota-monitor-skill` | 已被 `cost-benefit-router` 取代 |
| `canvas-design` | 已被 `ui-prototype-builder` 取代 |
| `optimization-status` | 動態實驗日誌偽裝成技能，非真正技能 |
| `episodic-consolidation` | 已合併進 `agency-orchestrator`（ADR-0006） |
| `reflection-module` | 已合併進 `agency-orchestrator`（ADR-0006） |
| `self-improvement` | 已合併進 `skill-evolution-governor`（ADR-0006） |
| `skill-governance-skill` | 已合併進 `skill-evolution-governor`（ADR-0006） |
| `handover-manual-skill` | 已合併進 `setup-hhai-skills` |
| `twse-dev-sop-skill` | 已合併進 `setup-hhai-skills` |
| `temp_images` | 執行期暫存圖片，非技能 |
| `skills/Archive/**` | 舊架構封存，逐一評估後只有少數值得復活（見 A-3） |

#### A-3. Archive 裡值得評估復活的

`chip-logic-expert`（籌碼邏輯）、`macro-linkage`（總體聯動）、`ownership-cluster`（股權群聚）——
這三個是現行技能樹沒有、但對台股分析可能有價值的分析維度，需要使用者決定。

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
- Flex Message 格式化（`markdown_to_flex.js` + `json-to-flex-renderer` 可整併）
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

**更新紀錄**：
- 2026-08-25: `bot-account-switcher` 遷移至 `skills/agents/` 完成。
- 2026-08-26: evidence-collector 等 6 個 analysis 型技能遷移完成。
