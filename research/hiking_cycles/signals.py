import json

import numpy as np
import pandas as pd

from ..data import ts
from . import spec as S


def candidate_pauses(history):
    pending = False
    rows = []
    for row in history.sort_values("known_at").to_dict("records"):
        delta = (row["target_low"] + row["target_high"] - row["previous_low"] - row["previous_high"]) / 2
        unchanged = row["target_low"] == row["previous_low"] and row["target_high"] == row["previous_high"]
        if delta > 1e-8:
            pending = True
        elif delta < -1e-8:
            pending = False
        elif unchanged and row["scheduled"] and pending:
            rows.append({**row, "pause_id": f"PAUSE_{row['event_id']}",
                         "communication_status": "text condition deferred; no validated historical classifier"})
            pending = False
    return pd.DataFrame(rows)


def communication_records(db, pauses):
    from macrodb.policy import text
    records = []
    for pause in pauses.to_dict("records"):
        key = f"FED:{pause['announcement_date']}:{pause['scheduled']}"
        sources = db.con.execute("""
            SELECT s.response_id,r.request_url,r.content_sha256
            FROM prov_policy_event_source s JOIN prov_raw_response r USING(response_id)
            WHERE s.policy_version_id=(SELECT max(policy_version_id) FROM bronze_policy_event WHERE event_key=?)
              AND s.source_role='statement'
        """, [key]).fetchall()
        if not sources:
            records.append({"pause_id": pause["pause_id"], "statement_text": "",
                            "status": "No contemporaneous statement; later minutes excluded"})
        for rid, url, sha in sources:
            records.append({"pause_id": pause["pause_id"], "response_id": rid, "url": url,
                            "content_sha256": sha, "announcement_ts": pause["announcement_ts"],
                            "conservative_known_at": pause["known_at"], "timing_basis": pause["timing_basis"],
                            "statement_text": text(db.raw_response(rid).decode("utf-8", errors="replace")),
                            "status": "Archived statement only; semantic classification deferred"})
    return pd.DataFrame(records)


def prepare_versions(frame):
    frame = frame.copy()
    known = []
    for row in frame.itertuples():
        if row.availability_basis == "vintage":
            day = pd.Timestamp(row.availability_ts).normalize() + pd.Timedelta(days=1)
            known.append(day.tz_localize("America/New_York").tz_convert("UTC"))
        else:
            known.append(pd.Timestamp(row.availability_ts).tz_localize("UTC"))
    frame["known_at"] = pd.to_datetime(known, utc=True)
    return frame.sort_values(["known_at", "bronze_id"])


def completion_condition(row):
    required = ["headline_yoy", "core_yoy", "core_dyoy3", "wages_yoy", "wages_dyoy6",
                "expectations_level", "expectations_change3"]
    missing = [key for key in required if pd.isna(row.get(key, np.nan))]
    stale = [key for key in ["headline", "core", "wages", "expectations"] if row.get(f"{key}_stale", True)]
    ready = not missing and not stale
    inf = (ready and row["headline_yoy"] < S.SPEC["inflation"]["headline_yoy_lt"]
           and row["core_yoy"] < S.SPEC["inflation"]["core_yoy_lt"]
           and row["core_dyoy3"] < S.SPEC["inflation"]["core_dyoy3_lt_pp"])
    wage = (ready and row["wages_yoy"] <= S.SPEC["wages"]["eci_yoy_le"]
            and row["wages_dyoy6"] <= S.SPEC["wages"]["eci_dyoy_two_quarters_le_pp"])
    exp = (ready and row["expectations_level"] <= S.SPEC["expectations"]["ten_year_expected_cpi_le"]
           and row["expectations_change3"] <= S.SPEC["expectations"]["change_three_observation_months_le_pp"])
    return {"inputs_complete": ready, "inflation_condition": bool(inf), "wage_condition": bool(wage),
            "expectations_condition": bool(exp), "completion_condition": bool(inf and wage and exp),
            "missing_or_stale": "|".join(missing + [f"{key}_stale" for key in stale])}


