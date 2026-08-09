import json

from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqladmin import Admin, ModelView, action
from sqladmin.authentication import AuthenticationBackend
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse
from markupsafe import Markup, escape
from wtforms import BooleanField as WTBooleanField, SelectField, StringField, TextAreaField
from wtforms.widgets import CheckboxInput

from app.config import settings
from app.database import engine
from app.models import PlanJob, UsageEvent, User, UserDailyActivity, UserSettings
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

# 每日活动「剧目」列：固定宽度 + 省略号，悬停看全文
_DRAMA_COL_MAX_WIDTH_PX = 200


def _iocpx_account(model, _attr):
    user = getattr(model, "user", None)
    if user is not None:
        return user.username
    user_id = getattr(model, "user_id", None)
    return f"#{user_id}" if user_id else "-"


def _plan_mode_label(model, _attr):
    mode = str(getattr(model, "plan_mode", None) or "").strip().lower()
    return PLAN_MODE_LABELS.get(mode, mode or "-")


def _drama_column_key(attr) -> str:
    """sqladmin 传入的 attr 可能是 ColumnProperty，也可能是列名字符串。"""
    if isinstance(attr, str):
        return attr
    key = getattr(attr, "key", None) or getattr(attr, "name", None)
    return str(key) if key else ""


def _drama_names_text(model, attr) -> str:
    """解析剧目 JSON 列表为顿号分隔文案。"""
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
    """列表页：定宽省略，title 悬停显示完整剧目。"""
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


def _drama_names_detail(model, attr):
    """详情页展示完整剧目名。"""
    return _drama_names_text(model, attr) or "-"


def _is_active_label(model, _attr):
    return "启用" if getattr(model, "is_active", True) else "已禁用"


def _valid_until_label(model, _attr):
    value = getattr(model, "valid_until", None)
    return value.isoformat() if value else "永久"


def _deepseek_keys_label(model, _attr):
    secret = getattr(model, "secrets", None)
    keys = (secret.deepseek_keys if secret else "") or ""
    if not keys:
        return "未配置"
    return keys if len(keys) <= 32 else f"{keys[:32]}…"


def _plan_llm_model_label(model, _attr):
    secret = getattr(model, "secrets", None)
    provider = normalize_plan_llm_provider(
        getattr(secret, "plan_llm_provider", None) if secret else None
    )
    model_name = normalize_plan_llm_model(
        getattr(secret, "plan_llm_model", None) if secret else None,
        provider=provider,
    )
    return plan_llm_preset_label(provider, model_name)


class _SwitchCheckboxInput(CheckboxInput):
    """紧凑的 Tabler 开关样式，兼容 wtforms 3.x。"""

    def __call__(self, field, **kwargs):
        kwargs["class"] = "form-check-input"
        kwargs.setdefault("role", "switch")
        if field.data:
            kwargs.setdefault("checked", True)
        checkbox = super().__call__(field, **kwargs)
        return Markup(
            '<div class="form-check form-switch m-0">'
            f"{checkbox}</div>"
        )


class _DesktopAccessField(WTBooleanField):
    widget = _SwitchCheckboxInput()


def _redirect_back(request: Request, identity: str) -> RedirectResponse:
    referer = request.headers.get("Referer")
    if referer:
        return RedirectResponse(referer, status_code=302)
    return RedirectResponse(
        str(request.url_for("admin:list", identity=identity)),
        status_code=302,
    )


def _set_users_active(model_view: ModelView, pks: list[str], active: bool) -> None:
    with model_view.session_maker() as session:
        for pk in pks:
            user = session.get(User, int(pk))
            if user is not None:
                user.is_active = active
        session.commit()


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = form.get("username")
        password = form.get("password")
        if username == settings.admin_username and password == settings.admin_password:
            request.session.update({"admin": True})
            return True
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return bool(request.session.get("admin"))


