"""管理后台编辑页集成测试。"""

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.testclient import TestClient

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.admin_panel import setup_admin
from app.config import settings
from app.database import Base
from app.models import User


@pytest.fixture()
def admin_client(monkeypatch, tmp_path):
    db_path = tmp_path / "admin_test.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add(
        User(
            username="a@b.com",
            password_hash="hash",
            plain_password="pwd",
            role="user",
            is_active=True,
        )
    )
    db.commit()
    db.close()

    monkeypatch.setattr("app.admin_panel.engine", engine)

    from app.deps import get_db

    def override_get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app = FastAPI()
    app.dependency_overrides[get_db] = override_get_db
    setup_admin(app)

    with TestClient(app, raise_server_exceptions=True) as client:
        login = client.post(
            "/admin/login",
            data={
                "username": settings.admin_username,
                "password": settings.admin_password,
            },
            follow_redirects=False,
        )
        assert login.status_code == 302
        yield client


def test_user_edit_page_renders(admin_client):
    response = admin_client.get("/admin/user/edit/1")
    assert response.status_code == 200, response.text[:2000]
    assert "允许使用桌面端" in response.text
    assert "允许使用视频下载" in response.text
    assert "每日下载上限" in response.text
    assert "策划 API Keys" in response.text
    assert "策划模型" in response.text
    assert "OpenCode Go" in response.text
    assert "OpenCode Go / MiMo-V2.5" in response.text
    assert 'value="opencode_go|mimo-v2.5"' in response.text
    assert "小米 MiMo" in response.text
    assert "mimo-v2.5" in response.text
    assert "智谱 GLM / glm-4.7-flash" in response.text
    assert 'value="zhipu|glm-4.7-flash"' in response.text
    assert "深度思考模式（Thinking）" in response.text
    assert 'id="plan_thinking_enabled"' in response.text
    assert "form-check form-switch" in response.text
    assert 'role="switch"' in response.text
    assert 'class="form-check-input"' in response.text
    assert 'class="form-control"' not in response.text.split("is_active")[1][:200]


def test_user_edit_saves_deepseek_keys(admin_client):
    save_resp = admin_client.post(
        "/admin/user/edit/1",
        data={
            "username": "a@b.com",
            "role": "user",
            "plan_llm_preset": "opencode_go|deepseek-v4-flash",
            "deepseek_keys": "sk-test-1,sk-test-2",
            "dashscope_key": "ds-key",
            "save": "Save",
        },
        follow_redirects=False,
    )
    assert save_resp.status_code == 302

    check_resp = admin_client.get("/admin/user/edit/1")
    assert check_resp.status_code == 200
    assert "sk-test-1,sk-test-2" in check_resp.text
    assert "ds-key" in check_resp.text
    assert 'value="opencode_go|deepseek-v4-flash"' in check_resp.text
    assert "selected" in check_resp.text


def test_user_edit_saves_zhipu_glm_47(admin_client):
    save_resp = admin_client.post(
        "/admin/user/edit/1",
        data={
            "username": "a@b.com",
            "role": "user",
            "plan_llm_preset": "zhipu|glm-4.7-flash",
            "deepseek_keys": "zp-key-123",
            "save": "Save",
        },
        follow_redirects=False,
    )
    assert save_resp.status_code == 302

    check_resp = admin_client.get("/admin/user/edit/1")
    assert check_resp.status_code == 200
    assert "zp-key-123" in check_resp.text
    assert 'value="zhipu|glm-4.7-flash" selected' in check_resp.text


def test_user_edit_toggle_is_active(admin_client):
    save_resp = admin_client.post(
        "/admin/user/edit/1",
        data={"username": "a@b.com", "role": "user", "save": "Save"},
        follow_redirects=False,
    )
    assert save_resp.status_code == 302

    check_resp = admin_client.get("/admin/user/edit/1")
    assert check_resp.status_code == 200
    assert 'id="is_active"' in check_resp.text
    assert 'id="is_active" type="checkbox" role="switch" name="is_active" value="y" checked' not in check_resp.text

    save_resp = admin_client.post(
        "/admin/user/edit/1",
        data={
            "username": "a@b.com",
            "role": "user",
            "is_active": "y",
            "save": "Save",
        },
        follow_redirects=False,
    )
    assert save_resp.status_code == 302

    check_resp = admin_client.get("/admin/user/edit/1")
    assert check_resp.status_code == 200
    assert 'id="is_active" type="checkbox" role="switch" name="is_active" value="y" checked' in check_resp.text


