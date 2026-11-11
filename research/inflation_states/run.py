"""Orchestrator: freeze definitions -> stage 1 (measurement & detection, no Treasury data) -> stage 2 (economic relevance)
-> figures. `python -m research.inflation_states` (needs PYTHONPATH=src for macrodb, like the forecasting code)."""
from __future__ import annotations

import datetime as dt
import json
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import beta as beta_dist

from ..calendar_pit import Calendar
from ..data import Inputs, iso
from ..stats import adjust_pvalues
from . import boot, classify as C, detection as D, outcomes as O, spec as S

OUT = Path("results/inflation_states")
NAMES = {"level": C.LEVEL_NAMES, "momentum": C.MOM_NAMES}


def w(df: pd.DataFrame, name: str):
    df.to_csv(OUT / f"{name}.csv", index=False)
    return df


def labels(m: D.Measure, kind: str, rid: str, p: str = "raw") -> pd.Series:
    return m.state(kind, rid, p).map(NAMES[kind])


def clopper_pearson(k: int, n: int, a: float = 0.05):
    if n == 0:
        return np.nan, np.nan
    lo = 0.0 if k == 0 else beta_dist.ppf(a / 2, k, n - k + 1)
    hi = 1.0 if k == n else beta_dist.ppf(1 - a / 2, k + 1, n - k)
    return float(lo), float(hi)


# ================================================================================================= stage 1
def stage1(inp: Inputs, dec: pd.DatetimeIndex):
    ms = {}
    first = {"HEADLINE": pd.Timestamp("1972-07-21"), "CORE": pd.Timestamp("1996-12-12")}      # first vintage dates (see coverage audit)
    for n, s in S.MEASURES.items():
        v = inp.versions(s)
        ms[n] = D.Measure(n, v, dec[dec >= v["availability_ts"].min()])
    w(pd.DataFrame([m.audit for m in ms.values()]), "vintage_coverage_audit")
    w(pd.concat([D.inputs_table(m) for m in ms.values()]), "inflation_state_inputs")
    w(pd.concat([D.history_table(m) for m in ms.values()]), "inflation_state_history")
    w(D.coverage_table(ms), "detection_coverage")
    a, b = D.agreement_tables(ms)
    w(a, "detection_agreement_headline_vs_core"); w(b, "detection_agreement_across_rules"); w(D.agreement_confusion(ms), "detection_confusion_headline_vs_core")
    r, mag = D.revision_tables(ms)
    w(r, "detection_revision_flips"); w(mag, "detection_revision_magnitudes"); w(D.revision_events(ms), "detection_revision_events")
    w(D.persistence_table(ms), "detection_persistence")
    d, tp = D.delay_table(ms)
    w(d, "detection_delay_events"); w(tp, "detection_turning_points_EXPOST"); w(D.delay_summary(d), "detection_delay_summary")
    w(D.delay_baseline(ms), "detection_delay_chance_baseline"); w(D.level_episode_delay(ms), "detection_level_episode_delay")
    for k, v in D.sensitivity_tables(ms).items():
        w(v, k)
    w(D.episode_table(ms), "robustness_episodes"); w(D.sample_start_table(ms), "robustness_sample_starts")
    w(D.independent_episodes(ms), "robustness_independent_episodes"); w(D.leave_one_episode_out(ms), "robustness_leave_one_episode_out")
    return ms


