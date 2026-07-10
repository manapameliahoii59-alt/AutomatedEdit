"""语义化版本号比较（major.minor.patch）。"""


def parse_version(version: str) -> tuple[int, ...]:
    text = (version or "").strip()
    if not text:
        return (0,)
    parts: list[int] = []
    for segment in text.split("."):
        token = segment.split("-", 1)[0].strip()
        if not token:
            parts.append(0)
            continue
        digits = ""
        for ch in token:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits or "0"))
    return tuple(parts) if parts else (0,)


def compare_versions(left: str, right: str) -> int:
    """left < right 返回 -1，相等 0，left > right 返回 1。"""
    a = parse_version(left)
    b = parse_version(right)
    width = max(len(a), len(b))
    a = a + (0,) * (width - len(a))
    b = b + (0,) * (width - len(b))
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


def is_version_older(current: str, target: str) -> bool:
    return compare_versions(current, target) < 0
