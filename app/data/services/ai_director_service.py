import json
import os
import re
import queue
import threading
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
        project_path = project.folder_path
        script_file = os.path.join(project_path, "full_script_data.json")
        if not os.path.exists(script_file):
            raise FileNotFoundError(f"《{project.name}》未找到 full_script_data.json，请先听写")

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

        safe_print(f"\n🎬 AI 导演策划: 《{project.name}》")

        BATCH_SIZE = 3
        task_groups = [("A", GROUP_A_COUNT), ("B", TARGET_CLIPS_COUNT - GROUP_A_COUNT)]

        for g_type, total_count in task_groups:
            completed_in_group = 0
            loop_count = 0

            while completed_in_group < total_count and loop_count < 15:
                loop_count += 1
                current_batch_need = min(BATCH_SIZE, total_count - completed_in_group)

                safe_print(f"   🤖 【{g_type}组】({completed_in_group}/{total_count})...")
                raw_res = AIDirectorService._call_deepseek(
                    project.name, compressed_script, current_batch_need, g_type, key_pool
                )
                if not raw_res:
                    continue

                try:
                    clean_res = raw_res.strip()
                    if clean_res.startswith("```json"):
                        clean_res = clean_res.split("```json")[1].split("```")[0].strip()
                    elif clean_res.startswith("```"):
                        clean_res = clean_res.split("```")[1].split("```")[0].strip()
                    clean_res = re.sub(r"\n", " ", clean_res)

                    clips = json.loads(clean_res).get("clips", [])
                    if not clips:
                        continue

                    batch_ok = 0
                    for item in clips:
                        s_ep = item.get("start_episode")
                        l_ep = item.get("cut_text_source_file")
                        start_time = item.get("start_time", 0)
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

                        cut_text = item.get("cut_text", "")
                        c_idx = AIDirectorService._find_cut_index(steps, cut_text)
                        if c_idx == -1:
                            continue

                        phys_end = steps[c_idx].get("end", 0)
                        ep_first_dur = episode_end_times.get(ordered_files[s_idx], 0)
                        total_dur = (
                            max(0, ep_first_dur - start_time)
                            + sum(episode_end_times.get(ordered_files[x], 0) for x in range(s_idx + 1, l_idx))
                            + phys_end
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
                                "last_episode_cut_point": round(phys_end + 0.3, 2),
                            },
                            "hook": item.get("hook", "点击查看大结局"),
                        })
                        batch_ok += 1

                    completed_in_group += batch_ok

                except Exception as e:
                    safe_print(f"      ⚠️ 解析失败: {e}")
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

        safe_print(f"📊 《{project.name}》策划完成: {len(unique_plans)} 个方案 -> {plan_output}")
        return plan_output

    @staticmethod
    def _call_deepseek(project_name, compressed_script, count, group_type, key_pool):
        api_key = key_pool.get()
        try:
            system_prompt = (
                f"你是一个短剧广告投放导演。任务：策划 {count} 个高转化引流剪辑计划。\n"
                f"时长 {MIN_DURATION_SECONDS}~{MAX_DURATION_SECONDS} 秒。\n"
                f"{group_type}组。{'从第1集切入' if group_type == 'A' else '从剧集中段反转点开始'}。\n"
                "输出纯 JSON: {\"clips\":[{\"start_episode\":\"1.mp4\",\"start_time\":0,\"cut_text_source_file\":\"6.mp4\",\"cut_text\":\"台词\",\"hook\":\"标题\"}]}"
            )
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": MODEL_NAME,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"剧本库：{json.dumps(compressed_script)}"},
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": 7000,
            }
            resp = http_session.post(API_URL, headers=headers, json=payload, timeout=(30, 120))
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            safe_print(f"   ❌ API 调用失败: {e}")
            return None
        finally:
            key_pool.put(api_key)

    @staticmethod
    def _find_cut_index(steps, target_text):
        if not target_text:
            return -1
        texts = [s["text"] for s in steps]
        best = process.extractOne(target_text, texts)
        if best and best[1] >= 55:
            for i, s in enumerate(steps):
                if s["text"] == best[0]:
                    return i
        return -1
