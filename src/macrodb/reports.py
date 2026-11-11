from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

GAP_DAYS = {"D": 4, "W": 10, "M": 40, "Q": 100, "A": 400}
STALE_DAYS = {"D": 7, "W": 21, "M": 75, "Q": 150, "A": 450}


def _expected(first: pd.Timestamp, last: pd.Timestamp, freq: str) -> int:
    if freq == "D":
        return int(np.busday_count(first.date(), (last + pd.Timedelta(days=1)).date()))
    if freq == "W":
        return (last - first).days // 7 + 1
    if freq == "M":
        return (last.year - first.year) * 12 + last.month - first.month + 1
    if freq == "Q":
        return ((last.year - first.year) * 12 + last.month - first.month) // 3 + 1
    return last.year - first.year + 1


def coverage_report(con, series_ids=None, as_of_today: date | None = None) -> pd.DataFrame:
    """Per (series, provider, field): historical coverage of the LATEST version of each observation.
    Business-day expectation for daily data ignores exchange holidays, so daily completeness can read a
    little under 100% for equities; gaps use a frequency-specific threshold."""
    today = pd.Timestamp(as_of_today or date.today())
    flt = f"WHERE series_id IN ({','.join('?' * len(series_ids))})" if series_ids else ""
    df = con.execute(f"""
        SELECT series_id, provider_id, field_id, frequency_id, observation_date, r.is_event_driven, dq_status, dq_flags,
               duplicate_class, ingested_at, pit_reliable, count(*) OVER (PARTITION BY series_id, provider_id, field_id) AS rows_all
        FROM silver_observation JOIN (SELECT series_id, is_event_driven FROM ref_series) r USING (series_id) {flt}
        QUALIFY row_number() OVER (PARTITION BY series_id, provider_id, field_id, observation_date
                                   ORDER BY availability_ts DESC, bronze_id DESC) = 1""", list(series_ids or [])).fetchdf()
    rev = con.execute("""SELECT series_id, provider_id, field_id,
                                count(*) FILTER (WHERE duplicate_class='revision') AS revision_rows,
                                count(DISTINCT observation_date) FILTER (WHERE duplicate_class='revision') AS revised_obs
                         FROM silver_observation GROUP BY ALL""").fetchdf().set_index(["series_id", "provider_id", "field_id"])
    rows = []
    for (sid, pid, fid), g in df.groupby(["series_id", "provider_id", "field_id"]):
        freq = g["frequency_id"].iloc[0]
        valid = g[g["dq_status"].isin(["ok", "suspect"])].sort_values("observation_date")
        d = valid["observation_date"]
        r = {"series_id": sid, "provider_id": pid, "field_id": fid, "frequency_id": freq,
             "n_obs": len(valid), "n_missing": int((g["dq_status"] == "missing").sum()),
             "n_invalid": int((g["dq_status"] == "invalid").sum()), "n_suspect": int((g["dq_status"] == "suspect").sum()),
             "pct_flagged": round(100 * float((g["dq_status"] != "ok").mean()), 2),
             "revised_obs": int(rev.loc[(sid, pid, fid), "revised_obs"]) if (sid, pid, fid) in rev.index else 0,
             "pit_reliable": bool(g["pit_reliable"].all()), "last_ingested_at": g["ingested_at"].max()}
        if len(d) and g["is_event_driven"].iloc[0]:     # change-date series: coverage statistics do not apply
            r.update(first_date=d.iloc[0].date(), last_date=d.iloc[-1].date(), is_stale=None)
        elif len(d):
            exp = _expected(d.iloc[0], d.iloc[-1], freq)
            gaps = d.diff().dt.days.dropna()
            r.update(first_date=d.iloc[0].date(), last_date=d.iloc[-1].date(), expected_obs=exp,
                     completeness_pct=round(100 * len(d) / exp, 2) if exp else np.nan,
                     n_gaps=int((gaps > GAP_DAYS[freq]).sum()), max_gap_days=int(gaps.max()) if len(gaps) else 0,
                     is_stale=bool((today - d.iloc[-1]).days > STALE_DAYS[freq]))
        rows.append(r)
    cols = ["series_id", "provider_id", "field_id", "frequency_id", "first_date", "last_date", "n_obs", "expected_obs",
            "completeness_pct", "n_gaps", "max_gap_days", "n_missing", "n_invalid", "n_suspect", "pct_flagged",
            "revised_obs", "pit_reliable", "is_stale", "last_ingested_at"]
    return pd.DataFrame(rows).reindex(columns=cols)


def quality_report(con, series_ids=None) -> dict[str, pd.DataFrame]:
    flt = f"WHERE series_id IN ({','.join('?' * len(series_ids))})" if series_ids else ""
    a = list(series_ids or [])
    status = con.execute(f"""SELECT series_id, provider_id, dq_status, count(*) AS rows FROM silver_observation {flt}
                             GROUP BY ALL ORDER BY 1, 2, 3""", a).fetchdf()
    flags = con.execute(f"""SELECT series_id, provider_id, flag, count(*) AS rows
                            FROM (SELECT series_id, provider_id, unnest(dq_flags) AS flag FROM silver_observation {flt})
                            GROUP BY ALL ORDER BY 1, 2, 4 DESC""", a).fetchdf()
    dups = con.execute(f"""SELECT series_id, provider_id, duplicate_class, count(*) AS rows FROM silver_observation {flt}
                           GROUP BY ALL ORDER BY 1, 2, 3""", a).fetchdf()
    ingest = con.execute("""SELECT t.batch_id, t.provider_id, t.source_series_id, t.status, t.rows_fetched, t.rows_new,
                                   t.error, t.warnings
                            FROM prov_ingestion_task t WHERE t.status <> 'ok' OR t.warnings <> '[]'
                            ORDER BY t.batch_id DESC, 2, 3""").fetchdf()
    return {"status": status, "flags": flags, "duplicates": dups, "ingestion_issues": ingest}


