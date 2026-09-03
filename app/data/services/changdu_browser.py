"""常读平台 Playwright / 下载请求共用的浏览器指纹，降低自动化特征。"""

from __future__ import annotations

# 与当前 Chromium 大致对齐的桌面 Chrome UA（登录与下载共用）
CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.7339.208 Safari/537.36"
)

BROWSER_LOCALE = "zh-CN"
BROWSER_TIMEZONE = "Asia/Shanghai"
BROWSER_VIEWPORT = {"width": 1440, "height": 900}
ACCEPT_LANGUAGE = "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7"

HOME_ORIGIN = "https://www.changdupingtai.com"
DOWNLOAD_CENTER_REFERER = f"{HOME_ORIGIN}/sale/download-center"

# 隐藏 webdriver，并补齐常见 navigator 字段
STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', {
  get: () => Object.freeze(['zh-CN', 'zh', 'en-US', 'en']),
});
if (!window.chrome) {
  window.chrome = { runtime: {} };
}
"""

LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
]


def browser_context_kwargs(*, storage_state: str | None = None) -> dict:
    """Playwright new_context 公共参数。"""
    kwargs: dict = {
        "user_agent": CHROME_USER_AGENT,
        "locale": BROWSER_LOCALE,
        "timezone_id": BROWSER_TIMEZONE,
        "viewport": dict(BROWSER_VIEWPORT),
        "color_scheme": "light",
        "extra_http_headers": {
            "Accept-Language": ACCEPT_LANGUAGE,
        },
    }
    if storage_state:
        kwargs["storage_state"] = storage_state
    return kwargs


def zip_download_headers(*, cookie: str | None = None) -> dict[str, str]:
    """给 requests 拉 zip 使用的浏览器风格请求头。"""
    headers = {
        "User-Agent": CHROME_USER_AGENT,
        "Accept": "application/zip,application/octet-stream,*/*;q=0.8",
        "Accept-Language": ACCEPT_LANGUAGE,
        "Accept-Encoding": "identity",
        "Referer": DOWNLOAD_CENTER_REFERER,
        "Origin": HOME_ORIGIN,
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site",
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


def format_cookie_header(cookies: list[dict]) -> str:
    parts: list[str] = []
    for item in cookies or []:
        name = item.get("name")
        value = item.get("value")
        if name and value is not None:
            parts.append(f"{name}={value}")
    return "; ".join(parts)
