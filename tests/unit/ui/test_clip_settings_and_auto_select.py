"""Unit tests for ClipSettingsDialog and clip_auto_select_after_import feature."""

from unittest.mock import patch
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from qfluentwidgets import qconfig

from app.common.config import cfg
from app.ui.components.clip_settings_dialog import ClipSettingsDialog
from app.ui.views.clip_edit.view import ClipEditPage


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def isolate_config(monkeypatch):
    """Prevent tests from writing to the real config.json on disk."""
    monkeypatch.setattr(qconfig, "save", lambda *args, **kwargs: None)



def _make_drama_folder(tmp_path, name="test_drama"):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "01.mp4").write_bytes(b"dummy")
    return d


class TestClipSettingsDialog:
    def test_auto_select_switch_initialization(self, qapp):
        # Test initialized to current cfg value (True)
        qconfig.set(cfg.clip_auto_select_after_import, True)
        dlg = ClipSettingsDialog()
        assert dlg._auto_select_switch.isChecked() is True
        assert dlg.result_auto_select_after_import() is True
        dlg.deleteLater()

        # Test initialized to False
        qconfig.set(cfg.clip_auto_select_after_import, False)
        dlg = ClipSettingsDialog()
        assert dlg._auto_select_switch.isChecked() is False
        assert dlg.result_auto_select_after_import() is False
        dlg.deleteLater()

        # Restore default
        qconfig.set(cfg.clip_auto_select_after_import, True)

    def test_auto_select_switch_toggle(self, qapp):
        dlg = ClipSettingsDialog()
        dlg._auto_select_switch.setChecked(False)
        assert dlg.result_auto_select_after_import() is False

        dlg._auto_select_switch.setChecked(True)
        assert dlg.result_auto_select_after_import() is True
        dlg.deleteLater()

    def test_auto_retry_switch_initialization(self, qapp):
        qconfig.set(cfg.clip_auto_retry_failed, True)
        dlg = ClipSettingsDialog()
        assert dlg._auto_retry_switch.isChecked() is True
        assert dlg.result_auto_retry_failed() is True
        dlg.deleteLater()

        qconfig.set(cfg.clip_auto_retry_failed, False)
        dlg = ClipSettingsDialog()
        assert dlg._auto_retry_switch.isChecked() is False
        assert dlg.result_auto_retry_failed() is False
        dlg.deleteLater()

        qconfig.set(cfg.clip_auto_retry_failed, True)

    def test_auto_retry_switch_toggle(self, qapp):
        dlg = ClipSettingsDialog()
        dlg._auto_retry_switch.setChecked(False)
        assert dlg.result_auto_retry_failed() is False

        dlg._auto_retry_switch.setChecked(True)
        assert dlg.result_auto_retry_failed() is True
        dlg.deleteLater()

    def test_dialog_hides_max_transcribe_control(self, qapp):
        # 识别集数上限改为仅后台管理页面可设置，客户端弹框不再暴露该控件
        dlg = ClipSettingsDialog()
        assert not hasattr(dlg, "_max_transcribe_spin")
        assert not hasattr(dlg, "result_max_transcribe_episodes")
        dlg.deleteLater()

    def test_render_engine_v3_selection(self, qapp):
        # 验证弹框支持选择并返回 v3 引擎
        dlg = ClipSettingsDialog()
        idx_v3 = dlg._render_engine_combo.findData("v3")
        assert idx_v3 >= 0
        dlg._render_engine_combo.setCurrentIndex(idx_v3)
        assert dlg.result_render_engine() == "v3"
        dlg.deleteLater()


