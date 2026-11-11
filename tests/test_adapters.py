import json

import pytest

from conftest import ecb_csv, yahoo_json
from macrodb.http import ProviderError
from macrodb.providers.base import SeriesRequest
from macrodb.providers.ecb import EcbAdapter
from macrodb.providers.fred import FredAdapter
from macrodb.providers.stooq import StooqAdapter
from macrodb.providers.treasury import TreasuryFiscalDataAdapter
from macrodb.providers.yahoo import YahooAdapter


def req(pid, sid="X", fields=("value",), freq="D", **params):
    return SeriesRequest(pid, sid, list(fields), freq, params)


def test_ecb_parse_keeps_raw_and_attrs():
    obs = EcbAdapter.parse(ecb_csv([("2024-01-02", "1.0956"), ("2024-02", "1.1")]), req("ecb"))
    assert obs[0].value_raw == "1.0956" and obs[0].source_attrs["OBS_STATUS"] == "A"
    assert str(obs[1].observation_date) == "2024-02-01" and obs[1].obs_date_raw == "2024-02"


def test_ecb_rejects_non_csv():
    with pytest.raises(ProviderError):
        EcbAdapter.parse(b"<html>nope</html>", req("ecb"))


def test_fred_parse_vintages_and_error_payload():
    body = json.dumps({"count": 2, "observations": [
        {"realtime_start": "2024-02-02", "realtime_end": "2024-03-07", "date": "2024-01-01", "value": "3.7"},
        {"realtime_start": "2024-03-08", "realtime_end": "9999-12-31", "date": "2024-01-01", "value": "3.8"}]}).encode()
    obs, count = FredAdapter.parse(body, req("fred"))
    assert count == 2 and str(obs[1].realtime_start) == "2024-03-08" and str(obs[1].realtime_end) == "9999-12-31"
    with pytest.raises(ProviderError, match="Bad Request"):
        FredAdapter.parse(json.dumps({"error_code": 400, "error_message": "Bad Request."}).encode(), req("fred"))


def test_treasury_parse():
    body = json.dumps({"data": [{"record_date": "2024-01-31", "avg_interest_rate_amt": "2.340"}],
                       "meta": {"total-pages": 3}}).encode()
    obs, pages = TreasuryFiscalDataAdapter.parse(body, req("treasury"), "record_date", "avg_interest_rate_amt")
    assert pages == 3 and obs[0].value_raw == "2.340"


def test_yahoo_parse_preserves_decimal_text_and_exchange_date():
    # 2024-01-02 14:30 UTC (09:30 New York)
    body = yahoo_json([(1704205800, 472.16, 473.67, 470.49, 472.65, 123456)])
    obs = YahooAdapter.parse(body, req("yahoo", fields=["open", "close", "volume"]))
    by = {o.field_id: o for o in obs}
    assert by["open"].value_raw == "472.16" and str(by["open"].observation_date) == "2024-01-02"
    assert by["volume"].value_num == 123456


def test_stooq_html_challenge_fails_loudly():
    with pytest.raises(ProviderError, match="HTML"):
        StooqAdapter.parse(b"<!DOCTYPE html><html>challenge</html>", req("stooq", fields=["close"]))


def test_stooq_csv_parse():
    obs = StooqAdapter.parse(b"Date,Open,High,Low,Close,Volume\n2024-01-02,1,2,0.5,1.5,100\n", req("stooq", fields=["close", "volume"]))
    assert {(o.field_id, o.value_raw) for o in obs} == {("close", "1.5"), ("volume", "100")}


def test_registry_loads_adapters_from_config(registry):
    assert set(registry.ids()) == {"fred", "ecb", "treasury", "yahoo", "stooq"}
    assert registry.ids(enabled_only=True) == ["fred", "ecb", "treasury"]
    assert isinstance(registry.get("ecb"), EcbAdapter)
    with pytest.raises(ProviderError):
        registry.get("nope")
