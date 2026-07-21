from __future__ import annotations

import pytest

from cancellation import CancellationToken
from market_data.types import (
    interval_to_ms,
    to_api_utc_ms_from_bjt,
)
from services.research_data_availability import (
    FormulaDataWindow,
    ResearchDataAvailabilityService,
    ResearchRangeRequest,
)
from services.research_data_backfill import (
    ResearchBackfillError,
    ResearchBackfillProgress,
    ResearchBackfillStatus,
    ResearchDataBackfillService,
)
from storage import StorageManager


def _stored_kline(interval: str, open_time_utc_ms: int) -> dict:
    step_ms = interval_to_ms(interval)
    return {
        "symbol": "BTCUSDT",
        "interval": interval,
        "open_time_utc_ms": open_time_utc_ms,
        "open_time_bjt": "2026-01-01T08:00:00.000+08:00",
        "close_time_utc_ms": open_time_utc_ms + step_ms - 1,
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 10.0,
        "quote_volume": 1200.5,
        "trade_count": 42,
        "taker_buy_base_volume": 3.25,
        "taker_buy_quote_volume": 650.75,
        "source": "test",
        "downloaded_at": "2026-01-01T09:00:00+08:00",
        "data_quality_status": "pass",
    }


def _exchange_kline(open_time_utc_ms: int, step_ms: int) -> list:
    return [
        open_time_utc_ms,
        "100.0",
        "102.0",
        "99.0",
        "101.0",
        "10.0",
        open_time_utc_ms + step_ms - 1,
        "1200.5",
        42,
        "3.25",
        "650.75",
        "0",
    ]


class _RecordingNetwork:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, int, int]] = []

    def download(
        self,
        symbol: str,
        interval: str,
        start_dt_bjt,
        end_dt_bjt,
        progress=None,
        cancelled=None,
    ) -> list[list]:
        del progress
        cancelled = cancelled or (lambda: False)
        start_time_utc_ms = to_api_utc_ms_from_bjt(start_dt_bjt)
        end_time_utc_ms = to_api_utc_ms_from_bjt(end_dt_bjt)
        self.requests.append(
            (symbol, interval, start_time_utc_ms, end_time_utc_ms)
        )
        step_ms = interval_to_ms(interval)
        return [
            _exchange_kline(open_time_ms, step_ms)
            for open_time_ms in range(
                start_time_utc_ms,
                end_time_utc_ms + 1,
                step_ms,
            )
        ]


class _FailingSecondChunkNetwork(_RecordingNetwork):
    def download(self, *args, **kwargs) -> list[list]:
        if len(self.requests) == 1:
            symbol, interval, start_dt_bjt, end_dt_bjt = args
            self.requests.append(
                (
                    symbol,
                    interval,
                    to_api_utc_ms_from_bjt(start_dt_bjt),
                    to_api_utc_ms_from_bjt(end_dt_bjt),
                )
            )
            raise ConnectionError("temporary network failure")
        return super().download(*args, **kwargs)


class _CancelAfterFirstChunkNetwork(_RecordingNetwork):
    def __init__(self, token: CancellationToken) -> None:
        super().__init__()
        self._token = token

    def download(self, *args, **kwargs) -> list[list]:
        rows = super().download(*args, **kwargs)
        self._token.request()
        return rows


def test_backfill_fetches_only_the_minimal_missing_range_and_persists_it(
    tmp_path,
) -> None:
    storage = StorageManager(tmp_path / "research.db")
    start_ms = 1_767_225_600_000
    storage.upsert_klines(
        [
            _stored_kline("1m", start_ms),
            _stored_kline("1m", start_ms + 3 * 60_000),
            _stored_kline("5m", start_ms),
            _stored_kline("15m", start_ms),
        ]
    )
    formula_window = FormulaDataWindow(
        version="test-no-extension",
        warmup_bars=0,
        outcome_bars=0,
    )
    availability = ResearchDataAvailabilityService(
        storage,
        formula_window=formula_window,
    )
    network = _RecordingNetwork()
    service = ResearchDataBackfillService(
        storage=storage,
        network=network,
        availability=availability,
    )
    request = ResearchRangeRequest(
        symbol="BTCUSDT",
        timeframes=("1m", "5m", "15m"),
        start_time_utc_ms=start_ms,
        end_time_utc_ms=start_ms + 3 * 60_000,
        as_of_utc_ms=start_ms + 3_600_000,
    )

    result = service.backfill(request)

    assert network.requests == [
        (
            "BTCUSDT",
            "1m",
            start_ms + 60_000,
            start_ms + 2 * 60_000,
        )
    ]
    assert result.completed_chunks == 1
    assert result.downloaded_bars == 2
    assert result.completeness.is_complete is True
    rows = storage.fetch_klines_for_range(
        symbol="BTCUSDT",
        interval="1m",
        start_time_utc_ms=start_ms,
        end_time_utc_ms=start_ms + 3 * 60_000,
    )
    assert [row["open_time_utc_ms"] for row in rows] == [
        start_ms + index * 60_000 for index in range(4)
    ]
    assert rows[1]["quote_volume"] == 1200.5


