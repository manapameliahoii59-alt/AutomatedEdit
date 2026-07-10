from app.core.playwright_worker import playwright_worker
from app.data.services.series_list_client import SeriesListClient


def test():
    with SeriesListClient(headless=False) as client:
        drama = client.find_drama_by_name("爱意迟暮不相逢")
        print(drama.get("series_name"), drama.get("book_id"))


if __name__ == "__main__":
    playwright_worker.run(test)