class UserAdmin(ModelView, model=User):
    name = "用户"
    name_plural = "用户"
    can_create = False
    form_include_pk = False
    form_columns = [
        User.username,
        User.role,
        User.is_active,
        User.valid_until,
        User.daily_plan_limit,
        User.daily_clip_limit,
    ]
    form_overrides = {"is_active": _DesktopAccessField}
    form_args = {
        "is_active": {"label": "允许使用桌面端"},
        "valid_until": {"label": "使用期限（空=永久）"},
        "daily_plan_limit": {"label": "每日策划上限（0=不限，默认30）"},
        "daily_clip_limit": {"label": "每日剪辑上限（0=不限，默认30）"},
    }
    form_widget_args = {"is_active": {"class": "form-check-input"}}
    column_list = [
        User.id,
        User.username,
        User.plain_password,
        User.role,
        User.is_active,
        User.valid_until,
        User.daily_plan_limit,
        User.daily_clip_limit,
        "plan_llm_model",
        "deepseek_keys",
        User.created_at,
    ]
    column_labels = {
        User.id: "ID",
        User.username: "账号",
        User.plain_password: "密码",
        User.role: "角色",
        User.is_active: "允许使用桌面端",
        User.valid_until: "使用期限",
        User.daily_plan_limit: "每日策划上限",
        User.daily_clip_limit: "每日剪辑上限",
        User.created_at: "创建时间",
        "plan_llm_model": "策划模型",
        "deepseek_keys": "策划 API Keys",
    }
    column_searchable_list = [User.username]
    column_formatters = {
        User.is_active: _is_active_label,
        User.valid_until: _valid_until_label,
        "plan_llm_model": _plan_llm_model_label,
        "deepseek_keys": _deepseek_keys_label,
    }
    column_details_list = [
        User.id,
        User.username,
        User.plain_password,
        User.role,
        User.is_active,
        User.valid_until,
        User.daily_plan_limit,
        User.daily_clip_limit,
        "plan_llm_model",
        "deepseek_keys",
        User.created_at,
    ]
    column_formatters_detail = {
        User.is_active: _is_active_label,
        User.valid_until: _valid_until_label,
        "plan_llm_model": _plan_llm_model_label,
        "deepseek_keys": _deepseek_keys_label,
    }

    def list_query(self, request: Request):
        return select(User).options(joinedload(User.secrets))

    def form_edit_query(self, request: Request):
        pk = request.path_params.get("pk")
        stmt = select(User).options(joinedload(User.secrets))
        if pk:
            return self._stmt_by_identifier(pk).options(joinedload(User.secrets))
        return stmt

    async def get_object_for_edit(self, request: Request):
        user = await super().get_object_for_edit(request)
        if user is None:
            return None
        secret = user.secrets
        user.deepseek_keys = (secret.deepseek_keys if secret else "") or ""
        user.dashscope_key = (secret.dashscope_key if secret else "") or ""
        provider = normalize_plan_llm_provider(
            getattr(secret, "plan_llm_provider", None) if secret else None
        )
        model_name = normalize_plan_llm_model(
            getattr(secret, "plan_llm_model", None) if secret else None,
            provider=provider,
        )
        user.plan_llm_preset = encode_plan_llm_preset(provider, model_name)
        return user

    async def scaffold_form(self, rules=None):
        base_form = await super().scaffold_form(rules=None)

        class UserForm(base_form):
            plan_llm_preset = SelectField(
                "策划模型",
                choices=list(PLAN_LLM_PRESET_CHOICES),
                default=f"{PLAN_LLM_PROVIDER_DEEPSEEK}|deepseek-v4-flash",
                description="官方填 DeepSeek Key；OpenCode Go 填 Zen/Go 套餐 Key",
            )
            deepseek_keys = TextAreaField(
                "策划 API Keys（逗号分隔）",
                description="与上方模型对应：官方 DeepSeek Key 或 OpenCode Go Key",
            )
            dashscope_key = StringField("DashScope Key（可选）")

        if rules:
            self._validate_form_class(rules, UserForm)
        return UserForm

    async def on_model_change(self, data, model, is_created, request):
        request.state.admin_user_deepseek_keys = (
            data.pop("deepseek_keys", None) or ""
        ).strip()
        request.state.admin_user_dashscope_key = (
            data.pop("dashscope_key", None) or ""
        ).strip()
        request.state.admin_user_plan_llm_preset = (
            data.pop("plan_llm_preset", None) or ""
        ).strip()

    async def after_model_change(self, data, model, is_created, request):
        deepseek = getattr(request.state, "admin_user_deepseek_keys", "")
        dashscope = getattr(request.state, "admin_user_dashscope_key", "")
        preset = getattr(request.state, "admin_user_plan_llm_preset", "")
        provider, llm_model = decode_plan_llm_preset(preset)
        with self.session_maker() as session:
            secret = ensure_user_secret(session, model.id)
            secret.deepseek_keys = deepseek
            secret.dashscope_key = dashscope
            secret.plan_llm_provider = provider
            secret.plan_llm_model = llm_model
            session.commit()

    @action(
        name="enable-access",
        label="启用桌面端",
        confirmation_message="确定允许选中用户使用桌面端？",
        add_in_detail=True,
        add_in_list=True,
    )
    async def enable_access(self, request: Request):
        pks = [pk for pk in request.query_params.get("pks", "").split(",") if pk]
        if pks:
            _set_users_active(self, pks, True)
        return _redirect_back(request, self.identity)

    @action(
        name="disable-access",
        label="禁用桌面端",
        confirmation_message="确定禁止选中用户使用桌面端？",
        add_in_detail=True,
        add_in_list=True,
    )
    async def disable_access(self, request: Request):
        pks = [pk for pk in request.query_params.get("pks", "").split(",") if pk]
        if pks:
            _set_users_active(self, pks, False)
        return _redirect_back(request, self.identity)


