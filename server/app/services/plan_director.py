"""服务端策划引擎（提示词与 LLM 调用仅存在于服务端）。"""

from __future__ import annotations

import json
import queue
import re
import time
from datetime import datetime
from typing import Any, Callable

import httpx
from fuzzywuzzy import fuzz, process

MIN_DURATION_SECONDS = 150
DEFAULT_MAX_DURATION_SECONDS = 720
MIN_MAX_DURATION_SECONDS = 300
MAX_MAX_DURATION_SECONDS = 900
ABS_MIN_DURATION_SECONDS = 120  # 短片最短下限
SEARCH_EPISODES = 15
MAX_TARGET_CLIPS_COUNT = 20
DEFAULT_TARGET_CLIPS_COUNT = 15
MIN_TARGET_CLIPS_COUNT = 5
# 兼容：短片/长片客户端仍限 15；混合可达 20
MAX_SHORT_LONG_CLIPS_COUNT = 15
DEFAULT_GLOBAL_SPEED = 1.15
MIN_GLOBAL_SPEED = 1.0
MAX_GLOBAL_SPEED = 3.0
GROUP_A_RATIO_NUM = 6  # 默认 A:B = 6:9
GROUP_A_BUFFER = 2
GROUP_B_BUFFER = 3
GROUP_U_BUFFER = 10
MAX_GROUP_LOOPS = 14
MAX_OUTPUT_TOKENS = 7000
# 切点台词模糊匹配阈值（略放宽，减少「台词对不上」导致条数不足）
CUT_TEXT_MATCH_MIN_SCORE = 50
# 切入点相对目标台词句首的前置缓冲（秒）；短片实际偏好窗中段
START_LEAD_IN_SECONDS = 0.9
# 短片：上一句 end → 本句 start 的原始空隙下限（含字幕消隐）
MIN_START_GAP_SECONDS = 1.1
# 短片：起点须至少早于 ASR 句首这么多秒，避免贴着/落入对白
MIN_BEFORE_SPEECH_SECONDS = 0.3
# 短片：上一句结束后再空出的字幕/余韵缓冲（不得贴 prev_end 起切）
POST_UTTERANCE_PAD_SECONDS = 0.3
# 切点尾垫：台词结束后保留的余韵（旧 0.3 → 0.5，避免尾音/混响被切）
POST_CUT_PAD_SECONDS = 0.5
# 模型引用台词可能横跨多条 ASR 分段：向后拼接检查的最大段数 / 完整包含阈值
CUT_SPAN_MAX_EXTRA = 3
CUT_SPAN_MIN_SCORE = 85
# 短片：同一开场起点最多占用目标条数的比例（2/5）
SAME_SHORT_START_RATIO_NUM = 2
SAME_SHORT_START_RATIO_DEN = 5

# 兼容旧引用
TARGET_CLIPS_COUNT = DEFAULT_TARGET_CLIPS_COUNT
MAX_DURATION_SECONDS = DEFAULT_MAX_DURATION_SECONDS
GROUP_A_COUNT = GROUP_A_RATIO_NUM

ProgressCallback = Callable[[dict[str, Any]], None]


