"""Unit tests for BatchExecutionDialog and batch execution timing models."""

import time
import pytest
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from app.data.models.batch_execution_record import (
    BatchExecutionSummary,
    DramaTimingRecord,
    format_duration,
    format_duration_short,
)
from app.ui.components.batch_execution_dialog import BatchExecutionDialog


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestBatchExecutionRecordModel:
    def test_timing_calculation(self):
        rec = DramaTimingRecord(
            project_id="p1",
            project_name="测试剧目",
            transcribe_time=12.4,
            plan_time=8.1,
            render_time=25.5,
        )
        assert abs(rec.total_time - 46.0) < 1e-5

    def test_is_success_single_and_all(self):
        rec = DramaTimingRecord(
            project_id="p1",
            project_name="测试剧目",
            transcribe_status="done",
            plan_status="done",
            render_status="failed",
        )
        assert rec.is_success("transcribe") is True
        assert rec.is_success("plan") is True
        assert rec.is_success("render") is False
        assert rec.is_success("all") is False

        rec.render_status = "done"
        assert rec.is_success("render") is True
        assert rec.is_success("all") is True

    def test_summary_counts(self):
        rec1 = DramaTimingRecord(
            project_id="p1",
            project_name="剧目1",
            transcribe_status="done",
            plan_status="done",
            render_status="done",
        )
        rec2 = DramaTimingRecord(
            project_id="p2",
            project_name="剧目2",
            transcribe_status="done",
            plan_status="failed",
            render_status="skipped",
            error_msg="策划失败",
        )
        summary = BatchExecutionSummary(task_type="all", records=[rec1, rec2])
        assert summary.total_count == 2
        assert summary.success_count == 1
        assert summary.fail_count == 1

    def test_duration_formatting(self):
        assert format_duration(15.2) == "15.2 秒"
        assert format_duration(75) == "1 分 15 秒"
        assert format_duration(3665) == "1 小时 1 分 5 秒"

        assert format_duration_short(15.2) == "15.2s"
        assert format_duration_short(75) == "1m 15s"
        assert format_duration_short(3665) == "1h 1m 5s"


