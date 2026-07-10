from app.data.services.series_list_client import (
    drama_search_keywords,
    normalize_drama_name,
    pick_drama_match,
)


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
