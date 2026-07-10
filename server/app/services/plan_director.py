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
MAX_DURATION_SECONDS = 720
SEARCH_EPISODES = 15
TARGET_CLIPS_COUNT = 15
GROUP_A_COUNT = 6
GROUP_A_BUFFER = 2
GROUP_B_BUFFER = 3
MAX_GROUP_LOOPS = 5
MAX_OUTPUT_TOKENS = 7000

ProgressCallback = Callable[[dict[str, Any]], None]


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
    if best and best[1] >= 55:
        for i, s in enumerate(steps):
            if s["text"] == best[0]:
                return i
    return -1


def _call_deepseek(
    *,
    api_url: str,
    model_name: str,
    compressed_script: str,
    count: int,
    group_type: str,
    key_pool: queue.Queue,
) -> tuple[str | None, float, str | None]:
    api_key = key_pool.get()
    t0 = time.perf_counter()
    try:
        if group_type == "A":
            scope_rule = (
                "A组从第1集切入：可在第1集内剪一段（se与le均为1.mp4，st到切点须达150~720秒），"
                "也可跨多集（le须晚于se）。"
            )
        else:
            scope_rule = "B组必须跨多集：le 须晚于 se，通常跨越 4~8 集。"
        system_prompt = (
            f"你是一个短剧广告投放导演。任务：策划 {count} 个高转化引流剪辑计划。\n"
            f"硬性要求：每条剪辑总时长必须在 {MIN_DURATION_SECONDS}~{MAX_DURATION_SECONDS} 秒之间。\n"
            f"{scope_rule}\n"
            "各方案切点须有明显差异，避免重复。ct 必须取自 le 对应集数的剧本原文。\n"
            '输出纯 JSON: {"clips":[{"se":"1.mp4","st":0,"le":"6.mp4","ct":"台词","hook":"引流标题"}]}\n'
            "字段: se=起始集, st=起始秒, le=结束集, ct=le集中台词(8~15字), hook=悬念引流标题"
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
) -> list[dict]:
    if not api_keys_raw.strip():
        raise ValueError("服务端未配置策划 API 密钥")

    target_episodes = ordered_files[:SEARCH_EPISODES]
    compressed_script = "".join(
        f"\n[{s['source_file']}]({s['end']:.0f}s){s['text']}"
        for s in steps
        if s.get("source_file") in target_episodes
    )

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
    date_str = datetime.now().strftime("%m%d")
    step_texts = [s.get("text", "") for s in steps]
    task_groups = [("A", GROUP_A_COUNT), ("B", TARGET_CLIPS_COUNT - GROUP_A_COUNT)]

    def _emit(detail: str = "") -> None:
        if progress_callback:
            progress_callback(
                {
                    "phase": "plan",
                    "current": len(final_plans),
                    "total": TARGET_CLIPS_COUNT,
                    "detail": detail,
                }
            )

    _emit("准备剧本…")

    for g_type, total_count in task_groups:
        completed_in_group = 0
        loop_count = 0
        group_buffer = GROUP_A_BUFFER if g_type == "A" else GROUP_B_BUFFER

        while completed_in_group < total_count and loop_count < MAX_GROUP_LOOPS:
            loop_count += 1
            remaining = total_count - completed_in_group
            request_count = remaining + group_buffer
            _emit(f"{g_type}组 {completed_in_group}/{total_count} · 正在生成方案…")

            raw_res, _elapsed, api_error = _call_deepseek(
                api_url=api_url,
                model_name=model_name,
                compressed_script=compressed_script,
                count=request_count,
                group_type=g_type,
                key_pool=key_pool,
            )
            if api_error or not raw_res:
                continue

            try:
                clips = _parse_clips_response(raw_res)
                if not clips:
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
                    if cut_point <= start_time:
                        continue

                    total_dur = _compute_clip_duration(
                        s_idx, l_idx, start_time, cut_point, ordered_files, episode_end_times
                    )
                    if total_dur < MIN_DURATION_SECONDS or total_dur > MAX_DURATION_SECONDS:
                        continue

                    fp = f"{s_ep}_{l_ep}_{round(phys_end)}_{round(start_time)}"
                    if fp in used_fingerprints:
                        continue
                    used_fingerprints.add(fp)

                    final_plans.append(
                        {
                            "title": f"{project_name}-{date_str}-{len(final_plans) + 1:02d}",
                            "project_name": project_name,
                            "global_speed": 1.15,
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

                completed_in_group += batch_ok
                _emit(f"{g_type}组 · 已通过 {len(final_plans)}/{TARGET_CLIPS_COUNT} 条")
            except Exception:
                continue

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
    return unique_plans
