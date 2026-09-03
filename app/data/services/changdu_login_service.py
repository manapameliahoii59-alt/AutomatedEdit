import re
from pathlib import Path

from playwright.sync_api import Frame, Page, sync_playwright

from app.common.aes import aes_decrypt
from app.common.config import cfg
from app.data.services.changdu_browser import (
    LAUNCH_ARGS,
    STEALTH_INIT_SCRIPT,
    browser_context_kwargs,
)
from app.data.services.changdu_paths import AUTH_FILE, ensure_changdu_dirs

HOME_URL = "https://www.changdupingtai.com/page/home?show=true"
SALE_URL_PATTERN = "**/sale/**"


def _is_browser_closed_error(exc: BaseException) -> bool:
    name = type(exc).__name__
    if "TargetClosed" in name or "BrowserClosed" in name:
        return True
    msg = str(exc).lower()
    return "has been closed" in msg or "target page" in msg


def get_changdu_credentials() -> tuple[str, str] | None:
    """读取设置中的常读邮箱与密码；未配置完整时返回 None。"""
    email = cfg.changdu_email.value.strip()
    encrypted = cfg.changdu_password.value.strip()
    if not email or not encrypted:
        return None
    password = aes_decrypt(encrypted)
    if not password:
        return None
    return email, password


def _find_login_root(page: Page) -> Page | Frame:
    for frame in page.frames:
        if frame.locator('input[name="email"]').count() > 0:
            return frame
    return page


def _try_autofill_changdu_login(page: Page, email: str, password: str) -> None:
    """打开登录弹框并填入邮箱密码；协议勾选、拖动验证与点击登录均由用户完成。"""
    try:
        trigger = page.get_by_text(re.compile(r"登录\s*/\s*注册"))
        trigger.first.click(timeout=10_000)
    except Exception:
        return

    try:
        page.wait_for_selector(
            'input[name="email"], .account-center-sdk-container',
            timeout=10_000,
        )
    except Exception:
        return

    root = _find_login_root(page)
    email_input = root.locator('input[name="email"]')
    if email_input.count() == 0:
        return

    email_input.first.fill(email, timeout=5_000)
    root.locator('input[name="password"]').first.fill(password, timeout=5_000)


def run_changdu_login(auth_file: Path | None = None) -> Path:
    """打开浏览器供用户登录，成功后保存 Playwright storageState。"""
    ensure_changdu_dirs()
    target = auth_file or AUTH_FILE
    credentials = get_changdu_credentials()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=False,
                args=list(LAUNCH_ARGS),
            )
            context = browser.new_context(**browser_context_kwargs())
            page = context.new_page()
            page.add_init_script(STEALTH_INIT_SCRIPT)
            page.goto(HOME_URL, timeout=60_000)
            if credentials:
                _try_autofill_changdu_login(page, credentials[0], credentials[1])
            page.wait_for_url(SALE_URL_PATTERN, timeout=0)
            context.storage_state(path=str(target))
            browser.close()
    except Exception as exc:
        if _is_browser_closed_error(exc):
            raise RuntimeError(
                "浏览器已关闭，登录未完成。请重新点击「打开浏览器登录」，"
                "并在登录成功前不要关闭窗口。"
            ) from exc
        raise

    return target


def is_auth_file_present(auth_file: Path | None = None) -> bool:
    return (auth_file or AUTH_FILE).is_file()


def clear_auth_file(auth_file: Path | None = None) -> bool:
    """删除 auth.json，文件存在且删除成功返回 True。"""
    target = auth_file or AUTH_FILE
    if not target.is_file():
        return False
    target.unlink()
    return True
