from app.core.playwright_worker import playwright_worker
from app.data.services.series_list_client import SeriesListClient


def test():
    with SeriesListClient(headless=True) as c:
        print("app:", c.app_info)
        for kw in ["爱意迟暮不相逢", "爱意迟暮", "爱意"]:
            r = c.search_by_name(kw)
            inner = r.get("data") or {}
            data = inner.get("data") or []
            print(
                f"{kw!r}: code={r.get('code')} total={inner.get('total')} count={len(data)}"
            )
            if data:
                print(" ", data[0].get("series_name"), data[0].get("book_id"))


if __name__ == "__main__":
    playwright_worker.run(test)
