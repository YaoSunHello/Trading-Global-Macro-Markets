# Inflation-state detection: findings

> Numbers and verdicts are computed from the CSVs on every run. The narrative sentences were written for the run below; if the data or definitions change, re-read them.

*Generated 2026-11-10 from `results/inflation_states/*.csv`. Definitions frozen at SHA-256 `e85e14573bf075bd` before any Treasury outcome was computed. Last decision 2026-10-30; last CPI observation 2026-09-01. Treasury series are an observed ETF proxy (IEF, 2002-07+) and a model-estimated 8y par bond (1962+); neither is the book's index.*

## 1. What was established

1. **Measurement.** Level and momentum states can be assigned in real time from ALFRED vintages: headline CPI from 1972-07-31, core CPI from 1996-12-31. Percentile-calibrated level rules exist only from 1994-02 (headline) because earlier ALFRED vintages are 19-month windows.
2. **Detection quality is mixed and should not be over-read.** Level labels from fixed thresholds are stable to revisions (headline: 1.7% of labels later differ, upper bound 2.8%) and slow-moving (1.25 transitions/yr). Momentum labels are noisy (headline M1 ~3.7 transitions/yr; 55% of spells last <= 2 months). A two-month confirmation rule removes most of that noise for about one extra month of delay.
3. **Headline and core disagree.** Weighted kappa for the level state is 0.29 (CI 0.03 to 0.50); it is 0.04 when the 2020-26 episode is excluded. Definitions also disagree with each other (section 4). A single 'inflation regime' label is therefore a modelling choice, not a measured fact.
4. **Economic relevance was not established.** No primary contrast survives correction (Holm-adjusted p 1.00, 1.00, 1.00, 1.00), and 0 of 83 exploratory contrasts survive BH. The conditional descriptions in section 6 are shown without inference; the bootstrap intervals are wide relative to the differences between cells.
5. **No trading signal, Sharpe optimisation or definition search was performed.** Rules were declared first, frozen and hashed, and no rule was chosen on Treasury outcomes.

## 2. Hypothesis scorecard

Verdicts apply the criteria declared in `spec.py`. 'Not supported' means the declared criterion was not met, not that the opposite was shown.

