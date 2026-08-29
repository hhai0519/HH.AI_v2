# MCP 環境設定與重建指南

> 建立日期：2026-08-26
> 用途：記錄 Antigravity IDE 的 MCP 設定結構，供環境重建時還原。若需開發新 MCP 伺服器或排錯，請參閱 [`skills/execution/mcp-engineer`](../skills/execution/mcp-engineer/SKILL.md) 技能。
> 背景：2026-07-26 曾發生系統崩潰需重建 OS 使用者帳號，當時 MCP 設定
> 完全不在版控中，無從還原。本文件即為補上這個缺口。

## 設定檔位置

`C:\Users\<USER>\.gemini\config\mcp_config.json`

**注意：此檔案位於 IDE 的個人設定目錄，不在專案資料夾內，因此不受 git
版控保護。環境重建時不會自動還原，必須依本指南手動重建。**

## 架構：兩層 MCP

系統的 MCP 分為兩層，只看設定檔會誤以為只有 6 個：

1. **直接設定層**（寫在 `mcp_config.json` 的 5 個）：
   chrome-devtools-mcp、github-mcp-server、notion-mcp-server、notebooklm、
   google-jules
2. **Gateway 動態層**（透過 `docker mcp gateway run` 管理）：
   Docker 官方的 MCP Gateway，提供 mcp-add / mcp-find / mcp-exec /
   mcp-config-set 等 8 個管理工具，可在執行期動態載入其他 MCP server。
   透過它載入的 server 不會出現在 `mcp_config.json` 中。

## 六個 MCP Server 的重建方式

| Server | 啟動方式 | 前置需求 | 需要的環境變數（設在 Windows User 層級，不寫進設定檔） |
|---|---|---|---|
| `chrome-devtools-mcp` | `npx -y chrome-devtools-mcp@latest` | Node.js | 無 |
| `github-mcp-server` | `docker run -i --rm -e GITHUB_PERSONAL_ACCESS_TOKEN ghcr.io/github/github-mcp-server` | Docker | `GITHUB_PERSONAL_ACCESS_TOKEN` |
| `notion-mcp-server` | `npx -y @notionhq/notion-mcp-server` | Node.js | `OPENAPI_MCP_HEADERS`、`NOTION_API_TOKEN` |
| `docker`（Gateway） | `docker mcp gateway run` | Docker Desktop | 無 |
| `notebooklm` | 本機執行檔 `notebooklm-mcp.exe` | `pip install notebooklm-mcp-cli`（v0.10.0）＋ `nlm login` 完成認證 | `NLM_USER_AGENT` |
| `google-jules` | `npx -y @google/jules-mcp@0.2.0` | 全域安裝 `@google/jules` 並完成 `jules login` | `JULES_API_KEY` |

> **註：google-jules 提供的 8 組工具**：create_session、list_sessions、get_session_state、get_bash_outputs、get_code_review_context、show_code_diff、send_reply_to_session、query_cache

> **註：notebooklm 於 2026-08-29 升級至 v0.10.0**，提供 48 個工具
> （14 個功能群組：auth／automation／chat／notebooks_manage／notebooks_read／
> notes／organization／query_multi／research／server／sharing／sources_manage／
> sources_read／studio）。可用 `server_info` 工具查詢實際版本與工具可見性。

## 金鑰存放方式（2026-08-29 起）

**所有 API 金鑰一律存放在 Windows User 層級環境變數，`mcp_config.json`
內不得出現任何 `env` 區塊形式的明文金鑰。**

目前以此方式存放的四個變數：

| 變數名稱 | 使用者 |
|---|---|
| `JULES_API_KEY` | `google-jules` |
| `GITHUB_PERSONAL_ACCESS_TOKEN` | `github-mcp-server` |
| `NOTION_API_TOKEN` | `notion-mcp-server` |
| `OPENAPI_MCP_HEADERS` | `notion-mcp-server` |

（`notebooklm` 的 `NLM_USER_AGENT` 不是機密，仍留在設定檔內。）

**設定方式**：PowerShell 執行
`[Environment]::SetEnvironmentVariable(名稱, 值, 'User')`，
設定後必須**完全關閉並重新開啟 Antigravity IDE**，僅重新載入視窗無效。

**為什麼這樣做**：ADR-0016 的憑證外洩，是把含明文金鑰的 `mcp_config.json`
複製成 `temp_mcp.json` 放進 repo 造成的。金鑰不在設定檔內，這條失效路徑
就不存在。詳見 ADR-0019。

**2026-08-29 重啟後實測結果**：六個 server 全部 Active；
`google-jules`（list_sessions）、`github-mcp-server`（get_me）、
`notion-mcp-server`（API-post-search）三個唯讀呼叫全部成功；
`npx -y @google/jules-mcp@0.2.0 doctor` 回報 API Key ✓、API Connection ✓。
其中 `github-mcp-server` 使用 `docker run -e GITHUB_PERSONAL_ACCESS_TOKEN`
（只給變數名不給值），傳遞鏈最長，實測確認 Antigravity → docker → 容器
可正確傳遞行程環境。

## 已知風險與待改善項目

### 1. 憑證雙處存放，且命名不一致（高風險）

同一組憑證同時存在於 `.env.local` 與 `mcp_config.json`，但變數名稱不同：

