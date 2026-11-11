# Onboarding

## A. Add a dataset (no code, no schema change)

1. Make sure the unit, frequency and field exist in `config/reference.yaml` (add a unit with its `dimension` and
   `to_base_factor` if needed).
2. Add an entry to `config/catalog.yaml`:

   ```yaml
   series:
     - series_id: US.RETAIL.SALES.SA          # canonical, provider-independent
       name: Advance Retail Sales, SA
       category: consumption
       frequency: M                            # canonical frequency (D W M Q A); not resampled
       unit: usd_mn                            # canonical unit
       seasonal_adjustment: SA
       # event_driven: true                    # only if the provider returns change dates only
       # outlier_method: diff | logret | none ; outlier_threshold: 8
       sources:
         - provider: fred
           source_series_id: RSAFS
           native_unit: usd_mn                 # must share a dimension with the canonical unit
           priority: 1                         # lower wins when several providers serve the series
           pit_support: vintage                # vintage | publication_ts | ingestion_only  (be honest)
           notes: "Census via ALFRED. Alternative: Census API. Limitation: ..."
   ```

   Market instruments use the `instruments:` block (one entry expands to `<id>.<field>` series).
3. `macrodb init && macrodb ingest --series US.RETAIL.SALES.SA && macrodb build-silver && macrodb report`.

Rules enforced at load time: unknown unit/frequency/field, unit-dimension mismatch, native≠canonical frequency
and invalid `pit_support` all fail loudly. Do not point a mapping at a *different* variable because it is easier
to download — add a separate canonical series instead.

## B. Add a provider

1. Subclass `ProviderAdapter` (`src/macrodb/providers/base.py`):

   ```python
   class MyAdapter(ProviderAdapter):
       provider_id = "my"
       incremental = "overlap"      # shared 30-day/catch-up window; 'full' for unsupported date filtering
       def fetch(self, req: SeriesRequest, since=None, until=None) -> FetchResult:
           r = self.http.get(URL, params={...})            # retries/rate limiting handled by HttpClient
           if r.status != 200: raise ProviderError(...)
           return FetchResult(pages=[FetchedPage(URL, params_without_secrets, r.status, r.content,
                                                 r.content_type, self.parse(r.content, req))])
   ```
   Adapters **never write to the database and never transform values.** Emit one `RawObs` per source fact:
   keep `value_raw` verbatim, parse `value_num`, set `realtime_start` / `published_at` only if the source really
   provides them, and never hide parse failures (leave `value_num=None`). Raise `ProviderError` for anything that
   is not the expected payload (HTML block pages, error JSON) — never store junk as data.
   Pass secrets only via `self.http.get(..., params=...)` and keep them out of `FetchedPage.params`.
2. Register it in `config/providers.yaml` (adapter path, auth env var, rate limit, `has_vintages`, licence note,
   limitations, `enabled`).
3. Map series to it in the catalog (section A). Source-specific parameters go in `params:`.
4. Test: add a parser test with a recorded payload and an ingest test using `FakeHttp` (see `tests/conftest.py`).

## C. Daily use

```bash
export FRED_API_KEY=...             # free: fred.stlouisfed.org/docs/api/api_key.html
macrodb init
macrodb ingest                      # enabled providers, including FOMC events; incremental
macrodb ingest --provider yahoo     # opt-in providers must be named (or --include-disabled)
macrodb build-silver                # only series with new Bronze rows; --full rebuilds all
macrodb report                      # data/reports/report.md + CSVs
macrodb export                      # Parquet snapshots
```

Routine ingestion requests the past 30 calendar days for existing series. After missed runs, the window
extends back to the last successful refresh (including empty responses). New series fetch full history.
Monthly, quarterly and annual series include their latest stored non-future observation period and align
the cutoff to the period start, so delayed releases are not skipped. These low-frequency windows can exceed
30 days; daily series with old/stale observations do not repeatedly download their full history.

FRED uses `observation_start` to restrict observation dates while retaining the full realtime window for
the requested observations, preserving original vintage dates. Revisions outside the refresh window are
not captured until an explicit `macrodb ingest --full`. Existing history is never deleted. Smaller windows
reduce downloaded rows and potentially pagination, not necessarily the number of requests or the risk of
provider blocking; configured rate limits and retry backoff still apply.

