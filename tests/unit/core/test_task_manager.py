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