| id | source | hypothesis (declared before analysis) | declared support criterion | evidence | verdict |
|---|---|---|---|---|---|
| M1 | extension | Inflation level (low/normal/high) and momentum (falling/stable/rising) can be assigned from real-time ALFRED CPI vintages. | Coverage >= 95% of decision dates in the primary window and release_ts <= decision_ts for every row. | Headline decisions 1972-07-31 to 2026-10-30 (n=652); core from 1996-12-31 (n=359). Min coverage of L1/M1-M4: 99.4%. Rows with release after decision: 0. Percentile rules (L2, L3) are defined for only 60% of headline decisions: ALFRED vintages before 1994-02 hold about 19 monthly observations, too few to calibrate a distribution without back-filling revised data. | Supported (for fixed-threshold level and all momentum rules) |
| D1 | extension | Headline and core CPI give consistent level and momentum classifications. | Lower 95% CI bound of weighted kappa >= 0.60 for the level rule. | Headline vs core, L1 level: weighted kappa 0.29 [0.03, 0.50], raw agreement 65% (n=359). M1 momentum: kappa 0.27 [0.17, 0.36]. Declared guide: lower bound >= 0.60. | Not supported |
| D2 | extension | Level/momentum labels are robust to reasonable rule definitions. | Median pairwise kappa >= 0.60 with CI. | Median pairwise weighted kappa across definitions: CORE level 0.399; CORE momentum 0.421; HEADLINE level 0.596; HEADLINE momentum 0.462. Declared guide: median >= 0.60. Pairwise range (headline level): 0.51 to 0.71. | Not supported |
| D3 | extension | Real-time labels are rarely changed by later revisions. | Upper 95% CI bound of the flip share <= 5% for the level rule and <= 10% for momentum. | Real-time label differs from latest-revised label (share, 95% CI upper bound vs limit 5% level / 10% momentum). Pass: H:L1 1.7%, H:L2 1.0%, H:M1 8.0%, H:M2 4.3%, C:L1 0.8%, C:L2 1.7%, C:M1 4.2%, C:M2 2.8%, C:M4 6.4%. Fail: H:L3 4.1% (upper 6.4%), H:M3 21.0% (upper 25.8%), H:M4 19.4% (upper 23.3%), C:L3 4.2% (upper 7.2%), C:M3 10.3% (upper 15.1%). Short-horizon annualised-pace momentum (M3, M4) is the revision-sensitive family (seasonal-factor revisions). | Partially supported |
| D4 | extension | Raw momentum labels switch too often; persistence rules reduce short-lived reversals at an acceptable delay cost. | confirm2/hyst cut short spells by >= 50% with a median added delay <= 3 months. | H M1 confirm2: short spells 55%->18% (67% lower), added median delay 1.0m; H M1 hyst: short spells 55%->49% (10% lower), added median delay 0.0m; H M2 confirm2: short spells 43%->20% (55% lower), added median delay 1.0m; H M2 hyst: short spells 43%->41% (6% lower), added median delay 0.0m; C M1 confirm2: short spells 51%->16% (69% lower), added median delay 1.0m; C M1 hyst: short spells 51%->34% (33% lower), added median delay 0.0m; C M2 confirm2: short spells 30%->10% (66% lower), added median delay 1.0m; C M2 hyst: short spells 30%->10% (68% lower), added median delay 0.0m | confirm2 supported; hyst not supported |
| D5 | extension | Momentum turns are detected within a useful delay. | Median delay <= 6 months and >= 75% of turning points detected within 18 months. | Headline M1 raw: 19/19 ex-post turning points matched within 18 months, median delay 2.0 months from the observation month (IQR 2.0-3.0). Chance check: only 38% of all switches into the matching state fall inside a post-turning-point window that covers 28% of the time (lift 1.36); the rule changes state ~3.7 times a year, so catching every turn is expected and most switches are not turning points. | Supported on the declared timeliness criterion, but weak evidence of discrimination |
| R1 | extension | Detection properties are stable across calibration scheme, sample start and inflation episodes. | Metrics change by less than the bootstrap half-width when any one episode is removed. | Largest change when any one declared episode is excluded vs CI half-width: headline-vs-core kappa (L1) 0.255 vs 0.236; revision flip share (L1) 0.005 vs 0.010; transitions per year (L1) 0.153 vs 0.442. Excluding the 2020-26 episode drops headline-vs-core level kappa from 0.29 to 0.04. | Not supported (headline-vs-core agreement is episode-dependent) |
| E1 | extension | Forward 3m Treasury excess returns are lower after high-inflation level states than otherwise. | CI excludes 0, sign negative, Holm-adjusted p < 0.05. | high vs not-high: mean forward 3m excess return difference -1.6% per year (95% CI -5.6% to 2.5%); cells 263 / 386 months in 20 / 21 spells; bootstrap p 0.45, Holm-adjusted 1.00; effect size -0.20 sd. | Not supported (inconclusive: CI includes zero) |
| E2 | extension | Forward 3m Treasury excess returns are lower after 'rising' than after 'falling' momentum states. | As E1. | rising - falling: mean forward 3m excess return difference 0.1% per year (95% CI -4.7% to 5.0%); cells 206 / 208 months in 55 / 54 spells; bootstrap p 0.96, Holm-adjusted 1.00; effect size 0.01 sd. | Not supported (inconclusive: CI includes zero) |
| E3 | extension | Forward 3m excess returns differ between low and high level states. | As E1. | low - high: mean forward 3m excess return difference -2.9% per year (95% CI -8.8% to 3.2%); cells 75 / 263 months in 14 / 20 spells; bootstrap p 0.35, Holm-adjusted 1.00; effect size -0.36 sd. | Not supported (inconclusive: CI includes zero) |
| E4/B3 | extension | High-and-rising inflation during tightening has worse forward 3m excess returns than high-but-falling inflation during easing. | As E1 and each cell has >=12 months and >=3 spells. | (high,rising,tightening) - (high,falling,easing): mean forward 3m excess return difference 1.2% per year (95% CI -7.7% to 11.0%); cells 66 / 43 months in 20 / 15 spells; bootstrap p 0.81, Holm-adjusted 1.00; effect size 0.16 sd. | Not supported (inconclusive: CI includes zero) |
| E5 | extension | The E1-E4 contrasts also hold for core CPI, other rules, other horizons (1m, 12m) and the IEF proxy. | Consistent sign and CI exclusion across most combinations after BH. | 83 estimable secondary contrasts of 128 defined; 0 significant after Benjamini-Hochberg. E1 (high vs not-high, expected negative): 15/17 negative, 0 with 95% CI below 0 before correction. E2 (rising - falling, expected negative): 24/47 negative, 1 with CI below 0 before correction. | Not supported |
| B1 | section 5 1 | The deep Treasury drawdowns (Table 5.1) are associated with Fed tightening cycles. | Share of drawdown peaks in tightening materially exceeds the unconditional tightening share, in every sub-sample with >=3 episodes. | 1/16 drawdown peaks fall in a 'tightening' state (6%, exact 95% CI 0%-30%) vs 27% of all decisions; mean share of peak-to-trough decisions in tightening 21%. The tightening state is a trailing 6-month change, so peaks naturally precede it. Deepest episodes (<= -20%): 1976-12..1981-09 -39% (tightening 67% of decisions inside); 2020-08..2026-09 -29% (tightening 24% of decisions inside). | Not supported as a general statement (declared metric); consistent for some of the deepest episodes |
| B2 | section 5 1 | The two drawdowns deeper than 10% (1977-81, 2020-23) coincided with very high inflation; without a major inflation problem drawdowns were ~10% or less. | Deep drawdown episodes start/run in 'high' level states, and shallow ones do not. | Share of peak-to-trough decisions with headline L1 'high': deep (<= -10%, n=9) mean 33%, shallow (n=7) mean 14%. Deepest: 1976-12..1981-09 -39% high inside 100%; 2020-08..2026-09 -29% high inside 41%; 1986-08..1987-10 -16% high inside 36%. Shallow episodes with >= 90% of decisions in 'high': 2008-03..2008-06 (-7%). | Partially consistent (descriptive only; not a clean separation) |
| B4 | section 5 1 | Ex-post real returns depend on starting real yields (Fig 5.1); fair-value 10Y real yield ~ potential growth (Fig 5.2). | n/a | Real-yield / potential-growth claims are not tested in this study. | Untested |

