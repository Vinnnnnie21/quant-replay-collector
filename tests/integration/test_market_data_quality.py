from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

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
from controllers.market_data_controller import persist_loaded_market_data


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


def test_cache_round_trip_preserves_float64_market_values_exactly(tmp_path):
    req = _request(use_cache=True)
    start_ms = int(req.start_dt_bjt.timestamp() * 1000)
    exact_open = 100.13693952214545
    raw = pd.DataFrame(
        [
            _row(start_ms, open_price=exact_open, high=101.0, low=99.0, close=100.5),
            _row(start_ms + 60_000),
            _row(start_ms + 120_000),
        ],
        columns=BINANCE_RAW_COLUMNS,
    )
    expected, _stats = _normalize_kline_df(
        raw,
        req.start_dt_bjt,
        req.end_dt_bjt,
        req.interval,
        "test",
    )
    loader = KlineLoader(tmp_path, client=object())
    path = loader.cache_path(req.symbol, req.interval, req.start_dt_bjt, req.end_dt_bjt)
    loader.cache.write_frame(path, expected)

    restored, _report = loader.read_cache(path, req, req.symbol, req.interval)

    assert restored.loc[0, "open"] == expected.loc[0, "open"]


def test_cache_round_trip_preserves_ancillary_null_and_zero_values(tmp_path):
    req = _request(use_cache=True)
    start_ms = int(req.start_dt_bjt.timestamp() * 1000)
    complete = _row(start_ms)
    complete[7:11] = [2_010.5, 42, 11.25, 1_130.75]
    zero = _row(start_ms + 60_000)
    zero[7:11] = [0.0, 0, 0.0, 0.0]
    missing = _row(start_ms + 120_000)
    missing[7:11] = [None, None, None, None]
    normalized, _stats = _normalize_kline_df(
        pd.DataFrame([complete, zero, missing], columns=BINANCE_RAW_COLUMNS),
        req.start_dt_bjt,
        req.end_dt_bjt,
        req.interval,
        "test",
    )
    loader = KlineLoader(tmp_path, client=object())
    path = loader.cache_path(
        req.symbol,
        req.interval,
        req.start_dt_bjt,
        req.end_dt_bjt,
    )
    loader.cache.write_frame(path, normalized)

    restored, _report = loader.read_cache(
        path,
        req,
        req.symbol,
        req.interval,
    )

    fields = [
        "quote_volume",
        "trade_count",
        "taker_buy_base_volume",
        "taker_buy_quote_volume",
    ]
    assert restored.loc[0, fields].tolist() == [
        2_010.5,
        42,
        11.25,
        1_130.75,
    ]
    assert restored.loc[1, fields].tolist() == [0.0, 0, 0.0, 0.0]
    assert restored.loc[2, fields].isna().all()


def test_collection_quality_report_audits_sort_deduplication_and_invalid_row_exclusion():
    req = _request()
    start_ms = int(req.start_dt_bjt.timestamp() * 1000)
    invalid = _row(start_ms + 120_000, high=98.0, low=99.0)
    raw = pd.DataFrame(
        [
            _row(start_ms + 60_000),
            _row(start_ms),
            _row(start_ms),
            invalid,
        ],
        columns=BINANCE_RAW_COLUMNS,
    )

    cleaned, stats = _normalize_kline_df(raw, req.start_dt_bjt, req.end_dt_bjt, req.interval, "test")
    report = assess_data_quality(cleaned, req.symbol, req.interval, req.start_dt_bjt, req.end_dt_bjt, "test", stats)

    assert report.repair_actions == (
        {"action": "sort_by_open_time", "affected_rows": 1},
        {"action": "drop_duplicate_bars", "affected_rows": 1},
        {"action": "exclude_invalid_rows", "affected_rows": 1},
    )


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


def test_binance_ancillary_fields_are_parsed_to_stable_nullable_columns():
    req = _request()
    start_ms = int(req.start_dt_bjt.timestamp() * 1000)
    complete = _row(start_ms)
    complete[7:11] = ["2010.5", "42", "11.25", "1130.75"]
    missing = _row(start_ms + 60_000)
    missing[7:11] = [None, "", None, ""]
    raw = pd.DataFrame([complete, missing], columns=BINANCE_RAW_COLUMNS)

    normalized, _stats = _normalize_kline_df(
        raw,
        req.start_dt_bjt,
        req.end_dt_bjt,
        req.interval,
        "test",
    )

    assert normalized.loc[0, "quote_volume"] == 2_010.5
    assert normalized.loc[0, "trade_count"] == 42
    assert normalized.loc[0, "taker_buy_base_volume"] == 11.25
    assert normalized.loc[0, "taker_buy_quote_volume"] == 1_130.75
    assert normalized.loc[
        1,
        [
            "quote_volume",
            "trade_count",
            "taker_buy_base_volume",
            "taker_buy_quote_volume",
        ],
    ].isna().all()


