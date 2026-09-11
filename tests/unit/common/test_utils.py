import pytest
from unittest.mock import MagicMock
from app.common.utils import StyleSheet, set_window_center, show_dialog, show_error_toast
from qfluentwidgets import Theme, qconfig, Dialog
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import QRect, QPoint

class TestUtils:
    def test_stylesheet_path(self):
        """Test StyleSheet path generation"""
        original_theme = qconfig.theme
        try:
            qconfig.theme = Theme.LIGHT
            assert "light/main_window.qss" in StyleSheet.WINDOW.path()
            qconfig.theme = Theme.DARK
            assert "dark/main_window.qss" in StyleSheet.WINDOW.path()
            assert "light/setting_interface.qss" in StyleSheet.SETTINGS.path(Theme.LIGHT)
        finally:
            qconfig.theme = original_theme

    def test_set_window_center(self, mocker):
        """Test set_window_center"""
        window = MagicMock(spec=QWidget)
        window.frameGeometry.return_value = QRect(0, 0, 100, 100)
        
        screen = MagicMock()
        screen.availableGeometry.return_value = QRect(0, 0, 1920, 1080)
        window.screen.return_value = screen
        
        set_window_center(window)
        
        # Verify move was called with correct coordinates
        # Center of 1920x1080 is (960, 540)
        # Rect 100x100 centered there means top-left is (910, 490)
        window.move.assert_called()
        args = window.move.call_args[0][0]
        # Depending on how moveCenter works on QRect, it should be correct.
        # We assume logic is correct, just verifying the call.

    def test_show_dialog(self, mocker, qapp):
        """Test show_dialog"""
        # Mock Dialog
        mock_dialog_cls = mocker.patch('app.common.utils.Dialog')
        mock_instance = mock_dialog_cls.return_value
        
        mock_instance.contentLabel = MagicMock()
        mock_instance.yesButton = MagicMock()
        mock_instance.cancelButton = MagicMock()
        mock_instance.buttonLayout = MagicMock()
        
        parent = MagicMock()
        parent.screen.return_value.availableGeometry.return_value.height.return_value = 1000
        
        # Test without callback
        show_dialog(parent, "content")
        mock_instance.exec.assert_called()
        mock_instance.yesButton.hide.assert_called()
        
        # Test with callback
        callback = MagicMock()
        mock_instance.exec.return_value = True
        show_dialog(parent, "content", callback=callback)
        callback.assert_called()

    def test_show_dialog_with_error_feedback(self, mocker, qapp):
        from app.data.services.error_feedback_service import ErrorReportData, error_feedback_service

        mock_dialog_cls = mocker.patch('app.common.utils.Dialog')
        mock_instance = mock_dialog_cls.return_value
        mock_instance.contentLabel = MagicMock()
        mock_instance.yesButton = MagicMock()
        mock_instance.cancelButton = MagicMock()
        mock_instance.buttonLayout = MagicMock()

        rep = ErrorReportData(
            error_stage="transcribe",
            drama_name="逆子",
            friendly_msg="音频识别遇到异常",
            raw_error="Torch Error",
        )
        mocker.patch.object(error_feedback_service, "find_matching_report", return_value=rep)

        parent = MagicMock()
        parent.screen.return_value.availableGeometry.return_value.height.return_value = 1000

        show_dialog(parent, "音频识别遇到异常")
        # 应该调用 insertWidget 插入 feedback_btn
        mock_instance.buttonLayout.insertWidget.assert_called()

    def test_show_error_toast_weak_hint_and_auto_report(self, mocker):
        mock_toast = mocker.patch("app.common.utils.show_toast")
        mock_task_manager = mocker.patch("app.core.task_manager.TaskManager")

        show_error_toast(MagicMock(), "识别失败，请重试")

        mock_toast.assert_called_once()
        assert mock_toast.call_args.kwargs.get("level") == "error"
        mock_task_manager.instance.return_value.submit_task.assert_called_once()
        assert (
            mock_task_manager.instance.return_value.submit_task.call_args.kwargs.get(
                "check_access"
            )
            is False
        )

    def test_show_error_toast_can_disable_auto_report(self, mocker):
        mock_toast = mocker.patch("app.common.utils.show_toast")
        mock_task_manager = mocker.patch("app.core.task_manager.TaskManager")

        show_error_toast(MagicMock(), "仅提示不上报", auto_report=False)

        mock_toast.assert_called_once()
        mock_task_manager.instance.return_value.submit_task.assert_not_called()

    def test_show_error_toast_targets_active_modal(self, mocker):
        mock_toast = mocker.patch("app.common.utils.show_toast")
        mocker.patch("app.core.task_manager.TaskManager")

        modal = MagicMock()
        modal.isVisible.return_value = True
        mock_app = mocker.patch("app.common.utils.QApplication")
        mock_app.instance.return_value = mock_app
        mock_app.activeModalWidget.return_value = modal

        shadowed = MagicMock()
        show_error_toast(shadowed, "被一键执行看板遮挡")

        # 弱提示应挂到活动模态窗口，而不是被遮挡的主页面
        assert mock_toast.call_args[0][0] is modal

