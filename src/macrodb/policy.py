"""Central acquisition, provenance and reconstruction of Federal Reserve policy announcements."""
import hashlib
import html
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd

from .archive import RawArchive
from .http import ProviderError
from .providers.base import FetchedPage, FetchResult, ProviderAdapter, SeriesRequest
from .providers.fred import FredAdapter
from .silver import SilverBuilder

NY = "America/New_York"

ROOT = "https://www.federalreserve.gov"
TARGETS = ["US.FED_FUNDS.TARGET.SINGLE", "US.FED_FUNDS.TARGET.LOWER", "US.FED_FUNDS.TARGET.UPPER"]


def text(body):
    body = re.sub(r"<(script|style)\b.*?</\1>", "", body, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()


def links(body):
    return [(urljoin(ROOT, html.unescape(u)), text(t)) for u, t in
            re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', body, re.S | re.I)]


def url_date(url):
    dates = re.findall(r"(?:19|20)\d{6}", url)
    return pd.Timestamp(datetime.strptime(dates[-1], "%Y%m%d")) if dates else None


def historical_index(body, year, url):
    rows = []
    chunks = re.split(r"<h5[^>]*>", body, flags=re.I)[1:]
    for chunk in chunks:
        heading, content = chunk.split("</h5>", 1)
        heading = text(heading)
        if "cancelled" in heading.lower():
            continue
        scheduled = "Meeting" in heading and "unscheduled" not in heading.lower()
        # Minutes of August 12 describe September 15, 2003 as a separate communications review,
        # explicitly before the next scheduled policy meeting on September 16.
        communications_review = year == 2003 and heading.startswith("September 15 ")
        if communications_review:
            scheduled = False
        ls = links(content.split('<div class="panel panel-default">', 1)[0])
        statements = [u for u, label in ls if label == "Statement" and not u.endswith(".pdf")]
        minutes = [u for u, label in ls if label == "Minutes" and not u.endswith(".pdf")]
        if not scheduled and not statements and not communications_review:
            continue
        primary = statements[0] if statements else (minutes[0] if minutes else "")
        if not primary:
            raise ValueError(f"No statement/minutes evidence: {heading}")
        ds = re.findall(r"([A-Z][a-z]+)\s+(\d{1,2})(?:-(\d{1,2}))?", heading)
        month, first, last = ds[-1]
        meeting_date = pd.Timestamp(f"{month} {last or first}, {year}")
        rows.append({"meeting_date": str(meeting_date.date()), "scheduled": scheduled,
                     "meeting_label": heading, "calendar_url": url, "statement_url": statements[0] if statements else "",
                     "minutes_url": minutes[0] if minutes else "", "source_url": primary})
    return rows


def modern_index(body, url):
    rows = []
    for match in re.finditer(r'<a[^>]*href=["\']([^"\']*monetary(\d{8})a\.htm)["\'][^>]*>\s*HTML\s*</a>', body):
        u, ds = match.groups()
        rows.append({"meeting_date": str(pd.Timestamp(ds).date()), "scheduled": True,
                     "meeting_label": "Scheduled meeting (official calendar)", "calendar_url": url,
                     "statement_url": urljoin(ROOT, u), "minutes_url": "", "source_url": urljoin(ROOT, u)})
    return rows


def announcement_time(body, event_date):
    t = text(body)
    m = re.search(r"For release at\s+(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\.?\s*(E[SD]T)", t, re.I)
    if not m:
        return "", (pd.Timestamp(event_date) + pd.Timedelta(days=1)).tz_localize(NY).isoformat(), "date_only_next_day"
    hour, minute, meridiem, zone = m.groups()
    hour = int(hour) % 12 + (12 if meridiem.lower() == "p" else 0)
    ts = (pd.Timestamp(event_date) + pd.Timedelta(hours=hour, minutes=int(minute or 0))).tz_localize(NY)
    return ts.isoformat(), ts.isoformat(), "statement_clock_time"


class FomcAdapter(ProviderAdapter):
    provider_id = "fomc"

    def fetch(self, req, since=None, until=None):
        url = urljoin(ROOT, req.source_series_id)
        r = self.http.get(url, params=req.params)
        if r.status != 200:
            raise ProviderError(f"FOMC document HTTP {r.status}: {url}")
        body = r.content.decode("utf-8", errors="replace")
        if "FOMC" not in body and "Federal Open Market Committee" not in body:
            raise ProviderError(f"FOMC document has unexpected content: {url}")
        return FetchResult(pages=[FetchedPage(url, req.params, r.status, r.content, r.content_type, [])])


class Sources:
    def __init__(self, con, settings, batch_id, registry, cache_only=False, full=False):
        self.con, self.batch_id = con, batch_id
        self.archive = RawArchive(settings.raw_dir)
        self.adapter = registry.get("fomc")
        self.cache_only, self.full = cache_only, full
        self.used = {}

    def get(self, url):
        if url in self.used:
            return self.archive.get(self.used[url]["archive_path"]).decode("utf-8", errors="replace")
        row = self.con.execute("""
            SELECT response_id, archive_path, content_sha256, fetched_at FROM prov_raw_response
            WHERE provider_id='fomc' AND request_url=? ORDER BY fetched_at DESC, response_id DESC LIMIT 1
        """, [url]).fetchone()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        doc_date = url_date(url)
        immutable = "fomchistorical" in url or (doc_date is not None and (pd.Timestamp(now) - doc_date).days > 30)
        fresh = row is not None and (self.cache_only or (
            not self.full and (immutable or row[3].date() == now.date())))
        if not fresh:
            if self.cache_only:
                raise RuntimeError(f"Policy source absent from the database: {url}; run macrodb ingest first")
            page = self.adapter.fetch(SeriesRequest("fomc", url, [], "D", {})).pages[0]
            when = datetime.now(timezone.utc)
            path, sha, size = self.archive.put("fomc", page.content, page.content_type, when)
            rid = self.con.execute("SELECT nextval('seq_response')").fetchone()[0]
            self.con.execute("INSERT INTO prov_raw_response VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             [rid, self.batch_id, "fomc", url, "{}", page.status, now, sha, page.content_type, size, path])
            row = rid, path, sha, now
        self.used[url] = {"response_id": row[0], "archive_path": row[1], "sha256": row[2],
                          "fetched_at": row[3], "url": url}
        return self.archive.get(row[1]).decode("utf-8", errors="replace")


def assemble(sources, levels, as_of):
    rows = []
    for year in range(1994, max(2021, pd.Timestamp(as_of).year - 5)):
        url = f"{ROOT}/monetarypolicy/fomchistorical{year}.htm"
        rows.extend(historical_index(sources.get(url), year, url))
    url = f"{ROOT}/monetarypolicy/fomccalendars.htm"
    rows.extend(modern_index(sources.get(url), url))
    feed_url = f"{ROOT}/feeds/press_monetary.xml"
    if not sources.cache_only:
        import xml.etree.ElementTree as ET
        feed = ET.fromstring(sources.get(feed_url))
        indexed = {r["statement_url"] for r in rows}
        for item in feed.findall("./channel/item"):
            link = item.findtext("link") or ""
            if "FOMC statement" in (item.findtext("title") or "") and link not in indexed and url_date(link) is not None:
                rows.append({"meeting_date": str(url_date(link).date()), "scheduled": False,
                             "meeting_label": "Intermeeting statement (official monetary-policy feed)",
                             "calendar_url": feed_url, "statement_url": link, "minutes_url": "", "source_url": link})
    index = pd.DataFrame(rows).sort_values("meeting_date").drop_duplicates(["meeting_date", "scheduled"])
    index = index[(index.meeting_date >= "1994-02-01") & (index.meeting_date <= as_of)]
    events, excluded = [], []
    prev = levels.iloc[0]
    for r in index.to_dict("records"):
        body = sources.get(r["source_url"])
        event_date = url_date(r["statement_url"]) if r["statement_url"] else pd.Timestamp(r["meeting_date"])
        # Conference-call deliberation date and public announcement date sometimes differ.
        r["announcement_date"] = str(event_date.date())
        available = levels.loc[:event_date + pd.Timedelta(days=1)]
        if available.empty:
            raise RuntimeError(f"No target-level validation for {event_date}")
        level = available.iloc[-1]
        changed = abs(level.target_low - prev.target_low) > 1e-8 or abs(level.target_high - prev.target_high) > 1e-8
        evidence = text(body)
        if (not changed and event_date + pd.Timedelta(days=1) > levels.index[-1] and
                re.search(r"decided\s+to\s+(?:raise|lower|reduce|increase)\s+(?:its\s+|the\s+)?target", evidence, re.I)):
            raise ProviderError(f"Announced target change on {event_date.date()} awaits updated numerical target levels")
        if not r["scheduled"] and not changed:
            excluded.append({**r, "reason": "intermeeting announcement without target change"})
            continue
        if r["statement_url"]:
            release, known, basis = announcement_time(body, event_date)
        else:
            release, known, basis = announcement_time("", event_date)
            basis = "scheduled_hold_reconstructed_next_day"
        r.update(announcement_ts=release, known_at=known, timing_basis=basis,
                 target_kind=level.target_kind, target_single=level.target_low if level.target_kind == "single" else None,
                 target_low=float(level.target_low), target_high=float(level.target_high),
                 previous_low=float(prev.target_low), previous_high=float(prev.target_high),
                 target_changed=changed, target_change_bp=50 * (
                     level.target_low + level.target_high - prev.target_low - prev.target_high),
                 target_source="FRED DFEDTAR" if level.target_kind == "single" else "FRED DFEDTARL/DFEDTARU",
                 target_source_url=f"https://fred.stlouisfed.org/series/{'DFEDTAR' if level.target_kind == 'single' else 'DFEDTARU'}",
                 effective_level_date=str(available.index[-1].date()),
                 source_evidence=evidence[:400] if not r["statement_url"] else
                 " | ".join(re.findall(r"[^.]{0,80}(?:federal funds|target range|For release at)[^.]{0,180}", evidence, re.I)[:3]))
        events.append(r)
        prev = level
    events = pd.DataFrame(events).sort_values(["announcement_date", "known_at"]).reset_index(drop=True)
    events.insert(0, "event_id", [f"FED_{i:04d}" for i in range(1, len(events) + 1)])
    # Every effective target change must be associated with an indexed public policy event.
    changes = levels[(levels.target_low.diff().abs() > 1e-8) | (levels.target_high.diff().abs() > 1e-8)]
    missing = []
    announced = pd.to_datetime(events.loc[events.target_changed, "announcement_date"])
    for d in changes.index:
        if not ((announced >= d - pd.Timedelta(days=3)) & (announced <= d)).any():
            missing.append(str(d.date()))
    if missing:
        raise RuntimeError(f"Unmatched effective target changes: {missing}")
    return events, pd.DataFrame(excluded)


def target_levels(con, as_of=None):
    from .access import MacroDB
    db = MacroDB(con=con)
    values = {}
    for sid in TARGETS:
        frame = db.get(sid, provider="fred", end=as_of)
        if frame.empty:
            raise RuntimeError(f"Policy input {sid} is missing; run macrodb ingest and build-silver first")
        values[sid] = frame.set_index("observation_date").value.astype(float)
    single = values[TARGETS[0]]
    bounds = pd.concat([values[TARGETS[1]], values[TARGETS[2]]], axis=1, keys=["target_low", "target_high"]).dropna()
    levels = pd.concat([pd.DataFrame({"target_low": single, "target_high": single}), bounds]).sort_index()
    levels.index.name = None
    levels["target_kind"] = ["single" if d < pd.Timestamp("2008-12-16") else "range" for d in levels.index]
    return levels


class PolicyIngester:
    def __init__(self, con, settings, registry):
        self.con, self.settings, self.registry = con, settings, registry

    def run(self, batch_id, as_of=None, cache_only=False, full=False):
        as_of = as_of or date.today().isoformat()
        pending = set(SilverBuilder(self.con).pending_series()) & set(TARGETS)
        if pending:
            SilverBuilder(self.con).build(sorted(pending))
        levels = target_levels(self.con, as_of)
        sources = Sources(self.con, self.settings, batch_id, self.registry, cache_only, full)
        events, excluded = assemble(sources, levels, as_of)
        added = 0
        self.con.execute("BEGIN")
        try:
            for e in events.to_dict("records"):
                payload = json.dumps(e, default=str)
                sha = hashlib.sha256(json.dumps(e, sort_keys=True, default=str).encode()).hexdigest()
                if self.con.execute("SELECT 1 FROM bronze_policy_event WHERE row_hash=?", [sha]).fetchone():
                    continue
                version = self.con.execute("SELECT nextval('seq_policy_event')").fetchone()[0]
                key = f"FED:{e['announcement_date']}:{e['scheduled']}"
                self.con.execute("INSERT INTO bronze_policy_event VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                 [version, key, e["announcement_date"], e["announcement_ts"] or None, e["known_at"],
                                  e["scheduled"], e["target_kind"], e["target_low"], e["target_high"], e["timing_basis"],
                                  payload, sha, batch_id, datetime.now(timezone.utc).replace(tzinfo=None)])
                for role, url in [("calendar", e["calendar_url"]), ("statement", e["statement_url"]),
                                  ("minutes", e["minutes_url"] if not e["statement_url"] else "")]:
                    if url:
                        response = sources.used[url]["response_id"]
                        self.con.execute("INSERT INTO prov_policy_event_source VALUES (?,?,?)", [version, role, response])
                ids = ["DFEDTAR"] if e["target_kind"] == "single" else ["DFEDTARL", "DFEDTARU"]
                for sid in ids:
                    row = self.con.execute("""
                        SELECT bronze_id FROM silver_observation
                        WHERE provider_id='fred' AND source_series_id=? AND observation_date=?
                        ORDER BY bronze_id DESC LIMIT 1
                    """, [sid, e["effective_level_date"]]).fetchone()
                    if not row:
                        raise RuntimeError(f"Missing target lineage for {e['announcement_date']}/{sid}")
                    self.con.execute("INSERT INTO prov_policy_target_lineage VALUES (?,?)", [version, row[0]])
                added += 1
            for e in excluded.to_dict("records"):
                self.con.execute("INSERT INTO prov_policy_exclusion VALUES (?,?,?)",
                                 [batch_id, e["announcement_date"], json.dumps(e)])
            self.con.execute("COMMIT")
        except Exception:
            self.con.execute("ROLLBACK")
            raise
        return {"events": len(events), "events_new": added, "sources_used": len(sources.used)}

    def import_cache(self, cache_path, as_of=None):
        """One-time migration of the original research cache; no network or research-output dependency."""
        from . import __version__
        from .ingest import Ingester
        import uuid
        path = Path(cache_path)
        cache = json.loads(path.read_text())
        original = RawArchive(path.parent / "raw" / "policy_documents")
        batch = f"{datetime.now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        self.con.execute("INSERT INTO prov_batch VALUES (?,?,NULL,'full','running',?,?)",
                         [batch, now, __version__, "Offline migration of cached policy sources"])
        ingester = Ingester(self.con, self.settings, self.registry)
        total = 0
        try:
            for entry in cache.values():
                content = original.get(entry["archive_path"])
                if hashlib.sha256(content).hexdigest() != entry["sha256"]:
                    raise RuntimeError(f"Cached source checksum mismatch: {entry['url']}")
                url, params = entry["url"], entry["params"]
                if "api.stlouisfed.org" in url:
                    sid = params["series_id"]
                    req = SeriesRequest("fred", sid, ["value"], "D", {})
                    obs, _ = FredAdapter.parse(content, req)
                    for o in obs:
                        o.realtime_start = o.realtime_end = None
                    page = FetchedPage(url, params, 200, content, "application/json", obs)
                    self.con.execute("BEGIN")
                    try:
                        _, added, _ = ingester._store_page(batch, req, page)
                        self.con.execute("COMMIT")
                    except Exception:
                        self.con.execute("ROLLBACK")
                        raise
                    total += added
                    self.con.execute("INSERT INTO prov_ingestion_task VALUES (?,?,?,'ok',?,?,NULL,'[]')",
                                     [batch, "fred", sid, len(obs), added])
                    rid = self.con.execute("SELECT max(response_id) FROM prov_raw_response WHERE batch_id=?", [batch]).fetchone()[0]
                else:
                    archive_path, sha, size = ingester.archive.put("fomc", content, "text/html")
                    rid = self.con.execute("SELECT nextval('seq_response')").fetchone()[0]
                    self.con.execute("INSERT INTO prov_raw_response VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                     [rid, batch, "fomc", url, json.dumps(params), 200, now, sha, "text/html", size, archive_path])
                fetched = datetime.fromisoformat(entry["fetched_at"]).astimezone(timezone.utc).replace(tzinfo=None)
                self.con.execute("UPDATE prov_raw_response SET fetched_at=? WHERE response_id=?", [fetched, rid])
            if total:
                ingester._mirror_batch_parquet(batch)
            result = self.run(batch, as_of=as_of, cache_only=True)
            self.con.execute("INSERT INTO prov_ingestion_task VALUES (?,?,?,'ok',?,?,NULL,'[]')",
                             [batch, "fomc", "FOMC.events", result["events"], result["events_new"]])
            self.con.execute("UPDATE prov_batch SET finished_at=?,status='ok' WHERE batch_id=?",
                             [datetime.now(timezone.utc).replace(tzinfo=None), batch])
            return {"batch_id": batch, "target_rows_new": total, **result}
        except Exception:
            self.con.execute("UPDATE prov_batch SET finished_at=?,status='failed' WHERE batch_id=?",
                             [datetime.now(timezone.utc).replace(tzinfo=None), batch])
            raise
