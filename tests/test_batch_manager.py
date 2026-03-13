from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from googleart_download.batch import BatchDownloadManager
from googleart_download.errors import DownloadError
from googleart_download.models import DownloadResult, DownloadSize, RetryConfig, TaskState
from googleart_download.reporters import Reporter


class SilentReporter(Reporter):
    pass


class BatchManagerTests(unittest.TestCase):
    def test_reruns_failed_tasks_and_tracks_attempts(self) -> None:
        calls: list[str] = []

        def fake_download_artwork(**kwargs):  # type: ignore[no-untyped-def]
            url = kwargs["url"]
            calls.append(url)
            if "bad" in url:
                raise DownloadError("boom")
            return DownloadResult(
                url=url,
                output_path=Path("/tmp/out.jpg"),
                title="ok",
                size=(10, 10),
                tile_count=1,
            )

        with TemporaryDirectory() as tmpdir:
            manager = BatchDownloadManager(
                urls=["https://bad.example", "https://good.example"],
                output_dir=Path(tmpdir),
                filename=None,
                workers=1,
                retry_config=RetryConfig(attempts=1),
                reporter=SilentReporter(),
                fail_fast=False,
                download_size=DownloadSize.MAX,
                max_dimension=None,
                skip_existing=False,
                write_metadata=False,
                write_sidecar=False,
                rerun_failures=1,
            )
            with patch("googleart_download.batch.download_artwork", side_effect=fake_download_artwork):
                result = manager.run()

        self.assertEqual(calls.count("https://bad.example"), 2)
        self.assertEqual(calls.count("https://good.example"), 1)
        self.assertEqual(result.snapshot.succeeded, 1)
        self.assertEqual(result.snapshot.failed, 1)
        self.assertEqual(result.rerun_rounds, 1)
        failed_task = next(task for task in result.snapshot.tasks if task.url == "https://bad.example")
        self.assertEqual(failed_task.state, TaskState.FAILED)
        self.assertEqual(failed_task.attempts, 2)

    def test_fail_fast_stops_current_round(self) -> None:
        calls: list[str] = []

        def fake_download_artwork(**kwargs):  # type: ignore[no-untyped-def]
            url = kwargs["url"]
            calls.append(url)
            raise DownloadError("boom")

        with TemporaryDirectory() as tmpdir:
            manager = BatchDownloadManager(
                urls=["https://bad-1.example", "https://bad-2.example"],
                output_dir=Path(tmpdir),
                filename=None,
                workers=1,
                retry_config=RetryConfig(attempts=1),
                reporter=SilentReporter(),
                fail_fast=True,
                download_size=DownloadSize.MAX,
                max_dimension=None,
                skip_existing=False,
                write_metadata=False,
                write_sidecar=False,
                rerun_failures=2,
            )
            with patch("googleart_download.batch.download_artwork", side_effect=fake_download_artwork):
                result = manager.run()

        self.assertEqual(calls, ["https://bad-1.example"])
        self.assertEqual(result.snapshot.failed, 1)
        self.assertEqual(result.snapshot.pending, 1)


if __name__ == "__main__":
    unittest.main()
