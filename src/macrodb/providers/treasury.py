from __future__ import annotations

import json
from datetime import date

from ..http import ProviderError
from ..timeutil import parse_obs_date
from .base import FetchedPage, FetchResult, ProviderAdapter, RawObs, SeriesRequest, to_float

BASE = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"


class TreasuryFiscalDataAdapter(ProviderAdapter):
    """U.S. Treasury FiscalData API (no key). One catalog entry selects an endpoint, a date field, a
    value field and equality filters via `params`:
      {endpoint: 'v2/accounting/od/avg_interest_rates', date_field: record_date,
       value_field: avg_interest_rate_amt, filters: {security_desc: 'Treasury Notes'}}
    FiscalData is not vintage-tracked: ingestion-time availability only."""

    provider_id = "treasury"
    incremental = "overlap"

    def fetch(self, req: SeriesRequest, since: date | None = None, until: date | None = None) -> FetchResult:
        p = req.params
        try:
            endpoint, dfield, vfield = p["endpoint"], p["date_field"], p["value_field"]
        except KeyError as e:
            raise ProviderError(f"treasury params missing {e}")
        flt = [f"{k}:eq:{v}" for k, v in (p.get("filters") or {}).items()]
        if since:
            flt.append(f"{dfield}:gte:{since.isoformat()}")
        if until:
            flt.append(f"{dfield}:lte:{until.isoformat()}")
        url = f"{BASE}/{endpoint}"
        res, page = FetchResult(), 1
        while True:
            params = {"sort": dfield, "page[size]": 10000, "page[number]": page}
            if flt:
                params["filter"] = ",".join(flt)
            r = self.http.get(url, params=params)
            if r.status != 200:
                raise ProviderError(f"Treasury HTTP {r.status}: {r.content[:200]!r}")
            obs, pages = self.parse(r.content, req, dfield, vfield)
            res.pages.append(FetchedPage(url, params, r.status, r.content, r.content_type or "application/json", obs))
            if page >= pages:
                break
            page += 1
        return res

    @staticmethod
    def parse(content: bytes, req: SeriesRequest, dfield: str, vfield: str) -> tuple[list[RawObs], int]:
        try:
            doc = json.loads(content)
        except ValueError as e:
            raise ProviderError(f"Treasury returned non-JSON: {e}")
        if "data" not in doc:
            raise ProviderError(f"Treasury error: {doc.get('error', doc)}")
        out = [RawObs(field_id=req.fields[0], obs_date_raw=row.get(dfield),
                      observation_date=parse_obs_date(row.get(dfield)),
                      value_raw=row.get(vfield), value_num=to_float(row.get(vfield)))
               for row in doc["data"]]
        return out, int(doc.get("meta", {}).get("total-pages", 1) or 1)
