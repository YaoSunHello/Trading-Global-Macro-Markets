"""Point-in-time CPI panel. For every monthly decision date F the as-of vintage (ALFRED, rows with availability <= F) is
rebuilt from scratch, inflation measures are computed on THAT vintage only, and calibration thresholds use only months
strictly before the observation month. Also builds the retrospective (latest-revised) panel for revision comparison.

Observation date (the month CPI describes) != vintage/release date != decision date. All three are retained."""
from __future__ import annotations

import numpy as np
import pandas as pd
from macrodb.estimates import estimate_mask

from ..data import asof_snapshot, iso, ts
from . import spec as S

MEASURE_COLS = ["yoy", "dyoy3", "dyoy6", "gap3", "gap6", "ann3", "ann6", "yoy_sm3"]


def derived(s: pd.Series) -> pd.DataFrame:
    """Measures on a monthly index series (index = month-start dates). Missing months stay NaN (no interpolation)."""
    if s.empty:
        return pd.DataFrame(columns=["idx"] + MEASURE_COLS)
    s = s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="MS"))
    d = pd.DataFrame({"idx": s})
    d["yoy"] = (s / s.shift(12) - 1.0) * 100.0
    d["ann3"] = ((s / s.shift(3)) ** 4 - 1.0) * 100.0
    d["ann6"] = ((s / s.shift(6)) ** 2 - 1.0) * 100.0
    d["dyoy3"] = d["yoy"] - d["yoy"].shift(3)
    d["dyoy6"] = d["yoy"] - d["yoy"].shift(6)
    d["gap3"] = d["ann3"] - d["yoy"]
    d["gap6"] = d["ann6"] - d["yoy"]
    d["yoy_sm3"] = d["yoy"].rolling(3, min_periods=3).mean()
    return d


def thresholds(yoy_prior: pd.Series) -> dict:
    """Percentile thresholds from yoy values STRICTLY BEFORE the observation month (past-only)."""
    h = yoy_prior.dropna()
    out = {}
    for tag, start in S.EXPANDING_STARTS.items():
        hh = h if start is None else h[h.index >= pd.Timestamp(start)]
        n = len(hh)
        ok = n >= S.MIN_HISTORY_MONTHS
        out[f"q25_exp_{tag}"] = float(np.quantile(hh, 0.25)) if ok else np.nan
        out[f"q75_exp_{tag}"] = float(np.quantile(hh, 0.75)) if ok else np.nan
        out[f"n_exp_{tag}"] = n
    for w in S.ROLL_WINDOWS:
        hh = h.iloc[-w:]
        ok = len(hh) >= w
        out[f"q25_roll{w}"] = float(np.quantile(hh, 0.25)) if ok else np.nan
        out[f"q75_roll{w}"] = float(np.quantile(hh, 0.75)) if ok else np.nan
    return out


def _row_from_derived(d: pd.DataFrame, t: pd.Timestamp) -> dict:
    r = d.loc[t, MEASURE_COLS + ["idx"]].to_dict()
    r.update(idx_t12=d["idx"].get(t - pd.DateOffset(years=1), np.nan), idx_t3=d["idx"].get(t - pd.DateOffset(months=3), np.nan),
             idx_t6=d["idx"].get(t - pd.DateOffset(months=6), np.nan))
    r.update(thresholds(d["yoy"].loc[: t - pd.DateOffset(months=1)]))
    return r


def coverage_audit(versions: pd.DataFrame, series_id: str) -> dict:
    """How much of the vintage archive is genuine real-time data. An observation whose FIRST appearance in the archive
    is more than 45 days after its month end entered the archive in a back-fill (archive start), not at its release."""
    official = versions[~estimate_mask(versions)]
    v = official[official["value"].notna() & official["dq_status"].isin(["ok", "suspect"])]
    first = v.groupby("observation_date")["availability_ts"].min()
    lag = (first - (first.index + pd.offsets.MonthEnd(0))).dt.days
    bad = lag[lag > S.GENUINE_FIRST_RELEASE_MAX_LAG_DAYS]
    last_bad = bad.index.max() if len(bad) else pd.NaT
    first_genuine_obs = (lag[lag.index > last_bad].index.min() if pd.notna(last_bad) else lag.index.min())
    first_vintage = v["availability_ts"].min()
    return dict(series_id=series_id, first_vintage_date=first_vintage.date(), n_obs=int(len(first)),
                n_obs_first_seen_late=int(len(bad)), last_backfilled_obs=last_bad.date() if pd.notna(last_bad) else "",
                first_genuine_release_obs=first_genuine_obs.date(), n_obs_genuine=int((lag.index >= first_genuine_obs).sum()),
                median_first_release_lag_days_genuine=float(lag[lag.index >= first_genuine_obs].median()),
                max_first_release_lag_days_genuine=int(lag[lag.index >= first_genuine_obs].max()),
                note="Observations before first_genuine_release_obs are present in the earliest vintage as back-fill: their values are usable as history "
                     "inside a vintage, but the decision dates before first_vintage_date are excluded from the primary analysis.")


