import time

from app.core.playwright_worker import playwright_worker
from app.data.services.series_list_client import SeriesListClient

TARGET = "爱意迟暮不相逢"


def test():
    with SeriesListClient(headless=True) as client:
        for days in [30, 60, 90, 180, 365]:
            time.sleep(2)
            dr = client._default_series_date_range(days=days)
            r = client.fetch_list(
                {
                    "query": TARGET,
                    "search_type": "2",
                    "page_index": "0",
                    "page_size": "20",
                    **dr,
                }
            )
            inner = r.get("data") or {}
            rows = inner.get("data") or []
            print(
                f"days={days} code={r.get('code')} total={inner.get('total')} "
                f"count={len(rows)} msg={r.get('message')}"
            )
            if rows:
                print(" ", rows[0].get("series_name"))


if __name__ == "__main__":
    playwright_worker.run(test)