class UserSettingsAdmin(ModelView, model=UserSettings):
    name = "用户配置"
    name_plural = "用户配置"
    column_list = [
        UserSettings.id,
        UserSettings.user_id,
        UserSettings.data,
        UserSettings.updated_at,
    ]
    column_labels = {
        UserSettings.user_id: "易投账号",
    }
    column_formatters = {
        UserSettings.user_id: _iocpx_account,
    }
    column_searchable_list = [UserSettings.data]
    form_excluded_columns = [UserSettings.user]

    def list_query(self, request: Request):
        return select(UserSettings).options(joinedload(UserSettings.user))

    def details_query(self, request: Request):
        return select(UserSettings).options(joinedload(UserSettings.user))


class UsageEventAdmin(ModelView, model=UsageEvent):
    name = "使用记录"
    name_plural = "使用记录"
    can_create = False
    can_edit = False
    can_delete = False
    column_list = [
        UsageEvent.id,
        UsageEvent.user_id,
        UsageEvent.event,
        UsageEvent.success,
        UsageEvent.meta,
        UsageEvent.plan_mode,
        UsageEvent.duration_ms,
        UsageEvent.client_version,
        UsageEvent.created_at,
    ]
    column_labels = {
        UsageEvent.user_id: "易投账号",
        UsageEvent.event: "事件",
        UsageEvent.success: "成功",
        UsageEvent.meta: "详情",
        UsageEvent.plan_mode: "策划模式",
        UsageEvent.duration_ms: "耗时(ms)",
        UsageEvent.client_version: "客户端版本",
        UsageEvent.created_at: "时间",
    }
    column_formatters = {
        UsageEvent.user_id: _iocpx_account,
        UsageEvent.plan_mode: _plan_mode_label,
    }
    column_sortable_list = [UsageEvent.id, UsageEvent.created_at, UsageEvent.plan_mode]
    column_default_sort = [(UsageEvent.id, True)]
    column_searchable_list = [UsageEvent.event, UsageEvent.meta, UsageEvent.plan_mode]
    column_details_list = [
        UsageEvent.id,
        UsageEvent.user_id,
        UsageEvent.event,
        UsageEvent.success,
        UsageEvent.meta,
        UsageEvent.plan_mode,
        UsageEvent.duration_ms,
        UsageEvent.client_version,
        UsageEvent.created_at,
    ]
    column_formatters_detail = {
        UsageEvent.user_id: _iocpx_account,
        UsageEvent.plan_mode: _plan_mode_label,
    }

    def list_query(self, request: Request):
        return select(UsageEvent).options(joinedload(UsageEvent.user))

    def details_query(self, request: Request):
        return select(UsageEvent).options(joinedload(UsageEvent.user))


class PlanJobAdmin(ModelView, model=PlanJob):
    name = "策划任务"
    name_plural = "策划任务"
    can_create = False
    can_edit = False
    can_delete = False
    column_list = [
        PlanJob.id,
        PlanJob.user_id,
        PlanJob.status,
        PlanJob.project_name,
        PlanJob.plan_mode,
        PlanJob.error,
        PlanJob.created_at,
        PlanJob.updated_at,
    ]
    column_labels = {
        PlanJob.id: "任务ID",
        PlanJob.user_id: "易投账号",
        PlanJob.status: "状态",
        PlanJob.project_name: "剧目",
        PlanJob.plan_mode: "策划模式",
        PlanJob.error: "错误",
        PlanJob.created_at: "创建时间",
        PlanJob.updated_at: "更新时间",
    }
    column_formatters = {
        PlanJob.user_id: _iocpx_account,
        PlanJob.plan_mode: _plan_mode_label,
    }
    column_sortable_list = [
        PlanJob.created_at,
        PlanJob.updated_at,
        PlanJob.status,
        PlanJob.plan_mode,
    ]
    column_default_sort = [(PlanJob.created_at, True)]
    column_searchable_list = [
        PlanJob.id,
        PlanJob.status,
        PlanJob.project_name,
        PlanJob.plan_mode,
        PlanJob.error,
    ]
    column_details_list = [
        PlanJob.id,
        PlanJob.user_id,
        PlanJob.status,
        PlanJob.project_name,
        PlanJob.plan_mode,
        PlanJob.progress_json,
        PlanJob.error,
        PlanJob.created_at,
        PlanJob.updated_at,
    ]
    column_formatters_detail = {
        PlanJob.user_id: _iocpx_account,
        PlanJob.plan_mode: _plan_mode_label,
    }


