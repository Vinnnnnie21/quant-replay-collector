from __future__ import annotations

import datetime as dt
import json

import pandas as pd

from app_config import BJT
from market_data import (
    BINANCE_RAW_COLUMNS,
    KlineLoader,
    LoadRequest,
    MarketDataClient,
    _normalize_kline_df,
    assess_data_quality,
)


def _row(open_ms: int, open_price=100.0, high=102.0, low=99.0, close=101.0):
    return [open_ms, open_price, high, low, close, 10.0, open_ms + 59_999, 0, 0, 0, 0, 0]


def _request(use_cache: bool = False):
    start = dt.datetime(2026, 1, 1, 0, 0, tzinfo=BJT)
    return LoadRequest("BTCUSDT", "1m", start, start + dt.timedelta(minutes=2), use_cache)


def test_normalization_reports_duplicate_and_invalid_ohlc():
    req = _request()
    start_ms = int(req.start_dt_bjt.timestamp() * 1000)
    raw = pd.DataFrame(
        [
            _row(start_ms),
            _row(start_ms),
            _row(start_ms + 60_000, high=98.0, low=99.0),
            _row(start_ms + 120_000),
        ],
        columns=BINANCE_RAW_COLUMNS,
    )

    df, stats = _normalize_kline_df(raw, req.start_dt_bjt, req.end_dt_bjt, req.interval, "test")
    report = assess_data_quality(df, req.symbol, req.interval, req.start_dt_bjt, req.end_dt_bjt, "test", stats)

    assert len(df) == 2
    assert report.duplicated_bars == 1
    assert report.invalid_rows == 1
    assert report.missing_bars == 1
    assert report.data_quality_status == "FAIL"


def test_quality_report_does_not_hide_out_of_order_input():
    req = _request()
    start_ms = int(req.start_dt_bjt.timestamp() * 1000)
    raw = pd.DataFrame(
        [_row(start_ms + 60_000), _row(start_ms), _row(start_ms + 120_000)],
        columns=BINANCE_RAW_COLUMNS,
    )

    df, stats = _normalize_kline_df(raw, req.start_dt_bjt, req.end_dt_bjt, req.interval, "test")
    report = assess_data_quality(df, req.symbol, req.interval, req.start_dt_bjt, req.end_dt_bjt, "test", stats)

    assert stats["out_of_order"] == 1
    assert report.strictly_increasing is False
    assert report.data_quality_status == "FAIL"


def test_negative_volume_is_rejected_by_quality_audit():
    req = _request()
    start_ms = int(req.start_dt_bjt.timestamp() * 1000)
    bad = _row(start_ms + 60_000)
    bad[5] = -1.0
    raw = pd.DataFrame([_row(start_ms), bad, _row(start_ms + 120_000)], columns=BINANCE_RAW_COLUMNS)

    df, stats = _normalize_kline_df(raw, req.start_dt_bjt, req.end_dt_bjt, req.interval, "test")
    report = assess_data_quality(df, req.symbol, req.interval, req.start_dt_bjt, req.end_dt_bjt, "test", stats)

    assert stats["invalid_volume"] == 1
    assert report.invalid_rows == 1
    assert report.data_quality_status == "FAIL"


def test_client_retries_rate_limit_and_keeps_timeout():
    class Response:
        def __init__(self, status, payload):
            self.status_code = status
            self.payload = payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(str(self.status_code))

        def json(self):
            return self.payload

    class Session:
        def __init__(self):
            self.calls = []
            self.responses = [Response(429, []), Response(200, [[1]])]

        def get(self, url, params, timeout):
            self.calls.append((url, params, timeout))
            return self.responses.pop(0)

    session = Session()
    client = MarketDataClient(session=session, timeout=(2, 7), max_retries=1, backoff_seconds=0, sleep=lambda _x: None)
    assert client._request_batch({"symbol": "BTCUSDT"}, lambda: False) == [[1]]
    assert len(session.calls) == 2
    assert session.calls[0][2] == (2, 7)


def test_loader_writes_manifest_and_falls_back_to_cache(tmp_path):
    req = _request()
    start_ms = int(req.start_dt_bjt.astimezone(dt.UTC).timestamp() * 1000)

    class GoodClient:
        def download(self, *args, **kwargs):
            return [_row(start_ms), _row(start_ms + 60_000), _row(start_ms + 120_000)]

    loader = KlineLoader(tmp_path, GoodClient())
    df, message = loader.load(req)
    cache_path = loader.cache_path(req.symbol, req.interval, req.start_dt_bjt, req.end_dt_bjt)
    manifest = json.loads(loader.manifest_path(cache_path).read_text(encoding="utf-8"))

    assert len(df) == 3
    assert "Downloaded" in message
    assert manifest["quality_report"]["data_quality_status"] == "PASS"

    class FailedClient:
        def download(self, *args, **kwargs):
            raise RuntimeError("offline")

    fallback = KlineLoader(tmp_path, FailedClient())
    cached_df, cached_message = fallback.load(req)
    assert len(cached_df) == 3
    assert "using cache" in cached_message
    assert cached_df.attrs["data_source"] == "cache"


def test_loader_returns_online_data_when_cache_write_fails(tmp_path, monkeypatch):
    req = _request()
    start_ms = int(req.start_dt_bjt.astimezone(dt.UTC).timestamp() * 1000)

    class GoodClient:
        def download(self, *args, **kwargs):
            return [_row(start_ms), _row(start_ms + 60_000), _row(start_ms + 120_000)]

    monkeypatch.setattr(pd.DataFrame, "to_csv", lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("read only")))
    df, message = KlineLoader(tmp_path, GoodClient()).load(req)

    assert len(df) == 3
    assert "cache write failed" in message