## 3. Measurement and point-in-time coverage

| series_id | first_vintage_date | first_genuine_release_obs | n_obs | n_obs_first_seen_late | n_obs_genuine | median_first_release_lag_days_genuine | max_first_release_lag_days_genuine |
|---|---|---|---|---|---|---|---|
| US.CPI.ALL_ITEMS.SA | 1972-07-21 | 1972-06-01 | 956 | 305 | 651 | 17.0 | 32 |
| US.CPI.CORE.SA | 1996-12-12 | 1996-10-01 | 836 | 477 | 359 | 15.0 | 42 |

* `n_obs_first_seen_late` are observations that entered the ALFRED archive in a back-fill (more than 45 days after their month end). They are usable as *history inside a vintage* but decision dates before the first vintage are excluded.
* Median information lag from the period a state describes to the decision date is 30 days (maximum 62). A state at a month-end decision describes the previous month.
* The October 2025 CPI release did not occur (federal shutdown); momentum rules that need that month are undefined for the affected decisions (shown as <100% coverage) rather than interpolated.
* Release time 08:30 ET is an assumption (ALFRED vintage dates are day-granular). Fed funds values before 1996-10 are back-filled in ALFRED, so their availability is assumed to be the day after month end (flagged `assumed_month_end_plus_1d`).

## 4. Detection quality

### 4.1 Headline vs core agreement (weighted kappa, 95% stationary block-bootstrap CI)

| rule | n | kappa | raw_agreement |
|---|---|---|---|
| L1_FIXED | 359 | 0.29 [0.03, 0.50] | 65% |
| L2_EXP_PCTL | 359 | 0.35 [0.10, 0.55] | 58% |
| L3_ROLL10Y_PCTL | 359 | 0.41 [0.20, 0.58] | 56% |
| M1_DYOY_3M | 358 | 0.27 [0.17, 0.36] | 50% |
| M2_DYOY_6M | 358 | 0.26 [0.11, 0.41] | 52% |
| M3_ANN6M_VS_YOY | 358 | 0.26 [0.13, 0.38] | 53% |
| M4_ANN3M_VS_YOY | 358 | 0.20 [0.09, 0.30] | 51% |

*What it shows:* consistency between two measures built from different baskets. *What it cannot show:* correctness; high agreement could coexist with both being wrong, and low agreement reflects genuine economic divergence (energy/food) as well as noise.

### 4.2 Revision-induced label changes (real-time label vs latest-revised label of the same month)

