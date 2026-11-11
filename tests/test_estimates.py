import json
import math

import pandas as pd
import pytest

from conftest import route_fred
from macrodb import MacroDB
from macrodb.estimates import record_geometric_estimate
from macrodb.estimates import estimate_mask
from macrodb.silver import SilverBuilder
from research.data import Inputs, asof_snapshot
from research.inflation_states import classify as C, pit_panel as P

HEADLINE, CORE = "US.CPI.ALL_ITEMS.SA", "US.CPI.CORE.SA"


@pytest.fixture
def estimated(ingester, http, synced, settings):
    months = pd.date_range("2024-09-01", "2026-10-01", freq="MS")
    data = {}
    for source, previous, following in [("CPIAUCSL", 324.245, 325.063), ("CPILFESL", 330.418, 331.043)]:
        rows = []
        for i, month in enumerate(months):
            value = str(320 + i * 0.5)
            if month == pd.Timestamp("2025-09-01"): value = str(previous)
            if month == pd.Timestamp("2025-10-01"): value = "."
            if month == pd.Timestamp("2025-11-01"): value = str(following)
            release = month + pd.offsets.MonthBegin(1) + pd.Timedelta(days=9)
            rows.append((str(month.date()), value, str(release.date())))
        data[source] = rows
    route_fred(http, data)
    ingester.run(series_ids=[HEADLINE, CORE])
    SilverBuilder(synced).build()
    api = MacroDB(settings, con=synced)
    before = synced.execute("SELECT * FROM bronze_observation ORDER BY bronze_id").fetchdf()
    for sid, value in [(HEADLINE, 324.654), (CORE, 330.730)]:
        record_geometric_estimate(api, sid, "2025-10-01", value)
    return api, before


def test_estimates_are_append_only_idempotent_and_traceable(estimated):
    api, before = estimated
    after = api.con.execute("SELECT * FROM bronze_observation ORDER BY bronze_id").fetchdf()
    pd.testing.assert_frame_equal(before, after[after.bronze_id.isin(before.bronze_id)].reset_index(drop=True))
    assert len(after) == len(before) + 2
    first = api.estimates(HEADLINE).estimate_id.iloc[0]
    assert record_geometric_estimate(api, HEADLINE, "2025-10-01", 324.654) == first
    assert len(api.estimates([HEADLINE, CORE])) == 2
    row = api.con.execute("""SELECT b.source_attrs,l.value_num,r.value_num FROM bronze_observation b
                            JOIN bronze_observation l ON l.bronze_id=CAST(json_extract_string(b.source_attrs,'$.left_bronze_id') AS BIGINT)
                            JOIN bronze_observation r ON r.bronze_id=CAST(json_extract_string(b.source_attrs,'$.right_bronze_id') AS BIGINT)
                            WHERE b.bronze_id=?""", [int(first)]).fetchone()
    payload = json.loads(row[0])
    assert payload["value"] == round(math.sqrt(row[1] * row[2]), 3)
    assert "not an official" in payload["note"]
    with pytest.raises(ValueError, match="official value"):
        record_geometric_estimate(api, HEADLINE, "2025-09-01", 324.654)
    with pytest.raises(ValueError, match="must match"):
        record_geometric_estimate(api, HEADLINE, "2025-10-01", 999)
    from macrodb.reports import write_reports
    from macrodb.db import export_parquet
    write_reports(api.con, api.settings.reports_dir)
    assert len(pd.read_csv(api.settings.reports_dir / "approved_estimates.csv")) == 2
    export_parquet(api.con, api.settings)
    assert api.con.execute("SELECT count(*) FROM read_parquet(?) WHERE list_contains(dq_flags,'ESTIMATED')",
                           [str(api.settings.parquet_dir / "silver/**/*.parquet")]).fetchone()[0] == 2


def test_estimate_overlay_is_labeled_gap_only_and_excluded_from_strict_pit(estimated):
    api, _ = estimated
    options = dict(start="2025-10-01", end="2025-10-01", quality="all")
    official = api.get(HEADLINE, include_estimates=False, **options)
    assert official.value.isna().all()
    filled = api.get(HEADLINE, include_estimates=True, **options).iloc[0]
    assert filled.value == 324.654 and filled.provider_id == "fred" and filled.source_series_id == "CPIAUCSL"
    assert api.get(HEADLINE, **options).value.iloc[0] == 324.654
    assert "ESTIMATED" in filled.dq_flags and not filled.pit_reliable
    assert pd.isna(filled.published_at) and pd.isna(filled.realtime_start)
    assert api.get(HEADLINE, include_estimates=True, pit="strict", **options).value.isna().all()
    assert api.get(HEADLINE, include_estimates=True, vintage="first", **options).value.isna().all()
    assert api.get(HEADLINE, include_estimates=True, quality="ok", start="2025-10-01", end="2025-10-01").empty
    assert api.get(HEADLINE, include_estimates=True, provider="ecb", **options).empty
    pd.testing.assert_frame_equal(
        api.get(HEADLINE, start="2025-09-01", end="2025-09-01"),
        api.get(HEADLINE, include_estimates=True, start="2025-09-01", end="2025-09-01"))


