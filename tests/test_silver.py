import numpy as np
import pandas as pd
import pytest

from conftest import ecb_csv, route_fred, yahoo_json
from macrodb.silver import SilverBuilder

UNRATE, EUR, PAYROLL = "US.UNEMPLOYMENT.RATE.SA", "FX.EURUSD.ECB_REF", "US.PAYROLLS.NONFARM.SA"


def silver(con, series=None, **kw):
    q = "select * from silver_observation" + (f" where series_id='{series}'" if series else "")
    return con.execute(q + " order by bronze_id").fetchdf()


def test_schema_missing_misaligned_and_future_flags(ingester, http, synced):
    route_fred(http, {"UNRATE": [("2024-01-01", ".", "2024-02-02"), ("2024-02-01", "abc", "2024-03-08"),
                                 ("2024-03-15", "3.9", "2024-04-05"), ("2024-04-01", "4.0", "2024-05-03"),
                                 ("2999-01-01", "4.1", "2024-05-03")]})
    ingester.run(series_ids=[UNRATE])
    SilverBuilder(synced).build()
    df = silver(synced, UNRATE).set_index("source_series_id", drop=False)
    by = {str(r.observation_date.date()): (r.dq_status, list(r.dq_flags)) for r in df.itertuples()}
    assert by["2024-01-01"] == ("missing", ["MISSING_VALUE"])
    assert by["2024-02-01"] == ("invalid", ["BAD_VALUE"])
    assert by["2024-03-01"] == ("suspect", ["FREQ_MISALIGNED"])      # 03-15 normalised to period start; raw kept in Bronze
    assert by["2024-04-01"] == ("ok", [])
    assert "FUTURE_DATE" in by["2999-01-01"][1]
    assert len(df) == 5                                   # flagged, never deleted


def test_lineage_one_silver_row_per_bronze_row(ingester, http, synced):
    route_fred(http, {"UNRATE": [("2024-01-01", "3.7", "2024-02-02"), ("2024-01-01", "3.8", "2024-03-08")]})
    ingester.run(series_ids=[UNRATE]); SilverBuilder(synced).build()
    assert synced.execute("""select count(*) from bronze_observation b full join silver_observation s using (bronze_id)
                             where b.bronze_id is null or s.bronze_id is null""").fetchone()[0] == 0
    assert synced.execute("select count(*) from silver_observation").fetchone()[0] == 2


def test_unit_normalisation_thousands_to_persons(ingester, http, synced):
    route_fred(http, {"PAYEMS": [("2024-01-01", "158000", "2024-02-02")]})
    ingester.run(series_ids=[PAYROLL]); SilverBuilder(synced).build()
    r = silver(synced, PAYROLL).iloc[0]
    assert r.value == 158_000_000 and r.unit_id == "persons"


def test_timestamp_normalisation_to_period_start(ingester, http, synced):
    http.on("data-api.ecb.europa.eu", lambda p: (200, ecb_csv([("2024-01", "2.8")], "ICP/M.U2.N.000000.4.ANR"), "text/csv"))
    ingester.run(series_ids=["EA.HICP.ALL_ITEMS.YOY"]); SilverBuilder(synced).build()
    r = silver(synced, "EA.HICP.ALL_ITEMS.YOY").iloc[0]
    assert str(r.observation_date.date()) == "2024-01-01" and str(r.period_end.date()) == "2024-01-31"


def _eur_rows(n=60, spike_at=None):
    days = pd.bdate_range("2024-01-01", periods=n)
    return [(d.date().isoformat(), f"{(1.08 + 0.002 * np.sin(i) + (0.4 if i == spike_at else 0)):.4f}") for i, d in enumerate(days)], days


def test_outlier_flagged_not_removed(ingester, http, synced):
    rows, days = _eur_rows(spike_at=30)
    http.on("data-api.ecb.europa.eu", lambda p: (200, ecb_csv(rows), "text/csv"))
    ingester.run(series_ids=[EUR]); SilverBuilder(synced).build()
    df = silver(synced, EUR).set_index("observation_date")
    assert "OUTLIER" in df.loc[days[30], "dq_flags"] and df.loc[days[30], "dq_status"] == "suspect"
    assert df.loc[days[30], "value"] == pytest.approx(1.48, abs=0.01)    # value untouched
    assert len(df) == 60
    assert (df["dq_status"] == "suspect").sum() <= 2                     # spike + immediate reversion only


