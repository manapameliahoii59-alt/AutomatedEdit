from __future__ import annotations

from dataclasses import dataclass, field

MODE_TRACKING = "tracking"
MODE_CURRENT_FRAME = "current_frame"
MODE_TIME_RANGE = "time_range"

MODE_LABELS = {
    MODE_TRACKING: "智能追踪",
    MODE_CURRENT_FRAME: "当前帧",
    MODE_TIME_RANGE: "关键帧段",
}

MODE_HINTS = {
    MODE_TRACKING: "① 暂停  ② 框选目标  ③ 点击右侧「开始追踪」（CSRT + 色彩校验，跟至片尾或丢失）",
    MODE_CURRENT_FRAME: "① 暂停到目标画面  ② 框选区域  ③ 仅对当前帧生效（精准补漏）",
    MODE_TIME_RANGE: "① 设入点/出点  ② 入点处框选  ③ 出点或其它时刻再框选，中间位置自动插值",
}


def format_time_ms(ms: int) -> str:
    total_seconds = max(0, ms) // 1000
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


@dataclass
class MaskRegion:
    """打码区域：坐标为相对视频原始画面的归一化值 (0~1)。"""

    nx: float
    ny: float
    nw: float
    nh: float
    start_ms: int
    end_ms: int
    label: str = ""
    mask_type: str = "gaussian"
    intensity: int = 50
    mode: str = MODE_CURRENT_FRAME
    track_keyframes: tuple[tuple[int, float, float, float, float], ...] = ()

    def display_text(self) -> str:
        name = self.label or "区域"
        mode_label = MODE_LABELS.get(self.mode, self.mode)
        if self.mode == MODE_CURRENT_FRAME or self.end_ms - self.start_ms <= 50:
            time_part = f"单帧 {format_time_ms(self.start_ms)}"
        else:
            time_part = f"{format_time_ms(self.start_ms)} - {format_time_ms(self.end_ms)}"
        kf_hint = ""
        if self.track_keyframes:
            if self.mode == MODE_TRACKING:
                kf_hint = f" · {len(self.track_keyframes)} 追踪点"
            elif self.mode == MODE_TIME_RANGE:
                kf_hint = f" · {len(self.track_keyframes)} 关键帧"
        return f"[{time_part}] {name}（{mode_label}{kf_hint}）"

    def clamped(self) -> MaskRegion:
        nx = max(0.0, min(1.0, self.nx))
        ny = max(0.0, min(1.0, self.ny))
        nw = max(0.0, min(1.0 - nx, self.nw))
        nh = max(0.0, min(1.0 - ny, self.nh))
        return MaskRegion(
            nx=nx,
            ny=ny,
            nw=nw,
            nh=nh,
            start_ms=self.start_ms,
            end_ms=self.end_ms,
            label=self.label,
            mask_type=self.mask_type,
            intensity=self.intensity,
            mode=self.mode,
            track_keyframes=self.track_keyframes,
        )

    def with_keyframes(
        self, keyframes: list[tuple[int, float, float, float, float]]
    ) -> MaskRegion:
        ordered = sorted(keyframes, key=lambda item: item[0])
        first = ordered[0] if ordered else (self.start_ms, self.nx, self.ny, self.nw, self.nh)
        return MaskRegion(
            nx=first[1],
            ny=first[2],
            nw=first[3],
            nh=first[4],
            start_ms=self.start_ms,
            end_ms=self.end_ms,
            label=self.label,
            mask_type=self.mask_type,
            intensity=self.intensity,
            mode=self.mode,
            track_keyframes=tuple(ordered),
        )

    def with_tracking_keyframes(
        self, keyframes: list[tuple[int, float, float, float, float]]
    ) -> MaskRegion:
        """写入追踪结果，并将有效结束时间截断到最后一个追踪点（目标消失后不再显示框）。"""
        ordered = sorted(keyframes, key=lambda item: item[0])
        if not ordered:
            return self
        first = ordered[0]
        last_ms = ordered[-1][0]
        return MaskRegion(
            nx=first[1],
            ny=first[2],
            nw=first[3],
            nh=first[4],
            start_ms=self.start_ms,
            end_ms=max(self.start_ms, last_ms),
            label=self.label,
            mask_type=self.mask_type,
            intensity=self.intensity,
            mode=self.mode,
            track_keyframes=tuple(ordered),
        )

    def _effective_end_ms(self) -> int:
        if self.mode == MODE_TRACKING and len(self.track_keyframes) >= 2:
            return max(item[0] for item in self.track_keyframes)
        return self.end_ms

    def upsert_keyframe(
        self,
        time_ms: int,
        nx: float,
        ny: float,
        nw: float,
        nh: float,
        *,
        merge_tolerance_ms: int = 50,
    ) -> MaskRegion:
        """在指定时刻添加或更新关键帧（追踪/时间段模式共用）。"""
        keyframes = [tuple(item) for item in self.track_keyframes]
        for index, (t_ms, *_rest) in enumerate(keyframes):
            if abs(t_ms - time_ms) <= merge_tolerance_ms:
                keyframes[index] = (time_ms, nx, ny, nw, nh)
                break
        else:
            keyframes.append((time_ms, nx, ny, nw, nh))
        return self.with_keyframes(keyframes)

    def is_active_at(self, position_ms: int) -> bool:
        return self.start_ms <= position_ms <= self._effective_end_ms()

    def bbox_at(self, position_ms: int) -> tuple[float, float, float, float] | None:
        """返回当前时刻的归一化框；不在时间范围内则返回 None。"""
        if position_ms < self.start_ms or position_ms > self._effective_end_ms():
            return None
        if self.track_keyframes:
            ordered = sorted(self.track_keyframes, key=lambda item: item[0])
            last_ms = ordered[-1][0]
            if self.mode == MODE_TRACKING and position_ms > last_ms:
                return None
            if position_ms <= ordered[0][0]:
                item = ordered[0]
                return item[1], item[2], item[3], item[4]
            return _interpolate_keyframes(ordered, position_ms, extrapolate=False)
        return (self.nx, self.ny, self.nw, self.nh)

    def seed_bbox_for_tracking(self) -> tuple[float, float, float, float] | None:
        """追踪/重新追踪在入点 start_ms 使用的种子框（与预览 bbox_at 对齐）。"""
        if self.nw <= 0 or self.nh <= 0:
            return None
        if not self.track_keyframes:
            return (self.nx, self.ny, self.nw, self.nh)
        bbox = self.bbox_at(self.start_ms)
        if bbox is not None:
            return bbox
        ordered = sorted(self.track_keyframes, key=lambda item: item[0])
        last_ms = ordered[-1][0]
        if self.mode == MODE_TRACKING and self.start_ms > last_ms:
            return None
        return _interpolate_keyframes(ordered, self.start_ms, extrapolate=True)

    def with_segment_times(self, start_ms: int, end_ms: int) -> MaskRegion:
        """更新片段入出点；有轨迹时按新入点同步种子框并裁剪区间外关键帧。"""
        end_ms = max(start_ms + 34, end_ms)
        keyframes = tuple(item for item in self.track_keyframes if item[0] <= end_ms)
        if not keyframes:
            return MaskRegion(
                nx=self.nx,
                ny=self.ny,
                nw=self.nw,
                nh=self.nh,
                start_ms=start_ms,
                end_ms=end_ms,
                label=self.label,
                mask_type=self.mask_type,
                intensity=self.intensity,
                mode=self.mode,
                track_keyframes=(),
            ).clamped()

        interim = MaskRegion(
            nx=self.nx,
            ny=self.ny,
            nw=self.nw,
            nh=self.nh,
            start_ms=start_ms,
            end_ms=end_ms,
            label=self.label,
            mask_type=self.mask_type,
            intensity=self.intensity,
            mode=self.mode,
            track_keyframes=keyframes,
        )
        seed = interim.seed_bbox_for_tracking()
        if seed is None:
            return MaskRegion(
                nx=self.nx,
                ny=self.ny,
                nw=0.0,
                nh=0.0,
                start_ms=start_ms,
                end_ms=end_ms,
                label=self.label,
                mask_type=self.mask_type,
                intensity=self.intensity,
                mode=self.mode,
                track_keyframes=(),
            )

        nx, ny, nw, nh = seed
        synced = interim.upsert_keyframe(start_ms, nx, ny, nw, nh)
        merge_tolerance_ms = 50
        kept = [
            item
            for item in synced.track_keyframes
            if item[0] >= start_ms - merge_tolerance_ms
        ]
        if not kept:
            kept = [(start_ms, nx, ny, nw, nh)]
        return synced.with_keyframes(kept).clamped()

    def timeline_spans(self) -> list[tuple[int, int, str]]:
        """时间轴可视化用的片段列表 (start_ms, end_ms, label)。"""
        name = self.label or "区域"
        if len(self.track_keyframes) >= 2:
            keyframes = sorted(self.track_keyframes, key=lambda item: item[0])
            spans: list[tuple[int, int, str]] = []
            effective_end = self._effective_end_ms()
            for index, (start_ms, *_rest) in enumerate(keyframes):
                end_ms = (
                    keyframes[index + 1][0]
                    if index + 1 < len(keyframes)
                    else effective_end
                )
                spans.append((start_ms, end_ms, name))
            return spans
        return [(self.start_ms, self.end_ms, name)]