def test_user_edit_download_controls(admin_client):
    save_resp = admin_client.post(
        "/admin/user/edit/1",
        data={
            "username": "a@b.com",
            "role": "user",
            "is_active": "y",
            "daily_download_limit": "5",
            "save": "Save",
        },
        follow_redirects=False,
    )
    assert save_resp.status_code == 302

    check_resp = admin_client.get("/admin/user/edit/1")
    assert check_resp.status_code == 200
    assert 'id="download_enabled"' in check_resp.text
    assert (
        'id="download_enabled" type="checkbox" role="switch" '
        'name="download_enabled" value="y" checked'
    ) not in check_resp.text
    assert 'id="daily_download_limit"' in check_resp.text
    assert 'name="daily_download_limit" value="5"' in check_resp.text

    save_resp = admin_client.post(
        "/admin/user/edit/1",
        data={
            "username": "a@b.com",
            "role": "user",
            "is_active": "y",
            "download_enabled": "y",
            "daily_download_limit": "12",
            "save": "Save",
        },
        follow_redirects=False,
    )
    assert save_resp.status_code == 302

    check_resp = admin_client.get("/admin/user/edit/1")
    assert check_resp.status_code == 200
    assert (
        'id="download_enabled" type="checkbox" role="switch" '
        'name="download_enabled" value="y" checked'
    ) in check_resp.text
    assert 'name="daily_download_limit" value="12"' in check_resp.text


def test_user_list_shows_deepseek_column(admin_client):
    response = admin_client.get("/admin/user/list")
    assert response.status_code == 200
    assert "策划 API Keys" in response.text
    assert "策划模型" in response.text
    assert "策划模式" in response.text
    assert "混合模式" in response.text
    assert "a@b.com" in response.text
    assert "ssr-table" in response.text
    assert "<td>a@b.com</td>" in response.text
    assets = admin_client.get("/static/admin/admin.js")
    assert assets.status_code == 200


def test_user_edit_toggle_plan_thinking_enabled(admin_client):
    # 默认未开启
    save_resp = admin_client.post(
        "/admin/user/edit/1",
        data={
            "username": "a@b.com",
            "role": "user",
            "plan_llm_preset": "zhipu|glm-4.7-flash",
            "save": "Save",
        },
        follow_redirects=False,
    )
    assert save_resp.status_code == 302

    check_resp = admin_client.get("/admin/user/edit/1")
    assert check_resp.status_code == 200
    assert 'id="plan_thinking_enabled"' in check_resp.text
    assert (
        'id="plan_thinking_enabled" type="checkbox" role="switch" '
        'name="plan_thinking_enabled" value="y" checked'
    ) not in check_resp.text

    # 勾选开启
    save_resp2 = admin_client.post(
        "/admin/user/edit/1",
        data={
            "username": "a@b.com",
            "role": "user",
            "plan_llm_preset": "zhipu|glm-4.7-flash",
            "plan_thinking_enabled": "y",
            "save": "Save",
        },
        follow_redirects=False,
    )
    assert save_resp2.status_code == 302

    check_resp2 = admin_client.get("/admin/user/edit/1")
    assert check_resp2.status_code == 200
    assert (
        'id="plan_thinking_enabled" type="checkbox" role="switch" '
        'name="plan_thinking_enabled" value="y" checked'
    ) in check_resp2.text


