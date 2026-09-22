from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, or_, select, text
from sqlalchemy.exc import OperationalError

from app.admin_panel import setup_admin
from app.database import Base, SessionLocal, engine
from app.models import User
from app.routers import admin, auth, client
from app.services.client_version import get_releases_dir, STATIC_MOUNT_PATH
from app.services.plan_jobs import fail_interrupted_jobs

logger = logging.getLogger(__name__)


def _ensure_user_plain_password_column() -> None:
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("users")}
    if "plain_password" in columns:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN plain_password VARCHAR(128) "
                "NOT NULL DEFAULT ''"
            )
        )


def _ensure_daily_quota_columns() -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    if "users" in table_names:
        user_cols = {col["name"] for col in inspector.get_columns("users")}
        with engine.begin() as conn:
            added_plan_limit = False
            added_clip_limit = False
            added_download_limit = False
            if "daily_plan_limit" not in user_cols:
                conn.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN daily_plan_limit INT "
                        "NOT NULL DEFAULT 30"
                    )
                )
                added_plan_limit = True
            if "daily_clip_limit" not in user_cols:
                conn.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN daily_clip_limit INT "
                        "NOT NULL DEFAULT 30"
                    )
                )
                added_clip_limit = True
            if "daily_download_limit" not in user_cols:
                conn.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN daily_download_limit INT "
                        "NOT NULL DEFAULT 30"
                    )
                )
                added_download_limit = True
            if "download_enabled" not in user_cols:
                conn.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN download_enabled TINYINT(1) "
                        "NOT NULL DEFAULT 1"
                    )
                )
            if "enabled_tabs" not in user_cols:
                conn.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN enabled_tabs VARCHAR(255) "
                        "NOT NULL DEFAULT 'video_download,clip_edit'"
                    )
                )
            if added_plan_limit:
                conn.execute(
                    text(
                        "UPDATE users SET daily_plan_limit = 30 "
                        "WHERE daily_plan_limit = 0"
                    )
                )
            if added_clip_limit:
                conn.execute(
                    text(
                        "UPDATE users SET daily_clip_limit = 30 "
                        "WHERE daily_clip_limit = 0"
                    )
                )
            if added_download_limit:
                conn.execute(
                    text(
                        "UPDATE users SET daily_download_limit = 30 "
                        "WHERE daily_download_limit = 0"
                    )
                )

    if "user_daily_activities" in table_names:
        activity_cols = {
            col["name"] for col in inspector.get_columns("user_daily_activities")
        }
        with engine.begin() as conn:
            if "planned_dramas" not in activity_cols:
                conn.execute(
                    text(
                        "ALTER TABLE user_daily_activities ADD COLUMN planned_dramas "
                        "TEXT NOT NULL"
                    )
                )
                conn.execute(
                    text(
                        "UPDATE user_daily_activities SET planned_dramas = '[]' "
                        "WHERE planned_dramas IS NULL OR planned_dramas = ''"
                    )
                )
            if "plan_count" not in activity_cols:
                conn.execute(
                    text(
                        "ALTER TABLE user_daily_activities ADD COLUMN plan_count "
                        "INT NOT NULL DEFAULT 0"
                    )
                )

    if "user_secrets" in table_names:
        secret_cols = {col["name"] for col in inspector.get_columns("user_secrets")}
        with engine.begin() as conn:
            if "plan_decrypt_key" not in secret_cols:
                conn.execute(
                    text(
                        "ALTER TABLE user_secrets ADD COLUMN plan_decrypt_key "
                        "VARCHAR(64) NOT NULL DEFAULT ''"
                    )
                )
            if "plan_llm_provider" not in secret_cols:
                conn.execute(
                    text(
                        "ALTER TABLE user_secrets ADD COLUMN plan_llm_provider "
                        "VARCHAR(32) NOT NULL DEFAULT 'deepseek'"
                    )
                )
            if "plan_llm_model" not in secret_cols:
                conn.execute(
                    text(
                        "ALTER TABLE user_secrets ADD COLUMN plan_llm_model "
                        "VARCHAR(64) NOT NULL DEFAULT ''"
                    )
                )
            if "plan_thinking_enabled" not in secret_cols:
                conn.execute(
                    text(
                        "ALTER TABLE user_secrets ADD COLUMN plan_thinking_enabled "
                        "BOOLEAN NOT NULL DEFAULT 0"
                    )
                )
            if "plan_group_id" not in secret_cols:
                conn.execute(
                    text(
                        "ALTER TABLE user_secrets ADD COLUMN plan_group_id "
                        "INT NULL DEFAULT NULL"
                    )
                )

    if "users" in table_names:
        user_cols = {col["name"] for col in inspector.get_columns("users")}
        with engine.begin() as conn:
            if "valid_until" not in user_cols:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN valid_until DATE NULL")
                )
            if "token_version" not in user_cols:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN token_version INT NOT NULL DEFAULT 1")
                )

    if "usage_events" in table_names:
        usage_cols = {col["name"] for col in inspector.get_columns("usage_events")}
        with engine.begin() as conn:
            if "plan_mode" not in usage_cols:
                conn.execute(
                    text(
                        "ALTER TABLE usage_events ADD COLUMN plan_mode "
                        "VARCHAR(16) NOT NULL DEFAULT ''"
                    )
                )
            if "encoder" not in usage_cols:
                conn.execute(
                    text(
                        "ALTER TABLE usage_events ADD COLUMN encoder "
                        "VARCHAR(32) NOT NULL DEFAULT ''"
                    )
                )
            if "resolution" not in usage_cols:
                conn.execute(
                    text(
                        "ALTER TABLE usage_events ADD COLUMN resolution "
                        "VARCHAR(32) NOT NULL DEFAULT ''"
                    )
                )
            if "cache_ms" not in usage_cols:
                conn.execute(
                    text(
                        "ALTER TABLE usage_events ADD COLUMN cache_ms "
                        "INT NOT NULL DEFAULT 0"
                    )
                )
            if "compose_ms" not in usage_cols:
                conn.execute(
                    text(
                        "ALTER TABLE usage_events ADD COLUMN compose_ms "
                        "INT NOT NULL DEFAULT 0"
                    )
                )
            if "render_engine" not in usage_cols:
                conn.execute(
                    text(
                        "ALTER TABLE usage_events ADD COLUMN render_engine "
                        "VARCHAR(16) NOT NULL DEFAULT ''"
                    )
                )
            if "plan_model" not in usage_cols:
                conn.execute(
                    text(
                        "ALTER TABLE usage_events ADD COLUMN plan_model "
                        "VARCHAR(64) NOT NULL DEFAULT ''"
                    )
                )
            if "transcribe_ms" not in usage_cols:
                conn.execute(
                    text(
                        "ALTER TABLE usage_events ADD COLUMN transcribe_ms "
                        "INT NOT NULL DEFAULT 0"
                    )
                )
            if "plan_ms" not in usage_cols:
                conn.execute(
                    text(
                        "ALTER TABLE usage_events ADD COLUMN plan_ms "
                        "INT NOT NULL DEFAULT 0"
                    )
                )
            if "render_ms" not in usage_cols:
                conn.execute(
                    text(
                        "ALTER TABLE usage_events ADD COLUMN render_ms "
                        "INT NOT NULL DEFAULT 0"
                    )
                )

    if "plan_jobs" in table_names:
        job_cols = {col["name"] for col in inspector.get_columns("plan_jobs")}
        with engine.begin() as conn:
            if "project_name" not in job_cols:
                conn.execute(
                    text(
                        "ALTER TABLE plan_jobs ADD COLUMN project_name "
                        "VARCHAR(255) NOT NULL DEFAULT ''"
                    )
                )
            if "plan_mode" not in job_cols:
                conn.execute(
                    text(
                        "ALTER TABLE plan_jobs ADD COLUMN plan_mode "
                        "VARCHAR(16) NOT NULL DEFAULT ''"
                    )
                )


