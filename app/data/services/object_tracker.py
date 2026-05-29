from __future__ import annotations

from app.common.my_logger import my_logger as logger

# 色彩相关性低于此值视为跟丢（略严于参考脚本 0.35，减少跟到背景上）
DEFAULT_SIMILARITY_THRESHOLD = 0.45
# 相对历史最佳相似度的跌幅超过此比例则判定跟丢（目标被替换/消失）
PEAK_SIMILARITY_DROP_RATIO = 0.72
# 追踪框面积相对种子框的允许倍数
MIN_AREA_RATIO = 0.12
MAX_AREA_RATIO = 4.0


_TRACKER_FACTORIES: tuple[tuple[str, str], ...] = (
    ("CSRT", "TrackerCSRT_create"),
    ("KCF", "TrackerKCF_create"),
    ("MOSSE", "TrackerMOSSE_create"),
    ("MIL", "TrackerMIL_create"),
)


def _create_tracker():
    """创建 OpenCV 追踪器；CSRT 在 contrib 包中，主包 opencv-python-headless 不含追踪模块。"""
    import cv2

    for name, factory_name in _TRACKER_FACTORIES:
        if hasattr(cv2, factory_name):
            tracker = getattr(cv2, factory_name)()
            logger.debug("使用追踪器: {}", name)
            return tracker
        legacy = getattr(cv2, "legacy", None)
        if legacy is not None and hasattr(legacy, factory_name):
            tracker = getattr(legacy, factory_name)()
            logger.debug("使用追踪器 (legacy): {}", name)
            return tracker

    raise RuntimeError(
        "当前 OpenCV 未包含追踪器（CSRT/KCF 等）。"
        "请安装 opencv-contrib-python-headless：uv sync"
    )


