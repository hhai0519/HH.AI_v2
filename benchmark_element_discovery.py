import time
from playwright.sync_api import sync_playwright
import tempfile
import os

html_content = """
<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
    """ + "".join([f'<a href="#link{i}">Link {i}</a>\n' for i in range(100)]) + """
    """ + "".join([f'<input name="input{i}" type="text">\n' for i in range(100)]) + """
</body>
</html>
"""

def benchmark_old():
    with tempfile.NamedTemporaryFile(delete=False, suffix='.html') as f:
        f.write(html_content.encode('utf-8'))
        filepath = f.name

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f"file://{filepath}")

        start_time = time.time()

        # Discover links
        links = page.locator('a[href]').all()
        for link in links:
            text = link.inner_text().strip()
            href = link.get_attribute('href')

        link_time = time.time() - start_time

        # Discover inputs
        start_time = time.time()
        inputs = page.locator('input, textarea, select').all()
        for input_elem in inputs:
            name = input_elem.get_attribute('name') or input_elem.get_attribute('id') or "[unnamed]"
            input_type = input_elem.get_attribute('type') or 'text'

        input_time = time.time() - start_time

        browser.close()
    os.remove(filepath)
    return link_time, input_time


def benchmark_new():
    with tempfile.NamedTemporaryFile(delete=False, suffix='.html') as f:
        f.write(html_content.encode('utf-8'))
        filepath = f.name

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f"file://{filepath}")

        start_time = time.time()

        links_data = page.evaluate('''() => {
            return Array.from(document.querySelectorAll('a[href]')).map(a => ({
                text: (a.innerText || a.textContent).trim(),
                href: a.getAttribute('href')
            }));
        }''')

        link_time = time.time() - start_time

        start_time = time.time()
        inputs_data = page.evaluate('''() => {
            return Array.from(document.querySelectorAll('input, textarea, select')).map(el => ({
                name: el.getAttribute('name') || el.getAttribute('id') || "[unnamed]",
                type: el.getAttribute('type') || 'text'
            }));
        }''')

        input_time = time.time() - start_time

        browser.close()
    os.remove(filepath)
    return link_time, input_time

if __name__ == "__main__":
    old_link, old_input = benchmark_old()
    new_link, new_input = benchmark_new()

    print(f"Old Link Time: {old_link:.4f}s")
    print(f"New Link Time: {new_link:.4f}s")
    print(f"Improvement: {old_link/new_link:.2f}x")

    print(f"Old Input Time: {old_input:.4f}s")
    print(f"New Input Time: {new_input:.4f}s")
    print(f"Improvement: {old_input/new_input:.2f}x")
