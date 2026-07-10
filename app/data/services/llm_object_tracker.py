from __future__ import annotations

import base64
import json
import os
import re
from collections.abc import Callable
from typing import Any

from app.common.my_logger import my_logger as logger

DEFAULT_SAMPLE_INTERVAL_MS = 200  # 5 fps
DEFAULT_MODEL = "qwen3-vl-plus"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MAX_IMAGE_SIDE = 768

_LOCATE_PROMPT = (
    "图1是用户框选的追踪目标锚定特写。"
    "请在图2视频帧中找到与图1同一种类、或高度关联的目标物体。"
    "仅返回 JSON，不要其它说明："
    '{"bbox_2d":[x1,y1,x2,y2]}，'
    "坐标为相对图2宽高的 0~1000 整数（左上角与右下角）；找不到则返回 {\"found\": false}。"
)


def resolve_dashscope_api_key() -> str:
    """从 config.json 或环境变量读取 DashScope API Key。"""
    try:
        from app.common.config import cfg

        key = str(cfg.dashscope_api_key.value or "").strip()
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("DASHSCOPE_API_KEY", "").strip()


def merge_supplement_keyframes(
    existing: list[tuple[int, float, float, float, float]],
    supplement: list[tuple[int, float, float, float, float]],
    *,
    tolerance_ms: int = 80,
) -> list[tuple[int, float, float, float, float]]:
    """保留已有 CV 追踪点，用 LLM 结果填补区间外或间隙。"""
    if not supplement:
        return list(existing)
    if not existing:
        return sorted(supplement, key=lambda item: item[0])

    existing_times = [item[0] for item in existing]
    first_cv = min(existing_times)
    last_cv = max(existing_times)
    merged = list(existing)
    for kf in supplement:
        time_ms = kf[0]
        if any(abs(time_ms - existing_time) <= tolerance_ms for existing_time in existing_times):
            continue
        if time_ms < first_cv - tolerance_ms or time_ms > last_cv + tolerance_ms:
            merged.append(kf)
    return sorted(merged, key=lambda item: item[0])


def _encode_frame_jpeg_base64(frame, *, max_side: int = MAX_IMAGE_SIDE) -> str:
    import cv2

    height, width = frame.shape[:2]
    if max(height, width) > max_side:
        scale = max_side / max(height, width)
        frame = cv2.resize(frame, (int(width * scale), int(height * scale)))
    ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("无法编码图像为 JPEG")
    encoded = base64.b64encode(buffer.tobytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _crop_normalized(frame, nx: float, ny: float, nw: float, nh: float):
    import cv2

    height, width = frame.shape[:2]
    x = max(0, min(width - 2, int(nx * width)))
    y = max(0, min(height - 2, int(ny * height)))
    w = max(2, min(width - x, int(nw * width)))
    h = max(2, min(height - y, int(nh * height)))
    crop = frame[y : y + h, x : x + w]
    if crop.size == 0:
        raise RuntimeError("锚定区域裁剪失败")
    return crop


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list) and parsed:
            first = parsed[0]
            return first if isinstance(first, dict) else None
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _coords_to_normalized(
    x1: float, y1: float, x2: float, y2: float
) -> tuple[float, float, float, float] | None:
    """将 bbox_2d 转为 0~1 归一化 (nx, ny, nw, nh)。"""
    peak = max(abs(x1), abs(y1), abs(x2), abs(y2))
    if peak > 1.5:
        if peak <= 1000:
            x1, y1, x2, y2 = x1 / 1000, y1 / 1000, x2 / 1000, y2 / 1000
        else:
            return None
    nx = max(0.0, min(1.0, min(x1, x2)))
    ny = max(0.0, min(1.0, min(y1, y2)))
    nw = max(0.0, min(1.0 - nx, abs(x2 - x1)))
    nh = max(0.0, min(1.0 - ny, abs(y2 - y1)))
    if nw > 0 and nh > 0:
        return nx, ny, nw, nh
    return None


