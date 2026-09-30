"""常读平台 Playwright / 下载请求共用的浏览器指纹，降低自动化特征。"""

from __future__ import annotations

import urllib.parse

# 与当前主流 Chromium 对齐的桌面 Chrome UA 及 Client Hints（登录与下载共用）
CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
SEC_CH_UA = '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"'
SEC_CH_UA_MOBILE = "?0"
SEC_CH_UA_PLATFORM = '"Windows"'

BROWSER_LOCALE = "zh-CN"
BROWSER_TIMEZONE = "Asia/Shanghai"
BROWSER_VIEWPORT = {"width": 1440, "height": 900}
ACCEPT_LANGUAGE = "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7"

HOME_ORIGIN = "https://www.changdupingtai.com"
DOWNLOAD_CENTER_REFERER = f"{HOME_ORIGIN}/sale/download-center"

# 拟真 Stealth 补丁（参考 playwright-stealth 与 puppeteer-extra-plugin-stealth）：
# 1. 在原型链层清除 navigator.webdriver，确保 hasOwnProperty 为 false；
# 2. 补全真实的 window.chrome 原生对象结构（含 [native code] 函数签名）；
# 3. 模拟真实的 navigator.plugins 数组（PDF 查看器等内置插件）；
# 4. 遮蔽 WebGL SwiftShader 软件渲染指纹，模拟正常 Intel 显卡特征。
STEALTH_INIT_SCRIPT = """
(function() {
  // 1. 原型链 webdriver 彻底清除
  try {
    const proto = Object.getPrototypeOf(navigator);
    if ('webdriver' in proto) {
      delete proto.webdriver;
    }
  } catch (e) {}
  try {
    delete navigator.webdriver;
  } catch (e) {}

  // 2. 补齐真实的 window.chrome 对象与 [native code] 原生函数特征
  if (!window.chrome) {
    window.chrome = {};
  }
  const makeNativeString = function(fnName) {
    return 'function ' + fnName + '() { [native code] }';
  };
  const dummyFn = function(name) {
    const fn = function() {};
    fn.toString = function() { return makeNativeString(name); };
    return fn;
  };
  if (!window.chrome.app) {
    window.chrome.app = {
      isInstalled: false,
      InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
      RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' },
      getDetails: dummyFn('getDetails'),
      getIsInstalled: dummyFn('getIsInstalled'),
      installState: dummyFn('installState'),
      runningState: dummyFn('runningState'),
    };
  }
  if (!window.chrome.csi) {
    window.chrome.csi = dummyFn('csi');
  }
  if (!window.chrome.loadTimes) {
    window.chrome.loadTimes = dummyFn('loadTimes');
  }
  if (!window.chrome.runtime) {
    window.chrome.runtime = {
      OnInstalledReason: { CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' },
      OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' },
      PlatformArch: { ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
      PlatformNaclArch: { ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
      PlatformOs: { ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win' },
      RequestUpdateCheckStatus: { NO_UPDATE: 'no_update', THROTTLED: 'throttled', UPDATE_AVAILABLE: 'update_available' },
      connect: dummyFn('connect'),
      sendMessage: dummyFn('sendMessage'),
    };
  }

  // 3. 补全常见插件数组，避免 Headless 模式下 plugins 长度为 0 的硬伤
  if (!navigator.plugins || navigator.plugins.length === 0) {
    const pluginList = [
      { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'WebKit built-in PDF', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
    ];
    Object.defineProperty(navigator, 'plugins', {
      get: function() {
        const arr = [...pluginList];
        arr.item = function(i) { return arr[i] || null; };
        arr.namedItem = function(name) { return arr.find(function(p) { return p.name === name; }) || null; };
        arr.refresh = function() {};
        return arr;
      },
    });
  }

  // 4. 遮蔽 WebGL SwiftShader，模拟主流显卡特征
  try {
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(param) {
      if (param === 37445) return 'Google Inc. (Intel)';
      if (param === 37446) return 'ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)';
      return getParameter.apply(this, arguments);
    };
    if (typeof WebGL2RenderingContext !== 'undefined') {
      const getParameter2 = WebGL2RenderingContext.prototype.getParameter;
      WebGL2RenderingContext.prototype.getParameter = function(param) {
        if (param === 37445) return 'Google Inc. (Intel)';
        if (param === 37446) return 'ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)';
        return getParameter2.apply(this, arguments);
      };
    }
  } catch (e) {}

  Object.defineProperty(navigator, 'languages', {
    get: function() { return Object.freeze(['zh-CN', 'zh', 'en-US', 'en']); },
  });
})();
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
            "sec-ch-ua": SEC_CH_UA,
            "sec-ch-ua-mobile": SEC_CH_UA_MOBILE,
            "sec-ch-ua-platform": SEC_CH_UA_PLATFORM,
        },
    }
    if storage_state:
        kwargs["storage_state"] = storage_state
    return kwargs


def _safe_header_str(val: Any) -> str:
    """确保输入字符串符合 HTTP 标头规范，非 latin-1 字符（如中文）转为安全 URL 百分号编码。"""
    s = str(val) if val is not None else ""
    try:
        s.encode("latin-1")
        return s
    except UnicodeEncodeError:
        return urllib.parse.quote(s, safe="/:@=+%$~*-_. ")


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
        "sec-ch-ua": SEC_CH_UA,
        "sec-ch-ua-mobile": SEC_CH_UA_MOBILE,
        "sec-ch-ua-platform": SEC_CH_UA_PLATFORM,
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site",
    }
    if cookie:
        try:
            cookie.encode("latin-1")
            headers["Cookie"] = cookie
        except UnicodeEncodeError:
            # 兜底清洗：若外部传入未经清洗的 Cookie 字符串，逐字转义非 latin-1 字符
            headers["Cookie"] = "".join(
                ch if ord(ch) <= 255 else urllib.parse.quote(ch) for ch in cookie
            )
    return headers


def format_cookie_header(cookies: list[dict]) -> str:
    parts: list[str] = []
    for item in cookies or []:
        name = item.get("name")
        value = item.get("value")
        if name and value is not None:
            safe_name = _safe_header_str(name)
            safe_value = _safe_header_str(value)
            parts.append(f"{safe_name}={safe_value}")
    return "; ".join(parts)