def policy_report(con) -> pd.DataFrame:
    return con.execute("""
        WITH latest AS (
            SELECT * FROM bronze_policy_event
            QUALIFY row_number() OVER (PARTITION BY event_key ORDER BY policy_version_id DESC) = 1
        )
        SELECT count(*) AS events,
               count(*) FILTER (WHERE scheduled) AS scheduled,
               count(*) FILTER (WHERE NOT scheduled) AS intermeeting,
               min(announcement_date) AS first_announcement,
               max(announcement_date) AS last_announcement,
               count(*) FILTER (WHERE timing_basis='statement_clock_time') AS verified_clocks,
               count(*) FILTER (WHERE timing_basis<>'statement_clock_time') AS conservative_date_only,
               (SELECT count(*) FROM prov_policy_event_source
                WHERE policy_version_id IN (SELECT policy_version_id FROM latest)) AS document_links,
               (SELECT count(*) FROM prov_policy_target_lineage
                WHERE policy_version_id IN (SELECT policy_version_id FROM latest)) AS target_links
        FROM latest
    """).fetchdf()


def _md(df: pd.DataFrame) -> str:
    if df.empty:
        return "_none_"
    cell = lambda v: "" if pd.isna(v) else str(v)
    lines = ["| " + " | ".join(df.columns) + " |", "|" + "---|" * len(df.columns)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


def write_reports(con, out_dir: Path, series_ids=None) -> list[Path]:
    """Write coverage + quality reports as CSV and one Markdown summary."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cov = coverage_report(con, series_ids)
    qr = quality_report(con, series_ids)
    policy = policy_report(con) if not series_ids else pd.DataFrame()
    estimate_filter = f"AND s.series_id IN ({','.join('?' * len(series_ids))})" if series_ids else ""
    estimates = con.execute(f"""
        SELECT s.series_id,s.observation_date,s.value,
               json_extract_string(b.source_attrs,'$.method') AS method,
               s.availability_ts AS created_at,s.bronze_id AS estimate_id,
               l.observation_date AS left_month,l.value_num AS left_value,
               r.observation_date AS right_month,r.value_num AS right_value
        FROM silver_observation s JOIN bronze_observation b USING(bronze_id)
        JOIN bronze_observation l ON l.bronze_id=CAST(json_extract_string(b.source_attrs,'$.left_bronze_id') AS BIGINT)
        JOIN bronze_observation r ON r.bronze_id=CAST(json_extract_string(b.source_attrs,'$.right_bronze_id') AS BIGINT)
        WHERE list_contains(s.dq_flags,'ESTIMATED')
        {estimate_filter}
        QUALIFY row_number() OVER (PARTITION BY s.series_id,s.observation_date ORDER BY s.bronze_id DESC)=1
        ORDER BY s.series_id,s.observation_date
    """, list(series_ids or [])).fetchdf()
    paths = []
    reports = {"coverage": cov, **{f"quality_{k}": v for k, v in qr.items()}}
    if not policy.empty:
        reports["policy_coverage"] = policy
    reports["approved_estimates"] = estimates
    for name, df in reports.items():
        p = out_dir / f"{name}.csv"
        df.to_csv(p, index=False)
        paths.append(p)
    pit = con.execute("""SELECT series_id, provider_id, pit_support FROM ref_provider_series
                         WHERE pit_support = 'ingestion_only' ORDER BY 1, 2""").fetchdf()
    md = ["# Data coverage & quality report", "", "## Coverage", "", _md(cov), "",
          "## Row status", "", _md(qr["status"]), "",
          "## Flags", "", _md(qr["flags"]), "",
          "## Series WITHOUT reliable historical availability (point-in-time) information", "",
          "As-of queries on these use first-ingestion time only; they cannot reproduce what was known "
          "before ingestion began.", "", _md(pit), "",
          "## Ingestion issues", "", _md(qr["ingestion_issues"]), ""]
    if not policy.empty:
        md += ["## Source-backed policy events", "", _md(policy), "",
               "Date-only timings are conservative reconstructions, not verified release clocks. "
               "FRED target levels are current-only numeric validation, not historical publication vintages. "
               "Calendar-day target series may exceed 100% in weekday-based scalar coverage; DFEDTAR is discontinued.", ""]
    if not estimates.empty:
        md += ["## Approved estimates (not official observations)", "", _md(estimates), "",
               "Estimates are stored in the original series and used by default; original missing versions are retained. "
               "availability is the actual estimate creation time, not a backdated source release. "
               "Future official values supersede estimates.", ""]
    p = out_dir / "report.md"
    p.write_text("\n".join(md))
    return paths + [p]
