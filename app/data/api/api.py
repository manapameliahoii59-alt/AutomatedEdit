import os
import time
from dataclasses import dataclass, field

import requests
from qfluentwidgets import qconfig

from app.common.aes import aes_decrypt
from app.common.config import VERSION, cfg, DEFAULT_API_BASE_URL, DEV_API_BASE_URL
from app.common.my_logger import my_logger as logger
from app.common.runtime import is_dev_runtime


class ApiError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        *,
        detail: str = "",
    ):
        super().__init__(message)
        self.status_code = status_code
        # 技术细节（服务器地址 / 底层异常）仅用于日志与排查，不面向用户展示
        self.detail = detail or ""


class ClientVersionUnsupportedError(ApiError):
    """客户端版本过低已被服务端停用 (HTTP 426)。"""
    pass


@dataclass
class LoginResult:
    access_token: str
    username: str
    role: str
    enabled_tabs: list[str] = field(
        default_factory=lambda: ["video_download", "clip_edit"]
    )


def _update_enabled_tabs(
    tabs: list[str] | str | None,
    download_enabled: bool | None = None,
) -> None:
    if tabs is None and download_enabled is None:
        return
    if isinstance(tabs, list):
        parsed = [str(t).strip() for t in tabs if str(t).strip()]
    elif tabs:
        parsed = [t.strip() for t in str(tabs).split(",") if t.strip()]
    else:
        parsed = [
            t.strip()
            for t in str(cfg.enabled_tabs.value or "video_download,clip_edit").split(",")
            if t.strip()
        ]

    # 如果明确未开通视频下载，强制从 Tab 中排除 video_download
    if download_enabled is False:
        parsed = [t for t in parsed if t != "video_download"]
    elif download_enabled is True and not tabs and "video_download" not in parsed:
        parsed.insert(0, "video_download")

    val = ",".join(parsed)
    qconfig.set(cfg.enabled_tabs, val)


