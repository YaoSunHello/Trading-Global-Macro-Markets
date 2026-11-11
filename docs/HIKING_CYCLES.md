# Section 5.3: pause versus completed tightening

This is one prespecified research extension, not a trading rule supplied or validated by the book.
The book motivates looking beyond smaller hikes, temporary pauses and falling-but-still-high inflation.
We do not forecast first hikes, short Treasuries, optimize thresholds or trade the retrospective last hike.

## Database first and information timing

Reuse central FOMC events, including scheduled holds, intermeeting changes and uncertain clocks; the
section 5.2 state/cycle definitions; and the existing CPI classifications, par-bond returns and bills.
Missing inputs identified before implementation were wage growth, productivity and a historically
available long-term expectations measure. Registered and ingested through ordinary macrodb:

| Input | Official identifier | Transformation |
|---|---|---|
| Headline and core CPI, SA | FRED/BLS CPIAUCSL, CPILFESL | YoY; core change in YoY over 3 observation months |
| Private-industry ECI wages/salaries, SA | FRED/BLS ECIWAG, quarterly, Dec 2005=100 | YoY; change in YoY over 2 quarters |
| Nonfarm-business output/hour, SA | FRED/BLS OPHNFB, quarterly | YoY context only |
| Cleveland Fed ten-year expected inflation | FRED EXPINF10YR, monthly percent | Level and change over 3 observation months |

Cleveland expectations are model-based (yields, swaps, inflation and surveys), not a direct survey.
Existing T5YIFR history has ingestion-only availability and is not substituted for historical vintages.
Historical backcasts in a model archive become usable only when that vintage was actually available.
ECI's 2006 classification/rebasing change and productivity revisions are retained in source vintages.

Research reads DuckDB only. Export every source version, Bronze ID, original availability/publication
fields, effective conservative `known_at` and raw-response provenance. ALFRED dates without clocks
become usable at **following calendar-day midnight ET**; no universal BLS/Cleveland clock is invented.
Ingestion-only facts, including approved October 2025 CPI estimates, become usable only at their actual
UTC ingestion time. No later release fills an earlier snapshot. Latest missing restatements stay missing.
Monthly inputs expire 90 days after their observation-period end; quarterly inputs expire after 210 days.
The latest published period is used, not a later observation or a substituted earlier nonmissing period.

## Candidate and one numerical signal

A candidate is the first unchanged **scheduled** decision after a run of hikes. Intermeeting hikes
reset eligibility and cuts clear it. Later holds without a new hike are not new candidates. Smaller
positive midpoint changes remain hikes. Width-only range changes do not invent a hiking direction.

All of the following must hold using available, non-stale inputs:

1. Headline YoY **<3.5%**, core YoY **<3.5%**, and core YoY minus its value three observation months
   earlier **<-0.30 percentage points**. This combines controlled levels with disinflation.
2. ECI wage YoY **<=3.5%**, and its change over two quarters **<=-0.50 percentage points**.
3. Ten-year expected inflation **<=2.5%**, with its change over three observation months **<=0**.

These are round, interpretable, unfit thresholds, frozen before returns. No weights or threshold grid.
Below the existing "high" CPI threshold is only an operational proxy for control, not achievement of
the Fed's 2% PCE objective.
Missing required inputs or transformations block activation; missing productivity does not.
Productivity YoY and wage-minus-productivity growth are descriptive context, not measured unit labor costs.

Official contemporaneous statement text, clocks and lineage are exported in `pause_communications.csv`;
later minutes are not treated as known at a pause. No validated
historical extraction of the requested communication concepts was established. Therefore this is
explicitly the **numerical-only** version; communications are deferred, not inferred from memory or
treated as an automatically satisfied fourth condition. Wage setting itself is not observed by ECI.

## Two allocations and execution

Both begin 100% in bills. Baseline switches to 100% duration after the first scheduled hold. The filter
remains in bills until the above conjunction is met, reevaluated at **every usable 10Y-CMT session close**
during hold-after-hiking. Activation is latched until a new hike. Any renewed hike returns both to bills;
an actual cut enters duration regardless of missing/failed numerical conditions. Easing and hold-after-
easing retain 100% duration; unknown/hiking retain 100% bills.

An observable close executes at the **next session close**, and earns only subsequent returns.
After-close/weekend events first enter a later observation close, then receive that same lag.
Charge **5bp times absolute duration-weight change**, including first entry; no separate bills fee.
A round trip costs 10bp. Net interval return is `(1-cost)*(1+gross)-1`; no forced final liquidation.

Primary target: existing synthetic **2Y**. Secondary: existing **8Y** (5Y/10Y interpolation).
Reuse daily re-entry par-bond returns and 91-day discount-bill-to-investment-yield financing with
calendar-day accrual/365 and compounding. These are modeled returns, not actual bond-index returns.

## Frozen evaluation

Freeze configuration and hashes of events, all numerical versions, market inputs, source manifest and
study cutoff before computing any returns. Reuse section 5.2's freeze/verify implementation. Changes
to configuration or inputs block computation; use a different output directory for a new declaration.

One primary comparison: **SYN2Y filter minus baseline full-path net cumulative return**. Also report
net excess over bills, drawdowns, turnover, duration exposure and every cycle, with no reset of the
actual cost/weight path at reporting boundaries. The reserved split is unchanged: whole cycles beginning
in 2015 or later; reserved, not blind out-of-sample, because previous studies exposed their outcomes.

Retrospective labels: time to next hike/cut/change, and renewed hike within **six calendar months** of
the pause. An observed renewed hike resolves the positive label early; absence is known only after
the whole window. Otherwise the outcome is right-censored. A cut does not terminate six-month follow-up.
No hike within six months is a finite-window outcome, not proof that tightening has permanently ended.
Outcomes and labels live in separate evaluation files and never enter signal construction.

For each pause, report filter entry delay (including entries forced by cuts), observed excess rally
missed while waiting, and numerical activations followed by renewed hikes within six months.
Unentered episodes retain censored delays. Descriptive 1/3/6-month duration excess returns enter one
session after the pause's first observation close and exit one session after the first close on/after
that decision date plus the horizon. Missing future data are censored, not filled.

Descriptive inflation strata reuse headline L1/M1: high >=3.5% with rising >0.30pp or falling <-0.30pp
three-month YoY change; other and unknown remain separate. Conditional daily returns are not
independent episodes. Inference uses paired complete-cycle net-return differences, at least **six
complete cycles and six input-informative complete cycles**, 2,000 bootstrap replications, seed 20261111.
Otherwise report insufficient evidence. No overlapping-month IID p-values or claims from unobserved
input periods. Full-sample operational performance must not be mistaken for economic signal validation.

## Run and outputs

```bash
PYTHONPATH=src python3 -m macrodb.cli ingest --series US.WAGES.ECI.PRIVATE.SA US.PRODUCTIVITY.NONFARM.SA US.INFLATION.EXPECTED.10Y.CLEVELAND
PYTHONPATH=src python3 -m macrodb.cli build-silver
PYTHONPATH=src:. python3 -m research.hiking_cycles
python3 -m pytest
```

Default output: `results/hiking_cycles/`. For a new input freeze:
`python3 -m research.hiking_cycles.run --out results/hiking_cycles_new`.
`FINDINGS.md` is the findings report; `spec_frozen.json` is the sole declared specification. Supporting
CSVs preserve candidate features, current publication availability, allocation decisions, daily trading
returns, per-cycle results, paired uncertainty, inflation descriptions, censored follow-up and waiting costs.
