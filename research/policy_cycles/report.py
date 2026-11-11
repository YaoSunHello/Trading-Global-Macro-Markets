import json
from pathlib import Path

import pandas as pd

from ..inflation_states.report import table


def percentages(frame, columns):
    frame = frame.copy()
    for col in columns:
        frame[col] = frame[col].map(lambda x: "n/a" if pd.isna(x) else f"{100 * x:.2f}%")
    return frame


def write_report(out):
    out = Path(out)
    meta = json.loads((out / "run_metadata.json").read_text())
    frozen = json.loads((out / "spec_frozen.json").read_text())
    spec = frozen["spec"]
    events = pd.read_csv(out / "policy_events.csv")
    conditional = pd.read_csv(out / "conditional_returns.csv")
    per_cycle = pd.read_csv(out / "per_cycle_returns.csv")
    perf = pd.read_csv(out / "strategy_performance.csv")
    strategy_cycles = pd.read_csv(out / "per_cycle_strategy.csv")
    comparison = json.loads((out / "inflation_comparison.json").read_text())
    inflation = pd.read_csv(out / "inflation_comparison_counts.csv")
    grid = pd.read_csv(out / "outcome_grid.csv")
    counts = pd.read_csv(out / "cycles.csv")
    full_perf = perf[perf["sample"] == "all"].set_index("strategy")
    reserved_perf = perf[perf["sample"] == "reserved"].set_index("strategy")
    inference = conditional[(conditional["sample"] == "all") & (conditional.target == "SYN8Y") &
                            (conditional.horizon_months == 3)][
        ["state", "cycle_equal_weight_mean", "cycle_ci_low", "cycle_ci_high", "inference"]]
    lines = [
        "# Section 5.2: policy-cycle study", "",
        f"Run {meta['run_at']}; market sessions {meta['first_session']} through {meta['last_session']}.",
        f"Frozen configuration and input hash: `{meta['spec_sha256']}`. No parameter search was performed.", "",
        "## Main findings", "",
        f"The fixed rule's net annualized model return is {100 * full_perf.loc['net', 'annualized_return']:.2f}%, "
        f"versus {100 * full_perf.loc['duration_buy_hold', 'annualized_return']:.2f}% for duration buy-and-hold "
        f"and {100 * full_perf.loc['bills_benchmark', 'annualized_return']:.2f}% for bills. "
        f"In reserved cycles it returns {100 * reserved_perf.loc['net', 'annualized_return']:.2f}% annualized, "
        f"below bills at {100 * reserved_perf.loc['bills_benchmark', 'annualized_return']:.2f}%. "
        "The full-sample advantage is therefore not a uniform advantage over cash across cycles.",
        "Hold-after-hiking has positive pooled forward duration excess returns, but the per-cycle tables "
        "show material variation. Six complete cycles provide only limited inferential support; design and "
        "reserved segments do not independently meet the six-cycle interval threshold. "
        f"The one inflation comparison reports **{comparison['status']}**.", "",
        "## Scope and evidence", "",
        "All policy targets, events and source provenance are read from the central DuckDB database. "
        "Research performs no downloads; result input CSVs are audit exports. Database migration preserved "
        "the original frozen configuration, input fingerprints and numerical outcomes.",
        f"{len(events)} events: {int(events.scheduled.sum())} scheduled decisions including holds, "
        f"{int((~events.scheduled).sum())} target-changing intermeeting announcements. "
        f"{int(counts.complete.sum())} complete cycles and {int((~counts.complete).sum())} ongoing cycle(s).",
        "Official Fed calendars/statements/minutes establish event dates and scheduled status. Official "
        "FRED target series establish numerical levels (single targets before December 16, 2008; ranges afterward). "
        "Target-level observation dates are not substituted for announcement dates.",
        "Historical statements that only say 'immediate release' have no fabricated clock time. "
        "Date-only announcements and reconstructed scheduled holds are conservatively usable only from the "
        "next calendar-day midnight, then subject to the execution lag. These rows are reconstruction, not verified "
        "intraday real-time observations.",
        table(pd.DataFrame(list(meta["timing_counts"].items()), columns=["Timing basis", "Events"])), "",
        "## State rules and timing", "",
        "A target midpoint increase establishes hiking; a decrease establishes easing. Only a later scheduled "
        "meeting leaving both bounds unchanged establishes hold-after-hiking/easing. An unchanged intermeeting "
        "announcement cannot establish a hold. Direction is initially unknown. Each directional change resets "
        "time since last change and consecutive scheduled holds. A range-width-only change has no inferred direction.",
        "ZLB is declared as target upper bound <=0.25%; it is a reporting flag, not an allocation override. "
        "One session of execution lag applies after the state is observable at a session close. Sunday/after-close "
        "announcements first enter the next eligible session's decision, then execute one session later.",
        "Daily/monthly state histories retain source event, target representation, availability, time since change, "
        "scheduled-hold counts, cycle and ZLB. See `policy_events.csv`, `event_state_history.csv`, "
        "`daily_state_history.csv` and `cycles.csv`.", "",
        "## Forward excess returns", "",
        "Month-end formation closes; returns begin at the next-session execution close and end at the equally "
        "lagged formation close 1, 3 or 6 months later. Percentages are horizon returns, not annualized. "
        "Months are not independent observations: 3/6-month windows overlap. Cycle counts are distinct "
        "hike-through-easing cycles, not state spells.",
        "Both maturities are MODEL-ESTIMATED daily-rebought par-bond targets, not observed tradable index returns. "
        "SYN2Y uses 2Y CMT; SYN8Y reuses linear 5Y/10Y interpolation. Coupon accrual and price changes use the existing "
        "semiannual par-bond model. Bills use the existing 91-day discount-to-investment-yield conversion, "
        "calendar-day accrual and compounding. Excess return is duration return minus bills return.", "",
    ]
    cols = ["target", "horizon_months", "state", "months", "cycles", "complete_cycles", "mean_excess", "inference"]
    lines += [table(percentages(conditional[conditional["sample"] == "all"][cols], ["mean_excess"])), "",
              "### Whole-cycle reserved split", "", spec["reserved_note"] + ".",
              "Cycles beginning in 2015 or later are reserved in their entirety, not split at January 2015. "
              "See design/reserved rows in `conditional_returns.csv`; no allocation or threshold was chosen "
              "using either segment's returns.", "", table(counts[["cycle_id", "start", "complete", "sample"]]), "",
              "### Per-cycle evidence", "",
              "The following reports the primary 8Y, 3-month horizon; both targets and every declared horizon "
              "are in `per_cycle_returns.csv`. Ongoing cycles are descriptive only.", "",
              table(percentages(per_cycle[(per_cycle.target == "SYN8Y") & (per_cycle.horizon_months == 3)][
                  ["cycle_id", "sample", "complete", "state", "months", "mean_excess"]], ["mean_excess"])), "",
              f"Inference requires at least {spec['inference']['min_complete_cycles']} complete cycles with observations "
              f"and {spec['inference']['min_months']} months per cell. Only complete-cycle, non-boundary-crossing "
              "windows enter equal-weight cycle-bootstrap intervals. No IID monthly standard errors or p-values. "
              f"Cells with intervals: {int(conditional.cycle_ci_low.notna().sum())}. "
              "A long monthly history does not overcome a small number of independent policy cycles.", "",
              "Primary SYN8Y/3m equal-weight complete-cycle means and descriptive 95% bootstrap intervals "
              "(different estimand from pooled monthly means above):", "",
              table(percentages(inference, ["cycle_equal_weight_mean", "cycle_ci_low", "cycle_ci_high"])), "",
              "## One fixed long-only rule", "",
              "100% SYN8Y in hold-after-hiking, easing and hold-after-easing; 100% bills in hiking and unknown. "
              "Hold-after-hiking is not anticipated at the final hike. Signals are evaluated at daily closes, "
              "executed one session later, and affect only subsequent returns. Inflation and ZLB do not change weights.",
              "Costs are 5bp per unit of duration notional bought or sold: 10bp for a full round trip, "
              "without a second charge on bills. Initial duration entry is charged; no artificial terminal exit. "
              "Duration buy-and-hold pays its initial 5bp; bills pay no duration cost. Split returns preserve "
              "the actual full-path trades rather than charging a new initial entry at each split.", "",
              table(percentages(perf[["strategy", "sample", "total_return", "annualized_return", "max_drawdown",
                                       "duration_turnover", "cost_sum"]],
                                ["total_return", "annualized_return", "max_drawdown", "cost_sum"])), "",
              "Per-cycle strategy and benchmark total returns:", "",
              table(percentages(strategy_cycles[["cycle_id", "sample", "strategy", "total_return"]], ["total_return"])), "",
              "These are descriptive model backtests, not proof of a tradable edge. The bond model omits "
              "actual roll-down, instrument selection, funding frictions and market impact; fixed 5bp costs "
              "do not validate historical execution feasibility.", "",
              "## One mutually exclusive inflation comparison", "",
              "Within hold-after-hiking only: headline CPI high (YoY >=3.5%) AND rising "
              "(three-month change in YoY >0.30pp), versus all other known headline inflation states. "
              "Unknown inflation is excluded. Existing point-in-time ALFRED snapshots and raw classification "
              "are reused; release timestamp/observation month are retained.",
              f"Target SYN8Y, forward 3 months. Status: **{comparison['status']}**.",
              "Declared difference (high-and-rising minus other): " +
              ("not estimated because the sufficiency gate failed." if comparison["difference"] is None
               else f"{100 * comparison['difference']:.2f}% (descriptive only)."),
              table(percentages(inflation, ["mean_excess"])),
              "At least 24 months and three complete cycles in each group are required for a descriptive "
              "difference. No second inflation contrast is substituted if evidence is insufficient.", "",
              "## Limitations and conclusion", "",
              f"Last month-end decision: {grid.decision_date.iloc[-1]}; incomplete forward horizons remain missing. "
              "Historical availability is only as reliable as the source/time flag. FRED/H.15 yields are used "
              "to model realized marks, not as contemporaneously available allocation predictors.",
              "The study measures policy-cycle associations and one fixed rule. Sparse cycle evidence, overlapping "
              "horizons, reconstructed early timing and prior exposure to reserved outcomes limit inference. "
              "No causality or optimized investment recommendation is claimed.",
              "Deferred: pre-1994 data, extra maturities, additional strategies, expectations proxies and "
              "term-premium models.", ""]
    (out / "FINDINGS.md").write_text("\n".join(lines))
