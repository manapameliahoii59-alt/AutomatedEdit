import os
import re
import uuid
import logging
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.orm import Session
from sqlalchemy import select, desc, func, delete

from app.models import RadioTrack, RadioGroup, RadioTrackGroup

logger = logging.getLogger(__name__)

# 静态资源保存路径
_APP_DIR = Path(__file__).resolve().parent.parent
_STATIC_RADIO_DIR = _APP_DIR / "static" / "radio"
_TRACKS_DIR = _STATIC_RADIO_DIR / "tracks"
_COVERS_DIR = _STATIC_RADIO_DIR / "covers"

_TRACKS_DIR.mkdir(parents=True, exist_ok=True)
_COVERS_DIR.mkdir(parents=True, exist_ok=True)

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_BILI_HEADERS = {
    "User-Agent": _DEFAULT_UA,
    "Referer": "https://www.bilibili.com",
}


def _extract_bvid(text: str) -> str:
    """从普通链接、短链或原始字符串中提取 BV 号。"""
    raw = (text or "").strip()
    # 匹配标准 BV 格式（以 BV 开头，后跟 10 位字母数字）
    match = re.search(r"BV[a-zA-Z0-9]{10}", raw)
    if match:
        return match.group(0)
    return ""


async def resolve_bilibili_url(raw_url: str) -> str:
    """如果是 b23.tv 短链，先进行 302 自动重定向追踪，得到最终链接。"""
    raw = (raw_url or "").strip()
    if "b23.tv" in raw:
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=_BILI_HEADERS) as client:
                resp = await client.get(raw)
                return str(resp.url)
        except Exception as e:
            logger.warning("解析 b23 短链失败: %s", e)
    return raw


async def parse_bilibili_video(url_or_bvid: str) -> dict[str, Any]:
    """解析 B 站视频信息，返回用于展示与确认的元数据。"""
    final_url = await resolve_bilibili_url(url_or_bvid)
    bvid = _extract_bvid(final_url)
    if not bvid:
        raise ValueError("未能识别有效的 Bilibili BV 号或视频链接，请检查输入！")

    api_view_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    async with httpx.AsyncClient(timeout=12.0, headers=_BILI_HEADERS) as client:
        resp = await client.get(api_view_url)
        if resp.status_code != 200:
            raise RuntimeError(f"B 站接口响应异常 (HTTP {resp.status_code})")
        data = resp.json()

    if data.get("code") != 0:
        msg = data.get("message") or "未知错误"
        raise RuntimeError(f"B 站视频解析失败: {msg} (code: {data.get('code')})")

    video_data = data.get("data") or {}
    title = (video_data.get("title") or "未知歌曲").strip()
    artist = (video_data.get("owner", {}).get("name") or "未知UP主").strip()
    duration = int(video_data.get("duration") or 0)
    pic = (video_data.get("pic") or "").strip()
    cid = int(video_data.get("cid") or 0)

    pages = []
    for p in video_data.get("pages") or []:
        pages.append({
            "cid": p.get("cid"),
            "page": p.get("page"),
            "part": p.get("part") or f"P{p.get('page')}",
            "duration": p.get("duration"),
        })

    return {
        "bvid": bvid,
        "title": title,
        "artist": artist,
        "duration": duration,
        "pic": pic,
        "cid": cid,
        "pages": pages,
        "canonical_url": f"https://www.bilibili.com/video/{bvid}",
    }