class TestClipEditAutoSelectAfterImport:
    def test_import_with_auto_select_enabled(self, qapp, tmp_path, monkeypatch):
        saved_calls = []

        def fake_set(item, val):
            item.value = val
            saved_calls.append((item, val))

        monkeypatch.setattr("qfluentwidgets.qconfig.set", fake_set)

        qconfig.set(cfg.clip_auto_select_after_import, True)
        folder = _make_drama_folder(tmp_path, "drama1")

        page = ClipEditPage()
        with patch("PySide6.QtWidgets.QFileDialog.getExistingDirectory", return_value=str(folder)):
            page._pick_drama_folder()

        assert page.table.rowCount() >= 1
        # All rows should be checked
        for row in range(page.table.rowCount()):
            item = page.table.item(row, 0)
            assert item is not None
            assert item.checkState() == Qt.CheckState.Checked

        # Select all header should be checked
        assert page._select_all_header.select_state() == Qt.CheckState.Checked
        page.deleteLater()

    def test_import_with_auto_select_disabled(self, qapp, tmp_path, monkeypatch):
        saved_calls = []

        def fake_set(item, val):
            item.value = val
            saved_calls.append((item, val))

        monkeypatch.setattr("qfluentwidgets.qconfig.set", fake_set)

        qconfig.set(cfg.clip_auto_select_after_import, False)
        folder = _make_drama_folder(tmp_path, "drama2")

        page = ClipEditPage()
        with patch("PySide6.QtWidgets.QFileDialog.getExistingDirectory", return_value=str(folder)):
            page._pick_drama_folder()

        assert page.table.rowCount() >= 1
        # All rows should be unchecked
        for row in range(page.table.rowCount()):
            item = page.table.item(row, 0)
            assert item is not None
            assert item.checkState() == Qt.CheckState.Unchecked

        # Select all header should be unchecked
        assert page._select_all_header.select_state() == Qt.CheckState.Unchecked
        page.deleteLater()

        # Restore default
        cfg.clip_auto_select_after_import.value = True

    def test_single_drama_import_remembers_parent_dir(self, qapp, tmp_path, monkeypatch):
        saved_configs = {}

        def fake_set(item, val):
            item.value = val
            saved_configs[item] = val

        monkeypatch.setattr("qfluentwidgets.qconfig.set", fake_set)

        drama_folder = _make_drama_folder(tmp_path / "collection", "drama_single")
        page = ClipEditPage()
        with patch("PySide6.QtWidgets.QFileDialog.getExistingDirectory", return_value=str(drama_folder)):
            page._pick_drama_folder()

        # Single drama: should remember parent folder
        import os
        expected_parent = os.path.normpath(str(tmp_path / "collection"))
        assert cfg.clip_last_import_dir in saved_configs
        assert saved_configs[cfg.clip_last_import_dir] == expected_parent
        page.deleteLater()

    def test_collection_folder_import_remembers_collection_itself(self, qapp, tmp_path, monkeypatch):
        saved_configs = {}

        def fake_set(item, val):
            item.value = val
            saved_configs[item] = val

        monkeypatch.setattr("qfluentwidgets.qconfig.set", fake_set)

        collection = tmp_path / "all_dramas"
        collection.mkdir(parents=True, exist_ok=True)
        _make_drama_folder(collection, "sub_drama1")
        _make_drama_folder(collection, "sub_drama2")

        page = ClipEditPage()
        with patch("PySide6.QtWidgets.QFileDialog.getExistingDirectory", return_value=str(collection)):
            page._pick_drama_folder()

        # Collection: should remember collection itself (not grandparent!)
        import os
        expected_collection = os.path.normpath(str(collection))
        assert cfg.clip_last_import_dir in saved_configs
        assert saved_configs[cfg.clip_last_import_dir] == expected_collection
        page.deleteLater()

    def test_open_clip_settings_saves_auto_select_setting(self, qapp):
        page = ClipEditPage()
        qconfig.set(cfg.clip_auto_select_after_import, True)

        with patch("app.ui.views.clip_edit.view.ClipSettingsDialog") as mock_dlg_cls:
            mock_dlg = mock_dlg_cls.return_value
            mock_dlg.exec.return_value = 1  # Accepted
            mock_dlg.result_enable_gpu.return_value = True
            mock_dlg.result_trim_ep1_continued.return_value = False
            mock_dlg.result_auto_select_after_import.return_value = False
            mock_dlg.result_resolution.return_value = "1280x720"

            page._open_clip_settings()

            assert cfg.clip_auto_select_after_import.value is False

        # Test switching back to True
        with patch("app.ui.views.clip_edit.view.ClipSettingsDialog") as mock_dlg_cls:
            mock_dlg = mock_dlg_cls.return_value
            mock_dlg.exec.return_value = 1  # Accepted
            mock_dlg.result_enable_gpu.return_value = True
            mock_dlg.result_trim_ep1_continued.return_value = True
            mock_dlg.result_auto_select_after_import.return_value = True
            mock_dlg.result_resolution.return_value = "1280x720"

            page._open_clip_settings()

            assert cfg.clip_auto_select_after_import.value is True

        page.deleteLater()

    def test_open_clip_settings_saves_auto_retry_setting(self, qapp):
        page = ClipEditPage()
        qconfig.set(cfg.clip_auto_retry_failed, True)

        with patch("app.ui.views.clip_edit.view.ClipSettingsDialog") as mock_dlg_cls:
            mock_dlg = mock_dlg_cls.return_value
            mock_dlg.exec.return_value = 1  # Accepted
            mock_dlg.result_enable_gpu.return_value = True
            mock_dlg.result_trim_ep1_continued.return_value = False
            mock_dlg.result_auto_select_after_import.return_value = True
            mock_dlg.result_auto_retry_failed.return_value = False
            mock_dlg.result_resolution.return_value = "1280x720"

            page._open_clip_settings()

            assert cfg.clip_auto_retry_failed.value is False

        # Test switching back to True
        with patch("app.ui.views.clip_edit.view.ClipSettingsDialog") as mock_dlg_cls:
            mock_dlg = mock_dlg_cls.return_value
            mock_dlg.exec.return_value = 1  # Accepted
            mock_dlg.result_enable_gpu.return_value = True
            mock_dlg.result_trim_ep1_continued.return_value = True
            mock_dlg.result_auto_select_after_import.return_value = True
            mock_dlg.result_auto_retry_failed.return_value = True
            mock_dlg.result_resolution.return_value = "1280x720"

            page._open_clip_settings()

            assert cfg.clip_auto_retry_failed.value is True

        page.deleteLater()

    def test_open_clip_settings_keeps_admin_max_transcribe(self, qapp):
        # 后台下发的识别集数上限不应被客户端设置弹框覆盖
        page = ClipEditPage()
        qconfig.set(cfg.clip_max_transcribe_episodes, 30)

        with patch("app.ui.views.clip_edit.view.ClipSettingsDialog") as mock_dlg_cls:
            mock_dlg = mock_dlg_cls.return_value
            mock_dlg.exec.return_value = 1  # Accepted
            mock_dlg.result_enable_gpu.return_value = True
            mock_dlg.result_trim_ep1_continued.return_value = False
            mock_dlg.result_auto_select_after_import.return_value = True
            mock_dlg.result_auto_retry_failed.return_value = True
            mock_dlg.result_resolution.return_value = "1280x720"

            page._open_clip_settings()

            assert cfg.clip_max_transcribe_episodes.value == 30

        qconfig.set(cfg.clip_max_transcribe_episodes, 15)
        page.deleteLater()

    def test_delete_project_without_confirmation(self, qapp):
        page = ClipEditPage()
        with patch.object(page.vm, "remove_project") as mock_remove, \
             patch("app.ui.views.clip_edit.view.Dialog") as mock_dialog:
            page._confirm_delete("test-proj-id")
            mock_remove.assert_called_once_with("test-proj-id")
            mock_dialog.assert_not_called()
        page.deleteLater()

    def test_new_user_default_settings(self):
        """验证新用户开箱默认配置符合业务规范。"""
        from app.common.config import Config
        from app.data.services.render_service import RenderService, RENDER_ENGINE_CHOICES

        fresh_cfg = Config()
        # 1. 混合模式策略版本 默认 "v2"
        assert fresh_cfg.plan_mixed_strategy.defaultValue == "v2"
        # 2. 渲染引擎 默认 "v3"（极速模式/三段式分块流复用，推荐）
        assert fresh_cfg.clip_render_engine.defaultValue == "v3"
        assert dict(RENDER_ENGINE_CHOICES).get("v3") == "v3"
        assert RenderService.normalize_render_engine("v3") == "v3"
        assert RenderService.normalize_render_engine("v2") == "current"
        # 3. 去掉未完待续 默认为 开 (True)
        assert fresh_cfg.clip_trim_ep1_continued.defaultValue is True
        # 4. 导入后自动全选 默认为 开 (True)
        assert fresh_cfg.clip_auto_select_after_import.defaultValue is True
        # 5. 流程结束后自动重试失败项 默认为 开 (True)
        assert fresh_cfg.clip_auto_retry_failed.defaultValue is True
        # 6. 叠字预渲染提速 默认为 开 (True)
        assert fresh_cfg.clip_overlay_bake_png.defaultValue is True
        # 7. 显卡加速检测 默认 关 (False)
        assert fresh_cfg.encode_enable_gpu.defaultValue is False
        # 8. 识别集数上限 默认为 15 集
        assert fresh_cfg.clip_max_transcribe_episodes.defaultValue == 15