class TestBatchExecutionDialogUi:
    def test_single_batch_dialog_lifecycle(self, qapp):
        dialog = BatchExecutionDialog(task_type="transcribe")
        assert dialog.windowTitle() == "批量识别进度与耗时"
        assert dialog.table.columnCount() == 5

        records = [
            DramaTimingRecord(project_id="p1", project_name="剧目1", episode_count=10),
            DramaTimingRecord(project_id="p2", project_name="剧目2", episode_count=15),
        ]
        summary = BatchExecutionSummary(task_type="transcribe", records=records)
        dialog.init_batch(summary)
        assert dialog.table.rowCount() == 2

        # 进度更新
        records[0].transcribe_status = "in_progress"
        dialog.update_progress(
            records[0],
            action_text="正在识别第 1/2 部：《剧目1》",
            current_index=1,
            total_count=2,
        )
        assert "正在识别第 1/2 部" in dialog.status_label.text()

        # 单项完成
        records[0].transcribe_status = "done"
        records[0].transcribe_time = 14.5
        dialog.update_progress(records[0], current_index=1, total_count=2)

        # 批次全部完成
        records[1].transcribe_status = "done"
        records[1].transcribe_time = 18.2
        summary.total_elapsed = 32.7
        dialog.finish_batch(summary)

        assert dialog.close_btn.isHidden() is False
        assert dialog.cancel_btn.isHidden() is True
        assert "批量识别执行完毕" in dialog.title_label.text()
        assert "32.7 秒" in dialog.status_label.text()
        dialog.close()

    def test_all_pipeline_dialog_lifecycle(self, qapp):
        dialog = BatchExecutionDialog(task_type="all")
        assert dialog.windowTitle() == "一键执行全流程与耗时结算"
        assert dialog.table.columnCount() == 7

        records = [
            DramaTimingRecord(
                project_id="p1",
                project_name="测试剧目",
                episode_count=12,
                transcribe_time=12.1,
                plan_time=8.5,
                render_time=30.4,
                transcribe_status="done",
                plan_status="done",
                render_status="done",
            )
        ]
        summary = BatchExecutionSummary(
            task_type="all",
            records=records,
            total_elapsed=51.0,
        )
        dialog.init_batch(summary)
        dialog.finish_batch(summary)

        assert "一键执行全部完毕" in dialog.title_label.text()
        assert dialog.open_export_btn.isHidden() is False
        assert dialog.close_btn.isHidden() is False

        # 验证表格内容
        assert dialog.table.item(0, 0).text() == "测试剧目"
        assert dialog.table.item(0, 1).text() == "12"
        assert dialog.table.item(0, 2).text() == "12.1s"
        assert dialog.table.item(0, 3).text() == "8.5s"
        assert dialog.table.item(0, 4).text() == "30.4s"
        assert dialog.table.item(0, 5).text() == "51.0s"
        assert "全部完成" in dialog.table.item(0, 6).text()
        dialog.close()

    def test_clip_edit_page_no_top_loading_bar(self, qapp, monkeypatch):
        from app.ui.views.clip_edit.view import ClipEditPage

        monkeypatch.setattr(
            "app.ui.views.clip_edit.view_model.ClipEditViewModel._load_settings_from_server",
            lambda self: None,
        )
        page = ClipEditPage()
        assert not hasattr(page, "loading_bar")
        # trigger loading
        page.vm.loadingChanged.emit(True, "正在批量识别", "第 1 部")
        assert not hasattr(page, "loading_bar")
        assert page._busy is True
        assert page.batch_all_btn.isEnabled() is False

        # trigger finished
        page.vm.loadingChanged.emit(False, "", "")
        assert page._busy is False
        assert page.batch_all_btn.isEnabled() is True
        page.close()

    def test_dialog_dimensions_and_tooltips(self, qapp):
        dialog = BatchExecutionDialog(task_type="transcribe")
        assert dialog.minimumWidth() == 760
        assert dialog.width() >= 850
        assert dialog.table.columnWidth(3) == 130  # 耗时栏位拓宽至 130px

        rec = DramaTimingRecord(
            project_id="p1",
            project_name="测试超长剧名-用于验证提示工具栏是否正常绑定气泡",
            episode_count=30,
            transcribe_status="done",
            transcribe_time=75.5,
        )
        summary = BatchExecutionSummary(task_type="transcribe", records=[rec])
        dialog.init_batch(summary)

        # 验证所有关键单元格 ToolTip 均已绑定
        assert dialog.table.item(0, 0).toolTip() == "测试超长剧名-用于验证提示工具栏是否正常绑定气泡"
        assert "30" in dialog.table.item(0, 1).toolTip()
        assert "完成" in dialog.table.item(0, 2).toolTip()
        assert "1 分 15" in dialog.table.item(0, 3).toolTip()
        dialog.close()

    def test_transcription_service_cancellation(self, monkeypatch, tmp_path):
        from app.data.models.drama_project import DramaProject
        from app.data.services.transcription_service import TranscriptionService

        (tmp_path / "01.mp4").write_bytes(b"")
        (tmp_path / "02.mp4").write_bytes(b"")
        project = DramaProject(
            id="p1",
            name="测试剧目",
            folder_path=str(tmp_path),
            episode_count=2,
        )

        monkeypatch.setattr(TranscriptionService, "init_model", classmethod(lambda cls: None))

        # 当 should_cancel 为 True 时，启动即抛出 InterruptedError
        with pytest.raises(InterruptedError, match="用户取消识别"):
            TranscriptionService.transcribe(project, should_cancel=lambda: True)

    def test_batch_dialog_header_enrichment_and_spinner(self, qapp):
        dialog = BatchExecutionDialog(task_type="transcribe")
        assert hasattr(dialog, "spinner")
        assert hasattr(dialog, "progress_detail_label")
        assert hasattr(dialog, "timer_label")
        assert dialog.spinner.isHidden() is True

        records = [
            DramaTimingRecord(project_id="p1", project_name="剧目1", episode_count=10),
            DramaTimingRecord(project_id="p2", project_name="剧目2", episode_count=20),
        ]
        summary = BatchExecutionSummary(task_type="transcribe", records=records)
        dialog.init_batch(summary)

        # 验证初始化后：动态指示器显示并启动、计时器启动、进度标签显示
        assert dialog.spinner.isHidden() is False
        assert dialog._elapsed_timer.isActive() is True
        assert "进度: 0/2 (0%)" in dialog.progress_detail_label.text()
        assert "⏱️ 00:00" in dialog.timer_label.text()

        # 验证实时耗时刷新
        dialog._start_time = time.perf_counter() - 65
        dialog._update_live_elapsed()
        assert "01:05" in dialog.timer_label.text()

        # 进度更新
        dialog.update_progress(records[0], action_text="正在识别第1部", current_index=1, total_count=2)
        assert "进度: 1/2 (50%)" in dialog.progress_detail_label.text()

        # 完成结算
        summary.total_elapsed = 70.0
        dialog.finish_batch(summary)
        assert dialog.spinner.isHidden() is True
        assert dialog._elapsed_timer.isActive() is False
        assert "已完成 0/2" in dialog.progress_detail_label.text()
        assert "⏱️ 总耗时: 1m 10s" in dialog.timer_label.text()
        dialog.close()

    def test_batch_dialog_cancel_stops_spinner_and_timer(self, qapp):
        dialog = BatchExecutionDialog(task_type="transcribe")
        records = [DramaTimingRecord(project_id="p1", project_name="剧目1")]
        summary = BatchExecutionSummary(task_type="transcribe", records=records)
        dialog.init_batch(summary)

        assert dialog.spinner.isHidden() is False
        assert dialog._elapsed_timer.isActive() is True

        # 点击取消按钮时，转轮保持旋转提示用户正在取消并等待
        dialog._on_cancel_clicked()
        assert dialog.spinner.isHidden() is False
        assert dialog._is_cancelling is True
        assert dialog.cancel_btn.isEnabled() is False
        assert "正在取消后续任务，请稍候…" in dialog.status_label.text()

        # 后台结算完成时，转轮停止隐藏
        summary.is_cancelled = True
        dialog.finish_batch(summary)
        assert dialog.spinner.isHidden() is True
        assert dialog._elapsed_timer.isActive() is False
        dialog.close()

    def test_batch_dialog_close_event_waits_for_cancellation(self, qapp):
        dialog = BatchExecutionDialog(task_type="transcribe")
        records = [DramaTimingRecord(project_id="p1", project_name="剧目1")]
        summary = BatchExecutionSummary(task_type="transcribe", records=records)
        dialog.init_batch(summary)

        cancelled_emitted = []
        dialog.cancelled.connect(lambda: cancelled_emitted.append(True))

        # 用户在执行中点击右上角关闭
        close_event = QCloseEvent()
        dialog.closeEvent(close_event)

        # 验证：事件被忽略（未直接销毁退出）、设置 close_on_finish、状态提示友好、发射取消信号
        assert close_event.isAccepted() is False
        assert dialog._close_on_finish is True
        assert dialog._is_cancelling is True
        assert "正在等待当前任务安全退出后关闭窗口" in dialog.status_label.text()
        assert len(cancelled_emitted) == 1
        assert dialog.spinner.isHidden() is False

        # 后台任务完成取消并回报 finish_batch
        summary.is_cancelled = True
        dialog.finish_batch(summary)

        # 验证等待后台安全退出后自动关闭
        assert dialog.isVisible() is False

    def test_batch_dialog_close_when_already_finished(self, qapp):
        dialog = BatchExecutionDialog(task_type="transcribe")
        records = [DramaTimingRecord(project_id="p1", project_name="剧目1")]
        summary = BatchExecutionSummary(task_type="transcribe", records=records)
        dialog.init_batch(summary)
        dialog.finish_batch(summary)

        # 任务已完成后，点击关闭直接放行
        close_event = QCloseEvent()
        dialog.closeEvent(close_event)
        assert close_event.isAccepted() is True

    def test_batch_dialog_reject_delegates_to_close(self, qapp):
        dialog = BatchExecutionDialog(task_type="transcribe")
        records = [DramaTimingRecord(project_id="p1", project_name="剧目1")]
        summary = BatchExecutionSummary(task_type="transcribe", records=records)
        dialog.init_batch(summary)

        # 按 ESC 触发 reject 时，在运行中同样进入安全取消等待
        dialog.reject()
        assert dialog._close_on_finish is True
        assert dialog._is_cancelling is True
        assert "正在等待当前任务安全退出后关闭窗口" in dialog.status_label.text()
        dialog.close()




