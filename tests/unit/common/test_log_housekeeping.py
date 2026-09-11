"""本地日志清理（log_housekeeping）单元测试。"""

import os
import time

from app.common.log_housekeeping import run_daily_log_cleanup


def _write(path, content=b"x"):
    with open(path, "wb") as f:
        f.write(content)


def test_deletes_old_logs_keeps_recent(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    old = logs / "v0.0.1.log"
    recent = logs / "v0.0.14.log"
    _write(old)
    _write(recent)

    old_time = time.time() - 10 * 86400
    os.utime(old, (old_time, old_time))

    assert run_daily_log_cleanup(str(tmp_path), force=True) is True
    assert not old.exists()
    assert recent.exists()


def test_trims_oversized_crash_log_keeping_tail(tmp_path):
    crash = tmp_path / "crash.log"
    _write(crash, b"A" * 100)

    run_daily_log_cleanup(str(tmp_path), max_crash_bytes=10, keep_bytes=5, force=True)

    assert crash.read_bytes() == b"A" * 5


def test_daily_marker_skips_repeat_until_forced(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    old_time = time.time() - 30 * 86400

    old = logs / "old.log"
    _write(old)
    os.utime(old, (old_time, old_time))
    assert run_daily_log_cleanup(str(tmp_path)) is True
    assert not old.exists()

    # 同一天再次调用应跳过每日清理
    again = logs / "old2.log"
    _write(again)
    os.utime(again, (old_time, old_time))
    assert run_daily_log_cleanup(str(tmp_path)) is False
    assert again.exists()

    # force 可强制清理
    assert run_daily_log_cleanup(str(tmp_path), force=True) is True
    assert not again.exists()
