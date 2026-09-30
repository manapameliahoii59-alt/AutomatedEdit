import pytest
from unittest.mock import MagicMock

from app.data.services.batch_download_service import (
    _resolve_episode_range,
    _transcode_poll_interval_sec,
)
from app.data.services.changdu_browser import (
    CHROME_USER_AGENT,
    SEC_CH_UA,
    STEALTH_INIT_SCRIPT,
    browser_context_kwargs,
    zip_download_headers,
)
from app.ui.views.video_download.view_model import (
    VideoDownloadTarget,
    VideoDownloadViewModel,
)


class TestAntiCrawlerStealth:
    def test_stealth_script_in_playwright(self):
        """验证 Playwright 注入补丁后，webdriver 彻底隐匿且原生对象特征完备。"""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
            context = browser.new_context()
            page = context.new_page()
            page.add_init_script(STEALTH_INIT_SCRIPT)
            page.goto("about:blank")

            # 1. 验证 webdriver 属性不存在于实例或原型链中
            has_own_webdriver = page.evaluate("() => navigator.hasOwnProperty('webdriver')")
            has_in_webdriver = page.evaluate("() => 'webdriver' in navigator")
            webdriver_val = page.evaluate("() => navigator.webdriver")
            assert has_own_webdriver is False
            assert has_in_webdriver is False
            assert webdriver_val is None

            # 2. 验证 window.chrome 与原生函数签名
            chrome_valid = page.evaluate(
                "() => !!window.chrome && !!window.chrome.runtime && typeof window.chrome.runtime.sendMessage === 'function'"
            )
            fn_str = page.evaluate("() => window.chrome.runtime.sendMessage.toString()")
            assert chrome_valid is True
            assert "[native code]" in fn_str

            # 3. 验证 plugins 拟真补全
            plugins_len = page.evaluate("() => navigator.plugins.length")
            assert plugins_len >= 5

            # 4. 验证 WebGL 软件渲染伪装
            webgl_info = page.evaluate("""() => {
                const canvas = document.createElement('canvas');
                const gl = canvas.getContext('webgl');
                if (!gl) return null;
                const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
                if (!debugInfo) return null;
                return {
                    vendor: gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL),
                    renderer: gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL),
                };
            }""")
            if webgl_info:
                assert "SwiftShader" not in webgl_info["renderer"]
                assert "Intel" in webgl_info["renderer"] or "Intel" in webgl_info["vendor"]

            browser.close()

    def test_client_hints_and_headers_consistency(self):
        """验证 Client Hints 与 User-Agent 版本完全一致。"""
        assert "131" in CHROME_USER_AGENT
        assert "131" in SEC_CH_UA

        kwargs = browser_context_kwargs()
        headers = kwargs["extra_http_headers"]
        assert headers["sec-ch-ua"] == SEC_CH_UA
        assert headers["sec-ch-ua-mobile"] == "?0"
        assert headers["sec-ch-ua-platform"] == '"Windows"'

        zip_headers = zip_download_headers()
        assert zip_headers["sec-ch-ua"] == SEC_CH_UA
        assert zip_headers["Sec-Fetch-Dest"] == "empty"
        assert zip_headers["Sec-Fetch-Mode"] == "cors"


class TestRequestDeduplicationAndPacing:
    def test_resolve_episode_range_skips_search_when_cached(self):
        """当 item 中已包含缓存的 bookId 和集数时，绝不二次发起网络搜索。"""
        mock_client = MagicMock()
        item = {
            "name": "测试短剧",
            "bookId": "book_12345",
            "episodeAmount": 80,
            "from": 1,
            "to": 15,
        }
        res = _resolve_episode_range(mock_client, item, {"from": 1, "to": 15})
        assert res["bookId"] == "book_12345"
        assert res["from"] == 1
        assert res["to"] == 15
        mock_client.find_drama_by_name.assert_not_called()

    def test_targets_to_payload_propagates_cached_metadata(self, mocker, qapp):
        """验证 ViewModel 生成 payload 时完整透传缓存的元数据。"""
        mocker.patch.object(VideoDownloadViewModel, "_load_settings_from_server")
        vm = VideoDownloadViewModel()
        target = VideoDownloadTarget(
            id="t1",
            name="首富归来",
            from_ep=1,
            to_ep=10,
            extra={
                "book_id": "sf_999",
                "episode_amount": 100,
            },
        )
        vm._targets = [target]
        payload = vm._targets_to_payload()
        assert len(payload) == 1
        assert payload[0]["name"] == "首富归来"
        assert payload[0]["bookId"] == "sf_999"
        assert payload[0]["episodeAmount"] == 100

    def test_transcode_poll_interval_with_jitter(self):
        """验证启用 jitter 时轮询时间在基础值附近波动，消除机械时钟周期。"""
        base = _transcode_poll_interval_sec(0, with_jitter=False)
        assert base == 60.0

        intervals = [_transcode_poll_interval_sec(0, with_jitter=True) for _ in range(10)]
        # 验证有波动且不全相等
        assert len(set(intervals)) > 1
        for val in intervals:
            assert 50.0 <= val <= 70.0

    def test_format_cookie_header_handles_chinese_characters(self):
        """验证 Cookie 中含有中文昵称或用户名时，自动进行 URL 百分号转义，避免 latin-1 异常。"""
        import http.client
        from app.data.services.changdu_browser import format_cookie_header

        cookies = [
            {"name": "sessionid", "value": "abc123xyz"},
            {"name": "username", "value": "桑悠恺"},
            {"name": "nickName", "value": "桑悠恺"},
            {"name": "userAvatar", "value": "https://example.com/avatar.jpg"},
        ]
        cookie_header = format_cookie_header(cookies)

        # 1. 验证必须能直接通过 latin-1 编码
        encoded = cookie_header.encode("latin-1")
        assert encoded is not None

        # 2. 验证中文被正确转义为 RFC 6265 兼容的百分号编码
        assert "%E6%A1%91%E6%82%A0%E6%81%BA" in cookie_header
        assert "桑悠恺" not in cookie_header

        # 3. 验证 http.client.putheader 绝不抛出 UnicodeEncodeError
        conn = http.client.HTTPConnection("example.com")
        conn.putrequest("GET", "/")
        conn.putheader("Cookie", cookie_header)
        conn.endheaders()

    def test_zip_download_headers_handles_raw_chinese_cookie_string(self):
        """验证外部传入未经清洗的原始中文 Cookie 字符串时，zip_download_headers 执行兜底清洗。"""
        raw_cookie = "adUserId=123; username=桑悠恺; role=admin"
        headers = zip_download_headers(cookie=raw_cookie)

        assert "Cookie" in headers
        headers["Cookie"].encode("latin-1")
        assert "%E6%A1%91%E6%82%A0%E6%81%BA" in headers["Cookie"]

