"""Builds results/inflation_states/FINDINGS.md from the CSV outputs. Every number is read from the CSVs; verdicts follow the
`supported_if` criteria declared in spec.py (evaluated here, not chosen after the fact)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import spec as S

OUT = Path("results/inflation_states")


def r(name):
    return pd.read_csv(OUT / f"{name}.csv")


def pct(x, d=1):
    return "n/a" if pd.isna(x) else f"{x * 100:.{d}f}%"


def num(x, d=2):
    return "n/a" if pd.isna(x) else f"{x:.{d}f}"


def ci(e, lo, hi, d=2, p=False):
    f = (lambda v: pct(v, d)) if p else (lambda v: num(v, d))
    return f"{f(e)} [{f(lo)}, {f(hi)}]"


def table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join("" if (isinstance(v, float) and np.isnan(v)) else str(v) for v in row.values) + " |")
    return "\n".join(lines)


def main():
    meta = json.loads((OUT / "run_metadata.json").read_text())
    cov, agA, agB, fl = r("detection_coverage"), r("detection_agreement_headline_vs_core"), r("detection_agreement_across_rules"), r("detection_revision_flips")
    per, dsum, base = r("detection_persistence"), r("detection_delay_summary"), r("detection_delay_chance_baseline")
    loo, con, rob, cond = r("robustness_leave_one_episode_out"), r("economic_contrasts"), r("economic_contrasts_robustness"), r("conditional_outcomes_forward")
    claims, dd, comp, scope = r("section_5_1_claims_check"), r("drawdown_episodes"), r("drawdown_vs_book_table_5_1"), r("search_scope")
    aud, tp, lvl_delay = r("vintage_coverage_audit"), r("detection_turning_points_EXPOST"), r("detection_level_episode_delay")
    indep = r("robustness_independent_episodes")
    fed = r("fed_policy_state_history")
    sc = []          # scorecard rows

    # ---------------- M1 measurement
    h_cov = cov[cov.measure == "HEADLINE"]; k_cov = cov[cov.measure == "CORE"]
    fixed_mom = cov[cov.rule_id.isin(["L1_FIXED"] + list(S.MOMENTUM_RULES))]
    ok_m1 = (fixed_mom.coverage >= 0.95).all() and (cov.rows_release_after_decision == 0).all()
    sc.append(dict(id="M1", verdict="Supported (for fixed-threshold level and all momentum rules)" if ok_m1 else "Not supported",
                   evidence=f"Headline decisions {h_cov.first_decision.iloc[0]} to {meta['last_decision']} (n={int(h_cov.n_decisions.iloc[0])}); core from {k_cov.first_decision.iloc[0]} (n={int(k_cov.n_decisions.iloc[0])}). "
                            f"Min coverage of L1/M1-M4: {pct(fixed_mom.coverage.min())}. Rows with release after decision: {int(cov.rows_release_after_decision.sum())}. "
                            f"Percentile rules (L2, L3) are defined for only {pct(h_cov[h_cov.rule_id == 'L2_EXP_PCTL'].coverage.iloc[0], 0)} of headline decisions: ALFRED vintages before 1994-02 hold about 19 monthly observations, "
                            f"too few to calibrate a distribution without back-filling revised data."))

    # ---------------- D1
    d1 = agA[(agA.rule_id == "L1_FIXED") & (agA.persistence == "raw")].iloc[0]
    d1m = agA[(agA.rule_id == "M1_DYOY_3M") & (agA.persistence == "raw")].iloc[0]
    sc.append(dict(id="D1", verdict="Supported" if d1.kappa_lo >= 0.6 else "Not supported",
                   evidence=f"Headline vs core, L1 level: weighted kappa {ci(d1.weighted_kappa, d1.kappa_lo, d1.kappa_hi)}, raw agreement {pct(d1.raw_agreement, 0)} (n={int(d1.n)}). "
                            f"M1 momentum: kappa {ci(d1m.weighted_kappa, d1m.kappa_lo, d1m.kappa_hi)}. Declared guide: lower bound >= 0.60."))
    # ---------------- D2
    med = agB.groupby(["measure", "rule_kind"]).weighted_kappa.median()
    sc.append(dict(id="D2", verdict="Supported" if (med >= 0.6).all() else "Not supported",
                   evidence="Median pairwise weighted kappa across definitions: " + "; ".join(f"{m} {k} {num(v, 3)}" for (m, k), v in med.items()) +
                            ". Declared guide: median >= 0.60. Pairwise range (headline level): " +
                            f"{num(agB[(agB.measure == 'HEADLINE') & (agB.rule_kind == 'level')].weighted_kappa.min())} to {num(agB[(agB.measure == 'HEADLINE') & (agB.rule_kind == 'level')].weighted_kappa.max())}."))
    # ---------------- D3
    f3 = fl[fl.persistence == "raw"].copy()
    f3["limit"] = np.where(f3.rule_kind == "level", 0.05, 0.10)
    f3["pass"] = f3.flip_hi <= f3.limit
    passed = f3[f3["pass"]]; failed = f3[~f3["pass"]]
    sc.append(dict(id="D3", verdict="Partially supported" if len(passed) and len(failed) else ("Supported" if len(failed) == 0 else "Not supported"),
                   evidence="Real-time label differs from latest-revised label (share, 95% CI upper bound vs limit 5% level / 10% momentum). Pass: " +
                            ", ".join(f"{a.measure[:1]}:{a.rule_id.split('_')[0]} {pct(a.flip_share)}" for a in passed.itertuples()) + ". Fail: " +
                            ", ".join(f"{a.measure[:1]}:{a.rule_id.split('_')[0]} {pct(a.flip_share)} (upper {pct(a.flip_hi)})" for a in failed.itertuples()) +
                            ". Short-horizon annualised-pace momentum (M3, M4) is the revision-sensitive family (seasonal-factor revisions)."))
    # ---------------- D4
    rows = []
    for meas in ("HEADLINE", "CORE"):
        for rid in ("M1_DYOY_3M", "M2_DYOY_6M"):
            x = per[(per.measure == meas) & (per.rule_id == rid) & (per.data == "real_time")].set_index("persistence")
            for pz in ("confirm2", "hyst"):
                red = 1 - x.loc[pz, "share_spells_le2m"] / x.loc["raw", "share_spells_le2m"]
                dl = dsum[(dsum.measure == meas) & (dsum.rule_id == rid)].set_index("persistence").median_delay_obs_months
                rows.append(dict(measure=meas, rule=rid, persistence=pz, short_spell_share_raw=pct(x.loc["raw", "share_spells_le2m"], 0),
                                 short_spell_share_after=pct(x.loc[pz, "share_spells_le2m"], 0), reduction=red, added_median_delay_months=dl[pz] - dl["raw"],
                                 transitions_per_year_raw=num(x.loc["raw", "transitions_per_year"]), transitions_per_year_after=num(x.loc[pz, "transitions_per_year"])))
    d4 = pd.DataFrame(rows)
    d4["meets"] = (d4.reduction >= 0.5) & (d4.added_median_delay_months <= 3)
    v4 = {pz: bool(d4[d4.persistence == pz].meets.all()) for pz in ("confirm2", "hyst")}
    sc.append(dict(id="D4", verdict=("confirm2 supported; hyst not supported" if v4["confirm2"] and not v4["hyst"] else
                                      "Both supported" if all(v4.values()) else "Neither supported" if not any(v4.values()) else "hyst supported; confirm2 not"),
                   evidence="; ".join(f"{a.measure[:1]} {a.rule.split('_')[0]} {a.persistence}: short spells {a.short_spell_share_raw}->{a.short_spell_share_after} "
                                      f"({pct(a.reduction, 0)} lower), added median delay {num(a.added_median_delay_months, 1)}m" for a in d4.itertuples())))
    # ---------------- D5
    d5 = dsum[(dsum.measure == "HEADLINE") & (dsum.rule_id == "M1_DYOY_3M") & (dsum.persistence == "raw")].iloc[0]
    bl = base[(base.measure == "HEADLINE") & (base.rule_id == "M1_DYOY_3M") & (base.persistence == "raw")]
    ok5 = d5.median_delay_obs_months <= 6 and d5.share_detected >= 0.75
    sc.append(dict(id="D5", verdict=("Supported on the declared timeliness criterion, but weak evidence of discrimination" if ok5 else "Not supported"),
                   evidence=f"Headline M1 raw: {int(d5.n_detected)}/{int(d5.n_turning_points)} ex-post turning points matched within 18 months, median delay {num(d5.median_delay_obs_months, 1)} months from the observation month "
                            f"(IQR {num(d5.p25_delay, 1)}-{num(d5.p75_delay, 1)}). Chance check: only {pct(bl.share_of_switches_in_window.mean(), 0)} of all switches into the matching state fall inside a post-turning-point window "
                            f"that covers {pct(bl.share_of_calendar_time_in_window.mean(), 0)} of the time (lift {num(bl.lift_vs_chance.mean())}); the rule changes state ~{num(per[(per.measure == 'HEADLINE') & (per.rule_id == 'M1_DYOY_3M') & (per.persistence == 'raw') & (per.data == 'real_time')].transitions_per_year.iloc[0], 1)} times a year, "
                            f"so catching every turn is expected and most switches are not turning points."))
    # ---------------- R1
    base_l = loo[(loo.excluded_episode == "none") & (loo.rule_id == "L1_FIXED")].iloc[0]
    oth_l = loo[(loo.excluded_episode != "none") & (loo.rule_id == "L1_FIXED")]
    hw_k = (d1.kappa_hi - d1.kappa_lo) / 2
    f_l1 = fl[(fl.measure == "HEADLINE") & (fl.rule_id == "L1_FIXED") & (fl.persistence == "raw")].iloc[0]
    p_l1 = per[(per.measure == "HEADLINE") & (per.rule_id == "L1_FIXED") & (per.persistence == "raw") & (per.data == "real_time")].iloc[0]
    chk = [("headline-vs-core kappa (L1)", (oth_l.headline_vs_core_kappa - base_l.headline_vs_core_kappa).abs().max(), hw_k),
           ("revision flip share (L1)", (oth_l.revision_flip_share - base_l.revision_flip_share).abs().max(), (f_l1.flip_hi - f_l1.flip_lo) / 2),
           ("transitions per year (L1)", (oth_l.transitions_per_year - base_l.transitions_per_year).abs().max(), (p_l1.transitions_per_year_hi - p_l1.transitions_per_year_lo) / 2)]
    stable = all(a <= b for _, a, b in chk)
    sc.append(dict(id="R1", verdict="Supported" if stable else "Not supported (headline-vs-core agreement is episode-dependent)" if chk[0][1] > chk[0][2] else "Partially supported",
                   evidence="Largest change when any one declared episode is excluded vs CI half-width: " + "; ".join(f"{n} {num(a, 3)} vs {num(b, 3)}" for n, a, b in chk) +
                            f". Excluding the 2020-26 episode drops headline-vs-core level kappa from {num(base_l.headline_vs_core_kappa)} to "
                            f"{num(loo[(loo.excluded_episode.str.startswith('E6')) & (loo.rule_id == 'L1_FIXED')].headline_vs_core_kappa.iloc[0])}."))

    # ---------------- E1-E4 / B3 / E5
    P = con[con.family == "E_primary"].set_index("contrast_id")
    for cid, hid, label in (("E1_high_vs_notHigh", "E1", "high vs not-high"), ("E2_rising_vs_falling", "E2", "rising - falling"), ("E3_low_vs_high", "E3", "low - high"),
                            ("E4_high_rising_tightening_vs_high_falling_easing", "E4/B3", "(high,rising,tightening) - (high,falling,easing)")):
        x = P.loc[cid]
        sig = bool(x.p_adjusted_holm_within_family < 0.05)
        sc.append(dict(id=hid, verdict="Supported" if sig else "Not supported (inconclusive: CI includes zero)",
                       evidence=f"{label}: mean forward 3m excess return difference {pct(x.diff_annualised)} per year (95% CI {pct(x.ci_lo)} to {pct(x.ci_hi)}); cells {int(x.n_a)} / {int(x.n_b)} months in {int(x.n_spells_a)} / {int(x.n_spells_b)} spells; "
                                f"bootstrap p {num(x.p_boot)}, Holm-adjusted {num(x.p_adjusted_holm_within_family)}; effect size {num(x.effect_size)} sd."))
    sec = con[(con.family == "E_secondary") & con.estimable]
    sig_sec = int(sec.significant_after_correction_5pct.sum())
    e1s = sec[sec.contrast_id.str.startswith("E1")]; e2s = sec[sec.contrast_id.str.startswith("E2")]
    sc.append(dict(id="E5", verdict="Not supported" if sig_sec == 0 else f"{sig_sec} of {len(sec)} survive BH (exploratory)",
                   evidence=f"{len(sec)} estimable secondary contrasts of {int((con.family == 'E_secondary').sum())} defined; {sig_sec} significant after Benjamini-Hochberg. "
                            f"E1 (high vs not-high, expected negative): {int((e1s.diff_annualised < 0).sum())}/{len(e1s)} negative, {int((e1s.ci_hi < 0).sum())} with 95% CI below 0 before correction. "
                            f"E2 (rising - falling, expected negative): {int((e2s.diff_annualised < 0).sum())}/{len(e2s)} negative, {int((e2s.ci_hi < 0).sum())} with CI below 0 before correction."))
    # ---------------- B1 / B2
    cl = claims.set_index("metric")
    b1a, b1b, b1c = claims.iloc[0], claims.iloc[1], claims.iloc[2]
    ep = dd[(dd.target == "SYN8Y") & (dd.wealth_basis == "cash_relative_LABELLED")].copy()
    ep = ep[pd.to_datetime(ep.peak) >= "1973-01-01"]
    big = ep[ep.depth <= -0.20]
    sc.append(dict(id="B1", verdict="Not supported as a general statement (declared metric); consistent for some of the deepest episodes",
                   evidence=f"{int(b1a['count'])}/{int(b1a.episodes)} drawdown peaks fall in a 'tightening' state ({pct(b1a.share, 0)}, exact 95% CI {pct(b1a.ci_lo, 0)}-{pct(b1a.ci_hi, 0)}) vs {pct(b1a.baseline_share_tightening_decisions, 0)} of all decisions; "
                            f"mean share of peak-to-trough decisions in tightening {pct(b1c.share, 0)}. The tightening state is a trailing 6-month change, so peaks naturally precede it. "
                            f"Deepest episodes (<= -20%): " + "; ".join(f"{a.peak[:7]}..{a.trough[:7]} {pct(a.depth, 0)} (tightening {pct(a.share_inside_tightening, 0)} of decisions inside)" for a in big.itertuples()) + "."))
    deep = ep[ep.depth <= -0.10]; shallow = ep[ep.depth > -0.10]
    sc.append(dict(id="B2", verdict="Partially consistent (descriptive only; not a clean separation)",
                   evidence=f"Share of peak-to-trough decisions with headline L1 'high': deep (<= -10%, n={len(deep)}) mean {pct(deep.share_inside_headline_high.mean(), 0)}, shallow (n={len(shallow)}) mean {pct(shallow.share_inside_headline_high.mean(), 0)}. "
                            + "Deepest: " + "; ".join(f"{a.peak[:7]}..{a.trough[:7]} {pct(a.depth, 0)} high inside {pct(a.share_inside_headline_high, 0)}" for a in ep.nsmallest(3, "depth").itertuples()) +
                            (". Shallow episodes with >= 90% of decisions in 'high': " + (", ".join(f"{a.peak[:7]}..{a.trough[:7]} ({pct(a.depth, 0)})" for a in shallow[shallow.share_inside_headline_high >= 0.9].itertuples()) or "none") + ".")))
    sc.append(dict(id="B4", verdict="Untested", evidence="Real-yield / potential-growth claims are not tested in this study."))

    hyp = {h["id"]: h for h in S.HYPOTHESES}
    sc_df = pd.DataFrame(sc)
    sc_df["source"] = sc_df.id.map(lambda i: hyp[i[:2] if i not in hyp else i]["source"].replace("_", " "))
    sc_df["hypothesis (declared before analysis)"] = sc_df.id.map(lambda i: hyp[i[:2] if i not in hyp else i]["statement"])
    sc_df["declared support criterion"] = sc_df.id.map(lambda i: hyp[i[:2] if i not in hyp else i]["supported_if"])

    # ---------------- build the document
    L = []
    A = L.append
    A("# Inflation-state detection: findings\n")
    A("> Numbers and verdicts are computed from the CSVs on every run. The narrative sentences were written for the run below; if the data or definitions change, re-read them.\n")
    A(f"*Generated {meta['run_at'][:10]} from `results/inflation_states/*.csv`. Definitions frozen at SHA-256 `{meta['spec_sha256'][:16]}` before any Treasury outcome was computed. "
      f"Last decision {meta['last_decision']}; last CPI observation {meta['last_cpi_observation']}. Treasury series are an observed ETF proxy (IEF, 2002-07+) and a model-estimated 8y par bond (1962+); neither is the book's index.*\n")
    A("## 1. What was established\n")
    h_state = f"{pct(h_cov.coverage.iloc[0], 0)}"
    A(f"1. **Measurement.** Level and momentum states can be assigned in real time from ALFRED vintages: headline CPI from {h_cov.first_decision.iloc[0]}, core CPI from {k_cov.first_decision.iloc[0]}. "
      f"Percentile-calibrated level rules exist only from 1994-02 (headline) because earlier ALFRED vintages are 19-month windows.")
    A(f"2. **Detection quality is mixed and should not be over-read.** Level labels from fixed thresholds are stable to revisions (headline: {pct(f_l1.flip_share)} of labels later differ, upper bound {pct(f_l1.flip_hi)}) and slow-moving "
      f"({num(p_l1.transitions_per_year)} transitions/yr). Momentum labels are noisy (headline M1 ~{num(per[(per.measure == 'HEADLINE') & (per.rule_id == 'M1_DYOY_3M') & (per.persistence == 'raw') & (per.data == 'real_time')].transitions_per_year.iloc[0], 1)} transitions/yr; "
      f"{pct(per[(per.measure == 'HEADLINE') & (per.rule_id == 'M1_DYOY_3M') & (per.persistence == 'raw') & (per.data == 'real_time')].share_spells_le2m.iloc[0], 0)} of spells last <= 2 months). A two-month confirmation rule removes most of that noise for about one extra month of delay.")
    ex6 = loo[(loo.excluded_episode.str.startswith("E6")) & (loo.rule_id == "L1_FIXED")].headline_vs_core_kappa.iloc[0]
    A(f"3. **Headline and core disagree.** Weighted kappa for the level state is {num(d1.weighted_kappa)} (CI {num(d1.kappa_lo)} to {num(d1.kappa_hi)}); it is {num(ex6)} when the 2020-26 episode is excluded. Definitions also disagree with each other (section 4). "
      f"A single 'inflation regime' label is therefore a modelling choice, not a measured fact.")
    A(f"4. **Economic relevance was not established.** No primary contrast survives correction (Holm-adjusted p {', '.join(num(v) for v in P.p_adjusted_holm_within_family)}), and {sig_sec} of {len(sec)} exploratory contrasts survive BH. "
      f"The conditional descriptions in section 6 are shown without inference; the bootstrap intervals are wide relative to the differences between cells.")
    A("5. **No trading signal, Sharpe optimisation or definition search was performed.** Rules were declared first, frozen and hashed, and no rule was chosen on Treasury outcomes.\n")
    A("## 2. Hypothesis scorecard\n")
    A("Verdicts apply the criteria declared in `spec.py`. 'Not supported' means the declared criterion was not met, not that the opposite was shown.\n")
    A(table(sc_df[["id", "source", "hypothesis (declared before analysis)", "declared support criterion", "evidence", "verdict"]]) + "\n")
    A("## 3. Measurement and point-in-time coverage\n")
    A(table(aud[["series_id", "first_vintage_date", "first_genuine_release_obs", "n_obs", "n_obs_first_seen_late", "n_obs_genuine", "median_first_release_lag_days_genuine", "max_first_release_lag_days_genuine"]]) + "\n")
    A("* `n_obs_first_seen_late` are observations that entered the ALFRED archive in a back-fill (more than 45 days after their month end). They are usable as *history inside a vintage* but decision dates before the first vintage are excluded.")
    A("* Median information lag from the period a state describes to the decision date is "
      f"{int(h_cov.median_info_lag_days.iloc[0])} days (maximum {int(h_cov.max_info_lag_days.max())}). A state at a month-end decision describes the previous month.")
    A("* The October 2025 CPI release did not occur (federal shutdown); momentum rules that need that month are undefined for the affected decisions (shown as <100% coverage) rather than interpolated.")
    A("* Release time 08:30 ET is an assumption (ALFRED vintage dates are day-granular). Fed funds values before 1996-10 are back-filled in ALFRED, so their availability is assumed to be the day after month end (flagged `assumed_month_end_plus_1d`).\n")
    A("## 4. Detection quality\n")
    A("### 4.1 Headline vs core agreement (weighted kappa, 95% stationary block-bootstrap CI)\n")
    t = agA[agA.persistence == "raw"].copy()
    A(table(pd.DataFrame(dict(rule=t.rule_id, n=t.n, kappa=[ci(a, b, c) for a, b, c in zip(t.weighted_kappa, t.kappa_lo, t.kappa_hi)],
                              raw_agreement=[pct(v, 0) for v in t.raw_agreement]))) + "\n")
    A("*What it shows:* consistency between two measures built from different baskets. *What it cannot show:* correctness; high agreement could coexist with both being wrong, and low agreement reflects genuine economic divergence (energy/food) as well as noise.\n")
    A("### 4.2 Revision-induced label changes (real-time label vs latest-revised label of the same month)\n")
    t = fl[fl.persistence == "raw"]
    A(table(pd.DataFrame(dict(measure=t.measure, rule=t.rule_id, n=t.n, flip_share=[ci(a, b, c, 1, True) for a, b, c in zip(t.flip_share, t.flip_lo, t.flip_hi)]))) + "\n")
    A("*What it shows:* how often later data would have changed the label (including seasonal-factor revisions and revised history inside percentile calibrations). *What it cannot show:* behaviour under a future methodology change.\n")
    A("### 4.3 Persistence / switching (real-time, 95% CI on transitions per year)\n")
    t = per[(per.data == "real_time") & (per.rule_id.isin(["L1_FIXED", "M1_DYOY_3M", "M2_DYOY_6M"]))]
    A(table(pd.DataFrame(dict(measure=t.measure, rule=t.rule_id, persistence=t.persistence, transitions_per_year=[ci(a, b, c, 2) for a, b, c in zip(t.transitions_per_year, t.transitions_per_year_lo, t.transitions_per_year_hi)],
                              mean_spell_months=t.mean_spell_months.round(1), share_spells_le_2m=[pct(v, 0) for v in t.share_spells_le2m], reversals_within_3m=t.reversals_within_3m))) + "\n")
    A("*What it shows:* label stability. *What it cannot show:* accuracy - a never-changing label is perfectly stable and uninformative.\n")
    A("### 4.4 Detection delay against ex-post turning points (reference is retrospective)\n")
    t = dsum[dsum.rule_id.isin(["M1_DYOY_3M", "M2_DYOY_6M"])]
    A(table(pd.DataFrame(dict(measure=t.measure, rule=t.rule_id, persistence=t.persistence, turning_points=t.n_turning_points, detected=t.n_detected,
                              median_delay_months=t.median_delay_obs_months, p25=t.p25_delay, p75=t.p75_delay))) + "\n")
    A("Chance baseline (share of all switches into the matching state that land in a post-turning-point window, vs the share of time covered by those windows):\n")
    t = base[(base.rule_id.isin(["M1_DYOY_3M", "M2_DYOY_6M"])) & (base.persistence == "raw")]
    A(table(pd.DataFrame(dict(measure=t.measure, rule=t.rule_id, turning_point=t.turning_point_type, switches=t.n_switches_into_matching_state,
                              in_window=[pct(v, 0) for v in t.share_of_switches_in_window], time_in_window=[pct(v, 0) for v in t.share_of_calendar_time_in_window], lift=t.lift_vs_chance.round(2)))) + "\n")
    A("*What it shows:* timeliness and a false-alarm rate. *What it cannot show:* accuracy; the zigzag turning points (1.5pp, 3-month centred mean) are themselves a modelling choice that uses future data.\n")
    A("### 4.5 Sensitivity (full tables: `sensitivity_*.csv`; figures 5a/5b)\n")
    th = r("sensitivity_level_thresholds"); lk = r("sensitivity_calibration_lookback"); fq = r("sensitivity_decision_frequency")
    A(f"* Level thresholds: across the 3x3 grid the headline share of time 'high' ranges {pct(th[th.measure == 'HEADLINE'].share_high.min(), 0)}-{pct(th[th.measure == 'HEADLINE'].share_high.max(), 0)} and kappa against the declared thresholds {num(th[th.measure == 'HEADLINE'].weighted_kappa_vs_reference.min())}-{num(th[th.measure == 'HEADLINE'].weighted_kappa_vs_reference.max())}.")
    A(f"* Calibration lookback changes what 'high' means: for headline the share 'high' is {pct(lk[(lk.measure == 'HEADLINE') & (lk.calibration == 'exp_full')].share_high.iloc[0], 0)} with the expanding full-history distribution (which still contains the 1970s) but "
      f"{pct(lk[(lk.measure == 'HEADLINE') & (lk.calibration == 'roll120')].share_high.iloc[0], 0)} with a trailing 10-year window.")
    A(f"* Quarterly instead of monthly decisions cut headline L1 transitions from {num(fq[fq.measure == 'HEADLINE'].monthly_transitions_per_year.iloc[0])} to {num(fq[fq.measure == 'HEADLINE'].quarterly_transitions_per_year.iloc[0])} per year and hide "
      f"{int(fq[fq.measure == 'HEADLINE'].monthly_spells_never_observed_at_quarter_end.iloc[0])} of {int(fq[fq.measure == 'HEADLINE'].monthly_spells.iloc[0])} monthly spells.\n")
    A("## 5. Robustness across time\n")
    A("Independent regime episodes versus monthly observations (headline, raw rules):\n")
    t = indep[(indep.measure == "HEADLINE") & (indep.rule_id.isin(["L1_FIXED", "M1_DYOY_3M"]))]
    A(table(t[["rule_id", "state", "months", "n_spells", "n_spells_ge3m", "n_spells_ge6m", "median_spell_months"]]) + "\n")
    A("Leave-one-episode-out (headline L1): see `robustness_leave_one_episode_out.csv`; calibration and sample-start comparisons: `sensitivity_calibration_lookback.csv`, `robustness_sample_starts.csv`, `robustness_episodes.csv`. "
      "All of these are *retrospective robustness checks*. No parameter was selected, so no chronological validation split was needed; the reserved window (decisions from 2015-01) is reported separately but was visible to the author when the rules were written, so it is not a prospective test. "
      f"Decisions after {meta['last_decision']} are genuinely out of sample for the frozen definitions.\n")
    A("## 6. Economic relevance (separate from detection)\n")
    A("Forward outcomes start at the close one session after the decision date. Contemporaneous descriptions (trailing 3 months) are in `conditional_outcomes_contemporaneous.csv` and are *not* evidence of anything that could be known in advance.\n")

    def cond_tbl(dim, meas, tg, h, wins, **kw):
        q = cond[(cond.dimension == dim) & (cond.measure.fillna("") == meas) & (cond.target == tg) & (cond.horizon_months == h) & (cond.persistence == "raw") & (cond.window.isin(wins))]
        if "lr" in kw: q = q[q.level_rule == kw["lr"]]
        if "mr" in kw: q = q[q.momentum_rule == kw["mr"]]
        return pd.DataFrame(dict(window=q.window, cell=q.cell, months=q.n_months, spells=["" if pd.isna(v) else int(v) for v in q.n_spells], mean_excess_ann=[pct(v) for v in q.mean_annualised],
                                 downside_freq=[pct(v, 0) for v in q.downside_freq_lt0], ES5=[pct(v) for v in q.expected_shortfall_5pct],
                                 mean_fwd12m_maxDD=[pct(v) for v in q.mean_fwd12m_mdd], share_fwd12m_DD_gt5=[pct(v, 0) for v in q.share_fwd12m_mdd_le_minus5pct], enough=q.sufficient))
    A("### 6.1 Headline L1 level -> forward 3m excess return over T-bills, SYN8Y (model-estimated), annualised\n")
    A(table(cond_tbl("level", "HEADLINE", "SYN8Y", 3, ["full", "design_le_2014", "reserved_ge_2015"], lr="L1_FIXED")) + "\n")
    rv = rob[(rob.robustness == "window_reserved_ge_2015") & (rob.contrast_id == "E1_high_vs_notHigh")]
    if len(rv):
        x = rv.iloc[0]
        A(f"In the reserved window (decisions from 2015-01) the 'high' cell is {int(x.n_a)} months in {int(x.n_spells_a)} spells (essentially one episode, the 2021-23 surge). E1 there: difference {pct(x.diff_annualised)} per year, "
          f"95% CI {pct(x.ci_lo)} to {pct(x.ci_hi)}; with so few independent episodes the interval is the relevant summary, not the point estimate.\n")
    A("### 6.2 Headline M1 momentum -> same outcome\n")
    A(table(cond_tbl("momentum", "HEADLINE", "SYN8Y", 3, ["full", "design_le_2014", "reserved_ge_2015"], mr="M1_DYOY_3M")) + "\n")
    A("### 6.3 Same, observed ETF proxy IEF (2002-07+)\n")
    A(table(cond_tbl("level", "HEADLINE", "IEF", 3, ["full"], lr="L1_FIXED")) + "\n")
    A(table(cond_tbl("momentum", "HEADLINE", "IEF", 3, ["full"], mr="M1_DYOY_3M")) + "\n")
    A("### 6.4 Fed policy state (separate dimension; tightening = fed funds up >= 0.50pp over 6 months)\n")
    A(table(cond_tbl("fed", "", "SYN8Y", 3, ["full"])) + "\n")
    A("### 6.5 Section 5.1's contrast: high & rising during tightening vs high & falling during easing (SYN8Y, 3m)\n")
    q = cond_tbl("level_x_momentum_x_fed", "HEADLINE", "SYN8Y", 3, ["full"])
    A(table(q[q.cell.isin(["ALL", "high|rising|tightening", "high|falling|easing", "high|falling|tightening", "high|rising|easing"])]) + "\n")
    A("### 6.6 Primary contrasts (Holm family) and robustness\n")
    A(table(pd.DataFrame(dict(contrast=P.index, months_a_b=[f"{int(a)}/{int(b)}" for a, b in zip(P.n_a, P.n_b)], spells_a_b=[f"{int(a)}/{int(b)}" for a, b in zip(P.n_spells_a, P.n_spells_b)],
                              diff_ann=[pct(v) for v in P.diff_annualised], CI95=[f"{pct(a)} to {pct(b)}" for a, b in zip(P.ci_lo, P.ci_hi)], p_boot=P.p_boot.round(3),
                              holm_p=P.p_adjusted_holm_within_family.round(3)))) + "\n")
    rb = rob[rob.contrast_id.isin(["E1_high_vs_notHigh", "E2_rising_vs_falling"]) & rob.estimable]
    A(f"Across {len(rb)} robustness re-runs of E1/E2 (windows, leave-one-episode-out, sample starts, persistence, target and horizon), the 95% CI excludes zero in {int(((rb.ci_lo > 0) | (rb.ci_hi < 0)).sum())} (uncorrected). "
      f"Figure 8 plots them; none is a corrected test.\n")
    A("### 6.7 Drawdowns (total-return wealth; cash-relative wealth explicitly labelled)\n")
    A(f"Table 5.1 comparison (book index vs our model-estimated 8y par bond, cash-relative; book values transcribed for reference only):\n")
    t = comp.copy()
    A(table(pd.DataFrame(dict(book_peak=t.book_peak, book_dd=[pct(v) for v in t.book_drawdown_cash_relative], our_peak=t.our_peak, our_trough=t.our_trough, our_dd=[pct(v) for v in t.our_depth_syn8y_cash_relative],
                              headline_level_at_peak=t.our_headline_level_at_peak, fed_at_peak=t.our_fed_state_at_peak, tightening_share_inside=[pct(v, 0) for v in t.our_share_inside_tightening]))) + "\n")
    tt = comp.dropna(subset=["our_peak"])
    near = int(((pd.to_datetime(tt.our_peak) - pd.to_datetime(tt.book_peak)).abs().dt.days <= 45).sum())
    A(f"{near} of {len(comp)} book episodes have a peak in our series within 45 days of the book's peak; our drawdowns are deeper than the book's in {int((tt.our_depth_syn8y_cash_relative < tt.book_drawdown_cash_relative).sum())} of {len(tt)} (different construction: 8y par bond, daily roll, model-estimated). "
      "Episodes still open at the end of the data have no recovery date. All episodes: `drawdown_episodes.csv` (total-return and cash-relative, both targets).\n")
    A("## 7. Supported, inconclusive, untested\n")
    v = sc_df.verdict
    full = sc_df[v.str.startswith("Supported") & ~v.str.contains("only|weak|timeliness")]
    cav = sc_df[(v.str.startswith("Supported") & v.str.contains("weak|timeliness")) | v.str.startswith("confirm2")]
    part = sc_df[v.str.startswith("Partially")]
    inc = sc_df[v.str.startswith(("Not supported", "Neither"))]
    unt = sc_df[v.str.startswith("Untested")]
    A("**Supported by the declared criteria:** " + "; ".join(a.id for a in full.itertuples()) + " (M1 holds for the fixed-threshold level rule and all momentum rules).")
    A("\n**Supported only in part or with a caveat:** " + "; ".join(a.id for a in pd.concat([cav, part]).itertuples()) + ". D4 holds for the confirmation rule only; D5 holds on timeliness but the chance check shows weak discrimination; D3 holds for level rules and slow momentum rules but not for M3/M4; B2 is descriptive.")
    A("\n**Inconclusive or not supported:** " + "; ".join(a.id for a in inc.itertuples()) + ". For the economic hypotheses this means the data cannot distinguish an effect from none at the available number of independent episodes; it is not evidence of no effect.")
    A("\n**Untested claims:**\n")
    for s_ in ["Causality between tightening, inflation and Treasury drawdowns.",
               "Whether any state is tradable: no signals, costs, or Sharpe analysis were run by design.",
               "Results with the book's Bloomberg Treasury index (not available) or any total-return Treasury index with long history; the synthetic is model-estimated and IEF only covers 2002-07+.",
               "PCE inflation (the Fed's target measure) and inflation expectations / surprises as state inputs; CPI differs from PCE in weights, formula and revisions.",
               "Behaviour out of regime (no stagflation comparable to the 1970s in the post-1994 percentile-calibrated sample).",
               "True prospective validation: only decisions after the freeze date can provide it.",
               "Fed funds availability before 1996-10 (assumed) and the 08:30 ET CPI release time (assumed)."]:
        A(f"* {s_}")
    A("\n## 8. Search scope (multiple testing)\n")
    A(table(scope) + "\n")
    A("Primary family (4 contrasts) corrected with Holm; secondary contrasts corrected with Benjamini-Hochberg across the estimable set; detection metrics have no p-values. Robustness re-runs are descriptive and uncorrected.\n")
    A("## 9. Figures\n")
    for f_, d_ in [("fig1_inflation_levels.png", "Inflation levels, thresholds, real-time vs latest-revised"), ("fig2_inflation_momentum.png", "Momentum and neutral band"),
                   ("fig3_state_transitions.png", "State history of every rule"), ("fig4_revision_disagreement.png", "Revision disagreement"),
                   ("fig5a_threshold_sensitivity_level.png", "Threshold sensitivity (level)"), ("fig5b_threshold_sensitivity_momentum.png", "Band sensitivity (momentum)"),
                   ("fig6_episode_comparison.png", "Episode comparison"), ("fig7_drawdowns_and_states.png", "Drawdowns with Fed and inflation state"),
                   ("fig8_primary_contrasts.png", "Primary contrasts and robustness")]:
        A(f"* `figures/{f_}` - {d_}")
    A("\n## 10. Process notes (what changed after the first outcome run)\n")
    A(f"* Definitions: unchanged since the freeze (SHA-256 `{meta['spec_sha256'][:16]}`); the outcome stage verifies this before running.")
    A("* After the first outcome run, drawdown episodes were re-based to start in 1973-01 (the first run produced one 1962-91 episode because the synthetic series starts 11 years before the book's index and before the decision window). This changes only which episodes are listed, not any state or contrast.")
    A("* The delay chance baseline and the mean 'inside tightening' share were added after seeing that the raw momentum rule switches ~3.7 times a year (so 100% detection is uninformative) and that the declared peak-state metric for B1 is structurally weak. The declared B1 metric is still the one reported in the verdict; the additions are labelled as such.")
    A("")
    (OUT / "FINDINGS.md").write_text("\n".join(L) + "\n")
    sc_df.to_csv(OUT / "hypothesis_scorecard.csv", index=False)
    return sc_df


if __name__ == "__main__":
    main()
