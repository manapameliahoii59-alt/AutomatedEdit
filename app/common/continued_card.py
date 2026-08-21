"""第一集片尾「未完待续」检测：只检查最后几秒，命中才裁。"""

from __future__ import annotations

import os
import re
import tempfile
import threading
from pathlib import Path

from app.common.win_subprocess import run as win_run

TAIL_SECONDS = 3.0
# 额外多裁掉的秒数
TRIM_PAD_SECONDS = 0.1
SAMPLE_FPS = 2
KEYWORDS = ("未完待续", "下集更精彩", "关注后继续", "下集再见")

_ocr = None
_ocr_lock = threading.Lock()
_ocr_failed = False
_warned_unavailable = False


def is_first_episode(filename: str) -> bool:
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    m = re.match(r"^(\d+)", stem)
    if m:
        return int(m.group(1)) == 1
    m = re.search(r"第\s*(\d+)\s*集", stem)
    return bool(m) and int(m.group(1)) == 1


def matches_continued_text(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    return any(key in compact for key in KEYWORDS)


def covers_tail(end: float | None, duration: float, tail: float = TAIL_SECONDS) -> bool:
    if duration <= tail:
        return False
    actual = duration if end is None else float(end)
    return actual > duration - tail + 1e-3


def trimmed_end(
    duration: float,
    tail: float = TAIL_SECONDS,
    pad: float = TRIM_PAD_SECONDS,
) -> float:
    return max(0.0, float(duration) - tail - pad)


def _get_ocr():
    global _ocr, _ocr_failed, _warned_unavailable
    if _ocr_failed:
        return None
    if _ocr is not None:
        return _ocr
    with _ocr_lock:
        if _ocr is not None or _ocr_failed:
            return _ocr
        try:
            from rapidocr_onnxruntime import RapidOCR

            _ocr = RapidOCR()
        except Exception as exc:
            _ocr_failed = True
            if not _warned_unavailable:
                print(f"⚠️ 未完待续检测不可用（OCR 未加载）: {exc}", flush=True)
                _warned_unavailable = True
            return None
    return _ocr


def detect_continued_card(
    ffmpeg: str,
    video_path: str,
    duration: float,
    *,
    tail: float = TAIL_SECONDS,
) -> bool:
    """抽原片最后 tail 秒做 OCR；命中关键词返回 True。"""
    if not ffmpeg or not video_path or not os.path.isfile(video_path):
        return False
    if duration <= tail:
        return False
    engine = _get_ocr()
    if engine is None:
        return False
    start = max(0.0, float(duration) - tail)
    with tempfile.TemporaryDirectory(prefix="ep1_tail_") as tmp:
        pattern = str(Path(tmp) / "f_%02d.png")
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{tail:.3f}",
            "-i",
            video_path,
            "-vf",
            f"fps={SAMPLE_FPS}",
            pattern,
        ]
        try:
            proc = win_run(cmd, capture_output=True, timeout=60)
        except Exception as exc:
            print(f"⚠️ 未完待续抽帧失败: {exc}", flush=True)
            return False
        if getattr(proc, "returncode", 0) not in (0, None):
            return False
        for img in sorted(Path(tmp).glob("*.png")):
            try:
                result, _elapse = engine(str(img))
            except Exception:
                continue
            texts = []
            for item in result or []:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    texts.append(str(item[1]))
                else:
                    texts.append(str(item))
            if matches_continued_text("".join(texts)):
                return True
    return False
