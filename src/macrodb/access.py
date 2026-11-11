from __future__ import annotations

import warnings
from datetime import date, datetime, timedelta
from typing import Iterable, Sequence

import pandas as pd

from . import db as _db
from .settings import Settings

QUALITY_SETS = {"ok": ("ok",), "usable": ("ok", "suspect"), "all": ("ok", "suspect", "missing", "invalid")}
COLUMNS = ["series_id", "field_id", "observation_date", "value", "unit_id", "frequency_id", "provider_id",
           "source_series_id", "availability_ts", "availability_basis", "pit_reliable", "realtime_start",
           "published_at", "ingested_at", "duplicate_class", "dq_status", "dq_flags", "bronze_id"]


class PointInTimeWarning(UserWarning):
    """Raised (as a warning) when an as-of query returns rows whose availability time is not reliable."""


def _as_list(x) -> list | None:
    if x is None:
        return None
    return [x] if isinstance(x, str) else list(x)


class MacroDB:
    """Standardised read interface. Canonical output is LONG format; use `to_wide` for analysis.
    No automatic interpolation; approved estimates in original series remain explicitly flagged."""

    def __init__(self, settings: Settings | None = None, con=None, read_only: bool = False):
        self.settings = settings or Settings()
        self.con = con if con is not None else _db.connect(self.settings, read_only=read_only)

    def close(self):
        self.con.close()

    def policy_events(self, start=None, end=None) -> pd.DataFrame:
        """Latest reconstructed policy-event versions; source clock/assumption flags remain explicit."""
        where, args = [], []
        if start:
            where.append("announcement_date >= ?"); args.append(pd.Timestamp(start).date())
        if end:
            where.append("announcement_date <= ?"); args.append(pd.Timestamp(end).date())
        flt = "WHERE " + " AND ".join(where) if where else ""
        rows = self.con.execute(f"""
            SELECT payload FROM bronze_policy_event {flt}
            QUALIFY row_number() OVER (PARTITION BY event_key ORDER BY policy_version_id DESC) = 1
            ORDER BY announcement_date, known_at
        """, args).fetchall()
        import json
        return pd.DataFrame([json.loads(r[0]) for r in rows])

    def policy_target_levels(self, end=None) -> pd.DataFrame:
        from .policy import target_levels
        return target_levels(self.con, end)

    def policy_sources(self) -> pd.DataFrame:
        return self.con.execute("""
            SELECT r.response_id, r.provider_id, r.request_url AS url, r.request_params AS params,
                   r.archive_path, r.content_sha256 AS sha256, r.fetched_at
            FROM prov_raw_response r
            WHERE r.provider_id='fomc' OR EXISTS (
                SELECT 1 FROM bronze_observation b WHERE b.response_id=r.response_id
                AND b.source_series_id IN ('DFEDTAR','DFEDTARL','DFEDTARU'))
            ORDER BY r.response_id
        """).fetchdf()

    def raw_response(self, response_id: int) -> bytes:
        from .archive import RawArchive
        row = self.con.execute("SELECT archive_path FROM prov_raw_response WHERE response_id=?", [response_id]).fetchone()
        if row is None:
            raise KeyError(f"unknown response: {response_id}")
        return RawArchive(self.settings.raw_dir).get(row[0])

    def estimates(self, series, start=None, end=None, as_of=None, provider=None, all_versions=False) -> pd.DataFrame:
        """Approved estimates with input lineage; availability is their actual creation time, in UTC."""
        ids = _as_list(series)
        where, args = [f"s.series_id IN ({','.join('?' * len(ids))})", "list_contains(s.dq_flags,'ESTIMATED')"], list(ids)
        for column, operator, bound in [("s.observation_date", ">=", start), ("s.observation_date", "<=", end)]:
            if bound is not None:
                where.append(f"{column} {operator} ?"); args.append(pd.Timestamp(bound).date())
        if as_of is not None:
            date_only = (isinstance(as_of, date) and not isinstance(as_of, datetime)) or (
                isinstance(as_of, str) and len(as_of) <= 10)
            when = pd.Timestamp(as_of)
            where.append("s.availability_ts < ?" if date_only else "s.availability_ts <= ?")
            args.append((when + timedelta(days=1) if date_only else when).to_pydatetime())
        if (providers := _as_list(provider)):
            where.append(f"s.provider_id IN ({','.join('?' * len(providers))})"); args += providers
        rank = "" if all_versions else (
            "QUALIFY row_number() OVER (PARTITION BY s.series_id,s.observation_date ORDER BY s.bronze_id DESC)=1")
        return self.con.execute(f"""
            SELECT {', '.join('s.' + column for column in COLUMNS)}, s.bronze_id AS estimate_id,
                   json_extract_string(b.source_attrs,'$.method') AS method
            FROM silver_observation s JOIN bronze_observation b USING(bronze_id)
            WHERE {' AND '.join(where)}
            {rank}
            ORDER BY s.series_id,s.observation_date,s.availability_ts,s.bronze_id
        """, args).fetchdf()

    # ------------------------------------------------------------------ metadata
    def list_series(self, category: str | None = None, provider: str | None = None) -> pd.DataFrame:
        q = """SELECT s.series_id, s.name, s.category, s.frequency_id, s.unit_id, s.field_id, s.instrument_id,
                      list(DISTINCT ps.provider_id ORDER BY ps.provider_id) AS providers
               FROM ref_series s LEFT JOIN ref_provider_series ps USING (series_id) WHERE 1=1"""
        args: list = []
        if category:
            q += " AND s.category = ?"; args.append(category)
        if provider:
            q += " AND EXISTS (SELECT 1 FROM ref_provider_series x WHERE x.series_id=s.series_id AND x.provider_id=?)"
            args.append(provider)
        return self.con.execute(q + " GROUP BY ALL ORDER BY 1", args).fetchdf()

    def providers(self) -> pd.DataFrame:
        return self.con.execute("SELECT * FROM ref_provider ORDER BY provider_id").fetchdf()

    def metadata(self, series_id: str) -> dict:
        s = self.con.execute("SELECT * FROM ref_series WHERE series_id=?", [series_id]).fetchdf()
        if s.empty:
            raise KeyError(f"unknown series '{series_id}'")
        maps = self.con.execute("""SELECT ps.*, p.name AS provider_name, p.licence_note, p.limitations
                                   FROM ref_provider_series ps JOIN ref_provider p USING (provider_id)
                                   WHERE series_id=? ORDER BY priority, provider_id""", [series_id]).fetchdf()
        return {"series": s.iloc[0].to_dict(), "sources": maps.to_dict("records"),
                "point_in_time": self.pit_status(series_id).to_dict("records")}

    def pit_status(self, series: str | Sequence[str] | None = None) -> pd.DataFrame:
        """Per (series, provider): can historical as-of queries be trusted? `pit_reliable_rows` is the share
        of stored rows with a real availability time (vintage or publication timestamp)."""
        ids = _as_list(series)
        flt = f"WHERE ps.series_id IN ({','.join('?' * len(ids))})" if ids else ""
        return self.con.execute(f"""
            SELECT ps.series_id, ps.provider_id, ps.pit_support,
                   ps.pit_support IN ('vintage','publication_ts') AS pit_supported,
                   count(s.bronze_id) AS rows,
                   avg(CASE WHEN s.pit_reliable THEN 1.0 ELSE 0.0 END) AS pit_reliable_rows,
                   count(*) FILTER (WHERE s.duplicate_class = 'revision') AS revision_rows
            FROM ref_provider_series ps
            LEFT JOIN silver_observation s USING (provider_id, source_series_id, field_id)
            {flt} GROUP BY ps.series_id, ps.provider_id, ps.pit_support ORDER BY 1, 2""", ids or []).fetchdf()

    # ------------------------------------------------------------------ data
    def get(self, series: str | Sequence[str], start=None, end=None, provider: str | Sequence[str] | None = None,
            field: str | Sequence[str] | None = None, as_of=None, vintage: str = "latest",
            quality: str | Iterable[str] = "usable", pit: str = "flag", wide: bool = False,
            include_estimates: bool = True) -> pd.DataFrame:
        """Fetch Silver observations (long format).

        start/end   filter on observation_date (inclusive).
        provider    restrict to provider(s). Default: for each series, the single highest-priority provider
                    that has data (providers are never mixed within a series).
        as_of       point-in-time: only versions available at/before this date or datetime.
        vintage     'latest' (default) | 'first' (first release) | 'all' (every stored version).
        quality     'ok' | 'usable' (ok+suspect, default) | 'all' | iterable of dq_status values. Applied
                    AFTER choosing the version, so a later 'missing' restatement hides an earlier value.
        pit         'flag' (default; rows carry pit_reliable and a warning is raised for as-of queries
                    touching unreliable availability) | 'strict' (drop rows without reliable availability).
        wide        return a wide table (observation_date x series) instead of long format.
        include_estimates fill missing latest values with labeled, approved estimates by default; all-version
                    queries include them for estimate-aware snapshots. First-release and strict PIT exclude them.
        """
        ids = _as_list(series)
        known = {r[0] for r in self.con.execute("SELECT series_id FROM ref_series").fetchall()}
        missing = [s for s in ids if s not in known]
        if missing:
            raise KeyError(f"unknown series: {missing}")
        if vintage not in ("latest", "first", "all"):
            raise ValueError("vintage must be latest|first|all")
        if pit not in ("flag", "strict"):
            raise ValueError("pit must be flag|strict")
        if isinstance(quality, str) and quality not in QUALITY_SETS:
            raise ValueError(f"quality must be one of {list(QUALITY_SETS)} or an iterable of statuses")
        statuses = QUALITY_SETS[quality] if isinstance(quality, str) else tuple(quality)

        where, args = [f"series_id IN ({','.join('?' * len(ids))})"], list(ids)
        if (f := _as_list(field)):
            where.append(f"field_id IN ({','.join('?' * len(f))})"); args += f
        if (p := _as_list(provider)):
            where.append(f"provider_id IN ({','.join('?' * len(p))})"); args += p
        if start is not None:
            where.append("observation_date >= ?"); args.append(pd.Timestamp(start).date())
        if end is not None:
            where.append("observation_date <= ?"); args.append(pd.Timestamp(end).date())
        if as_of is not None:
            ts = pd.Timestamp(as_of)
            date_only = (isinstance(as_of, date) and not isinstance(as_of, datetime)) or \
                (isinstance(as_of, str) and len(as_of) <= 10)
            # a bare date means "end of that day" (vintage dates are day-granular)
            where.append("availability_ts < ?" if date_only else "availability_ts <= ?")
            args.append((ts + timedelta(days=1) if date_only else ts).to_pydatetime())
        if pit == "strict":
            where.append("pit_reliable")
        where.append("observation_date IS NOT NULL")
        where.append("NOT list_contains(dq_flags,'ESTIMATED')")

        order = {"latest": "DESC", "first": "ASC"}.get(vintage)
        rank = (f"QUALIFY row_number() OVER (PARTITION BY series_id, provider_id, field_id, observation_date "
                f"ORDER BY availability_ts {order}, bronze_id {order}) = 1") if order else ""
        # explicit provider list -> no selection; otherwise one provider per series by priority
        sel = ""
        if not p:
            sel = """JOIN (SELECT series_id, provider_id FROM (
                        SELECT b.series_id, b.provider_id,
                               row_number() OVER (PARTITION BY b.series_id ORDER BY m.prio, b.provider_id) AS rn
                        FROM (SELECT DISTINCT series_id, provider_id FROM cand) b
                        JOIN (SELECT series_id, provider_id, min(priority) AS prio FROM ref_provider_series
                              GROUP BY 1, 2) m USING (series_id, provider_id)) WHERE rn = 1)
                     USING (series_id, provider_id)"""
        sql = f"""WITH cand AS (SELECT * FROM silver_observation WHERE {' AND '.join(where)}),
                       pick AS (SELECT cand.* FROM cand {sel})
                  SELECT {', '.join(COLUMNS)} FROM pick {rank}
                  ORDER BY series_id, field_id, observation_date, availability_ts, bronze_id"""
        df = self.con.execute(sql, args).fetchdf()
        if include_estimates and vintage != "first" and pit != "strict":
            from .estimates import fill_missing
            estimated = self.estimates(ids, start, end, as_of, provider, all_versions=vintage == "all")
            if (fields := _as_list(field)):
                estimated = estimated[estimated.field_id.isin(fields)]
            if not estimated.empty:
                df = pd.concat([df, estimated], ignore_index=True) if vintage == "all" else fill_missing(df, estimated)
                df = df.sort_values(["series_id", "field_id", "observation_date", "availability_ts", "bronze_id"])
        df = df[df["dq_status"].isin(statuses)].reset_index(drop=True)
        if as_of is not None and len(df) and not df["pit_reliable"].all():
            bad = sorted(df.loc[~df["pit_reliable"], "series_id"].unique())
            warnings.warn(f"as_of query includes series without reliable historical availability info "
                          f"(ingestion-time only): {bad}", PointInTimeWarning, stacklevel=2)
        return self.to_wide(df) if wide else df

    def vintages(self, series: str, observation_date=None, **kw) -> pd.DataFrame:
        """Every stored version of a series (optionally one observation date), oldest first."""
        df = self.get(series, vintage="all", quality="all", **kw)
        if observation_date is not None:
            df = df[df["observation_date"] == pd.Timestamp(observation_date)]
        return df.reset_index(drop=True)

    def as_of(self, series, as_of, **kw) -> pd.DataFrame:
        return self.get(series, as_of=as_of, **kw)

    @staticmethod
    def to_wide(df: pd.DataFrame, values: str = "value") -> pd.DataFrame:
        """Temporary wide view: index observation_date, one column per series (series.field when a series has
        several fields). Absent observations stay NaN; no filling or interpolation."""
        if df.empty:
            return pd.DataFrame()
        d = df.copy()
        multi = d.groupby("series_id")["field_id"].nunique().gt(1).any()
        d["col"] = d["series_id"] + ("|" + d["field_id"] if multi else "")
        if d.duplicated(["observation_date", "col"]).any():
            raise ValueError("multiple versions/providers per observation; use vintage='latest'/'first' and one provider")
        return d.pivot(index="observation_date", columns="col", values=values).sort_index()

    # ------------------------------------------------------------------ reports (see reports.py)
    def coverage_report(self, **kw) -> pd.DataFrame:
        from .reports import coverage_report
        return coverage_report(self.con, **kw)

    def quality_report(self, **kw) -> dict[str, pd.DataFrame]:
        from .reports import quality_report
        return quality_report(self.con, **kw)
