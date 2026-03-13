from __future__ import annotations

import argparse
import os
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .core import download_artwork
from .errors import DownloadError
from .logging_utils import configure_logging
from .models import DownloadResult
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

    return urls


def render_summary(results: list[DownloadResult]) -> None:
    console = Console()
    table = Table(title="Download Summary", header_style="bold cyan")
    table.add_column("Title")
    table.add_column("Size", justify="right")
    table.add_column("Tiles", justify="right")
    table.add_column("Saved To")
    for result in results:
        table.add_row(result.title, f"{result.size[0]}x{result.size[1]}", str(result.tile_count), str(result.output_path))
    console.print(table)


def main() -> int:
    args = parse_args()
    configure_logging(verbose=args.verbose, log_file=args.log_file)

    reporter = build_reporter(args.tui)
    results: list[DownloadResult] = []

    try:
        urls = collect_urls(args)
        reporter.batch_started(len(urls))

        for index, url in enumerate(urls, start=1):
            result = download_artwork(
                url=url,
                output_dir=Path(args.output_dir),
                filename=args.filename,
                workers=max(1, args.workers),
                reporter=reporter,
                index=index,
                total=len(urls),
            )
            results.append(result)
            reporter.artwork_finished(result)

        reporter.batch_finished(results)
    except DownloadError as exc:
        Console(stderr=True).print(f"[bold red]Error:[/bold red] {exc}")
        return 1
    finally:
        reporter.close()

    render_summary(results)
    return 0
