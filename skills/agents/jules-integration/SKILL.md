---
name: jules-integration
description: 將耗時長、Token 消耗大的重構或修復任務委派給雲端 Google Jules 代理人執行，並保持與本地 git 分支同步。當使用者提到「委派給 Jules」、「雲端重構」、「交給 Jules 處理」，或本地任務預估修改檔案數超過 5 個、預期耗時超過 10 分鐘時使用。
disable-model-invocation: true
type: "action"
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

Jules 每日只有 **5 次**額度，每一次委派都會消耗這個稀缺資源、在雲端建立真實 session、
產生真實的 git branch。這符合 `skills/agents/AGENTS.md` 定義的「有實際副作用」標準，
不適合讓模型自主判斷「這個任務看起來適合委派」就自己觸發——必須由使用者明確要求。

## 使用時機

- 使用者明確要求「委派給 Jules」或類似措辭
- 使用者確認某個任務範圍大（修改檔案數 > 5、預估耗時 > 10 分鐘），且主動要求委派

## 流程

### 1. 額度檢查（強制，不可跳過）

在呼叫委派功能前，**必須**先確認今天剩餘額度：

- 剩餘 2 次以上：可以正常詢問使用者是否要繼續
- **剩餘 1 次**：明確警告使用者「Jules 額度僅剩 1 次，請審慎確認這個任務真的需要委派」，
  取得使用者明確回覆「確認繼續」才能往下走
- **剩餘 0 次**：**直接拒絕**，告知使用者今日額度已用盡，任務轉回本地執行，或提示明天再試。
  不要嘗試任何繞過方式。

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
