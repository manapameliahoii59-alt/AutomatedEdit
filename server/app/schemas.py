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
    # 可选：客户端策划设置（缺省则服务端用默认 15 条 / 720s / 分 A/B）
    target_clips_count: int | None = Field(default=None, ge=5, le=15)
    max_duration_seconds: int | None = Field(default=None, ge=120, le=900)
    min_duration_seconds: int | None = Field(default=None, ge=120, le=900)
    split_ab: bool | None = None


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
    auto_plan: bool = True
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
    auto_plan: bool | None = None
    auto_import_clip: bool | None = None
    auto_start_after_add: bool | None = None
    changdu_email: str | None = None
    changdu_password: str | None = None

    model_config = {"extra": "allow"}


class PlanSettings(BaseModel):
    """自动化剪辑「策划设置」（短片/长片模式 + 条数 / 最长时长）。"""

    mode: str = Field(default="long")
    clip_count: int = Field(default=15, ge=5, le=15)
    max_duration_sec: int = Field(default=720, ge=300, le=900)
    short_clip_count: int = Field(default=15, ge=5, le=15)
    short_max_duration_sec: int = Field(default=300, ge=120, le=300)

    model_config = {"extra": "allow"}

    @model_validator(mode="after")
    def _clamp(self) -> "PlanSettings":
        self.mode = "short" if str(self.mode or "").strip().lower() == "short" else "long"
        self.clip_count = max(5, min(15, int(self.clip_count)))
        self.max_duration_sec = max(300, min(900, int(self.max_duration_sec)))
        self.short_clip_count = max(5, min(15, int(self.short_clip_count)))
        self.short_max_duration_sec = max(120, min(300, int(self.short_max_duration_sec)))
        return self


class PlanSettingsPatch(BaseModel):
    mode: str | None = None
    clip_count: int | None = Field(default=None, ge=5, le=15)
    max_duration_sec: int | None = Field(default=None, ge=300, le=900)
    short_clip_count: int | None = Field(default=None, ge=5, le=15)
    short_max_duration_sec: int | None = Field(default=None, ge=120, le=300)

    model_config = {"extra": "allow"}


class OverlayPosSettings(BaseModel):
    x_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    y_pct: float = Field(default=0.0, ge=0.0, le=100.0)

    model_config = {"extra": "allow"}

    @model_validator(mode="after")
    def _clamp(self) -> "OverlayPosSettings":
        self.x_pct = max(0.0, min(100.0, float(self.x_pct)))
        self.y_pct = max(0.0, min(100.0, float(self.y_pct)))
        return self


class OverlayTextStyleSettings(BaseModel):
    """画面叠字样式（剧名 / 提示共用结构；横竖各自位置）。"""

    text: str = ""
    font: str = "msyh"
    fontsize: int = Field(default=16, ge=8, le=200)
    color: str = "#FFFFFF"
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    layout: str = Field(default="horizontal")
    # 兼容旧扁平字段
    x_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    y_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    portrait: OverlayPosSettings | None = None
    landscape: OverlayPosSettings | None = None

    model_config = {"extra": "allow"}

    @model_validator(mode="after")
    def _clamp(self) -> "OverlayTextStyleSettings":
        self.text = str(self.text) if self.text is not None else ""
        font = str(self.font or "msyh").strip().lower()
        allowed = {"msyh", "simhei", "simsun", "simkai", "msyhbd"}
        self.font = font if font in allowed else "msyh"
        self.fontsize = max(8, min(200, int(self.fontsize)))
        color = str(self.color or "#FFFFFF").strip()
        if color.startswith("#"):
            color = color[1:]
        if len(color) == 3 and all(c in "0123456789abcdefABCDEF" for c in color):
            color = "".join(c * 2 for c in color)
        if len(color) == 6 and all(c in "0123456789abcdefABCDEF" for c in color):
            self.color = f"#{color.upper()}"
        else:
            self.color = "#FFFFFF"
        self.opacity = max(0.0, min(1.0, float(self.opacity)))
        self.layout = (
            "vertical"
            if str(self.layout or "").strip().lower() == "vertical"
            else "horizontal"
        )

        if self.portrait is None:
            if self.x_pct is not None or self.y_pct is not None:
                self.portrait = OverlayPosSettings(
                    x_pct=float(self.x_pct if self.x_pct is not None else 0.0),
                    y_pct=float(self.y_pct if self.y_pct is not None else 0.0),
                )
            else:
                self.portrait = OverlayPosSettings(x_pct=4.0, y_pct=94.5)
        if self.landscape is None:
            self.landscape = OverlayPosSettings(
                x_pct=float(self.portrait.x_pct),
                y_pct=float(self.portrait.y_pct),
            )
        # 清理扁平字段，统一以 portrait/landscape 为准
        self.x_pct = None
        self.y_pct = None
        return self


