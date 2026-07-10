from app.core.playwright_worker import playwright_worker
from app.data.services.series_list_client import SeriesListClient


def test():
    with SeriesListClient(headless=False) as client:
        page = client.page
        assert page
        page.wait_for_timeout(5000)
        info = page.evaluate(
            """() => {
                const text = document.body.innerText || '';
                const pickers = [...document.querySelectorAll('[class*=picker],[class*=date],[class*=range]')]
                    .slice(0, 20)
                    .map(el => ({cls: (el.className||'').slice(0,80), text: (el.innerText||'').slice(0,60)}));
                return {
                    hasDateText: /20\\d{2}-\\d{2}-\\d{2}/.test(text),
                    dateMatches: text.match(/20\\d{2}-\\d{2}-\\d{2}/g)?.slice(0, 4) || [],
                    pickers,
                };
            }"""
        )
        print(info)


if __name__ == "__main__":
    playwright_worker.run(test)
