from app.data.models.drama_project import DramaProject
from app.ui.components.mask_edit_dialog import resolve_video_files


class TestResolveVideoFiles:
    def test_uses_stored_video_files(self):
        project = DramaProject("1", "剧", 2, video_files=("/a/01.mp4", "/a/02.mp4"))
        assert resolve_video_files(project) == ["/a/01.mp4", "/a/02.mp4"]

    def test_scans_folder_when_paths_missing(self, tmp_path):
        (tmp_path / "01.mp4").write_bytes(b"")
        project = DramaProject("1", "剧", 1, folder_path=str(tmp_path))
        files = resolve_video_files(project)
        assert len(files) == 1
        assert files[0].endswith("01.mp4")

    def test_reimport_updates_video_files(self, tmp_path):
        from app.ui.views.batch_edit.view_model import BatchEditViewModel

        (tmp_path / "01.mp4").write_bytes(b"")
        (tmp_path / "02.mp4").write_bytes(b"")
        vm = BatchEditViewModel()
        vm.import_drama_folder(str(tmp_path))
        project = vm.get_projects()[0]
        assert len(project.video_files) == 2
