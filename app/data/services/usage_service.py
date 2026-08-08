import threading

from app.data.api.api import ApiError, get_api
from app.data.services.quota_service import QuotaService


def _run_in_background(fn) -> None:
    """用量上报不阻塞 UI；失败静默。"""
    threading.Thread(target=fn, daemon=True, name="usage-report").start()


class UsageService:
    @staticmethod
    def report(event: str, success: bool = True, duration_ms: int = 0, meta: str = ""):
        def _do():
            api = get_api()
            if hasattr(api, "report_usage"):
                try:
                    api.report_usage(
                        event, success=success, duration_ms=duration_ms, meta=meta
                    )
                except ApiError:
                    pass

        _run_in_background(_do)

    @staticmethod
    def report_app_login() -> None:
        def _do():
            api = get_api()
            if hasattr(api, "report_usage"):
                try:
                    api.report_usage("app_login")
                except ApiError:
                    pass
            QuotaService.instance().refresh()

        _run_in_background(_do)

    @staticmethod
    def report_app_close() -> None:
        UsageService.report("app_close")

    @staticmethod
    def report_download_dramas(names: list[str]) -> None:
        cleaned = [(name or "").strip() for name in names]
        cleaned = [n for n in cleaned if n]
        if not cleaned:
            return

        def _do():
            for text in cleaned:
                api = get_api()
                if hasattr(api, "report_usage"):
                    try:
                        api.report_usage("download_drama", meta=text)
                    except ApiError:
                        pass

        _run_in_background(_do)

    @staticmethod
    def report_plan_drama(name: str, plan_mode: str | None = None) -> None:
        text = (name or "").strip()
        if not text:
            return

        mode = str(plan_mode or "").strip().lower() or None
        if mode not in {"short", "long", "mixed"}:
            mode = None

        def _do():
            api = get_api()
            if hasattr(api, "report_usage"):
                try:
                    api.report_usage("plan_drama", meta=text, plan_mode=mode)
                except ApiError:
                    return
            QuotaService.instance().mark_planned(text)

        _run_in_background(_do)

    @staticmethod
    def report_clip_drama(name: str) -> None:
        text = (name or "").strip()
        if not text:
            return

        def _do():
            api = get_api()
            if hasattr(api, "report_usage"):
                try:
                    api.report_usage("clip_drama", meta=text)
                except ApiError:
                    return
            QuotaService.instance().mark_clipped(text)

        _run_in_background(_do)
