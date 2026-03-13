from __future__ import annotations

from collections import deque

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

from .models import ArtworkContext, BatchRunResult, BatchSnapshot, BatchTask, DownloadResult


class Reporter:
    def log(self, message: str) -> None:
        pass

    def batch_started(self, total: int) -> None:
        pass

    def batch_updated(self, snapshot: BatchSnapshot) -> None:
        pass

    def artwork_started(self, context: ArtworkContext) -> None:
        pass

    def tile_advanced(self, completed: int, total: int) -> None:
        pass

    def stitching_started(self) -> None:
        pass

    def artwork_finished(self, result: DownloadResult) -> None:
        pass

    def task_skipped(self, task: BatchTask) -> None:
        pass

    def task_failed(self, task: BatchTask) -> None:
        pass

    def batch_finished(self, run_result: BatchRunResult) -> None:
        pass

    def close(self) -> None:
        pass


class RichCliReporter(Reporter):
    def __init__(self) -> None:
        self.console = Console(stderr=True)
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=None),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=self.console,
            transient=False,
        )
        self.overall_task_id: TaskID | None = None
        self.tile_task_id: TaskID | None = None
        self.current_tile_total = 0
        self.last_snapshot: BatchSnapshot | None = None

    def log(self, message: str) -> None:
        self.console.print(f"[cyan]•[/cyan] {message}")

    def batch_started(self, total: int) -> None:
        self.progress.start()
        self.overall_task_id = self.progress.add_task("Total artworks", total=total)

    def batch_updated(self, snapshot: BatchSnapshot) -> None:
        self.last_snapshot = snapshot
        if self.overall_task_id is not None:
            self.progress.update(
                self.overall_task_id,
                completed=snapshot.succeeded + snapshot.failed + snapshot.skipped,
                total=snapshot.total,
            )

    def artwork_started(self, context: ArtworkContext) -> None:
        description = f"[{context.index}/{context.total}] {context.page.title[:60]}"
        total_tiles = context.selected_level.tile_count
        self.current_tile_total = total_tiles
        self.tile_task_id = self.progress.add_task(description, total=total_tiles)
        self.log(f"Output: {context.output_path}")
        self.log(
            f"Image: {context.tile_info.image_width_for(context.selected_level)}x"
            f"{context.tile_info.image_height_for(context.selected_level)}, "
            f"tiles: {context.selected_level.num_tiles_x}x{context.selected_level.num_tiles_y}"
        )

    def tile_advanced(self, completed: int, total: int) -> None:
        if self.tile_task_id is not None:
            self.progress.update(self.tile_task_id, completed=completed, total=total)

    def stitching_started(self) -> None:
        if self.tile_task_id is not None:
            self.progress.update(self.tile_task_id, description="Stitching image", completed=self.current_tile_total)

    def artwork_finished(self, result: DownloadResult) -> None:
        if self.tile_task_id is not None:
            self.progress.update(self.tile_task_id, completed=self.current_tile_total)
        self.log(f"Saved: {result.output_path}")
        if result.sidecar_path is not None:
            self.log(f"Sidecar: {result.sidecar_path}")

    def task_skipped(self, task: BatchTask) -> None:
        result = task.result
        if result is not None:
            self.log(f"Skipped existing: {result.output_path}")
            if result.sidecar_path is not None:
                self.log(f"Existing sidecar: {result.sidecar_path}")

    def task_failed(self, task: BatchTask) -> None:
        self.log(f"Failed: {task.url} | {task.error}")

    def batch_finished(self, run_result: BatchRunResult) -> None:
        self.progress.stop()
        snapshot = run_result.snapshot
        style = "bold green" if snapshot.failed == 0 else "bold yellow"
        self.console.print(
            f"[{style}]Completed {snapshot.succeeded} succeeded, {snapshot.skipped} skipped, "
            f"{snapshot.failed} failed, {snapshot.pending} pending.[/{style}]"
        )
        if run_result.rerun_rounds:
            self.log(f"Rerun rounds used: {run_result.rerun_rounds}")


