from __future__ import annotations

import pytest

from research.entry_context_features import (
    EntryStructuralFeatureSnapshot,
    StructuralFeatureGroup,
    StructuralFeatureValue,
)
from research.exit_behavior_features import (
    ExitPositionStateSnapshot,
    build_exit_position_state,
)
from research.exit_similarity import (
    compare_exit_position_states,
    compare_exit_structural_snapshot_sets,
)


def test_exit_similarity_golden_uses_market_position_and_calendar_weights():
    left_market = _market_snapshots(0.0)
    right_market = _market_snapshots(0.2)
    left_position = ExitPositionStateSnapshot(
        unrealized_atr=0.0,
        mfe_atr=0.0,
        mae_atr=0.0,
        giveback_atr=0.0,
        range_position=0.0,
        holding_bars=1,
        bars_since_mfe=0,
        bars_since_mae=0,
    )
    right_position = ExitPositionStateSnapshot(
        unrealized_atr=1.0,
        mfe_atr=1.0,
        mae_atr=1.0,
        giveback_atr=1.0,
        range_position=0.5,
        holding_bars=3,
        bars_since_mfe=1,
        bars_since_mae=1,
    )

    result = compare_exit_structural_snapshot_sets(
        left_market,
        right_market,
        left_position=left_position,
        right_position=right_position,
        left_cutoff_utc_ms=0,
        right_cutoff_utc_ms=0,
    )

    assert result.aggregate is not None
    assert result.aggregate.market_distance == pytest.approx(0.20)
    assert result.aggregate.position_distance == pytest.approx(0.375)
    assert result.aggregate.calendar_distance == pytest.approx(0.0)
    assert result.aggregate.total_distance == pytest.approx(0.25)
    assert result.aggregate.similarity == pytest.approx(75.0)


def test_flat_holding_path_marks_only_range_position_unavailable():
    state = build_exit_position_state(
        (
            {
                "open_time_utc_ms": 0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
            },
        ),
        direction="LONG",
        actual_entry_price=100.0,
        entry_atr20=2.0,
    )

    comparison = compare_exit_position_states(state, state)

    assert state.range_position is None
    assert comparison.distance == pytest.approx(0.0)
    assert comparison.comparable_count == 7
    assert comparison.total_count == 8
    assert comparison.completeness_ratio == pytest.approx(0.875)
    assert comparison.feature("range_position").unavailable_reason == (
        "both:zero_favorable_adverse_span"
    )


def test_tp_sl_not_applicable_configuration_difference_and_missing_are_distinct():
    no_levels = _position_state()
    with_take_profit = _position_state(
        take_profit_status="SET",
        take_profit_distance_atr=2.0,
    )
    missing_take_profit = _position_state(take_profit_status="MISSING")

    not_applicable = compare_exit_position_states(no_levels, no_levels)
    configuration_difference = compare_exit_position_states(
        no_levels,
        with_take_profit,
    )
    missing = compare_exit_position_states(
        missing_take_profit,
        with_take_profit,
    )

    assert not_applicable.total_count == 8
    assert not_applicable.feature("take_profit_distance_atr").unavailable_reason == (
        "not_applicable:both_not_set"
    )
    assert configuration_difference.feature("take_profit_distance_atr").distance == 1.0
    assert configuration_difference.total_count == 9
    assert missing.feature("take_profit_distance_atr").distance is None
    assert missing.feature("take_profit_distance_atr").unavailable_reason == (
        "left:expected_value_missing"
    )
    assert missing.completeness_ratio == pytest.approx(8 / 9)


