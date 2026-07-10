from qfluentwidgets import qconfig

from app.common.config import cfg
from app.data.services.access_control_service import access_control
from app.data.api.api import ApiError, LoginResult, get_api


class AuthService:
    def login(self, username: str, password: str) -> LoginResult:
        api = get_api()
        try:
            result = api.login(username, password)
        except ApiError as exc:
            raise RuntimeError(
                access_control.mask_login_error(str(exc), exc.status_code)
            ) from exc
        if isinstance(result, LoginResult) and result.access_token:
            access_control.unblock()
            qconfig.set(cfg.access_token, result.access_token)
            self._apply_secrets(api)
            return result
        raise RuntimeError("登录失败，请检查账号密码")

    def try_auto_login(self) -> bool:
        token = (cfg.access_token.value or '').strip()
        if not token:
            return False

        api = get_api()
        if not api.validate_session():
            access_control.block()
            return False
        access_control.unblock()
        self._apply_secrets(api)
        return True

    def _apply_secrets(self, api) -> None:
        if not hasattr(api, 'fetch_secrets'):
            return
        secrets = api.fetch_secrets()
        deepseek = (secrets.get('deepseek_keys') or '').strip()
        dashscope = (secrets.get('dashscope_key') or '').strip()
        plan_key = (secrets.get('plan_decrypt_key') or '').strip()
        if deepseek:
            qconfig.set(cfg.deepseek_api_keys, deepseek)
        if dashscope:
            qconfig.set(cfg.dashscope_api_key, dashscope)
        if plan_key:
            qconfig.set(cfg.plan_decrypt_key, plan_key)

    def logout(self):
        qconfig.set(cfg.access_token, '')
