from __future__ import annotations

import csv
import io
from datetime import date

from ..http import ProviderError
from ..timeutil import parse_obs_date
from .base import FetchedPage, FetchResult, ProviderAdapter, RawObs, SeriesRequest, to_float

URL = "https://stooq.com/q/d/l/"
COLS = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}


class StooqAdapter(ProviderAdapter):
    """Stooq daily CSV download. As of 2026-11 Stooq fronts the endpoint with a JavaScript proof-of-work
    challenge, so unauthenticated programmatic access returns HTML. The adapter detects this and raises
    a clear ProviderError instead of storing junk. If Stooq issues an apikey, set STOOQ_API_KEY
    (see docs/PROVIDERS.md). Disabled by default."""

    provider_id = "stooq"
    incremental = "overlap"

    def fetch(self, req: SeriesRequest, since: date | None = None, until: date | None = None) -> FetchResult:
        params = {"s": req.source_series_id.lower(), "i": "d"}
        if since:
            params["d1"] = since.strftime("%Y%m%d")
        if until:
            params["d2"] = until.strftime("%Y%m%d")
        key = self.credential()
        r = self.http.get(URL, params={**params, **({"apikey": key} if key else {})})
        if r.status != 200:
            raise ProviderError(f"Stooq HTTP {r.status}")
        return FetchResult(pages=[FetchedPage(URL, params, r.status, r.content, r.content_type or "text/csv",
                                              self.parse(r.content, req))])

    @staticmethod
    def parse(content: bytes, req: SeriesRequest) -> list[RawObs]:
        text = content.decode("utf-8-sig", errors="replace")
        head = text.lstrip()[:20].lower()
        if head.startswith("<!doctype") or head.startswith("<html"):
            raise ProviderError("Stooq returned an HTML page (JavaScript/anti-bot challenge or apikey "
                                "required); programmatic CSV access unavailable")
        if text.strip().lower().startswith("no data"):
            return []
        rows = csv.DictReader(io.StringIO(text))
        if not rows.fieldnames or "Date" not in rows.fieldnames:
            raise ProviderError("Stooq CSV missing Date column")
        out = []
        for r in rows:
            for f in req.fields:
                col = COLS.get(f)
                if col and col in r:
                    out.append(RawObs(field_id=f, obs_date_raw=r["Date"], observation_date=parse_obs_date(r["Date"]),
                                      value_raw=r[col], value_num=to_float(r[col])))
        return out
