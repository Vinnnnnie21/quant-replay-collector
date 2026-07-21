from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import math
import sqlite3

import pytest
import research.entry_outcome_comparison as outcome_comparison_module
import services.entry_outcome_comparison as outcome_service_module
from errors import DatabaseError

from research.market_episodes import (
    MarketEpisodeService,
    ResearchSampleWindow,
    TimeRange,
)
from research.setups import (
    CreateSetup,
    DecisionProtocol,
    SetupDirection,
    SetupLibrary,
    SetupVersionSpec,
    TimeframeProfile,
)

from research.entry_outcome_comparison import (
    ENTRY_MATCH_SENSITIVITY_THRESHOLDS,
    EntryDecisionForComparison,
    EntryOutcomeEvidenceStage,
    EntryOutcomeEvidenceStatus,
    EntryPairSimilarity,
    EntryPairOutcomeDifference,
    MatchedEntryPair,
    EntryOutcomeMetric,
    EntryOutcomePath,
    EntryOutcomeValue,
    OutcomeBar,
    calculate_entry_outcome_path,
    aggregate_entry_episode_differences,
    adjust_entry_outcome_family,
    build_entry_outcome_matrix,
    classify_entry_outcome_evidence_stage,
    classify_entry_outcome_evidence_status,
    global_match_entry_reject,
    infer_entry_episode_differences,
)
from services.entry_outcome_comparison import EntryOutcomeComparisonService
from storage import StorageManager


def test_long_entry_outcome_uses_next_bar_open_and_formula_golden_values():
    path = calculate_entry_outcome_path(
        direction="LONG",
        decision_cutoff_utc_ms=999,
        bars=(
            OutcomeBar(1_000, 100.0, 103.0, 99.0, 101.0),
            OutcomeBar(2_000, 101.0, 105.0, 101.0, 104.0),
            OutcomeBar(3_000, 104.0, 104.0, 100.0, 103.0),
        ),
    )

    assert path.execution_price == pytest.approx(100.0)
    assert path.value(3, EntryOutcomeMetric.CLOSE_RETURN) == pytest.approx(0.03)
    assert path.value(3, EntryOutcomeMetric.MFE) == pytest.approx(0.05)
    assert path.value(3, EntryOutcomeMetric.MAE) == pytest.approx(-0.01)


def test_short_entry_outcome_has_independent_direction_adjusted_golden_values():
    path = calculate_entry_outcome_path(
        direction="SHORT",
        decision_cutoff_utc_ms=999,
        bars=(
            OutcomeBar(1_000, 100.0, 103.0, 99.0, 101.0),
            OutcomeBar(2_000, 101.0, 105.0, 101.0, 104.0),
            OutcomeBar(3_000, 104.0, 104.0, 100.0, 103.0),
        ),
    )

    assert path.execution_price == pytest.approx(100.0)
    assert path.value(3, EntryOutcomeMetric.CLOSE_RETURN) == pytest.approx(-0.03)
    assert path.value(3, EntryOutcomeMetric.MFE) == pytest.approx(0.01)
    assert path.value(3, EntryOutcomeMetric.MAE) == pytest.approx(-0.05)


def test_missing_next_bar_is_unavailable_and_actual_fill_cannot_replace_it():
    path = calculate_entry_outcome_path(
        direction="LONG",
        decision_cutoff_utc_ms=999,
        bars=(OutcomeBar(0, 90.0, 91.0, 89.0, 90.5),),
        actual_fill_price=123.45,
    )

    assert path.available is False
    assert path.execution_price is None
    assert path.unavailable_reason == "next_decision_bar_missing"
    assert path.outcomes == ()


def test_a_later_bar_cannot_replace_the_missing_next_decision_bar():
    path = calculate_entry_outcome_path(
        direction="LONG",
        decision_cutoff_utc_ms=999,
        decision_interval_ms=1_000,
        bars=(OutcomeBar(2_000, 100.0, 101.0, 99.0, 100.0),),
    )

    assert path.available is False
    assert path.unavailable_reason == "next_decision_bar_missing"


