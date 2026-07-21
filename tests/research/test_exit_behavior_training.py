from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import sqlite3

import pytest
import services.entry_behavior_training as behavior_service_module

from research.entry_behavior_model import (
    BehaviorFeatureValue,
    EntryBehaviorScoreStatus,
    BehaviorModelTarget,
    BehaviorTrainingRequest,
    BehaviorTrainingSample,
    EXIT_BEHAVIOR_FEATURES,
    LeaveEpisodeOutSimilarity,
    score_behavior_features,
)
from research.entry_behavior_training import fit_behavior_model
from research.exit_behavior_features import build_exit_position_state
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
from services.entry_behavior_training import BehaviorTrainingService
from storage import StorageManager


BASE_TIME = datetime(2025, 1, 1, tzinfo=UTC)


def test_shared_behavior_engine_trains_exit_now_against_hold():
    samples = _typed_exit_samples(60)

    result = fit_behavior_model(
        samples,
        request=BehaviorTrainingRequest(
            target=BehaviorModelTarget.EXIT_SELECTION,
            setup_version_id="setup_version_exit",
            grouping_version_id="grouping_exit",
            direction="LONG",
            seed=20260719,
        ),
        app_version="1.6-test",
        experiment_id="exit_experiment_tracer",
        model_version_id="exit_model_tracer",
        created_at="2026-07-19T00:00:00+00:00",
    )

    assert result.model is not None
    assert result.target is BehaviorModelTarget.EXIT_SELECTION
    assert result.model.target is BehaviorModelTarget.EXIT_SELECTION
    assert result.model.manifest.label_counts == (
        ("EXIT_NOW", 30),
        ("HOLD", 30),
    )
    assert result.model.manifest.positive_label == "EXIT_NOW"
    assert result.model.manifest.negative_label == "HOLD"
    assert result.model.manifest.episode_kind == "HOLDING"


def test_shared_behavior_domain_rejects_cross_target_model_state():
    result = fit_behavior_model(
        _typed_exit_samples(60),
        request=BehaviorTrainingRequest(
            target=BehaviorModelTarget.EXIT_SELECTION,
            setup_version_id="setup_version_exit_identity",
            grouping_version_id="grouping_exit_identity",
            direction="LONG",
        ),
        app_version="1.6-test",
        experiment_id="exit_experiment_identity",
        model_version_id="exit_model_identity",
        created_at="2026-07-19T00:00:00+00:00",
    )
    assert result.model is not None

    with pytest.raises(ValueError, match="target"):
        replace(result.model, target=BehaviorModelTarget.ENTRY_SELECTION)
    with pytest.raises(ValueError, match="target"):
        replace(result, target=BehaviorModelTarget.ENTRY_SELECTION)


def test_exit_score_is_suppressed_outside_the_holding_episode_domain():
    samples = _typed_exit_samples(100)
    leave_scores = tuple(
        LeaveEpisodeOutSimilarity(
            decision_event_id=f"exit_sample_{index * 2:03d}",
            episode_id=f"holding_episode_{index * 2:03d}",
            reference_episode_ids=(
                f"reference_{index}_a",
                f"reference_{index}_b",
                f"reference_{index}_c",
            ),
            similarity=50.0 + index,
        )
        for index in range(10)
    )
    result = fit_behavior_model(
        samples,
        request=BehaviorTrainingRequest(
            target=BehaviorModelTarget.EXIT_SELECTION,
            setup_version_id="setup_version_exit_score",
            grouping_version_id="grouping_exit_score",
            direction="LONG",
        ),
        app_version="1.6-test",
        experiment_id="exit_experiment_score",
        model_version_id="exit_model_score",
        created_at="2026-07-19T00:00:00+00:00",
        leave_episode_out_scores=leave_scores,
    )

    assert result.model is not None
    threshold = result.model.applicability_threshold
    assert threshold is not None
    outside = score_behavior_features(
        result.model,
        samples[0].features,
        structural_similarity=threshold - 0.01,
    )
    inside = score_behavior_features(
        result.model,
        samples[0].features,
        structural_similarity=threshold,
    )

    assert outside.status is EntryBehaviorScoreStatus.OUT_OF_DOMAIN
    assert outside.selection_tendency is None
    assert "立即平仓选择倾向" in outside.message_zh
    assert inside.status is EntryBehaviorScoreStatus.COMPUTED
    assert inside.selection_tendency is not None


