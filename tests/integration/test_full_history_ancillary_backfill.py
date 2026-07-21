from __future__ import annotations

import pytest

from services.full_history_ancillary_backfill import (
    FullHistoryAncillaryBackfillService,
    FullHistoryBackfillError,
)
from storage import StorageManager

from tests.research.test_research_data_backfill import (
    _FailingSecondChunkNetwork,
    _RecordingNetwork,
    _stored_kline,
)


def test_explicit_full_history_backfill_only_fetches_incomplete_local_series(
    tmp_path,
) -> None:
    storage = StorageManager(tmp_path / "research.db")
    start_ms = 1_767_225_600_000
    incomplete = _stored_kline("1m", start_ms + 60_000)
    incomplete["quote_volume"] = None
    zero_is_complete = _stored_kline("5m", start_ms)
    zero_is_complete["symbol"] = "ETHUSDT"
    zero_is_complete.update(
        {
            "quote_volume": 0.0,
            "trade_count": 0,
            "taker_buy_base_volume": 0.0,
            "taker_buy_quote_volume": 0.0,
        }
    )
    storage.upsert_klines(
        [
            _stored_kline("1m", start_ms),
            incomplete,
            zero_is_complete,
        ]
    )
    network = _RecordingNetwork()

    result = FullHistoryAncillaryBackfillService(
        storage=storage,
        network=network,
    ).backfill()

    assert network.requests == [
        (
            "BTCUSDT",
            "1m",
            start_ms + 60_000,
            start_ms + 60_000,
        )
    ]
    assert result.total_series == 1
    assert result.completed_series == 1
    assert result.downloaded_bars == 1
    assert result.is_complete is True
    assert storage.list_kline_series_ranges(
        ancillary_incomplete_only=True
    ) == []


def test_full_history_cancellation_during_audit_returns_partial_result(
    tmp_path,
) -> None:
    storage = StorageManager(tmp_path / "research.db")
    start_ms = 1_767_225_600_000
    incomplete = _stored_kline("1m", start_ms)
    incomplete["quote_volume"] = None
    storage.upsert_klines([incomplete])
    network = _RecordingNetwork()
    cancellation_checks = 0

    def cancel_after_series_selection() -> bool:
        nonlocal cancellation_checks
        cancellation_checks += 1
        return cancellation_checks >= 2

    result = FullHistoryAncillaryBackfillService(
        storage=storage,
        network=network,
    ).backfill(cancelled=cancel_after_series_selection)

    assert result.cancelled is True
    assert result.completed_series == 0
    assert result.downloaded_bars == 0
    assert result.is_complete is False
    assert network.requests == []


def test_full_history_failure_reports_confirmed_series_for_retry(
    tmp_path,
) -> None:
    storage = StorageManager(tmp_path / "research.db")
    start_ms = 1_767_225_600_000
    btc = _stored_kline("1m", start_ms)
    btc["quote_volume"] = None
    eth = _stored_kline("1m", start_ms)
    eth["symbol"] = "ETHUSDT"
    eth["quote_volume"] = None
    storage.upsert_klines([btc, eth])

    with pytest.raises(FullHistoryBackfillError) as caught:
        FullHistoryAncillaryBackfillService(
            storage=storage,
            network=_FailingSecondChunkNetwork(),
        ).backfill()

    partial = caught.value.result
    assert partial.total_series == 2
    assert partial.completed_series == 1
    assert partial.downloaded_bars == 1
    assert partial.is_complete is False
    assert partial.cancelled is False
    remaining = storage.list_kline_series_ranges(
        ancillary_incomplete_only=True
    )
    assert [(item["symbol"], item["interval"]) for item in remaining] == [
        ("ETHUSDT", "1m")
    ]
