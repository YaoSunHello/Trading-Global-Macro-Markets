from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from macrodb import catalog, db
from macrodb.http import HttpResponse
from macrodb.ingest import Ingester
from macrodb.registry import ProviderRegistry
from macrodb.settings import Settings

CONFIG = Path(__file__).resolve().parents[1] / "config"


class FakeHttp:
    """Scripted HTTP transport: routes (substring of url) -> callable(params)->(status, bytes, ctype)."""

    def __init__(self):
        self.routes: list[tuple[str, callable]] = []
        self.calls: list[tuple[str, dict]] = []

    def on(self, fragment: str, handler):
        self.routes.append((fragment, handler))

    def get(self, url, params=None, headers=None):
        self.calls.append((url, dict(params or {})))
        for frag, h in self.routes:
            if frag in url:
                status, body, ctype = h(params or {})
                return HttpResponse(url, status, body, {"Content-Type": ctype})
        raise AssertionError(f"no route for {url}")


def fred_json(rows, count=None):
    """rows: (date, value, realtime_start)"""
    obs = [{"realtime_start": rs, "realtime_end": "9999-12-31", "date": d, "value": v} for d, v, rs in rows]
    return json.dumps({"count": count if count is not None else len(obs), "observations": obs}).encode()


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "SECRET-KEY-123")
    return Settings(home=tmp_path / "data", config_dir=CONFIG)


@pytest.fixture
def con(settings):
    c = db.connect(settings)
    yield c
    c.close()


@pytest.fixture
def http():
    return FakeHttp()


@pytest.fixture
def registry(http):
    reg = ProviderRegistry.from_yaml(CONFIG / "providers.yaml", http_factory=lambda cfg: http)
    return reg


@pytest.fixture
def synced(con, settings, registry):
    catalog.sync_all(con, settings, registry)
    return con


@pytest.fixture
def ingester(synced, settings, registry):
    return Ingester(synced, settings, registry)


def ecb_csv(rows, key="EXR.D.USD.EUR.SP00.A"):
    head = "KEY,FREQ,TIME_PERIOD,OBS_VALUE,OBS_STATUS,OBS_CONF,UNIT,UNIT_MULT,DECIMALS\n"
    return (head + "".join(f"{key},D,{d},{v},A,F,USD,0,4\n" for d, v in rows)).encode()


def yahoo_json(rows, offset=-18000):
    """rows: (epoch_ts, open, high, low, close, vol) with values kept as source text"""
    ts = [r[0] for r in rows]
    q = {k: [r[i] for r in rows] for i, k in enumerate(["open", "high", "low", "close", "volume"], start=1)}
    txt = json.dumps({"chart": {"result": [{"meta": {"gmtoffset": offset, "symbol": "SPY"}, "timestamp": ts,
                      "indicators": {"quote": [q], "adjclose": [{"adjclose": q["close"]}]}}], "error": None}})
    return txt.encode()


def route_fred(http, rows_by_series: dict):
    def h(params):
        return 200, fred_json(rows_by_series[params["series_id"]]), "application/json"
    http.on("api.stlouisfed.org", h)
