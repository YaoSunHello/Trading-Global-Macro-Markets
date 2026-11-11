# Inflation-state detection: methodology and hypotheses

Code: `research/inflation_states/` (shared helpers: `research/data.py`, `calendar_pit.py`, `targets.py`, `stats.py`). The earlier factor-vs-Treasury-return forecasting work has been removed.
Outputs: `results/inflation_states/` (CSVs, `figures/`, `FINDINGS.md`). Run: `PYTHONPATH=src python3 -m research.inflation_states` then `python3 -m research.inflation_states.report`.

## 1. Purpose: three questions, kept apart

1. **Measurement.** What inflation level (low / normal / high) and momentum (falling / stable / rising) does the data available *at the decision date* indicate?
2. **Detection quality.** How stable, reproducible and revision-robust is that classification? There is no observed "true regime", so a label can never be scored for accuracy against the indicator that defines it.
3. **Economic relevance.** Do Treasury outcomes *after* detection differ across states? This is tested separately and never used to choose definitions.

The earlier factor-to-return regressions were an extension of section 5.1 and have been removed.

## 2. Source: section 5.1 and what was extended

Section 5.1 ("A treasure to behold") makes these empirical claims relevant here: US Treasury drawdowns deeper than 5% (Table 5.1, excess of 3m T-bills) are mostly associated with Fed hiking cycles; only the 1977-81 and 2020-23 drawdowns exceeded 10% and both coincided with very high inflation; without a major inflation problem drawdowns were about 10% or less; in real terms Treasuries are exposed to unexpected inflation, and excess returns over T-bills are closer to real returns. Everything about inflation *level/momentum states*, detection stability, revision sensitivity and real-time identifiability is a **research extension**: the book does not define or test such states.

## 3. Hypotheses (declared in `spec.py` before any analysis; frozen and hashed)