def test_exit_latest_twenty_percent_cannot_change_model_selection():
    samples = _typed_exit_samples(100)
    changed_holdout = tuple(
        replace(
            sample,
            features=tuple(
                replace(feature, value=feature.value * -10_000.0)
                for feature in sample.features
            ),
        )
        if index >= 80
        else sample
        for index, sample in enumerate(samples)
    )
    request = BehaviorTrainingRequest(
        target=BehaviorModelTarget.EXIT_SELECTION,
        setup_version_id="setup_version_exit_holdout",
        grouping_version_id="grouping_exit_holdout",
        direction="LONG",
        seed=37,
    )
    common = {
        "request": request,
        "app_version": "1.6-test",
        "created_at": "2026-07-19T00:00:00+00:00",
    }

    original = fit_behavior_model(
        samples,
        experiment_id="exit_experiment_holdout_a",
        model_version_id="exit_model_holdout_a",
        **common,
    )
    changed = fit_behavior_model(
        changed_holdout,
        experiment_id="exit_experiment_holdout_b",
        model_version_id="exit_model_holdout_b",
        **common,
    )

    assert original.model is not None
    assert changed.model is not None
    manifest = original.model.manifest
    assert manifest.test_sample_ids == tuple(
        sample.decision_event_id for sample in samples[80:]
    )
    assert set(manifest.test_episode_ids).isdisjoint(
        episode_id
        for fold in manifest.temporal_folds
        for episode_id in (
            *fold.train_episode_ids,
            *fold.validation_episode_ids,
        )
    )
    assert manifest.selected_c == changed.model.manifest.selected_c
    assert original.model.research_threshold == changed.model.research_threshold
    assert original.model.intercept == changed.model.intercept
    assert original.model.stable_features == changed.model.stable_features
    assert manifest.test_metrics != changed.model.manifest.test_metrics


def test_exit_label_flip_reverses_the_encoded_training_target():
    samples = _typed_exit_samples(60)
    flipped = tuple(
        replace(
            sample,
            label="HOLD" if sample.label == "EXIT_NOW" else "EXIT_NOW",
        )
        for sample in samples
    )
    request = BehaviorTrainingRequest(
        target=BehaviorModelTarget.EXIT_SELECTION,
        setup_version_id="setup_version_exit_flip",
        grouping_version_id="grouping_exit_flip",
        direction="LONG",
    )
    common = {
        "request": request,
        "app_version": "1.6-test",
        "created_at": "2026-07-19T00:00:00+00:00",
    }

    original = fit_behavior_model(
        samples,
        experiment_id="exit_experiment_flip_a",
        model_version_id="exit_model_flip_a",
        **common,
    )
    reversed_labels = fit_behavior_model(
        flipped,
        experiment_id="exit_experiment_flip_b",
        model_version_id="exit_model_flip_b",
        **common,
    )

    assert original.model is not None
    assert reversed_labels.model is not None
    for left_fold, right_fold in zip(
        original.model.manifest.temporal_folds,
        reversed_labels.model.manifest.temporal_folds,
        strict=True,
    ):
        assert left_fold.validation_sample_ids == right_fold.validation_sample_ids
        assert right_fold.validation_labels == tuple(
            1 - label for label in left_fold.validation_labels
        )


