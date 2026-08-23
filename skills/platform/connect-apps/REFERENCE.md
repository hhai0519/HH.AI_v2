# 外部應用連接器 (Connect Apps) - 技術細節參考

## 📋 標準整合模式

### Gmail 整合

```python
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import base64
from email.mime.text import MIMEText

def send_email(to: str, subject: str, body: str, credentials_file: str):
    """透過 Gmail API 發送郵件"""
    creds = Credentials.from_authorized_user_file(credentials_file)
    service = build('gmail', 'v1', credentials=creds)
    
    message = MIMEText(body, 'html')
    message['to'] = to
    message['subject'] = subject
    
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(
        userId='me',
        body={'raw': raw}
    ).execute()
    
    return f"✅ 郵件已成功發送至 {to}"

def search_emails(query: str, max_results: int = 10):
    """搜尋 Gmail"""
    # query 語法: "from:boss@company.com after:2026/01/01"
    results = service.users().messages().list(
        userId='me', q=query, maxResults=max_results
    ).execute()
    return results.get('messages', [])
```

### Slack 整合

```python
from slack_sdk import WebClient

def send_slack_message(channel: str, text: str, token: str, blocks: list = None):
    """發送 Slack 訊息（支援 Block Kit 富文本）"""
    client = WebClient(token=token)
    
    payload = {"channel": channel, "text": text}
    if blocks:
        payload["blocks"] = blocks
    
    result = client.chat_postMessage(**payload)
    return f"✅ 訊息已發送至 #{channel} (ts: {result['ts']})"

# Block Kit 範例（帶按鈕的通知卡片）
ALERT_BLOCK = [
    {
        "type": "section",
        "text": {"type": "mrkdwn", "text": "*🚨 系統警報*\n服務 `webapp` 偵測到異常！"},
    },
    {
        "type": "actions",
        "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "📊 查看詳情"}, "style": "danger"},
            {"type": "button", "text": {"type": "plain_text", "text": "✅ 確認處理"}, "style": "primary"}
        ]
    }
]
```

### GitLab 整合 (New Default)

```python
import requests

class GitLabAPI:
    BASE = "https://gitlab.com/api/v4"
    
    def __init__(self, token: str, project_id: str):
        # project_id 可以是數字 ID 或 URL-encoded 的完整路徑 (如 "group%2Fproject")
        self.headers = {
            "Private-Token": token,
            "Content-Type": "application/json"
        }
        self.project_id = project_id
    
    def create_issue(self, title: str, description: str, labels: str = "") -> dict:
        resp = requests.post(
            f"{self.BASE}/projects/{self.project_id}/issues",
            headers=self.headers,
            json={"title": title, "description": description, "labels": labels}
        )
        issue = resp.json()
        return {"url": issue.get('web_url'), "id": issue.get('iid')}
    
    def list_issues(self, state: str = "opened") -> list:
        resp = requests.get(
            f"{self.BASE}/projects/{self.project_id}/issues?state={state}",
            headers=self.headers
        )
        return [{"title": i['title'], "url": i['web_url']} for i in resp.json()]
```

### GitHub 整合 (Legacy)

```python
import requests

class GitHubAPI:
    BASE = "https://api.github.com"
    
    def __init__(self, token: str, owner: str, repo: str):
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        self.repo = f"{owner}/{repo}"
    
    def create_issue(self, title: str, body: str, labels: list = []) -> dict:
        resp = requests.post(
            f"{self.BASE}/repos/{self.repo}/issues",
            headers=self.headers,
            json={"title": title, "body": body, "labels": labels}
        )
        issue = resp.json()
        return {"url": issue['html_url'], "number": issue['number']}
```

---

## 🔐 認證管理最佳實踐

```python
# 集中管理所有服務憑證（使用環境變數，永不硬編碼）
import os

CREDENTIALS = {
    "slack_token": os.environ.get("SLACK_BOT_TOKEN"),
    "gitlab_token": os.environ.get("GITLAB_TOKEN"),
    "github_token": os.environ.get("GITHUB_TOKEN"),
    "notion_token": os.environ.get("NOTION_TOKEN"),
}

# 驗證所有必要憑證
def validate_credentials(services: list):
    missing = [s for s in services if not CREDENTIALS.get(f"{s}_token")]
    if missing:
        raise ValueError(f"缺少以下服務的 Token：{', '.join(missing)}\n請在環境變數或 .env 中設定")
```

---

## 🔄 自動化工作流範例

```
工作流：「每日下午 5 點，彙整當日 GitHub PR 並發送摘要到 Slack #team 頻道」

1. GitHub: list_merged_prs(since=today_9am)
2. 整理 PR 清單（標題、作者、連結）
3. 格式化為 Slack Block Kit 卡片
4. Slack: send_message(channel="#team", blocks=card)
```
