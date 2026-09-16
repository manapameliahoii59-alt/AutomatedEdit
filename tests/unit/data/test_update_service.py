import pytest

from app.data.services import update_service


def test_fetch_update_info_when_up_to_date(mocker):
    mocker.patch("app.data.services.update_service.VERSION", "0.0.2")
    mocker.patch(
        "app.data.services.update_service.get_api",
        return_value=mocker.Mock(
            fetch_client_version=lambda: {
                "latest": "0.0.2",
                "min_supported": "0.0.1",
                "download_url": "https://x/setup.exe",
            }
        ),
    )
    assert update_service.fetch_update_info() is None


def test_fetch_update_info_when_update_available(mocker):
    mocker.patch("app.data.services.update_service.VERSION", "0.0.1")
    mocker.patch(
        "app.data.services.update_service.get_api",
        return_value=mocker.Mock(
            fetch_client_version=lambda: {
                "latest": "0.0.2",
                "min_supported": "0.0.1",
                "download_url": "https://x/setup.exe",
                "changelog": "修复问题",
            }
        ),
    )
    info = update_service.fetch_update_info()
    assert info is not None
    assert info.latest == "0.0.2"
    assert info.force is False


def test_fetch_update_info_force_when_below_min_supported(mocker):
    mocker.patch("app.data.services.update_service.VERSION", "0.0.1")
    mocker.patch(
        "app.data.services.update_service.get_api",
        return_value=mocker.Mock(
            fetch_client_version=lambda: {
                "latest": "0.2.0",
                "min_supported": "0.2.0",
                "download_url": "https://x/setup.exe",
            }
        ),
    )
    info = update_service.fetch_update_info()
    assert info is not None
    assert info.force is True


def test_should_prompt_update_respects_dismissed(mocker):
    mocker.patch("app.data.services.update_service.cfg")
    from app.data.services.update_service import cfg

    cfg.update_dismissed_version.value = "0.0.2"
    info = update_service.UpdateInfo(
        latest="0.0.2",
        min_supported="0.0.1",
        download_url="https://x/setup.exe",
        changelog="",
        force=False,
    )
    assert update_service.should_prompt_update(info) is False


def test_installer_filename_from_url():
    assert (
        update_service._installer_filename(
            "https://cdn.example/path/%E5%89%AA%E8%BE%91%E5%8A%A9%E6%89%8B-v0.0.2-installer.exe",
            "0.0.2",
        )
        == "剪辑助手-v0.0.2-installer.exe"
    )


def test_installer_filename_fallback():
    assert (
        update_service._installer_filename("https://cdn.example/download", "1.2.3")
        == "剪辑助手-v1.2.3-installer.exe"
    )


def test_download_update_installer(mocker, tmp_path):
    class FakeResp:
        headers = {"content-length": "4"}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=0):
            yield b"abcd"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    mocker.patch("app.data.services.update_service.requests.get", return_value=FakeResp())
    mocker.patch(
        "app.data.services.update_service.tempfile.gettempdir",
        return_value=str(tmp_path),
    )
    progress = []
    path = update_service.download_update_installer(
        "https://x/setup.exe",
        version="0.0.2",
        progress_callback=lambda d, t: progress.append((d, t)),
    )
    assert path.exists()
    assert path.read_bytes() == b"abcd"
    assert progress == [(4, 4)]


def test_check_mandatory_update_on_startup_when_no_update(mocker):
    mocker.patch("app.data.services.update_service.fetch_update_info", return_value=None)
    assert update_service.check_mandatory_update_on_startup() is False


def test_check_mandatory_update_on_startup_when_not_force(mocker):
    info = update_service.UpdateInfo(
        latest="0.0.2",
        min_supported="0.0.1",
        download_url="https://x/setup.exe",
        changelog="",
        force=False,
    )
    mocker.patch("app.data.services.update_service.fetch_update_info", return_value=info)
    assert update_service.check_mandatory_update_on_startup() is False


def test_check_mandatory_update_on_startup_blocks_and_exits(mocker, qapp):
    info = update_service.UpdateInfo(
        latest="0.0.2",
        min_supported="0.0.2",
        download_url="https://x/setup.exe",
        changelog="",
        force=True,
    )
    mocker.patch("app.data.services.update_service.fetch_update_info", return_value=info)
    mocker.patch.object(update_service.ForcedUpdateDialog, "exec", return_value=0)
    mock_exit = mocker.patch("sys.exit")

    blocked_called = []
    update_service.check_mandatory_update_on_startup(
        on_blocked=lambda: blocked_called.append(True)
    )

    assert blocked_called == [True]
    assert mock_exit.called


def test_forced_update_dialog_blocks_esc(mocker, qapp):
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent, Qt

    info = update_service.UpdateInfo(
        latest="0.0.2",
        min_supported="0.0.2",
        download_url="",
        changelog="必须更新",
        force=True,
    )
    dialog = update_service.ForcedUpdateDialog(info)
    mock_exit = mocker.patch("sys.exit")

    # 按 ESC 必须被忽略且不关闭
    esc_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    dialog.keyPressEvent(esc_event)
    assert not esc_event.isAccepted()

