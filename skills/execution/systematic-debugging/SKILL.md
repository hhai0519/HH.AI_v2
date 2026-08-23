---
name: systematic-debugging
description: 當遇到 MCP 連接失敗、工具載入錯誤、npm/pip 安裝失敗、Docker 問題、JSON 設定語法錯誤或本地環境中的任何異常行為時，在提出任何修正方案前使用此技能。強制執行「先找根本原因、再提修正」的四階段除錯流程。
---

# 系統化除錯技能 (Systematic Debugging)

隨機嘗試修正浪費時間且製造新問題。快速補丁只是掩蓋根本原因。

**Core principle:** 永遠先找到根本原因，才能提出修正。症狀修補是失敗的除錯。

**The Iron Law:**
```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

## When to Use

適用於本地環境的任何技術問題：
- MCP 伺服器無法載入或連線失敗
- npm / pip 安裝錯誤（404、permission denied、version conflict）
- Docker 錯誤（container exits, gateway OAuth errors）
- JSON 設定語法問題（工具全部消失）
- 工具數量超出 100 上限
- 瀏覽器子代理人操作失敗
- `BLOCKED` 狀態的子代理人（連續 2 次以上）

**尤其要用在：**
- 時間緊迫時（緊急感讓猜測變得誘人，但系統化更快）
- 「這應該很簡單」的問題（簡單問題也有根本原因）
- 已經試過多次修正卻失敗

## The Four Phases

完成每個階段後才能進入下一個。詳細步驟請見 [REFERENCE.md](./REFERENCE.md)。

- **Phase 1**：根本原因調查（修正前必做）
- **Phase 2**：模式分析（比對正常與異常的差異）
- **Phase 3**：假說與測試（單一假說、最小化測試）
- **Phase 4**：實作修正（≥3 次失敗 → 質疑架構）

## 本地環境常見問題速查

| 症狀 | 最可能的根本原因 | Phase 1 第一步 |
|------|----------------|----------------|
| 所有工具消失 | JSON 語法錯誤 | 驗證 mcp_config.json 格式 |
| 工具超出 100 上限 | 新增 MCP 超出額度 | 計算各 MCP 工具數，找可停用的 |
| MCP server 啟動失敗 | 執行檔路徑錯誤或不存在 | `Test-Path <executable>` |
| GitHub MCP 連線失敗 | PAT 過期 / Docker 未啟動 | `docker ps` + 確認 PAT 有效期 |
| NotebookLM 認證錯誤 | Session 過期 | `nlm doctor` 接著 `nlm login` 重新登入 |
| Docker OAuth 警告 | Docker Desktop 背景服務 | 確認 Docker Desktop 已開啟，可忽略 |
| npm 404 錯誤 | 套件名稱錯誤 | 確認官方文件中的正確 npm 套件名 |

## Red Flags — 停下來，回到 Phase 1

如果你發現自己在想：
- 「快速修一下，之後再查原因」
- 「就改 X 看看」
- 「同時改多個地方，跑看看」
- 「不完全理解，但這個可能有用」
- 「再試一次修正」（已失敗 2 次以上）

**以上全都代表：停止。回到 Phase 1。**

## 🤝 協同技能

- `notebooklm-mcp`：NotebookLM 相關問題的專屬指令參考
