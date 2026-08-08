"""开发环境本地策划：直接加载 server/plan_director，调用 DeepSeek。

正式打包环境不会走这里。可用环境变量：
- AE_FORCE_REMOTE_PLAN=1  开发环境仍走服务端
- DEEPSEEK_API_KEYS / AE_DEEPSEEK_API_KEYS
- DEEPSEEK_API_URL / AE_DEEPSEEK_API_URL
- DEEPSEEK_MODEL / AE_DEEPSEEK_MODEL
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any, Callable

from app.common.aes import aes_decrypt
from app.common.config import cfg
from app.common.my_logger import my_logger as logger
from app.common.plan_settings import resolve_active_plan_params
from app.common.runtime import is_dev_runtime
from app.data.models.drama_project import DramaProject
from app.data.services.remote_plan_service import RemotePlanService

_DEFAULT_API_URL = "https://api.deepseek.com/chat/completions"
_DEFAULT_MODEL = "deepseek-v4-flash"
_plan_director_mod = None


def use_local_plan() -> bool:
    """开发源码运行且未强制远端时，走本地策划。"""
    if not is_dev_runtime():
        return False
    force_remote = os.environ.get("AE_FORCE_REMOTE_PLAN", "").strip().lower()
    return force_remote not in {"1", "true", "yes", "on"}


def _project_root() -> Path:
    # app/data/services/local_plan_service.py → 仓库根
    return Path(__file__).resolve().parents[3]


def _load_dotenv_file(path: Path) -> None:
    """轻量加载 .env（不覆盖已有环境变量）。"""
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def _ensure_env_loaded() -> None:
    root = _project_root()
    _load_dotenv_file(root / ".env")
    _load_dotenv_file(root / ".env.local_plan")
    _load_dotenv_file(root / "server" / ".env")


def _resolve_api_keys() -> str:
    _ensure_env_loaded()
    for name in ("AE_DEEPSEEK_API_KEYS", "DEEPSEEK_API_KEYS"):
        raw = (os.environ.get(name) or "").strip()
        if raw:
            return raw
    stored = aes_decrypt((cfg.deepseek_api_keys.value or "").strip())
    if stored:
        return stored
    raise RuntimeError(
        "本地策划未配置 DeepSeek Key。"
        "请在仓库根目录 .env 写入 DEEPSEEK_API_KEYS=sk-...，"
        "或设置环境变量 AE_DEEPSEEK_API_KEYS。"
    )


def _resolve_api_url() -> str:
    _ensure_env_loaded()
    return (
        (os.environ.get("AE_DEEPSEEK_API_URL") or "").strip()
        or (os.environ.get("DEEPSEEK_API_URL") or "").strip()
        or _DEFAULT_API_URL
    )


def _resolve_model() -> str:
    _ensure_env_loaded()
    return (
        (os.environ.get("AE_DEEPSEEK_MODEL") or "").strip()
        or (os.environ.get("DEEPSEEK_MODEL") or "").strip()
        or _DEFAULT_MODEL
    )


def _load_plan_director():
    """从 server/app/services/plan_director.py 动态加载（改服务器同文件即可本地生效）。"""
    global _plan_director_mod
    if _plan_director_mod is not None:
        return _plan_director_mod

    path = _project_root() / "server" / "app" / "services" / "plan_director.py"
    if not path.is_file():
        raise FileNotFoundError(f"找不到本地策划引擎：{path}")

    # 开发时每次重新加载，方便改 plan_director 后无需重启解释器缓存
    # （同一进程内多次策划仍可强制 reload）
    name = "ae_server_plan_director"
    if name in sys.modules:
        del sys.modules[name]

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载策划引擎：{path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    _plan_director_mod = mod
    return mod


def reload_plan_director() -> None:
    """强制下次策划重新读取 server/plan_director.py。"""
    global _plan_director_mod
    _plan_director_mod = None


class LocalPlanService:
    @classmethod
    def plan(
        cls,
        project: DramaProject,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        from app.common.crypto import write_encrypted_json
        from app.common.drama_artifact_paths import (
            finalize_written_artifact,
            prepare_write_path,
        )

        # 每次重新加载 server/plan_director.py，改完即生效，无需重启客户端
        reload_plan_director()
        director = _load_plan_director()
        payload = RemotePlanService._build_payload(project)
        plan_output = prepare_write_path(project.folder_path, script=False)
        target_count = int(resolve_active_plan_params()["clip_count"])
        api_keys = _resolve_api_keys()
        api_url = _resolve_api_url()
        model_name = _resolve_model()

        logger.info(
            "本地策划《{}》：直接调用 DeepSeek（model={}）",
            project.name,
            model_name,
        )
        if progress_callback:
            progress_callback(
                {
                    "phase": "plan",
                    "current": 0,
                    "total": target_count,
                    "detail": "本地策划：准备剧本…",
                }
            )

        plans = director.run_plan(
            project_name=payload["project_name"],
            steps=payload["steps"],
            ordered_files=payload["ordered_files"],
            api_keys_raw=api_keys,
            api_url=api_url,
            model_name=model_name,
            progress_callback=progress_callback,
            target_clips_count=payload.get("target_clips_count"),
            max_duration_seconds=payload.get("max_duration_seconds"),
            min_duration_seconds=payload.get("min_duration_seconds"),
            split_ab=payload.get("split_ab"),
            global_speed=payload.get("global_speed"),
            plan_mode=payload.get("plan_mode"),
        )
        write_encrypted_json(plan_output, plans)
        finalize_written_artifact(plan_output)
        count = len(plans) if isinstance(plans, list) else 0
        return {
            "path": plan_output,
            "count": count,
            "target": target_count,
            "underfilled": count < target_count,
            "local": True,
        }
