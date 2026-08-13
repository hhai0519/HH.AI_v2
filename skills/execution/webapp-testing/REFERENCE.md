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

## 📊 響應式多裝置快速截圖

```python
async def multi_device_screenshot(url: str):
    """一次生成多裝置截圖"""
    devices = [
        ("mobile", 375, 812),
        ("tablet", 768, 1024),
        ("desktop", 1440, 900),
    ]
    
    for name, w, h in devices:
        tester = QuickWebTester()
        await tester.start(url, viewport={"width": w, "height": h})
        await tester.screenshot(f"check_{name}.png")
        await tester.close()
        print(f"✅ {name} ({w}×{h}) 截圖完成")
```

---

## 🤝 協同技能

- `playwright-automation`：完整 E2E 測試框架建立
- `systematic-debugging-skill`：深層問題排障
- `webapp-testing-skill`：臺股網站的進階測試流程

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
> - 若本技能為 `Cognitive` 型：接收戰略目標、語氣設定、情緒變數；拒絕 SQL/DOM/技術指令。
> - 若本技能為 `Execution` 型：只接收 URL、DOM Selector、SQL、JSON Schema；拒絕認知參數。

發送協定 (Zero-Block Policy)： 執行中若遇能力不足或需外部協作，嚴禁中斷或詢問使用者。必須主動封裝 Dynamic Payload 並發出：
`[SYSTEM-CALL: 目標ID | PAYLOAD: { ... }]` 調閱其他技能。

回傳協定： 任務終止時，必須且只能輸出 `[SYSTEM-RETURN: SUCCESS/FAILED | DATA: <結果>]`。
