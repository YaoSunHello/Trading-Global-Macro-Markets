"""Stage 1 - MEASUREMENT and DETECTION QUALITY. No Treasury data is read in this module.

What each table can and cannot show is written next to the code that makes it (and repeated in the findings report):
 * coverage        - whether a state is defined and observable before the decision. Cannot show correctness.
 * agreement       - consistency between measures/definitions. Two measures can agree and both be wrong.
 * revisions       - how often later data would have changed the label. Says nothing about future revision regimes.
 * persistence     - stability / flip behaviour. Mechanically lower for slow-moving measures; not accuracy.
 * delay           - timeliness vs an EX-POST reference. The reference is itself a modelling choice.
 * sensitivity     - dependence on thresholds/lookbacks. Descriptive; no 'best' rule is selected.
"""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

from ..data import iso
from . import boot, classify as C, spec as S
from .pit_panel import MEASURE_COLS, build_panel, build_retro, coverage_audit, revision_scales

KINDS = {"level": S.LEVEL_RULES, "momentum": S.MOMENTUM_RULES}
NAMES = {"level": C.LEVEL_NAMES, "momentum": C.MOM_NAMES}


class Measure:
    """Everything for one CPI measure: PIT panel, revision scales, retrospective panel and all rule states."""

    def __init__(self, name, versions, decisions):
        self.name, self.series_id = name, S.MEASURES.get(name, name)
        self.audit = coverage_audit(versions, self.series_id)
        self.panel, self.snaps = build_panel(versions, decisions, self.series_id, name)
        self.rs = revision_scales(self.panel, self.snaps)
        self.retro = build_retro(versions, decisions[-1])
        self.states = C.all_rule_states(self.panel)
        self.retro_states = C.all_rule_states(self.retro)

    def state(self, kind, rid, p="raw") -> pd.Series:
        return self.states[(kind, rid, p)]["state"]

    def retro_state_at_decisions(self, kind, rid, p="raw") -> pd.Series:
        s = self.retro_states[(kind, rid, p)]["state"]
        return pd.Series(s.reindex(self.panel["obs_month"]).values, index=self.panel.index)


# ------------------------------------------------------------------------------------------- history tables (deliverables)
def inputs_table(m: Measure) -> pd.DataFrame:
    p = m.panel.copy()
    cols = ["measure", "series_id", "obs_month", "period_end", "first_release_ts", "release_ts", "vintage_date", "decision_ts", "info_lag_days",
            "availability_basis", "n_obs_in_vintage", "idx", "idx_t3", "idx_t6", "idx_t12"] + MEASURE_COLS + \
           [c for c in p.columns if c.startswith(("q25_", "q75_", "n_exp_"))]
    out = p[cols].copy()
    out = out.join(m.rs[[c for c in m.rs.columns if c.startswith("rev_scale_") and not c.startswith("rev_scale_is")]])
    for c in ("obs_month", "period_end", "vintage_date"):
        out[c] = out[c].dt.date.astype(str)
    for c in ("first_release_ts", "release_ts", "decision_ts"):
        out[c] = out[c].map(iso)
    out["calibration_note"] = "thresholds use yoy of months strictly before obs_month, from this vintage only (past-only)"
    out["decision_ts_assumption"] = "decision at 16:00 ET close of the last bond-market session of the month; CPI release assumed 08:30 ET on vintage_date"
    return out.reset_index()


