"""视频下载完成后自动导入剪辑并一键执行：handoff 信号、设置联动与配额处理测试。"""

from unittest.mock import MagicMock, patch
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from qfluentwidgets import qconfig

from app.common.config import cfg
from app.data.services.quota_service import DailyQuota, QuotaService
from app.ui.views.clip_edit.view import ClipEditPage
from app.ui.views.video_download.view_model import (
    VideoDownloadTarget,
    VideoDownloadViewModel,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def isolate_config(monkeypatch):
    monkeypatch.setattr(qconfig, "save", lambda *args, **kwargs: None)


@pytest.fixture
def vm(qapp, mocker):
    mocker.patch(
        "app.ui.views.video_download.view_model.VideoDownloadViewModel._load_settings_from_server"
    )
    return VideoDownloadViewModel()


def _make_drama_folder(tmp_path, name="test_drama"):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "01.mp4").write_bytes(b"dummy")
    return d


def test_download_success_emits_handoff_when_auto_batch_all_enabled(vm, mocker, tmp_path):
    qconfig.set(cfg.video_download_auto_batch_all, True)
    folder_a = tmp_path / "剧A"
    folder_b = tmp_path / "剧B"
    folder_a.mkdir()
    folder_b.mkdir()

    handoffs = []
    vm.handoffToClipEdit.connect(lambda folders: handoffs.append(list(folders)))

    mocker.patch("app.ui.views.video_download.view_model.UsageService.report_download_dramas")
    mocker.patch("app.ui.views.video_download.view_model.task_manager.submit_task")

    # 模拟 start_download 内的 _on_success 回调
    # 直接设置目标并触发 _do_download 的 on_success
    vm._targets = [
        VideoDownloadTarget(id="1", name="剧A", from_ep=1, to_ep=15, status="下载中"),
        VideoDownloadTarget(id="2", name="剧B", from_ep=1, to_ep=15, status="下载中"),
    ]

    # 提取 submit_task 传入的 on_success
    captured_callbacks = {}

    def fake_submit(task_fn, on_success=None, on_error=None):
        captured_callbacks["on_success"] = on_success

    mocker.patch("app.ui.views.video_download.view_model.task_manager.submit_task", side_effect=fake_submit)
    mocker.patch("app.ui.views.video_download.view_model.is_auth_file_present", return_value=True)
    mocker.patch.object(vm, "_ensure_can_download", return_value=True)

    vm.start_download()
    assert "on_success" in captured_callbacks

    # 调用 on_success，模拟 batch_download_service 返回的 downloaded_folders
    captured_callbacks["on_success"]({
        "downloaded_folders": [str(folder_a), str(folder_b)]
    })

    assert len(handoffs) == 1
    assert handoffs[0] == [str(folder_a), str(folder_b)]


def test_download_success_no_handoff_when_disabled(vm, mocker, tmp_path):
    qconfig.set(cfg.video_download_auto_batch_all, False)
    folder_a = tmp_path / "剧A"
    folder_a.mkdir()

    handoffs = []
    vm.handoffToClipEdit.connect(lambda folders: handoffs.append(list(folders)))

    mocker.patch("app.ui.views.video_download.view_model.UsageService.report_download_dramas")
    vm._targets = [
        VideoDownloadTarget(id="1", name="剧A", from_ep=1, to_ep=15, status="下载中")
    ]
    captured_callbacks = {}

    def fake_submit(task_fn, on_success=None, on_error=None):
        captured_callbacks["on_success"] = on_success

    mocker.patch("app.ui.views.video_download.view_model.task_manager.submit_task", side_effect=fake_submit)
    mocker.patch("app.ui.views.video_download.view_model.is_auth_file_present", return_value=True)
    mocker.patch.object(vm, "_ensure_can_download", return_value=True)

    vm.start_download()
    captured_callbacks["on_success"]({
        "downloaded_folders": [str(folder_a)]
    })

    assert len(handoffs) == 0


def test_clip_edit_start_auto_batch_all_full_quota(qapp, mocker, tmp_path):
    folder_a = _make_drama_folder(tmp_path, "剧A")
    folder_b = _make_drama_folder(tmp_path, "剧B")

    page = ClipEditPage()
    mocker.patch("app.ui.views.clip_edit.view.access_control.ensure_authorized_interactive", return_value=True)
    mocker.patch.object(page.vm, "check_batch_clip_quota", return_value=(True, "配额充足", 10, 2))
    batch_all_mock = mocker.patch.object(page.vm, "batch_all")
    set_checked_mock = mocker.patch.object(page, "_set_checked_ids")

    page.start_auto_batch_all_from_download([str(folder_a), str(folder_b)])

    assert batch_all_mock.called
    target_ids = batch_all_mock.call_args[0][0]
    assert len(target_ids) == 2
    assert set_checked_mock.called
    page.deleteLater()


