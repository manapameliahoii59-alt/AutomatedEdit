from app.core.playwright_worker import playwright_worker
from app.data.services.series_list_client import SeriesListClient

TARGET = "爱意迟暮不相逢"


def test():
    with SeriesListClient(headless=True) as client:
        r = client.search_by_name(TARGET)  # current impl with content_genre
        inner = r.get("data") or {}
        print("current:", inner.get("total"), len(inner.get("data") or []))

        # 模拟网站成功请求：无 content_genre、无日期
        params = {
            "search_type": "2",
            "query": TARGET,
            "sort_type": "1",
            "sort_field": "8",
            "aweme_user_new_version": "true",
            "page_index": "0",
            "page_size": "10",
        }
        r2 = client._api_fetch(
            "/novelsale/distributor/content/series/list/v1/",
            params,
            referer="https://www.changdupingtai.com/sale/short-play/list",
        )
        inner2 = r2.get("data") or {}
        rows = inner2.get("data") or []
        print("website-like:", inner2.get("total"), len(rows))
        if rows:
            print(rows[0].get("series_name"), rows[0].get("book_id"))


if __name__ == "__main__":
    playwright_worker.run(test)
