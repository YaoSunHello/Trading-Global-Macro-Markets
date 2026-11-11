-- macrodb schema (DuckDB). Idempotent: every statement is CREATE ... IF NOT EXISTS.
-- Layers: ref_* (shared reference data), prov_* (provenance), bronze_*, silver_*.

------------------------------------------------------------------ reference
CREATE TABLE IF NOT EXISTS ref_provider (
    provider_id        VARCHAR PRIMARY KEY,
    name               VARCHAR NOT NULL,
    adapter            VARCHAR NOT NULL,            -- dotted path of adapter class
    base_url           VARCHAR,
    auth_type          VARCHAR NOT NULL DEFAULT 'none',   -- none | api_key | oauth | session
    auth_env_var       VARCHAR,
    rate_limit_per_min INTEGER,
    licence_note       VARCHAR,
    has_vintages       BOOLEAN NOT NULL DEFAULT FALSE,
    limitations        VARCHAR,
    is_enabled         BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS ref_frequency (
    frequency_id    VARCHAR PRIMARY KEY,            -- D W M Q A
    name            VARCHAR NOT NULL,
    periods_per_year DOUBLE NOT NULL
);

CREATE TABLE IF NOT EXISTS ref_unit (
    unit_id         VARCHAR PRIMARY KEY,
    name            VARCHAR NOT NULL,
    dimension       VARCHAR NOT NULL,               -- e.g. percent, usd, index, count, fx_rate
    to_base_factor  DOUBLE  NOT NULL DEFAULT 1.0    -- value_in_base = value * factor (same dimension only)
);

CREATE TABLE IF NOT EXISTS ref_field (
    field_id        VARCHAR PRIMARY KEY,            -- value open high low close adj_close volume ...
    description     VARCHAR,
    is_price_like   BOOLEAN NOT NULL DEFAULT FALSE  -- price-like fields must be > 0 (DQ check)
);

CREATE TABLE IF NOT EXISTS ref_instrument (
    instrument_id   VARCHAR PRIMARY KEY,
    name            VARCHAR NOT NULL,
    asset_class     VARCHAR,
    currency        VARCHAR,
    exchange        VARCHAR
);

CREATE TABLE IF NOT EXISTS ref_series (                -- canonical series
    series_id            VARCHAR PRIMARY KEY,
    name                 VARCHAR NOT NULL,
    description          VARCHAR,
    category             VARCHAR,
    frequency_id         VARCHAR NOT NULL REFERENCES ref_frequency(frequency_id),
    unit_id              VARCHAR NOT NULL REFERENCES ref_unit(unit_id),       -- canonical unit
    field_id             VARCHAR NOT NULL REFERENCES ref_field(field_id),
    instrument_id        VARCHAR REFERENCES ref_instrument(instrument_id),    -- NULL for macro series
    seasonal_adjustment  VARCHAR,
    is_event_driven      BOOLEAN NOT NULL DEFAULT FALSE,   -- observations only on change dates (e.g. policy rates)
    outlier_method       VARCHAR NOT NULL DEFAULT 'diff',   -- diff | logret | none
    outlier_threshold    DOUBLE  NOT NULL DEFAULT 8.0       -- robust z (MAD) threshold
);

CREATE TABLE IF NOT EXISTS ref_dataset (
    dataset_id      VARCHAR PRIMARY KEY,
    provider_id     VARCHAR NOT NULL REFERENCES ref_provider(provider_id),
    name            VARCHAR NOT NULL,
    url             VARCHAR,
    licence_note    VARCHAR
);

CREATE TABLE IF NOT EXISTS ref_provider_series (       -- provider-specific mapping
    provider_id       VARCHAR NOT NULL REFERENCES ref_provider(provider_id),
    source_series_id  VARCHAR NOT NULL,
    field_id          VARCHAR NOT NULL REFERENCES ref_field(field_id),
    series_id         VARCHAR NOT NULL REFERENCES ref_series(series_id),
    dataset_id        VARCHAR REFERENCES ref_dataset(dataset_id),
    native_unit_id    VARCHAR NOT NULL REFERENCES ref_unit(unit_id),
    native_frequency_id VARCHAR NOT NULL REFERENCES ref_frequency(frequency_id),
    priority          INTEGER NOT NULL DEFAULT 100,    -- lower = preferred
    pit_support       VARCHAR NOT NULL,                -- vintage | publication_ts | ingestion_only
    params            VARCHAR,                         -- JSON of adapter-specific parameters
    selection_notes   VARCHAR,                         -- alternatives considered, limitations
    PRIMARY KEY (provider_id, source_series_id, field_id)
);

------------------------------------------------------------------ provenance
CREATE SEQUENCE IF NOT EXISTS seq_response START 1;
CREATE SEQUENCE IF NOT EXISTS seq_bronze   START 1;

CREATE TABLE IF NOT EXISTS prov_batch (
    batch_id     VARCHAR PRIMARY KEY,
    started_at   TIMESTAMP NOT NULL,
    finished_at  TIMESTAMP,
    mode         VARCHAR NOT NULL,                 -- full | incremental
    status       VARCHAR NOT NULL,                 -- running | ok | partial | failed
    code_version VARCHAR,
    note         VARCHAR
);

CREATE TABLE IF NOT EXISTS prov_raw_response (
    response_id     BIGINT PRIMARY KEY,
    batch_id        VARCHAR NOT NULL REFERENCES prov_batch(batch_id),
    provider_id     VARCHAR NOT NULL REFERENCES ref_provider(provider_id),
    request_url     VARCHAR NOT NULL,              -- secrets redacted
    request_params  VARCHAR,                       -- JSON, secrets redacted
    http_status     INTEGER,
    fetched_at      TIMESTAMP NOT NULL,
    content_sha256  VARCHAR NOT NULL,
    content_type    VARCHAR,
    byte_size       BIGINT NOT NULL,
    archive_path    VARCHAR NOT NULL               -- relative to raw archive root
);

CREATE TABLE IF NOT EXISTS prov_ingestion_task (
    batch_id          VARCHAR NOT NULL REFERENCES prov_batch(batch_id),
    provider_id       VARCHAR NOT NULL REFERENCES ref_provider(provider_id),
    source_series_id  VARCHAR NOT NULL,
    status            VARCHAR NOT NULL,            -- ok | error | empty
    rows_fetched      INTEGER NOT NULL DEFAULT 0,
    rows_new          INTEGER NOT NULL DEFAULT 0,
    error             VARCHAR,
    warnings          VARCHAR,                     -- JSON list
    PRIMARY KEY (batch_id, provider_id, source_series_id)
);

------------------------------------------------------------------ bronze
-- Append-only. Never UPDATE or DELETE. Revisions are new rows.
CREATE TABLE IF NOT EXISTS bronze_observation (
    bronze_id         BIGINT PRIMARY KEY,
    provider_id       VARCHAR NOT NULL,
    source_series_id  VARCHAR NOT NULL,
    field_id          VARCHAR NOT NULL,
    obs_date_raw      VARCHAR,                     -- original date string
    observation_date  DATE,                        -- parsed (NULL if unparseable)
    observation_ts    TIMESTAMP,                   -- parsed timestamp when source has one
    value_raw         VARCHAR,                     -- original value representation
    value_num         DOUBLE,                      -- parsed numeric (NULL if not numeric)
    realtime_start    DATE,                        -- vintage: first date this value was current
    realtime_end      DATE,                        -- vintage: last date seen current (informational)
    published_at      TIMESTAMP,                   -- publication timestamp if provider gives one
    source_attrs      VARCHAR,                     -- JSON of source-side attributes (status flags etc.)
    ingested_at       TIMESTAMP NOT NULL,
    batch_id          VARCHAR NOT NULL REFERENCES prov_batch(batch_id),
    response_id       BIGINT  NOT NULL REFERENCES prov_raw_response(response_id),
    row_hash          VARCHAR NOT NULL UNIQUE,     -- idempotency key
    FOREIGN KEY (provider_id, source_series_id, field_id)
        REFERENCES ref_provider_series(provider_id, source_series_id, field_id)
);
CREATE INDEX IF NOT EXISTS idx_bronze_series ON bronze_observation(provider_id, source_series_id, field_id, observation_date);

------------------------------------------------------------------ silver
-- Rebuildable, deterministic function of bronze + reference data + DQ config.
-- Exactly one Silver row per Bronze row (lineage: silver.bronze_id = bronze.bronze_id).
CREATE TABLE IF NOT EXISTS silver_observation (
    bronze_id         BIGINT PRIMARY KEY REFERENCES bronze_observation(bronze_id),
    series_id         VARCHAR NOT NULL REFERENCES ref_series(series_id),
    provider_id       VARCHAR NOT NULL,
    source_series_id  VARCHAR NOT NULL,
    field_id          VARCHAR NOT NULL,
    observation_date  DATE,                        -- normalised period start
    period_end        DATE,
    value             DOUBLE,                      -- canonical unit
    unit_id           VARCHAR NOT NULL REFERENCES ref_unit(unit_id),
    frequency_id      VARCHAR NOT NULL REFERENCES ref_frequency(frequency_id),
    availability_ts   TIMESTAMP,                   -- when this value was knowable (see basis)
    availability_basis VARCHAR NOT NULL,           -- vintage | publication_ts | ingestion_only
    pit_reliable      BOOLEAN NOT NULL,
    realtime_start    DATE,
    published_at      TIMESTAMP,
    ingested_at       TIMESTAMP NOT NULL,
    duplicate_class   VARCHAR NOT NULL,            -- unique | revision | duplicate_same_value | conflict
    dq_status         VARCHAR NOT NULL,            -- ok | suspect | missing | invalid
    dq_flags          VARCHAR[] NOT NULL,
    silver_run_id     VARCHAR NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_silver_series ON silver_observation(series_id, field_id, observation_date);

CREATE TABLE IF NOT EXISTS silver_run (
    silver_run_id  VARCHAR PRIMARY KEY,
    started_at     TIMESTAMP NOT NULL,
    config_json    VARCHAR NOT NULL,               -- thresholds etc: makes the run reproducible
    code_version   VARCHAR,
    series_rebuilt INTEGER,
    rows_written   BIGINT
);

------------------------------------------------------------------ policy announcements
CREATE SEQUENCE IF NOT EXISTS seq_policy_event START 1;
CREATE TABLE IF NOT EXISTS bronze_policy_event (
    policy_version_id BIGINT PRIMARY KEY,
    event_key         VARCHAR NOT NULL,
    announcement_date DATE NOT NULL,
    announcement_ts   TIMESTAMPTZ,
    known_at          TIMESTAMPTZ NOT NULL,
    scheduled         BOOLEAN NOT NULL,
    target_kind       VARCHAR NOT NULL CHECK (target_kind IN ('single', 'range')),
    target_low        DOUBLE NOT NULL,
    target_high       DOUBLE NOT NULL,
    timing_basis      VARCHAR NOT NULL,
    payload           VARCHAR NOT NULL,
    row_hash          VARCHAR NOT NULL UNIQUE,
    batch_id          VARCHAR NOT NULL REFERENCES prov_batch(batch_id),
    ingested_at       TIMESTAMP NOT NULL,
    CHECK (target_low <= target_high)
);
CREATE INDEX IF NOT EXISTS idx_policy_event ON bronze_policy_event(event_key, policy_version_id);
CREATE TABLE IF NOT EXISTS prov_policy_event_source (
    policy_version_id BIGINT NOT NULL REFERENCES bronze_policy_event(policy_version_id),
    source_role       VARCHAR NOT NULL,
    response_id       BIGINT NOT NULL REFERENCES prov_raw_response(response_id),
    PRIMARY KEY (policy_version_id, source_role)
);
CREATE TABLE IF NOT EXISTS prov_policy_target_lineage (
    policy_version_id BIGINT NOT NULL REFERENCES bronze_policy_event(policy_version_id),
    bronze_id         BIGINT NOT NULL REFERENCES bronze_observation(bronze_id),
    PRIMARY KEY (policy_version_id, bronze_id)
);
CREATE TABLE IF NOT EXISTS prov_policy_exclusion (
    batch_id          VARCHAR NOT NULL REFERENCES prov_batch(batch_id),
    announcement_date DATE NOT NULL,
    payload           VARCHAR NOT NULL
);
