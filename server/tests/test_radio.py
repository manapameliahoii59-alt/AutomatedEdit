"""音乐电台与 B 站音频提取功能测试。"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

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
from app.models import RadioTrack, RadioGroup, RadioTrackGroup
from app.services.radio_service import (
    _extract_bvid,
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
)


def test_extract_bvid():
    """测试不同格式 B 站链接的 BV 号精准提取。"""
    assert _extract_bvid("https://www.bilibili.com/video/BV1xx411c7mD") == "BV1xx411c7mD"
    assert (
        _extract_bvid("https://www.bilibili.com/video/BV1xx411c7mD?p=2&share_source=copy_web")
        == "BV1xx411c7mD"
    )
    assert _extract_bvid("BV1xx411c7mD") == "BV1xx411c7mD"
    assert _extract_bvid("【全网最火】听了停不下来 BV1a1421773H 推荐") == "BV1a1421773H"
    assert _extract_bvid("https://www.youtube.com/watch?v=12345") == ""
    assert _extract_bvid("") == ""


import asyncio

def test_parse_bilibili_video():
    """测试 B 站元数据接口解析与多 P 提取。"""
    fake_view_data = {
        "code": 0,
        "data": {
            "title": "测试热门歌曲",
            "owner": {"name": "音乐UP主"},
            "duration": 215,
            "pic": "http://i0.hdslb.com/bfs/archive/fake_pic.jpg",
            "cid": 12345678,
            "pages": [
                {"cid": 12345678, "page": 1, "part": "完整版", "duration": 215},
                {"cid": 12345679, "page": 2, "part": "伴奏版", "duration": 215},
            ],
        },
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = fake_view_data

    async def _run():
        with patch("httpx.AsyncClient.get", return_value=mock_resp):
            return await parse_bilibili_video("https://www.bilibili.com/video/BV1xx411c7mD")

    info = asyncio.run(_run())
    assert info["bvid"] == "BV1xx411c7mD"
    assert info["title"] == "测试热门歌曲"
    assert info["artist"] == "音乐UP主"
    assert info["duration"] == 215
    assert info["cid"] == 12345678
    assert len(info["pages"]) == 2


def test_download_bilibili_track(tmp_path, monkeypatch):
    """测试提取 DASH 音频流并保存至磁盘与数据库。"""
    db_path = tmp_path / "radio_test.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    tracks_dir = tmp_path / "tracks"
    covers_dir = tmp_path / "covers"
    tracks_dir.mkdir(parents=True, exist_ok=True)
    covers_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("app.services.radio_service._TRACKS_DIR", tracks_dir)
    monkeypatch.setattr("app.services.radio_service._COVERS_DIR", covers_dir)

    fake_parse_data = {
        "bvid": "BV1xx411c7mD",
        "title": "经典名曲",
        "artist": "周杰伦",
        "duration": 180,
        "pic": "https://example.com/pic.jpg",
        "cid": 888888,
        "pages": [],
        "canonical_url": "https://www.bilibili.com/video/BV1xx411c7mD",
    }

    fake_playurl_data = {
        "code": 0,
        "data": {
            "dash": {
                "audio": [
                    {"id": 30216, "baseUrl": "https://audio-stream.example.com/30216.m4a"},
                    {"id": 30280, "baseUrl": "https://audio-stream.example.com/30280.m4a"},
                ]
            }
        },
    }

    async def fake_get(self, url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if "playurl" in str(url):
            resp.json.return_value = fake_playurl_data
        elif "pic.jpg" in str(url):
            resp.content = b"fake_jpeg_bytes"
        return resp

    class FakeStreamContext:
        def __init__(self, *args, **kwargs):
            self.status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def aiter_bytes(self, chunk_size=65536):
            yield b"\x00\x00\x00\x20ftypiso5" + b"\x01" * 1024

    async def _run():
        with (
            patch("app.services.radio_service.parse_bilibili_video", return_value=fake_parse_data),
            patch("httpx.AsyncClient.get", fake_get),
            patch("httpx.AsyncClient.stream", return_value=FakeStreamContext()),
        ):
            return await download_bilibili_track(
                "BV1xx411c7mD",
                db,
                custom_title="晴天 (现场版)",
                custom_artist="周董",
            )

    track = asyncio.run(_run())
    assert track.id is not None
    assert track.title == "晴天 (现场版)"
    assert track.artist == "周董"
    assert track.source_type == "bilibili"
    assert track.source_id == "BV1xx411c7mD"
    assert track.play_count == 0
    assert track.file_size > 0
    assert "/static/radio/tracks/" in track.audio_url

    db.close()


def test_uploaded_track_and_crud(tmp_path, monkeypatch):
    """测试本地上传文件、查询、修改、播放计数及删除流程。"""
    db_path = tmp_path / "radio_crud.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    tracks_dir = tmp_path / "tracks"
    covers_dir = tmp_path / "covers"
    tracks_dir.mkdir(parents=True, exist_ok=True)
    covers_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("app.services.radio_service._TRACKS_DIR", tracks_dir)
    monkeypatch.setattr("app.services.radio_service._COVERS_DIR", covers_dir)

    # 1. 保存上传
    audio_content = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xFF\xFB" * 50
    track = asyncio.run(save_uploaded_track(
        audio_content,
        "my_song.mp3",
        db,
        custom_title="我的本地歌曲",
        custom_artist="原创作者",
    ))
    assert track.id is not None
    assert track.title == "我的本地歌曲"
    assert track.artist == "原创作者"
    assert track.source_type == "upload"

    # 2. 列表与检索
    all_tracks = list_radio_tracks(db)
    assert len(all_tracks) == 1
    searched = list_radio_tracks(db, q="本地歌曲")
    assert len(searched) == 1
    assert list_radio_tracks(db, q="不存在的歌名") == []

    # 3. 更新
    updated = update_radio_track(track.id, "修改后的标题", "修改后的歌手", db)
    assert updated is not None
    assert updated.title == "修改后的标题"
    assert updated.artist == "修改后的歌手"

    # 4. 播放计数递增
    increment_track_play_count(track.id, db)
    refreshed = get_radio_track(track.id, db)
    assert refreshed.play_count == 1

    # 5. 统计数据
    stats = get_radio_stats(db)
    assert stats["total_tracks"] == 1
    assert stats["upload_tracks"] == 1
    assert stats["bilibili_tracks"] == 0
    assert stats["total_plays"] == 1

    # 6. 删除
    deleted = delete_radio_track(track.id, db)
    assert deleted is True
    assert get_radio_track(track.id, db) is None
    assert len(list_radio_tracks(db)) == 0

    db.close()


@pytest.fixture()
def radio_client(monkeypatch, tmp_path):
    """创建带有管理后台和电台环境的测试客户端。"""
    db_path = tmp_path / "radio_admin.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # 初始插入一首歌曲
    initial_track = RadioTrack(
        title="测试曲目A",
        artist="测试艺术家",
        duration=200,
        cover_url="/static/radio/default_cover.svg",
        audio_url="/static/radio/tracks/demo.m4a",
        source_type="bilibili",
        source_id="BV1demo0001",
        file_size=2048000,
        play_count=3,
    )
    db.add(initial_track)
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
        # 登录
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


def test_radio_page_and_api(radio_client):
    """测试后台电台工作台页面渲染与相关 API 增删改查。"""
    # 1. 访问电台工作台页面
    resp = radio_client.get("/admin/radio")
    assert resp.status_code == 200
    assert "音乐电台" in resp.text
    assert "B 站音源一键提取" in resp.text
    assert "测试曲目A" in resp.text
    assert "测试艺术家" in resp.text

    # 2. 查询曲库 API
    resp_tracks = radio_client.get("/admin/api/radio/tracks")
    assert resp_tracks.status_code == 200
    data = resp_tracks.json()
    assert "tracks" in data
    assert len(data["tracks"]) == 1
    t = data["tracks"][0]
    track_id = t["id"]
    assert t["title"] == "测试曲目A"

    # 3. 递增播放次数
    resp_play = radio_client.post(f"/admin/api/radio/tracks/{track_id}/play")
    assert resp_play.status_code == 200

    # 4. 编辑修改歌曲信息
    resp_update = radio_client.post(
        f"/admin/api/radio/tracks/{track_id}/update",
        json={"title": "新曲名B", "artist": "新歌手B"},
    )
    assert resp_update.status_code == 200
    assert resp_update.json().get("ok") is True

    # 5. 上传本地音频 API
    fake_audio_file = ("test_sample.mp3", b"\xFF\xFB\x90\x44" * 100, "audio/mpeg")
    resp_upload = radio_client.post(
        "/admin/api/radio/upload",
        files={"file": fake_audio_file},
        data={"title": "上传样本", "artist": "样本歌手"},
    )
    assert resp_upload.status_code == 200
    assert resp_upload.json().get("ok") is True
    uploaded_id = resp_upload.json()["track"]["id"]

    # 6. 删除曲目
    resp_del = radio_client.post(f"/admin/api/radio/tracks/{uploaded_id}/delete")
    assert resp_del.status_code == 200
    assert resp_del.json().get("ok") is True


def test_radio_group_crud(tmp_path):
    """测试自定义分组基础 CRUD 及重名约束。"""
    db_path = tmp_path / "radio_group_crud.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # 1. 创建分组
    g1 = create_radio_group("车载精选", "适合开车听的动感歌曲", db)
    assert g1.id is not None
    assert g1.name == "车载精选"
    assert g1.description == "适合开车听的动感歌曲"

    # 2. 重名防重创建约束
    with pytest.raises(ValueError, match="已存在"):
        create_radio_group("车载精选", "重复创建", db)

    # 3. 创建第二个分组
    g2 = create_radio_group("轻音乐", "睡前放松", db)
    assert g2.id is not None

    # 4. 获取分组
    fetched = get_radio_group(g1.id, db)
    assert fetched is not None
    assert fetched.name == "车载精选"

    # 5. 更新分组
    updated = update_radio_group(g1.id, "车载精选V2", "新描述", db)
    assert updated.name == "车载精选V2"
    assert updated.description == "新描述"

    # 6. 重名更新冲突检测
    with pytest.raises(ValueError, match="已被其他分组使用"):
        update_radio_group(g1.id, "轻音乐", "尝试改为g2的名称", db)

    # 7. 列表查询
    groups = list_radio_groups(db)
    assert len(groups) == 2
    names = [g["name"] for g in groups]
    assert "车载精选V2" in names
    assert "轻音乐" in names

    # 8. 删除分组
    assert delete_radio_group(g1.id, db) is True
    assert get_radio_group(g1.id, db) is None
    assert len(list_radio_groups(db)) == 1


def test_track_group_association_and_filtering(tmp_path):
    """测试歌曲分配分组、多对多关联、按分组筛选及级联关系。"""
    db_path = tmp_path / "radio_track_groups.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # 创建 2 个分组
    g_rock = create_radio_group("摇滚精选", "Rock", db)
    g_pop = create_radio_group("流行金曲", "Pop", db)

    # 创建 2 首歌曲
    t1 = RadioTrack(title="晴天", artist="周杰伦", duration=269, play_count=0, audio_url="/static/radio/tracks/t1.mp3")
    t2 = RadioTrack(title="It's My Life", artist="Bon Jovi", duration=224, play_count=0, audio_url="/static/radio/tracks/t2.mp3")
    db.add_all([t1, t2])
    db.commit()
    db.refresh(t1)
    db.refresh(t2)

    # 设置分组：t1 属于 流行金曲；t2 属于 摇滚精选 和 流行金曲
    assigned_t1 = set_track_groups(t1.id, [g_pop.id], db)
    assert len(assigned_t1) == 1
    assert assigned_t1[0]["id"] == g_pop.id

    assigned_t2 = set_track_groups(t2.id, [g_rock.id, g_pop.id], db)
    assert len(assigned_t2) == 2

    # 查询全部歌曲
    all_tracks = list_radio_tracks(db)
    assert len(all_tracks) == 2
    # 验证 groups 属性自动挂载
    for trk in all_tracks:
        if trk.id == t1.id:
            assert trk.group_ids == [g_pop.id]
        elif trk.id == t2.id:
            assert set(trk.group_ids) == {g_rock.id, g_pop.id}

    # 按分组筛选
    rock_tracks = list_radio_tracks(db, group_id=g_rock.id)
    assert len(rock_tracks) == 1
    assert rock_tracks[0].id == t2.id

    pop_tracks = list_radio_tracks(db, group_id=g_pop.id)
    assert len(pop_tracks) == 2

    # 统计歌曲数
    groups_data = list_radio_groups(db)
    counts_map = {g["id"]: g["track_count"] for g in groups_data}
    assert counts_map[g_rock.id] == 1
    assert counts_map[g_pop.id] == 2

    # 删除分组测试（仅清理关联，歌曲本身不删）
    delete_radio_group(g_rock.id, db)
    remain_t2 = get_radio_track(t2.id, db)
    assert remain_t2 is not None
    assert remain_t2.group_ids == [g_pop.id]

    # 删除歌曲测试（级联清理 RadioTrackGroup 关联）
    delete_radio_track(t1.id, db)
    assert get_radio_track(t1.id, db) is None
    pop_after_del = list_radio_tracks(db, group_id=g_pop.id)
    assert len(pop_after_del) == 1
    assert pop_after_del[0].id == t2.id


def test_radio_group_api(radio_client):
    """测试电台分组相关的后台 API 接口与页面。"""
    # 1. 创建分组 API
    resp = radio_client.post(
        "/admin/api/radio/groups/create",
        json={"name": "夜间电台", "description": "深夜放空"},
    )
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["ok"] is True
    group_id = res_data["group"]["id"]
    assert res_data["group"]["name"] == "夜间电台"

    # 2. 查询所有分组 API
    resp_list = radio_client.get("/admin/api/radio/groups")
    assert resp_list.status_code == 200
    groups = resp_list.json()["groups"]
    assert any(g["id"] == group_id for g in groups)

    # 3. 为已有歌曲分配分组 API
    tracks_resp = radio_client.get("/admin/api/radio/tracks")
    track_id = tracks_resp.json()["tracks"][0]["id"]

    resp_set = radio_client.post(
        f"/admin/api/radio/tracks/{track_id}/groups",
        json={"group_ids": [group_id]},
    )
    assert resp_set.status_code == 200
    assert resp_set.json()["ok"] is True
    assert len(resp_set.json()["groups"]) == 1

    # 4. 按分组查询曲目列表 API
    resp_grouped_tracks = radio_client.get(f"/admin/api/radio/tracks?group_id={group_id}")
    assert resp_grouped_tracks.status_code == 200
    assert len(resp_grouped_tracks.json()["tracks"]) == 1
    assert resp_grouped_tracks.json()["tracks"][0]["id"] == track_id

    # 5. 访问带 group_id 的电台管理页
    page_resp = radio_client.get(f"/admin/radio?group_id={group_id}")
    assert page_resp.status_code == 200
    assert "夜间电台" in page_resp.text
    assert "播放该分组" in page_resp.text

    # 6. 编辑分组 API
    resp_edit = radio_client.post(
        f"/admin/api/radio/groups/{group_id}/update",
        json={"name": "夜间电台PRO", "description": "深夜放空升级版"},
    )
    assert resp_edit.status_code == 200
    assert resp_edit.json()["ok"] is True
    assert resp_edit.json()["group"]["name"] == "夜间电台PRO"

    # 7. 删除分组 API
    resp_del = radio_client.post(f"/admin/api/radio/groups/{group_id}/delete")
    assert resp_del.status_code == 200
    assert resp_del.json()["ok"] is True
