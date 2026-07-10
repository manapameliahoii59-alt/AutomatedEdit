import os

import pytest

from app.common import drama_artifact_paths as paths


class TestDramaArtifactPaths:
    def test_dev_writes_to_project_root(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "is_dev_runtime", lambda: True)
        project = str(tmp_path)

        script = paths.script_data_write_path(project)
        plan = paths.production_plan_write_path(project)

        assert script == os.path.join(project, "full_script_data.json")
        assert plan == os.path.join(project, "production_plan_v3.json")

    def test_production_writes_to_hidden_dir(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "is_dev_runtime", lambda: False)
        project = str(tmp_path)

        script = paths.script_data_write_path(project)
        plan = paths.production_plan_write_path(project)

        assert script == os.path.join(project, ".automatededit", "full_script_data.json")
        assert plan == os.path.join(project, ".automatededit", "production_plan_v3.json")

    def test_locate_prefers_hidden_then_legacy(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "is_dev_runtime", lambda: False)
        project = tmp_path
        legacy = project / "full_script_data.json"
        hidden = project / ".automatededit" / "full_script_data.json"

        legacy.write_text("legacy", encoding="utf-8")
        assert paths.locate_script_data(str(project)) == str(legacy)

        hidden.parent.mkdir()
        hidden.write_text("hidden", encoding="utf-8")
        assert paths.locate_script_data(str(project)) == str(hidden)

    def test_prepare_write_path_creates_hidden_dir(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "is_dev_runtime", lambda: False)
        project = str(tmp_path)

        out = paths.prepare_write_path(project, script=True)
        assert os.path.isdir(os.path.join(project, ".automatededit"))
        assert out.endswith(os.path.join(".automatededit", "full_script_data.json"))

    @pytest.mark.skipif(os.name != "nt", reason="Windows hidden attribute")
    def test_finalize_sets_hidden_on_windows(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "is_dev_runtime", lambda: False)
        project = tmp_path
        hidden_dir = project / ".automatededit"
        hidden_dir.mkdir()
        target = hidden_dir / "full_script_data.json"
        target.write_text("{}", encoding="utf-8")

        paths.finalize_written_artifact(str(target))

        import ctypes

        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(target))
        assert attrs != -1
        assert attrs & 0x02
