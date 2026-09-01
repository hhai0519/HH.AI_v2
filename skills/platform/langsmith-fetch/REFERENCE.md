# langsmith-fetch Reference

## 🔍 常見問題診斷

| 症狀 | 診斷步驟 | 可能原因 |
|---|---|---|
| Agent 無限迴圈 | 查看 Run Tree，找循環路徑 | Max iterations 設定錯誤 |
| Tool Call 全失敗 | 檢查 tool 子 Run 的 error | API Key 失效/限流 |
| 回應太慢 | 查 duration_sec，定位最慢步驟 | 某個 Tool 阻塞 |
| 輸出不完整 | 查 completion_tokens 是否達上限 | max_tokens 太小 |
| 記憶體讀取失敗 | 查 memory 相關 tool 的 error | Vector Store 異常 |

---

## ⚡ CLI 快速使用

```bash
# 查看最近 20 個 runs
langsmith-fetch list --project my-agent --limit 20

# 分析特定 run
langsmith-fetch trace --run-id <RUN_ID>

# 只看錯誤
langsmith-fetch list --project my-agent --errors-only

# 輸出 JSON 供進一步分析
langsmith-fetch trace --run-id <RUN_ID> --format json > trace.json
```

---

## 🤝 協同技能

- `systematic-debugging`：更廣泛的環境除錯流程

---

## 版本紀錄 (Changelog)
- **[2.0.0]** 2026-05-04：V2.0.0 Polymorphic Labeling Migration — 依生命週期 SOP 導入多態功能性技術標籤 (tool_category, execution_env, io_format)，建立執行層 Manifest 路由能力。

## [Security] Smart Integration & DLP
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議


---
⚙️ 【系統通訊層宣告 (System Comms Layer)】

網路狀態： 本技能已強制接入總控通訊網路。

接收協定 (Dynamic Payload)： 本文檔不再接收無結構的自然語言，必須處理封裝後的動態參數：
`[SYSTEM-CALL: langsmith-fetch | PAYLOAD: { objective: "<核心意圖>", target_audience: "<受眾>", strategic_constraints: "<策略限制/禁語>", tone_variables: "<語氣微調>" }]`

> [!IMPORTANT]
> **Payload 淨化規則**（規範本體見 `.agents/rules/skill-engineering-guardrails.md` §3）：
> 本技能位於 `platform/`，屬技術型技能，因此：
> - 接收：URL、API Endpoint、SQL Query、JSON Schema、檔案絕對路徑
> - 拒絕：認知參數、語氣描述、角色設定、情緒變數

執行中若遇能力不足或需要外部協作，應停下來明確告知使用者目前卡在哪裡，不要自行尋找替代方案掩蓋問題。
`[SYSTEM-CALL: 目標ID | PAYLOAD: { ... }]` 調閱其他技能。

回傳協定： 任務終止時，必須且只能輸出 `[SYSTEM-RETURN: SUCCESS/FAILED | DATA: <結果>]`。
