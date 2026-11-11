"""Figures (PNG). All plotted values come from the stage-1/2 objects; real-time series are labelled as such and the
latest-revised (retrospective) series is always drawn as a thin reference line."""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

from . import classify as C, spec as S

COL = {-1: "#4C78A8", 0: "#D9D9D9", 1: "#E45756"}
FED_COL = {"tightening": "#E45756", "hold": "#D9D9D9", "easing": "#54A24B", "unknown": "#FFFFFF"}


def _shade(ax, st: pd.Series, alpha=0.25):
    s = st.dropna()
    if s.empty:
        return
    start, cur = s.index[0], s.iloc[0]
    idx = list(s.index)
    for i in range(1, len(idx) + 1):
        if i == len(idx) or s.iloc[i] != cur:
            ax.axvspan(start, idx[i - 1] + pd.Timedelta(days=20), color=COL[int(cur)], alpha=alpha, lw=0)
            if i < len(idx):
                start, cur = idx[i], s.iloc[i]


def fig_levels(ms, out):
    fig, axs = plt.subplots(2, 1, figsize=(12, 7), sharex=False)
    for ax, (name, m) in zip(axs, ms.items()):
        p = m.panel
        _shade(ax, m.state("level", "L1_FIXED"))
        ax.plot(p["obs_month"], p["yoy"], color="k", lw=1.2, label="real-time YoY (as known at each decision)")
        ax.plot(m.retro.index[m.retro.index >= p["obs_month"].min()], m.retro["yoy"][m.retro.index >= p["obs_month"].min()], color="#7B3294", lw=0.7,
                label="latest-revised YoY (RETROSPECTIVE reference)")
        ax.axhline(1.5, color="#4C78A8", ls="--", lw=.8); ax.axhline(3.5, color="#E45756", ls="--", lw=.8)
        ax.set_title(f"{name} CPI inflation level, L1 fixed thresholds (low<1.5, high>=3.5)  |  shading = real-time state at each decision")
        ax.set_ylabel("YoY %"); ax.grid(alpha=.3)
        ax.legend(handles=[Patch(color=COL[-1], alpha=.4, label="low"), Patch(color=COL[0], alpha=.6, label="normal"), Patch(color=COL[1], alpha=.4, label="high")] +
                  ax.get_legend_handles_labels()[0], ncol=5, fontsize=8, loc="upper right")
    fig.tight_layout(); fig.savefig(out / "fig1_inflation_levels.png", dpi=130); plt.close(fig)


def fig_momentum(ms, out):
    fig, axs = plt.subplots(2, 1, figsize=(12, 7))
    for ax, (name, m) in zip(axs, ms.items()):
        p = m.panel
        _shade(ax, m.state("momentum", "M1_DYOY_3M"))
        ax.plot(p["obs_month"], p["dyoy3"], color="k", lw=1, label="real-time change in YoY over 3m")
        ax.plot(m.retro.index[m.retro.index >= p["obs_month"].min()], m.retro["dyoy3"][m.retro.index >= p["obs_month"].min()], color="#7B3294", lw=.6,
                label="latest-revised (RETROSPECTIVE)")
        b = S.MOMENTUM_RULES["M1_DYOY_3M"]["band"]
        ax.axhline(b, color="#E45756", ls="--", lw=.8); ax.axhline(-b, color="#4C78A8", ls="--", lw=.8); ax.axhline(0, color="k", lw=.4)
        ax.set_title(f"{name} CPI inflation momentum, M1: change in YoY over 3 months, neutral band ±{b}pp  |  shading = real-time state")
        ax.set_ylabel("pp"); ax.grid(alpha=.3)
        ax.legend(handles=[Patch(color=COL[-1], alpha=.4, label="falling"), Patch(color=COL[0], alpha=.6, label="stable"), Patch(color=COL[1], alpha=.4, label="rising")] +
                  ax.get_legend_handles_labels()[0], ncol=5, fontsize=8, loc="upper right")
    fig.tight_layout(); fig.savefig(out / "fig2_inflation_momentum.png", dpi=130); plt.close(fig)


