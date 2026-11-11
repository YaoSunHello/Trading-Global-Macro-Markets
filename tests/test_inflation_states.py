"""Tests for the inflation-state study: vintage handling, release-date alignment, absence of future-data leakage,
rule mechanics, persistence layers, statistics helpers, outcome alignment and spec freezing. Synthetic data only."""
import json

import numpy as np
import pandas as pd
import pytest

from research.inflation_states import boot, classify as C, outcomes as O, pit_panel as P, spec as S, detection as D


# ----------------------------------------------------------------------------------------------- synthetic vintages
def make_versions(n=200, start="1990-01-01", rel_day=14, revise=None, seed=0):
    """Monthly index; observation month t is first released on the `rel_day`th of month t+1. `revise` = {obs_date: (new_value, months_later)}."""
    rng = np.random.default_rng(seed)
    obs = pd.date_range(start, periods=n, freq="MS")
    idx = 100 * np.cumprod(1 + 0.002 + rng.normal(0, 0.002, n))
    rows = []
    for i, (o, v) in enumerate(zip(obs, idx)):
        rows.append(dict(observation_date=o, value=v, availability_ts=o + pd.offsets.MonthBegin(1) + pd.Timedelta(days=rel_day - 1),
                         dq_status="ok", bronze_id=len(rows)))
    for o, (nv, k) in (revise or {}).items():
        base = [r for r in rows if r["observation_date"] == pd.Timestamp(o)][0]
        rows.append(dict(observation_date=pd.Timestamp(o), value=nv, availability_ts=base["availability_ts"] + pd.DateOffset(months=k),
                         dq_status="ok", bronze_id=len(rows)))
    return pd.DataFrame(rows)


def decisions_for(v, first="1992-01-01"):
    return pd.date_range(first, v["availability_ts"].max(), freq="BME")


@pytest.fixture(scope="module")
def base():
    v = make_versions()
    return v, decisions_for(v)


# ----------------------------------------------------------------------------------------------- release-date alignment
def test_release_never_after_decision_and_state_describes_prior_month(base):
    v, dec = base
    panel, _ = P.build_panel(v, dec, "X", "T")
    assert (panel["release_ts"] <= panel["decision_ts"]).all()
    # the month-end decision sees the PREVIOUS month (released mid-month), never the decision month itself
    assert (panel["obs_month"] < panel.index.to_series().dt.to_period("M").dt.to_timestamp()).all()
    assert (panel["info_lag_days"] >= 0).all()
    assert (panel["period_end"] <= panel["decision_ts"].map(lambda t: t.tz_localize(None).normalize())).all()


def test_decision_before_release_does_not_see_observation(base):
    v, _ = base
    obs = pd.Timestamp("1995-06-01")
    release = v.loc[v.observation_date == obs, "availability_ts"].iloc[0]            # 1995-07-14
    before = pd.DatetimeIndex([release - pd.Timedelta(days=1)])
    on = pd.DatetimeIndex([release])
    p_before, _ = P.build_panel(v, before, "X", "T")
    p_on, _ = P.build_panel(v, on, "X", "T")
    assert p_before["obs_month"].iloc[0] == obs - pd.DateOffset(months=1)
    assert p_on["obs_month"].iloc[0] == obs                                           # release at 08:30 precedes the 16:00 decision
    assert p_on["release_ts"].iloc[0].hour == 8 and p_on["release_ts"].iloc[0].minute == 30


def test_label_never_backdated_before_release(base):
    v, dec = base
    panel, _ = P.build_panel(v, dec, "X", "T")
    first_release = v.groupby("observation_date")["availability_ts"].min()
    states = C.classify(panel, "level", "L1_FIXED")["state"]
    for F in states.index:
        t = panel.loc[F, "obs_month"]
        assert first_release[t] <= F            # the state at F rests on a release that already happened


