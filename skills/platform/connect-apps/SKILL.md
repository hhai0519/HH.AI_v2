---
name: connect-apps
description: "操控 Gmail、Slack、GitHub、Notion 等外部服務執行自動化任務。當使用者要求『在 Slack 發通知』、『建立 GitHub Issue』、『更新 Notion 頁面』、『發送郵件』或『跨系統資料同步』時使用。"
disable-model-invocation: true
---

# 外部應用連接器 (Connect Apps)

### 【摘要】觸發條件與 DLP 聲明
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議

本技能讓 本協作系統 Agent **直接操控外部服務**，包括 Gmail、Slack、GitHub、Notion、Calendar 等，透過 API 自動化完成跨平臺任務，無需使用者手動切換應用程式。

---

## 🎯 觸發條件

- 「幫我發一封資訊給...」「在 Slack 發通知」
- 「建立一個 GitHub Issue」「更新 Notion 頁面」
- 「把這個結果分享到...」
- 需要跨系統資料同步或自動化通知

---

## 🛠️ 支援服務矩陣

| 服務 | 支援操作 | 認證方式 |
|---|---|---|
| **Gmail** | 讀取/發送/搜尋郵件、管理標籤 | OAuth2 |
| **Slack** | 發送訊息、建立頻道、上傳檔案 | Bot Token |
| **GitLab** | Issues/MR/Commits/CI-CD (新預設) | Personal Token |
| **GitHub** | Issues/PR/Commits/Releases (受限) | Personal Token |
| **Notion** | 頁面讀寫、資料庫查詢 | Integration Token |
| **Google Calendar** | 建立/讀取/修改事件 | OAuth2 |
| **Discord** | 發送訊息、Webhook 觸發 | Webhook URL |
| **LINE Notify** | 推播通知 | Token |

---

## 🤝 協同技能

- `notebooklm-mcp`：將外部資料源匯入知識庫
- `changelog-generator`：GitHub commit → Slack 發佈公告

---

## 🛠️ 技術細節與 API 參考

關於各個服務的標準整合模式、認證管理最佳實踐與自動化工作流範例，請參考：
👉 **[REFERENCE.md](./REFERENCE.md)**
