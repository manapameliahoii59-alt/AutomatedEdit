"""批量任务执行计时与耗时记录模型。"""

from __future__ import annotations

from dataclasses import dataclass, field


def format_duration(seconds: float) -> str:
    """人性化耗时格式化。"""
    if seconds <= 0:
        return "0.0 秒"
    if seconds < 60:
        return f"{seconds:.1f} 秒"
    minutes, secs = divmod(int(seconds), 60)
    if minutes < 60:
        remainder = seconds - int(seconds)
        if remainder > 0.05:
            return f"{minutes} 分 {secs + remainder:.1f} 秒"
        return f"{minutes} 分 {secs} 秒"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小时 {minutes} 分 {secs} 秒"


def format_duration_short(seconds: float) -> str:
    """简短表格耗时格式化（如 15.2s、1m 15s）。"""
    if seconds <= 0:
        return "-"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m {secs}s"


@dataclass
class DramaTimingRecord:
    project_id: str
    project_name: str
    episode_count: int = 0
    # 各阶段耗时（秒）
    transcribe_time: float = 0.0
    plan_time: float = 0.0
    render_time: float = 0.0
    # 各阶段状态：pending / in_progress / done / failed / cancelled / skipped
    transcribe_status: str = "pending"
    plan_status: str = "pending"
    render_status: str = "pending"
    error_msg: str = ""

    @property
    def total_time(self) -> float:
        return self.transcribe_time + self.plan_time + self.render_time

    def is_success(self, task_type: str) -> bool:
        if task_type == "transcribe":
            return self.transcribe_status == "done"
        if task_type == "plan":
            return self.plan_status == "done"
        if task_type == "render":
            return self.render_status == "done"
        # task_type == "all"
        return (
            self.transcribe_status == "done"
            and self.plan_status == "done"
            and self.render_status == "done"
        )


@dataclass
class BatchExecutionSummary:
    task_type: str  # "transcribe" | "plan" | "render" | "all"
    records: list[DramaTimingRecord] = field(default_factory=list)
    total_elapsed: float = 0.0
    is_cancelled: bool = False

    @property
    def total_count(self) -> int:
        return len(self.records)

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.records if r.is_success(self.task_type))

    @property
    def fail_count(self) -> int:
        return sum(
            1
            for r in self.records
            if not r.is_success(self.task_type)
            and not self.is_cancelled
            and (
                r.transcribe_status == "failed"
                or r.plan_status == "failed"
                or r.render_status == "failed"
                or bool(r.error_msg)
            )
        )

    @property
    def task_name(self) -> str:
        names = {
            "transcribe": "批量识别",
            "plan": "批量策划",
            "render": "批量渲染",
            "all": "一键执行",
        }
        return names.get(self.task_type, "批量任务")
