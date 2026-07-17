import os

from app.common.ffmpeg_paths import ensure_bundled_ffmpeg_on_path


def test_ensure_bundled_ffmpeg_on_path_prepends_dir(monkeypatch, tmp_path):
    fake_ff = tmp_path / "tools" / "ffmpeg" / "win" / "ffmpeg.exe"
    fake_ff.parent.mkdir(parents=True)
    fake_ff.write_bytes(b"MZ")

    monkeypatch.setattr(
        "app.common.ffmpeg_paths._app_base_dir",
        lambda: tmp_path,
    )
    monkeypatch.setenv("PATH", r"C:\Windows\System32")

    added = ensure_bundled_ffmpeg_on_path()
    assert added == str(fake_ff.parent.resolve())
    path = os.environ["PATH"]
    assert path.split(os.pathsep)[0] == str(fake_ff.parent.resolve())


def test_ensure_bundled_does_not_import_config(monkeypatch, tmp_path):
    """启动早期调用不得触发 qfluentwidgets/PySide6。"""
    fake_ff = tmp_path / "tools" / "ffmpeg" / "win" / "ffmpeg.exe"
    fake_ff.parent.mkdir(parents=True)
    fake_ff.write_bytes(b"MZ")
    monkeypatch.setattr(
        "app.common.ffmpeg_paths._app_base_dir",
        lambda: tmp_path,
    )
    monkeypatch.setenv("PATH", "")

    import builtins
    import sys

    blocked = {"app.common.config", "qfluentwidgets", "PySide6"}
    for name in list(sys.modules):
        if (
            name in blocked
            or name.startswith("PySide6.")
            or name.startswith("qfluentwidgets")
        ):
            sys.modules.pop(name, None)

    real_import = builtins.__import__

    def _guard(name, globals=None, locals=None, fromlist=(), level=0):
        root = name.split(".", 1)[0]
        if name in blocked or root in {"PySide6", "qfluentwidgets"}:
            raise AssertionError(f"early ffmpeg PATH must not import {name}")
        if name == "app.common.config" or name.startswith("app.common.config."):
            raise AssertionError(f"early ffmpeg PATH must not import {name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _guard)
    assert ensure_bundled_ffmpeg_on_path() is not None
