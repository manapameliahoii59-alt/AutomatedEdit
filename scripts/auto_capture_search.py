"""自动在常读短剧列表页模拟搜索并捕获 API 参数。"""

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


def _parse_url(url: str) -> dict:
    qs = parse_qs(urlparse(url).query)
    return {k: v[0] if len(v) == 1 else v for k, v in qs.items()}


def auto_capture():
    captured = []
    with SeriesListClient(headless=True) as client:
        page = client.page
        assert page

        page.on(
            "response",
            lambda resp: captured.append(
                {
                    "url": resp.url,
                    "params": _parse_url(resp.url) if "series/list" in resp.url else {},
                    "body": resp.json() if "series/list" in resp.url and resp.status == 200 else None,
                }
            )
            if "series/list" in resp.url
            else None,
        )

        page.goto(
            "https://www.changdupingtai.com/sale/short-play/list",
            timeout=90_000,
            wait_until="load",
        )
        page.wait_for_timeout(4000)

        # 找搜索框
        selectors = [
            "input[placeholder*='剧名']",
            "input[placeholder*='搜索']",
            "input[placeholder*='短剧']",
            ".arco-input",
            "input[type='text']",
        ]
        for sel in selectors:
            loc = page.locator(sel)
            if loc.count() == 0:
                continue
            for i in range(min(loc.count(), 5)):
                el = loc.nth(i)
                try:
                    if not el.is_visible():
                        continue
                    el.click(timeout=2000)
                    el.fill(KEYWORD, timeout=3000)
                    el.press("Enter")
                    print(f"used selector {sel}[{i}]")
                    page.wait_for_timeout(5000)
                    break
                except Exception as exc:
                    print(f"selector {sel}[{i}] failed: {exc}")
            else:
                continue
            break

        results = []
        for item in captured:
            if not item.get("params"):
                continue
            body = item.get("body") or {}
            inner = body.get("data") or {}
            rows = inner.get("data") or []
            results.append(
                {
                    "params": item["params"],
                    "code": body.get("code"),
                    "total": inner.get("total"),
                    "count": len(rows),
                    "names": [r.get("series_name") for r in rows[:5]],
                }
            )

        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    playwright_worker.run(auto_capture)