class RichTuiReporter(Reporter):
    def __init__(self) -> None:
        self.console = Console(stderr=True)
        self.logs: deque[str] = deque(maxlen=10)
        self.current_status = "Idle"
        self.current_title = "-"
        self.current_output = "-"
        self.current_size = "-"
        self.current_tiles = "-"
        self.total_artworks = 0
        self.completed_artworks = 0
        self.skipped_artworks = 0
        self.failed_artworks = 0
        self.pending_artworks = 0
        self.current_tile_total = 0
        self.progress = Progress(
            SpinnerColumn(style="cyan"),
            TextColumn("[bold]{task.description}"),
            BarColumn(bar_width=None, complete_style="green", finished_style="green"),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=self.console,
            expand=True,
        )
        self.total_task_id: TaskID = self.progress.add_task("Artworks", total=1)
        self.tile_task_id: TaskID = self.progress.add_task("Tiles", total=1)
        self.live = Live(self.render(), console=self.console, refresh_per_second=8)
        self.live.start()

    def log_line(self, message: str) -> None:
        self.logs.appendleft(message)
        self.live.update(self.render())

    def log(self, message: str) -> None:
        self.log_line(message)

    def render(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="logs", size=12),
        )
        layout["body"].split_row(Layout(name="summary", ratio=3), Layout(name="progress", ratio=2))

        header = Panel(
            Text(f"Google Art Downloader  |  {self.current_status}", style="bold white on dark_green"),
            border_style="green",
        )

        summary = Table.grid(padding=(0, 1))
        summary.add_column(style="bold cyan", width=12)
        summary.add_column()
        summary.add_row("Title", self.current_title)
        summary.add_row("Output", self.current_output)
        summary.add_row("Image", self.current_size)
        summary.add_row("Tiles", self.current_tiles)
        summary.add_row("Batch", f"{self.completed_artworks}/{self.total_artworks}")
        summary.add_row("Skipped", str(self.skipped_artworks))
        summary.add_row("Failed", str(self.failed_artworks))
        summary.add_row("Pending", str(self.pending_artworks))

        logs = Group(*[Text(line) for line in self.logs]) if self.logs else Text("No logs yet.")

        layout["header"].update(header)
        layout["summary"].update(Panel(summary, title="Current Artwork", border_style="cyan"))
        layout["progress"].update(Panel(self.progress, title="Progress", border_style="magenta"))
        layout["logs"].update(Panel(logs, title="Logs", border_style="yellow"))
        return layout

    def batch_started(self, total: int) -> None:
        self.total_artworks = total
        self.pending_artworks = total
        self.progress.update(self.total_task_id, total=total, completed=0)
        self.log_line(f"Batch started: {total} artwork(s)")

    def batch_updated(self, snapshot: BatchSnapshot) -> None:
        self.completed_artworks = snapshot.succeeded
        self.skipped_artworks = snapshot.skipped
        self.failed_artworks = snapshot.failed
        self.pending_artworks = snapshot.pending
        self.progress.update(
            self.total_task_id,
            total=snapshot.total,
            completed=snapshot.succeeded + snapshot.failed + snapshot.skipped,
        )
        self.live.update(self.render())

    def artwork_started(self, context: ArtworkContext) -> None:
        self.current_status = f"Downloading [{context.index}/{context.total}]"
        self.current_title = context.page.title
        self.current_output = str(context.output_path)
        self.current_size = (
            f"{context.tile_info.image_width_for(context.selected_level)}x"
            f"{context.tile_info.image_height_for(context.selected_level)}"
        )
        self.current_tiles = (
            f"{context.selected_level.num_tiles_x}x{context.selected_level.num_tiles_y}"
            f" ({context.selected_level.tile_count} total)"
        )
        total_tiles = context.selected_level.tile_count
        self.current_tile_total = total_tiles
        self.progress.update(self.tile_task_id, description="Tiles", total=total_tiles, completed=0)
        self.log_line(f"Start: {context.page.title}")

    def tile_advanced(self, completed: int, total: int) -> None:
        self.progress.update(self.tile_task_id, completed=completed, total=total)
        self.live.update(self.render())

    def stitching_started(self) -> None:
        self.current_status = "Stitching"
        self.progress.update(self.tile_task_id, description="Stitching", completed=self.current_tile_total)
        self.log_line("All tiles downloaded, stitching image")

    def artwork_finished(self, result: DownloadResult) -> None:
        self.current_status = "Saved"
        self.log_line(f"Saved: {result.output_path}")
        if result.sidecar_path is not None:
            self.log_line(f"Sidecar: {result.sidecar_path}")
        self.live.update(self.render())

    def task_skipped(self, task: BatchTask) -> None:
        self.current_status = "Skipped"
        if task.result is not None:
            self.log_line(f"Skipped existing: {task.result.output_path}")
            if task.result.sidecar_path is not None:
                self.log_line(f"Existing sidecar: {task.result.sidecar_path}")
        self.live.update(self.render())

    def task_failed(self, task: BatchTask) -> None:
        self.current_status = "Failed"
        self.log_line(f"Failed: {task.url} | {task.error}")

    def batch_finished(self, run_result: BatchRunResult) -> None:
        self.current_status = "Completed"
        self.log_line(
            f"Finished {run_result.snapshot.succeeded} succeeded, {run_result.snapshot.skipped} skipped, "
            f"{run_result.snapshot.failed} failed"
        )
        if run_result.rerun_rounds:
            self.log_line(f"Rerun rounds used: {run_result.rerun_rounds}")
        self.live.update(self.render())

    def close(self) -> None:
        self.live.stop()


def build_reporter(use_tui: bool) -> Reporter:
    return RichTuiReporter() if use_tui else RichCliReporter()
