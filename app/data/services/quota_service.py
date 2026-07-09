"""每日策划/剪辑剧目配额（服务端校验 + 本地缓存）。"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.data.api.api import ApiError, get_api
from app.data.services.access_control_service import access_control


@dataclass
class DailyQuota:
    plan_count: int = 0
    clip_count: int = 0
    plan_limit: int = 0
    clip_limit: int = 0
    planned_dramas: list[str] = field(default_factory=list)
    clipped_dramas: list[str] = field(default_factory=list)
    can_plan: bool = True
    can_clip: bool = True

    @classmethod
    def from_api(cls, data: dict | None) -> "DailyQuota":
        if not data:
            return cls()
        return cls(
            plan_count=int(data.get("plan_count") or 0),
            clip_count=int(data.get("clip_count") or 0),
            plan_limit=int(data.get("plan_limit") or 0),
            clip_limit=int(data.get("clip_limit") or 0),
            planned_dramas=list(data.get("planned_dramas") or []),
            clipped_dramas=list(data.get("clipped_dramas") or []),
            can_plan=bool(data.get("can_plan", True)),
            can_clip=bool(data.get("can_clip", True)),
        )


class QuotaService:
    _instance: "QuotaService | None" = None
    _quota: DailyQuota = DailyQuota()

    @classmethod
    def instance(cls) -> "QuotaService":
        if cls._instance is None:
            cls._instance = QuotaService()
        return cls._instance

    def refresh(self) -> DailyQuota:
        api = get_api()
        if not hasattr(api, "fetch_daily_quota"):
            return self._quota
        try:
            data = api.fetch_daily_quota()
            self._quota = DailyQuota.from_api(data)
        except ApiError:
            pass
        return self._quota

    def get_quota(self) -> DailyQuota:
        return self._quota

    def _drama_in_list(self, drama_name: str, names: list[str]) -> bool:
        drama_name = (drama_name or "").strip()
        return bool(drama_name and drama_name in names)

    def _deny_message(self) -> str:
        return access_control.random_error()

    def can_plan(self, drama_name: str, *, refresh: bool = True) -> tuple[bool, str]:
        quota = self.refresh() if refresh else self._quota
        drama_name = (drama_name or "").strip()
        if not drama_name:
            return True, ""
        if self._drama_in_list(drama_name, quota.planned_dramas):
            return True, ""
        if quota.plan_limit > 0 and quota.plan_count >= quota.plan_limit:
            return False, self._deny_message()
        return True, ""

    def can_clip(self, drama_name: str, *, refresh: bool = True) -> tuple[bool, str]:
        quota = self.refresh() if refresh else self._quota
        drama_name = (drama_name or "").strip()
        if not drama_name:
            return True, ""
        if self._drama_in_list(drama_name, quota.clipped_dramas):
            return True, ""
        if quota.clip_limit > 0 and quota.clip_count >= quota.clip_limit:
            return False, self._deny_message()
        return True, ""

    def check_remote(self, action: str, drama_name: str) -> tuple[bool, str]:
        api = get_api()
        if not hasattr(api, "check_daily_quota"):
            return True, ""
        try:
            data = api.check_daily_quota(action, drama_name) or {}
            if data.get("quota"):
                self._quota = DailyQuota.from_api(data["quota"])
            if data.get("allowed"):
                return True, ""
            return False, self._deny_message()
        except ApiError as exc:
            if exc.status_code == 429:
                return False, self._deny_message()
            return True, ""

    def mark_planned(self, drama_name: str) -> None:
        drama_name = (drama_name or "").strip()
        if not drama_name or drama_name in self._quota.planned_dramas:
            return
        self._quota.planned_dramas.append(drama_name)
        self._quota.plan_count = len(self._quota.planned_dramas)

    def mark_clipped(self, drama_name: str) -> None:
        drama_name = (drama_name or "").strip()
        if not drama_name or drama_name in self._quota.clipped_dramas:
            return
        self._quota.clipped_dramas.append(drama_name)
        self._quota.clip_count = len(self._quota.clipped_dramas)
