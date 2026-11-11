# macrodb — historical financial & economic database

Provider-agnostic, free-data-first database for quantitative research. DuckDB + Parquet,
Bronze → Silver (+ shared reference data). **Gold, signals, features and backtests are out of scope.**

> The database defines the data. Provider adapters determine how to acquire it. Downstream research determines how to use it.

```bash
python3 -m pip install -e '.[dev]'     # or: PYTHONPATH=src
macrodb init && macrodb ingest --provider ecb treasury && macrodb build-silver && macrodb report
python3 -m pytest                       # 97 tests, no network needed
```

| Doc | Contents |
|---|---|
| [docs/SCHEMA.md](docs/SCHEMA.md) | ER diagram, table semantics, point-in-time model, DQ flags |
| [docs/PROVIDERS.md](docs/PROVIDERS.md) | provider status, selection record, **limitations** |
| [docs/ONBOARDING.md](docs/ONBOARDING.md) | add a dataset / add a provider / daily use / Python API |

Layout: `config/` (providers, reference, catalog) · `src/macrodb/` (schema.sql, providers/, ingest, silver, access,
reports, cli) · `tests/` · `data/` (gitignored: DuckDB, raw archive, Parquet, reports).

## Deliverable map

1. Schema docs → `docs/SCHEMA.md` · 2. Reference tables → `ref_*` · 3. Bronze → `bronze_observation` ·
4. Silver → `silver_observation` · 5. Adapters → `providers/` (FRED/ALFRED, ECB, Treasury, Yahoo, Stooq) ·
6. Registry → `config/providers.yaml`, `registry.py` · 7. Raw archive → `archive.py`, `prov_raw_response` ·
8. Access → `MacroDB` · 9. Point-in-time → `MacroDB.as_of/vintages`, `availability_*` · 10. Reports → `reports.py` ·
11. Tests → `tests/` · 12. Onboarding → `docs/ONBOARDING.md`.

## Known limitations (details in docs/PROVIDERS.md)

* FRED/ALFRED adapter is live-verified (key via `.env`/`FRED_API_KEY`). Long daily series (>2000 vintage dates, e.g. DGS10) are stored as current values only, without vintages.
* Stooq is currently blocked by a JS challenge; Yahoo is unofficial/personal-use. Both are disabled by default.
* IG, Trading 212, BLS, BEA, Bank of England adapters are not implemented.
* Only FRED/ALFRED provides true vintages; other providers are point-in-time from first ingestion only and are
  flagged `pit_reliable = FALSE`.
* Daily completeness uses weekdays, ignoring exchange holidays.
* Single-writer DuckDB; no concurrent ingestion.

## Inflation-state study (Coding Task 3)

`research/inflation_states/` reframes the question from "predict Treasury returns" to "can inflation level and momentum
states be detected in real time, how stable are they, and do Treasury outcomes differ across them". The earlier factor-vs-Treasury-return forecasting work was removed as irrelevant to section 5.1. Methodology and hypotheses: `docs/INFLATION_STATES.md`.

```bash
PYTHONPATH=src:. python3 -m research.inflation_states          # freeze definitions -> detection -> outcomes -> figures
PYTHONPATH=src:. python3 -m research.inflation_states.report   # results/inflation_states/FINDINGS.md + hypothesis_scorecard.csv
```

Outputs are in `results/inflation_states/` (state history with availability provenance, detection-quality and robustness
tables, conditional Treasury outcomes, drawdown episodes, figures, `FINDINGS.md`). Definitions are frozen and hashed
(`spec_frozen.json`) before outcomes are computed; the outcome stage refuses to run if they change.

## Policy-cycle study (section 5.2)

`research/policy_cycles/` reconstructs official scheduled decisions and intermeeting target changes from
February 1994, classifies four real-time policy states, and evaluates model-estimated 2Y/8Y forward excess
returns plus one fixed long-only 8Y-duration-versus-bills rule. Sources, timing assumptions, costs, cycle
inference limits, the reserved split and the single inflation comparison are documented in
[docs/POLICY_CYCLES.md](docs/POLICY_CYCLES.md). Findings: `results/policy_cycles/FINDINGS.md`.

```bash
PYTHONPATH=src python3 -m macrodb.cli ingest --provider fred fomc
PYTHONPATH=src python3 -m macrodb.cli build-silver
PYTHONPATH=src:. python3 -m research.policy_cycles
```

Policy target series and source-backed FOMC events are ingested centrally by `macrodb` before research.
The study reads DuckDB only; result CSVs are audit exports, not standalone input datasets.

## Hiking-cycle completion study (section 5.3)

`research/hiking_cycles/` compares buying duration at the first scheduled hold with one frozen,
numerical-only completion filter using real-time CPI, ECI wages and long-term expected inflation.
Missing required inputs block activation; communications classification is explicitly deferred.
Methodology: [docs/HIKING_CYCLES.md](docs/HIKING_CYCLES.md).
Findings and frozen inputs: `results/hiking_cycles/`.

```bash
PYTHONPATH=src:. python3 -m research.hiking_cycles
```