def build_panel(versions: pd.DataFrame, decisions: pd.DatetimeIndex, series_id: str, measure: str,
                keep_derived: bool = True):
    """Returns (panel, snaps). panel: one row per decision date with a usable vintage. snaps: {F: derived frame}."""
    v = versions[versions["value"].notna()]
    first_release = v[v["dq_status"].isin(["ok", "suspect"])].groupby("observation_date")["availability_ts"].min()
    rows, snaps = [], {}
    for F in decisions:
        snap = asof_snapshot(versions, F)
        if snap.empty:
            continue
        s = snap["value"].astype(float)
        d = derived(s)
        t = s.index.max()
        r = _row_from_derived(d, t)
        av = snap.loc[t, "availability_ts"]
        r.update(decision_date=F, measure=measure, series_id=series_id, obs_month=t,
                 period_end=t + pd.offsets.MonthEnd(0), decision_ts=ts(F, 16.0),
                 vintage_date=pd.Timestamp(av).normalize(), release_ts=ts(av, S.CPI_RELEASE_HOUR),
                 first_release_ts=ts(first_release[t], S.CPI_RELEASE_HOUR),
                 info_lag_days=int((F - (t + pd.offsets.MonthEnd(0))).days), n_obs_in_vintage=int(len(s)),
                 availability_basis="source_verified_vintage")
        estimated = snap[estimate_mask(snap)]
        if not estimated.empty:
            latest_is_estimate = "ESTIMATED" in snap.loc[t, "dq_flags"]
            if latest_is_estimate:
                r["release_ts"] = pd.Timestamp(av).tz_localize("UTC").tz_convert("America/New_York")
                r["first_release_ts"] = r["release_ts"]
            r.update(availability_basis="source_verified_vintage_with_estimated_history",
                     n_estimated_inputs=len(estimated),
                     estimated_observation_months="|".join(str(d.date()) for d in estimated.index),
                     input_availability_ts=max(r["release_ts"], pd.Timestamp(
                         estimated.availability_ts.max()).tz_localize("UTC").tz_convert("America/New_York")))
        rows.append(r)
        if keep_derived:
            snaps[F] = d
    panel = pd.DataFrame(rows).set_index("decision_date")
    return panel, snaps


def build_retro(versions: pd.DataFrame, last_decision: pd.Timestamp) -> pd.DataFrame:
    """RETROSPECTIVE panel: the latest-revised history, indexed by observation month, thresholds still past-only within it."""
    snap = asof_snapshot(versions, last_decision)
    d = derived(snap["value"].astype(float))
    rows = {}
    for t in d.index:
        if np.isnan(d.loc[t, "yoy"]):
            continue
        rows[t] = _row_from_derived(d, t)
    return pd.DataFrame(rows).T.astype(float)


def revision_scales(panel: pd.DataFrame, snaps: dict) -> pd.DataFrame:
    """Past-only revision scale per measure column: expanding p90 of |real-time - matured| where 'matured' is the same
    observation month in the vintage known 13 decision dates later. At decision k only pairs with j + 13 <= k are used."""
    dec = list(panel.index)
    pairs = {c: [] for c in ("yoy", "dyoy3", "dyoy6", "gap3", "gap6")}
    for j, F in enumerate(dec):
        if j + S.REVISION_MATURITY_MONTHS >= len(dec):
            for c in pairs:
                pairs[c].append(np.nan)
            continue
        t = panel.loc[F, "obs_month"]
        later = snaps[dec[j + S.REVISION_MATURITY_MONTHS]]
        for c in pairs:
            a, b = panel.loc[F, c], later[c].get(t, np.nan)
            pairs[c].append(abs(a - b) if pd.notna(a) and pd.notna(b) else np.nan)
    out = {}
    for c, arr in pairs.items():
        ser = pd.Series(arr, index=dec)
        sc = []
        for k in range(len(dec)):
            known = ser.iloc[: max(0, k - S.REVISION_MATURITY_MONTHS + 1)].dropna()
            sc.append(float(np.quantile(known, 0.90)) if len(known) >= 24 else np.nan)
        out[f"rev_abs_{c}"] = ser
        out[f"rev_p90_{c}"] = pd.Series(sc, index=dec)
        out[f"rev_scale_{c}"] = pd.Series(sc, index=dec).fillna(S.REVISION_PRIOR[c]).clip(lower=0.02)
        out[f"rev_scale_is_prior_{c}"] = pd.Series(sc, index=dec).isna()
    return pd.DataFrame(out)
