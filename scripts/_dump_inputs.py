from app.core.playwright_worker import playwright_worker
from app.data.services.series_list_client import SeriesListClient


def dump():
    with SeriesListClient(headless=False) as client:
        page = client.page
        assert page
        page.wait_for_timeout(8000)
        data = page.evaluate(
            """() => {
                const out = [];
                for (const el of document.querySelectorAll('input,textarea,[contenteditable=true],.arco-input-search,.arco-select')) {
                    const rect = el.getBoundingClientRect();
                    out.push({
                        tag: el.tagName,
                        type: el.type || '',
                        placeholder: el.placeholder || el.getAttribute('placeholder') || '',
                        className: (el.className || '').slice(0, 120),
                        aria: el.getAttribute('aria-label') || '',
                        text: (el.innerText || '').slice(0, 40),
                        w: rect.width,
                        h: rect.height,
                    });
                }
                return out;
            }"""
        )
        print("inputs:", len(data))
        for item in data:
            print(item)


if __name__ == "__main__":
    playwright_worker.run(dump)