def test_short_position_state_uses_direction_adjusted_path_values():
    long_rows = (
        {
            "open_time_utc_ms": 0,
            "high": 104.0,
            "low": 98.0,
            "close": 103.0,
        },
        {
            "open_time_utc_ms": 60_000,
            "high": 106.0,
            "low": 101.0,
            "close": 102.0,
        },
    )
    short_rows = tuple(
        {
            **row,
            "high": 200.0 - row["low"],
            "low": 200.0 - row["high"],
            "close": 200.0 - row["close"],
        }
        for row in long_rows
    )

    long_state = build_exit_position_state(
        long_rows,
        direction="LONG",
        actual_entry_price=100.0,
        entry_atr20=2.0,
    )
    short_state = build_exit_position_state(
        short_rows,
        direction="SHORT",
        actual_entry_price=100.0,
        entry_atr20=2.0,
    )

    assert short_state == long_state


def test_exit_failed_experiment_is_persisted_without_overwriting_entry_models(
    tmp_path,
):
    storage = StorageManager(tmp_path / "exit_behavior_failed.db")
    setup = SetupLibrary(storage).create_setup(
        CreateSetup(
            display_name="平仓选择倾向测试",
            version=SetupVersionSpec(
                direction=SetupDirection.LONG,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="只使用平仓判断截止点及以前的信息。",
                timeframes=TimeframeProfile("1m", "5m", "15m"),
            ),
        )
    ).version
    grouping = MarketEpisodeService(storage).create_automatic_grouping(
        (
            ResearchSampleWindow(
                sample_id="exit_seed_000",
                symbol="BTCUSDT",
                timeframe="1m",
                feature_window=TimeRange(
                    BASE_TIME - timedelta(hours=16),
                    BASE_TIME,
                ),
                outcome_window=TimeRange(
                    BASE_TIME,
                    BASE_TIME + timedelta(minutes=20),
                ),
            ),
        ),
        created_at=BASE_TIME,
    )
    service = BehaviorTrainingService(
        storage,
        app_version="1.6-test",
        clock=lambda: datetime(2026, 7, 19, tzinfo=UTC),
    )

    result = service.train(
        BehaviorTrainingRequest(
            target=BehaviorModelTarget.EXIT_SELECTION,
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping.grouping_version_id,
            direction="LONG",
        )
    )

    assert result.failure is not None
    assert result.failure.code == "INSUFFICIENT_LABELS"
    assert result.model is None
    assert service.get_result(
        result.experiment_id,
        target=BehaviorModelTarget.EXIT_SELECTION,
    ) == result
    assert service.list_models(
        target=BehaviorModelTarget.EXIT_SELECTION,
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        direction="LONG",
    ) == ()
    assert storage.fetch_table("entry_behavior_experiments") == []


def test_public_exit_training_uses_market_and_position_state_without_account_pressure(
    tmp_path,
):
    storage = StorageManager(tmp_path / "exit_behavior_success.db")
    setup = _setup_version(storage)
    sample_times = tuple(
        BASE_TIME + timedelta(days=index * 2) for index in range(60)
    )
    grouping = _grouping(storage, sample_times)
    _store_exit_training_samples(
        storage,
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        sample_times=sample_times,
    )
    service = BehaviorTrainingService(
        storage,
        app_version="1.6-test",
        clock=lambda: datetime(2026, 7, 19, tzinfo=UTC),
    )

    rows = storage.list_behavior_training_events(
        target=BehaviorModelTarget.EXIT_SELECTION,
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        direction="LONG",
    )
    result = service.train(
        BehaviorTrainingRequest(
            target=BehaviorModelTarget.EXIT_SELECTION,
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping.grouping_version_id,
            direction="LONG",
            seed=20260719,
        )
    )

    assert len(rows) == 60
    assert all(
        "position_equity_ratio" not in row
        and "account_drawdown_pct" not in row
        and "realized_pnl_quote" not in row
        and "net_pnl_quote" not in row
        for row in rows
    )
    assert result.model is not None
    assert result.model.manifest.label_counts == (
        ("EXIT_NOW", 30),
        ("HOLD", 30),
    )
    assert result.model.manifest.feature_limit == 6
    assert result.model.stable_features
    assert all(
        feature.feature_id
        in {definition.feature_id for definition in EXIT_BEHAVIOR_FEATURES}
        and "account" not in feature.feature_id
        for feature in result.model.stable_features
    )
    assert service.get_model(
        result.model.model_version_id,
        target=BehaviorModelTarget.EXIT_SELECTION,
    ) == result.model
    assert storage.fetch_table("entry_behavior_experiments") == []
    assert storage.fetch_table("entry_behavior_model_versions") == []
    assert service.model_freshness(
        result.model.model_version_id,
        target=BehaviorModelTarget.EXIT_SELECTION,
    ).needs_retraining is False