def test_user_edit_enabled_tabs(admin_client):
    # 默认状态
    resp = admin_client.get("/admin/user/edit/1")
    assert resp.status_code == 200
    assert "应用导航页面展示 (Tab 权限)" in resp.text
    assert 'id="tab_clip_edit"' in resp.text
    assert 'id="tab_batch_edit"' in resp.text
    assert 'name="tab_clip_edit" value="y" checked' in resp.text
    assert 'name="tab_batch_edit" value="y" checked' not in resp.text

    # 仅开启 batch_edit
    save_resp = admin_client.post(
        "/admin/user/edit/1",
        data={
            "username": "a@b.com",
            "role": "user",
            "tabs_submitted": "1",
            "tab_batch_edit": "y",
            "save": "Save",
        },
        follow_redirects=False,
    )
    assert save_resp.status_code == 302

    check_resp = admin_client.get("/admin/user/edit/1")
    assert check_resp.status_code == 200
    assert 'name="tab_batch_edit" value="y" checked' in check_resp.text
    assert 'name="tab_clip_edit" value="y" checked' not in check_resp.text
    assert (
        'id="download_enabled" type="checkbox" role="switch" '
        'name="download_enabled" value="y" checked'
    ) not in check_resp.text

    # 全开启
    save_resp2 = admin_client.post(
        "/admin/user/edit/1",
        data={
            "username": "a@b.com",
            "role": "user",
            "tabs_submitted": "1",
            "download_enabled": "y",
            "tab_clip_edit": "y",
            "tab_batch_edit": "y",
            "save": "Save",
        },
        follow_redirects=False,
    )
    assert save_resp2.status_code == 302

    check_resp2 = admin_client.get("/admin/user/edit/1")
    assert check_resp2.status_code == 200
    assert 'name="tab_batch_edit" value="y" checked' in check_resp2.text
    assert 'name="tab_clip_edit" value="y" checked' in check_resp2.text
    assert (
        'id="download_enabled" type="checkbox" role="switch" '
        'name="download_enabled" value="y" checked'
    ) in check_resp2.text


def test_unconfigured_keys_modal_and_api(admin_client):
    # 初始状态：用户 a@b.com 尚未配置密钥
    resp = admin_client.get("/admin/users")
    assert resp.status_code == 200
    assert 'id="missing-keys-dialog"' in resp.text
    assert 'id="missing-keys-dismiss-today"' in resp.text
    assert 'admin_missing_keys_dismissed_today' in resp.text
    css_resp = admin_client.get("/static/admin/admin.css")
    assert 'min(880px, 96vw)' in css_resp.text
    assert 'isEditPage' in resp.text
    assert "a@b.com" in resp.text
    assert "menu-missing-keys-badge" in resp.text

    # 测试 API 接口返回
    api_resp = admin_client.get("/admin/api/unconfigured-users")
    assert api_resp.status_code == 200
    users = api_resp.json().get("users", [])
    assert len(users) == 1
    assert users[0]["username"] == "a@b.com"

    # 配置密钥并保存
    save_resp = admin_client.post(
        "/admin/user/edit/1",
        data={
            "username": "a@b.com",
            "role": "user",
            "plan_llm_preset": "deepseek|deepseek-v4-flash",
            "deepseek_keys": "sk-real-key-123456",
            "save": "Save",
        },
        follow_redirects=False,
    )
    assert save_resp.status_code == 302

    # 再次访问用户列表：未配置弹窗与角标不再呈现
    resp2 = admin_client.get("/admin/users")
    assert resp2.status_code == 200
    assert 'id="missing-keys-dialog"' not in resp2.text
    assert "menu-missing-keys-badge" not in resp2.text

    # API 返回空
    api_resp2 = admin_client.get("/admin/api/unconfigured-users")
    assert api_resp2.status_code == 200
    assert api_resp2.json().get("users") == []


def test_user_edit_renders_encode_settings(admin_client):
    resp = admin_client.get("/admin/user/edit/1")
    assert resp.status_code == 200, resp.text[:2000]
    assert "编码 / 渲染设置" in resp.text
    assert 'id="encode_nvenc_preset"' in resp.text
    assert 'id="encode_amf_preset"' in resp.text
    assert 'id="encode_qsv_preset"' in resp.text
    assert 'id="encode_x264_preset"' in resp.text
    assert 'id="encode_enable_gpu"' in resp.text
    assert 'id="clip_auto_retry_failed"' in resp.text
    assert 'id="clip_max_transcribe_episodes"' in resp.text
    assert 'id="clip_render_engine"' in resp.text
    assert 'id="clip_export_dir_display"' in resp.text