def fig_transitions(ms, out):
    fig, axs = plt.subplots(2, 1, figsize=(13, 9), gridspec_kw=dict(height_ratios=[1, 0.9]))
    cmap = ListedColormap([COL[-1], COL[0], COL[1]])
    rows_def = [("level", r, "raw") for r in S.LEVEL_RULES] + [("level", "L1_FIXED", "confirm2"), ("level", "L1_FIXED", "hyst")] + \
               [("momentum", r, "raw") for r in S.MOMENTUM_RULES] + [("momentum", "M1_DYOY_3M", "confirm2"), ("momentum", "M1_DYOY_3M", "hyst")]
    for ax, (name, m) in zip(axs, ms.items()):
        idx = m.panel.index
        Z = np.vstack([m.state(k, r, p).reindex(idx).values for k, r, p in rows_def])
        ax.imshow(np.where(np.isnan(Z), np.nan, Z), aspect="auto", cmap=cmap, vmin=-1, vmax=1, interpolation="nearest",
                  extent=[mdates.date2num(idx[0]), mdates.date2num(idx[-1]), len(rows_def), 0])
        ax.xaxis_date(); ax.set_yticks(np.arange(len(rows_def)) + .5)
        ax.set_yticklabels([f"{r}{'' if p == 'raw' else ' / ' + p}" for k, r, p in rows_def], fontsize=8)
        ax.set_title(f"{name}: real-time state of every declared rule (blue = low/falling, grey = normal/stable, red = high/rising; blank = undefined)")
        ax.axhline(len(S.LEVEL_RULES) + 2, color="k", lw=1)
    fig.tight_layout(); fig.savefig(out / "fig3_state_transitions.png", dpi=130); plt.close(fig)


def fig_revisions(ms, out, flips: pd.DataFrame):
    fig, axs = plt.subplots(2, 1, figsize=(12, 8))
    m = ms["HEADLINE"]; p = m.panel
    rev = (p["yoy"].values - m.retro["yoy"].reindex(p["obs_month"]).values)
    axs[0].bar(p["obs_month"], rev, width=25, color="#7B3294")
    rr = m.retro_state_at_decisions("level", "L1_FIXED")
    fl = (m.state("level", "L1_FIXED") != rr) & rr.notna()
    axs[0].scatter(p.loc[fl, "obs_month"], np.full(int(fl.sum()), rev.max() * 1.05), marker="v", color="#E45756", label="L1 level label differs from latest-revised label")
    axs[0].set_title("HEADLINE: real-time YoY minus latest-revised YoY for the same month (percentage points)"); axs[0].legend(); axs[0].grid(alpha=.3)
    f = flips[flips.persistence == "raw"].copy()
    f["lab"] = f.measure.str[:4] + " " + f.rule_id.str.replace("_", " ", n=1).str.split().str[0]
    f = f.sort_values(["measure", "rule_id"], ascending=[True, True])
    y = np.arange(len(f))
    axs[1].barh(y, f.flip_share * 100, color=["#4C78A8" if k == "level" else "#E45756" for k in f.rule_kind])
    axs[1].errorbar(f.flip_share * 100, y, xerr=[(f.flip_share - f.flip_lo) * 100, (f.flip_hi - f.flip_share) * 100], fmt="none", ecolor="k", lw=1)
    axs[1].set_yticks(y); axs[1].set_yticklabels(f.measure.str[:4] + " " + f.rule_id, fontsize=8)
    axs[1].set_xlabel("% of decisions whose real-time label differs from the latest-revised label (95% block-bootstrap CI); blue = level, red = momentum")
    axs[1].grid(alpha=.3, axis="x")
    fig.tight_layout(); fig.savefig(out / "fig4_revision_disagreement.png", dpi=130); plt.close(fig)


