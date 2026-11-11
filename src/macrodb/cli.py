from __future__ import annotations

import argparse
import json
import logging
import sys

from . import catalog, db
from .access import MacroDB
from .ingest import Ingester
from .registry import ProviderRegistry
from .reports import write_reports
from .settings import Settings, load_dotenv
from .silver import SilverBuilder


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="macrodb")
    ap.add_argument("--home", help="data directory (default $MACRODB_HOME or ./data)")
    ap.add_argument("--config", help="config directory (default $MACRODB_CONFIG or ./config)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create schema and sync providers/reference/catalog from config")
    p = sub.add_parser("ingest", help="fetch -> raw archive -> Bronze")
    p.add_argument("--series", nargs="*"); p.add_argument("--provider", nargs="*")
    p.add_argument("--full", action="store_true", help="refetch full history instead of the 30-day refresh/catch-up window")
    p.add_argument("--include-disabled", action="store_true")
    p = sub.add_parser("build-silver", help="Bronze -> Silver for pending series")
    p.add_argument("--series", nargs="*"); p.add_argument("--full", action="store_true", help="rebuild every series")
    p = sub.add_parser("report", help="write coverage & quality reports")
    p.add_argument("--series", nargs="*")
    p = sub.add_parser("export", help="export Parquet snapshots")
    p = sub.add_parser("query", help="print series data")
    p.add_argument("series", nargs="+"); p.add_argument("--start"); p.add_argument("--end")
    p.add_argument("--provider", nargs="*"); p.add_argument("--as-of"); p.add_argument("--vintage", default="latest")
    p.add_argument("--quality", default="usable"); p.add_argument("--wide", action="store_true")
    sub.add_parser("series", help="list canonical series")
    a = ap.parse_args(argv)

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    kw = {k: v for k, v in (("home", a.home), ("config_dir", a.config)) if v}
    st = Settings(**kw)
    con = db.connect(st)
    registry = ProviderRegistry.from_yaml(st.providers_yaml)

    if a.cmd == "init":
        print(json.dumps(catalog.sync_all(con, st, registry)))
    elif a.cmd == "ingest":
        catalog.sync_all(con, st, registry)
        res = Ingester(con, st, registry).run(a.series, a.provider, "full" if a.full else "incremental", a.include_disabled)
        print(json.dumps(res))
        return 0 if res["errors"] == 0 else 2
    elif a.cmd == "build-silver":
        print(json.dumps(SilverBuilder(con).build(a.series, a.full)))
    elif a.cmd == "report":
        for p in write_reports(con, st.reports_dir, a.series):
            print(p)
    elif a.cmd == "export":
        for p in db.export_parquet(con, st):
            print(p)
    elif a.cmd == "series":
        print(MacroDB(st, con=con).list_series().to_string(index=False))
    elif a.cmd == "query":
        df = MacroDB(st, con=con).get(a.series, a.start, a.end, a.provider, as_of=a.as_of, vintage=a.vintage,
                                      quality=a.quality, wide=a.wide)
        print(df.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