| id | source | question | statement | measurable | supported if | cannot establish |
|---|---|---|---|---|---|---|
| B1 | §5.1 (book) | economic | The deep Treasury drawdowns (Table 5.1) are associated with Fed tightening cycles. | Share of >5% drawdown episodes whose peak decision date is in the 'tightening' Fed state, vs the unconditional share of tightening months. | Share of drawdown peaks in tightening materially exceeds the unconditional tightening share, in every sub-sample with >=3 episodes. | Causality; the book's index (1973+) is not available, so episodes come from a model-estimated 8y par bond (1962+) and the IEF ETF proxy. |
| B2 | §5.1 (book) | economic | The two drawdowns deeper than 10% (1977-81, 2020-23) coincided with very high inflation; without a major inflation problem drawdowns were ~10% or less. | Inflation level / momentum state (point-in-time) at peak and during deep (> 10%) vs shallow drawdowns. | Deep drawdown episodes start/run in 'high' level states, and shallow ones do not. | Only a handful of independent episodes exist; no inferential test is meaningful. |
| B3 | §5.1 (book) | economic | High-and-rising inflation during tightening is where Treasuries are hurt; high-but-falling inflation during easing is not. | Forward excess return, downside frequency and forward 12m drawdown in (high, rising, tightening) vs (high, falling, easing). | Block-bootstrap CI of the mean difference excludes 0 in the book's direction and survives leave-one-episode-out. | Whether the states can be traded; no signals are generated in this study. |
| B4 | §5.1 (book) | out_of_scope | Ex-post real returns depend on starting real yields (Fig 5.1); fair-value 10Y real yield ~ potential growth (Fig 5.2). | Not tested here. | n/a | n/a |
| M1 | research extension | measurement | Inflation level (low/normal/high) and momentum (falling/stable/rising) can be assigned from real-time ALFRED CPI vintages. | Coverage: share of decision dates with a defined state, per measure, within the vintage-verified window; release-to-decision lag. | Coverage >= 95% of decision dates in the primary window and release_ts <= decision_ts for every row. | That the state is 'correct': no observed true regime exists. |
| D1 | research extension | detection | Headline and core CPI give consistent level and momentum classifications. | Weighted Cohen's kappa and raw agreement, headline vs core (1997+), stationary block-bootstrap CI. | Lower 95% CI bound of weighted kappa >= 0.60 for the level rule. | Accuracy; two noisy measures can agree and both be wrong. |
| D2 | research extension | detection | Level/momentum labels are robust to reasonable rule definitions. | Pairwise weighted kappa between L1-L3 and between M1-M4 (headline, core). | Median pairwise kappa >= 0.60 with CI. | Truth; rules built on the same index share error. |
| D3 | research extension | detection | Real-time labels are rarely changed by later revisions. | Share of decision dates whose real-time label differs from the label for the same month under latest-revised data. | Upper 95% CI bound of the flip share <= 5% for the level rule and <= 10% for momentum. | Stability of future, differently-revised data (e.g. the 2013/2019 CPI methodology changes are in the sample but rare). |
| D4 | research extension | detection | Raw momentum labels switch too often; persistence rules reduce short-lived reversals at an acceptable delay cost. | Transitions/year, share of spells <= 2 months, reversals within 3 months, and detection delay vs ex-post turning points, per persistence rule. | confirm2/hyst cut short spells by >= 50% with a median added delay <= 3 months. | Which rule is 'best': the delay reference is ex-post and itself a modelling choice. |
| D5 | research extension | detection | Momentum turns are detected within a useful delay. | Months from ex-post zigzag turning point (retrospective, latest-revised YoY) to the first matching momentum switch. | Median delay <= 6 months and >= 75% of turning points detected within 18 months. | Timeliness only - not accuracy; the reference is ex-post. |
| R1 | research extension | robustness | Detection properties are stable across calibration scheme, sample start and inflation episodes. | State shares, transition rates and agreement metrics by calibration, sample start and leaving out each declared episode. | Metrics change by less than the bootstrap half-width when any one episode is removed. | Out-of-regime behaviour: only ~6 distinct episodes exist. |
| E1 | research extension | economic | Forward 3m Treasury excess returns are lower after high-inflation level states than otherwise. | Mean forward 3m excess return (SYN8Y), high vs not-high, headline L1; block-bootstrap CI. | CI excludes 0, sign negative, Holm-adjusted p < 0.05. | Predictability net of costs; a tradable edge. |
| E2 | research extension | economic | Forward 3m Treasury excess returns are lower after 'rising' than after 'falling' momentum states. | Mean difference rising - falling, headline M1. | As E1. | As E1. |
| E3 | research extension | economic | Forward 3m excess returns differ between low and high level states. | Mean difference low - high, headline L1. | As E1. | As E1. |
| E4 | research extension | economic | High-and-rising inflation during tightening has worse forward 3m excess returns than high-but-falling inflation during easing. | Mean difference (high,rising,tightening) - (high,falling,easing). | As E1 and each cell has >=12 months and >=3 spells. | As E1. |
| E5 | research extension | economic | The E1-E4 contrasts also hold for core CPI, other rules, other horizons (1m, 12m) and the IEF proxy. | All other contrast x measure x rule x target x horizon combinations (exploratory; Benjamini-Hochberg, total count disclosed). | Consistent sign and CI exclusion across most combinations after BH. | Confirmatory evidence. |

## 4. Point-in-time conventions