class UserDailyActivityAdmin(ModelView, model=UserDailyActivity):
    name = "每日活动"
    name_plural = "每日活动"
    can_create = False
    can_edit = False
    can_delete = False
    column_list = [
        UserDailyActivity.id,
        UserDailyActivity.user_id,
        UserDailyActivity.activity_date,
        UserDailyActivity.login_at,
        UserDailyActivity.logout_at,
        UserDailyActivity.downloaded_dramas,
        UserDailyActivity.planned_dramas,
        UserDailyActivity.clipped_dramas,
        UserDailyActivity.plan_count,
        UserDailyActivity.clip_count,
        UserDailyActivity.updated_at,
    ]
    column_labels = {
        UserDailyActivity.user_id: "易投账号",
        UserDailyActivity.activity_date: "日期",
        UserDailyActivity.login_at: "登录时间",
        UserDailyActivity.logout_at: "关闭时间",
        UserDailyActivity.downloaded_dramas: "下载剧目",
        UserDailyActivity.planned_dramas: "策划剧目",
        UserDailyActivity.clipped_dramas: "剪辑剧目",
        UserDailyActivity.plan_count: "策划部数",
        UserDailyActivity.clip_count: "剪辑部数",
        UserDailyActivity.updated_at: "更新时间",
    }
    column_formatters = {
        UserDailyActivity.user_id: _iocpx_account,
        UserDailyActivity.downloaded_dramas: _drama_names_ellipsis,
        UserDailyActivity.planned_dramas: _drama_names_ellipsis,
        UserDailyActivity.clipped_dramas: _drama_names_ellipsis,
    }
    column_sortable_list = [
        UserDailyActivity.id,
        UserDailyActivity.activity_date,
        UserDailyActivity.updated_at,
    ]
    column_default_sort = [(UserDailyActivity.activity_date, True)]
    column_searchable_list = [
        UserDailyActivity.downloaded_dramas,
        UserDailyActivity.planned_dramas,
        UserDailyActivity.clipped_dramas,
    ]
    column_details_list = [
        UserDailyActivity.id,
        UserDailyActivity.user_id,
        UserDailyActivity.activity_date,
        UserDailyActivity.login_at,
        UserDailyActivity.logout_at,
        UserDailyActivity.downloaded_dramas,
        UserDailyActivity.planned_dramas,
        UserDailyActivity.clipped_dramas,
        UserDailyActivity.plan_count,
        UserDailyActivity.clip_count,
        UserDailyActivity.updated_at,
    ]
    column_formatters_detail = {
        UserDailyActivity.user_id: _iocpx_account,
        UserDailyActivity.downloaded_dramas: _drama_names_detail,
        UserDailyActivity.planned_dramas: _drama_names_detail,
        UserDailyActivity.clipped_dramas: _drama_names_detail,
    }

    def list_query(self, request: Request):
        return select(UserDailyActivity).options(joinedload(UserDailyActivity.user))

    def details_query(self, request: Request):
        return select(UserDailyActivity).options(joinedload(UserDailyActivity.user))


def setup_admin(app: Starlette) -> Admin:
    authentication_backend = AdminAuth(secret_key=settings.jwt_secret)
    admin = Admin(
        app,
        engine,
        authentication_backend=authentication_backend,
        middlewares=[Middleware(SessionMiddleware, secret_key=settings.jwt_secret)],
    )
    admin.add_view(UserAdmin)
    admin.add_view(UserSettingsAdmin)
    admin.add_view(UsageEventAdmin)
    admin.add_view(PlanJobAdmin)
    admin.add_view(UserDailyActivityAdmin)
    return admin