async def download_bilibili_track(
    url_or_bvid: str,
    db: Session,
    *,
    custom_title: str | None = None,
    custom_artist: str | None = None,
    cid_override: int | None = None,
    group_id: int | None = None,
) -> RadioTrack:
    """从 B 站下载纯音频流与封面并存库。"""
    info = await parse_bilibili_video(url_or_bvid)
    bvid = info["bvid"]
    cid = cid_override or info["cid"]
    title = (custom_title or info["title"]).strip()
    artist = (custom_artist or info["artist"]).strip()
    duration = info["duration"]

    # 1. 请求 DASH 格式音频流
    playurl_api = f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&fnval=16"
    async with httpx.AsyncClient(timeout=12.0, headers=_BILI_HEADERS) as client:
        resp = await client.get(playurl_api)
        if resp.status_code != 200:
            raise RuntimeError(f"获取 B 站播放流失败 (HTTP {resp.status_code})")
        play_data = resp.json()

    if play_data.get("code") != 0:
        raise RuntimeError(f"B 站音频流获取失败: {play_data.get('message')}")

    audio_list = play_data.get("data", {}).get("dash", {}).get("audio", [])
    if not audio_list:
        # 兼容备选 durl 格式
        durls = play_data.get("data", {}).get("durl", [])
        if not durls:
            raise RuntimeError("该视频未提供有效的音频流，可能为充电专属或地区限制视频。")
        audio_stream_url = durls[0].get("url")
    else:
        # 挑选最高码率音频流 (id 越大音质越优，如 30280 / 30232 / 30216)
        best_audio = max(audio_list, key=lambda a: a.get("id", 0))
        audio_stream_url = best_audio.get("baseUrl") or (best_audio.get("backupUrl") or [None])[0]

    if not audio_stream_url:
        raise RuntimeError("未能解析出可用的音频下载直链！")

    # 2. 生成本地唯一文件名
    track_uuid = uuid.uuid4().hex[:12]
    audio_filename = f"{bvid}_{track_uuid}.m4a"
    cover_filename = f"{bvid}_{track_uuid}.jpg"

    audio_file_path = _TRACKS_DIR / audio_filename
    cover_file_path = _COVERS_DIR / cover_filename

    # 3. 下载封面图（本地化缓存，解决 B 站防盗链问题）
    cover_url_web = ""
    pic_url = info.get("pic")
    if pic_url:
        try:
            async with httpx.AsyncClient(timeout=10.0, headers=_BILI_HEADERS) as client:
                pic_resp = await client.get(pic_url)
                if pic_resp.status_code == 200 and pic_resp.content:
                    cover_file_path.write_bytes(pic_resp.content)
                    cover_url_web = f"/static/radio/covers/{cover_filename}"
        except Exception as e:
            logger.warning("下载封面失败，使用默认封面: %s", e)

    # 4. 流式下载音频文件
    total_bytes = 0
    try:
        async with httpx.AsyncClient(timeout=60.0, headers=_BILI_HEADERS) as client:
            async with client.stream("GET", audio_stream_url) as stream:
                if stream.status_code >= 400:
                    raise RuntimeError(f"下载音频流被拒绝 (HTTP {stream.status_code})")
                with open(audio_file_path, "wb") as f:
                    async for chunk in stream.aiter_bytes(chunk_size=65536):
                        f.write(chunk)
                        total_bytes += len(chunk)
    except Exception as e:
        if audio_file_path.is_file():
            try:
                audio_file_path.unlink()
            except OSError:
                pass
        raise RuntimeError(f"下载音频流失败: {e}") from e

    audio_url_web = f"/static/radio/tracks/{audio_filename}"

    # 5. 写入数据库
    track = RadioTrack(
        title=title,
        artist=artist,
        duration=duration,
        cover_url=cover_url_web,
        audio_url=audio_url_web,
        source_type="bilibili",
        source_url=info["canonical_url"],
        source_id=bvid,
        file_size=total_bytes,
        play_count=0,
    )
    db.add(track)
    db.commit()
    db.refresh(track)
    if group_id:
        group = db.get(RadioGroup, group_id)
        if group:
            db.add(RadioTrackGroup(group_id=group.id, track_id=track.id))
            db.commit()

    _attach_track_groups([track], db)
    return track


async def save_uploaded_track(
    file_bytes: bytes,
    filename: str,
    db: Session,
    *,
    custom_title: str | None = None,
    custom_artist: str | None = None,
    group_id: int | None = None,
) -> RadioTrack:
    """上传本地音频文件并收录入库。"""
    clean_name = Path(filename).name
    ext = Path(filename).suffix.lower()
    if ext not in (".mp3", ".m4a", ".wav", ".flac", ".aac", ".ogg"):
        raise ValueError(f"不支持的音频文件格式 ({ext})，仅支持 MP3/M4A/WAV/FLAC/AAC 等！")

    stem = Path(filename).stem
    track_uuid = uuid.uuid4().hex[:12]
    saved_filename = f"upload_{track_uuid}{ext}"
    target_path = _TRACKS_DIR / saved_filename
    target_path.write_bytes(file_bytes)

    # 默认歌曲名与歌手
    title = (custom_title or stem).strip()
    artist = (custom_artist or "本地上传").strip()
    total_bytes = len(file_bytes)

    track = RadioTrack(
        title=title,
        artist=artist,
        duration=0,  # 本地上传若未探测时长则默认为 0，前端播放时由 HTML5 Audio 自动获取并上报
        cover_url="",
        audio_url=f"/static/radio/tracks/{saved_filename}",
        source_type="upload",
        source_url="",
        source_id=clean_name,
        file_size=total_bytes,
        play_count=0,
    )
    db.add(track)
    db.commit()
    db.refresh(track)
    if group_id:
        group = db.get(RadioGroup, group_id)
        if group:
            db.add(RadioTrackGroup(group_id=group.id, track_id=track.id))
            db.commit()

    _attach_track_groups([track], db)
    return track


