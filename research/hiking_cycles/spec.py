from ..policy_cycles import spec as policy

SERIES = {
    "headline": "US.CPI.ALL_ITEMS.SA",
    "core": "US.CPI.CORE.SA",
    "wages": "US.WAGES.ECI.PRIVATE.SA",
    "productivity": "US.PRODUCTIVITY.NONFARM.SA",
    "expectations": "US.INFLATION.EXPECTED.10Y.CLEVELAND",
}
SPEC = {
    "section": "5.3", "start": "1994-02-01",
    "candidate": "first unchanged scheduled decision after each run of hikes; intermeeting changes count; no later holds until a renewed hike",
    "signal_kind": "numerical-only research extension; communication condition explicitly deferred",
    "series": SERIES,
    "availability": "ALFRED day-only vintages usable at following calendar-day midnight ET; ingestion-only facts and approved estimates usable at actual UTC ingestion time; never backdated",
    "staleness_days_from_period_end": {"headline": 90, "core": 90, "wages": 210, "productivity": 210, "expectations": 90},
    "inflation": {"headline_yoy_lt": 3.5, "core_yoy_lt": 3.5, "core_dyoy3_lt_pp": -0.30,
                  "note": "core disinflation plus both CPI measures below the existing high-inflation threshold"},
    "wages": {"eci_yoy_le": 3.5, "eci_dyoy_two_quarters_le_pp": -0.50},
    "expectations": {"ten_year_expected_cpi_le": 2.5, "change_three_observation_months_le_pp": 0.0,
                     "proxy": "Cleveland Fed model-based estimate; not a pure survey; archive availability limits early cycles"},
    "productivity": "YoY context only, contemporaneously available; wage growth minus productivity growth is descriptive, not unit labor costs",
    "missing": "any missing/stale required transformation blocks activation; optional productivity/communications never filled",
    "communication": "archive official statements, clock and document lineage for inspection; no reliable validated historical text classifier, no text in signal",
    "evaluation": "each usable 10Y-CMT session close while hold_after_hiking; activated position latched until a new hike; cut enters duration regardless",
    "outside_transition_weights": {"unknown": 0.0, "hiking": 0.0, "easing": 1.0, "hold_after_easing": 1.0},
    "baseline": "100% duration after first scheduled hold; otherwise existing state allocation",
    "completion_filter": "100% bills during hold_after_hiking until numerical signal; 100% duration after activation or an actual cut",
    "initial_duration_weight": 0.0, "execution_lag_sessions": 1,
    "cost_per_duration_notional": policy.SPEC["cost_per_duration_notional"],
    "costs": policy.SPEC["costs"], "financing": policy.SPEC["financing"],
    "targets": {"SYN2Y": "primary, existing synthetic 2Y", "SYN8Y": "secondary, existing synthetic 8Y"},
    "followup_months": 6, "return_horizons_months": [1, 3, 6],
    "return_horizon_timing": "entry one session after first close seeing pause; exit one session after first close on/after decision-date plus 1/3/6 calendar months",
    "outcome_censoring": "no renewed hike in six months is known only after six calendar months of follow-up; a cut does not terminate follow-up",
    "primary": "SYN2Y completion-filter minus baseline net cumulative return, same common path; cycle-paired differences for uncertainty",
    "reserved_cycle_start": policy.SPEC["reserved_cycle_start"],
    "reserved_note": policy.SPEC["reserved_note"],
    "inference": {"min_complete_cycles": 6, "min_informative_cycles": 6, "reps": 2000, "seed": 20261111,
                  "unit": "paired full-cycle net-return differences; no overlapping-month p-values"},
    "inflation_descriptions": "existing headline L1_FIXED high >=3.5 and M1_DYOY_3M rising >0.30/falling <-0.30; unknown separate; never used as retrospective labels",
    "deferred": ["first-hike forecasting", "shorts", "parameter search", "historical communication classifier",
                 "additional strategies", "retrospective last-hike trading rule"],
}


def freeze(out, hashes):
    return policy.freeze(out, hashes, spec=SPEC)


def verify(out, hashes):
    return policy.verify(out, hashes, spec=SPEC)
