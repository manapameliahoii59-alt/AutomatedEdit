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
    # 成片全局倍速（缺省服务端用 1.15）
    global_speed: float | None = Field(default=None, ge=1.0, le=1.5)


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

    episode_from: int = Field(default=1, ge=1, le=15)
    episode_to: int = Field(default=15, ge=1, le=15)
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
        self.episode_from = max(1, min(self.episode_from, 15))
        self.episode_to = max(self.episode_from, min(self.episode_to, 15))
        return self


class VideoDownloadSettingsPatch(BaseModel):
    episode_from: int | None = Field(default=None, ge=1, le=15)
    episode_to: int | None = Field(default=None, ge=1, le=15)
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
    short_max_duration_sec: int = Field(default=300, ge=120, le=360)
    global_speed: float = Field(default=1.15, ge=1.0, le=1.5)

    model_config = {"extra": "allow"}

    @model_validator(mode="after")
    def _clamp(self) -> "PlanSettings":
        self.mode = "short" if str(self.mode or "").strip().lower() == "short" else "long"
        self.clip_count = max(5, min(15, int(self.clip_count)))
        self.max_duration_sec = max(300, min(900, int(self.max_duration_sec)))
        self.short_clip_count = max(5, min(15, int(self.short_clip_count)))
        self.short_max_duration_sec = max(120, min(360, int(self.short_max_duration_sec)))
        try:
            spd = float(self.global_speed)
        except (TypeError, ValueError):
            spd = 1.15
        self.global_speed = max(1.0, min(1.5, round(spd, 2)))
        return self


class PlanSettingsPatch(BaseModel):
    mode: str | None = None
    clip_count: int | None = Field(default=None, ge=5, le=15)
    max_duration_sec: int | None = Field(default=None, ge=300, le=900)
    short_clip_count: int | None = Field(default=None, ge=5, le=15)
    short_max_duration_sec: int | None = Field(default=None, ge=120, le=360)
    global_speed: float | None = Field(default=None, ge=1.0, le=1.5)

    model_config = {"extra": "allow"}


class OverlayPosSettings(BaseModel):
    """横或竖某一向：位置 + 字体等样式（缺省字段由顶层迁移）。"""

    x_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    y_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    font: str | None = None
    fontsize: int | None = Field(default=None, ge=8, le=90)
    color: str | None = None
    opacity: float | None = Field(default=None, ge=0.0, le=1.0)
    layout: str | None = None
    effect: str | None = None
    glow_color: str | None = None

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
    fontsize: int = Field(default=16, ge=8, le=90)
    color: str = "#FFFFFF"
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    layout: str = Field(default="horizontal")
    effect: str = Field(default="none")
    glow_color: str = "#FFFFFF"
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
        allowed = {
            "msyh",
            "msyhbd",
            "msyhl",
            "simhei",
            "simsun",
            "simsunb",
            "simkai",
            "simfang",
            "simli",
            "simyou",
            "stxingka",
            "stxinwei",
            "stkaiti",
            "stliti",
            "sthupo",
            "stcaiyun",
            "stxihei",
            "stzhongs",
            "stsong",
            "stfangso",
            "fzstk",
            "fzytk",
        }
        self.font = font if font in allowed else "msyh"
        self.fontsize = max(8, min(90, int(self.fontsize)))
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
        effect = str(self.effect or "none").strip().lower()
        allowed_effects = {
            "none",
            "glow",
            "ice_white",
            "poster_white",
            "pink_mood",
            "guochao",
            "red_impact",
            "sunset",
            "rose_gold",
            "warm_gold",
            "soft_yellow",
            "manga_yellow",
            "orange_fire",
            "neon",
            "cold_blue",
            "cyan_mint",
            "purple_dream",
            "violet_neon",
            "deep_purple",
            "cyber_lime",
            "ink_red",
            "outline",
            "heavy_outline",
        }
        self.effect = effect if effect in allowed_effects else "none"
        glow = str(self.glow_color or "#FFFFFF").strip()
        if glow.startswith("#"):
            glow = glow[1:]
        if len(glow) == 3 and all(c in "0123456789abcdefABCDEF" for c in glow):
            glow = "".join(c * 2 for c in glow)
        if len(glow) == 6 and all(c in "0123456789abcdefABCDEF" for c in glow):
            self.glow_color = f"#{glow.upper()}"
        else:
            defaults = {
                "none": "#FFFFFF",
                "glow": "#FFFFFF",
                "ice_white": "#F5FBFF",
                "poster_white": "#FFFFFF",
                "pink_mood": "#FF4FA3",
                "guochao": "#FF2D6A",
                "red_impact": "#FF1E3C",
                "sunset": "#FF6B9D",
                "rose_gold": "#FF8FAB",
                "warm_gold": "#FFB020",
                "soft_yellow": "#FFE566",
                "manga_yellow": "#FFD400",
                "orange_fire": "#FF6A00",
                "neon": "#00E5FF",
                "cold_blue": "#5B8CFF",
                "cyan_mint": "#3DFFC8",
                "purple_dream": "#B44DFF",
                "violet_neon": "#C77DFF",
                "deep_purple": "#7B2FFF",
                "cyber_lime": "#B8FF00",
                "ink_red": "#E6392B",
                "outline": "#FFFFFF",
                "heavy_outline": "#FFFFFF",
            }
            self.glow_color = defaults.get(self.effect, "#FFFFFF")

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
        effect="none",
        glow_color="#FFFFFF",
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
        effect="none",
        glow_color="#FFFFFF",
        portrait=OverlayPosSettings(x_pct=4.0, y_pct=96.9),
        landscape=OverlayPosSettings(x_pct=2.5, y_pct=94.0),
    )