def test_global_matching_is_one_to_one_and_beats_greedy_pair_selection():
    decisions = tuple(
        EntryDecisionForComparison(
            decision_event_id=event_id,
            label=label,
            setup_version_id="setup_v1",
            grouping_version_id="group_v1",
            episode_id=episode_id,
            symbol="BTCUSDT",
            direction="LONG",
            decision_timeframe="5m",
            decision_cutoff_utc_ms=cutoff,
        )
        for event_id, label, episode_id, cutoff in (
            ("entry_1", "ENTRY", "episode_1", 1_000),
            ("entry_2", "ENTRY", "episode_2", 2_000),
            ("reject_1", "REJECT", "episode_3", 3_000),
            ("reject_2", "REJECT", "episode_4", 4_000),
        )
    )
    similarities = tuple(
        EntryPairSimilarity(entry_id, reject_id, similarity)
        for entry_id, reject_id, similarity in (
            ("entry_1", "reject_1", 99.0),
            ("entry_1", "reject_2", 98.0),
            ("entry_2", "reject_1", 97.0),
            ("entry_2", "reject_2", 10.0),
        )
    )

    matches = global_match_entry_reject(
        decisions,
        similarities,
        similarity_threshold=75.0,
    )

    assert {
        (pair.entry_decision_event_id, pair.reject_decision_event_id)
        for pair in matches
    } == {("entry_1", "reject_2"), ("entry_2", "reject_1")}
    assert len({pair.entry_decision_event_id for pair in matches}) == 2
    assert len({pair.reject_decision_event_id for pair in matches}) == 2


def test_global_matching_orients_dense_matrix_by_the_smaller_label_class(
    monkeypatch,
):
    decisions = tuple(
        EntryDecisionForComparison(
            decision_event_id=f"entry_{index:03d}",
            label="ENTRY",
            setup_version_id="setup_v1",
            grouping_version_id="group_v1",
            episode_id=f"entry_episode_{index:03d}",
            symbol="BTCUSDT",
            direction="LONG",
            decision_timeframe="5m",
            decision_cutoff_utc_ms=index,
        )
        for index in range(100)
    ) + tuple(
        EntryDecisionForComparison(
            decision_event_id=f"reject_{index:03d}",
            label="REJECT",
            setup_version_id="setup_v1",
            grouping_version_id="group_v1",
            episode_id=f"reject_episode_{index:03d}",
            symbol="BTCUSDT",
            direction="LONG",
            decision_timeframe="5m",
            decision_cutoff_utc_ms=1_000 + index,
        )
        for index in range(2)
    )
    similarities = tuple(
        EntryPairSimilarity(
            f"entry_{entry_index:03d}",
            f"reject_{reject_index:03d}",
            90.0,
        )
        for entry_index in range(100)
        for reject_index in range(2)
    )
    from scipy.optimize import linear_sum_assignment as actual_assignment
    observed_shapes = []

    def capture_shape(costs):
        observed_shapes.append(costs.shape)
        return actual_assignment(costs)

    monkeypatch.setattr(
        outcome_comparison_module,
        "_solve_assignment",
        capture_shape,
    )

    matches = global_match_entry_reject(decisions, similarities)

    assert len(matches) == 2
    assert observed_shapes == [(2, 102)]


def test_global_matching_prioritizes_cardinality_before_total_distance():
    decisions = tuple(
        EntryDecisionForComparison(
            decision_event_id=f"{label.lower()}_{index}",
            label=label,
            setup_version_id="setup_v1",
            grouping_version_id="group_v1",
            episode_id=f"{label.lower()}_episode_{index}",
            symbol="BTCUSDT",
            direction="LONG",
            decision_timeframe="5m",
            decision_cutoff_utc_ms=index,
        )
        for label in ("ENTRY", "REJECT")
        for index in range(10)
    )
    similarities = tuple(
        EntryPairSimilarity(entry_id, reject_id, similarity)
        for entry_id, reject_id, similarity in (
            *((f"entry_{index}", f"reject_{index}", 100.0) for index in range(9)),
            ("entry_9", "reject_0", 75.0),
            *((f"entry_{index}", f"reject_{index + 1}", 75.0) for index in range(9)),
        )
    )

    matches = global_match_entry_reject(decisions, similarities)

    assert len(matches) == 10


