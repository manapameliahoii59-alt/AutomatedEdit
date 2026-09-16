"""自建管理后台（手写 HTML），入口 /admin。"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from sqlalchemy import desc, func, or_, select, update
from sqlalchemy.orm import Session, joinedload, sessionmaker
from starlette.applications import Starlette
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import engine
from app.models import ErrorReport, PlanJob, UsageEvent, User, UserDailyActivity, UserMachine, UserSettings
from app.services import client_version as client_version_service
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
from app.services.user_machine import get_machine
from app.services.user_settings import get_user_settings, patch_user_settings

_DRAMA_COL_MAX_WIDTH_PX = 200
_PAGE_SIZE = 40
_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_STATIC_DIR = Path(__file__).resolve().parent / "static" / "admin"
_THEME_FILE = _STATIC_DIR / "login_theme.json"
_UPLOADED_BG_FILE = _STATIC_DIR / "custom_login_bg.jpg"
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))

LOGIN_BG_PRESETS: list[dict[str, str]] = [
    {
        "key": "default",
        "name": "经典浅灰",
        "css": "background-color: #f5f7fa;",
        "preview_css": "background: #f5f7fa; border: 1px solid #dcdfe6;",
        "desc": "极简纯净，专注高效",
    },
    {
        "key": "gradient_frost",
        "name": "蓝莓霜雾",
        "css": "background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);",
        "preview_css": "background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);",
        "desc": "蓝紫梦幻渐变，现代科技感",
    },
    {
        "key": "gradient_tech",
        "name": "赛博深空",
        "css": "background: linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%);",
        "preview_css": "background: linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%);",
        "desc": "深色科技渐变，沉稳大气",
    },
    {
        "key": "gradient_aurora",
        "name": "极光微澜",
        "css": "background: linear-gradient(135deg, #134e5e 0%, #71b280 100%);",
        "preview_css": "background: linear-gradient(135deg, #134e5e 0%, #71b280 100%);",
        "desc": "青绿自然微光，清新典雅",
    },
    {
        "key": "gradient_ocean",
        "name": "深海雅致",
        "css": "background: linear-gradient(135deg, #2b5876 0%, #4e4376 100%);",
        "preview_css": "background: linear-gradient(135deg, #2b5876 0%, #4e4376 100%);",
        "desc": "深海靛蓝渐变，低调内敛",
    },
    {
        "key": "gradient_sunset",
        "name": "晚霞流彩",
        "css": "background: linear-gradient(135deg, #fa709a 0%, #fee140 100%);",
        "preview_css": "background: linear-gradient(135deg, #fa709a 0%, #fee140 100%);",
        "desc": "落日温暖霞光，柔和明丽",
    },
]


def _get_login_theme() -> dict[str, Any]:
    default_theme: dict[str, Any] = {
        "mode": "default",
        "preset_key": "default",
        "custom_url": "",
        "glass": True,
        "has_uploaded": _UPLOADED_BG_FILE.is_file(),
    }
    if not _THEME_FILE.is_file():
        return default_theme
    try:
        data = json.loads(_THEME_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            default_theme.update(data)
    except Exception:
        pass
    default_theme["has_uploaded"] = _UPLOADED_BG_FILE.is_file()
    return default_theme


def _save_login_theme(theme_data: dict[str, Any]) -> None:
    _STATIC_DIR.mkdir(parents=True, exist_ok=True)
    _THEME_FILE.write_text(json.dumps(theme_data, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_login_bg_style(theme: dict[str, Any]) -> tuple[str, bool]:
    mode = theme.get("mode", "default")
    glass = bool(theme.get("glass", True))
    if mode == "preset":
        preset_key = theme.get("preset_key", "default")
        for p in LOGIN_BG_PRESETS:
            if p["key"] == preset_key:
                return p["css"], glass
        return "background-color: #f5f7fa;", False
    elif mode == "url":
        url = (theme.get("custom_url") or "").strip()
        if url:
            return f"background: url('{url}') center center / cover no-repeat fixed;", glass
        return "background-color: #f5f7fa;", False
    elif mode == "upload":
        if _UPLOADED_BG_FILE.is_file():
            mtime = int(_UPLOADED_BG_FILE.stat().st_mtime)
            return (
                f"background: url('/static/admin/custom_login_bg.jpg?t={mtime}') center center / cover no-repeat fixed;",
                glass,
            )
        return "background-color: #f5f7fa;", False
    else:
        return "background-color: #f5f7fa;", False


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


def _fmt_duration_ms(ms: int | None) -> str:
    if not ms or ms <= 0:
        return "—"
    sec = ms / 1000.0
    if sec < 60:
        return f"{sec:.1f}s"
    m, s = divmod(int(sec), 60)
    remainder = sec - int(sec)
    if remainder >= 0.05:
        return f"{m}m {s + remainder:.1f}s"
    return f"{m}m {s}s"


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
        ("machines", "/admin/machines", "机器信息"),
        ("activity", "/admin/activity", "每日活动"),
        ("usage", "/admin/usage", "使用记录"),
        ("jobs", "/admin/jobs", "策划任务"),
        ("settings", "/admin/settings", "用户配置"),
        ("errors", "/admin/errors", "错误反馈"),
        ("radio", "/admin/radio", "音乐电台"),
        ("version", "/admin/version", "版本更新"),
        ("profile", "/admin/profile", "个人中心"),
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


def _parse_tristate(raw: str | None) -> bool | None:
    """三态开关解析：开→True、关→False、空/未知→None（表示不设置）。"""
    text = str(raw or "").strip().lower()
    if text in {"1", "true", "yes", "on", "y"}:
        return True
    if text in {"0", "false", "no", "off", "n"}:
        return False
    return None


def _parse_valid_until(raw: str | None) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    next: str = "",
    error: str = "",
    preview: str = "",
):
    is_preview = preview in ("1", "true", "yes")
    if _is_logged_in(request) and not is_preview:
        return RedirectResponse("/admin/users", status_code=302)
    theme = _get_login_theme()
    bg_css, is_glass = _get_login_bg_style(theme)
    return templates.TemplateResponse(
        request,
        "admin/login.html",
        {
            "next": next,
            "error": error,
            "app_name": "剪辑助手",
            "bg_css": bg_css,
            "is_glass": is_glass,
            "is_preview": is_preview,
        },
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
    theme = _get_login_theme()
    bg_css, is_glass = _get_login_bg_style(theme)
    return templates.TemplateResponse(
        request,
        "admin/login.html",
        {
            "next": next,
            "error": "账号或密码错误",
            "app_name": "剪辑助手",
            "bg_css": bg_css,
            "is_glass": is_glass,
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
    msg: str = "",
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
            msg=msg,
            machine=_machine_to_dict(get_machine(db, user.id)),
            clip_edit=get_user_settings(db, user.id).clip_edit,
            plan=get_user_settings(db, user.id).plan,
            default_preset=f"{PLAN_LLM_PROVIDER_DEEPSEEK}|deepseek-flash",
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
    encode_enable_gpu: Annotated[str | None, Form()] = None,
    encode_nvenc_preset: Annotated[str | None, Form()] = None,
    encode_amf_preset: Annotated[str | None, Form()] = None,
    encode_qsv_preset: Annotated[str | None, Form()] = None,
    encode_x264_preset: Annotated[str | None, Form()] = None,
    clip_trim_ep1_continued: Annotated[str | None, Form()] = None,
    clip_overlay_bake_png: Annotated[str | None, Form()] = None,
    clip_auto_select_after_import: Annotated[str | None, Form()] = None,
    clip_render_engine: Annotated[str | None, Form()] = None,
    plan_mixed_strategy: Annotated[str | None, Form()] = None,
    session_action: Annotated[str | None, Form()] = None,
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
    if session_action == "revoke":
        user.token_version = (getattr(user, "token_version", 1) or 1) + 1
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

    # 编码/渲染设置：仅提交显式选择的值；空/未设置表示“不下发、不改动”
    clip_patch: dict[str, Any] = {}
    for key, raw in (
        ("encode_enable_gpu", encode_enable_gpu),
        ("clip_trim_ep1_continued", clip_trim_ep1_continued),
        ("clip_overlay_bake_png", clip_overlay_bake_png),
        ("clip_auto_select_after_import", clip_auto_select_after_import),
    ):
        value = _parse_tristate(raw)
        if value is not None:
            clip_patch[key] = value
    for key, raw in (
        ("encode_nvenc_preset", encode_nvenc_preset),
        ("encode_amf_preset", encode_amf_preset),
        ("encode_qsv_preset", encode_qsv_preset),
        ("encode_x264_preset", encode_x264_preset),
        ("clip_render_engine", clip_render_engine),
    ):
        text = (raw or "").strip()
        if text and text != "__unset__":
            clip_patch[key] = text
    if clip_patch:
        patch_user_settings(db, user.id, {"clip_edit": clip_patch})
        db.commit()

    # 策划设置：混合模式策略版本
    strat = (plan_mixed_strategy or "").strip().lower()
    if strat in ("v1", "v2"):
        patch_user_settings(db, user.id, {"plan": {"mixed_strategy": strat}})
        db.commit()

    return RedirectResponse(f"/admin/user/edit/{user_id}?saved=1", status_code=302)


@router.post("/users/{user_id}/revoke-session")
@router.post("/user/edit/{user_id}/revoke-session")
def user_revoke_session(
    request: Request,
    user_id: int,
    db: Db,
):
    if not _is_logged_in(request):
        return RedirectResponse("/admin/login", status_code=302)
    user = db.get(User, user_id)
    if user is None:
        return HTMLResponse("用户不存在", status_code=404)
    user.token_version = (getattr(user, "token_version", 1) or 1) + 1
    db.commit()
    referer = request.headers.get("referer") or f"/admin/user/edit/{user_id}"
    sep = "&" if "?" in referer else "?"
    return RedirectResponse(f"{referer}{sep}msg=session_revoked", status_code=302)


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
            "plan_model": row.plan_model or "—",
            "transcribe_time": _fmt_duration_ms(row.transcribe_ms),
            "plan_time": _fmt_duration_ms(row.plan_ms),
            "render_time": _fmt_duration_ms(row.render_ms),
            "duration_time": _fmt_duration_ms(row.duration_ms),
            "duration_ms": row.duration_ms,
            "encoder": row.encoder or "—",
            "resolution": row.resolution or "—",
            "cache_ms": row.cache_ms,
            "compose_ms": row.compose_ms,
            "render_engine": row.render_engine or "—",
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
        search_cols=[
            UsageEvent.event,
            UsageEvent.meta,
            UsageEvent.plan_mode,
            UsageEvent.plan_model,
            UsageEvent.encoder,
        ],
        q=q,
        page=page,
        row_mapper=mapper,
    )


def _cores_text(physical: int, logical: int) -> str:
    if physical > 0 and logical > 0 and physical != logical:
        return f"{physical} 核 / {logical} 线程"
    if physical > 0:
        return f"{physical} 核"
    if logical > 0:
        return f"{logical} 线程"
    return "—"


def _ram_text(total_mb: int, available_mb: int) -> str:
    if total_mb <= 0:
        return "—"
    total_gb = total_mb / 1024.0
    if available_mb > 0:
        return f"{total_gb:.1f} GB（可用 {available_mb / 1024.0:.1f} GB）"
    return f"{total_gb:.1f} GB"


def _machine_to_dict(row: UserMachine | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "os": row.os or "—",
        "hostname": row.hostname or "—",
        "cpu_name": row.cpu_name or "—",
        "cores": _cores_text(row.cpu_cores_physical, row.cpu_cores_logical),
        "ram": _ram_text(row.ram_total_mb, row.ram_available_mb),
        "gpu_summary": row.gpu_summary or "—",
        "client_version": row.client_version or "—",
        "updated_at": _fmt_dt(row.updated_at),
    }


@router.get("/machines", response_class=HTMLResponse)
def machines_list(
    request: Request,
    db: Db,
    q: str = "",
    page: int = Query(default=1, ge=1),
):
    def mapper(row: UserMachine) -> dict:
        username = row.user.username if row.user else f"#{row.user_id}"
        return {
            "id": row.id,
            "username": username,
            "cpu_name": row.cpu_name or "—",
            "cores": _cores_text(row.cpu_cores_physical, row.cpu_cores_logical),
            "ram": _ram_text(row.ram_total_mb, row.ram_available_mb),
            "gpu_summary": row.gpu_summary or "—",
            "os": row.os or "—",
            "hostname": row.hostname or "—",
            "client_version": row.client_version or "—",
            "updated_at": _fmt_dt(row.updated_at),
        }

    return _list_page(
        request,
        db,
        active="machines",
        template="admin/machines.html",
        model=UserMachine,
        order_col=UserMachine.updated_at,
        search_cols=[
            UserMachine.cpu_name,
            UserMachine.gpu_summary,
            UserMachine.os,
            UserMachine.hostname,
        ],
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


@router.post("/errors/batch-resolve")
def error_reports_batch_resolve(
    request: Request,
    db: Db,
    q: Annotated[str, Form()] = "",
    status: Annotated[str, Form()] = "resolved",
):
    if not _is_logged_in(request):
        return RedirectResponse("/admin/login", status_code=302)

    target_status = status if status in ("resolved", "ignored") else "resolved"
    stmt = update(ErrorReport).where(ErrorReport.status == "pending")

    keyword = (q or "").strip()
    if keyword:
        like = f"%{keyword}%"
        search_cols = [
            ErrorReport.username,
            ErrorReport.drama_name,
            ErrorReport.friendly_msg,
            ErrorReport.raw_error,
            ErrorReport.error_stage,
        ]
        stmt = stmt.where(or_(*[col.like(like) for col in search_cols]))

    stmt = stmt.values(status=target_status)
    db.execute(stmt)
    db.commit()

    referer = request.headers.get("referer") or "/admin/errors"
    return RedirectResponse(referer, status_code=302)


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


@router.get("/profile", response_class=HTMLResponse)
def profile_page(
    request: Request,
    db: Db,
    msg: str = "",
    error: str = "",
):
    if not _is_logged_in(request):
        return RedirectResponse("/admin/login", status_code=302)
    theme = _get_login_theme()
    return templates.TemplateResponse(
        request,
        "admin/profile.html",
        _ctx(
            request,
            active="profile",
            db=db,
            theme=theme,
            presets=LOGIN_BG_PRESETS,
            admin_username=settings.admin_username,
            msg=msg,
            error=error,
            now_str=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )


@router.post("/profile/theme")
async def profile_theme_save(
    request: Request,
    mode: Annotated[str, Form()] = "default",
    preset_key: Annotated[str, Form()] = "default",
    custom_url: Annotated[str, Form()] = "",
    glass: Annotated[str, Form()] = "",
    bg_file: UploadFile | None = File(None),
):
    if not _is_logged_in(request):
        return RedirectResponse("/admin/login", status_code=302)

    try:
        _STATIC_DIR.mkdir(parents=True, exist_ok=True)
        has_uploaded = _UPLOADED_BG_FILE.is_file()

        if bg_file and bg_file.filename:
            ext = Path(bg_file.filename).suffix.lower()
            if ext not in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".svg"):
                from urllib.parse import quote
                return RedirectResponse(f"/admin/profile?error={quote('仅支持上传图片格式文件 (PNG/JPG/WEBP等)')}", status_code=302)
            content = await bg_file.read()
            if not content:
                from urllib.parse import quote
                return RedirectResponse(f"/admin/profile?error={quote('上传的文件内容为空，请重新选择')}", status_code=302)
            if len(content) > 15 * 1024 * 1024:
                from urllib.parse import quote
                return RedirectResponse(f"/admin/profile?error={quote('上传文件过大，单张背景图片请控制在 15MB 以内')}", status_code=302)
            _UPLOADED_BG_FILE.write_bytes(content)
            has_uploaded = True
            mode = "upload"

        mode_clean = mode.strip().lower()
        if mode_clean not in ("preset", "url", "upload", "default"):
            mode_clean = "default"

        theme_data = {
            "mode": mode_clean,
            "preset_key": (preset_key or "default").strip(),
            "custom_url": (custom_url or "").strip(),
            "glass": glass in ("1", "true", "on"),
            "has_uploaded": has_uploaded,
        }
        _save_login_theme(theme_data)
        return RedirectResponse("/admin/profile?msg=saved", status_code=302)
    except Exception as e:
        from urllib.parse import quote
        logger.exception("保存登录封面设置失败: {}", e)
        return RedirectResponse(f"/admin/profile?error={quote('保存失败: ' + str(e))}", status_code=302)


@router.post("/profile/theme/reset-upload")
def profile_theme_reset_upload(request: Request):
    if not _is_logged_in(request):
        return RedirectResponse("/admin/login", status_code=302)
    if _UPLOADED_BG_FILE.is_file():
        try:
            _UPLOADED_BG_FILE.unlink()
        except OSError:
            pass
    theme = _get_login_theme()
    if theme.get("mode") == "upload":
        theme["mode"] = "default"
    theme["has_uploaded"] = False
    _save_login_theme(theme)
    return RedirectResponse("/admin/profile?msg=upload_deleted", status_code=302)


# ---------------------------------------------------------------------------
# 音乐电台与 B 站音源管理
# ---------------------------------------------------------------------------
from app.services.radio_service import (
    parse_bilibili_video,
    download_bilibili_track,
    save_uploaded_track,
    list_radio_tracks,
    get_radio_track,
    update_radio_track,
    delete_radio_track,
    increment_track_play_count,
    get_radio_stats,
    list_radio_groups,
    get_radio_group,
    create_radio_group,
    update_radio_group,
    delete_radio_group,
    set_track_groups,
    _STATIC_RADIO_DIR,
)


@router.get("/radio", response_class=HTMLResponse)
def radio_page(
    request: Request,
    db: Db,
    q: str = "",
    group_id: int | None = None,
    msg: str = "",
    error: str = "",
):
    if not _is_logged_in(request):
        return RedirectResponse("/admin/login", status_code=302)
    tracks = list_radio_tracks(db, q=q, group_id=group_id)
    stats = get_radio_stats(db)
    groups = list_radio_groups(db)
    active_group = get_radio_group(group_id, db) if group_id else None
    return templates.TemplateResponse(
        request,
        "admin/radio.html",
        _ctx(
            request,
            active="radio",
            db=db,
            tracks=tracks,
            stats=stats,
            groups=groups,
            active_group_id=group_id,
            active_group=active_group,
            q=q,
            msg=msg,
            error=error,
        ),
    )


@router.get("/api/radio/tracks")
def api_radio_tracks(request: Request, db: Db, q: str = "", group_id: int | None = None):
    if not _is_logged_in(request):
        return JSONResponse({"detail": "未登录"}, status_code=401)
    tracks = list_radio_tracks(db, q=q, group_id=group_id)
    return {
        "tracks": [
            {
                "id": t.id,
                "title": t.title,
                "artist": t.artist,
                "duration": t.duration,
                "cover_url": t.cover_url,
                "audio_url": t.audio_url,
                "source_type": t.source_type,
                "source_url": t.source_url,
                "source_id": t.source_id,
                "file_size": t.file_size,
                "play_count": t.play_count,
                "groups": getattr(t, "groups", []),
                "group_ids": getattr(t, "group_ids", []),
                "created_at": t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else "",
            }
            for t in tracks
        ]
    }


@router.get("/api/radio/groups")
def api_radio_groups(request: Request, db: Db):
    if not _is_logged_in(request):
        return JSONResponse({"ok": False, "error": "未登录"}, status_code=401)
    return {"ok": True, "groups": list_radio_groups(db)}


@router.post("/api/radio/groups/create")
async def api_radio_group_create(request: Request, db: Db):
    if not _is_logged_in(request):
        return JSONResponse({"ok": False, "error": "未登录"}, status_code=401)
    try:
        data = await request.json()
    except Exception:
        data = {}
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    try:
        group = create_radio_group(name, description, db)
        return {
            "ok": True,
            "group": {
                "id": group.id,
                "name": group.name,
                "description": group.description or "",
                "track_count": 0,
            },
        }
    except ValueError as ve:
        return JSONResponse({"ok": False, "error": str(ve)})
    except Exception as e:
        logger.exception("创建分组失败: %s", e)
        return JSONResponse({"ok": False, "error": "创建分组失败，请稍后重试"})


@router.post("/api/radio/groups/{group_id}/update")
async def api_radio_group_update(request: Request, group_id: int, db: Db):
    if not _is_logged_in(request):
        return JSONResponse({"ok": False, "error": "未登录"}, status_code=401)
    try:
        data = await request.json()
    except Exception:
        data = {}
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    try:
        group = update_radio_group(group_id, name, description, db)
        if not group:
            return JSONResponse({"ok": False, "error": "分组不存在"}, status_code=404)
        return {
            "ok": True,
            "group": {
                "id": group.id,
                "name": group.name,
                "description": group.description or "",
            },
        }
    except ValueError as ve:
        return JSONResponse({"ok": False, "error": str(ve)})
    except Exception as e:
        logger.exception("更新分组失败: %s", e)
        return JSONResponse({"ok": False, "error": "更新分组失败，请稍后重试"})


@router.post("/api/radio/groups/{group_id}/delete")
def api_radio_group_delete(request: Request, group_id: int, db: Db):
    if not _is_logged_in(request):
        return JSONResponse({"ok": False, "error": "未登录"}, status_code=401)
    success = delete_radio_group(group_id, db)
    if not success:
        return JSONResponse({"ok": False, "error": "分组不存在或删除失败"}, status_code=404)
    return {"ok": True}


@router.post("/api/radio/tracks/{track_id}/groups")
async def api_radio_track_set_groups(request: Request, track_id: int, db: Db):
    if not _is_logged_in(request):
        return JSONResponse({"ok": False, "error": "未登录"}, status_code=401)
    try:
        data = await request.json()
    except Exception:
        data = {}
    raw_group_ids = data.get("group_ids", [])
    group_ids: list[int] = []
    if isinstance(raw_group_ids, list):
        for gid in raw_group_ids:
            try:
                group_ids.append(int(gid))
            except (TypeError, ValueError):
                pass
    try:
        assigned_groups = set_track_groups(track_id, group_ids, db)
        return {"ok": True, "groups": assigned_groups}
    except Exception as e:
        logger.exception("设置曲目分组失败: %s", e)
        return JSONResponse({"ok": False, "error": str(e)})


@router.post("/api/radio/bilibili/parse")
async def api_radio_bilibili_parse(request: Request):
    if not _is_logged_in(request):
        return JSONResponse({"ok": False, "error": "未登录"}, status_code=401)
    try:
        data = await request.json()
    except Exception:
        data = {}
    url = (data.get("url") or "").strip()
    if not url:
        return JSONResponse({"ok": False, "error": "请输入有效的 B 站视频链接或 BV 号！"})
    try:
        info = await parse_bilibili_video(url)
        return {"ok": True, "data": info}
    except Exception as e:
        logger.warning("B站链接解析失败: %s", e)
        return JSONResponse({"ok": False, "error": str(e)})


@router.post("/api/radio/bilibili/download")
async def api_radio_bilibili_download(request: Request, db: Db):
    if not _is_logged_in(request):
        return JSONResponse({"ok": False, "error": "未登录"}, status_code=401)
    try:
        data = await request.json()
    except Exception:
        data = {}
    url = (data.get("url") or "").strip()
    custom_title = (data.get("title") or "").strip() or None
    custom_artist = (data.get("artist") or "").strip() or None
    cid = data.get("cid")
    if cid:
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            cid = None

    group_id = data.get("group_id")
    if group_id:
        try:
            group_id = int(group_id)
        except (TypeError, ValueError):
            group_id = None

    if not url:
        return JSONResponse({"ok": False, "error": "缺少 B 站链接参数！"})
    try:
        track = await download_bilibili_track(
            url,
            db,
            custom_title=custom_title,
            custom_artist=custom_artist,
            cid_override=cid,
            group_id=group_id,
        )
        return {
            "ok": True,
            "track": {
                "id": track.id,
                "title": track.title,
                "artist": track.artist,
                "duration": track.duration,
                "cover_url": track.cover_url,
                "audio_url": track.audio_url,
                "source_type": track.source_type,
                "source_url": track.source_url,
                "source_id": track.source_id,
                "file_size": track.file_size,
                "play_count": track.play_count,
                "groups": getattr(track, "groups", []),
                "group_ids": getattr(track, "group_ids", []),
            },
        }
    except Exception as e:
        logger.exception("B站音频下载入库失败: %s", e)
        return JSONResponse({"ok": False, "error": str(e)})


@router.post("/api/radio/upload")
async def api_radio_upload(
    request: Request,
    db: Db,
    file: UploadFile = File(...),
    title: Annotated[str, Form()] = "",
    artist: Annotated[str, Form()] = "",
    group_id: Annotated[int | None, Form()] = None,
):
    if not _is_logged_in(request):
        return JSONResponse({"ok": False, "error": "未登录"}, status_code=401)
    try:
        content = await file.read()
        if not content:
            return JSONResponse({"ok": False, "error": "上传的文件内容为空！"})
        if len(content) > 50 * 1024 * 1024:
            return JSONResponse({"ok": False, "error": "文件过大，单首音频请控制在 50MB 以内！"})
        track = await save_uploaded_track(
            content,
            file.filename or "unknown.mp3",
            db,
            custom_title=title or None,
            custom_artist=artist or None,
            group_id=group_id,
        )
        return {
            "ok": True,
            "track": {
                "id": track.id,
                "title": track.title,
                "artist": track.artist,
                "duration": track.duration,
                "cover_url": track.cover_url,
                "audio_url": track.audio_url,
                "source_type": track.source_type,
                "source_id": track.source_id,
                "file_size": track.file_size,
                "groups": getattr(track, "groups", []),
                "group_ids": getattr(track, "group_ids", []),
            },
        }
    except Exception as e:
        logger.exception("本地音频上传入库失败: %s", e)
        return JSONResponse({"ok": False, "error": str(e)})


@router.post("/api/radio/tracks/{track_id}/update")
async def api_radio_track_update(request: Request, track_id: int, db: Db):
    if not _is_logged_in(request):
        return JSONResponse({"ok": False, "error": "未登录"}, status_code=401)
    try:
        data = await request.json()
    except Exception:
        data = {}
    title = (data.get("title") or "").strip()
    artist = (data.get("artist") or "").strip()
    track = update_radio_track(track_id, title, artist, db)
    if not track:
        return JSONResponse({"ok": False, "error": "曲目不存在"}, status_code=404)
    return {"ok": True}


@router.post("/api/radio/tracks/{track_id}/delete")
def api_radio_track_delete(request: Request, track_id: int, db: Db):
    if not _is_logged_in(request):
        return JSONResponse({"ok": False, "error": "未登录"}, status_code=401)
    success = delete_radio_track(track_id, db)
    if not success:
        return JSONResponse({"ok": False, "error": "曲目不存在或删除失败"}, status_code=404)
    return {"ok": True}


@router.post("/api/radio/tracks/{track_id}/play")
def api_radio_track_play(request: Request, track_id: int, db: Db):
    if not _is_logged_in(request):
        return JSONResponse({"ok": False}, status_code=401)
    increment_track_play_count(track_id, db)
    return {"ok": True}


@router.get("/version", response_class=HTMLResponse)
def admin_version_page(request: Request, db: Db):
    if not _is_logged_in(request):
        return _login_redirect(request)

    v_out = client_version_service.build_client_version_out(request)
    raw_file = client_version_service._load_version_file() or {}
    installer_name = str(raw_file.get("installer") or raw_file.get("filename") or "").strip()

    version_stats: list[dict[str, Any]] = []
    try:
        rows = db.execute(
            select(
                UserMachine.client_version,
                func.count(UserMachine.id).label("machine_count"),
                func.max(UserMachine.updated_at).label("last_active"),
            )
            .where(UserMachine.client_version != "")
            .group_by(UserMachine.client_version)
            .order_by(desc("machine_count"))
        ).all()
        for r in rows:
            ver = r[0]
            count = r[1]
            last_active = r[2]
            is_blocked = False
            if v_out.min_supported:
                is_blocked = client_version_service.is_version_older(
                    ver.lstrip("vV"), v_out.min_supported.lstrip("vV")
                )
            version_stats.append(
                {
                    "version": ver,
                    "machine_count": count,
                    "last_active": last_active.strftime("%Y-%m-%d %H:%M") if last_active else "—",
                    "is_blocked": is_blocked,
                }
            )
    except Exception:
        version_stats = []

    ctx = _ctx(
        request,
        active="version",
        db=db,
        version_out=v_out,
        installer_name=installer_name,
        version_stats=version_stats,
    )
    return templates.TemplateResponse(
        request,
        "admin/version.html",
        ctx,
    )


@router.post("/api/version/save")
async def admin_api_version_save(request: Request, db: Db):
    if not _is_logged_in(request):
        return JSONResponse({"ok": False, "error": "未登录"}, status_code=401)
    try:
        data = await request.json()
    except Exception:
        data = {}
    latest = (data.get("latest") or "").strip()
    min_supported = (data.get("min_supported") or "").strip()
    download_url = (data.get("download_url") or "").strip()
    changelog = (data.get("changelog") or "").strip()
    installer = (data.get("installer") or "").strip()

    if not latest:
        return JSONResponse({"ok": False, "error": "最新版本号不能为空"}, status_code=400)
    if not min_supported:
        min_supported = latest

    saved = client_version_service.save_version_file(
        latest=latest,
        min_supported=min_supported,
        download_url=download_url,
        changelog=changelog,
        installer=installer,
    )
    return {"ok": True, "data": saved, "message": "版本配置已保存，实时生效"}


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
    _STATIC_RADIO_DIR.mkdir(parents=True, exist_ok=True)
    (_STATIC_RADIO_DIR / "tracks").mkdir(parents=True, exist_ok=True)
    (_STATIC_RADIO_DIR / "covers").mkdir(parents=True, exist_ok=True)
    app.mount(
        "/static/radio",
        StaticFiles(directory=str(_STATIC_RADIO_DIR)),
        name="radio-static",
    )
    return router