def clamp_clip_count(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = DEFAULT_TARGET_CLIPS_COUNT
    return max(MIN_TARGET_CLIPS_COUNT, min(MAX_TARGET_CLIPS_COUNT, n))


def clamp_max_duration_seconds(value: Any) -> int:
    """长片默认 clamp（300~900）；兼容旧调用。"""
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        n = DEFAULT_MAX_DURATION_SECONDS
    return max(MIN_MAX_DURATION_SECONDS, min(MAX_MAX_DURATION_SECONDS, n))


def clamp_plan_duration_seconds(value: Any, *, default: int) -> int:
    """策划请求时长：允许短片 120s 起，最高 900s。"""
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        n = default
    return max(ABS_MIN_DURATION_SECONDS, min(MAX_MAX_DURATION_SECONDS, n))


def clamp_global_speed(value: Any) -> float:
    """成片倍速 1.0~3.0；缺省/非法回落 1.15。"""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return DEFAULT_GLOBAL_SPEED
    if n != n:
        return DEFAULT_GLOBAL_SPEED
    return max(MIN_GLOBAL_SPEED, min(MAX_GLOBAL_SPEED, round(n, 2)))


def split_ab_counts(total: int) -> tuple[int, int]:
    """按默认 6:9 比例分配；总条数≥2 时保证 A/B 至少各 1。"""
    total = clamp_clip_count(total)
    if total <= 1:
        return total, 0
    a = int(round(total * GROUP_A_RATIO_NUM / DEFAULT_TARGET_CLIPS_COUNT))
    a = min(max(a, 1), total - 1)
    return a, total - a


def max_same_short_start(target_count: int) -> int:
    """同一开场最多占用目标条数的 2/5（至少 1）。"""
    try:
        n = int(target_count)
    except (TypeError, ValueError):
        n = DEFAULT_TARGET_CLIPS_COUNT
    n = max(1, n)
    return max(1, (n * SAME_SHORT_START_RATIO_NUM) // SAME_SHORT_START_RATIO_DEN)


def _parse_clips_response(raw_res: str) -> list:
    return _parse_plan_json(raw_res).get("clips", [])


def _parse_plan_json(raw_res: str) -> dict:
    clean_res = raw_res.strip()
    if clean_res.startswith("```json"):
        clean_res = clean_res.split("```json")[1].split("```")[0].strip()
    elif clean_res.startswith("```"):
        clean_res = clean_res.split("```")[1].split("```")[0].strip()
    clean_res = re.sub(r"\n", " ", clean_res)
    data = json.loads(clean_res)
    return data if isinstance(data, dict) else {}


def _parse_short_starts_ends(raw_res: str) -> tuple[list[dict], list[dict]]:
    """解析短片 starts/ends；若仅有旧版 clips 则拆成两端候选。"""
    data = _parse_plan_json(raw_res)
    starts = data.get("starts") if isinstance(data.get("starts"), list) else []
    ends = data.get("ends") if isinstance(data.get("ends"), list) else []
    clips = data.get("clips") if isinstance(data.get("clips"), list) else []
    if (not starts or not ends) and clips:
        if not starts:
            starts = [
                {
                    "se": c.get("se") or c.get("start_episode"),
                    "st": c.get("st", c.get("start_time", 0)),
                }
                for c in clips
                if isinstance(c, dict)
            ]
        if not ends:
            ends = [
                {
                    "le": c.get("le") or c.get("cut_text_source_file"),
                    "ct": c.get("ct") or c.get("cut_text", ""),
                    "hook": c.get("hook") or c.get("hk") or "点击查看大结局",
                }
                for c in clips
                if isinstance(c, dict)
            ]
    return starts, ends


def _compute_clip_duration(s_idx, l_idx, start_time, cut_point, ordered_files, episode_end_times):
    if s_idx > l_idx:
        return 0
    if s_idx == l_idx:
        return max(0, cut_point - start_time)
    phys_end = cut_point - POST_CUT_PAD_SECONDS
    first_ep = ordered_files[s_idx]
    duration = max(0, episode_end_times.get(first_ep, 0) - start_time)
    for x in range(s_idx + 1, l_idx):
        duration += episode_end_times.get(ordered_files[x], 0)
    duration += phys_end
    return duration


def _parse_clip_fields(item: dict) -> tuple[str | None, str | None, float, str, str]:
    s_ep = item.get("se") or item.get("start_episode")
    l_ep = item.get("le") or item.get("cut_text_source_file")
    start_time = item.get("st", item.get("start_time", 0))
    cut_text = item.get("ct") or item.get("cut_text", "")
    hook = item.get("hook") or item.get("hk") or "点击查看大结局"
    return s_ep, l_ep, start_time, cut_text, hook


def _find_cut_index(steps, target_text, texts=None):
    if not target_text:
        return -1
    if texts is None:
        texts = [s["text"] for s in steps]
    best = process.extractOne(target_text, texts)
    if best and best[1] >= CUT_TEXT_MATCH_MIN_SCORE:
        for i, s in enumerate(steps):
            if s["text"] == best[0]:
                return i
    return -1


def _resolve_cut_span(
    steps: list[dict],
    c_idx: int,
    cut_text: str,
    *,
    step_texts: list[str] | None = None,
) -> int:
    """模型引用的台词可能横跨多条 ASR 分段（ASR 常把一句话拆成两段）：
    从 c_idx 向后拼接同集连续分段，返回引用完整覆盖到的最后一段索引；
    未覆盖更多段则原样返回 c_idx（保守回退，不连续引用不跨段）。"""
    if not cut_text or c_idx < 0 or c_idx >= len(steps):
        return c_idx
    if step_texts is None:
        step_texts = [str(s.get("text") or "") for s in steps]
    src = steps[c_idx].get("source_file")
    combined = str(step_texts[c_idx] or "")
    last = c_idx
    for k in range(1, CUT_SPAN_MAX_EXTRA + 1):
        j = c_idx + k
        if j >= len(steps) or steps[j].get("source_file") != src:
            break
        combined += str(step_texts[j] or "")
        # 长度接近 + 引用完整包含于拼接文本 → 句子延续到第 j 段；
        # 仅凭 partial_ratio 不够：短段文本必然是长引用的子串（=100 分）
        if (
            len(combined) >= len(cut_text) - 1
            and fuzz.partial_ratio(cut_text, combined) >= CUT_SPAN_MIN_SCORE
        ):
            last = j
            break
    return last


def _step_bounds(step: dict, *, prev_end: float = 0.0) -> tuple[float, float]:
    """返回台词起止秒；缺 start 时用上一句 end 兜底。"""
    try:
        end = float(step.get("end") or 0)
    except (TypeError, ValueError):
        end = 0.0
    raw_start = step.get("start")
    if raw_start is None:
        start = prev_end
    else:
        try:
            start = float(raw_start)
        except (TypeError, ValueError):
            start = prev_end
    if start < 0:
        start = 0.0
    if end < start:
        end = start
    return start, end


def _episode_utterances(
    steps: list[dict], source_file: str
) -> list[tuple[float, float]]:
    ep_steps: list[tuple[float, float]] = []
    prev_end = 0.0
    for s in steps:
        if s.get("source_file") != source_file:
            continue
        start, end = _step_bounds(s, prev_end=prev_end)
        ep_steps.append((start, end))
        prev_end = end
    return ep_steps


def _target_utterance_index(ep_steps: list[tuple[float, float]], t: float) -> int:
    if not ep_steps:
        return 0
    first_start = ep_steps[0][0]
    if t <= first_start:
        return 0
    target_idx = len(ep_steps) - 1
    for i, (start, end) in enumerate(ep_steps):
        if start <= t < end:
            return i
        if t < start:
            return i
    return target_idx


def _cut_point_after(steps: list[dict], c_idx: int) -> float:
    """切点 = 该句结束 + 尾垫；下一句更早开始时钳制到其句首前。"""
    phys_end = float(steps[c_idx].get("end") or 0)
    cut = phys_end + POST_CUT_PAD_SECONDS
    for start, _end in _episode_utterances(steps, steps[c_idx].get("source_file")):
        if start > phys_end + 1e-6:
            clamped = start - MIN_BEFORE_SPEECH_SECONDS
            if clamped < phys_end:
                # ASR 重叠兜底：钳制点已落回本句，只保留最小尾垫
                cut = phys_end + 0.1
            else:
                cut = min(cut, clamped)
            break
    return round(cut, 3)


def _short_start_windows(
    steps: list[dict],
    source_file: str,
    start_time: float,
    *,
    lead_in_seconds: float,
    min_gap_seconds: float,
    min_before_speech: float = MIN_BEFORE_SPEECH_SECONDS,
    post_utterance_pad: float = POST_UTTERANCE_PAD_SECONDS,
) -> list[tuple[float, float, float]]:
    """短片可用切入窗口列表：(floor, preferred, latest)。

    floor = 上一句 end + 字幕消隐垫，避免贴着上句字幕起切；
    preferred 取干净窗中段（略偏下一句前）；latest 早于本句 ASR 句首。
    """
    try:
        t = float(start_time)
    except (TypeError, ValueError):
        t = 0.0
    if t < 0:
        t = 0.0

    lead_in = max(0.0, float(lead_in_seconds))
    min_gap = max(0.0, float(min_gap_seconds))
    min_before = max(0.0, float(min_before_speech))
    post_pad = max(0.0, float(post_utterance_pad))

    ep_steps = _episode_utterances(steps, source_file)
    if not ep_steps:
        return []

    target_idx = _target_utterance_index(ep_steps, t)
    windows: list[tuple[float, float, float]] = []
    for idx in range(target_idx, len(ep_steps)):
        utter_start = ep_steps[idx][0]
        prev_end = ep_steps[idx - 1][1] if idx > 0 else 0.0
        if prev_end < 0:
            prev_end = 0.0
        # ASR 重叠：上一句 end 已进入本句，句前无静音
        if prev_end >= utter_start:
            continue
        raw_gap = utter_start - prev_end
        if raw_gap < min_gap:
            continue
        # 有上一句时抬高 floor，避开上句字幕残留
        floor = (prev_end + post_pad) if idx > 0 else 0.0
        latest = utter_start - min_before
        if latest < floor:
            continue
        # 窗中段略偏后（更远离上句结束）；也可落在 lead_in 点（若仍在窗内）
        span = latest - floor
        preferred = floor + span * 0.55
        lead_pref = utter_start - lead_in
        if floor <= lead_pref <= latest:
            # 两者取更靠后的，进一步离开 prev_end
            preferred = max(preferred, lead_pref)
        preferred = min(max(floor, preferred), latest)
        windows.append((floor, preferred, latest))
    return windows


def _snap_start_to_utterance(
    steps: list[dict],
    source_file: str,
    start_time: float,
    *,
    lead_in_seconds: float | None = None,
    min_gap_seconds: float = 0.0,
) -> float | None:
    """将起始秒吸附到同集台词附近，避免从对白中间起切。

    先定位目标句（句中→该句；空隙→下一句），再：
    实际起点 = max(上一句结束, 本句 start - lead_in, 0)

    min_gap_seconds > 0 时（短片）：要求句前静音足够，且起点严格早于句首；
    空隙不够则向后找下一句，仍没有则返回 None。
    """
    try:
        t = float(start_time)
    except (TypeError, ValueError):
        t = 0.0
    if t < 0:
        t = 0.0

    if lead_in_seconds is None:
        lead_in = START_LEAD_IN_SECONDS
    else:
        try:
            lead_in = max(0.0, float(lead_in_seconds))
        except (TypeError, ValueError):
            lead_in = START_LEAD_IN_SECONDS

    try:
        min_gap = max(0.0, float(min_gap_seconds))
    except (TypeError, ValueError):
        min_gap = 0.0

    if min_gap > 0:
        windows = _short_start_windows(
            steps,
            source_file,
            t,
            lead_in_seconds=lead_in,
            min_gap_seconds=min_gap,
        )
        if not windows:
            return None
        return round(windows[0][1], 3)

    ep_steps = _episode_utterances(steps, source_file)
    if not ep_steps:
        return round(t, 3)

    target_idx = _target_utterance_index(ep_steps, t)
    utter_start = ep_steps[target_idx][0]
    floor = ep_steps[target_idx - 1][1] if target_idx > 0 else 0.0
    lead = max(0.0, utter_start - lead_in)
    return round(max(floor, lead, 0.0), 3)


def _pick_short_start_for_duration(
    steps: list[dict],
    source_file: str,
    start_time: float,
    *,
    s_idx: int,
    l_idx: int,
    cut_point: float,
    ordered_files: list[str],
    episode_end_times: dict,
    min_dur: float,
    max_dur: float,
    lead_in_seconds: float = START_LEAD_IN_SECONDS,
    min_gap_seconds: float = MIN_START_GAP_SECONDS,
) -> float | None:
    """短片：在多个句前窗口内选起点，必要时微调使时长落在区间内。"""

    def _dur(st: float) -> float:
        return _compute_clip_duration(
            s_idx, l_idx, st, cut_point, ordered_files, episode_end_times
        )

    windows = _short_start_windows(
        steps,
        source_file,
        start_time,
        lead_in_seconds=lead_in_seconds,
        min_gap_seconds=min_gap_seconds,
    )
    for floor, preferred, latest in windows:
        if cut_point <= floor:
            continue
        # 优先 preferred；时长不合则在 [floor, latest] 内二分
        for trial in (preferred, floor, latest):
            if cut_point <= trial:
                continue
            d = _dur(trial)
            if min_dur <= d <= max_dur:
                return round(trial, 3)

        d_early = _dur(floor)
        d_late = _dur(min(latest, cut_point - 0.05)) if cut_point > floor else 0.0
        # 起点越晚时长越短（同集/首集段）
        if d_early < min_dur:
            continue
        if d_late > max_dur:
            continue

        lo, hi = floor, min(latest, cut_point - 0.05)
        if hi <= lo:
            continue
        best: float | None = None
        for _ in range(24):
            mid = (lo + hi) / 2
            d = _dur(mid)
            if d > max_dur:
                lo = mid
            elif d < min_dur:
                hi = mid
            else:
                best = mid
                # 尽量靠近 preferred（窗中段），避免贴 floor（上句字幕区）
                if mid < preferred:
                    lo = mid
                else:
                    hi = mid
        if best is not None and min_dur <= _dur(best) <= max_dur:
            return round(best, 3)
    return None


def _asr_clean_start_hints(
    steps: list[dict],
    ordered_files: list[str],
    *,
    limit: int = 24,
) -> list[dict]:
    """从 ASR 句缝枚举干净开场候选，补足模型 starts 不足。"""
    hints: list[dict] = []
    seen: set[str] = set()
    for ep in ordered_files[:SEARCH_EPISODES]:
        ep_steps = _episode_utterances(steps, ep)
        for i, (utter_start, _utter_end) in enumerate(ep_steps):
            prev_end = ep_steps[i - 1][1] if i > 0 else 0.0
            probe = (prev_end + utter_start) / 2.0 if i > 0 else max(0.0, utter_start - 0.5)
            windows = _short_start_windows(
                steps,
                ep,
                probe,
                lead_in_seconds=START_LEAD_IN_SECONDS,
                min_gap_seconds=MIN_START_GAP_SECONDS,
            )
            if not windows:
                continue
            st = round(windows[0][1], 3)
            key = f"{ep}_{round(st, 1)}"
            if key in seen:
                continue
            seen.add(key)
            hints.append({"se": ep, "st": st})
            if len(hints) >= limit:
                return hints
    return hints


def _normalize_short_ends(
    ends_raw: list[dict],
    *,
    steps: list[dict],
    step_texts: list[str],
    ordered_files: list[str],
) -> list[dict]:
    """校验切点台词，返回可用 end 候选。"""
    out: list[dict] = []
    seen_fp: set[str] = set()
    for item in ends_raw:
        if not isinstance(item, dict):
            continue
        l_ep = item.get("le") or item.get("cut_text_source_file")
        cut_text = item.get("ct") or item.get("cut_text", "")
        hook = item.get("hook") or item.get("hk") or "点击查看大结局"
        if l_ep not in ordered_files or not cut_text:
            continue
        c_idx = _find_cut_index(steps, cut_text, step_texts)
        if c_idx == -1:
            continue
        if steps[c_idx].get("source_file") != l_ep:
            continue
        # 引用可能横跨多条 ASR 分段：末覆盖段才是句尾
        c_idx = _resolve_cut_span(steps, c_idx, cut_text, step_texts=step_texts)
        phys_end = float(steps[c_idx].get("end") or 0)
        fp = f"{l_ep}_{round(phys_end)}"
        if fp in seen_fp:
            continue
        seen_fp.add(fp)
        out.append(
            {
                "le": l_ep,
                "l_idx": ordered_files.index(l_ep),
                "phys_end": phys_end,
                "cut_point": _cut_point_after(steps, c_idx),
                "hook": hook,
                "ct": cut_text,
            }
        )
    return out


def _normalize_short_starts(
    starts_raw: list[dict],
    *,
    ordered_files: list[str],
) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for item in starts_raw:
        if not isinstance(item, dict):
            continue
        s_ep = item.get("se") or item.get("start_episode")
        if s_ep not in ordered_files:
            continue
        try:
            st = float(item.get("st", item.get("start_time", 0)) or 0)
        except (TypeError, ValueError):
            st = 0.0
        if st < 0:
            st = 0.0
        key = f"{s_ep}_{round(st, 1)}"
        if key in seen:
            continue
        seen.add(key)
        out.append({"se": s_ep, "s_idx": ordered_files.index(s_ep), "st": st})
    return out


def _compose_short_plans_from_starts_ends(
    *,
    starts_raw: list[dict],
    ends_raw: list[dict],
    steps: list[dict],
    step_texts: list[str],
    ordered_files: list[str],
    episode_end_times: dict,
    min_dur: float,
    max_dur: float,
    target_count: int,
    used_fingerprints: set[str],
    used_short_starts: dict[str, int],
    project_name: str,
    date_str: str,
    speed: float,
    supplement_asr_starts: bool = True,
    same_start_limit: int | None = None,
    group_type: str | None = None,
) -> list[dict]:
    """用开头×切点按时长组合方案（短片 U / 混合 A·B）。"""
    starts = _normalize_short_starts(starts_raw, ordered_files=ordered_files)
    if group_type == "A":
        starts = [s for s in starts if s["se"] == "1.mp4"]
    if supplement_asr_starts and len(starts) < max(6, target_count):
        asr_eps = (
            ["1.mp4"]
            if group_type == "A" and "1.mp4" in ordered_files
            else ordered_files
        )
        asr_hints = _asr_clean_start_hints(
            steps, asr_eps, limit=max(16, target_count * 2)
        )
        starts = _normalize_short_starts(
            [{"se": s["se"], "st": s["st"]} for s in starts]
            + asr_hints,
            ordered_files=ordered_files,
        )
        if group_type == "A":
            starts = [s for s in starts if s["se"] == "1.mp4"]
    ends = _normalize_short_ends(
        ends_raw,
        steps=steps,
        step_texts=step_texts,
        ordered_files=ordered_files,
    )
    if not starts or not ends:
        return []

    mid_dur = (min_dur + max_dur) / 2.0
    candidates: list[tuple[float, float, dict]] = []
    # 限制组合规模，避免 starts×ends 过大
    max_starts = min(len(starts), max(12, target_count * 2))
    max_ends = min(len(ends), max(16, target_count * 2))
    for start in starts[:max_starts]:
        for end in ends[:max_ends]:
            if start["s_idx"] > end["l_idx"]:
                continue
            if group_type == "B" and start["s_idx"] >= end["l_idx"]:
                continue
            if group_type == "A" and start["se"] != "1.mp4":
                continue
            snapped = _pick_short_start_for_duration(
                steps,
                start["se"],
                start["st"],
                s_idx=start["s_idx"],
                l_idx=end["l_idx"],
                cut_point=end["cut_point"],
                ordered_files=ordered_files,
                episode_end_times=episode_end_times,
                min_dur=min_dur,
                max_dur=max_dur,
            )
            if snapped is None:
                continue
            total_dur = _compute_clip_duration(
                start["s_idx"],
                end["l_idx"],
                snapped,
                end["cut_point"],
                ordered_files,
                episode_end_times,
            )
            if total_dur < min_dur or total_dur > max_dur:
                continue
            # 分越低越好：时长贴近中位 + 跨集略加分（多样性）
            score = abs(total_dur - mid_dur)
            if start["s_idx"] != end["l_idx"]:
                score -= 8.0
            candidates.append(
                (
                    score,
                    total_dur,
                    {
                        "se": start["se"],
                        "s_idx": start["s_idx"],
                        "st": snapped,
                        "le": end["le"],
                        "l_idx": end["l_idx"],
                        "phys_end": end["phys_end"],
                        "cut_point": end["cut_point"],
                        "hook": end["hook"],
                    },
                )
            )

    candidates.sort(key=lambda x: x[0])
    plans: list[dict] = []
    start_cap = (
        max(1, int(same_start_limit))
        if same_start_limit is not None
        else max_same_short_start(target_count)
    )
    for _score, _dur, item in candidates:
        fp = f"{item['se']}_{item['le']}_{round(item['phys_end'])}"
        start_key = f"{item['se']}_{round(float(item['st']), 1)}"
        if fp in used_fingerprints:
            continue
        if used_short_starts.get(start_key, 0) >= start_cap:
            continue
        used_fingerprints.add(fp)
        used_short_starts[start_key] = used_short_starts.get(start_key, 0) + 1
        plans.append(
            {
                "title": f"{project_name}-{date_str}-{len(plans) + 1:02d}",
                "project_name": project_name,
                "global_speed": speed,
                "files_config": {
                    "first_episode_cut_start": round(item["st"], 1),
                    "full_episodes": ordered_files[item["s_idx"] : item["l_idx"]],
                    "last_episode": item["le"],
                    "last_episode_cut_point": round(item["cut_point"], 2),
                },
                "hook": item["hook"],
            }
        )
        if len(plans) >= target_count:
            break
    return plans


def _compress_script(steps: list[dict], target_episodes: list[str]) -> str:
    """压缩剧本：带每句起止秒，便于模型选句首 st。"""
    parts: list[str] = []
    prev_by_ep: dict[str, float] = {}
    episode_set = set(target_episodes)
    for s in steps:
        src = s.get("source_file")
        if src not in episode_set:
            continue
        prev_end = prev_by_ep.get(src, 0.0)
        start, end = _step_bounds(s, prev_end=prev_end)
        prev_by_ep[src] = end
        text = str(s.get("text") or "")
        parts.append(f"\n[{src}]({start:.1f}-{end:.1f}){text}")
    return "".join(parts)


def _build_short_plan_prompt(
    *,
    count: int,
    min_duration_seconds: int,
    max_duration_seconds: int,
) -> str:
    """短片模式专用提示词（与长片完全独立，互不影响）。

    模型只给开头/切点候选；服务端按时长组合，以保证条数与开场质量。
    """
    start_n = max(8, count)
    end_n = max(12, count + 5)
    return (
        f"你是一个短剧广告投放导演。任务：为约 {count} 条短片提供开场与切点候选"
        f"（最终条数由服务端按时长 {min_duration_seconds}~{max_duration_seconds} 秒自动组合）。\n"
        "不要直接输出完整 clips；分别给出 starts 与 ends。\n"
        f"请给出约 {start_n} 个开场候选、约 {end_n} 个切点候选；"
        "开场与切点尽量分散到不同集/不同剧情节点。\n"
        "剧本条目格式为 [集名](起始秒-结束秒)台词。\n"
        "starts 规则：st 必须落在两句之间的干净空镜，"
        "须晚于上一句结束约 0.3 秒以上（避开上句字幕残留），"
        "且早于下一句起始秒，禁止从对白中间起切；se 为起始集。\n"
        "ends 规则：ct 必须逐字摘自 le 对应集剧本原文（8~15字），禁止改写/概括；"
        "hook 为悬念引流标题；切点彼此尽量不同。\n"
        '输出纯 JSON: {"starts":[{"se":"1.mp4","st":12.5}],'
        '"ends":[{"le":"6.mp4","ct":"台词原文","hook":"引流标题"}]}\n'
        "字段: se=起始集, st=起始秒(句前缓冲), le=结束集, ct=le集中台词(8~15字), hook=悬念引流标题"
    )


def _build_long_plan_prompt(
    *,
    count: int,
    min_duration_seconds: int,
    max_duration_seconds: int,
    group_type: str,
) -> str:
    """长片模式专用提示词（A/B 组规则；与短片完全独立）。

    与历史长片提示词一致：不要求 st 必须落在某句台词起始秒，
    只约束时长、A/B 范围、切点差异与 ct 原文摘录。
    """
    if group_type == "A":
        scope_rule = (
            "A组从第1集切入：可在第1集内剪一段（se与le均为1.mp4，"
            f"st到切点须达{min_duration_seconds}~{max_duration_seconds}秒），"
            "也可跨多集（le须晚于se）。"
        )
    else:
        # B 组（及兜底）
        scope_rule = "B组必须跨多集：le 须晚于 se，通常跨越 2 集及以上即可。"

    return (
        f"你是一个短剧广告投放导演。任务：策划 {count} 个高转化引流剪辑计划。\n"
        f"硬性要求：每条剪辑总时长必须在 {min_duration_seconds}~{max_duration_seconds} 秒之间。\n"
        f"{scope_rule}\n"
        "各方案切点须有明显差异，避免重复。"
        "ct 必须逐字摘自 le 对应集剧本原文（8~15字），禁止改写/概括。\n"
        '输出纯 JSON: {"clips":[{"se":"1.mp4","st":0,"le":"6.mp4","ct":"台词","hook":"引流标题"}]}\n'
        "字段: se=起始集, st=起始秒, le=结束集, ct=le集中台词(8~15字), hook=悬念引流标题"
    )


def _build_mixed_plan_prompt(
    *,
    count: int,
    min_duration_seconds: int,
    max_duration_seconds: int,
    group_type: str,
) -> str:
    """混合模式专用提示词（与短片/长片完全独立）。

    范围规则对齐长片 A/B；输出格式对齐短片 starts/ends，由服务端按时长组合。
    """
    start_n = max(8, count)
    end_n = max(12, count + 5)
    if group_type == "A":
        scope_rule = (
            "A组从第1集切入：开场 se 必须为 1.mp4；"
            "可在第1集内结束（le 亦为 1.mp4），也可跨多集（le 须晚于 se）。"
        )
    else:
        scope_rule = (
            "B组必须跨多集：开场 se 与切点 le 须不同集，且 le 对应集晚于 se，"
            "通常跨越 2 集及以上。"
        )
    return (
        f"你是一个短剧广告投放导演。任务：为混合模式约 {count} 条剪辑"
        f"（本组）提供开场与切点候选；最终条数由服务端按时长 "
        f"{min_duration_seconds}~{max_duration_seconds} 秒自动组合。\n"
        f"{scope_rule}\n"
        "不要直接输出完整 clips；分别给出 starts 与 ends。\n"
        f"请给出约 {start_n} 个开场候选、约 {end_n} 个切点候选；"
        "开场与切点尽量分散、彼此有明显差异。\n"
        "剧本条目格式为 [集名](起始秒-结束秒)台词。\n"
        "starts 规则：st 必须落在两句之间的干净空镜，"
        "须晚于上一句结束约 0.3 秒以上（避开上句字幕残留），"
        "且早于下一句起始秒，禁止从对白中间起切；se 为起始集。\n"
        "ends 规则：ct 必须逐字摘自 le 对应集剧本原文（8~15字），禁止改写/概括；"
        "hook 为悬念引流标题；切点彼此尽量不同。\n"
        '输出纯 JSON: {"starts":[{"se":"1.mp4","st":12.5}],'
        '"ends":[{"le":"6.mp4","ct":"台词原文","hook":"引流标题"}]}\n'
        "字段: se=起始集, st=起始秒(句前缓冲), le=结束集, ct=le集中台词(8~15字), hook=悬念引流标题"
    )


def _system_prompt_for_group(
    *,
    group_type: str,
    count: int,
    min_duration_seconds: int,
    max_duration_seconds: int,
    plan_mode: str = "long",
) -> str:
    """按策划模式与组类型选择提示词。"""
    mode = str(plan_mode or "").strip().lower()
    if mode == "short" or group_type == "U":
        return _build_short_plan_prompt(
            count=count,
            min_duration_seconds=min_duration_seconds,
            max_duration_seconds=max_duration_seconds,
        )
    if mode == "mixed":
        return _build_mixed_plan_prompt(
            count=count,
            min_duration_seconds=min_duration_seconds,
            max_duration_seconds=max_duration_seconds,
            group_type=group_type,
        )
    return _build_long_plan_prompt(
        count=count,
        min_duration_seconds=min_duration_seconds,
        max_duration_seconds=max_duration_seconds,
        group_type=group_type,
    )


def _call_deepseek(
    *,
    api_url: str,
    model_name: str,
    compressed_script: str,
    count: int,
    group_type: str,
    key_pool: queue.Queue,
    min_duration_seconds: int,
    max_duration_seconds: int,
    plan_mode: str = "long",
    provider: str = "deepseek",
    llm_session_id: str = "",
) -> tuple[str | None, float, str | None]:
    api_key = key_pool.get()
    t0 = time.perf_counter()
    try:
        system_prompt = _system_prompt_for_group(
            group_type=group_type,
            count=count,
            min_duration_seconds=min_duration_seconds,
            max_duration_seconds=max_duration_seconds,
            plan_mode=plan_mode,
        )
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        provider_key = str(provider or "").strip().lower()
        # OpenCode Go 部分模型需要会话亲和头
        if provider_key == "opencode_go" and llm_session_id:
            headers["x-opencode-session"] = str(llm_session_id)
        # 小米 MiMo 官方文档用 api-key 头（同时保留 Bearer 以兼容网关）
        if provider_key == "xiaomi":
            headers["api-key"] = api_key
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"剧本库：{compressed_script}"},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": MAX_OUTPUT_TOKENS,
            # 全通道关闭 thinking，避免推理模式拖慢策划
            "thinking": {"type": "disabled"},
        }
        with httpx.Client(timeout=httpx.Timeout(30.0, read=180.0)) as client:
            resp = client.post(api_url, headers=headers, json=payload)
        elapsed = time.perf_counter() - t0

        if resp.status_code != 200:
            return None, elapsed, f"HTTP {resp.status_code}: {resp.text[:300]}"

        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content")
        if content and str(content).strip():
            return str(content).strip(), elapsed, None

        finish_reason = choice.get("finish_reason", "unknown")
        return None, elapsed, f"响应内容为空 (finish_reason={finish_reason})"
    except Exception as exc:
        return None, time.perf_counter() - t0, str(exc)
    finally:
        key_pool.put(api_key)