| measure | rule | n | flip_share |
|---|---|---|---|
| HEADLINE | L1_FIXED | 652 | 1.7% [0.8%, 2.8%] |
| HEADLINE | L2_EXP_PCTL | 393 | 1.0% [0.0%, 3.1%] |
| HEADLINE | L3_ROLL10Y_PCTL | 393 | 4.1% [2.0%, 6.4%] |
| HEADLINE | M1_DYOY_3M | 651 | 8.0% [6.1%, 10.0%] |
| HEADLINE | M2_DYOY_6M | 648 | 4.3% [2.8%, 6.2%] |
| HEADLINE | M3_ANN6M_VS_YOY | 651 | 21.0% [16.7%, 25.8%] |
| HEADLINE | M4_ANN3M_VS_YOY | 651 | 19.4% [15.4%, 23.3%] |
| CORE | L1_FIXED | 359 | 0.8% [0.0%, 2.2%] |
| CORE | L2_EXP_PCTL | 359 | 1.7% [0.3%, 3.6%] |
| CORE | L3_ROLL10Y_PCTL | 359 | 4.2% [1.7%, 7.2%] |
| CORE | M1_DYOY_3M | 358 | 4.2% [2.0%, 6.7%] |
| CORE | M2_DYOY_6M | 358 | 2.8% [0.8%, 5.0%] |
| CORE | M3_ANN6M_VS_YOY | 358 | 10.3% [6.1%, 15.1%] |
| CORE | M4_ANN3M_VS_YOY | 358 | 6.4% [3.6%, 9.2%] |

*What it shows:* how often later data would have changed the label (including seasonal-factor revisions and revised history inside percentile calibrations). *What it cannot show:* behaviour under a future methodology change.

### 4.3 Persistence / switching (real-time, 95% CI on transitions per year)

| measure | rule | persistence | transitions_per_year | mean_spell_months | share_spells_le_2m | reversals_within_3m |
|---|---|---|---|---|---|---|
| HEADLINE | L1_FIXED | raw | 1.25 [0.83, 1.71] | 9.4 | 42% | 34 |
| HEADLINE | L1_FIXED | confirm2 | 0.83 [0.55, 1.12] | 14.2 | 22% | 14 |
| HEADLINE | L1_FIXED | hyst | 0.88 [0.57, 1.20] | 13.3 | 27% | 14 |
| HEADLINE | M1_DYOY_3M | raw | 3.71 [3.23, 4.22] | 3.2 | 55% | 81 |
| HEADLINE | M1_DYOY_3M | confirm2 | 2.10 [1.80, 2.37] | 5.7 | 18% | 25 |
| HEADLINE | M1_DYOY_3M | hyst | 3.37 [2.89, 3.85] | 3.5 | 49% | 66 |
| HEADLINE | M2_DYOY_6M | raw | 2.50 [2.04, 2.94] | 4.7 | 43% | 47 |
| HEADLINE | M2_DYOY_6M | confirm2 | 1.67 [1.40, 1.97] | 7.1 | 20% | 13 |
| HEADLINE | M2_DYOY_6M | hyst | 2.10 [1.71, 2.50] | 5.7 | 41% | 25 |
| CORE | L1_FIXED | raw | 0.53 [0.17, 0.97] | 21.1 | 41% | 7 |
| CORE | L1_FIXED | confirm2 | 0.33 [0.10, 0.64] | 32.6 | 18% | 2 |
| CORE | L1_FIXED | hyst | 0.33 [0.13, 0.60] | 32.6 | 18% | 1 |
| CORE | M1_DYOY_3M | raw | 2.51 [1.91, 3.15] | 4.6 | 51% | 35 |
| CORE | M1_DYOY_3M | confirm2 | 1.24 [0.77, 1.74] | 9.4 | 16% | 12 |
| CORE | M1_DYOY_3M | hyst | 2.34 [1.81, 2.91] | 5.1 | 34% | 29 |
| CORE | M2_DYOY_6M | raw | 1.27 [0.80, 1.78] | 9.0 | 30% | 16 |
| CORE | M2_DYOY_6M | confirm2 | 0.94 [0.53, 1.34] | 12.4 | 10% | 8 |
| CORE | M2_DYOY_6M | hyst | 1.00 [0.67, 1.37] | 11.6 | 10% | 4 |

*What it shows:* label stability. *What it cannot show:* accuracy - a never-changing label is perfectly stable and uninformative.

### 4.4 Detection delay against ex-post turning points (reference is retrospective)