def test_user_edit_saves_encode_settings(admin_client):
    save_resp = admin_client.post(
        "/admin/user/edit/1",
        data={
            "username": "a@b.com",
            "role": "user",
            "encode_enable_gpu": "1",
            "encode_nvenc_preset": "p7",
            "encode_x264_preset": "BOGUS",
            "clip_trim_ep1_continued": "0",
            "clip_overlay_bake_png": "1",
            "clip_auto_retry_failed": "1",
            "clip_max_transcribe_episodes": "25",
            "clip_render_engine": "legacy",
            "save": "Save",
        },
        follow_redirects=False,
    )
    assert save_resp.status_code == 302

    check = admin_client.get("/admin/user/edit/1")
    assert check.status_code == 200, check.text[:2000]
    assert 'id="encode_nvenc_preset"' in check.text
    assert '<option value="p7" selected>' in check.text
    assert '<option value="legacy" selected>' in check.text
    # 非法档位被丢弃，退回“不设置”
    assert '<option value="BOGUS" selected>' not in check.text
    # 三态布尔：显卡加速开 / 自动重试开
    assert '<option value="1" selected>' in check.text
    auto_retry_html = check.text.split('id="clip_auto_retry_failed"')[1].split('</select>')[0]
    assert '<option value="1" selected>' in auto_retry_html
    assert 'value="25"' in check.text


def test_unconfigured_keys_skips_demo_user(admin_client):
    import app.admin_panel as ap
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=ap.engine)
    db = Session()
    db.add(
        User(
            username="demo",
            password_hash="pwd_hash",
            plain_password="demo",
            role="user",
            is_active=True,
        )
    )
    db.commit()
    db.close()

    # 先为 a@b.com 配置好密钥，此时数据库中仅剩 demo 用户未配置
    admin_client.post(
        "/admin/user/edit/1",
        data={
            "username": "a@b.com",
            "role": "user",
            "plan_llm_preset": "deepseek|deepseek-v4-flash",
            "deepseek_keys": "sk-real-key-123456",
            "save": "Save",
        },
        follow_redirects=False,
    )

    # 验证 demo 用户被豁免，不触发未配置弹窗与角标，API 返回空
    resp = admin_client.get("/admin/users")
    assert resp.status_code == 200
    assert 'id="missing-keys-dialog"' not in resp.text
    assert "menu-missing-keys-badge" not in resp.text

    api_resp = admin_client.get("/admin/api/unconfigured-users")
    assert api_resp.status_code == 200
    assert api_resp.json().get("users") == []


def test_admin_usage_page_renders_model_and_timing_columns(admin_client):
    resp = admin_client.get("/admin/usage")
    assert resp.status_code == 200
    assert "模型" in resp.text
    assert "识别耗时" in resp.text
    assert "策划耗时" in resp.text
    assert "渲染耗时" in resp.text
    assert "总耗时" in resp.text
    # 验证左上角冗余标题与重复数据条数已移除
    assert "<h1>使用记录</h1>" not in resp.text
    assert "<p>共 " not in resp.text
    assert "head--search-only" in resp.text
    # 验证查询框靠左排列样式规则生效
    css_resp = admin_client.get("/static/admin/admin.css")
    assert ".head.head--search-only" in css_resp.text
    assert "justify-content: flex-start" in css_resp.text


def test_admin_usage_engine_label_mapping_and_search(admin_client):
    from app.admin_panel import engine
    from app.models import UsageEvent
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)
    db = Session()
    # 插入一条包含 current 引擎的事件
    db.add(
        UsageEvent(
            user_id=1,
            event="batch_all_render",
            success=True,
            duration_ms=50000,
            meta="测试映射剧目",
            render_engine="current",
        )
    )
    db.commit()
    db.close()

    # 1. 验证常规列表页面中 current 被映射为 v2
    resp = admin_client.get("/admin/usage")
    assert resp.status_code == 200
    assert "测试映射剧目" in resp.text
    assert '"render_engine": "v2"' in resp.text or '<td>v2</td>' in resp.text
    assert '"render_engine": "current"' not in resp.text

    # 2. 验证搜索 q=v2 能够命中该条记录（别名搜索）
    search_resp = admin_client.get("/admin/usage?q=v2")
    assert search_resp.status_code == 200
    assert "测试映射剧目" in search_resp.text


def test_admin_login_page_renders_remember_me_and_theme(admin_client):
    # 退出当前登录以测试登录页渲染
    admin_client.get("/admin/logout", follow_redirects=False)
    resp = admin_client.get("/admin/login")
    assert resp.status_code == 200
    assert "记住密码" in resp.text
    assert 'id="rememberMe"' in resp.text
    assert 'id="usernameInput"' in resp.text
    assert 'id="passwordInput"' in resp.text
    assert "admin_remember_user" in resp.text
    assert "admin_remember_pwd" in resp.text
    assert "admin_remember_enabled" in resp.text


