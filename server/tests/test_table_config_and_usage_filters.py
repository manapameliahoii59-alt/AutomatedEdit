"""测试后台表格配置持久化API与使用记录多维筛选功能。"""

import sys
from datetime import datetime, timedelta
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
from app.models import AdminTableConfig, UsageEvent, User


@pytest.fixture()
def client_env(monkeypatch, tmp_path):
    db_path = tmp_path / "table_config_test.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()

    u1 = User(
        username="user1@test.com",
        password_hash="hash",
        plain_password="pwd",
        role="user",
        is_active=True,
    )
    u2 = User(
        username="user2@test.com",
        password_hash="hash",
        plain_password="pwd",
        role="user",
        is_active=True,
    )
    db.add_all([u1, u2])
    db.commit()

    now = datetime.now()
    yesterday = now - timedelta(days=2)

    e1 = UsageEvent(
        user_id=u1.id,
        event="batch_render_u1",
        success=True,
        meta="u1_meta_info",
        created_at=now,
    )
    e2 = UsageEvent(
        user_id=u2.id,
        event="batch_render_u2",
        success=True,
        meta="u2_meta_info",
        created_at=yesterday,
    )
    db.add_all([e1, e2])
    db.commit()

    u1_id = u1.id
    u2_id = u2.id
    db.close()

    monkeypatch.setattr("app.admin_panel.engine", engine)

    app = FastAPI()
    setup_admin(app)
    c = TestClient(app)

    # 登录管理员
    login_resp = c.post(
        "/admin/login",
        data={"username": settings.admin_username, "password": settings.admin_password},
        follow_redirects=False,
    )
    assert login_resp.status_code == 302

    return {
        "client": c,
        "app": app,
        "engine": engine,
        "Session": Session,
        "u1_id": u1_id,
        "u2_id": u2_id,
    }


def test_table_config_api_unauthorized():
    app = FastAPI()
    setup_admin(app)
    anon_client = TestClient(app)
    resp = anon_client.get("/admin/api/table-config/test_table")
    assert resp.status_code == 401

    resp_post = anon_client.post("/admin/api/table-config/test_table", json={"columns": []})
    assert resp_post.status_code == 401

    resp_del = anon_client.delete("/admin/api/table-config/test_table")
    assert resp_del.status_code == 401


def test_table_config_api_crud_flow(client_env):
    c = client_env["client"]

    # 1. 初始读取为空
    get_res = c.get("/admin/api/table-config/my_grid")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["success"] is True
    assert data["config"] is None

    # 2. 写入配置
    payload = {
        "columns": [
            {"field": "username", "width": 180},
            {"field": "event", "width": 120},
            {"field": "id", "width": 90},
        ],
        "updated_at": "2026-09-20T10:00:00",
    }
    save_res = c.post("/admin/api/table-config/my_grid", json=payload)
    assert save_res.status_code == 200
    assert save_res.json()["message"] == "saved"

    # 3. 再次读取已持久化内容
    get_res2 = c.get("/admin/api/table-config/my_grid")
    assert get_res2.status_code == 200
    data2 = get_res2.json()
    assert data2["success"] is True
    assert data2["config"]["columns"][0]["field"] == "username"
    assert data2["config"]["columns"][0]["width"] == 180

    # 4. 重置恢复默认
    del_res = c.delete("/admin/api/table-config/my_grid")
    assert del_res.status_code == 200
    assert del_res.json()["message"] == "reset"

    # 5. 重置后再次读取应为 None
    get_res3 = c.get("/admin/api/table-config/my_grid")
    assert get_res3.status_code == 200
    assert get_res3.json()["config"] is None


def test_usage_page_user_select_filter(client_env):
    c = client_env["client"]
    u1_id = client_env["u1_id"]
    u2_id = client_env["u2_id"]

    # 默认全查
    resp_all = c.get("/admin/usage")
    assert resp_all.status_code == 200
    assert "batch_render_u1" in resp_all.text
    assert "batch_render_u2" in resp_all.text
    assert 'name="user_id"' in resp_all.text

    # 仅查 user1
    resp_u1 = c.get(f"/admin/usage?user_id={u1_id}")
    assert resp_u1.status_code == 200
    assert "batch_render_u1" in resp_u1.text
    assert "batch_render_u2" not in resp_u1.text
    assert f'value="{u1_id}" selected' in resp_u1.text

    # 仅查 user2
    resp_u2 = c.get(f"/admin/usage?user_id={u2_id}")
    assert resp_u2.status_code == 200
    assert "batch_render_u2" in resp_u2.text
    assert "batch_render_u1" not in resp_u2.text
    assert f'value="{u2_id}" selected' in resp_u2.text


def test_usage_page_date_range_filter(client_env):
    c = client_env["client"]
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    # 筛选今天的数据，昨天的数据将被过滤排除
    resp = c.get(f"/admin/usage?start_date={today_str}&end_date={tomorrow_str}")
    assert resp.status_code == 200
    assert "batch_render_u1" in resp.text
    assert "batch_render_u2" not in resp.text
    assert f'value="{today_str}"' in resp.text


def test_usage_page_draggable_and_reset_elements(client_env):
    c = client_env["client"]
    resp = c.get("/admin/usage")
    assert resp.status_code == 200
    # 验证 tableKey 传入
    assert 'tableKey: "admin_usage_table"' in resp.text
    # 验证重置表头按钮存在
    assert "resetTableLayout('admin_usage_table')" in resp.text
    # 验证 admin.js 与 admin.css 中的拖拽与恢复机制存在
    js_resp = c.get("/static/admin/admin.js")
    assert "window.resetTableLayout" in js_resp.text
    css_resp = c.get("/static/admin/admin.css")
    assert "is-draggable-col" in css_resp.text
    # 验证 Element 风格自主封装日期范围选择器与 Select 组件存在
    assert 'id="usage-date-picker"' in resp.text
    assert "initDateRangePicker" in resp.text
    assert 'id="usage-user-select"' in resp.text
    assert "initSelect" in resp.text
    assert "el-select__clear" in resp.text
    assert "window.initSelect" in js_resp.text
    assert ".el-select__wrapper" in css_resp.text
    assert 'name="start_date"' in resp.text
    assert 'name="end_date"' in resp.text


def test_usage_page_with_empty_user_id_query(client_env):
    """测试选择日期提交表单时，user_id 为空字符串不会触发 FastAPI 422 int_parsing 错误。"""
    c = client_env["client"]
    resp = c.get("/admin/usage?user_id=&start_date=2026-09-10&end_date=2026-09-30&q=")
    assert resp.status_code == 200
    assert "使用记录" in resp.text

    # 测试非法非数字 user_id 也优雅降级
    resp_invalid = c.get("/admin/usage?user_id=invalid&start_date=&end_date=&q=")
    assert resp_invalid.status_code == 200
