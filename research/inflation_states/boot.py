"""Time-series resampling and agreement/persistence statistics (no look-ahead concepts here; pure statistics)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import spec as S


def rng() -> np.random.Generator:
    return np.random.default_rng(S.BOOTSTRAP["seed"])


def stationary_indices(n: int, mean_block: float, reps: int, g: np.random.Generator) -> np.ndarray:
    """Politis-Romano stationary bootstrap index matrix (reps x n): geometric block lengths, circular wrap."""
    p = 1.0 / max(mean_block, 1.0)
    idx = np.empty((reps, n), dtype=np.int64)
    idx[:, 0] = g.integers(0, n, reps)
    for t in range(1, n):
        new = g.random(reps) < p
        idx[:, t] = np.where(new, g.integers(0, n, reps), (idx[:, t - 1] + 1) % n)
    return idx


def block_ci(stat_fn, arrays: list[np.ndarray], mean_block: float | None = None, reps: int | None = None,
             alpha: float = 0.05) -> tuple[float, float, float, np.ndarray]:
    """Point estimate, percentile CI and the bootstrap distribution of stat_fn(*resampled arrays)."""
    n = len(arrays[0])
    est = float(stat_fn(*arrays))
    if n < 8:
        return est, np.nan, np.nan, np.array([])
    reps = reps or S.BOOTSTRAP["reps"]
    b = mean_block or S.BOOTSTRAP["min_block"]
    idx = stationary_indices(n, b, reps, rng())
    dist = np.array([stat_fn(*[a[i] for a in arrays]) for i in idx])
    dist = dist[np.isfinite(dist)]
    if len(dist) < 20:
        return est, np.nan, np.nan, dist
    return est, float(np.quantile(dist, alpha / 2)), float(np.quantile(dist, 1 - alpha / 2)), dist


def boot_p(est: float, dist: np.ndarray) -> float:
    """Two-sided p-value for H0: statistic = 0 by the centred bootstrap distribution (|d* - est| >= |est|)."""
    if len(dist) < 20 or not np.isfinite(est):
        return np.nan
    return float((1 + np.sum(np.abs(dist - est) >= abs(est))) / (len(dist) + 1))


def weighted_kappa(a: np.ndarray, b: np.ndarray, k: int = 3) -> float:
    """Linearly weighted Cohen's kappa for ordinal states coded 0..k-1 (here shifted from -1,0,1)."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok].astype(int) + 1, b[ok].astype(int) + 1
    if len(a) == 0:
        return np.nan
    O = np.zeros((k, k))
    np.add.at(O, (a, b), 1)
    O /= O.sum()
    E = np.outer(O.sum(1), O.sum(0))
    W = 1.0 - np.abs(np.subtract.outer(np.arange(k), np.arange(k))) / (k - 1)
    po, pe = (W * O).sum(), (W * E).sum()
    return float((po - pe) / (1 - pe)) if pe < 1 else np.nan


def raw_agreement(a, b) -> float:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    return float((a[ok] == b[ok]).mean()) if ok.any() else np.nan


def spells(state: pd.Series) -> pd.DataFrame:
    """Contiguous runs of the same state (a NaN ends a run). length = number of decision dates."""
    rows, cur, start, last, n = [], None, None, None, 0
    for d, s in state.items():
        if np.isnan(s):
            if cur is not None:
                rows.append((cur, start, last, n)); cur = None
            continue
        if cur is not None and s == cur:
            n += 1; last = d
        else:
            if cur is not None:
                rows.append((cur, start, last, n))
            cur, start, last, n = s, d, d, 1
    if cur is not None:
        rows.append((cur, start, last, n))
    return pd.DataFrame(rows, columns=["state", "start", "end", "length"])


def flip_series(state: pd.Series) -> np.ndarray:
    s = state.values
    f = np.zeros(len(s))
    f[1:] = (s[1:] != s[:-1]) & np.isfinite(s[1:]) & np.isfinite(s[:-1])
    return f


def reversal_series(state: pd.Series, within: int = 3) -> np.ndarray:
    """1 at t if the state moved away from its t-1 value at t and was back at that value within `within` months (A -> B -> A)."""
    s = state.values
    r = np.zeros(len(s))
    for t in range(1, len(s)):
        if np.isfinite(s[t]) and np.isfinite(s[t - 1]) and s[t] != s[t - 1]:
            for k in range(1, within + 1):
                if t + k < len(s) and s[t + k] == s[t - 1]:
                    r[t] = 1
                    break
    return r


def persistence_stats(state: pd.Series) -> dict:
    st = state.dropna()
    sp = spells(state)
    f = flip_series(state)[np.isfinite(state.values)]
    rv = reversal_series(state)[np.isfinite(state.values)]
    n = len(st)
    est, lo, hi, _ = block_ci(lambda x: x.mean() * 12.0, [f]) if n > 24 else (np.nan, np.nan, np.nan, None)
    return dict(n_decisions=n, n_spells=len(sp), transitions_per_year=est, transitions_per_year_lo=lo, transitions_per_year_hi=hi,
                mean_spell_months=float(sp["length"].mean()) if len(sp) else np.nan,
                median_spell_months=float(sp["length"].median()) if len(sp) else np.nan,
                share_spells_le2m=float((sp["length"] <= 2).mean()) if len(sp) else np.nan,
                reversals_within_3m=int(rv.sum()), share_time_low=float((st == -1).mean()), share_time_normal=float((st == 0).mean()),
                share_time_high=float((st == 1).mean()))


def zigzag(y: pd.Series, thresh: float) -> pd.DataFrame:
    """Ex-post turning points: alternate peaks/troughs, each confirmed only after a retracement of >= `thresh` (pp).
    RETROSPECTIVE (uses data after each turning point) - used only as a timing reference."""
    y = y.dropna()
    if len(y) < 3:
        return pd.DataFrame(columns=["month", "type", "value"])
    pts = []
    mode, ext_i, ext_v = None, 0, y.iloc[0]
    lo_i, lo_v, hi_i, hi_v = 0, y.iloc[0], 0, y.iloc[0]
    for i, v in enumerate(y.values):
        if v > hi_v: hi_i, hi_v = i, v
        if v < lo_v: lo_i, lo_v = i, v
        if mode is None:
            if hi_v - v >= thresh and hi_i >= lo_i:
                pts.append((y.index[hi_i], "peak", hi_v)); mode = "down"; lo_i, lo_v = i, v
            elif v - lo_v >= thresh and lo_i >= hi_i:
                pts.append((y.index[lo_i], "trough", lo_v)); mode = "up"; hi_i, hi_v = i, v
        elif mode == "down":
            if v < lo_v: lo_i, lo_v = i, v
            if v - lo_v >= thresh:
                pts.append((y.index[lo_i], "trough", lo_v)); mode = "up"; hi_i, hi_v = i, v
        else:
            if v > hi_v: hi_i, hi_v = i, v
            if hi_v - v >= thresh:
                pts.append((y.index[hi_i], "peak", hi_v)); mode = "down"; lo_i, lo_v = i, v
    return pd.DataFrame(pts, columns=["month", "type", "value"])