class RemoteApi:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self._token = ''
        self._session = requests.Session()

    def set_token(self, token: str):
        self._token = token or ''

    def _headers(self) -> dict:
        headers = {
            'Content-Type': 'application/json',
            'X-Client-Version': str(VERSION),
        }
        if self._token:
            headers['Authorization'] = f'Bearer {self._token}'
        return headers

    def _request(self, method: str, path: str, **kwargs):
        url = f'{self.base_url}{path}'
        timeout = kwargs.pop('timeout', 30)
        try:
            # connect / read 分开，避免连接阶段拖满整个 timeout
            if isinstance(timeout, (int, float)):
                timeout = (min(10.0, float(timeout)), float(timeout))
            resp = self._session.request(
                method, url, headers=self._headers(), timeout=timeout, **kwargs
            )
        except requests.exceptions.ConnectTimeout as e:
            logger.warning("连接服务器超时: {} ({})", self.base_url, e)
            raise ApiError(
                "无法连接服务器（连接超时），请检查网络或稍后重试",
                detail=f"{self.base_url} | {e}",
            ) from e
        except requests.exceptions.ReadTimeout as e:
            logger.warning("服务器响应超时: {} ({})", self.base_url, e)
            raise ApiError(
                "服务器响应超时，请稍后重试",
                detail=f"{self.base_url} | {e}",
            ) from e
        except requests.RequestException as e:
            logger.warning("无法连接服务器: {} ({})", self.base_url, e)
            raise ApiError(
                "无法连接服务器，请检查网络或稍后重试",
                detail=f"{self.base_url} | {e}",
            ) from e
        if resp.encoding is None:
            resp.encoding = 'utf-8'
        if resp.status_code >= 400:
            detail = resp.text
            try:
                detail = resp.json().get('detail', detail)
            except Exception:
                pass
            if isinstance(detail, list):
                detail = str(detail)
            msg = str(detail or "").strip()
            if not msg:
                msg = f"服务器错误 HTTP {resp.status_code}"
            if resp.status_code == 426:
                raise ClientVersionUnsupportedError(msg, status_code=426)
            raise ApiError(msg, status_code=resp.status_code)
        if resp.content:
            return resp.json()
        return None

    def login(self, username, password, captcha='', sms_code=''):
        data = self._request(
            'POST',
            '/api/auth/login',
            json={'username': username, 'password': password},
        )
        token = data['access_token']
        user = data.get('user') or {}
        self._token = token
        raw_tabs = user.get('enabled_tabs')
        download_enabled = user.get('download_enabled')
        _update_enabled_tabs(raw_tabs, download_enabled=download_enabled)
        parsed_tabs = (
            raw_tabs
            if isinstance(raw_tabs, list)
            else (
                [t.strip() for t in str(raw_tabs).split(",") if t.strip()]
                if raw_tabs
                else ["video_download", "clip_edit"]
            )
        )
        if download_enabled is False:
            parsed_tabs = [t for t in parsed_tabs if t != "video_download"]
        return LoginResult(
            access_token=token,
            username=user.get('username', username),
            role=user.get('role', 'user'),
            enabled_tabs=parsed_tabs,
        )

    def check_session(self) -> str:
        """校验登录会话。

        Returns:
            "valid" — 会话有效
            "expired" — 登录态失效 / 401（Token 过期或被管理员设为已过期）
            "invalid" — 明确无效（无 token / 403 / is_active=False）
            "unreachable" — 网络或服务端暂时不可达（不应因此封禁客户端）
        """
        if not self._token:
            return 'invalid'
        try:
            # 探活略放宽，降低服务端短暂变慢时的误判
            data = self._request('GET', '/api/auth/me', timeout=10) or {}
            if not bool(data.get('is_active', True)):
                return 'invalid'
            _update_enabled_tabs(
                data.get('enabled_tabs'),
                download_enabled=data.get('download_enabled'),
            )
            return 'valid'
        except ApiError as exc:
            if exc.status_code == 401:
                return 'expired'
            if exc.status_code == 403:
                return 'invalid'
            return 'unreachable'

    def validate_session(self) -> bool:
        """兼容旧调用：仅在明确有效时返回 True。"""
        return self.check_session() == 'valid'

    def fetch_secrets(self) -> dict:
        return self._request('GET', '/api/client/secrets') or {}

    def report_usage(
        self,
        event: str,
        success: bool = True,
        duration_ms: int = 0,
        meta: str = '',
        plan_mode: str | None = None,
        plan_model: str = '',
        transcribe_ms: int = 0,
        plan_ms: int = 0,
        render_ms: int = 0,
        encoder: str = '',
        resolution: str = '',
        cache_ms: int = 0,
        compose_ms: int = 0,
        render_engine: str = '',
    ):
        if not self._token:
            return
        payload = {
            'event': event,
            'success': success,
            'duration_ms': max(0, int(duration_ms)),
            'meta': meta,
            'client_version': VERSION,
        }
        if plan_mode:
            payload['plan_mode'] = plan_mode
        if plan_model:
            payload['plan_model'] = plan_model
        if transcribe_ms:
            payload['transcribe_ms'] = max(0, int(transcribe_ms))
        if plan_ms:
            payload['plan_ms'] = max(0, int(plan_ms))
        if render_ms:
            payload['render_ms'] = max(0, int(render_ms))
        if encoder:
            payload['encoder'] = encoder
        if resolution:
            payload['resolution'] = resolution
        if cache_ms:
            payload['cache_ms'] = max(0, int(cache_ms))
        if compose_ms:
            payload['compose_ms'] = max(0, int(compose_ms))
        if render_engine:
            payload['render_engine'] = render_engine
        self._request(
            'POST',
            '/api/client/usage',
            json=payload,
        )

    def fetch_daily_quota(self) -> dict:
        data = self._request('GET', '/api/client/quota/today') or {}
        _update_enabled_tabs(
            data.get('enabled_tabs'),
            download_enabled=data.get('download_enabled'),
        )
        return data

    def check_daily_quota(self, action: str, drama_name: str) -> dict:
        return self._request(
            'POST',
            '/api/client/quota/check',
            json={'action': action, 'drama_name': drama_name},
        ) or {}

    def get_settings(self) -> dict:
        return self._request('GET', '/api/client/settings') or {}

    def update_settings(self, patch: dict) -> dict:
        return self._request('PATCH', '/api/client/settings', json=patch) or {}

    def create_plan_job(self, payload: dict) -> dict:
        return self._request('POST', '/api/client/plan/jobs', json=payload) or {}

    def get_plan_job_status(self, job_id: str) -> dict:
        return self._request('GET', f'/api/client/plan/jobs/{job_id}') or {}

    def get_plan_job_result(self, job_id: str) -> dict:
        return self._request('GET', f'/api/client/plan/jobs/{job_id}/result') or {}

    def fetch_client_version(self) -> dict:
        return self._request('GET', '/api/client/version') or {}

    def post_error_report(self, payload: dict) -> dict:
        return self._request('POST', '/api/client/error-reports', json=payload) or {}

    def report_machine_info(self, payload: dict) -> dict:
        if not self._token:
            return {}
        return self._request('POST', '/api/client/machine', json=payload) or {}

    def fetch_invite_info(self) -> dict:
        return self._request('GET', '/api/client/invite/info') or {}

    def bind_invite_code(self, invite_code: str) -> dict:
        return self._request('POST', '/api/client/invite/bind', json={'invite_code': invite_code}) or {}



def _resolve_base_url() -> str:
    custom = (
        os.environ.get("AE_API_BASE_URL") or cfg.api_base_url.value or ""
    ).strip().rstrip('/')
    if custom:
        return custom
    return DEV_API_BASE_URL if is_dev_runtime() else DEFAULT_API_BASE_URL


def get_api() -> RemoteApi:
    api = RemoteApi(_resolve_base_url())
    token = aes_decrypt((cfg.access_token.value or '').strip())
    if token:
        api.set_token(token)
    return api