def test_exit_applicability_excludes_each_holding_episode_from_its_references(
    tmp_path,
):
    storage = StorageManager(tmp_path / "exit_behavior_domain.db")
    setup = _setup_version(storage)
    sample_times = tuple(
        BASE_TIME + timedelta(days=index * 2) for index in range(60)
    )
    grouping = _grouping(storage, sample_times)
    _store_exit_training_samples(
        storage,
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        sample_times=sample_times,
    )

    result = BehaviorTrainingService(
        storage,
        app_version="1.6-test",
    ).train(
        BehaviorTrainingRequest(
            target=BehaviorModelTarget.EXIT_SELECTION,
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping.grouping_version_id,
            direction="LONG",
        )
    )

    assert result.model is not None
    scores = result.model.manifest.leave_episode_out_scores
    assert len(scores) == 30
    assert result.model.applicability_threshold is not None
    assert all(
        score.episode_id not in score.reference_episode_ids
        and len(set(score.reference_episode_ids)) == 3
        for score in scores
    )


def test_exit_training_groups_multiple_decisions_from_one_position_lifecycle(
    tmp_path,
):
    storage = StorageManager(tmp_path / "exit_holding_episode.db")
    setup = _setup_version(storage)
    sample_times = (BASE_TIME, BASE_TIME + timedelta(days=2))
    grouping = _grouping(storage, sample_times)
    _store_exit_training_samples(
        storage,
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        sample_times=sample_times,
        shared_trade_id="shared_position_lifecycle",
    )

    rows = storage.list_behavior_training_events(
        target=BehaviorModelTarget.EXIT_SELECTION,
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        direction="LONG",
    )

    assert len({row["episode_id"] for row in rows}) == 2
    assert {row["holding_episode_id"] for row in rows} == {
        "shared_position_lifecycle"
    }


def test_exit_training_universe_excludes_post_outcome_relabels(tmp_path):
    storage = StorageManager(tmp_path / "exit_post_outcome_exclusion.db")
    setup = _setup_version(storage)
    sample_times = (BASE_TIME, BASE_TIME + timedelta(days=2))
    grouping = _grouping(storage, sample_times)
    _store_exit_training_samples(
        storage,
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        sample_times=sample_times,
    )
    assert storage.insert_exit_judgment(
        {
            "judgment_id": "exit_post_outcome_relabel",
            "decision_event_id": "exit_decision_000",
            "version_number": 2,
            "phase": "POST_OUTCOME",
            "label": "HOLD",
            "reason_tags": ("future_seen",),
            "confidence": 5,
            "note": "后验复标不能进入行为模型。",
            "previous_judgment_id": "exit_judgment_000",
            "eligible_for_primary_research": False,
            "created_at": sample_times[0].isoformat(),
        }
    )

    rows = storage.list_behavior_training_events(
        target=BehaviorModelTarget.EXIT_SELECTION,
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        direction="LONG",
    )

    assert [row["decision_event_id"] for row in rows] == [
        "exit_decision_001"
    ]


