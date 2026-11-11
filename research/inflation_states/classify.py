"""Deterministic classification rules, persistence/hysteresis layers and a SEPARATE confidence description.

States are integers: level  -1 low / 0 normal / +1 high;  momentum -1 falling / 0 stable / +1 rising.
Confidence is NOT a probability: threshold rules are deterministic, so only distances/agreement/age are reported."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import spec as S

LEVEL_NAMES = {-1: "low", 0: "normal", 1: "high"}
MOM_NAMES = {-1: "falling", 0: "stable", 1: "rising"}
R = 6          # rounding (pp) before comparing, to avoid float noise at exact thresholds


def level_bounds(df: pd.DataFrame, rule: dict) -> tuple[pd.Series, pd.Series]:
    if rule["kind"] == "fixed":
        return pd.Series(rule["low"], index=df.index), pd.Series(rule["high"], index=df.index)
    key = {"expanding_full": "exp_full", "expanding_from1970": "exp_from1970", "expanding_from1985": "exp_from1985"}.get(rule["scope"], rule["scope"])
    return df[f"q25_{key}"], df[f"q75_{key}"]


def momentum_bounds(df: pd.DataFrame, rule: dict) -> tuple[pd.Series, pd.Series]:
    return pd.Series(-rule["band"], index=df.index), pd.Series(rule["band"], index=df.index)


def measure_series(df: pd.DataFrame, kind: str, rule: dict) -> pd.Series:
    return df["yoy"] if kind == "level" else df[rule["measure"]]


def bounds(df: pd.DataFrame, kind: str, rule: dict):
    return level_bounds(df, rule) if kind == "level" else momentum_bounds(df, rule)


def raw_states(x: pd.Series, lo: pd.Series, hi: pd.Series, kind: str) -> pd.Series:
    """level: low if x < lo, high if x >= hi.  momentum: falling if x < -band, rising if x > +band (neutral band closed)."""
    x, lo, hi = x.round(R), lo.round(R), hi.round(R)
    out = pd.Series(0.0, index=x.index)
    if kind == "level":
        out[x < lo] = -1.0
        out[x >= hi] = 1.0
    else:
        out[x < lo] = -1.0
        out[x > hi] = 1.0
    out[x.isna() | lo.isna() | hi.isna()] = np.nan
    return out


def _raw_one(x, lo, hi, kind):
    if np.isnan(x) or np.isnan(lo) or np.isnan(hi):
        return np.nan
    x, lo, hi = round(x, R), round(lo, R), round(hi, R)
    if kind == "level":
        return -1.0 if x < lo else 1.0 if x >= hi else 0.0
    return -1.0 if x < lo else 1.0 if x > hi else 0.0


def hysteresis(x: pd.Series, lo: pd.Series, hi: pd.Series, margin: float, kind: str) -> pd.Series:
    """Schmitt trigger: enter 'high'/'low' at the threshold, leave only after retreating `margin` beyond it."""
    out, state = [], None
    for xi, loi, hii in zip(x.values, lo.values, hi.values):
        if np.isnan(xi) or np.isnan(loi) or np.isnan(hii):
            out.append(state if state is not None else np.nan)
            continue
        r = _raw_one(xi, loi, hii, kind)
        if state is None or np.isnan(state) or state == 0:
            state = r
        elif state == 1 and xi < hii - margin:
            state = r
        elif state == -1 and xi >= loi + margin:
            state = r
        out.append(state)
    return pd.Series(out, index=x.index)


def confirm(raw: pd.Series, k: int = 2) -> pd.Series:
    """Adopt a new state only after it is the raw state on k consecutive decisions."""
    out, state, cand, cnt = [], None, None, 0
    for r in raw.values:
        if np.isnan(r):
            out.append(state if state is not None else np.nan); continue
        if state is None:
            state = r
        elif r == state:
            cand, cnt = None, 0
        else:
            cnt = cnt + 1 if r == cand else 1
            cand = r
            if cnt >= k:
                state, cand, cnt = r, None, 0
        out.append(state)
    return pd.Series(out, index=raw.index)


def classify(df: pd.DataFrame, kind: str, rule_id: str, persistence: str = "raw", rule: dict | None = None,
             x: pd.Series | None = None) -> pd.DataFrame:
    """Returns state, raw_state, measure, lower/upper bound, signed margin for one rule on a (decision-ordered) panel.
    `rule` / `x` override the declared rule and measure (used only by the sensitivity analysis)."""
    rule = rule or (S.LEVEL_RULES if kind == "level" else S.MOMENTUM_RULES)[rule_id]
    x = x if x is not None else measure_series(df, kind, rule)
    lo, hi = bounds(df, kind, rule)
    raw = raw_states(x, lo, hi, kind)
    if persistence == "raw":
        st = raw
    elif persistence == "confirm2":
        st = confirm(raw, 2)
    elif persistence == "hyst":
        st = hysteresis(x, lo, hi, rule["hyst"], kind)
    else:
        raise ValueError(persistence)
    return pd.DataFrame(dict(state=st, raw_state=raw, measure_value=x, lower=lo, upper=hi, margin=signed_margin(x, lo, hi, st, kind)))


def signed_margin(x, lo, hi, state, kind) -> pd.Series:
    """Distance (measure units) from x to the boundary of the REPORTED state's region. > 0: x still lies inside that region;
    < 0: x already sits in another region (the persistence layer is holding the old label)."""
    m = pd.Series(np.nan, index=x.index)
    hi_ = state == 1
    lo_ = state == -1
    mid = state == 0
    m[hi_] = (x - hi)[hi_]
    m[lo_] = (lo - x)[lo_]
    m[mid] = pd.concat([x - lo, hi - x], axis=1).min(axis=1)[mid]
    return m


def state_age(state: pd.Series) -> pd.Series:
    """Consecutive decision dates the reported state has been unchanged (1 = just changed)."""
    age, out, prev = 0, [], object()
    for s in state.values:
        if np.isnan(s):
            out.append(np.nan); age = 0; prev = object(); continue
        age = age + 1 if s == prev else 1
        prev = s
        out.append(age)
    return pd.Series(out, index=state.index)


def margin_tier(margin_in_rev_units: pd.Series) -> pd.Series:
    t = pd.Series("unknown", index=margin_in_rev_units.index, dtype=object)
    m = margin_in_rev_units
    t[m >= S.CONFIDENCE_TIERS["high"]] = "high"
    t[(m >= S.CONFIDENCE_TIERS["medium"]) & (m < S.CONFIDENCE_TIERS["high"])] = "medium"
    t[(m >= 0) & (m < S.CONFIDENCE_TIERS["medium"])] = "low"
    t[m < 0] = "contested"
    return t


def all_rule_states(df: pd.DataFrame) -> dict:
    """{(kind, rule_id, persistence): classify-frame} for every declared rule x persistence variant."""
    out = {}
    for kind, rules in (("level", S.LEVEL_RULES), ("momentum", S.MOMENTUM_RULES)):
        for rid in rules:
            for p in S.PERSISTENCE:
                out[(kind, rid, p)] = classify(df, kind, rid, p)
    return out
