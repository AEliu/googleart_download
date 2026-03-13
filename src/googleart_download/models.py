from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


@dataclass(frozen=True)
class PageInfo:
    title: str
    base_url: str
    token: str
    metadata: "ArtworkMetadata | None" = None

    @property
    def path(self) -> str:
        return self.base_url.split("/", 3)[3]

    @property
    def tile_info_url(self) -> str:
        return f"{self.base_url}=g"


@dataclass(frozen=True)
class PyramidLevel:
    z: int
    num_tiles_x: int
    num_tiles_y: int
    empty_pels_x: int
    empty_pels_y: int


@dataclass(frozen=True)
class TileInfo:
    tile_width: int
    tile_height: int
    levels: list[PyramidLevel]

    @property
    def highest_level(self) -> PyramidLevel:
        return self.levels[-1]

    @property
    def image_width(self) -> int:
        level = self.highest_level
        return self.tile_width * level.num_tiles_x - level.empty_pels_x

    @property
    def image_height(self) -> int:
        level = self.highest_level
        return self.tile_height * level.num_tiles_y - level.empty_pels_y


@dataclass(frozen=True)
class TileJob:
    x: int
    y: int
    url: str


@dataclass(frozen=True)
class ArtworkContext:
    index: int
    total: int
    url: str
    page: PageInfo
    tile_info: TileInfo
    output_path: Path


@dataclass(frozen=True)
class DownloadResult:
    url: str
    output_path: Path
    title: str
    size: tuple[int, int] | None
    tile_count: int | None
    skipped: bool = False
    sidecar_path: Path | None = None


@dataclass(frozen=True)
class RetryConfig:
    attempts: int = 3
    backoff_base_seconds: float = 0.75
    backoff_multiplier: float = 2.0
    retry_http_statuses: tuple[int, ...] = (408, 425, 429, 500, 502, 503, 504)


@dataclass(frozen=True)
class ArtworkMetadata:
    title: str | None = None
    creator: str | None = None
    description: str | None = None
    source_url: str | None = None
    date_created: str | None = None
    rights: str | None = None
    external_link: str | None = None
    partner: str | None = None


class TaskState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SKIPPED = "skipped"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class BatchTask:
    index: int
    url: str
    state: TaskState
    result: DownloadResult | None = None
    error: str | None = None


@dataclass(frozen=True)
class BatchSnapshot:
    tasks: list[BatchTask]

    @property
    def total(self) -> int:
        return len(self.tasks)

    @property
    def pending(self) -> int:
        return sum(task.state == TaskState.PENDING for task in self.tasks)

    @property
    def running(self) -> int:
        return sum(task.state == TaskState.RUNNING for task in self.tasks)

    @property
    def succeeded(self) -> int:
        return sum(task.state == TaskState.SUCCEEDED for task in self.tasks)

    @property
    def skipped(self) -> int:
        return sum(task.state == TaskState.SKIPPED for task in self.tasks)

    @property
    def failed(self) -> int:
        return sum(task.state == TaskState.FAILED for task in self.tasks)


@dataclass(frozen=True)
class BatchRunResult:
    snapshot: BatchSnapshot
    succeeded: list[DownloadResult]
    failed: list[BatchTask]