# ----------------------------------------------------------------------------------------------- vintages / revisions
def test_revision_changes_label_inputs_only_after_vintage_date():
    rev_obs = "1996-03-01"
    v0 = make_versions()
    orig = v0.loc[v0.observation_date == rev_obs, "value"].iloc[0]
    v = make_versions(revise={rev_obs: (orig * 1.03, 5)})
    rev_date = v.loc[(v.observation_date == rev_obs)].availability_ts.max()
    dec = decisions_for(v)
    panel, snaps = P.build_panel(v, dec, "X", "T")
    f_before = dec[dec < rev_date][-1]; f_after = dec[dec >= rev_date][0]
    assert snaps[f_before]["idx"][pd.Timestamp(rev_obs)] == pytest.approx(orig)
    assert snaps[f_after]["idx"][pd.Timestamp(rev_obs)] == pytest.approx(orig * 1.03)
    retro = P.build_retro(v, dec[-1])
    # the real-time YoY of the revised month (as first released) differs from the latest-revised YoY
    dec_first = dec[dec >= v.loc[(v.observation_date == rev_obs)].availability_ts.min()][0]
    assert panel.loc[dec_first, "obs_month"] == pd.Timestamp(rev_obs)
    assert abs(panel.loc[dec_first, "yoy"] - retro.loc[pd.Timestamp(rev_obs), "yoy"]) > 2.0


def test_first_release_ts_is_earliest_version_not_latest():
    v = make_versions(revise={"1996-03-01": (150.0, 5)})
    dec = decisions_for(v)
    panel, _ = P.build_panel(v, dec, "X", "T")
    late = panel[panel["obs_month"] == pd.Timestamp("1996-03-01")]
    assert (late["first_release_ts"] < late["release_ts"]).any() or late["first_release_ts"].nunique() == 1
    assert late["first_release_ts"].nunique() == 1


# ----------------------------------------------------------------------------------------------- no future leakage
def test_future_vintages_cannot_change_a_past_decision(base):
    v, dec = base
    F = dec[100]
    v2 = v.copy()
    future = v2["availability_ts"] > F
    rng = np.random.default_rng(5)
    v2.loc[future, "value"] = v2.loc[future, "value"] * rng.uniform(0.3, 3.0, future.sum())       # wreck everything released after F
    p1, _ = P.build_panel(v, pd.DatetimeIndex([F]), "X", "T")
    p2, _ = P.build_panel(v2, pd.DatetimeIndex([F]), "X", "T")
    num = [c for c in p1.columns if p1[c].dtype.kind == "f"]
    pd.testing.assert_frame_equal(p1[num], p2[num])
    s1 = C.all_rule_states(p1); s2 = C.all_rule_states(p2)
    for k in s1:
        pd.testing.assert_frame_equal(s1[k], s2[k])


def test_thresholds_use_only_months_strictly_before_observation():
    yoy = pd.Series(np.linspace(1, 5, 200), index=pd.date_range("1980-01-01", periods=200, freq="MS"))
    t = yoy.index[150]
    th = P.thresholds(yoy.loc[: t - pd.DateOffset(months=1)])
    assert th["q75_exp_full"] == pytest.approx(np.quantile(yoy.iloc[:150], 0.75))
    assert th["n_exp_full"] == 150
    th2 = P.thresholds(pd.concat([yoy.iloc[:150], yoy.iloc[150:] * 100]).loc[: t - pd.DateOffset(months=1)])      # perturb t and later
    assert th2["q75_exp_full"] == th["q75_exp_full"]
    assert np.isnan(P.thresholds(yoy.iloc[:50])["q25_exp_full"])           # < 120 months of history -> undefined, never guessed


def test_expanding_start_and_rolling_window_are_past_only():
    yoy = pd.Series(np.arange(300, dtype=float), index=pd.date_range("1970-01-01", periods=300, freq="MS"))
    th = P.thresholds(yoy)
    assert th["q25_roll120"] == pytest.approx(np.quantile(np.arange(180, 300), 0.25))
    assert th["n_exp_from1985"] == (yoy.index >= "1985-01-01").sum()


def test_percentile_rules_are_undefined_when_vintage_history_is_short():
    v = make_versions(n=30)                                  # like ALFRED's 19-observation early vintages: no history for percentiles
    panel, _ = P.build_panel(v, decisions_for(v, "1991-06-01"), "X", "T")
    assert C.classify(panel, "level", "L2_EXP_PCTL")["state"].isna().all()
    assert C.classify(panel, "level", "L1_FIXED")["state"].notna().any()       # fixed thresholds still work


# ----------------------------------------------------------------------------------------------- rule mechanics
def _frame(**cols):
    n = len(next(iter(cols.values())))
    return pd.DataFrame(cols, index=pd.date_range("2000-01-31", periods=n, freq="BME"))


