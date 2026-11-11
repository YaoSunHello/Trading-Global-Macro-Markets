import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research import targets as T
from research.calendar_pit import Calendar
from research.data import asof_snapshot
from research.stats import adjust_pvalues


def test_multiple_testing_adjustments():
    p = pd.Series([0.001, 0.01, 0.04, 0.5, np.nan])
    a = adjust_pvalues(p)
    assert a.loc[0, "p_holm"] == pytest.approx(0.004) and a.loc[1, "p_holm"] == pytest.approx(0.03)   # Holm, m=4 tests: 4x, 3x, 2x
    assert a.loc[2, "p_holm"] == pytest.approx(0.08) and bool(a.loc[2, "reject_holm_5pct"]) is False
    assert (a.loc[:3, "p_bh"] >= p[:4]).all() and np.isnan(a.loc[4, "p_holm"])


def test_par_bond_return_properties():
    # unchanged yield: return = carry (coupon accrual), price back at par
    r = T.par_bond_return(np.array([0.04]), np.array([0.04]), 10.0, np.array([1 / 12]))
    assert r[0] == pytest.approx(0.04 / 12, abs=2e-4)
    up = T.par_bond_return(np.array([0.04]), np.array([0.05]), 10.0, np.array([1 / 12]))[0]
    assert up < 0 and up == pytest.approx(-0.07 + 0.04 / 12, abs=0.012)       # ~ -modified duration (~8) x 1pt


def test_tbill_conversion():
    assert T.tbill_investment_yield(5.0) == pytest.approx(0.0513, abs=1e-3)


def test_calendar_execution_after_availability_and_drops_partial_month():
    sess = pd.bdate_range("2024-01-01", "2024-03-20")
    cal = Calendar(sess, lag=2)
    assert cal.formation[-1] == pd.Timestamp("2024-02-29")        # March is incomplete -> dropped
    F = cal.formation[0]
    assert cal.market_availability(F) < cal.exec_ts(cal.exec_date(0))   # public before the trade
    assert cal.exec_date(0) == sess[sess.get_loc(F) + 2]
    # a lag of 1 would trade BEFORE the H.15 value is assumed public
    assert Calendar(sess, lag=1).market_availability(F) > Calendar(sess, lag=1).exec_ts(Calendar(sess, lag=1).exec_date(0))


def test_asof_snapshot_ignores_future_vintages():
    d = pd.DataFrame({"observation_date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-02-01"]),
                      "availability_ts": pd.to_datetime(["2024-02-13", "2024-03-12", "2024-03-12"]), "bronze_id": [1, 2, 3],
                      "value": [100.0, 101.0, 102.0], "dq_status": "ok"})
    s = asof_snapshot(d, pd.Timestamp("2024-03-01"))
    assert s["value"].to_dict() == {pd.Timestamp("2024-01-01"): 100.0}           # revision (03-12) and Feb value not yet known
    s = asof_snapshot(d, pd.Timestamp("2024-03-12"))
    assert s["value"].to_dict() == {pd.Timestamp("2024-01-01"): 101.0, pd.Timestamp("2024-02-01"): 102.0}
