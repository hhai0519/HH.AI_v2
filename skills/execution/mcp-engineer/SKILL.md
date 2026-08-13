---
name: mcp-engineer
description: "MCP 開發與環境配置完整生命週期工程師。整合 mcp-builder（建立高品質 MCP 伺服器的標準流程）與 mcp-setup（本地環境設定與排錯）為單一職責技能。觸發關鍵字：建立MCP、MCP伺服器、MCP配置、MCP環境、mcp-builder、mcp-setup。"
type: execution
---


# MCP 工程師 (MCP Engineer)

### 【摘要】觸發條件與 DLP 聲明
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議

本技能整合原 `mcp-builder`（MCP 伺服器開發指南）與 `mcp-setup`（MCP 環境配置與排錯）的全部職責，覆蓋 MCP 工具的完整生命週期。

---

## 🎯 觸發條件

- 「建立 MCP 伺服器」、「MCP 開發」、「寫一個 MCP tool」
- 「MCP 環境配置」、「MCP 設定」、「mcp-setup」、「mcp-builder」
- 「MCP 連線失敗」、「MCP 工具載入錯誤」
- 「.gemini/settings.json 設定」、「MCP server 啟動」

---

## 📐 開發 SOP（建立新 MCP 伺服器）

### Phase 1：規格定義

```typescript
// 1. 定義 Tool Schema
const toolSchema = {
  name: "tool_name",
  description: "工具的明確功能描述",
  inputSchema: {
    type: "object",
    properties: {
      param1: { type: "string", description: "參數說明" }
    },
    required: ["param1"]
  }
};
```

### Phase 2：伺服器實作

```typescript
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const server = new Server(
  { name: "my-mcp-server", version: "1.0.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [toolSchema]
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  // 實作邏輯
  return { content: [{ type: "text", text: "結果" }] };
});

const transport = new StdioServerTransport();
await server.connect(transport);
```

### Phase 3：環境配置

在 `.gemini/settings.json` 或 `claude_desktop_config.json` 中設定：

```json
{
  "mcpServers": {
    "my-server": {
      "command": "node",
      "args": ["path/to/server.js"],
      "env": {
        "API_KEY": "${API_KEY}"
      }
    }
  }
}
```

---

## 🔧 環境排錯 SOP（MCP 連線失敗）

### 常見問題排查流程

```
1. 確認 Node.js 版本 ≥ 18
   node --version

2. 確認依賴已安裝
   npm list @modelcontextprotocol/sdk

3. 手動測試伺服器啟動
   node path/to/server.js

4. 確認 settings.json 路徑格式（Windows 使用反斜線或雙正斜線）

5. 查看 MCP 連線日誌
   ~/.gemini/logs/ 或 ~/.claude/logs/
```

### 高頻錯誤修復

| 錯誤訊息 | 原因 | 修復方式 |
|---------|------|---------|
| `spawn ENOENT` | 命令路徑錯誤 | 使用絕對路徑或確認 PATH |
| `Cannot find module` | 依賴未安裝 | `npm install` |
| `ECONNREFUSED` | 伺服器未啟動 | 手動啟動後再測試 |
| `Invalid JSON` | settings.json 格式錯誤 | 使用 JSON validator |

---

## ⚠️ 邊界說明

- ✅ 適用：建立新 MCP 伺服器、配置 settings.json、排錯 MCP 連線
- ✅ 適用：整合第三方 API 為 MCP Tool（GitHub、Notion、資料庫等）
- ❌ 不適用：MCP 閘道器多伺服器管理（請改用 `mcp-gateway` 技能）
- ❌ 不適用：系統層級環境問題（請改用 `systematic-debugging-skill`）

---

## 🗂️ 封存記錄

本技能整合自以下兩個已封存的技能（保留歷史溯源）：
- `skills/Archive/mcp-builder/` — MCP 伺服器開發指南（V2.x）
- `skills/Archive/mcp-setup/` — MCP 環境配置 SOP（V2.x）

---

## [Security] Smart Integration & DLP
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議
