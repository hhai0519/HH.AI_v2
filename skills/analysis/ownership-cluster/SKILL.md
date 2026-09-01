---
name: ownership-cluster
description: 機構持股與籌碼集中度指數（CI_INDEX）分析。當使用者詢問法人進出、籌碼集中度、千張大戶動向或主力佈局時使用。
---
# 籌碼叢集追蹤 (Ownership Clustering)

### 【摘要】觸發條件與 DLP 宣告
- ✓ DLP 資料安全驗證已透過 | 資料加密處理 | 隱私保護協議

本技能深度分析**三大法人（外資、投資訊、自營）持股結構**與籌碼集中度指數（CI_INDEX），識別主力佈局、大戶進出及籌碼鎖定狀態，為選股與停利判斷提供機構級依據。

---

## 🎯 觸發條件

- 詢問法人進出、籌碼分析、持股集中度
- 需要分析大戶持股比例（千張大戶動向）
- 需要偵測主力佈局或吸籌行為
- 涉及融資維持率與散戶比例評估

---

## 🛠️ 核心指標體系

### CI_INDEX（籌碼集中度指數）

```
CI_INDEX = (三大法人合計持股% × 0.6) + (千張大戶比% × 0.4)

分級：
  ≥ 70  →  🔴 高度集中（主力鎖倉，跟蹤進場視窗）
  50~69 →  🟡 中度集中（法人佈局中，觀察方向）
  < 50  →  🟢 分散（散戶主導，波動較大）
```

### 三大法人分析框架

| 法人型別 | 行為特徵 | 訊號強度 |
|---|---|---|
| **外資（FINI）** | 趨勢追蹤，量大、方向持續性強 | ⭐⭐⭐⭐⭐ |
| **投資訊** | 主動選股，逆向建倉，季末調整 | ⭐⭐⭐⭐ |
| **自營商** | 避險為主，反向訊號較多 | ⭐⭐ |

---

## 📋 標準分析流程

```python
# 籌碼集中度計算範例
def calc_ci_index(foreign_ratio, trust_ratio, dealer_ratio, major_1000_ratio):
    """
    foreign_ratio: 外資持股%
    trust_ratio: 投資訊持股%
    dealer_ratio: 自營持股%
    major_1000_ratio: 千張大戶持股%
    """
    institutional = foreign_ratio + trust_ratio + dealer_ratio
    ci_index = institutional * 0.6 + major_1000_ratio * 0.4
    
    if ci_index >= 70:
        signal = "🔴 高度集中 - 主力鎖倉"
    elif ci_index >= 50:
        signal = "🟡 中度集中 - 法人佈局"
    else:
        signal = "🟢 分散 - 散戶主導"
    
    return {"ci_index": round(ci_index, 2), "signal": signal}
```

---

## 🔍 大戶衝突偵測模型

> 當出現以下矛盾資訊號時，需深入調查：  
> - 外資買超 + 千張大戶減少 → 法人對倒嫌疑  
> - 融資增加 + 大戶減持 → 散戶接盤，警示出場  
> - 三大法人一致買超 + 股價不漲 → 上方賣壓測試

---

## 📊 融資維持率監控

```
維持率 = 市值 / 融資金額 × 100%

臨界閾值：
  < 120% → 追繳令風險（平倉危機）
  120~140% → 觀察區（波動放大）
  > 140% → 安全區
```

---

## 🤝 協同技能

> 依 SOP §6.1 反死鎖協定：本技能採單向依賴，不直接引用同層的 `chip-logic-expert`。
> 共用的籌碼邏輯框架已向下抽取至 `twse-market-logic` 進行中轉。

- `twse-market-logic`：系統級臺股市場邏輯框架（共用中樞，含 CI_INDEX 邏輯、融資維持率、軋空模型）
- `tech-analyzer`：籌碼面 + 技術面雙重確認

---
## [Security] Smart Integration & DLP
- ✓ DLP 資料安全驗證已透過 | 資料加密處理 | 隱私保護協議

## 版本紀錄 (Changelog)
- **[3.0.0]** 解耦與 `chip-logic-expert` 的迴圈依賴，符合 SOP §6.1 反死鎖協定。版本躍升至 V3.0.0。
- **[2.0.0]** 匯入 V2 架構，實裝多維度認知矩陣標籤與 Dynamic Payload 預備介面。


---
⚙️ 【系統通訊層宣告 (System Comms Layer)】

網路狀態： 本技能已強制接入總控通訊網路。

接收協定 (Dynamic Payload)： 本文件不再接收無結構的自然語言，必須處理封裝後的動態引數：
`[SYSTEM-CALL: ownership-cluster | PAYLOAD: { objective: "<核心意圖>", target_audience: "<受眾>", strategic_constraints: "<策略限制/禁語>", tone_variables: "<語氣微調>" }]`

> [!IMPORTANT]
> **Payload 淨化規則**（規範本體見 `.agents/rules/skill-engineering-guardrails.md` §3）：
> 本技能位於 `analysis/`，屬認知型技能，因此：
> - 接收：戰略目標、語氣設定、情緒變數、自然語言約束
> - 拒絕：SQL 語句、DOM 路徑、raw URL、純技術指令

執行中若遇能力不足或需要外部協作，應停下來明確告知使用者目前卡在哪裡，不要自行尋找替代方案掩蓋問題。
`[SYSTEM-CALL: 目標ID | PAYLOAD: { ... }]` 調閱其他技能。

回傳協定： 任務終止時，必須且只能輸出 `[SYSTEM-RETURN: SUCCESS/FAILED | DATA: <結果>]`。

---
> [!WARNING]
> **全域鐵律：NotebookLM 研究遵從指示**
> 1. 當任務指示「透過 NotebookLM 進行研究/查詢」時，必須嚴格呼叫 `notebooklm` 相關 MCP 工具。
> 2. 若遇到無法連線、憑證過期 (`auth_status: stale` 或 `Authentication expired`) 等錯誤時，**絕對禁止**未經同意自行改用常規網路搜尋 (Web Search) 或其他工具替代。
> 3. 遇到錯誤時，請**立刻中斷動作並主動告知使用者**，請使用者協助登入或修復連線後，再繼續研究任務。
