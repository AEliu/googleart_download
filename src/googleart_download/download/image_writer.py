from __future__ import annotations

import io
import re
from pathlib import Path

from PIL import Image

from ..models import ArtworkMetadata, TileInfo
from ..metadata.output import build_exif_bytes


def sanitize_filename(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    return name[:180] or "google-art"


def resolve_output_path(output_dir: Path, filename: str | None, title: str) -> Path:
    if filename:
        return output_dir / filename
    return output_dir / f"{sanitize_filename(title)}.jpg"


def stitch_tiles(
    tile_info: TileInfo,
    tiles: dict[tuple[int, int], bytes],
    output_path: Path,
    metadata: ArtworkMetadata | None = None,
    write_metadata: bool = False,
) -> None:
    image = Image.new("RGB", (tile_info.image_width, tile_info.image_height))
    level = tile_info.highest_level

    for y in range(level.num_tiles_y):
        for x in range(level.num_tiles_x):
            tile = Image.open(io.BytesIO(tiles[(x, y)]))
            tile.load()
            left = x * tile_info.tile_width
            top = y * tile_info.tile_height
            right = min(left + tile.width, tile_info.image_width)
            bottom = min(top + tile.height, tile_info.image_height)
            cropped = tile.crop((0, 0, right - left, bottom - top))
            image.paste(cropped, (left, top))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if write_metadata and metadata is not None:
        exif_bytes = build_exif_bytes(metadata)
        image.save(output_path, quality=95, exif=exif_bytes)
    else:
        image.save(output_path, quality=95)