* **Three dates are never conflated:** the *observation month* a CPI value describes; its *vintage/release date* (ALFRED `realtime_start`; release assumed 08:30 ET, vintage dates are day-granular); and the *decision timestamp* (16:00 ET close of the last bond-market session of the month). A month-end decision therefore describes the previous month. A state is never back-dated before its release.
* **As-of snapshot per decision.** For each decision date the vintage of the CPI series known on that date is rebuilt from the stored versions (rows with availability <= decision date); all measures and thresholds are computed on that snapshot only.
* **Primary window = defensible vintage coverage.** Headline CPI: first genuine release vintage 1972-07-21. Core CPI: 1996-12-12 (earlier observations are archive back-fill). Decisions before those dates are excluded. `vintage_coverage_audit.csv` documents the evidence (first-appearance lag of every observation).
* **Short early vintages.** Before 1994-02 each headline vintage holds only about 19 monthly observations, enough for YoY/momentum and fixed thresholds but not for a historical distribution; percentile rules are therefore undefined before 1994-02 rather than back-filled with revised data.
* **Latest-revised data** is used only for the revision comparison, the ex-post turning-point reference and plots, and is always labelled RETROSPECTIVE.
* **CPI is not the Fed's target.** The Fed targets PCE inflation; CPI differs in weights, formula and revision behaviour and has run roughly 0.3-0.5pp above PCE. Fixed thresholds are set with that wedge in mind. PCE was not tested.
* **Fed policy state** uses the effective fed funds rate (FEDFUNDS). ALFRED coverage starts 1996-12; before 1996-10 availability is assumed to be the day after month end (flagged per row).

## 5. Definitions (no definition was chosen on Treasury performance)

Level (YoY CPI, %):

| rule | definition | hysteresis margin (pp) |
|---|---|---|
| `L1_FIXED` | YoY CPI %: low < 1.5, high >= 3.5, else normal (fixed, economically motivated; CPI != PCE) | 0.25 |
| `L2_EXP_PCTL` | YoY relative to its own expanding past-only distribution: <= 25th pct low, >= 75th pct high | 0.25 |
| `L3_ROLL10Y_PCTL` | YoY relative to the trailing 120-month past-only distribution (25th/75th pct) | 0.25 |

Momentum (percentage points; neutral band closed, so |x| <= band is "stable"):

| rule | definition | band | hysteresis margin (pp) |
|---|---|---|---|
| `M1_DYOY_3M` | Change in YoY inflation over 3 months; neutral band +/-0.30pp (index rounding + seasonal-revision noise scale) | ±0.3pp | 0.15 |
| `M2_DYOY_6M` | Change in YoY inflation over 6 months; neutral band +/-0.50pp | ±0.5pp | 0.25 |
| `M3_ANN6M_VS_YOY` | 6-month annualised SA inflation minus YoY (recent pace vs trailing year); neutral band +/-0.50pp | ±0.5pp | 0.25 |
| `M4_ANN3M_VS_YOY` | 3-month annualised SA inflation minus YoY; neutral band +/-1.00pp (noisier horizon, wider band) | ±1.0pp | 0.5 |

Percentile thresholds use YoY values of months *strictly before* the observation month, taken from the same vintage; they are undefined with fewer than 120 months of history. Fixed thresholds and bands are declared constants, not estimated.

Persistence variants: `raw` (baseline); `confirm2` (adopt a new state after two consecutive monthly observations); `hyst` (Schmitt trigger with the margins above).

**Confidence is separate from the label.** For every row the history file reports the signed distance of the measure from the boundary of the reported state (`margin`), the same distance in units of a past-only 90th-percentile revision scale (`margin_in_rev_units`, tier high >= 3, medium >= 1, low >= 0, contested < 0), the state's age, and the share of other raw rules that agree. These are deterministic descriptions, not probabilities.

**Fed state:** tightening if fed funds rose by >= 0.50pp over the last 6 completed months, easing if it fell by >= 0.50pp, else hold (sensitivity: 3/12-month windows and 25bp band are declared in `spec.py`).

## 6. Detection-quality evaluation (what each metric can and cannot show)