def test_backfill_with_no_gaps_finishes_without_constructing_network_work(
    tmp_path,
) -> None:
    storage = StorageManager(tmp_path / "research.db")
    start_ms = 1_767_225_600_000
    storage.upsert_klines(
        [
            _stored_kline("1m", start_ms),
            _stored_kline("5m", start_ms),
            _stored_kline("15m", start_ms),
        ]
    )
    availability = ResearchDataAvailabilityService(
        storage,
        formula_window=FormulaDataWindow(
            version="test-no-extension",
            warmup_bars=0,
            outcome_bars=0,
        ),
    )
    network = _RecordingNetwork()

    result = ResearchDataBackfillService(
        storage=storage,
        network=network,
        availability=availability,
    ).backfill(
        ResearchRangeRequest(
            symbol="BTCUSDT",
            timeframes=("1m", "5m", "15m"),
            start_time_utc_ms=start_ms,
            end_time_utc_ms=start_ms,
            as_of_utc_ms=start_ms + 3_600_000,
        )
    )

    assert network.requests == []
    assert result.status is ResearchBackfillStatus.COMPLETE
    assert result.total_chunks == 0
    assert result.completed_chunks == 0


def test_backfill_splits_each_gap_at_the_exchange_page_limit(tmp_path) -> None:
    storage = StorageManager(tmp_path / "research.db")
    start_ms = 1_767_225_600_000
    minute_ms = interval_to_ms("1m")
    end_ms = start_ms + 1_000 * minute_ms
    storage.upsert_klines(
        [
            *(
                _stored_kline("5m", open_time_ms)
                for open_time_ms in range(
                    start_ms,
                    end_ms + 1,
                    interval_to_ms("5m"),
                )
            ),
            *(
                _stored_kline("15m", open_time_ms)
                for open_time_ms in range(
                    start_ms,
                    end_ms + 1,
                    interval_to_ms("15m"),
                )
            ),
        ]
    )
    availability = ResearchDataAvailabilityService(
        storage,
        formula_window=FormulaDataWindow(
            version="test-no-extension",
            warmup_bars=0,
            outcome_bars=0,
        ),
    )
    network = _RecordingNetwork()
    service = ResearchDataBackfillService(
        storage=storage,
        network=network,
        availability=availability,
    )

    result = service.backfill(
        ResearchRangeRequest(
            symbol="BTCUSDT",
            timeframes=("1m", "5m", "15m"),
            start_time_utc_ms=start_ms,
            end_time_utc_ms=end_ms,
            as_of_utc_ms=end_ms + 3_600_000,
        )
    )

    assert network.requests == [
        (
            "BTCUSDT",
            "1m",
            start_ms,
            start_ms + 999 * minute_ms,
        ),
        (
            "BTCUSDT",
            "1m",
            start_ms + 1_000 * minute_ms,
            start_ms + 1_000 * minute_ms,
        ),
    ]
    assert result.total_chunks == 2
    assert result.completed_chunks == 2
    assert result.downloaded_bars == 1_001


