"""通过服务端代理完成策划，并解密写入本地。"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Callable

from qfluentwidgets import qconfig

from app.common.aes import aes_encrypt, aes_decrypt
from app.common.config import cfg
from app.common.plan_crypto import decrypt_plan_payload
from app.data.api.api import ApiError, get_api
from app.data.models.drama_project import DramaProject


class RemotePlanService:
    POLL_INTERVAL_SEC = 2.0
    POLL_TIMEOUT_SEC = 20 * 60

    @staticmethod
    def _require_api():
        token = aes_decrypt((cfg.access_token.value or "").strip())
        if not token:
            raise RuntimeError("请先登录后再策划")
        api = get_api()
        if not hasattr(api, "create_plan_job"):
            raise RuntimeError("当前未连接服务端，无法策划")
        return api

    @staticmethod
    def _require_plan_key() -> str:
        key = aes_decrypt((cfg.plan_decrypt_key.value or "").strip())
        if not key:
            raise RuntimeError("策划密钥未就绪，请重新登录")
        return key

    @staticmethod
    def _build_payload(project: DramaProject) -> dict[str, Any]:
        from app.common.crypto import read_json
        from app.common.drama_artifact_paths import locate_script_data

        project_path = project.folder_path
        script_file = locate_script_data(project_path)
        if not script_file:
            raise FileNotFoundError(f"《{project.name}》未找到 full_script_data.json，请先识别")

        steps = read_json(script_file).get("steps", [])
        ordered_files = sorted(
            [f for f in os.listdir(project_path) if f.lower().endswith(".mp4")],
            key=lambda s: [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)],
        )
        if not ordered_files:
            raise FileNotFoundError(f"《{project.name}》未找到视频文件")

        return {
            "project_name": project.name,
            "drama_name": project.name,
            "steps": steps,
            "ordered_files": ordered_files,
        }

    @classmethod
    def plan(
        cls,
        project: DramaProject,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> str:
        from app.common.drama_artifact_paths import finalize_written_artifact, prepare_write_path
        from app.common.crypto import write_encrypted_json

        api = cls._require_api()
        plan_key = cls._require_plan_key()
        payload = cls._build_payload(project)
        plan_output = prepare_write_path(project.folder_path, script=False)

        job = api.create_plan_job(payload)
        job_id = job.get("job_id") or job.get("id")
        if not job_id:
            raise RuntimeError("服务端未返回策划任务 ID")

        deadline = time.time() + cls.POLL_TIMEOUT_SEC
        while time.time() < deadline:
            status = api.get_plan_job_status(job_id)
            progress = status.get("progress") or {}
            if progress_callback and progress:
                progress_callback(progress)

            state = status.get("status") or ""
            if state == "done":
                result = api.get_plan_job_result(job_id)
                plans = decrypt_plan_payload(
                    plan_key,
                    result["ciphertext"],
                    result["nonce"],
                )
                write_encrypted_json(plan_output, plans)
                finalize_written_artifact(plan_output)
                return plan_output
            if state == "failed":
                raise RuntimeError(status.get("error") or "策划失败")

            time.sleep(cls.POLL_INTERVAL_SEC)

        raise RuntimeError("策划超时，请稍后重试")

    @classmethod
    def refresh_plan_key_from_server(cls) -> None:
        api = cls._require_api()
        try:
            secrets = api.fetch_secrets()
        except ApiError:
            return
        plan_key = (secrets.get("plan_decrypt_key") or "").strip()
        if plan_key:
            qconfig.set(cfg.plan_decrypt_key, aes_encrypt(plan_key))
