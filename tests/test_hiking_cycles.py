import numpy as np
import pandas as pd
import pytest

from test_policy_cycles import events
from research.data import ts
from research.policy_cycles.states import classify_events, cycles, panel
from research.hiking_cycles import outcomes as O, signals as F, spec as S


def good():
    return {"headline_yoy": 2.5, "core_yoy": 2.5, "core_dyoy3": -.4,
            "wages_yoy": 3.0, "wages_dyoy6": -.6,
            "expectations_level": 2.2, "expectations_change3": 0.0,
            **{f"{key}_stale": False for key in ["headline", "core", "wages", "expectations"]}}


def history():
    return classify_events(events([
        ("2024-01-02", 3.5, 3.5, True, "2:00 p.m. EST"),
        ("2024-01-03", 3.5, 3.5, True, "2:00 p.m. EST"),
        ("2024-01-10", 3.75, 3.75, False, "2:00 p.m. EST"),
        ("2024-01-12", 3.75, 3.75, True, "2:00 p.m. EST"),
        ("2024-01-15", 3.5, 3.5, False, "2:00 p.m. EST"),
        ("2024-01-17", 3.5, 3.5, True, "2:00 p.m. EST")]))


def test_smaller_and_intermeeting_hikes_remain_hikes_and_generate_new_pause():
    h = history()
    assert h.state.tolist() == ["hiking", "hold_after_hiking", "hiking", "hold_after_hiking", "easing", "hold_after_easing"]
    pauses = F.candidate_pauses(h)
    assert pauses.announcement_date.tolist() == ["2024-01-03", "2024-01-12"]
    result = O.followup(pauses, h, pd.Timestamp("2024-08-01", tz="UTC"))
    assert bool(result.renewed_hike_6m.iloc[0])
    assert result.days_to_next_hike.iloc[0] == 7
    assert result.days_to_next_cut.iloc[1] == 3
    assert not bool(result.renewed_hike_6m.iloc[1])


def test_incomplete_followup_is_censored_and_later_cut_is_not_backfilled():
    h = history()
    pauses = F.candidate_pauses(h).iloc[:1]
    censored = O.followup(pauses, h, pd.Timestamp("2024-01-05", tz="UTC")).iloc[0]
    assert censored.censored_6m and pd.isna(censored.renewed_hike_6m)
    assert censored.next_cut_censored and pd.isna(censored.next_cut_known_at)
    observed = O.followup(pauses, h, pd.Timestamp("2024-01-11", tz="UTC")).iloc[0]
    assert bool(observed.renewed_hike_6m) and not observed.censored_6m


def test_high_but_falling_is_not_controlled_and_missing_inputs_block_signal():
    assert F.completion_condition(good())["completion_condition"]
    high = {**good(), "headline_yoy": 6.0, "core_yoy": 5.0, "core_dyoy3": -1.0}
    assert not F.completion_condition(high)["completion_condition"]
    assert not F.completion_condition({**good(), "wages_yoy": np.nan})["inputs_complete"]
    assert not F.completion_condition({**good(), "expectations_stale": True})["completion_condition"]
    assert F.completion_condition({**good(), "productivity_yoy": np.nan})["completion_condition"]


def test_filter_waits_rechecks_latches_resets_on_hike_and_enters_on_cut():
    h = history()
    sessions = pd.bdate_range("2024-01-01", "2024-01-19")
    p = panel(h, sessions)
    f = pd.DataFrame({"completion_condition": False}, index=p.decision_ts)
    f.loc[ts("2024-01-05", 16).tz_convert("UTC"), "completion_condition"] = True
    a = F.allocations(p, f)
    assert a.loc["2024-01-03", "baseline_weight"] == 1
    assert a.loc["2024-01-03", "completion_filter_weight"] == 0
    assert a.loc["2024-01-05", "signal_activation"]
    assert a.loc["2024-01-08", "completion_filter_weight"] == 1
    assert a.loc["2024-01-10", "completion_filter_weight"] == 0
    assert a.loc["2024-01-12", "completion_filter_weight"] == 0
    assert a.loc["2024-01-15", "completion_filter_weight"] == 1
    assert not a.loc["2024-01-15", "signal_activation"]


def frames(basis="vintage", availability="2024-01-03"):
    return {key: pd.DataFrame([{
        "observation_date": pd.Timestamp("2023-10-01"), "value": 100.0,
        "availability_ts": pd.Timestamp(availability), "availability_basis": basis,
        "dq_status": "ok", "dq_flags": [], "bronze_id": i + 1,
    }]) for i, key in enumerate(S.SERIES)}


