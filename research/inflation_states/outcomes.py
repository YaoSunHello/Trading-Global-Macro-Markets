"""Stage 2 - ECONOMIC RELEVANCE. Reads the frozen state history; never alters a definition.

Contemporaneous description (return over the 3 months ENDING at the decision date) is kept apart from FUTURE outcomes
(returns / drawdowns starting at the close one session after the decision date, i.e. after the state was observable).
Total-return wealth is used for investor drawdowns; cash-relative wealth (wealth / T-bill wealth) is labelled as such."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import targets as T
from ..data import asof_snapshot
from ..stats import adjust_pvalues
from . import boot, spec as S

# Table 5.1 of the book (Bloomberg index, excess of 3m T-bills), reproduced only as a reference for comparison.
BOOK_TABLE_5_1 = pd.DataFrame([
    ("1973-02-02", "1974-09-27", -0.074, 0.122), ("1977-01-03", "1981-09-30", -0.255, 0.146), ("1986-09-01", "1987-10-29", -0.091, 0.053),
    ("1993-11-01", "1994-11-21", -0.090, 0.031), ("1998-10-06", "2000-01-12", -0.102, 0.038), ("2008-12-19", "2009-06-10", -0.073, 0.028),
    ("2016-07-11", "2018-11-08", -0.074, 0.029), ("2020-08-05", "2023-10-19", -0.231, 0.090)],
    columns=["book_peak", "book_trough", "book_drawdown_cash_relative", "book_cpi_peak"])
BOOK_TABLE_5_1["book_peak"] = pd.to_datetime(BOOK_TABLE_5_1["book_peak"])


# ------------------------------------------------------------------------------------------- wealth series
class Treasury:
    """Daily total-return and T-bill wealth for the two targets."""

    def __init__(self, inp, sessions: pd.DatetimeIndex):
        dtb3 = inp.daily("US.TBILL.3M.DISCOUNT")
        y8 = T.interp_cmt(inp.daily("US.TREASURY.CMT.5Y"), inp.daily("US.TREASURY.CMT.10Y"), 8.0).dropna()
        self.wealth, self.bill = {}, {}
        # model-estimated synthetic: one-day par-bond holding return from consecutive CMT observations (calendar-day accrual)
        d = y8.index.to_series().diff().dt.days.iloc[1:].values
        r = T.par_bond_return(y8.values[:-1] / 100.0, y8.values[1:] / 100.0, 8.0, d / 365.0)
        self.wealth["SYN8Y"] = pd.Series(np.cumprod(1 + r), index=y8.index[1:])
        self.bill["SYN8Y"] = self._bill(dtb3, self.wealth["SYN8Y"].index)
        px = inp.daily("IEF.adj_close")
        self.wealth["IEF"] = px / px.iloc[0]
        self.bill["IEF"] = self._bill(dtb3, px.index)

    @staticmethod
    def _bill(dtb3: pd.Series, idx: pd.DatetimeIndex) -> pd.Series:
        rate = dtb3.reindex(dtb3.index.union(idx)).ffill().reindex(idx)
        days = idx.to_series().diff().dt.days.fillna(0).values
        rf = np.array([T.tbill_investment_yield(x) if np.isfinite(x) else 0.0 for x in rate.shift(1).fillna(rate.iloc[0]).values]) * days / 365.0
        return pd.Series(np.cumprod(1 + rf), index=idx)

    def at(self, target: str, date, kind="wealth"):
        W = self.wealth[target] if kind == "wealth" else self.bill[target]
        i = W.index.searchsorted(pd.Timestamp(date), side="right") - 1
        if i < 0 or (pd.Timestamp(date) - W.index[i]).days > 5:
            return np.nan
        return float(W.iloc[i])

    def ret(self, target, d0, d1, kind="tr") -> float:
        if pd.isna(d0) or pd.isna(d1):
            return np.nan
        w0, w1 = self.at(target, d0), self.at(target, d1)
        if kind == "tr":
            return w1 / w0 - 1.0
        b0, b1 = self.at(target, d0, "bill"), self.at(target, d1, "bill")
        return (w1 / w0 - 1.0) - (b1 / b0 - 1.0)          # excess return over T-bill (difference)

    def mdd(self, target, d0, d1, relative=False) -> float:
        W = self.wealth[target]
        w = W[(W.index >= pd.Timestamp(d0)) & (W.index <= pd.Timestamp(d1))]
        if relative:
            w = w / self.bill[target].reindex(w.index)
        if len(w) < 3:
            return np.nan
        return float((w / w.cummax() - 1.0).min())


def max_drawdown(w: pd.Series) -> float:
    return float((w / w.cummax() - 1.0).min())


def drawdown_episodes(w: pd.Series, min_depth: float = S.DRAWDOWN_MIN) -> pd.DataFrame:
    """Peak -> trough -> recovery (first date wealth regains the peak). Depth measured on whatever wealth is passed in."""
    rows = []
    peak_i, peak_v, in_dd, trough_i, trough_v = 0, w.iloc[0], False, 0, w.iloc[0]
    vals, idx = w.values, w.index
    for i, v in enumerate(vals):
        if v >= peak_v:
            if in_dd and trough_v / peak_v - 1 <= min_depth:
                rows.append((idx[peak_i], idx[trough_i], idx[i], trough_v / peak_v - 1))
            peak_i, peak_v, in_dd, trough_i, trough_v = i, v, False, i, v
        else:
            in_dd = True
            if v < trough_v:
                trough_i, trough_v = i, v
    if in_dd and trough_v / peak_v - 1 <= min_depth:
        rows.append((idx[peak_i], idx[trough_i], pd.NaT, trough_v / peak_v - 1))
    return pd.DataFrame(rows, columns=["peak", "trough", "recovery", "depth"])


# ------------------------------------------------------------------------------------------- fed policy state
def fed_state_panel(versions: pd.DataFrame, decisions: pd.DatetimeIndex, window=6, band=0.5) -> pd.DataFrame:
    """Policy state from the effective Fed funds rate. ALFRED starts 1996-12: earlier values are back-filled, so their
    availability is ASSUMED to be the first day after month end (the rate is essentially unrevised). Flagged per row."""
    v = versions.copy()
    me = v["observation_date"] + pd.offsets.MonthEnd(0)
    backfill = (v["observation_date"] < "1996-10-01") & (v["availability_ts"] <= "1996-12-31")
    v.loc[backfill, "availability_ts"] = me[backfill] + pd.Timedelta(days=1)
    rows = []
    for F in decisions:
        s = asof_snapshot(v, F)
        if s.empty:
            continue
        x = s["value"].astype(float)
        t = x.index.max()
        prev = x.get(t - pd.DateOffset(months=window), np.nan)
        chg = x[t] - prev if pd.notna(prev) else np.nan
        st = "unknown" if pd.isna(chg) else "tightening" if chg >= band - 1e-9 else "easing" if chg <= -band + 1e-9 else "hold"
        rows.append(dict(decision_date=F, fed_obs_month=t, fed_rate=x[t], fed_change=chg, fed_state=st,
                         fed_availability_basis="assumed_month_end_plus_1d" if bool(backfill[(v.observation_date == t)].any()) and t < pd.Timestamp("1996-10-01")
                         else "source_verified_vintage"))
    return pd.DataFrame(rows).set_index("decision_date")


# ------------------------------------------------------------------------------------------- forward / contemporaneous returns
def build_grid(tr: Treasury, cal, decisions: pd.DatetimeIndex) -> pd.DataFrame:
    ex = pd.Series(cal.exec_dates, index=cal.formation)
    pos = {d: i for i, d in enumerate(cal.formation)}
    rows = []
    for F in decisions:
        i = pos[F]
        r = dict(decision_date=F, exec_date=ex.iloc[i])
        for tg in S.TARGETS:
            for h in S.HORIZONS:
                j = i + h
                d1 = ex.iloc[j] if j < len(ex) else pd.NaT
                r[f"fwd_{tg}_{h}"] = tr.ret(tg, ex.iloc[i], d1, "excess")
                r[f"fwdtr_{tg}_{h}"] = tr.ret(tg, ex.iloc[i], d1, "tr")
            j = i + 12
            d1 = ex.iloc[j] if j < len(ex) else pd.NaT
            r[f"fwd_mdd12_{tg}"] = tr.mdd(tg, ex.iloc[i], d1) if pd.notna(d1) and pd.notna(ex.iloc[i]) else np.nan
            r[f"fwd_mdd12_rel_{tg}"] = tr.mdd(tg, ex.iloc[i], d1, relative=True) if pd.notna(d1) and pd.notna(ex.iloc[i]) else np.nan
            k = i - 3
            r[f"contemp3_{tg}"] = tr.ret(tg, cal.formation[k], F, "excess") if k >= 0 else np.nan
        rows.append(r)
    return pd.DataFrame(rows).set_index("decision_date")


# ------------------------------------------------------------------------------------------- conditional tables
def label_spells(lab: pd.Series) -> dict:
    """Number of contiguous runs per label (NaN/None breaks a run)."""
    out, prev = {}, None
    for v in lab.values:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            prev = None; continue
        if v != prev:
            out[v] = out.get(v, 0) + 1
        prev = v
    return out


def cond_stats(y: pd.Series, mdd: pd.Series, lab: pd.Series, h: int, sigma: float) -> pd.DataFrame:
    """Statistics of y (excess return over horizon h) by label. 'ALL' = unconditional on the same rows."""
    d = pd.concat([y, mdd, lab], axis=1, keys=["y", "mdd", "lab"]).dropna(subset=["y", "lab"])
    spells = label_spells(lab[lab.index.isin(d.index)])
    rows = []
    for name, g in [("ALL", d)] + [(k, x) for k, x in d.groupby("lab")]:
        yy = g["y"]
        k = max(1, int(np.ceil(0.05 * len(yy))))
        rows.append(dict(cell=name, n_months=len(yy), n_spells=(spells.get(name, 0) if name != "ALL" else np.nan),
                         mean_period=yy.mean(), mean_annualised=yy.mean() * 12.0 / h, std_period=yy.std(),
                         downside_freq_lt0=float((yy < 0).mean()), tail_freq_le_minus_1sigma=float((yy <= -sigma).mean()) if sigma > 0 else np.nan,
                         expected_shortfall_5pct=float(yy.nsmallest(k).mean()) if len(yy) >= 40 else np.nan, worst=float(yy.min()), median=float(yy.median()),
                         mean_fwd12m_mdd=float(g["mdd"].mean()) if g["mdd"].notna().any() else np.nan,
                         median_fwd12m_mdd=float(g["mdd"].median()) if g["mdd"].notna().any() else np.nan,
                         share_fwd12m_mdd_le_minus5pct=float((g["mdd"] <= S.DRAWDOWN_MIN).mean()) if g["mdd"].notna().any() else np.nan,
                         sufficient=bool(len(yy) >= S.MIN_MONTHS_CELL and (name == "ALL" or (spells.get(name, 0) >= S.MIN_SPELLS_CELL)))))
    return pd.DataFrame(rows)


_IDX_CACHE: dict = {}


def _boot_idx(n: int, block: float) -> np.ndarray:
    key = (n, block)
    if key not in _IDX_CACHE:
        _IDX_CACHE[key] = boot.stationary_indices(n, block, S.BOOTSTRAP["reps"], boot.rng())
    return _IDX_CACHE[key]


def contrast(y: pd.Series, a: pd.Series, b: pd.Series, h: int) -> dict:
    """Mean(y | a) - mean(y | b), annualised; stationary block bootstrap (block = max(12, 2h)) over (y, a, b) jointly."""
    d = pd.concat([y, a.astype(float), b.astype(float)], axis=1, keys=["y", "a", "b"]).dropna()
    yv, av, bv = d["y"].values, d["a"].values.astype(bool), d["b"].values.astype(bool)
    na, nb = int(av.sum()), int(bv.sum())
    out = dict(n_total=len(d), n_a=na, n_b=nb)
    if na < 2 or nb < 2:
        return dict(out, diff_annualised=np.nan, ci_lo=np.nan, ci_hi=np.nan, p_boot=np.nan, effect_size=np.nan)
    est = (yv[av].mean() - yv[bv].mean()) * 12.0 / h
    idx = _boot_idx(len(d), max(S.BOOTSTRAP["min_block"], 2 * h))
    Y, A, B = yv[idx], av[idx].astype(float), bv[idx].astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        dist = ((Y * A).sum(1) / A.sum(1) - (Y * B).sum(1) / B.sum(1)) * 12.0 / h
    dist = dist[np.isfinite(dist)]
    return dict(out, diff_annualised=float(est), ci_lo=float(np.quantile(dist, 0.025)), ci_hi=float(np.quantile(dist, 0.975)),
                p_boot=boot.boot_p(est, dist), effect_size=float(est / (yv.std() * np.sqrt(12.0 / h))) if yv.std() > 0 else np.nan,
                mean_a_annualised=float(yv[av].mean() * 12.0 / h), mean_b_annualised=float(yv[bv].mean() * 12.0 / h))


def spells_in(mask: pd.Series) -> int:
    return label_spells(mask.map({True: "x", False: None}))["x"] if mask.any() else 0
