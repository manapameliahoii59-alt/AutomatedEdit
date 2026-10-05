from app.data.models.batch_execution_record import (
    BatchExecutionSummary,
    DramaTimingRecord,
)
from app.data.models.drama_project import DramaProject, DramaStatus
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

    def test_remove_project(self, tmp_path):
        folder = _make_drama_folder(tmp_path)
        vm = ClipEditViewModel()
        vm.import_drama_folder(str(folder), emit_message=False)
        assert len(vm.get_projects()) == 1
        pid = vm.get_projects()[0].id

        vm.remove_project(pid)
        assert len(vm.get_projects()) == 0
        assert pid not in vm._status


class TestClipEditViewModelQueueAppend:
    def test_append_to_batch_all_when_not_running(self):
        vm = ClipEditViewModel()
        assert not vm.is_batch_running()
        project = DramaProject(id="p1", name="剧目一", folder_path="/path/1", episode_count=10)
        assert vm.append_to_batch_all([project]) is False

    def test_append_to_batch_all_success_and_deduplicate(self):
        vm = ClipEditViewModel()
        p1 = DramaProject(id="p1", name="剧目一", folder_path="/path/1", episode_count=10)
        p2 = DramaProject(id="p2", name="剧目二", folder_path="/path/2", episode_count=20)
        vm._projects = [p1, p2]

        # 模拟当前正在运行一键执行任务
        rec1 = DramaTimingRecord(project_id="p1", project_name="剧目一")
        summary = BatchExecutionSummary(task_type="all", records=[rec1])
        vm._is_batch_running = True
        vm._active_batch_queue = [p1]
        vm._active_batch_records = [rec1]
        vm._current_batch_summary = summary

        assert vm.is_batch_running() is True

        emitted_events = []
        vm.batchExecutionTaskAppended.connect(
            lambda recs, total: emitted_events.append((recs, total))
        )

        # 追加新下载的剧目 p2
        res = vm.append_to_batch_all([p2])
        assert res is True
        assert len(vm._active_batch_queue) == 2
        assert vm._active_batch_queue[1].id == "p2"
        assert len(vm._active_batch_records) == 2
        assert vm._active_batch_records[1].project_id == "p2"
        assert len(summary.records) == 2
        assert len(emitted_events) == 1
        new_recs, total = emitted_events[0]
        assert len(new_recs) == 1
        assert new_recs[0].project_id == "p2"
        assert total == 2

        # 重复追加 p2 时被幂等去重
        res2 = vm.append_to_batch_all([p2])
        assert res2 is True
        assert len(vm._active_batch_queue) == 2
        assert len(emitted_events) == 1
