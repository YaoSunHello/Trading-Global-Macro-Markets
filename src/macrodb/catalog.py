from __future__ import annotations

import json
from pathlib import Path

import duckdb
import yaml

from .registry import ProviderRegistry

PRICE_FIELDS = ("open", "high", "low", "close", "adj_close")
PIT_VALUES = {"vintage", "publication_ts", "ingestion_only"}


def _upsert(con: duckdb.DuckDBPyConnection, table: str, pk: list[str], row: dict) -> None:
    """Insert, or update only the columns that changed. (DuckDB rejects ON CONFLICT DO UPDATE on rows that
    are referenced by foreign keys, even when nothing changes, hence read-compare-write.)"""
    where = " AND ".join(f"{k}=?" for k in pk)
    cols = list(row)
    cur = con.execute(f"SELECT {', '.join(cols)} FROM {table} WHERE {where}", [row[k] for k in pk]).fetchone()
    if cur is None:
        con.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", list(row.values()))
        return
    changed = {c: row[c] for c, old in zip(cols, cur) if old != row[c]}
    if not changed:
        return
    try:
        con.execute(f"UPDATE {table} SET {', '.join(f'{c}=?' for c in changed)} WHERE {where}",
                    [*changed.values(), *[row[k] for k in pk]])
    except duckdb.ConstraintException as e:
        raise ValueError(f"cannot change {sorted(changed)} of {table} {[row[k] for k in pk]}: key/FK columns of "
                         f"referenced reference rows are immutable (add a new series instead): {e}")


def sync_providers(con, registry: ProviderRegistry) -> None:
    for pid, c in registry.config.items():
        _upsert(con, "ref_provider", ["provider_id"], {
            "provider_id": pid, "name": c.get("name", pid), "adapter": c["adapter"],
            "base_url": c.get("base_url"), "auth_type": c.get("auth_type", "none"),
            "auth_env_var": c.get("auth_env_var"), "rate_limit_per_min": c.get("rate_limit_per_min"),
            "licence_note": c.get("licence_note"), "has_vintages": bool(c.get("has_vintages", False)),
            "limitations": c.get("limitations"), "is_enabled": bool(c.get("enabled", True))})


def sync_reference(con, path: Path) -> None:
    doc = yaml.safe_load(Path(path).read_text()) or {}
    for f in doc.get("frequencies", []):
        _upsert(con, "ref_frequency", ["frequency_id"], f)
    for u in doc.get("units", []):
        _upsert(con, "ref_unit", ["unit_id"], {"to_base_factor": 1.0, **u})
    for f in doc.get("fields", []):
        _upsert(con, "ref_field", ["field_id"], {"is_price_like": False, **f})


def _dimension(con, unit_id: str) -> tuple[str, float]:
    r = con.execute("SELECT dimension, to_base_factor FROM ref_unit WHERE unit_id=?", [unit_id]).fetchone()
    if r is None:
        raise ValueError(f"unknown unit '{unit_id}' (add it to reference.yaml)")
    return r


def _expand_instruments(doc: dict) -> list[dict]:
    """Instrument entries expand to one canonical series per field, e.g. SPY.close."""
    out = []
    for ins in doc.get("instruments", []):
        for f in ins["fields"]:
            unit = ("count" if f == "volume" else ins["price_unit"])
            out.append({
                "series_id": f"{ins['instrument_id']}.{f}", "name": f"{ins['name']} {f}",
                "category": ins.get("asset_class"), "frequency": "D", "unit": unit, "field": f,
                "instrument_id": ins["instrument_id"], "outlier_method": "logret" if f != "volume" else "none",
                "sources": [{**s, "native_unit": s.get("native_unit", unit if f != "volume" else "count")}
                            for s in ins["sources"] if f in s.get("fields", ins["fields"])],
            })
    return out


def sync_catalog(con, path: Path, registry: ProviderRegistry | None = None) -> dict:
    """Load catalog.yaml into ref_instrument / ref_series / ref_provider_series. Idempotent."""
    doc = yaml.safe_load(Path(path).read_text()) or {}
    for d in doc.get("datasets", []):
        _upsert(con, "ref_dataset", ["dataset_id"], {
            "dataset_id": d["dataset_id"], "provider_id": d["provider"], "name": d["name"],
            "url": d.get("url"), "licence_note": d.get("licence_note")})
    for ins in doc.get("instruments", []):
        _upsert(con, "ref_instrument", ["instrument_id"], {
            "instrument_id": ins["instrument_id"], "name": ins["name"], "asset_class": ins.get("asset_class"),
            "currency": ins.get("currency"), "exchange": ins.get("exchange")})
    n_series = n_map = 0
    for s in doc.get("series", []) + _expand_instruments(doc):
        unit_dim, _ = _dimension(con, s["unit"])
        _upsert(con, "ref_series", ["series_id"], {
            "series_id": s["series_id"], "name": s["name"], "description": s.get("description"),
            "category": s.get("category"), "frequency_id": s["frequency"], "unit_id": s["unit"],
            "field_id": s.get("field", "value"), "instrument_id": s.get("instrument_id"),
            "seasonal_adjustment": s.get("seasonal_adjustment"),
            "is_event_driven": bool(s.get("event_driven", False)),
            "outlier_method": s.get("outlier_method", "diff"),
            "outlier_threshold": float(s.get("outlier_threshold", 8.0))})
        n_series += 1
        for src in s.get("sources", []):
            if src.get("pit_support") is None and "provider" in src:
                pit = "vintage" if registry and registry.config.get(src["provider"], {}).get("has_vintages") else "ingestion_only"
            else:
                pit = src.get("pit_support")
            if pit not in PIT_VALUES:
                raise ValueError(f"{s['series_id']}: pit_support must be one of {PIT_VALUES}")
            if src.get("native_frequency", s["frequency"]) != s["frequency"]:
                raise ValueError(f"{s['series_id']}: native frequency differs from canonical frequency; "
                                 f"resampling is a research decision, not a Silver transformation")
            if _dimension(con, src["native_unit"])[0] != unit_dim:
                raise ValueError(f"{s['series_id']}: native unit {src['native_unit']} has a different "
                                 f"dimension than canonical unit {s['unit']}")
            _upsert(con, "ref_provider_series", ["provider_id", "source_series_id", "field_id"], {
                "provider_id": src["provider"], "source_series_id": src["source_series_id"],
                "field_id": s.get("field", "value"), "series_id": s["series_id"],
                "dataset_id": src.get("dataset"), "native_unit_id": src["native_unit"],
                "native_frequency_id": src.get("native_frequency", s["frequency"]),
                "priority": int(src.get("priority", 100)), "pit_support": pit,
                "params": json.dumps(src["params"]) if src.get("params") else None,
                "selection_notes": src.get("notes")})
            n_map += 1
    return {"series": n_series, "mappings": n_map}


def sync_all(con, settings, registry: ProviderRegistry) -> dict:
    sync_providers(con, registry)
    sync_reference(con, settings.reference_yaml)
    return sync_catalog(con, settings.catalog_yaml, registry)