**Database first:** register and ingest required inputs before running research. The enabled `fomc`
provider adds policy announcements to central DuckDB, automatically ingesting its three FRED target-rate
prerequisites and building their Silver rows before event reconstruction. An explicit provider list
must include `fomc` to refresh events:

```bash
macrodb ingest --provider fred ecb treasury yahoo fomc
macrodb build-silver
macrodb report
macrodb policy-events --start 2020-03-01 --end 2020-03-31
```

Existing target series use the 30-day/catch-up window; discontinued DFEDTAR windows beyond its end
make no HTTP request. Calendar/feed and recent policy documents refresh at most once a day; historical
documents remain cached in central `prov_raw_response`. This is not intraday monitoring. `--full`
explicitly re-fetches historical documents. No active research-side cache is consulted.

For installations with the former policy-study cache, migrate once without network requests:

```bash
macrodb import-policy-cache data/policy_source_cache.json --as-of 2026-11-11
```

The old JSON/raw folder can remain as migration backup; they are not inputs to subsequent research.
Use `MacroDB.policy_events()`, `policy_target_levels()`, `policy_sources()` and `raw_response(response_id)`
for database-backed policy access.

### Explicitly approved CPI gap estimates

The absent October 2025 CPI observations have user-approved estimates: headline **324.654**, core
**330.730** (seasonally adjusted, 1982-84=100). They use `sqrt(September * November)`, rounded to three
decimals. These are imputations, not official observations or statistically identified true values.

```bash
macrodb estimate-month US.CPI.ALL_ITEMS.SA 2025-10-01 324.654
macrodb estimate-month US.CPI.CORE.SA 2025-10-01 330.730
macrodb query US.CPI.ALL_ITEMS.SA US.CPI.CORE.SA --start 2025-10-01 --end 2025-10-01
macrodb report
macrodb export
```

The command requires a missing official month and validates the approved value against both adjacent
official inputs. Repeating it with unchanged inputs is idempotent. Estimates are appended to the
original FRED CPIAUCSL/CPILFESL Bronze series and built into ordinary Silver, with `ESTIMATED` flags,
input lineage and actual creation time. Archived JSON identifies a local user-approved imputation,
not an official release. Original missing versions are retained. No separate estimate source is used.
Normal reads now use estimates to fill gaps; request `include_estimates=False` or CLI
`--exclude-estimates` for official observations only.

New research `Inputs` reads include approved estimates by default. Historical decisions before estimate
creation remain unchanged; no estimate is backdated to October 2025 or invented as a BLS vintage.
Affected new inflation inputs/states carry estimated-history flags. Use
`Inputs(include_estimates=False)` for source-only research. Existing findings/frozen result files are
not regenerated; changed policy-study inputs still fail the freeze gate. To reproduce its original
source-only run, use `python3 -m research.policy_cycles.run --exclude-estimates`; an estimate-aware
policy run requires a separate `--out` directory.

```python
from macrodb import MacroDB
db = MacroDB()
db.get("US.UNEMPLOYMENT.RATE.SA", start="2015-01-01")                    # latest vintage, long format
db.get(["US.CPI.ALL_ITEMS.SA", "FX.EURUSD.ECB_REF"], wide=True)         # temporary wide view; NaNs kept
db.as_of("US.PAYROLLS.NONFARM.SA", "2020-06-05")                         # what was published by that day
db.vintages("US.GDP.REAL.SAAR", "2020-01-01")                           # every revision of one observation
db.get("SPY.close", provider="yahoo", quality="ok")                      # quality filter
db.pit_status()                                                          # which series can be trusted as-of
db.metadata("US.GDP.REAL.SAAR")
```

Defaults: `vintage="latest"`, `quality="usable"` (ok + suspect; missing/invalid hidden but stored), `pit="flag"`.
With no `provider`, each series is served by its single highest-priority provider (providers are never spliced).
Quality is applied after choosing the version, so a later "missing" restatement is not masked by an older value.
