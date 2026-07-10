import pytest

from app.common.version_utils import compare_versions, is_version_older, parse_version


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("0.0.1", "0.0.2", -1),
        ("1.0.0", "0.9.9", 1),
        ("1.2.3", "1.2.3", 0),
        ("1.2", "1.2.0", 0),
        ("2.0.0-beta", "2.0.0", 0),
    ],
)
def test_compare_versions(left, right, expected):
    assert compare_versions(left, right) == expected


def test_is_version_older():
    assert is_version_older("0.0.1", "0.0.2")
    assert not is_version_older("0.0.2", "0.0.1")


def test_parse_version_empty():
    assert parse_version("") == (0,)