| measure | rule | persistence | turning_points | detected | median_delay_months | p25 | p75 |
|---|---|---|---|---|---|---|---|
| CORE | M1_DYOY_3M | confirm2 | 3 | 3 | 3.0 | 3.0 | 5.5 |
| CORE | M1_DYOY_3M | hyst | 3 | 3 | 2.0 | 2.0 | 2.5 |
| CORE | M1_DYOY_3M | raw | 3 | 3 | 2.0 | 2.0 | 2.5 |
| CORE | M2_DYOY_6M | confirm2 | 3 | 2 | 6.0 | 6.0 | 6.0 |
| CORE | M2_DYOY_6M | hyst | 3 | 3 | 5.0 | 5.0 | 8.0 |
| CORE | M2_DYOY_6M | raw | 3 | 3 | 5.0 | 5.0 | 8.0 |
| HEADLINE | M1_DYOY_3M | confirm2 | 19 | 19 | 3.0 | 3.0 | 4.0 |
| HEADLINE | M1_DYOY_3M | hyst | 19 | 19 | 2.0 | 2.0 | 3.0 |
| HEADLINE | M1_DYOY_3M | raw | 19 | 19 | 2.0 | 2.0 | 3.0 |
| HEADLINE | M2_DYOY_6M | confirm2 | 19 | 19 | 6.0 | 4.5 | 7.0 |
| HEADLINE | M2_DYOY_6M | hyst | 19 | 19 | 5.0 | 3.5 | 6.0 |
| HEADLINE | M2_DYOY_6M | raw | 19 | 19 | 5.0 | 3.5 | 6.0 |

Chance baseline (share of all switches into the matching state that land in a post-turning-point window, vs the share of time covered by those windows):

| measure | rule | turning_point | switches | in_window | time_in_window | lift |
|---|---|---|---|---|---|---|
| HEADLINE | M1_DYOY_3M | peak | 54 | 39% | 29% | 1.33 |
| HEADLINE | M1_DYOY_3M | trough | 55 | 36% | 26% | 1.39 |
| HEADLINE | M2_DYOY_6M | peak | 37 | 43% | 29% | 1.48 |
| HEADLINE | M2_DYOY_6M | trough | 32 | 47% | 26% | 1.79 |
| CORE | M1_DYOY_3M | peak | 23 | 17% | 11% | 1.64 |
| CORE | M1_DYOY_3M | trough | 16 | 6% | 5% | 1.18 |
| CORE | M2_DYOY_6M | peak | 13 | 15% | 11% | 1.45 |
| CORE | M2_DYOY_6M | trough | 6 | 17% | 5% | 3.15 |

*What it shows:* timeliness and a false-alarm rate. *What it cannot show:* accuracy; the zigzag turning points (1.5pp, 3-month centred mean) are themselves a modelling choice that uses future data.

### 4.5 Sensitivity (full tables: `sensitivity_*.csv`; figures 5a/5b)

* Level thresholds: across the 3x3 grid the headline share of time 'high' ranges 32%-52% and kappa against the declared thresholds 0.72-1.00.
* Calibration lookback changes what 'high' means: for headline the share 'high' is 7% with the expanding full-history distribution (which still contains the 1970s) but 27% with a trailing 10-year window.
* Quarterly instead of monthly decisions cut headline L1 transitions from 1.25 to 0.79 per year and hide 14 of 69 monthly spells.

## 5. Robustness across time

Independent regime episodes versus monthly observations (headline, raw rules):

| rule_id | state | months | n_spells | n_spells_ge3m | n_spells_ge6m | median_spell_months |
|---|---|---|---|---|---|---|
| L1_FIXED | low | 75 | 14 | 9 | 4 | 3.0 |
| L1_FIXED | normal | 313 | 34 | 21 | 15 | 5.0 |
| L1_FIXED | high | 264 | 21 | 10 | 5 | 2.0 |
| M1_DYOY_3M | falling | 210 | 55 | 33 | 11 | 3.0 |
| M1_DYOY_3M | stable | 235 | 93 | 28 | 9 | 1.0 |
| M1_DYOY_3M | rising | 206 | 55 | 31 | 8 | 3.0 |

Leave-one-episode-out (headline L1): see `robustness_leave_one_episode_out.csv`; calibration and sample-start comparisons: `sensitivity_calibration_lookback.csv`, `robustness_sample_starts.csv`, `robustness_episodes.csv`. All of these are *retrospective robustness checks*. No parameter was selected, so no chronological validation split was needed; the reserved window (decisions from 2015-01) is reported separately but was visible to the author when the rules were written, so it is not a prospective test. Decisions after 2026-10-30 are genuinely out of sample for the frozen definitions.

## 6. Economic relevance (separate from detection)

Forward outcomes start at the close one session after the decision date. Contemporaneous descriptions (trailing 3 months) are in `conditional_outcomes_contemporaneous.csv` and are *not* evidence of anything that could be known in advance.

