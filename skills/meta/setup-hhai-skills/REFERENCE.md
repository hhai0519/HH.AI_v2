# Setup HH.AI Skills - 技術細節參考

## 1. 臺股網站標準目錄結構

```text
<需動態確認當前工作目錄>/
├── index.html              # 首頁（大盤概況）
├── stock.html              # 個股 K 線圖頁面
├── css/
│   ├── main.css            # 全域樣式 & 深色主題
│   └── components.css      # 元件樣式
├── js/
│   ├── candlestick.js      # K 線圖
│   ├── api.js              # TWSE API 呼叫層
│   └── utils.js            # 共用工具
├── data/                   # 假資料（開發階段使用）
└── tests/
    ├── verify_task.py      # 通用驗證腳本
    └── screenshots/        # 驗證截圖存放
```

## 2. TWSE 公開 API 參考

```javascript
// 常用臺股開放資料 API（無需 Key）
const TWSE_API = {
  // 個股日 K（近 30 天）
  dailyK: (stock, yyyymm) =>
    `https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=${yyyymm}01&stockNo=${stock}`,

  // 大盤加權指數
  taiex: (yyyymm) =>
    `https://www.twse.com.tw/exchangeReport/FMTQIK?response=json&date=${yyyymm}01`,

  // 類股即時行情
  sector: () =>
    `https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&type=MS`,
};

// 資料清洗（TWSE 回傳格式統一處理）
function parseTWSEDailyK(rawData) {
  if (!rawData.data || rawData.stat !== 'OK') return [];
  return rawData.data.map(row => ({
    date: row[0].replace(/\//g, '-').replace(/^(\d+)/, m => (parseInt(m) + 1911).toString()), // 民國轉西元
    volume: parseInt(row[1].replace(/,/g, ''), 10),
    open:   parseFloat(row[3].replace(/,/g, '')),
    high:   parseFloat(row[4].replace(/,/g, '')),
    low:    parseFloat(row[5].replace(/,/g, '')),
    close:  parseFloat(row[6].replace(/,/g, '')),
    change: parseFloat(row[7].replace(/[+,]/g, '')),
  })).filter(d => !isNaN(d.close));
}
```

## 3. 驗證腳本範例 (`verify_task.py`)

```python
# verify_task.py — 每次完成功能後執行
from playwright.sync_api import sync_playwright
import os

def verify_feature(url, task_name):
    errors = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        
        # 偵測主控臺錯誤
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"PAGE ERROR: {e}"))
        
        page.goto(url)
        page.wait_for_load_state('networkidle')
        
        # 確保 screenshots 目錄存在
        os.makedirs('screenshots', exist_ok=True)
        screenshot_path = f'screenshots/verify_{task_name}.png'
        page.screenshot(path=screenshot_path, full_page=True)
        
        svg_count = page.locator('svg').count()
        browser.close()
    
    print(f"✅ Task: {task_name} | 📸 {screenshot_path} | 📊 SVG: {svg_count}")
    if errors:
        print(f"❌ 主控臺錯誤 ({len(errors)} 個)：")
        for e in errors: print(f"   - {e}")
    else:
        print(f"✅ 無主控臺錯誤")
    
    return len(errors) == 0

# 用法（根據實際情況調整）
# verify_feature('http://localhost:3000', 'k-line-chart')
# verify_feature('file:///<需動態確認當前工作目錄>/index.html', 'homepage')
```
