import re
import time
from pathlib import Path

from loguru import logger
from playwright.sync_api import Frame, Page, sync_playwright

from app.common.aes import aes_decrypt
from app.common.config import cfg
from app.data.services.changdu_browser import (
    LAUNCH_ARGS,
    STEALTH_INIT_SCRIPT,
    apply_device_cookies,
    browser_context_kwargs,
    save_device_cookies,
)
from app.data.services.changdu_paths import AUTH_FILE, ensure_changdu_dirs

HOME_URL = "https://www.changdupingtai.com/page/home?show=true"

# 真正维持登录的是服务端下发的 HttpOnly 会话 Cookie（页面 JS 读不到）。
# 登录是否完成应当以此为准，而不是看落地页 URL，也不是看 adUserId。
SESSION_COOKIES = ("sessionid", "sid_guard")
# 业务接口需要的账号标识（非 HttpOnly，位于 www.changdupingtai.com）。
# 站点改版后只下发 adUserId；rootAdUserId 已不再出现在展示类 Cookie 中，
# 因此不作为必需项，仅在能拿到时一并保存。
ACCOUNT_COOKIES = ("adUserId",)
OPTIONAL_ACCOUNT_COOKIES = ("rootAdUserId",)
COOKIE_DOMAIN = ".changdupingtai.com"
# 登录后需要进入销售页，站点才会下发完整的账号标识（rootAdUserId 尤其如此）。
SALE_PAGE_URL = "https://www.changdupingtai.com/sale/short-play/list"