### 6.1 Headline L1 level -> forward 3m excess return over T-bills, SYN8Y (model-estimated), annualised

| window | cell | months | spells | mean_excess_ann | downside_freq | ES5 | mean_fwd12m_maxDD | share_fwd12m_DD_gt5 | enough |
|---|---|---|---|---|---|---|---|---|---|
| full | ALL | 649 |  | 1.6% | 48% | -7.6% | -5.9% | 49% | True |
| full | high | 263 | 20 | 0.7% | 53% | -9.4% | -6.5% | 51% | True |
| full | low | 75 | 14 | -2.2% | 53% | -6.5% | -6.0% | 59% | True |
| full | normal | 311 | 34 | 3.3% | 43% | -5.3% | -5.5% | 45% | True |
| design_le_2014 | ALL | 510 |  | 2.4% | 47% | -7.8% | -5.9% | 48% | True |
| design_le_2014 | high | 233 | 17 | 1.8% | 51% | -9.2% | -5.9% | 46% | True |
| design_le_2014 | low | 43 | 13 | -1.9% | 56% | -6.8% | -6.1% | 51% | True |
| design_le_2014 | normal | 234 | 29 | 3.8% | 41% | -5.4% | -5.7% | 49% | True |
| reserved_ge_2015 | ALL | 139 |  | -1.3% | 54% | -7.2% | -6.3% | 53% | True |
| reserved_ge_2015 | high | 30 | 3 | -8.1% | 73% | n/a | -11.1% | 87% | True |
| reserved_ge_2015 | low | 32 | 2 | -2.6% | 50% | n/a | -5.8% | 69% | False |
| reserved_ge_2015 | normal | 77 | 5 | 1.8% | 48% | -4.6% | -4.6% | 32% | True |

In the reserved window (decisions from 2015-01) the 'high' cell is 30 months in 3 spells (essentially one episode, the 2021-23 surge). E1 there: difference -8.6% per year, 95% CI -15.8% to 0.4%; with so few independent episodes the interval is the relevant summary, not the point estimate.

### 6.2 Headline M1 momentum -> same outcome

| window | cell | months | spells | mean_excess_ann | downside_freq | ES5 | mean_fwd12m_maxDD | share_fwd12m_DD_gt5 | enough |
|---|---|---|---|---|---|---|---|---|---|
| full | ALL | 648 |  | 1.6% | 48% | -7.6% | -5.9% | 49% | True |
| full | falling | 208 | 54 | 1.7% | 47% | -7.1% | -5.6% | 49% | True |
| full | rising | 206 | 55 | 1.8% | 47% | -8.8% | -6.9% | 55% | True |
| full | stable | 234 | 92 | 1.4% | 51% | -6.8% | -5.4% | 44% | True |
| design_le_2014 | ALL | 510 |  | 2.4% | 47% | -7.8% | -5.9% | 48% | True |
| design_le_2014 | falling | 167 | 46 | 2.6% | 46% | -7.4% | -5.6% | 47% | True |
| design_le_2014 | rising | 160 | 41 | 3.2% | 44% | -8.6% | -6.6% | 54% | True |
| design_le_2014 | stable | 183 | 71 | 1.5% | 49% | -7.1% | -5.4% | 43% | True |
| reserved_ge_2015 | ALL | 138 |  | -1.3% | 54% | -7.2% | -6.3% | 53% | True |
| reserved_ge_2015 | falling | 41 | 9 | -2.1% | 49% | -5.4% | -5.7% | 56% | True |
| reserved_ge_2015 | rising | 46 | 14 | -3.1% | 54% | -9.0% | -7.9% | 59% | True |
| reserved_ge_2015 | stable | 51 | 21 | 1.1% | 57% | -5.3% | -5.4% | 45% | True |

### 6.3 Same, observed ETF proxy IEF (2002-07+)

| window | cell | months | spells | mean_excess_ann | downside_freq | ES5 | mean_fwd12m_maxDD | share_fwd12m_DD_gt5 | enough |
|---|---|---|---|---|---|---|---|---|---|
| full | ALL | 289 |  | 1.7% | 45% | -6.7% | -6.2% | 54% | True |
| full | high | 58 | 9 | -1.5% | 59% | -9.8% | -9.0% | 71% | True |
| full | low | 64 | 10 | -2.1% | 50% | -6.1% | -5.9% | 61% | True |
| full | normal | 167 | 18 | 4.3% | 39% | -4.7% | -5.3% | 45% | True |

