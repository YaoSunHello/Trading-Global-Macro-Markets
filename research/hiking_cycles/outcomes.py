import numpy as np
import pandas as pd

from ..data import ts
from ..inflation_states.outcomes import Treasury
from ..policy_cycles import outcomes as P
from . import spec as S


def execution_date(known_at, sessions):
    closes = pd.DatetimeIndex([ts(day, 16).tz_convert("UTC") for day in sessions])
    position = closes.searchsorted(pd.Timestamp(known_at))
    position += S.SPEC["execution_lag_sessions"]
    return sessions[position] if position < len(sessions) else pd.NaT


def followup(pauses, history, as_of):
    available = history[history.known_at <= as_of]
    rows = []
    for pause in pauses.to_dict("records"):
        future = available[available.known_at > pause["known_at"]]
        change = future.target_low + future.target_high - future.previous_low - future.previous_high
        hikes = future[change > 1e-8]
        cuts = future[change < -1e-8]
        nxt = future[change.abs() > 1e-8]
        horizon = pd.Timestamp(pause["announcement_date"]) + pd.DateOffset(months=S.SPEC["followup_months"])
        first_hike = hikes.iloc[0] if len(hikes) else None
        positive = first_hike is not None and pd.Timestamp(first_hike.announcement_date) <= horizon
        full = pd.Timestamp(as_of.tz_convert("America/New_York").date()) >= horizon
        row = {"pause_id": pause["pause_id"], "cycle_id": pause["cycle_id"],
               "six_month_deadline": horizon, "six_month_window_complete": full,
               "renewed_hike_6m": True if positive else False if full else np.nan,
               "censored_6m": not positive and not full}
        for kind, frame in [("hike", hikes), ("cut", cuts), ("change", nxt)]:
            row[f"next_{kind}_known_at"] = frame.known_at.iloc[0] if len(frame) else pd.NaT
            row[f"days_to_next_{kind}"] = (
                (pd.Timestamp(frame.announcement_date.iloc[0]) - pd.Timestamp(pause["announcement_date"])).days
                if len(frame) else np.nan)
            row[f"next_{kind}_censored"] = frame.empty
        rows.append(row)
    return pd.DataFrame(rows)


def summarize(g):
    wealth = np.r_[1.0, np.cumprod(1 + g.net.to_numpy())]
    bill = np.r_[1.0, np.cumprod(1 + g.bills_return.to_numpy())]
    relative = wealth / bill
    days = (g.end_session.iloc[-1] - g.index[0]).days
    return {"sessions": len(g), "net_return": wealth[-1] - 1, "bills_return": bill[-1] - 1,
            "net_excess_over_bills": wealth[-1] - bill[-1],
            "annualized_net_return": wealth[-1] ** (365 / days) - 1,
            "annualized_excess_over_bills": wealth[-1] ** (365 / days) - bill[-1] ** (365 / days),
            "max_drawdown": (wealth / np.maximum.accumulate(wealth) - 1).min(),
            "relative_to_bills_drawdown": (relative / np.maximum.accumulate(relative) - 1).min(),
            "duration_turnover": g.turnover.sum(), "cost_sum": g.cost.sum(),
            "time_in_duration": g.weight.mean()}


def strategies(actions, sessions, wealth, bill, cycle_table):
    daily_frames, summaries, per_cycle, descriptions = [], [], [], []
    complete = cycle_table.set_index("cycle_id").complete.to_dict()
    informative = actions[actions.policy_state.eq("hold_after_hiking") & actions.inputs_complete].cycle_id.unique()
    for target, prices in wealth.items():
        dr, br = prices.shift(-1) / prices - 1, bill.shift(-1) / bill - 1
        for rule in ["baseline", "completion_filter"]:
            weights = actions[f"{rule}_weight"].shift(S.SPEC["execution_lag_sessions"]).fillna(0)
            daily = P.allocation_returns(dr, br, weights, S.SPEC["cost_per_duration_notional"])
            daily["bills_return"] = br
            daily = daily.join(actions[["cycle_id", "sample", "inflation_group", "signal_activation"]])
            daily["end_session"] = pd.Series(sessions, index=sessions).shift(-1)
            daily = daily.iloc[:-1]
            if daily[["net", "bills_return"]].isna().any().any():
                raise RuntimeError("Missing strategy returns; cannot bridge market-data gaps")
            for sample in ["all", "design", "reserved"]:
                g = daily if sample == "all" else daily[daily["sample"] == sample]
                if len(g):
                    summaries.append({"target": target, "rule": rule, "sample": sample,
                                      "cycles": g.cycle_id.nunique(), **summarize(g)})
            for cycle, g in daily.dropna(subset=["cycle_id"]).groupby("cycle_id"):
                per_cycle.append({"target": target, "rule": rule, "cycle_id": cycle,
                                  "sample": g["sample"].iloc[0], "complete": complete[cycle],
                                  "informative": cycle in informative, **summarize(g)})
            for group, g in daily.groupby("inflation_group"):
                descriptions.append({"target": target, "rule": rule, "inflation_group": group,
                                     "sessions": len(g), "cycles": g.cycle_id.nunique(),
                                     "mean_daily_net_excess": (g.net - g.bills_return).mean(),
                                     "time_in_duration": g.weight.mean(),
                                     "note": "noncontiguous conditional sessions, descriptive only"})
            daily_frames.append(daily.reset_index(names="execution_date").assign(target=target, rule=rule))
    return pd.concat(daily_frames, ignore_index=True), pd.DataFrame(summaries), pd.DataFrame(per_cycle), pd.DataFrame(descriptions)


