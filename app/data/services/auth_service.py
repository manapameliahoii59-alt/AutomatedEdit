from qfluentwidgets import qconfig

from app.common.aes import aes_encrypt, aes_decrypt
from app.common.config import cfg
from app.data.services.access_control_service import access_control
from app.data.api.api import ApiError, LoginResult, get_api


class AuthService:
    def login(self, username: str, password: str) -> LoginResult:
        # 允许用新账号密码重新登录，即使此前会话已被标记封禁
        access_control.unblock()
        api = get_api()
        try:
            result = api.login(username, password)
        except ApiError as exc:
            raise RuntimeError(
                access_control.mask_login_error(str(exc), exc.status_code)
            ) from exc
        if isinstance(result, LoginResult) and result.access_token:
            access_control.unblock()
            qconfig.set(cfg.access_token, aes_encrypt(result.access_token))
            self._apply_secrets(api)
            return result
        raise RuntimeError("登录失败，请检查账号密码")

    def try_auto_login(self) -> bool:
        token = aes_decrypt((cfg.access_token.value or '').strip())
        if not token:
            return False

        api = get_api()
        status = api.check_session() if hasattr(api, "check_session") else (
            "valid" if api.validate_session() else "invalid"
        )
        if status == "valid":
            access_control.unblock()
            self._apply_secrets(api)
            return True
        if status == "invalid":
            access_control.block()
            return False
        # 服务暂时不可达：不封禁，也不当作自动登录成功
        return False

    def _apply_secrets(self, api) -> None:
        if not hasattr(api, 'fetch_secrets'):
            return
        try:
            secrets = api.fetch_secrets()
        except ApiError:
            # 密钥拉取失败不阻断登录；策划密钥可稍后重试
            return
        deepseek = (secrets.get('deepseek_keys') or '').strip()
        dashscope = (secrets.get('dashscope_key') or '').strip()
        plan_key = (secrets.get('plan_decrypt_key') or '').strip()
        if deepseek:
            qconfig.set(cfg.deepseek_api_keys, aes_encrypt(deepseek))
        if dashscope:
            qconfig.set(cfg.dashscope_api_key, aes_encrypt(dashscope))
        if plan_key:
            qconfig.set(cfg.plan_decrypt_key, aes_encrypt(plan_key))

    def logout(self):
        qconfig.set(cfg.access_token, '')
