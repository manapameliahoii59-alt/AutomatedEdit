"""自建管理后台（手写 HTML），入口 /admin。"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session, joinedload, sessionmaker
from starlette.applications import Starlette
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import engine
from app.models import ErrorReport, PlanJob, UsageEvent, User, UserDailyActivity, UserSettings
from app.services.plan_secrets import (
    PLAN_LLM_PRESET_CHOICES,
    PLAN_LLM_PROVIDER_DEEPSEEK,
    decode_plan_llm_preset,
    encode_plan_llm_preset,
    ensure_user_secret,
    normalize_plan_llm_model,
    normalize_plan_llm_provider,
    plan_llm_preset_label,
)
from app.services.usage_meta import PLAN_MODE_LABELS

_DRAMA_COL_MAX_WIDTH_PX = 200
_PAGE_SIZE = 40
_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_STATIC_DIR = Path(__file__).resolve().parent / "static" / "admin"
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))

router = APIRouter(prefix="/admin")


def _drama_column_key(attr) -> str:
    """兼容列名字符串或 ColumnProperty。"""
    if isinstance(attr, str):
        return attr
    key = getattr(attr, "key", None) or getattr(attr, "name", None)
    return str(key) if key else ""


def _drama_names_text(model, attr) -> str:
    key = _drama_column_key(attr)
    if not key:
        return ""
    raw = getattr(model, key, None)
    if raw is None:
        return ""
    text = str(raw).strip()
    if not text or text == "[]":
        return ""
    try:
        data = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return text
    if isinstance(data, list):
        names = [str(item).strip() for item in data if str(item).strip()]
        return "、".join(names)
    return text


def _drama_names_ellipsis(model, attr):
    full = _drama_names_text(model, attr)
    if not full:
        return "-"
    safe = escape(full)
    return Markup(
        f'<span title="{safe}" style="'
        f"display:inline-block;max-width:{_DRAMA_COL_MAX_WIDTH_PX}px;"
        "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
        f'vertical-align:bottom;">{safe}</span>'
    )


def _session() -> Session:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def get_admin_db():
    db = _session()
    try:
        yield db
    finally:
        db.close()


Db = Annotated[Session, Depends(get_admin_db)]


def _is_logged_in(request: Request) -> bool:
    return bool(request.session.get("admin"))


def _login_redirect(request: Request) -> RedirectResponse:
    nxt = request.url.path
    if request.url.query:
        nxt = f"{nxt}?{request.url.query}"
    qs = urlencode({"next": nxt}) if nxt and nxt != "/admin/login" else ""
    url = "/admin/login"
    if qs:
        url = f"{url}?{qs}"
    return RedirectResponse(url, status_code=302)


def _fmt_dt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _plan_mode_label(mode: str | None) -> str:
    key = str(mode or "").strip().lower()
    return PLAN_MODE_LABELS.get(key, key or "—")


def _keys_preview(keys: str | None) -> str:
    text = (keys or "").strip()
    if not text:
        return "未配置"
    return text if len(text) <= 32 else f"{text[:32]}…"


def _user_plan_fields(user: User) -> tuple[str, str, str, str, bool]:
    secret = user.secrets
    keys = (secret.deepseek_keys if secret else "") or ""
    dashscope = (secret.dashscope_key if secret else "") or ""
    provider = normalize_plan_llm_provider(
        getattr(secret, "plan_llm_provider", None) if secret else None
    )
    model_name = normalize_plan_llm_model(
        getattr(secret, "plan_llm_model", None) if secret else None,
        provider=provider,
    )
    preset = encode_plan_llm_preset(provider, model_name)
    label = plan_llm_preset_label(provider, model_name)
    thinking_enabled = (
        bool(getattr(secret, "plan_thinking_enabled", False)) if secret else False
    )
    return preset, label, keys, dashscope, thinking_enabled


def _nav(active: str) -> list[dict[str, str]]:
    items = [
        ("users", "/admin/users", "用户"),
        ("activity", "/admin/activity", "每日活动"),
        ("usage", "/admin/usage", "使用记录"),
        ("jobs", "/admin/jobs", "策划任务"),
        ("settings", "/admin/settings", "用户配置"),
        ("errors", "/admin/errors", "错误反馈"),
    ]
    return [
        {"key": key, "href": href, "label": label, "active": key == active}
        for key, href, label in items
    ]


def _get_users_missing_plan_keys(db: Session) -> list[dict[str, Any]]:
    """查询所有尚未配置「策划 API Keys」的用户（启用与禁用均包含，启用排在前面）。"""
    stmt = (
        select(User)
        .options(joinedload(User.secrets))
        .order_by(desc(User.is_active), desc(User.id))
    )
    rows = db.scalars(stmt).unique().all()
    missing = []
    for user in rows:
        if (user.username or "").strip().lower() == "demo":
            continue
        _preset, _label, keys, _dash, _thinking = _user_plan_fields(user)
        if not (keys or "").strip():
            missing.append(
                {
                    "id": user.id,
                    "username": user.username,
                    "role": user.role,
                    "is_active": user.is_active,
                    "valid_until": user.valid_until.isoformat() if user.valid_until else "永久",
                }
            )
    return missing


def _ctx(
    request: Request,
    *,
    active: str,
    db: Session | None = None,
    **extra: Any,
) -> dict[str, Any]:
    missing_plan_keys_users = []
    pending_errors_count = 0
    if db is not None:
        try:
            missing_plan_keys_users = _get_users_missing_plan_keys(db)
        except Exception:
            missing_plan_keys_users = []
        try:
            pending_errors_count = int(
                db.scalar(select(func.count(ErrorReport.id)).where(ErrorReport.status == "pending")) or 0
            )
        except Exception:
            pending_errors_count = 0
    just_logged_in = bool(request.session.pop("just_logged_in", False))
    data = {
        "request": request,
        "nav": _nav(active),
        "active": active,
        "app_name": "剪辑助手",
        "missing_plan_keys_users": missing_plan_keys_users,
        "pending_errors_count": pending_errors_count,
        "just_logged_in": just_logged_in,
        "today_date": date.today().isoformat(),
    }
    data.update(extra)
    return data


def _paginate(query_count: int, page: int) -> tuple[int, int, int]:
    total_pages = max(1, (query_count + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * _PAGE_SIZE
    return page, total_pages, offset


def _parse_int(raw: str | None, default: int) -> int:
    try:
        return int(str(raw or "").strip())
    except (TypeError, ValueError):
        return default


def _parse_valid_until(raw: str | None) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "", error: str = ""):
    if _is_logged_in(request):
        return RedirectResponse("/admin/users", status_code=302)
    return templates.TemplateResponse(
        request,
        "admin/login.html",
        {"next": next, "error": error, "app_name": "剪辑助手"},
    )


@router.post("/login")
def login_submit(
    request: Request,
    username: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "",
):
    if username == settings.admin_username and password == settings.admin_password:
        request.session["admin"] = True
        request.session["just_logged_in"] = True
        dest = (next or "").strip() or "/admin/users"
        if not dest.startswith("/admin"):
            dest = "/admin/users"
        return RedirectResponse(dest, status_code=302)
    return templates.TemplateResponse(
        request,
        "admin/login.html",
        {
            "next": next,
            "error": "账号或密码错误",
            "app_name": "剪辑助手",
        },
        status_code=401,
    )


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=302)


@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
def admin_home():
    return RedirectResponse("/admin/users", status_code=302)


@router.get("/users", response_class=HTMLResponse)
@router.get("/user/list", response_class=HTMLResponse)
def users_list(
    request: Request,
    db: Db,
    q: str = "",
    page: int = Query(default=1, ge=1),
):
    stmt = select(User).options(joinedload(User.secrets))
    count_stmt = select(func.count(User.id))
    keyword = q.strip()
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(User.username.like(like), User.role.like(like)))
        count_stmt = count_stmt.where(
            or_(User.username.like(like), User.role.like(like))
        )
    total = int(db.scalar(count_stmt) or 0)
    page, total_pages, offset = _paginate(total, page)
    rows = db.scalars(
        stmt.order_by(desc(User.id)).offset(offset).limit(_PAGE_SIZE)
    ).all()
    users = []
    for user in rows:
        preset, label, keys, _dash, _thinking = _user_plan_fields(user)
        users.append(
            {
                "id": user.id,
                "username": user.username,
                "password": user.plain_password or "",
                "role": user.role,
                "is_active": user.is_active,
                "download_enabled": getattr(user, "download_enabled", True),
                "valid_until": user.valid_until.isoformat() if user.valid_until else "永久",
                "plan_limit": user.daily_plan_limit,
                "clip_limit": user.daily_clip_limit,
                "download_limit": getattr(user, "daily_download_limit", 30),
                "plan_label": label,
                "keys_preview": _keys_preview(keys),
                "created_at": _fmt_dt(user.created_at),
                "preset": preset,
            }
        )
    return templates.TemplateResponse(
        request,
        "admin/users.html",
        _ctx(
            request,
            active="users",
            db=db,
            users=users,
            q=keyword,
            page=page,
            total_pages=total_pages,
            total=total,
        ),
    )


@router.get("/users/{user_id}", response_class=HTMLResponse)
@router.get("/user/edit/{user_id}", response_class=HTMLResponse)
def user_edit_page(
    request: Request,
    user_id: int,
    db: Db,
    saved: int = 0,
):
    user = db.scalar(
        select(User).options(joinedload(User.secrets)).where(User.id == user_id)
    )
    if user is None:
        return HTMLResponse("用户不存在", status_code=404)
    preset, _label, keys, dashscope, thinking_enabled = _user_plan_fields(user)
    raw_tabs = getattr(user, "enabled_tabs", None)
    enabled_tabs = (
        [t.strip() for t in str(raw_tabs).split(",") if t.strip()]
        if raw_tabs
        else ["video_download", "clip_edit"]
    )
    if not getattr(user, "download_enabled", True):
        enabled_tabs = [t for t in enabled_tabs if t != "video_download"]
    return templates.TemplateResponse(
        request,
        "admin/user_edit.html",
        _ctx(
            request,
            active="users",
            db=db,
            user=user,
            enabled_tabs=enabled_tabs,
            plan_llm_preset=preset,
            deepseek_keys=keys,
            dashscope_key=dashscope,
            plan_thinking_enabled=thinking_enabled,
            plan_choices=list(PLAN_LLM_PRESET_CHOICES),
            saved=bool(saved),
            default_preset=f"{PLAN_LLM_PROVIDER_DEEPSEEK}|deepseek-v4-flash",
        ),
    )


@router.post("/users/{user_id}")
@router.post("/user/edit/{user_id}")
def user_edit_save(
    request: Request,
    user_id: int,
    db: Db,
    username: Annotated[str, Form()] = "",
    role: Annotated[str, Form()] = "user",
    is_active: Annotated[str | None, Form()] = None,
    download_enabled: Annotated[str | None, Form()] = None,
    valid_until: Annotated[str | None, Form()] = None,
    daily_plan_limit: Annotated[str | None, Form()] = None,
    daily_clip_limit: Annotated[str | None, Form()] = None,
    daily_download_limit: Annotated[str | None, Form()] = None,
    tabs_submitted: Annotated[str | None, Form()] = None,
    tab_video_download: Annotated[str | None, Form()] = None,
    tab_clip_edit: Annotated[str | None, Form()] = None,
    tab_batch_edit: Annotated[str | None, Form()] = None,
    plan_llm_preset: Annotated[str | None, Form()] = None,
    plan_thinking_enabled: Annotated[str | None, Form()] = None,
    deepseek_keys: Annotated[str | None, Form()] = None,
    dashscope_key: Annotated[str | None, Form()] = None,
    save: Annotated[str | None, Form()] = None,
):
    user = db.get(User, user_id)
    if user is None:
        return HTMLResponse("用户不存在", status_code=404)
    name = (username or "").strip() or user.username
    user.username = name
    user.role = (role or "user").strip() or "user"
    user.is_active = bool(is_active)
    user.valid_until = _parse_valid_until(valid_until)
    if daily_plan_limit is not None and str(daily_plan_limit).strip() != "":
        user.daily_plan_limit = _parse_int(daily_plan_limit, user.daily_plan_limit)
    if daily_clip_limit is not None and str(daily_clip_limit).strip() != "":
        user.daily_clip_limit = _parse_int(daily_clip_limit, user.daily_clip_limit)
    if daily_download_limit is not None and str(daily_download_limit).strip() != "":
        user.daily_download_limit = _parse_int(
            daily_download_limit, user.daily_download_limit
        )

    # 导航栏 Tab 权限配置
    video_on = bool(download_enabled) or bool(tab_video_download)
    if tabs_submitted or tab_video_download or tab_clip_edit or tab_batch_edit:
        tabs = []
        if video_on:
            tabs.append("video_download")
        if tab_clip_edit:
            tabs.append("clip_edit")
        if tab_batch_edit:
            tabs.append("batch_edit")
        user.enabled_tabs = ",".join(tabs)
        user.download_enabled = video_on
    else:
        user.download_enabled = video_on
        current_tabs = [
            t.strip()
            for t in str(getattr(user, "enabled_tabs", "") or "").split(",")
            if t.strip()
        ]
        if not current_tabs:
            current_tabs = ["video_download", "clip_edit"]
        if video_on and "video_download" not in current_tabs:
            current_tabs.append("video_download")
        elif not video_on and "video_download" in current_tabs:
            current_tabs.remove("video_download")
        user.enabled_tabs = ",".join(current_tabs)
    db.commit()

    preset = (plan_llm_preset or "").strip()
    provider, llm_model = decode_plan_llm_preset(preset)
    secret = ensure_user_secret(db, user.id)
    if deepseek_keys is not None:
        secret.deepseek_keys = deepseek_keys.strip()
    if dashscope_key is not None:
        secret.dashscope_key = dashscope_key.strip()
    secret.plan_llm_provider = provider
    secret.plan_llm_model = llm_model
    secret.plan_thinking_enabled = bool(plan_thinking_enabled)
    db.commit()
    return RedirectResponse(f"/admin/user/edit/{user_id}?saved=1", status_code=302)


def _list_page(
    request: Request,
    db: Session,
    *,
    active: str,
    template: str,
    model,
    order_col,
    search_cols: list,
    q: str,
    page: int,
    row_mapper,
    extra_filters=None,
):
    stmt = select(model).options(joinedload(model.user))
    count_stmt = select(func.count(model.id))
    keyword = q.strip()
    if keyword:
        like = f"%{keyword}%"
        cond = or_(*[col.like(like) for col in search_cols])
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if extra_filters is not None:
        stmt = extra_filters(stmt)
        count_stmt = extra_filters(count_stmt)
    total = int(db.scalar(count_stmt) or 0)
    page, total_pages, offset = _paginate(total, page)
    rows = db.scalars(
        stmt.order_by(desc(order_col)).offset(offset).limit(_PAGE_SIZE)
    ).unique().all()
    return templates.TemplateResponse(
        request,
        template,
        _ctx(
            request,
            active=active,
            db=db,
            rows=[row_mapper(row) for row in rows],
            q=keyword,
            page=page,
            total_pages=total_pages,
            total=total,
        ),
    )


@router.get("/activity", response_class=HTMLResponse)
def activity_list(
    request: Request,
    db: Db,
    q: str = "",
    page: int = Query(default=1, ge=1),
):
    def mapper(row: UserDailyActivity) -> dict:
        username = row.user.username if row.user else f"#{row.user_id}"
        return {
            "id": row.id,
            "username": username,
            "date": _fmt_dt(row.activity_date),
            "login_at": _fmt_dt(row.login_at),
            "logout_at": _fmt_dt(row.logout_at),
            "downloaded": _drama_names_text(row, "downloaded_dramas") or "—",
            "planned": _drama_names_text(row, "planned_dramas") or "—",
            "clipped": _drama_names_text(row, "clipped_dramas") or "—",
            "plan_count": row.plan_count,
            "clip_count": row.clip_count,
        }

    return _list_page(
        request,
        db,
        active="activity",
        template="admin/activity.html",
        model=UserDailyActivity,
        order_col=UserDailyActivity.activity_date,
        search_cols=[
            UserDailyActivity.downloaded_dramas,
            UserDailyActivity.planned_dramas,
            UserDailyActivity.clipped_dramas,
        ],
        q=q,
        page=page,
        row_mapper=mapper,
    )


@router.get("/usage", response_class=HTMLResponse)
def usage_list(
    request: Request,
    db: Db,
    q: str = "",
    page: int = Query(default=1, ge=1),
):
    def mapper(row: UsageEvent) -> dict:
        username = row.user.username if row.user else f"#{row.user_id}"
        return {
            "id": row.id,
            "username": username,
            "event": row.event,
            "success": "是" if row.success else "否",
            "meta": row.meta or "—",
            "plan_mode": _plan_mode_label(row.plan_mode),
            "duration_ms": row.duration_ms,
            "client_version": row.client_version or "—",
            "created_at": _fmt_dt(row.created_at),
        }

    return _list_page(
        request,
        db,
        active="usage",
        template="admin/usage.html",
        model=UsageEvent,
        order_col=UsageEvent.id,
        search_cols=[UsageEvent.event, UsageEvent.meta, UsageEvent.plan_mode],
        q=q,
        page=page,
        row_mapper=mapper,
    )


@router.get("/jobs", response_class=HTMLResponse)
def jobs_list(
    request: Request,
    db: Db,
    q: str = "",
    page: int = Query(default=1, ge=1),
):
    def mapper(row: PlanJob) -> dict:
        username = row.user.username if row.user else f"#{row.user_id}"
        return {
            "id": row.id,
            "username": username,
            "status": row.status,
            "project_name": row.project_name or "—",
            "plan_mode": _plan_mode_label(row.plan_mode),
            "error": row.error or "—",
            "created_at": _fmt_dt(row.created_at),
            "updated_at": _fmt_dt(row.updated_at),
        }

    return _list_page(
        request,
        db,
        active="jobs",
        template="admin/jobs.html",
        model=PlanJob,
        order_col=PlanJob.created_at,
        search_cols=[
            PlanJob.id,
            PlanJob.status,
            PlanJob.project_name,
            PlanJob.plan_mode,
            PlanJob.error,
        ],
        q=q,
        page=page,
        row_mapper=mapper,
    )


@router.get("/settings", response_class=HTMLResponse)
def settings_list(
    request: Request,
    db: Db,
    q: str = "",
    page: int = Query(default=1, ge=1),
):
    def mapper(row: UserSettings) -> dict:
        username = row.user.username if row.user else f"#{row.user_id}"
        data = (row.data or "").strip() or "{}"
        preview = data if len(data) <= 120 else data[:120] + "…"
        return {
            "id": row.id,
            "username": username,
            "data": data,
            "data_preview": preview,
            "updated_at": _fmt_dt(row.updated_at),
        }

    return _list_page(
        request,
        db,
        active="settings",
        template="admin/settings.html",
        model=UserSettings,
        order_col=UserSettings.updated_at,
        search_cols=[UserSettings.data],
        q=q,
        page=page,
        row_mapper=mapper,
    )


@router.get("/api/unconfigured-users")
def get_unconfigured_users(db: Db):
    return {"users": _get_users_missing_plan_keys(db)}


_ERROR_STAGE_LABELS = {
    "transcribe": "语音识别",
    "plan": "方案策划",
    "render": "动态渲染",
    "download": "视频下载",
    "general": "通用业务",
}


@router.get("/errors", response_class=HTMLResponse)
def error_reports_list(
    request: Request,
    db: Db,
    q: str = "",
    status: str = "",
    page: int = Query(default=1, ge=1),
):
    def mapper(row: ErrorReport) -> dict:
        username = row.username or (row.user.username if row.user else "—")
        stage_label = _ERROR_STAGE_LABELS.get(row.error_stage, row.error_stage or "通用业务")
        raw = row.raw_error or ""
        preview = raw if len(raw) <= 100 else raw[:100] + "…"
        return {
            "id": row.id,
            "username": username,
            "app_version": row.app_version or "—",
            "error_stage": row.error_stage,
            "error_stage_label": stage_label,
            "drama_name": row.drama_name or "—",
            "friendly_msg": row.friendly_msg or "—",
            "raw_error": raw,
            "raw_error_preview": preview,
            "client_info": row.client_info or "—",
            "status": row.status or "pending",
            "created_at": _fmt_dt(row.created_at),
        }

    def status_filter(stmt):
        if status.strip() in ("pending", "resolved", "ignored"):
            return stmt.where(ErrorReport.status == status.strip())
        return stmt

    return _list_page(
        request,
        db,
        active="errors",
        template="admin/errors.html",
        model=ErrorReport,
        order_col=ErrorReport.created_at,
        search_cols=[
            ErrorReport.username,
            ErrorReport.drama_name,
            ErrorReport.friendly_msg,
            ErrorReport.raw_error,
            ErrorReport.error_stage,
        ],
        q=q,
        page=page,
        row_mapper=mapper,
        extra_filters=status_filter,
    )


@router.post("/errors/{report_id}/status")
def error_report_set_status(
    request: Request,
    report_id: int,
    db: Db,
    status: Annotated[str, Form()] = "resolved",
):
    if not _is_logged_in(request):
        return RedirectResponse("/admin/login", status_code=302)
    report = db.get(ErrorReport, report_id)
    if report:
        report.status = status if status in ("pending", "resolved", "ignored") else "resolved"
        db.commit()
    referer = request.headers.get("referer") or "/admin/errors"
    return RedirectResponse(referer, status_code=302)


@router.post("/errors/{report_id}/delete")
def error_report_delete(
    request: Request,
    report_id: int,
    db: Db,
):
    if not _is_logged_in(request):
        return RedirectResponse("/admin/login", status_code=302)
    report = db.get(ErrorReport, report_id)
    if report:
        db.delete(report)
        db.commit()
    referer = request.headers.get("referer") or "/admin/errors"
    return RedirectResponse(referer, status_code=302)


def setup_admin(app: Starlette):
    """挂载手写后台，并处理未登录跳转。"""

    @app.middleware("http")
    async def _admin_guard(request: Request, call_next):
        path = request.url.path
        if path.startswith("/admin") and not path.startswith("/admin/login"):
            if not request.session.get("admin"):
                return _login_redirect(request)
        return await call_next(request)

    app.add_middleware(SessionMiddleware, secret_key=settings.jwt_secret)
    app.include_router(router)
    if _STATIC_DIR.is_dir():
        app.mount(
            "/static/admin",
            StaticFiles(directory=str(_STATIC_DIR)),
            name="admin-static",
        )
    return router
