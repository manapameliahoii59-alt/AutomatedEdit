from urllib.parse import quote

from app.core.playwright_worker import playwright_worker
from app.data.services.series_list_client import SeriesListClient

TARGET = "爱意迟暮不相逢"


def test():
    with SeriesListClient(headless=True) as client:
        page = client.page
        assert page
        page.goto(
            f"https://www.changdupingtai.com/sale/short-play/list?search={quote(TARGET)}",
            timeout=90_000,
            wait_until="load",
        )
        page.wait_for_timeout(6000)
        for i in range(3):
            r = client.search_by_name(TARGET)
            inner = r.get("data") or {}
            rows = inner.get("data") or []
            print(f"try {i+1}: total={inner.get('total')} count={len(rows)}")
            if rows:
                print(" ", rows[0].get("series_name"))


if __name__ == "__main__":
    playwright_worker.run(test)