def _default_overlay_title() -> OverlayTextStyleSettings:
    return OverlayTextStyleSettings(
        text="《{name}》",
        font="msyh",
        fontsize=22,
        color="#FFFFFF",
        opacity=0.8,
        layout="horizontal",
        portrait=OverlayPosSettings(x_pct=4.0, y_pct=94.5),
        landscape=OverlayPosSettings(x_pct=2.5, y_pct=90.0),
    )


def _default_overlay_disclaimer() -> OverlayTextStyleSettings:
    return OverlayTextStyleSettings(
        text="内容纯属虚构 请勿带入现实",
        font="msyh",
        fontsize=14,
        color="#FFFFFF",
        opacity=0.6,
        layout="horizontal",
        portrait=OverlayPosSettings(x_pct=4.0, y_pct=96.9),
        landscape=OverlayPosSettings(x_pct=2.5, y_pct=94.0),
    )


class ClipEditSettings(BaseModel):
    """自动化剪辑页配置（文件名标识 + 画面叠字）。"""

    export_name_tag: str = Field(default="", max_length=64)
    overlay_title: OverlayTextStyleSettings = Field(
        default_factory=_default_overlay_title
    )
    overlay_disclaimer: OverlayTextStyleSettings = Field(
        default_factory=_default_overlay_disclaimer
    )

    model_config = {"extra": "allow"}

    @model_validator(mode="after")
    def _clamp(self) -> "ClipEditSettings":
        self.export_name_tag = str(self.export_name_tag or "").strip()[:64]
        return self


class ClipEditSettingsPatch(BaseModel):
    export_name_tag: str | None = Field(default=None, max_length=64)
    overlay_title: OverlayTextStyleSettings | dict[str, Any] | None = None
    overlay_disclaimer: OverlayTextStyleSettings | dict[str, Any] | None = None

    model_config = {"extra": "allow"}

    @model_validator(mode="after")
    def _normalize_overlays(self) -> "ClipEditSettingsPatch":
        if isinstance(self.overlay_title, dict):
            self.overlay_title = OverlayTextStyleSettings.model_validate(
                self.overlay_title
            )
        if isinstance(self.overlay_disclaimer, dict):
            self.overlay_disclaimer = OverlayTextStyleSettings.model_validate(
                self.overlay_disclaimer
            )
        return self


class UserSettingsPatch(BaseModel):
    """部分更新用户配置；未出现的命名空间保持不变，命名空间内仅更新提供的字段。"""

    video_download: VideoDownloadSettingsPatch | None = None
    plan: PlanSettingsPatch | None = None
    clip_edit: ClipEditSettingsPatch | None = None

    model_config = {"extra": "allow"}


class UserSettingsOut(BaseModel):
    """用户配置响应；已知命名空间带默认值，其余命名空间原样透传。"""

    video_download: VideoDownloadSettings = Field(default_factory=VideoDownloadSettings)
    plan: PlanSettings = Field(default_factory=PlanSettings)
    clip_edit: ClipEditSettings = Field(default_factory=ClipEditSettings)
    updated_at: datetime | None = None

    model_config = {"extra": "allow"}


class ClientVersionOut(BaseModel):
    latest: str = ""
    min_supported: str = ""
    download_url: str = ""
    changelog: str = ""
