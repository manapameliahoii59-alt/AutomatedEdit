import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.services.usage_meta import (
    format_plan_drama_meta,
    normalize_plan_mode,
    parse_drama_name_from_meta,
    parse_plan_mode_from_meta,
)


def test_format_and_parse_plan_drama_meta():
    assert format_plan_drama_meta("剧A", "mixed") == "剧A（混合）"
    assert format_plan_drama_meta("剧A", "short") == "剧A（短片）"
    assert format_plan_drama_meta("剧A", "long") == "剧A（长片）"
    assert format_plan_drama_meta("剧A", None) == "剧A"
    assert parse_drama_name_from_meta("剧A（混合）") == "剧A"
    assert parse_drama_name_from_meta("剧A") == "剧A"
    assert parse_plan_mode_from_meta("剧A（混合）") == "mixed"
    assert parse_plan_mode_from_meta("剧A") is None
    assert normalize_plan_mode("MIXED") == "mixed"
    assert normalize_plan_mode("other") is None