class TestBatchAllAutoRetry:
    def test_batch_all_auto_retry_flow(self, qapp, monkeypatch):
        from types import SimpleNamespace
        from app.data.models.drama_project import DramaProject
        from app.ui.views.clip_edit.view_model import ClipEditViewModel

        p1 = DramaProject(id="p1", name="剧目1", folder_path="d1", episode_count=1)
        p2 = DramaProject(id="p2", name="剧目2", folder_path="d2", episode_count=1)

        monkeypatch.setattr(
            "app.ui.views.clip_edit.view_model.ClipEditViewModel._load_settings_from_server",
            lambda self: None,
        )

        vm = ClipEditViewModel()
        vm._projects = [p1, p2]

        monkeypatch.setattr(vm, "_ensure_can_plan", lambda *args: True)
        monkeypatch.setattr(vm, "_ensure_can_clip", lambda *args: True)
        monkeypatch.setattr(
            "app.data.services.usage_service.UsageService.report",
            lambda *args, **kwargs: None,
        )
        monkeypatch.setattr(
            "app.data.services.usage_service.UsageService.report_render",
            lambda *args, **kwargs: None,
        )

        def fake_submit_task(fn, on_success=None, on_error=None):
            try:
                res = fn()
                if on_success:
                    on_success(res)
            except Exception as e:
                if on_error:
                    on_error(str(e))

        monkeypatch.setattr("app.core.task_manager.task_manager.submit_task", fake_submit_task)

        def fake_submit_render(project, on_success, on_error, index=1, total=1):
            on_success(SimpleNamespace(total_seconds=0.5, success_count=1, error_count=0))

        monkeypatch.setattr(vm, "_submit_render", fake_submit_render)

        transcribe_calls = []
        def fake_transcribe(proj, **kwargs):
            transcribe_calls.append(proj.id)
            return True

        monkeypatch.setattr(
            "app.data.services.transcription_service.TranscriptionService.transcribe",
            fake_transcribe,
        )

        p2_attempt = [0]
        plan_calls = []
        def fake_plan(proj, **kwargs):
            plan_calls.append(proj.id)
            if proj.id == "p2":
                p2_attempt[0] += 1
                if p2_attempt[0] == 1:
                    raise RuntimeError("模拟策划网络错误")
            return {"status": "ok"}

        monkeypatch.setattr(
            "app.data.services.ai_director_service.AIDirectorService.plan",
            fake_plan,
        )

        messages = []
        vm.messageReceived.connect(lambda msg: messages.append(msg))

        # Case 1: clip_auto_retry_failed 为 True
        qconfig.set(cfg.clip_auto_retry_failed, True)
        vm.batch_all(["p1", "p2"])

        # 验证断点续跑：p2 在第二轮重试时跳过识别（transcribe_calls 仍然只有 2 次）
        assert transcribe_calls == ["p1", "p2"]
        # 策划在第二轮重试了 p2（总共 3 次策划：p1, p2, p2）
        assert plan_calls == ["p1", "p2", "p2"]
        # 最终 summary 应该成功 2 部，失败 0 部
        assert vm._current_batch_summary is not None
        assert vm._current_batch_summary.success_count == 2
        assert vm._current_batch_summary.fail_count == 0
        assert any("正在自动重新执行失败项" in m for m in messages)
        assert any("含自动重试" in m for m in messages)

        # Case 2: clip_auto_retry_failed 为 False 时不重试
        transcribe_calls.clear()
        plan_calls.clear()
        p2_attempt[0] = 0
        messages.clear()
        qconfig.set(cfg.clip_auto_retry_failed, False)

        vm.batch_all(["p1", "p2"])
        assert transcribe_calls == ["p1", "p2"]
        assert plan_calls == ["p1", "p2"]
        assert vm._current_batch_summary.success_count == 1
        assert vm._current_batch_summary.fail_count == 1
        assert not any("正在自动重新执行失败项" in m for m in messages)