def test_missing_frozen_position_state_saves_failed_experiment(tmp_path):
    storage = StorageManager(tmp_path / "exit_behavior_missing_state.db")
    setup = _setup_version(storage)
    grouping = _grouping(storage, (BASE_TIME,))
    _store_exit_training_samples(
        storage,
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        sample_times=(BASE_TIME,),
        missing_entry_atr_index=0,
    )
    service = BehaviorTrainingService(storage, app_version="1.6-test")

    result = service.train(
        BehaviorTrainingRequest(
            target=BehaviorModelTarget.EXIT_SELECTION,
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping.grouping_version_id,
            direction="LONG",
        )
    )

    assert result.failure is not None
    assert result.failure.code == "FEATURE_DATA_INCOMPLETE"
    assert result.model is None
    assert service.get_result(
        result.experiment_id,
        target=BehaviorModelTarget.EXIT_SELECTION,
    ) == result


def test_exit_training_preserves_frozen_tp_sl_configuration_for_applicability(
    tmp_path,
    monkeypatch,
):
    storage = StorageManager(tmp_path / "exit_behavior_risk_levels.db")
    setup = _setup_version(storage)
    grouping = _grouping(storage, (BASE_TIME,))
    _store_exit_training_samples(
        storage,
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        sample_times=(BASE_TIME,),
        take_profit_status="SET",
        take_profit_price=110.0,
        stop_loss_status="SET",
        stop_loss_price=95.0,
    )
    captured = []
    actual_builder = build_exit_position_state

    def capture_builder(rows, **kwargs):
        captured.append(kwargs)
        return actual_builder(rows, **kwargs)

    monkeypatch.setattr(
        behavior_service_module,
        "build_exit_position_state",
        capture_builder,
    )

    BehaviorTrainingService(storage).train(
        BehaviorTrainingRequest(
            target=BehaviorModelTarget.EXIT_SELECTION,
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping.grouping_version_id,
            direction="LONG",
        )
    )

    assert captured[0]["take_profit_status"] == "SET"
    assert captured[0]["take_profit_price"] == pytest.approx(110.0)
    assert captured[0]["stop_loss_status"] == "SET"
    assert captured[0]["stop_loss_price"] == pytest.approx(95.0)


def test_schema_15_upgrade_adds_exit_behavior_tables_and_keeps_prior_rows(
    tmp_path,
):
    db_path = tmp_path / "schema_15_exit_behavior.db"
    backup_dir = tmp_path / "backups"
    legacy = StorageManager(db_path, backup_dir=backup_dir)
    setup = _setup_version(legacy)
    with legacy.connect() as conn:
        conn.executescript(
            """
            DROP TABLE exit_behavior_model_versions;
            DROP TABLE exit_behavior_experiments;
            PRAGMA user_version=15;
            """
        )

    upgraded = StorageManager(db_path, backup_dir=backup_dir)

    assert upgraded.schema_version() == StorageManager.SCHEMA_VERSION
    assert upgraded.get_setup_version(setup.setup_version_id) == setup
    assert upgraded.fetch_table("exit_behavior_experiments") == []
    assert upgraded.fetch_table("exit_behavior_model_versions") == []
    assert list(
        backup_dir.glob(f"*v15_to_v{StorageManager.SCHEMA_VERSION}*.db")
    )


def test_exit_behavior_experiments_are_immutable(tmp_path):
    storage = StorageManager(tmp_path / "immutable_exit_behavior.db")
    setup = _setup_version(storage)
    grouping = _grouping(storage, (BASE_TIME,))
    result = BehaviorTrainingService(
        storage,
        app_version="1.6-test",
    ).train(
        BehaviorTrainingRequest(
            target=BehaviorModelTarget.EXIT_SELECTION,
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping.grouping_version_id,
            direction="LONG",
        )
    )

    with storage.connect() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE exit_behavior_experiments SET direction='SHORT' "
            "WHERE experiment_id=?",
            (result.experiment_id,),
        )


def _setup_version(storage: StorageManager):
    return SetupLibrary(storage).create_setup(
        CreateSetup(
            display_name="平仓选择倾向测试",
            version=SetupVersionSpec(
                direction=SetupDirection.LONG,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="只使用平仓判断截止点及以前的信息。",
                timeframes=TimeframeProfile("1m", "5m", "15m"),
            ),
        )
    ).version


