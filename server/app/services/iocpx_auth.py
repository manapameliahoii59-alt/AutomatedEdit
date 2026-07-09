"""易投（iocpx）第三方登录校验，对应客户端 ensureAuth 的账号密码登录流程。"""

from __future__ import annotations

import httpx

from app.config import settings


class IocpxAuthError(Exception):
    def __init__(self, message: str, *, status_code: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _extract_session_id(response: httpx.Response) -> str | None:
    session_id = response.cookies.get("ocpx_session_id")
    if session_id:
        return session_id

    for header in response.headers.get_list("set-cookie"):
        if header.startswith("ocpx_session_id="):
            return header.split(";", 1)[0].split("=", 1)[1]
    return None


def verify_iocpx_credentials(
    email: str,
    password: str,
    *,
    base_url: str | None = None,
) -> str:
    """
    使用易投账号密码登录，成功返回 ocpx_session_id。
    流程：login1 → 取 Cookie → login2(moduleId=3)
    """
    account = email.strip()
    if not account or not password:
        raise IocpxAuthError("请输入易投账号和密码")

    api_base = (base_url or settings.iocpx_base_url).rstrip("/")
    headers = {
        "Content-Type": "application/json",
        "Origin": "https://console.iocpx.com",
        "Referer": "https://console.iocpx.com/",
    }

    try:
        with httpx.Client(base_url=api_base, timeout=15.0, headers=headers) as client:
            login1 = client.post(
                "/merchant/auth/login1",
                json={"email": account, "password": password, "rememberMe": True},
            )
            if login1.status_code >= 400:
                raise IocpxAuthError("易投账号或密码错误")

            session_id = _extract_session_id(login1)
            if not session_id:
                raise IocpxAuthError("易投登录失败：未获取到会话信息")

            login2 = client.post(
                "/merchant/auth/login2",
                json={"moduleId": 3},
                cookies={"ocpx_session_id": session_id},
            )
            if login2.status_code >= 400:
                raise IocpxAuthError("易投账号或密码错误")

            return session_id
    except IocpxAuthError:
        raise
    except httpx.TimeoutException as exc:
        raise IocpxAuthError("无法连接易投平台，请检查网络", status_code=503) from exc
    except httpx.RequestError as exc:
        raise IocpxAuthError("无法连接易投平台，请检查网络", status_code=503) from exc
