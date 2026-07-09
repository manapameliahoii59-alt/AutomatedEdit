from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.admin_panel import setup_admin
from app.database import Base, engine
from app.routers import admin, auth, client


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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _ensure_user_plain_password_column()
    _ensure_daily_quota_columns()
    yield


app = FastAPI(title="AutomatedEdit API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(client.router)
app.include_router(admin.router)

setup_admin(app)


@app.get("/health")
def health():
    return {"status": "ok"}
