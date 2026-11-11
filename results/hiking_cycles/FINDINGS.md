# Section 5.3: How to Trade a Hiking Cycle

**Conclusion: Not validated. This is a fixed, numerical-only research extension, not the book's executable rule.**

Primary measured difference (SYN2Y filter minus first-hold baseline, full-path net cumulative return): **-31.00 percentage points** (baseline 185.68%; filter 154.69%). This cumulative difference is not annualized. Cycle-level inference: **insufficient evidence** (6 complete cycles; 1 with usable required inputs during a pause).

## Book observations versus our extension

The book's observations motivate caution about smaller hikes, temporary pauses and high-but-falling inflation. The last hike is identified only retrospectively. Wage-setting, expectations and communications may matter; this study does not establish those mechanisms. Pre-first-hike weakness is not tested here, and no last-hike oracle is traded. First-hike forecasting, shorts and broader searches are deferred.

Our one operational rule requires headline/core YoY <3.5%, core YoY falling more than 0.30pp over three observation months; ECI wage YoY <=3.5% and down at least 0.50pp over two quarters; Cleveland Fed modeled ten-year expectations <=2.5% and non-increasing over three observation months. All required inputs must be available and fresh. Productivity is optional context, not a gate. No thresholds were tuned.

Official contemporaneous statements, clocks and archived lineage are retained in pause_communications.csv; later minutes are excluded. A reliable historical communication classifier was not established: the text condition is explicitly deferred, not reconstructed from memory or silently treated as satisfied.

## Measured allocation results

| target | rule | sample | annualized_excess_over_bills | max_drawdown | duration_turnover | time_in_duration |
|---|---|---|---|---|---|---|
| SYN2Y | baseline | all | 0.68% | -3.13% | 41.0 | 80.35% |
| SYN2Y | baseline | design | 1.12% | -2.74% | 17.0 | 82.56% |
| SYN2Y | baseline | reserved | -0.19% | -3.13% | 24.0 | 76.02% |
| SYN2Y | completion_filter | all | 0.32% | -3.13% | 12.0 | 57.40% |
| SYN2Y | completion_filter | design | 0.60% | -2.74% | 7.0 | 64.91% |
| SYN2Y | completion_filter | reserved | -0.24% | -3.13% | 5.0 | 42.42% |
| SYN8Y | baseline | all | 1.98% | -11.26% | 41.0 | 80.35% |
| SYN8Y | baseline | design | 3.11% | -11.22% | 17.0 | 82.56% |
| SYN8Y | baseline | reserved | -0.24% | -11.26% | 24.0 | 76.02% |
| SYN8Y | completion_filter | all | 0.70% | -11.26% | 12.0 | 57.40% |
| SYN8Y | completion_filter | design | 1.49% | -11.22% | 7.0 | 64.91% |
| SYN8Y | completion_filter | reserved | -0.86% | -11.26% | 5.0 | 42.42% |

Percentages: annualized net return minus annualized bills return; strategy peak-to-trough drawdown; share of execution intervals in duration. Turnover is one-way duration notional. Full-path costs are retained when subdividing samples. Both paths begin in bills, execute one session after observation and pay 5bp per unit of duration bought/sold (10bp round trip). Returns are model-estimated, not observed Treasury indexes.

## Pauses, activation and waiting

21 observable candidate pauses; 13 renewed hikes within six months; 1 censored no-hike follow-ups. Required inputs were complete at 3 first-hold observations. 0 numerical activations; 0 observed renewed hikes within six months of activation, 0 activated follow-ups unclassified/censored. Median entry delay when an entry is observed: 276 calendar days; 15 entries censored before entry. Median positive excess rally missed while waiting: 0.00%.

No numerical activations occurred. The filter therefore waited for cuts or remained in bills. Its realized performance cannot validate an ability to recognize completion, and no activation accuracy can be estimated.

pause_diagnostics.csv reports every pause/target's entry timing, observed waiting return, positive excess rally missed, and descriptive 1/3/6-month outcomes. Positive/negative outcomes and future hikes/cuts are retrospective evaluation fields only; none enter allocations. No hike in six months is not proof of permanent completion.

## Each independent cycle

