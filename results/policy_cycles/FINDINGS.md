# Section 5.2: policy-cycle study

Run 2026-11-11T12:40:02.614640+00:00; market sessions 1994-02-01 through 2026-11-09.
Frozen configuration and input hash: `f0815094750500c7e2aa37009a49fe8da16c41c51f9d186f7d1fb57a23c5146d`. No parameter search was performed.

## Main findings

The fixed rule's net annualized model return is 4.55%, versus 3.81% for duration buy-and-hold and 2.57% for bills. In reserved cycles it returns 2.13% annualized, below bills at 2.37%. The full-sample advantage is therefore not a uniform advantage over cash across cycles.
Hold-after-hiking has positive pooled forward duration excess returns, but the per-cycle tables show material variation. Six complete cycles provide only limited inferential support; design and reserved segments do not independently meet the six-cycle interval threshold. The one inflation comparison reports **insufficient evidence**.

## Scope and evidence

All policy targets, events and source provenance are read from the central DuckDB database. Research performs no downloads; result input CSVs are audit exports. Database migration preserved the original frozen configuration, input fingerprints and numerical outcomes.
271 events: 262 scheduled decisions including holds, 9 target-changing intermeeting announcements. 6 complete cycles and 1 ongoing cycle(s).
Official Fed calendars/statements/minutes establish event dates and scheduled status. Official FRED target series establish numerical levels (single targets before December 16, 2008; ranges afterward). Target-level observation dates are not substituted for announcement dates.
Historical statements that only say 'immediate release' have no fabricated clock time. Date-only announcements and reconstructed scheduled holds are conservatively usable only from the next calendar-day midnight, then subject to the execution lag. These rows are reconstruction, not verified intraday real-time observations.
| Timing basis | Events |
|---|---|
| date_only_next_day | 152 |
| statement_clock_time | 89 |
| scheduled_hold_reconstructed_next_day | 30 |

## State rules and timing

A target midpoint increase establishes hiking; a decrease establishes easing. Only a later scheduled meeting leaving both bounds unchanged establishes hold-after-hiking/easing. An unchanged intermeeting announcement cannot establish a hold. Direction is initially unknown. Each directional change resets time since last change and consecutive scheduled holds. A range-width-only change has no inferred direction.
ZLB is declared as target upper bound <=0.25%; it is a reporting flag, not an allocation override. One session of execution lag applies after the state is observable at a session close. Sunday/after-close announcements first enter the next eligible session's decision, then execute one session later.
Daily/monthly state histories retain source event, target representation, availability, time since change, scheduled-hold counts, cycle and ZLB. See `policy_events.csv`, `event_state_history.csv`, `daily_state_history.csv` and `cycles.csv`.

## Forward excess returns

Month-end formation closes; returns begin at the next-session execution close and end at the equally lagged formation close 1, 3 or 6 months later. Percentages are horizon returns, not annualized. Months are not independent observations: 3/6-month windows overlap. Cycle counts are distinct hike-through-easing cycles, not state spells.
Both maturities are MODEL-ESTIMATED daily-rebought par-bond targets, not observed tradable index returns. SYN2Y uses 2Y CMT; SYN8Y reuses linear 5Y/10Y interpolation. Coupon accrual and price changes use the existing semiannual par-bond model. Bills use the existing 91-day discount-to-investment-yield conversion, calendar-day accrual and compounding. Excess return is duration return minus bills return.