def history_table(m: Measure) -> pd.DataFrame:
    frames = []
    for (kind, rid, p), f in m.states.items():
        d = f.copy()
        d["rule_kind"], d["rule_id"], d["persistence"] = kind, rid, p
        d["state_label"] = d["state"].map(NAMES[kind])
        d["state_age_decisions"] = C.state_age(d["state"])
        col = "yoy" if kind == "level" else KINDS[kind][rid]["measure"]
        d["rev_scale"] = m.rs[f"rev_scale_{col}"]
        d["rev_scale_is_prior"] = m.rs[f"rev_scale_is_prior_{col}"]
        d["margin_in_rev_units"] = d["margin"] / d["rev_scale"]
        d["confidence_tier"] = C.margin_tier(d["margin_in_rev_units"])
        d["calibration"] = KINDS[kind][rid].get("scope", "fixed_declared_threshold") if kind == "level" else "fixed_declared_band"
        frames.append(d)
    h = pd.concat(frames).reset_index().rename(columns={"index": "decision_date"})
    h["measure"] = m.name
    # agreement of the other raw rules of the same dimension with the reported label (separate from the label itself)
    raw = {(k, r): m.states[(k, r, "raw")]["state"] for (k, r, p) in m.states if p == "raw"}
    ag = {}
    for kind in KINDS:
        ids = list(KINDS[kind])
        M_ = pd.concat([raw[(kind, r)] for r in ids], axis=1)
        for p in S.PERSISTENCE:
            for r in ids:
                st = m.states[(kind, r, p)]["state"]
                ag[(kind, r, p)] = (M_.eq(st, axis=0).sum(axis=1) / M_.notna().sum(axis=1)).where(st.notna())
    h["rule_agreement_share"] = [ag[(k, r, p)].get(d, np.nan) for k, r, p, d in zip(h.rule_kind, h.rule_id, h.persistence, h.decision_date)]
    h["obs_month"] = h["decision_date"].map(m.panel["obs_month"]).dt.date.astype(str)
    h["decision_date"] = h["decision_date"].dt.date.astype(str)
    cols = ["decision_date", "measure", "obs_month", "rule_kind", "rule_id", "persistence", "state", "state_label", "raw_state", "measure_value",
            "lower", "upper", "margin", "rev_scale", "rev_scale_is_prior", "margin_in_rev_units", "confidence_tier", "state_age_decisions",
            "rule_agreement_share", "calibration"]
    return h[cols]


# ------------------------------------------------------------------------------------------- coverage
def coverage_table(ms: dict[str, Measure]) -> pd.DataFrame:
    rows = []
    for name, m in ms.items():
        p = m.panel
        leak = int((p["release_ts"] > p["decision_ts"]).sum())
        for kind, rules in KINDS.items():
            for rid in rules:
                st = m.state(kind, rid)
                rows.append(dict(measure=name, rule_kind=kind, rule_id=rid, first_decision=p.index.min().date(), last_decision=p.index.max().date(),
                                 n_decisions=len(p), n_defined=int(st.notna().sum()), coverage=float(st.notna().mean()),
                                 median_info_lag_days=float(p["info_lag_days"].median()), max_info_lag_days=int(p["info_lag_days"].max()),
                                 rows_release_after_decision=leak, **{f"audit_{k}": v for k, v in m.audit.items() if k != "note"}))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------- agreement
def _ci(a, b, fn):
    est, lo, hi, _ = boot.block_ci(fn, [np.asarray(a, float), np.asarray(b, float)])
    return est, lo, hi