def test_clean_series_has_no_flags(ingester, http, synced):
    rows, _ = _eur_rows()
    http.on("data-api.ecb.europa.eu", lambda p: (200, ecb_csv(rows), "text/csv"))
    ingester.run(series_ids=[EUR]); SilverBuilder(synced).build()
    assert (silver(synced, EUR)["dq_status"] == "ok").all()


def test_duplicate_classification(ingester, http, synced):
    route_fred(http, {"UNRATE": [("2024-01-01", "3.7", "2024-02-02"), ("2024-01-01", "3.8", "2024-03-08"),
                                 ("2024-02-01", "3.9", "2024-03-08"), ("2024-02-01", "3.9", "2024-04-05"),
                                 ("2024-03-01", "4.0", "2024-04-05"), ("2024-03-01", "4.1", "2024-04-05")]})
    ingester.run(series_ids=[UNRATE]); SilverBuilder(synced).build()
    df = silver(synced, UNRATE)
    cls = {(str(r.observation_date.date()), r.value): r.duplicate_class for r in df.itertuples()}
    assert cls[("2024-01-01", 3.7)] == cls[("2024-01-01", 3.8)] == "revision"
    assert cls[("2024-02-01", 3.9)] in ("unique", "duplicate_same_value")
    assert df[df.observation_date == "2024-02-01"].duplicate_class.tolist() == ["unique", "duplicate_same_value"]
    assert cls[("2024-03-01", 4.0)] == cls[("2024-03-01", 4.1)] == "conflict"       # same availability, different values
    assert df[df.observation_date == "2024-03-01"].dq_status.eq("suspect").all()


def test_price_checks_nonpositive_and_ohlc(ingester, http, synced):
    t = 1704205800  # 2024-01-02
    rows = [(t + i * 86400, 100, 101, 99, 100, 10) for i in range(25)]
    rows[5] = (rows[5][0], 100, 99, 98, 100, 10)         # high < open/close
    rows[7] = (rows[7][0], 100, 101, 99, 0, 10)          # close = 0
    http.on("query1.finance.yahoo.com", lambda p: (200, yahoo_json(rows), "application/json"))
    ingester.run(series_ids=[f"SPY.{f}" for f in ("open", "high", "low", "close", "volume")], providers=["yahoo"]); SilverBuilder(synced).build()
    df = silver(synced).set_index(["field_id", "observation_date"])
    assert "OHLC_INCONSISTENT" in df.loc[("high", pd.Timestamp("2024-01-07")), "dq_flags"]
    assert "NONPOSITIVE_PRICE" in df.loc[("close", pd.Timestamp("2024-01-09")), "dq_flags"]


def test_silver_is_idempotent_and_reproducible(ingester, http, synced):
    rows, _ = _eur_rows(spike_at=30)
    http.on("data-api.ecb.europa.eu", lambda p: (200, ecb_csv(rows), "text/csv"))
    ingester.run(series_ids=[EUR])
    b = SilverBuilder(synced)
    assert b.build()["series_rebuilt"] == 1
    first = silver(synced, EUR).drop(columns="silver_run_id")
    assert b.build()["series_rebuilt"] == 0                              # nothing pending
    b.build(full=True)                                                   # full rebuild gives identical content
    pd.testing.assert_frame_equal(first, silver(synced, EUR).drop(columns="silver_run_id"))
    assert synced.execute("select count(*) from silver_run").fetchone()[0] == 3
    assert "mad_to_sigma" in synced.execute("select config_json from silver_run limit 1").fetchone()[0]


def test_new_bronze_rows_trigger_rebuild_of_only_affected_series(ingester, http, synced):
    rows = [("2024-01-01", "3.7", "2024-02-02")]
    route_fred(http, {"UNRATE": rows})
    ingester.run(series_ids=[UNRATE]); SilverBuilder(synced).build()
    rows.append(("2024-01-01", "3.8", "2024-03-08"))
    ingester.run(series_ids=[UNRATE])
    assert SilverBuilder(synced).pending_series() == [UNRATE]