def _ensure_user_machine_columns() -> None:
    """确保 user_machines 表具备 machine_id, ip_address, local_ip 字段。"""
    inspector = inspect(engine)
    if "user_machines" not in inspector.get_table_names():
        return
    cols = {col["name"] for col in inspector.get_columns("user_machines")}
    with engine.begin() as conn:
        if "machine_id" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE user_machines ADD COLUMN machine_id "
                    "VARCHAR(64) NOT NULL DEFAULT ''"
                )
            )
        if "ip_address" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE user_machines ADD COLUMN ip_address "
                    "VARCHAR(64) NOT NULL DEFAULT ''"
                )
            )
        if "local_ip" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE user_machines ADD COLUMN local_ip "
                    "VARCHAR(128) NOT NULL DEFAULT ''"
                )
            )


def _ensure_default_llm_channels_and_groups() -> None:
    from app.database import SessionLocal
    from app.models import LlmChannel, LlmGroup

    with SessionLocal() as db:
        try:
            if db.query(LlmChannel).count() == 0:
                ch1 = LlmChannel(
                    name="官方主力 DeepSeek-Flash",
                    provider="deepseek",
                    model_name="deepseek-flash",
                    api_url="",
                    api_keys=settings.deepseek_api_keys or "",
                    priority=1,
                    is_active=True,
                )
                ch2 = LlmChannel(
                    name="智谱 GLM-5.3-Flash",
                    provider="zhipu",
                    model_name="glm-5.3-flash",
                    api_url="",
                    api_keys="",
                    priority=2,
                    is_active=True,
                )
                db.add(ch1)
                db.add(ch2)
                db.commit()
                db.refresh(ch1)
                db.refresh(ch2)

                if db.query(LlmGroup).count() == 0:
                    g1 = LlmGroup(
                        name="混合模式主力串行组 (DeepSeek+智谱接力)",
                        dispatch_mode="serial",
                        channel_ids=f"{ch1.id},{ch2.id}",
                        max_loops_per_channel=2,
                        is_default=True,
                    )
                    g2 = LlmGroup(
                        name="混合模式极速并发组 (DeepSeek+智谱并发)",
                        dispatch_mode="parallel",
                        channel_ids=f"{ch1.id},{ch2.id}",
                        max_loops_per_channel=2,
                        is_default=False,
                    )
                    db.add(g1)
                    db.add(g2)
                    db.commit()
        except Exception:
            db.rollback()


