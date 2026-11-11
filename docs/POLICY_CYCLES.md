# Section 5.2: policy cycles

This is one fixed, descriptive US policy-cycle study from February 1994, not an optimized strategy.

## Sources and reconstruction

`src/macrodb/policy.py` indexes official Fed historical year pages and the current
FOMC calendar, supplemented by the official monetary-policy feed for recent intermeeting statements.
It includes scheduled decisions with unchanged targets and target-changing
intermeeting announcements. Cancelled meetings and non-rate communications/liquidity announcements are
excluded. The September 15, 2003 communications-review meeting is not a scheduled rate decision; the
[August 12 minutes](https://www.federalreserve.gov/fomc/minutes/20030812.htm) distinguish it from the
September 16 scheduled meeting.

Statement dates, not deliberation or effective dates, date announcements. FRED `DFEDTAR` and
`DFEDTARL`/`DFEDTARU` supply independently source-backed numerical levels, using the last daily level by
announcement date +1 day. Every effective target change must match an announcement within three days.
This is a historical reconstruction, not a claim that the FRED record was available at announcement time.
Single targets retain a single value and equal bounds; ranges retain both endpoints from December 16, 2008.

Stated release clocks are retained in New York time with DST. Missing clocks remain missing.
Date-only statements and pre-announcement-of-holds-era scheduled decisions inferred from meeting dates,
minutes and unchanged targets become usable conservatively at the following calendar-day midnight.
No universal 14:00 release time is assumed. These timing assumptions are flagged separately from verified
clocks. All source inputs are stored in central `data/macrodb.duckdb`: scalar targets in Bronze/Silver;
events in `bronze_policy_event`; document and target lineage in `prov_policy_event_source` and
`prov_policy_target_lineage`. Downloaded bodies use the standard `data/raw/fomc/` and `data/raw/fred/`
archives and `prov_raw_response` metadata. Recent documents refresh at most daily, historical ones
remain cached, and explicit `--full` re-fetches them. A newly announced change awaiting numerical
target updates is reported as an ingestion error, not silently classified as a hold.
The research reads `MacroDB` only; `policy_events.csv`, `target_level_validation.csv` and
`source_manifest.csv` under results are audit exports, never research input files.

## States, cycles and execution

* Initial direction is unknown; no pre-1994 cycle seed.
* Midpoint increases/decreases establish hiking/easing and reset consecutive holds and time since change.
* Only a subsequent scheduled decision leaving both target endpoints unchanged establishes
  hold-after-hiking/easing. An unchanged intermeeting communication does not establish a hold.
* Representation/range-width changes with unchanged midpoint do not invent a policy direction.
* A new hike after easing begins a whole cycle. Subsequent hikes and holds do not create new cycles.
  The cycle includes its easing phase, ending at the next such hike. The final cycle is marked ongoing.
* ZLB means target upper bound <=0.25%. It and inflation are reporting flags only.

Use the existing usable daily 10Y CMT session calendar. A state is observed at a session's 16:00 ET close;
the fixed allocation executes at the next session close and earns only subsequent interval returns.
After-close/weekend announcements first enter a later session close, then receive the one-session lag.
Monthly forward outcomes use the existing `Calendar(lag=1)`: month-end decision, next-session entry,
and similarly lagged exits 1, 3 and 6 formation months later.

## Targets and one strategy

SYN2Y uses 2Y CMT. SYN8Y reuses linear 5Y/10Y interpolation and the existing daily par-bond return model:
semiannual coupons, calendar-day accrual/365, daily re-entry at par. Both are model-estimated, not observed
Treasury index returns; actual roll-down and instrument/execution details are omitted.

Bills reuse the existing 91-day discount-basis-to-investment-yield conversion and compounded
calendar-day accrual at the start-interval rate. Excess returns are duration total return minus bill
total return over identical windows, not wealth ratios or annualized horizon returns.

The single allocation is 100% SYN8Y in hold-after-hiking, easing and hold-after-easing; 100% bills in
hiking/unknown. Charge 5bp times absolute duration-weight turnover, including initial entry, with no
duplicate fee on bills. A full round trip costs 10bp. No forced final liquidation is assumed.
Net interval return is `(1 - transaction_cost) * (1 + gross_return) - 1`.
Compare with duration buy-and-hold (initial 5bp) and bills (no duration cost), preserving the same
full-path trades when reporting splits. Zero terminal yields use the par-bond formula's finite limit.

## Freeze, evidence and splits

`spec_frozen.json` hashes the entire declared configuration and event/validation/market/CPI inputs
before Treasury outcomes. Existing freezes cannot be silently replaced. Changes to configuration,
input hashes or the frozen payload block the outcome stage.

Report months, distinct cycles and complete-cycle counts for each state/target/horizon and
design/reserved split; per-cycle outcomes are mandatory. Windows crossing a cycle boundary remain
descriptive but are excluded from inference. Equal-weight cycle-mean bootstrap intervals require six
complete cycles and 24 months per cell; overlapping monthly observations never substitute for cycles.
There are no IID-month p-values. Ongoing cycles cannot support inference.

Reserve whole cycles beginning in 2015 or later. Label them **reserved**, acknowledging prior exposure
to their outcomes; this is not pristine out-of-sample evidence.

Exactly one inflation comparison is declared: within hold-after-hiking, headline CPI high-and-rising
(YoY >=3.5%; three-month change in YoY >0.30pp) versus all other known inflation states, SYN8Y/3m only.
Reuse existing ALFRED as-of snapshots and raw fixed classifications. Unknown inflation is excluded.
Require 24 months and three complete cycles in each group, otherwise report insufficient evidence
without substituting another contrast. Neither inflation nor ZLB affects strategy weights.

## Running

From the project root, first enrich the database using the existing dependencies and `.env` FRED key:

```bash
PYTHONPATH=src python3 -m macrodb.cli ingest --provider fred fomc
PYTHONPATH=src python3 -m macrodb.cli build-silver
PYTHONPATH=src:. python3 -m research.policy_cycles
python3 -m pytest
```

To migrate an existing standalone cache once, offline:

```bash
PYTHONPATH=src python3 -m macrodb.cli import-policy-cache data/policy_source_cache.json --as-of 2026-11-11
```

The former JSON/raw folder is retained only as migration backup. All study reruns are database-only,
read-only and perform no network requests. `research.policy_cycles.events` now exports database inputs.
Results and the single findings report are in `results/policy_cycles/`. Updating inputs deliberately
invalidates the existing freeze; use a new output directory (`research.policy_cycles.run --out ...`)
for a separately declared database-backed run. The database migration preserved the original
configuration, input fingerprints and outcomes exactly.

Deferred: pre-1994 outcomes, extra maturities, additional strategies, expectations proxies and
term-premium models.