# ================================================================================================= stage 2
def stage2(inp: Inputs, cal: Calendar, ms: dict, dec: pd.DatetimeIndex):
    S_dir = OUT
    O_ = O
    tr = O.Treasury(inp, cal.s)
    H, K = ms["HEADLINE"], ms["CORE"]
    ffv = inp.versions(S.POLICY_SERIES)
    fed = O.fed_state_panel(ffv, dec, S.FED_STATE["window_months"], S.FED_STATE["band_pp"])
    grid = O.build_grid(tr, cal, dec[dec >= H.panel.index.min()]).join(fed)
    w(fed.reset_index().assign(decision_date=lambda x: x.decision_date.dt.date, fed_obs_month=lambda x: x.fed_obs_month.dt.date), "fed_policy_state_history")
    # target sanity (observed ETF proxy vs model-estimated synthetic) on the common sample
    both = grid[["fwd_SYN8Y_1", "fwd_IEF_1"]].dropna()
    w(pd.DataFrame([dict(comparison="IEF excess vs SYN8Y excess, 1m, decision grid", n=len(both), corr=both.corr().iloc[0, 1],
                         note="proxy check only; IEF (observed ETF) and SYN8Y (model-estimated) are different objects")]), "target_proxy_check")

    windows = {"full": (None, None), "design_le_2014": (None, "2014-12-31"), "reserved_ge_2015": (S.RESERVED_WINDOW_START, None)}

    def win(df, wn):
        a, b = windows[wn]
        m = np.ones(len(df), bool)
        if a: m &= df.index >= a
        if b: m &= df.index <= b
        return df[m]

    # ------------------------------------------------------------ label sets
    sets = []     # (dimension, measure, level_rule, mom_rule, persistence, label series)
    for mn, m in ms.items():
        for rid in S.LEVEL_RULES:
            sets.append(("level", mn, rid, "", "raw", labels(m, "level", rid)))
        for rid in S.MOMENTUM_RULES:
            sets.append(("momentum", mn, "", rid, "raw", labels(m, "momentum", rid)))
        for p in ("confirm2", "hyst"):
            sets.append(("level", mn, "L1_FIXED", "", p, labels(m, "level", "L1_FIXED", p)))
            sets.append(("momentum", mn, "", "M1_DYOY_3M", p, labels(m, "momentum", "M1_DYOY_3M", p)))
        L, M_ = labels(m, "level", "L1_FIXED"), labels(m, "momentum", "M1_DYOY_3M")
        both = (L + "|" + M_)
        sets.append(("level_x_momentum", mn, "L1_FIXED", "M1_DYOY_3M", "raw", both))
        f = grid["fed_state"].reindex(both.index)
        sets.append(("level_x_fed", mn, "L1_FIXED", "", "raw", L + "|" + f))
        sets.append(("level_x_momentum_x_fed", mn, "L1_FIXED", "M1_DYOY_3M", "raw", both + "|" + f))
    sets.append(("fed", "", "", "", "raw", grid["fed_state"]))

    rows = []
    for dim, mn, lr, mr, p, lab in sets:
        lab = lab.reindex(grid.index)
        for tg in S.TARGETS:
            for h in S.HORIZONS:
                y, mdd = grid[f"fwd_{tg}_{h}"], grid["fwd_mdd12_" + tg]
                for wn in windows:
                    yw, mw, lw = win(y, wn), win(mdd, wn), win(lab, wn)
                    dd = pd.concat([yw, lw], axis=1).dropna()
                    if len(dd) < 12:
                        continue
                    sig = float(dd.iloc[:, 0].std())
                    cs = O.cond_stats(yw, mw, lw, h, sig)
                    cs.insert(0, "window", wn)
                    for c, v in (("dimension", dim), ("measure", mn), ("level_rule", lr), ("momentum_rule", mr), ("persistence", p),
                                 ("target", tg), ("horizon_months", h)):
                        cs.insert(0, c, v)
                    rows.append(cs)
    cond = pd.concat(rows)
    cond["target_type"] = cond["target"].map({"SYN8Y": "model_estimated_synthetic", "IEF": "observed_etf_proxy"})
    cond["outcome_type"] = "future_after_detection"
    w(cond, "conditional_outcomes_forward")

    # contemporaneous (3m ENDING at the decision date) - descriptive, includes returns before the state was observable
    rows = []
    for dim, mn, lr, mr, p, lab in sets:
        if p != "raw" or dim not in ("level", "momentum", "fed"):
            continue
        lab = lab.reindex(grid.index)
        for tg in S.TARGETS:
            y = grid[f"contemp3_{tg}"]
            dd = pd.concat([y, lab], axis=1).dropna()
            if len(dd) < 12:
                continue
            cs = O.cond_stats(y, pd.Series(dtype=float), lab, 3, float(dd.iloc[:, 0].std()))
            for c, v in (("dimension", dim), ("measure", mn), ("level_rule", lr), ("momentum_rule", mr), ("target", tg), ("window", "full")):
                cs.insert(0, c, v)
            rows.append(cs)
    cc = pd.concat(rows)
    cc["outcome_type"] = "contemporaneous_trailing_3m_ending_at_decision_DESCRIPTIVE_NOT_FORWARD"
    w(cc.drop(columns=["mean_fwd12m_mdd", "median_fwd12m_mdd", "share_fwd12m_mdd_le_minus5pct"]), "conditional_outcomes_contemporaneous")

    # ------------------------------------------------------------ contrasts (declared families)
    def spells_ok(mask: pd.Series) -> int:
        return O.spells_in(mask.fillna(False))

    def defs(mn, lr, mr):
        m = ms[mn]
        sl, sm = m.state("level", lr), m.state("momentum", mr)
        f = grid["fed_state"].reindex(sl.index)
        return {
            "E1_high_vs_notHigh": (sl == 1, sl < 1, "level"), "E3_low_vs_high": (sl == -1, sl == 1, "level"),
            "E2_rising_vs_falling": (sm == 1, sm == -1, "momentum"),
            "E4_high_rising_tightening_vs_high_falling_easing": ((sl == 1) & (sm == 1) & (f == "tightening"), (sl == 1) & (sm == -1) & (f == "easing"), "combined")}

    def run_contrasts(sel_measure, lr, mr, tg, h, wn="full", skip_idx=None, start=None, pers="raw", only=None):
        out = []
        d = defs(sel_measure, lr, mr)
        if pers != "raw":
            m = ms[sel_measure]
            sl, sm = m.state("level", lr, pers), m.state("momentum", mr, pers)
            f = grid["fed_state"].reindex(sl.index)
            d = {"E1_high_vs_notHigh": (sl == 1, sl < 1, "level"), "E3_low_vs_high": (sl == -1, sl == 1, "level"),
                 "E2_rising_vs_falling": (sm == 1, sm == -1, "momentum"),
                 "E4_high_rising_tightening_vs_high_falling_easing": ((sl == 1) & (sm == 1) & (f == "tightening"), (sl == 1) & (sm == -1) & (f == "easing"), "combined")}
        y = grid[f"fwd_{tg}_{h}"]
        for cid, (a, b, kind) in d.items():
            if only is not None and cid[:2] not in only:
                continue
            a, b = a.reindex(grid.index), b.reindex(grid.index)
            yy = y
            a_, b_ = a.copy(), b.copy()
            if start:
                keep = grid.index >= start
                yy, a_, b_ = yy[keep], a_[keep], b_[keep]
            else:
                yy, a_, b_ = win(yy, wn), win(a_, wn), win(b_, wn)
            if skip_idx is not None:
                keep = ~skip_idx(yy.index)
                yy, a_, b_ = yy[keep], a_[keep], b_[keep]
            r = O.contrast(yy, a_, b_, h)
            ok = r["n_a"] >= S.MIN_MONTHS_CELL and r["n_b"] >= S.MIN_MONTHS_CELL and spells_ok(a_.reindex(yy.dropna().index)) >= S.MIN_SPELLS_CELL \
                and spells_ok(b_.reindex(yy.dropna().index)) >= S.MIN_SPELLS_CELL
            out.append(dict(contrast_id=cid, measure=sel_measure, level_rule=lr, momentum_rule=mr, persistence=pers, target=tg, horizon_months=h, window=wn,
                            estimable=bool(ok), n_spells_a=spells_ok(a_.reindex(yy.dropna().index)), n_spells_b=spells_ok(b_.reindex(yy.dropna().index)),
                            **{k: (v if ok or k in ("n_total", "n_a", "n_b") else np.nan) for k, v in r.items()}))
        return out

    prim = []
    for tg in S.TARGETS:
        for h in S.HORIZONS:
            for mn in ms:
                combos = [(lr, "M1_DYOY_3M", ("E1", "E3") + (("E4",) if lr == "L1_FIXED" else ())) for lr in S.LEVEL_RULES]
                combos += [("L1_FIXED", mr, ("E2",)) for mr in S.MOMENTUM_RULES]
                for lr, mr, only in combos:
                    for r in run_contrasts(mn, lr, mr, tg, h, only=only):
                        r["family"] = "E_primary" if (mn, lr, mr, tg, h) == (S.PRIMARY["measure"], S.PRIMARY["level"], S.PRIMARY["momentum"], S.PRIMARY_TARGET, S.PRIMARY_HORIZON) else "E_secondary"
                        prim.append(r)
    T_ = pd.DataFrame(prim)
    # a contrast defined by one dimension is repeated across the other dimension's rules: keep each distinct test once
    T_["key"] = T_.apply(lambda r: (r.contrast_id, r.measure, r.level_rule if r.contrast_id.startswith(("E1", "E3", "E4")) else "",
                                    r.momentum_rule if r.contrast_id.startswith(("E2", "E4")) else "", r.target, r.horizon_months), axis=1)
    T_ = T_.drop_duplicates("key").drop(columns="key").reset_index(drop=True)
    P = T_.family == "E_primary"
    T_["p_adjusted_holm_within_family"] = np.nan
    T_["p_adjusted_bh_within_family"] = np.nan
    ok = P & T_.estimable & T_.p_boot.notna()
    if ok.any():
        adj = adjust_pvalues(T_.loc[ok, "p_boot"])
        T_.loc[ok, "p_adjusted_holm_within_family"] = adj["p_holm"].values
        T_.loc[ok, "p_adjusted_bh_within_family"] = adj["p_bh"].values
    ok2 = (~P) & T_.estimable & T_.p_boot.notna()
    adj2 = adjust_pvalues(T_.loc[ok2, "p_boot"])
    T_.loc[ok2, "p_adjusted_holm_within_family"] = adj2["p_holm"].values
    T_.loc[ok2, "p_adjusted_bh_within_family"] = adj2["p_bh"].values
    T_["family_size_tested"] = np.where(P, int(ok.sum()), int(ok2.sum()))
    T_["hypothesis_id"] = np.where(P, T_.contrast_id.str[:2], "E5")
    T_["significant_after_correction_5pct"] = np.where(P, T_.p_adjusted_holm_within_family < 0.05, T_.p_adjusted_bh_within_family < 0.05)
    w(T_, "economic_contrasts")

    # robustness of the primary contrasts
    rob = []
    p0 = (S.PRIMARY["measure"], S.PRIMARY["level"], S.PRIMARY["momentum"], S.PRIMARY_TARGET, S.PRIMARY_HORIZON)
    for wn in ("design_le_2014", "reserved_ge_2015"):
        for r in run_contrasts(*p0[:3], p0[3], p0[4], wn=wn):
            rob.append(dict(r, robustness=f"window_{wn}"))
    for eid, s0, s1 in S.EPISODES:
        for r in run_contrasts(*p0[:3], p0[3], p0[4], skip_idx=lambda ix, s0=s0, s1=s1: (ix >= s0) & (ix <= s1)):
            rob.append(dict(r, robustness=f"exclude_{eid}"))
    for st in ("1985-01-01", "1997-01-01", "2002-08-01"):
        for r in run_contrasts(*p0[:3], p0[3], p0[4], start=st):
            rob.append(dict(r, robustness=f"sample_start_{st}"))
    for pers in ("confirm2", "hyst"):
        for r in run_contrasts(*p0[:3], p0[3], p0[4], pers=pers):
            rob.append(dict(r, robustness=f"persistence_{pers}"))
    for tg in S.TARGETS:
        for h in S.HORIZONS:
            for r in run_contrasts(*p0[:3], tg, h):
                rob.append(dict(r, robustness=f"target_{tg}_h{h}"))
    R_ = pd.DataFrame(rob)
    w(R_, "economic_contrasts_robustness")
    scope = pd.DataFrame([
        dict(item="detection metrics tables", count=int(sum(1 for _ in S.LEVEL_RULES) + sum(1 for _ in S.MOMENTUM_RULES)), note="rules x 3 persistence x 2 measures; no p-values; CIs only"),
        dict(item="economic contrasts, primary family (Holm)", count=int(P.sum()), note="headline, L1/M1, SYN8Y, 3m"),
        dict(item="economic contrasts, secondary family (BH)", count=int((~P).sum()), note="all other measure x rule x target x horizon combinations, full sample"),
        dict(item="economic contrasts, robustness re-runs of primary (not corrected, descriptive)", count=len(R_), note="windows, leave-one-episode-out, starts, persistence, targets/horizons"),
        dict(item="conditional-outcome table rows (descriptive)", count=len(cond), note="no tests"),
        dict(item="level rules / momentum rules / persistence variants", count=f"{len(S.LEVEL_RULES)} / {len(S.MOMENTUM_RULES)} / {len(S.PERSISTENCE)}", note="declared before outcomes; none selected on outcomes"),
        dict(item="threshold sensitivity grid", count="3x3 level thresholds; 4 band multiples x 4 rules x 3 persistence; 6 calibrations", note="reporting only"),
    ])
    w(scope, "search_scope")

    # ------------------------------------------------------------ drawdown episodes (investor total-return wealth; cash-relative labelled)
    eps = []
    gi = grid.copy()
    for tg in S.TARGETS:
        for kind, W_ in (("total_return", tr.wealth[tg]), ("cash_relative_LABELLED", tr.wealth[tg] / tr.bill[tg])):
            if tg == "SYN8Y":      # book's index starts 1973 and our decisions start 1972-07: episodes are measured from 1973-01 on
                W_ = W_[W_.index >= "1973-01-01"]
            e = O.drawdown_episodes(W_)
            for _, r in e.iterrows():
                def ctx(date, tag):
                    k = gi.index.searchsorted(pd.Timestamp(date), side="right") - 1
                    if k < 0:
                        return {f"{tag}_decision": "", f"{tag}_headline_level": "pre-vintage", f"{tag}_headline_momentum": "pre-vintage", f"{tag}_fed_state": "pre-vintage", f"{tag}_headline_yoy": np.nan}
                    F = gi.index[k]
                    return {f"{tag}_decision": F.date(), f"{tag}_headline_level": NAMES["level"].get(H.state("level", "L1_FIXED").get(F), "n/a"),
                            f"{tag}_headline_momentum": NAMES["momentum"].get(H.state("momentum", "M1_DYOY_3M").get(F), "n/a"),
                            f"{tag}_fed_state": gi["fed_state"].get(F, "n/a"), f"{tag}_headline_yoy": H.panel["yoy"].get(F, np.nan)}
                inside = gi[(gi.index >= r.peak) & (gi.index <= r.trough)]
                eps.append(dict(target=tg, wealth_basis=kind, peak=r.peak.date(), trough=r.trough.date(), recovery=r.recovery.date() if pd.notna(r.recovery) else "",
                                depth=r.depth, days_to_trough=(r.trough - r.peak).days, days_to_recover=(r.recovery - r.trough).days if pd.notna(r.recovery) else np.nan,
                                n_decisions_inside=len(inside),
                                share_inside_tightening=float((inside.fed_state == "tightening").mean()) if len(inside) else np.nan,
                                share_inside_headline_high=float((H.state("level", "L1_FIXED").reindex(inside.index) == 1).mean()) if len(inside) else np.nan,
                                max_headline_yoy_inside=float(H.panel["yoy"].reindex(inside.index).max()) if len(inside) else np.nan,
                                **ctx(r.peak, "at_peak"), **ctx(r.trough, "at_trough")))
    E_ = pd.DataFrame(eps)
    # book comparison on the cash-relative synthetic (book: Bloomberg index excess of T-bills, 1973+)
    cr = E_[(E_.target == "SYN8Y") & (E_.wealth_basis == "cash_relative_LABELLED")].copy()
    comp = []
    for _, b in O.BOOK_TABLE_5_1.iterrows():
        c = cr[(pd.to_datetime(cr.peak) - b.book_peak).abs() <= pd.Timedelta(days=550)]
        c = c.loc[(c.depth).idxmin()] if len(c) else None
        comp.append(dict(book_peak=b.book_peak.date(), book_trough=b.book_trough, book_drawdown_cash_relative=b.book_drawdown_cash_relative, book_cpi_peak=b.book_cpi_peak,
                         our_peak=c.peak if c is not None else "", our_trough=c.trough if c is not None else "", our_depth_syn8y_cash_relative=c.depth if c is not None else np.nan,
                         our_headline_level_at_peak=c.at_peak_headline_level if c is not None else "", our_fed_state_at_peak=c.at_peak_fed_state if c is not None else "",
                         our_share_inside_tightening=c.share_inside_tightening if c is not None else np.nan,
                         note="book values transcribed from Table 5.1 for comparison only; our series is a model-estimated 8y par bond, not the book's index"))
    w(E_, "drawdown_episodes"); w(pd.DataFrame(comp), "drawdown_vs_book_table_5_1")

    # B1/B2: claims about drawdowns
    claims = []
    crd = cr[pd.to_datetime(cr.peak) >= H.panel.index.min()]
    base_tight = float((grid.fed_state == "tightening").mean())
    n = len(crd)
    k = int((crd.at_peak_fed_state == "tightening").sum())
    kin = int((crd.share_inside_tightening >= 0.5).sum())
    lo, hi = clopper_pearson(k, n); lo2, hi2 = clopper_pearson(kin, n)
    claims.append(dict(claim_id="B1", metric="share of >5% cash-relative drawdowns (SYN8Y, peaks since 1972-07) whose peak decision is in a tightening state",
                       episodes=n, count=k, share=k / n if n else np.nan, ci_lo=lo, ci_hi=hi, baseline_share_tightening_decisions=base_tight))
    claims.append(dict(claim_id="B1", metric="share of those drawdowns with >= 50% of the peak-to-trough decisions in tightening",
                       episodes=n, count=kin, share=kin / n if n else np.nan, ci_lo=lo2, ci_hi=hi2, baseline_share_tightening_decisions=base_tight))
    claims.append(dict(claim_id="B1", metric="mean share of peak-to-trough decisions in tightening (compare with baseline share)", episodes=n,
                       count=np.nan, share=float(crd.share_inside_tightening.mean()) if n else np.nan, baseline_share_tightening_decisions=base_tight))
    deep = crd[crd.depth <= -0.10]; shallow = crd[crd.depth > -0.10]
    claims.append(dict(claim_id="B2", metric="deep (<=-10%) drawdowns: share with headline L1 level 'high' at peak", episodes=len(deep),
                       count=int((deep.at_peak_headline_level == "high").sum()), share=float((deep.at_peak_headline_level == "high").mean()) if len(deep) else np.nan,
                       mean_share_inside_high=float(deep.share_inside_headline_high.mean()) if len(deep) else np.nan, mean_max_yoy_inside=float(deep.max_headline_yoy_inside.mean()) if len(deep) else np.nan))
    claims.append(dict(claim_id="B2", metric="shallow (-10%,-5%] drawdowns: share with headline L1 level 'high' at peak", episodes=len(shallow),
                       count=int((shallow.at_peak_headline_level == "high").sum()), share=float((shallow.at_peak_headline_level == "high").mean()) if len(shallow) else np.nan,
                       mean_share_inside_high=float(shallow.share_inside_headline_high.mean()) if len(shallow) else np.nan, mean_max_yoy_inside=float(shallow.max_headline_yoy_inside.mean()) if len(shallow) else np.nan))
    w(pd.DataFrame(claims), "section_5_1_claims_check")

    # within-spell drawdowns by state (contemporaneous, total-return wealth, SYN8Y)
    rows = []
    for dim, lab in (("headline_L1_level", labels(H, "level", "L1_FIXED")), ("headline_M1_momentum", labels(H, "momentum", "M1_DYOY_3M")), ("fed", grid.fed_state)):
        lab = lab.reindex(grid.index)
        cur, s0 = None, None
        spells = []
        idx = list(grid.index)
        for i, F in enumerate(idx):
            v = lab.iloc[i]
            if v != cur:
                if cur is not None and isinstance(cur, str):
                    spells.append((cur, s0, idx[i - 1]))
                cur, s0 = v, F
        if isinstance(cur, str):
            spells.append((cur, s0, idx[-1]))
        for st, a, b in spells:
            e0, e1 = grid.exec_date[a], grid.exec_date.get(b, pd.NaT)
            if pd.isna(e0) or pd.isna(e1) or e1 <= e0:
                continue
            rows.append(dict(dimension=dim, state=st, start=a.date(), end=b.date(), months=idx.index(b) - idx.index(a) + 1,
                             mdd_total_return_SYN8Y=tr.mdd("SYN8Y", e0, e1), mdd_cash_relative_SYN8Y_LABELLED=tr.mdd("SYN8Y", e0, e1, relative=True),
                             return_total_SYN8Y=tr.ret("SYN8Y", e0, e1, "tr")))
    sp = pd.DataFrame(rows)
    w(sp, "drawdown_within_state_spells")
    agg = sp.groupby(["dimension", "state"]).agg(n_spells=("months", "size"), months=("months", "sum"), median_mdd_tr=("mdd_total_return_SYN8Y", "median"),
                                                  worst_mdd_tr=("mdd_total_return_SYN8Y", "min"),
                                                  share_spells_mdd_le_minus5pct=("mdd_total_return_SYN8Y", lambda x: float((x <= -0.05).mean()))).reset_index()
    w(agg, "drawdown_within_state_summary")
    w(grid.reset_index().assign(decision_date=lambda x: x.decision_date.dt.date, exec_date=lambda x: x.exec_date.dt.date), "outcome_grid")
    return grid, tr, T_, E_, cond


