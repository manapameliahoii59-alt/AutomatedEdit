from datetime import datetime, timedelta

from app.data.services.series_list_client import (
    SeriesListClient,
    drama_search_keywords,
    normalize_drama_name,
    pick_drama_match,
)
from app.ui.views.video_download.view_model import _format_changdu_precheck_error


def test_default_series_date_range_is_inclusive_month():
    """与网站一致：30 天含首尾（如 6/17～7/16），不是 end-30 的 31 天。"""
    end = datetime(2026, 7, 16, 12, 0, 0)
    # 直接复用公式，避免依赖 now()
    start = end - timedelta(days=29)
    assert start.strftime("%Y-%m-%d") == "2026-06-17"
    assert end.strftime("%Y-%m-%d") == "2026-07-16"

    dr = SeriesListClient._default_series_date_range(days=30)
    start_d = datetime.strptime(dr["start_time"], "%Y-%m-%d")
    end_d = datetime.strptime(dr["end_time"], "%Y-%m-%d")
    assert (end_d - start_d).days == 29


def test_format_changdu_precheck_error_distinguishes_date_limit():
    msg = _format_changdu_precheck_error("查询时间范围超过最大查询天数限制")
    assert "登录态已过期" not in msg
    assert "查询" in msg


def test_drama_search_keywords_splits_on_chinese_comma():
    assert drama_search_keywords("三代恩怨，逆袭归来") == [
        "三代恩怨，逆袭归来",
        "三代恩怨",
        "逆袭归来",
    ]


def test_pick_drama_match_prefers_exact_name():
    candidates = [
        {"series_name": "其他剧", "book_id": "1"},
        {"series_name": "偷藏半分喜", "book_id": "2"},
    ]
    picked = pick_drama_match(candidates, "偷藏半分喜")
    assert picked["book_id"] == "2"


def test_pick_drama_match_falls_back_to_partial():
    candidates = [
        {"series_name": "三代恩怨之逆袭归来", "book_id": "9"},
    ]
    picked = pick_drama_match(candidates, "三代恩怨")
    assert picked["book_id"] == "9"


def test_normalize_drama_name_strips_whitespace():
    assert normalize_drama_name(" 半 分 喜 ") == "半分喜"