def test_network_failure_keeps_confirmed_chunks_and_retry_resumes_remaining_gap(
    tmp_path,
) -> None:
    storage = StorageManager(tmp_path / "research.db")
    start_ms = 1_767_225_600_000
    minute_ms = interval_to_ms("1m")
    end_ms = start_ms + 1_000 * minute_ms
    storage.upsert_klines(
        [
            *(
                _stored_kline("5m", open_time_ms)
                for open_time_ms in range(
                    start_ms,
                    end_ms + 1,
                    interval_to_ms("5m"),
                )
            ),
            *(
                _stored_kline("15m", open_time_ms)
                for open_time_ms in range(
                    start_ms,
                    end_ms + 1,
                    interval_to_ms("15m"),
                )
            ),
        ]
    )
    availability = ResearchDataAvailabilityService(
        storage,
        formula_window=FormulaDataWindow(
            version="test-no-extension",
            warmup_bars=0,
            outcome_bars=0,
        ),
    )
    request = ResearchRangeRequest(
        symbol="BTCUSDT",
        timeframes=("1m", "5m", "15m"),
        start_time_utc_ms=start_ms,
        end_time_utc_ms=end_ms,
        as_of_utc_ms=end_ms + 3_600_000,
    )

    with pytest.raises(ResearchBackfillError) as caught:
        ResearchDataBackfillService(
            storage=storage,
            network=_FailingSecondChunkNetwork(),
            availability=availability,
        ).backfill(request)

    partial = caught.value.result
    assert partial.total_chunks == 2
    assert partial.completed_chunks == 1
    assert partial.downloaded_bars == 1_000
    assert partial.completeness.is_complete is False
    assert partial.completeness.timeframes[0].missing_bar_count == 1

    retry_network = _RecordingNetwork()
    retry = ResearchDataBackfillService(
        storage=storage,
        network=retry_network,
        availability=availability,
    ).backfill(request)

    assert retry_network.requests == [
        (
            "BTCUSDT",
            "1m",
            start_ms + 1_000 * minute_ms,
            start_ms + 1_000 * minute_ms,
        )
    ]
    assert retry.completeness.is_complete is True


def test_cancellation_stops_between_chunks_without_rolling_back_confirmed_data(
    tmp_path,
) -> None:
    storage = StorageManager(tmp_path / "research.db")
    start_ms = 1_767_225_600_000
    minute_ms = interval_to_ms("1m")
    end_ms = start_ms + 1_000 * minute_ms
    storage.upsert_klines(
        [
            *(
                _stored_kline("5m", open_time_ms)
                for open_time_ms in range(
                    start_ms,
                    end_ms + 1,
                    interval_to_ms("5m"),
                )
            ),
            *(
                _stored_kline("15m", open_time_ms)
                for open_time_ms in range(
                    start_ms,
                    end_ms + 1,
                    interval_to_ms("15m"),
                )
            ),
        ]
    )
    availability = ResearchDataAvailabilityService(
        storage,
        formula_window=FormulaDataWindow(
            version="test-no-extension",
            warmup_bars=0,
            outcome_bars=0,
        ),
    )
    token = CancellationToken()
    network = _CancelAfterFirstChunkNetwork(token)

    result = ResearchDataBackfillService(
        storage=storage,
        network=network,
        availability=availability,
    ).backfill(
        ResearchRangeRequest(
            symbol="BTCUSDT",
            timeframes=("1m", "5m", "15m"),
            start_time_utc_ms=start_ms,
            end_time_utc_ms=end_ms,
            as_of_utc_ms=end_ms + 3_600_000,
        ),
        cancelled=token.is_requested,
    )

    assert result.status is ResearchBackfillStatus.CANCELLED
    assert result.total_chunks == 2
    assert result.completed_chunks == 1
    assert result.downloaded_bars == 1_000
    assert result.completeness.is_complete is False
    assert len(network.requests) == 1


def test_backfill_reports_progress_only_after_each_chunk_is_committed(
    tmp_path,
) -> None:
    storage = StorageManager(tmp_path / "research.db")
    start_ms = 1_767_225_600_000
    minute_ms = interval_to_ms("1m")
    end_ms = start_ms + 1_000 * minute_ms
    storage.upsert_klines(
        [
            *(
                _stored_kline("5m", open_time_ms)
                for open_time_ms in range(
                    start_ms,
                    end_ms + 1,
                    interval_to_ms("5m"),
                )
            ),
            *(
                _stored_kline("15m", open_time_ms)
                for open_time_ms in range(
                    start_ms,
                    end_ms + 1,
                    interval_to_ms("15m"),
                )
            ),
        ]
    )
    availability = ResearchDataAvailabilityService(
        storage,
        formula_window=FormulaDataWindow(
            version="test-no-extension",
            warmup_bars=0,
            outcome_bars=0,
        ),
    )
    progress: list[ResearchBackfillProgress] = []

    result = ResearchDataBackfillService(
        storage=storage,
        network=_RecordingNetwork(),
        availability=availability,
    ).backfill(
        ResearchRangeRequest(
            symbol="BTCUSDT",
            timeframes=("1m", "5m", "15m"),
            start_time_utc_ms=start_ms,
            end_time_utc_ms=end_ms,
            as_of_utc_ms=end_ms + 3_600_000,
        ),
        progress=progress.append,
    )

    assert [
        (
            event.completed_chunks,
            event.total_chunks,
            event.downloaded_bars,
            event.interval,
        )
        for event in progress
    ] == [
        (1, 2, 1_000, "1m"),
        (2, 2, 1_001, "1m"),
    ]
    assert result.status is ResearchBackfillStatus.COMPLETE
