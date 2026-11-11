"""Treasury return targets: ETF proxies (observed) and a duration-based synthetic (model-estimated), plus the
evaluation that decides whether a defensible target exists."""
from __future__ import annotations

import numpy as np
import pandas as pd


def par_bond_return(y0: np.ndarray, y1: np.ndarray, n_years: float, tau: np.ndarray) -> np.ndarray:
    """MODEL-ESTIMATED holding-period return of a constant-maturity par-coupon bond (semi-annual coupons).
    Buy at par with coupon = y0 and maturity n; sell after `tau` years (remaining maturity n - tau) at yield y1.
    return = coupon accrual (y0 * tau) + clean price change. Yields are decimals. Ignores roll-down differences
    between the CMT curve and the actual bond universe, accrued-interest conventions and financing."""
    N = 2.0 * (n_years - tau)
    j = y1 / 2.0
    c = y0 / 2.0
    discount = (1.0 + j) ** (-N)
    annuity = np.divide(1.0 - discount, j, out=np.array(N, dtype=float, copy=True), where=j != 0)
    price = c * annuity + discount
    return y0 * tau + (price - 1.0)


def interp_cmt(y5: pd.Series, y10: pd.Series, maturity: float) -> pd.Series:
    """Linear interpolation of the 5Y and 10Y CMT yields (percent) to `maturity` (5 <= maturity <= 10)."""
    return y5 + (maturity - 5.0) / 5.0 * (y10 - y5)


def synthetic_excess_inputs(y5: pd.Series, y10: pd.Series, maturity: float) -> pd.Series:
    return interp_cmt(y5, y10, maturity)


def etf_return(prices: pd.Series, d0: pd.Timestamp, d1: pd.Timestamp) -> float:
    if d0 in prices.index and d1 in prices.index:
        return float(prices[d1] / prices[d0] - 1.0)
    return np.nan


def tbill_investment_yield(d_pct: float) -> float:
    """Discount-basis 3M bill rate (percent) -> bond-equivalent yield (decimal), 91-day bill."""
    d = d_pct / 100.0
    return 365.0 * d / (360.0 - 91.0 * d)


# ---------------------------------------------------------------- grids on the formation calendar
def grid_returns(prices: pd.Series, cal, h: int = 1) -> pd.Series:
    """Total return from the execution close of formation m to that of formation m+h (indexed by formation date m)."""
    ex = cal.exec_dates
    out = []
    for i in range(len(ex)):
        j = i + h
        out.append(etf_return(prices, ex[i], ex[j]) if j < len(ex) and pd.notna(ex[i]) and pd.notna(ex[j]) else np.nan)
    return pd.Series(out, index=cal.formation, name=f"ret_{h}m")


def grid_synthetic(y_pct: pd.Series, cal, n_years: float, h: int = 1) -> pd.Series:
    """MODEL-ESTIMATED par-bond return on the same grid, from CMT yields observed at the execution closes."""
    ex = cal.exec_dates
    out = []
    for i in range(len(ex)):
        j = i + h
        if j >= len(ex) or pd.isna(ex[i]) or pd.isna(ex[j]) or ex[i] not in y_pct.index or ex[j] not in y_pct.index:
            out.append(np.nan); continue
        tau = np.array([(ex[j] - ex[i]).days / 365.0])
        out.append(float(par_bond_return(np.array([y_pct[ex[i]] / 100]), np.array([y_pct[ex[j]] / 100]), n_years, tau)[0]))
    return pd.Series(out, index=cal.formation, name=f"synthetic_{h}m")


def grid_rf(dtb3: pd.Series, cal, h: int = 1) -> pd.Series:
    """Cash accrual over the same window: 3M bill investment yield at the start execution date x elapsed days / 365."""
    ex = cal.exec_dates
    out = []
    for i in range(len(ex)):
        j = i + h
        if j >= len(ex) or pd.isna(ex[i]) or pd.isna(ex[j]):
            out.append(np.nan); continue
        v = dtb3[:ex[i]]
        if v.empty or (ex[i] - v.index[-1]).days > 5:
            out.append(np.nan); continue
        out.append(tbill_investment_yield(v.iloc[-1]) * (ex[j] - ex[i]).days / 365.0)
    return pd.Series(out, index=cal.formation, name=f"rf_{h}m")


def evaluate_targets(rets: dict[str, pd.Series], synth: pd.Series, ety_pct: pd.Series) -> pd.DataFrame:
    """Compare each ETF proxy with the model-estimated series on common months. These are different objects:
    the comparison is a sanity check on the proxy (is it dominated by rate risk?), not an equivalence claim."""
    rows = []
    for name, r in rets.items():
        d = pd.concat([r, synth], axis=1, keys=["etf", "syn"]).dropna()
        if len(d) < 24:
            rows.append(dict(target=name, n_months=len(d))); continue
        beta = np.polyfit(d.syn, d.etf, 1)
        rows.append(dict(target=name, comparison="vs synthetic 8y par bond (model-estimated)", n_months=len(d),
                         first_month=d.index[0].date(), last_month=d.index[-1].date(),
                         corr=d.corr().iloc[0, 1], beta_on_synthetic=beta[0],
                         mean_diff_ann=(d.etf - d.syn).mean() * 12, tracking_error_ann=(d.etf - d.syn).std() * np.sqrt(12),
                         etf_ann_return=d.etf.mean() * 12, etf_ann_vol=d.etf.std() * np.sqrt(12),
                         synth_ann_return=d.syn.mean() * 12, synth_ann_vol=d.syn.std() * np.sqrt(12)))
    return pd.DataFrame(rows)
