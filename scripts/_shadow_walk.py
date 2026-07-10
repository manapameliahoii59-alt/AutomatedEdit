from app.core.playwright_worker import playwright_worker
from app.data.services.series_list_client import SeriesListClient


def walk():
    with SeriesListClient(headless=False) as client:
        page = client.page
        assert page
        page.wait_for_timeout(6000)
        found = page.evaluate(
            """() => {
                const out = [];
                function walk(root) {
                    const nodes = root.querySelectorAll ? root.querySelectorAll('input,textarea,[contenteditable=true]') : [];
                    for (const el of nodes) {
                        const ph = el.placeholder || el.getAttribute('placeholder') || '';
                        const aria = el.getAttribute('aria-label') || '';
                        const rect = el.getBoundingClientRect();
                        out.push({ph, aria, cls: (el.className||'').slice(0,100), w: rect.width, h: rect.height});
                    }
                    const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
                    for (const el of all) {
                        if (el.shadowRoot) walk(el.shadowRoot);
                    }
                }
                walk(document);
                return out;
            }"""
        )
        for item in found:
            print(item)


if __name__ == "__main__":
    playwright_worker.run(walk)
