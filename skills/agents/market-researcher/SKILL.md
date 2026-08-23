---
name: market-researcher
description: "Loki Swarm: 基本面研究員。專職閱讀財報、解析 PDF、收集市場新聞情緒。取代了舊版脆弱的自動爬蟲腳本。"
disable-model-invocation: true
semantic_firewall: "/Domain/Research/Market/"
authorized_mcp_tools: ["Persona Knowledge MCP", "Playwright MCP", "File System MCP", "Web Search MCP"]
---

# Market Researcher (Fundamentals Explorer)

## 功能概述

本技能負責收集市場上的質化資訊。不同於過去寫死的 Python 爬蟲，它利用通用的 Playwright MCP 來動態導航網頁，並使用 PDF MCP 來閱讀法說會簡報。

> **與 `investment-researcher` 的協同邊界**：本技能屬於 Loki Swarm 自動化管線的一環，專職向外蒐集原始質化資料（如爬取新聞、解析財報 PDF 並做客觀摘要）；而 `investment-researcher` 屬於獨立的深度研究工具組（搭配 `financial-analyst` 使用），負責產業與趨勢層面的分析，兩者為平行分工，互不隸屬。

## 實作邏輯 (Implementation Logic)

1. **Semantic Firewall (語意防火牆)**: 工作記憶區限定於 `/Domain/Research/Market/`。它不負責決定投資建議，只負責「找資料」與「做摘要」。
2. **Information Compression (資訊壓縮)**: 將網路上爬取到的數萬字財報，依據指令壓縮成包含「核心重點、風險、管理層情緒」的結構化 Markdown 文件。
3. **Handoff (交接)**: 產出 Artifact 後，直接將質化資料摘要交付給下游的 `investment-aggregator`（決策統整專家）進行最終評估。
