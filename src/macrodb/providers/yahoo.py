from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from ..http import ProviderError
from .base import FetchedPage, FetchResult, ProviderAdapter, RawObs, SeriesRequest, to_float

BASE = "https://query1.finance.yahoo.com/v8/finance/chart"


class YahooAdapter(ProviderAdapter):
    """Yahoo Finance chart endpoint (daily). UNOFFICIAL and subject to Yahoo's terms: Yahoo data is for
    personal use; disabled by default in providers.yaml. Raw JSON is preserved (a thin wrapper over the
    same endpoint yfinance uses). Values are kept as the source's decimal text (parse_float=str).
    adj_close is retroactively restated by Yahoo on splits/dividends; every restatement is appended as
    a new Bronze row (ingestion-time availability only)."""

    provider_id = "yahoo"
    incremental = "overlap"

    def fetch(self, req: SeriesRequest, since: date | None = None, until: date | None = None) -> FetchResult:
        url = f"{BASE}/{req.source_series_id}"
        p1 = int(datetime.combine(since or date(1970, 1, 2), datetime.min.time(), timezone.utc).timestamp())
        p2 = int(datetime.combine((until or date.today()) + timedelta(days=1), datetime.min.time(),
                                  timezone.utc).timestamp())
        params = {"period1": p1, "period2": p2, "interval": "1d", "events": "div,splits"}
        r = self.http.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"})
        if r.status != 200:
            raise ProviderError(f"Yahoo HTTP {r.status} for {req.source_series_id}: {r.content[:200]!r}")
        return FetchResult(pages=[FetchedPage(url, params, r.status, r.content, r.content_type or "application/json",
                                              self.parse(r.content, req))])

    @staticmethod
    def parse(content: bytes, req: SeriesRequest) -> list[RawObs]:
        try:
            doc = json.loads(content, parse_float=str)
            result = doc["chart"]["result"]
        except (ValueError, KeyError, TypeError):
            raise ProviderError("Yahoo: unexpected payload")
        if not result:
            raise ProviderError(f"Yahoo error: {doc['chart'].get('error')}")
        res = result[0]
        ts = res.get("timestamp") or []
        offset = int(res["meta"].get("gmtoffset", 0))
        ind = res["indicators"]
        series = {k: v for k, v in (ind.get("quote") or [{}])[0].items()}
        if ind.get("adjclose"):
            series["adj_close"] = ind["adjclose"][0].get("adjclose", [])
        out = []
        for f in req.fields:
            vals = series.get(f)
            if vals is None:
                continue
            for t, v in zip(ts, vals):
                d = (datetime.fromtimestamp(t, timezone.utc) + timedelta(seconds=offset)).date()
                raw = None if v is None else str(v)
                out.append(RawObs(field_id=f, obs_date_raw=d.isoformat(), observation_date=d,
                                  value_raw="" if raw is None else raw, value_num=to_float(raw),
                                  observation_ts=datetime.fromtimestamp(t, timezone.utc).replace(tzinfo=None)))
        return out
