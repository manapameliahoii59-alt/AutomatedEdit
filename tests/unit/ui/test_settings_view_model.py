import pytest
from app.ui.views.settings.view_model import SettingsViewModel

class TestSettingsViewModel:
    def test_init(self, qapp):
        vm = SettingsViewModel()
        assert vm is not None

    def test_invite_signals(self, qapp, qtbot, mocker):
        vm = SettingsViewModel()
        mock_api = mocker.patch("app.data.api.api.get_api")
        mock_api.return_value.fetch_invite_info.return_value = {
            "invite_code": "TEST66",
            "has_used_invite": False,
            "current_reward_per_invite": 5,
        }
        mock_api.return_value.bind_invite_code.return_value = {
            "ok": True,
            "reward": 5,
            "message": "兑换成功",
        }

        with qtbot.waitSignal(vm.inviteInfoLoaded, timeout=2000) as blocker:
            vm.load_invite_info()
        assert blocker.args[0]["invite_code"] == "TEST66"

        with qtbot.waitSignal(vm.inviteBindFinished, timeout=2000) as blocker:
            vm.bind_invite_code("TEST66")
        assert blocker.args[0] is True
        assert "兑换成功" in blocker.args[1]

