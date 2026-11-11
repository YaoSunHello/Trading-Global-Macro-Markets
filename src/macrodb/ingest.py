from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

import duckdb
import pandas as pd

from . import __version__
from .archive import RawArchive
from .http import ProviderError
from .providers.base import FetchedPage, SeriesRequest
from .registry import ProviderRegistry
from .settings import Settings

log = logging.getLogger(__name__)

SECRET_PARAMS = {"api_key", "apikey", "key", "token"}


def _redact(params: dict) -> dict:
    return {k: ("***" if k.lower() in SECRET_PARAMS else v) for k, v in params.items()}


def row_hash(provider_id, source_series_id, o) -> str:
    """Idempotency key: identical source facts hash identically across re-ingestions; a changed value or
    a new vintage hashes differently and is appended (revisions are never overwritten)."""
    parts = [provider_id, source_series_id, o.field_id, o.obs_date_raw or "", o.value_raw if o.value_raw is not None else "\x00",
             o.realtime_start.isoformat() if o.realtime_start else "", o.published_at.isoformat() if o.published_at else ""]
    return hashlib.sha1("\x1f".join(parts).encode()).hexdigest()


class Ingester:
    """Provider -> raw archive -> Bronze. Never updates or deletes Bronze rows."""

    def __init__(self, con, settings: Settings, registry: ProviderRegistry, now=None):
        self.con, self.settings, self.registry = con, settings, registry
        self.archive = RawArchive(settings.raw_dir)
        self._now = now or (lambda: datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0))

    # ------------------------------------------------------------------ planning
    def _tasks(self, series_ids, providers, include_disabled):
        q = """SELECT ps.provider_id, ps.source_series_id, ps.field_id, ps.native_frequency_id, ps.params, p.is_enabled
               FROM ref_provider_series ps JOIN ref_provider p USING (provider_id)
               WHERE 1=1"""
        args: list = []
        if series_ids:
            q += f" AND ps.series_id IN ({','.join('?' * len(series_ids))})"
            args += list(series_ids)
        if providers:
            q += f" AND ps.provider_id IN ({','.join('?' * len(providers))})"
            args += list(providers)
        elif not include_disabled:
            q += " AND p.is_enabled"
        tasks: dict[tuple, SeriesRequest] = {}
        for pid, sid, fld, freq, params, _ in self.con.execute(q + " ORDER BY 1,2,3", args).fetchall():
            t = tasks.setdefault((pid, sid), SeriesRequest(pid, sid, [], freq, json.loads(params) if params else {}))
            t.fields.append(fld)
        return list(tasks.values())

    def _since(self, adapter, req: SeriesRequest, mode: str):
        if mode != "incremental" or adapter.incremental != "overlap":
            return None
        d = self.con.execute("SELECT max(observation_date) FROM bronze_observation WHERE provider_id=? AND source_series_id=?",
                             [req.provider_id, req.source_series_id]).fetchone()[0]
        return d - timedelta(days=adapter.overlap_days) if d else None

    # ------------------------------------------------------------------ run
    def run(self, series_ids=None, providers=None, mode: str = "incremental", include_disabled: bool = False,
            note: str | None = None) -> dict:
        if mode not in ("incremental", "full"):
            raise ValueError("mode must be incremental|full")
        batch_id = f"{self._now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"
        self.con.execute("INSERT INTO prov_batch VALUES (?,?,NULL,?,?,?,?)",
                         [batch_id, self._now(), mode, "running", __version__, note])
        summary = {"batch_id": batch_id, "tasks": 0, "ok": 0, "errors": 0, "rows_new": 0}
        for req in self._tasks(series_ids, providers, include_disabled):
            summary["tasks"] += 1
            r = self._run_task(batch_id, req, mode)
            summary["ok" if r["status"] != "error" else "errors"] += 1
            summary["rows_new"] += r["rows_new"]
        status = "ok" if summary["errors"] == 0 else ("failed" if summary["ok"] == 0 else "partial")
        self.con.execute("UPDATE prov_batch SET finished_at=?, status=? WHERE batch_id=?", [self._now(), status, batch_id])
        if summary["rows_new"]:
            self._mirror_batch_parquet(batch_id)
        summary["status"] = status
        return summary

    def _run_task(self, batch_id: str, req: SeriesRequest, mode: str) -> dict:
        warnings: list[str] = []
        fetched = new = 0
        try:
            adapter = self.registry.get(req.provider_id)
            res = adapter.fetch(req, since=self._since(adapter, req, mode))
            warnings += res.warnings
            for attempt in (1, 2):
                fetched = new = 0
                self.con.execute("BEGIN")
                try:
                    for page in res.pages:
                        n_f, n_n, w = self._store_page(batch_id, req, page)
                        fetched, new, warnings = fetched + n_f, new + n_n, warnings + w
                    self.con.execute("COMMIT")
                    break
                except Exception as e:
                    self.con.execute("ROLLBACK")
                    # a transient DuckDB InternalException was seen once on a large insert; retry once
                    if attempt == 1 and isinstance(e, duckdb.InternalException):
                        warnings.append("retried after transient DuckDB internal error")
                        continue
                    raise
            status, err = ("ok" if fetched else "empty"), None
        except Exception as e:      # one failing series must not abort the batch
            log.error("ingest failed %s/%s: %s", req.provider_id, req.source_series_id, e)
            status, err = "error", f"{type(e).__name__}: {e}"
            fetched = new = 0
        self.con.execute("INSERT INTO prov_ingestion_task VALUES (?,?,?,?,?,?,?,?)",
                         [batch_id, req.provider_id, req.source_series_id, status, fetched, new, err, json.dumps(warnings)])
        return {"status": status, "rows_new": new}

    def _store_page(self, batch_id: str, req: SeriesRequest, page: FetchedPage):
        now = self._now()
        rel, sha, size = self.archive.put(req.provider_id, page.content, page.content_type, now)
        rid = self.con.execute("SELECT nextval('seq_response')").fetchone()[0]
        self.con.execute("INSERT INTO prov_raw_response VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         [rid, batch_id, req.provider_id, page.url, json.dumps(_redact(page.params), default=str),
                          page.status, now, sha, page.content_type, size, rel])
        if not page.observations:
            return 0, 0, []
        df = pd.DataFrame([{
            "provider_id": req.provider_id, "source_series_id": req.source_series_id, "field_id": o.field_id,
            "obs_date_raw": o.obs_date_raw, "observation_date": o.observation_date, "observation_ts": o.observation_ts,
            "value_raw": o.value_raw, "value_num": o.value_num, "realtime_start": o.realtime_start,
            "realtime_end": o.realtime_end, "published_at": o.published_at,
            "source_attrs": json.dumps(o.source_attrs) if o.source_attrs else None,
            "row_hash": row_hash(req.provider_id, req.source_series_id, o)} for o in page.observations])
        for col in ("observation_date", "realtime_start", "realtime_end"):
            df[col] = df[col].astype(object)       # python dates: 9999-12-31 overflows pandas ns timestamps
        df["observation_ts"] = pd.to_datetime(df["observation_ts"])
        df["published_at"] = pd.to_datetime(df["published_at"])
        df["value_num"] = df["value_num"].astype("float64")
        warnings = []
        n_dup = int(df["row_hash"].duplicated().sum())
        if n_dup:
            df = df.drop_duplicates("row_hash")
            warnings.append(f"{n_dup} exact duplicate rows inside one payload collapsed (payload preserved in raw archive)")
        self.con.register("incoming", df)
        try:
            n_new = self.con.execute("""
                INSERT INTO bronze_observation
                SELECT nextval('seq_bronze'), provider_id, source_series_id, field_id, obs_date_raw,
                       CAST(observation_date AS DATE), observation_ts, value_raw, value_num,
                       CAST(realtime_start AS DATE), CAST(realtime_end AS DATE), published_at, source_attrs,
                       ?, ?, ?, row_hash
                FROM incoming WHERE row_hash NOT IN (SELECT row_hash FROM bronze_observation)
                """, [now, batch_id, rid]).fetchone()[0]
        finally:
            self.con.unregister("incoming")
        return len(page.observations), n_new, warnings

    def _mirror_batch_parquet(self, batch_id: str) -> None:
        """Immutable per-batch Parquet copy of the Bronze rows added in this batch."""
        d = self.settings.parquet_dir / "bronze_batches"
        d.mkdir(parents=True, exist_ok=True)
        self.con.execute(f"COPY (SELECT * FROM bronze_observation WHERE batch_id='{batch_id}') "
                         f"TO '{d / (batch_id + '.parquet')}' (FORMAT PARQUET)")
