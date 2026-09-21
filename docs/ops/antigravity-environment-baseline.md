# Antigravity Environment Baseline & Recovery Checklist — IDE 2.5.5

## 0. Trigger & Mandatory Pre-Production Prerequisite

本文件為 HH.AI_v2 在 Antigravity IDE 2.5.5 下的環境安全設定與災後恢復檢核清單（Recovery Checklist）。

以下事件任一發生時：

1. **新電腦設定（New Computer Setup）**
2. **重新安裝 Antigravity（Antigravity Reinstall）**
3. **IDE 版本更新（IDE Version Update）**

在任何 production batch 工作開始前，**必須先完成本文件的 Environment Baseline Checklist 與重啟核對**。
平時正常 production batch 則不需要每批重新設定或重啟。

---

## 1. Purpose and Evidence Boundary

本文件記錄 Agent 權限、GitHub MCP、Web Access、Git Credential Manager 操作基準與分層持久性事實。

本文件用途：
- 換電腦（New computer trigger）；
- 重新安裝 Antigravity（Reinstall trigger）；
- IDE 更新（IDE update trigger）；
- 權限漂移核對；
- K6-A posture recovery。

本文件不是 secret store。嚴禁放入任何 credential value、token、PAT、OAuth secret、Windows 實際使用者名稱、使用者個人桌面實際目錄路徑、transcript、credential hash / prefix / suffix / length。所有桌面個人資料夾均使用泛稱。

證據來源：`evidence_origin = USER_PROVIDED`，`verified IDE version = 2.5.5`。

---

## 2. Updated K6-A Architecture — Two Layers

Antigravity IDE 2.5.5 的安全防護架構明確拆分為兩層：

1. **PERSISTENT LAYER（持久防護層）**：經實測在 IDE 重啟後可持久保存之設定，為目前主要防禦層（defense-in-depth）。
2. **NON-PERSISTENT / DEPRECATED LAYER（非持久／棄用層）**：重啟後會遺失或失效之舊設定，已正式廢除，不得作為安全權威。

### 2.1 PERSISTENT LAYER

A. **Advanced File Access 收斂**：
- old repo `.env.local` unconditional write 已移除；
- `%USERPROFILE%\Desktop` broad unconditional read 已移除（桌面目錄使用泛稱）；
- obsolete `.gemini\antigravity\skills` unconditional read 已移除。
- 此類刪除：`USER_PROVIDED` restart-persistent observed。

B. **MCP permanent Allow 收斂**：
- GitHub write / mutation tools 已全數移除 permanent Allow；
- `chrome-devtools-mcp/evaluate_script` 已移除 permanent Allow；
- 此類設定：`USER_PROVIDED` restart-persistent observed。

C. **Manage MCP Servers → GitHub**：
- 18 write-capable tools disabled，24 / 42 enabled；
- restart-persistent observed。

D. **Advanced Command Access → Terminal Commands**：
- 12 entries 全部設為 **Deny**；
- 明確不在 Deny：`git push`、`git switch -c`；
- 持久性證據精度（Direct-vs-inferred persistence distinction）：
  - **DIRECTLY RESTART-VERIFIED**：`git credential`、`git reset`。
  - **SAME-MECHANISM PERSISTENCE INFERENCE**：其餘 10 entries（`--delete`、`git branch -D`、`git checkout`、`git clean`、`git commit --amend`、`git rebase`、`git restore`、`git stash`、`git switch --discard-changes`、`git switch -C`）位於同一持久清單中，為同機制推論，非逐一重啟測試事實。下次正常重啟可順便確認，但不得當作每批 production 之前提。

E. **Advanced Web Access → Execute URLs**：
- `localhost` = Allow
- `github.com` = Deny
- `github.com` = Deny 已經 `USER_PROVIDED` restart-persistent verified。
- **重要限制警告**：限制 `github.com` 必須保留 entry 並明確設定為 `Deny`，**不得靠 delete entry 表達限制**。

### 2.2 NON-PERSISTENT / DEPRECATED LAYER