@pytest.mark.parametrize(
    ("pair_count", "episode_count", "expected"),
    (
        (9, 5, EntryOutcomeEvidenceStage.INSUFFICIENT),
        (10, 4, EntryOutcomeEvidenceStage.INSUFFICIENT),
        (10, 5, EntryOutcomeEvidenceStage.EXPLORATORY),
        (29, 10, EntryOutcomeEvidenceStage.EXPLORATORY),
        (30, 9, EntryOutcomeEvidenceStage.EXPLORATORY),
        (30, 10, EntryOutcomeEvidenceStage.FORMAL),
    ),
)
def test_evidence_stage_and_preregistered_calipers_are_fixed(
    pair_count,
    episode_count,
    expected,
):
    assert ENTRY_MATCH_SENSITIVITY_THRESHOLDS == (70.0, 75.0, 80.0)
    assert classify_entry_outcome_evidence_stage(
        pair_count=pair_count,
        episode_count=episode_count,
    ) is expected


def test_pair_differences_are_reduced_to_one_median_per_entry_episode():
    summary = aggregate_entry_episode_differences(
        (
            EntryPairOutcomeDifference("entry_1", "reject_1", "episode_a", 1.0),
            EntryPairOutcomeDifference("entry_2", "reject_2", "episode_a", 100.0),
            EntryPairOutcomeDifference("entry_3", "reject_3", "episode_b", -1.0),
            EntryPairOutcomeDifference("entry_4", "reject_4", "episode_c", 2.0),
        )
    )

    assert summary.pair_count == 4
    assert summary.episode_count == 3
    assert tuple(item.value for item in summary.episodes) == pytest.approx(
        (50.5, -1.0, 2.0)
    )
    assert summary.median_difference == pytest.approx(2.0)
    assert summary.mean_difference == pytest.approx((50.5 - 1.0 + 2.0) / 3.0)
    assert summary.rank_biserial == pytest.approx(1.0 / 3.0)


def test_pairs_sharing_either_market_episode_are_one_evidence_cluster():
    summary = aggregate_entry_episode_differences(
        (
            EntryPairOutcomeDifference(
                "entry_a",
                "reject_a",
                "episode_entry_a",
                0.02,
                counterparty_episode_id="episode_reject_shared",
            ),
            EntryPairOutcomeDifference(
                "entry_b",
                "reject_b",
                "episode_entry_b",
                0.04,
                counterparty_episode_id="episode_reject_shared",
            ),
        )
    )

    assert summary.pair_count == 2
    assert summary.episode_count == 1
    assert summary.episodes[0].value == pytest.approx(0.03)


def test_cluster_bootstrap_and_episode_sign_flip_are_seed_reproducible():
    summary = aggregate_entry_episode_differences(
        tuple(
            EntryPairOutcomeDifference(
                f"entry_{index}",
                f"reject_{index}",
                f"episode_{index:02d}",
                value,
            )
            for index, value in enumerate(
                (-0.04, -0.02, -0.01, 0.01, 0.02, 0.03, 0.05, 0.08, 0.13, 0.21)
            )
        )
    )

    first = infer_entry_episode_differences(summary, random_seed=17)
    repeated = infer_entry_episode_differences(summary, random_seed=17)

    assert first == repeated
    assert first.bootstrap_draws == 5_000
    assert first.permutation_draws == 10_000
    assert first.random_seed == 17
    assert first.ci_low <= summary.median_difference <= first.ci_high
    assert 0.0 <= first.p_value <= 1.0


def test_all_fifteen_outcomes_share_one_benjamini_hochberg_family():
    q_values = adjust_entry_outcome_family(
        (0.001, 0.01, 0.03, *([None] * 12))
    )

    assert q_values[:3] == pytest.approx((0.015, 0.075, 0.15))
    assert q_values[3:] == (None,) * 12

    with pytest.raises(ValueError, match="exactly 15"):
        adjust_entry_outcome_family((0.01,) * 14)


