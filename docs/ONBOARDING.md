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
       incremental = "overlap"      # 'overlap' (caller passes since=last-obs-overlap_days) or 'full'
       overlap_days = 30
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
macrodb ingest                      # enabled providers, incremental; --full to refetch everything
macrodb ingest --provider yahoo     # opt-in providers must be named (or --include-disabled)
macrodb build-silver                # only series with new Bronze rows; --full rebuilds all
macrodb report                      # data/reports/report.md + CSVs
macrodb export                      # Parquet snapshots
```

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
