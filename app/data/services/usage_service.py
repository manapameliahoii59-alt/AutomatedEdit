import threading

from app.data.api.api import ApiError, get_api
from app.data.services.quota_service import QuotaService


def _run_in_background(fn) -> None:
    """用量上报不阻塞 UI；失败静默。"""
    threading.Thread(target=fn, daemon=True, name="usage-report").start()


class UsageService:
    @staticmethod
    def report(
        event: str,
        success: bool = True,
        duration_ms: int = 0,
        meta: str = "",
        *,
        plan_mode: str | None = None,
        plan_model: str = "",
        transcribe_ms: int = 0,
        plan_ms: int = 0,
        render_ms: int = 0,
        encoder: str = "",
        resolution: str = "",
        cache_ms: int = 0,
        compose_ms: int = 0,
        render_engine: str = "",
    ):
        def _do():
            api = get_api()
            if hasattr(api, "report_usage"):
                try:
                    api.report_usage(
                        event,
                        success=success,
                        duration_ms=duration_ms,
                        meta=meta,
                        plan_mode=plan_mode,
                        plan_model=plan_model,
                        transcribe_ms=transcribe_ms,
                        plan_ms=plan_ms,
                        render_ms=render_ms,
                        encoder=encoder,
                        resolution=resolution,
                        cache_ms=cache_ms,
                        compose_ms=compose_ms,
                        render_engine=render_engine,
                    )
                except ApiError:
                    pass

        _run_in_background(_do)

    @staticmethod
    def report_render(
        result,
        *,
        event: str = "batch_all_render",
        meta: str = "",
        transcribe_ms: int = 0,
        plan_ms: int = 0,
        render_ms: int = 0,
    ) -> None:
        """上报渲染结果：实际编码器 + 分辨率 + 缓存/合成耗时 + 阶段耗时。"""
        actual_render_ms = render_ms or int(getattr(result, "total_seconds", 0.0) * 1000)
        total_duration = (
            (transcribe_ms + plan_ms + actual_render_ms)
            if (transcribe_ms or plan_ms)
            else actual_render_ms
        )
        UsageService.report(
            event,
            success=getattr(result, "success_count", 0) > 0,
            duration_ms=total_duration,
            meta=meta,
            transcribe_ms=transcribe_ms,
            plan_ms=plan_ms,
            render_ms=actual_render_ms,
            encoder=str(getattr(result, "encoder", "") or ""),
            resolution=str(getattr(result, "resolution", "") or ""),
            cache_ms=int(getattr(result, "cache_seconds", 0.0) * 1000),
            compose_ms=int(getattr(result, "compose_seconds", 0.0) * 1000),
            render_engine=str(getattr(result, "render_engine", "") or ""),
        )

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

            from app.data.services.machine_info_service import MachineInfoService

            MachineInfoService.report_daily()

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
                        continue
                QuotaService.instance().mark_downloaded(text)

        _run_in_background(_do)

    @staticmethod
    def report_plan_drama(
        name: str,
        plan_mode: str | None = None,
        *,
        duration_ms: int = 0,
        plan_ms: int = 0,
        plan_model: str = "",
    ) -> None:
        text = (name or "").strip()
        if not text:
            return

        mode = str(plan_mode or "").strip().lower() or None
        if mode not in {"short", "long", "mixed"}:
            mode = None

        cost = plan_ms or duration_ms

        def _do():
            api = get_api()
            if hasattr(api, "report_usage"):
                try:
                    api.report_usage(
                        "plan_drama",
                        meta=text,
                        plan_mode=mode,
                        duration_ms=cost,
                        plan_ms=cost,
                        plan_model=plan_model,
                    )
                except ApiError:
                    return
            QuotaService.instance().mark_planned(text)

        _run_in_background(_do)

    @staticmethod
    def report_clip_drama(
        name: str,
        *,
        duration_ms: int = 0,
        render_ms: int = 0,
    ) -> None:
        text = (name or "").strip()
        if not text:
            return

        cost = render_ms or duration_ms

        def _do():
            api = get_api()
            if hasattr(api, "report_usage"):
                try:
                    api.report_usage(
                        "clip_drama",
                        meta=text,
                        duration_ms=cost,
                        render_ms=cost,
                    )
                except ApiError:
                    return
            QuotaService.instance().mark_clipped(text)

        _run_in_background(_do)
