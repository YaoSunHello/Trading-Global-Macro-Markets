import warnings

import numpy as np
import pandas as pd
import pytest

from conftest import ecb_csv, route_fred
from macrodb import MacroDB
from macrodb.access import PointInTimeWarning
from macrodb.reports import coverage_report, quality_report, write_reports
from macrodb.silver import SilverBuilder

UNRATE, EUR = "US.UNEMPLOYMENT.RATE.SA", "FX.EURUSD.ECB_REF"
VINTAGES = [("2024-01-01", "3.7", "2024-02-02"), ("2024-01-01", "3.8", "2024-03-08"),
            ("2024-02-01", "3.9", "2024-03-08"), ("2024-03-01", ".", "2024-04-05")]


@pytest.fixture
def api(ingester, http, synced, settings):
    route_fred(http, {"UNRATE": VINTAGES})
    days = pd.bdate_range("2024-01-01", periods=30)
    http.on("data-api.ecb.europa.eu", lambda p: (200, ecb_csv([(d.date().isoformat(), f"{1.08 + 0.001 * i:.4f}")
                                                                for i, d in enumerate(days) if i != 10]), "text/csv"))
    ingester.run(series_ids=[UNRATE, EUR]); SilverBuilder(synced).build()
    return MacroDB(settings, con=synced)


def test_latest_first_all_vintages(api):
    latest = api.get(UNRATE, vintage="latest").set_index("observation_date")["value"]
    first = api.get(UNRATE, vintage="first").set_index("observation_date")["value"]
    assert latest[pd.Timestamp("2024-01-01")] == 3.8 and first[pd.Timestamp("2024-01-01")] == 3.7
    assert len(api.get(UNRATE, vintage="all", quality="all")) == 4
    v = api.vintages(UNRATE, "2024-01-01")
    assert v["value"].tolist() == [3.7, 3.8] and v["availability_basis"].eq("vintage").all()


def test_point_in_time_as_of(api):
    a = api.as_of(UNRATE, "2024-02-15").set_index("observation_date")["value"]
    assert a.to_dict() == {pd.Timestamp("2024-01-01"): 3.7}               # Feb not yet published, Jan unrevised
    b = api.as_of(UNRATE, "2024-03-08").set_index("observation_date")["value"]
    assert b.to_dict() == {pd.Timestamp("2024-01-01"): 3.8, pd.Timestamp("2024-02-01"): 3.9}   # day-granular inclusive
    assert api.as_of(UNRATE, "2024-02-01").empty
    assert not api.as_of(UNRATE, pd.Timestamp("2024-03-07 23:59")).pipe(lambda d: d["value"].eq(3.8).any())


def test_vintage_series_has_no_pit_warning(api):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        api.as_of(UNRATE, "2024-03-08")


def test_ingestion_only_series_flagged_for_pit(api):
    with pytest.warns(PointInTimeWarning, match="FX.EURUSD.ECB_REF"):
        df = api.as_of(EUR, "2999-01-01")
    assert not df["pit_reliable"].any() and df["availability_basis"].eq("ingestion_only").all()
    assert api.as_of(EUR, "2999-01-01", pit="strict").empty               # strict refuses unreliable history
    assert api.as_of(EUR, "2000-01-01").empty                             # nothing was known before ingestion
    st = api.pit_status().set_index("series_id")
    assert bool(st.loc[UNRATE, "pit_supported"]) and not bool(st.loc[EUR, "pit_supported"])


def test_quality_filtering_and_missing_not_hidden(api):
    assert api.get(UNRATE, quality="ok")["observation_date"].max() == pd.Timestamp("2024-02-01")
    allq = api.get(UNRATE, quality="all")
    assert allq.loc[allq.observation_date == "2024-03-01", "dq_status"].tolist() == ["missing"]
    assert api.get(UNRATE, quality=["missing"]).shape[0] == 1


