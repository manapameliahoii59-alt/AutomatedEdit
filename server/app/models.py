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
    daily_plan_limit: Mapped[int] = mapped_column(Integer, default=30)
    daily_clip_limit: Mapped[int] = mapped_column(Integer, default=30)
    daily_download_limit: Mapped[int] = mapped_column(Integer, default=30)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    secrets: Mapped["UserSecret | None"] = relationship(back_populates="user", uselist=False)
    settings: Mapped["UserSettings | None"] = relationship(back_populates="user", uselist=False)
    usage_events: Mapped[list["UsageEvent"]] = relationship(back_populates="user")
    daily_activities: Mapped[list["UserDailyActivity"]] = relationship(back_populates="user")
    plan_jobs: Mapped[list["PlanJob"]] = relationship(back_populates="user")


class UserSecret(Base):
    __tablename__ = "user_secrets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    # 策划 LLM 密钥（官方 DeepSeek / OpenCode Go / 小米 MiMo / 智谱 GLM，由 plan_llm_provider 决定）
    deepseek_keys: Mapped[str] = mapped_column(Text, default="")
    dashscope_key: Mapped[str] = mapped_column(Text, default="")
    plan_decrypt_key: Mapped[str] = mapped_column(String(64), default="")
    # deepseek | opencode_go | xiaomi | zhipu
    plan_llm_provider: Mapped[str] = mapped_column(String(32), default="deepseek")
    # 空=通道默认模型
    plan_llm_model: Mapped[str] = mapped_column(String(64), default="")
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


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event: Mapped[str] = mapped_column(String(32), index=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[str] = mapped_column(Text, default="")
    plan_mode: Mapped[str] = mapped_column(String(16), default="")
    client_version: Mapped[str] = mapped_column(String(32), default="")
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
