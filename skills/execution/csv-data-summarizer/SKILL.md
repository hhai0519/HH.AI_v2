---
name: csv-data-summarizer
description: 全自動解析 CSV 或 TSV 資料並產出統計報告與視覺化圖表。當使用者要求「分析 CSV 資料」、「了解資料統計特徵」、「偵測離群值與缺失值」、「生成資料視覺化圖表」或「繪製相關性熱力圖」時使用。
---

# CSV 資料引擎 (CSV Data Summarizer)

本技能利用 **Python + pandas + matplotlib + seaborn** 全自動解析 CSV / TSV 資料，產出完整的描述性統計報告、多種分布圖表、時間序列趨勢與相關性熱力圖，讓資料洞察在 30 秒內呈現。

## 🎯 觸發條件

- 使用者上傳 `.csv` / `.tsv` 資料檔案需要分析
- 需要快速了解資料集的統計特徵（平均、中位數、標準差）
- 需要偵測缺失值、重複行或離群值
- 需要自動生成資料視覺化圖表
- 需要時間序列趨勢或相關性分析

## 🛠️ 依賴安裝

```bash
pip install pandas>=2.0.0 matplotlib>=3.7.0 seaborn>=0.12.0 openpyxl scipy
```

## ⚡ 快速使用

```python
# 一鍵分析
df = auto_analyze_csv("sales_data.csv", output_dir="./sales_analysis")

# 只看基本統計
df = pd.read_csv("data.csv")
print(df.describe())
print(df.isnull().sum())
```

## 📊 輸出文件清單

| 文件 | 內容 |
|---|---|
| `distributions.png` | 每個數值欄位的分布圖 + 箱形圖 |
| `correlation.png` | 欄位相關性熱力圖 |
| `timeseries.png` | 時間序列趨勢（若有日期欄位）|
| 控制臺輸出 | 描述性統計 + 品質報告 + 離群值摘要 |

## 🤝 協同技能

- `xlsx`：分析結果輸出至 Excel 表格
- `d3js-visualization`：進階互動式圖表
- `notebooklm-mcp`：將分析報告匯入知識庫

> [!NOTE]
> 完整分析管線程式碼（全自動一鍵分析、視覺化套件）請見 [REFERENCE.md](./REFERENCE.md)