def fig_sensitivity(sens, out):
    th = sens["sensitivity_level_thresholds"]
    fig, axs = plt.subplots(2, 3, figsize=(14, 8))
    for r, name in enumerate(["HEADLINE", "CORE"]):
        d = th[th.measure == name]
        for c, (col, ttl, fmt) in enumerate([("share_high", "share of time 'high'", "{:.0%}"), ("transitions_per_year", "transitions / year", "{:.2f}"),
                                             ("weighted_kappa_vs_reference", "weighted kappa vs declared (1.5 / 3.5)", "{:.2f}")]):
            pv = d.pivot(index="low", columns="high", values=col)
            ax = axs[r, c]
            im = ax.imshow(pv.values, cmap="viridis", aspect="auto")
            ax.set_xticks(range(len(pv.columns))); ax.set_xticklabels(pv.columns); ax.set_yticks(range(len(pv.index))); ax.set_yticklabels(pv.index)
            for i in range(pv.shape[0]):
                for j in range(pv.shape[1]):
                    ax.text(j, i, fmt.format(pv.values[i, j]), ha="center", va="center", color="w", fontsize=9)
            ax.set_title(f"{name}: {ttl}", fontsize=9); ax.set_xlabel("high threshold (%)"); ax.set_ylabel("low threshold (%)")
    fig.tight_layout(); fig.savefig(out / "fig5a_threshold_sensitivity_level.png", dpi=130); plt.close(fig)
    mm = sens["sensitivity_momentum_bands"]
    fig, axs = plt.subplots(1, 2, figsize=(13, 4.5))
    for ax, name in zip(axs, ["HEADLINE", "CORE"]):
        for rid, g in mm[(mm.measure == name) & (mm.persistence == "raw")].groupby("rule_id"):
            ax.plot(g.band_multiple, g.transitions_per_year, marker="o", label=rid)
        ax.set_title(f"{name}: momentum transitions/yr vs neutral-band multiple (raw)"); ax.set_xlabel("band multiple of declared band"); ax.grid(alpha=.3); ax.legend(fontsize=7)
    fig.tight_layout(); fig.savefig(out / "fig5b_threshold_sensitivity_momentum.png", dpi=130); plt.close(fig)


def fig_episodes(ms, grid, out):
    H = ms["HEADLINE"]
    fig, axs = plt.subplots(1, 3, figsize=(16, 5))
    labs = [e[0] for e in S.EPISODES]
    short = [e[0].split("_")[0] for e in S.EPISODES]
    L = H.state("level", "L1_FIXED")
    share = {k: [] for k in (-1, 0, 1)}
    means = {k: [] for k in (-1, 0, 1)}
    ns = {k: [] for k in (-1, 0, 1)}
    for eid, s0, s1 in S.EPISODES:
        mk = (L.index >= s0) & (L.index <= s1)
        x = L[mk].dropna()
        for k in (-1, 0, 1):
            share[k].append((x == k).mean() if len(x) else np.nan)
            y = grid.loc[x.index[x == k], "fwd_SYN8Y_3"].dropna() if (x == k).any() else pd.Series(dtype=float)
            means[k].append(y.mean() * 4 if len(y) >= 6 else np.nan)
            ns[k].append(len(y))
    bot = np.zeros(len(labs))
    for k, nm in ((-1, "low"), (0, "normal"), (1, "high")):
        axs[0].bar(short, share[k], bottom=bot, color=COL[k], label=nm); bot += np.nan_to_num(share[k])
    axs[0].set_title("HEADLINE L1: share of decisions by state, per episode"); axs[0].legend()
    wd = 0.27
    for i, k in enumerate((-1, 0, 1)):
        axs[1].bar(np.arange(len(labs)) + (i - 1) * wd, np.array(means[k]) * 100, width=wd, color=COL[k], edgecolor="k", lw=.4)
    axs[1].set_xticks(range(len(labs))); axs[1].set_xticklabels(short)
    axs[1].axhline(0, color="k", lw=.5)
    axs[1].set_title("Mean forward 3m excess return (SYN8Y, annualised %), by L1 state within episode\n(cells with < 6 months omitted; episodes are not independent of each other)", fontsize=9)
    M1 = H.state("momentum", "M1_DYOY_3M")
    for i, k in enumerate((-1, 0, 1)):
        v = []
        for eid, s0, s1 in S.EPISODES:
            x = M1[(M1.index >= s0) & (M1.index <= s1)].dropna()
            y = grid.loc[x.index[x == k], "fwd_SYN8Y_3"].dropna() if (x == k).any() else pd.Series(dtype=float)
            v.append(y.mean() * 400 if len(y) >= 6 else np.nan)
        axs[2].bar(np.arange(len(labs)) + (i - 1) * wd, v, width=wd, color=COL[k], edgecolor="k", lw=.4)
    axs[2].set_xticks(range(len(labs))); axs[2].set_xticklabels(short); axs[2].axhline(0, color="k", lw=.5)
    axs[2].set_title("Mean forward 3m excess return (SYN8Y, annualised %), by M1 momentum state within episode", fontsize=9)
    fig.tight_layout(); fig.savefig(out / "fig6_episode_comparison.png", dpi=130); plt.close(fig)


