import time

from app.core.playwright_worker import playwright_worker
from app.data.services.series_list_client import SeriesListClient

TARGET = "爱意迟暮不相逢"


def search(client, label):
    params = {
        "search_type": "2",
        "query": TARGET,
        "sort_type": "1",
        "sort_field": "8",
        "aweme_user_new_version": "true",
        "page_index": "0",
        "page_size": "10",
    }
    r = client._api_fetch(
        "/novelsale/distributor/content/series/list/v1/",
        params,
        referer="https://www.changdupingtai.com/sale/short-play/list",
    )
    inner = r.get("data") or {}
    rows = inner.get("data") or []
    print(f"{label}: total={inner.get('total')} count={len(rows)}")
    if rows:
        print(" ", rows[0].get("series_name"), rows[0].get("book_id"))


def test():
    with SeriesListClient(headless=True) as client:
        # 模拟网站：先拉列表（capture #4）
        client._api_fetch(
            "/novelsale/distributor/content/series/list/v1/",
            {
                "search_type": "2",
                "sort_type": "1",
                "sort_field": "8",
                "aweme_user_new_version": "true",
                "page_index": "0",
                "page_size": "10",
            },
            referer="https://www.changdupingtai.com/sale/short-play/list",
        )
        time.sleep(1)
        search(client, "after warmup list")


if __name__ == "__main__":
    playwright_worker.run(test)
