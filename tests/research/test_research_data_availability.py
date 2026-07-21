from __future__ import annotations

import pytest

from cancellation import CancellationToken
from market_data.types import (
    DataLoadCancelled,
    KLINE_ANCILLARY_COLUMNS,
    interval_to_ms,
)
from services.research_data_availability import (
    FormulaDataWindow,
    ResearchDataIncompleteError,
    ResearchDataAvailabilityService,
    ResearchOperation,
    ResearchRangeRequest,
    V1_6_FORMULA_DATA_WINDOW,
    require_complete_research_data,
)
from storage import StorageManager


def _kline_row(
    *,
    interval: str,
    open_time_utc_ms: int,
    ancillary: dict[str, float | int | None] | None = None,
) -> dict:
    step_ms = interval_to_ms(interval)
    values = {
        "quote_volume": 1200.5,
        "trade_count": 42,
        "taker_buy_base_volume": 3.25,
        "taker_buy_quote_volume": 650.75,
    }
    if ancillary:
        values.update(ancillary)
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
        **values,
        "source": "test",
        "downloaded_at": "2026-01-01T09:00:00+08:00",
        "data_quality_status": "pass",
    }


def test_public_service_reports_three_timeframe_bar_and_field_gaps(tmp_path) -> None:
    storage = StorageManager(tmp_path / "research.db")
    start_ms = 1_767_225_600_000  # 2026-01-01T00:00:00Z
    storage.upsert_klines(
        [
            _kline_row(interval="1m", open_time_utc_ms=start_ms),
            _kline_row(
                interval="1m",
                open_time_utc_ms=start_ms + 60_000,
                ancillary={"quote_volume": None},
            ),
            # Third 1m bar is absent.
            _kline_row(interval="5m", open_time_utc_ms=start_ms),
            # The 15m bar exists and real zero values are complete, not missing.
            _kline_row(
                interval="15m",
                open_time_utc_ms=start_ms,
                ancillary={
                    "quote_volume": 0.0,
                    "trade_count": 0,
                    "taker_buy_base_volume": 0.0,
                    "taker_buy_quote_volume": 0.0,
                },
            ),
        ]
    )
    service = ResearchDataAvailabilityService(
        storage,
        formula_window=FormulaDataWindow(
            version="test-no-extension",
            warmup_bars=0,
            outcome_bars=0,
        ),
    )

    report = service.inspect(
        ResearchRangeRequest(
            symbol="BTCUSDT",
            timeframes=("1m", "5m", "15m"),
            start_time_utc_ms=start_ms,
            end_time_utc_ms=start_ms + 120_000,
            as_of_utc_ms=start_ms + 3_600_000,
        )
    )

    one_minute, five_minute, fifteen_minute = report.timeframes
    assert one_minute.expected_bars == 3
    assert one_minute.present_bars == 2
    assert one_minute.missing_bar_count == 1
    assert one_minute.missing_field_counts["quote_volume"] == 2
    assert one_minute.missing_field_counts["trade_count"] == 1
    assert one_minute.coverage_ratio == 1 / 3
    assert [
        (gap.start_time_utc_ms, gap.end_time_utc_ms)
        for gap in one_minute.missing_ranges
    ] == [
        (start_ms + 60_000, start_ms + 120_000),
    ]
    assert set(one_minute.missing_ranges[0].missing_fields) == set(
        KLINE_ANCILLARY_COLUMNS
    )

    assert five_minute.expected_bars == 1
    assert five_minute.is_complete is True
    assert fifteen_minute.expected_bars == 1
    assert fifteen_minute.is_complete is True
    assert all(
        count == 0 for count in fifteen_minute.missing_field_counts.values()
    )
    assert report.is_complete is False