def test_date_range_multi_series_and_wide_without_fill(api):
    df = api.get([UNRATE, EUR], start="2024-01-15", end="2024-02-15")
    assert set(df.series_id) == {UNRATE, EUR} and df.observation_date.between("2024-01-15", "2024-02-15").all()
    w = api.get([UNRATE, EUR], start="2024-01-01", end="2024-01-31", wide=True)
    assert list(w.columns) == [EUR, UNRATE]
    assert w[UNRATE].notna().sum() == 1 and w[EUR].notna().all()          # UNRATE is NaN on EUR dates: nothing filled
    assert pd.Timestamp("2024-01-15") not in w.index                       # EUR gap date: no row invented


def test_wide_refuses_ambiguous_versions(api):
    with pytest.raises(ValueError):
        api.to_wide(api.get(UNRATE, vintage="all"))


def test_provider_selection_by_priority_and_explicit(synced, api, settings):
    # add a lower-priority second source for the same canonical series: it must not be mixed in
    synced.execute("""INSERT INTO ref_provider_series VALUES ('ecb','ALT/KEY','value','FX.EURUSD.ECB_REF',NULL,'usd_per_eur','D',
                      50,'ingestion_only',NULL,'alt')""")
    assert api.get(EUR)["provider_id"].unique().tolist() == ["ecb"]
    assert api.get(EUR, provider="ecb").shape == api.get(EUR).shape
    assert api.get(EUR, provider="fred").empty


def test_errors(api):
    with pytest.raises(KeyError):
        api.get("NOPE")
    with pytest.raises(ValueError):
        api.get(UNRATE, vintage="bogus")
    with pytest.raises(ValueError):
        api.get(UNRATE, quality="bogus")


def test_metadata_and_listing(api):
    m = api.metadata(UNRATE)
    assert m["series"]["unit_id"] == "pct" and m["sources"][0]["provider_id"] == "fred"
    assert m["point_in_time"][0]["pit_support"] == "vintage"
    assert UNRATE in api.list_series(category="labour")["series_id"].tolist()
    assert "fred" in api.providers()["provider_id"].tolist()


def test_coverage_report(api):
    cov = coverage_report(api.con, as_of_today=pd.Timestamp("2024-02-10").date()).set_index("series_id")
    e = cov.loc[EUR]
    assert (e.n_obs, e.expected_obs) == (29, 30) and e.completeness_pct == pytest.approx(96.67, abs=0.01)
    u = cov.loc[UNRATE]
    assert u.n_obs == 2 and u.n_missing == 1 and u.revised_obs == 1 and bool(u.pit_reliable)
    assert not bool(cov.loc[EUR, "pit_reliable"])


def test_quality_report_and_files(api, settings):
    q = quality_report(api.con)
    assert "MISSING_VALUE" in q["flags"]["flag"].tolist()
    paths = write_reports(api.con, settings.reports_dir)
    text = (settings.reports_dir / "report.md").read_text()
    assert "WITHOUT reliable historical availability" in text and EUR in text
    assert all(p.exists() for p in paths)


def test_parquet_export(api, settings):
    from macrodb.db import export_parquet
    out = export_parquet(api.con, settings)
    assert any("bronze" in str(p) for p in out)
    assert list(settings.parquet_dir.glob("bronze_batches/*.parquet"))
    n = api.con.execute(f"select count(*) from read_parquet('{settings.parquet_dir}/bronze/**/*.parquet')").fetchone()[0]
    assert n == api.con.execute("select count(*) from bronze_observation").fetchone()[0]


def test_event_driven_series_excluded_from_completeness(ingester, http, synced):
    http.on("data-api.ecb.europa.eu", lambda p: (200, ecb_csv([("2023-09-20", "4.50"), ("2024-06-12", "4.25")],
                                                               "FM.B.U2.EUR.4F.KR.MRR_FR.LEV"), "text/csv"))
    ingester.run(series_ids=["EA.ECB.MRO_RATE"]); SilverBuilder(synced).build()
    r = coverage_report(synced).set_index("series_id").loc["EA.ECB.MRO_RATE"]
    assert r.n_obs == 2 and pd.isna(r.completeness_pct) and pd.isna(r.n_gaps)
    assert len(MacroDB(con=synced).get("EA.ECB.MRO_RATE")) == 2         # and nothing is filled in between