def run_plan(
    *,
    project_name: str,
    steps: list[dict],
    ordered_files: list[str],
    api_keys_raw: str,
    api_url: str,
    model_name: str,
    progress_callback: ProgressCallback | None = None,
    target_clips_count: int | None = None,
    max_duration_seconds: int | None = None,
    min_duration_seconds: int | None = None,
    split_ab: bool | None = None,
    global_speed: float | None = None,
    plan_mode: str | None = None,
    provider: str = "deepseek",
    llm_session_id: str = "",
) -> list[dict]:
    if not api_keys_raw.strip():
        raise ValueError("服务端未配置策划 API 密钥")
    llm_provider = str(provider or "deepseek").strip().lower() or "deepseek"
    session_id = str(llm_session_id or "").strip()

    use_ab = True if split_ab is None else bool(split_ab)
    mode = str(plan_mode or "").strip().lower()
    if mode not in {"short", "long", "mixed"}:
        # 兼容旧客户端：无 plan_mode 时由 split_ab 推断
        mode = "short" if not use_ab else "long"
    use_pair = mode in {"short", "mixed"}

    speed = (
        clamp_global_speed(global_speed)
        if global_speed is not None
        else DEFAULT_GLOBAL_SPEED
    )

    target_total = (
        clamp_clip_count(target_clips_count)
        if target_clips_count is not None
        else DEFAULT_TARGET_CLIPS_COUNT
    )
    default_min = (
        ABS_MIN_DURATION_SECONDS if mode in {"short", "mixed"} else MIN_DURATION_SECONDS
    )
    if min_duration_seconds is not None:
        min_dur = clamp_plan_duration_seconds(
            min_duration_seconds, default=default_min
        )
    else:
        min_dur = default_min
    if max_duration_seconds is not None:
        max_dur = clamp_plan_duration_seconds(
            max_duration_seconds, default=DEFAULT_MAX_DURATION_SECONDS
        )
    else:
        max_dur = DEFAULT_MAX_DURATION_SECONDS
    if max_dur <= min_dur:
        max_dur = min(MAX_MAX_DURATION_SECONDS, min_dur + 30)

    if mode == "short":
        task_groups = [("U", target_total)]
    else:
        group_a_count, group_b_count = split_ab_counts(target_total)
        task_groups = [("A", group_a_count), ("B", group_b_count)]

    target_episodes = ordered_files[:SEARCH_EPISODES]
    compressed_script = _compress_script(steps, target_episodes)

    episode_end_times: dict[str, float] = {}
    for s in steps:
        src = s.get("source_file")
        if src:
            episode_end_times[src] = max(episode_end_times.get(src, 0), s.get("end", 0))

    api_keys = [k.strip() for k in api_keys_raw.split(",") if k.strip()]
    key_pool: queue.Queue = queue.Queue()
    for key in api_keys:
        key_pool.put(key)

    final_plans: list[dict] = []
    used_fingerprints: set[str] = set()
    used_short_starts: dict[str, int] = {}
    date_str = datetime.now().strftime("%m%d")
    step_texts = [s.get("text", "") for s in steps]

    def _emit(detail: str = "") -> None:
        if progress_callback:
            progress_callback(
                {
                    "phase": "plan",
                    "current": len(final_plans),
                    "total": target_total,
                    "detail": detail,
                }
            )

    _emit("准备剧本…")

    for g_type, total_count in task_groups:
        if total_count <= 0:
            continue
        completed_in_group = 0
        loop_count = 0
        if g_type == "A":
            group_buffer = GROUP_A_BUFFER
        elif g_type == "B":
            group_buffer = GROUP_B_BUFFER
        else:
            group_buffer = GROUP_U_BUFFER

        consecutive_empty = 0
        while completed_in_group < total_count and loop_count < MAX_GROUP_LOOPS:
            loop_count += 1
            remaining = total_count - completed_in_group
            # 通过率低时加大超量请求，尽量一次多出候选
            extra = group_buffer + (group_buffer if consecutive_empty >= 1 else 0)
            request_count = remaining + extra
            if g_type == "U":
                _emit(f"策划 {completed_in_group}/{total_count} · 正在生成方案…")
            else:
                _emit(f"{g_type}组 {completed_in_group}/{total_count} · 正在生成方案…")

            raw_res, _elapsed, api_error = _call_deepseek(
                api_url=api_url,
                model_name=model_name,
                compressed_script=compressed_script,
                count=request_count,
                group_type=g_type,
                key_pool=key_pool,
                min_duration_seconds=min_dur,
                max_duration_seconds=max_dur,
                plan_mode=mode,
                provider=llm_provider,
                llm_session_id=session_id,
            )
            if api_error or not raw_res:
                consecutive_empty += 1
                continue

            try:
                if use_pair:
                    starts_raw, ends_raw = _parse_short_starts_ends(raw_res)
                    # 切点必须来自模型；开场不足时可由 ASR 句缝补
                    if not ends_raw:
                        consecutive_empty += 1
                        continue
                    need = total_count - completed_in_group
                    paired = _compose_short_plans_from_starts_ends(
                        starts_raw=starts_raw,
                        ends_raw=ends_raw,
                        steps=steps,
                        step_texts=step_texts,
                        ordered_files=ordered_files,
                        episode_end_times=episode_end_times,
                        min_dur=min_dur,
                        max_dur=max_dur,
                        target_count=need,
                        used_fingerprints=used_fingerprints,
                        used_short_starts=used_short_starts,
                        project_name=project_name,
                        date_str=date_str,
                        speed=speed,
                        supplement_asr_starts=True,
                        same_start_limit=max_same_short_start(target_total),
                        group_type=None if g_type == "U" else g_type,
                    )
                    # 修正标题序号（组合函数内从 1 起，需接上已有条数）
                    for plan in paired:
                        final_plans.append(plan)
                        plan["title"] = (
                            f"{project_name}-{date_str}-{len(final_plans):02d}"
                        )
                    batch_ok = len(paired)
                    if batch_ok <= 0:
                        consecutive_empty += 1
                    else:
                        consecutive_empty = 0
                    completed_in_group += batch_ok
                    if g_type == "U":
                        _emit(f"已通过 {len(final_plans)}/{target_total} 条")
                    else:
                        _emit(
                            f"{g_type}组 · 已通过 {len(final_plans)}/{target_total} 条"
                        )
                    if len(final_plans) >= target_total:
                        break
                    continue

                clips = _parse_clips_response(raw_res)
                if not clips:
                    consecutive_empty += 1
                    continue

                batch_ok = 0
                for item in clips:
                    s_ep, l_ep, start_time, cut_text, hook = _parse_clip_fields(item)
                    if not isinstance(start_time, (int, float)) or start_time < 0:
                        start_time = 0

                    if g_type == "A":
                        s_ep = "1.mp4"
                    if s_ep not in ordered_files or l_ep not in ordered_files:
                        continue

                    s_idx = ordered_files.index(s_ep)
                    l_idx = ordered_files.index(l_ep)
                    if s_idx > l_idx:
                        continue
                    if g_type == "B" and s_idx == l_idx:
                        continue

                    c_idx = _find_cut_index(steps, cut_text, step_texts)
                    if c_idx == -1:
                        continue
                    if steps[c_idx].get("source_file") != l_ep:
                        continue

                    # 引用可能横跨多条 ASR 分段：末覆盖段才是句尾
                    c_idx = _resolve_cut_span(
                        steps, c_idx, cut_text, step_texts=step_texts
                    )
                    phys_end = steps[c_idx].get("end", 0)
                    cut_point = _cut_point_after(steps, c_idx)
                    if cut_point <= start_time:
                        continue

                    total_dur = _compute_clip_duration(
                        s_idx, l_idx, start_time, cut_point, ordered_files, episode_end_times
                    )
                    if total_dur < min_dur or total_dur > max_dur:
                        continue

                    fp = f"{s_ep}_{l_ep}_{round(phys_end)}_{round(start_time)}"
                    if fp in used_fingerprints:
                        continue
                    used_fingerprints.add(fp)

                    final_plans.append(
                        {
                            "title": f"{project_name}-{date_str}-{len(final_plans) + 1:02d}",
                            "project_name": project_name,
                            "global_speed": speed,
                            "files_config": {
                                "first_episode_cut_start": round(start_time, 1),
                                "full_episodes": ordered_files[s_idx:l_idx],
                                "last_episode": l_ep,
                                "last_episode_cut_point": round(cut_point, 2),
                            },
                            "hook": hook,
                        }
                    )
                    batch_ok += 1
                    if len(final_plans) >= target_total:
                        break

                if batch_ok <= 0:
                    consecutive_empty += 1
                else:
                    consecutive_empty = 0
                completed_in_group += batch_ok
                _emit(f"{g_type}组 · 已通过 {len(final_plans)}/{target_total} 条")
                if len(final_plans) >= target_total:
                    break
            except Exception:
                consecutive_empty += 1
                continue
        if len(final_plans) >= target_total:
            break

    if not final_plans:
        raise RuntimeError(f"《{project_name}》策划未产出有效方案")

    seen: set[str] = set()
    unique_plans: list[dict] = []
    for plan in final_plans:
        cfg_key = json.dumps(plan["files_config"], sort_keys=True)
        if cfg_key in seen:
            continue
        seen.add(cfg_key)
        unique_plans.append(plan)
        if len(unique_plans) >= target_total:
            break

    # 重编号标题，避免中途跳号
    for i, plan in enumerate(unique_plans, start=1):
        plan["title"] = f"{project_name}-{date_str}-{i:02d}"

    if len(unique_plans) < target_total:
        # 仍返回已通过方案，但带不足标记供服务端进度/客户端提示
        if progress_callback:
            progress_callback(
                {
                    "phase": "plan",
                    "current": len(unique_plans),
                    "total": target_total,
                    "detail": (
                        f"仅通过 {len(unique_plans)}/{target_total} 条"
                        "（开头/切点组合或台词匹配不足）"
                    ),
                    "underfilled": True,
                }
            )
    return unique_plans
