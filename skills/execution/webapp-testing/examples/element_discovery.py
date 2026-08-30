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
    # SEMANTIC DIFFERENCE WARNING (1/2) — button visibility:
    # This snippet uses the browser's native checkVisibility() with `checkOpacity: false`.
    # Therefore, elements with `opacity: 0` are evaluated as "visible".
    # This differs from Playwright's locator.is_visible() which treats opacity:0 as hidden.
    # If you require the exact semantics of Playwright's is_visible(), you must use
    # locator.is_visible() directly, at the cost of reverting to N+1 IPC roundtrips.
    #
    # SEMANTIC DIFFERENCE WARNING (2/2) — link text extraction:
    # Link text is now read as `(a.innerText || a.textContent).trim()` inside the browser.
    # Two behavioural differences from the previous `link.inner_text().strip()`:
    #   1. innerText is CSS-aware and returns "" for hidden elements; the `|| textContent`
    #      fallback then yields the raw text. The previous code returned "" in that case.
    #      In short: hidden links now show their text instead of appearing blank.
    #   2. JavaScript's String.prototype.trim() and Python's str.strip() agree on ASCII
    #      whitespace but differ on some Unicode whitespace characters.
    # Both are acceptable for this discovery example, but do not copy this pattern into
    # code that relies on visibility semantics.
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
    links_data = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('a[href]')).map(a => ({
            text: (a.innerText || a.textContent).trim(),
            href: a.getAttribute('href')
        }));
    }""")
    print(f"\nFound {len(links_data)} links:")
    for link in links_data[:5]:  # Show first 5
        print(f"  - {link['text']} -> {link['href']}")

    # Discover input fields
    inputs_data = page.evaluate('''() => {
        return Array.from(document.querySelectorAll('input, textarea, select')).map(el => {
            const name = el.getAttribute('name') || el.getAttribute('id') || "[unnamed]";
            const type = el.getAttribute('type') || 'text';
            return { name, type };
        });
    }''')
    print(f"\nFound {len(inputs_data)} input fields:")
    for data in inputs_data:
        print(f"  - {data['name']} ({data['type']})")

    # Take screenshot for visual reference
    page.screenshot(path='/tmp/page_discovery.png', full_page=True)
    print("\nScreenshot saved to /tmp/page_discovery.png")

    browser.close()