def _interpolate_keyframes(
    keyframes: tuple[tuple[int, float, float, float, float], ...] | list[tuple[int, float, float, float, float]],
    position_ms: int,
    *,
    extrapolate: bool = True,
) -> tuple[float, float, float, float]:
    ordered = sorted(keyframes, key=lambda item: item[0])
    if position_ms <= ordered[0][0]:
        return ordered[0][1], ordered[0][2], ordered[0][3], ordered[0][4]
    if position_ms >= ordered[-1][0]:
        if not extrapolate:
            item = ordered[-1]
            return item[1], item[2], item[3], item[4]
        item = ordered[-1]
        return item[1], item[2], item[3], item[4]

    for index in range(len(ordered) - 1):
        t0, nx0, ny0, nw0, nh0 = ordered[index]
        t1, nx1, ny1, nw1, nh1 = ordered[index + 1]
        if t0 <= position_ms <= t1:
            if t1 <= t0:
                return nx0, ny0, nw0, nh0
            ratio = (position_ms - t0) / (t1 - t0)
            return (
                nx0 + (nx1 - nx0) * ratio,
                ny0 + (ny1 - ny0) * ratio,
                nw0 + (nw1 - nw0) * ratio,
                nh0 + (nh1 - nh0) * ratio,
            )

    item = ordered[-1]
    return item[1], item[2], item[3], item[4]


class TimeRangeNotReadyError(ValueError):
    """时间段模式尚未设置完整入出点。"""


def compute_region_time_range(
    playhead_ms: int,
    duration_ms: int,
    mode: str,
    *,
    mark_in_ms: int | None = None,
    mark_out_ms: int | None = None,
) -> tuple[int, int]:
    """按打码模式计算时间区间。"""
    duration_ms = max(1, duration_ms)
    playhead_ms = max(0, min(duration_ms, playhead_ms))

    if mode == MODE_TIME_RANGE:
        if mark_in_ms is None or mark_out_ms is None:
            raise TimeRangeNotReadyError("请先设置入点和出点")
        start = max(0, min(mark_in_ms, mark_out_ms))
        end = min(duration_ms, max(mark_in_ms, mark_out_ms))
        if end <= start:
            end = min(duration_ms, start + 34)
        return start, end

    if mode == MODE_TRACKING:
        return playhead_ms, duration_ms

    frame_ms = 34
    return playhead_ms, min(duration_ms, playhead_ms + frame_ms)


@dataclass
class EpisodeMaskState:
    video_path: str
    regions: list[MaskRegion] = field(default_factory=list)
