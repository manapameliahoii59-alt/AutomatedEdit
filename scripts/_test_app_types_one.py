import time

from app.core.playwright_worker import playwright_worker
from app.data.services.series_list_client import SeriesListClient

TARGET = "爱意迟暮不相逢"


def test():
    for app_type in [19, 20, 21, 22, 1, 10]:
        time.sleep(3)
        with SeriesListClient(headless=True, app_type=app_type) as client:
            r = client.search_by_name(TARGET)
            inner = r.get("data") or {}
            rows = inner.get("data") or []
            print(
                f"app_type={app_type} app_id={client.app_info['app_id']} "
                f"code={r.get('code')} total={inner.get('total')} count={len(rows)}"
            )
            for row in rows[:2]:
                print(" ", row.get("series_name"))


if __name__ == "__main__":
    playwright_worker.run(test)
