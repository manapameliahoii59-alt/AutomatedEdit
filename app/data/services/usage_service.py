from app.data.api.api import get_api


class UsageService:
    @staticmethod
    def report(event: str, success: bool = True, duration_ms: int = 0, meta: str = ''):
        api = get_api()
        if hasattr(api, 'report_usage'):
            api.report_usage(event, success=success, duration_ms=duration_ms, meta=meta)
