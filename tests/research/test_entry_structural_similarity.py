from __future__ import annotations

import math
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from research.entry_context_features import (
    ENTRY_STRUCTURAL_FEATURE_VERSION,
    StructuralFeatureGroup,
    StructuralFeatureValue,
    build_entry_structural_feature_snapshot,
)
from research.entry_similarity import (
    ENTRY_SIMILARITY_FORMULA_VERSION,
    SimilarityStatus,
    SimilarityUsage,
    aggregate_entry_similarity,
    calendar_distance_bjt,
    compare_timeframe_structural_features,
)
from research.entry_blind_review import BlindJudgmentInput
from research.setups import SetupDirection
from services.entry_blind_review import EntryBlindReviewService
from services.entry_structural_similarity import EntryStructuralSimilarityService
from storage import StorageManager
from tests.research.test_entry_blind_review import (
    DECISION_TIME,
    _actual_open,
    _grouping_for_samples,
    _setup_version,
)


def test_documented_complete_pair_aggregates_to_similarity_78():
    result = aggregate_entry_similarity(
        timeframe_distances=(0.175, 0.20, 0.30),
        calendar_distance=0.40,
    )

    assert math.isclose(result.market_distance, 0.20)
    assert math.isclose(result.calendar_distance, 0.40)
    assert math.isclose(result.total_distance, 0.22)
    assert math.isclose(result.similarity, 78.0)


def test_calendar_distance_uses_beijing_cyclic_day_and_week_distances():
    left = datetime.fromisoformat("2026-07-20T23:00:00+08:00")
    right = datetime.fromisoformat("2026-07-21T01:00:00+08:00")

    result = calendar_distance_bjt(
        int(left.timestamp() * 1_000),
        int(right.timestamp() * 1_000),
    )

    assert result.day_distance == pytest.approx(120 / 720)
    assert result.week_distance == pytest.approx(1 / 3)
    assert result.weekend_distance == 0.0
    assert result.distance == pytest.approx(0.60 * (120 / 720) + 0.20 * (1 / 3))


def test_price_paths_use_fixed_5_20_60_anchors_and_atr_percentage():
    bars = _structural_bars()

    snapshot = build_entry_structural_feature_snapshot(
        bars,
        symbol="BTCUSDT",
        interval="1m",
        cutoff_time_utc_ms=int(bars.iloc[-1]["close_time_utc_ms"]),
    )

    assert snapshot.feature_version == ENTRY_STRUCTURAL_FEATURE_VERSION
    paths = snapshot.group("price_path")
    assert [len(paths.feature(name).values) for name in ("path_5", "path_20", "path_60")] == [5, 10, 15]
    path_20 = paths.feature("path_20")
    expected_positions = (41, 43, 45, 47, 49, 52, 54, 56, 58, 60)
    atr_20 = sum(_true_ranges(bars)[-20:]) / 20
    expected = tuple(
        math.log(bars.iloc[position]["close"] / bars.iloc[expected_positions[0]]["close"])
        / (atr_20 / bars.iloc[-1]["close"])
        for position in expected_positions
    )
    assert path_20.values == pytest.approx(expected)


def test_candle_shape_and_range_position_follow_formula_specification():
    bars = _structural_bars()

    snapshot = build_entry_structural_feature_snapshot(
        bars,
        symbol="BTCUSDT",
        interval="1m",
        cutoff_time_utc_ms=int(bars.iloc[-1]["close_time_utc_ms"]),
    )

    candle = snapshot.group("candle_shape")
    assert candle.feature("body_direction").values == pytest.approx((1 / 6,))
    assert candle.feature("upper_wick_ratio").values == pytest.approx((0.5,))
    assert candle.feature("lower_wick_ratio").values == pytest.approx((1 / 3,))
    assert candle.feature("bullish_ratio_5").values == (1.0,)
    assert candle.feature("body_net_5").values == pytest.approx((1 / 6,))
    last_20 = bars.tail(20)
    expected_position = (
        bars.iloc[-1]["close"] - last_20["low"].min()
    ) / (last_20["high"].max() - last_20["low"].min())
    assert candle.feature("range_position_20").values == pytest.approx(
        (expected_position,)
    )


