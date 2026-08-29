# webapp-testing Reference

## ⚡ 快速使用範例

```python
import asyncio

async def quick_test():
    tester = QuickWebTester(headless=True)
    
    # 載入技能儀錶板
    await tester.start("file:///<YOUR_PROJECT_PATH>/skills_dashboard.html")
    
    # 截圖存證
    await tester.screenshot("dashboard_check.png", full_page=True)
    
    # 檢查關鍵元素
    await tester.check_element(".skill-card")
    await tester.check_element("#search-input")
    await tester.check_element("header")
    
    # 點擊第一個技能卡片
    await tester.click_and_observe(".skill-card")
    
    # 確認 Modal 是否出現
    await tester.check_element(".modal")
    
    # 控制臺健康報告
    report = await tester.get_console_report()
    
    # 結論
    if report["errors"] == 0 and report["js_crashes"] == 0:
        print("\n✅ 頁面健康：零錯誤")
    else:
        print(f"\n⚠️ 需要修復：{report['errors']} 個 JS 錯誤")
    
    await tester.close()

asyncio.run(quick_test())
```

---

## 📊 響應式多裝置截圖

響應式多裝置截圖統一由 `playwright-automation` 提供（含水平捲軸斷言與 4K 檔位），
本技能不重複實作，需要時請改呼叫該技能。

## 🤝 協同技能

- `playwright-automation`：完整 E2E 測試框架建立
- `systematic-debugging`：深層問題排障

---

## 版本紀錄 (Changelog)
- **[2.0.0]** 2026-05-04：V2.0.0 Polymorphic Labeling Migration — 依生命週期 SOP 導入多態功能性技術標籤 (tool_category, execution_env, io_format)，建立執行層 Manifest 路由能力。

## [Security] Smart Integration & DLP
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議


---
⚙️ 【系統通訊層宣告 (System Comms Layer)】

網路狀態： 本技能已強制接入總控通訊網路。

接收協定 (Dynamic Payload)： 本文檔不再接收無結構的自然語言，必須處理封裝後的動態參數：
`[SYSTEM-CALL: webapp-testing | PAYLOAD: { objective: "<核心意圖>", target_audience: "<受眾>", strategic_constraints: "<策略限制/禁語>", tone_variables: "<語氣微調>" }]`

> [!IMPORTANT]
> **Payload 淨化規則 (§6.3)**：
> - 若本技能屬於 analysis/ 或 orchestration/（無外部副作用）：接收戰略目標、語氣設定、情緒變數；拒絕 SQL/DOM/技術指令。
> - 若本技能屬於 execution/ 或 platform/（工具與整合層）：只接收 URL、DOM Selector、SQL、JSON Schema；拒絕認知參數。

發送協定：執行中若遇能力不足或需要外部協作，應停下來明確告知使用者目前卡在哪裡，不要自行尋找替代方案掩蓋問題。如需調閱其他技能，封裝 Dynamic Payload 並發出：
`[SYSTEM-CALL: 目標ID | PAYLOAD: { ... }]`

回傳協定： 任務終止時，必須且只能輸出 `[SYSTEM-RETURN: SUCCESS/FAILED | DATA: <結果>]`。

---

## 🛠️ QuickWebTester 完整類別（複雜斷言與自訂邏輯）

```python
import asyncio
from playwright.async_api import async_playwright
from datetime import datetime
import os

class QuickWebTester:
    """快速 Web 測試工具（無需測試框架）"""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.browser = None
        self.page = None
        self.console_logs = []
        self.js_errors = []

    async def start(self, url: str, viewport: dict = None):
        """啟動瀏覽器並導航到 URL"""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)

        context = await self.browser.new_context(
            viewport=viewport or {"width": 1440, "height": 900}
        )
        self.page = await context.new_page()

        # 監聽控制臺輸出
        self.page.on("console", lambda msg: self._on_console(msg))
        self.page.on("pageerror", lambda err: self.js_errors.append(str(err)))

        await self.page.goto(url, wait_until="networkidle")
        print(f"✅ 已載入：{url}")
        return self

    def _on_console(self, msg):
        self.console_logs.append({"type": msg.type, "text": msg.text})
        if msg.type == "error":
            print(f"🔴 JS Error: {msg.text}")

    async def screenshot(self, filename: str = None, full_page: bool = True) -> str:
        """截圖並保存"""
        if not filename:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{ts}.png"

        await self.page.screenshot(path=filename, full_page=full_page)
        print(f"📸 截圖已保存：{filename}")
        return filename

    async def check_element(self, selector: str) -> dict:
        """檢查元素狀態"""
        element = self.page.locator(selector)
        count = await element.count()

        if count == 0:
            return {"found": False, "selector": selector}

        is_visible = await element.first.is_visible()
        is_enabled = await element.first.is_enabled()
        text = await element.first.inner_text() if is_visible else ""

        result = {
            "found": True,
            "count": count,
            "visible": is_visible,
            "enabled": is_enabled,
            "text_preview": text[:100]
        }

        status = "✅" if is_visible and is_enabled else "⚠️"
        print(f"{status} [{selector}] count={count}, visible={is_visible}, text='{text[:50]}'")
        return result

    async def click_and_observe(self, selector: str, wait_ms: int = 1000):
        """點擊元素並觀察變化"""
        before_screenshot = await self.screenshot(f"before_click_{selector[:20]}.png")

        await self.page.locator(selector).first.click()
        await self.page.wait_for_timeout(wait_ms)

        after_screenshot = await self.screenshot(f"after_click_{selector[:20]}.png")
        print(f"✅ 點擊完成，截圖對比：{before_screenshot} → {after_screenshot}")

    async def get_console_report(self) -> dict:
        """輸出控制臺報告"""
        errors = [l for l in self.console_logs if l["type"] == "error"]
        warnings = [l for l in self.console_logs if l["type"] == "warning"]

        report = {
            "total_logs": len(self.console_logs),
            "errors": len(errors),
            "warnings": len(warnings),
            "js_crashes": len(self.js_errors),
            "error_messages": [e["text"] for e in errors[:5]],
            "js_crash_messages": self.js_errors[:3]
        }

        print("\n=== 🔍 控制臺健康報告 ===")
        print(f"  總日誌：{report['total_logs']} 條")
        print(f"  錯誤：{report['errors']} 個")
        print(f"  警告：{report['warnings']} 個")
        print(f"  JS 崩潰：{report['js_crashes']} 個")

        if errors:
            print("\n主要錯誤：")
            for e in errors[:3]:
                print(f"  ❌ {e['text'][:120]}")

        return report

    async def close(self):
        if self.browser:
            await self.browser.close()
        await self.playwright.stop()
```