def _ensure_invite_columns_and_codes() -> None:
    """确保 users 表具备 invite_code 和 invited_by_id 字段，并为存量用户补全邀请码。"""
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "users" in table_names:
        user_cols = {col["name"] for col in inspector.get_columns("users")}
        with engine.begin() as conn:
            if "invite_code" not in user_cols:
                conn.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN invite_code VARCHAR(16) NULL DEFAULT NULL"
                    )
                )
                try:
                    conn.execute(
                        text("CREATE UNIQUE INDEX ix_users_invite_code ON users (invite_code)")
                    )
                except Exception:
                    pass
            if "invited_by_id" not in user_cols:
                conn.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN invited_by_id INT NULL DEFAULT NULL"
                    )
                )

    if "user_invite_records" in table_names:
        invite_cols = {col["name"] for col in inspector.get_columns("user_invite_records")}
        with engine.begin() as conn:
            if "valid_days" not in invite_cols:
                conn.execute(
                    text("ALTER TABLE user_invite_records ADD COLUMN valid_days INT NOT NULL DEFAULT 30")
                )
            if "expires_at" not in invite_cols:
                conn.execute(
                    text("ALTER TABLE user_invite_records ADD COLUMN expires_at DATETIME NULL DEFAULT NULL")
                )
                try:
                    conn.execute(
                        text("CREATE INDEX ix_user_invite_records_expires_at ON user_invite_records (expires_at)")
                    )
                except Exception:
                    pass
            if "inviter_rewarded" not in invite_cols:
                conn.execute(
                    text("ALTER TABLE user_invite_records ADD COLUMN inviter_rewarded TINYINT(1) NOT NULL DEFAULT 1")
                )
            if "inviter_temp_reward" not in invite_cols:
                conn.execute(
                    text("ALTER TABLE user_invite_records ADD COLUMN inviter_temp_reward INT NOT NULL DEFAULT 0")
                )
            if "inviter_expires_at" not in invite_cols:
                conn.execute(
                    text("ALTER TABLE user_invite_records ADD COLUMN inviter_expires_at DATETIME NULL DEFAULT NULL")
                )
            if "invitee_temp_reward" not in invite_cols:
                conn.execute(
                    text("ALTER TABLE user_invite_records ADD COLUMN invitee_temp_reward INT NOT NULL DEFAULT 0")
                )
            if "invitee_expires_at" not in invite_cols:
                conn.execute(
                    text("ALTER TABLE user_invite_records ADD COLUMN invitee_expires_at DATETIME NULL DEFAULT NULL")
                )

    # 存量用户补全邀请码
    try:
        from app.services.invite_service import ensure_user_invite_code

        with SessionLocal() as db:
            users_without_code = db.scalars(
                select(User).where(or_(User.invite_code == "", User.invite_code.is_(None)))
            ).all()
            for u in users_without_code:
                ensure_user_invite_code(db, u)
    except Exception as exc:
        logger.warning("补全用户邀请码异常: %s", exc)


