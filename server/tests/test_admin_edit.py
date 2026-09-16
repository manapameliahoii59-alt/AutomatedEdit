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

    app = FastAPI()
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
    assert "a@b.com" in response.text
    assert "ssr-table" in response.text
    assert "<td>a@b.com</td>" in response.text
    assets = admin_client.get("/static/admin/vxe-table.umd.min.js")
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
    assert 'min(880px, 96vw)' in resp.text
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
    # 三态布尔：显卡加速开
    assert '<option value="1" selected>' in check.text


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
    assert "backdrop-filter: blur(20px)" in login_resp.text

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


def test_admin_errors_page_batch_resolve_modal(admin_client):
    resp = admin_client.get("/admin/errors")
    assert resp.status_code == 200
    # 不得含有原生 confirm(' 弹框
    assert "confirm(" not in resp.text
    # 含有现代化确认模态框
    assert 'id="batch-resolve-modal"' in resp.text
    assert "确认一键处理" in resp.text





