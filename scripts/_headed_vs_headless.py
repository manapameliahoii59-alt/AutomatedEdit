from urllib.parse import quote

from app.core.playwright_worker import playwright_worker
from app.data.services.series_list_client import SeriesListClient

TARGET = "爱意迟暮不相逢"


def test():
    captured = []

    def on_resp(resp):
        if "series/list" not in resp.url:
            return
        try:
            body = resp.json()
        except Exception:
            body = {}
        inner = body.get("data") or {}
        captured.append(
            {
                "url": resp.url,
                "total": inner.get("total"),
                "count": len(inner.get("data") or []),
                "first": ((inner.get("data") or [{}])[0]).get("series_name"),
            }
        )

    for headless in [True, False]:
        captured.clear()
        with SeriesListClient(headless=headless) as client:
            page = client.page
            assert page
            page.on("response", on_resp)
            page.goto(
                f"https://www.changdupingtai.com/sale/short-play/list?search={quote(TARGET)}",
                timeout=90_000,
                wait_until="load",
            )
            page.wait_for_timeout(6000)
            print("headless=", headless, "captured", len(captured))
            for c in captured:
                print(" ", c)


if __name__ == "__main__":
    playwright_worker.run(test)
