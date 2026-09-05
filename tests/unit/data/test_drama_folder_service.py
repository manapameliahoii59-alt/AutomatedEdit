import pytest

from app.data.services.drama_folder_service import (
    DramaFolderError,
    list_drama_folders_under,
    scan_drama_folder,
)


class TestScanDramaFolder:
    def test_counts_videos_and_uses_folder_name(self, tmp_path):
        (tmp_path / "02.mp4").write_bytes(b"")
        (tmp_path / "01.mkv").write_bytes(b"")
        (tmp_path / "readme.txt").write_bytes(b"note")

        result = scan_drama_folder(str(tmp_path))

        assert result.name == tmp_path.name
        assert result.episode_count == 2
        assert result.folder_path == str(tmp_path.resolve())
        assert result.video_files[0].endswith("01.mkv")
        assert result.video_files[1].endswith("02.mp4")

    def test_empty_folder_raises(self, tmp_path):
        with pytest.raises(DramaFolderError, match="未找到"):
            scan_drama_folder(str(tmp_path))

    def test_invalid_path_raises(self, tmp_path):
        missing = tmp_path / "missing"
        with pytest.raises(DramaFolderError, match="不是有效文件夹"):
            scan_drama_folder(str(missing))


class TestListDramaFoldersUnder:
    def test_finds_direct_drama_folders(self, tmp_path):
        drama_a = tmp_path / "剧A"
        drama_b = tmp_path / "剧B"
        drama_a.mkdir()
        drama_b.mkdir()
        (drama_a / "01.mp4").write_bytes(b"")
        (drama_a / "02.mp4").write_bytes(b"")
        (drama_b / "第01集.mp4").write_bytes(b"")
        (tmp_path / "说明.txt").write_bytes(b"note")

        folders = list_drama_folders_under(str(tmp_path))

        assert len(folders) == 2
        assert any(f.endswith("剧A") for f in folders)
        assert any(f.endswith("剧B") for f in folders)

    def test_finds_single_nested_season_folder(self, tmp_path):
        """嵌套结构：剧名/第一季/*.mp4。"""
        season = tmp_path / "剧C" / "第一季"
        season.mkdir(parents=True)
        (season / "01.mp4").write_bytes(b"")

        folders = list_drama_folders_under(str(tmp_path))

        assert len(folders) == 1
        assert folders[0].endswith("第一季")

    def test_skips_folders_without_videos(self, tmp_path):
        has_video = tmp_path / "有视频"
        has_video.mkdir()
        (has_video / "01.mp4").write_bytes(b"")
        empty = tmp_path / "空目录"
        empty.mkdir()

        folders = list_drama_folders_under(str(tmp_path))

        assert len(folders) == 1
        assert folders[0].endswith("有视频")

    def test_invalid_root_returns_empty(self, tmp_path):
        assert list_drama_folders_under(str(tmp_path / "missing")) == []

    def test_root_without_children_returns_empty(self, tmp_path):
        assert list_drama_folders_under(str(tmp_path)) == []

    def test_nested_multi_subfolder_not_treated_as_drama(self, tmp_path):
        """多层嵌套（剧名/第一季/上半部）不向下递归。"""
        deep = tmp_path / "剧D" / "第一季" / "上半部"
        deep.mkdir(parents=True)
        (deep / "01.mp4").write_bytes(b"")

        assert list_drama_folders_under(str(tmp_path)) == []