def fig_drawdowns(ms, grid, tr, out):
    H = ms["HEADLINE"]
    W = (tr.wealth["SYN8Y"] / tr.bill["SYN8Y"])
    W = W[W.index >= "1973-01-01"]
    W = W / W.iloc[0]
    fig, axs = plt.subplots(3, 1, figsize=(13, 8), sharex=True, gridspec_kw=dict(height_ratios=[4, .5, .5]))
    axs[0].semilogy(W.index, W.values, color="k", lw=1)
    from .outcomes import drawdown_episodes
    for _, e in drawdown_episodes(W).iterrows():
        axs[0].axvspan(e.peak, e.trough, color="#E45756", alpha=.25, lw=0)
        axs[0].text(e.peak, W.max() * .98, f"{e.depth:.0%}", fontsize=7, rotation=90, va="top")
    axs[0].set_title("SYN8Y (model-estimated 8y par bond) CASH-RELATIVE wealth (wealth / T-bill wealth), rebased 1973-01; shaded = >5% drawdowns peak->trough")
    axs[0].grid(alpha=.3)
    def ribbon(ax, st, cmap, title):
        s = st.dropna()
        for d_, v in s.items():
            ax.axvspan(d_, d_ + pd.Timedelta(days=31), color=cmap[v], lw=0)
        ax.set_yticks([]); ax.set_ylabel(title, rotation=0, ha="right", va="center", fontsize=8)
    ribbon(axs[1], grid["fed_state"].reindex(grid.index), FED_COL, "Fed state")
    ribbon(axs[2], H.state("level", "L1_FIXED").reindex(grid.index).map({-1: "low", 0: "normal", 1: "high"}),
           {"low": COL[-1], "normal": COL[0], "high": COL[1]}, "HEADLINE L1")
    axs[2].set_xlim(W.index[0], W.index[-1])
    fig.tight_layout(); fig.savefig(out / "fig7_drawdowns_and_states.png", dpi=130); plt.close(fig)


def fig_contrasts(T_, R_, out):
    p = T_[T_.family == "E_primary"]
    r = R_[R_.contrast_id.isin(["E1_high_vs_notHigh", "E2_rising_vs_falling"])]
    fig, axs = plt.subplots(1, 2, figsize=(14, 5))
    ax = axs[0]
    y = np.arange(len(p))
    ax.errorbar(p.diff_annualised * 100, y, xerr=[(p.diff_annualised - p.ci_lo) * 100, (p.ci_hi - p.diff_annualised) * 100], fmt="o", color="k", capsize=3)
    ax.set_yticks(y); ax.set_yticklabels(p.contrast_id.str.replace("_", " "), fontsize=8); ax.axvline(0, color="grey", lw=.7)
    ax.set_xlabel("difference in mean forward 3m excess return, annualised % (95% stationary-bootstrap CI)")
    ax.set_title("Primary contrasts (HEADLINE, L1/M1, SYN8Y). Holm-adjusted p: " + ", ".join(f"{v:.2f}" for v in p.p_adjusted_holm_within_family), fontsize=9)
    ax.grid(alpha=.3)
    ax = axs[1]
    r = r[r.estimable].copy()
    r["lab"] = r.contrast_id.str[:2] + " " + r.robustness.str.replace("exclude_", "excl ").str.replace("sample_start_", "from ").str.replace("window_", "")
    r = r.reset_index(drop=True)
    y = np.arange(len(r))
    ax.errorbar(r.diff_annualised * 100, y, xerr=[(r.diff_annualised - r.ci_lo) * 100, (r.ci_hi - r.diff_annualised) * 100], fmt="o", ms=3, color="#4C78A8", capsize=2, lw=.8)
    ax.set_yticks(y); ax.set_yticklabels(r.lab, fontsize=6); ax.axvline(0, color="grey", lw=.7); ax.invert_yaxis()
    ax.set_title("Robustness of E1/E2 (windows, leave-one-episode-out,\nsample starts, persistence, target/horizon)", fontsize=9); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(out / "fig8_primary_contrasts.png", dpi=130); plt.close(fig)


def make_all(ms, grid, tr, T_, E_, cond, out: Path):
    out = Path(out) / "figures"
    out.mkdir(parents=True, exist_ok=True)
    from . import detection as D
    flips, _ = D.revision_tables(ms)
    fig_levels(ms, out); fig_momentum(ms, out); fig_transitions(ms, out); fig_revisions(ms, out, flips)
    fig_sensitivity(D.sensitivity_tables(ms), out); fig_episodes(ms, grid, out); fig_drawdowns(ms, grid, tr, out)
    R_ = pd.read_csv(Path(out).parent / "economic_contrasts_robustness.csv")
    fig_contrasts(T_, R_, out)
