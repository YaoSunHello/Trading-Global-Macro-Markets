import numpy as np
import pandas as pd

from .. import targets as T
from ..calendar_pit import Calendar
from ..data import ts
from ..inflation_states.outcomes import Treasury
from . import spec as S
from .states import panel


def synthetic_wealth(yield_pct, maturity):
    y = yield_pct.dropna().sort_index()
    if not y.index.is_unique or len(y) < 2:
        raise ValueError("Synthetic target needs unique dates and at least two yields")
    days = y.index.to_series().diff().dt.days.iloc[1:].to_numpy() / 365
    r = T.par_bond_return(y.to_numpy()[:-1] / 100, y.to_numpy()[1:] / 100, maturity, days)
    return pd.Series(np.r_[1.0, np.cumprod(1 + r)], index=y.index)


def market_wealth(inputs):
    y8 = T.interp_cmt(inputs["y5"], inputs["y10"], 8.0).dropna()
    return {"SYN2Y": synthetic_wealth(inputs["y2"], 2.0), "SYN8Y": synthetic_wealth(y8, 8.0)}


def align_wealth(w, sessions):
    frame = pd.DataFrame({"date": w.index, "wealth": w.values})
    aligned = pd.merge_asof(pd.DataFrame({"session": sessions}), frame, left_on="session", right_on="date",
                            tolerance=pd.Timedelta(days=5), direction="backward")
    return pd.Series(aligned.wealth.to_numpy(), index=sessions)


def return_between(w, start, end):
    if pd.isna(start) or pd.isna(end) or start not in w.index or end not in w.index:
        return np.nan
    values = w.loc[start:end]
    if values.isna().any() or len(values) < 2:
        return np.nan
    return float(values.iloc[-1] / values.iloc[0] - 1)


def forward_grid(history, cycle_table, sessions, wealth, bill):
    cal = Calendar(sessions, lag=S.SPEC["execution_lag_sessions"])
    decisions = cal.formation[cal.formation >= S.SPEC["start"]]
    grid = panel(history, decisions)
    execution = pd.Series(cal.exec_dates, index=cal.formation)
    grid["execution_date"] = execution.reindex(decisions)
    end_by_cycle = cycle_table.set_index("cycle_id").end_known_at
    for h in S.SPEC["horizons_months"]:
        ending = execution.shift(-h).reindex(decisions)
        grid[f"end_{h}m"] = ending
        within = []
        for f, e in ending.items():
            cycle_id = grid.loc[f, "cycle_id"]
            boundary = end_by_cycle.get(cycle_id, pd.NaT)
            within.append(pd.notna(e) and (pd.isna(boundary) or ts(e, 16).tz_convert("UTC") < boundary))
        grid[f"within_cycle_{h}m"] = within
        for target, w in wealth.items():
            excess = []
            for f in decisions:
                start, end = grid.loc[f, "execution_date"], ending.loc[f]
                excess.append(return_between(w, start, end) - return_between(bill, start, end))
            grid[f"{target}_{h}m_excess"] = excess
    return grid


def cycle_interval(g, cycle_table):
    complete = set(cycle_table.loc[cycle_table.complete, "cycle_id"])
    observed = g[g.cycle_id.isin(complete)]
    means = observed.groupby("cycle_id").excess.mean().dropna()
    eligible = len(means) >= S.SPEC["inference"]["min_complete_cycles"] and len(observed) >= S.SPEC["inference"]["min_months"]
    if not eligible:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(S.SPEC["inference"]["seed"])
    dist = rng.choice(means.to_numpy(), size=(S.SPEC["inference"]["bootstrap_reps"], len(means)), replace=True).mean(axis=1)
    return float(means.mean()), float(np.quantile(dist, 0.025)), float(np.quantile(dist, 0.975))


def conditional_tables(grid, cycle_table):
    rows, per = [], []
    complete = set(cycle_table.loc[cycle_table.complete, "cycle_id"])
    for target in S.SPEC["targets"]:
        for h in S.SPEC["horizons_months"]:
            d = grid.reset_index().rename(columns={f"{target}_{h}m_excess": "excess"}).dropna(subset=["excess"])
            for sample in ["all", "design", "reserved"]:
                subset = d if sample == "all" else d[d["sample"] == sample]
                for state in S.SPEC["states"]:
                    g = subset[subset.state == state]
                    eligible_g = g[g[f"within_cycle_{h}m"]]
                    estimate, lo, hi = cycle_interval(eligible_g, cycle_table)
                    rows.append({"target": target, "horizon_months": h, "sample": sample, "state": state,
                                 "months": len(g), "cycles": g.cycle_id.nunique(),
                                 "complete_cycles": len(set(g.cycle_id.dropna()) & complete),
                                 "mean_excess": g.excess.mean(), "median_excess": g.excess.median(),
                                 "cycle_equal_weight_mean": estimate, "cycle_ci_low": lo, "cycle_ci_high": hi,
                                 "inference": "cycle-bootstrap interval" if pd.notna(lo) else "descriptive only",
                                 "cross_cycle_windows": int((~g[f"within_cycle_{h}m"]).sum())})
            for (cycle, state), g in d.dropna(subset=["cycle_id"]).groupby(["cycle_id", "state"]):
                per.append({"target": target, "horizon_months": h, "cycle_id": cycle, "state": state,
                            "sample": g["sample"].iloc[0], "complete": cycle in complete,
                            "months": len(g), "mean_excess": g.excess.mean(),
                            "cross_cycle_windows": int((~g[f"within_cycle_{h}m"]).sum())})
    return pd.DataFrame(rows), pd.DataFrame(per)


