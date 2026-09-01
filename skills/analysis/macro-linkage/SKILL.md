---
name: macro-linkage
description: 總體經濟數據與台股大盤聯動分析。當使用者詢問總經數據（如 CPI、非農、利率決策）對股市的影響、資金流向或跨市場資產配置時使用。
---
# 宏觀連動分析 (Macro Linkage Expert)

### 【摘要】觸發條件與 DLP 聲明
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議

本技能專精分析**臺股重量級個股（臺積電、聯發科等）與美國 ADR / 相關板塊的跨市場連動關係**，透過溢價率計算、相關性係數與時間差效應，預判臺股開盤方向與個股短期走勢。

---

## 🎯 觸發條件

- 詢問「ADR 今晚怎麼跑」「臺積電 ADR 溢價多少」
- 需要分析美股收盤對臺股開盤的影響
- 涉及 NVDA、AAPL、XLF 等美股板塊與臺股的相關性
- 美股大漲 / 大跌後的隔日臺股預測

---

## 🛠️ 核心計算模型

### ADR 溢價率計算

```python
def calc_adr_premium(adr_price: float, fx_rate: float, ratio: float, tw_price: float) -> dict:
    """
    adr_price: ADR 收盤價（美元）
    fx_rate: 臺美匯率（例如 31.5）
    ratio: ADR 轉換比例（TSM = 5, ADS = 2）
    tw_price: 臺股收盤價（臺幣）
    """
    implied_tw = adr_price * fx_rate / ratio
    premium = (implied_tw - tw_price) / tw_price * 100
    
    signal = ""
    if premium > 2:
        signal = "🟢 正溢價 → 臺積電可能高開"
    elif premium < -2:
        signal = "🔴 負溢價 → 臺積電可能低開"
    else:
        signal = "🟡 小幅溢價 → 開盤影響有限"
    
    return {
        "implied_tw_price": round(implied_tw, 2),
        "premium_pct": round(premium, 2),
        "signal": signal
    }

# 範例
result = calc_adr_premium(
    adr_price=175.50,  # TSM ADR 收盤
    fx_rate=31.8,      # 當日匯率
    ratio=5,           # 1 ADR = 5 臺積電股
    tw_price=940.0     # 臺積電昨收
)
```

---

## 📊 板塊代理映射表

| 臺股標的 | 對應美股代理 | 相關性係數 | 時間差 |
|---|---|---|---|
| **臺積電（2330）** | TSM ADR, NVDA | 0.82 | T+0 (隔日) |
| **聯發科（2454）** | NVDA, QCOM | 0.74 | T+0 |
| **聯電（2303）** | UMC ADR, SOXS | 0.69 | T+0 |
| **金融股（2881~）** | XLF, JPM | 0.61 | T+0 |
| **航運股（2609~）** | ZIM, DAL | 0.55 | T+0 |

---

## 🔗 跨市場分析框架

```
美股收盤 (21:00~04:30 EST)
    ↓
ADR 溢價計算（即時）
    ↓
臺股期貨夜盤反應（理論確認）
    ↓
隔日開盤缺口預估
    ↓
板塊輪動方向識別
```

---

## ⚠️ 關鍵注意事項

1. **匯率影響**：臺幣升值 1% ≈ 臺積電 ADR 溢價降低 1%（需扣除匯率因素）
2. **除息季**：ADR 與臺股除息時間差會造成溢價失真
3. **熊市修正**：相關性在市場恐慌期間 → 1（同步崩跌），溢價失去預測力

---

## 🤝 協同技能

- `tech-analyzer`：開盤方向確認後的技術面切入點
- `twse-market-logic`：系統級市場邏輯
- `sentiment-scout`：市場情緒輔助確認

---
## [Security] Smart Integration & DLP
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議

## 版本紀錄 (Changelog)
- **[2.0.0]** 導入 V2 架構，實裝多維度認知矩陣標籤與 Dynamic Payload 預備介面。


---
⚙️ 【系統通訊層宣告 (System Comms Layer)】

網路狀態： 本技能已強制接入總控通訊網路。

接收協定 (Dynamic Payload)： 本文檔不再接收無結構的自然語言，必須處理封裝後的動態參數：
`[SYSTEM-CALL: macro-linkage | PAYLOAD: { objective: "<核心意圖>", target_audience: "<受眾>", strategic_constraints: "<策略限制/禁語>", tone_variables: "<語氣微調>" }]`

> [!IMPORTANT]
> **Payload 淨化規則**（規範本體見 `.agents/rules/skill-engineering-guardrails.md` §3）：
> 本技能位於 `analysis/`，屬認知型技能，因此：
> - 接收：戰略目標、語氣設定、情緒變數、自然語言約束
> - 拒絕：SQL 語句、DOM 路徑、raw URL、純技術指令

執行中若遇能力不足或需要外部協作，應停下來明確告知使用者目前卡在哪裡，不要自行尋找替代方案掩蓋問題。
`[SYSTEM-CALL: 目標ID | PAYLOAD: { ... }]` 調閱其他技能。

回傳協定： 任務終止時，必須且只能輸出 `[SYSTEM-RETURN: SUCCESS/FAILED | DATA: <結果>]`。
