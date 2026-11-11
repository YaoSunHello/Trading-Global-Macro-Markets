import hashlib
import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from conftest import fred_json
from macrodb import MacroDB
from macrodb.archive import RawArchive
from macrodb.ingest import Ingester
from macrodb.http import ProviderError
from macrodb.policy import PolicyIngester, ROOT, Sources
from macrodb.providers.base import SeriesRequest
from research.policy_cycles.events import policy_inputs


def legacy_cache(settings):
    archive = RawArchive(settings.home / "raw" / "policy_documents")
    cache = {}
    def add(url, content, params=None):
        when = datetime(2024, 3, 10, tzinfo=timezone.utc)
        path, sha, _ = archive.put("fed", content, "application/json" if params else "text/html", when)
        key = url + (json.dumps(params) if params else "")
        cache[key] = {"url": url, "params": params or {}, "archive_path": path,
                      "sha256": sha, "fetched_at": when.isoformat()}
    target_rows = {
        "DFEDTAR": [("1994-02-01", "3", "2024-03-10"), ("1994-02-05", "3.25", "2024-03-10"),
                    ("2008-12-15", "3.25", "2024-03-10")],
        "DFEDTARL": [("2008-12-16", "0", "2024-03-10"), ("2024-03-01", "0", "2024-03-10")],
        "DFEDTARU": [("2008-12-16", "0.25", "2024-03-10"), ("2024-03-01", "0.25", "2024-03-10")]}
    for sid, rows in target_rows.items():
        add("https://api.stlouisfed.org/fred/series/observations", fred_json(rows), {"series_id": sid})
    for year in range(1994, 2021):
        body = "<html>Federal Open Market Committee</html>"
        if year == 1994:
            body = '<h5>February 4 Meeting - 1994</h5><a href="/fomc/19940204default.htm">Statement</a>'
        if year == 2008:
            body = '<h5>December 16 Meeting - 2008</h5><a href="/newsevents/pressreleases/monetary20081216a.htm">Statement</a>'
        add(f"{ROOT}/monetarypolicy/fomchistorical{year}.htm", body.encode())
    add(f"{ROOT}/monetarypolicy/fomccalendars.htm", b"<html>Federal Open Market Committee</html>")
    add(f"{ROOT}/fomc/19940204default.htm", b"For immediate release. Federal Open Market Committee raises federal funds target.")
    add(f"{ROOT}/newsevents/pressreleases/monetary20081216a.htm",
        b"For release at 2:00 p.m. EST. Federal Open Market Committee lowers target range.")
    path = settings.home / "policy_source_cache.json"
    path.write_text(json.dumps(cache))
    return path


@pytest.fixture
def migrated(synced, settings, registry):
    ingester = PolicyIngester(synced, settings, registry)
    path = legacy_cache(settings)
    result = ingester.import_cache(path, "2024-03-01")
    return ingester, path, result


def test_offline_migration_centralizes_raw_targets_events_and_lineage(migrated, synced, settings, http):
    ingester, path, result = migrated
    assert not http.calls
    assert result["target_rows_new"] == 7 and result["events_new"] == 2
    assert synced.execute("SELECT count(*) FROM silver_observation").fetchone()[0] == 7
    assert synced.execute("SELECT count(*) FROM prov_policy_event_source").fetchone()[0] == 4
    assert synced.execute("SELECT count(*) FROM prov_policy_target_lineage").fetchone()[0] == 3
    assert synced.execute("SELECT count(*) FROM bronze_observation WHERE realtime_start IS NOT NULL").fetchone()[0] == 0
    db = MacroDB(settings, con=synced)
    events, event_text, level_text = policy_inputs(db)
    assert events.target_kind.tolist() == ["single", "range"]
    assert events.timing_basis.tolist() == ["date_only_next_day", "statement_clock_time"]
    assert "1994-02-04" in event_text and "2008-12-16" in level_text
    rid, sha = synced.execute("SELECT response_id,content_sha256 FROM prov_raw_response WHERE provider_id='fomc' LIMIT 1").fetchone()
    assert hashlib.sha256(db.raw_response(rid)).hexdigest() == sha
    again = ingester.import_cache(path, "2024-03-01")
    assert again["target_rows_new"] == 0 and again["events_new"] == 0
    assert len(db.policy_events()) == 2