class OverlayTextGroupSettings(BaseModel):
    id: str = ""
    name: str = Field(default="默认", max_length=64)
    title: OverlayTextStyleSettings = Field(default_factory=_default_overlay_title)
    disclaimer: OverlayTextStyleSettings = Field(
        default_factory=_default_overlay_disclaimer
    )

    model_config = {"extra": "allow"}

    @model_validator(mode="after")
    def _clamp(self) -> "OverlayTextGroupSettings":
        self.id = str(self.id or "").strip() or "default"
        self.name = str(self.name or "").strip()[:64] or "默认"
        if isinstance(self.title, dict):
            self.title = OverlayTextStyleSettings.model_validate(self.title)
        if isinstance(self.disclaimer, dict):
            self.disclaimer = OverlayTextStyleSettings.model_validate(self.disclaimer)
        return self


class OverlayTextLibrarySettings(BaseModel):
    selected_id: str = ""
    groups: list[OverlayTextGroupSettings] = Field(default_factory=list)

    model_config = {"extra": "allow"}

    @model_validator(mode="after")
    def _ensure_default(self) -> "OverlayTextLibrarySettings":
        groups = list(self.groups or [])
        if not any(g.id == "default" for g in groups):
            groups.insert(
                0,
                OverlayTextGroupSettings(
                    id="default",
                    name="默认",
                    title=_default_overlay_title(),
                    disclaimer=_default_overlay_disclaimer(),
                ),
            )
        self.groups = groups
        self.selected_id = str(self.selected_id or "").strip()
        if self.selected_id and not any(g.id == self.selected_id for g in self.groups):
            self.selected_id = ""
        return self


def _default_overlay_library() -> OverlayTextLibrarySettings:
    return OverlayTextLibrarySettings(
        selected_id="default",
        groups=[
            OverlayTextGroupSettings(
                id="default",
                name="默认",
                title=_default_overlay_title(),
                disclaimer=_default_overlay_disclaimer(),
            )
        ],
    )


class ClipEditSettings(BaseModel):
    """自动化剪辑页配置（文件名标识 + 画面叠字/文字组）。"""

    export_name_tag: str = Field(default="", max_length=20)
    overlay_title: OverlayTextStyleSettings = Field(
        default_factory=_default_overlay_title
    )
    overlay_disclaimer: OverlayTextStyleSettings = Field(
        default_factory=_default_overlay_disclaimer
    )
    overlay_text_library: OverlayTextLibrarySettings | None = None

    model_config = {"extra": "allow"}

    @model_validator(mode="after")
    def _clamp(self) -> "ClipEditSettings":
        self.export_name_tag = str(self.export_name_tag or "").strip()[:20]
        if isinstance(self.overlay_text_library, dict):
            self.overlay_text_library = OverlayTextLibrarySettings.model_validate(
                self.overlay_text_library
            )
        # 有库时派生当前启用样式到旧字段，便于旧客户端
        if self.overlay_text_library is not None:
            lib = self.overlay_text_library
            active = None
            if lib.selected_id:
                active = next((g for g in lib.groups if g.id == lib.selected_id), None)
            if active is None:
                active = next((g for g in lib.groups if g.id == "default"), None)
            if active is not None:
                self.overlay_title = active.title
                self.overlay_disclaimer = active.disclaimer
        return self


class ClipEditSettingsPatch(BaseModel):
    export_name_tag: str | None = Field(default=None, max_length=20)
    overlay_title: OverlayTextStyleSettings | dict[str, Any] | None = None
    overlay_disclaimer: OverlayTextStyleSettings | dict[str, Any] | None = None
    overlay_text_library: OverlayTextLibrarySettings | dict[str, Any] | None = None

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
        if isinstance(self.overlay_text_library, dict):
            self.overlay_text_library = OverlayTextLibrarySettings.model_validate(
                self.overlay_text_library
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