def test_admin_profile_page_and_theme_settings(admin_client, tmp_path, monkeypatch):
    import app.admin_panel as ap

    # 使用临时主题文件避免污染生产配置
    theme_file = tmp_path / "test_theme.json"
    upload_file = tmp_path / "test_custom_bg.jpg"
    monkeypatch.setattr(ap, "_THEME_FILE", theme_file)
    monkeypatch.setattr(ap, "_UPLOADED_BG_FILE", upload_file)

    # 1. 访问个人中心页面
    resp = admin_client.get("/admin/profile")
    assert resp.status_code == 200
    assert "个人中心" in resp.text
    assert "管理员基本资料" in resp.text
    assert "登录界面封面与外观设置" in resp.text
    assert "内置精选渐变" in resp.text
    assert "网络图片链接" in resp.text
    assert "本地图片上传" in resp.text
    assert "实时渲染效果预览" in resp.text

    # 2. 保存预设主题 (蓝莓霜雾)
    save_resp = admin_client.post(
        "/admin/profile/theme",
        data={
            "mode": "preset",
            "preset_key": "gradient_frost",
            "glass": "1",
        },
        follow_redirects=False,
    )
    assert save_resp.status_code == 302
    assert "msg=saved" in save_resp.headers.get("location", "")

    # 3. 验证登录页正确应用所选渐变背景及毛玻璃
    admin_client.get("/admin/logout", follow_redirects=False)
    login_resp = admin_client.get("/admin/login")
    assert login_resp.status_code == 200
    assert "linear-gradient(135deg, #667eea 0%, #764ba2 100%)" in login_resp.text
    assert "backdrop-filter: blur(" in login_resp.text

    # 4. 重新登录并设置网络图片主题
    admin_client.post(
        "/admin/login",
        data={
            "username": settings.admin_username,
            "password": settings.admin_password,
        },
        follow_redirects=False,
    )
    save_url_resp = admin_client.post(
        "/admin/profile/theme",
        data={
            "mode": "url",
            "custom_url": "https://images.example.com/login_bg.jpg",
            "glass": "1",
        },
        follow_redirects=False,
    )
    assert save_url_resp.status_code == 302

    admin_client.get("/admin/logout", follow_redirects=False)
    login_url_resp = admin_client.get("/admin/login")
    assert login_url_resp.status_code == 200
    assert "https://images.example.com/login_bg.jpg" in login_url_resp.text

    # 5. 重新登录，验证已登录状态下访问 /admin/login?preview=1 不跳转，正常进入预览模式
    admin_client.post(
        "/admin/login",
        data={
            "username": settings.admin_username,
            "password": settings.admin_password,
        },
        follow_redirects=False,
    )
    # 未带 preview 参数应正常重定向至 /admin/users
    direct_login = admin_client.get("/admin/login", follow_redirects=False)
    assert direct_login.status_code == 302
    assert "/admin/users" in direct_login.headers.get("location", "")

    # 带 preview=1 参数应直接渲染登录界面并包含预览标头
    preview_resp = admin_client.get("/admin/login?preview=1")
    assert preview_resp.status_code == 200
    assert "登录界面封面预览模式" in preview_resp.text

    # 6. 验证个人中心上传非法文件时返回弱提示错误
    bad_upload_resp = admin_client.post(
        "/admin/profile/theme",
        files={"bg_file": ("test.exe", b"binary content", "application/octet-stream")},
        follow_redirects=False,
    )
    assert bad_upload_resp.status_code == 302
    assert "error=" in bad_upload_resp.headers.get("location", "")

    profile_err_resp = admin_client.get(bad_upload_resp.headers.get("location"))
    assert profile_err_resp.status_code == 200
    assert 'id="toast-error"' in profile_err_resp.text


def test_admin_errors_page_batch_resolve_modal(admin_client):
    resp = admin_client.get("/admin/errors")
    assert resp.status_code == 200
    # 不得含有原生 confirm(' 弹框
    assert "confirm(" not in resp.text
    # 含有现代化确认模态框
    assert 'id="batch-resolve-modal"' in resp.text
    assert "确认一键处理" in resp.text