def _parse_bbox_payload(payload: dict[str, Any]) -> tuple[float, float, float, float] | None:
    if payload.get("found") is False:
        return None

    if "bbox_2d" in payload:
        raw = payload["bbox_2d"]
        if isinstance(raw, (list, tuple)) and len(raw) >= 4:
            return _coords_to_normalized(
                float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3])
            )

    keys = ("x", "y", "w", "h")
    if all(key in payload for key in keys):
        nx = float(payload["x"])
        ny = float(payload["y"])
        nw = float(payload["w"])
        nh = float(payload["h"])
        peak = max(abs(nx), abs(ny), abs(nw), abs(nh))
        if peak > 1.5 and peak <= 1000:
            nx, ny, nw, nh = nx / 1000, ny / 1000, nw / 1000, nh / 1000
        if nw > 0 and nh > 0:
            return (
                max(0.0, min(1.0, nx)),
                max(0.0, min(1.0, ny)),
                max(0.0, min(1.0, nw)),
                max(0.0, min(1.0, nh)),
            )
    return None


def _call_qwen_locate(
    anchor_b64: str,
    frame_b64: str,
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
) -> tuple[float, float, float, float] | None:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": anchor_b64}},
                        {"type": "image_url", "image_url": {"url": frame_b64}},
                        {"type": "text", "text": _LOCATE_PROMPT},
                    ],
                }
            ],
        )
    except Exception as exc:
        raise RuntimeError(f"追踪服务调用失败: {exc}") from exc

    text = completion.choices[0].message.content or ""
    payload = _extract_json_object(text)
    if payload is None:
        logger.debug("无法解析追踪服务返回: {}", text[:200])
        return None
    return _parse_bbox_payload(payload)


def track_object_with_llm(
    video_path: str,
    start_ms: int,
    end_ms: int,
    anchor_time_ms: int,
    anchor_nx: float,
    anchor_ny: float,
    anchor_nw: float,
    anchor_nh: float,
    *,
    sample_interval_ms: int = DEFAULT_SAMPLE_INTERVAL_MS,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    existing_keyframes: list[tuple[int, float, float, float, float]] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[tuple[int, float, float, float, float]]:
    """用通义千问视觉模型补充追踪：锚定图 + 片段内 5fps 采样帧。"""
    import cv2

    resolved_key = (api_key or resolve_dashscope_api_key()).strip()
    if not resolved_key:
        raise RuntimeError("视觉追踪服务未配置，请联系管理员。")

    capture = cv2.VideoCapture(video_path)
    if not capture.isOpened():
        raise RuntimeError(f"无法打开视频: {video_path}")

    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if width < 1 or height < 1:
        capture.release()
        raise RuntimeError("无法读取视频尺寸")

    anchor_frame_index = max(0, int(anchor_time_ms / 1000 * fps))
    capture.set(cv2.CAP_PROP_POS_FRAMES, anchor_frame_index)
    ok, anchor_frame = capture.read()
    if not ok or anchor_frame is None:
        capture.release()
        raise RuntimeError("无法读取锚定帧")
    anchor_crop = _crop_normalized(
        anchor_frame, anchor_nx, anchor_ny, anchor_nw, anchor_nh
    )
    anchor_b64 = _encode_frame_jpeg_base64(anchor_crop)

    start_frame = max(0, int(start_ms / 1000 * fps))
    end_frame = max(start_frame, int(end_ms / 1000 * fps))
    frame_step = max(1, int(sample_interval_ms / 1000 * fps))

    llm_keyframes: list[tuple[int, float, float, float, float]] = []
    capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    frame_index = start_frame - 1
    while frame_index < end_frame:
        if should_cancel and should_cancel():
            logger.info("智能追踪已取消（切换剧集或新任务）")
            break
        ok, frame = capture.read()
        if not ok or frame is None:
            break
        frame_index += 1
        if (frame_index - start_frame) % frame_step != 0 and frame_index != start_frame:
            continue

        time_ms = int(frame_index / fps * 1000)
        if time_ms > end_ms:
            break
        frame_b64 = _encode_frame_jpeg_base64(frame)
        bbox = _call_qwen_locate(
            anchor_b64,
            frame_b64,
            api_key=resolved_key,
            model=model,
            base_url=base_url,
        )
        if bbox is None:
            logger.debug("追踪服务未定位到目标 time_ms={}", time_ms)
            continue
        llm_keyframes.append((time_ms, *bbox))

    capture.release()

    if not llm_keyframes:
        raise RuntimeError("智能追踪未能在片段内定位到目标，请检查锚定框或联系管理员。")

    seed = (start_ms, anchor_nx, anchor_ny, anchor_nw, anchor_nh)
    if not llm_keyframes or llm_keyframes[0][0] != start_ms:
        llm_keyframes.insert(0, seed)

    existing = list(existing_keyframes or [])
    return merge_supplement_keyframes(existing, llm_keyframes)