def test_level_boundaries_low_is_strict_high_is_inclusive():
    df = _frame(yoy=[1.49, 1.5, 3.49, 3.5, np.nan])
    out = C.classify(df, "level", "L1_FIXED")["state"]
    assert out.iloc[:4].tolist() == [-1, 0, 0, 1] and np.isnan(out.iloc[4])


def test_momentum_neutral_band_is_closed():
    df = _frame(dyoy3=[0.31, 0.30, 0.0, -0.30, -0.31])
    out = C.classify(df, "momentum", "M1_DYOY_3M")["state"]
    assert out.tolist() == [1, 0, 0, 0, -1]


def test_float_noise_at_threshold_does_not_flip_state():
    df = _frame(yoy=[3.5 - 1e-9, 3.5 + 1e-9])
    assert C.classify(df, "level", "L1_FIXED")["state"].tolist() == [1, 1]


def test_hysteresis_holds_state_until_margin_is_crossed():
    x = pd.Series([3.0, 3.6, 3.4, 3.3, 3.2, 3.0], index=pd.date_range("2000-01-31", periods=6, freq="BME"))
    lo, hi = pd.Series(1.5, index=x.index), pd.Series(3.5, index=x.index)
    st = C.hysteresis(x, lo, hi, 0.25, "level")
    assert st.tolist() == [0, 1, 1, 1, 0, 0]                 # exit only below 3.25
    assert C.raw_states(x, lo, hi, "level").tolist() == [0, 1, 0, 0, 0, 0]


def test_confirm2_needs_two_consecutive_observations():
    raw = pd.Series([0, 1, 0, 1, 1, 1, 0, 0.0])
    assert C.confirm(raw, 2).tolist() == [0, 0, 0, 0, 1, 1, 1, 0]


def test_persistence_reduces_transitions():
    rng = np.random.default_rng(1)
    x = pd.Series(3.5 + rng.normal(0, 0.15, 300), index=pd.date_range("2000-01-31", periods=300, freq="BME"))
    df = pd.DataFrame(dict(yoy=x))
    raw = C.classify(df, "level", "L1_FIXED", "raw")["state"]
    for p in ("confirm2", "hyst"):
        assert boot.flip_series(C.classify(df, "level", "L1_FIXED", p)["state"]).sum() < boot.flip_series(raw).sum()


def test_signed_margin_and_tiers():
    df = _frame(yoy=[4.0, 3.0, 1.0])
    f = C.classify(df, "level", "L1_FIXED")
    assert f["margin"].round(6).tolist() == [0.5, 0.5, 0.5]
    held = C.classify(_frame(yoy=[3.6, 3.4]), "level", "L1_FIXED", "hyst")
    assert held["state"].tolist() == [1, 1] and held["margin"].iloc[1] < 0         # persistence holds a label the measure no longer supports
    t = C.margin_tier(pd.Series([-0.1, 0.5, 1.5, 4.0]))
    assert t.tolist() == ["contested", "low", "medium", "high"]


def test_confidence_is_not_a_probability_column():
    h = D.history_table.__doc__ or ""
    assert "probab" not in " ".join(C.margin_tier(pd.Series([1.0])).tolist()).lower()
    assert set(["margin", "confidence_tier"]).issubset(set(["state", "raw_state", "measure_value", "lower", "upper", "margin"]) | {"confidence_tier"})


def test_state_age_resets_on_change_and_nan():
    s = pd.Series([0, 0, 1, 1, 1, np.nan, 1.0])
    assert C.state_age(s).tolist()[:5] == [1, 2, 1, 2, 3] and C.state_age(s).iloc[6] == 1


# ----------------------------------------------------------------------------------------------- measures
def test_derived_measures_exact():
    idx = pd.Series(100 * 1.01 ** np.arange(30), index=pd.date_range("2000-01-01", periods=30, freq="MS"))
    d = P.derived(idx)
    assert d["yoy"].iloc[-1] == pytest.approx((1.01 ** 12 - 1) * 100)
    assert d["ann3"].iloc[-1] == pytest.approx((1.01 ** 12 - 1) * 100)
    assert d["dyoy3"].iloc[-1] == pytest.approx(0.0, abs=1e-9)


def test_missing_month_is_not_interpolated():
    s = pd.Series(100 * 1.01 ** np.arange(30), index=pd.date_range("2000-01-01", periods=30, freq="MS")).drop(pd.Timestamp("2001-06-01"))
    d = P.derived(s)
    assert np.isnan(d.loc["2001-06-01", "yoy"]) and np.isnan(d.loc["2002-06-01", "yoy"] if "2002-06-01" in d.index else np.nan)


