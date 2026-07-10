from app.core.playwright_worker import playwright_worker
from app.data.services.series_list_client import SeriesListClient

TARGET = "爱意迟暮不相逢"


def test():
    with SeriesListClient(headless=True) as client:
        r = client.page.evaluate(
            """async () => {
                const params = new URLSearchParams({
                    query: '爱意迟暮不相逢',
                    search_type: '2',
                    content_genre: '2',
                    sort_type: '1',
                    sort_field: '8',
                    aweme_user_new_version: 'true',
                    page_index: '0',
                    page_size: '20',
                });
                const res = await fetch(`/novelsale/distributor/content/series/list/v1/?${params}`, {
                    credentials: 'include',
                });
                const text = await res.text();
                return { status: res.status, url: res.url, text: text.slice(0, 800) };
            }"""
        )
        print(r["status"])
        print(r["url"][-120:])
        print(r["text"])


if __name__ == "__main__":
    playwright_worker.run(test)
