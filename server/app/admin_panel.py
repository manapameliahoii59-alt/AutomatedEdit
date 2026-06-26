from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request

from app.config import settings
from app.database import engine
from app.models import UsageEvent, User, UserSecret


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
    column_list = [User.id, User.username, User.role, User.is_active, User.created_at]
    column_searchable_list = [User.username]
    form_excluded_columns = [User.password_hash, User.secrets, User.usage_events]


class UserSecretAdmin(ModelView, model=UserSecret):
    column_list = [
        UserSecret.id,
        UserSecret.user_id,
        UserSecret.deepseek_keys,
        UserSecret.dashscope_key,
        UserSecret.updated_at,
    ]


class UsageEventAdmin(ModelView, model=UsageEvent):
    column_list = [
        UsageEvent.id,
        UsageEvent.user_id,
        UsageEvent.event,
        UsageEvent.success,
        UsageEvent.duration_ms,
        UsageEvent.client_version,
        UsageEvent.created_at,
    ]
    column_sortable_list = [UsageEvent.id, UsageEvent.created_at]
    column_default_sort = [(UsageEvent.id, True)]


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
    admin.add_view(UsageEventAdmin)
    return admin
