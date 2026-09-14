"""机器信息上报服务单元测试（每天最多一次，失败不写日期）。"""

import datetime

import app.data.services.machine_info_service as mod
from app.data.api.api import ApiError


class _FakeItem:
    def __init__(self, value: str = ""):
        self.value = value


class _FakeCfg:
    def __init__(self, value: str = ""):
        self.machine_info_reported_date = _FakeItem(value)


class _RecordingQConfig:
    def __init__(self):
        self.marked = {}

    def set(self, item, value):
        self.marked["value"] = value


class TestReportDaily:
    def test_skips_when_already_reported_today(self, monkeypatch):
        today = datetime.date.today().isoformat()
        monkeypatch.setattr(mod, "cfg", _FakeCfg(today))
        collected = {"n": 0}

        def _collect():
            collected["n"] += 1
            return {}

        monkeypatch.setattr(mod, "collect_machine_info", _collect)
        mod.MachineInfoService._run()
        assert collected["n"] == 0

    def test_reports_and_marks_date_on_success(self, monkeypatch):
        today = datetime.date.today().isoformat()
        monkeypatch.setattr(mod, "cfg", _FakeCfg(""))
        monkeypatch.setattr(mod, "collect_machine_info", lambda: {"cpu_name": "X"})
        posted = {}

        class _Api:
            def report_machine_info(self, payload):
                posted.update(payload)

        monkeypatch.setattr(mod, "get_api", lambda: _Api())
        recorder = _RecordingQConfig()
        monkeypatch.setattr(mod, "qconfig", recorder)

        mod.MachineInfoService._run()

        assert posted == {"cpu_name": "X"}
        assert recorder.marked["value"] == today

    def test_does_not_mark_date_on_api_error(self, monkeypatch):
        monkeypatch.setattr(mod, "cfg", _FakeCfg(""))
        monkeypatch.setattr(mod, "collect_machine_info", lambda: {})

        class _Api:
            def report_machine_info(self, payload):
                raise ApiError("boom")

        monkeypatch.setattr(mod, "get_api", lambda: _Api())
        recorder = _RecordingQConfig()
        monkeypatch.setattr(mod, "qconfig", recorder)

        mod.MachineInfoService._run()

        assert "value" not in recorder.marked