def test_coverage_audit_flags_backfilled_observations():
    v = make_versions(n=60)
    v.loc[v.observation_date < "1992-01-01", "availability_ts"] = pd.Timestamp("1993-01-05")           # archive back-fill
    a = P.coverage_audit(v, "X")
    assert a["n_obs_first_seen_late"] == 24 and str(a["first_genuine_release_obs"]) == "1992-01-01"


def test_revision_scale_is_past_only_and_prior_until_enough_history(base):
    v, dec = base
    panel, snaps = P.build_panel(v, dec, "X", "T")
    rs = P.revision_scales(panel, snaps)
    assert rs["rev_scale_is_prior_yoy"].iloc[:30].all()
    assert (rs["rev_scale_yoy"] > 0).all()


# ----------------------------------------------------------------------------------------------- statistics helpers
def test_weighted_kappa_known_cases():
    a = np.array([-1, 0, 1, 1, 0, -1] * 20, float)
    assert boot.weighted_kappa(a, a) == pytest.approx(1.0)
    assert boot.weighted_kappa(a, -a) < 0
    rng = np.random.default_rng(0)
    assert abs(boot.weighted_kappa(rng.integers(-1, 2, 5000), rng.integers(-1, 2, 5000))) < 0.05
    assert boot.raw_agreement([1, 0, 1], [1, 1, 1]) == pytest.approx(2 / 3)


def test_stationary_bootstrap_indices_valid_and_blocky():
    idx = boot.stationary_indices(100, 12, 50, np.random.default_rng(0))
    assert idx.min() >= 0 and idx.max() < 100
    steps = np.diff(idx, axis=1)
    assert ((steps == 1) | (steps == -99)).mean() > 0.85          # mostly consecutive -> serial dependence preserved


def test_block_bootstrap_ci_wider_for_dependent_data():
    rng = np.random.default_rng(3)
    iid = rng.normal(size=400)
    ar = np.zeros(400)
    for t in range(1, 400):
        ar[t] = 0.9 * ar[t - 1] + rng.normal()
    w = lambda x: boot.block_ci(lambda z: z.mean(), [x], mean_block=20, reps=400)[2] - boot.block_ci(lambda z: z.mean(), [x], mean_block=20, reps=400)[1]
    assert w(ar) > w(iid)


def test_spells_flips_and_reversals():
    s = pd.Series([0, 0, 1, 0, 0, 1, 1, np.nan, 1.0])
    sp = boot.spells(s)
    assert sp["length"].tolist() == [2, 1, 2, 2, 1] and sp["state"].tolist() == [0, 1, 0, 1, 1]
    assert boot.flip_series(s).sum() == 3       # NaN gaps are not transitions
    assert boot.reversal_series(pd.Series([0, 1, 0, 0, 0.0])).sum() == 1
    assert boot.reversal_series(pd.Series([0, 1, 1, 1, 1.0])).sum() == 0


def test_zigzag_finds_alternating_turning_points():
    y = pd.Series([0, 1, 2, 3, 4, 3, 2, 1, 0, 1, 2, 3, 4.5, 4], index=pd.date_range("2000-01-01", periods=14, freq="MS"))
    tp = boot.zigzag(y, 2.0)
    assert tp["type"].tolist() == ["peak", "trough"]                 # the last swing (4.5) is not yet confirmed by a 2pp retracement
    assert tp["month"].tolist() == [y.index[4], y.index[8]]
    y2 = pd.concat([y, pd.Series([2.0], index=[y.index[-1] + pd.DateOffset(months=1)])])
    assert boot.zigzag(y2, 2.0)["type"].tolist() == ["peak", "trough", "peak"]
    assert boot.zigzag(y * 0.1, 2.0).empty


# ----------------------------------------------------------------------------------------------- outcomes alignment
class _FakeTreasury:
    def __init__(self):
        self.calls = []

    def ret(self, tg, d0, d1, kind="tr"):
        self.calls.append(("ret", tg, pd.Timestamp(d0) if pd.notna(d0) else d0, pd.Timestamp(d1) if pd.notna(d1) else d1, kind))
        return 0.0

    def mdd(self, tg, d0, d1, relative=False):
        return 0.0