# ================================================================================================= main
def main():
    warnings.simplefilter("ignore")
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    h = S.freeze(OUT, dt.datetime.now(dt.timezone.utc).isoformat())
    print("definitions frozen:", h[:12])
    inp = Inputs()
    sessions = inp.daily("US.TREASURY.CMT.10Y").index
    cal = Calendar(sessions, lag=S.OUTCOME_LAG_SESSIONS)
    dec = cal.formation[cal.formation >= "1972-07-01"]
    ms = stage1(inp, dec)
    print("stage 1 done", round(time.time() - t0), "s")
    S.verify_frozen(OUT)                       # no definition may change between detection and outcomes
    grid, tr, T_, E_, cond = stage2(inp, cal, ms, dec)
    print("stage 2 done", round(time.time() - t0), "s")
    from . import figures
    figures.make_all(ms, grid, tr, T_, E_, cond, OUT)
    print("figures done", round(time.time() - t0), "s")
    meta = dict(run_at=dt.datetime.now(dt.timezone.utc).isoformat(), spec_sha256=h, last_decision=str(dec[-1].date()),
                last_cpi_observation=str(ms["HEADLINE"].panel.obs_month.iloc[-1].date()),
                prospective_note="decisions after this run's last_decision are genuinely out-of-sample for definitions frozen at spec_sha256")
    (OUT / "run_metadata.json").write_text(json.dumps(meta, indent=2))
    return ms, grid, tr, T_, E_, cond


if __name__ == "__main__":
    main()