def test_transcription_service_max_episodes_truncation(tmp_path, monkeypatch):
    import os
    from unittest.mock import MagicMock
    from app.data.models.drama_project import DramaProject
    from app.data.services.transcription_service import TranscriptionService

    folder = tmp_path / "drama_20_eps"
    folder.mkdir()
    for i in range(1, 21):
        (folder / f"ep_{i:02d}.mp4").write_bytes(b"dummy")

    project = DramaProject(id="p_test", name="20集剧目", folder_path=str(folder), episode_count=20)

    generated_inputs = []
    mock_model = MagicMock()

    def fake_generate(**kwargs):
        generated_inputs.append(kwargs.get("input"))
        return [{"words": ["你好"], "timestamp": [[0, 500]]}]

    mock_model.generate = fake_generate

    monkeypatch.setattr(TranscriptionService, "init_model", lambda: None)
    monkeypatch.setattr(TranscriptionService, "_model", mock_model)
    monkeypatch.setattr(TranscriptionService, "_torch", MagicMock())

    # 1. 指定 max_episodes=5，应只识别前 5 集
    TranscriptionService.transcribe(project, max_episodes=5)
    assert len(generated_inputs) == 5
    assert os.path.basename(generated_inputs[0]) == "ep_01.mp4"
    assert os.path.basename(generated_inputs[4]) == "ep_05.mp4"

    # 2. 缺省使用 cfg.clip_max_transcribe_episodes (例如 8)
    generated_inputs.clear()
    qconfig.set(cfg.clip_max_transcribe_episodes, 8)
    TranscriptionService.transcribe(project)
    assert len(generated_inputs) == 8
    assert os.path.basename(generated_inputs[7]) == "ep_08.mp4"

    # 还原
    qconfig.set(cfg.clip_max_transcribe_episodes, 15)

