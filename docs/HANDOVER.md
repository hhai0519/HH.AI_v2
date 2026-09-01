# HH.AI_v2 重構專案 — 完整交接手冊

> 產出日期：2026-08-28
> 產出者：Claude（宏觀審計官角色，見 ADR-0007）
> 用途：供接手者（新的 Claude 對話、其他 AI、或人類）完整掌握專案狀態與工作方法

---

## 目錄

1. [專案概述](#1-專案概述)
2. [資料來源](#2-資料來源)
3. [從頭到尾做了什麼](#3-從頭到尾做了什麼)
4. [已完成項目與細節](#4-已完成項目與細節)
5. [未完成項目與細節](#5-未完成項目與細節)
6. [已處理的風險](#6-已處理的風險)
7. [未處理的風險](#7-未處理的風險)
8. [使用者的工作習慣](#8-使用者的工作習慣)
9. [與 Antigravity IDE Agent 協作規範](#9-與-antigravity-ide-agent-協作規範)
10. [Antigravity Agent 的已知出錯模式與風險評估](#10-antigravity-agent-的已知出錯模式與風險評估)
11. [Claude 自身的已知失誤](#11-claude-自身的已知失誤)
12. [接手第一步該做什麼](#12-接手第一步該做什麼)

---

## 1. 專案概述

### 目標

把舊專案 `HH.AI_260806` 的 AI 技能庫，重構遷移到新專案 `HH.AI_v2`，
採用 mattpocock/skills 風格的七桶（bucket）架構。

**最終目標**：`HH.AI_v2` 完全取代 `HH.AI_260806` 成為使用者唯一的工作系統。
在重構完成前，使用者持續使用舊系統，不切換。

### 系統性質

這不只是「股票分析系統」，而是使用者的**萬能總管**——處理日常所有事項的
AI 代理系統。台股分析只是其中一個領域。

### 三方角色分工

| 角色 | 職責 |
|---|---|
| **Claude**（本手冊產出者） | 宏觀審計官（ADR-0007）。親自查證舊 repo 原始檔、產出給 Antigravity 的提示詞、獨立 clone 核對執行結果。**不接受口頭回報，一律驗證實際檔案** |
| **Antigravity IDE Agent** | 在使用者本機執行實際檔案操作與 git 指令 |
| **使用者（HH）** | 在兩者之間傳遞訊息、做架構決策、執行 Claude 無法做的操作（GitHub 網頁操作、環境設定） |

**關鍵約束**：Claude 沒有使用者本機的存取權，只能 clone 公開 repo；
Antigravity 有本機權限但沒有獨立查證能力（它自己的回報不可全信）。
這個分工是刻意設計，見 ADR-0007。

### 七桶架構（ADR-0001）

| Bucket | 定位 |
|---|---|
| `orchestration/` | 流程調度、任務路由、狀態機（無副作用） |
| `analysis/` | 分析與判斷（純分析，不執行外部動作） |
| `agents/` | RARV 執行型，有真實副作用（發訊息／寫檔／下單）→ 需 `authorized_mcp_tools` + `disable-model-invocation: true` |
| `execution/` | 16 | d3js-visualization、webapp-testing、mcp-engineer、pdf、xlsx、csv-data-summarizer、artifacts-builder、changelog-generator、systematic-debugging、tool-executor、frontend-developer、declarative-visual-intent-generator、gemma-4-api、image-enhancer、theme-factory、playwright-automation |
| `platform/` | 平台整合（LINE／Telegram／MCP／Postgres） |
| `meta/` | 造技能的技能、治理類 |
| `deprecated/` | 已棄用，不維護 |

---

## 2. 資料來源

### 兩個 GitHub Repo（皆為公開，可直接 clone）

| Repo | 用途 | 狀態 |
|---|---|---|
| `https://github.com/hhai0519/HH.AI_260806` | 舊專案，遷移來源 | **唯讀**，不做任何寫入 |
| `https://github.com/hhai0519/HH.AI_v2` | 新專案，遷移目標 | 主要工作區 |

**重要**：Claude 可以直接執行 `git clone --depth 1 <url>` 查證兩個 repo，
不需要請使用者貼終端機輸出。這是 ADR-0007 定義的獨立查證方式。

### 本機路徑（Antigravity 操作用）

```
C:\Users\HH.AI_260806\Desktop\HH.AI_260806\   （舊）
C:\Users\HH.AI_260806\Desktop\HH.AI_v2\        （新）
C:\Users\HH.AI_260806\.gemini\config\mcp_config.json   （MCP 設定，不在版控）
```

注意：`HH.AI_260806` 同時是**專案名稱**與 **Windows 使用者名稱**，
路徑中出現時要判斷是哪一個，不要誤改。

### 專案內的關鍵文件

| 文件 | 用途 |
|---|---|
| `HH.AI_v2/AGENTS.md` | 架構規範（七桶定義、SKILL.md 格式、frontmatter 規則） |
| `HH.AI_v2/docs/refactor-backlog.md` | 進度與待辦清單（**接手必讀**） |
| `HH.AI_v2/docs/adr/` | 20 份架構決策紀錄 |
| `HH.AI_v2/.agents/rules/` | 4 份 workspace 規則（Antigravity 自動載入） |
| `HH.AI_v2/SOP/` | 10 份操作流程 + `SOP_00A_Master_Index.json`（`$$` 指令權威路由表） |
| `HH.AI_v2/scripts/validate_skills.py` | 唯一的自動化驗證工具 |

### 使用者提供的外部資料

使用者陸續提供了大量歷史文件（上傳到對話），包含：
- 多份 SOP14 審計報告、壓力測試報告、沙盒測試報告
- LINE / Telegram 雙平台連線的診斷與執行計畫（多個版本）
- 全系統交接手冊、`.env.local` 內容、MCP 設定
- Cloudflare Worker 原始碼、Jules 相關報告

**這些文件的關鍵資訊已經轉化為 ADR-0009 至 ADR-0017**，
原始檔案不在 repo 內，若需要細節要請使用者重新提供。

### 架構設計的外部參考來源

本次重構的架構設計，參考了以下外部專案。逐一附上採用決策：

| 來源 | 網址 | 採用狀態 |
|---|---|---|
| **mattpocock/skills** | `https://github.com/mattpocock/skills` | ✅ **主要架構參考**。七桶分類法、per-folder `AGENTS.md`、精簡優先的設計哲學皆源自此 |
| **anthropics/skills** | `https://github.com/anthropics/skills` | ✅ **官方規格來源**。SKILL.md frontmatter 規則（kebab-case、長度上限、欄位白名單）已整合進 `validate_skills.py` |
| **obra/superpowers** | `https://github.com/obra/superpowers` | ✅ 部分採用。task artifact 追蹤機制寫入遷移指令稿；觸發積極度分級記於 ADR-0002 |
| **ImL1s/oh-my-agy** | `https://github.com/ImL1s/oh-my-agy` | ✅ 部分採用。per-folder `AGENTS.md` 模式、ADR 文件模式；未安裝整套 CLI |
| **ImL1s/antigravity_for_loop** | `https://github.com/ImL1s/antigravity_for_loop` | ❌ 不採用。2026-08 已歸檔，Antigravity 2.0 移除其 CDP 依賴的 UI 介面 |
| **Germain-L/Send2Jules**（= Antigravity Jules Bridge） | `https://github.com/Germain-L/Send2Jules` | ❌ **已停用**。原為 ADR-0003 採用方案，2026-08-29 改採 Google 官方 `@google/jules` CLI 與 `@google/jules-mcp`（ADR-0019 取代 ADR-0003） |
| **sajidmahamud835/antigravity-jules-integration** | `https://github.com/sajidmahamud835/antigravity-jules-integration` | ❌ 不採用。手動 vendor 路線，金鑰會明文寫入 `mcp_config.json`（ADR-0003 決策理由） |
| **jacob-bd/gemini-notebook-mcp-cli** | `https://github.com/jacob-bd/gemini-notebook-mcp-cli` | ✅ 使用中。即 `notebooklm-mcp-cli` pip 套件，對應 `platform/notebooklm-mcp` 技能 |
| **alchaincyf/nuwa-skill** | `https://github.com/alchaincyf/nuwa-skill` | ⏳ **待採用**。「女媧造人」persona 生成技能。官方 `examples/` 有 15 個 A 級完整範例（429-541 行，保真度 89-97 分），與本專案 15 個 persona 清單**完全一致**，可直接採用官方版本填充 |
| **optimistengineer/remoat**（= antigravity-telegram-remote） | `https://github.com/optimistengineer/remoat` | ⚠️ **已 vendored 在舊 repo**。`telegram-bot-cdp-bridge/telegram-bot-project/` 即此專案（179 檔）。使用者在其中加入自製的 `reply_tg.js` 等橋接腳本，故不能直接改用 npm 安裝 |
| **lackeyjb/playwright-skill** | `https://github.com/lackeyjb/playwright-skill` | ⚠️ **已 vendored 在舊 repo**。即 `03_Execution/playwright-automation`，MIT 授權，author: lackeyjb |
| **karpathy/autoresearch** | `https://github.com/karpathy/autoresearch` | ⚠️ **已 vendored 並改造**。舊 repo 的 `01_Orchestrators/autoresearch-agent` 即此專案的 CPU 移植版（上游僅支援單張 NVIDIA GPU，作者明示暫不支援 CPU）。`prepare_cpu.py`／`train_cpu.py`／`program_cpu.md` 對應上游三檔；`auto_optimize_controller.py` 與 `results.tsv` 為本專案自製的背景控制器與日誌，上游無對應物。MIT 授權，遷移時適用 ADR-0018 |
| **frostant/awesome-claude-skills** | `https://github.com/frostant/awesome-claude-skills` | ❌ 不整合。半年未更新，僅作 bookmark |
| **MIBlue119/claude-code-harness-blog** | `https://github.com/MIBlue119/claude-code-harness-blog` | ❌ 不整合。靜態文件站，閱讀參考用 |
| **carvel-dev/secretgen-controller** | `https://github.com/carvel-dev/secretgen-controller` | ❌ 完全無關。K8s 工具，早期誤列 |

### 已識別的 vendored 外部資產

以下技能實際上是外部專案的副本，**尚無標示規則**（`AGENTS.md` 缺這條，
可能需補 ADR）：

| 技能 | 來源 | 授權 | 狀態 |
|---|---|---|---|
| `telegram-bot-cdp-bridge` 內的 `telegram-bot-project` | `optimistengineer/remoat` v0.2.14 | — | 完整 vendored + 使用者自製腳本 |

**遷移時應統一決定標示方式**，例如在 frontmatter 補 `license` 欄位
（可參照官方 theme-factory 的寫法：`license: Complete terms in LICENSE.txt`）。

### 官方文件參考

| 主題 | 網址 |
|---|---|
| Claude Agent Skills 規格 | `https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview` |
| Anthropic 使用量與長度限制 | `https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work` |
| Claude Code 模型與用量 | `https://support.claude.com/en/articles/14552983-models-usage-and-limits-in-claude-code` |
| Jules（Google 雲端 AI 代理） | `https://jules.google.com` ／ 文件 `https://jules.google/docs` |
| Cloudflare Worker（本專案的 LINE 門面） | `https://line-proxy.hh-ai-19850519.workers.dev`（部署中） |

### 使用者的 NotebookLM 筆記本（Claude 無法存取）

使用者曾提供三個 NotebookLM 連結，內含 LINE/TG 架構的歷次改版資料。
**這些是需要 Google 帳號登入的私人筆記本，Claude 無法讀取**
（網站也擋自動存取）。若需要其中資訊，須請使用者手動摘錄。

- `https://notebook.google.com/notebook/b16a1fb5-2ca1-4665-89ce-2cfb324d0de9`
- `https://notebook.google.com/notebook/2522bbdf-3743-4689-a73d-5bb0a7d861ee`
- `https://notebook.google.com/notebook/e2e7b0a1-a20c-42a7-94e2-1b0bc3015d35`

---

## 3. 從頭到尾做了什麼

依時間順序的完整工作紀錄：

### 階段一：架構設計與骨架建立

- 研究 `mattpocock/skills`、`anthropics/skills`、`obra/superpowers`、
  `ImL1s/oh-my-agy` 等 15+ 個 GitHub repo
- 確立七桶分類法（ADR-0001）、觸發積極度分級（ADR-0002）
- 建立 `HH.AI_v2` 骨架：`AGENTS.md`、`MISSION.md`、7 個 bucket 的
  `AGENTS.md` 與 `README.md`、`validate_skills.py`、ADR 模板
- 評估 Jules 整合方式，決定用官方擴充套件而非 vendor 原始碼（ADR-0003）

### 階段二：技能審計與批次遷移

- 修復 5 個空白 description（`connect-apps`、`csv-data-summarizer`、
  `gemma-4-api`、`notebooklm-mcp`、`xlsx`）
- diff 11 組重名技能（現行版 vs Archive 版），發現 4 個技能遺失
  「NotebookLM 研究遵從指示」鐵律（ADR-0004）
- 分批遷移各 bucket 技能，每批經過三層核對（ADR-0005）
- 合併類技能處理：`episodic-consolidation` + `reflection-module`
  → `agency-orchestrator`；`self-improvement` + `skill-governance-skill`
  → `skill-evolution-governor`（ADR-0006）
- 冗餘掃描：查證三組疑似重複的技能，全部確認為分工而非重複，
  意外發現「雙平行系統」架構（ADR-0008）

### 階段三：SOP 處理

- 逐份分析 22 份 SOP，決定去向
- 10 份遷移、3 份轉 ADR（ADR-0011/0012/0013）、8 份淘汰、
  1 份持續運作（`SOP_00A`）
- 建立 `$$` 指令權威路由表，清掉 4 個幽靈指令

### 階段四：LINE/TG 雙平台診斷

- 實機診斷 LINE 完全不通的根因（ADR-0015）
- 對照 Telegram 健康狀態，得出「失效點數量決定穩定度」的核心洞察
- 將實戰教訓轉為 ADR-0009（Windows Job Object）、
  ADR-0010（PowerShell 參數傳遞）、ADR-0014（PM2 設定檔地雷）

### 階段五：安全事件處理

- 發現 `temp_mcp.json` 含明文 GitHub PAT 與 Notion Token（本機未推送）
- 用 `git reset --soft` 清除，強化 `.gitignore`
- 分析三道資安防線為何全部失效（ADR-0016）
- 建立 MCP 環境重建指南（`docs/mcp-environment-guide.md`）

### 階段六：Jules 分支整合

- 處理 Jules（Google 雲端 AI 代理）產出的 12 個分支
- 11 個合併、1 個評估後不採用
- 引入專案首批自動化測試：**0 → 30 個**（第二批處理後累積至 41 個，見 §4.6）
- 12 個 GitHub PR 全數關閉並留言說明

### 階段七：Port 規範與雜項

- 確立 port 分配規範（ADR-0017）
- 修正 `jules-integration` 的過時額度資訊（5 次 → 100 次）
- 清理舊 repo 的執行期產物與子 repo 干擾

---

## 4. 已完成項目與細節

### 4.1 技能遷移：54 個

| Bucket | 數量 | 技能清單 |
|---|---|---|
| `analysis/` | 14 | financial-analyst、investment-researcher、tech-analyzer、pe-river-map、evidence-collector、software-architect、backend-architect、data-engineer、devops-engineer、twse-market-logic、sentiment-scout、quant-research-loop、ownership-cluster、macro-linkage |
| `execution/` | 16 | d3js-visualization、webapp-testing、mcp-engineer、pdf、xlsx、csv-data-summarizer、artifacts-builder、changelog-generator、systematic-debugging、tool-executor、frontend-developer、declarative-visual-intent-generator、gemma-4-api、image-enhancer、theme-factory、playwright-automation |
| `orchestration/` | 10 | active-inference、agency-orchestrator、security-auditor、stock-orchestrator、reality-checker、real-time-stream-orchestrator、subagent-collaboration、recursive-research-automation、cost-benefit-router、epistemic-state-governor |
| `agents/` | 6 | jules-integration、investment-aggregator、twse-data-analyst、market-researcher、line-interaction-manager、bot-account-switcher |
| `platform/` | 6 | connect-apps、postgres、notebooklm-mcp、mcp-gateway、langsmith-fetch、json-to-flex-renderer |
| `meta/` | 2 | skill-evolution-governor、setup-hhai-skills |
| `deprecated/` | 0 | （尚無） |

**完成度**：舊 repo 66 個現行技能中，49 個已遷移（含 5 個去除 `-skill`
後綴的改名遷移）、10 個確定不遷移、7 個待遷移。新 repo 共 54 個技能
＝ 49 個遷移自舊 repo ＋ 5 個新建／復活／合併產生
（`jules-integration`、`macro-linkage`、`ownership-cluster`、
`setup-hhai-skills`、`skill-evolution-governor`）。

### 4.2 ADR：20 份

| 編號 | 主題 |
|---|---|
| 0001 | 七桶分類法 |
| 0002 | 技能觸發積極度分級 |
| 0003 | Jules 整合走官方擴充套件，不 vendor 原始碼 |
| 0004 | 補回 4 個分析技能遺失的 NotebookLM 鐵律 |
| 0005 | 高風險技能的三層核對流程 |
| 0006 | orchestration 技能合併決策 |
| 0007 | **宏觀審計官角色定位**（核心方法論） |
| 0008 | 雙平行系統架構（Loki Swarm vs 深度研究工具組） |
| 0009 | Windows Job Object 進程回收，啟動須單一 Task 串接 |
| 0010 | PowerShell 參數傳遞陷阱 |
| 0011 | 雙平台連線架構演進史 |
| 0012 | 分散式悲觀鎖機制 |
| 0013 | Watchdog 非同步錯誤暫存（Neon DB） |
| 0014 | PM2 設定檔三地雷與沙盒先行驗證 |
| 0015 | **LINE 隧道鏈路斷裂與雙平台失效點對照** |
| 0016 | **憑證外洩的三道防線失效分析** |
| 0017 | Port 分配規範 |
| 0018 | vendored 外部資產保留 fork，並以三層方式標示 |
| 0019 | **Jules 整合改採官方 CLI 與 MCP，取代 ADR-0003** |

### 4.3 Workspace 規則：4 份（`.agents/rules/`）

| 檔案 | 內容 |
|---|---|
| `skills-architecture.md` | 技能架構強制規則 |
| `git-and-reporting.md` | **Git 操作與回報紀律**（含三次踩坑紀錄） |
| `skill-engineering-guardrails.md` | 四大架構防禦條款 |
| `powershell-encoding-protocol.md` | 跨平台編碼協定 |

### 4.4 SOP：10 份 + 索引

遷移的 10 份：SOP_01、02、04、05、06、09、11、12、13、14
另有 `SOP_00A_Master_Index.json`（`$$` 指令權威路由表，11 條有效路由）
與 `SOP/README.md`（含 12 份淘汰／轉換 SOP 的去向紀錄）

### 4.5 自動化測試：41 個（從 0 開始）

| 檔案 | 測試數 | 覆蓋 |
|---|---|---|
| `scripts/tests/test_validate_skills.py` | 28 | `parse_frontmatter`(8)、`validate_name`(5)、`validate_description`(7)、`validate_bucket_structure`(1)、`validate_skill`(1)、`main`(3)、`report_results`(3) |
| `skills/execution/webapp-testing/tests/test_with_server.py` | 13 | `start_server_process`(4)、command injection 防護(1)、`is_server_ready`(3)、`main`(5) |

**驗證方式**：Claude 於每一批合併後獨立 clone 並在自身環境執行全部測試，
不接受執行端的回報數字。並用「故意失敗測試」確認驗證邏輯未在重構中失效。

**未受測試覆蓋的檔案**：`skills/execution/webapp-testing/examples/element_discovery.py`
位於 `examples/`，無測試覆蓋，變更時以 `python3 -m py_compile` 與
括號配對檢查驗證。

### 4.6 Jules 分支整合：兩批共 24 個全數處理

**已合併（11 個）**：
- 2 個安全修正：`with_server.py` command injection、d3js tooltip XSS
- 3 個效能優化：平行啟動、行數計算、element discovery
- 2 個重構：`validate_skills.py` 拆函式、移除未用 import
- 4 個測試分支（手動整合，非 rebase）

**不採用（1 個）**：`refactor-with-server-script` — 基於修正前的舊版重構，
其 `server_manager` 仍帶 `shell=True`，合併會把已修好的漏洞改回。
**分支保留在遠端不刪除**，供日後查閱。

**12 個 PR 全數 closed**（非 merged），每個都留言說明處理方式。

**第二批 12 個分支（2026-08-29 處理完畢）**

依檔案交集分為五組，同組內依序合併。**7 個合併（含 3 個部分合併）、
5 個評估後不採用**。測試由 30 增至 41。逐組的處置與理由見
`docs/refactor-backlog.md`「三之二」章節。

四條累積的審查教訓：

1. **純刪除型分支最容易與同批新增型分支互斥**——移除未使用的 import
   看似最安全，但被刪的項目可能正是別的分支即將使用的。
   第 3 組的 `remove-unused-pytest-import` 即因此不採用。
2. **行為改動與其斷言必須成對合併**——第 4 組的 `optimize-server-polling`
   同時改了實作與對應斷言，只合其中一邊必定測試失敗。
3. **效能優化常夾帶語意變化**——把 Playwright locator API 換成瀏覽器原生
   API 可消除 IPC 往返，但可見性與文字擷取語意並不等價。
   第 1 批的按鈕與第 5 組的連結都屬此類，皆已在程式碼中加註語意差異說明。
4. **夾帶檔案已發生四次**（三次根目錄 `tests/`、一次根目錄
   `benchmark_element_discovery.py`）。`.gitignore` 的樣式擋不住任意檔名，
   **必須在 `git status` 閘門人工攔截**。

### 4.7 其他產出

- `docs/refactor-backlog.md` — 逐項查證過的完整待辦清單
- `docs/mcp-environment-guide.md` — 6 個 MCP server 的重建指南
- `requirements.txt` — Python 相依（pytest、playwright）

---

## 5. 未完成項目與細節

### 5.1 待遷移技能：7 個

| 技能 | 舊位置 | 預計去向 | 阻塞原因／注意事項 |
|---|---|---|---|
| `line-bot-zero-delay` | `03_Execution/` | `platform/` | **等 runtime 架構決策**。內嵌 12 檔 Node.js 專案（`line-bot-project/`） |
| `telegram-bot-cdp-bridge` | `03_Execution/` | `platform/` | **等 runtime 架構決策**。內嵌 vendored 開源專案 `remoat`（179 檔） |
| `ui-prototype-builder` | `03_Execution/` | `execution/` | 683 行、4 個子目錄，規模最大，建議獨立一批 |
| `skill-creator` | `03_Execution/` | `meta/` | 與 `nuwa-skill` 職責可能重疊，需評估 |
| `workspace-migration-recovery` | `03_Execution/` | `meta/` | 可用來驗證本次遷移完整性 |
| `dynamic-tool-synthesizer` | `02_Cognitive/` | `meta/` | persona 呼叫鏈的關鍵環節 |
| `autoresearch-agent` | `01_Orchestrators/` | `agents/` | `$$自動化_微型模型$$` 路由目標。含 `SKIP_LOCK` 機制（ADR-0012 未記載）。遷移注意：`program_cpu.md` 是人類調校用的技能文件不是資料檔；`*.bak` 兩檔不遷移；為 `karpathy/autoresearch` 的 CPU 改造版，適用 ADR-0018 標示規則 |

（另有 `shared-bot-utils` 待評估歸屬，可能該進 `shared/` 而非 `skills/`）

### 5.2 攔截項（兩項已裁決，一項待裁決）

**攔截項一：`theme-factory` 的 legacy 衝突 — ✅ 2026-08-29 已裁決**

裁決結果：移除 `legacy_notice`，遷入 `skills/execution/`。
查證依據：`ui-prototype-builder` 全文 693 行中「主題」僅出現 1 次且為無關語境，
不具備 theme-factory 的 10 組預設主題與 CSS Token 生成器；該 legacy 字串與
`canvas-design` 一字不差，屬整批誤貼；且已有三個現役技能依賴 theme-factory。
`AGENTS.md` §8.3 規則本身維持不變。詳見 `refactor-backlog.md` 三、第 7 點。

**攔截項二：`playwright-automation` 與 `webapp-testing` 重疊 — ✅ 2026-08-29 已裁決**

裁決結果：劃界共存，不合併。`playwright-automation` 負責完整 E2E 測試框架，
`webapp-testing` 負責快速即時調試。響應式多裝置截圖統一由前者提供，
後者改為指向。不合併的硬性理由：`playwright-automation` 是 MIT 完整 vendored
套件，合併會破壞上游可追溯性（ADR-0018）。

**攔截項三：runtime 層架構選擇（ADR-0015）**

三個選項，需使用者拍板：
1. **改用固定網址的隧道服務**（Cloudflare Named Tunnel，需自有網域）
   — 四個環節縮成一個，最少失效點
2. **完成 Worker 方案** — 重寫遺失的 `start_line_tunnel.js`，
   移除 `bridge.js` 直接覆寫 LINE Webhook 的邏輯
3. **不遷移 LINE 通道** — Telegram 已滿足需求的話

### 5.3 Persona 認知顧問：15 個（階段一可立即做）

- 位置：`HH.AI_260806/Data/personas/`（15 個資料夾，1.8MB）
- **架構決策已定**：維持「設定檔而非技能」定位，不放進 `skills/`
- **現況**：`references/` 調研資料完整（含一手／二手來源標註），
  但 `SKILL.md` 全部停在 36 行模板骨架，`name` 欄位全是 `updated-persona`
- **階段一**（可立即做）：建立 `personas/` 目錄，遷移調研資料 +
  `invocation_guide.md`，保全資產
- **階段二**（需另立專案）：重建呼叫鏈。目前斷點：
  - `global-workspace`（攔截 `persona_target`）→ 已淘汰
  - `persona-distiller`（蒸餾器）→ 從未存在
  - `dynamic-tool-synthesizer`（知識編譯）→ 尚未遷移
  - `Persona Knowledge MCP`（讀取工具）→ 不存在於 `mcp_config.json`
- **相關工具**：`nuwa-skill`（github.com/alchaincyf/nuwa-skill，MIT）
  官方提供 15 個 A 級完整範例（429-541 行，保真度 89-97 分），
  與本專案 15 個 persona 清單完全一致，可直接採用官方版本填充

### 5.4 runtime / shared 層（尚未開始）

**核心問題**：生產環境的執行程式目前住在「技能文件資料夾」裡。

`ecosystem.config.js` 的 PM2 六大進程來源：

| PM2 進程 | 實際腳本 | 備註 |
|---|---|---|
| `line-bridge` | `skills/03_Execution/line-bot-zero-delay/line-bot-project/bridge.js` | 在 skills/ 內 |
| `tg-bridge-zero-delay` | `skills/03_Execution/telegram-bot-cdp-bridge/telegram-bot-project/dist/bin/cli-zero-delay.js` | 編譯後產物 |
| `line-daemon` | `skills/03_Execution/line-bot-zero-delay/line-bot-project/start_line.js` | 在 skills/ 內 |
| `tg-daemon` | `scripts/tg_daemon.js` | **路徑在 `args` 不在 `script`** |
| `line-tunnel` | `_archive_legacy_docs/bin/cloudflared.exe` | **從「封存舊文件」資料夾執行生產程式** |
| `sync-tunnel` | `scripts/sync_tunnel_url.js` | **路徑在 `args`** |

所有進程的 `out_file`／`error_file` 都指向 `Data/logs/`，該目錄必須一併遷移。

**已識別的共用模組候選**（`shared/`）：
- `Modules/shared/dlpSanitizer.js`（已存在，註解明寫「同時服務 LINE 與 TG」）
- `Modules/shared/workspaceLoader.js`（已存在）
- `skills/03_Execution/shared-bot-utils/`（`textNormalizer.js`、`mediaDownloader.js`）
- `writeStateAtomic()`（`reply.js` 與 `reply_tg.js` 重複實作）
- Flex Message 格式化（`markdown_to_flex.js` + `json-to-flex-renderer`）
- Redlock／AGENT_TRANSFER 控制權邏輯（`db_state_manager.js`）

**關鍵發現**：`poll_inbox.js` 與 `poll_tg.js` 是同一套邏輯的雙胞胎，
差異只有 port（3000 vs 3001）與訊息標籤（`[LINE_REQUEST]` vs `[TG_REQUEST]`），
可抽出共用輪詢核心。

### 5.5 其他待辦

| 項目 | 說明 |
|---|---|
| **舊 repo 1 個未推送 commit** | `968bb6d chore: purge runtime artifacts...`，等使用者換完金鑰才能推 |
| **pre-commit hook** | ADR-0016 記錄的缺口，`HH.AI_v2` 目前無任何 commit 前憑證檢查 |
| **LINE/TG 遠端免確認設定** | 遠端下指令時 MCP 授權會跳確認視窗，失去遠端操作意義 |
| ~~**Agent 操控 Jules**~~ | ✅ 2026-08-29 解除。官方 MCP 提供 `list_sessions`、`get_session_state` 等 8 組工具，可直接查詢（ADR-0019） |
| **`ADR-0012` 補 `SKIP_LOCK`** | `autoresearch-agent` 用 `SKIP_LOCK=1` 繞過全域鎖，ADR-0012 未記載 |
| **vendored 外部資產標示規則** | `theme-factory`（Anthropic 官方）、`remoat`（第三方）缺標示規範，`AGENTS.md` 無此條，可能要補 ADR |
| **Payload 淨化規則詞彙不一致** | 舊分層詞彙（`Cognitive`／`Execution` 型）的**行為指令**尚存 **6 個檔案、12 行**，待單獨一批收斂，清單見 `refactor-backlog.md` 第 19 點。原記載的「7 個檔案」經 2026-09-01 實測在任何算法下皆不成立：以含反引號的模式搜尋得 8 個檔案，其中 2 個屬版本紀錄等歷史留痕（依 `.agents/rules/git-and-reporting.md` §3 應保留），扣除後為 6 個 |
| **DLP 安全宣告為裝飾性樣板** | 「✓ DLP 資料安全驗證已通過 \| 資料加密處理 \| 隱私保護協議」出現在 25 份 SKILL.md，但不對應任何實際驗證行為；`dlpSanitizer.js` 做的是遮蔽非加密，且只在 LINE/TG 寫對話紀錄時作用，不在 commit 路徑上。**源頭已於 2026-09-01 查明並斷源**：`skills/meta/skill-evolution-governor/SKILL.md` 原第 40-49 行要求每個技能加上該宣告，已改為指向 SOP_02 §1 與 guardrails §3。25 份存量待單獨一批清理，見 `refactor-backlog.md` 第 17 點 |
| **`json-to-flex-renderer` 指向舊 repo 路徑** | SKILL.md 第 31 行引用 `skills/03_Execution/line-bot-zero-delay/`，屬合法註記（runtime 尚未遷移），但 runtime 遷移完成後必須回頭更新 |

---

## 6. 已處理的風險

### 6.1 憑證外洩（本機，未推送）

- **檔案**：`temp_mcp.json`，含明文 GitHub PAT（`ghp_` 開頭）與
  Notion API Token（`ntn_` 開頭）
- **狀態**：在本機 commit `003427b`（2026-08-10），**未推送到 GitHub**
- **處置**：`git reset --soft HEAD~2` 退回，刪除檔案，
  `.gitignore` 補上 `temp_mcp.json`、`mcp_config*.json`
- **殘留動作**：使用者已決定重構完成後統一更換所有金鑰

### 6.2 已修復的兩個安全漏洞

| 漏洞 | 檔案 | 修法 | 驗證 |
|---|---|---|---|
| Command Injection | `with_server.py` | 移除 `shell=True`，改用 `shlex.split()` + list 傳參 | 5 個測試，含 `$(whoami)` 注入防護驗證 |
| XSS | `d3js-visualization/assets/interactive-template.jsx` | HTML entity escaping（5 個字元，`&` 順序正確） | 手動核對 diff |

### 6.3 遷移過程中攔截的問題（不完整列舉）

| 問題 | 發現方式 |
|---|---|
| `Zero-Block Policy`（「嚴禁詢問使用者」）散布在多個技能 | 逐字讀完整檔案，非摘要 |
| 4 個技能遺失 NotebookLM 鐵律 | 要求逐字比對全文而非 diff 摘要 |
| `mcp-gateway` 宣稱取代 `connect-apps`（未實現的願景） | 查證實際程式碼 |
| `$$額度$$` 宣稱 Bridge 直接攔截（程式碼不存在） | 查證 `bridge.js` |
| GitLab-First Policy（已廢棄政策殘留完整程式碼） | 全域搜尋 |
| `d3-viz-skill` 幽靈引用（技能從未存在） | 查證舊 repo |
| 改名後舊名稱殘留 9 處 | 宏觀審計全域掃描 |
| 舊分層編號（`04_`／`05_`／`06_`）殘留 | 擴大掃描範圍後發現 |
| 根目錄 `tests/` 被 Jules 分支夾帶 3 次 | `git diff origin/main --stat` |
| `run.js` 被 `git add -A` 夾帶進不相關 commit | 宏觀審計檔案清單 |
| `agents/README.md` 兩個 User-invoked 區塊 | README 索引一致性掃描 |

### 6.4 執行期產物清理（舊 repo）

已脫離版控：`scratch/` 三個一次性腳本、`temp_images/` 六張圖、
`bridge_state.json`。`.gitignore` 已強化。
`gemini-notebook-mcp-cli` 子 repo 已移出專案資料夾。

---

## 7. 未處理的風險

### 7.1 🔴 最高優先：`nlm_cookies.txt` 已推送至公開 repo

- **檔案**：`HH.AI_260806/nlm_cookies.txt`
- **內容**：Google session cookie（`OSID=g.a000BQlXn0CY...`，329 bytes）
- **狀態**：**已推送至公開 GitHub**，隨 commit `9552009` 進版控，
  任何人 `--depth 1` clone 即可取得
- **處置建議**：
  1. **立即至 Google 帳號撤銷該 session**（登出所有裝置）
  2. 刪除檔案不足以解決，git 歷史紀錄仍存在，須清理歷史或視為已洩漏
  3. `.gitignore` 已補規則防止再次發生
- **注意**：`refactor-backlog.md` F 節僅記載「憑證檔案，不該進版控」，
  但未標明它**已經實際外洩**

**2026-08-29 處置結果**：
- 使用者已於 Google 帳號執行「登出所有裝置」，並確認登入清單中無陌生裝置
- 檔案已從舊 repo 的 HEAD 移除（commit `4729c04`），
  舊 repo `.gitignore` 補上 `nlm_cookies.txt` 與 `*cookies*`
- git 歷史仍保有該檔案（清歷史需 force push，違反
  `.agents/rules/git-and-reporting.md`），該組 cookie 應永久視為已洩漏
- 上游文件載明 cookie 生命週期約 2-4 週，該憑證早已自然過期；
  實測 NotebookLM MCP 回報 `Authentication expired` 與此相符
- 該檔案本非必要：上游正規憑證存放位置為 `~/.notebooklm-mcp-cli`，
  執行 `nlm login` 即可，repo 內不需保留 cookie 檔
- 使用者已親自檢視 Google 帳號登入紀錄，確認無他人登入；
  並確認本專案自始使用測試帳號，後續將全盤更換金鑰與 Google 帳號

### 7.2 🔴 LINE 通道完全失效（根因已查明，未修復）

**斷鏈位置**：

```
bridge.js 啟動 Pinggy 取得新網址
  → [start_line_tunnel.js 遺失] ← 斷點在這
  → sync_tunnel_url.js 讀 .env.local 的 TUNNEL_URL（永遠是 8/9 的死網址）
  → 成功寫入 Worker KV（HTTP 200）
  → Worker 轉發到失效位址 → 訊息石沉大海
```

**關鍵特性**：每個環節都回報「成功」，整條鏈路卻是斷的——**靜默失敗**。

**次要問題**：系統中同時存在兩套互斥的隧道方案
（Worker 固定門面 vs `bridge.js` 直接覆寫 LINE Webhook），
若後者生效會破壞前者設計。

**使用者決定**：等重構完成後再處理。

### 7.3 🟡 資安防線的結構性缺口（ADR-0016）

三道防線都存在、都有能力，但都沒在正確時機觸發：

| 防線 | 有能力 | 為何失效 |
|---|---|---|
| `pre-commit` hook | ❌ | 只查 `.js`／`.ps1`，`.json`／`.txt` 不在範圍 |
| `SOP_14` 審計 | ✅ | 五個觸發條件皆無「commit 前」 |
| `security-auditor` 技能 | ✅ | model-invoked，需 Agent 主動想到才會用 |

**`HH.AI_v2` 目前尚未建立 pre-commit hook**，憑證防護完全依賴人工審查。

**2026-08-29 更新**：已實測 gitleaks 8.30.1 的偵測能力並由使用者裁決。
結論為不部署自動化攔截，維持人工審查定位。
實測數據與重啟條件見 `docs/refactor-backlog.md` 第 16 點。
關鍵發現：gitleaks 預設規則**偵測不到**本專案唯一實際外洩的憑證
（`nlm_cookies.txt` 的 Google session cookie），
亦偵測不到 `postgresql://` 連線字串。
因此「未部署 gitleaks」與「部署了 gitleaks」對本專案已發生的風險，
差異小於直覺預期。

### 7.4 🟡 記憶體是被低估的失效因素

- 16GB 環境，同時跑 Antigravity IDE（1.7GB）、Chrome（1.6GB）、
  Docker、多個 Node 常駐進程時，可用記憶體曾降至 638MB（96% 使用率）
- 診斷時發現 PM2 六大進程只剩 1 個存活，其餘全部消失——
  **符合記憶體不足時 Windows 強制回收進程的行為模式**
- 各進程記憶體需求：`line-bridge` ~132MB、`tg-bridge-zero-delay` ~122MB、
  `sync-tunnel` ~65MB

### 7.5 🟡 Telegram 的 Heap Usage 偏高

`tg-bridge-zero-delay` 的 V8 Heap Usage 達 **96.94%**（59.42MB 中用了 57.60MB）。
總記憶體 122MB 仍在 300MB 上限內，且已穩定運行 2 天，不是立即危險，
但遷移後應持續觀察是否有增長趨勢。

### 7.6 🟡 Port 衝突（潛在，未來必然發生）

- 目前：LINE bridge 3000、TG bridge 3001
- 已消失但未來會重建的 `tw-stock-web`（Next.js）**預設也是 3000**
- 使用者確認兩個功能未來會交疊使用
- **衝突後果不會明顯報錯**：若 Next.js 佔走 3000，
  cloudflared 隧道會把 LINE webhook 轉發到網頁應用，訊息靜默消失
- 規範已定（ADR-0017）：Next.js 應使用 3002

### 7.7 🟢 其他

| 風險 | 說明 |
|---|---|
| `line-daemon` 缺 `autorestart` | 沙盒報告建議加上，但實際未執行（ADR-0014 記錄） |
| Redis 未運行 | `bridge.js` 會自動降級為記憶體模式，代價是訊息佇列不持久化 |
| MCP 憑證雙處存放 | `.env.local` 與系統環境變數各有一份，變數名稱還不同（`GITHUB_TOKEN` vs `GITHUB_PERSONAL_ACCESS_TOKEN`），改一邊另一邊會靜默失效。2026-08-29 已把 `mcp_config.json` 那一側完全移除，由三處縮為兩處，尚未根除。 |
| `notebooklm` MCP 路徑含 Python 版本號 | `pythoncore-3.14-64`，Python 升級後路徑失效 |

---

## 8. 使用者的工作習慣

### 8.1 明確表達過的偏好

| 項目 | 內容 |
|---|---|
| **語言** | 繁體中文（台灣用語）。`SOP_01`、`SOP_02` 明訂嚴禁簡體中文 |
| **提示詞格式** | 要求「**一鍵複製**」——單一完整區塊，不要分段讓他拼接 |
| **提示詞數量** | **一次只給一份**，不要同時給多份讓他選 |
| **提示詞節奏** | **每一次回覆的結尾都要直接附上下一步要給 Antigravity 的提示詞**，不要等使用者開口要。唯一例外：需要使用者裁決或提供資料時，改為列出待確認事項，該輪不出提示詞 |
| **Agent 回覆格式** | 要求 Agent 回覆結尾加「以上是 Antigravity IDE Agent 的回覆」，方便辨識來源 |
| **查證要求** | 反覆強調「請親自檢視資料」「請宏觀角度思考」——不接受憑印象的判斷 |
| **每輪審計** | 明確要求每一輪都要重新確認整體架構（ADR-0007 的來源） |

### 8.2 工作模式

- 使用 **Antigravity IDE**（VS Code fork）在本機操作
- 同時開啟舊/新兩個 workspace（記憶體吃緊時會關掉一個）
- 常在對話中途重開 Agent（避免舊 Agent 產生幻覺）
- 會提供大量歷史文件供參考，但**文件版本多、可能過時**，需查證
- **附件上傳經常失敗**（本次對話失敗超過 10 次），
  請優先請他直接貼文字或截圖

### 8.3 決策風格

- 願意授權，但要求先說明利弊
- 在意「不出任何差錯」勝過速度
- 會主動指出 Claude 的錯誤與態度問題，且指得準確
- 對於「開新對話」這類建議會抗拒——他希望的是解決問題，不是繞過問題

### 8.4 環境限制

| 項目 | 現況 |
|---|---|
| 記憶體 | 16GB DDR4（吃緊） |
| Jules 額度 | 100 次/天（Google AI Pro/Ultra） |
| MCP servers | 6 個、161 個工具（notebooklm 48、github 44、chrome-devtools 29、notion 24、docker gateway 8、google-jules 8） |
| Claude 訂閱 | 有使用量限制，長對話會快速消耗 |

---

## 9. 與 Antigravity IDE Agent 協作規範

### 9.1 提示詞必備要素

每份提示詞結尾固定加上：

```
請將完整回覆整理成一份可以直接複製的純文字內容（不要用只能在你這裡展開查看的
折疊區塊），並在回覆的最後加上一行：「以上是 Antigravity IDE Agent 的回覆」。
```

### 9.2 必須明確指定的事項

| 事項 | 原因 |
|---|---|
| **工作目錄** | 曾發生在錯誤 repo 執行的疑慮。指示開頭應要求先確認 `pwd` |
| **不要 commit/push** | 若要先核對，必須明講「先不要 commit/push，等我核對」 |
| **git add 用明確路徑** | 禁止 `git add -A`（已寫入 `.agents/rules/`） |
| **注解位置** | 註記要放在指令外面，不要塞進反引號包住的指令字串（踩過兩次） |
| **寫入方式** | 內容含巢狀 code block 時，要求用 Python 三重雙引號字串寫入 |
| **編碼設定** | 執行 `validate_skills.py` 前要 `$env:PYTHONIOENCODING = "utf-8"` |

### 9.3 提示詞結構模板

```
【背景】（新 Agent 才需要，接續的可省略）
【要處理的問題】逐項列出，每項附上實際查證的證據（行號、原文）
【處理方式】具體到可以照做，不要留模糊空間
【驗證步驟】明確的檢查指令與預期結果
【提交方式】git add 路徑、commit message、是否 push
【回報要求】要它貼出什麼內容供核對
```

### 9.4 分批原則

- **高風險技能**（`orchestration/`、`agents/`、含程式碼的）：
  先查證 → 提方案 → 核對草稿 → 才寫入
- **低風險技能**（純文件、無外部副作用）：可直接遷移後核對
- **一次不超過 4-6 個技能**，超過容易出錯且難核對
- **同一檔案有多個來源要改**：必須依序處理，不可平行

---

## 10. Antigravity Agent 的已知出錯模式與風險評估

### 10.1 已實際發生的出錯模式（依嚴重度排序）

| # | 出錯模式 | 實際案例 | 嚴重度 |
|---|---|---|---|
| 1 | **回報「已完成」但實際沒做** | `subagent-collaboration` 的舊 bucket 名稱三處完全沒改，回報時也沒提 | 🔴 高 |
| 2 | **回報狀態與實際不符** | 說「等待您的核准」但其實已經 commit | 🔴 高 |
| 3 | **只給摘要，隱藏問題** | `agency-orchestrator` 第一輪只給 frontmatter 比對，看完整內容才發現 Zero-Block Policy 等 4 個問題 | 🔴 高 |
| 4 | **`git add -A` 夾帶無關檔案** | `run.js` 被夾帶進不相關 commit | 🟡 中 |
| 5 | **字串取代造成語法損壞** | 中文註解被塞進 bash 指令中間、塞進反引號檔名清單 | 🟡 中 |
| 6 | **修一個問題引入新問題** | 修正時把已遷移的 `webapp-testing` 誤標為「尚未遷移」 | 🟡 中 |
| 7 | **萬用字元造成副作用** | `git restore --staged "temp_images/*"` 把脫離追蹤的狀態也一起退回 | 🟡 中 |
| 8 | **只改當下看到的檔案** | 同技能的 `REFERENCE.md` 漏改（踩過三次） | 🟡 中 |
| 9 | **查錯路徑得出錯誤結論** | 查 `line-bot-project/.env.local` 而非根目錄的，誤判金鑰遺失 | 🟡 中 |
| 10 | **憑印象標註狀態** | 未實際查詢就標記技能遷移狀態 | 🟢 低 |
| 11 | **用 `--amend` + force push** | 規則寫下後仍違反一次 | 🟢 低 |
| 12 | **commit message 被 shell 展開** | `$$` 未用單引號包住 | 🟢 低 |
| 13 | **計算方式錯誤但結論碰巧正確** | 用 `count('```')` 算出 548（實際是單反引號數） | 🟢 低 |
| 14 | **產生暫存腳本未清理** | `write_rules.py`、`fix_json_to_flex.py` 等 | 🟢 低 |
| 15 | **回報內容整份虛構** | 2026-09-01：六個檔案的實際改動完全正確，但回報貼出的四份「完整內容」與實際檔案整份不同，是看起來更整齊的重新設計版；四份中三份的總行數亦不符。危害在於審查者若採信，會下令回滾一份本來正確的檔案 | 🔴 高 |

### 10.2 Agent 表現良好的部分（值得保持的做法）

- 主動查證而非憑印象（後期明顯進步）
- 不確定時明說「需要你確認」，不編造
- 主動發現並回報自己造成的副作用
- 會把教訓寫成操作準則
- 對「宣稱取代」這類陳述會實際驗證程式碼

### 10.3 風險緩解措施（已建立）

| 措施 | 效果 |
|---|---|
| **獨立 clone 核對**（ADR-0007） | 抓到過至少 8 次「回報已完成但沒做」 |
| **三層核對流程**（ADR-0005） | 高風險技能不接受摘要，要求完整內容 |
| **`.agents/rules/git-and-reporting.md`** | 規則自動載入，不依賴每次口頭提醒 |
| **`validate_skills.py`** | 自動化格式把關（但抓不到語意問題） |
| **41 個自動化測試** | 保護 `validate_skills.py` 與 `with_server.py`。另有 `scripts/check_consistency.py` 做七項跨檔案一致性檢查 |

### 10.4 核對時的重點檢查項

每批遷移後，至少確認：

```bash
# 1. 技能總數是否符合預期
find skills -name SKILL.md | wc -l

# 2. frontmatter 是否乾淨（不該有 type、version、capabilities）
grep -rn "^type:\|^version:\|^capabilities:" skills --include="SKILL.md"

# 3. 已知問題字串是否殘留
grep -rln "嚴禁中斷或詢問使用者\|Zero-Block Policy" skills/

# 4. 舊架構名稱是否殘留
grep -rn "0[1-9]_[A-Za-z\u4e00-\u9fff]" skills/

# 5. 拆分後的 code block 是否配對
# 正確算法：以 ``` 開頭的行數（見 .agents/rules/git-and-reporting.md §3）

# 6. README 索引是否同步
# 7. validate_skills.py 是否 0 錯誤
```

---

## 11. Claude 自身的已知失誤

誠實記錄，供接手者避免：

| # | 失誤 | 後果 |
|---|---|---|
| 1 | **憑猜測寫規格** | `semantic_firewall` 被寫成布林值，實際是字串路徑。後來才依實際資料修正 |
| 2 | **判斷反覆** | LINE 通道狀態判斷錯三次（先說 8/9 前正常、再說從未通過、最後才拼出正確時間軸） |
| 3 | **自己的 prompt 也有巢狀 code block 問題** | ADR-0007 的內容因為巢狀反引號被截斷，來回多輪才修好 |
| 4 | **審計腳本有偽陽性** | 把 README 說明文字裡的格式範例誤判為技能條目 |
| 5 | **沒先核對就質疑 Agent** | 質疑 Port 9229 是編造，實際是舊 SOP 原文就有 |
| 6 | **過度分批** | 把可以一次做完的批次拆開，增加來回成本 |
| 7 | **重複 clone 同一個 repo 20 次以上** | 大量無謂的 token 消耗 |
| 8 | **態度問題** | 使用者要求看檔案時連續四次回「不需要看」「這條對話結束吧」，
     那不是替他省成本，是在推開他 |
| 9 | **交接不完整** | 以為建好 Project、上傳文件就是交接，實際上新對話第一件事就卡住
     （不知道自己可以 clone repo） |

---

## 12. 接手第一步該做什麼

### 12.1 建立脈絡（約 5 分鐘）

```bash
git clone --depth 1 https://github.com/hhai0519/HH.AI_v2.git
cd HH.AI_v2
cat docs/refactor-backlog.md        # 進度與待辦
cat AGENTS.md                        # 架構規範
cat .agents/rules/git-and-reporting.md   # 協作紀律
ls docs/adr/                         # 20 份決策紀錄
```

**不需要請使用者貼終端機輸出**——兩個 repo 都是公開的，直接 clone。

### 12.2 優先處理順序（建議）

1. **提醒使用者撤銷 `nlm_cookies.txt` 的 Google session**（最急，與重構無關）
2. **請使用者裁決攔截項三**（runtime 層架構選擇，見 §5.2。
   攔截項一與二已於 2026-08-29 裁決完畢）
3. `jules-integration` 技能改寫（`authorized_mcp_tools` 與內文仍在描述
   已停用的擴充套件路線，見 ADR-0019），需同步 `agency-orchestrator`
4. 繼續遷移剩餘 7 個技能（見 §5.1）
5. persona 階段一（保全調研資料）
6. runtime／shared 層（最大工程，需先完成第 2 項的架構決策）

### 12.3 工作方法（不可省略）

- **產出提示詞前，親自 clone 查看舊 repo 的目標檔案**，
  不要憑 backlog 的描述反推
- **Agent 回報後，獨立 clone 核對實際檔案**，不接受口頭回報
- **每批完成後跑 `validate_skills.py`**，並確認技能總數符合預期
- **每 2-3 批做一次宏觀掃描**（拓撲、介面一致性、冗餘）

### 12.4 溝通原則

- 回應簡短，直接給判斷與下一步
- 使用者要求看什麼就看，不要替他決定「不需要看」
- 不確定時明說，不用推測填補
- 發現自己判斷錯誤時直接更正，不要為了維持一致性而堅持

---

## 附錄：常用指令速查

```bash
# 查證兩個 repo
git clone --depth 1 https://github.com/hhai0519/HH.AI_260806.git
git clone --depth 1 https://github.com/hhai0519/HH.AI_v2.git

# 技能總數
find skills -name SKILL.md | wc -l

# 各 bucket 分布
for b in orchestration analysis agents execution platform meta deprecated; do
  echo "$b: $(find skills/$b -name SKILL.md 2>/dev/null | wc -l)"
done

# 驗證（Windows 需先設編碼）
$env:PYTHONIOENCODING = "utf-8"
python3 scripts/validate_skills.py

# 測試
python3 -m pytest scripts/tests/ skills/execution/webapp-testing/tests/ -q

# code block 圍欄數（正確算法）
python3 -c "
t=open('檔案路徑',encoding='utf-8').read()
print(sum(1 for l in t.splitlines() if l.strip().startswith('\`\`\`')))
"
```

---

> 最後更新：2026-08-29（本階段完成 ADR-0018、ADR-0019、3 個 execution 技能遷移、
> Jules 官方 CLI/MCP 整合留痕、`AGENTS.md` 測試指令與 `.gitignore` 憑證防呆）

**手冊結束。**

如需更新此手冊，建議放入 `HH.AI_v2/docs/HANDOVER.md`，
並在每次重大階段完成後更新「已完成／未完成」兩節。