| target | horizon_months | state | months | cycles | complete_cycles | mean_excess | inference |
|---|---|---|---|---|---|---|---|
| SYN2Y | 1 | unknown | 0 | 0 | 0 | n/a | descriptive only |
| SYN2Y | 1 | hiking | 75 | 7 | 6 | -0.13% | cycle-bootstrap interval |
| SYN2Y | 1 | hold_after_hiking | 90 | 6 | 6 | 0.15% | cycle-bootstrap interval |
| SYN2Y | 1 | easing | 48 | 6 | 6 | 0.09% | cycle-bootstrap interval |
| SYN2Y | 1 | hold_after_easing | 179 | 6 | 6 | 0.04% | cycle-bootstrap interval |
| SYN2Y | 3 | unknown | 0 | 0 | 0 | n/a | descriptive only |
| SYN2Y | 3 | hiking | 74 | 6 | 6 | -0.27% | cycle-bootstrap interval |
| SYN2Y | 3 | hold_after_hiking | 90 | 6 | 6 | 0.36% | cycle-bootstrap interval |
| SYN2Y | 3 | easing | 48 | 6 | 6 | 0.27% | cycle-bootstrap interval |
| SYN2Y | 3 | hold_after_easing | 178 | 6 | 6 | 0.11% | cycle-bootstrap interval |
| SYN2Y | 6 | unknown | 0 | 0 | 0 | n/a | descriptive only |
| SYN2Y | 6 | hiking | 74 | 6 | 6 | -0.49% | cycle-bootstrap interval |
| SYN2Y | 6 | hold_after_hiking | 90 | 6 | 6 | 0.82% | cycle-bootstrap interval |
| SYN2Y | 6 | easing | 48 | 6 | 6 | 0.73% | cycle-bootstrap interval |
| SYN2Y | 6 | hold_after_easing | 175 | 6 | 6 | 0.14% | descriptive only |
| SYN8Y | 1 | unknown | 0 | 0 | 0 | n/a | descriptive only |
| SYN8Y | 1 | hiking | 75 | 7 | 6 | -0.22% | cycle-bootstrap interval |
| SYN8Y | 1 | hold_after_hiking | 90 | 6 | 6 | 0.45% | cycle-bootstrap interval |
| SYN8Y | 1 | easing | 48 | 6 | 6 | 0.01% | cycle-bootstrap interval |
| SYN8Y | 1 | hold_after_easing | 179 | 6 | 6 | 0.14% | cycle-bootstrap interval |
| SYN8Y | 3 | unknown | 0 | 0 | 0 | n/a | descriptive only |
| SYN8Y | 3 | hiking | 74 | 6 | 6 | -0.29% | cycle-bootstrap interval |
| SYN8Y | 3 | hold_after_hiking | 90 | 6 | 6 | 1.06% | cycle-bootstrap interval |
| SYN8Y | 3 | easing | 48 | 6 | 6 | 0.16% | cycle-bootstrap interval |
| SYN8Y | 3 | hold_after_easing | 178 | 6 | 6 | 0.43% | cycle-bootstrap interval |
| SYN8Y | 6 | unknown | 0 | 0 | 0 | n/a | descriptive only |
| SYN8Y | 6 | hiking | 74 | 6 | 6 | -0.51% | cycle-bootstrap interval |
| SYN8Y | 6 | hold_after_hiking | 90 | 6 | 6 | 2.10% | cycle-bootstrap interval |
| SYN8Y | 6 | easing | 48 | 6 | 6 | 0.89% | cycle-bootstrap interval |
| SYN8Y | 6 | hold_after_easing | 175 | 6 | 6 | 0.79% | descriptive only |

### Whole-cycle reserved split

reserved whole cycles, not pristine out-of-sample: prior exposure to their outcomes.
Cycles beginning in 2015 or later are reserved in their entirety, not split at January 2015. See design/reserved rows in `conditional_returns.csv`; no allocation or threshold was chosen using either segment's returns.

| cycle_id | start | complete | sample |
|---|---|---|---|
| CYCLE_19940204 | 1994-02-04 | True | design |
| CYCLE_19970325 | 1997-03-25 | True | design |
| CYCLE_19990630 | 1999-06-30 | True | design |
| CYCLE_20040630 | 2004-06-30 | True | design |
| CYCLE_20151216 | 2015-12-16 | True | reserved |
| CYCLE_20220316 | 2022-03-16 | True | reserved |
| CYCLE_20260916 | 2026-09-16 | False | reserved |

### Per-cycle evidence

The following reports the primary 8Y, 3-month horizon; both targets and every declared horizon are in `per_cycle_returns.csv`. Ongoing cycles are descriptive only.

