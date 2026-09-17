from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    plain_password: Mapped[str] = mapped_column(String(128), default="")
    role: Mapped[str] = mapped_column(String(16), default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    download_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled_tabs: Mapped[str] = mapped_column(
        String(255), default="video_download,clip_edit"
    )
    daily_plan_limit: Mapped[int] = mapped_column(Integer, default=30)
    daily_clip_limit: Mapped[int] = mapped_column(Integer, default=30)
    daily_download_limit: Mapped[int] = mapped_column(Integer, default=30)
    invite_code: Mapped[str | None] = mapped_column(String(16), unique=True, index=True, nullable=True, default=None)
    invited_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, default=None)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    secrets: Mapped["UserSecret | None"] = relationship(back_populates="user", uselist=False)
    settings: Mapped["UserSettings | None"] = relationship(back_populates="user", uselist=False)
    machine: Mapped["UserMachine | None"] = relationship(back_populates="user", uselist=False)
    usage_events: Mapped[list["UsageEvent"]] = relationship(back_populates="user")
    daily_activities: Mapped[list["UserDailyActivity"]] = relationship(back_populates="user")
    plan_jobs: Mapped[list["PlanJob"]] = relationship(back_populates="user")


class UserSecret(Base):
    __tablename__ = "user_secrets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    # 策划 LLM 密钥（官方 DeepSeek / OpenCode Go / 小米 MiMo / 智谱 GLM / 硅基流动 / 通义千问，由 plan_llm_provider 决定）
    deepseek_keys: Mapped[str] = mapped_column(Text, default="")
    dashscope_key: Mapped[str] = mapped_column(Text, default="")
    plan_decrypt_key: Mapped[str] = mapped_column(String(64), default="")
    # deepseek | opencode_go | xiaomi | zhipu | siliconflow | tongyi
    plan_llm_provider: Mapped[str] = mapped_column(String(32), default="deepseek")
    # 空=通道默认模型
    plan_llm_model: Mapped[str] = mapped_column(String(64), default="")
    # 深度思考模式（默认关闭提速；智谱 GLM-5.3 等强制思考模型不受此限制）
    plan_thinking_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # 混合模式调度策略组（关联 LlmGroup.id；为 NULL 或 0 时跟随默认组或回退单模型）
    plan_group_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="secrets")


class UserSettings(Base):
    """用户客户端配置，按命名空间以 JSON 存储，便于后续扩展。"""

    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    data: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="settings")


