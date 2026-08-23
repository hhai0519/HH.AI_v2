---
name: xlsx
description: 提供 Excel (XLSX) 檔案讀寫、多 Sheet 整合與格式化報表生成。當使用者要求「讀取 Excel」、「產生格式化 Excel 報表」、「跨 Sheet 整合資料」、「套用條件格式」或「Excel 格式轉換」時使用。
---

# Excel 全能處理器 (XLSX Toolkit)

本技能提供 Excel / CSV / Google Sheets 格式的**完整讀寫與處理能力**，覆蓋資料讀取、多 Sheet 操作、公式計算、條件格式、圖表生成及格式轉換，使用 openpyxl + pandas 的黃金組合。

## 🎯 觸發條件

- 使用者上傳 `.xlsx` / `.xls` / `.csv` 要讀取或分析
- 需要生成格式化的 Excel 報表
- 需要在多個 Sheet 間整合資料
- 需要套用條件格式（高亮異常值）
- 需要從 Excel 到 CSV/PDF 的格式轉換

## 🛠️ 依賴安裝

```bash
pip install openpyxl pandas xlrd xlsxwriter
```

## ⚡ 快速使用範例

```python
# 讀取並查看 Excel 結構
info = get_excel_info("report.xlsx")
data = read_excel("report.xlsx", sheet_name="月報")

# 生成格式化報表
create_formatted_report(df, "formatted_report.xlsx", title="季度報告")

# 轉換格式
excel_to_csv("data.xlsx", output_dir="./csv_output")
csv_to_excel(["sales.csv", "inventory.csv"], "combined.xlsx")
```

## 🤝 協同技能

- `csv-data-summarizer`：讀出的資料快速統計視覺化
- `pdf`：Excel 報表轉 PDF 輸出
- `d3js-visualization`：Excel 原始資料的互動圖表

> [!NOTE]
> 詳細程式碼範例（讀取、格式化報表、條件格式、圖表、格式轉換）請見 [REFERENCE.md](./REFERENCE.md)
