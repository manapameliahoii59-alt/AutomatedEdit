"""监听常读短剧列表页搜索时的真实 API 请求，并与应用内搜索对比。

用法:
  uv run python scripts/capture_changdu_search.py

浏览器打开后，请在短剧列表页手动搜索（例如「爱意迟暮不相逢」）。
脚本会记录所有 series/list 请求参数与响应，写入 changdu_data/search_capture.json
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.playwright_worker import playwright_worker
from datetime import timedelta

from app.data.services.series_list_client import SeriesListClient

OUTPUT = ROOT / "changdu_data" / "search_capture.json"
SERIES_LIST_MARKER = "content/series/list"
WAIT_SEC = 600  # 10 分钟，供用户手动搜索


def _short_play_list_url() -> str:
    """与网站列表页一致的 URL（含日期范围、page_index=1）。"""
    end = datetime.now()
    start = end - timedelta(days=30)
    return (
        "https://www.changdupingtai.com/sale/short-play/list"
        f"?sort_type=1"
        f"&start_time={start.strftime('%Y-%m-%d')}"
        f"&end_time={end.strftime('%Y-%m-%d')}"
        f"&sort_field=8"
        f"&aweme_user_new_version=true"
        f"&page_index=1"
        f"&page_size=10"
    )


def _parse_url(url: str) -> dict:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    return {k: v[0] if len(v) == 1 else v for k, v in qs.items()}


def _summarize_response(body: dict | None) -> dict:
    if not body:
        return {"code": None, "total": None, "count": 0, "first": None}
    inner = body.get("data") or {}
    rows = inner.get("data") or []
    first = None
    if rows:
        first = {
            "series_name": rows[0].get("series_name"),
            "book_id": rows[0].get("book_id"),
        }
    return {
        "code": body.get("code"),
        "message": body.get("message"),
        "total": inner.get("total"),
        "count": len(rows),
        "first": first,
    }


def capture():
    captured: list[dict] = []
    keyword_hint = "凌晨四点合伙人"

    list_url = _short_play_list_url()

    print("=" * 60)
    print("常读搜索抓包工具")
    print("=" * 60)
    print(f"将打开列表页：{list_url}")
    print(f"请在浏览器中手动搜索，例如：{keyword_hint}")
    print(f"也可再搜一个失败的剧名做对比")
    print(f"监听 {WAIT_SEC // 60} 分钟，结果写入：{OUTPUT}")
    print("=" * 60)

    with SeriesListClient(headless=False) as client:
        assert client.page
        page = client.page

        def on_response(response):
            url = response.url
            if SERIES_LIST_MARKER not in url:
                return
            entry = {
                "time": datetime.now(timezone.utc).isoformat(),
                "url": url,
                "params": _parse_url(url),
                "status": response.status,
            }
            try:
                body = response.json()
                entry["response"] = body
                entry["summary"] = _summarize_response(body)
            except Exception as exc:
                entry["parse_error"] = str(exc)
            captured.append(entry)
            summary = entry.get("summary") or {}
            print(
                f"\n[捕获 #{len(captured)}] query={entry['params'].get('query')!r} "
                f"search_type={entry['params'].get('search_type')} "
                f"code={summary.get('code')} total={summary.get('total')} "
                f"count={summary.get('count')}"
            )
            print(f"  完整 URL:\n  {url}")
            if summary.get("first"):
                print(f"  首条: {summary['first']['series_name']} ({summary['first']['book_id']})")
            # 增量保存，防止浏览器提前关闭丢数据
            OUTPUT.parent.mkdir(parents=True, exist_ok=True)
            OUTPUT.write_text(
                json.dumps(
                    {
                        "captured_at": datetime.now(timezone.utc).isoformat(),
                        "website_requests": captured,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        page.on("response", on_response)

        page.goto(list_url, timeout=90_000, wait_until="load")
        page.wait_for_timeout(3000)
        print(f"\n当前页面 URL: {page.url}")

        print(f"\n等待你在浏览器中操作搜索（最多 {WAIT_SEC // 60} 分钟）…")
        print("  建议：① 等列表加载  ② 搜「爱意迟暮不相逢」  ③ 再搜一个搜不到的剧名")
        deadline = time.time() + WAIT_SEC
        last_count = 0
        while time.time() < deadline:
            try:
                page.wait_for_timeout(2000)
            except Exception:
                break
            if len(captured) > last_count:
                last_count = len(captured)
                extra = time.time() + 30
                while time.time() < extra and time.time() < deadline:
                    try:
                        page.wait_for_timeout(2000)
                    except Exception:
                        break

        # 用户操作结束后再测应用内 API，避免干扰手动搜索
        app_searches: list[dict] = []
        print("\n[应用内 API 测试]")
        test_keywords = [keyword_hint, "爱意迟暮", "爱意"]
        seen_queries = {
            str((item.get("params") or {}).get("query"))
            for item in captured
            if (item.get("params") or {}).get("query")
        }
        for q in seen_queries:
            test_keywords.append(q)
        test_keywords = list(dict.fromkeys(test_keywords))[:5]
        for kw in test_keywords:
            try:
                r = client.search_by_name(kw)
                s = _summarize_response(r)
                app_searches.append({"keyword": kw, "summary": s})
                print(
                    f"  app search_by_name({kw!r}) -> code={s['code']} "
                    f"total={s['total']} count={s['count']}"
                )
                if s["first"]:
                    print(f"    首条: {s['first']['series_name']}")
            except Exception as exc:
                app_searches.append({"keyword": kw, "error": str(exc)})
                print(f"  app search_by_name({kw!r}) -> ERROR: {exc}")

        # 用网站捕获到的参数重放（若有）
        replays: list[dict] = []
        for item in captured:
            params = dict(item.get("params") or {})
            if not params.get("query"):
                continue
            try:
                r = client.fetch_list(params)
                replays.append(
                    {
                        "params": params,
                        "app_result": _summarize_response(r),
                    }
                )
            except Exception as exc:
                replays.append({"params": params, "error": str(exc)})

        report = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "list_page_url": list_url,
            "final_page_url": page.url,
            "app_info": client.app_info,
            "website_requests": captured,
            "app_searches": app_searches,
            "app_replays": replays,
        }
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n完成。共捕获 {len(captured)} 个请求，报告已保存。")
        if captured:
            print("\n网站 vs 应用 参数差异（首条捕获）:")
            web_params = captured[0].get("params") or {}
            app_params = {
                "query": web_params.get("query", keyword_hint),
                "search_type": "2",
                "content_genre": "2",
                "page_index": "0",
                "page_size": "20",
            }
            only_web = {k: v for k, v in web_params.items() if web_params.get(k) != app_params.get(k)}
            only_app = {k: v for k, v in app_params.items() if app_params.get(k) != web_params.get(k)}
            print("  网站独有参数:", json.dumps(only_web, ensure_ascii=False))
            print("  应用独有参数:", json.dumps(only_app, ensure_ascii=False))
        return report


if __name__ == "__main__":
    playwright_worker.run(capture)
