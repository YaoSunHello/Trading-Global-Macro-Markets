from __future__ import annotations

import csv
import io
from datetime import date

from ..http import ProviderError
from ..timeutil import parse_obs_date
from .base import FetchedPage, FetchResult, ProviderAdapter, RawObs, SeriesRequest, to_float

BASE = "https://data-api.ecb.europa.eu/service/data"
ATTR_COLS = ("OBS_STATUS", "OBS_CONF", "UNIT", "UNIT_MULT", "DECIMALS")


class EcbAdapter(ProviderAdapter):
    """ECB Data Portal SDMX REST API (no key). source_series_id is '<FLOW>/<KEY>', e.g.
    'EXR/D.USD.EUR.SP00.A'. No vintages or publication timestamps -> ingestion-time availability only."""

    provider_id = "ecb"
    incremental = "overlap"

    def fetch(self, req: SeriesRequest, since: date | None = None, until: date | None = None) -> FetchResult:
        url = f"{BASE}/{req.source_series_id}"
        params: dict = {"format": "csvdata"}
        if since:
            params["startPeriod"] = since.isoformat()
        if until:
            params["endPeriod"] = until.isoformat()
        r = self.http.get(url, params=params, headers={"Accept": "text/csv"})
        if r.status == 404:   # SDMX: no data for the requested window
            return FetchResult(pages=[FetchedPage(url, params, r.status, r.content, r.content_type, [])],
                               warnings=["ECB returned 404 (no data for window)"])
        if r.status != 200:
            raise ProviderError(f"ECB HTTP {r.status} for {req.source_series_id}: {r.content[:200]!r}")
        return FetchResult(pages=[FetchedPage(url, params, r.status, r.content, r.content_type or "text/csv",
                                              self.parse(r.content, req))])

    @staticmethod
    def parse(content: bytes, req: SeriesRequest) -> list[RawObs]:
        rows = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
        if not rows.fieldnames or "TIME_PERIOD" not in rows.fieldnames or "OBS_VALUE" not in rows.fieldnames:
            raise ProviderError("ECB CSV missing TIME_PERIOD/OBS_VALUE columns")
        field_id = req.fields[0]
        return [RawObs(field_id=field_id, obs_date_raw=r["TIME_PERIOD"],
                       observation_date=parse_obs_date(r["TIME_PERIOD"]),
                       value_raw=r["OBS_VALUE"], value_num=to_float(r["OBS_VALUE"]),
                       source_attrs={c: r[c] for c in ATTR_COLS if r.get(c)})
                for r in rows]
