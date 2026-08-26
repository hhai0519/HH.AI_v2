# Platform

平台整合（LINE/Telegram/MCP/Postgres 等外部串接）。

## User-invoked

- **[connect-apps](./connect-apps/SKILL.md)** — 操控 Gmail、Slack、GitHub、Notion 等外部服務執行自動化任務。當使用者要求『在 Slack 發通知』、『建立 GitHub Issue』、『更新 Notion 頁面』、『發送郵件』或『跨系統資料同步』時使用。
- **[postgres](./postgres/SKILL.md)** — 對多個 PostgreSQL 資料庫執行唯讀 SQL 查詢。支援結構探索、資料分析和品質檢查。為確保安全，封鎖所有寫入操作。
- **[mcp-gateway](./mcp-gateway/SKILL.md)** — Zero-Trust 萬用執行閘道器。負責啟動並連接所有的 MCP 伺服器，目前為未實作的設計草案。

## Model-invoked

- **[notebooklm-mcp](./notebooklm-mcp/SKILL.md)** — 操控 NotebookLM 建立知識庫、進行深度研究與生成報告音頻。當使用者要求『建立 NotebookLM 筆記本』、『製作 Podcast/Audio Overview』、『跨筆記本知識查詢』或『從 URL/PDF 建立知識庫』時使用。
- **[langsmith-fetch](./langsmith-fetch/SKILL.md)** — 從 LangSmith 獲取執行追蹤以偵錯 Agent 行為。
- **[json-to-flex-renderer](./json-to-flex-renderer/SKILL.md)** — 將 JSON 分析報告純程式化轉換為 LINE Flex Message。