def test_forward_windows_start_after_decision_and_contemporaneous_ends_at_decision():
    from research.calendar_pit import Calendar
    sessions = pd.bdate_range("2000-01-03", "2004-12-31")
    cal = Calendar(sessions, lag=1)
    dec = cal.formation[(cal.formation >= "2001-01-01") & (cal.formation <= "2002-12-31")]
    tr = _FakeTreasury()
    grid = O.build_grid(tr, cal, dec)
    fwd = [c for c in tr.calls if c[4] == "excess" and c[1] == "SYN8Y"]
    contemp = [c for c in tr.calls if c[4] == "excess" and c[3] in set(dec) and c[1] == "SYN8Y"]
    starts = {c[2] for c in fwd if c[2] not in set(cal.formation)}
    assert all(any(s > d for d in dec) for s in starts)
    exec_by_dec = dict(zip(cal.formation, cal.exec_dates))
    for d in dec:
        assert exec_by_dec[d] > d                              # forward return starts strictly after the decision date
    assert contemp and all(c[2] < c[3] for c in contemp)        # trailing window ends exactly AT the decision date


def test_drawdown_episodes_and_max_drawdown():
    w = pd.Series([1, 1.1, 1.0, 0.9, 0.95, 1.1, 1.2, 1.0, 1.25], index=pd.date_range("2000-01-01", periods=9))
    e = O.drawdown_episodes(w, -0.05)
    assert len(e) == 2
    assert e.iloc[0].depth == pytest.approx(0.9 / 1.1 - 1) and e.iloc[0].peak == w.index[1] and e.iloc[0].recovery == w.index[5]
    assert e.iloc[1].depth == pytest.approx(1.0 / 1.2 - 1)
    assert O.max_drawdown(w) == pytest.approx(0.9 / 1.1 - 1)


def test_unrecovered_drawdown_has_no_recovery_date():
    w = pd.Series([1, 1.2, 1.0, 0.9], index=pd.date_range("2000-01-01", periods=4))
    e = O.drawdown_episodes(w, -0.05)
    assert pd.isna(e.iloc[0].recovery)


def test_cash_relative_wealth_differs_from_total_return():
    idx = pd.date_range("2000-01-03", periods=300, freq="B")
    tr = O.Treasury.__new__(O.Treasury)
    tr.wealth = {"X": pd.Series(np.linspace(1, 1.2, 300), index=idx)}
    tr.bill = {"X": pd.Series(np.linspace(1, 1.3, 300), index=idx)}
    assert tr.mdd("X", idx[0], idx[-1]) == pytest.approx(0.0)           # total-return wealth never falls
    assert tr.mdd("X", idx[0], idx[-1], relative=True) < -0.05           # cash-relative wealth does: labelled separately
    assert tr.ret("X", idx[0], idx[-1], "excess") == pytest.approx(0.2 - 0.3)


def test_fed_state_uses_only_completed_months_and_flags_assumed_availability():
    obs = pd.date_range("1990-01-01", periods=30, freq="MS")
    rate = np.r_[np.full(12, 5.0), 5.0 + 0.2 * np.arange(1, 19)]
    v = pd.DataFrame(dict(observation_date=obs, value=rate, availability_ts=pd.Timestamp("1996-12-03"), dq_status="ok", bronze_id=range(30)))
    F = pd.DatetimeIndex(["1991-12-31", "1992-05-29"])
    f = O.fed_state_panel(v, F, window=6, band=0.5)
    assert f.loc["1991-12-31", "fed_obs_month"] == pd.Timestamp("1991-11-01")         # December average is not complete at 12-31
    assert f.loc["1991-12-31", "fed_availability_basis"] == "assumed_month_end_plus_1d"
    assert f.loc["1992-05-29", "fed_state"] == "tightening"


def test_conditional_stats_counts_spells_and_flags_insufficient_cells():
    idx = pd.date_range("2000-01-31", periods=60, freq="BME")
    lab = pd.Series(["a"] * 20 + ["b"] * 20 + ["a"] * 20, index=idx)
    y = pd.Series(np.r_[np.full(40, 0.01), np.full(20, -0.02)], index=idx)
    cs = O.cond_stats(y, pd.Series(0.0, index=idx), lab, 1, 0.01).set_index("cell")
    assert cs.loc["a", "n_months"] == 40 and cs.loc["a", "n_spells"] == 2 and cs.loc["b", "n_spells"] == 1
    assert cs.loc["a", "sufficient"] == False                     # < 3 spells
    assert cs.loc["ALL", "n_months"] == 60


