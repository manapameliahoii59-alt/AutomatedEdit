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
from app.models import RadioTrack
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