def allocation_returns(duration_returns, bill_returns, duration_weights, cost=0.0005):
    """Each row is an execution-close -> next-close interval; trade costs precede that interval's return."""
    d = pd.concat([duration_returns, bill_returns, duration_weights], axis=1, keys=["duration", "bills", "weight"])
    d["turnover"] = d.weight.diff().abs()
    if len(d):
        d.iloc[0, d.columns.get_loc("turnover")] = abs(d.weight.iloc[0])
    d["cost"] = cost * d.turnover
    d["gross"] = d.weight * d.duration + (1 - d.weight) * d.bills
    d["net"] = (1 - d.cost) * (1 + d.gross) - 1
    return d


def strategy(history, cycle_table, sessions, wealth, bill):
    states = panel(history, sessions)
    # State observable at yesterday's close executes at today's close.
    weight = states.state.map(S.SPEC["duration_weights"]).shift(S.SPEC["execution_lag_sessions"]).fillna(0)
    target = wealth[S.SPEC["allocation_target"]]
    dr = target.shift(-1) / target - 1
    br = bill.shift(-1) / bill - 1
    daily = allocation_returns(dr, br, weight, S.SPEC["cost_per_duration_notional"])
    bh = allocation_returns(dr, br, pd.Series(1.0, index=sessions), S.SPEC["cost_per_duration_notional"])
    daily["duration_buy_hold"] = bh.net
    daily["bills_benchmark"] = br
    daily["decision_state"] = states.state
    daily["executed_state"] = states.state.shift(S.SPEC["execution_lag_sessions"]).fillna("unknown")
    daily["cycle_id"] = states.cycle_id
    daily["sample"] = states["sample"]
    daily["zlb"] = states.zlb
    daily["end_session"] = pd.Series(sessions, index=sessions).shift(-1)
    daily = daily.iloc[:-1]
    if daily[["net", "duration_buy_hold", "bills_benchmark"]].isna().any().any():
        raise RuntimeError("Missing strategy returns; refusing to silently bridge data gaps")
    rows = []
    for name in ["net", "duration_buy_hold", "bills_benchmark"]:
        for group, g in [("all", daily), ("design", daily[daily["sample"] == "design"]),
                         ("reserved", daily[daily["sample"] == "reserved"])]:
            if not len(g):
                continue
            w = pd.Series(np.r_[1.0, np.cumprod(1 + g[name].to_numpy())])
            days = (g.end_session.iloc[-1] - g.index[0]).days
            rows.append({"strategy": name, "sample": group, "sessions": len(g), "start": g.index[0], "end": g.end_session.iloc[-1],
                         "total_return": w.iloc[-1] - 1, "annualized_return": w.iloc[-1] ** (365 / days) - 1,
                         "max_drawdown": (w / w.cummax() - 1).min(),
                         "duration_turnover": g.turnover.sum() if name == "net" else (1.0 if name == "duration_buy_hold" and group == "all" else 0.0),
                         "cost_sum": g.cost.sum() if name == "net" else (S.SPEC["cost_per_duration_notional"] if name == "duration_buy_hold" and group == "all" else 0)})
    per = []
    for cycle, g in daily.dropna(subset=["cycle_id"]).groupby("cycle_id"):
        for name in ["net", "duration_buy_hold", "bills_benchmark"]:
            per.append({"cycle_id": cycle, "sample": g["sample"].iloc[0], "strategy": name,
                        "sessions": len(g), "total_return": (1 + g[name]).prod() - 1})
    return daily, pd.DataFrame(rows), pd.DataFrame(per)


def inflation_comparison(grid, cycle_table):
    rule = S.SPEC["inflation_comparison"]
    d = grid[(grid.state == rule["state"]) & grid.inflation_group.notna()].copy()
    d["excess"] = d[f'{rule["target"]}_{rule["horizon_months"]}m_excess']
    d = d.dropna(subset=["excess"])
    complete = set(cycle_table.loc[cycle_table.complete, "cycle_id"])
    counts = []
    for label in rule["groups"]:
        g = d[d.inflation_group == label]
        counts.append({"group": label, "months": len(g), "cycles": g.cycle_id.nunique(),
                       "complete_cycles": len(set(g.cycle_id.dropna()) & complete), "mean_excess": g.excess.mean()})
    counts = pd.DataFrame(counts)
    supported = (counts.months >= rule["min_months_each"]).all() and (
        counts.complete_cycles >= rule["min_complete_cycles_each"]).all()
    result = {"comparison": "high-and-rising minus other known inflation within hold-after-hiking",
              "target": rule["target"], "horizon_months": rule["horizon_months"],
              "status": "descriptive comparison" if supported else "insufficient evidence",
              "difference": counts.mean_excess.iloc[0] - counts.mean_excess.iloc[1] if supported else None,
              "inference": "none; no additional comparisons or tuning"}
    return counts, result


def compute(out, input_hashes, inputs, history, cycle_table, sessions, inflation):
    S.verify(out, input_hashes)
    wealth = {name: align_wealth(w, sessions) for name, w in market_wealth(inputs).items()}
    bill = Treasury._bill(inputs["bills"], sessions)
    grid = forward_grid(history, cycle_table, sessions, wealth, bill).join(inflation)
    conditional, per_cycle = conditional_tables(grid, cycle_table)
    daily, performance, per_cycle_strategy = strategy(history, cycle_table, sessions, wealth, bill)
    inflation_counts, comparison = inflation_comparison(grid, cycle_table)
    return {"outcome_grid": grid.reset_index(), "conditional_returns": conditional,
            "per_cycle_returns": per_cycle, "strategy_daily": daily.reset_index(names="execution_date"),
            "strategy_performance": performance, "per_cycle_strategy": per_cycle_strategy,
            "inflation_comparison_counts": inflation_counts}, comparison
