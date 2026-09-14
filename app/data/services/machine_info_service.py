"""桌面端机器信息上报：每天最多一次，失败静默。"""

from __future__ import annotations

import datetime
import threading

from qfluentwidgets import qconfig

from app.common.config import cfg
from app.common.machine_info import collect_machine_info
from app.common.my_logger import my_logger as logger
from app.data.api.api import ApiError, get_api


class MachineInfoService:
    @staticmethod
    def report_daily() -> None:
        threading.Thread(
            target=MachineInfoService._run,
            daemon=True,
            name="machine-info-report",
        ).start()

    @staticmethod
    def _run() -> None:
        today = datetime.date.today().isoformat()
        if (cfg.machine_info_reported_date.value or "") == today:
            return

        payload = collect_machine_info()
        api = get_api()
        if not hasattr(api, "report_machine_info"):
            return
        try:
            api.report_machine_info(payload)
        except ApiError as exc:
            logger.debug("上报机器信息失败: {}", exc)
            return
        except Exception as exc:
            logger.debug("上报机器信息异常: {}", exc)
            return

        try:
            qconfig.set(cfg.machine_info_reported_date, today)
        except Exception:
            pass