| 用途 | `.env.local` | `mcp_config.json` |
|---|---|---|
| GitHub | `GITHUB_TOKEN` | `GITHUB_PERSONAL_ACCESS_TOKEN` |
| Notion | `NOTION_TOKEN` | `NOTION_API_TOKEN` |

**風險**：重新產生憑證時若只更新一邊，另一邊會靜默失效，且因名稱不同，
用 `GITHUB_TOKEN` 全域搜尋找不到 MCP 那份。

**待改善**：評估是否讓 MCP 設定改為讀取環境變數而非硬編碼值，
使 `.env.local` 成為單一真實來源。

### 2. notebooklm 的絕對路徑含 Python 版本號（中風險）

目前設定為：
`C:\Users\<USER>\AppData\Local\Python\pythoncore-3.14-64\Scripts\notebooklm-mcp.exe`

**風險**：Python 升級到 3.15 後此路徑失效；換電腦或換使用者名稱亦然。

**2026-08-29 已評估，決定維持絕對路徑。**

兩個替代方案都經實測否決：

- **加入 PATH**：該 `Scripts` 目錄含 26 個執行檔，其中 `pytest.exe`、
  `py.test.exe`、`uv.exe`、`uvx.exe`、`mcp.exe`、`fastmcp.exe`、`keyring.exe`
  等都是通用開發工具。把它推進 PATH 等於讓某個 Python 3.14 環境搶佔全域
  指令名稱，失效方式會從「找不到指令」變成「跑到錯的指令」，比原本的風險更糟。
- **`python -m` 呼叫**：實測 `python -m notebooklm_tools` 回報
  `'notebooklm_tools' is a package and cannot be directly executed`，
  該套件沒有 `__main__`，不支援模組模式。

因此 Python 升級到 3.15 時仍須手動更新此路徑，這是已知且已接受的成本。
升級 Python 後若 notebooklm MCP 啟動失敗，第一個要檢查的就是這條路徑。

### 認證重建：`nlm login` 的正確流程

**執行 `nlm login` 前，必須完全關閉所有 Chromium 系列瀏覽器行程。**

原因：`nlm login` 會啟動一個**專屬 profile** 的瀏覽器
（`~/.notebooklm-mcp-cli/chrome-profiles/<name>/`），不是使用者日常使用的
profile。若日常瀏覽器正在執行，新實例會被既有行程接手，CDP 連不上，
指令會停在 `Waiting for sign-in in browser window` 直到 300 秒逾時。

正確流程：

1. 工作管理員確認 Edge（或設定的偏好瀏覽器）行程完全結束，含背景行程
2. 執行 `nlm login`（本專案需用絕對路徑，見上方已知風險 2）
3. 等一個**乾淨的**瀏覽器視窗跳出——沒有書籤、沒有擴充套件、未登入任何帳號
4. 在**那個視窗**登入 Google 帳號並進入 Gemini Notebook
5. 終端機出現 `Successfully authenticated!` 即完成

★ 這一步無法交由 Agent 代跑 ★ —— 需要人在瀏覽器互動，Agent 執行只會等到逾時。

**已知陷阱**：在自己日常的瀏覽器登入 NotebookLM 對此無效，
CLI 讀的是它自己那個 profile。`nlm doctor` 顯示的
`Headless auth: available (saved Google login)` 指的是「有這個機制可用」，
不代表該 profile 目前的登入有效。

憑證存放位置：`~/.notebooklm-mcp-cli/profiles/<name>/auth.json`。
可用 `nlm login --check` 驗證，成功時會實際查詢並回報筆記本數量。

**偏好瀏覽器**可用 `nlm config set auth.browser chrome` 指定
（支援 chrome、edge、brave、chromium、vivaldi、opera），找不到會自動偵測。

### 3. Gateway 動態載入的 server 無紀錄（中風險）

透過 `docker mcp gateway` 動態載入的 MCP server 不會寫入
`mcp_config.json`，環境重建時無從得知原本載入過哪些。

**待改善**：定期匯出 Gateway 的 profile（`mcp-create-profile` 可建立
當前狀態快照），並將 profile 清單（不含憑證）納入本文件。

## 環境重建檢查清單

重建環境時依序執行：

- [ ] 安裝 Node.js（chrome-devtools-mcp、notion-mcp-server 需要）
- [ ] 安裝 Docker Desktop（github-mcp-server、Gateway 需要）
- [ ] `pip install notebooklm-mcp-cli`（notebooklm 需要）
- [ ] 建立 `C:\Users\<USER>\.gemini\config\mcp_config.json`，依上表填入
      六個 server 的設定
- [ ] 重新產生並填入憑證：GitHub PAT、Notion API Token、NLM User Agent
- [ ] 確認 `.env.local` 的 `GITHUB_TOKEN` / `NOTION_TOKEN` 與
      `mcp_config.json` 的值一致
- [ ] 在 Antigravity 的 Manage MCP servers 介面確認六個 server 皆為
      Enabled 狀態
- [ ] 執行一次工具呼叫測試（例如透過 notebooklm 查詢、透過 github
      列出 repo）確認實際可用
- [ ] 安裝 Python 相依套件：`pip install -r requirements.txt`
      （pytest 測試框架、playwright 瀏覽器自動化，詳見 `requirements.txt`）
