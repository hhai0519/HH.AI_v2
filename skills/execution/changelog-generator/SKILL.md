---
name: changelog-generator
description: 透過分析提交歷史、對變更進行分類，並將技術性提交訊息轉換為清晰、對客戶友好的發佈說明，從 Git 提交紀錄自動生成面向使用者的版本日誌。當需要產出 Release Notes、整理 changelog、準備 GitHub Release 或為非技術使用者說明更新內容時觸發。
---

# 版本日誌生成器 (Changelog Generator)

本技能自動解析 git commit 歷史，將晦澀的技術提交訊息**轉化為使用者友好的版本發佈說明**，支援 Keep a Changelog 標準格式、Conventional Commits 規範，以及自定義分類策略。

## 🎯 觸發條件

- 需要產出新版本的 Release Notes
- 詢問「把這些 commit 整理成 changelog」
- 準備 GitHub Release / 產品公告
- 需要為非技術使用者說明本次更新內容

## 🛠️ 核心工作流程

### Step 1：提取 Commit 歷史

```bash
# 提取上一個 tag 到現在的所有 commit
git log v1.0.0..HEAD --pretty=format:"%h|%s|%an|%ad" --date=short

# 或提取最近 N 個 commit
git log -30 --pretty=format:"%h|%s|%an|%ad" --date=short
```

## 🔧 CLI 快速使用

```bash
# 從上個 TAG 到現在
python changelog_gen.py --from-tag v1.2.0 --version 1.3.0

# 最近 50 個 commits
python changelog_gen.py --count 50 --version 1.3.0

# 輸出到文件
python changelog_gen.py --version 1.3.0 --output CHANGELOG.md
```

## 🤝 協同技能

- `handover-manual-skill`：版本交接文件整合
- `notebooklm-mcp`：將 changelog 匯入知識庫存檔

> [!NOTE]
> Commit 分類引擎、技術語言轉換、標準輸出格式範例請見 [REFERENCE.md](./REFERENCE.md)