def _attach_track_groups(tracks: list[RadioTrack], db: Session) -> None:
    """批量为歌曲对象附加所属分组列表信息。"""
    if not tracks:
        return
    track_ids = [t.id for t in tracks]
    stmt = (
        select(RadioTrackGroup.track_id, RadioGroup.id, RadioGroup.name)
        .join(RadioGroup, RadioTrackGroup.group_id == RadioGroup.id)
        .where(RadioTrackGroup.track_id.in_(track_ids))
    )
    rows = db.execute(stmt).all()
    group_map: dict[int, list[dict[str, Any]]] = {}
    for tid, gid, gname in rows:
        if tid not in group_map:
            group_map[tid] = []
        group_map[tid].append({"id": gid, "name": gname})

    for t in tracks:
        t.groups = group_map.get(t.id, [])
        t.group_ids = [g["id"] for g in t.groups]


def list_radio_tracks(db: Session, q: str = "", group_id: int | None = None) -> list[RadioTrack]:
    """查询曲库列表，支持按关键字搜索和按自定义分组筛选。"""
    stmt = select(RadioTrack)
    if group_id:
        matching_track_ids = db.scalars(
            select(RadioTrackGroup.track_id).where(RadioTrackGroup.group_id == group_id)
        ).all()
        if not matching_track_ids:
            return []
        stmt = stmt.where(RadioTrack.id.in_(matching_track_ids))

    query_text = (q or "").strip()
    if query_text:
        stmt = stmt.where(
            (RadioTrack.title.ilike(f"%{query_text}%")) |
            (RadioTrack.artist.ilike(f"%{query_text}%")) |
            (RadioTrack.source_id.ilike(f"%{query_text}%"))
        )
    stmt = stmt.order_by(desc(RadioTrack.id))
    tracks = list(db.scalars(stmt).all())
    _attach_track_groups(tracks, db)
    return tracks


def get_radio_track(track_id: int, db: Session) -> RadioTrack | None:
    track = db.get(RadioTrack, track_id)
    if track:
        _attach_track_groups([track], db)
    return track


def update_radio_track(track_id: int, title: str, artist: str, db: Session) -> RadioTrack | None:
    track = db.get(RadioTrack, track_id)
    if not track:
        return None
    if title:
        track.title = title.strip()
    if artist:
        track.artist = artist.strip()
    db.commit()
    db.refresh(track)
    _attach_track_groups([track], db)
    return track


def delete_radio_track(track_id: int, db: Session) -> bool:
    track = db.get(RadioTrack, track_id)
    if not track:
        return False

    # 清除分组关联
    db.execute(delete(RadioTrackGroup).where(RadioTrackGroup.track_id == track_id))

    # 清理物理音频文件
    if track.audio_url and track.audio_url.startswith("/static/radio/tracks/"):
        fname = track.audio_url.replace("/static/radio/tracks/", "")
        p = _TRACKS_DIR / fname
        if p.is_file():
            try:
                p.unlink()
            except OSError:
                pass

    # 清理本地封面文件
    if track.cover_url and track.cover_url.startswith("/static/radio/covers/"):
        cname = track.cover_url.replace("/static/radio/covers/", "")
        cp = _COVERS_DIR / cname
        if cp.is_file():
            try:
                cp.unlink()
            except OSError:
                pass

    db.delete(track)
    db.commit()
    return True


def increment_track_play_count(track_id: int, db: Session) -> None:
    track = db.get(RadioTrack, track_id)
    if track:
        track.play_count = (track.play_count or 0) + 1
        db.commit()


def get_radio_stats(db: Session) -> dict[str, Any]:
    """获取电台总曲目数、B站音源数、本地上传数、累计播放次数及总大小。"""
    tracks = list_radio_tracks(db)
    total_tracks = len(tracks)
    bilibili_tracks = sum(1 for t in tracks if t.source_type == "bilibili")
    upload_tracks = sum(1 for t in tracks if t.source_type == "upload")
    total_plays = sum((t.play_count or 0) for t in tracks)
    total_duration = sum(t.duration for t in tracks)
    total_size = sum(t.file_size for t in tracks)
    return {
        "total_tracks": total_tracks,
        "bilibili_tracks": bilibili_tracks,
        "upload_tracks": upload_tracks,
        "total_plays": total_plays,
        "total_duration": total_duration,
        "total_size": total_size,
    }