- **舊「Deny List Terminal Commands」**：實測重啟後會清空（restart -> empty），已正式標記為 **DEPRECATED / NON-PERSISTENT / DO NOT USE**。不得作為 production prerequisite、security authority 或 recovery target。
- **Execute URLs delete-to-restrict**：實測若直接 delete `github.com` entry，重啟後 `github.com` 會重新以 `Allow` 出現。因此 delete entry 不得視為 web 限制手段。

---

## 3. Step 0 — Check Before Reapply

換電腦、重新安裝或登入帳號後：

1. **先檢查設定是否已自動帶回**：透過 account synchronization、本機既有狀態或其他 persistence 機制，設定可能已存在。
2. **若目標設定已存在**：只做逐項核對（verification only），**不要重複建立或覆蓋**。
3. **若設定不存在或漂移**：才依照第 4 節 UI 操作步驟逐步建立。

---

## 4. UI Instructions & Recovery Configuration

進入 Antigravity IDE Settings，找到以下 sections 逐項設定：

### 4.1 Terminal Command Auto Execution
- **Target**：`Always Proceed`

### 4.2 Advanced Command Access → Terminal Commands
點擊 **Add entry**，逐條輸入以下 **12 entries**（12 Deny entries），並將下拉選單設為 **Deny**：

```text
--delete
git branch -D
git checkout
git clean
git commit --amend
git credential
git rebase
git reset
git restore
git stash
git switch --discard-changes
git switch -C
```

確認：
- `git push` **不存在**於 Deny；
- `git switch -c` **不存在**於 Deny。

記錄：
- `git credential` 與 `git reset` 已 direct restart-tested；
- 其餘 10 項為 same-mechanism persistence inference，下次重啟順便核對即可。

### 4.3 Advanced File Access
移除／確認不存在下列項目（File Access deletion 為 restart-persistent observed）：
- 舊專案 `.env.local` unconditional write
- 桌面整體（`%USERPROFILE%\Desktop`）unconditional read
- 廢棄 `.gemini\antigravity\skills` read

個人資料夾一律使用泛稱，不寫入實體資料夾名稱。

### 4.4 MCP Permanent Allow
確認 GitHub write / mutation 工具不得出現在 permanent Allow。
保留之 GitHub read-class permanent Allow entries：
- `get_commit`
- `get_me`
- `list_branches`
- `list_pull_requests`
- `list_workflow_runs`
- `pull_request_read`

其餘既有 non-GitHub MCP entries 不因本文件隨意增刪。

### 4.5 Manage MCP Servers → GitHub
進入 Manage MCP Servers → GitHub，核對 tool 狀態：
- **Target**：**24 / 42 enabled**（18 disabled exact set）。

**Exact 18 Disabled Set**：
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

> [!CAUTION]
> 若 IDE 更新後 total tool count != 42，不得強套 24/42，必須 STOP production 並重新審查。

### 4.6 Advanced Web Access
- **Execute URLs**：
  - `localhost`：設為 `Allow`
  - `github.com`：設為 `Deny`
  - **明確警告（Explicit Warning）**：`github.com` 必須保留 entry 並設為 `Deny`，**絕對不得 delete github.com entry**（刪除 entry 重啟會恢復為 Allow）。
- **Read URLs**：
  - `github.com`：`Allow`
  - `raw.githubusercontent.com`：`Allow`
  - `sinotrade.github.io`：`Allow`

### 4.7 舊版設定棄用聲明
- 舊「Deny List Terminal Commands」：**DEPRECATED / NON-PERSISTENT / DO NOT USE**。

---

## 5. Git Authentication & Credential Boundary

### 5.1 使用者本機驗證
當使用者本人需要重新登入或核對身分時：
- 重新登入：`git credential-manager github login`（使用者在自身 terminal 經 browser 登入）
- 核對帳號：`git credential-manager github list`

### 5.2 Executor 機密邊界
Executor 永遠嚴格遵守：
- **永遠不得執行**：`git credential fill` 或任何等價 secret extraction 指令；
- **嚴禁讀取**：PAT、OAuth token、Authorization header 或任何環境機密變數；
- **嚴禁**：為取得 remote evidence 或完成目標而嘗試讀取本機機密儲存。

