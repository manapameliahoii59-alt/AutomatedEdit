from qfluentwidgets import qconfig

from app.common.config import cfg
from app.data.api.api import LoginResult, get_api


class AuthService:
    def login(self, username: str, password: str) -> LoginResult:
        api = get_api()
        result = api.login(username, password)
        if isinstance(result, LoginResult) and result.access_token:
            qconfig.set(cfg.access_token, result.access_token)
            self._apply_secrets(api)
        return result

    def try_auto_login(self) -> bool:
        base = (cfg.api_base_url.value or '').strip()
        if not base:
            return bool(cfg.user.value)

        token = (cfg.access_token.value or '').strip()
        if not token:
            return False

        api = get_api()
        if not hasattr(api, 'validate_session'):
            return False
        if not api.validate_session():
            return False
        self._apply_secrets(api)
        return True

    def _apply_secrets(self, api) -> None:
        if not hasattr(api, 'fetch_secrets'):
            return
        secrets = api.fetch_secrets()
        deepseek = (secrets.get('deepseek_keys') or '').strip()
        dashscope = (secrets.get('dashscope_key') or '').strip()
        if deepseek:
            qconfig.set(cfg.deepseek_api_keys, deepseek)
        if dashscope:
            qconfig.set(cfg.dashscope_api_key, dashscope)

    def logout(self):
        qconfig.set(cfg.access_token, '')
