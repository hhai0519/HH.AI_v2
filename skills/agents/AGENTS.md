<!-- Parent: ../../AGENTS.md -->

# skills/agents

## Purpose

RARV 執行型 agent：會實際呼叫工具、寫檔案、發送訊息、觸發外部動作。
這是整個技能庫裡風險最高的一類，因為錯誤會直接影響真實世界（金融資料、
使用者收到的訊息等）。

## For AI Agents

### 這個資料夾工作時要注意

- 每個技能的 frontmatter **必須**包含 `authorized_mcp_tools` 白名單，列出這個
  技能被允許呼叫的工具，不能省略（見根目錄 AGENTS.md 第 2 節自訂欄位）。
- 這類技能預設應該是 user-invoked（`disable-model-invocation: true`），除非你
  很確定讓模型自主呼叫不會有風險——判斷標準見根目錄 AGENTS.md 第 5 節。
- 新增技能前，先確認同樣的執行邏輯有沒有已經存在的技能可以呼叫，不要重複造輪子
  （尤其是發送 LINE 訊息、寫入資料庫這類共用動作）。

### 常見錯誤

- 把 `authorized_mcp_tools` 留空或寫成萬用字元——這個欄位存在的目的就是限制
  範圍，寫成允許所有工具等於沒有這個機制。
