from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .core import download_artwork
from .errors import DownloadError
from .models import BatchRunResult, BatchSnapshot, BatchTask, DownloadResult, RetryConfig, TaskState
from .reporters import Reporter


class BatchDownloadManager:
    def __init__(
        self,
        *,
        urls: list[str],
        output_dir: Path,
        filename: str | None,
        workers: int,
        retry_config: RetryConfig,
        reporter: Reporter,
        fail_fast: bool,
        skip_existing: bool,
        write_metadata: bool,
        write_sidecar: bool,
    ) -> None:
        self.urls = urls
        self.output_dir = output_dir
        self.filename = filename
        self.workers = workers
        self.retry_config = retry_config
        self.reporter = reporter
        self.fail_fast = fail_fast
        self.skip_existing = skip_existing
        self.write_metadata = write_metadata
        self.write_sidecar = write_sidecar
        self.tasks = [
            BatchTask(index=index, url=url, state=TaskState.PENDING)
            for index, url in enumerate(urls, start=1)
        ]

    def run(self) -> BatchRunResult:
        self.reporter.batch_started(len(self.tasks))
        self.reporter.batch_updated(self.snapshot)

        for task in list(self.tasks):
            self._update_task(task.index, state=TaskState.RUNNING, error=None)
            self.reporter.batch_updated(self.snapshot)

            try:
                result = download_artwork(
                    url=task.url,
                    output_dir=self.output_dir,
                    filename=self.filename,
                    workers=self.workers,
                    retry_config=self.retry_config,
                    skip_existing=self.skip_existing,
                    write_metadata=self.write_metadata,
                    write_sidecar=self.write_sidecar,
                    reporter=self.reporter,
                    index=task.index,
                    total=len(self.tasks),
                )
            except DownloadError as exc:
                failed_task = self._update_task(task.index, state=TaskState.FAILED, error=str(exc))
                self.reporter.task_failed(failed_task)
                self.reporter.batch_updated(self.snapshot)
                if self.fail_fast:
                    break
            else:
                state = TaskState.SKIPPED if result.skipped else TaskState.SUCCEEDED
                completed_task = self._update_task(task.index, state=state, result=result, error=None)
                if result.skipped:
                    self.reporter.task_skipped(completed_task)
                else:
                    self.reporter.artwork_finished(result)
                self.reporter.batch_updated(self.snapshot)

        run_result = BatchRunResult(
            snapshot=self.snapshot,
            succeeded=[task.result for task in self.tasks if task.result is not None],
            failed=[task for task in self.tasks if task.state == TaskState.FAILED],
        )
        self.reporter.batch_finished(run_result)
        return run_result

    @property
    def snapshot(self) -> BatchSnapshot:
        return BatchSnapshot(tasks=list(self.tasks))

    def _update_task(
        self,
        index: int,
        *,
        state: TaskState,
        result: DownloadResult | None = None,
        error: str | None = None,
    ) -> BatchTask:
        task_index = index - 1
        updated = replace(self.tasks[task_index], state=state, result=result, error=error)
        self.tasks[task_index] = updated
        return updated
