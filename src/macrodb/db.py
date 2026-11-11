from __future__ import annotations

from importlib import resources
from pathlib import Path

import duckdb

from .settings import Settings


def connect(settings: Settings, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    settings.home.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(settings.db_path), read_only=read_only)
    if not read_only:
        init_schema(con)
    return con


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    ddl = resources.files("macrodb").joinpath("schema.sql").read_text()
    con.execute(ddl)


def export_parquet(con: duckdb.DuckDBPyConnection, settings: Settings) -> list[Path]:
    """Snapshot Bronze/Silver/reference tables to Parquet (Bronze partitioned by provider)."""
    out: list[Path] = []
    base = settings.parquet_dir
    for layer, table, part in [
        ("bronze", "bronze_observation", "provider_id"),
        ("silver", "silver_observation", "provider_id"),
    ]:
        d = base / layer
        d.mkdir(parents=True, exist_ok=True)
        con.execute(
            f"COPY {table} TO '{d}' (FORMAT PARQUET, PARTITION_BY ({part}), OVERWRITE_OR_IGNORE)"
        )
        out.append(d)
    ref = base / "reference"
    ref.mkdir(parents=True, exist_ok=True)
    for t in ["ref_provider", "ref_series", "ref_provider_series", "ref_unit", "ref_frequency",
              "ref_field", "ref_instrument", "ref_dataset"]:
        p = ref / f"{t}.parquet"
        con.execute(f"COPY {t} TO '{p}' (FORMAT PARQUET)")
        out.append(p)
    policy = base / "policy"
    policy.mkdir(parents=True, exist_ok=True)
    for table in ["bronze_policy_event", "prov_policy_event_source", "prov_policy_target_lineage",
                  "prov_policy_exclusion"]:
        p = policy / f"{table}.parquet"
        con.execute(f"COPY {table} TO '{p}' (FORMAT PARQUET)")
        out.append(p)
    return out
