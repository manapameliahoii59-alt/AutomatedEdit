import pytest
from app.data.models.drama_project import DramaStatus
from app.ui.views.batch_edit.view import BatchEditPage
from app.ui.views.batch_edit.view_model import BatchEditViewModel


class TestBatchEditViewModel:
    def test_starts_with_empty_list(self):
        vm = BatchEditViewModel()
        assert vm.get_projects() == []

    def test_import_drama_folder(self, tmp_path):
        (tmp_path / "01.mp4").write_bytes(b"")
        (tmp_path / "02.mp4").write_bytes(b"")
        vm = BatchEditViewModel()
        vm.import_drama_folder(str(tmp_path))

        projects = vm.get_projects()
        assert len(projects) == 1
        assert projects[0].name == tmp_path.name
        assert projects[0].episode_count == 2
        assert projects[0].folder_path == str(tmp_path.resolve())
        assert len(projects[0].video_files) == 2
        assert projects[0].status == DramaStatus.PENDING

    def test_reimport_same_folder_updates_episode_count(self, tmp_path):
        (tmp_path / "01.mp4").write_bytes(b"")
        vm = BatchEditViewModel()
        vm.import_drama_folder(str(tmp_path))
        project_id = vm.get_projects()[0].id

        (tmp_path / "02.mp4").write_bytes(b"")
        vm.import_drama_folder(str(tmp_path))

        projects = vm.get_projects()
        assert len(projects) == 1
        assert projects[0].id == project_id
        assert projects[0].episode_count == 2

    def test_import_invalid_folder_emits_error(self, tmp_path, qtbot):
        vm = BatchEditViewModel()
        with qtbot.waitSignal(vm.errorOccurred, timeout=1000):
            vm.import_drama_folder(str(tmp_path))

    def test_complete_mask_marks_done(self, tmp_path):
        (tmp_path / "01.mp4").write_bytes(b"")
        vm = BatchEditViewModel()
        vm.import_drama_folder(str(tmp_path))
        project_id = vm.get_projects()[0].id
        vm.complete_mask_for_project(project_id)
        project = next(p for p in vm.get_projects() if p.id == project_id)
        assert project.status == DramaStatus.DONE


class TestBatchEditPage:
    def test_init(self, qapp):
        page = BatchEditPage(None)
        assert page.objectName() == "batch_edit_page"
