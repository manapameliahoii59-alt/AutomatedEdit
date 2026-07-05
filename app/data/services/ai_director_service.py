import json
import os
import re
import queue
import threading
import time
from datetime import datetime

import requests
from fuzzywuzzy import process
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from app.common.config import cfg
from app.data.models.drama_project import DramaProject

API_URL = "https://api.deepseek.com/chat/completions"
MODEL_NAME = "deepseek-v4-flash"
MIN_DURATION_SECONDS = 150
MAX_DURATION_SECONDS = 720
SEARCH_EPISODES = 15
TARGET_CLIPS_COUNT = 15
GROUP_A_COUNT = 6
GROUP_A_BUFFER = 2
GROUP_B_BUFFER = 3
MAX_GROUP_LOOPS = 5
MAX_OUTPUT_TOKENS = 7000

http_session = requests.Session()
retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["POST"],
)
http_session.mount("https://", HTTPAdapter(max_retries=retry_strategy))
http_session.mount("http://", HTTPAdapter(max_retries=retry_strategy))

print_lock = threading.Lock()


def safe_print(*args, **kwargs):
    with print_lock:
        print(*args, **kwargs)


class AIDirectorService:

    @staticmethod
    def plan(project: DramaProject) -> str:
        plan_start = time.perf_counter()
        project_path = project.folder_path
        script_file = os.path.join(project_path, "full_script_data.json")
        if not os.path.exists(script_file):
            raise FileNotFoundError(f"《{project.name}》未找到 full_script_data.json，请先识别")

        plan_output = os.path.join(project_path, "production_plan_v3.json")

        from app.common.crypto import read_json
        steps = read_json(script_file).get("steps", [])

        ordered_files = sorted(
            [f for f in os.listdir(project_path) if f.lower().endswith(".mp4")],
            key=lambda s: [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)],
        )

        target_episodes = ordered_files[:SEARCH_EPISODES]
        compressed_script = "".join(
            f"\n[{s['source_file']}]({s['end']:.0f}s){s['text']}"
            for s in steps
            if s["source_file"] in target_episodes
        )
        script_chars = len(compressed_script)

        episode_end_times = {}
        for s in steps:
            episode_end_times[s["source_file"]] = max(
                episode_end_times.get(s["source_file"], 0), s.get("end", 0)
            )

        api_keys_raw = cfg.deepseek_api_keys.value
        if not api_keys_raw:
            raise ValueError("未配置 DeepSeek API Key，请在设置中配置")

        api_keys = [k.strip() for k in api_keys_raw.split(",") if k.strip()]
        key_pool = queue.Queue()
        for k in api_keys:
            key_pool.put(k)

        final_plans = []
        used_fingerprints = set()
        date_str = datetime.now().strftime("%m%d")
        step_texts = [s["text"] for s in steps]
        api_call_count = 0
        api_total_seconds = 0.0

        safe_print(f"\n🎬 AI 导演策划: 《{project.name}》")
        safe_print(f"   📄 剧本: {script_chars:,} 字 | 前 {len(target_episodes)} 集")

        task_groups = [("A", GROUP_A_COUNT), ("B", TARGET_CLIPS_COUNT - GROUP_A_COUNT)]

        for g_type, total_count in task_groups:
            completed_in_group = 0
            loop_count = 0
            group_buffer = GROUP_A_BUFFER if g_type == "A" else GROUP_B_BUFFER

            while completed_in_group < total_count and loop_count < MAX_GROUP_LOOPS:
                loop_count += 1
                remaining = total_count - completed_in_group
                request_count = remaining + group_buffer

                safe_print(f"   🤖 【{g_type}组】({completed_in_group}/{total_count}) 请求 {request_count} 条...")
                raw_res, elapsed, api_error = AIDirectorService._call_deepseek(
                    compressed_script, request_count, g_type, key_pool
                )
                api_call_count += 1
                api_total_seconds += elapsed

                if api_error:
                    safe_print(f"      📡 API #{api_call_count} 失败 | 耗时 {elapsed:.1f}s | {api_error}")
                    continue

                if not raw_res:
                    safe_print(f"      📡 API #{api_call_count} 失败 | 耗时 {elapsed:.1f}s | 响应内容为空")
                    continue

                try:
                    clips = AIDirectorService._parse_clips_response(raw_res)
                    if not clips:
                        safe_print(
                            f"      📡 API #{api_call_count} | 耗时 {elapsed:.1f}s | 返回 0 条"
                        )
                        continue

                    batch_ok = 0
                    batch_hooks = []
                    for item in clips:
                        s_ep, l_ep, start_time, cut_text, hook = AIDirectorService._parse_clip_fields(item)
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

                        c_idx = AIDirectorService._find_cut_index(steps, cut_text, step_texts)
                        if c_idx == -1:
                            continue
                        if steps[c_idx].get("source_file") != l_ep:
                            continue

                        phys_end = steps[c_idx].get("end", 0)
                        cut_point = phys_end + 0.3
                        if cut_point <= start_time:
                            continue

                        total_dur = AIDirectorService._compute_clip_duration(
                            s_idx, l_idx, start_time, cut_point, ordered_files, episode_end_times
                        )
                        if total_dur < MIN_DURATION_SECONDS or total_dur > MAX_DURATION_SECONDS:
                            continue

                        fp = f"{s_ep}_{l_ep}_{round(phys_end)}_{round(start_time)}"
                        if fp in used_fingerprints:
                            continue
                        used_fingerprints.add(fp)

                        final_plans.append({
                            "title": f"{project.name}-{date_str}-{len(final_plans)+1:02d}",
                            "project_name": project.name,
                            "global_speed": 1.15,
                            "files_config": {
                                "first_episode_cut_start": round(start_time, 1),
                                "full_episodes": ordered_files[s_idx:l_idx],
                                "last_episode": l_ep,
                                "last_episode_cut_point": round(cut_point, 2),
                            },
                            "hook": hook,
                        })
                        batch_ok += 1
                        batch_hooks.append(hook)

                    completed_in_group += batch_ok
                    safe_print(
                        f"      📡 API #{api_call_count} | 耗时 {elapsed:.1f}s "
                        f"| 返回 {len(clips)} 条 | 通过 {batch_ok} 条 "
                        f"| 组内累计 {completed_in_group}/{total_count}"
                    )
                    for i, hook in enumerate(batch_hooks, 1):
                        safe_print(f"         hook[{i}]: {hook}")

                except Exception as e:
                    safe_print(f"      ⚠️ 解析失败 (API #{api_call_count}, {elapsed:.1f}s): {e}")
                    continue

        if not final_plans:
            raise RuntimeError(f"《{project.name}》AI 策划未产出有效方案")

        seen = set()
        unique_plans = []
        for plan in final_plans:
            cfg_key = json.dumps(plan["files_config"], sort_keys=True)
            if cfg_key in seen:
                continue
            seen.add(cfg_key)
            unique_plans.append(plan)

        from app.common.crypto import write_encrypted_json
        write_encrypted_json(plan_output, unique_plans)

        total_elapsed = time.perf_counter() - plan_start
        safe_print(
            f"📊 《{project.name}》策划完成: {len(unique_plans)} 个方案 -> {plan_output}\n"
            f"   ⏱️ 总耗时 {total_elapsed:.1f}s | API {api_call_count} 次 "
            f"(合计 {api_total_seconds:.1f}s) | 剧本 {script_chars:,} 字"
        )
        return plan_output

    @staticmethod
    def _parse_clips_response(raw_res: str) -> list:
        clean_res = raw_res.strip()
        if clean_res.startswith("```json"):
            clean_res = clean_res.split("```json")[1].split("```")[0].strip()
        elif clean_res.startswith("```"):
            clean_res = clean_res.split("```")[1].split("```")[0].strip()
        clean_res = re.sub(r"\n", " ", clean_res)
        return json.loads(clean_res).get("clips", [])

    @staticmethod
    def _compute_clip_duration(s_idx, l_idx, start_time, cut_point, ordered_files, episode_end_times):
        """与渲染拼接逻辑一致的成片时长（秒）。"""
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

    @staticmethod
    def _parse_clip_fields(item: dict) -> tuple[str | None, str | None, float, str, str]:
        s_ep = item.get("se") or item.get("start_episode")
        l_ep = item.get("le") or item.get("cut_text_source_file")
        start_time = item.get("st", item.get("start_time", 0))
        cut_text = item.get("ct") or item.get("cut_text", "")
        hook = item.get("hook") or item.get("hk") or "点击查看大结局"
        return s_ep, l_ep, start_time, cut_text, hook

    @staticmethod
    def _call_deepseek(compressed_script, count, group_type, key_pool):
        """返回 (content, elapsed_seconds, error_message)。"""
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
                "输出纯 JSON: {\"clips\":[{\"se\":\"1.mp4\",\"st\":0,\"le\":\"6.mp4\",\"ct\":\"台词\",\"hook\":\"引流标题\"}]}\n"
                "字段: se=起始集, st=起始秒, le=结束集, ct=le集中台词(8~15字), hook=悬念引流标题"
            )
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": MODEL_NAME,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"剧本库：{compressed_script}"},
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": MAX_OUTPUT_TOKENS,
                "thinking": {"type": "disabled"},
            }
            resp = http_session.post(API_URL, headers=headers, json=payload, timeout=(30, 180))
            elapsed = time.perf_counter() - t0

            if resp.status_code != 200:
                detail = resp.text[:300]
                return None, elapsed, f"HTTP {resp.status_code}: {detail}"

            data = resp.json()
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            content = message.get("content")
            if content and str(content).strip():
                return str(content).strip(), elapsed, None

            finish_reason = choice.get("finish_reason", "unknown")
            usage = data.get("usage") or {}
            reasoning_tokens = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
            hint = f"finish_reason={finish_reason}"
            if reasoning_tokens:
                hint += f", reasoning_tokens={reasoning_tokens}"
            if message.get("reasoning_content"):
                hint += ", 存在 reasoning_content 但 content 为空(请关闭 thinking 或增大 max_tokens)"
            return None, elapsed, f"响应内容为空 ({hint})"

        except Exception as e:
            return None, time.perf_counter() - t0, str(e)
        finally:
            key_pool.put(api_key)

    @staticmethod
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
