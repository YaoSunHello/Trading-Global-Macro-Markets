"""Database-only policy input export; acquisition belongs to macrodb."""
from pathlib import Path

from macrodb import MacroDB
from macrodb.policy import announcement_time, historical_index, modern_index, url_date

OUT = Path("results/policy_cycles")


def policy_inputs(db):
    events = db.policy_events(start="1994-02-01")
    if events.empty:
        raise RuntimeError("Policy events are missing from the database; run macrodb ingest first")
    levels = db.policy_target_levels()
    event_text = events.to_csv(index=False)
    level_text = levels.to_csv(index_label="effective_date")
    return events, event_text, level_text


def export_inputs(db, out=OUT):
    out = Path(out)
    events, event_text, level_text = policy_inputs(db)
    out.mkdir(parents=True, exist_ok=True)
    (out / "policy_events.csv").write_text(event_text)
    (out / "target_level_validation.csv").write_text(level_text)
    db.policy_sources().to_csv(out / "source_manifest.csv", index=False)
    exclusions = db.con.execute("""
        SELECT payload FROM prov_policy_exclusion
        WHERE batch_id=(SELECT batch_id FROM prov_policy_exclusion ORDER BY batch_id DESC LIMIT 1)
    """).fetchall()
    if exclusions:
        import json
        import pandas as pd
        pd.DataFrame([json.loads(r[0]) for r in exclusions]).to_csv(out / "excluded_intermeeting_events.csv", index=False)
    return events, event_text, level_text


if __name__ == "__main__":
    db = MacroDB(read_only=True)
    try:
        export_inputs(db)
    finally:
        db.close()