def test_position_path_uses_actual_entry_and_frozen_entry_atr_for_long_and_short():
    long_state = build_exit_position_state(
        (
            {
                "open_time_utc_ms": 0,
                "high": 99.0,
                "low": 95.0,
                "close": 98.0,
            },
        ),
        direction="LONG",
        actual_entry_price=100.0,
        entry_atr20=2.0,
        take_profit_status="SET",
        take_profit_price=106.0,
        stop_loss_status="SET",
        stop_loss_price=96.0,
    )
    short_state = build_exit_position_state(
        (
            {
                "open_time_utc_ms": 0,
                "high": 105.0,
                "low": 101.0,
                "close": 102.0,
            },
        ),
        direction="SHORT",
        actual_entry_price=100.0,
        entry_atr20=2.0,
        take_profit_status="SET",
        take_profit_price=94.0,
        stop_loss_status="SET",
        stop_loss_price=104.0,
    )

    assert short_state == long_state
    assert long_state.unrealized_atr == pytest.approx(-1.0)
    assert long_state.mfe_atr == 0.0
    assert long_state.mae_atr == pytest.approx(-2.5)
    assert long_state.giveback_atr == pytest.approx(1.0)
    assert long_state.range_position == pytest.approx(0.6)
    assert long_state.take_profit_distance_atr == pytest.approx(4.0)
    assert long_state.stop_loss_distance_atr == pytest.approx(1.0)


def test_position_path_spans_holding_interval_and_tracks_last_extrema():
    state = build_exit_position_state(
        (
            {
                "open_time_utc_ms": 0,
                "high": 104.0,
                "low": 99.0,
                "close": 103.0,
            },
            {
                "open_time_utc_ms": 60_000,
                "high": 103.0,
                "low": 96.0,
                "close": 98.0,
            },
            {
                "open_time_utc_ms": 120_000,
                "high": 102.0,
                "low": 98.0,
                "close": 101.0,
            },
        ),
        direction="LONG",
        actual_entry_price=100.0,
        entry_atr20=2.0,
    )

    assert state.holding_bars == 3
    assert state.bars_since_mfe == 2
    assert state.bars_since_mae == 1
    assert state.unrealized_atr == pytest.approx(0.5)
    assert state.giveback_atr == pytest.approx(1.5)
    assert state.range_position == pytest.approx(0.625)


@pytest.mark.parametrize(
    "changes",
    (
        {"unrealized_atr": float("nan")},
        {"range_position": 1.01},
        {"holding_bars": 0},
        {"bars_since_mfe": -1},
        {"holding_bars": 3, "bars_since_mae": 3},
    ),
)
def test_position_snapshot_rejects_non_finite_and_impossible_path_state(changes):
    with pytest.raises(ValueError):
        _position_state(**changes)


def _position_state(**changes):
    values = {
        "unrealized_atr": 0.0,
        "mfe_atr": 1.0,
        "mae_atr": -1.0,
        "giveback_atr": 1.0,
        "range_position": 0.5,
        "holding_bars": 5,
        "bars_since_mfe": 1,
        "bars_since_mae": 2,
        "take_profit_status": "NOT_SET",
        "take_profit_distance_atr": None,
        "stop_loss_status": "NOT_SET",
        "stop_loss_distance_atr": None,
    }
    values.update(changes)
    return ExitPositionStateSnapshot(**values)


def _market_snapshots(offset: float):
    groups = (
        StructuralFeatureGroup(
            "price_path",
            (StructuralFeatureValue("path_5", (offset * 4.0,)),),
        ),
        StructuralFeatureGroup(
            "candle_shape",
            (StructuralFeatureValue("body_direction", (offset * 2.0,)),),
        ),
        StructuralFeatureGroup(
            "trend_volatility",
            (StructuralFeatureValue("range_position_20", (offset,)),),
        ),
        StructuralFeatureGroup(
            "trading_activity",
            (StructuralFeatureValue("aggressor_current", (offset * 2.0,)),),
        ),
    )
    return tuple(
        EntryStructuralFeatureSnapshot(
            symbol="BTCUSDT",
            interval=interval,
            cutoff_time_utc_ms=0,
            feature_version="entry-structural-features-v1",
            groups=groups,
        )
        for interval in ("1m", "5m", "15m")
    )
