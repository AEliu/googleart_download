from __future__ import annotations

import time
import urllib.error
import urllib.request

from ..constants import REQUEST_TIMEOUT, USER_AGENT
from ..errors import DownloadError
from ..logging_utils import get_logger
from ..models import RetryConfig


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
