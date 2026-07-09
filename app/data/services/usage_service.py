from app.data.api.api import ApiError, get_api
from app.data.services.quota_service import QuotaService


class UsageService:
    @staticmethod
    def report(event: str, success: bool = True, duration_ms: int = 0, meta: str = ""):
        api = get_api()
        if hasattr(api, "report_usage"):
            try:
                api.report_usage(event, success=success, duration_ms=duration_ms, meta=meta)
            except ApiError:
                pass

    @staticmethod
    def report_app_login() -> None:
        UsageService.report("app_login")
        QuotaService.instance().refresh()

    @staticmethod
    def report_app_close() -> None:
        UsageService.report("app_close")

    @staticmethod
    def report_download_dramas(names: list[str]) -> None:
        for name in names:
            text = (name or "").strip()
            if text:
                UsageService.report("download_drama", meta=text)

    @staticmethod
    def report_plan_drama(name: str) -> None:
        text = (name or "").strip()
        if not text:
            return
        api = get_api()
        if hasattr(api, "report_usage"):
            try:
                api.report_usage("plan_drama", meta=text)
            except ApiError:
                return
        QuotaService.instance().mark_planned(text)

    @staticmethod
    def report_clip_drama(name: str) -> None:
        text = (name or "").strip()
        if not text:
            return
        api = get_api()
        if hasattr(api, "report_usage"):
            try:
                api.report_usage("clip_drama", meta=text)
            except ApiError:
                return
        QuotaService.instance().mark_clipped(text)
