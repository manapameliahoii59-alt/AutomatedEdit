"""对比：直接 API 搜索 vs 先在页面输入搜索框后再 API。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.playwright_worker import playwright_worker
from app.data.services.series_list_client import SeriesListClient

KEYWORD = "爱意迟暮不相逢"


def summarize(body):
    inner = (body or {}).get("data") or {}
    rows = inner.get("data") or []
    return {
        "code": (body or {}).get("code"),
        "total": inner.get("total"),
        "count": len(rows),
        "first": rows[0].get("series_name") if rows else None,
    }


def compare():
    captured = []

    def on_response(resp):
        if "series/list" not in resp.url:
            return
        try:
            body = resp.json()
        except Exception:
            body = None
        captured.append(
            {
                "params": {
                    k: v[0] if len(v) == 1 else v
                    for k, v in parse_qs(urlparse(resp.url).query).items()
                },
                "summary": summarize(body),
            }
        )

    with SeriesListClient(headless=True) as client:
        page = client.page
        assert page
        page.on("response", on_response)

        page.goto(
            "https://www.changdupingtai.com/sale/short-play/list",
            timeout=90_000,
            wait_until="load",
        )
        page.wait_for_timeout(5000)

        print("=== 1) 直接 search_by_name (当前实现) ===")
        r1 = client.search_by_name(KEYWORD)
        print(json.dumps(summarize(r1), ensure_ascii=False))

        print("\n=== 2) 不带 content_genre ===")
        r2 = client.fetch_list(
            {
                "query": KEYWORD,
                "search_type": "2",
                "page_index": "0",
                "page_size": "20",
            }
        )
        print(json.dumps(summarize(r2), ensure_ascii=False))

        print("\n=== 3) 页面搜索框输入后再 search_by_name ===")
        captured.clear()
        inp = page.locator("input[placeholder*='剧名']").first
        if inp.count() == 0:
            inp = page.locator("input[type='text']").first
        inp.click()
        inp.fill(KEYWORD)
        inp.press("Enter")
        page.wait_for_timeout(4000)
        r3 = client.search_by_name(KEYWORD)
        print("after UI:", json.dumps(summarize(r3), ensure_ascii=False))
        print("UI captured requests:")
        for i, c in enumerate(captured, 1):
            print(f"  #{i}", json.dumps(c, ensure_ascii=False))

        print("\n=== 4) 用网站捕获参数重放 ===")
        if captured:
            web_params = captured[-1]["params"]
            r4 = client.fetch_list(web_params)
            print("web params:", json.dumps(web_params, ensure_ascii=False))
            print("replay:", json.dumps(summarize(r4), ensure_ascii=False))


if __name__ == "__main__":
    playwright_worker.run(compare)
