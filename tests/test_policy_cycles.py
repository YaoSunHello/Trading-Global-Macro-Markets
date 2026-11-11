import json

import numpy as np
import pandas as pd
import pytest

from research import targets as T
from research.policy_cycles import events as E, outcomes as O, spec as S, states as P
from research.policy_cycles.run import inflation_panel


def events(actions):
    rows = []
    previous = (3.0, 3.0)
    for i, (date, low, high, scheduled, clock) in enumerate(actions):
        release, known, basis = E.announcement_time(f"For release at {clock}" if clock else "", date)
        rows.append({"event_id": f"E{i}", "announcement_date": date, "announcement_ts": release, "known_at": known,
                     "timing_basis": basis, "scheduled": scheduled, "target_low": low, "target_high": high,
                     "previous_low": previous[0], "previous_high": previous[1],
                     "target_kind": "single" if low == high else "range"})
        previous = (low, high)
    return pd.DataFrame(rows)


def test_unknown_hike_scheduled_hold_ease_and_hold_ease():
    d = events([
        ("1994-02-01", 3, 3, True, "2:00 p.m. EST"),
        ("1994-02-04", 3.25, 3.25, True, None),
        ("1994-02-10", 3.25, 3.25, False, None),
        ("1994-03-22", 3.25, 3.25, True, None),
        ("1994-04-18", 3.5, 3.5, False, None),
        ("1994-05-17", 3.5, 3.5, True, None),
        ("1994-07-06", 3.25, 3.25, True, None),
        ("1994-08-16", 3.25, 3.25, True, None)])
    h = P.classify_events(d)
    assert h.state.tolist() == ["unknown", "hiking", "hiking", "hold_after_hiking",
                                "hiking", "hold_after_hiking", "easing", "hold_after_easing"]
    assert h.consecutive_scheduled_holds.tolist() == [1, 0, 0, 1, 0, 1, 0, 1]
    assert pd.isna(h.last_change_known_at.iloc[0])
    assert h.time_since_last_change_days.iloc[3] > 0
    assert h.time_since_last_change_days.iloc[4] == 0


def test_consecutive_holds_reset_on_intermeeting_reversal_and_cycles():
    d = events([
        ("1994-02-04", 3.25, 3.25, True, None),
        ("1994-03-22", 3.25, 3.25, True, None),
        ("1994-05-17", 3.25, 3.25, True, None),
        ("1994-06-01", 3, 3, False, None),
        ("1994-07-06", 3, 3, True, None),
        ("1994-08-16", 3.25, 3.25, True, None)])
    h = P.classify_events(d)
    assert h.consecutive_scheduled_holds.tolist() == [0, 1, 2, 0, 1, 0]
    assert h.state.iloc[3] == "easing"
    assert h.cycle_id.iloc[0] == h.cycle_id.iloc[4] != h.cycle_id.iloc[5]
    cycles = P.cycles(h)
    assert cycles.complete.tolist() == [True, False]


def test_single_target_to_range_zlb_and_width_only_change():
    d = events([
        ("2008-10-29", 1, 1, True, None),
        ("2008-12-16", 0, 0.25, True, None),
        ("2009-01-28", 0, 0.25, True, None),
        ("2009-02-01", -0.125, 0.375, False, None)])
    h = P.classify_events(d)
    assert h.state.tolist() == ["easing", "easing", "hold_after_easing", "hold_after_easing"]
    assert h.zlb.tolist() == [False, True, True, False]
    assert h.target_kind.iloc[0] == "single" and h.target_kind.iloc[1] == "range"
    assert h.last_change_known_at.iloc[3] == h.last_change_known_at.iloc[1]
    assert h.consecutive_scheduled_holds.iloc[3] == 0


def test_no_hold_after_hiking_before_subsequent_scheduled_hold():
    d = events([("2024-01-02", 3.25, 3.25, True, "2:00 p.m. EST"),
                ("2024-01-04", 3.25, 3.25, True, "2:00 p.m. EST")])
    p = P.panel(P.classify_events(d), pd.bdate_range("2024-01-01", "2024-01-05"))
    assert p.state.tolist() == ["unknown", "hiking", "hiking", "hold_after_hiking", "hold_after_hiking"]


def test_exact_release_clock_date_only_and_after_close_no_leakage():
    d = events([("2024-01-02", 3.25, 3.25, True, None),
                ("2024-01-04", 3, 3, False, "5:00 p.m. EST")])
    p = P.panel(P.classify_events(d), pd.bdate_range("2024-01-01", "2024-01-08"))
    assert p.loc["2024-01-02", "state"] == "unknown"
    assert p.loc["2024-01-03", "state"] == "hiking"
    assert p.loc["2024-01-04", "state"] == "hiking"
    assert p.loc["2024-01-05", "state"] == "easing"
    for date, row in p.dropna(subset=["known_at"]).iterrows():
        assert row.known_at <= row.decision_ts
    release, known, basis = E.announcement_time("For release at 7:00 a.m. EDT", "2008-10-08")
    assert pd.Timestamp(release).hour == 7 and pd.Timestamp(release).utcoffset().total_seconds() == -14400


