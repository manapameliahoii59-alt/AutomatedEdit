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