def _roi_histogram(frame, x: int, y: int, w: int, h: int):
    import cv2

    fh, fw = frame.shape[:2]
    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(fw, x0 + max(1, w))
    y1 = min(fh, y0 + max(1, h))
    roi = frame[y0:y1, x0:x1]
    if roi.size == 0:
        return None
    hist = cv2.calcHist([roi], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
    cv2.normalize(hist, hist)
    return hist


def _histogram_similarity(hist_start, frame, x: int, y: int, w: int, h: int) -> float | None:
    import cv2

    hist_curr = _roi_histogram(frame, x, y, w, h)
    if hist_curr is None:
        return None
    return float(cv2.compareHist(hist_start, hist_curr, cv2.HISTCMP_CORREL))


def _validate_tracked_box(
    frame,
    x: int,
    y: int,
    w: int,
    h: int,
    frame_width: int,
    frame_height: int,
    last_box: tuple[int, int, int, int],
    seed_w: int,
    seed_h: int,
    hist_start,
    *,
    similarity_threshold: float,
    peak_similarity: float,
) -> tuple[bool, float]:
    if w < 2 or h < 2:
        return False, peak_similarity
    if x < -w or y < -h or x > frame_width or y > frame_height:
        return False, peak_similarity

    seed_area = max(1, seed_w * seed_h)
    area = w * h
    if area < seed_area * MIN_AREA_RATIO or area > seed_area * MAX_AREA_RATIO:
        logger.debug("追踪框面积异常 ratio={:.2f}", area / seed_area)
        return False, peak_similarity

    sim = _histogram_similarity(hist_start, frame, x, y, w, h)
    if sim is not None:
        peak_similarity = max(peak_similarity, sim)
        if sim < similarity_threshold:
            logger.debug("追踪色彩校验失败 similarity={:.3f}", sim)
            return False, peak_similarity
        if peak_similarity > 0 and sim < peak_similarity * PEAK_SIMILARITY_DROP_RATIO:
            logger.debug(
                "追踪色彩衰减 similarity={:.3f} peak={:.3f}",
                sim,
                peak_similarity,
            )
            return False, peak_similarity

    lx, ly, _, _ = last_box
    dist = ((x - lx) ** 2 + (y - ly) ** 2) ** 0.5
    if dist > max(seed_w, seed_h) * 0.8:
        logger.debug("追踪位移过大 dist={:.1f}", dist)
        return False, peak_similarity
    return True, peak_similarity


def _normalize_box(
    x: int, y: int, w: int, h: int, width: int, height: int
) -> tuple[float, float, float, float]:
    return (
        max(0.0, min(1.0, x / width)),
        max(0.0, min(1.0, y / height)),
        max(0.0, min(1.0, w / width)),
        max(0.0, min(1.0, h / height)),
    )


def _record_box(
    results: dict[int, tuple[int, int, int, int]],
    frame_index: int,
    box: tuple[int, int, int, int],
) -> None:
    results[frame_index] = box


def _run_csrt_on_frames(
    frames: list[tuple[int, object]],
    seed_list_index: int,
    initial_box: tuple[int, int, int, int],
    width: int,
    height: int,
    *,
    similarity_threshold: float,
) -> dict[int, tuple[int, int, int, int]]:
    """在短缓存帧列上双向 CSRT（对齐参考脚本 run_feature_tracker）。"""
    seed_frame = frames[seed_list_index][1]
    x0, y0, w0, h0 = initial_box
    hist_start = _roi_histogram(seed_frame, x0, y0, w0, h0)
    if hist_start is None:
        return {frames[seed_list_index][0]: initial_box}

    results: dict[int, tuple[int, int, int, int]] = {
        frames[seed_list_index][0]: initial_box,
    }

    def run_direction(forward: bool) -> None:
        tracker = _create_tracker()
        tracker.init(seed_frame, initial_box)
        last_box = initial_box
        indices = (
            range(seed_list_index + 1, len(frames))
            if forward
            else range(seed_list_index - 1, -1, -1)
        )
        peak_similarity = 0.0
        for list_index in indices:
            frame_index, frame = frames[list_index]
            tracked, bbox = tracker.update(frame)
            if not tracked:
                break
            bx, by, bw, bh = map(int, bbox)
            ok, peak_similarity = _validate_tracked_box(
                frame,
                bx,
                by,
                bw,
                bh,
                width,
                height,
                last_box,
                w0,
                h0,
                hist_start,
                similarity_threshold=similarity_threshold,
                peak_similarity=peak_similarity,
            )
            if not ok:
                break
            _record_box(results, frame_index, (bx, by, bw, bh))
            last_box = (bx, by, bw, bh)

    run_direction(forward=True)
    run_direction(forward=False)
    return results


def track_object_in_video(
    video_path: str,
    start_ms: int,
    end_ms: int,
    nx: float,
    ny: float,
    nw: float,
    nh: float,
    *,
    sample_interval_ms: int = 100,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    backward_buffer_seconds: float = 3.0,
) -> list[tuple[int, float, float, float, float]]:
    """手动框选 + CSRT 追踪，返回归一化关键帧。

    与云端 API 检测方案相比，仅初始框来源不同；追踪阶段同样为 CSRT，
    并增加色彩直方图与位移突变校验，减少目标消失后的框残留。
    """
    import cv2

    capture = cv2.VideoCapture(video_path)
    if not capture.isOpened():
        raise RuntimeError(f"无法打开视频: {video_path}")

    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if width < 1 or height < 1:
        capture.release()
        raise RuntimeError("无法读取视频尺寸")

    start_frame = max(0, min(total_frames - 1, int(start_ms / 1000 * fps)))
    end_frame = max(start_frame, min(total_frames - 1, int(end_ms / 1000 * fps)))
    frame_step = max(1, int(sample_interval_ms / 1000 * fps))

    x = int(nx * width)
    y = int(ny * height)
    w = max(2, int(nw * width))
    h = max(2, int(nh * height))
    x = max(0, min(width - w, x))
    y = max(0, min(height - h, y))
    initial_box = (x, y, w, h)

    capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    ok, seed_frame = capture.read()
    if not ok or seed_frame is None:
        capture.release()
        raise RuntimeError("无法读取追踪起始帧")

    hist_start = _roi_histogram(seed_frame, x, y, w, h)
    if hist_start is None:
        capture.release()
        raise RuntimeError("无法提取追踪目标特征")

    raw_boxes: dict[int, tuple[int, int, int, int]] = {start_frame: initial_box}

    tracker = _create_tracker()
    tracker.init(seed_frame, initial_box)
    last_box = initial_box
    peak_similarity = 1.0
    frame_index = start_frame
    while frame_index < end_frame:
        ok, frame = capture.read()
        if not ok or frame is None:
            break
        frame_index += 1
        tracked, bbox = tracker.update(frame)
        if not tracked:
            logger.warning("追踪丢失 frame={}", frame_index)
            break
        bx, by, bw, bh = map(int, bbox)
        ok_box, peak_similarity = _validate_tracked_box(
            frame,
            bx,
            by,
            bw,
            bh,
            width,
            height,
            last_box,
            w,
            h,
            hist_start,
            similarity_threshold=similarity_threshold,
            peak_similarity=peak_similarity,
        )
        if not ok_box:
            logger.warning("追踪校验失败 frame={}", frame_index)
            break
        last_box = (bx, by, bw, bh)
        if (frame_index - start_frame) % frame_step == 0:
            raw_boxes[frame_index] = last_box

    backward_start = max(0, start_frame - int(backward_buffer_seconds * fps))
    if start_frame > backward_start:
        buf_frames: list[tuple[int, object]] = []
        capture.set(cv2.CAP_PROP_POS_FRAMES, backward_start)
        for idx in range(backward_start, start_frame + 1):
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            buf_frames.append((idx, frame))
        if buf_frames:
            seed_idx = start_frame - backward_start
            back_boxes = _run_csrt_on_frames(
                buf_frames,
                seed_idx,
                initial_box,
                width,
                height,
                similarity_threshold=similarity_threshold,
            )
            for idx, box in back_boxes.items():
                if idx < start_frame:
                    raw_boxes[idx] = box

    capture.release()

    keyframes: list[tuple[int, float, float, float, float]] = []
    for frame_index in sorted(raw_boxes):
        time_ms = int(frame_index / fps * 1000)
        if time_ms > end_ms + sample_interval_ms:
            continue
        bx, by, bw, bh = raw_boxes[frame_index]
        keyframes.append((time_ms, *_normalize_box(bx, by, bw, bh, width, height)))

    if not keyframes or keyframes[0][0] != start_ms:
        keyframes.insert(0, (start_ms, nx, ny, nw, nh))
    return keyframes