| cycle_id | sample | complete | state | months | mean_excess |
|---|---|---|---|---|---|
| CYCLE_19940204 | design | True | easing | 4 | -3.20% |
| CYCLE_19940204 | design | True | hiking | 8 | 0.15% |
| CYCLE_19940204 | design | True | hold_after_easing | 16 | 0.61% |
| CYCLE_19940204 | design | True | hold_after_hiking | 9 | 1.78% |
| CYCLE_19970325 | design | True | easing | 3 | -2.78% |
| CYCLE_19970325 | design | True | hiking | 2 | 3.25% |
| CYCLE_19970325 | design | True | hold_after_easing | 7 | -2.62% |
| CYCLE_19970325 | design | True | hold_after_hiking | 16 | 2.50% |
| CYCLE_19990630 | design | True | easing | 15 | 0.59% |
| CYCLE_19990630 | design | True | hiking | 8 | 0.07% |
| CYCLE_19990630 | design | True | hold_after_easing | 27 | 1.37% |
| CYCLE_19990630 | design | True | hold_after_hiking | 10 | 2.19% |
| CYCLE_20040630 | design | True | easing | 12 | 1.75% |
| CYCLE_20040630 | design | True | hiking | 25 | -0.33% |
| CYCLE_20040630 | design | True | hold_after_easing | 87 | 0.94% |
| CYCLE_20040630 | design | True | hold_after_hiking | 13 | 0.80% |
| CYCLE_20151216 | reserved | True | easing | 6 | 0.72% |
| CYCLE_20151216 | reserved | True | hiking | 14 | 0.75% |
| CYCLE_20151216 | reserved | True | hold_after_easing | 26 | -0.85% |
| CYCLE_20151216 | reserved | True | hold_after_hiking | 29 | 0.15% |
| CYCLE_20220316 | reserved | True | easing | 8 | -0.68% |
| CYCLE_20220316 | reserved | True | hiking | 17 | -1.91% |
| CYCLE_20220316 | reserved | True | hold_after_easing | 15 | -0.70% |
| CYCLE_20220316 | reserved | True | hold_after_hiking | 13 | 0.20% |

Inference requires at least 6 complete cycles with observations and 24 months per cell. Only complete-cycle, non-boundary-crossing windows enter equal-weight cycle-bootstrap intervals. No IID monthly standard errors or p-values. Cells with intervals: 22. A long monthly history does not overcome a small number of independent policy cycles.

Primary SYN8Y/3m equal-weight complete-cycle means and descriptive 95% bootstrap intervals (different estimand from pooled monthly means above):

| state | cycle_equal_weight_mean | cycle_ci_low | cycle_ci_high | inference |
|---|---|---|---|---|
| unknown | n/a | n/a | n/a | descriptive only |
| hiking | 0.33% | -0.87% | 1.66% | cycle-bootstrap interval |
| hold_after_hiking | 1.27% | 0.55% | 2.04% | cycle-bootstrap interval |
| easing | -0.60% | -2.01% | 0.81% | cycle-bootstrap interval |
| hold_after_easing | -0.03% | -1.38% | 1.05% | cycle-bootstrap interval |

## One fixed long-only rule

100% SYN8Y in hold-after-hiking, easing and hold-after-easing; 100% bills in hiking and unknown. Hold-after-hiking is not anticipated at the final hike. Signals are evaluated at daily closes, executed one session later, and affect only subsequent returns. Inflation and ZLB do not change weights.
Costs are 5bp per unit of duration notional bought or sold: 10bp for a full round trip, without a second charge on bills. Initial duration entry is charged; no artificial terminal exit. Duration buy-and-hold pays its initial 5bp; bills pay no duration cost. Split returns preserve the actual full-path trades rather than charging a new initial entry at each split.