def test_sunday_announcement_and_one_session_execution_lag():
    d = events([("2020-03-15", 0, 0.25, False, "5:00 p.m. EDT")])
    history = P.classify_events(d)
    sessions = pd.bdate_range("2020-03-13", "2020-03-20")
    wealth = {"SYN8Y": pd.Series(np.cumprod(np.r_[1, np.repeat(1.01, len(sessions) - 1)]), index=sessions)}
    bill = pd.Series(1.0, index=sessions)
    daily, _, _ = O.strategy(history, P.cycles(history), sessions, wealth, bill)
    assert daily.loc["2020-03-16", "weight"] == 0
    assert daily.loc["2020-03-17", "weight"] == 1
    assert daily.loc["2020-03-17", "cost"] == pytest.approx(0.0005)


def test_duration_transaction_costs_charge_only_one_leg_and_initial_entry():
    idx = pd.bdate_range("2024-01-01", periods=5)
    duration = pd.Series([0.01, 0.02, -0.01, 0.01, 0], index=idx)
    bills = pd.Series(0.001, index=idx)
    weights = pd.Series([1, 1, 0, 0, 1], index=idx)
    d = O.allocation_returns(duration, bills, weights)
    assert d.cost.tolist() == pytest.approx([0.0005, 0, 0.0005, 0, 0.0005])
    assert d.net.iloc[0] == pytest.approx((1 - 0.0005) * 1.01 - 1)
    assert d.net.iloc[2] == pytest.approx((1 - 0.0005) * 1.001 - 1)
    assert d.net.iloc[3] == pytest.approx(0.001)


def test_synthetic_2y_8y_returns_and_zero_yield_limit():
    dates = pd.to_datetime(["2024-01-05", "2024-01-08", "2024-01-09"])
    y = pd.Series([4, 4, 5], index=dates)
    two, eight = O.synthetic_wealth(y, 2), O.synthetic_wealth(y, 8)
    assert two.iloc[1] / two.iloc[0] - 1 == pytest.approx(0.04 * 3 / 365)
    assert eight.iloc[2] / eight.iloc[1] < two.iloc[2] / two.iloc[1]
    assert T.par_bond_return(np.array([0.0]), np.array([0.0]), 2, np.array([1 / 365]))[0] == 0
    r = T.par_bond_return(np.array([0.04]), np.array([0.0]), 2, np.array([1 / 365]))[0]
    assert r == pytest.approx(0.04 * 1 / 365 + 0.02 * 2 * (2 - 1 / 365))
    bill_rate = pd.Series(5.0, index=dates)
    bill = O.Treasury._bill(bill_rate, dates)
    assert bill.iloc[1] == pytest.approx(1 + T.tbill_investment_yield(5) * 3 / 365)


def test_forward_windows_start_one_session_later_and_do_not_bridge_missing_values():
    sessions = pd.bdate_range("2024-01-01", "2024-08-30")
    d = events([("2024-01-02", 3.25, 3.25, True, "2:00 p.m. EST")])
    history = P.classify_events(d)
    w = pd.Series(np.linspace(1, 1.2, len(sessions)), index=sessions)
    bill = pd.Series(np.linspace(1, 1.02, len(sessions)), index=sessions)
    grid = O.forward_grid(history, P.cycles(history), sessions, {"SYN2Y": w}, bill)
    row = grid.loc["2024-01-31"]
    assert row.execution_date == pd.Timestamp("2024-02-01")
    assert row.end_1m == pd.Timestamp("2024-03-01")
    expected = w[row.end_1m] / w[row.execution_date] - bill[row.end_1m] / bill[row.execution_date]
    assert row.SYN2Y_1m_excess == pytest.approx(expected)
    assert pd.isna(grid.iloc[-1].SYN2Y_1m_excess)
    w.loc["2024-02-15"] = np.nan
    assert np.isnan(O.return_between(w, row.execution_date, row.end_1m))


def test_whole_cycle_reserved_labels_do_not_split_in_2015():
    d = events([("2014-12-15", 3.25, 3.25, True, "2:00 p.m. EST"),
                ("2015-01-15", 3, 3, True, "2:00 p.m. EST"),
                ("2015-12-15", 3.25, 3.25, True, "2:00 p.m. EST")])
    h = P.classify_events(d)
    p = P.panel(h, pd.to_datetime(["2015-06-01", "2016-01-04"]))
    assert p["sample"].tolist() == ["design", "reserved"]


