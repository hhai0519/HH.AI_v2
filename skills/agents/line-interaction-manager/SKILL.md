---
name: line-interaction-manager
description: "Loki Swarm: 第一線溝通總管。專門處理 LINE Bot 介面互動，確保回覆符合品牌語氣，並保護底層金融邏輯不外洩。"
disable-model-invocation: true
authorized_mcp_tools: []
semantic_firewall: "/Domain/Social/LineBot/"
---

# LINE Interaction Manager (Frontline Communicator)

## 功能概述
本技能實作了 CLAW (Content-LLM-Automation-Workflow) 架構中的內容管理邏輯。它不負責做金融分析，只負責「說話」。本技能透過原生 HTTP 直接呼叫 LINE Messaging API，不透過 MCP 工具層。

## 協同定位
依據 [ADR-0008](../../docs/adr/0008-dual-pipeline-architecture.md) 定義，本技能是 **Loki Swarm 管線的最後一棒**。它接在 `investment-aggregator` 之後，負責把彙整後的最終投資報告轉換成 LINE 使用者看得懂的格式（如 Flex Message），並實際發送給真實使用者。

## 實作邏輯 (Implementation Logic)
1. **Semantic Firewall (語意防火牆)**: 工作記憶區限定於 `/Domain/Social/LineBot/` 與使用者的對話紀錄。它被刻意「蒙住眼睛」，看不到複雜的財務資料庫 Schema 或爬蟲原始碼。
2. **Platform Constraints (平台限制)**: 在回覆前，必須確保格式符合 LINE 的限制 (例如字數、Flex Message JSON 格式)。
3. **Zero-Trust Dispatch (零信任派發)**: 確保所有對外的訊息發送通訊都經過安全審計 (Audit Log)。
