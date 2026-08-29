from playwright.sync_api import sync_playwright

# Example: Discovering buttons and other elements on a page

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    # Navigate to page and wait for it to fully load
    page.goto('http://localhost:5173')
    page.wait_for_load_state('networkidle')

    # NOTE: Discovering elements via page.evaluate() eliminates N+1 IPC roundtrips.
    # This is the officially recommended Playwright best practice and significantly
    # improves performance when querying many elements.
    #
    # SEMANTIC DIFFERENCE WARNING:
    # This snippet uses the browser's native checkVisibility() with `checkOpacity: false`.
    # Therefore, elements with `opacity: 0` are evaluated as "visible".
    # This differs from Playwright's locator.is_visible() which treats opacity:0 as hidden.
    # If you require the exact semantics of Playwright's is_visible(), you must use
    # locator.is_visible() directly, at the cost of reverting to N+1 IPC roundtrips.
    button_texts = page.evaluate('''() => {
        return Array.from(document.querySelectorAll('button')).map(b => {
            const isVisible = typeof b.checkVisibility === 'function'
                ? b.checkVisibility({ checkOpacity: false, checkVisibilityCSS: true })
                : !!(b.offsetWidth || b.offsetHeight || b.getClientRects().length);
            return isVisible ? (b.innerText || b.textContent) : "[hidden]";
        });
    }''')
    print(f"Found {len(button_texts)} buttons:")
    for i, text in enumerate(button_texts):
        print(f"  [{i}] {text}")

    # Discover links
    links_data = page.evaluate('''() => {
        return Array.from(document.querySelectorAll('a[href]')).map(a => ({
            text: (a.innerText || a.textContent).trim(),
            href: a.getAttribute('href')
        }));
    }''')
    print(f"\nFound {len(links_data)} links:")
    for link in links_data[:5]:  # Show first 5
        print(f"  - {link['text']} -> {link['href']}")

    # Discover input fields
    inputs = page.locator('input, textarea, select').all()
    print(f"\nFound {len(inputs)} input fields:")
    for input_elem in inputs:
        name = input_elem.get_attribute('name') or input_elem.get_attribute('id') or "[unnamed]"
        input_type = input_elem.get_attribute('type') or 'text'
        print(f"  - {name} ({input_type})")

    # Take screenshot for visual reference
    page.screenshot(path='/tmp/page_discovery.png', full_page=True)
    print("\nScreenshot saved to /tmp/page_discovery.png")

    browser.close()