def _typed_exit_samples(count: int) -> tuple[BehaviorTrainingSample, ...]:
    return tuple(
        BehaviorTrainingSample(
            decision_event_id=f"exit_sample_{index:03d}",
            episode_id=f"holding_episode_{index:03d}",
            decision_cutoff_utc_ms=index * 60_000,
            label="EXIT_NOW" if index % 2 == 0 else "HOLD",
            features=tuple(
                BehaviorFeatureValue(
                    feature_id=definition.feature_id,
                    name_zh=definition.name_zh,
                    value=(
                        (1.0 if index % 2 == 0 else -1.0)
                        * (1.0 + feature_index * 0.05)
                        + index * 0.001 * (feature_index + 1)
                    ),
                )
                for feature_index, definition in enumerate(
                    EXIT_BEHAVIOR_FEATURES
                )
            ),
        )
        for index in range(count)
    )


def _grouping(storage: StorageManager, sample_times: tuple[datetime, ...]):
    return MarketEpisodeService(storage).create_automatic_grouping(
        tuple(
            ResearchSampleWindow(
                sample_id=f"exit_sample_{index:03d}",
                symbol="BTCUSDT",
                timeframe="1m",
                feature_window=TimeRange(
                    cutoff - timedelta(hours=16),
                    cutoff,
                ),
                outcome_window=TimeRange(
                    cutoff,
                    cutoff + timedelta(minutes=20),
                ),
            )
            for index, cutoff in enumerate(sample_times)
        ),
        created_at=BASE_TIME,
    )