def test_admin_user_edit_session_revocation(admin_client):
    import app.admin_panel as ap
    from app.auth import create_access_token
    from app.routers.auth import router as auth_router
    from sqlalchemy.orm import sessionmaker

    admin_client.app.include_router(auth_router)

    Session = sessionmaker(bind=ap.engine)
    db = Session()
    user = db.get(User, 1)
    initial_ver = user.token_version
    assert initial_ver >= 1

    # 1. 验证编辑页渲染登录状态控制项与强制下线按钮、模态框
    resp = admin_client.get("/admin/user/edit/1")
    assert resp.status_code == 200
    assert "登录状态控制" in resp.text
    assert "⚡ 强制下线" in resp.text
    assert 'id="session_action"' in resp.text
    assert 'id="revoke-session-modal"' in resp.text
    assert "确认强制下线" in resp.text

    # 2. 为该用户签发当前有效版本的 Token 与旧版本 Token
    valid_token = create_access_token(user.id, user.username, user.role, token_version=user.token_version)
    old_token = create_access_token(user.id, user.username, user.role, token_version=user.token_version - 1)

    # 3. 验证使用当前有效 Token 请求 /api/auth/me 成功
    me_resp = admin_client.get("/api/auth/me", headers={"Authorization": f"Bearer {valid_token}"})
    assert me_resp.status_code == 200
    assert me_resp.json().get("username") == "a@b.com"

    # 4. 验证使用旧版本 Token 请求 /api/auth/me 得到 401
    bad_resp = admin_client.get("/api/auth/me", headers={"Authorization": f"Bearer {old_token}"})
    assert bad_resp.status_code == 401
    assert "过期" in bad_resp.text

    # 5. 管理员调用 revoke-session 路由强制使会话失效
    revoke_resp = admin_client.post("/admin/users/1/revoke-session", follow_redirects=False)
    assert revoke_resp.status_code == 302
    assert "msg=session_revoked" in revoke_resp.headers.get("location", "")

    # 6. 验证数据库中 token_version 递增
    db.expire_all()
    user = db.get(User, 1)
    assert user.token_version == initial_ver + 1

    # 7. 此前原本有效的 valid_token 立即失效，返回 401
    revoked_me_resp = admin_client.get("/api/auth/me", headers={"Authorization": f"Bearer {valid_token}"})
    assert revoked_me_resp.status_code == 401
    assert "过期" in revoked_me_resp.text

    # 8. 重新用最新版本签发 Token，恢复可用
    new_token = create_access_token(user.id, user.username, user.role, token_version=user.token_version)
    new_me_resp = admin_client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert new_me_resp.status_code == 200

    # 9. 测试通过常规编辑页表单选择 session_action="revoke" 保存
    save_resp = admin_client.post(
        "/admin/user/edit/1",
        data={
            "username": "a@b.com",
            "role": "user",
            "is_active": "y",
            "session_action": "revoke",
            "save": "Save",
        },
        follow_redirects=False,
    )
    assert save_resp.status_code == 302

    db.expire_all()
    user = db.get(User, 1)
    assert user.token_version == initial_ver + 2
    db.close()


def test_user_edit_plan_group_mode_persistence(admin_client):
    from app.models import UserSecret

    # 1. 初始渲染检查包含新容器与脚本
    resp = admin_client.get("/admin/user/edit/1")
    assert resp.status_code == 200
    assert 'id="group-mode-notice"' in resp.text
    assert 'id="single-model-section"' in resp.text
    assert "updatePlanModelModeUI" in resp.text
    assert "多模型策略组调度已生效" in resp.text
    assert "独立单模型专属配置" in resp.text

    # 2. 显式设为 0（独立单模型模式）
    save_resp = admin_client.post(
        "/admin/user/edit/1",
        data={
            "username": "a@b.com",
            "role": "user",
            "plan_group_id": "0",
            "plan_llm_preset": "deepseek|deepseek-chat",
            "deepseek_keys": "sk-single-test",
            "save": "Save",
        },
        follow_redirects=False,
    )
    assert save_resp.status_code == 302

    check_resp = admin_client.get("/admin/user/edit/1")
    assert check_resp.status_code == 200
    group_select_html = check_resp.text.split('id="plan_group_id"')[1].split('</select>')[0]
    assert '<option value="0" selected>' in group_select_html
    assert '<option value="" selected>' not in group_select_html

    # 3. 恢复为跟随系统默认组（plan_group_id=""）
    save_resp2 = admin_client.post(
        "/admin/user/edit/1",
        data={
            "username": "a@b.com",
            "role": "user",
            "plan_group_id": "",
            "save": "Save",
        },
        follow_redirects=False,
    )
    assert save_resp2.status_code == 302

    check_resp2 = admin_client.get("/admin/user/edit/1")
    assert check_resp2.status_code == 200
    group_select_html2 = check_resp2.text.split('id="plan_group_id"')[1].split('</select>')[0]
    assert '<option value="" selected>' in group_select_html2
    assert '<option value="0" selected>' not in group_select_html2