def test_inference_uses_complete_cycles_not_months_or_spells():
    g = pd.DataFrame({"cycle_id": ["A"] * 100, "excess": np.arange(100) / 1000})
    cycles = pd.DataFrame({"cycle_id": ["A", "B"], "complete": [True, False]})
    assert all(np.isnan(x) for x in O.cycle_interval(g, cycles))
    g = pd.DataFrame({"cycle_id": list("ABCDEF") + ["OPEN"] * 100, "excess": [0.01] * 106})
    cycles = pd.DataFrame({"cycle_id": list("ABCDEF") + ["OPEN"], "complete": [True] * 6 + [False]})
    assert all(np.isnan(x) for x in O.cycle_interval(g, cycles))


def test_freeze_blocks_spec_input_and_artifact_changes_before_outcomes(tmp_path, monkeypatch):
    hashes = {"events": "abc", "yields": "def"}
    with pytest.raises(RuntimeError, match="Freeze"):
        O.compute(tmp_path, hashes, {}, None, None, None, None)
    S.freeze(tmp_path, hashes)
    original = (tmp_path / "spec_frozen.json").read_text()
    S.freeze(tmp_path, hashes)
    assert (tmp_path / "spec_frozen.json").read_text() == original
    monkeypatch.setitem(S.SPEC, "cost_per_duration_notional", 0.01)
    with pytest.raises(RuntimeError, match="changed"):
        O.compute(tmp_path, hashes, {}, None, None, None, None)
    with pytest.raises(RuntimeError, match="changed"):
        S.freeze(tmp_path, hashes)
    monkeypatch.setitem(S.SPEC, "cost_per_duration_notional", 0.0005)
    with pytest.raises(RuntimeError, match="changed"):
        S.verify(tmp_path, {"events": "different", "yields": "def"})
    f = json.loads(original); f["spec"]["zlb_upper_pct"] = 100
    (tmp_path / "spec_frozen.json").write_text(json.dumps(f))
    with pytest.raises(RuntimeError, match="changed"):
        S.verify(tmp_path, hashes)


def test_historical_index_excludes_cancelled_and_communications_review():
    body = """
    <h5>September 15 Meeting - 2003</h5><a href="/fomc/minutes/20030812.htm">Minutes</a>
    <h5>September 16 Meeting - 2003</h5><a href="/boarddocs/press/monetary/2003/20030916/default.htm">Statement</a>
    <h5>October 28 (cancelled) Meeting - 2003</h5>
    """
    rows = E.historical_index(body, 2003, "index")
    assert len(rows) == 2 and rows[0]["scheduled"] is False and rows[1]["scheduled"] is True
    assert rows[0]["meeting_date"] == "2003-09-15"
    body = '<h5>January 21 Conference Call - 2008</h5><a href="/newsevents/press/monetary/20080122b.htm">Statement</a>'
    row = E.historical_index(body, 2008, "index")[0]
    assert row["meeting_date"] == "2008-01-21"
    assert E.url_date(row["statement_url"]) == pd.Timestamp("2008-01-22")


def test_inflation_groups_are_exclusive_and_unknown_is_not_other():
    obs = pd.date_range("1992-01-01", periods=38, freq="MS")
    versions = pd.DataFrame({"observation_date": obs, "value": 100 * 1.004 ** np.arange(len(obs)),
                             "availability_ts": obs + pd.offsets.MonthBegin(1) + pd.Timedelta(days=13),
                             "dq_status": "ok", "bronze_id": np.arange(len(obs))})
    decisions = pd.to_datetime(["1992-02-28", "1994-01-31", "1994-02-28"])
    p = inflation_panel(versions, decisions)
    assert pd.isna(p.inflation_group.iloc[0])
    assert p.inflation_group.iloc[1] == "other_known_inflation"
    assert (pd.to_datetime(p.inflation_observation_month.iloc[1:]) < decisions[1:]).all()
    changed = versions.copy()
    changed.loc[changed.availability_ts > decisions[-1], "value"] *= 2
    pd.testing.assert_frame_equal(p, inflation_panel(changed, decisions))
    grid = pd.DataFrame({"state": ["hold_after_hiking"] * 50,
                         "inflation_group": ["high_and_rising"] * 25 + ["other_known_inflation"] * 25,
                         "cycle_id": ["A"] * 50, "SYN8Y_3m_excess": [0.01] * 50})
    counts, comparison = O.inflation_comparison(grid, pd.DataFrame({"cycle_id": ["A"], "complete": [True]}))
    assert counts.months.sum() == len(grid)
    assert comparison["status"] == "insufficient evidence" and comparison["difference"] is None
