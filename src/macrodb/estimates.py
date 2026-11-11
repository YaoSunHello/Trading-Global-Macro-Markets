"""User-approved imputations appended to the original series, explicitly flagged as estimates."""
import json
import math
import uuid
from datetime import datetime, timezone

import pandas as pd


def estimate_mask(frame):
    if "dq_flags" not in frame:
        return pd.Series(False, index=frame.index)
    return frame.dq_flags.map(lambda flags: "ESTIMATED" in flags)


def record_geometric_estimate(db, series_id, observation_date, value):
    month = pd.Timestamp(observation_date)
    meta = db.metadata(series_id)["series"]
    if meta["frequency_id"] != "M" or month.day != 1:
        raise ValueError("Geometric interpolation requires a monthly period-start date")
    current = db.get(series_id, start=month, end=month, provider="fred", quality="all", include_estimates=False)
    if current.value.notna().any():
        raise ValueError("Cannot estimate a month with an official value")
    left_date, right_date = month - pd.DateOffset(months=1), month + pd.DateOffset(months=1)
    neighbors = db.get(series_id, start=left_date, end=right_date, provider="fred",
                       include_estimates=False).set_index("observation_date")
    if left_date not in neighbors.index or right_date not in neighbors.index:
        raise ValueError("Both adjacent official months are required")
    left, right = neighbors.loc[left_date], neighbors.loc[right_date]
    if left.value <= 0 or right.value <= 0:
        raise ValueError("Adjacent index values must be positive")
    calculated = math.sqrt(float(left.value) * float(right.value))
    if not math.isfinite(value) or value != round(calculated, 3):
        raise ValueError("Approved value must match geometric interpolation rounded to three decimals")
    payload = {"series_id": series_id, "observation_date": str(month.date()), "value": value,
               "method": "geometric_interpolation", "formula": "sqrt(previous_month * next_month)",
               "left_bronze_id": int(left.bronze_id), "right_bronze_id": int(right.bronze_id),
               "left_value": float(left.value), "right_value": float(right.value),
               "unrounded_value": calculated, "rounding_decimals": 3,
               "note": "User-approved estimate, not an official CPI observation"}
    payload.update(is_estimate=True, origin="user_approved_imputation",
                   reason="October 2025 official CPI observation is unavailable following the government shutdown")
    from . import __version__
    from .ingest import Ingester, row_hash
    from .providers.base import FetchedPage, RawObs, SeriesRequest
    from .silver import SilverBuilder
    source = left.source_series_id
    obs = RawObs(meta["field_id"], str(month.date()), month.date(), f"{value:.3f}", value, source_attrs=payload)
    sha = row_hash("fred", source, obs)
    existing = db.con.execute("SELECT bronze_id FROM bronze_observation WHERE row_hash=?", [sha]).fetchone()
    if existing:
        return existing[0]
    batch = f"estimate-{datetime.now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    ingester = Ingester(db.con, db.settings, None)
    db.con.execute("BEGIN")
    try:
        db.con.execute("INSERT INTO prov_batch VALUES (?,?,NULL,'manual_estimate','running',?,?)",
                       [batch, now, __version__, payload["note"]])
        request = SeriesRequest("fred", source, [meta["field_id"]], "M")
        page = FetchedPage(f"urn:macrodb:user-approved-estimate:{source}:{month.date()}", {}, 0,
                           json.dumps(payload, sort_keys=True).encode(), "application/json", [obs])
        _, added, _ = ingester._store_page(batch, request, page)
        db.con.execute("INSERT INTO prov_ingestion_task VALUES (?,?,?,'ok',1,?,NULL,?)",
                       [batch, "fred", source, added, json.dumps(["ESTIMATED: not an official release"])])
        db.con.execute("UPDATE prov_batch SET status='ok',finished_at=? WHERE batch_id=?", [now, batch])
        db.con.execute("COMMIT")
    except Exception:
        db.con.execute("ROLLBACK")
        raise
    ingester._mirror_batch_parquet(batch)
    SilverBuilder(db.con).build([series_id])
    return db.con.execute("SELECT bronze_id FROM bronze_observation WHERE row_hash=?", [sha]).fetchone()[0]


def fill_missing(official, estimates, keys=("series_id", "field_id", "observation_date")):
    """Known official values win, including official releases made after an estimate was stored."""
    if estimates.empty:
        return official
    valid = official[official.value.notna() | ~official.dq_status.eq("missing")]
    observed = set(valid[list(keys)].itertuples(index=False, name=None))
    estimates = estimates[[key not in observed for key in estimates[list(keys)].itertuples(index=False, name=None)]]
    if estimates.empty:
        return official
    replaced = set(estimates[list(keys)].itertuples(index=False, name=None))
    official = official[[key not in replaced for key in official[list(keys)].itertuples(index=False, name=None)]]
    return pd.concat([official, estimates], ignore_index=True)
