---
name: tool-executor
description: 萬用工具執行器。作為大腦層 (System 2) 與外部環境之間的唯一橋樑。將自然語言意圖轉換為嚴謹的 JSON-RPC 工具呼叫，並提供完整的 Audit Log 追蹤。
---

# Tool Executor (Deterministic Bridge)

## 功能概述

> **與 MCP 工程師的上下游關係**：`mcp-engineer`（路徑：`skills/execution/mcp-engineer`）負責開發階段（撰寫 MCP 伺服器程式碼與環境配置），本技能 (`tool-executor`) 負責執行階段（規範 Agent 如何安全呼叫工具）。

本技能取代了高達 18 個硬體編碼的自動化腳本 (包含網頁爬蟲、PDF解析、資料處理等)。它本身不包含任何業務邏輯，而是負責「正確地」將 Agent 的需求傳遞給 MCP Gateway，並將結果結構化返回。

## 實作邏輯 (Implementation Logic)
1. **Schema 驗證**: 在將需求發送給 Gateway 前，根據 MCP Server 提供的 Schema 進行嚴格的型別與參數驗證，確保 JSON-RPC Request 格式完全正確。
2. **RARV 循環對接**: 當 Loki Swarm 進入 RARV 迴圈的 "Act" (行動) 階段時，強制調用此技能，防止 Agent 直接寫 code 去執行高風險操作。
3. **Traceability (可追溯性)**: 強制將每一次的工具呼叫 (Request Payload)、執行結果 (Result) 以及錯誤狀態 (Error) 記錄到系統層級的 Audit Log 中，確保系統具備 Enterprise-grade 的可審計性。
