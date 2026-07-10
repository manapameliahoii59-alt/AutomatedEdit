import json
from urllib.parse import parse_qs, urlparse

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
            body = None
        captured.append({"url": resp.url, "body": body})

    with SeriesListClient(headless=False) as client:
        page = client.page
        assert page
        page.on("response", on_resp)
        page.wait_for_timeout(4000)

        # 点击级联选择器「请选择」
        cascader = page.locator(".arco-cascader, .arco-select").first
        print("cascader count", page.locator(".arco-cascader").count())
        try:
            cascader.click(timeout=5000)
            page.wait_for_timeout(1000)
            # 选第一项
            opt = page.locator(".arco-cascader-option, .arco-select-option").first
            if opt.count():
                print("click option", opt.inner_text(timeout=2000))
                opt.click(timeout=3000)
                page.wait_for_timeout(2000)
        except Exception as exc:
            print("cascader click failed:", exc)

        print("direct api before:", client.search_by_name(TARGET).get("data"))

        # 再试键盘搜索
        page.keyboard.press("Control+F")  # 可能无效
        page.wait_for_timeout(1000)

        print("captured so far", len(captured))
        for c in captured:
            params = {k: v[0] for k, v in parse_qs(urlparse(c["url"]).query).items()}
            inner = (c["body"] or {}).get("data") or {}
            print("url params", json.dumps(params, ensure_ascii=False)[:200])
            print(" total", inner.get("total"), "count", len(inner.get("data") or []))

        page.wait_for_timeout(15000)


if __name__ == "__main__":
    playwright_worker.run(test)
