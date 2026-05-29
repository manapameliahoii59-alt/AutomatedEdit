from dataclasses import dataclass
from pathlib import Path

VIDEO_EXTENSIONS = frozenset(
    {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".ts"}
)


@dataclass(frozen=True)
class DramaFolderScanResult:
    name: str
    folder_path: str
    episode_count: int
    video_files: tuple[str, ...]


class DramaFolderError(ValueError):
    """剧集目录扫描失败。"""


def scan_drama_folder(folder_path: str) -> DramaFolderScanResult:
    """扫描剧集文件夹，统计其中的视频文件。"""
    root = Path(folder_path).expanduser().resolve()
    if not root.is_dir():
        raise DramaFolderError("所选路径不是有效文件夹。")

    videos = sorted(
        (p for p in root.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS),
        key=lambda p: p.name.lower(),
    )
    if not videos:
        raise DramaFolderError("该文件夹内未找到支持的视频文件（如 mp4、mkv 等）。")

    return DramaFolderScanResult(
        name=root.name,
        folder_path=str(root),
        episode_count=len(videos),
        video_files=tuple(str(p) for p in videos),
    )
