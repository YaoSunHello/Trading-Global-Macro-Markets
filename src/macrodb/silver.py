from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pyarrow as pa

from . import __version__
from .providers.base import MISSING_MARKERS
from .timeutil import is_aligned, period_end, period_start

DEFAULT_CONFIG = {"outlier_min_points": 20, "mad_to_sigma": 0.6745, "ohlc_tolerance": 1e-9}
INVALID_FLAGS = {"BAD_DATE", "BAD_VALUE", "NONFINITE"}
INFO_FLAGS = {"PIT_INFO_MISSING"}      # availability notes: do not make a value "suspect"


def _status(flags) -> str:
    f = set(flags) - INFO_FLAGS | (set(flags) & INVALID_FLAGS) | ({"MISSING_VALUE"} & set(flags))
    return "invalid" if f & INVALID_FLAGS else "missing" if "MISSING_VALUE" in f else "suspect" if f else "ok"


def _vkeys(g: pd.DataFrame) -> set:
    """Comparable value identities of a group: the number, or the raw missing-marker text."""
    return {v if not pd.isna(v) else ("raw", r) for v, r in zip(g["value"], g["value_raw"])}


class SilverBuilder:
    """Bronze -> Silver. Deterministic and idempotent: each affected canonical series is rebuilt from
    Bronze + reference data + config (stored in silver_run.config_json). One Silver row per Bronze row;
    suspicious rows are flagged, never dropped."""

    def __init__(self, con, config: dict | None = None, now=None):
        self.con, self.config = con, {**DEFAULT_CONFIG, **(config or {})}
        self._now = now or (lambda: datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0))

    def pending_series(self) -> list[str]:
        """Series with Bronze rows lacking a Silver row."""
        return [r[0] for r in self.con.execute("""
            SELECT DISTINCT ps.series_id FROM bronze_observation b
            JOIN ref_provider_series ps USING (provider_id, source_series_id, field_id)
            WHERE NOT EXISTS (SELECT 1 FROM silver_observation s WHERE s.bronze_id = b.bronze_id)
            ORDER BY 1""").fetchall()]

    def build(self, series_ids: list[str] | None = None, full: bool = False) -> dict:
        if series_ids is None:
            series_ids = [r[0] for r in self.con.execute("SELECT series_id FROM ref_series ORDER BY 1").fetchall()] \
                if full else self.pending_series()
        run_id = f"{self._now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"
        rows = 0
        self.con.execute("BEGIN")
        try:
            self.con.execute("INSERT INTO silver_run VALUES (?,?,?,?,NULL,NULL)",
                             [run_id, self._now(), json.dumps(self.config, sort_keys=True), __version__])
            for sid in series_ids:
                rows += self._build_series(sid, run_id)
            if series_ids:
                self._ohlc_pass([r[0] for r in self.con.execute(
                    f"SELECT DISTINCT instrument_id FROM ref_series WHERE instrument_id IS NOT NULL "
                    f"AND series_id IN ({','.join('?' * len(series_ids))})", list(series_ids)).fetchall()])
            self.con.execute("UPDATE silver_run SET series_rebuilt=?, rows_written=? WHERE silver_run_id=?",
                             [len(series_ids), rows, run_id])
            self.con.execute("COMMIT")
        except Exception:
            self.con.execute("ROLLBACK")
            raise
        return {"silver_run_id": run_id, "series_rebuilt": len(series_ids), "rows_written": rows}

    # ------------------------------------------------------------------ per series
    def _build_series(self, series_id: str, run_id: str) -> int:
        meta = self.con.execute("""SELECT s.frequency_id, s.unit_id, u.to_base_factor, s.outlier_method, s.outlier_threshold
                                   FROM ref_series s JOIN ref_unit u ON u.unit_id = s.unit_id WHERE series_id=?""",
                                [series_id]).fetchone()
        freq, unit_id, canon_factor, method, threshold = meta
        df = self.con.execute("""
            SELECT b.bronze_id, b.provider_id, b.source_series_id, b.field_id, b.obs_date_raw, b.observation_date AS obs_date,
                   b.value_raw, b.value_num, b.realtime_start, b.published_at, b.ingested_at, b.source_attrs,
                   ps.pit_support, nu.to_base_factor AS native_factor, f.is_price_like
            FROM bronze_observation b
            JOIN ref_provider_series ps USING (provider_id, source_series_id, field_id)
            JOIN ref_unit nu ON nu.unit_id = ps.native_unit_id
            JOIN ref_field f ON f.field_id = b.field_id
            WHERE ps.series_id = ? ORDER BY b.bronze_id""", [series_id]).fetchdf()
        self.con.execute("DELETE FROM silver_observation WHERE series_id=?", [series_id])
        if df.empty:
            return 0

        flags: list[list[str]] = [[] for _ in range(len(df))]
        df["is_estimate"] = df.source_attrs.map(lambda a: bool(json.loads(a or "{}").get("is_estimate")))

        def flag(i, name):
            if name not in flags[i]:
                flags[i].append(name)

        # -- schema / missing-data checks, timestamp + unit normalisation
        obs = pd.to_datetime(df["obs_date"])
        value = df["value_num"].astype("float64").copy()
        norm_start, norm_end = [], []
        for i, (d, vraw, vnum) in enumerate(zip(obs, df["value_raw"], value)):
            if pd.isna(d):
                flag(i, "BAD_DATE")
                norm_start.append(pd.NaT); norm_end.append(pd.NaT)
            else:
                dd = d.date()
                norm_start.append(pd.Timestamp(period_start(dd, freq)))
                norm_end.append(pd.Timestamp(period_end(dd, freq)))
                if not is_aligned(dd, freq):
                    flag(i, "FREQ_MISALIGNED")
                if dd > df["ingested_at"].iloc[i].date():
                    flag(i, "FUTURE_DATE")
            raw_missing = vraw is None or str(vraw).strip() in MISSING_MARKERS
            if raw_missing:
                flag(i, "MISSING_VALUE")
            elif pd.isna(vnum):
                flag(i, "BAD_VALUE")
            elif not math.isfinite(vnum):
                flag(i, "NONFINITE"); value.iloc[i] = np.nan
        value = value * (df["native_factor"] / canon_factor)
        df["period_start"], df["period_end"], df["value"] = norm_start, norm_end, value

        # -- availability (point-in-time) basis
        avail, reliable = [], []
        for i, r in enumerate(df.itertuples()):
            ts = None
            if r.is_estimate:
                flag(i, "ESTIMATED")
            elif r.pit_support == "vintage" and not pd.isna(r.realtime_start):
                ts = pd.Timestamp(r.realtime_start)
            elif r.pit_support == "publication_ts" and not pd.isna(r.published_at):
                ts = r.published_at
            if ts is None:
                if r.pit_support != "ingestion_only":
                    flag(i, "PIT_INFO_MISSING")
                ts, ok = r.ingested_at, False
            else:
                ok = True
            avail.append(ts); reliable.append(ok)
        df["availability_ts"], df["pit_reliable"] = avail, reliable
        df["availability_basis"] = np.where(df["pit_reliable"], df["pit_support"], "ingestion_only")

        # -- duplicate classification within (provider, source series, field, normalised period)
        df["dup_class"] = "unique"
        key = ["provider_id", "source_series_id", "field_id", "period_start"]
        for _, g in df[df["period_start"].notna() & ~df.is_estimate].groupby(key, sort=False):
            if len(g) < 2:
                continue
            if len(_vkeys(g)) == 1:
                df.loc[g.index[1:], "dup_class"] = "duplicate_same_value"
                continue
            df.loc[g.index, "dup_class"] = "revision"
            for _, same_ts in g.groupby("availability_ts"):
                if len(_vkeys(same_ts)) > 1:
                    df.loc[same_ts.index, "dup_class"] = "conflict"
                    for ix in same_ts.index:
                        flag(df.index.get_loc(ix), "DUPLICATE_CONFLICT")

        # -- value-sanity checks
        for i, r in enumerate(df.itertuples()):
            if r.is_price_like and not pd.isna(r.value) and r.value <= 0:
                flag(i, "NONPOSITIVE_PRICE")
            if r.field_id == "volume" and not pd.isna(r.value) and r.value < 0:
                flag(i, "NEGATIVE_VOLUME")

        self._outliers(df, self._latest_idx(df[~df.is_estimate]), method, threshold, flag)

        status = [_status(f) for f in flags]

        out = pd.DataFrame({
            "bronze_id": df["bronze_id"], "series_id": series_id, "provider_id": df["provider_id"],
            "source_series_id": df["source_series_id"], "field_id": df["field_id"],
            "observation_date": df["period_start"], "period_end": df["period_end"], "value": df["value"],
            "unit_id": unit_id, "frequency_id": freq, "availability_ts": pd.to_datetime(df["availability_ts"]),
            "availability_basis": df["availability_basis"], "pit_reliable": df["pit_reliable"],
            "realtime_start": pd.to_datetime(df["realtime_start"]), "published_at": pd.to_datetime(df["published_at"]),
            "ingested_at": df["ingested_at"], "duplicate_class": df["dup_class"], "dq_status": status,
            "silver_run_id": run_id})
        # explicit list<string> type: DuckDB cannot infer it when every flag list is empty
        tbl = pa.Table.from_pandas(out, preserve_index=False).append_column(
            "dq_flags", pa.array([sorted(f) for f in flags], type=pa.list_(pa.string())))
        self.con.register("silver_in", tbl)
        try:
            self.con.execute("""INSERT INTO silver_observation
                SELECT bronze_id, series_id, provider_id, source_series_id, field_id, CAST(observation_date AS DATE),
                       CAST(period_end AS DATE), value, unit_id, frequency_id, availability_ts, availability_basis,
                       pit_reliable, CAST(realtime_start AS DATE), published_at, ingested_at, duplicate_class,
                       dq_status, dq_flags, silver_run_id FROM silver_in""")
        finally:
            self.con.unregister("silver_in")
        return len(out)

    @staticmethod
    def _latest_idx(df: pd.DataFrame) -> pd.Index:
        """Index of the latest-available version of each (provider, source series, field, period)."""
        d = df[df["period_start"].notna()].assign(_b=df["bronze_id"])
        d = d.sort_values(["availability_ts", "_b"])
        return d.groupby(["provider_id", "source_series_id", "field_id", "period_start"], sort=False).tail(1).index

    def _ohlc_pass(self, instrument_ids: list[str]) -> None:
        """Cross-field check (needs the open/high/low/close series of one instrument together): flag bars where
        high < max(open, close, low) or low > min(open, close, high), on the latest version of each bar.
        Idempotent: recomputes the flag from scratch for each instrument."""
        tol = self.config["ohlc_tolerance"]
        for ins in instrument_ids:
            d = self.con.execute("""SELECT s.bronze_id, s.provider_id, s.source_series_id, s.field_id, s.observation_date,
                                           s.value, s.availability_ts, s.dq_flags
                                    FROM silver_observation s JOIN ref_series r USING (series_id)
                                    WHERE r.instrument_id = ? AND s.field_id IN ('open','high','low','close')""", [ins]).fetchdf()
            if d.empty:
                continue
            d["flags"] = d["dq_flags"].map(list)
            lat = d[d["value"].notna()].sort_values(["availability_ts", "bronze_id"]) \
                .groupby(["provider_id", "source_series_id", "field_id", "observation_date"]).tail(1)
            piv = lat.pivot_table(index=["provider_id", "source_series_id", "observation_date"], columns="field_id",
                                  values="value", aggfunc="last").dropna(subset=["open", "high", "low", "close"], how="any") \
                if {"open", "high", "low", "close"} <= set(lat["field_id"]) else pd.DataFrame()
            bad = set()
            if len(piv):
                m = (piv["high"] < piv[["open", "close", "low"]].max(axis=1) - tol) | \
                    (piv["low"] > piv[["open", "close", "high"]].min(axis=1) + tol)
                bad = set(piv.index[m])
            latest_ids = set(lat["bronze_id"])
            updates = []
            for r in d.itertuples():
                new = [f for f in r.flags if f != "OHLC_INCONSISTENT"]
                if r.bronze_id in latest_ids and (r.provider_id, r.source_series_id, r.observation_date) in bad:
                    new = sorted(new + ["OHLC_INCONSISTENT"])
                if new != r.flags:
                    updates.append((new, _status(new), int(r.bronze_id)))
            if updates:
                self.con.executemany("UPDATE silver_observation SET dq_flags=?, dq_status=? WHERE bronze_id=?", updates)

    def _outliers(self, df, latest, method, threshold, flag):
        if method == "none":
            return
        d = df.loc[latest]
        d = d[d["value"].notna()]
        for _, g in d.groupby(["provider_id", "source_series_id", "field_id"], sort=False):
            g = g.sort_values("period_start")
            v = g["value"].to_numpy(dtype=float)
            if method == "logret":
                with np.errstate(divide="ignore", invalid="ignore"):
                    ch = np.diff(np.where(v > 0, np.log(np.where(v > 0, v, 1.0)), np.nan))
            else:
                ch = np.diff(v)
            ok = ch[np.isfinite(ch)]
            if len(ok) < self.config["outlier_min_points"]:
                continue
            med = np.median(ok)
            mad = np.median(np.abs(ok - med))
            scale = mad / self.config["mad_to_sigma"] if mad > 0 else 1.253314 * np.mean(np.abs(ok - med))
            if scale <= 0:
                continue
            z = np.abs(ch - med) / scale
            for pos in np.where(np.isfinite(z) & (z > threshold))[0]:
                flag(df.index.get_loc(g.index[pos + 1]), "OUTLIER")
