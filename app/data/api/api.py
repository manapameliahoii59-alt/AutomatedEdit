import time
from dataclasses import dataclass

import requests

from app.common.aes import aes_decrypt
from app.common.config import VERSION, cfg, DEFAULT_API_BASE_URL


class ApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class LoginResult:
    access_token: str
    username: str
    role: str


class DemoApi:

    def get_captcha(self):
        time.sleep(1)
        b64_data = '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'
        return {'data': b64_data}

    def login(self, username, password, captcha='', sms_code=''):
        raise ApiError("未配置服务端地址，无法登录")


class RemoteApi:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self._token = ''

    def set_token(self, token: str):
        self._token = token or ''

    def _headers(self) -> dict:
        headers = {'Content-Type': 'application/json'}
        if self._token:
            headers['Authorization'] = f'Bearer {self._token}'
        return headers

    def _request(self, method: str, path: str, **kwargs):
        url = f'{self.base_url}{path}'
        try:
            resp = requests.request(method, url, headers=self._headers(), timeout=30, **kwargs)
        except requests.RequestException as e:
            raise ApiError(f'无法连接服务器：{e}') from e
        if resp.status_code >= 400:
            detail = resp.text
            try:
                detail = resp.json().get('detail', detail)
            except Exception:
                pass
            raise ApiError(str(detail), status_code=resp.status_code)
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
        return LoginResult(
            access_token=token,
            username=user.get('username', username),
            role=user.get('role', 'user'),
        )

    def validate_session(self) -> bool:
        if not self._token:
            return False
        try:
            data = self._request('GET', '/api/auth/me') or {}
            return bool(data.get('is_active', True))
        except ApiError:
            return False

    def fetch_secrets(self) -> dict:
        return self._request('GET', '/api/client/secrets') or {}

    def report_usage(
        self,
        event: str,
        success: bool = True,
        duration_ms: int = 0,
        meta: str = '',
    ):
        if not self._token:
            return
        self._request(
            'POST',
            '/api/client/usage',
            json={
                'event': event,
                'success': success,
                'duration_ms': duration_ms,
                'meta': meta,
                'client_version': VERSION,
            },
        )

    def fetch_daily_quota(self) -> dict:
        return self._request('GET', '/api/client/quota/today') or {}

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


def _resolve_base_url() -> str:
    custom = (cfg.api_base_url.value or '').strip().rstrip('/')
    return custom or DEFAULT_API_BASE_URL


def get_api() -> RemoteApi:
    api = RemoteApi(_resolve_base_url())
    token = aes_decrypt((cfg.access_token.value or '').strip())
    if token:
        api.set_token(token)
    return api


demo_api = DemoApi()