def test_publication_day_uncertainty_and_ingestion_clock_never_leak():
    before = ts("2024-01-03", 16).tz_convert("UTC")
    after = ts("2024-01-04", 16).tz_convert("UTC")
    result = F.feature_snapshots(frames(), [before, after])
    assert pd.isna(result.loc[before, "max_input_known_at"])
    assert result.loc[after, "max_input_known_at"] <= after
    assert result.loc[after, "expectations_level"] == 100
    result = F.feature_snapshots(frames("ingestion_only", "2024-01-03 22:00"), [before, after])
    assert pd.isna(result.loc[before, "max_input_known_at"])
    assert result.loc[after, "max_input_known_at"] == pd.Timestamp("2024-01-03 22:00", tz="UTC")
    revised = frames()
    for key in revised:
        later = revised[key].iloc[0].copy()
        later["availability_ts"] = pd.Timestamp("2024-03-01")
        later["value"], later["bronze_id"] = 999.0, later["bronze_id"] + 100
        revised[key] = pd.concat([revised[key], later.to_frame().T], ignore_index=True)
    pd.testing.assert_frame_equal(F.feature_snapshots(frames(), [after]), F.feature_snapshots(revised, [after]))


def test_one_session_execution_lag_and_same_unambiguous_costs():
    h = history()
    sessions = pd.bdate_range("2024-01-01", "2024-01-19")
    assert O.execution_date(ts("2024-01-02", 14).tz_convert("UTC"), sessions) == pd.Timestamp("2024-01-03")
    assert O.execution_date(ts("2024-01-02", 17).tz_convert("UTC"), sessions) == pd.Timestamp("2024-01-04")
    f = pd.DataFrame({"completion_condition": False, "inputs_complete": True, "inflation_group": "other"},
                     index=panel(h, sessions).decision_ts)
    f.loc[ts("2024-01-05", 16).tz_convert("UTC"), "completion_condition"] = True
    a = F.allocations(panel(h, sessions), f)
    w = pd.Series(1.01 ** np.arange(len(sessions)), index=sessions)
    b = pd.Series(1.001 ** np.arange(len(sessions)), index=sessions)
    daily, _, _, _ = O.strategies(a, sessions, {"SYN2Y": w}, b, cycles(h))
    baseline = daily[daily.rule.eq("baseline")].set_index("execution_date")
    filtered = daily[daily.rule.eq("completion_filter")].set_index("execution_date")
    assert baseline.loc["2024-01-03", "weight"] == 0
    assert baseline.loc["2024-01-04", "weight"] == 1
    assert filtered.loc["2024-01-04", "weight"] == 0
    assert filtered.loc["2024-01-08", "weight"] == 1
    assert filtered.loc["2024-01-08", "net"] == pytest.approx((1 - .0005) * 1.01 - 1)
    assert filtered.loc["2024-01-11", "cost"] == pytest.approx(.0005)


def test_cycle_inference_does_not_count_input_uncovered_cycles_as_evidence():
    records = [{"target": "SYN2Y", "rule": rule, "cycle_id": str(i), "sample": "reserved",
                "complete": True, "informative": i < 2, "net_return": .01 if rule == "baseline" else .02}
               for rule in ["baseline", "completion_filter"] for i in range(6)]
    _, inference = O.cycle_comparison(pd.DataFrame(records))
    row = inference[(inference.target == "SYN2Y") & (inference["sample"] == "all")].iloc[0]
    assert row.complete_cycles == 6 and row.informative_complete_cycles == 2
    assert row.status == "insufficient evidence" and pd.isna(row.cycle_ci_low)


def test_freeze_rejects_rule_changes_before_any_outcomes(tmp_path, monkeypatch):
    hashes = {"events": "fixed", "wages": "fixed"}
    with pytest.raises(RuntimeError, match="Freeze"):
        O.compute(tmp_path, hashes, None, None, None, None, None, None)
    S.freeze(tmp_path, hashes)
    original = (tmp_path / "spec_frozen.json").read_text()
    S.freeze(tmp_path, hashes)
    assert (tmp_path / "spec_frozen.json").read_text() == original
    monkeypatch.setitem(S.SPEC, "cost_per_duration_notional", .01)
    with pytest.raises(RuntimeError, match="changed"):
        O.compute(tmp_path, hashes, None, None, None, None, None, None)