def test_event_corrections_append_versions_without_overwriting(migrated, synced, settings, registry, monkeypatch):
    ingester, _, _ = migrated
    db = MacroDB(settings, con=synced)
    revised = db.policy_events()
    old_text = revised.loc[0, "source_evidence"]
    revised.loc[0, "source_evidence"] = old_text + " corrected evidence"
    def assemble(sources, levels, as_of):
        for e in revised.to_dict("records"):
            sources.get(e["calendar_url"])
            sources.get(e["statement_url"])
        return revised, pd.DataFrame()
    monkeypatch.setattr("macrodb.policy.assemble", assemble)
    synced.execute("INSERT INTO prov_batch VALUES ('correction',now(),NULL,'incremental','running',NULL,NULL)")
    result = ingester.run("correction", "2024-03-01", cache_only=True)
    assert result["events_new"] == 1
    assert synced.execute("SELECT count(*) FROM bronze_policy_event").fetchone()[0] == 3
    assert db.policy_events().loc[0, "source_evidence"].endswith("corrected evidence")
    assert old_text in synced.execute("SELECT payload FROM bronze_policy_event ORDER BY policy_version_id LIMIT 1").fetchone()[0]
    from macrodb.reports import policy_report, write_reports
    coverage = policy_report(synced).iloc[0]
    assert coverage.events == 2 and coverage.document_links == 4 and coverage.target_links == 3
    write_reports(synced, settings.reports_dir)
    assert (settings.reports_dir / "policy_coverage.csv").exists()


def test_policy_only_refresh_fetches_target_prerequisites_and_updates_daily(migrated, synced, settings, registry, http):
    today = datetime.now(timezone.utc).date()
    def fred(params):
        value = "0.25" if params["series_id"] == "DFEDTARU" else "0"
        return 200, fred_json([(str(today), value, str(today))]), "application/json"
    http.on("api.stlouisfed.org", fred)
    http.on("fomccalendars.htm", lambda p: (200, b"<html>Federal Open Market Committee</html>", "text/html"))
    http.on("press_monetary.xml", lambda p: (200, b"<rss><channel><title>FOMC</title></channel></rss>", "application/rss+xml"))
    result = Ingester(synced, settings, registry).run(providers=["fomc"])
    assert result["errors"] == 0 and result["tasks"] == 4 and result["policy_events_new"] == 0
    calls = [p for u, p in http.calls if "api.stlouisfed.org" in u]
    assert {p["series_id"] for p in calls} == {"DFEDTARL", "DFEDTARU"}
    assert all(p["observation_start"] == str(today - timedelta(days=30)) and "realtime_start" not in p for p in calls)
    before = len(http.calls)
    # Document requests are now cached in central provenance, independently of the old JSON.
    path = settings.home / "policy_source_cache.json"
    path.unlink()
    Ingester(synced, settings, registry).run(providers=["fomc"])
    new_calls = http.calls[before:]
    assert all("api.stlouisfed.org" in u for u, _ in new_calls)


def test_recent_documents_revalidate_daily_but_history_is_cached(migrated, synced, settings, registry, http):
    ingester, _, result = migrated
    http.on("fomccalendars.htm", lambda p: (200, b"<html>Federal Open Market Committee refreshed</html>", "text/html"))
    sources = Sources(synced, settings, result["batch_id"], registry)
    historical = f"{ROOT}/monetarypolicy/fomchistorical1994.htm"
    assert "February 4" in sources.get(historical)
    assert not http.calls
    current = f"{ROOT}/monetarypolicy/fomccalendars.htm"
    assert "refreshed" in sources.get(current)
    assert len(http.calls) == 1
    again = Sources(synced, settings, result["batch_id"], registry)
    assert "refreshed" in again.get(current)
    assert len(http.calls) == 1


def test_current_only_target_adapter_never_fabricates_vintages(registry, http, settings):
    http.on("api.stlouisfed.org", lambda p: (200, fred_json([("2024-01-01", "5.5", "2024-03-10")]), "application/json"))
    req = SeriesRequest("fred", "DFEDTARU", ["value"], "D", {"current_only": True, "history_start": "2008-12-16"})
    result = registry.get("fred").fetch(req)
    assert result.pages[0].observations[0].realtime_start is None
    assert "realtime_start" not in http.calls[0][1]
    req = SeriesRequest("fred", "DFEDTAR", ["value"], "D", {"history_end": "2008-12-15"})
    result = registry.get("fred").fetch(req, since=datetime(2026, 1, 1).date())
    assert not result.pages and len(http.calls) == 1


def test_research_requires_central_inputs_not_output_csvs(synced, settings, tmp_path):
    (tmp_path / "policy_events.csv").write_text("a fake research-side input is not a database input")
    with pytest.raises(RuntimeError, match="database"):
        policy_inputs(MacroDB(settings, con=synced))


def test_new_rate_change_cannot_be_misclassified_as_hold_before_fred_updates():
    from macrodb.policy import assemble
    class Source:
        cache_only = True
        def get(self, url):
            if "fomccalendars" in url:
                return '<a href="/newsevents/pressreleases/monetary20240301a.htm">HTML</a>'
            if "pressreleases" in url:
                return "The Federal Open Market Committee decided to lower the target range."
            return "<html>FOMC</html>"
    for last_date in ["2024-02-29", "2024-03-01"]:
        levels = pd.DataFrame({"target_low": [1.0], "target_high": [1.25],
                               "target_kind": ["range"]}, index=pd.to_datetime([last_date]))
        with pytest.raises(ProviderError, match="awaits"):
            assemble(Source(), levels, "2024-03-01")
