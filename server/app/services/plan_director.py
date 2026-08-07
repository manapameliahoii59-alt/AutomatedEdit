"""服务端策划引擎（提示词与 LLM 调用仅存在于服务端）。"""

from __future__ import annotations

import json
import queue
import re
import time
from datetime import datetime
from typing import Any, Callable

import httpx
from fuzzywuzzy import process

MIN_DURATION_SECONDS = 150
DEFAULT_MAX_DURATION_SECONDS = 720
MIN_MAX_DURATION_SECONDS = 300
MAX_MAX_DURATION_SECONDS = 900
ABS_MIN_DURATION_SECONDS = 120  # 短片最短下限
SEARCH_EPISODES = 15
DEFAULT_TARGET_CLIPS_COUNT = 15
MIN_TARGET_CLIPS_COUNT = 5
MAX_TARGET_CLIPS_COUNT = 15
DEFAULT_GLOBAL_SPEED = 1.15
MIN_GLOBAL_SPEED = 1.0
MAX_GLOBAL_SPEED = 1.5
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
# 短片：同一开场起点最多共用几条（仍允许少量共用）
MAX_SAME_SHORT_START = 2

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
    """成片倍速 1.0~1.5；缺省/非法回落 1.15。"""
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


def _parse_clips_response(raw_res: str) -> list:
    clean_res = raw_res.strip()
    if clean_res.startswith("```json"):
        clean_res = clean_res.split("```json")[1].split("```")[0].strip()
    elif clean_res.startswith("```"):
        clean_res = clean_res.split("```")[1].split("```")[0].strip()
    clean_res = re.sub(r"\n", " ", clean_res)
    return json.loads(clean_res).get("clips", [])


def _compute_clip_duration(s_idx, l_idx, start_time, cut_point, ordered_files, episode_end_times):
    if s_idx > l_idx:
        return 0
    if s_idx == l_idx:
        return max(0, cut_point - start_time)
    phys_end = cut_point - 0.3
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
    """短片模式专用提示词（与长片完全独立，互不影响）。"""
    return (
        f"你是一个短剧广告投放导演。任务：策划 {count} 个短片引流剪辑计划。\n"
        f"硬性要求：每条剪辑总时长必须在 {min_duration_seconds}~{max_duration_seconds} 秒之间。\n"
        "可在单集内剪一段（se与le相同），也可跨多集（le须晚于se）；"
        "起始集不限。若单集时长不足最短秒数，必须跨多集。"
        "剧本条目格式为 [集名](起始秒-结束秒)台词；"
        "st 必须落在两句之间的干净空镜："
        "须晚于上一句结束约 0.3 秒以上（避开上句字幕残留），"
        "且早于下一句起始秒，禁止从对白中间起切。"
        "好的开场可少量共用，但不要大量片头挤在同一秒；切点 ct 与 hook 尽量有差异。\n"
        "ct 必须逐字摘自 le 对应集剧本原文（8~15字），禁止改写/概括。\n"
        '输出纯 JSON: {"clips":[{"se":"1.mp4","st":0,"le":"6.mp4","ct":"台词","hook":"引流标题"}]}\n'
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


def _system_prompt_for_group(
    *,
    group_type: str,
    count: int,
    min_duration_seconds: int,
    max_duration_seconds: int,
) -> str:
    """按组类型选择短片或长片提示词。U=短片；A/B=长片。"""
    if group_type == "U":
        return _build_short_plan_prompt(
            count=count,
            min_duration_seconds=min_duration_seconds,
            max_duration_seconds=max_duration_seconds,
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
) -> tuple[str | None, float, str | None]:
    api_key = key_pool.get()
    t0 = time.perf_counter()
    try:
        system_prompt = _system_prompt_for_group(
            group_type=group_type,
            count=count,
            min_duration_seconds=min_duration_seconds,
            max_duration_seconds=max_duration_seconds,
        )
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"剧本库：{compressed_script}"},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": MAX_OUTPUT_TOKENS,
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
) -> list[dict]:
    if not api_keys_raw.strip():
        raise ValueError("服务端未配置策划 API 密钥")

    use_ab = True if split_ab is None else bool(split_ab)
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
    default_min = MIN_DURATION_SECONDS if use_ab else ABS_MIN_DURATION_SECONDS
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

    if use_ab:
        group_a_count, group_b_count = split_ab_counts(target_total)
        task_groups = [("A", group_a_count), ("B", group_b_count)]
    else:
        task_groups = [("U", target_total)]

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
            )
            if api_error or not raw_res:
                consecutive_empty += 1
                continue

            try:
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

                    phys_end = steps[c_idx].get("end", 0)
                    cut_point = phys_end + 0.3

                    # 短片：在句前静音窗内选 st，并按时长微调；长片不改 st。
                    if g_type == "U":
                        snapped = _pick_short_start_for_duration(
                            steps,
                            s_ep,
                            start_time,
                            s_idx=s_idx,
                            l_idx=l_idx,
                            cut_point=cut_point,
                            ordered_files=ordered_files,
                            episode_end_times=episode_end_times,
                            min_dur=min_dur,
                            max_dur=max_dur,
                        )
                        if snapped is None:
                            continue
                        start_time = snapped
                    elif cut_point <= start_time:
                        continue

                    total_dur = _compute_clip_duration(
                        s_idx, l_idx, start_time, cut_point, ordered_files, episode_end_times
                    )
                    if total_dur < min_dur or total_dur > max_dur:
                        continue

                    # 短片：切点去重；同一开场 st 最多共用 MAX_SAME_SHORT_START 次
                    if g_type == "U":
                        fp = f"{s_ep}_{l_ep}_{round(phys_end)}"
                        start_key = f"{s_ep}_{round(float(start_time), 1)}"
                        if used_short_starts.get(start_key, 0) >= MAX_SAME_SHORT_START:
                            continue
                    else:
                        fp = f"{s_ep}_{l_ep}_{round(phys_end)}_{round(start_time)}"
                    if fp in used_fingerprints:
                        continue
                    used_fingerprints.add(fp)
                    if g_type == "U":
                        used_short_starts[start_key] = (
                            used_short_starts.get(start_key, 0) + 1
                        )

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
                if g_type == "U":
                    _emit(f"已通过 {len(final_plans)}/{target_total} 条")
                else:
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
                        "（多数候选因时长或台词未匹配被过滤）"
                    ),
                    "underfilled": True,
                }
            )
    return unique_plans
