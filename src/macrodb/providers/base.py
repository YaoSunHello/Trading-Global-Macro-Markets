from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from ..http import HttpClient, ProviderError

MISSING_MARKERS = {"", ".", "NA", "N/A", "NaN", "nan", "null", "None"}


@dataclass
class SeriesRequest:
    """What the ingester asks an adapter for: one provider series (all mapped fields)."""
    provider_id: str
    source_series_id: str
    fields: list[str]
    frequency_id: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawObs:
    """One source-faithful observation. Nothing is dropped; unparseable values keep value_num=None."""
    field_id: str
    obs_date_raw: str | None
    observation_date: date | None
    value_raw: str | None
    value_num: float | None
    realtime_start: date | None = None
    realtime_end: date | None = None
    published_at: datetime | None = None
    observation_ts: datetime | None = None
    source_attrs: dict | None = None


@dataclass
class FetchedPage:
    url: str                      # with secrets redacted
    params: dict                  # with secrets redacted
    status: int
    content: bytes
    content_type: str
    observations: list[RawObs]


@dataclass
class FetchResult:
    pages: list[FetchedPage] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)   # provider-level data-quality notes


def to_float(raw: str | None) -> float | None:
    if raw is None or raw.strip() in MISSING_MARKERS:
        return None
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


class ProviderAdapter(ABC):
    """Common provider interface. A new provider = a subclass + a providers.yaml entry;
    the database schema never changes.

    Contract:
      * fetch() performs the (paged) HTTP calls and returns every raw payload plus its parsed rows.
      * Adapters never write to the database and never transform values (that is Silver's job).
      * `incremental` declares how incremental updates work:
          'overlap'  -> caller passes `since` = last stored observation - overlap_days
          'full'     -> provider returns full history/vintages; caller always refetches (dedup by hash)
    """

    provider_id: str = ""
    incremental: str = "overlap"
    overlap_days: int = 45

    def __init__(self, http: HttpClient, config: dict | None = None):
        self.http = http
        self.config = config or {}

    # -- metadata & auth ---------------------------------------------------------------
    def metadata(self) -> dict:
        return {"provider_id": self.provider_id, "incremental": self.incremental,
                "overlap_days": self.overlap_days, **{k: v for k, v in self.config.items()
                                                      if k not in ("api_key",)}}

    def credential(self) -> str | None:
        env = self.config.get("auth_env_var")
        return os.environ.get(env) if env else None

    def require_credential(self) -> str:
        key = self.credential()
        if not key:
            raise ProviderError(
                f"{self.provider_id}: missing credential; set env var {self.config.get('auth_env_var')}")
        return key

    # -- retrieval ---------------------------------------------------------------------
    @abstractmethod
    def fetch(self, req: SeriesRequest, since: date | None = None,
              until: date | None = None) -> FetchResult:
        ...