def test_formal_matrix_keeps_all_fifteen_items_and_requires_bh_plus_interval():
    template = MatchedEntryPair(
        entry_decision_event_id="entry_0",
        reject_decision_event_id="reject_0",
        entry_episode_id="episode_0",
        reject_episode_id="control_episode_0",
        symbol="BTCUSDT",
        decision_timeframe="5m",
        similarity=90.0,
        context_distance=0.1,
        similarity_threshold=75.0,
    )
    pairs = tuple(
        replace(
            template,
            entry_decision_event_id=f"entry_{index}",
            reject_decision_event_id=f"reject_{index}",
            entry_episode_id=f"episode_{index % 10}",
            reject_episode_id=f"control_episode_{index % 10}",
        )
        for index in range(30)
    )

    def path(value):
        return EntryOutcomePath(
            direction="LONG",
            execution_price=100.0,
            outcomes=tuple(
                EntryOutcomeValue(horizon, metric, value)
                for horizon in (1, 3, 5, 10, 20)
                for metric in EntryOutcomeMetric
            ),
        )

    paths = {
        **{
            f"entry_{index}": path(0.01 * (1 + index % 10))
            for index in range(30)
        },
        **{f"reject_{index}": path(0.00) for index in range(30)},
    }

    matrix = build_entry_outcome_matrix(
        pairs,
        paths,
        random_seed=17,
        bootstrap_draws=500,
        permutation_draws=10_000,
    )

    assert len(matrix) == 15
    assert [(cell.horizon_bars, cell.metric) for cell in matrix] == [
        (horizon, metric)
        for horizon in (1, 3, 5, 10, 20)
        for metric in EntryOutcomeMetric
    ]
    assert all(cell.stage is EntryOutcomeEvidenceStage.FORMAL for cell in matrix)
    assert all(
        cell.q_value is not None and cell.q_value < 0.05
        for cell in matrix
    ), [(cell.p_value, cell.q_value) for cell in matrix]
    assert all(cell.ci_low > 0.0 for cell in matrix)
    assert all(
        cell.evidence_status is EntryOutcomeEvidenceStatus.DIFFERENCE_EVIDENCE
        for cell in matrix
    )


@pytest.mark.parametrize(
    ("stage", "q_value", "ci", "expected"),
    (
        (
            EntryOutcomeEvidenceStage.EXPLORATORY,
            None,
            (None, None),
            EntryOutcomeEvidenceStatus.INSUFFICIENT,
        ),
        (
            EntryOutcomeEvidenceStage.FORMAL,
            0.01,
            (-0.01, 0.02),
            EntryOutcomeEvidenceStatus.NO_RELIABLE_DIFFERENCE,
        ),
        (
            EntryOutcomeEvidenceStage.FORMAL,
            0.05,
            (0.01, 0.02),
            EntryOutcomeEvidenceStatus.NO_RELIABLE_DIFFERENCE,
        ),
        (
            EntryOutcomeEvidenceStage.FORMAL,
            0.10,
            (0.01, 0.02),
            EntryOutcomeEvidenceStatus.NO_RELIABLE_DIFFERENCE,
        ),
        (
            EntryOutcomeEvidenceStage.FORMAL,
            0.01,
            (0.01, 0.02),
            EntryOutcomeEvidenceStatus.DIFFERENCE_EVIDENCE,
        ),
    ),
)
def test_evidence_status_requires_both_strict_bh_and_nonzero_interval(
    stage,
    q_value,
    ci,
    expected,
):
    assert classify_entry_outcome_evidence_status(
        stage=stage,
        q_value=q_value,
        ci_low=ci[0],
        ci_high=ci[1],
    ) is expected