# ---------------------------------------------------------------------------
# 自定义分组 (Radio Groups) 服务逻辑
# ---------------------------------------------------------------------------


def list_radio_groups(db: Session) -> list[dict[str, Any]]:
    """获取所有自定义分组列表及组内歌曲统计。"""
    groups = list(db.scalars(select(RadioGroup).order_by(RadioGroup.id.asc())).all())
    count_stmt = (
        select(RadioTrackGroup.group_id, func.count(RadioTrackGroup.track_id))
        .group_by(RadioTrackGroup.group_id)
    )
    counts = dict(db.execute(count_stmt).all())
    return [
        {
            "id": g.id,
            "name": g.name,
            "description": g.description or "",
            "track_count": counts.get(g.id, 0),
            "created_at": g.created_at.strftime("%Y-%m-%d %H:%M") if g.created_at else "",
        }
        for g in groups
    ]


def get_radio_group(group_id: int, db: Session) -> RadioGroup | None:
    """获取指定分组。"""
    return db.get(RadioGroup, group_id)


def create_radio_group(name: str, description: str, db: Session) -> RadioGroup:
    """新建自定义分组。"""
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("分组名称不能为空！")
    existing = db.scalar(select(RadioGroup).where(RadioGroup.name == clean_name))
    if existing:
        raise ValueError(f"分组「{clean_name}」已存在，请勿重复创建！")

    group = RadioGroup(name=clean_name, description=(description or "").strip())
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


def update_radio_group(group_id: int, name: str, description: str, db: Session) -> RadioGroup | None:
    """修改分组名称或描述。"""
    group = db.get(RadioGroup, group_id)
    if not group:
        return None
    clean_name = (name or "").strip()
    if clean_name and clean_name != group.name:
        existing = db.scalar(select(RadioGroup).where(RadioGroup.name == clean_name))
        if existing and existing.id != group_id:
            raise ValueError(f"分组名称「{clean_name}」已被其他分组使用！")
        group.name = clean_name
    if description is not None:
        group.description = description.strip()
    db.commit()
    db.refresh(group)
    return group


def delete_radio_group(group_id: int, db: Session) -> bool:
    """删除分组（仅删除分组关系，不删除歌曲本体）。"""
    group = db.get(RadioGroup, group_id)
    if not group:
        return False
    db.execute(delete(RadioTrackGroup).where(RadioTrackGroup.group_id == group_id))
    db.delete(group)
    db.commit()
    return True


def set_track_groups(track_id: int, group_ids: list[int], db: Session) -> list[dict[str, Any]]:
    """设置单首歌曲所属的自定义分组列表。"""
    track = db.get(RadioTrack, track_id)
    if not track:
        raise ValueError("曲目不存在！")

    db.execute(delete(RadioTrackGroup).where(RadioTrackGroup.track_id == track_id))

    if group_ids:
        valid_groups = list(db.scalars(select(RadioGroup).where(RadioGroup.id.in_(group_ids))).all())
        for g in valid_groups:
            db.add(RadioTrackGroup(track_id=track_id, group_id=g.id))

    db.commit()

    stmt = (
        select(RadioGroup.id, RadioGroup.name)
        .join(RadioTrackGroup, RadioTrackGroup.group_id == RadioGroup.id)
        .where(RadioTrackGroup.track_id == track_id)
    )
    return [{"id": gid, "name": gname} for gid, gname in db.execute(stmt).all()]


def add_track_to_group(track_id: int, group_id: int, db: Session) -> bool:
    """将单首歌曲加入指定分组。"""
    track = db.get(RadioTrack, track_id)
    group = db.get(RadioGroup, group_id)
    if not track or not group:
        return False
    existing = db.scalar(
        select(RadioTrackGroup).where(
            RadioTrackGroup.track_id == track_id,
            RadioTrackGroup.group_id == group_id,
        )
    )
    if not existing:
        db.add(RadioTrackGroup(track_id=track_id, group_id=group_id))
        db.commit()
    return True


def remove_track_from_group(track_id: int, group_id: int, db: Session) -> bool:
    """将单首歌曲从指定分组中移除。"""
    db.execute(
        delete(RadioTrackGroup).where(
            RadioTrackGroup.track_id == track_id,
            RadioTrackGroup.group_id == group_id,
        )
    )
    db.commit()
    return True


