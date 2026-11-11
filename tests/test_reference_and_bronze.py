import json
import re
from datetime import datetime
from pathlib import Path

import duckdb
import pytest
import yaml

from conftest import CONFIG, ecb_csv, fred_json, route_fred, yahoo_json
from macrodb import catalog
from macrodb.archive import RawArchive
from macrodb.http import HttpClient, ProviderError
from macrodb.ingest import Ingester

UNRATE = "US.UNEMPLOYMENT.RATE.SA"
EUR = "FX.EURUSD.ECB_REF"


def test_catalog_sync_is_idempotent(con, settings, registry):
    a = catalog.sync_all(con, settings, registry)
    before = con.execute("select count(*) from ref_provider_series").fetchone()[0]
    b = catalog.sync_all(con, settings, registry)
    assert a == b and con.execute("select count(*) from ref_provider_series").fetchone()[0] == before
    assert con.execute("select count(*) from ref_series").fetchone()[0] >= 10


def test_foreign_keys_enforced(synced):
    with pytest.raises(duckdb.ConstraintException):
        synced.execute("INSERT INTO ref_series (series_id,name,frequency_id,unit_id,field_id) VALUES ('X','x','Z','pct','value')")
    with pytest.raises(duckdb.ConstraintException):   # bronze row for an unmapped provider series
        synced.execute("INSERT INTO prov_batch VALUES ('b',now(),NULL,'full','ok',NULL,NULL)")
        synced.execute("INSERT INTO prov_raw_response VALUES (1,'b','fred','u',NULL,200,now(),'h',NULL,1,'p')")
        synced.execute("""INSERT INTO bronze_observation VALUES (1,'fred','NOPE','value','2024-01-01',DATE '2024-01-01',NULL,'1',1,
                          NULL,NULL,NULL,NULL,now(),'b',1,'hash')""")


def test_native_unit_dimension_mismatch_rejected(synced, settings, registry, tmp_path):
    doc = {"series": [{"series_id": "T.BAD", "name": "bad", "frequency": "M", "unit": "pct",
                       "sources": [{"provider": "fred", "source_series_id": "X", "native_unit": "usd", "pit_support": "vintage"}]}]}
    p = tmp_path / "c.yaml"; p.write_text(yaml.dump(doc))
    with pytest.raises(ValueError, match="dimension"):
        catalog.sync_catalog(synced, p, registry)


def test_new_series_needs_no_schema_change(synced, settings, registry, http, tmp_path):
    cols_before = synced.execute("describe bronze_observation").fetchall()
    doc = {"series": [{"series_id": "US.NEW.SERIES", "name": "new", "frequency": "M", "unit": "pct",
                       "sources": [{"provider": "fred", "source_series_id": "NEWID", "native_unit": "pct", "pit_support": "vintage"}]}]}
    p = tmp_path / "c.yaml"; p.write_text(yaml.dump(doc))
    catalog.sync_catalog(synced, p, registry)
    route_fred(http, {"NEWID": [("2024-01-01", "1.5", "2024-02-01")]})
    assert Ingester(synced, settings, registry).run(series_ids=["US.NEW.SERIES"])["rows_new"] == 1
    assert synced.execute("describe bronze_observation").fetchall() == cols_before


def test_reingest_is_idempotent_and_revisions_preserved(ingester, http, synced):
    rows = [("2024-01-01", "3.7", "2024-02-02")]
    route_fred(http, {"UNRATE": rows})
    assert ingester.run(series_ids=[UNRATE])["rows_new"] == 1
    assert ingester.run(series_ids=[UNRATE])["rows_new"] == 0          # same payload -> nothing appended
    rows.append(("2024-01-01", "3.8", "2024-03-08"))                    # a revision appears
    assert ingester.run(series_ids=[UNRATE])["rows_new"] == 1
    got = synced.execute("select value_raw, realtime_start from bronze_observation order by bronze_id").fetchall()
    assert [g[0] for g in got] == ["3.7", "3.8"]                         # original kept, revision appended


def test_bronze_preserves_source_representation(ingester, http, synced):
    route_fred(http, {"UNRATE": [("2024-01-01", ".", "2024-02-02"), ("2024-02-01", "3.90", "2024-03-08")]})
    ingester.run(series_ids=[UNRATE])
    rows = synced.execute("select obs_date_raw, value_raw, value_num from bronze_observation order by 1").fetchall()
    assert rows == [("2024-01-01", ".", None), ("2024-02-01", "3.90", 3.9)]   # '.' and '3.90' kept verbatim


def test_raw_archive_traceability_and_secret_redaction(ingester, http, synced, settings):
    payload = fred_json([("2024-01-01", "3.7", "2024-02-02")])
    http.on("api.stlouisfed.org", lambda p: (200, payload, "application/json"))
    ingester.run(series_ids=[UNRATE])
    (rel, sha, params, url), = synced.execute(
        """select r.archive_path, r.content_sha256, r.request_params, r.request_url
           from bronze_observation b join prov_raw_response r using (response_id)""").fetchall()
    assert RawArchive(settings.raw_dir).get(rel) == payload             # byte-exact raw response
    assert "SECRET-KEY-123" not in params + url and "api_key" not in params
    for f in Path(settings.home).rglob("*"):
        if f.is_file() and f.suffix not in (".duckdb", ".wal"):
            assert b"SECRET-KEY-123" not in f.read_bytes()


