"""Tests for Windows silent subprocess helper."""

import subprocess
import sys

from app.common.win_subprocess import install_silent_subprocess, subprocess_kwargs


def test_subprocess_kwargs_sets_create_no_window_on_win32():
    kwargs = subprocess_kwargs(capture_output=True)
    assert kwargs["capture_output"] is True
    if sys.platform == "win32":
        assert kwargs["creationflags"] & 0x08000000
    else:
        assert "creationflags" not in kwargs


def test_install_silent_subprocess_patches_popen_on_win32():
    if sys.platform != "win32":
        return
    install_silent_subprocess()
    assert subprocess.Popen.__name__ == "_SilentPopen"