def test_trend_and_volatility_use_direction_efficiency_and_fixed_atr_ratios():
    bars = _structural_bars()
    for index in range(len(bars)):
        close = float(bars.iloc[index]["close"]) + math.sin(index / 2) * 0.4
        bars.loc[index, ["open", "high", "low", "close"]] = [
            close - 0.25,
            close + 0.75,
            close - 0.75,
            close,
        ]

    snapshot = build_entry_structural_feature_snapshot(
        bars,
        symbol="BTCUSDT",
        interval="1m",
        cutoff_time_utc_ms=int(bars.iloc[-1]["close_time_utc_ms"]),
    )

    trend = snapshot.group("trend_volatility")
    closes = bars["close"].tolist()
    expected_efficiency = (closes[-1] - closes[-21]) / sum(
        abs(closes[index] - closes[index - 1])
        for index in range(len(closes) - 20, len(closes))
    )
    assert trend.feature("direction_efficiency_20").values == pytest.approx(
        (expected_efficiency,)
    )
    ranges = _true_ranges(bars)
    atr_5 = sum(ranges[-5:]) / 5
    atr_20 = sum(ranges[-20:]) / 20
    atr_60 = sum(ranges[-60:]) / 60
    assert trend.feature("volatility_level").values == pytest.approx(
        (atr_20 / closes[-1],)
    )
    assert trend.feature("volatility_shock").values == pytest.approx(
        (atr_5 / atr_20,)
    )
    assert trend.feature("volatility_regime").values == pytest.approx(
        (atr_20 / atr_60,)
    )


def test_trading_activity_uses_raw_quote_trade_and_taker_buy_fields():
    bars = _structural_bars()

    snapshot = build_entry_structural_feature_snapshot(
        bars,
        symbol="BTCUSDT",
        interval="1m",
        cutoff_time_utc_ms=int(bars.iloc[-1]["close_time_utc_ms"]),
    )

    activity = snapshot.group("trading_activity")
    current = bars.iloc[-1]
    prior20 = bars.iloc[-21:-1]
    assert activity.feature("quote_activity_20").values == pytest.approx(
        (math.log(current["quote_volume"] / prior20["quote_volume"].median()),)
    )
    assert activity.feature("trade_count_activity_20").values == pytest.approx(
        (math.log(current["trade_count"] / prior20["trade_count"].median()),)
    )
    expected_imbalance = (
        2 * current["taker_buy_quote_volume"] / current["quote_volume"] - 1
    )
    assert activity.feature("aggressor_current").values == pytest.approx(
        (expected_imbalance,)
    )
    assert activity.feature("aggressor_delta").available


def test_fixed_feature_scales_feed_equal_weight_group_decomposition():
    bars = _structural_bars()
    for index in range(len(bars)):
        close = float(bars.iloc[index]["close"]) + math.sin(index / 2) * 0.4
        bars.loc[index, ["open", "high", "low", "close"]] = [
            close - 0.25,
            close + 0.75,
            close - 0.75,
            close,
        ]
    original = build_entry_structural_feature_snapshot(
        bars,
        symbol="BTCUSDT",
        interval="1m",
        cutoff_time_utc_ms=int(bars.iloc[-1]["close_time_utc_ms"]),
    )
    left = _replace_feature(original, "candle_shape", "body_direction", (-1.0,))
    right = _replace_feature(original, "candle_shape", "body_direction", (1.0,))

    breakdown = compare_timeframe_structural_features(left, right)

    candle = breakdown.group("candle_shape")
    assert candle.feature("body_direction").distance == 1.0
    assert candle.comparable_count == candle.total_count == 10
    assert math.isclose(candle.distance, 0.10)
    assert math.isclose(breakdown.distance, 0.025)


