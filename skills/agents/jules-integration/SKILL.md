---
name: jules-integration
description: 將耗時長、Token 消耗大的重構或修復任務委派給雲端 Google Jules 代理人執行，並保持與本地 git 分支同步。當使用者提到「委派給 Jules」、「雲端重構」、「交給 Jules 處理」，或本地任務預估修改檔案數超過 5 個、預期耗時超過 10 分鐘時使用。
disable-model-invocation: true
authorized_mcp_tools: ["antigravity-jules-bridge.sendToJules"]
semantic_firewall: true
---

# Jules 雲端委派

透過 Antigravity 擴充套件 **Antigravity Jules Bridge**（`antigravity-jules-bridge.antigravity-jules-bridge`，來源：
[Germain-L/Send2Jules](https://github.com/Germain-L/Send2Jules)），將工作交接給雲端 Jules 代理人執行。

**前置條件**：這個擴充套件必須已經透過 Antigravity 的 Extensions 面板安裝，並執行過
`Jules: Set API Key` 完成金鑰設定（金鑰存放在 OS 層級的 SecretStorage，不會落地成明文檔案）。
這個技能**不包含**任何自行 vendor 原始碼或編譯部署的步驟——所有橋接邏輯由官方擴充套件負責，
本技能只定義「什麼時候該用、用之前要檢查什麼」。

## 為什麼這是 user-invoked（`disable-model-invocation: true`）

Jules 每日額度為 **100 次** session（Google AI Pro/Ultra 訂閱者），
每一次委派都會在雲端建立真實 session、產生真實的 git branch，
並可能開啟 PR。這符合 `skills/agents/AGENTS.md` 定義的「有實際副作用」標準，
屬於有真實副作用的操作，應由使用者明確要求才執行。

## 使用時機

- 使用者明確要求「委派給 Jules」或類似措辭
- 使用者確認某個任務範圍大（修改檔案數 > 5、預估耗時 > 10 分鐘），且主動要求委派

## 流程

### 1. 額度確認

Jules 每日額度為 100 次 session，日常使用通常不會用盡。
委派前建議確認剩餘額度，但不需要像稀缺資源那樣逐次警告：

- **剩餘 20 次以上**：正常委派，不需特別提醒
- **剩餘 5-20 次**：委派時順帶告知使用者目前剩餘數量
- **剩餘 5 次以下**：明確提醒使用者額度即將用盡，確認任務優先度後再委派
- **剩餘 0 次**：告知使用者今日額度已用盡，任務轉回本地執行或提示明日再試

參見 [REFERENCE.md](./REFERENCE.md) 了解額度查詢的具體做法。

### 2. Git 狀態確認

確認目前是 git repository 且已連結遠端。擴充套件會自動處理未提交變更（WIP commit + 
push 到暫存分支），但如果偵測到目前分支狀態複雜（例如已經在一個 rebase/merge 進行中），
先停下來提醒使用者手動處理，不要讓委派流程疊加在一個未完成的 git 操作上。

### 3. 委派

透過擴充套件的「Send to Jules」指令送出任務，附上清楚的任務描述。**不要**把 `.env`、
金鑰、連線字串等敏感內容包進要傳送的 context 裡——委派前快速檢查一次要傳送的檔案清單。

### 4. 追蹤與驗證

記錄 Jules 建立的 session 與分支名稱，告知使用者可以在 Jules Dashboard 追蹤進度。
**Jules 完成後產生的分支，合併回主分支前一律跑一次 `execution/webapp-testing`（或對應的測試技能）
驗證，不要無條件信任雲端產出的程式碼。**

### 5. 合併衝突處理

如果拉回 Jules 分支後出現 merge conflict，**停下來，交給使用者判斷**，不要自己猜測該保留哪一邊
覆蓋掉另一邊——尤其這個專案涉及金融計算邏輯，錯誤合併的代價高。

## 進一步細節

參見 [REFERENCE.md](./REFERENCE.md) 了解額度查詢的實作方式、context 打包內容、
以及跟 `skills/agents/AGENTS.md` 授權白名單機制的對應關係。
