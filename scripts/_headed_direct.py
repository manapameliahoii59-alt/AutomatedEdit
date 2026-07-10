from app.core.playwright_worker import playwright_worker
from app.data.services.series_list_client import SeriesListClient

TARGET = "爱意迟暮不相逢"


def test():
    with SeriesListClient(headless=False) as client:
        r = client.search_by_name(TARGET)
        inner = r.get("data") or {}
        rows = inner.get("data") or []
        print("headed direct:", inner.get("total"), len(rows))
        if rows:
            print(rows[0].get("series_name"))


if __name__ == "__main__":
    playwright_worker.run(test)
