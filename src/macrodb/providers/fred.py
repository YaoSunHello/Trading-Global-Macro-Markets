from __future__ import annotations

import json
from datetime import date

from ..http import ProviderError
from ..timeutil import parse_obs_date
from .base import FetchedPage, FetchResult, ProviderAdapter, RawObs, SeriesRequest, to_float

BASE = "https://api.stlouisfed.org/fred/series/observations"
PAGE = 100000


class FredAdapter(ProviderAdapter):
    """FRED + ALFRED. Always requests the full vintage history (realtime window 1776-07-04..9999-12-31)
    so every revision is captured with its `realtime_start` (the date that value first became current).

    Caveats (documented in docs/PROVIDERS.md): for observations that pre-date ALFRED's archive, the
    earliest realtime_start is the archive start, not the true first-release date."""

    provider_id = "fred"
    incremental = "full"          # clipping realtime windows would corrupt realtime_start; refetch + dedup

    def fetch(self, req: SeriesRequest, since: date | None = None, until: date | None = None) -> FetchResult:
        key = self.require_credential()
        try:
            return self._fetch(req, key, vintages=True)
        except ProviderError as e:
            if "vintage dates" not in str(e):
                raise
        # Too many vintage dates (FRED caps a request at 2000; typical for long daily series).
        # Fall back to current values only. The default realtime window would stamp every row with today's
        # date, so realtime fields are dropped: the rows carry NO availability info and Silver flags them.
        res = self._fetch(req, key, vintages=False)
        for page in res.pages:
            for o in page.observations:
                o.realtime_start = o.realtime_end = None
        res.warnings.append("FRED: too many vintage dates; stored current values only, no vintage history "
                            "(point-in-time unavailable for this series)")
        return res

    def _fetch(self, req: SeriesRequest, key: str, vintages: bool) -> FetchResult:
        res, offset = FetchResult(), 0
        while True:
            params = {"series_id": req.source_series_id, "file_type": "json", "limit": PAGE, "offset": offset}
            if vintages:
                params.update(realtime_start="1776-07-04", realtime_end="9999-12-31")
            r = self.http.get(BASE, params={**params, "api_key": key})
            if r.status != 200:
                raise ProviderError(f"FRED HTTP {r.status} for {req.source_series_id}: {r.content[:300]!r}")
            obs, count = self.parse(r.content, req)
            res.pages.append(FetchedPage(BASE, params, r.status, r.content, r.content_type or "application/json", obs))
            offset += PAGE
            if offset >= count:
                break
        return res

    @staticmethod
    def parse(content: bytes, req: SeriesRequest) -> tuple[list[RawObs], int]:
        try:
            doc = json.loads(content)
        except ValueError as e:
            raise ProviderError(f"FRED returned non-JSON: {e}")
        if "observations" not in doc:
            raise ProviderError(f"FRED error: {doc.get('error_message', doc)}")
        field_id = req.fields[0]
        out = []
        for o in doc["observations"]:
            out.append(RawObs(
                field_id=field_id, obs_date_raw=o.get("date"), observation_date=parse_obs_date(o.get("date")),
                value_raw=o.get("value"), value_num=to_float(o.get("value")),
                realtime_start=parse_obs_date(o.get("realtime_start")),
                realtime_end=parse_obs_date(o.get("realtime_end")),
            ))
        return out, int(doc.get("count", len(out)))
