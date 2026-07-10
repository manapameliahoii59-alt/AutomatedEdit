from app.data.models.drama_project import DramaStatus
from app.ui.views.clip_edit.view_model import ClipEditViewModel


def _make_drama_folder(tmp_path):
    (tmp_path / "01.mp4").write_bytes(b"")
    return tmp_path


class TestClipEditViewModelImport:
    def test_import_detects_transcribe_and_plan_from_disk(self, tmp_path):
        folder = _make_drama_folder(tmp_path)
        (folder / "full_script_data.json").write_text("{}", encoding="utf-8")
        (folder / "production_plan_v3.json").write_text("{}", encoding="utf-8")

        vm = ClipEditViewModel()
        vm.import_drama_folder(str(folder), emit_message=False)

        project = vm.get_projects()[0]
        status = vm._status[project.id]
        assert status["transcribe"] == DramaStatus.DONE
        assert status["plan"] == DramaStatus.DONE
        assert status["render"] == DramaStatus.PENDING

    def test_import_detects_transcribe_only(self, tmp_path):
        folder = _make_drama_folder(tmp_path)
        (folder / "full_script_data.json").write_text("{}", encoding="utf-8")

        vm = ClipEditViewModel()
        vm.import_drama_folder(str(folder), emit_message=False)

        status = vm._status[vm.get_projects()[0].id]
        assert status["transcribe"] == DramaStatus.DONE
        assert status["plan"] == DramaStatus.PENDING


class TestClipEditViewModelTiming:
    def test_format_elapsed(self):
        assert ClipEditViewModel._format_elapsed(12.4) == "12.4 秒"
        assert ClipEditViewModel._format_elapsed(75) == "1 分 15 秒"
        assert ClipEditViewModel._format_elapsed(3665) == "1 小时 1 分 5 秒"

    def test_reimport_refreshes_disk_status(self, tmp_path):
        folder = _make_drama_folder(tmp_path)
        vm = ClipEditViewModel()
        vm.import_drama_folder(str(folder), emit_message=False)
        project_id = vm.get_projects()[0].id
        assert vm._status[project_id]["transcribe"] == DramaStatus.PENDING

        (folder / "full_script_data.json").write_text("{}", encoding="utf-8")
        (folder / "production_plan_v3.json").write_text("{}", encoding="utf-8")
        vm.import_drama_folder(str(folder), emit_message=False)

        status = vm._status[project_id]
        assert status["transcribe"] == DramaStatus.DONE
        assert status["plan"] == DramaStatus.DONE