def test_public_service_runs_three_calipers_and_round_trips_an_audited_matrix(
    tmp_path,
    monkeypatch,
):
    storage = StorageManager(tmp_path / "entry_outcome.db")
    setup = SetupLibrary(storage).create_setup(
        CreateSetup(
            display_name="后验比较",
            version=SetupVersionSpec(
                direction=SetupDirection.LONG,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="只比较盲态明确判断。",
                timeframes=TimeframeProfile("1m", "5m", "15m"),
            ),
        )
    ).version
    cutoff = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    source_ids = ("source_entry_1", "source_entry_2", "source_reject_1", "source_reject_2")
    grouping = MarketEpisodeService(storage).create_automatic_grouping(
        tuple(
            ResearchSampleWindow(
                sample_id=source_id,
                symbol="BTCUSDT",
                timeframe="1m",
                feature_window=TimeRange(cutoff - timedelta(hours=2), cutoff),
                outcome_window=TimeRange(cutoff, cutoff + timedelta(minutes=20)),
            )
            for source_id in source_ids
        ),
        created_at=cutoff,
    )
    _store_outcome_klines(storage, cutoff)
    episode_by_source = grouping.episode_id_by_sample()
    cutoff_ms = int(cutoff.timestamp() * 1_000) - 1
    for index, source_id in enumerate(source_ids):
        label = "ENTRY" if "entry" in source_id else "REJECT"
        event_id = f"decision_{index}"
        judgment_id = f"judgment_{index}"
        created_at = (cutoff + timedelta(seconds=index)).isoformat()
        assert storage.insert_entry_decision_event(
            event={
                "decision_event_id": event_id,
                "source_sample_id": source_id,
                "setup_version_id": setup.setup_version_id,
                "grouping_version_id": grouping.grouping_version_id,
                "episode_id": episode_by_source[source_id],
                "session_id": None,
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "decision_timeframe": "1m",
                "context_timeframe_one": "5m",
                "context_timeframe_two": "15m",
                "decision_cutoff_utc_ms": cutoff_ms,
                "decision_bar_open_time_utc_ms": cutoff_ms - 59_999,
                "observed_action_time_utc_ms": None,
                "timing_approximate": False,
                "created_at": created_at,
            },
            original_action={
                "seed_source": "MANUAL_POSITION",
                "original_action": "NONE",
                "source_event_id": None,
                "action_time_utc_ms": None,
                "created_at": created_at,
            },
        )
        assert storage.insert_entry_judgment(
            {
                "judgment_id": judgment_id,
                "decision_event_id": event_id,
                "version_number": 1,
                "phase": "BLIND",
                "label": label,
                "reason_tags": (),
                "confidence": 3,
                "note": "",
                "previous_judgment_id": None,
                "eligible_for_primary_research": True,
                "created_at": created_at,
            }
        )
        assert storage.insert_entry_review_reveal(
            {
                "decision_event_id": event_id,
                "blind_judgment_id": judgment_id,
                "revealed_at": created_at,
            }
        )

    service = EntryOutcomeComparisonService(
        storage,
        clock=lambda: datetime(2026, 7, 20, tzinfo=UTC),
    )
    outcome_reads = []
    comparison_calls = []
    fetch_klines_for_range = storage.fetch_klines_for_range
    compare_snapshots = (
        outcome_service_module.compare_entry_structural_snapshot_sets
    )

    def tracked_fetch_klines_for_range(**kwargs):
        if int(kwargs["start_time_utc_ms"]) > cutoff_ms:
            outcome_reads.append(kwargs["start_time_utc_ms"])
        return fetch_klines_for_range(**kwargs)

    def tracked_compare_snapshots(*args, **kwargs):
        assert outcome_reads == []
        comparison_calls.append(True)
        return compare_snapshots(*args, **kwargs)

    monkeypatch.setattr(
        storage,
        "fetch_klines_for_range",
        tracked_fetch_klines_for_range,
    )
    monkeypatch.setattr(
        outcome_service_module,
        "compare_entry_structural_snapshot_sets",
        tracked_compare_snapshots,
    )
    result = service.run(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        direction="LONG",
        random_seed=20260720,
    )

    assert len(comparison_calls) == 4
    assert outcome_reads
    assert tuple(item.similarity_threshold for item in result.sensitivities) == (
        70.0,
        75.0,
        80.0,
    )
    assert result.primary.similarity_threshold == 75.0
    assert len(result.primary.pairs) == 2
    assert len(result.primary.matrix) == 15
    assert tuple(
        item.decision_event_id for item in result.eligible_decisions
    ) == (
        "decision_0",
        "decision_1",
        "decision_2",
        "decision_3",
    )
    assert tuple(
        item.blind_judgment_id for item in result.eligible_decisions
    ) == (
        "judgment_0",
        "judgment_1",
        "judgment_2",
        "judgment_3",
    )
    assert len(result.input_feature_fingerprint) == 64
    assert set(result.input_feature_fingerprint) <= set("0123456789abcdef")
    with pytest.raises(ValueError, match="input feature fingerprint"):
        replace(result, input_feature_fingerprint="not-a-sha256")
    with pytest.raises(ValueError, match="three preregistered sensitivities"):
        replace(result, sensitivities=result.sensitivities[:2])
    primary_with_unknown_event = replace(
        result.primary,
        pairs=(
            replace(
                result.primary.pairs[0],
                entry_decision_event_id="outside_eligible_universe",
            ),
            *result.primary.pairs[1:],
        ),
    )
    with pytest.raises(ValueError, match="eligible decision universe"):
        replace(
            result,
            sensitivities=(
                result.sensitivities[0],
                primary_with_unknown_event,
                result.sensitivities[2],
            ),
        )
    with pytest.raises(ValueError, match="matched similarity"):
        replace(result.primary.pairs[0], similarity=float("nan"))
    records = result.matrix_records()
    assert len(records) == 15
    assert {record["metric"] for record in records} == {
        "close_return",
        "mfe",
        "mae",
    }
    assert all("q_value" in record for record in records)
    assert service.get_result(result.comparison_id) == result
    with storage.connect() as conn:
        match_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM entry_outcome_matches
            WHERE comparison_id=?
            """,
            (result.comparison_id,),
        ).fetchone()[0]
        assert match_count == 6
        persisted_input_fingerprint = conn.execute(
            """
            SELECT input_feature_fingerprint
            FROM entry_outcome_comparisons
            WHERE comparison_id=?
            """,
            (result.comparison_id,),
        ).fetchone()[0]
        assert persisted_input_fingerprint == result.input_feature_fingerprint
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                UPDATE entry_outcome_comparisons
                SET random_seed=1
                WHERE comparison_id=?
                """,
                (result.comparison_id,),
            )

    failed_comparison_id = "comparison_forced_transaction_failure"
    with storage.connect() as conn:
        conn.execute(
            """
            CREATE TRIGGER fail_entry_outcome_match_insert
            BEFORE INSERT ON entry_outcome_matches
            WHEN NEW.comparison_id='comparison_forced_transaction_failure'
            BEGIN
                SELECT RAISE(ABORT, 'forced match insert failure');
            END
            """
        )
    with pytest.raises(DatabaseError, match="forced match insert failure"):
        storage.save_entry_outcome_result(
            replace(result, comparison_id=failed_comparison_id)
        )
    assert storage.get_entry_outcome_result(failed_comparison_id) is None