def test_legacy_cache_ancillary_column_names_are_normalized_without_data_loss():
    req = _request()
    start_ms = int(req.start_dt_bjt.timestamp() * 1000)
    legacy_columns = [
        "open_time_ms",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time_ms",
        "qav",
        "num_trades",
        "tbbav",
        "tbqav",
        "ignore",
    ]
    raw = pd.DataFrame(
        [
            [
                start_ms,
                100.0,
                102.0,
                99.0,
                101.0,
                10.0,
                start_ms + 59_999,
                "2010.5",
                "42",
                "11.25",
                "1130.75",
                0,
            ]
        ],
        columns=legacy_columns,
    )

    normalized, _stats = _normalize_kline_df(
        raw,
        req.start_dt_bjt,
        req.end_dt_bjt,
        req.interval,
        "legacy cache",
    )

    assert normalized.loc[0, "quote_volume"] == 2_010.5
    assert normalized.loc[0, "trade_count"] == 42
    assert normalized.loc[0, "taker_buy_base_volume"] == 11.25
    assert normalized.loc[0, "taker_buy_quote_volume"] == 1_130.75


def test_non_finite_volume_is_excluded_and_recorded_as_collection_repair():
    req = _request()
    start_ms = int(req.start_dt_bjt.timestamp() * 1000)
    bad = _row(start_ms + 60_000)
    bad[5] = float("inf")
    raw = pd.DataFrame([_row(start_ms), bad, _row(start_ms + 120_000)], columns=BINANCE_RAW_COLUMNS)

    cleaned, stats = _normalize_kline_df(raw, req.start_dt_bjt, req.end_dt_bjt, req.interval, "test")
    report = assess_data_quality(cleaned, req.symbol, req.interval, req.start_dt_bjt, req.end_dt_bjt, "test", stats)

    assert len(cleaned) == 2
    assert stats["dropped_invalid"] == 1
    assert {"action": "exclude_invalid_rows", "affected_rows": 1} in report.repair_actions


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


def test_loader_reuses_superset_cache_for_subrange_without_network(tmp_path):
    start = dt.datetime(2025, 4, 1, 8, tzinfo=BJT)
    full = LoadRequest("BTCUSDT", "1d", start, start + dt.timedelta(days=2), True)
    start_ms = int(start.astimezone(dt.UTC).timestamp() * 1000)

    class FullClient:
        def download(self, *_args, **_kwargs):
            return [_row(start_ms + day * 86_400_000) for day in range(3)]

    KlineLoader(tmp_path, FullClient()).load(full)

    class OfflineClient:
        def download(self, *_args, **_kwargs):
            raise AssertionError("covered subrange must not access network")

    sub = LoadRequest("BTCUSDT", "1d", start + dt.timedelta(days=1), start + dt.timedelta(days=2), True)
    frame, message = KlineLoader(tmp_path, OfflineClient()).load(sub)
    assert len(frame) == 2
    assert "covered cache" in message


def test_loader_downloads_only_missing_cache_suffix(tmp_path):
    start = dt.datetime(2025, 4, 1, 8, tzinfo=BJT)
    first = LoadRequest("BTCUSDT", "1d", start, start + dt.timedelta(days=1), True)
    start_ms = int(start.astimezone(dt.UTC).timestamp() * 1000)

    class FirstClient:
        def download(self, *_args, **_kwargs):
            return [_row(start_ms), _row(start_ms + 86_400_000)]

    KlineLoader(tmp_path, FirstClient()).load(first)

    class GapClient:
        def __init__(self):
            self.ranges = []

        def download(self, _symbol, _interval, range_start, range_end, *_args):
            self.ranges.append((range_start, range_end))
            return [_row(start_ms + 2 * 86_400_000)]

    client = GapClient()
    extended = LoadRequest("BTCUSDT", "1d", start, start + dt.timedelta(days=2), True)
    frame, message = KlineLoader(tmp_path, client).load(extended)
    assert len(frame) == 3
    assert len(client.ranges) == 1
    assert client.ranges[0][0].date() == (start + dt.timedelta(days=2)).date()
    assert "Filled cache gaps" in message


def test_loaded_market_persistence_records_quality_without_rewriting_the_cache_in_sqlite():
    class Storage:
        def __init__(self):
            self.quality_reports = []
            self.kline_upserts = 0

        def save_data_quality_report(self, report):
            self.quality_reports.append(report)

        def upsert_klines(self, _rows):
            self.kline_upserts += 1

    frame = pd.DataFrame(
        [{"open_time_ms": 1, "open_time_bjt": "2026-01-01T00:00:00+08:00", "close_time_ms": 2, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 3}]
    )
    frame.attrs["data_source"] = "cache"
    frame.attrs["data_quality_report"] = {"report_id": "quality_1", "created_at": "2026-01-01T00:00:00+08:00", "data_quality_status": "PASS"}
    storage = Storage()
    window = SimpleNamespace(
        df=frame,
        storage=storage,
        _loaded_market_key=("BTCUSDT", "1m", "2026-01-01", "2026-01-01"),
        _current_market_key=lambda: ("BTCUSDT", "1m", "2026-01-01", "2026-01-01"),
        _log=lambda _message: None,
    )

    persist_loaded_market_data(window)

    assert storage.quality_reports[0]["report_json"]
    assert storage.kline_upserts == 0
