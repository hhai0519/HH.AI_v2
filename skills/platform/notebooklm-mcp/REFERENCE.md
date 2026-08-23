# NotebookLM 智庫整合 (NotebookLM MCP) - 技術細節參考

## 📋 完整工作流範例

### 工作流 1：快速資料入庫 → 查詢

```
Step 1: mcp_notebooklm_notebook_create(title="臺股籌碼分析")
Step 2: mcp_notebooklm_source_add(source_type="url", url="https://...")
Step 3: mcp_notebooklm_source_add(source_type="text", text="...", title="研究摘要")
        ↑ 等待 2~3 分鐘讓 NotebookLM 處理來源
Step 4: mcp_notebooklm_notebook_query(query="主要的籌碼資訊號有哪些？")
```

### 工作流 2：深度研究 → 報告生成

```
Step 1: mcp_notebooklm_research_start(query="臺積電法人籌碼分析", mode="deep")
Step 2: mcp_notebooklm_research_status(notebook_id=...) → 輪詢直到 completed
Step 3: mcp_notebooklm_research_import(notebook_id=..., task_id=...)
Step 4: mcp_notebooklm_studio_create(artifact_type="report", report_format="Briefing Doc")
Step 5: mcp_notebooklm_download_artifact(artifact_type="report", output_path="./report.md")
```

### 工作流 3：Podcast 製作（Audio Overview）

```
Step 1: 確認筆記本有足夠來源（建議 5+ 個來源）
Step 2: mcp_notebooklm_studio_create(
          artifact_type="audio",
          audio_format="deep_dive",  # 或 "briefing"
          audio_length="default"
        )
Step 3: mcp_notebooklm_studio_status(notebook_id=...) → 等待生成（約 3~5 分鐘）
Step 4: mcp_notebooklm_download_artifact(artifact_type="audio", output_path="./podcast.mp4")
```

### 工作流 4：跨筆記本知識整合查詢

```python
# 向多個筆記本同時提問，彙整答案
mcp_notebooklm_cross_notebook_query(
    query="恐慌指數超過 30 的歷史案例",
    notebook_names="臺股籌碼分析, 市場恐慌指數研究, ADR 連動分析"
)
```

---

## 📦 內容生成類型對照

| artifact_type | 格式選項 | 用途 |
|---|---|---|
| `audio` | deep_dive / briefing | Podcast、語音摘要 |
| `video` | explainer | 視頻概覽 |
| `report` | Briefing Doc / Study Guide / Blog Post | 文字報告 |
| `quiz` | json / markdown / html | 測驗題目 |
| `flashcards` | json / markdown | 學習卡片 |
| `mind_map` | JSON | 思維導圖 |
| `slide_deck` | pdf / pptx | 投影片 |
| `infographic` | PNG | 資訊圖表 |
| `data_table` | CSV | 結構化資料表 |

---

## 🔐 認證管理

> [!WARNING]
> Antigravity IDE 的擴充套件可能干擾 Chrome 的背景登入。若發生 `401 Unauthorized` 錯誤，強烈建議使用 Edge 進行登入 (`nlm config set auth.browser edge`) 或採用 File Mode 擷取 Cookie。

```bash
# 診斷環境與連線
nlm doctor

# 首次登入（在終端執行）
nlm login

# 切換 Google 帳號
nlm login switch <profile>

# 重新整理 token（若出現 401）
mcp_notebooklm_refresh_auth
```

---

## ⚠️ 重要限制

| 限制 | 數值 | 應對方法 |
|---|---|---|
| 單筆記本來源數上限 | ~300 個 | 拆分為多個筆記本 |
| Audio 生成時間 | 3~10 分鐘 | 用 studio_status 輪詢 |
| 深度研究時間 | ~5 分鐘 | 用 research_status 輪詢 |
| 查詢 timeout 預設 | 120 秒 | 大型筆記本用 notebook_query_start |