def test_v1_6_formula_window_expands_warmup_outcome_and_closed_boundaries(
    tmp_path,
) -> None:
    storage = StorageManager(tmp_path / "research.db")
    minute_ms = interval_to_ms("1m")
    start_ms = 1_767_269_010_000  # 2026-01-01T12:03:30Z
    end_ms = 1_767_269_399_999  # 2026-01-01T12:09:59.999Z
    as_of_ms = 1_767_270_630_000  # 2026-01-01T12:30:30Z

    report = ResearchDataAvailabilityService(storage).inspect(
        ResearchRangeRequest(
            symbol="BTCUSDT",
            timeframes=("1m", "5m", "15m"),
            start_time_utc_ms=start_ms,
            end_time_utc_ms=end_ms,
            as_of_utc_ms=as_of_ms,
        )
    )

    one_minute, five_minute, fifteen_minute = report.timeframes
    assert report.formula_version == V1_6_FORMULA_DATA_WINDOW.version
    # First decision bar is 12:04; v1.6 needs 60 prior bars and 20 outcomes.
    assert one_minute.required_start_time_utc_ms == 1_767_265_440_000
    assert one_minute.required_end_time_utc_ms == 1_767_270_540_000
    # Higher timeframes need their own 60-bar feature warmup, never outcomes.
    assert five_minute.required_start_time_utc_ms == 1_767_251_100_000
    assert five_minute.required_end_time_utc_ms == 1_767_269_100_000
    assert fifteen_minute.required_start_time_utc_ms == 1_767_215_700_000
    assert fifteen_minute.required_end_time_utc_ms == 1_767_268_800_000
    assert one_minute.required_end_time_utc_ms + minute_ms <= as_of_ms


def test_manual_review_allows_ohlcv_but_ancillary_dependent_operations_fail_fast(
    tmp_path,
) -> None:
    storage = StorageManager(tmp_path / "research.db")
    start_ms = 1_767_225_600_000
    storage.upsert_klines(
        [
            _kline_row(
                interval="1m",
                open_time_utc_ms=start_ms,
                ancillary={"quote_volume": None},
            ),
            _kline_row(interval="5m", open_time_utc_ms=start_ms),
            _kline_row(interval="15m", open_time_utc_ms=start_ms),
        ]
    )
    report = ResearchDataAvailabilityService(
        storage,
        formula_window=FormulaDataWindow(
            version="test-no-extension",
            warmup_bars=0,
            outcome_bars=0,
        ),
    ).inspect(
        ResearchRangeRequest(
            symbol="BTCUSDT",
            timeframes=("1m", "5m", "15m"),
            start_time_utc_ms=start_ms,
            end_time_utc_ms=start_ms,
            as_of_utc_ms=start_ms + 3_600_000,
        )
    )

    require_complete_research_data(ResearchOperation.MANUAL_REVIEW, report)

    for operation in (
        ResearchOperation.CANDIDATE_GENERATION,
        ResearchOperation.MODEL_TRAINING,
        ResearchOperation.FORMAL_MATCHING,
    ):
        with pytest.raises(ResearchDataIncompleteError) as caught:
            require_complete_research_data(operation, report)
        assert caught.value.operation is operation
        assert caught.value.deficits[0].interval == "1m"
        assert caught.value.deficits[0].missing_bar_count == 0
        assert caught.value.deficits[0].missing_field_counts == {
            "quote_volume": 1
        }


def test_local_completeness_audit_honors_cancellation_before_scanning(
    tmp_path,
) -> None:
    storage = StorageManager(tmp_path / "research.db")
    token = CancellationToken()
    token.request()
    start_ms = 1_767_225_600_000

    with pytest.raises(DataLoadCancelled):
        ResearchDataAvailabilityService(storage).inspect(
            ResearchRangeRequest(
                symbol="BTCUSDT",
                timeframes=("1m", "5m", "15m"),
                start_time_utc_ms=start_ms,
                end_time_utc_ms=start_ms,
                as_of_utc_ms=start_ms + 24 * 60 * 60_000,
            ),
            cancelled=token.is_requested,
        )


def test_range_request_allows_one_timeframe_for_explicit_maintenance() -> None:
    start_ms = 1_767_225_600_000

    request = ResearchRangeRequest(
        symbol="BTCUSDT",
        timeframes=("1m",),
        start_time_utc_ms=start_ms,
        end_time_utc_ms=start_ms,
        as_of_utc_ms=start_ms + 60_000,
    )

    assert request.timeframes == ("1m",)