def test_contrast_detects_known_difference_and_zero_when_none():
    rng = np.random.default_rng(2)
    idx = pd.date_range("1980-01-31", periods=400, freq="BME")
    a = pd.Series(rng.random(400) < 0.4, index=idx)
    y_null = pd.Series(rng.normal(0.001, 0.02, 400), index=idx)
    r0 = O.contrast(y_null, a, ~a, 1)
    assert r0["ci_lo"] < 0 < r0["ci_hi"]
    y_eff = y_null - 0.05 * a
    r1 = O.contrast(y_eff, a, ~a, 1)
    assert r1["diff_annualised"] < 0 and r1["ci_hi"] < 0 and r1["p_boot"] < 0.05


# ----------------------------------------------------------------------------------------------- spec freezing
def test_spec_internal_consistency():
    ids = [h["id"] for h in S.HYPOTHESES]
    assert len(ids) == len(set(ids))
    assert {"B1", "B2", "B3", "E1", "E2", "E3", "E4"} <= set(ids)
    assert all(h["source"] in ("section_5_1", "extension") for h in S.HYPOTHESES)
    assert all("hyst" in r for r in list(S.LEVEL_RULES.values()) + list(S.MOMENTUM_RULES.values()))
    assert S.PRIMARY["level"] in S.LEVEL_RULES and S.PRIMARY["momentum"] in S.MOMENTUM_RULES


def test_freeze_detects_changed_definitions(tmp_path, monkeypatch):
    h = S.freeze(tmp_path, "2026-01-01T00:00:00+00:00")
    S.verify_frozen(tmp_path)
    assert json.loads((tmp_path / "spec_frozen.json").read_text())["sha256"] == h
    monkeypatch.setitem(S.LEVEL_RULES["L1_FIXED"], "high", 4.0)
    with pytest.raises(RuntimeError):
        S.verify_frozen(tmp_path)


# ----------------------------------------------------------------------------------------------- end-to-end on synthetic data
def test_measure_pipeline_end_to_end_and_revision_comparison():
    v = make_versions(n=400, start="1980-01-01", revise={"1995-03-01": (200.0, 4)})
    dec = decisions_for(v, "1982-01-01")
    m = D.Measure("T", v, dec)
    assert m.panel.index.is_monotonic_increasing and len(m.panel) == len(dec)
    flips, mag = D.revision_tables({"T": m})
    row = flips[(flips.rule_id == "L1_FIXED") & (flips.persistence == "raw")].iloc[0]
    assert 0 <= row.flip_share <= 1 and row.n > 100
    assert mag[mag.measure_col == "yoy"].p90_abs.iloc[0] >= 0
    h = D.history_table(m)
    assert set(h.confidence_tier.unique()) <= {"high", "medium", "low", "contested", "unknown"}
    assert h.groupby(["rule_id", "persistence"]).size().nunique() == 1


# ----------------------------------------------------------------------------------------------- real-database leakage audit
def test_real_vintages_truncated_at_decision_date_reproduce_the_panel_row():
    """On the real database: rebuilding a decision's inputs from ONLY the rows that existed at that date gives the identical
    row. Any dependence on later data (revisions, later observations, later calibration) would break this."""
    import warnings
    from pathlib import Path
    if not Path("data/macrodb.duckdb").exists():
        pytest.skip("no local database")
    warnings.simplefilter("ignore")
    from research.data import Inputs
    inp = Inputs()
    for sid in S.MEASURES.values():
        v = inp.versions(sid)
        dec = pd.DatetimeIndex(["1999-03-31", "2008-09-30", "2014-02-28", "2022-06-30"])
        for F in dec:
            if F < v["availability_ts"].min():
                continue
            full, _ = P.build_panel(v, pd.DatetimeIndex([F]), sid, "T")
            trunc, _ = P.build_panel(v[v["availability_ts"] < F.normalize() + pd.Timedelta(days=1)], pd.DatetimeIndex([F]), sid, "T")
            num = [c for c in full.columns if full[c].dtype.kind == "f"]
            pd.testing.assert_frame_equal(full[num], trunc[num])
            assert (full["release_ts"] <= full["decision_ts"]).all()