def test_zero_and_null_trade_counts_remain_distinct_and_fail_80_percent_gate():
    complete_bars = _structural_bars()
    for index in range(len(complete_bars)):
        close = float(complete_bars.iloc[index]["close"]) + math.sin(index / 2) * 0.4
        complete_bars.loc[index, ["open", "high", "low", "close"]] = [
            close - 0.25,
            close + 0.75,
            close - 0.75,
            close,
        ]
    zero_bars = complete_bars.copy()
    zero_bars.loc[len(zero_bars) - 1, "trade_count"] = 0
    null_bars = complete_bars.copy()
    null_bars.loc[len(null_bars) - 1, "trade_count"] = None
    cutoff = int(complete_bars.iloc[-1]["close_time_utc_ms"])

    complete = build_entry_structural_feature_snapshot(
        complete_bars,
        symbol="BTCUSDT",
        interval="1m",
        cutoff_time_utc_ms=cutoff,
    )
    zero = build_entry_structural_feature_snapshot(
        zero_bars,
        symbol="BTCUSDT",
        interval="1m",
        cutoff_time_utc_ms=cutoff,
    )
    null = build_entry_structural_feature_snapshot(
        null_bars,
        symbol="BTCUSDT",
        interval="1m",
        cutoff_time_utc_ms=cutoff,
    )

    assert (
        zero.group("trading_activity")
        .feature("trade_count_activity_20")
        .unavailable_reason
        == "zero_trade_count"
    )
    assert (
        null.group("trading_activity")
        .feature("trade_count_activity_20")
        .unavailable_reason
        == "missing_trade_count"
    )
    breakdown = compare_timeframe_structural_features(complete, zero)
    activity = breakdown.group("trading_activity")
    assert activity.completeness_ratio < 0.80
    assert activity.distance is None
    assert breakdown.distance is None
    assert breakdown.unavailable_reasons == (
        "trading_activity:group_completeness_below_80_percent",
    )


def test_exact_80_percent_common_fields_are_reweighted_within_the_group():
    bars = _structural_bars()
    for index in range(len(bars)):
        close = float(bars.iloc[index]["close"]) + math.sin(index / 2) * 0.4
        bars.loc[index, ["open", "high", "low", "close"]] = [
            close - 0.25,
            close + 0.75,
            close - 0.75,
            close,
        ]
    snapshot = build_entry_structural_feature_snapshot(
        bars,
        symbol="BTCUSDT",
        interval="1m",
        cutoff_time_utc_ms=int(bars.iloc[-1]["close_time_utc_ms"]),
    )
    partial = _replace_unavailable_feature(
        _replace_unavailable_feature(
            snapshot,
            "candle_shape",
            "upper_wick_ratio",
        ),
        "candle_shape",
        "lower_wick_ratio",
    )

    breakdown = compare_timeframe_structural_features(snapshot, partial)
    candle = breakdown.group("candle_shape")

    assert candle.comparable_count == 8
    assert candle.total_count == 10
    assert candle.completeness_ratio == pytest.approx(0.80)
    assert candle.distance == 0.0
    assert breakdown.distance == 0.0


def test_zero_price_range_and_unavailable_atr_are_not_converted_to_zero_features():
    complete_bars = _structural_bars()
    flat_bars = complete_bars.copy()
    flat_bars[["open", "high", "low", "close"]] = 100.0
    cutoff = int(flat_bars.iloc[-1]["close_time_utc_ms"])
    complete = build_entry_structural_feature_snapshot(
        complete_bars,
        symbol="BTCUSDT",
        interval="1m",
        cutoff_time_utc_ms=cutoff,
    )
    flat = build_entry_structural_feature_snapshot(
        flat_bars,
        symbol="BTCUSDT",
        interval="1m",
        cutoff_time_utc_ms=cutoff,
    )

    assert flat.group("candle_shape").feature("body_direction").values == ()
    assert (
        flat.group("candle_shape").feature("body_direction").unavailable_reason
        == "zero_or_invalid_range"
    )
    assert flat.group("price_path").feature("path_60").values == ()
    assert compare_timeframe_structural_features(complete, flat).distance is None