| strategy | sample | total_return | annualized_return | max_drawdown | duration_turnover | cost_sum |
|---|---|---|---|---|---|---|
| net | all | 330.47% | 4.55% | -11.26% | 41.0 | 2.05% |
| net | design | 242.01% | 5.78% | -11.22% | 17.0 | 0.85% |
| net | reserved | 25.80% | 2.13% | -11.26% | 24.0 | 1.20% |
| duration_buy_hold | all | 241.15% | 3.81% | -22.61% | 1.0 | 0.05% |
| duration_buy_hold | design | 213.36% | 5.36% | -11.22% | 0.0 | 0.00% |
| duration_buy_hold | reserved | 10.35% | 0.91% | -22.61% | 0.0 | 0.00% |
| bills_benchmark | all | 129.97% | 2.57% | -0.00% | 0.0 | 0.00% |
| bills_benchmark | design | 78.03% | 2.67% | -0.00% | 0.0 | 0.00% |
| bills_benchmark | reserved | 29.11% | 2.37% | -0.00% | 0.0 | 0.00% |

Per-cycle strategy and benchmark total returns:

| cycle_id | sample | strategy | total_return |
|---|---|---|---|
| CYCLE_19940204 | design | net | 23.55% |
| CYCLE_19940204 | design | duration_buy_hold | 15.13% |
| CYCLE_19940204 | design | bills_benchmark | 17.38% |
| CYCLE_19970325 | design | net | 18.69% |
| CYCLE_19970325 | design | duration_buy_hold | 20.12% |
| CYCLE_19970325 | design | bills_benchmark | 11.80% |
| CYCLE_19990630 | design | net | 39.70% |
| CYCLE_19990630 | design | duration_buy_hold | 39.80% |
| CYCLE_19990630 | design | bills_benchmark | 16.33% |
| CYCLE_20040630 | design | net | 66.96% |
| CYCLE_20040630 | design | duration_buy_hold | 62.08% |
| CYCLE_20040630 | design | bills_benchmark | 16.61% |
| CYCLE_20151216 | reserved | net | 8.70% |
| CYCLE_20151216 | reserved | duration_buy_hold | 10.16% |
| CYCLE_20151216 | reserved | bills_benchmark | 5.98% |
| CYCLE_20220316 | reserved | net | 13.77% |
| CYCLE_20220316 | reserved | duration_buy_hold | -1.56% |
| CYCLE_20220316 | reserved | bills_benchmark | 21.07% |
| CYCLE_20260916 | reserved | net | 1.72% |
| CYCLE_20260916 | reserved | duration_buy_hold | 1.76% |
| CYCLE_20260916 | reserved | bills_benchmark | 0.61% |

These are descriptive model backtests, not proof of a tradable edge. The bond model omits actual roll-down, instrument selection, funding frictions and market impact; fixed 5bp costs do not validate historical execution feasibility.

## One mutually exclusive inflation comparison

Within hold-after-hiking only: headline CPI high (YoY >=3.5%) AND rising (three-month change in YoY >0.30pp), versus all other known headline inflation states. Unknown inflation is excluded. Existing point-in-time ALFRED snapshots and raw classification are reused; release timestamp/observation month are retained.
Target SYN8Y, forward 3 months. Status: **insufficient evidence**.
Declared difference (high-and-rising minus other): not estimated because the sufficiency gate failed.
| group | months | cycles | complete_cycles | mean_excess |
|---|---|---|---|---|
| high_and_rising | 3 | 3 | 3 | 3.15% |
| other_known_inflation | 87 | 6 | 6 | 0.99% |
At least 24 months and three complete cycles in each group are required for a descriptive difference. No second inflation contrast is substituted if evidence is insufficient.

## Limitations and conclusion

Last month-end decision: 2026-10-30; incomplete forward horizons remain missing. Historical availability is only as reliable as the source/time flag. FRED/H.15 yields are used to model realized marks, not as contemporaneously available allocation predictors.
The study measures policy-cycle associations and one fixed rule. Sparse cycle evidence, overlapping horizons, reconstructed early timing and prior exposure to reserved outcomes limit inference. No causality or optimized investment recommendation is claimed.
Deferred: pre-1994 data, extra maturities, additional strategies, expectations proxies and term-premium models.
