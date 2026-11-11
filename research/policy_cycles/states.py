import numpy as np
import pandas as pd

from ..data import ts
from .spec import SPEC


def classify_events(events):
    events = events.copy()
    events["known_at"] = pd.to_datetime(events.known_at, utc=True)
    events = events.sort_values(["known_at", "event_id"])
    state, direction, holds = "unknown", None, 0
    last_change, cycle, cycle_start = pd.NaT, None, pd.NaT
    rows = []
    for e in events.to_dict("records"):
        low, high = float(e["target_low"]), float(e["target_high"])
        old_low, old_high = float(e["previous_low"]), float(e["previous_high"])
        delta = (low + high - old_low - old_high) / 2
        unchanged = abs(low - old_low) < 1e-8 and abs(high - old_high) < 1e-8
        if abs(delta) > 1e-8:
            new_direction = "hiking" if delta > 0 else "easing"
            if new_direction == "hiking" and direction != "hiking":
                cycle_start = pd.Timestamp(e["announcement_date"])
                cycle = f"CYCLE_{cycle_start:%Y%m%d}"
            direction, state, holds = new_direction, new_direction, 0
            last_change = e["known_at"]
        elif unchanged and e["scheduled"]:
            holds += 1
            if direction:
                state = "hold_after_hiking" if direction == "hiking" else "hold_after_easing"
        elif not unchanged:
            holds = 0
        rows.append({**e, "state": state, "last_direction": direction, "consecutive_scheduled_holds": holds,
                     "last_change_known_at": last_change, "cycle_id": cycle, "cycle_start": cycle_start,
                     "zlb": high <= SPEC["zlb_upper_pct"] + 1e-8,
                     "time_since_last_change_days": (e["known_at"] - last_change).total_seconds() / 86400
                     if pd.notna(last_change) else np.nan})
    return pd.DataFrame(rows)


def panel(history, decisions):
    """State known by each decision close; date-only events cannot leak into their announcement day."""
    decisions = pd.DatetimeIndex(decisions)
    left = pd.DataFrame({"decision_date": decisions,
                         "decision_ts": pd.to_datetime([ts(d, 16).tz_convert("UTC") for d in decisions])})
    cols = ["event_id", "known_at", "state", "target_kind", "target_low", "target_high",
            "last_change_known_at", "consecutive_scheduled_holds", "cycle_id", "cycle_start", "zlb"]
    out = pd.merge_asof(left.sort_values("decision_ts"), history[cols].sort_values("known_at"),
                        left_on="decision_ts", right_on="known_at")
    out["state"] = out.state.fillna("unknown")
    out["consecutive_scheduled_holds"] = out.consecutive_scheduled_holds.fillna(0).astype(int)
    out["time_since_last_change_days"] = (out.decision_ts - out.last_change_known_at).dt.total_seconds() / 86400
    out["sample"] = np.where(out.cycle_start >= pd.Timestamp(SPEC["reserved_cycle_start"]), "reserved", "design")
    out.loc[out.cycle_id.isna(), "sample"] = "unknown"
    return out.set_index("decision_date")


def cycles(history):
    starts = history.dropna(subset=["cycle_id"]).drop_duplicates("cycle_id")
    rows = []
    for i, e in enumerate(starts.to_dict("records")):
        nxt = starts.iloc[i + 1] if i + 1 < len(starts) else None
        rows.append({"cycle_id": e["cycle_id"], "start": e["cycle_start"],
                     "start_known_at": e["known_at"], "end_known_at": nxt.known_at if nxt is not None else pd.NaT,
                     "complete": nxt is not None,
                     "sample": "reserved" if e["cycle_start"] >= pd.Timestamp(SPEC["reserved_cycle_start"]) else "design"})
    return pd.DataFrame(rows)
