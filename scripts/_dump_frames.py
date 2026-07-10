from app.core.playwright_worker import playwright_worker
from app.data.services.series_list_client import SeriesListClient


def dump():
    with SeriesListClient(headless=False) as client:
        page = client.page
        assert page
        page.wait_for_timeout(5000)
        print("frames:", len(page.frames))
        for i, f in enumerate(page.frames):
            print(i, f.url[:120])
        text = page.evaluate(
            """() => {
                const body = document.body.innerText || '';
                return body.includes('剧名') || body.includes('搜索') || body.includes('短剧');
            }"""
        )
        print("body has search keywords:", text)
        hits = page.evaluate(
            """() => {
                const out = [];
                for (const el of document.querySelectorAll('*')) {
                    const t = (el.innerText || '').trim();
                    if (t === '剧名' || t === '搜索' || (t.length < 8 && /剧名|搜索/.test(t))) {
                        out.push({tag: el.tagName, class: (el.className||'').slice(0,80), text: t});
                    }
                }
                return out.slice(0, 20);
            }"""
        )
        print("label hits:", hits)


if __name__ == "__main__":
    playwright_worker.run(dump)
