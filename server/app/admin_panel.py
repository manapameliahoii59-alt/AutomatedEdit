from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqladmin import Admin, ModelView, action
from sqladmin.authentication import AuthenticationBackend
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse
from markupsafe import Markup
from wtforms import BooleanField as WTBooleanField
from wtforms.widgets import CheckboxInput

from app.config import settings
from app.database import engine
from app.models import UsageEvent, User, UserDailyActivity, UserSecret, UserSettings


def _iocpx_account(model, _attr):
    user = getattr(model, "user", None)
    if user is not None:
        return user.username
    user_id = getattr(model, "user_id", None)
    return f"#{user_id}" if user_id else "-"


def _is_active_label(model, _attr):
    return "启用" if getattr(model, "is_active", True) else "已禁用"


def _valid_until_label(model, _attr):
    value = getattr(model, "valid_until", None)
    return value.isoformat() if value else "永久"


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
    }
    column_searchable_list = [User.username]
    column_formatters = {
        User.is_active: _is_active_label,
        User.valid_until: _valid_until_label,
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
        User.created_at,
    ]
    column_formatters_detail = {
        User.is_active: _is_active_label,
        User.valid_until: _valid_until_label,
    }

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


class UserSecretAdmin(ModelView, model=UserSecret):
    name = "用户密钥"
    name_plural = "用户密钥"
    form_columns = [
        UserSecret.user_id,
        UserSecret.deepseek_keys,
        UserSecret.dashscope_key,
    ]
    form_excluded_columns = [UserSecret.plan_decrypt_key]
    form_args = {
        "user_id": {"label": "用户 ID"},
        "deepseek_keys": {
            "label": "DeepSeek API Keys（逗号分隔，策划专用）",
            "description": "为该用户配置独立的 DeepSeek 密钥，策划时将优先使用此处配置",
        },
        "dashscope_key": {"label": "DashScope Key（可选）"},
    }
    column_list = [
        UserSecret.id,
        UserSecret.user_id,
        UserSecret.deepseek_keys,
        UserSecret.dashscope_key,
        UserSecret.plan_decrypt_key,
        UserSecret.updated_at,
    ]
    column_labels = {
        UserSecret.user_id: "易投账号",
        UserSecret.deepseek_keys: "DeepSeek Keys",
        UserSecret.dashscope_key: "DashScope Key",
        UserSecret.plan_decrypt_key: "策划解密密钥",
        UserSecret.updated_at: "更新时间",
    }
    column_formatters = {
        UserSecret.user_id: _iocpx_account,
    }

    def list_query(self, request: Request):
        return select(UserSecret).options(joinedload(UserSecret.user))

    def details_query(self, request: Request):
        return select(UserSecret).options(joinedload(UserSecret.user))


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
        UsageEvent.duration_ms,
        UsageEvent.client_version,
        UsageEvent.created_at,
    ]
    column_labels = {
        UsageEvent.user_id: "易投账号",
        UsageEvent.event: "事件",
        UsageEvent.success: "成功",
        UsageEvent.meta: "详情",
        UsageEvent.duration_ms: "耗时(ms)",
        UsageEvent.client_version: "客户端版本",
        UsageEvent.created_at: "时间",
    }
    column_formatters = {
        UsageEvent.user_id: _iocpx_account,
    }
    column_sortable_list = [UsageEvent.id, UsageEvent.created_at]
    column_default_sort = [(UsageEvent.id, True)]
    column_searchable_list = [UsageEvent.event, UsageEvent.meta]
    column_details_list = [
        UsageEvent.id,
        UsageEvent.user_id,
        UsageEvent.event,
        UsageEvent.success,
        UsageEvent.meta,
        UsageEvent.duration_ms,
        UsageEvent.client_version,
        UsageEvent.created_at,
    ]
    column_formatters_detail = {
        UsageEvent.user_id: _iocpx_account,
    }

    def list_query(self, request: Request):
        return select(UsageEvent).options(joinedload(UsageEvent.user))

    def details_query(self, request: Request):
        return select(UsageEvent).options(joinedload(UsageEvent.user))


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
    admin.add_view(UserSecretAdmin)
    admin.add_view(UserSettingsAdmin)
    admin.add_view(UsageEventAdmin)
    admin.add_view(UserDailyActivityAdmin)
    return admin