def _store_outcome_klines(storage: StorageManager, cutoff: datetime) -> None:
    cutoff_ms = int(cutoff.timestamp() * 1_000)
    rows = []
    for interval, duration_ms in (("1m", 60_000), ("5m", 300_000), ("15m", 900_000)):
        for offset in range(-80, 21):
            open_time = cutoff_ms + offset * duration_ms
            base = 100.0 + 0.03 * (offset + 80) + math.sin(offset / 7.0)
            rows.append(
                {
                    "symbol": "BTCUSDT",
                    "interval": interval,
                    "open_time_utc_ms": open_time,
                    "open_time_bjt": datetime.fromtimestamp(
                        open_time / 1_000,
                        UTC,
                    ).isoformat(),
                    "close_time_utc_ms": open_time + duration_ms - 1,
                    "open": base - 0.05,
                    "high": base + 0.8,
                    "low": base - 0.8,
                    "close": base,
                    "volume": 100.0 + offset + 80,
                    "quote_volume": (100.0 + offset + 80) * base,
                    "trade_count": 20 + offset + 80,
                    "taker_buy_base_volume": 50.0 + (offset + 80) / 2.0,
                    "taker_buy_quote_volume": (50.0 + (offset + 80) / 2.0) * base,
                    "source": "test_exchange",
                    "downloaded_at": cutoff.isoformat(),
                    "data_quality_status": "ok",
                }
            )
    storage.upsert_klines(rows)
