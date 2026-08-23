---
name: notebooklm-mcp
description: "操控 NotebookLM 建立知識庫、進行深度研究與生成報告音頻。當使用者要求『建立 NotebookLM 筆記本』、『製作 Podcast/Audio Overview』、『跨筆記本知識查詢』或『從 URL/PDF 建立知識庫』時使用。"
---

# NotebookLM 智庫整合 (NotebookLM MCP)

### 【摘要】觸發條件與 DLP 聲明
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議

本技能透過 **NotebookLM MCP Server** 讓 本協作系統 Agent 直接自動化操控 Gemini Notebook (formerly Google NotebookLM)，實現：批量建立知識庫、多源研究彙整、Podcast 製作、AI 報告生成，以及跨 Notebook 的深度知識交叉查詢。

---

## 🎯 觸發條件

- 提到「notebooklm」「nlm」「podcast」「audio overview」
- 需要建立或管理知識筆記本
- 需要生成 AI 研究報告、音頻摘要或 Podcast
- 需要從 URL、YouTube、PDF、Google Drive 建立知識庫
- 需要跨筆記本的知識合併查詢

---

## 🛠️ 核心功能矩陣

本 MCP 伺服器包含 43 個強大工具，近期新增 `label`, `studio_revise`, `note`, `pipeline` 等自動化控制單元。

| 功能類別 | MCP 工具 | 說明 |
|---|---|---|
| **筆記本管理** | `notebook_create/list/get/rename` | 建立、列出、查詢、重命名 |
| **來源添加** | `source_add` | url / text / drive / file 四種類型 |
| **AI 查詢** | `notebook_query` | 對已有來源進行 AI 問答 |
| **異步查詢** | `notebook_query_start/status` | 大型筆記本的非阻塞查詢 |
| **內容生成** | `studio_create` | audio/video/report/quiz/flashcards/mind_map |
| **深度研究** | `research_start/status/import` | 自動網頁搜索並匯入結果 |
| **批量操作** | `batch` | 批量查詢 / 建立 / 新增來源 |
| **下載輸出** | `download_artifact` | 下載 MP4/PDF/JSON/CSV 等格式 |
| **分享協作** | `notebook_share_invite` | 邀請協作者 |

---

## 🤝 協同技能

- `csv-data-summarizer`：下載的 data_table 後續統計分析

---

## 🛠️ 技術細節與 API 參考

關於完整工作流範例、內容生成類型對照、認證管理以及重要限制，請參考：
👉 **[REFERENCE.md](./REFERENCE.md)**