| window | cell | months | spells | mean_excess_ann | downside_freq | ES5 | mean_fwd12m_maxDD | share_fwd12m_DD_gt5 | enough |
|---|---|---|---|---|---|---|---|---|---|
| full | ALL | 288 |  | 1.8% | 45% | -6.7% | -6.2% | 54% | True |
| full | falling | 95 | 27 | 0.3% | 46% | -5.9% | -5.9% | 57% | True |
| full | rising | 101 | 30 | 3.2% | 40% | -7.8% | -6.8% | 52% | True |
| full | stable | 92 | 48 | 1.6% | 50% | -5.8% | -5.9% | 52% | True |

### 6.4 Fed policy state (separate dimension; tightening = fed funds up >= 0.50pp over 6 months)

| window | cell | months | spells | mean_excess_ann | downside_freq | ES5 | mean_fwd12m_maxDD | share_fwd12m_DD_gt5 | enough |
|---|---|---|---|---|---|---|---|---|---|
| full | ALL | 649 |  | 1.6% | 48% | -7.6% | -5.9% | 49% | True |
| full | easing | 162 | 23 | 2.7% | 49% | -6.8% | -5.9% | 52% | True |
| full | hold | 310 | 42 | 1.3% | 45% | -7.1% | -6.0% | 49% | True |
| full | tightening | 177 | 24 | 1.1% | 54% | -8.7% | -5.9% | 46% | True |

### 6.5 Section 5.1's contrast: high & rising during tightening vs high & falling during easing (SYN8Y, 3m)

| window | cell | months | spells | mean_excess_ann | downside_freq | ES5 | mean_fwd12m_maxDD | share_fwd12m_DD_gt5 | enough |
|---|---|---|---|---|---|---|---|---|---|
| full | ALL | 648 |  | 1.6% | 48% | -7.6% | -5.9% | 49% | True |
| full | high|falling|easing | 43 | 15 | 1.3% | 51% | -7.8% | -5.7% | 47% | True |
| full | high|falling|tightening | 24 | 10 | 1.2% | 54% | n/a | -6.2% | 58% | True |
| full | high|rising|easing | 16 | 7 | 3.8% | 44% | n/a | -6.0% | 56% | True |
| full | high|rising|tightening | 66 | 20 | 2.6% | 47% | -10.7% | -7.6% | 65% | True |

### 6.6 Primary contrasts (Holm family) and robustness

| contrast | months_a_b | spells_a_b | diff_ann | CI95 | p_boot | holm_p |
|---|---|---|---|---|---|---|
| E1_high_vs_notHigh | 263/386 | 20/21 | -1.6% | -5.6% to 2.5% | 0.45 | 1.0 |
| E3_low_vs_high | 75/263 | 14/20 | -2.9% | -8.8% to 3.2% | 0.347 | 1.0 |
| E4_high_rising_tightening_vs_high_falling_easing | 66/43 | 20/15 | 1.2% | -7.7% to 11.0% | 0.808 | 1.0 |
| E2_rising_vs_falling | 206/208 | 55/54 | 0.1% | -4.7% to 5.0% | 0.964 | 1.0 |

Across 38 robustness re-runs of E1/E2 (windows, leave-one-episode-out, sample starts, persistence, target and horizon), the 95% CI excludes zero in 0 (uncorrected). Figure 8 plots them; none is a corrected test.

### 6.7 Drawdowns (total-return wealth; cash-relative wealth explicitly labelled)

Table 5.1 comparison (book index vs our model-estimated 8y par bond, cash-relative; book values transcribed for reference only):

| book_peak | book_dd | our_peak | our_trough | our_dd | headline_level_at_peak | fed_at_peak | tightening_share_inside |
|---|---|---|---|---|---|---|---|
| 1973-02-02 | -7.4% | 1973-01-04 | 1974-08-26 | -12.4% | high | tightening | 84% |
| 1977-01-03 | -25.5% | 1976-12-10 | 1981-09-30 | -39.3% | high | hold | 67% |
| 1986-09-01 | -9.1% | 1986-08-29 | 1987-10-16 | -15.7% | normal | easing | 21% |
| 1993-11-01 | -9.0% | 1993-10-15 | 1994-11-21 | -14.7% | normal | hold | 46% |
| 1998-10-06 | -10.2% | 1998-10-05 | 2000-01-20 | -15.0% | normal | hold | 7% |
| 2008-12-19 | -7.3% | 2008-12-18 | 2009-06-10 | -11.3% | high | easing | 0% |
| 2016-07-11 | -7.4% | 2016-07-05 | 2018-11-08 | -11.2% | low | hold | 32% |
| 2020-08-05 | -23.1% | 2020-08-04 | 2026-09-30 | -29.1% | low | easing | 24% |