def test_clip_edit_start_auto_batch_all_partial_quota(qapp, mocker, tmp_path):
    folder_a = _make_drama_folder(tmp_path, "剧A")
    folder_b = _make_drama_folder(tmp_path, "剧B")

    page = ClipEditPage()
    mocker.patch("app.ui.views.clip_edit.view.access_control.ensure_authorized_interactive", return_value=True)
    # 模拟剩余配额为 1 部，而本次有 2 部
    mocker.patch.object(page.vm, "check_batch_clip_quota", return_value=(False, "超出配额", 1, 2))
    fake_quota = DailyQuota(clip_count=9, clip_limit=10, clipped_dramas=[])
    mocker.patch.object(QuotaService.instance(), "get_quota", return_value=fake_quota)
    batch_all_mock = mocker.patch.object(page.vm, "batch_all")
    set_checked_mock = mocker.patch.object(page, "_set_checked_ids")

    page.start_auto_batch_all_from_download([str(folder_a), str(folder_b)])

    # 方案 2：自动对额度内的第 1 部执行
    assert batch_all_mock.called
    target_ids = batch_all_mock.call_args[0][0]
    assert len(target_ids) == 1
    assert set_checked_mock.called
    page.deleteLater()


def test_clip_edit_start_auto_batch_all_zero_quota(qapp, mocker, tmp_path):
    folder_a = _make_drama_folder(tmp_path, "剧A")

    page = ClipEditPage()
    mocker.patch("app.ui.views.clip_edit.view.access_control.ensure_authorized_interactive", return_value=True)
    # 模拟今日配额为 0
    mocker.patch.object(page.vm, "check_batch_clip_quota", return_value=(False, "今日剪辑额度已用尽", 0, 1))
    batch_all_mock = mocker.patch.object(page.vm, "batch_all")

    page.start_auto_batch_all_from_download([str(folder_a)])

    # 配额为 0 时跳过自动一键执行
    assert not batch_all_mock.called
    page.deleteLater()


def test_video_download_settings_dialog_linkage_and_save(qapp, mocker):
    mocker.patch(
        "app.ui.views.video_download.view_model.VideoDownloadViewModel._load_settings_from_server"
    )
    save_server_mock = mocker.patch(
        "app.ui.views.video_download.view_model.VideoDownloadViewModel.save_to_server"
    )
    qconfig.set(cfg.video_download_auto_unzip, False)
    qconfig.set(cfg.video_download_auto_batch_all, False)
    qconfig.set(cfg.video_download_auto_start_after_add, True)

    from app.ui.views.video_download.view import VideoDownloadPage
    from qfluentwidgets import CheckBox, Dialog

    page = VideoDownloadPage()

    def fake_exec(self):
        boxes = self.findChildren(CheckBox)
        unzip_cb = next(b for b in boxes if "解压" in b.text())
        batch_all_cb = next(b for b in boxes if "一键执行" in b.text())
        start_cb = next(b for b in boxes if "添加剧目" in b.text())

        assert not unzip_cb.isChecked()
        assert not batch_all_cb.isChecked()
        assert start_cb.isChecked()

        # 联动 1：勾选一键执行 -> 自动勾选解压
        batch_all_cb.setChecked(True)
        assert unzip_cb.isChecked()

        # 联动 2：取消解压 -> 自动取消一键执行
        unzip_cb.setChecked(False)
        assert not batch_all_cb.isChecked()

        # 重新勾选一键执行
        batch_all_cb.setChecked(True)
        return 1

    mocker.patch.object(Dialog, "exec", fake_exec)

    page._open_download_settings_dialog()

    assert cfg.video_download_auto_unzip.value is True
    assert cfg.video_download_auto_batch_all.value is True
    assert save_server_mock.called
    patch_sent = save_server_mock.call_args[0][0]["video_download"]
    assert patch_sent["auto_unzip"] is True
    assert patch_sent["auto_batch_all"] is True
    page.deleteLater()