def _store_exit_training_samples(
    storage: StorageManager,
    *,
    setup_version_id: str,
    grouping_version_id: str,
    sample_times: tuple[datetime, ...],
    missing_entry_atr_index: int | None = None,
    shared_trade_id: str | None = None,
    take_profit_status: str = "NOT_SET",
    take_profit_price: float | None = None,
    stop_loss_status: str = "NOT_SET",
    stop_loss_price: float | None = None,
) -> None:
    assignments = MarketEpisodeService(storage).resolve_episode_ids(
        grouping_version_id,
        tuple(f"exit_sample_{index:03d}" for index in range(len(sample_times))),
    )
    for index, (cutoff, assignment) in enumerate(
        zip(sample_times, assignments, strict=True)
    ):
        label = "EXIT_NOW" if index % 2 == 0 else "HOLD"
        slope = 1.0 if label == "EXIT_NOW" else -1.0
        _store_complete_history(storage, cutoff, slope=slope)
        trade_id = shared_trade_id or f"exit_trade_{index:03d}"
        entry_event_id = (
            f"entry_event_{shared_trade_id}"
            if shared_trade_id
            else f"entry_event_{index:03d}"
        )
        entry_time = cutoff - timedelta(minutes=30)
        if shared_trade_id is None or index == 0:
            storage.insert_trade(
                {
                    "trade_id": trade_id,
                    "symbol": "BTCUSDT",
                    "interval": "1m",
                    "side": "LONG",
                    "status": "OPEN",
                    "entry_event_id": entry_event_id,
                    "entry_bar_time_bjt": entry_time.isoformat(),
                    "entry_real_time_bjt": entry_time.isoformat(),
                    "entry_fill_price": 100.0,
                    "created_at": cutoff.isoformat(),
                    "updated_at": cutoff.isoformat(),
                }
            )
        decision_event_id = f"exit_decision_{index:03d}"
        assert storage.insert_exit_decision_event(
            event={
                "decision_event_id": decision_event_id,
                "source_sample_id": f"exit_sample_{index:03d}",
                "setup_version_id": setup_version_id,
                "review_setup_version_id": setup_version_id,
                "grouping_version_id": grouping_version_id,
                "episode_id": assignment.episode_id,
                "trade_id": trade_id,
                "entry_event_id": entry_event_id,
                "session_id": None,
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "decision_timeframe": "1m",
                "context_timeframe_one": "5m",
                "context_timeframe_two": "15m",
                "decision_cutoff_utc_ms": int(cutoff.timestamp() * 1_000),
                "decision_bar_open_time_utc_ms": int(
                    (cutoff - timedelta(minutes=1)).timestamp() * 1_000
                ),
                "observed_action_time_utc_ms": None,
                "timing_approximate": False,
                "setup_link_status": "LINKED",
                "eligible_for_formal_research": True,
                "created_at": cutoff.isoformat(),
            },
            position={
                "actual_entry_price": 100.0,
                "entry_price_source": "FILL",
                "entry_atr20": (
                    None if index == missing_entry_atr_index else 2.0
                ),
                "entry_atr_status": (
                    "MISSING"
                    if index == missing_entry_atr_index
                    else "AVAILABLE"
                ),
                "entry_bar_index": 0,
                "decision_bar_index": 30,
                "take_profit_status": take_profit_status,
                "take_profit_price": take_profit_price,
                "stop_loss_status": stop_loss_status,
                "stop_loss_price": stop_loss_price,
                "created_at": cutoff.isoformat(),
            },
            account_pressure={
                "equity_before_decision": 1_000.0,
                "position_notional_quote": 900.0 if label == "EXIT_NOW" else 10.0,
                "position_equity_ratio": 0.9 if label == "EXIT_NOW" else 0.01,
                "total_open_notional_quote": 900.0,
                "total_exposure_ratio": 0.9,
                "open_position_count": 1,
                "account_drawdown_pct": 0.5 if label == "EXIT_NOW" else 0.0,
                "leverage": None,
                "margin_quote": None,
                "liquidation_price": None,
                "created_at": cutoff.isoformat(),
            },
            original_action={
                "seed_source": "MANUAL_POSITION",
                "original_action": "NONE",
                "source_event_id": None,
                "action_time_utc_ms": None,
                "realized_pnl_quote": None,
                "created_at": cutoff.isoformat(),
            },
        )
        assert storage.insert_exit_judgment(
            {
                "judgment_id": f"exit_judgment_{index:03d}",
                "decision_event_id": decision_event_id,
                "version_number": 1,
                "phase": "BLIND",
                "label": label,
                "reason_tags": ("position_path",),
                "confidence": 3,
                "note": "",
                "previous_judgment_id": None,
                "eligible_for_primary_research": True,
                "created_at": cutoff.isoformat(),
            }
        )


def _store_complete_history(
    storage: StorageManager,
    cutoff: datetime,
    *,
    slope: float,
) -> None:
    rows = []
    for interval, minutes in (("1m", 1), ("5m", 5), ("15m", 15)):
        duration = timedelta(minutes=minutes)
        for index in range(62):
            close_time = cutoff - duration * (61 - index)
            open_time = close_time - duration
            close = 100.0 + slope * index * 0.08
            volume = 20.0 + index + (3.0 if slope > 0 else 0.0)
            rows.append(
                {
                    "symbol": "BTCUSDT",
                    "interval": interval,
                    "open_time_utc_ms": int(open_time.timestamp() * 1_000),
                    "open_time_bjt": open_time.isoformat(),
                    "close_time_utc_ms": int(close_time.timestamp() * 1_000),
                    "open": close - slope * 0.04,
                    "high": close + 0.35,
                    "low": close - 0.35,
                    "close": close,
                    "volume": volume,
                    "quote_volume": volume * close,
                    "trade_count": 100 + index,
                    "taker_buy_base_volume": volume * (0.6 if slope > 0 else 0.4),
                    "taker_buy_quote_volume": volume * close * (
                        0.6 if slope > 0 else 0.4
                    ),
                    "source": "test_exchange",
                    "downloaded_at": cutoff.isoformat(),
                    "data_quality_status": "ok",
                }
            )
    storage.upsert_klines(rows)
