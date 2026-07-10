from app.core.playwright_worker import playwright_worker
from app.data.services.series_list_client import SeriesListClient

TARGET = "爱意迟暮不相逢"


def test():
    with SeriesListClient(headless=True) as client:
        r = client.fetch_list(
            {
                "query": TARGET,
                "search_type": "2",
                "page_index": "0",
                "page_size": "10",
            }
        )
        inner = r.get("data") or {}
        rows = inner.get("data") or []
        print("without content_genre:", inner.get("total"), len(rows))
        if rows:
            print(rows[0].get("series_name"), rows[0].get("book_id"))


if __name__ == "__main__":
    playwright_worker.run(test)