def test_research_timing_never_backdates_estimates_or_uses_after_close_values(estimated):
    api, _ = estimated
    created = api.estimates(HEADLINE).availability_ts.iloc[0]
    versions = Inputs(api).versions(HEADLINE)
    month = pd.Timestamp("2025-10-01")
    before = asof_snapshot(versions, created.normalize() - pd.Timedelta(days=1))
    assert month not in before.index
    after = asof_snapshot(versions, created.normalize() + pd.Timedelta(days=1))
    assert after.loc[month, "value"] == 324.654
    changed = versions.copy()
    mask = estimate_mask(changed)
    # 17:00 ET is after the formation close; timestamp is stored in UTC.
    from research.data import ts
    changed.loc[mask, "availability_ts"] = ts(created, 17).tz_convert("UTC").tz_localize(None)
    assert month not in asof_snapshot(changed, created.normalize()).index
    assert month in asof_snapshot(changed, created.normalize() + pd.Timedelta(days=1)).index
    assert not estimate_mask(Inputs(api, include_estimates=False).versions(HEADLINE)).any()


def test_official_releases_always_supersede_estimates_but_missing_refreshes_do_not(estimated):
    api, _ = estimated
    versions = Inputs(api).versions(HEADLINE)
    estimated_row = versions[estimate_mask(versions)].iloc[0]
    month = pd.Timestamp("2025-10-01")
    official = versions[versions.observation_date.eq(month) & ~estimate_mask(versions)].iloc[0].copy()
    official["availability_ts"] = estimated_row.availability_ts + pd.Timedelta(days=1)
    official["bronze_id"] = versions.bronze_id.max() + 1
    updated = pd.concat([versions, official.to_frame().T], ignore_index=True)
    decision = official.availability_ts.normalize() + pd.Timedelta(days=1)
    assert asof_snapshot(updated, decision).loc[month, "value"] == 324.654
    updated.loc[updated.index[-1], ["value", "dq_status"]] = [324.9, "ok"]
    assert asof_snapshot(updated, decision).loc[month, "value"] == 324.9
    # An official value also wins if its publication predates the approved estimate.
    updated.loc[updated.index[-1], "availability_ts"] = estimated_row.availability_ts - pd.Timedelta(hours=1)
    assert asof_snapshot(updated, decision).loc[month, "value"] == 324.9


def test_new_research_computes_yoy_states_and_labels_estimated_history(estimated):
    api, _ = estimated
    created = api.estimates(HEADLINE).availability_ts.iloc[0]
    decision = pd.DatetimeIndex([created.normalize() + pd.Timedelta(days=1)])
    official, _ = P.build_panel(Inputs(api, include_estimates=False).versions(HEADLINE), decision, HEADLINE, "HEADLINE")
    filled, _ = P.build_panel(Inputs(api).versions(HEADLINE), decision, HEADLINE, "HEADLINE")
    assert pd.isna(official.yoy.iloc[0]) and pd.notna(filled.yoy.iloc[0])
    assert filled.yoy.iloc[0] == pytest.approx((filled.idx.iloc[0] / 324.654 - 1) * 100)
    for kind, rule in [("level", "L1_FIXED"), ("momentum", "M1_DYOY_3M"), ("momentum", "M2_DYOY_6M")]:
        assert C.classify(filled, kind, rule).state.notna().all()
    assert filled.n_estimated_inputs.iloc[0] == 1
    assert filled.estimated_observation_months.iloc[0] == "2025-10-01"
    assert (filled.input_availability_ts <= filled.decision_ts).all()
    assert "estimated" in filled.availability_basis.iloc[0]
    assert P.coverage_audit(Inputs(api).versions(HEADLINE), HEADLINE) == P.coverage_audit(
        Inputs(api, include_estimates=False).versions(HEADLINE), HEADLINE)
