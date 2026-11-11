import json

import pandas as pd
from macrodb.reports import _md


def write_report(out):
    meta = json.loads((out / "run_metadata.json").read_text())
    performance = pd.read_csv(out / "performance.csv")
    paired = pd.read_csv(out / "paired_cycle_differences.csv")
    uncertainty = pd.read_csv(out / "cycle_uncertainty.csv")
    pauses = pd.read_csv(out / "pause_followup.csv")
    diagnostics = pd.read_csv(out / "pause_diagnostics.csv")
    inputs = pd.read_csv(out / "input_coverage.csv")
    candidates = pd.read_csv(out / "pause_events.csv")
    primary = performance[(performance.target == "SYN2Y") & (performance["sample"] == "all")].set_index("rule")
    difference = primary.loc["completion_filter", "net_return"] - primary.loc["baseline", "net_return"]
    table = performance[["target", "rule", "sample", "annualized_excess_over_bills", "max_drawdown",
                         "duration_turnover", "time_in_duration"]].copy()
    for column in ["annualized_excess_over_bills", "max_drawdown", "time_in_duration"]:
        table[column] = table[column].map(lambda value: f"{value:.2%}")
    cycles = paired[["target", "cycle_id", "sample", "complete", "informative",
                     "baseline", "completion_filter", "filter_minus_baseline_net"]].copy()
    for column in ["baseline", "completion_filter", "filter_minus_baseline_net"]:
        cycles[column] = cycles[column].map(lambda value: f"{value:.2%}")
    primary_uncertainty = uncertainty[(uncertainty.target == "SYN2Y") & (uncertainty["sample"] == "all")].iloc[0]
    unique = diagnostics[diagnostics.target == "SYN2Y"]
    known_delay = unique.entry_delay_calendar_days.dropna()
    active = unique[unique.signal_activated_at.notna()]
    false_starts = active.renewed_hike_after_activation_6m
    status = "Not validated. This is a fixed, numerical-only research extension, not the book's executable rule."
    lines = [
        "# Section 5.3: How to Trade a Hiking Cycle", "", f"**Conclusion: {status}**", "",
        f"Primary measured difference (SYN2Y filter minus first-hold baseline, full-path net cumulative return): "
        f"**{difference * 100:+.2f} percentage points** "
        f"(baseline {primary.loc['baseline', 'net_return']:.2%}; filter "
        f"{primary.loc['completion_filter', 'net_return']:.2%}). This cumulative difference is not annualized. "
        f"Cycle-level inference: **{primary_uncertainty['status']}** "
        f"({int(primary_uncertainty.complete_cycles)} complete cycles; "
        f"{int(primary_uncertainty.informative_complete_cycles)} with usable required inputs during a pause).", "",
        "## Book observations versus our extension", "",
        "The book's observations motivate caution about smaller hikes, temporary pauses and high-but-falling inflation. "
        "The last hike is identified only retrospectively. Wage-setting, expectations and communications may matter; "
        "this study does not establish those mechanisms. Pre-first-hike weakness is not tested here, and no last-hike "
        "oracle is traded. First-hike forecasting, shorts and broader searches are deferred.", "",
        "Our one operational rule requires headline/core YoY <3.5%, core YoY falling more than 0.30pp over three "
        "observation months; ECI wage YoY <=3.5% and down at least 0.50pp over two quarters; Cleveland Fed modeled "
        "ten-year expectations <=2.5% and non-increasing over three observation months. All required inputs must "
        "be available and fresh. Productivity is optional context, not a gate. No thresholds were tuned.", "",
        "Official contemporaneous statements, clocks and archived lineage are retained in pause_communications.csv; "
        "later minutes are excluded. A reliable historical communication classifier was not established: the text condition "
        "is explicitly deferred, not reconstructed from memory or silently treated as satisfied.", "",
        "## Measured allocation results", "", _md(table), "",
        "Percentages: annualized net return minus annualized bills return; strategy peak-to-trough drawdown; "
        "share of execution intervals in duration. Turnover is one-way duration notional. Full-path costs are retained "
        "when subdividing samples. Both paths begin in bills, execute one session after observation and pay 5bp per "
        "unit of duration bought/sold (10bp round trip). Returns are model-estimated, not observed Treasury indexes.", "",
        "## Pauses, activation and waiting", "",
        f"{len(pauses)} observable candidate pauses; {int(pauses.renewed_hike_6m.eq(True).sum())} renewed hikes within six "
        f"months; {int(pauses.censored_6m.sum())} censored no-hike follow-ups. "
        f"Required inputs were complete at {int(candidates.inputs_complete.sum())} first-hold observations. "
        f"{meta['signal_activations']} numerical activations; "
        f"{int(false_starts.eq(True).sum())} observed renewed hikes within six months of activation, "
        f"{int(false_starts.isna().sum())} activated follow-ups unclassified/censored. "
        f"Median entry delay when an entry is observed: {known_delay.median():.0f} calendar days; "
        f"{int(unique.entry_delay_censored.sum())} entries censored before entry. "
        f"Median positive excess rally missed while waiting: {unique.positive_rally_missed_excess.median():.2%}.", "",
        ("No numerical activations occurred. The filter therefore waited for cuts or remained in bills. Its realized "
         "performance cannot validate an ability to recognize completion, and no activation accuracy can be estimated."
         if not meta["signal_activations"] else
         "Activation is not proof of completion. False starts and censored follow-ups are kept separate; "
         "do not infer reliability from a small count of activations."), "",
        "pause_diagnostics.csv reports every pause/target's entry timing, observed waiting return, positive excess "
        "rally missed, and descriptive 1/3/6-month outcomes. Positive/negative outcomes and future hikes/cuts are "
        "retrospective evaluation fields only; none enter allocations. No hike in six months is not proof of "
        "permanent completion.", "",
        "## Each independent cycle", "", _md(cycles), "",
        "Cycle returns are net cumulative returns, not annualized. The final cycle is ongoing. The reserved split "
        "uses whole cycles starting in 2015 or later; it is **reserved, not blind out-of-sample**, because prior "
        "research has already exposed their outcomes. Multiple pauses within one cycle are not independent cycles.", "",
        "## Availability and limitations", "", _md(inputs), "",
        "Unknown historical publication clocks are not invented: day-only vintages become usable the following "
        "calendar-day midnight ET, and ingestion-only/estimated observations are never backdated. Missing months "
        "remain missing at earlier decisions. Early archive backfills are usable only when that vintage was actually "
        "available. Missing required inputs block the signal, so full-sample performance mixes an operational "
        "missing-data policy with the proposed economic detector; it is not evidence that the detector worked in "
        "input-uncovered cycles.", "",
        "Existing daily 5Y5Y breakevens were not substituted: their stored history lacks historical availability. "
        "The newly ingested Cleveland Fed series is a model-based long-term expectations proxy, not a direct survey; "
        "ECI is aggregate wage growth, not a direct measure of wage-setting behavior. Productivity revisions, "
        "quarterly wage releases, conservative clocks and model limitations constrain identification.", "",
        "inflation_description.csv gives descriptive high/rising, high/falling, other and unknown strata, using "
        "the existing headline thresholds. These are conditional, noncontiguous sessions, not independent episodes "
        "or additional strategies. Uncertainty resamples paired complete cycles only, and requires at least six "
        "input-informative complete cycles; otherwise the result is insufficient evidence. No monthly IID p-values.", "",
        f"Frozen SHA-256: `{meta['spec_sha256']}`. All inputs are database-derived; source versions, provenance, "
        "decision features, trades, censoring and the single frozen specification are exported alongside this report.", ""]
    (out / "FINDINGS.md").write_text("\n".join(lines))