---

## 6. Environment Baseline Completion Checklist

完成上述設定後，逐項確認以下 14 點：

- [ ] 1. Verified IDE version（2.5.5 或更新紀錄版本）
- [ ] 2. Terminal Command Auto Execution 設為 `Always Proceed`
- [ ] 3. Advanced Command Access → Terminal Commands 包含上述 **12 Deny entries**
- [ ] 4. `git push` **不存在**於 Deny
- [ ] 5. `git switch -c` **不存在**於 Deny
- [ ] 6. Advanced File Access 已移除舊 repo `.env.local` write、Desktop broad read、obsolete skills read
- [ ] 7. MCP permanent Allow 已移除 GitHub write 工具與 `evaluate_script`
- [ ] 8. GitHub MCP Server 共有 18 個 write 工具 disabled
- [ ] 9. GitHub MCP Server 狀態為 **24 / 42 enabled**
- [ ] 10. Advanced Web Access Execute URLs 包含 `localhost` = Allow
- [ ] 11. Advanced Web Access Execute URLs 包含 `github.com` = Deny（保留 entry 設 Deny）
- [ ] 12. Read URLs 包含 `github.com`、`raw.githubusercontent.com`、`sinotrade.github.io`
- [ ] 13. 舊 Deny List Terminal Commands 未被使用（已棄用）
- [ ] 14. Executor 未執行任何 `git credential fill` 或機密讀取指令

---

## 7. Restart Verification Protocol

在 recovery、reinstall 或 version-update 完成上述 Checklist 後：

1. **完整關閉 IDE，重新啟動一次（Restart Verification）**。
2. **再次核對持久層設定**：
   - Advanced Command Access 12 Deny 仍在；
   - `github.com` Execute URL Deny 仍在；
   - Advanced File Access 減量保持；
   - MCP permanent Allow 減量保持；
   - GitHub MCP 18 disabled（24 / 42）保持。
3. **異常處置**：若上述任何一項重啟後遺失或漂移，**立即 STOP production**，交由 External Macro Auditor 重新評估。
4. **日常免責**：普通 production batch **不需要每批重啟 IDE**，信任實測之持久性。

---

## 8. IDE Version Update Protocol

當 Antigravity IDE 版本更新時：

1. 除了完成上述完整 Checklist 外，必須重新驗證：
   - explicit Deny entry persistence（尤其是 Terminal Commands）；
   - Execute URL `github.com` Deny persistence；
2. **Matcher semantics 警告**：新版本的 matcher semantics（exact match、prefix、argument handling 等）在未重新實測前視為 **UNKNOWN**。
3. **不得推論**：不得自動假設 2.5.5 的實測結論直接適用於新版。

---

## 9. Persistence Discovery History

記錄本專案探索 Antigravity IDE 2.5.5 設定持久性之歷史證據：

1. **舊 Deny List Terminal Commands**：實測重啟後直接變為 empty，確認為 non-persistent。
2. **Execute URLs github.com 刪除**：實測 delete entry 後重啟，`github.com` 會自動以 `Allow` 重現；改為 explicit Deny entry 後重啟，`Deny` 狀態成功保存。
3. **Advanced Command Access explicit Deny**：
   - `git credential` 與 `git reset`：實測重啟後 `Deny` 狀態成功保存（directly restart-tested）；
   - 其他 10 項：基於相同儲存機制推論（same-mechanism inference），非逐一測試。
4. **底層儲存探索記錄**：
   先前以 sentinel 字串 `git switch --discard-changes` 搜尋 `%USERPROFILE%\.gemini`、`%APPDATA%\Antigravity IDE`、`%LOCALAPPDATA%` 等路徑（排除 brain、conversations、cache），以 UTF-8 與 UTF-16 搜尋皆為 **zero plaintext match**。
   **結論**：Searched locations 中未發現 plaintext persistence，底層實際儲存機制（internal/compressed/cloud sync）為 **UNKNOWN**。因此本 recovery checklist 為唯一的可靠手動恢復與驗證基準。