def test_one_failing_series_does_not_abort_batch(ingester, http, synced):
    http.on("api.stlouisfed.org", lambda p: (500, b"boom", "text/plain"))
    http.on("data-api.ecb.europa.eu", lambda p: (200, ecb_csv([("2024-01-02", "1.0956")]), "text/csv"))
    res = ingester.run(series_ids=[UNRATE, EUR])
    assert (res["status"], res["errors"], res["ok"]) == ("partial", 1, 1)
    st = dict(synced.execute("select provider_id, status from prov_ingestion_task").fetchall())
    assert st == {"fred": "error", "ecb": "ok"}
    assert "HTTP 500" in synced.execute("select error from prov_ingestion_task where provider_id='fred'").fetchone()[0]


def test_ecb_incremental_uses_overlap_window(ingester, http, synced):
    ingester._now = lambda: datetime(2024, 3, 10)
    http.on("data-api.ecb.europa.eu", lambda p: (200, ecb_csv([("2024-03-01", "1.08")]), "text/csv"))
    ingester.run(series_ids=[EUR])
    ingester.run(series_ids=[EUR])
    assert "startPeriod" not in http.calls[0][1]
    assert http.calls[1][1]["startPeriod"] == "2024-02-09"               # refresh date minus 30 days
    ingester.run(series_ids=[EUR], mode="full")
    assert "startPeriod" not in http.calls[2][1]


def test_missed_refreshes_extend_window_but_failures_do_not_advance_it(ingester, http, synced):
    ingester._now = lambda: datetime(2024, 3, 1)
    http.on("data-api.ecb.europa.eu", lambda p: (200, ecb_csv([("2024-02-29", "1.08")]), "text/csv"))
    ingester.run(series_ids=[EUR])
    ingester._now = lambda: datetime(2024, 4, 15)
    http.routes.clear()
    http.on("data-api.ecb.europa.eu", lambda p: (500, b"unavailable", "text/plain"))
    assert ingester.run(series_ids=[EUR])["errors"] == 1
    assert http.calls[-1][1]["startPeriod"] == "2024-03-01"
    ingester._now = lambda: datetime(2024, 4, 20)
    http.routes.clear()
    http.on("data-api.ecb.europa.eu", lambda p: (200, ecb_csv([("2024-04-19", "1.09")]), "text/csv"))
    ingester.run(series_ids=[EUR])
    assert http.calls[-1][1]["startPeriod"] == "2024-03-01"


def test_stale_daily_observations_and_empty_refresh_do_not_expand_window(ingester, http, synced):
    ingester._now = lambda: datetime(2024, 3, 10)
    http.on("data-api.ecb.europa.eu", lambda p: (200, ecb_csv([("2020-01-02", "1.08")]), "text/csv"))
    ingester.run(series_ids=[EUR])
    http.routes.clear()
    http.on("data-api.ecb.europa.eu", lambda p: (404, b"no data", "text/plain"))
    assert ingester.run(series_ids=[EUR])["status"] == "ok"
    assert http.calls[-1][1]["startPeriod"] == "2024-02-09"
    ingester._now = lambda: datetime(2024, 4, 15)
    ingester.run(series_ids=[EUR])
    assert http.calls[-1][1]["startPeriod"] == "2024-03-10"


@pytest.mark.parametrize("series_id, source_id, observation_date, expected", [
    (UNRATE, "UNRATE", "2024-01-01", "2024-01-01"),
    ("US.GDP.REAL.SAAR", "GDPC1", "2023-10-01", "2023-10-01"),
])
def test_low_frequency_refresh_includes_latest_release_period(
        ingester, http, series_id, source_id, observation_date, expected):
    ingester._now = lambda: datetime(2024, 3, 10)
    rows = [(observation_date, "3.7", "2024-02-02")]
    route_fred(http, {source_id: rows})
    ingester.run(series_ids=[series_id])
    assert "observation_start" not in http.calls[-1][1]
    rows.append((observation_date, "3.8", "2024-03-08"))
    assert ingester.run(series_ids=[series_id])["rows_new"] == 1
    assert http.calls[-1][1]["observation_start"] == expected


def test_fred_daily_refresh_bounds_observations_not_vintage_dates(ingester, http, synced):
    ingester._now = lambda: datetime(2024, 3, 10)
    route_fred(http, {"DGS10": [("2024-03-01", "4.0", "2024-03-04")]})
    series_id = "US.TREASURY.CMT.10Y"
    ingester.run(series_ids=[series_id])
    assert "observation_start" not in http.calls[-1][1]
    assert ingester.run(series_ids=[series_id])["rows_new"] == 0
    params = http.calls[-1][1]
    assert params["observation_start"] == "2024-02-09"
    assert params["realtime_start"] == "1776-07-04"
    assert params["realtime_end"] == "9999-12-31"
    assert str(synced.execute("select realtime_start from bronze_observation").fetchone()[0]) == "2024-03-04"
    ingester.run(series_ids=[series_id], mode="full")
    assert "observation_start" not in http.calls[-1][1]