8 of 8 book episodes have a peak in our series within 45 days of the book's peak; our drawdowns are deeper than the book's in 8 of 8 (different construction: 8y par bond, daily roll, model-estimated). Episodes still open at the end of the data have no recovery date. All episodes: `drawdown_episodes.csv` (total-return and cash-relative, both targets).

## 7. Supported, inconclusive, untested

**Supported by the declared criteria:** M1 (M1 holds for the fixed-threshold level rule and all momentum rules).

**Supported only in part or with a caveat:** D4; D5; D3; B2. D4 holds for the confirmation rule only; D5 holds on timeliness but the chance check shows weak discrimination; D3 holds for level rules and slow momentum rules but not for M3/M4; B2 is descriptive.

**Inconclusive or not supported:** D1; D2; R1; E1; E2; E3; E4/B3; E5; B1. For the economic hypotheses this means the data cannot distinguish an effect from none at the available number of independent episodes; it is not evidence of no effect.

**Untested claims:**

* Causality between tightening, inflation and Treasury drawdowns.
* Whether any state is tradable: no signals, costs, or Sharpe analysis were run by design.
* Results with the book's Bloomberg Treasury index (not available) or any total-return Treasury index with long history; the synthetic is model-estimated and IEF only covers 2002-07+.
* PCE inflation (the Fed's target measure) and inflation expectations / surprises as state inputs; CPI differs from PCE in weights, formula and revisions.
* Behaviour out of regime (no stagflation comparable to the 1970s in the post-1994 percentile-calibrated sample).
* True prospective validation: only decisions after the freeze date can provide it.
* Fed funds availability before 1996-10 (assumed) and the 08:30 ET CPI release time (assumed).

## 8. Search scope (multiple testing)

| item | count | note |
|---|---|---|
| detection metrics tables | 7 | rules x 3 persistence x 2 measures; no p-values; CIs only |
| economic contrasts, primary family (Holm) | 4 | headline, L1/M1, SYN8Y, 3m |
| economic contrasts, secondary family (BH) | 128 | all other measure x rule x target x horizon combinations, full sample |
| economic contrasts, robustness re-runs of primary (not corrected, descriptive) | 76 | windows, leave-one-episode-out, starts, persistence, targets/horizons |
| conditional-outcome table rows (descriptive) | 2946 | no tests |
| level rules / momentum rules / persistence variants | 3 / 4 / 3 | declared before outcomes; none selected on outcomes |
| threshold sensitivity grid | 3x3 level thresholds; 4 band multiples x 4 rules x 3 persistence; 6 calibrations | reporting only |

Primary family (4 contrasts) corrected with Holm; secondary contrasts corrected with Benjamini-Hochberg across the estimable set; detection metrics have no p-values. Robustness re-runs are descriptive and uncorrected.

## 9. Figures

* `figures/fig1_inflation_levels.png` - Inflation levels, thresholds, real-time vs latest-revised
* `figures/fig2_inflation_momentum.png` - Momentum and neutral band
* `figures/fig3_state_transitions.png` - State history of every rule
* `figures/fig4_revision_disagreement.png` - Revision disagreement
* `figures/fig5a_threshold_sensitivity_level.png` - Threshold sensitivity (level)
* `figures/fig5b_threshold_sensitivity_momentum.png` - Band sensitivity (momentum)
* `figures/fig6_episode_comparison.png` - Episode comparison
* `figures/fig7_drawdowns_and_states.png` - Drawdowns with Fed and inflation state
* `figures/fig8_primary_contrasts.png` - Primary contrasts and robustness

## 10. Process notes (what changed after the first outcome run)

* Definitions: unchanged since the freeze (SHA-256 `e85e14573bf075bd`); the outcome stage verifies this before running.
* After the first outcome run, drawdown episodes were re-based to start in 1973-01 (the first run produced one 1962-91 episode because the synthetic series starts 11 years before the book's index and before the decision window). This changes only which episodes are listed, not any state or contrast.
* The delay chance baseline and the mean 'inside tightening' share were added after seeing that the raw momentum rule switches ~3.7 times a year (so 100% detection is uninformative) and that the declared peak-state metric for B1 is structurally weak. The declared B1 metric is still the one reported in the verdict; the additions are labelled as such.

