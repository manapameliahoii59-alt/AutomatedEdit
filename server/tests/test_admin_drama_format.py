"""每日活动剧目列格式化：兼容 sqladmin 传入列名字符串。"""

from types import SimpleNamespace

from app.admin_panel import _drama_names_text


def test_drama_names_text_accepts_string_attr():
    model = SimpleNamespace(downloaded_dramas='["剧A", "剧B"]')
    assert _drama_names_text(model, "downloaded_dramas") == "剧A、剧B"


def test_drama_names_text_accepts_column_like_attr():
    model = SimpleNamespace(planned_dramas='["策划剧"]')
    attr = SimpleNamespace(key="planned_dramas")
    assert _drama_names_text(model, attr) == "策划剧"


def test_drama_names_text_empty_list():
    model = SimpleNamespace(clipped_dramas="[]")
    assert _drama_names_text(model, "clipped_dramas") == ""
