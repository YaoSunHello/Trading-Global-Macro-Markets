"""Database-only loaders: official Silver facts and explicitly approved, gap-only estimates."""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from macrodb import MacroDB
from macrodb.estimates import estimate_mask

NY = "America/New_York"
MARKET_PUBLICATION_HOUR = 16.5       # H.15 yields for day d are assumed public at 16:30 ET on the NEXT session
CPI_RELEASE_HOUR = 8.5               # BLS releases at 08:30 ET on the vintage date
CLOSE_HOUR = 16.0


def ts(d, hour: float) -> pd.Timestamp:
    """Date -> tz-aware New York timestamp at the given hour (ISO 8601 via .isoformat())."""
    return (pd.Timestamp(d).normalize() + pd.Timedelta(hours=hour)).tz_localize(NY)


def iso(t) -> str:
    return "" if t is None or pd.isna(t) else pd.Timestamp(t).isoformat()


class Inputs:
    """Thin read layer over MacroDB with the conventions used by the research code."""

    def __init__(self, db: MacroDB | None = None, include_estimates: bool = True):
        self.db = db or MacroDB()
        self.include_estimates = include_estimates
        warnings.simplefilter("ignore")

    def daily(self, sid: str) -> pd.Series:
        """Latest version, ok+suspect rows (outlier-flagged values are kept: they are flagged, not wrong)."""
        d = self.db.get(sid, quality="usable", include_estimates=self.include_estimates)
        return d.set_index("observation_date")["value"].astype(float).dropna().sort_index()

    def versions(self, sid: str) -> pd.DataFrame:
        """Source versions plus approved estimates; estimate-aware snapshots preserve official precedence."""
        return self.db.get(sid, vintage="all", quality="all", include_estimates=self.include_estimates)

    def pit_status(self, sid: str) -> dict:
        r = self.db.pit_status(sid).iloc[0]
        return r.to_dict()


def asof_snapshot(v: pd.DataFrame, when: pd.Timestamp, hour: float = CPI_RELEASE_HOUR) -> pd.DataFrame:
    """The vintage of a series as known at `when` (date): rows with realtime_start <= when. ALFRED vintage dates are
    day-granular, so source releases on formation dates are known. Estimates must exist by the 16:00 ET close."""
    d = v[v["availability_ts"] < pd.Timestamp(when).normalize() + pd.Timedelta(days=1)]
    estimated = d[estimate_mask(d)]
    if not estimated.empty:
        from macrodb.estimates import fill_missing
        cutoff = ts(when, CLOSE_HOUR).tz_convert("UTC").tz_localize(None)
        estimated = estimated[estimated.availability_ts <= cutoff].sort_values(
            ["availability_ts", "bronze_id"]).drop_duplicates("observation_date", keep="last")
        d = d[~estimate_mask(d)]
        d = d.sort_values(["availability_ts", "bronze_id"]).drop_duplicates("observation_date", keep="last")
        d = fill_missing(d, estimated, keys=("observation_date",))
    d = d.sort_values(["availability_ts", "bronze_id"]).drop_duplicates("observation_date", keep="last")
    d = d[d["value"].notna() & (d["dq_status"].isin(["ok", "suspect"]))]
    return d.set_index("observation_date").sort_index()


def asof_value(s: pd.Series, date: pd.Timestamp, tol_days: int = 5):
    """Last observation on or before `date` within tol_days -> (value, observation_date) or (nan, NaT)."""
    i = s.index.searchsorted(pd.Timestamp(date), side="right") - 1
    if i < 0 or (pd.Timestamp(date) - s.index[i]).days > tol_days:
        return np.nan, pd.NaT
    return float(s.iloc[i]), s.index[i]
