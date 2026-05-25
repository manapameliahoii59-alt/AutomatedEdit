from dataclasses import dataclass, field
from enum import Enum


class DramaStatus(Enum):
    PENDING = "待处理"
    IN_PROGRESS = "处理中"
    DONE = "已完成"


@dataclass
class DramaProject:
    """单部短剧/漫剧的批量处理单元。"""

    id: str
    name: str
    episode_count: int
    folder_path: str = ""
    status: DramaStatus = field(default=DramaStatus.PENDING)

    @property
    def status_label(self) -> str:
        return self.status.value
