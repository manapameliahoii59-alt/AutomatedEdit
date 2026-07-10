import json
from urllib.parse import parse_qs, urlparse

from app.core.playwright_worker import playwright_worker
from app.data.services.series_list_client import SeriesListClient

KEYWORD = "爱意迟暮不相逢"


def test():
    captured = []

    def on_resp(resp):
        if "series/list" not in resp.url:
            return
        try:
            body = resp.json()
        except Exception:
            body = None
        captured.append({"url": resp.url, "body": body})

    with SeriesListClient(headless=False) as client:
        page = client.page
        assert page
        page.on("response", on_resp)
        page.wait_for_timeout(3000)

        # 尝试 JS 触发
        triggered = page.evaluate(
            """(keyword) => {
                const candidates = [...document.querySelectorAll('input,textarea')];
                for (const el of candidates) {
                    const ph = (el.placeholder || '') + (el.getAttribute('aria-label') || '');
                    if (/剧|搜|名称|短剧/.test(ph) || el.closest('[class*=search]')) {
                        el.focus();
                        el.value = keyword;
                        el.dispatchEvent(new InputEvent('input', { bubbles: true, data: keyword }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
                        return ph || el.className;
                    }
                }
                return null;
            }""",
            KEYWORD,
        )
        print("js trigger:", triggered)
        page.wait_for_timeout(6000)

        print("captured", len(captured))
        for i, c in enumerate(captured, 1):
            params = parse_qs(urlparse(c["url"]).query)
            flat = {k: v[0] if len(v) == 1 else v for k, v in params.items()}
            inner = (c["body"] or {}).get("data") or {}
            rows = inner.get("data") or []
            print(f"#{i} query={flat.get('query')} total={inner.get('total')} count={len(rows)}")
            print("   URL:", c["url"][:300])
            if rows:
                print("   first:", rows[0].get("series_name"))

        input("按 Enter 关闭浏览器…")


if __name__ == "__main__":
    playwright_worker.run(test)
