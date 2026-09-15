"""内存日志环形缓冲区：记录最近的运行轨迹，仅在异常打包时加密持久化。"""

from __future__ import annotations

import collections
import threading


class LogRingBuffer:
    _MAX_LINES = 300
    _buffer: collections.deque[str] = collections.deque(maxlen=_MAX_LINES)
    _lock = threading.Lock()

    @classmethod
    def append(cls, line: str) -> None:
        """接收 loguru 写入的单条日志行。"""
        if not line:
            return
        clean_line = line.rstrip("\r\n")
        with cls._lock:
            cls._buffer.append(clean_line)

    @classmethod
    def get_recent_logs(cls, count: int = 200) -> list[str]:
        """获取最近 N 条日志快照。"""
        with cls._lock:
            lines = list(cls._buffer)
        return lines[-count:] if len(lines) > count else lines

    @classmethod
    def clear(cls) -> None:
        """清空缓冲区（主要用于测试）。"""
        with cls._lock:
            cls._buffer.clear()


def loguru_ring_sink(message) -> None:
    """Loguru sink 回调函数。"""
    try:
        LogRingBuffer.append(str(message))
    except Exception:
        pass
