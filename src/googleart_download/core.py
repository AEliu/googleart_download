from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable, cast
from xml.etree import ElementTree

from Crypto.Cipher import AES
from PIL import Image

from .constants import AES_IV, AES_KEY, ENCRYPTION_MARKER, REQUEST_TIMEOUT, SIGNING_KEY, USER_AGENT
from .errors import DownloadError
from .logging_utils import get_logger
from .models import ArtworkContext, ArtworkMetadata, DownloadResult, PageInfo, PyramidLevel, RetryConfig, TileInfo, TileJob
from .reporters import Reporter


class HttpClient:
    def __init__(self, retry_config: RetryConfig, timeout: int = REQUEST_TIMEOUT) -> None:
        self.retry_config = retry_config
        self.timeout = timeout
        self.logger = get_logger()

    def fetch_bytes(self, url: str, *, description: str) -> bytes:
        last_error: Exception | None = None

        for attempt in range(1, self.retry_config.attempts + 1):
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                last_error = exc
                if not self._should_retry_http(exc.code, attempt):
                    raise DownloadError(f"{description} failed: {url} -> HTTP {exc.code}") from exc
                self._sleep_before_retry(description, url, attempt, f"HTTP {exc.code}")
            except urllib.error.URLError as exc:
                last_error = exc
                if attempt >= self.retry_config.attempts:
                    raise DownloadError(f"{description} failed: {url} -> {exc.reason}") from exc
                self._sleep_before_retry(description, url, attempt, str(exc.reason))

        raise DownloadError(f"{description} failed after retries: {url} -> {last_error}")

    def fetch_text(self, url: str, *, description: str) -> str:
        return self.fetch_bytes(url, description=description).decode("utf-8", errors="ignore")

    def _should_retry_http(self, status_code: int, attempt: int) -> bool:
        return attempt < self.retry_config.attempts and status_code in self.retry_config.retry_http_statuses

    def _sleep_before_retry(self, description: str, url: str, attempt: int, reason: str) -> None:
        delay = self.retry_config.backoff_base_seconds * (self.retry_config.backoff_multiplier ** (attempt - 1))
        self.logger.warning(
            "Retrying %s (attempt %s/%s) after %ss due to %s: %s",
            description,
            attempt + 1,
            self.retry_config.attempts,
            f"{delay:.2f}",
            reason,
            url,
        )
        time.sleep(delay)


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


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", html_unescape(value)).strip()
    return value or None


def decode_js_escapes(value: str) -> str:
    try:
        return bytes(value, "utf-8").decode("unicode_escape")
    except UnicodeDecodeError:
        return value


def extract_json_ld_metadata(html: str) -> dict[str, object] | None:
    matches = re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S | re.I)
    for raw in matches:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if isinstance(item, dict) and item.get("@type") == "CreativeWork":
                return item
    return None


def get_str_value(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) else None


def extract_named_field(html: str, name: str) -> str | None:
    pattern = rf'\["{re.escape(name)}",\[\["(.*?)"'
    match = re.search(pattern, html)
    if not match:
        return None
    return clean_text(decode_js_escapes(match.group(1)))


def parse_artwork_metadata(html: str, fallback_url: str, fallback_title: str) -> ArtworkMetadata:
    payload = extract_json_ld_metadata(html) or {}
    title = clean_text(get_str_value(payload, "name") or fallback_title)
    creator = clean_text(get_str_value(payload, "author"))
    description = clean_text(get_str_value(payload, "description"))
    source_url = clean_text(get_str_value(payload, "url") or fallback_url)

    return ArtworkMetadata(
        title=title,
        creator=creator,
        description=description,
        source_url=source_url,
        date_created=extract_named_field(html, "Date Created"),
        rights=extract_named_field(html, "Rights"),
        external_link=extract_named_field(html, "External Link"),
        partner=extract_named_field(html, "Provider"),
    )


def parse_page_info(html: str) -> PageInfo:
    title_match = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    title = title_match.group(1).replace("— Google Arts &amp; Culture", "").strip() if title_match else "google-art"
    title = html_unescape(title)

    match = re.search(r']\r?\n?,"(//[a-zA-Z0-9./_\-]+)",(?:"([^"]+)"|null)', html)
    if not match:
        raise DownloadError("could not find tile base URL in page HTML")

    page_url_match = re.search(r'<meta property="og:url" content="([^"]+)"', html)
    page_url = page_url_match.group(1) if page_url_match else ""
    metadata = parse_artwork_metadata(html, fallback_url=page_url, fallback_title=title)

    return PageInfo(
        title=title,
        base_url=f"https:{match.group(1)}",
        token=match.group(2) or "",
        metadata=metadata,
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


def download_tiles(jobs: Iterable[TileJob], workers: int, reporter: Reporter, http_client: HttpClient) -> dict[tuple[int, int], bytes]:
    tiles: dict[tuple[int, int], bytes] = {}
    job_list = list(jobs)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(http_client.fetch_bytes, job.url, description=f"tile x={job.x} y={job.y}"): job
            for job in job_list
        }
        completed = 0
        total = len(job_list)

        for future in as_completed(future_map):
            job = future_map[future]
            tile_data = decrypt_tile_if_needed(future.result())
            tiles[(job.x, job.y)] = tile_data
            completed += 1
            reporter.tile_advanced(completed, total)

    return tiles