| metric | useful evidence | cannot establish |
|---|---|---|
| coverage / release-before-decision | state defined and observable in real time | correctness |
| headline vs core agreement (weighted kappa, block-bootstrap CI) | consistency across measures | accuracy; both can be wrong |
| agreement across definitions | sensitivity to rule choice | truth; shared index error |
| real-time vs latest-revised label flips | revision robustness | future revision regimes |
| spells, transitions/yr, short spells, reversals | stability | accuracy; a constant label is stable |
| delay vs ex-post turning points (zigzag 1.5pp on 3m-centred latest-revised YoY) + chance baseline | timeliness, false-alarm rate | accuracy; the reference is retrospective |
| sensitivity (thresholds, bands, lookbacks, smoothing, decision frequency) | dependence on choices | which choice is best |

Statistical inference uses the Politis-Romano stationary bootstrap (mean block 12 months; `max(12, 2h)` for h-month overlapping returns). No p-values are reported for differences created mechanically by the classification rule.

## 7. Robustness

Expanding vs rolling calibration (L2 vs L3; windows 60/120/180; expanding from full/1970/1985), alternative sample starts, six declared inflation episodes (`spec.EPISODES`, declared before analysis) with each excluded in turn, and an explicit count of independent spells versus monthly observations. All are retrospective. No model or parameter was selected, so no chronological validation split was needed; a **reserved window** (decisions from 2015-01) is reported separately but was visible to the author when rules were written, so it is *not* prospective. Decisions after the freeze date (`run_metadata.json`) are genuinely out of sample for the frozen definitions.

## 8. Economic relevance design

* **Targets.** `SYN8Y`: 8-year constant-maturity par bond from 5Y/10Y CMT yields, daily holding return (MODEL-ESTIMATED, 1962+). `IEF`: adjusted-close total return (OBSERVED ETF PROXY, 2002-07+). Excess = total return minus 3m T-bill accrual. Neither is the book's index.
* **Forward vs contemporaneous.** Forward outcomes (1, 3, 12 months) start at the close one session *after* the decision date. Trailing-3-month returns ending at the decision date are reported in a separate file and are descriptive only.
* **Statistics.** Mean excess return (annualised), standard deviation, share of negative periods, share below -1 sd, 5% expected shortfall, forward-12-month maximum drawdown (total-return wealth) and the share of forward windows with a drawdown beyond 5%. Cells with fewer than 12 months or 3 spells are flagged `sufficient=False` and not tested.
* **Drawdown episodes.** Peak-to-trough-to-recovery on total-return wealth; cash-relative wealth (wealth / T-bill wealth, as in the book's Table 5.1) is computed separately and labelled. Episodes are measured from 1973-01 to match the book's start.
* **Test families.** Primary: four declared contrasts (E1-E4; headline, L1/M1, SYN8Y, 3m) with Holm. Secondary: every other measure x rule x target x horizon contrast, Benjamini-Hochberg across the estimable set. Robustness re-runs are descriptive. Total search scope is in `search_scope.csv`.
* **Not done by design:** trading signals, position sizing, Sharpe optimisation.

## 9. Files

`inflation_state_inputs.csv` (input values and availability provenance per decision x measure), `inflation_state_history.csv` (state, label, margin, tier, age, agreement per decision x measure x rule x persistence), `detection_*.csv`, `sensitivity_*.csv`, `robustness_*.csv`, `conditional_outcomes_*.csv`, `economic_contrasts*.csv`, `drawdown_*.csv`, `section_5_1_claims_check.csv`, `hypothesis_scorecard.csv`, `spec_frozen.json`, `run_metadata.json`, `FINDINGS.md`, `figures/`.

## 10. Tests (`tests/test_inflation_states.py`)

Release-date alignment (a decision never sees an unreleased month; release 08:30 precedes the 16:00 decision), vintage handling (a revision changes inputs only after its vintage date; first-release timestamp is the earliest version), no-leakage (wrecking every value released after a decision leaves that row and all states unchanged; a real-database test rebuilds a row from only the data that existed that day), past-only thresholds, undefined percentile rules on short vintages, rule boundaries, hysteresis/confirmation, statistics helpers, forward-vs-contemporaneous window alignment, drawdown definitions, cash-relative vs total-return wealth, fed-state availability, and frozen-spec enforcement.
