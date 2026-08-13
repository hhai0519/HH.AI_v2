---
name: webapp-testing
description: "使用 Playwright 互動和測試本地 Web 應用程式的工具包。支援驗證前端功能、偵錯 UI 行為、擷取瀏覽器螢幕截圖以及查看瀏覽器日誌。"
type: execution
---


# Web 應用快速測試 (WebApp Testing)

### 【摘要】觸發條件與 DLP 聲明
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議

本技能透過 **Playwright** 對本地 Web 應用進行即時互動測試：一鍵截圖存證、捕獲 JS 錯誤、驗證元素狀態、模擬使用者操作，提供比完整 E2E 框架更快速的即時調試循環。

> **與 `playwright-automation` 的區別**：本技能用於**快速即時調試**，無需建立測試套件；`playwright-automation` 用於建立**完整自動化測試框架**。

---

## 🎯 觸發條件

- 提到「截圖」「測試這個頁面」「UI 有沒有問題」
- 需要快速驗證頁面渲染是否正確
- 需要捕獲 JavaScript 錯誤或控制臺日誌
- 需要驗證某個功能按鈕是否可點擊
- 需要測試 localhost 本地服務

---

## 🛠️ 輕量 MCP 直接測試模式 (新支援)

當只需快速驗證頁面渲染、檢查控制台錯誤，或進行簡單互動時，優先使用 `chrome-devtools-mcp` 提供之原生工具，避免編寫與執行實體腳本：

1. **載入網頁分頁**：
   - 呼叫 `new_page(url="http://localhost:3000", timeout=15000)` 建立並載入頁面。**請注意：`url` 為必要參數。**
2. **截圖驗證外觀**：
   - 呼叫 `take_screenshot` 取得渲染結果。
3. **檢查控制台錯誤**：
   - 呼叫 `list_console_messages` 檢查有無 JS 報錯。
4. **點擊與輸入互動 (關鍵規範)**：
   > [!IMPORTANT]
   > `chrome-devtools-mcp` 的 `click` 與 `fill` 工具**不接受** CSS 選擇器 (Selector)，僅接受 a11y 樹的 `uid`。請依以下兩種方式進行互動：
   > - **方式一 (原生 MCP)**：先呼叫 `take_snapshot` 取得頁面節點的 `uid`，再將 `uid` 帶入 `click(uid="...")` 或 `fill(uid="...", value="...")`。
   > - **方式二 (JS 注入)**：呼叫 `evaluate_script` 注入執行，例如：`function: "() => document.querySelector('#search-input').click()"`。
5. **釋放資源**：
   - 任務結束時，務必呼叫 `close_page` 關閉分頁以防止記憶體溢出。

---

## 🛠️ 快速啟動（單文件模式 - 複雜斷言與自訂邏輯）

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

---


> [!NOTE]
> 詳細參數與 API 清單、進階範例請見 [REFERENCE.md](./REFERENCE.md)
