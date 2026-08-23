# changelog-generator Reference

## Step 2：Commit 分類引擎

```python
import subprocess
import re
from collections import defaultdict

CATEGORIES = {
    "✨ 新功能": ["feat:", "feature:", "add:", "新增", "新功能"],
    "🐛 錯誤修復": ["fix:", "bugfix:", "hotfix:", "修復", "修正", "bug"],
    "⚡ 效能優化": ["perf:", "optimize:", "speed:", "效能", "優化"],
    "🔧 維護更新": ["chore:", "refactor:", "cleanup:", "重構"],
    "📚 文件更新": ["docs:", "doc:", "文件", "readme"],
    "🛡️ 安全更新": ["security:", "sec:", "auth:", "安全"],
    "💥 重大變更": ["BREAKING CHANGE", "breaking:", "major:"]
}

def categorize_commits(commits: list) -> dict:
    categorized = defaultdict(list)

    for commit in commits:
        hash_, msg, author, date = commit.split('|', 3)
        assigned = False

        for category, keywords in CATEGORIES.items():
            for kw in keywords:
                if kw.lower() in msg.lower():
                    categorized[category].append({
                        "hash": hash_,
                        "message": clean_commit_msg(msg, kw),
                        "author": author,
                        "date": date
                    })
                    assigned = True
                    break
            if assigned:
                break

        if not assigned:
            categorized["🔧 維護更新"].append({
                "hash": hash_, "message": msg,
                "author": author, "date": date
            })

    return categorized

def clean_commit_msg(msg: str, prefix: str) -> str:
    """移除 conventional commit 前綴，首字母大寫"""
    cleaned = re.sub(r'^(feat|fix|perf|chore|docs|security|refactor)\s*[:\(][^)]*\)?\s*', '', msg, flags=re.I)
    return cleaned.strip().capitalize() if cleaned.strip() else msg
```

## Step 3：技術語言 → 使用者語言 轉換

```python
# LLM 轉換 Prompt
HUMANIZE_PROMPT = """
你是一個技術作家。將以下技術 commit 訊息，改寫成使用者友好的說明。

規則：
1. 用「您」或「你」的角度描述使用者獲得的好處
2. 避免技術術語（如「重構」「refactor」「config」）
3. 每條控制在 50 字以內
4. 繁體中文

技術訊息：{commit_msg}
使用者友好版本：
"""

def humanize_commits(commits: list) -> list:
    return [llm_call(HUMANIZE_PROMPT.format(commit_msg=c['message'])) for c in commits]
```

## Step 4：生成標準 Changelog

```python
def generate_changelog(version: str, date: str, categorized: dict) -> str:
    lines = [
        f"# v{version} ({date})",
        "",
        "> 感謝您使用我們的產品！以下是本次更新的重要內容：",
        ""
    ]

    # 重大變更優先顯示
    priority_order = ["💥 重大變更", "✨ 新功能", "🐛 錯誤修復",
                      "⚡ 效能優化", "🛡️ 安全更新", "📚 文件更新", "🔧 維護更新"]

    for category in priority_order:
        if category in categorized and categorized[category]:
            lines.append(f"## {category}")
            for commit in categorized[category]:
                lines.append(f"- {commit['message']}")
            lines.append("")

    return '\n'.join(lines)
```

## 📄 標準輸出格式範例

```markdown
# v2.3.0 (2026-04-17)

> 感謝您使用我們的產品！以下是本次更新的重要內容：

## ✨ 新功能
- 新增技能儀錶板的黑暗模式切換功能
- 支援從 Google Drive 直接匯入研究文件

## 🐛 錯誤修復
- 修復在 Windows 環境下中文字型無法正確顯示的問題
- 解決技能卡片在手機裝置上點擊無效的問題

## ⚡ 效能優化
- 技能儀錶板載入速度提升 40%

## 🛡️ 安全更新
- 加強 API Token 的加密儲存機制
```
