from __future__ import annotations

import argparse
import os
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .batch import BatchDownloadManager
from .errors import DownloadError
from .logging_utils import configure_logging
from .models import BatchRunResult, RetryConfig
from .reporters import build_reporter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download high-resolution Google Arts & Culture images by stitching tiles.",
    )
    parser.add_argument("urls", nargs="*", help="one or more Google Arts & Culture asset URLs")
    parser.add_argument("--url-file", help="text file with one asset URL per line")
    parser.add_argument(
        "-o",
        "--output-dir",
        default="downloads",
        help="destination directory (default: downloads)",
    )
    parser.add_argument(
        "-f",
        "--filename",
        help="output filename, only valid when downloading a single URL",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=min(16, (os.cpu_count() or 4) * 2),
        help="concurrent tile downloads (default: auto)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="request retry attempts for pages, metadata, and tiles (default: 3)",
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=0.75,
        help="base backoff in seconds before retrying failed requests (default: 0.75)",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="stop the batch immediately after the first failed artwork",
    )
    parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="download again even if the target file already exists",
    )
    parser.add_argument(
        "--write-metadata",
        action="store_true",
        help="write artwork metadata into the output JPEG EXIF",
    )
    parser.add_argument(
        "--write-sidecar",
        action="store_true",
        help="write artwork metadata to a JSON sidecar next to the image",
    )
    parser.add_argument("--tui", action="store_true", help="show a richer live terminal dashboard")
    parser.add_argument("--log-file", help="write logs to a file")
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    return parser.parse_args()


def collect_urls(args: argparse.Namespace) -> list[str]:
    urls: list[str] = list(args.urls)

    if args.url_file:
        file_urls = [
            line.strip()
            for line in Path(args.url_file).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        urls.extend(file_urls)

    if not urls:
        raise DownloadError("provide at least one URL or use --url-file")

    if args.filename and len(urls) > 1:
        raise DownloadError("--filename can only be used with a single URL")

    if args.retries < 1:
        raise DownloadError("--retries must be at least 1")

    if args.retry_backoff < 0:
        raise DownloadError("--retry-backoff must be >= 0")

    return urls


def render_summary(run_result: BatchRunResult) -> None:
    console = Console()
    table = Table(title="Download Summary", header_style="bold cyan")
    table.add_column("Status")
    table.add_column("Title / URL")
    table.add_column("Size", justify="right")
    table.add_column("Tiles", justify="right")
    table.add_column("Path / Error")
    table.add_column("Sidecar")

    for result in run_result.succeeded:
        status = "skipped" if result.skipped else "ok"
        size = "-" if result.size is None else f"{result.size[0]}x{result.size[1]}"
        tiles = "-" if result.tile_count is None else str(result.tile_count)
        table.add_row(
            status,
            result.title,
            size,
            tiles,
            str(result.output_path),
            str(result.sidecar_path) if result.sidecar_path else "-",
        )
    for task in run_result.failed:
        table.add_row("failed", task.url, "-", "-", task.error or "unknown error", "-")
    console.print(table)


def main() -> int:
    args = parse_args()
    configure_logging(verbose=args.verbose, log_file=args.log_file)

    reporter = build_reporter(args.tui)
    retry_config = RetryConfig(
        attempts=args.retries,
        backoff_base_seconds=args.retry_backoff,
    )
    run_result: BatchRunResult | None = None

    try:
        urls = collect_urls(args)
        manager = BatchDownloadManager(
            urls=urls,
            output_dir=Path(args.output_dir),
            filename=args.filename,
            workers=max(1, args.workers),
            retry_config=retry_config,
            reporter=reporter,
            fail_fast=args.fail_fast,
            skip_existing=not args.no_skip_existing,
            write_metadata=args.write_metadata,
            write_sidecar=args.write_sidecar,
        )
        run_result = manager.run()
    except DownloadError as exc:
        Console(stderr=True).print(f"[bold red]Error:[/bold red] {exc}")
        return 1
    finally:
        reporter.close()

    assert run_result is not None
    render_summary(run_result)
    return 0 if run_result.snapshot.failed == 0 else 1
