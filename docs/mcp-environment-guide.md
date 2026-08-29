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
   chrome-devtools-mcp、github-mcp-server、notion-mcp-server、notebooklm
2. **Gateway 動態層**（透過 `docker mcp gateway run` 管理）：
   Docker 官方的 MCP Gateway，提供 mcp-add / mcp-find / mcp-exec /
   mcp-config-set 等 8 個管理工具，可在執行期動態載入其他 MCP server。
   透過它載入的 server 不會出現在 `mcp_config.json` 中。

## 六個 MCP Server 的重建方式

| Server | 啟動方式 | 前置需求 | 需要的環境變數 |
|---|---|---|---|
| `chrome-devtools-mcp` | `npx -y chrome-devtools-mcp@latest` | Node.js | 無 |
| `github-mcp-server` | `docker run -i --rm -e GITHUB_PERSONAL_ACCESS_TOKEN ghcr.io/github/github-mcp-server` | Docker | `GITHUB_PERSONAL_ACCESS_TOKEN` |
| `notion-mcp-server` | `npx -y @notionhq/notion-mcp-server` | Node.js | `OPENAPI_MCP_HEADERS`、`NOTION_API_TOKEN` |
| `docker`（Gateway） | `docker mcp gateway run` | Docker Desktop | 無 |
| `notebooklm` | 本機執行檔 `notebooklm-mcp.exe` | `pip install notebooklm-mcp-cli` | `NLM_USER_AGENT` |
| `google-jules` | `npx -y @google/jules-mcp@0.2.0` | 全域安裝 `@google/jules` 並完成 `jules login` | `JULES_API_KEY` |

> **註：google-jules 提供的 8 組工具**：create_session、list_sessions、get_session_state、get_bash_outputs、get_code_review_context、show_code_diff、send_reply_to_session、query_cache

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

**待改善**：評估改用 `notebooklm-mcp`（依賴 PATH 解析）或 `python -m`
的呼叫方式，避免寫死版本號路徑。

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