class UserMachine(Base):
    """用户桌面端机器信息（每用户仅保留最新一条）。"""

    __tablename__ = "user_machines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    cpu_name: Mapped[str] = mapped_column(String(255), default="")
    cpu_cores_logical: Mapped[int] = mapped_column(Integer, default=0)
    cpu_cores_physical: Mapped[int] = mapped_column(Integer, default=0)
    ram_total_mb: Mapped[int] = mapped_column(Integer, default=0)
    ram_available_mb: Mapped[int] = mapped_column(Integer, default=0)
    gpus: Mapped[str] = mapped_column(Text, default="[]")
    gpu_summary: Mapped[str] = mapped_column(String(512), default="")
    os: Mapped[str] = mapped_column(String(255), default="")
    hostname: Mapped[str] = mapped_column(String(128), default="")
    client_version: Mapped[str] = mapped_column(String(32), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="machine")


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event: Mapped[str] = mapped_column(String(32), index=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[str] = mapped_column(Text, default="")
    plan_mode: Mapped[str] = mapped_column(String(16), default="")
    plan_model: Mapped[str] = mapped_column(String(64), default="")
    # 阶段计时（毫秒）：识别、策划、渲染
    transcribe_ms: Mapped[int] = mapped_column(Integer, default=0)
    plan_ms: Mapped[int] = mapped_column(Integer, default=0)
    render_ms: Mapped[int] = mapped_column(Integer, default=0)
    client_version: Mapped[str] = mapped_column(String(32), default="")
    # 渲染遥测：实际生效编码器 + 分辨率 + 缓存/合成耗时（毫秒）
    encoder: Mapped[str] = mapped_column(String(32), default="")
    resolution: Mapped[str] = mapped_column(String(32), default="")
    cache_ms: Mapped[int] = mapped_column(Integer, default=0)
    compose_ms: Mapped[int] = mapped_column(Integer, default=0)
    render_engine: Mapped[str] = mapped_column(String(16), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    user: Mapped["User"] = relationship(back_populates="usage_events")


class UserDailyActivity(Base):
    """用户每日活动汇总：登录/关闭时间、下载与剪辑剧目。"""

    __tablename__ = "user_daily_activities"
    __table_args__ = (UniqueConstraint("user_id", "activity_date", name="uq_user_daily_activity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    activity_date: Mapped[date] = mapped_column(Date, index=True)
    login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    logout_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    downloaded_dramas: Mapped[str] = mapped_column(Text, default="[]")
    planned_dramas: Mapped[str] = mapped_column(Text, default="[]")
    clipped_dramas: Mapped[str] = mapped_column(Text, default="[]")
    plan_count: Mapped[int] = mapped_column(Integer, default=0)
    clip_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="daily_activities")


class PlanJob(Base):
    """策划异步任务（落库，避免重启/多 worker 丢任务导致 404）。"""

    __tablename__ = "plan_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    project_name: Mapped[str] = mapped_column(String(255), default="")
    plan_mode: Mapped[str] = mapped_column(String(16), default="")
    progress_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    result_json: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), index=True
    )

    user: Mapped["User | None"] = relationship(back_populates="plan_jobs")


class ErrorReport(Base):
    """客户端错误反馈记录（方便开发者与管理员集中定位排查）。"""

    __tablename__ = "error_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    username: Mapped[str] = mapped_column(String(64), default="", index=True)
    app_version: Mapped[str] = mapped_column(String(32), default="")
    error_stage: Mapped[str] = mapped_column(String(32), default="general", index=True)  # transcribe, plan, render, download, general
    drama_name: Mapped[str] = mapped_column(String(255), default="")
    friendly_msg: Mapped[str] = mapped_column(Text, default="")
    raw_error: Mapped[str] = mapped_column(Text, default="")
    client_info: Mapped[str] = mapped_column(Text, default="")  # OS, Python, CPU/GPU
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending | resolved | ignored
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    user: Mapped["User | None"] = relationship()


class RadioTrack(Base):
    """音乐电台曲目（从B站扒取的音源或本地上传的音乐）。"""

    __tablename__ = "radio_tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    artist: Mapped[str] = mapped_column(String(128), default="未知艺术家")
    duration: Mapped[int] = mapped_column(Integer, default=0)  # 秒
    cover_url: Mapped[str] = mapped_column(String(512), default="")
    audio_url: Mapped[str] = mapped_column(String(512), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), default="bilibili")  # bilibili | upload
    source_url: Mapped[str] = mapped_column(String(512), default="")
    source_id: Mapped[str] = mapped_column(String(64), default="", index=True)  # BV号或原始标识
    file_size: Mapped[int] = mapped_column(Integer, default=0)  # 字节
    play_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class RadioGroup(Base):
    """音乐电台自定义分组/歌单。"""

    __tablename__ = "radio_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RadioTrackGroup(Base):
    """歌曲与自定义分组关联关系表。"""

    __tablename__ = "radio_track_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    track_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LlmChannel(Base):
    """大模型渠道配置（支持 deepseek / zhipu / xiaomi / opencode_go / siliconflow / tongyi 等）。"""

    __tablename__ = "llm_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), default="deepseek")
    model_name: Mapped[str] = mapped_column(String(64), default="")
    api_url: Mapped[str] = mapped_column(String(255), default="")
    api_keys: Mapped[str] = mapped_column(Text, default="")
    thinking_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LlmGroup(Base):
    """大模型策略调度组（支持串行接力 serial / 并发融合 parallel）。"""

    __tablename__ = "llm_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # serial (串行接力) | parallel (并行融合)
    dispatch_mode: Mapped[str] = mapped_column(String(32), default="serial")
    # 逗号分隔的 LlmChannel.id 列表，按执行优先级排序（如 "1,2,3"）
    channel_ids: Mapped[str] = mapped_column(String(255), default="")
    # 串行模式下单渠道最大尝试轮次（遇到切点不满足或停滞时切换下一个渠道）
    max_loops_per_channel: Mapped[int] = mapped_column(Integer, default=2)
    # 是否为混合模式系统默认调度组
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SystemSetting(Base):
    """全局系统配置（键值对，供后台动态调整）。"""

    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(String(255), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class UserInviteRecord(Base):
    """用户邀请裂变流水记录表（记录谁邀请了谁，以及当时奖励的额度）。"""

    __tablename__ = "user_invite_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inviter_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    invitee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    reward_clip_limit: Mapped[int] = mapped_column(Integer, default=5)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    inviter: Mapped["User"] = relationship("User", foreign_keys=[inviter_id])
    invitee: Mapped["User"] = relationship("User", foreign_keys=[invitee_id])