def agreement_tables(ms: dict[str, Measure]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(a) headline vs core, same rule; (b) pairwise between definitions within a measure. Weighted kappa + block-bootstrap CI."""
    rows_a, rows_b = [], []
    H, K = ms["HEADLINE"], ms["CORE"]
    for kind, rules in KINDS.items():
        for rid in rules:
            for p in S.PERSISTENCE:
                a, b = H.state(kind, rid, p), K.state(kind, rid, p)
                j = pd.concat([a, b], axis=1, keys=["h", "c"]).dropna()
                k_est, k_lo, k_hi = _ci(j.h, j.c, boot.weighted_kappa)
                g_est, g_lo, g_hi = _ci(j.h, j.c, boot.raw_agreement)
                rows_a.append(dict(rule_kind=kind, rule_id=rid, persistence=p, n=len(j), first=j.index.min().date(), last=j.index.max().date(),
                                   weighted_kappa=k_est, kappa_lo=k_lo, kappa_hi=k_hi, raw_agreement=g_est, agree_lo=g_lo, agree_hi=g_hi,
                                   share_headline_high_or_rising=float((j.h == 1).mean()), share_core_high_or_rising=float((j.c == 1).mean()),
                                   headline_higher_than_core_share=float((j.h > j.c).mean()), headline_lower_than_core_share=float((j.h < j.c).mean())))
    for name, m in ms.items():
        for kind, rules in KINDS.items():
            for r1, r2 in itertools.combinations(rules, 2):
                a, b = m.state(kind, r1), m.state(kind, r2)
                j = pd.concat([a, b], axis=1, keys=["a", "b"]).dropna()
                k_est, k_lo, k_hi = _ci(j.a, j.b, boot.weighted_kappa)
                g_est, g_lo, g_hi = _ci(j.a, j.b, boot.raw_agreement)
                rows_b.append(dict(measure=name, rule_kind=kind, rule_a=r1, rule_b=r2, persistence="raw", n=len(j), weighted_kappa=k_est, kappa_lo=k_lo,
                                   kappa_hi=k_hi, raw_agreement=g_est, agree_lo=g_lo, agree_hi=g_hi))
    return pd.DataFrame(rows_a), pd.DataFrame(rows_b)


def agreement_confusion(ms) -> pd.DataFrame:
    H, K = ms["HEADLINE"], ms["CORE"]
    out = []
    for kind, rules in KINDS.items():
        for rid in rules:
            j = pd.concat([H.state(kind, rid), K.state(kind, rid)], axis=1, keys=["h", "c"]).dropna()
            ct = pd.crosstab(j.h.map(NAMES[kind]), j.c.map(NAMES[kind]))
            for r_, row in ct.iterrows():
                for c_, v in row.items():
                    out.append(dict(rule_id=rid, headline_state=r_, core_state=c_, months=int(v)))
    return pd.DataFrame(out)


# ------------------------------------------------------------------------------------------- revisions
def revision_tables(ms: dict[str, Measure]) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, mag = [], []
    for name, m in ms.items():
        for (kind, rid, p) in m.states:
            rt, rr = m.state(kind, rid, p), m.retro_state_at_decisions(kind, rid, p)
            j = pd.concat([rt, rr], axis=1, keys=["rt", "retro"]).dropna()
            flip = (j.rt != j.retro).astype(float).values
            est, lo, hi, _ = boot.block_ci(lambda x: x.mean(), [flip])
            rows.append(dict(measure=name, rule_kind=kind, rule_id=rid, persistence=p, n=len(j), flip_share=est, flip_lo=lo, flip_hi=hi,
                             n_flips=int(flip.sum()), weighted_kappa_rt_vs_retro=boot.weighted_kappa(j.rt, j.retro),
                             first=j.index.min().date(), last=j.index.max().date()))
        for c in ("yoy", "dyoy3", "dyoy6", "gap3", "gap6"):
            rt = m.panel[c]
            retro = m.retro[c].reindex(m.panel["obs_month"]).values
            d = (rt.values - retro)
            d = d[np.isfinite(d)]
            mag.append(dict(measure=name, measure_col=c, n=len(d), mean_signed_rt_minus_latest=float(d.mean()), median_abs=float(np.median(np.abs(d))),
                            p90_abs=float(np.quantile(np.abs(d), 0.9)), max_abs=float(np.abs(d).max()), share_abs_gt_0p1=float((np.abs(d) > 0.1).mean())))
    return pd.DataFrame(rows), pd.DataFrame(mag)


def revision_events(ms) -> pd.DataFrame:
    """Dated list of decisions where the real-time raw label differs from the latest-revised label of the same month."""
    out = []
    for name, m in ms.items():
        for kind, rules in KINDS.items():
            for rid in rules:
                rt, rr = m.state(kind, rid), m.retro_state_at_decisions(kind, rid)
                j = pd.concat([rt, rr, m.panel["obs_month"]], axis=1, keys=["rt", "retro", "obs"]).dropna(subset=["rt", "retro"])
                f = j[j.rt != j.retro]
                for d, r in f.iterrows():
                    out.append(dict(measure=name, rule_id=rid, decision_date=d.date(), obs_month=r.obs.date(), realtime_state=NAMES[kind][r.rt],
                                    latest_revised_state=NAMES[kind][r.retro]))
    return pd.DataFrame(out)


# ------------------------------------------------------------------------------------------- persistence / delay
def persistence_table(ms) -> pd.DataFrame:
    rows = []
    for name, m in ms.items():
        for (kind, rid, p), f in m.states.items():
            rows.append(dict(measure=name, rule_kind=kind, rule_id=rid, persistence=p, data="real_time", **boot.persistence_stats(f["state"])))
        for (kind, rid, p), f in m.retro_states.items():
            if p == "raw":
                s = f["state"][f["state"].index >= m.panel["obs_month"].min()]
                rows.append(dict(measure=name, rule_kind=kind, rule_id=rid, persistence=p, data="latest_revised_RETROSPECTIVE", **boot.persistence_stats(s)))
    return pd.DataFrame(rows)


def turning_points(m: Measure) -> pd.DataFrame:
    """Ex-post turning points of latest-revised YoY (3m centred MA, zigzag threshold 1.5pp). RETROSPECTIVE reference only."""
    y = m.retro["yoy"].rolling(S.TURNING_POINT["smooth_months"], center=True, min_periods=2).mean()
    y = y[y.index >= m.panel["obs_month"].min() - pd.DateOffset(months=6)]
    tp = boot.zigzag(y, S.TURNING_POINT["zigzag_pp"])
    return tp


def delay_table(ms) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Months from an ex-post turning point to the first real-time switch into the matching momentum state."""
    rows, tps = [], []
    W = S.TURNING_POINT["detect_window_months"]
    for name, m in ms.items():
        tp = turning_points(m)
        tp = tp[tp["month"] >= m.panel["obs_month"].min() + pd.DateOffset(months=6)]
        for _, r in tp.iterrows():
            tps.append(dict(measure=name, turning_point_obs_month=r.month.date(), type=r.type, smoothed_yoy=r.value))
        for rid in S.MOMENTUM_RULES:
            for p in S.PERSISTENCE:
                st = m.state("momentum", rid, p)
                obs = m.panel["obs_month"]
                for _, r in tp.iterrows():
                    target = -1.0 if r.type == "peak" else 1.0
                    prev = st.shift(1)
                    cand = st[(obs >= r.month) & (obs <= r.month + pd.DateOffset(months=W)) & (st == target) & (prev != target)]
                    if len(cand):
                        d = cand.index[0]
                        o = obs[d]
                        rows.append(dict(measure=name, rule_id=rid, persistence=p, turning_point=r.month.date(), type=r.type, detected=True,
                                         detection_decision=d.date(), delay_obs_months=(o.year - r.month.year) * 12 + o.month - r.month.month,
                                         delay_calendar_months_from_period_end=((d.year - (r.month + pd.offsets.MonthEnd(0)).year) * 12
                                                                                  + d.month - (r.month + pd.offsets.MonthEnd(0)).month)))
                    else:
                        rows.append(dict(measure=name, rule_id=rid, persistence=p, turning_point=r.month.date(), type=r.type, detected=False))
    return pd.DataFrame(rows), pd.DataFrame(tps)


def delay_summary(d: pd.DataFrame) -> pd.DataFrame:
    g = []
    for (meas, rid, p), x in d.groupby(["measure", "rule_id", "persistence"]):
        det = x[x.detected]
        g.append(dict(measure=meas, rule_id=rid, persistence=p, n_turning_points=len(x), n_detected=len(det), share_detected=len(det) / len(x),
                      median_delay_obs_months=float(det.delay_obs_months.median()) if len(det) else np.nan,
                      p25_delay=float(det.delay_obs_months.quantile(.25)) if len(det) else np.nan, p75_delay=float(det.delay_obs_months.quantile(.75)) if len(det) else np.nan,
                      median_delay_calendar_months=float(det.delay_calendar_months_from_period_end.median()) if len(det) else np.nan))
    return pd.DataFrame(g)


def delay_baseline(ms) -> pd.DataFrame:
    """Chance benchmark for the delay metric. A momentum rule that flips several times a year will 'detect' almost any
    turning point within 18 months. Here: of ALL switches into the target state (e.g. into 'falling'), how many fall inside
    an 18-month post-turning-point window of the right type, versus the share of calendar time those windows cover."""
    W = S.TURNING_POINT["detect_window_months"]
    rows = []
    for name, m in ms.items():
        tp = turning_points(m)
        tp = tp[tp["month"] >= m.panel["obs_month"].min() + pd.DateOffset(months=6)]
        obs = m.panel["obs_month"]
        for rid in S.MOMENTUM_RULES:
            for p in S.PERSISTENCE:
                st = m.state("momentum", rid, p)
                prev = st.shift(1)
                for typ, target in (("peak", -1.0), ("trough", 1.0)):
                    sw = st[(st == target) & (prev != target) & prev.notna()]
                    inwin = pd.Series(False, index=obs.index)
                    for t0 in tp[tp.type == typ].month:
                        inwin |= (obs >= t0) & (obs <= t0 + pd.DateOffset(months=W))
                    k = int(inwin.reindex(sw.index).sum())
                    share_t = float(inwin.mean())
                    rows.append(dict(measure=name, rule_id=rid, persistence=p, turning_point_type=typ, n_switches_into_matching_state=len(sw), n_in_window=k,
                                     share_of_switches_in_window=k / len(sw) if len(sw) else np.nan, share_of_calendar_time_in_window=share_t,
                                     lift_vs_chance=(k / len(sw)) / share_t if len(sw) and share_t > 0 else np.nan))
    return pd.DataFrame(rows)


def level_episode_delay(ms) -> pd.DataFrame:
    """Level state vs ex-post high-inflation episodes (smoothed latest-revised YoY >= high threshold for >= 6 months).
    Because L1 uses the same threshold, this measures only release lag + noise filtering, not classification accuracy."""
    rows = []
    hi = S.LEVEL_RULES["L1_FIXED"]["high"]
    for name, m in ms.items():
        y = m.retro["yoy"].rolling(3, center=True, min_periods=2).mean()
        y = y[y.index >= m.panel["obs_month"].min()]
        on = (y >= hi).astype(int)
        runs = (on != on.shift()).cumsum()
        for _, seg in on.groupby(runs):
            if seg.iloc[0] == 1 and len(seg) >= 6:
                s, e = seg.index[0], seg.index[-1]
                for p in S.PERSISTENCE:
                    st = m.state("level", "L1_FIXED", p)
                    obs = m.panel["obs_month"]
                    cand = st[(obs >= s - pd.DateOffset(months=6)) & (obs <= s + pd.DateOffset(months=18)) & (st == 1)]
                    cexit = st[(obs >= e) & (obs <= e + pd.DateOffset(months=18)) & (st < 1)]
                    rows.append(dict(measure=name, persistence=p, episode_start=s.date(), episode_end=e.date(), episode_months=len(seg),
                                     entry_delay_obs_months=((obs[cand.index[0]].year - s.year) * 12 + obs[cand.index[0]].month - s.month) if len(cand) else np.nan,
                                     exit_delay_obs_months=((obs[cexit.index[0]].year - e.year) * 12 + obs[cexit.index[0]].month - e.month) if len(cexit) else np.nan))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------- sensitivity
def _stats_row(st: pd.Series, ref: pd.Series | None = None, **kw):
    s = st.dropna()
    sp = boot.spells(st)
    row = dict(kw, n=len(s), share_low=float((s == -1).mean()), share_normal=float((s == 0).mean()), share_high=float((s == 1).mean()),
               transitions_per_year=float(boot.flip_series(st)[np.isfinite(st.values)].mean() * 12), n_spells=len(sp),
               median_spell_months=float(sp.length.median()) if len(sp) else np.nan)
    if ref is not None:
        row["weighted_kappa_vs_reference"] = boot.weighted_kappa(st.reindex(ref.index), ref)
    return row


def sensitivity_tables(ms) -> dict[str, pd.DataFrame]:
    out = {}
    thr, mom, lookback, smooth, freq = [], [], [], [], []
    for name, m in ms.items():
        p = m.panel
        ref = m.state("level", "L1_FIXED")
        for lo, hi in itertools.product([1.0, 1.5, 2.0], [3.0, 3.5, 4.0]):
            rule = dict(S.LEVEL_RULES["L1_FIXED"], low=lo, high=hi)
            thr.append(_stats_row(C.classify(p, "level", "L1_FIXED", "raw", rule=rule)["state"], ref, measure=name, low=lo, high=hi,
                                  is_declared=(lo == 1.5 and hi == 3.5)))
        for rid, rule in S.MOMENTUM_RULES.items():
            ref_m = m.state("momentum", rid)
            for mult in (0.5, 1.0, 1.5, 2.0):
                r2 = dict(rule, band=rule["band"] * mult, hyst=rule["hyst"] * mult)
                for pers in ("raw", "confirm2", "hyst"):
                    mom.append(_stats_row(C.classify(p, "momentum", rid, pers, rule=r2)["state"], ref_m, measure=name, rule_id=rid, band_multiple=mult,
                                          band_pp=r2["band"], persistence=pers, is_declared=(mult == 1.0)))
        for scope in ["exp_full", "exp_from1970", "exp_from1985", "roll60", "roll120", "roll180"]:
            rule = dict(S.LEVEL_RULES["L2_EXP_PCTL"], scope={"exp_full": "expanding_full", "exp_from1970": "expanding_from1970",
                                                              "exp_from1985": "expanding_from1985"}.get(scope, scope))
            st = C.classify(p, "level", "L2_EXP_PCTL", "raw", rule=rule)["state"]
            lookback.append(_stats_row(st, ref, measure=name, calibration=scope, first_defined=str(st.dropna().index.min().date()) if st.notna().any() else ""))
        # smoothing: 3-month trailing mean of YoY before applying the fixed thresholds
        for lab, x in (("raw_yoy", p["yoy"]), ("yoy_3m_mean", p["yoy_sm3"])):
            smooth.append(_stats_row(C.classify(p, "level", "L1_FIXED", "raw", x=x)["state"], ref, measure=name, input=lab))
        # decision frequency: quarter-end decisions only
        full = m.state("level", "L1_FIXED")
        q = full[full.index.month.isin([3, 6, 9, 12])]
        sp = boot.spells(full)
        seen = 0
        for _, r in sp.iterrows():
            seen += int(((q.index >= r.start) & (q.index <= r.end)).any())
        freq.append(dict(measure=name, rule_id="L1_FIXED", monthly_transitions_per_year=float(boot.flip_series(full)[np.isfinite(full.values)].mean() * 12),
                         quarterly_transitions_per_year=float(boot.flip_series(q)[np.isfinite(q.values)].mean() * 4), monthly_spells=len(sp),
                         monthly_spells_never_observed_at_quarter_end=len(sp) - seen))
    return dict(sensitivity_level_thresholds=pd.DataFrame(thr), sensitivity_momentum_bands=pd.DataFrame(mom),
                sensitivity_calibration_lookback=pd.DataFrame(lookback), sensitivity_smoothing=pd.DataFrame(smooth),
                sensitivity_decision_frequency=pd.DataFrame(freq))


# ------------------------------------------------------------------------------------------- robustness across time
def episode_table(ms) -> pd.DataFrame:
    rows = []
    for name, m in ms.items():
        for eid, s0, s1 in S.EPISODES:
            for (kind, rid, p) in [("level", "L1_FIXED", "raw"), ("level", "L2_EXP_PCTL", "raw"), ("level", "L3_ROLL10Y_PCTL", "raw"),
                                   ("momentum", "M1_DYOY_3M", "raw"), ("momentum", "M1_DYOY_3M", "hyst")]:
                st = m.state(kind, rid, p)
                st = st[(st.index >= s0) & (st.index <= s1)]
                if st.dropna().empty:
                    continue
                r = _stats_row(st, measure=name, episode=eid, rule_kind=kind, rule_id=rid, persistence=p, start=str(st.dropna().index.min().date()),
                               end=str(st.dropna().index.max().date()))
                r["mean_yoy_in_episode"] = float(m.panel.loc[st.index, "yoy"].mean())
                rows.append(r)
    return pd.DataFrame(rows)


def sample_start_table(ms) -> pd.DataFrame:
    rows = []
    for name, m in ms.items():
        for s0 in S.SAMPLE_STARTS:
            for (kind, rid, p) in [("level", "L1_FIXED", "raw"), ("level", "L2_EXP_PCTL", "raw"), ("level", "L3_ROLL10Y_PCTL", "raw"),
                                   ("momentum", "M1_DYOY_3M", "raw")]:
                st = m.state(kind, rid, p)
                st = st[st.index >= s0]
                if st.dropna().empty:
                    continue
                rows.append(_stats_row(st, measure=name, sample_start=s0, rule_kind=kind, rule_id=rid, persistence=p))
    return pd.DataFrame(rows)


def independent_episodes(ms) -> pd.DataFrame:
    """Months vs spells: the number of independent regime episodes is far below the number of monthly observations."""
    rows = []
    for name, m in ms.items():
        for (kind, rid, p), f in m.states.items():
            if p == "raw" and rid in ("L1_FIXED", "L2_EXP_PCTL", "L3_ROLL10Y_PCTL", "M1_DYOY_3M", "M2_DYOY_6M"):
                sp = boot.spells(f["state"])
                for s, g in sp.groupby("state"):
                    rows.append(dict(measure=name, rule_id=rid, state=NAMES[kind][s], months=int(g.length.sum()), n_spells=len(g),
                                     n_spells_ge3m=int((g.length >= 3).sum()), n_spells_ge6m=int((g.length >= 6).sum()),
                                     median_spell_months=float(g.length.median()), months_per_spell=float(g.length.sum() / len(g))))
    return pd.DataFrame(rows)


def leave_one_episode_out(ms) -> pd.DataFrame:
    """Key detection metrics recomputed with each declared episode removed."""
    rows = []
    H, K = ms["HEADLINE"], ms["CORE"]
    for excl in [None] + [e[0] for e in S.EPISODES]:
        def keep(idx):
            if excl is None:
                return np.ones(len(idx), bool)
            _, s0, s1 = [e for e in S.EPISODES if e[0] == excl][0]
            return ~((idx >= s0) & (idx <= s1))
        for kind, rid in (("level", "L1_FIXED"), ("momentum", "M1_DYOY_3M")):
            a, b = H.state(kind, rid), K.state(kind, rid)
            j = pd.concat([a, b], axis=1, keys=["h", "c"]).dropna()
            j = j[keep(j.index)]
            rt, rr = H.state(kind, rid), H.retro_state_at_decisions(kind, rid)
            x = pd.concat([rt, rr], axis=1, keys=["rt", "rr"]).dropna()
            x = x[keep(x.index)]
            hs = H.state(kind, rid)
            hs = hs.where(keep(hs.index))          # excluded months become NaN so no artificial transition is created at the join
            rows.append(dict(excluded_episode=excl or "none", rule_id=rid, n_months_headline=len(hs.dropna()),
                             headline_vs_core_kappa=boot.weighted_kappa(j.h, j.c) if len(j) > 12 else np.nan, n_months_headline_vs_core=len(j),
                             revision_flip_share=float((x.rt != x.rr).mean()), transitions_per_year=float(boot.flip_series(hs)[np.isfinite(hs.values)].mean() * 12),
                             share_high_or_rising=float((hs.dropna() == 1).mean())))
    return pd.DataFrame(rows)