def test_missing_plan_keys_with_strategy_groups(monkeypatch, tmp_path):
    from app.admin_panel import _get_users_missing_plan_keys
    from app.models import LlmGroup, UserSecret

    db_path = tmp_path / "missing_keys_test.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # 用户1: 独立单模型模式 (plan_group_id=0), 未填 Key -> 应该预警
    u1 = User(username="u1@test.com", password_hash="h", plain_password="p", is_active=True)
    db.add(u1)
    db.flush()
    db.add(UserSecret(user_id=u1.id, plan_group_id=0, deepseek_keys=""))

    # 用户2: 策略组模式 (plan_group_id=1), 未填 Key -> 有策略组，不应预警
    u2 = User(username="u2@test.com", password_hash="h", plain_password="p", is_active=True)
    db.add(u2)
    db.flush()
    db.add(UserSecret(user_id=u2.id, plan_group_id=1, deepseek_keys=""))

    # 用户3: 默认组模式 (plan_group_id=None), 未填 Key
    u3 = User(username="u3@test.com", password_hash="h", plain_password="p", is_active=True)
    db.add(u3)
    db.flush()
    db.add(UserSecret(user_id=u3.id, plan_group_id=None, deepseek_keys=""))

    db.commit()

    # 当前无默认组: u1 和 u3 应预警，u2 不预警
    missing = _get_users_missing_plan_keys(db)
    missing_ids = [m["id"] for m in missing]
    assert u1.id in missing_ids
    assert u3.id in missing_ids
    assert u2.id not in missing_ids

    # 添加系统默认组后，u3 走默认渠道组调度，不再预警
    grp = LlmGroup(name="Default Group", dispatch_mode="parallel", is_default=True, channel_ids="1")
    db.add(grp)
    db.commit()

    missing_after = _get_users_missing_plan_keys(db)
    missing_after_ids = [m["id"] for m in missing_after]
    assert u1.id in missing_after_ids
    assert u3.id not in missing_after_ids
    assert u2.id not in missing_after_ids

    db.close()


def test_user_edit_saves_plan_mode(admin_client):
    # 1. 检查页面上渲染了策划模式下拉选项
    resp = admin_client.get("/admin/user/edit/1")
    assert resp.status_code == 200
    assert '策划模式（双向同步）' in resp.text
    assert 'id="plan_mode"' in resp.text
    assert '混合模式（主流推荐 / A+B组装箱）' in resp.text

    # 2. 保存策划模式为 short
    save_resp = admin_client.post(
        "/admin/user/edit/1",
        data={
            "username": "a@b.com",
            "role": "user",
            "plan_mode": "short",
            "save": "Save",
        },
        follow_redirects=False,
    )
    assert save_resp.status_code == 302

    # 3. 验证编辑页回显为 short 并且用户列表显示短片模式
    check_resp = admin_client.get("/admin/user/edit/1")
    assert check_resp.status_code == 200
    assert '<option value="short" selected>短片模式（历史旧版）</option>' in check_resp.text

    list_resp = admin_client.get("/admin/users")
    assert list_resp.status_code == 200
    assert "短片模式" in list_resp.text

    # 4. 改回 mixed 混合模式
    save_resp2 = admin_client.post(
        "/admin/user/edit/1",
        data={
            "username": "a@b.com",
            "role": "user",
            "plan_mode": "mixed",
            "save": "Save",
        },
        follow_redirects=False,
    )
    assert save_resp2.status_code == 302

    list_resp2 = admin_client.get("/admin/users")
    assert list_resp2.status_code == 200
    assert "混合模式" in list_resp2.text








