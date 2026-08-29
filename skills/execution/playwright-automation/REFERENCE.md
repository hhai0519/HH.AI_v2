> 本技能為 vendored 外部資產：來源為 https://github.com/lackeyjb/playwright-skill
> v4.1.0，授權 MIT（完整條款見同目錄 LICENSE）。上游原始 API 說明保留在同目錄
> 的 API_REFERENCE.md。
> 與上游的已知差異：未複製上游的 .gitignore，因其 *.png 與 screenshots/ 規則
> 會使本目錄下的圖檔靜默無法進版控。
> 修改前請先閱讀 docs/adr/0018-vendored-external-assets.md。

## 📋 核心測試腳本模板

### 基本頁面測試

```javascript
const { test, expect, chromium } = require('@playwright/test');

test.describe('Skills Dashboard', () => {
  let browser, page;
  
  test.beforeAll(async () => {
    browser = await chromium.launch({ headless: true });
  });
  
  test.afterAll(async () => {
    await browser.close();
  });
  
  test.beforeEach(async () => {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 }
    });
    page = await context.newPage();
    
    // 捕獲所有控制臺錯誤
    page.on('console', msg => {
      if (msg.type() === 'error') {
        console.error(`[BROWSER ERROR] ${msg.text()}`);
      }
    });
    
    // 捕獲頁面崩潰
    page.on('pageerror', err => {
      console.error(`[JS CRASH] ${err.message}`);
    });
  });
  
  test('首頁正常載入', async () => {
    await page.goto('http://localhost:3000');
    await expect(page).toHaveTitle(/Skills Dashboard/);
    
    // 確認關鍵元素存在
    await expect(page.locator('header')).toBeVisible();
    await expect(page.locator('.skill-card').first()).toBeVisible();
  });
  
  test('技能卡片可以點擊開啟 Modal', async () => {
    await page.goto('http://localhost:3000');
    
    // 等待卡片載入
    await page.waitForSelector('.skill-card', { timeout: 5000 });
    
    // 點擊第一張卡片
    await page.locator('.skill-card').first().click();
    
    // 確認 Modal 出現
    await expect(page.locator('.modal')).toBeVisible();
    await expect(page.locator('.modal-content')).toBeVisible();
    
    // 截圖存證
    await page.screenshot({ path: 'test-modal.png', fullPage: false });
  });
  
  test('搜尋功能正常', async () => {
    await page.goto('http://localhost:3000');
    
    const searchInput = page.locator('#search-input');
    await searchInput.fill('技術分析');
    
    // 等待過濾結果
    await page.waitForTimeout(500);
    
    const visibleCards = await page.locator('.skill-card:visible').count();
    expect(visibleCards).toBeGreaterThan(0);
  });
});
```

### 響應式設計測試

```javascript
const VIEWPORTS = [
  { name: 'Mobile', width: 375, height: 812 },
  { name: 'Tablet', width: 768, height: 1024 },
  { name: 'Desktop', width: 1440, height: 900 },
  { name: '4K', width: 2560, height: 1440 }
];

test('響應式佈局驗證', async ({ browser }) => {
  for (const viewport of VIEWPORTS) {
    const context = await browser.newContext({ viewport });
    const page = await context.newPage();
    
    await page.goto('http://localhost:3000');
    
    // 截圖
    await page.screenshot({ 
      path: `screenshots/${viewport.name.toLowerCase()}.png`,
      fullPage: true 
    });
    
    // 確認沒有水平滾動條（響應式問題的常見指標）
    const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
    expect(bodyWidth).toBeLessThanOrEqual(viewport.width + 5);
    
    console.log(`✅ ${viewport.name} (${viewport.width}x${viewport.height}) 通過`);
    await context.close();
  }
});
```

### 表單自動填寫

```javascript
async function fill_and_submit_form(page, formData) {
  for (const [selector, value] of Object.entries(formData)) {
    const element = page.locator(selector);
    const tagName = await element.evaluate(el => el.tagName.toLowerCase());
    
    if (tagName === 'select') {
      await element.selectOption(value);
    } else if (tagName === 'input' && await element.getAttribute('type') === 'checkbox') {
      if (value) await element.check(); else await element.uncheck();
    } else {
      await element.fill(value);
    }
  }
  
  await page.keyboard.press('Enter');
  await page.waitForNavigation({ waitUntil: 'networkidle' });
}

// 使用範例
await fill_and_submit_form(page, {
  '#username': 'testuser@example.com',
  '#password': '<SECRET_PASSWORD>',
  '#remember-me': true
});
```

### 連結檢查器

```javascript
async function check_all_links(page, base_url) {
  await page.goto(base_url);
  
  const links = await page.$$eval('a[href]', els => 
    els.map(el => el.href).filter(href => href.startsWith('http'))
  );
  
  console.log(`檢查 ${links.length} 個連結...`);
  const broken = [];
  
  for (const url of [...new Set(links)]) {
    try {
      const response = await page.request.get(url, { timeout: 10000 });
      if (!response.ok()) {
        broken.push({ url, status: response.status() });
        console.log(`❌ ${response.status()} - ${url}`);
      }
    } catch (e) {
      broken.push({ url, error: e.message });
      console.log(`❌ ERROR - ${url}: ${e.message}`);
    }
  }
  
  console.log(`\n完成！${links.length - broken.length}/${links.length} 連結正常`);
  return broken;
}
```

---

## 📊 測試報告配置

```javascript
// playwright.config.js
module.exports = {
  testDir: './tests',
  timeout: 30000,
  retries: 2,
  reporter: [
    ['html', { outputFolder: 'playwright-report' }],
    ['json', { outputFile: 'test-results.json' }]
  ],
  use: {
    headless: true,
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    trace: 'on-first-retry'
  }
};
```

---

