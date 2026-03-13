from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PageInfo:
    title: str
    base_url: str
    token: str

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
    size: tuple[int, int]
    tile_count: int
