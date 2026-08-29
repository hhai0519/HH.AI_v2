# ADR-0019: Jules 整合改採 Google 官方 CLI 與 MCP，取代擴充套件方案

- Status: Accepted
- Date: 2026-08-29
- Supersedes: ADR-0003

## Context

ADR-0003（2026-08-10）決定 Jules 整合走 Antigravity 擴充套件
**Antigravity Jules Bridge**（來源 `Germain-L/Send2Jules`），並明確否決了
「手動把 `JULES_API_KEY` 寫進 `mcp_config.json`」的路線，理由是明文金鑰的
安全性不如擴充套件使用的 OS SecretStorage。

該決策成立時，Google 尚未提供官方的 CLI 與 MCP 套件。2026-08-29 查證確認
官方套件已存在且可用，能力遠超過原方案（原方案只有單一 `sendToJules`
指令，官方 MCP 提供 8 組工具）。因此 ADR-0003 的決策前提已不成立，
本 ADR 取代之。

**2026-08-29 於使用者本機的實測結果：**

| 項目 | 實測值 |
|---|---|
| CLI 套件 | `@google/jules` v0.1.42，全域安裝於 `AppData\Roaming\npm` |
| CLI 認證 | 已完成 `jules login`（Google OAuth2），token 由 CLI 自行管理 |
| MCP 套件 | `mcp_config.json` 以 `npx -y @google/jules-mcp` 啟動，**未指定版本** |
| MCP 實測版本 | `--version` 回報 `0.1.0`；npm registry 最新為 `0.2.0`（疑為 npx 快取） |
| MCP 工具數 | 8 組，全部 Active |
| 金鑰位置 | `C:\Users\HH.AI_260806\.gemini\config\mcp_config.json` 的 `env.JULES_API_KEY` |
| 該檔案是否在版控內 | 否。`git rev-parse --show-toplevel` 回報 `fatal: not a git repository` |
| 兩 repo git 歷史 | `mcp_config` / `temp_mcp` 完整 log 零命中，歷史乾淨 |

**8 組 MCP 工具：** `create_session`（必填 `prompt`）、`list_sessions`（無必填）、
`get_session_state`、`get_bash_outputs`、`get_code_review_context`、
`show_code_diff`（以上必填 `sessionId`）、`send_reply_to_session`
（必填 `sessionId`、`action`）、`query_cache`（必填 `query`）。

**CLI 實際語法（實測 `--help`，與初期說明不同）：**

- `jules remote new` 僅有三個參數：`--repo owner/name`、`--session "任務描述"`、
  `--parallel N`（1-5）。**沒有指定分支的參數**，base branch 由 Jules 服務端
  綁定，CLI 無法覆寫。
- 任務描述支援 pipe：`cat task.md | jules remote new --repo owner/name`
- 查詢用 `jules remote list --session`
- `jules teleport <session-id>`：clone repo + checkout 分支 + 套用 patch
- `jules remote pull --session <id> --apply`：把結果直接套進本地 repo
- 版本查詢是 `jules version`，不是 `jules --version`

## Decision

**一、改採官方 `@google/jules` CLI 與 `@google/jules-mcp`，ADR-0003 的擴充套件
方案停止使用。**

**二、`JULES_API_KEY` 維持存放於 `~/.gemini/config/mcp_config.json`。**

官方 MCP 套件的 `--help` 只提供 `config` 子指令設定金鑰，未載明支援從 OS
環境變數讀取，故無更安全的現成替代方案。緩解措施是該檔案位於使用者家目錄、
不在任何 git repository 內。

**三、`mcp_config.json` 及其任何副本，禁止以任何形式進入本專案 repo。**

ADR-0016 的憑證外洩正是把該檔案複製成 `temp_mcp.json` 放進 repo 造成的。
本 ADR 要求在 `.gitignore` 建立防呆規則，不依賴人工記得。

**四、MCP 套件應鎖定版本。**

目前 `npx -y @google/jules-mcp` 未指定版本，每次啟動都會取用上游最新版，
上游變更會無預警進入環境，且斷網時 MCP 直接失效。這與 ADR-0018 對 vendored
外部資產的版本鎖定原則矛盾。建議改為 `@google/jules-mcp@0.2.0`。
此項需修改 `mcp_config.json`（在 repo 外），由使用者執行，不在本次 commit 範圍。

## 2026-08-29 當日更正

本 ADR 寫成後同日的實測推翻了上方兩處判斷，原文保留，更正記錄於此。

**更正一：金鑰不必留在 `mcp_config.json`。**

Decision 第二條依據「官方 MCP 套件的 `--help` 只提供 `config` 子指令設定金鑰，
未載明支援從 OS 環境變數讀取」而決定維持現狀。實測 `doctor` 指令的錯誤訊息
明白寫著 `Run 'jules-mcp config' or set JULES_API_KEY env var`，
且在只有系統環境變數參與的情況下回報 `API Connection: ✓ Authenticated`。

因此改採環境變數，並同批把 `github-mcp-server` 與 `notion-mcp-server` 的金鑰
一併遷出。**`mcp_config.json` 現已不含任何明文金鑰**，ADR-0016 的
「複製設定檔即洩漏」失效路徑就此消除。作法見
`docs/mcp-environment-guide.md` 的「金鑰存放方式」一節。

教訓：`--help` 沒寫不等於不支援，應直接跑 `doctor` 這類診斷指令看實際行為。

**更正二：本套件並非「官方支援」產品。**

本 ADR 通篇以「Google 官方 CLI 與 MCP」描述，措辭不準確。
上游 README 明載 `This is not an officially supported Google product`，
且不納入 Google 開源漏洞獎勵計畫。

準確描述應為：由 Google 以 `@google` npm scope 發布、Apache-2.0 授權，
但聲明為非官方支援產品。決策本身不變（8 組工具 vs 原方案單一指令，
能力差距明確），但取代 ADR-0003 的理由不應建立在「官方 vs 非官方」
這個對比上。

另註：上游 README 只列 7 個工具且寫作 `send_reply`，
本機實際暴露 8 個、名稱為 `send_reply_to_session`，並多一個 `get_bash_outputs`。
本 ADR 的工具清單取自本機實測，較 README 準確，不需更正。

## Consequences

- 取得 8 組 MCP 工具，Agent 可直接查詢 session 狀態、讀取 bash 輸出與 diff，
  不必再手動開 Jules Dashboard。HANDOVER §5.5 的待辦「Agent 操控 Jules」因此解除。
- `jules teleport` 與 `jules remote pull --apply` 提供比手動 `git fetch` 更直接的
  結果套用路徑，可改善上一批 12 個分支的整合成本。
- 代價：金鑰以明文存在本機設定檔，安全性低於 SecretStorage。這是官方套件目前的
  設計限制，非本專案可選擇。若日後官方支援環境變數，應重新評估。
- `jules-integration` 技能的 `authorized_mcp_tools` 只列了舊的
  `antigravity-jules-bridge.sendToJules`，SKILL.md 內文也仍在描述擴充套件路線，
  與現況不符，需另立一批改寫，並依 `AGENTS.md` §6 同步 `agency-orchestrator`。
- `docs/mcp-environment-guide.md` 原本記錄 5 個 MCP server，現為 6 個，需補上。
- Jules 在雲端 VM 是孤立環境，只能依賴 `AGENTS.md` 判斷如何執行測試。本專案
  `AGENTS.md` 原本沒有測試指令，已於同批補上；日後變更測試方式時務必一併檢查。
