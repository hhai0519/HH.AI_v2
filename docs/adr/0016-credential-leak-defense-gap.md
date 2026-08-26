# ADR-0016: 憑證外洩的三道防線都存在，但都沒有在正確時機觸發

- Status: Accepted
- Date: 2026-08-26

## Context

舊專案 HH.AI_260806 發生過兩次憑證進入版控的事件：

**事件一：`nlm_cookies.txt`（已實際推送至公開 GitHub）**
內容為 Google 帳號的有效 session cookie（`OSID`、`__Secure-OSID`）。
該檔案已推送到公開 repo，任何人都能 clone 取得。發現時間為 2026-08-25，
於本次重構的例行檢查中被發現。

**事件二：`temp_mcp.json`（僅存在本機 commit，未推送）**
內容為 `mcp_config.json` 的完整副本，包含明文的 GitHub Personal Access
Token（`ghp_` 開頭）與 Notion API Token（`ntn_` 開頭）。
於 2026-08-26 清理舊專案執行期產物時發現，該 commit（`003427b`，
2026-08-10）尚未推送，已用 `git reset --soft` 清除。

## 核心發現：三道防線都存在，都有能力，但都沒被觸發

調查後確認，系統其實有三層資安防護，每一層都具備偵測憑證的能力或職責，
但每一層都因為不同原因沒有在這兩次事件中生效：

| 防線 | 是否具備憑證偵測能力 | 為什麼沒攔到 |
|---|---|---|
| `.githooks/pre-commit` | ❌ 不具備 | 檢查規則只有三條，全部是程式碼行為規範（禁止 `while($true)`、`Stop-Process -Name`、`Start-Process powershell`），沒有任何一條在查 token。而且 `sop_linter.js` 用 `.filter(f => f.endsWith('.js') \|\| f.endsWith('.ps1'))` 過濾，`.json` 與 `.txt` 根本不在檢查範圍 |
| `SOP_14` 嚴謹驗證與審計標準程序 | ✅ 具備 | 「1.1 資安稽核官」職責明列「檢查金鑰暴露（如 `.env.local` 密碼洩漏）」，但**五個強制觸發條件中沒有任何一條涵蓋「commit 或 push 前」**，因此在這兩次事件中從未被啟動 |
| `security-auditor` 技能 | ✅ 具備 | description 明列「掃描 API 密鑰外洩」，但它是 model-invoked 技能，需要 Agent 主動判斷該使用才會執行。兩次事件中 Agent 都直接執行了 commit，沒有想到先呼叫此技能 |

**這不是「沒有防護」，而是「防護的觸發時機沒對上」。**
後者比前者更危險，因為系統中存在資安審計的技能與 SOP，會讓人誤以為
已有保障。

## Decision

HH.AI_v2 的資安防護必須同時滿足三個條件，缺一不可：

### 1. 必須是自動觸發，不能依賴 Agent 主動判斷

`security-auditor` 這類 model-invoked 技能可以保留作為深度審查工具，
但**不能作為唯一防線**。憑證外洩的防護必須是 commit 時強制執行的
pre-commit hook，無法被「忘記使用」。

### 2. 檢查範圍不能依副檔名過濾

舊系統的 `sop_linter.js` 只檢查 `.js` 與 `.ps1`，導致 `.json`
（`temp_mcp.json`）與 `.txt`（`nlm_cookies.txt`）完全不在範圍內。
新的 hook 必須掃描**所有**被 staged 的檔案，不論副檔名。

### 3. 必須有針對憑證特徵的檢查規則

至少應涵蓋以下模式（實際實作時應再擴充）：
- GitHub PAT：`ghp_`、`gho_`、`ghu_`、`ghs_`、`ghr_`、`github_pat_` 開頭
- Notion：`ntn_`、`secret_` 開頭
- LINE Channel Access Token：長度超過 150 字元的 base64 字串
- Telegram Bot Token：`數字:英數字串` 格式
- Google session cookie：`OSID=`、`__Secure-OSID=`
- 通用：`api[_-]?key`、`access[_-]?token`、`client[_-]?secret`
  等欄位名稱後面接著長字串
- 檔名黑名單：`*cookies*`、`mcp_config*.json`、`.env*`（非範本）

### 4. SOP_14 的觸發條件應補上「版控操作前」

`SOP/SOP_14_Rigorous_Verification_and_Audit_Protocol.md` 的觸發條件
應新增一條：「任何 commit 或 push 操作前，若 staged 檔案中包含
設定檔（`.json`、`.env`、`.yaml`）或非程式碼檔案」。

## Consequences

- HH.AI_v2 目前**尚未建立** pre-commit hook。在建立之前，憑證防護
  完全依賴人工審查與 Agent 的主動判斷，與舊系統的狀態相同。
  這是已知的缺口，應在 runtime 層遷移時一併補上。
- 舊專案的 `nlm_cookies.txt` 已推送至公開 GitHub，該 Google session
  憑證應視為已洩漏。使用者已知悉，並規劃於重構完成後統一更換所有金鑰。
- 本 ADR 記錄的「能力存在但觸發時機錯位」模式，不限於資安。
  任何依賴 Agent 主動判斷的防護機制，都應評估是否需要改為自動強制執行。
- 舊專案的 `.gitignore` 已於 2026-08-26 強化，新增 `temp_mcp.json`、
  `mcp_config*.json`、`temp_images/`、`bridge_state.json`、`*.tmp`
  等排除規則，並將已被追蹤的執行期產物以 `git rm --cached` 脫離版控。
