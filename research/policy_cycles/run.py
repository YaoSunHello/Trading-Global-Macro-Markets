import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from macrodb import MacroDB

from ..calendar_pit import Calendar
from ..data import Inputs
from ..inflation_states import classify as C, pit_panel as P
from . import outcomes as O, spec as S
from .events import OUT, export_inputs, policy_inputs
from .states import classify_events, cycles, panel


def frame_hash(frame):
    return hashlib.sha256(frame.to_csv().encode()).hexdigest()


def inflation_panel(versions, decisions):
    result = pd.DataFrame(index=decisions, columns=["inflation_group", "inflation_yoy", "inflation_dyoy3",
                                                 "inflation_observation_month", "inflation_release_ts"])
    usable = decisions[decisions >= versions.availability_ts.min().normalize()]
    if not len(usable):
        return result
    p, _ = P.build_panel(versions, usable, "US.CPI.ALL_ITEMS.SA", "HEADLINE", keep_derived=False)
    level = C.classify(p, "level", "L1_FIXED", rule={"kind": "fixed", "low": 1.5,
                                                 "high": S.SPEC["inflation_comparison"]["high_yoy_pct"]})["state"]
    momentum = C.classify(p, "momentum", "M1_DYOY_3M", rule={
        "measure": "dyoy3", "band": S.SPEC["inflation_comparison"]["rising_dyoy3_pp"]})["state"]
    known = level.notna() & momentum.notna()
    group = pd.Series(np.nan, index=p.index, dtype=object)
    group[known] = "other_known_inflation"
    group[known & (level == 1) & (momentum == 1)] = "high_and_rising"
    result.loc[p.index, "inflation_group"] = group
    for dest, source in [("inflation_yoy", "yoy"), ("inflation_dyoy3", "dyoy3"),
                         ("inflation_observation_month", "obs_month"), ("inflation_release_ts", "release_ts")]:
        result.loc[p.index, dest] = p[source]
    return result


def main(out=OUT, include_estimates=True):
    out = Path(out)
    inp = Inputs(MacroDB(read_only=True), include_estimates=include_estimates)
    try:
        events, event_text, level_text = policy_inputs(inp.db)
        inputs = {key: inp.daily(sid) for key, sid in {
            "y2": "US.TREASURY.CMT.2Y", "y5": "US.TREASURY.CMT.5Y", "y10": "US.TREASURY.CMT.10Y",
            "bills": "US.TBILL.3M.DISCOUNT"}.items()}
        # Include no pre-1994 Treasury outcomes; retain the first session as the initial wealth anchor.
        inputs = {key: values[values.index >= S.SPEC["start"]] for key, values in inputs.items()}
        sessions = inputs["y10"].index
        cpi = inp.versions("US.CPI.ALL_ITEMS.SA")
        hashes = {key: frame_hash(value) for key, value in inputs.items()}
        hashes.update(policy_events=hashlib.sha256(event_text.encode()).hexdigest(), cpi_vintages=frame_hash(cpi),
                      target_validation=hashlib.sha256(level_text.encode()).hexdigest())
        sha = S.freeze(out, hashes)
        export_inputs(inp.db, out)
        history = classify_events(events)
        cycle_table = cycles(history)
        history.to_csv(out / "event_state_history.csv", index=False)
        cycle_table.to_csv(out / "cycles.csv", index=False)
        decisions = Calendar(sessions, lag=S.SPEC["execution_lag_sessions"]).formation
        decisions = decisions[decisions >= S.SPEC["start"]]
        inflation = inflation_panel(cpi, decisions)
        panel(history, sessions).to_csv(out / "daily_state_history.csv", index_label="decision_date")
        frames, comparison = O.compute(out, hashes, inputs, history, cycle_table, sessions, inflation)
        for name, df in frames.items():
            df.to_csv(out / f"{name}.csv", index=False)
        (out / "inflation_comparison.json").write_text(json.dumps(comparison, indent=2, default=str))
        meta = {"run_at": datetime.now(timezone.utc).isoformat(), "spec_sha256": sha,
                "include_estimates": include_estimates,
                "first_session": str(sessions[0].date()), "last_session": str(sessions[-1].date()),
                "events": len(events), "complete_cycles": int(cycle_table.complete.sum()),
                "timing_counts": events.timing_basis.value_counts().to_dict(),
                "reserved_note": S.SPEC["reserved_note"],
                "input_hashes": hashes}
        (out / "run_metadata.json").write_text(json.dumps(meta, indent=2))
        from .report import write_report
        write_report(out)
        print(json.dumps(meta, indent=2))
        print("findings:", out / "FINDINGS.md")
    finally:
        inp.db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--exclude-estimates", action="store_true", help="reproduce source-only frozen inputs")
    args = parser.parse_args()
    main(args.out, include_estimates=not args.exclude_estimates)