def test_structural_features_reject_a_hidden_gap_even_when_61_rows_remain():
    bars = _structural_bars(count=62).drop(index=30).reset_index(drop=True)

    snapshot = build_entry_structural_feature_snapshot(
        bars,
        symbol="BTCUSDT",
        interval="1m",
        cutoff_time_utc_ms=int(bars.iloc[-1]["close_time_utc_ms"]),
    )

    path = snapshot.group("price_path").feature("path_60")
    assert path.values == ()
    assert path.unavailable_reason == "missing_bar_continuity"


def test_invalid_ohlc_bounds_are_unavailable_instead_of_negative_shape_values():
    bars = _structural_bars()
    last = len(bars) - 1
    bars.loc[last, "high"] = bars.loc[last, "close"] - 0.1

    snapshot = build_entry_structural_feature_snapshot(
        bars,
        symbol="BTCUSDT",
        interval="1m",
        cutoff_time_utc_ms=int(bars.iloc[-1]["close_time_utc_ms"]),
    )

    candle = snapshot.group("candle_shape")
    assert candle.feature("body_direction").values == ()
    assert candle.feature("upper_wick_ratio").values == ()
    assert (
        candle.feature("upper_wick_ratio").unavailable_reason
        == "invalid_ohlc_bounds"
    )


def test_non_finite_feature_values_become_structured_unavailable_distances():
    bars = _structural_bars()
    snapshot = build_entry_structural_feature_snapshot(
        bars,
        symbol="BTCUSDT",
        interval="1m",
        cutoff_time_utc_ms=int(bars.iloc[-1]["close_time_utc_ms"]),
    )
    contaminated = _replace_feature(
        snapshot,
        "candle_shape",
        "body_direction",
        (math.nan,),
    )

    breakdown = compare_timeframe_structural_features(snapshot, contaminated)
    feature = breakdown.group("candle_shape").feature("body_direction")

    assert feature.distance is None
    assert feature.unavailable_reason == "feature_value_not_comparable"


