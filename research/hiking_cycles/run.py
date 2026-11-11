import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from macrodb import MacroDB

from ..data import Inputs, ts
from ..policy_cycles.run import frame_hash
from ..policy_cycles.states import classify_events, cycles, panel
from . import outcomes as O, signals as F, spec as S

OUT = Path("results/hiking_cycles")


def main(out=OUT):
    out = Path(out)
    db = MacroDB(read_only=True)
    try:
        inp = Inputs(db)
        versions = {key: inp.versions(sid) for key, sid in S.SERIES.items()}
        if any(frame.empty for frame in versions.values()):
            raise RuntimeError("Missing study inputs; ingest the registered macrodb series first")
        markets = {key: inp.daily(sid).loc[S.SPEC["start"]:] for key, sid in {
            "y2": "US.TREASURY.CMT.2Y", "y5": "US.TREASURY.CMT.5Y",
            "y10": "US.TREASURY.CMT.10Y", "bills": "US.TBILL.3M.DISCOUNT"}.items()}
        sessions = markets["y10"].index
        as_of = ts(sessions[-1], 16).tz_convert("UTC")
        events = db.policy_events(start=S.SPEC["start"])
        events = events[pd.to_datetime(events.known_at, utc=True) <= as_of]
        source_ids = list(S.SERIES.values())
        sources = db.con.execute(f"""
            SELECT DISTINCT r.* FROM prov_raw_response r
            WHERE r.provider_id='fomc' OR r.response_id IN (
                SELECT b.response_id FROM bronze_observation b
                JOIN ref_provider_series p USING(provider_id,source_series_id,field_id)
                WHERE p.series_id IN ({','.join('?' * len(source_ids))}))
            ORDER BY r.response_id
        """, source_ids).fetchdf()
        hashes = {**{key: frame_hash(frame) for key, frame in versions.items()},
                  **{key: frame_hash(values) for key, values in markets.items()},
                  "policy_events": frame_hash(events), "source_manifest": frame_hash(sources),
                  "as_of": as_of.isoformat()}
        sha = S.freeze(out, hashes)
        history = classify_events(events)
        cycle_table = cycles(history)
        pauses = F.candidate_pauses(history)
        closes = pd.DatetimeIndex([ts(day, 16).tz_convert("UTC") for day in sessions])
        features = F.feature_snapshots(versions, list(closes) + pauses.known_at.tolist())
        if (features.max_input_known_at.dropna() > features.max_input_known_at.dropna().index).any():
            raise RuntimeError("Input publication timing leaked into an earlier decision")
        actions = F.allocations(panel(history, sessions), features.reindex(closes))
        outputs = O.compute(out, hashes, history, pauses, actions, sessions, markets, cycle_table)
        for key, frame in versions.items():
            F.prepare_versions(frame).to_csv(out / f"input_{key}_versions.csv", index=False)
        sources.to_csv(out / "source_manifest.csv", index=False)
        events.to_csv(out / "policy_events.csv", index=False)
        cycle_table.to_csv(out / "cycles.csv", index=False)
        pause_features = features.reindex(pd.DatetimeIndex(pauses.known_at)).reset_index(drop=True)
        pd.concat([pauses.reset_index(drop=True), pause_features], axis=1).to_csv(out / "pause_events.csv", index=False)
        F.communication_records(db, pauses).to_csv(out / "pause_communications.csv", index=False)
        actions.to_csv(out / "allocation_decisions.csv", index_label="decision_date")
        for name, frame in outputs.items():
            frame.to_csv(out / f"{name}.csv", index=False)
        audit = []
        for name, frame in versions.items():
            prepared = F.prepare_versions(frame)
            audit.append({"input": name, "series_id": S.SERIES[name], "versions": len(frame),
                          "first_observation": frame.observation_date.min(),
                          "last_observation": frame.observation_date.max(),
                          "first_conservatively_known": prepared.known_at.min(),
                          "vintage_rows": int(frame.availability_basis.eq("vintage").sum()),
                          "ingestion_only_rows": int(frame.availability_basis.eq("ingestion_only").sum())})
        pd.DataFrame(audit).to_csv(out / "input_coverage.csv", index=False)
        meta = {"run_at": datetime.now(timezone.utc).isoformat(), "spec_sha256": sha,
                "first_session": str(sessions[0].date()), "last_session": str(sessions[-1].date()),
                "candidate_pauses": len(pauses), "complete_cycles": int(cycle_table.complete.sum()),
                "signal_activations": int(actions.signal_activation.sum()),
                "reserved_note": S.SPEC["reserved_note"], "communication": S.SPEC["communication"],
                "input_hashes": hashes}
        (out / "run_metadata.json").write_text(json.dumps(meta, indent=2))
        from .report import write_report
        write_report(out)
        print(json.dumps(meta, indent=2))
        print("findings:", out / "FINDINGS.md")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(OUT))
    main(parser.parse_args().out)
