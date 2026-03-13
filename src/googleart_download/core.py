from __future__ import annotations

import base64
import hashlib
import hmac
import io
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree

from Crypto.Cipher import AES
from PIL import Image

from .constants import AES_IV, AES_KEY, ENCRYPTION_MARKER, REQUEST_TIMEOUT, SIGNING_KEY, USER_AGENT
from .errors import DownloadError
from .logging_utils import get_logger
from .models import ArtworkContext, DownloadResult, PageInfo, PyramidLevel, TileInfo, TileJob
from .reporters import Reporter


def fetch_bytes(url: str, timeout: int = REQUEST_TIMEOUT) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise DownloadError(f"request failed: {url} -> HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise DownloadError(f"request failed: {url} -> {exc.reason}") from exc


def fetch_text(url: str, timeout: int = REQUEST_TIMEOUT) -> str:
    return fetch_bytes(url, timeout=timeout).decode("utf-8", errors="ignore")


def normalize_asset_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme:
        url = f"https://{url.lstrip('/')}"
        parsed = urllib.parse.urlparse(url)

    if parsed.netloc not in {"artsandculture.google.com", "g.co"}:
        raise DownloadError("only Google Arts & Culture asset URLs are supported")

    return url


def html_unescape(text: str) -> str:
    return (
        text.replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )


def parse_page_info(html: str) -> PageInfo:
    title_match = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    title = title_match.group(1).replace("— Google Arts &amp; Culture", "").strip() if title_match else "google-art"
    title = html_unescape(title)

    match = re.search(r']\r?\n?,"(//[a-zA-Z0-9./_\-]+)",(?:"([^"]+)"|null)', html)
    if not match:
        raise DownloadError("could not find tile base URL in page HTML")

    return PageInfo(
        title=title,
        base_url=f"https:{match.group(1)}",
        token=match.group(2) or "",
    )


def parse_tile_info(xml_data: bytes) -> TileInfo:
    root = ElementTree.fromstring(xml_data)
    levels = [
        PyramidLevel(
            z=index,
            num_tiles_x=int(level.attrib["num_tiles_x"]),
            num_tiles_y=int(level.attrib["num_tiles_y"]),
            empty_pels_x=int(level.attrib["empty_pels_x"]),
            empty_pels_y=int(level.attrib["empty_pels_y"]),
        )
        for index, level in enumerate(root.findall("pyramid_level"))
    ]
    if not levels:
        raise DownloadError("tile metadata is missing pyramid levels")

    return TileInfo(
        tile_width=int(root.attrib["tile_width"]),
        tile_height=int(root.attrib["tile_height"]),
        levels=levels,
    )


def build_tile_url(page: PageInfo, x: int, y: int, z: int) -> str:
    suffix = f"=x{x}-y{y}-z{z}-t"
    message = f"{page.path}{suffix}{page.token}".encode("utf-8")
    digest = hmac.new(SIGNING_KEY, message, hashlib.sha1).digest()
    signature = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=").replace("-", "_")
    return f"{page.base_url}{suffix}{signature}"


def decrypt_tile_if_needed(data: bytes) -> bytes:
    if not data.startswith(ENCRYPTION_MARKER):
        return data

    if len(data) < 12:
        raise DownloadError("encrypted tile is too short")

    header_size = int.from_bytes(data[-4:], "little")
    encrypted_size_offset = 4 + header_size
    encrypted_size = int.from_bytes(data[encrypted_size_offset : encrypted_size_offset + 4], "little")
    encrypted_start = encrypted_size_offset + 4
    encrypted_end = encrypted_start + encrypted_size
    footer_end = len(data) - 4

    header = data[4 : 4 + header_size]
    encrypted = data[encrypted_start:encrypted_end]
    footer = data[encrypted_end:footer_end]

    if len(encrypted) % AES.block_size != 0:
        raise DownloadError("encrypted tile size is not aligned to AES block size")

    cipher = AES.new(AES_KEY, AES.MODE_CBC, iv=AES_IV)
    decrypted = cipher.decrypt(encrypted)
    return header + decrypted + footer


def sanitize_filename(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    return name[:180] or "google-art"


def build_jobs(page: PageInfo, tile_info: TileInfo) -> list[TileJob]:
    level = tile_info.highest_level
    return [
        TileJob(x=x, y=y, url=build_tile_url(page, x, y, level.z))
        for y in range(level.num_tiles_y)
        for x in range(level.num_tiles_x)
    ]


def download_tiles(jobs: Iterable[TileJob], workers: int, reporter: Reporter) -> dict[tuple[int, int], bytes]:
    tiles: dict[tuple[int, int], bytes] = {}
    job_list = list(jobs)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(fetch_bytes, job.url): job for job in job_list}
        completed = 0
        total = len(job_list)

        for future in as_completed(future_map):
            job = future_map[future]
            tile_data = decrypt_tile_if_needed(future.result())
            tiles[(job.x, job.y)] = tile_data
            completed += 1
            reporter.tile_advanced(completed, total)

    return tiles


def stitch_tiles(tile_info: TileInfo, tiles: dict[tuple[int, int], bytes], output_path: Path) -> None:
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
    image.save(output_path, quality=95)


def resolve_output_path(output_dir: Path, filename: str | None, page: PageInfo) -> Path:
    if filename:
        return output_dir / filename
    return output_dir / f"{sanitize_filename(page.title)}.jpg"


def download_artwork(
    url: str,
    output_dir: Path,
    filename: str | None,
    workers: int,
    reporter: Reporter,
    index: int,
    total: int,
) -> DownloadResult:
    logger = get_logger()
    asset_url = normalize_asset_url(url)
    logger.info("Fetching artwork page: %s", asset_url)
    reporter.log(f"Fetching artwork page: {asset_url}")
    html = fetch_text(asset_url)
    page = parse_page_info(html)
    tile_info = parse_tile_info(fetch_bytes(page.tile_info_url))
    output_path = resolve_output_path(output_dir, filename, page)

    context = ArtworkContext(
        index=index,
        total=total,
        url=asset_url,
        page=page,
        tile_info=tile_info,
        output_path=output_path,
    )
    reporter.artwork_started(context)

    jobs = build_jobs(page, tile_info)
    logger.info(
        "Artwork metadata: title=%s size=%sx%s tiles=%s",
        page.title,
        tile_info.image_width,
        tile_info.image_height,
        len(jobs),
    )
    reporter.log(f"Metadata ready: {page.title} | {tile_info.image_width}x{tile_info.image_height} | {len(jobs)} tiles")
    tiles = download_tiles(jobs, workers=workers, reporter=reporter)
    reporter.stitching_started()
    stitch_tiles(tile_info, tiles, output_path)

    return DownloadResult(
        url=asset_url,
        output_path=output_path,
        title=page.title,
        size=(tile_info.image_width, tile_info.image_height),
        tile_count=len(jobs),
    )