def build_exif_bytes(metadata: ArtworkMetadata) -> bytes:
    exif = Image.Exif()

    def utf16le_bytes(value: str) -> bytes:
        return value.encode("utf-16le") + b"\x00\x00"

    def set_exif_value(tag: int, value: str | bytes) -> None:
        cast(Any, exif)[tag] = value

    title = clean_text(metadata.title)
    creator = clean_text(metadata.creator)
    description = clean_text(metadata.description)
    rights = clean_text(metadata.rights)

    comment_parts = []
    if metadata.source_url:
        comment_parts.append(f"Source URL: {metadata.source_url}")
    if metadata.date_created:
        comment_parts.append(f"Date Created: {metadata.date_created}")
    if metadata.external_link:
        comment_parts.append(f"External Link: {metadata.external_link}")
    if metadata.partner:
        comment_parts.append(f"Partner: {metadata.partner}")
    if rights and rights not in comment_parts:
        comment_parts.append(f"Rights: {rights}")
    comment = clean_text(" | ".join(comment_parts))

    if description:
        set_exif_value(270, description[:2000])
    if creator:
        set_exif_value(315, creator[:512])
        set_exif_value(40093, utf16le_bytes(creator[:512]))
    if rights:
        set_exif_value(33432, rights[:2000])
    if title:
        set_exif_value(40091, utf16le_bytes(title[:512]))
    if comment:
        set_exif_value(40092, utf16le_bytes(comment[:1500]))
        set_exif_value(37510, b"ASCII\x00\x00\x00" + comment[:1500].encode("ascii", errors="replace"))

    return exif.tobytes()


def metadata_to_dict(metadata: ArtworkMetadata) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in metadata.__dict__.items():
        cleaned = clean_text(value)
        if cleaned:
            result[key] = cleaned
    return result


def write_metadata_sidecar(output_path: Path, metadata: ArtworkMetadata) -> Path:
    sidecar_path = output_path.with_suffix(output_path.suffix + ".json")
    payload = metadata_to_dict(metadata)
    sidecar_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return sidecar_path


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


def resolve_output_path(output_dir: Path, filename: str | None, page: PageInfo) -> Path:
    if filename:
        return output_dir / filename
    return output_dir / f"{sanitize_filename(page.title)}.jpg"


def download_artwork(
    url: str,
    output_dir: Path,
    filename: str | None,
    workers: int,
    retry_config: RetryConfig,
    skip_existing: bool,
    write_metadata: bool,
    write_sidecar: bool,
    reporter: Reporter,
    index: int,
    total: int,
) -> DownloadResult:
    logger = get_logger()
    http_client = HttpClient(retry_config=retry_config)
    asset_url = normalize_asset_url(url)
    logger.info("Fetching artwork page: %s", asset_url)
    reporter.log(f"Fetching artwork page: {asset_url}")
    html = http_client.fetch_text(asset_url, description="artwork page")
    page = parse_page_info(html)
    output_path = resolve_output_path(output_dir, filename, page)

    if skip_existing and output_path.exists():
        sidecar_path = output_path.with_suffix(output_path.suffix + ".json") if write_sidecar else None
        return DownloadResult(
            url=asset_url,
            output_path=output_path,
            title=page.title,
            size=None,
            tile_count=None,
            skipped=True,
            sidecar_path=sidecar_path if sidecar_path and sidecar_path.exists() else None,
        )

    tile_info = parse_tile_info(http_client.fetch_bytes(page.tile_info_url, description="tile metadata"))

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
    tiles = download_tiles(jobs, workers=workers, reporter=reporter, http_client=http_client)
    reporter.stitching_started()
    stitch_tiles(tile_info, tiles, output_path, metadata=page.metadata, write_metadata=write_metadata)
    sidecar_path = None
    if write_sidecar and page.metadata is not None:
        sidecar_path = write_metadata_sidecar(output_path, page.metadata)

    return DownloadResult(
        url=asset_url,
        output_path=output_path,
        title=page.title,
        size=(tile_info.image_width, tile_info.image_height),
        tile_count=len(jobs),
        sidecar_path=sidecar_path,
    )
