# Antigravity Environment Baseline — IDE 2.5.5

## 1. Purpose and Evidence Boundary

本文件記錄 HH.AI_v2 在 Antigravity IDE 2.5.5 下的 Agent 權限、GitHub MCP、Web Access 與 Git Credential Manager 操作基準。

本文件用途：

- 換電腦；
- 重新安裝 Antigravity；
- IDE 更新後重新驗證；
- 權限漂移檢查；
- K6-A posture recovery。

本文件不是 secret store。

嚴禁放入：

- credential value；
- token；
- PAT；
- OAuth secret；
- Windows 實際使用者名稱；
- 使用者完整 absolute path；
- transcript；
- credential hash / prefix / suffix / length。

本文件中的 Antigravity UI 狀態：

evidence_origin = USER_PROVIDED

verified IDE version = 2.5.5

所有 UI 結論都綁定此版本。

---

## 2. Step 0 — Reuse Before Reset

換電腦、重新安裝或登入同一帳號後：

第一步不是直接重設。

先打開 Antigravity Settings
檢查下列項目
是否已自動帶入。

可能來源包括：

- account-level synchronization；
- IDE internal storage；
- 其他未確認的 persistence mechanism。

若目標設定已存在：

只做逐項核對。

不要重複新增。

若設定不存在或漂移：

才依本文件手動恢復。

不要假設 permissions 一定會或一定不會跨裝置同步。

---

## 3. Terminal Permission Baseline

### 3.1 Terminal Command Auto Execution

Target：

Always Proceed

### 3.2 Deny List Terminal Commands

EXACT target entries：

- `git branch -D`
- `git checkout`
- `git clean`
- `git commit --amend`
- `git credential`
- `git rebase`
- `git reset`
- `git restore`
- `git stash`

`git push`：

NOT in Deny list。

原因：

K5-A 已取消每次 main push
額外 human approval。

main advancement 的控制點改為：

- External Macro-issued unique full-SHA promotion prompt；
- server-side ruleset；
- exact-SHA required checks；
- same-SHA post-main verification；
- External Macro final audit。

### 3.3 Allow List Terminal Commands

Target：

empty

### 3.4 Expected Deny Behavior

Antigravity IDE 2.5.5
Deny entry 的效果是：

match 時要求 permission

不是 hard block。

例如：

`git checkout`

可能同時命中：

`git checkout -b`

因此正常建立 branch
可能需要使用者批准一次。

不得因為 permission prompt
而改用其他指令
刻意繞過 K6。

---

## 4. Agent Security / Context Baseline

Agent security mode：

Full access

History：

enabled

Knowledge：

enabled

但：

History / Knowledge
只能作 context。

不得作：

production authority
repo truth
Git truth
GitHub truth
audit verdict authority。

production-impact facts
必須由 current：

repo
Git
GitHub

重新驗證。

Agent Non-Workspace File Access：

Off

---

## 5. Advanced File Access Baseline

### 5.1 Removed Write Permission

已移除：

old repo `.env.local`

之 unconditional write permission。

### 5.2 Removed Read Permissions

已移除：

`.gemini\antigravity\skills`

之 unconditional read permission。

已移除：

`%USERPROFILE%\Desktop`

整個桌面
之 unconditional read permission。

目的：

避免 Agent
在 workspace 外
無條件讀取：

- 舊 repo secret-bearing files；
- `.env.local`；
- 交接資料；
- unrelated desktop content。

HH.AI_v2
作為開啟中的 workspace
不依賴此 Desktop-wide allow。

### 5.3 Residual Legacy Permissions — Cleanup Backlog

以下 USER_PROVIDED UI categories
目前仍存在，
本次 K6 未清除。

它們不是 future reinstall 的 target。

不要主動重建。

若 UI 中仍存在，
由 B-108 後續低優先清理
逐項確認後再移除。

Read residuals：

- `%USERPROFILE%\.antigravity-ide\extensions`
- `%USERPROFILE%\.pm2\logs`
- Python installation directory entries × 3
- `%USERPROFILE%\Desktop\交接手冊` 下 legacy read entries × 2
- old project `skills\03_Execution` read entry

Write residuals：

- old project `skills\03_Execution...` legacy write entries × 5
- `%USERPROFILE%\Desktop\migrate_orch.py`
- `%USERPROFILE%\Desktop\migrate.py`
- `%USERPROFILE%\Desktop\交接手冊` 下 legacy write entries × 2
- `%USERPROFILE%\Desktop\門禁評估\generate_ppt.py`

其中沒有完整精確 UI path
由 current authoritative evidence 提供者：

不得自行補寫或猜測。

後續清理以實際 UI
當下顯示值為準。

---

## 6. MCP Permission Baseline

### 6.1 Permanent Allow List

GitHub MCP permanent Allow
不應包含 write / mutation tools。

已移除 permanent Allow：

- `github-mcp-server/add_issue_comment`
- `github-mcp-server/create_branch`
- `github-mcp-server/create_pull_request`
- `github-mcp-server/create_repository`
- `github-mcp-server/merge_pull_request`
- `github-mcp-server/update_pull_request`

另已移除：

- `chrome-devtools-mcp/evaluate_script`

原因：

`evaluate_script`
可在 browser page context
執行任意程式碼，
可形成 URL permission 旁路。

目前 USER_PROVIDED
已知保留之 GitHub read-class
permanent Allow entries：

- `get_commit`
- `get_me`
- `list_branches`
- `list_pull_requests`
- `list_workflow_runs`
- `pull_request_read`

若未來 UI naming 改變：

不得依名稱猜測 write/read semantics。

必須重新驗證。

---

## 7. GitHub MCP Server Tool Baseline

Antigravity IDE 2.5.5
Manage MCP Servers → GitHub：

