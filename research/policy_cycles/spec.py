import hashlib
import json
from pathlib import Path

SPEC = {
    "start": "1994-02-01",
    "states": ["unknown", "hiking", "hold_after_hiking", "easing", "hold_after_easing"],
    "direction": "sign of announced target midpoint change; single targets have equal bounds",
    "hold": "only a subsequent scheduled meeting with identical target bounds establishes a hold state",
    "initial": "unknown until first directional change; no pre-1994 direction seed",
    "unknown_time": "date-only announcements conservatively available at next calendar-day midnight ET",
    "cycle": "first hike after easing begins a cycle; ends immediately before next such hike",
    "zlb_upper_pct": 0.25,
    "execution_lag_sessions": 1,
    "sessions": "existing usable daily 10Y CMT observation calendar, as in the inflation study",
    "targets": {"SYN2Y": "2Y CMT daily par-bond model", "SYN8Y": "5Y/10Y interpolated 8Y daily par-bond model"},
    "return_model": "research.targets.par_bond_return; daily rebought par bonds; calendar days/365",
    "financing": "existing 91-day discount-bill investment-yield convention; start-interval rate",
    "horizons_months": [1, 3, 6],
    "excess": "duration total return minus compounded bills return over the same execution window",
    "allocation_target": "SYN8Y",
    "duration_weights": {"unknown": 0.0, "hiking": 0.0, "hold_after_hiking": 1.0,
                         "easing": 1.0, "hold_after_easing": 1.0},
    "cost_per_duration_notional": 0.0005,
    "costs": "5bp times absolute duration-weight change, including initial entry; no bills-leg fee; no forced final exit",
    "strategy_grid": "daily close state, execute next session close; weight applies after execution close",
    "reserved_cycle_start": "2015-01-01",
    "reserved_note": "reserved whole cycles, not pristine out-of-sample: prior exposure to their outcomes",
    "inference": {"min_complete_cycles": 6, "min_months": 24, "bootstrap_reps": 2000, "seed": 20261111,
                  "unit": "equal-weight complete cycle means; resample cycles, not overlapping months",
                  "output": "descriptive 95% cycle-bootstrap intervals only; no p-values"},
    "inflation_comparison": {
        "state": "hold_after_hiking", "target": "SYN8Y", "horizon_months": 3,
        "measure": "HEADLINE", "level_rule": "L1_FIXED", "momentum_rule": "M1_DYOY_3M",
        "persistence": "raw", "high_yoy_pct": 3.5, "rising_dyoy3_pp": 0.30,
        "groups": ["high_and_rising", "other_known_inflation"],
        "unknown": "excluded, not assigned to the comparison group",
        "min_complete_cycles_each": 3, "min_months_each": 24,
        "note": "one mutually exclusive comparison; inflation and ZLB never alter allocation"},
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def freeze(out, input_hashes, spec=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    payload = {"spec": SPEC if spec is None else spec, "inputs": input_hashes}
    sha = digest(payload)
    path = out / "spec_frozen.json"
    if path.exists():
        verify(out, input_hashes, spec=spec)
        return sha
    from datetime import datetime, timezone
    path.write_text(json.dumps({"sha256": sha, "frozen_at": datetime.now(timezone.utc).isoformat(),
                               **payload}, indent=2))
    return sha


def verify(out, input_hashes, spec=None):
    path = Path(out) / "spec_frozen.json"
    if not path.exists():
        raise RuntimeError("Freeze configuration and inputs before computing outcomes")
    frozen = json.loads(path.read_text())
    payload = {"spec": SPEC if spec is None else spec, "inputs": input_hashes}
    if frozen.get("sha256") != digest(payload) or digest(
            {"spec": frozen["spec"], "inputs": frozen["inputs"]}) != frozen["sha256"]:
        raise RuntimeError("Frozen configuration or inputs changed; refusing to compute outcomes")