def test_public_research_service_compares_two_revealed_samples_and_persists_audit(
    tmp_path,
):
    storage = StorageManager(tmp_path / "entry_similarity.db")
    setup = _setup_version(storage)
    second_time = DECISION_TIME + timedelta(days=7)
    _actual_open(storage)
    grouping = _grouping_for_samples(
        storage,
        (
            ("event_open_1", DECISION_TIME),
            ("manual_similarity_1", second_time),
        ),
    )
    _store_similarity_history(storage, DECISION_TIME.replace(second=0, microsecond=0))
    _store_similarity_history(storage, second_time.replace(second=0, microsecond=0))
    review = EntryBlindReviewService(storage)
    actual = review.enqueue_actual_open(
        trade_event_id="event_open_1",
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    manual = review.enqueue_manual_position(
        manual_seed_id="manual_similarity_1",
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        symbol="BTCUSDT",
        direction="LONG",
        decision_time=second_time,
    )
    batch = review.create_batch(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        limit=2,
    )
    for item in batch.items:
        review.save_blind_judgment(
            batch_id=batch.batch_id,
            blind_item_id=item.blind_item_id,
            judgment=BlindJudgmentInput(
                label="ENTRY",
                reason_tags=("manual_review",),
                confidence=3,
            ),
        )
        review.reveal(
            batch_id=batch.batch_id,
            blind_item_id=item.blind_item_id,
        )

    service = EntryStructuralSimilarityService(storage)
    result = service.compare_revealed_samples(
        actual.decision_event_id,
        manual.decision_event_id,
    )

    assert result.status is SimilarityStatus.COMPUTED
    assert result.similarity == pytest.approx(100.0)
    assert result.formula_version == ENTRY_SIMILARITY_FORMULA_VERSION
    assert result.feature_version == ENTRY_STRUCTURAL_FEATURE_VERSION
    assert result.usage is SimilarityUsage.FREE_BROWSE
    assert result.eligible_for_formal_evidence is False
    assert [item.interval for item in result.timeframes] == ["1m", "5m", "15m"]
    assert all(
        [group.name for group in item.groups]
        == ["price_path", "candle_shape", "trend_volatility", "trading_activity"]
        for item in result.timeframes
    )
    assert service.get_audit(result.result_id) == result


def test_revealed_pair_with_empty_history_returns_structured_not_computable_result(
    tmp_path,
):
    storage = StorageManager(tmp_path / "entry_similarity_empty.db")
    _, actual_id, manual_id = _create_revealed_pair(storage)

    result = EntryStructuralSimilarityService(storage).compare_revealed_samples(
        actual_id,
        manual_id,
    )

    assert result.status is SimilarityStatus.NOT_COMPUTABLE
    assert result.similarity is None
    assert {reason.split(":", 1)[0] for reason in result.unavailable_reasons} == {
        "1m",
        "5m",
        "15m",
    }


def test_future_kline_perturbation_does_not_change_similarity_or_feature_fingerprint(
    tmp_path,
):
    storage = StorageManager(tmp_path / "entry_similarity_no_future.db")
    _, actual_id, manual_id = _create_revealed_pair(storage)
    second_time = DECISION_TIME + timedelta(days=7)
    first_cutoff = DECISION_TIME.replace(second=0, microsecond=0)
    second_cutoff = second_time.replace(second=0, microsecond=0)
    _store_similarity_history(storage, first_cutoff)
    _store_similarity_history(storage, second_cutoff)
    service = EntryStructuralSimilarityService(storage)

    before = service.compare_revealed_samples(actual_id, manual_id)
    _store_future_perturbation(storage, first_cutoff)
    _store_future_perturbation(storage, second_cutoff)
    after = service.compare_revealed_samples(actual_id, manual_id)

    assert after == before
    assert after.similarity == pytest.approx(100.0)


def test_public_service_keeps_61_closed_high_timeframe_bars_at_unaligned_cutoff(
    tmp_path,
):
    storage = StorageManager(tmp_path / "entry_similarity_high_tf_boundary.db")
    _, actual_id, manual_id = _create_revealed_pair(storage)
    second_time = DECISION_TIME + timedelta(days=7)
    _store_boundary_aligned_similarity_history(
        storage,
        DECISION_TIME.replace(second=0, microsecond=0),
    )
    _store_boundary_aligned_similarity_history(
        storage,
        second_time.replace(second=0, microsecond=0),
    )

    result = EntryStructuralSimilarityService(storage).compare_revealed_samples(
        actual_id,
        manual_id,
    )

    assert result.status is SimilarityStatus.COMPUTED
    assert result.similarity == pytest.approx(100.0)
    assert all(timeframe.distance == pytest.approx(0.0) for timeframe in result.timeframes)


def test_similarity_audits_from_different_formula_or_feature_versions_cannot_compare(
    tmp_path,
):
    storage = StorageManager(tmp_path / "entry_similarity_versions.db")
    _, actual_id, manual_id = _create_revealed_pair(storage)
    second_time = DECISION_TIME + timedelta(days=7)
    _store_similarity_history(storage, DECISION_TIME.replace(second=0, microsecond=0))
    _store_similarity_history(storage, second_time.replace(second=0, microsecond=0))
    result = EntryStructuralSimilarityService(storage).compare_revealed_samples(
        actual_id,
        manual_id,
    )

    with pytest.raises(ValueError, match="versions are not directly comparable"):
        result.require_compatible_version(
            replace(result, feature_version="entry-structural-features-v2")
        )


def test_public_service_lists_only_revealed_samples_for_free_browse(tmp_path):
    storage = StorageManager(tmp_path / "entry_similarity_browsable.db")
    setup, actual_id, manual_id = _create_revealed_pair(storage)
    service = EntryStructuralSimilarityService(storage)

    samples = service.list_browsable_samples(
        setup_version_id=setup.setup_version_id,
        direction="LONG",
    )

    assert {sample.decision_event_id for sample in samples} == {
        actual_id,
        manual_id,
    }
    assert all(sample.revealed for sample in samples)


def test_public_similarity_service_rejects_an_unrevealed_sample_before_scoring(
    tmp_path,
):
    storage = StorageManager(tmp_path / "entry_similarity_unrevealed.db")
    _, actual_id, manual_id = _create_revealed_pair(storage)
    with storage.connect() as conn:
        conn.execute(
            "DELETE FROM entry_review_reveals WHERE decision_event_id=?",
            (manual_id,),
        )

    with pytest.raises(PermissionError, match="revealed"):
        EntryStructuralSimilarityService(storage).compare_revealed_samples(
            actual_id,
            manual_id,
        )

    assert storage.fetch_table("entry_similarity_audits") == []


def test_short_direction_pair_uses_the_same_audited_formula_without_long_sign_leakage(
    tmp_path,
):
    storage = StorageManager(tmp_path / "entry_similarity_short.db")
    _, actual_id, manual_id = _create_revealed_pair(
        storage,
        SetupDirection.SHORT,
    )
    second_time = DECISION_TIME + timedelta(days=7)
    _store_similarity_history(storage, DECISION_TIME.replace(second=0, microsecond=0))
    _store_similarity_history(storage, second_time.replace(second=0, microsecond=0))

    result = EntryStructuralSimilarityService(storage).compare_revealed_samples(
        actual_id,
        manual_id,
    )

    assert result.direction == "SHORT"
    assert result.status is SimilarityStatus.COMPUTED
    assert result.similarity == pytest.approx(100.0)


def test_schema_10_upgrade_adds_similarity_audit_without_changing_setup_history(
    tmp_path,
):
    db_path = tmp_path / "schema_10_similarity.db"
    backup_dir = tmp_path / "backups"
    legacy = StorageManager(db_path, backup_dir=backup_dir)
    setup = _setup_version(legacy)
    with legacy.connect() as conn:
        conn.execute("DROP TABLE entry_similarity_audits")
        conn.execute("PRAGMA user_version=10")

    upgraded = StorageManager(db_path, backup_dir=backup_dir)

    assert upgraded.schema_version() == StorageManager.SCHEMA_VERSION
    assert upgraded.get_setup_version(setup.setup_version_id) == setup
    assert upgraded.fetch_table("entry_similarity_audits") == []
    assert list(
        backup_dir.glob(f"*v10_to_v{StorageManager.SCHEMA_VERSION}*.db")
    )


def test_similarity_audit_rows_are_immutable_and_status_score_consistent(tmp_path):
    storage = StorageManager(tmp_path / "entry_similarity_audit_guards.db")
    _, actual_id, manual_id = _create_revealed_pair(storage)
    second_time = DECISION_TIME + timedelta(days=7)
    _store_similarity_history(storage, DECISION_TIME.replace(second=0, microsecond=0))
    _store_similarity_history(storage, second_time.replace(second=0, microsecond=0))
    result = EntryStructuralSimilarityService(storage).compare_revealed_samples(
        actual_id,
        manual_id,
    )

    with storage.connect() as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                "UPDATE entry_similarity_audits SET similarity=99 WHERE result_id=?",
                (result.result_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO entry_similarity_audits (
                    result_id, left_decision_event_id, right_decision_event_id,
                    setup_version_id, direction, formula_version, feature_version,
                    left_feature_fingerprint, right_feature_fingerprint,
                    status, similarity, usage, eligible_for_formal_evidence,
                    result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "invalid_not_computable_score",
                    result.left_decision_event_id,
                    result.right_decision_event_id,
                    result.setup_version_id,
                    result.direction,
                    result.formula_version,
                    result.feature_version,
                    result.left_feature_fingerprint,
                    result.right_feature_fingerprint,
                    "NOT_COMPUTABLE",
                    50.0,
                    "FREE_BROWSE",
                    0,
                    "{}",
                    result.created_at,
                ),
            )


def _structural_bars(count: int = 61) -> pd.DataFrame:
    start_ms = 1_767_225_600_000
    rows = []
    for index in range(count):
        close = 100.0 * math.exp(index * 0.002)
        rows.append(
            {
                "open_time_utc_ms": start_ms + index * 60_000,
                "close_time_utc_ms": start_ms + (index + 1) * 60_000,
                "open": close - 0.25,
                "high": close + 0.75,
                "low": close - 0.75,
                "close": close,
                "volume": 100.0 + index,
                "quote_volume": 10_000.0 + index * 100.0,
                "trade_count": 100 + index,
                "taker_buy_base_volume": 50.0 + index,
                "taker_buy_quote_volume": 5_000.0 + index * 50.0,
            }
        )
    return pd.DataFrame(rows)


def _true_ranges(bars: pd.DataFrame) -> list[float]:
    values = []
    for index in range(1, len(bars)):
        row = bars.iloc[index]
        previous_close = bars.iloc[index - 1]["close"]
        values.append(
            max(
                row["high"] - row["low"],
                abs(row["high"] - previous_close),
                abs(row["low"] - previous_close),
            )
        )
    return values


def _replace_feature(snapshot, group_name: str, feature_name: str, values):
    groups = []
    for group in snapshot.groups:
        if group.name != group_name:
            groups.append(group)
            continue
        groups.append(
            StructuralFeatureGroup(
                group.name,
                tuple(
                    StructuralFeatureValue(feature.name, tuple(values))
                    if feature.name == feature_name
                    else feature
                    for feature in group.features
                ),
            )
        )
    return replace(snapshot, groups=tuple(groups))


def _replace_unavailable_feature(snapshot, group_name: str, feature_name: str):
    groups = []
    for group in snapshot.groups:
        if group.name != group_name:
            groups.append(group)
            continue
        groups.append(
            StructuralFeatureGroup(
                group.name,
                tuple(
                    StructuralFeatureValue(feature.name, (), "test_missing")
                    if feature.name == feature_name
                    else feature
                    for feature in group.features
                ),
            )
        )
    return replace(snapshot, groups=tuple(groups))


def _store_similarity_history(storage: StorageManager, cutoff) -> None:
    rows = []
    for interval, minutes in (("1m", 1), ("5m", 5), ("15m", 15)):
        for index in range(61):
            close_time = cutoff - timedelta(minutes=(60 - index) * minutes)
            open_time = close_time - timedelta(minutes=minutes)
            close = 100.0 * math.exp(index * 0.002) + math.sin(index / 2) * 0.4
            rows.append(
                {
                    "symbol": "BTCUSDT",
                    "interval": interval,
                    "open_time_utc_ms": int(open_time.timestamp() * 1_000),
                    "open_time_bjt": open_time.isoformat(),
                    "close_time_utc_ms": int(close_time.timestamp() * 1_000),
                    "open": close - 0.25,
                    "high": close + 0.75,
                    "low": close - 0.75,
                    "close": close,
                    "volume": 100.0 + index,
                    "quote_volume": 10_000.0 + index * 100.0,
                    "trade_count": 100 + index,
                    "taker_buy_base_volume": 50.0 + index,
                    "taker_buy_quote_volume": 5_000.0 + index * 50.0,
                    "source": "test_exchange",
                    "downloaded_at": cutoff.isoformat(),
                    "data_quality_status": "ok",
                }
            )
    storage.upsert_klines(rows)


def _store_boundary_aligned_similarity_history(
    storage: StorageManager,
    cutoff: datetime,
) -> None:
    rows = []
    cutoff_ms = int(cutoff.timestamp() * 1_000)
    for interval, minutes in (("1m", 1), ("5m", 5), ("15m", 15)):
        step_ms = minutes * 60_000
        latest_close_ms = cutoff_ms - (cutoff_ms % step_ms)
        latest_close = datetime.fromtimestamp(latest_close_ms / 1_000, UTC)
        for index in range(61):
            close_time = latest_close - timedelta(minutes=(60 - index) * minutes)
            open_time = close_time - timedelta(minutes=minutes)
            close = 100.0 * math.exp(index * 0.002) + math.sin(index / 2) * 0.4
            rows.append(
                {
                    "symbol": "BTCUSDT",
                    "interval": interval,
                    "open_time_utc_ms": int(open_time.timestamp() * 1_000),
                    "open_time_bjt": open_time.isoformat(),
                    "close_time_utc_ms": int(close_time.timestamp() * 1_000),
                    "open": close - 0.25,
                    "high": close + 0.75,
                    "low": close - 0.75,
                    "close": close,
                    "volume": 100.0 + index,
                    "quote_volume": 10_000.0 + index * 100.0,
                    "trade_count": 100 + index,
                    "taker_buy_base_volume": 50.0 + index,
                    "taker_buy_quote_volume": 5_000.0 + index * 50.0,
                    "source": "test_exchange",
                    "downloaded_at": cutoff.isoformat(),
                    "data_quality_status": "ok",
                }
            )
    storage.upsert_klines(rows)


def _create_revealed_pair(
    storage: StorageManager,
    direction: SetupDirection = SetupDirection.LONG,
):
    setup = _setup_version(storage, direction)
    second_time = DECISION_TIME + timedelta(days=7)
    side = direction.value
    _actual_open(storage, side=side)
    grouping = _grouping_for_samples(
        storage,
        (
            ("event_open_1", DECISION_TIME),
            ("manual_similarity_1", second_time),
        ),
    )
    review = EntryBlindReviewService(storage)
    actual = review.enqueue_actual_open(
        trade_event_id="event_open_1",
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    manual = review.enqueue_manual_position(
        manual_seed_id="manual_similarity_1",
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        symbol="BTCUSDT",
        direction=side,
        decision_time=second_time,
    )
    batch = review.create_batch(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        limit=2,
    )
    for item in batch.items:
        review.save_blind_judgment(
            batch_id=batch.batch_id,
            blind_item_id=item.blind_item_id,
            judgment=BlindJudgmentInput(
                label="ENTRY",
                reason_tags=("manual_review",),
                confidence=3,
            ),
        )
        review.reveal(
            batch_id=batch.batch_id,
            blind_item_id=item.blind_item_id,
        )
    return setup, actual.decision_event_id, manual.decision_event_id


def _store_future_perturbation(storage: StorageManager, cutoff) -> None:
    rows = []
    for interval, minutes in (("1m", 1), ("5m", 5), ("15m", 15)):
        open_time = cutoff - timedelta(seconds=1)
        close_time = cutoff + timedelta(minutes=minutes)
        rows.append(
            {
                "symbol": "BTCUSDT",
                "interval": interval,
                "open_time_utc_ms": int(open_time.timestamp() * 1_000),
                "open_time_bjt": open_time.isoformat(),
                "close_time_utc_ms": int(close_time.timestamp() * 1_000),
                "open": 1.0,
                "high": 1_000_000.0,
                "low": 0.01,
                "close": 999_999.0,
                "volume": 9_999_999.0,
                "quote_volume": 9_999_999.0,
                "trade_count": 9_999_999,
                "taker_buy_base_volume": 9_999_999.0,
                "taker_buy_quote_volume": 9_999_999.0,
                "source": "future_perturbation",
                "downloaded_at": cutoff.isoformat(),
                "data_quality_status": "ok",
            }
        )
    storage.upsert_klines(rows)
