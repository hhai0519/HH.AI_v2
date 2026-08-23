# xlsx Reference

## 📋 核心操作程式庫

### 讀取 Excel

```python
import pandas as pd
import openpyxl

def read_excel(file_path: str, sheet_name: str = None) -> dict:
    """智能讀取 Excel（自動偵測 Sheet）"""

    # 讀取所有 Sheet 名稱
    xl = pd.ExcelFile(file_path)
    sheet_names = xl.sheet_names
    print(f"📂 共 {len(sheet_names)} 個 Sheet：{sheet_names}")

    if sheet_name:
        df = pd.read_excel(file_path, sheet_name=sheet_name)
        return {sheet_name: df}
    else:
        # 讀取全部 Sheet
        return {name: pd.read_excel(file_path, sheet_name=name)
                for name in sheet_names}

def get_excel_info(file_path: str) -> dict:
    """取得 Excel 基本資訊"""
    wb = openpyxl.load_workbook(file_path, read_only=True)
    info = {}
    for name in wb.sheetnames:
        ws = wb[name]
        info[name] = {
            "rows": ws.max_row,
            "cols": ws.max_column,
            "size": f"{ws.max_row} × {ws.max_column}"
        }
    return info
```

### 建立格式化 Excel 報表

```python
def create_formatted_report(data: dict, output_path: str, title: str = "報告"):
    """建立帶有完整格式的 Excel 報表"""
    from openpyxl import Workbook
    from openpyxl.styles import (Font, PatternFill, Alignment,
                                   Border, Side, numbers)
    from openpyxl.utils import get_column_letter

    wb = Workbook()

    # ── 主資料 Sheet ──
    ws = wb.active
    ws.title = "資料"

    # 標題行樣式
    header_font = Font(name='微軟正黑體', bold=True, color='FFFFFF', size=12)
    header_fill = PatternFill(start_color='2563EB', end_color='2563EB', fill_type='solid')
    header_align = Alignment(horizontal='center', vertical='center')
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )

    # 寫入標題
    headers = list(data.keys()) if isinstance(data, dict) else data.columns.tolist()
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border
        ws.row_dimensions[1].height = 30

    # 寫入資料
    rows = list(zip(*data.values())) if isinstance(data, dict) else data.values.tolist()
    for row_idx, row in enumerate(rows, 2):
        for col_idx, value in enumerate(row, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.border = thin_border
            cell.alignment = Alignment(horizontal='left', vertical='center')

            # 交替行顏色
            if row_idx % 2 == 0:
                cell.fill = PatternFill(start_color='EFF6FF', end_color='EFF6FF', fill_type='solid')

    # 自動調整欄寬
    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(max_len + 4, 50)

    # 凍結標題行
    ws.freeze_panes = 'A2'

    wb.save(output_path)
    print(f"✅ 已生成：{output_path}")
    return output_path
```

### 條件格式（異常值高亮）

```python
def apply_conditional_formatting(ws, col_letter: str, start_row: int, end_row: int,
                                   threshold_high: float = None, threshold_low: float = None):
    """套用條件格式：超界值自動高亮"""
    from openpyxl.formatting.rule import ColorScaleRule, CellIsRule
    from openpyxl.styles import PatternFill

    red_fill = PatternFill(start_color='FFCCCC', end_color='FFCCCC', fill_type='solid')
    green_fill = PatternFill(start_color='CCFFCC', end_color='CCFFCC', fill_type='solid')

    cell_range = f"{col_letter}{start_row}:{col_letter}{end_row}"

    if threshold_high:
        ws.conditional_formatting.add(cell_range,
            CellIsRule(operator='greaterThan', formula=[str(threshold_high)], fill=red_fill))

    if threshold_low:
        ws.conditional_formatting.add(cell_range,
            CellIsRule(operator='lessThan', formula=[str(threshold_low)], fill=red_fill))

def add_chart(ws, chart_type: str = 'bar', data_range: str = 'A1:B10',
              title: str = '', position: str = 'D2'):
    """在 Excel 中插入圖表"""
    from openpyxl.chart import BarChart, LineChart, PieChart, Reference

    chart_map = {'bar': BarChart, 'line': LineChart, 'pie': PieChart}
    ChartClass = chart_map.get(chart_type, BarChart)
    chart = ChartClass()
    chart.title = title
    chart.style = 10
    chart.height = 15
    chart.width = 25

    ws.add_chart(chart, position)
```

### 格式轉換

```python
def excel_to_csv(excel_path: str, output_dir: str = '.') -> list:
    """每個 Sheet 轉為獨立的 CSV"""
    import os
    base = os.path.splitext(os.path.basename(excel_path))[0]
    outputs = []

    xl = pd.ExcelFile(excel_path)
    for sheet in xl.sheet_names:
        df = pd.read_excel(excel_path, sheet_name=sheet)
        csv_path = os.path.join(output_dir, f"{base}_{sheet}.csv")
        df.to_csv(csv_path, index=False, encoding='utf-8-sig')  # utf-8-sig 確保中文 Excel 能正確開啟
        outputs.append(csv_path)
        print(f"✅ {sheet} → {csv_path}")

    return outputs

def csv_to_excel(csv_paths: list, output_path: str) -> str:
    """多個 CSV 合併為多 Sheet Excel"""
    import os
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        for csv_path in csv_paths:
            df = pd.read_csv(csv_path, encoding='utf-8-sig')
            sheet_name = os.path.splitext(os.path.basename(csv_path))[0][:31]  # Sheet 名稱上限 31 字元
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    return output_path
```
