from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class SecretsOut(BaseModel):
    deepseek_keys: str = ""
    dashscope_key: str = ""
    plan_decrypt_key: str = ""


class PlanJobCreateRequest(BaseModel):
    project_name: str = Field(min_length=1, max_length=256)
    drama_name: str = Field(min_length=1, max_length=256)
    steps: list[dict[str, Any]]
    ordered_files: list[str] = Field(min_length=1)


class PlanJobCreateResponse(BaseModel):
    job_id: str


class PlanJobStatusOut(BaseModel):
    job_id: str
    status: str
    progress: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class PlanJobResultOut(BaseModel):
    job_id: str
    ciphertext: str
    nonce: str
    key_id: str = "default"


class UsageReport(BaseModel):
    event: str = Field(min_length=1, max_length=64)
    success: bool = True
    duration_ms: int = 0
    meta: str = ""
    client_version: str = ""


class UsageEventOut(BaseModel):
    id: int
    user_id: int
    event: str
    success: bool
    duration_ms: int
    meta: str
    client_version: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DailyActivityOut(BaseModel):
    id: int
    user_id: int
    activity_date: date
    login_at: datetime | None
    logout_at: datetime | None
    downloaded_dramas: str
    planned_dramas: str = "[]"
    clipped_dramas: str
    plan_count: int = 0
    clip_count: int
    updated_at: datetime

    model_config = {"from_attributes": True}


class DailyQuotaOut(BaseModel):
    """今日策划/剪辑配额与使用情况。"""

    activity_date: date
    plan_count: int
    clip_count: int
    plan_limit: int
    clip_limit: int
    planned_dramas: list[str]
    clipped_dramas: list[str]
    can_plan: bool
    can_clip: bool


class QuotaCheckRequest(BaseModel):
    action: str = Field(pattern="^(plan|clip)$")
    drama_name: str = Field(min_length=1, max_length=256)


class QuotaCheckOut(BaseModel):
    allowed: bool
    message: str = ""
    quota: DailyQuotaOut


class VideoDownloadSettings(BaseModel):
    """视频下载页配置（对应客户端 cfg.video_download_* 及默认集数）。"""

    episode_from: int = Field(default=1, ge=1, le=10)
    episode_to: int = Field(default=10, ge=1, le=10)
    download_dir: str = ""
    auto_unzip: bool = True
    auto_transcribe: bool = True
    auto_import_clip: bool = True
    auto_start_after_add: bool = True
    changdu_email: str = ""
    changdu_password: str = ""

    model_config = {"extra": "allow"}

    @model_validator(mode="after")
    def _clamp_episode_range(self) -> "VideoDownloadSettings":
        self.episode_from = max(1, min(self.episode_from, 10))
        self.episode_to = max(self.episode_from, min(self.episode_to, 10))
        return self


class VideoDownloadSettingsPatch(BaseModel):
    episode_from: int | None = Field(default=None, ge=1, le=10)
    episode_to: int | None = Field(default=None, ge=1, le=10)
    download_dir: str | None = None
    auto_unzip: bool | None = None
    auto_transcribe: bool | None = None
    auto_import_clip: bool | None = None
    auto_start_after_add: bool | None = None
    changdu_email: str | None = None
    changdu_password: str | None = None

    model_config = {"extra": "allow"}


class UserSettingsPatch(BaseModel):
    """部分更新用户配置；未出现的命名空间保持不变，命名空间内仅更新提供的字段。"""

    video_download: VideoDownloadSettingsPatch | None = None

    model_config = {"extra": "allow"}


class UserSettingsOut(BaseModel):
    """用户配置响应；已知命名空间带默认值，其余命名空间原样透传。"""

    video_download: VideoDownloadSettings = Field(default_factory=VideoDownloadSettings)
    updated_at: datetime | None = None

    model_config = {"extra": "allow"}