target：

24 / 42 enabled

18 / 42 disabled

### 7.1 Disabled 18 Tools

EXACT disabled set：

1. `add_comment_to_pending_review`
2. `add_issue_comment`
3. `add_reply_to_pull_request_comment`
4. `assign_copilot_to_issue`
5. `create_branch`
6. `create_or_update_file`
7. `create_pull_request`
8. `create_repository`
9. `delete_file`
10. `fork_repository`
11. `issue_write`
12. `merge_pull_request`
13. `pull_request_review_write`
14. `push_files`
15. `request_copilot_review`
16. `sub_issue_write`
17. `update_pull_request`
18. `update_pull_request_branch`

### 7.2 Enabled Set

Current authoritative evidence
沒有列出另外 24 個工具
的逐一名稱。

因此不得杜撰。

在 IDE 2.5.5
相同 42-tool inventory 下：

enabled set
定義為：

42-tool set
MINUS
§7.1 exact disabled 18

結果必須：

24 enabled / 42 total。

如果未來 IDE：

total tool count != 42

或 tool names 改變：

不要強行套用 24/42。

STOP production work
並重新做 capability / permission revalidation。

### 7.3 Other MCP Servers

本次 K6
沒有修改：

- Chrome DevTools
- docker
- google-jules
- Notion

此處不代表
這些 server 的所有 tools
都已安全審查。

---

## 8. Advanced Web Access Baseline

### Execute URLs

Target：

- `localhost`

`github.com`
不得存在於
unconditional Execute URLs allow。

### Read URLs

Target entries：

- `github.com`
- `raw.githubusercontent.com`
- `sinotrade.github.io`

Read permission
不等於 mutation authorization。

---

## 9. Git Credential Manager Baseline

Verified USER_PROVIDED
Git Credential Manager version：

2.9.0

### 9.1 Interactive Login

使用者本人可在自己的 terminal：

`git credential-manager github login`

透過 browser
完成 GitHub authentication。

### 9.2 Account Listing

使用者本人可執行：

`git credential-manager github list`

用於列出 account identity。

不得把 secret value
輸出或複製。

### 9.3 Forbidden Command for Executor

Executor 永遠不得執行：

`git credential fill`

也不得執行任何等價
credential extraction。

Executor 不得：

- read OAuth token；
- read PAT；
- enumerate credential store；
- read Windows Credential Manager secret；
- build Authorization header from local credential；
- use credential value in inline script。

若 Git operation
要求 interactive browser authentication：

等待使用者本人完成。

不得繞過。

---

## 10. Secret / Remote Evidence Ownership

Executor
不得為取得 remote evidence
突破 secret boundary。

特別是：

GitHub Actions raw job log
由 External Macro Auditor
負責驗證。

Executor
若只能安全取得：

- run ID；
- event；
- head branch；
- head SHA；
- attempt；
- status；
- conclusion；

就只回報這些 metadata。

若 evidence
無法在不讀 credential 的前提下取得：

回報：

`UNKNOWN / DEFER_TO_EXTERNAL_MACRO`

不是 failure。

禁止為了達成提示詞
而自行突破 credential boundary。

---

## 11. IDE Update Revalidation

production batch
執行途中：

不得更新 Antigravity IDE。

IDE 更新後，
開始下一個 production batch 前：

只做 UI / capability revalidation。

至少確認：

1. About 顯示的新 IDE version；
2. HH.AI_v2 Rules list；
3. actual customization / token usage；
4. Terminal Deny list 仍存在；
5. Allow list 沒有危險漂移；
6. Advanced File Access；
7. Agent Non-Workspace File Access；
8. MCP permanent Allow；
9. GitHub MCP server tool enable/disable state；
10. Advanced Web Access；
11. Full access / Always Proceed posture。

若 GitHub MCP：

total tool inventory
仍為 42：

應確認：

§7.1 的 18 tools
仍 disabled，

結果為：

24 / 42 enabled。

若 inventory
已不是 42：

不得照抄舊 count。

重新評估。

若任何 permission anomaly：

STOP production。

---

## 12. Settings Persistence Findings

USER_PROVIDED
唯讀查證：

`%APPDATA%\Antigravity IDE\User\settings.json`

只觀察到一般設定，
沒有找到上述 Agent permissions。

以字串：

`git credential`

搜尋時：

`%USERPROFILE%\.gemini`

排除 brain 後
只命中：

Antigravity conversation database

不是已確認 settings store。

`%APPDATA%\Antigravity IDE`

未取得可確認的
permission settings file。

因此目前結論：

permission settings
可能存於：

- internal / compressed storage；
- account synchronization；
- 其他未確認機制。

UNKNOWN。

不得繼續做 invasive environment probing。

本文件即為：

manual recovery / verification baseline。

---

## 13. Recovery Procedure Summary

新電腦、重新安裝或 IDE 更新後：

0.
先檢查設定是否已自動同步。

1.
確認 IDE version。

2.
確認 Terminal：

Always Proceed
+
9-entry Deny list
+
empty Allow list。

3.
確認 Full access、
History、
Knowledge、
Non-Workspace File Access。

4.
確認 Advanced File Access。

5.
確認 GitHub MCP permanent Allow。

6.
確認 GitHub server disabled 18
及 inventory count。

7.
確認 Execute / Read URLs。

8.
如需新的 Git authentication，
由使用者本人使用：

`git credential-manager github login`

9.
永遠不得讓 Executor
使用：

`git credential fill`

10.
完成後再開始 production batch。

---

## 14. Version Binding

本文件的已驗證基準：

Antigravity IDE 2.5.5

任何 IDE 更新：

都會使 runtime-dependent
permission / capability assumption
進入：

REVALIDATION REQUIRED

直到 §11
完成為止。
