---
name: mcp-gateway
description: "Zero-Trust 萬用執行閘道器。負責啟動並連接所有的 MCP (Model Context Protocol) 伺服器，管理安全白名單 (mcp_config.json)，並訂閱外部資料的即時更新 (Server-Sent Events 推播)。"
disable-model-invocation: true
---

# MCP Gateway (Broker & Mediator)

> [!NOTE]
> **架構設計草案 (Vision/Concept)**
> 本技能目前為未實作的架構設計草案，尚未包含實體的 Gateway 伺服器運作程式碼。實際的跨系統自動化 API 串接，請直接使用 `connect-apps` 等具體技能，請勿嘗試呼叫本技能取代現有連線腳本。

## 功能概述
它作為系統中所有外部互動的單一出入口願景，確保 Agent 只能使用被明確授權的工具。

## 實作邏輯 (Implementation Logic)
1. **Zero-Trust 初始化**: 啟動時強制讀取 `mcp_config.json`。任何未在白名單中的 MCP 伺服器或指令皆被阻斷。
2. **連線生命週期管理**: 透過 JSON-RPC 2.0 建立 Client-Host-Server 架構，負責 Capability Negotiation (能力交涉) 與憑證管理 (OAuth)。
3. **即時事件訂閱 (Pub/Sub)**: 支援 Streamable HTTP 與 Server-Sent Events (SSE)。當外部資源 (如資料庫或檔案系統) 發生變化時，主動推播通知給需要的 Agent，取代低效的 polling 迴圈。
