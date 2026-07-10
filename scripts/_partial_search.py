from app.core.playwright_worker import playwright_worker
from app.data.services.series_list_client import SeriesListClient

TARGET = "爱意迟暮不相逢"


def test():
    with SeriesListClient(headless=True) as client:
        for kw in [TARGET, "爱意迟暮不相", "迟暮不相逢", "爱意迟暮", "爱意"]:
            r = client.search_by_name(kw, {"page_size": "50"})
            rows = (r.get("data") or {}).get("data") or []
            hit = [x for x in rows if TARGET in (x.get("series_name") or "")]
            print(f"kw={kw!r} total={(r.get('data') or {}).get('total')} count={len(rows)} hit={len(hit)}")
            for x in hit[:3]:
                print(" ", x.get("series_name"), x.get("book_id"))


if __name__ == "__main__":
    playwright_worker.run(test)
