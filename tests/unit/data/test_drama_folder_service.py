import pytest

from app.data.services.drama_folder_service import DramaFolderError, scan_drama_folder


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