def cycle_comparison(per_cycle):
    idx = ["target", "cycle_id", "sample", "complete", "informative"]
    wide = per_cycle.pivot(index=idx, columns="rule", values="net_return").reset_index()
    wide["filter_minus_baseline_net"] = wide.completion_filter - wide.baseline
    rows = []
    for target in S.SPEC["targets"]:
        for sample in ["all", "design", "reserved"]:
            g = wide[(wide.target == target) & wide.complete]
            if sample != "all":
                g = g[g["sample"] == sample]
            informative = g[g.informative]
            enough = len(g) >= S.SPEC["inference"]["min_complete_cycles"] and len(informative) >= S.SPEC["inference"]["min_informative_cycles"]
            low, high = np.nan, np.nan
            if enough:
                rng = np.random.default_rng(S.SPEC["inference"]["seed"])
                samples = rng.choice(informative.filter_minus_baseline_net.to_numpy(),
                                     (S.SPEC["inference"]["reps"], len(informative)), replace=True).mean(axis=1)
                low, high = np.quantile(samples, [.025, .975])
            rows.append({"target": target, "sample": sample, "complete_cycles": len(g),
                         "informative_complete_cycles": len(informative),
                         "equal_cycle_mean_net_difference": informative.filter_minus_baseline_net.mean(),
                         "cycle_ci_low": low, "cycle_ci_high": high,
                         "status": "descriptive cycle-bootstrap interval" if enough else "insufficient evidence"})
    return wide, pd.DataFrame(rows)


def pause_results(pauses, followups, actions, sessions, wealth, bill, as_of):
    rows = []
    for pause in pauses.to_dict("records"):
        outcome = followups[followups.pause_id == pause["pause_id"]].iloc[0]
        end = outcome.next_hike_known_at
        window = actions[(actions.decision_ts >= pause["known_at"]) &
                         ((actions.decision_ts < end) if pd.notna(end) else True)]
        if window.empty:
            continue
        baseline_date = execution_date(pause["known_at"], sessions)
        enters = window[window.completion_filter_weight > 0]
        filter_date = execution_date(enters.decision_ts.iloc[0], sessions) if len(enters) else pd.NaT
        activations = window[window.signal_activation]
        activated = activations.decision_ts.iloc[0] if len(activations) else pd.NaT
        observed_end = execution_date(end, sessions) if pd.notna(end) else sessions[-1]
        if pd.isna(observed_end):
            observed_end = sessions[-1]
        waiting_end = filter_date if pd.notna(filter_date) else observed_end
        for target, prices in wealth.items():
            def excess(start, finish):
                if pd.notna(start) and start == finish:
                    return 0.0
                return P.return_between(prices, start, finish) - P.return_between(bill, start, finish)
            waiting_excess = excess(baseline_date, waiting_end)
            row = {"pause_id": pause["pause_id"], "cycle_id": pause["cycle_id"], "target": target,
                   "baseline_execution": baseline_date, "filter_execution": filter_date,
                   "signal_activated_at": activated,
                   "entry_delay_calendar_days": (filter_date - baseline_date).days if pd.notna(filter_date) and pd.notna(baseline_date) else np.nan,
                   "entry_delay_censored": pd.isna(filter_date),
                   "observed_wait_calendar_days": (waiting_end - baseline_date).days if pd.notna(baseline_date) else np.nan,
                   "duration_excess_while_waiting": waiting_excess,
                   "positive_rally_missed_excess": max(0, waiting_excess) if pd.notna(waiting_excess) else np.nan,
                   "entry_reason": ("numerical_signal" if pd.notna(activated) else "actual_cut") if len(enters) else "not_entered"}
            deadline = activated + pd.DateOffset(months=S.SPEC["followup_months"]) if pd.notna(activated) else pd.NaT
            row["renewed_hike_after_activation_6m"] = (
                True if pd.notna(activated) and pd.notna(end) and end <= deadline else
                False if pd.notna(activated) and as_of >= deadline else np.nan)
            for horizon in S.SPEC["return_horizons_months"]:
                final = execution_date(ts(window.index[0] + pd.DateOffset(months=horizon), 16).tz_convert("UTC"), sessions)
                row[f"duration_excess_{horizon}m"] = excess(baseline_date, final)
                row[f"return_censored_{horizon}m"] = pd.isna(final)
            rows.append(row)
    return pd.DataFrame(rows)


def compute(out, hashes, history, pauses, actions, sessions, inputs, cycle_table):
    S.verify(out, hashes)
    wealth = {name: P.align_wealth(values, sessions) for name, values in P.market_wealth(inputs).items()}
    bill = Treasury._bill(inputs["bills"], sessions)
    as_of = ts(sessions[-1], 16).tz_convert("UTC")
    followups = followup(pauses, history, as_of)
    daily, summary, per_cycle, groups = strategies(actions, sessions, wealth, bill, cycle_table)
    paired, inference = cycle_comparison(per_cycle)
    diagnostics = pause_results(pauses, followups, actions, sessions, wealth, bill, as_of)
    return {"pause_followup": followups, "strategy_daily": daily, "performance": summary,
            "per_cycle_performance": per_cycle, "paired_cycle_differences": paired,
            "cycle_uncertainty": inference, "pause_diagnostics": diagnostics, "inflation_description": groups}
