"""穷举 series/list 搜索参数，找出能让「爱意迟暮不相逢」返回结果的配置。"""

import json
import time

from app.core.playwright_worker import playwright_worker
from app.data.services.series_list_client import SeriesListClient

TARGET = "爱意迟暮不相逢"


def hit(body):
    rows = (body.get("data") or {}).get("data") or []
    return any(TARGET in (r.get("series_name") or "") for r in rows)


def test():
    with SeriesListClient(headless=True) as client:
        base = {
            "query": TARGET,
            "search_type": "2",
            "page_index": "0",
            "page_size": "20",
        }
        date = client._default_series_date_range()
        cases = [
            ("current search_by_name", None),
            ("no content_genre", {**base}),
            ("with 30d dates", {**base, **date}),
            ("empty dates", {**base, "start_time": "", "end_time": ""}),
            ("sort_field=1", {**base, "sort_field": "1"}),
            ("aweme false", {**base, "aweme_user_new_version": "false"}),
            ("no query + filter client", {"search_type": "2", "page_index": "0", "page_size": "100", **date}),
        ]
        for label, params in cases:
            time.sleep(2)
            if params is None:
                body = client.search_by_name(TARGET)
            else:
                body = client.fetch_list(params)
            inner = body.get("data") or {}
            rows = inner.get("data") or []
            ok = hit(body)
            print(
                f"{label}: code={body.get('code')} total={inner.get('total')} "
                f"count={len(rows)} hit={ok} msg={body.get('message')}"
            )
            if ok:
                for r in rows:
                    if TARGET in (r.get("series_name") or ""):
                        print("  FOUND", r.get("series_name"), r.get("book_id"))
                        print("  params", json.dumps(params or base, ensure_ascii=False))


if __name__ == "__main__":
    playwright_worker.run(test)
