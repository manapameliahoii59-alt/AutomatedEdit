import pytest
import time
from app.common.aes import aes_encrypt, aes_decrypt
from app.core.task_manager import TaskManager

class TestPerformance:
    def test_aes_benchmark(self):
        """Benchmark AES encryption"""
        # benchmark fixture comes from pytest-benchmark if installed, 
        # but user didn't ask for pytest-benchmark specifically, just 'performance tests'.
        # If pytest-benchmark is not available, we can write a manual timing test.
        # Since I didn't install pytest-benchmark, I will do manual timing.
        
        data = "x" * 1024 * 10 # 10KB
        
        start = time.time()
        iterations = 1000
        for _ in range(iterations):
            enc = aes_encrypt(data)
            _ = aes_decrypt(enc)
        end = time.time()
        
        duration = end - start
        avg_time = duration / iterations
        print(f"\nAES Encrypt/Decrypt 10KB: {avg_time*1000:.4f} ms/op")
        
        # Simple assertion to ensure it's not super slow (e.g. < 10ms per op)
        assert avg_time < 0.01

    def test_task_manager_load(self, qtbot):
        """Load test for TaskManager"""
        tm = TaskManager.instance()
        task_count = 100
        completed_count = 0
        
        def task():
            return 1
            
        def on_success(res):
            nonlocal completed_count
            completed_count += res
            
        start = time.time()
        for _ in range(task_count):
            tm.submit_task(task, on_success=on_success)
            
        # Wait for all to finish
        qtbot.waitUntil(lambda: completed_count == task_count, timeout=5000)
        end = time.time()
        
        print(f"\nTaskManager processed {task_count} tasks in {end-start:.4f}s")
