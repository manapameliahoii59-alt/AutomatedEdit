"""机器信息采集模块单元测试（Windows 原生采集，mock 掉外部调用）。"""

from app.common import machine_info as mi


class TestHelpers:
    def test_to_int(self):
        assert mi._to_int("12.0") == 12
        assert mi._to_int(None) == 0
        assert mi._to_int("bad") == 0

    def test_vendor_from_name(self):
        assert mi._vendor_from_name("NVIDIA GeForce RTX 3060") == "NVIDIA"
        assert mi._vendor_from_name("AMD Radeon RX 6800") == "AMD"
        assert mi._vendor_from_name("Intel(R) UHD Graphics") == "Intel"
        assert mi._vendor_from_name("Virtual Display") == ""

    def test_is_virtual_display(self):
        assert mi._is_virtual_display("GameViewer Virtual Display Adapter")
        assert mi._is_virtual_display("Microsoft Basic Display Adapter")
        assert not mi._is_virtual_display("AMD Radeon RX 5600 XT")


class TestNvidiaGpus:
    def test_parses_nvidia_smi_output(self, monkeypatch):
        class _Proc:
            returncode = 0
            stdout = "NVIDIA GeForce RTX 3060, 12288, 551.23\nNVIDIA GeForce GTX 1650, 4096, 551.23\n"

        monkeypatch.setattr(mi, "win_run", lambda *a, **k: _Proc())
        gpus = mi._nvidia_gpus()
        assert len(gpus) == 2
        assert gpus[0]["name"] == "NVIDIA GeForce RTX 3060"
        assert gpus[0]["vram_mb"] == 12288
        assert gpus[0]["vendor"] == "NVIDIA"
        assert gpus[1]["vram_mb"] == 4096

    def test_returns_empty_on_failure(self, monkeypatch):
        class _Proc:
            returncode = 1
            stdout = ""

        monkeypatch.setattr(mi, "win_run", lambda *a, **k: _Proc())
        assert mi._nvidia_gpus() == []


class TestCollectMachineInfo:
    def test_collect_returns_expected_fields(self, monkeypatch):
        monkeypatch.setattr(mi, "_cpu_name", lambda: "Test CPU")
        monkeypatch.setattr(mi, "_physical_cores", lambda: 8)
        monkeypatch.setattr(mi, "_memory_mb", lambda: (16384, 8192))
        monkeypatch.setattr(
            mi,
            "_collect_gpus",
            lambda: [{"name": "NVIDIA RTX 3060", "vendor": "NVIDIA", "vram_mb": 12288, "driver": "1"}],
        )

        info = mi.collect_machine_info()
        assert info["cpu_name"] == "Test CPU"
        assert info["cpu_cores_physical"] == 8
        assert info["ram_total_mb"] == 16384
        assert info["ram_available_mb"] == 8192
        assert info["gpu_summary"] == "NVIDIA RTX 3060"
        assert info["client_version"]
        assert set(info) >= {
            "os",
            "hostname",
            "cpu_name",
            "cpu_cores_logical",
            "cpu_cores_physical",
            "ram_total_mb",
            "ram_available_mb",
            "gpus",
            "gpu_summary",
            "client_version",
        }

    def test_windows_gpus_returns_empty_on_bad_output(self, monkeypatch):
        class _Proc:
            returncode = 0
            stdout = "not-json"

        monkeypatch.setattr(mi, "win_run", lambda *a, **k: _Proc())
        assert mi._windows_gpus() == []

    def test_windows_gpus_filters_virtual_adapters(self, monkeypatch):
        class _Proc:
            returncode = 0
            stdout = (
                '[{"Name":"GameViewer Virtual Display Adapter","AdapterRAM":null},'
                '{"Name":"AMD Radeon RX 5600 XT","AdapterRAM":4293918720}]'
            )

        monkeypatch.setattr(mi, "win_run", lambda *a, **k: _Proc())
        gpus = mi._windows_gpus()
        assert len(gpus) == 1
        assert gpus[0]["name"] == "AMD Radeon RX 5600 XT"
        assert gpus[0]["vendor"] == "AMD"
