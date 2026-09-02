# ADR-0014: PM2 設定檔的三個地雷，與沙盒先行驗證流程

- Status: Accepted
- Date: 2026-08-25

## Context

2026-08-09 執行「雙平台全連線根除與升級」時，依照 v24.5 計畫書執行到
步驟 7，PM2 啟動發生嚴重崩潰。緊急停止後進行沙盒診斷，確認計畫書本身
存在兩處致命瑕疵：

**地雷一：路徑錯置（Path Mismatch）**
計畫書指示 `tg-bridge-zero-delay` 與 `line-daemon` 的啟動路徑為
`.agents/skills/...`，但實體目錄的正確位置是 `skills/03_Execution/...`，
導致 PM2 報錯 `MODULE_NOT_FOUND`。

**地雷二：Windows PM2 的 npm 相容性問題**
計畫書指示 `line-bridge` 用 `script: 'npm', args: 'run dev'` 啟動。
兩個問題：
1. Windows 上的 PM2 若不指定 `.cmd`，會錯誤地把 npm 當成 JavaScript
   腳本解析，引發 `SyntaxError`
2. 更根本的是，經過比對專案原始設定檔後發現，真正的啟動腳本根本不是
   `npm`，而是 `bridge.js`——計畫書這段內容是幻覺，不是筆誤

這是同一種模式的重複出現：文件描述的內容與實際程式碼不符
（另見 mcp-gateway 宣稱取代 connect-apps、$$額度$$ 宣稱 Bridge 直接
攔截、GitLab-First Policy 等案例）。

## Decision

### 1. 修復方式與驗證結果

建立 `sandbox_ecosystem.config.js` 在沙盒環境修正並模擬啟動，確認可行
後才覆寫實體 `ecosystem.config.js`。修正後的正確設定：

- `line-bridge` → `skills/03_Execution/line-bot-zero-delay/line-bot-project/bridge.js`
- `tg-bridge-zero-delay` → `skills/03_Execution/telegram-bot-cdp-bridge/telegram-bot-project/dist/bin/cli-zero-delay.js`
- `line-daemon` → `skills/03_Execution/line-bot-zero-delay/line-bot-project/start_line.js`

修復後執行壓力測試驗證（雙向每秒 1000 次併發、持續 20 秒，
注入 `x-sop14-mock: true` 阻斷外部 API 以免消耗真實額度）：

| 指標 | LINE Bridge | TG Bridge |
|---|---|---|
| 總請求數 | 18,000 | 18,000 |
| HTTP 200 | 18,000 | 18,000 |
| 失敗/逾時 | 0 | 0 |
| 平均吞吐 | ~900 req/s | ~900 req/s |
| PM2 重啟次數 | 0 | 0 |
| 記憶體變化 | 74.7MB → 123.9MB | 171.3MB → 135.9MB（GC 正常回收） |

36,000 筆請求零錯誤、零重啟，排除 memory leak 可能性。

### 2. `line-daemon` 的 Stopped 狀態是設計預期，不是故障

沙盒測試中 `line-daemon` 顯示 Stopped，原因是它啟動時 `bridge.js` 尚未
完全綁定連接埠，daemon 會主動退出等待下次重試。**這是它的設計行為，
不是 bug。**

遷移或排障時，如果看到 `line-daemon` 處於 Stopped 狀態，先確認
`bridge.js` 是否已就緒，不要誤判為進程崩潰而做不必要的修復。

### 3. 待辦：`line-daemon` 缺少 autorestart 設定

沙盒報告建議「在實際部署中加上 PM2 原生的重啟機制即可完美運作」，
但查證目前的 `ecosystem.config.js`，`line-daemon` 這個進程**並沒有
設定 `autorestart`**，該建議未被執行。

遷移 runtime 層時應評估是否補上此設定，否則 `line-daemon` 在
`bridge.js` 尚未就緒時退出後，不會自動重試。

### 4. 沙盒先行驗證流程（Sandbox-First Validation）

本節規範已移至 `SOP/SOP_14_Rigorous_Verification_and_Audit_Protocol.md` §2.1。

## Consequences

- 遷移 runtime 層時，`ecosystem.config.js` 的路徑必須逐一實際驗證，
  不能依賴任何計畫書或文件的描述——本次事件證明文件可能包含幻覺內容。
- `sandbox_ecosystem.config.js` 目前仍留在舊專案根目錄，遷移時可作為
  沙盒驗證的範本保留，或在確認流程已文件化後淘汰。
- 壓力測試用的 `x-sop14-mock: true` 標頭機制是有價值的設計（測試時
  阻斷外部 API 呼叫），遷移 runtime 時應確認 `bridge.js` 與
  `cli-zero-delay.js` 裡的這段邏輯有被保留。
- 本 ADR 與 ADR-0009（Windows Job Object 進程回收）、ADR-0010
  （PowerShell 參數傳遞陷阱）同屬雙平台連線的實戰教訓，遷移 runtime
  時應三份一起參照。

## 2026-09-01 分層搬移

依 `PRINCIPLES.md` §1，原 §4 的沙盒先行驗證五步驟屬可執行規範，
已移至 `SOP/SOP_14_Rigorous_Verification_and_Audit_Protocol.md` §2.1。
Context、§1 至 §3 與 Consequences 原文未變動。
