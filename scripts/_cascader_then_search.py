from app.core.playwright_worker import playwright_worker
from app.data.services.series_list_client import SeriesListClient

TARGET = "爱意迟暮不相逢"


def test():
    with SeriesListClient(headless=False) as client:
        page = client.page
        assert page
        page.wait_for_timeout(4000)

        # 尝试点开顶部筛选区域
        for sel in [".arco-cascader", ".arco-select", "text=请选择"]:
            try:
                loc = page.locator(sel).first
                if loc.count() and loc.is_visible():
                    loc.click(timeout=3000)
                    page.wait_for_timeout(800)
                    opt = page.locator(".arco-cascader-option, .arco-select-option").first
                    if opt.count():
                        opt.click(timeout=2000)
                        page.wait_for_timeout(1500)
                    break
            except Exception:
                pass

        r = client.search_by_name(TARGET)
        inner = r.get("data") or {}
        rows = inner.get("data") or []
        print("after cascader:", r.get("code"), inner.get("total"), len(rows))
        if rows:
            print(rows[0].get("series_name"), rows[0].get("book_id"))


if __name__ == "__main__":
    playwright_worker.run(test)
