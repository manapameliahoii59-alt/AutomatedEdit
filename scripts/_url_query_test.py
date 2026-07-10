from app.core.playwright_worker import playwright_worker
from app.data.services.series_list_client import SeriesListClient

TARGET = "爱意迟暮不相逢"


def test():
    captured = []

    def on_resp(resp):
        if "series/list" in resp.url:
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

    with SeriesListClient(headless=True) as client:
        page = client.page
        assert page
        page.on("response", on_resp)

        from urllib.parse import quote

        for url in [
            f"https://www.changdupingtai.com/sale/short-play/list?query={quote(TARGET)}",
            f"https://www.changdupingtai.com/sale/short-play/list?search={quote(TARGET)}",
            f"https://www.changdupingtai.com/sale/short-play/list?keyword={quote(TARGET)}",
        ]:
            captured.clear()
            page.goto(url, timeout=90_000, wait_until="load")
            page.wait_for_timeout(5000)
            print("goto", url[:80])
            for c in captured:
                print(" ", c)
            r = client.search_by_name(TARGET)
            inner = r.get("data") or {}
            print(
                " api after goto: total=",
                inner.get("total"),
                "count=",
                len(inner.get("data") or []),
            )


if __name__ == "__main__":
    playwright_worker.run(test)