def _wait_for_account_cookies(
    context,
    page: Page,
    *,
    timeout_s: float = 20.0,
    poll_ms: int = 500,
) -> list[str]:
    """在限定时间内等待账号标识 Cookie 出现，返回仍缺失的名称。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        names = {c.get("name") for c in context.cookies()}
        missing = [n for n in ACCOUNT_COOKIES if n not in names]
        if not missing:
            return []
        try:
            page.wait_for_timeout(poll_ms)
        except Exception as exc:  # 浏览器关闭则直接返回当前状态
            if _is_browser_closed_error(exc):
                break
            raise
    names = {c.get("name") for c in context.cookies()}
    missing = [n for n in ACCOUNT_COOKIES if n not in names]
    if missing:
        logger.warning(
            "进入销售页后仍缺少账号标识 {}，当前 Cookie({})：{}",
            ", ".join(missing),
            len(names),
            ", ".join(sorted(n for n in names if n)) or "(空)",
        )
    return missing


def _wait_for_login_cookies(
    context,
    page: Page,
    *,
    required: tuple[str, ...] = SESSION_COOKIES,
    poll_ms: int = 500,
    log_every_s: float = 5.0,
    url_hint: str = "/sale/",
    settle_s: float = 3.0,
) -> list[str]:
    """等待登录完成，返回仍缺失的会话 Cookie。

    判定顺序：
    1. 会话 Cookie（sessionid / sid_guard）全部出现 —— 最可靠，立即返回；
    2. 页面已进入销售页（/sale/）—— 兼容旧行为，给站点 settle_s 秒补写
       Cookie 后返回，避免在 Cookie 读取异常时无限等待、浏览器关不掉。

    用户主动关闭浏览器时抛 RuntimeError。
    """
    last_log = 0.0
    dumped = False
    while True:
        try:
            cookies = context.cookies()
        except Exception as exc:  # 浏览器已关闭
            if _is_browser_closed_error(exc):
                raise RuntimeError("浏览器已关闭，登录未完成") from exc
            raise

        names = {c.get("name") for c in cookies}
        missing = [n for n in required if n not in names]
        if not missing:
            logger.warning("登录会话 Cookie 已就绪（共 {} 个）", len(names))
            return []

        try:
            url = page.url
        except Exception:
            url = "?"

        if not dumped and url_hint in url:
            dumped = True
            logger.warning(
                "已进入 {} 页面，当前 Cookie({})：{}",
                url_hint,
                len(names),
                ", ".join(sorted(n for n in names if n)) or "(空)",
            )

        # 兜底：已经进到销售页，说明登录动作完成了，给站点一点时间补写 Cookie 后放行
        if url_hint in url:
            logger.warning("已进入销售页，等待 {}s 让站点补写 Cookie…", settle_s)
            try:
                page.wait_for_timeout(int(settle_s * 1000))
            except Exception as exc:
                if _is_browser_closed_error(exc):
                    raise RuntimeError("浏览器已关闭，登录未完成") from exc
                raise
            final_names = {c.get("name") for c in context.cookies()}
            still = [n for n in required if n not in final_names]
            if still:
                logger.warning(
                    "进入销售页后仍未取得会话 Cookie {}，当前 Cookie({})：{}",
                    ", ".join(still),
                    len(final_names),
                    ", ".join(sorted(n for n in final_names if n)) or "(空)",
                )
            return still

        now = time.monotonic()
        if now - last_log >= log_every_s:
            last_log = now
            logger.warning(
                "等待登录… 页面={} Cookie {} 个，缺少 {}",
                url,
                len(names),
                ", ".join(missing),
            )

        try:
            page.wait_for_timeout(poll_ms)
        except Exception as exc:  # 页面/浏览器已关闭
            if _is_browser_closed_error(exc):
                raise RuntimeError("浏览器已关闭，登录未完成") from exc
            raise


_READ_ACCOUNT_ID_JS = """
(name) => {
  try {
    const m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
    if (m) return decodeURIComponent(m[1]);
  } catch (e) {}
  try {
    const direct = localStorage.getItem(name);
    if (direct) return direct;
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.toLowerCase() === name.toLowerCase()) return localStorage.getItem(k);
    }
  } catch (e) {}
  try {
    const m2 = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
    if (m2) return decodeURIComponent(m2[1]);
  } catch (e) {}
  return null;
}
"""


def _ensure_account_ids(context, page: Page) -> list[str]:
    """确保账号标识存在于上下文的 Cookie 中。

    adUserId 是接口需要的必需项；rootAdUserId 站点已基本不再下发，能取到就一并保存。
    两者都是非 HttpOnly，站点可能放在 Cookie，也可能只在 localStorage，
    这里从页面读取后回填为 Cookie，以便 storage_state 一并保存。
    返回仍然缺失的必需项名称列表。
    """
    present = {c.get("name") for c in context.cookies()}
    wanted = [n for n in (*ACCOUNT_COOKIES, *OPTIONAL_ACCOUNT_COOKIES) if n not in present]
    if not wanted:
        return []

    recovered: list[dict] = []
    for name in wanted:
        try:
            value = page.evaluate(_READ_ACCOUNT_ID_JS, name)
        except Exception:
            value = None
        if value:
            recovered.append(
                {"name": name, "value": str(value), "domain": COOKIE_DOMAIN, "path": "/"}
            )

    if recovered:
        try:
            context.add_cookies(recovered)
            logger.warning(
                "已从页面存储回填账号标识：{}", ", ".join(c["name"] for c in recovered)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("回填账号标识失败：{}", exc)

    final = {c.get("name") for c in context.cookies()}
    return [n for n in ACCOUNT_COOKIES if n not in final]


def _verify_saved_auth(target: Path) -> list[str]:
    """确认保存下来的 auth.json 里带了会话 Cookie。

    返回仍缺失的必需账号标识（adUserId），供调用方提示。
    会话 Cookie 缺失则直接报错——那才是登录没成功。
    """
    import json

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return []
    names = {c.get("name") for c in data.get("cookies", [])}
    missing_session = [n for n in SESSION_COOKIES if n not in names]
    if missing_session:
        raise RuntimeError(
            "登录未完成：保存的登录信息里缺少会话 Cookie " + "、".join(missing_session)
        )
    return [n for n in ACCOUNT_COOKIES if n not in names]


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
            launch_kwargs = {
                "headless": False,
                "args": list(LAUNCH_ARGS),
            }
            try:
                # 优先调用系统真实 Chrome 渠道
                browser = playwright.chromium.launch(
                    channel="chrome",
                    **launch_kwargs,
                )
            except Exception:
                browser = playwright.chromium.launch(**launch_kwargs)
            context = browser.new_context(**browser_context_kwargs())
            # 登录与下载共用同一份设备标识，避免被当成新设备
            apply_device_cookies(context)
            page = context.new_page()
            page.add_init_script(STEALTH_INIT_SCRIPT)
            page.goto(HOME_URL, timeout=60_000)
            if credentials:
                _try_autofill_changdu_login(page, credentials[0], credentials[1])
            missing_session = _wait_for_login_cookies(context, page)
            # 会话 Cookie 已就绪：进入销售页，触发站点下发账号标识
            try:
                page.goto(SALE_PAGE_URL, timeout=60_000)
                page.wait_for_load_state("domcontentloaded", timeout=15_000)
            except Exception as exc:  # noqa: BLE001
                logger.warning("进入销售页失败（不影响会话保存）：{}", exc)

            missing_account = _wait_for_account_cookies(context, page)
            if missing_account:
                missing_account = _ensure_account_ids(context, page)

            context.storage_state(path=str(target))
            # 登录过程中可能刷新了设备标识，一并保存供后续下载复用
            save_device_cookies(context.cookies())
            missing_after_save = _verify_saved_auth(target)
            browser.close()
            leftover = sorted(set(missing_account) | set(missing_after_save))
            if leftover:
                logger.warning(
                    "登录已完成，但未取得账号标识 {}；下载接口可能失败，如遇报错请重新登录",
                    ", ".join(leftover),
                )
            if missing_session:
                logger.warning("登录完成但未读到会话 Cookie：{}", ", ".join(missing_session))
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
