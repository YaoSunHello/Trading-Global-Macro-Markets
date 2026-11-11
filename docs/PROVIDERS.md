# Providers: selection record, status and limitations

Status reflects what was **verified on 2026-11-10** by live requests (ECB, Treasury FiscalData, Yahoo, Stooq) or
by parser tests against recorded payload shapes (FRED). Free-tier limits quoted for providers that were not
exercised live are from memory of their public documentation and must be re-checked before relying on them.

| Provider | Status | Auth | Rate limit (configured) | Vintages | History / frequencies | Licence / terms |
|---|---|---|---|---|---|---|
| **FRED/ALFRED** | Implemented, enabled, **live-verified** (series with >2000 vintage dates fall back to current values only) | Free API key (`FRED_API_KEY`) | 120/min | **Yes** (ALFRED) | Decades; D/W/M/Q/A | FRED API ToU; some series carry third-party copyright |
| **ECB Data Portal** | Implemented, enabled, **live-verified** | none | 60/min | No | 1990s+; D/M/… | Reuse with acknowledgement |
| **US Treasury FiscalData** | Implemented, enabled, **live-verified** | none | 60/min | No | 2001+ (avg interest rates); monthly | Public domain |
| **Yahoo Finance** | Implemented, **disabled by default**, live-verified | none | 30/min | No | Decades; daily | Personal use only; unofficial endpoint; may break/block |
| **Stooq** | Implemented, **disabled**; **currently unusable** | `STOOQ_API_KEY` (if one is obtainable) | 20/min | No | daily | — |
| BLS, BEA | Not implemented (adapters welcome) | free key | — | No | — | Public domain |
| Bank of England | Not implemented | none (IADB CSV) | — | No | — | Open Government Licence |
| IG | Not implemented | account + API key | per-account allowances | No | historical prices within weekly data-point allowance | Broker terms |
| Trading 212 | Not implemented | API key | strict | No | **account/transaction data**, not market history | Broker terms |

## Findings that shaped the design

* **Stooq** (probed 2026-11-10): `stooq.com/q/d/l/` returns an HTML page running a JavaScript proof-of-work
  challenge, not CSV. The adapter detects HTML and raises `ProviderError` rather than storing it. It is wired and
  tested for the CSV format so it works if/when access returns.
* **Yahoo**: the adapter calls the same unofficial chart endpoint as yfinance and archives the raw JSON
  (yfinance itself does not expose raw responses). `adj_close` is restated by Yahoo after dividends/splits; each
  restatement is appended as a new Bronze row (visible as `revision` in Silver, with ingestion-time availability).
* **FRED/ALFRED vintages**: the adapter always requests the full realtime window, so every revision is stored. For
  observations older than a series' ALFRED archive start, `realtime_start` is the archive start, **not** the true
  first-release date — such early history is not truly point-in-time. FRED incremental updates are full refetches
  (clipping the realtime window would rewrite `realtime_start`); idempotent hashing makes this safe.
* **ECB / Treasury / Yahoo have no vintages or publication timestamps**: Silver marks them
  `availability_basis = ingestion_only`, `pit_reliable = FALSE`. Revisions made *before* first ingestion are
  invisible; later ones are captured (overlap window re-fetch).
* **Treasury FiscalData ≠ yield curve.** `US.TREASURY.AVG_RATE.NOTES` is the weighted-average coupon of
  outstanding notes, not a market yield. Market yields (CMT) come from FRED `DGS10`; Treasury's own Daily Par Yield
  Curve files are on home.treasury.gov and need a separate adapter.
* **Event-driven series** (ECB main refinancing rate returns change dates only) are flagged `is_event_driven`
  so coverage reports do not call them incomplete. They are never forward-filled.

## Selection record per dataset (alternatives & limitations)

Recorded in machine-readable form in `ref_provider_series.selection_notes` (from `config/catalog.yaml`). Summary:

| Canonical series | Chosen | Alternatives considered | Limitation |
|---|---|---|---|
| US CPI-U SA, UNRATE, PAYEMS | FRED/ALFRED (BLS data, vintages) | BLS API v2 (free key, no vintages) | ALFRED archive start |
| US real GDP | FRED/ALFRED (BEA data) | BEA API (free key, no vintages) | chained-dollar base year changes across vintages |
| Fed funds (monthly), 10Y CMT | FRED (H.15) | Treasury par-yield files (not yet an adapter) | — |
| ECB reference EURUSD, HICP, MRO | ECB | FRED `DEXUSEU` is the Fed H.10 noon rate — a *different* variable, deliberately not substituted | no vintages |
| SPY, S&P 500 | Yahoo (optional) → Stooq (alt) | IG (needs account) | unofficial/personal-use; Stooq blocked |

## Operational notes

* API keys come from environment variables named in `providers.yaml`; they are redacted from stored request
  URLs/params and never written to the archive.
* The HTTP client retries 429/5xx/network errors with exponential backoff (live run hit transient ECB 504s and
  recovered) and spaces calls to the configured rate limit.
* One failing series never aborts a batch; failures are recorded in `prov_ingestion_task` and the batch is
  `partial`/`failed`.
