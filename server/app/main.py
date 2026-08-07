from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from app.admin_panel import setup_admin
from app.database import Base, engine
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

    if "users" in table_names:
        user_cols = {col["name"] for col in inspector.get_columns("users")}
        with engine.begin() as conn:
            if "valid_until" not in user_cols:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN valid_until DATE NULL")
                )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _ensure_user_plain_password_column()
    _ensure_daily_quota_columns()
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