| target | cycle_id | sample | complete | informative | baseline | completion_filter | filter_minus_baseline_net |
|---|---|---|---|---|---|---|---|
| SYN2Y | CYCLE_19940204 | design | True | False | 19.75% | 16.71% | -3.04% |
| SYN2Y | CYCLE_19970325 | design | True | False | 14.02% | 8.92% | -5.10% |
| SYN2Y | CYCLE_19990630 | design | True | False | 26.63% | 23.62% | -3.01% |
| SYN2Y | CYCLE_20040630 | design | True | False | 30.53% | 28.78% | -1.75% |
| SYN2Y | CYCLE_20151216 | reserved | True | False | 4.96% | 5.90% | 0.94% |
| SYN2Y | CYCLE_20220316 | reserved | True | True | 19.63% | 17.96% | -1.67% |
| SYN2Y | CYCLE_20260916 | reserved | False | True | 0.76% | 0.70% | -0.06% |
| SYN8Y | CYCLE_19940204 | design | True | False | 23.55% | 13.33% | -10.21% |
| SYN8Y | CYCLE_19970325 | design | True | False | 18.69% | 0.57% | -18.11% |
| SYN8Y | CYCLE_19990630 | design | True | False | 39.70% | 30.70% | -9.00% |
| SYN8Y | CYCLE_20040630 | design | True | False | 66.96% | 63.61% | -3.34% |
| SYN8Y | CYCLE_20151216 | reserved | True | False | 8.70% | 5.13% | -3.58% |
| SYN8Y | CYCLE_20220316 | reserved | True | True | 13.77% | 10.90% | -2.88% |
| SYN8Y | CYCLE_20260916 | reserved | False | True | 1.72% | 1.05% | -0.66% |

Cycle returns are net cumulative returns, not annualized. The final cycle is ongoing. The reserved split uses whole cycles starting in 2015 or later; it is **reserved, not blind out-of-sample**, because prior research has already exposed their outcomes. Multiple pauses within one cycle are not independent cycles.

## Availability and limitations

| input | series_id | versions | first_observation | last_observation | first_conservatively_known | vintage_rows | ingestion_only_rows |
|---|---|---|---|---|---|---|---|
| headline | US.CPI.ALL_ITEMS.SA | 3365 | 1947-01-01 | 2026-10-01 | 1972-07-22 04:00:00+00:00 | 3364 | 1 |
| core | US.CPI.CORE.SA | 2263 | 1957-01-01 | 2026-10-01 | 1996-12-13 05:00:00+00:00 | 2262 | 1 |
| wages | US.WAGES.ECI.PRIVATE.SA | 414 | 1980-01-01 | 2026-07-01 | 1996-10-30 05:00:00+00:00 | 414 | 0 |
| productivity | US.PRODUCTIVITY.NONFARM.SA | 13123 | 1947-01-01 | 2026-07-01 | 1968-05-28 04:00:00+00:00 | 13123 | 0 |
| expectations | US.INFLATION.EXPECTED.10Y.CLEVELAND | 597 | 1982-01-01 | 2026-11-01 | 2021-10-14 04:00:00+00:00 | 597 | 0 |

Unknown historical publication clocks are not invented: day-only vintages become usable the following calendar-day midnight ET, and ingestion-only/estimated observations are never backdated. Missing months remain missing at earlier decisions. Early archive backfills are usable only when that vintage was actually available. Missing required inputs block the signal, so full-sample performance mixes an operational missing-data policy with the proposed economic detector; it is not evidence that the detector worked in input-uncovered cycles.

Existing daily 5Y5Y breakevens were not substituted: their stored history lacks historical availability. The newly ingested Cleveland Fed series is a model-based long-term expectations proxy, not a direct survey; ECI is aggregate wage growth, not a direct measure of wage-setting behavior. Productivity revisions, quarterly wage releases, conservative clocks and model limitations constrain identification.

inflation_description.csv gives descriptive high/rising, high/falling, other and unknown strata, using the existing headline thresholds. These are conditional, noncontiguous sessions, not independent episodes or additional strategies. Uncertainty resamples paired complete cycles only, and requires at least six input-informative complete cycles; otherwise the result is insufficient evidence. No monthly IID p-values.

Frozen SHA-256: `44b851055155cae9b741adc23e415ed9ffecb64b1b947b4c3e6a845ba2a9500f`. All inputs are database-derived; source versions, provenance, decision features, trades, censoring and the single frozen specification are exported alongside this report.
