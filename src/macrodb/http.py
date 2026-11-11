from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import requests

log = logging.getLogger(__name__)


class ProviderError(Exception):
    """Non-retryable provider failure (bad request, auth, blocked, unparseable)."""


@dataclass
class HttpResponse:
    url: str
    status: int
    content: bytes
    headers: dict = field(default_factory=dict)

    @property
    def content_type(self) -> str:
        return self.headers.get("Content-Type", "")


class HttpClient:
    """requests wrapper: retries with exponential backoff on 429/5xx/network errors and a
    minimum interval between calls (rate limiting). Replaceable in tests (same `.get`)."""

    def __init__(self, min_interval_s: float = 0.0, max_retries: int = 4, backoff_s: float = 1.0,
                 timeout_s: float = 60.0, user_agent: str = "macrodb/0.1 (research)"):
        self.min_interval_s, self.max_retries = min_interval_s, max_retries
        self.backoff_s, self.timeout_s = backoff_s, timeout_s
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self._last = 0.0

    def get(self, url: str, params: dict | None = None, headers: dict | None = None) -> HttpResponse:
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            wait = self.min_interval_s - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                r = self.session.get(url, params=params, headers=headers, timeout=self.timeout_s)
            except requests.RequestException as e:
                last_err = e
            else:
                if r.status_code == 429 or r.status_code >= 500:
                    last_err = ProviderError(f"HTTP {r.status_code} from {url}")
                    ra = r.headers.get("Retry-After")
                    if ra and ra.isdigit():
                        time.sleep(min(int(ra), 120))
                else:
                    return HttpResponse(r.url, r.status_code, r.content, dict(r.headers))
            if attempt < self.max_retries:
                delay = self.backoff_s * (2 ** attempt)
                log.warning("retry %d for %s in %.1fs (%s)", attempt + 1, url, delay, last_err)
                time.sleep(delay)
        raise ProviderError(f"giving up on {url}: {last_err}")
