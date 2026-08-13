import pytest
from PySide6.QtCore import QThreadPool
import time
from app.core.task_manager import TaskManager, TaskRunnable

class TestTaskManager:
    def test_singleton(self, qapp):
        """Test that TaskManager is a singleton"""
        tm1 = TaskManager.instance()
        tm2 = TaskManager.instance()
        assert tm1 is tm2

    def test_submit_task_success(self, qtbot):
        """Test submitting a task that succeeds"""
        tm = TaskManager.instance()
        
        def success_task(a, b):
            return a + b
            
        result_container = []
        
        def on_success(result):
            result_container.append(result)
            
        # No-op context manager replacement since we can't wait on QThreadPool directly
        pass

        # Using qtbot.waitUntil to wait for the callback side effect
        tm.submit_task(success_task, args=(1, 2), on_success=on_success)
        
        qtbot.waitUntil(lambda: len(result_container) > 0, timeout=1000)
        assert result_container[0] == 3

    def test_callback_survives_runnable_autodelete(self, qtbot):
        """Queued callbacks must still fire after QRunnable AutoDelete."""
        tm = TaskManager.instance()
        results = []

        def work():
            time.sleep(0.05)
            return "ok"

        def on_success(result):
            # Allow the runnable to be auto-deleted before this runs.
            time.sleep(0.05)
            results.append(result)

        tm.submit_task(work, on_success=on_success)
        qtbot.waitUntil(lambda: len(results) == 1, timeout=2000)
        assert results[0] == "ok"
        qtbot.waitUntil(lambda: len(tm._live_signals) == 0, timeout=1000)

    def test_submit_task_error(self, qtbot):
        """Test submitting a task that raises an exception"""
        tm = TaskManager.instance()
        
        def error_task():
            raise ValueError("Test Error")
            
        error_container = []
        
        def on_error(err):
            error_container.append(err)
            
        tm.submit_task(error_task, on_error=on_error)
        
        qtbot.waitUntil(lambda: len(error_container) > 0, timeout=1000)
        assert "Test Error" in error_container[0]

    def test_concurrency(self, qtbot):
        """Test running multiple tasks concurrently"""
        tm = TaskManager.instance()
        
        # Ensure we have enough threads
        max_threads = QThreadPool.globalInstance().maxThreadCount()
        if max_threads < 2:
            pytest.skip("Not enough threads for concurrency test")
            
        results = []
        
        def slow_task(idx):
            time.sleep(0.1)
            return idx
            
        def on_success(res):
            results.append(res)
            
        # Submit 2 tasks
        tm.submit_task(slow_task, args=(1,), on_success=on_success)
        tm.submit_task(slow_task, args=(2,), on_success=on_success)
        
        qtbot.waitUntil(lambda: len(results) == 2, timeout=2000)
        assert 1 in results
        assert 2 in results

    def test_check_access_false_allows_login_while_blocked(self, qtbot, mocker):
        """封禁状态下登录任务仍应执行（不能被随机错误拦死）。"""
        from app.data.services.access_control_service import access_control

        tm = TaskManager.instance()
        access_control.block()
        mocker.patch.object(access_control, "refresh", return_value=False)
        results = []
        errors = []

        def login_like():
            return "logged-in"

        tm.submit_task(
            login_like,
            on_success=results.append,
            on_error=errors.append,
            check_access=False,
        )
        qtbot.waitUntil(lambda: len(results) + len(errors) > 0, timeout=1000)
        assert results == ["logged-in"]
        assert errors == []
        access_control.unblock()
