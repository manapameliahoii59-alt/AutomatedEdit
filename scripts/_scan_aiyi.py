import time

from app.core.playwright_worker import playwright_worker
from app.data.services.series_list_client import SeriesListClient

TARGET = "爱意迟暮不相逢"


def test():
    with SeriesListClient(headless=True) as client:
        for page_idx in range(0, 6):
            time.sleep(2)
            r = client.search_by_name("爱意", {"page_index": str(page_idx), "page_size": "20"})
            inner = r.get("data") or {}
            rows = inner.get("data") or []
            print(
                f"page={page_idx} code={r.get('code')} total={inner.get('total')} count={len(rows)}"
            )
            for row in rows:
                name = row.get("series_name") or ""
                if TARGET in name or name in TARGET:
                    print("  HIT", name, row.get("book_id"))


if __name__ == "__main__":
    playwright_worker.run(test)
