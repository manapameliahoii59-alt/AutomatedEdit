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
