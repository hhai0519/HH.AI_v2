---
name: json-to-flex-renderer
description: 純程式化 (Template-based) 將 JSON 分析報告轉換為 LINE Flex Message 結構的渲染引擎。
---

# JSON to LINE Flex Message 渲染引擎

## 1. 核心定位 (Mission)
你是 `platform/` 層負責 LINE 視覺化渲染的終端模組。
負責接收來自總管（`orchestration/agency-orchestrator`）的純 JSON 分析報告，並嚴格遵循 BLUF（Bottom Line Up Front，結論先行）原則，將數據純程式化轉換為 LINE 官方標準的 Flex Message JSON 結構。

## 2. 轉換規則 (Transformation Rules)
1. **Header (標題區)**: 根據報告類型顯示標題與視覺狀態燈號。
2. **Hero/Body (內容區)**: 
   - 提取 JSON 中的 `summary` 放在置頂位置。
   - 使用 Separator 分隔，下方逐一條列 `details` 內的各領域分析摘要。
3. **Footer (操作區)**: 將 JSON 中的 `conclusions` 轉化為按鈕或可行動 (Actionable) 提示。

## 3. 系統通訊層宣告 (System Comms Layer)
網路狀態： 本技能為本地端腳本，無需網路權限。
接收協定： 透過 STDIN 接收標準的 `{"summary": "...", "details": {...}, "conclusions": [...]}` JSON 結構。
傳送協定： 向 STDOUT 輸出陣列形式的 LINE Message JSON (包含 `[ { type: 'flex', ... } ]`)。

## 協同邊界

本技能負責將**結構化 JSON 分析報告**轉換為 LINE Flex Message。
另有一支 `markdown_to_flex.js` 負責將 **Markdown 文字**轉換為
Flex Message，兩者輸入來源不同、職責互補，非重複實作。

（註：`markdown_to_flex.js` 位於舊專案的
`skills/03_Execution/line-bot-zero-delay/line-bot-project/`，
屬 runtime 層程式碼，尚未遷移至 HH.AI_v2。）