def test_future_projections_do_not_move_refresh_cutoff_into_future(ingester, http):
    ingester._now = lambda: datetime(2024, 3, 10)
    route_fred(http, {"GDPPOT": [("2024-01-01", "100", "2024-02-01"), ("2036-10-01", "200", "2024-02-01")]})
    ingester.run(series_ids=["US.GDP.POTENTIAL.CBO"])
    ingester.run(series_ids=["US.GDP.POTENTIAL.CBO"])
    assert http.calls[-1][1]["observation_start"] == "2024-01-01"


@pytest.mark.parametrize("provider, series_id, route, payload, key, expected", [
    ("yahoo", "SPY.close", "finance.yahoo.com",
     yahoo_json([(1709303400, 1, 2, 0.5, 1.5, 100)]), "period1", 1707436800),
    ("treasury", "US.TREASURY.AVG_RATE.NOTES", "fiscaldata.treasury.gov",
     json.dumps({"data": [{"record_date": "2024-02-29", "avg_interest_rate_amt": "3.4"}],
                 "meta": {"total-pages": 1}}).encode(), "filter", "record_date:gte:2024-02-01"),
])
def test_yahoo_and_treasury_use_shared_refresh_window(
        ingester, http, provider, series_id, route, payload, key, expected):
    ingester._now = lambda: datetime(2024, 3, 10)
    http.on(route, lambda p: (200, payload, "application/json"))
    assert ingester.run(series_ids=[series_id], providers=[provider])["status"] == "ok"
    assert ingester.run(series_ids=[series_id], providers=[provider])["rows_new"] == 0
    value = http.calls[-1][1][key]
    assert value == expected if provider == "yahoo" else expected in value


def test_disabled_provider_skipped_unless_requested(ingester, http, synced):
    assert ingester.run(series_ids=["SPY.close"])["tasks"] == 0


def test_bronze_is_never_updated_or_deleted_by_code():
    src = Path(__file__).resolve().parents[1] / "src" / "macrodb"
    for f in src.rglob("*.py"):
        assert not re.search(r"(UPDATE|DELETE\s+FROM)\s+bronze_observation", f.read_text(), re.I), f


def test_http_client_retries_then_succeeds():
    class R:
        def __init__(self, code): self.status_code, self.headers, self.content, self.url = code, {}, b"ok", "u"
    seq = [R(503), R(429), R(200)]
    c = HttpClient(backoff_s=0, max_retries=3)
    c.session.get = lambda *a, **k: seq.pop(0)
    assert c.get("http://x").status == 200 and not seq


def test_http_client_gives_up():
    class R:
        status_code, headers, content, url = 500, {}, b"", "u"
    c = HttpClient(backoff_s=0, max_retries=1)
    c.session.get = lambda *a, **k: R()
    with pytest.raises(ProviderError):
        c.get("http://x")


def test_missing_credential_is_clear_error(ingester, http, synced, monkeypatch):
    monkeypatch.delenv("FRED_API_KEY")
    ingester.run(series_ids=[UNRATE])
    err = synced.execute("select error from prov_ingestion_task").fetchone()[0]
    assert "FRED_API_KEY" in err


def test_catalog_metadata_change_applies_even_when_referenced(synced, settings, registry, tmp_path):
    import shutil
    cfg = tmp_path / "cfg"; shutil.copytree(CONFIG, cfg)
    c = yaml.safe_load((cfg / "catalog.yaml").read_text())
    c["series"][0]["name"] = "Renamed CPI"
    (cfg / "catalog.yaml").write_text(yaml.dump(c))
    catalog.sync_catalog(synced, cfg / "catalog.yaml", registry)
    assert synced.execute("select name from ref_series where series_id='US.CPI.ALL_ITEMS.SA'").fetchone()[0] == "Renamed CPI"


def test_fred_too_many_vintages_falls_back_without_fake_vintage_dates(ingester, http, synced):
    calls = []
    def h(p):
        calls.append(p)
        if "realtime_start" in p:
            return 400, b'{"error_code":400,"error_message":"There are 5147 vintage dates in the specified real-time period"}', "application/json"
        return 200, fred_json([("2024-01-02", "4.0", "2026-11-10")]), "application/json"   # FRED stamps today
    http.on("api.stlouisfed.org", h)
    res = ingester.run(series_ids=["US.TREASURY.CMT.10Y"])
    assert res["status"] == "ok" and len(calls) == 2
    assert synced.execute("select realtime_start from bronze_observation").fetchone()[0] is None
    assert "no vintage history" in synced.execute("select warnings from prov_ingestion_task").fetchone()[0]
    from macrodb.silver import SilverBuilder
    SilverBuilder(synced).build()
    assert synced.execute("select pit_reliable, dq_flags, dq_status from silver_observation").fetchone() == (False, ["PIT_INFO_MISSING"], "ok")