def _ensure_default_render_engine_v3() -> None:
    """平滑升级存量用户的历史旧默认渲染引擎 current / v2 -> v3。"""
    import json
    from app.models import UserSettings

    inspector = inspect(engine)
    if "user_settings" not in inspector.get_table_names():
        return
    with SessionLocal() as db:
        try:
            rows = db.query(UserSettings).all()
            changed = False
            for row in rows:
                if not row.data:
                    continue
                try:
                    data = json.loads(row.data)
                except Exception:
                    continue
                if not isinstance(data, dict):
                    continue
                clip_edit = data.get("clip_edit")
                if (
                    isinstance(clip_edit, dict)
                    and clip_edit.get("clip_render_engine") in ("current", "v2")
                ):
                    clip_edit["clip_render_engine"] = "v3"
                    row.data = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
                    changed = True
            if changed:
                db.commit()
                logger.info("已将存量用户的旧默认渲染引擎平滑升级为 v3")
        except Exception as exc:
            db.rollback()
            logger.warning("平滑升级渲染引擎至 v3 失败: %s", exc)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _ensure_user_plain_password_column()
    _ensure_daily_quota_columns()
    _ensure_user_machine_columns()
    _ensure_invite_columns_and_codes()
    _ensure_default_llm_channels_and_groups()
    _ensure_default_render_engine_v3()
    interrupted = fail_interrupted_jobs()
    if interrupted:
        logger.warning("已将 %s 个未完成策划任务标记为失败（服务重启）", interrupted)
    yield


app = FastAPI(title="AutomatedEdit API", version="1.0.0", lifespan=lifespan)

# 桌面端走 requests，不依赖 CORS；避免 * + credentials 的非法组合
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(client.router)
app.include_router(admin.router)

# 桌面端安装包：release/ → /release/<文件名>（与打包输出目录一致）
_releases_dir = get_releases_dir()
_releases_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    STATIC_MOUNT_PATH,
    StaticFiles(directory=str(_releases_dir)),
    name="release",
)

setup_admin(app)


@app.exception_handler(OperationalError)
async def _db_operational_error_handler(_request: Request, exc: OperationalError):
    logger.exception("数据库不可用: %s", exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "数据库暂时不可用，请稍后重试"},
    )


@app.get("/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("health 检查失败: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="database unavailable",
        ) from exc
    return {"status": "ok", "database": "ok"}