def feature_snapshots(versions, times):
    """Incrementally replay actual versions; no revised value is inserted into an earlier snapshot."""
    data = {key: prepare_versions(frame).to_dict("records") for key, frame in versions.items()}
    cursor, state = {key: 0 for key in data}, {key: {} for key in data}
    output = []
    for when in sorted(set(pd.to_datetime(times, utc=True))):
        used, row = [], {"decision_ts": when}
        day = pd.Timestamp(when.tz_convert("America/New_York").date())
        for key, records in data.items():
            while cursor[key] < len(records) and records[cursor[key]]["known_at"] <= when:
                record = records[cursor[key]]
                state[key][record["observation_date"]] = record
                cursor[key] += 1
            available_dates = [date for date in state[key] if date <= day]
            latest = max(available_dates) if available_dates else pd.NaT
            snapshot = state[key]

            def value(date):
                record = snapshot.get(date)
                if record is None:
                    return np.nan
                used.append(record)
                if record["dq_status"] not in ("ok", "suspect"):
                    return np.nan
                return float(record["value"])

            def yoy(date):
                current, previous = value(date), value(date - pd.DateOffset(years=1))
                return (current / previous - 1) * 100 if pd.notna(previous) and previous > 0 else np.nan

            if pd.isna(latest):
                row[f"{key}_stale"] = True
                continue
            latest_record = snapshot[latest]
            end = latest + (pd.offsets.QuarterEnd(0) if key in ("wages", "productivity") else pd.offsets.MonthEnd(0))
            row.update({f"{key}_obs_month": latest, f"{key}_known_at": latest_record["known_at"],
                        f"{key}_bronze_id": latest_record["bronze_id"],
                        f"{key}_stale": (day - end).days > S.SPEC["staleness_days_from_period_end"][key]})
            if key == "expectations":
                row["expectations_level"] = value(latest)
                row["expectations_change3"] = value(latest) - value(latest - pd.DateOffset(months=3))
            else:
                row[f"{key}_yoy"] = yoy(latest)
                if key in ("headline", "core"):
                    row[f"{key}_dyoy3"] = yoy(latest) - yoy(latest - pd.DateOffset(months=3))
                if key == "wages":
                    row["wages_dyoy6"] = yoy(latest) - yoy(latest - pd.DateOffset(months=6))
        for key in ["headline_yoy", "headline_dyoy3", "core_yoy", "core_dyoy3", "wages_yoy",
                    "wages_dyoy6", "productivity_yoy", "expectations_level", "expectations_change3"]:
            row.setdefault(key, np.nan)
        if row.get("productivity_stale", True):
            row["productivity_yoy"] = np.nan
        row["wage_minus_productivity_yoy"] = row["wages_yoy"] - row["productivity_yoy"]
        row["input_bronze_ids"] = json.dumps(sorted({int(record["bronze_id"]) for record in used}))
        row["max_input_known_at"] = max((record["known_at"] for record in used), default=pd.NaT)
        row["input_has_estimate"] = any("ESTIMATED" in record["dq_flags"] for record in used)
        high, momentum = row["headline_yoy"], row["headline_dyoy3"]
        row["inflation_group"] = (
            "unknown" if pd.isna(high) or pd.isna(momentum) or row.get("headline_stale", True) else
            "high_rising" if high >= 3.5 and momentum > .30 else
            "high_falling" if high >= 3.5 and momentum < -.30 else "other")
        row.update(completion_condition(row))
        output.append(row)
    return pd.DataFrame(output).set_index("decision_ts")


def allocations(policy_panel, features):
    features = features.copy()
    features.index = policy_panel.index
    rows, active, last_change = [], False, None
    for date, policy in policy_panel.iterrows():
        signal = features.loc[date]
        changed = pd.notna(policy.last_change_known_at) and policy.last_change_known_at != last_change
        if changed:
            active = False
        last_change = policy.last_change_known_at
        activation = False
        if policy.state == "hold_after_hiking":
            activation = not active and bool(signal.completion_condition)
            active = active or activation
            filtered = float(active)
        else:
            active = False
            filtered = S.SPEC["outside_transition_weights"][policy.state]
        baseline = 1.0 if policy.state == "hold_after_hiking" else S.SPEC["outside_transition_weights"][policy.state]
        rows.append({"decision_date": date, "decision_ts": policy.decision_ts,
                     "baseline_weight": baseline, "completion_filter_weight": filtered,
                     "signal_activation": activation, "policy_state": policy.state,
                     "cycle_id": policy.cycle_id, "sample": policy["sample"]})
    return pd.DataFrame(rows).set_index("decision_date").join(features)
