from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import sqlite3
from statistics import median

import pytest
from sklearn.exceptions import ConvergenceWarning

import research.entry_behavior_training as behavior_training_engine

from research.entry_behavior_model import (
    ENTRY_BEHAVIOR_FEATURES,
    BehaviorFeatureValue,
    EntryBehaviorExperimentStatus,
    EntryBehaviorModelMaturity,
    EntryBehaviorSample,
    EntryBehaviorScoreStatus,
    EntryBehaviorTrainingRequest,
    LeaveEpisodeOutSimilarity,
    score_entry_behavior_features,
)
from research.entry_behavior_training import fit_entry_behavior_model
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
from services.entry_behavior_training import EntryBehaviorTrainingService
from services.entry_blind_review import EntryBlindReviewService
from storage import StorageManager


BASE_TIME = datetime(2025, 1, 1, tzinfo=UTC)


def test_public_training_creates_a_retrievable_immutable_exploratory_model(
    tmp_path,
):
    storage = StorageManager(tmp_path / "entry_behavior.db")
    setup = _setup_version(storage)
    sample_times = tuple(
        BASE_TIME + timedelta(days=index * 2)
        for index in range(61)
    )
    grouping = _grouping(storage, sample_times)
    _store_blind_training_samples(
        storage,
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        sample_times=sample_times[:60],
    )
    service = EntryBehaviorTrainingService(
        storage,
        app_version="1.6-test",
        clock=lambda: datetime(2026, 7, 19, tzinfo=UTC),
    )

    result = service.train(
        EntryBehaviorTrainingRequest(
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping.grouping_version_id,
            direction="LONG",
            seed=20260719,
        )
    )

    assert result.status is EntryBehaviorExperimentStatus.COMPLETED
    assert result.failure is None
    assert result.model is not None
    assert result.model.maturity is EntryBehaviorModelMaturity.EXPLORATORY
    assert result.model.setup_version_id == setup.setup_version_id
    assert result.model.direction == "LONG"
    assert result.model.manifest.label_counts == (("ENTRY", 30), ("REJECT", 30))
    assert len(result.model.manifest.leave_episode_out_scores) == 30
    assert result.model.applicability_threshold is not None
    assert result.model.manifest.dependency_versions["scikit-learn"] == "1.9.0"
    assert service.get_model(result.model.model_version_id) == result.model

    _store_blind_training_samples(
        storage,
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        sample_times=sample_times[60:],
        start_index=60,
    )
    freshness = service.model_freshness(result.model.model_version_id)
    assert freshness.needs_retraining is True
    assert freshness.new_label_count == 1
    assert "新训练" in freshness.message_zh
    assert service.get_model(result.model.model_version_id) == result.model


def test_training_manifest_proves_episode_pure_time_validation_and_train_only_scaling():
    samples = _typed_behavior_samples(80)
    request = EntryBehaviorTrainingRequest(
        setup_version_id="setup_version_time_split",
        grouping_version_id="grouping_time_split",
        direction="LONG",
        seed=17,
    )

    result = fit_entry_behavior_model(
        samples,
        request=request,
        app_version="1.6-test",
        experiment_id="experiment_time_split",
        model_version_id="model_time_split",
        created_at="2026-07-19T00:00:00+00:00",
    )

    assert result.model is not None
    manifest = result.model.manifest
    assert len(manifest.test_episode_ids) == 16
    assert len(manifest.temporal_folds) >= 3
    assert set(manifest.test_episode_ids).isdisjoint(
        episode_id
        for fold in manifest.temporal_folds
        for episode_id in (
            *fold.train_episode_ids,
            *fold.validation_episode_ids,
        )
    )
    value_by_sample = {
        sample.decision_event_id: {
            feature.feature_id: feature.value
            for feature in sample.features
        }
        for sample in samples
    }
    for fold in manifest.temporal_folds:
        assert set(fold.train_episode_ids).isdisjoint(
            fold.validation_episode_ids
        )
        assert fold.train_end_utc_ms < fold.validation_start_utc_ms
        for normalization in fold.normalizations:
            assert normalization.median == median(
                value_by_sample[sample_id][normalization.feature_id]
                for sample_id in fold.train_sample_ids
            )


def test_regularization_uses_balanced_loss_one_se_and_stable_feature_gate():
    samples = _typed_behavior_samples(100)
    result = fit_entry_behavior_model(
        samples,
        request=EntryBehaviorTrainingRequest(
            setup_version_id="setup_version_regularization",
            grouping_version_id="grouping_regularization",
            direction="LONG",
            seed=23,
        ),
        app_version="1.6-test",
        experiment_id="experiment_regularization",
        model_version_id="model_regularization",
        created_at="2026-07-19T00:00:00+00:00",
    )

    assert result.model is not None
    manifest = result.model.manifest
    assert tuple(item.c_value for item in manifest.regularization_path) == (
        0.03,
        0.1,
        0.3,
        1.0,
        3.0,
    )
    best = min(
        manifest.regularization_path,
        key=lambda item: item.mean_balanced_log_loss,
    )
    one_se_candidates = tuple(
        item
        for item in manifest.regularization_path
        if item.mean_balanced_log_loss
        <= best.mean_balanced_log_loss + best.standard_error
        and item.maximum_nonzero_count <= manifest.feature_limit
    )
    assert manifest.selected_c == min(
        item.c_value for item in one_se_candidates
    )
    for fold in manifest.temporal_folds:
        train_count = sum(count for _label, count in fold.label_counts)
        weights = dict(fold.class_weights)
        counts = dict(fold.label_counts)
        assert weights["ENTRY"] == train_count / (2 * counts["ENTRY"])
        assert weights["REJECT"] == train_count / (2 * counts["REJECT"])
    assert 1 <= len(result.model.stable_features) <= manifest.feature_limit
    assert all(
        feature.nonzero_fold_count * 3 >= feature.fold_count * 2
        for feature in result.model.stable_features
    )
    assert all(
        feature.fold_coefficient_min * feature.fold_coefficient_max > 0.0
        for feature in result.model.stable_features
    )


def test_research_threshold_meets_recall_floor_then_maximizes_precision():
    result = fit_entry_behavior_model(
        _typed_behavior_samples(100),
        request=EntryBehaviorTrainingRequest(
            setup_version_id="setup_version_threshold",
            grouping_version_id="grouping_threshold",
            direction="LONG",
            seed=29,
        ),
        app_version="1.6-test",
        experiment_id="experiment_threshold",
        model_version_id="model_threshold",
        created_at="2026-07-19T00:00:00+00:00",
    )

    assert result.model is not None
    assert result.model.research_threshold is not None
    selection = result.model.manifest.threshold_selection
    assert selection is not None
    assert selection.mean_recall >= 0.80
    assert selection.minimum_fold_recall >= 0.70
    eligible = tuple(
        item
        for item in result.model.manifest.threshold_candidates
        if item.mean_recall >= 0.80 and item.minimum_fold_recall >= 0.70
    )
    best_precision = max(item.mean_precision for item in eligible)
    expected = max(
        item.threshold
        for item in eligible
        if item.mean_precision == best_precision
    )
    assert result.model.research_threshold == expected
    validation = result.model.manifest.validation_metrics
    assert validation.sample_count == sum(
        len(fold.validation_sample_ids)
        for fold in result.model.manifest.temporal_folds
    )
    assert validation.balanced_log_loss >= 0.0
    assert validation.recall is not None
    assert validation.precision is not None


def test_latest_holdout_is_evaluated_once_and_only_qualifying_data_is_formal():
    result = fit_entry_behavior_model(
        _typed_behavior_samples(100),
        request=EntryBehaviorTrainingRequest(
            setup_version_id="setup_version_holdout",
            grouping_version_id="grouping_holdout",
            direction="LONG",
            seed=31,
        ),
        app_version="1.6-test",
        experiment_id="experiment_holdout",
        model_version_id="model_holdout",
        created_at="2026-07-19T00:00:00+00:00",
        leave_episode_out_scores=_leave_episode_out_scores(),
    )

    assert result.model is not None
    assert result.model.maturity is EntryBehaviorModelMaturity.FORMAL
    metrics = result.model.manifest.test_metrics
    assert metrics.sample_count == 20
    assert metrics.label_counts == (("ENTRY", 10), ("REJECT", 10))
    assert metrics.episode_counts == (("ENTRY", 10), ("REJECT", 10))
    assert metrics.balanced_log_loss >= 0.0
    assert 0.0 <= metrics.brier_score <= 1.0
    assert metrics.recall is not None
    assert metrics.precision is not None


def test_leave_episode_out_domain_gate_suppresses_out_of_scope_formal_score():
    samples = _typed_behavior_samples(100)
    leave_episode_out_scores = _leave_episode_out_scores()
    result = fit_entry_behavior_model(
        samples,
        request=EntryBehaviorTrainingRequest(
            setup_version_id="setup_version_domain",
            grouping_version_id="grouping_domain",
            direction="LONG",
            seed=41,
        ),
        app_version="1.6-test",
        experiment_id="experiment_domain",
        model_version_id="model_domain",
        created_at="2026-07-19T00:00:00+00:00",
        leave_episode_out_scores=leave_episode_out_scores,
    )

    assert result.model is not None
    assert result.model.maturity is EntryBehaviorModelMaturity.FORMAL
    expected = 40.9
    assert result.model.applicability_threshold == expected
    assert result.model.manifest.leave_episode_out_scores == (
        leave_episode_out_scores
    )
    assert all(
        item.episode_id not in item.reference_episode_ids
        and len(set(item.reference_episode_ids)) == 3
        for item in result.model.manifest.leave_episode_out_scores
    )

    out_of_scope = score_entry_behavior_features(
        result.model,
        samples[0].features,
        structural_similarity=expected - 0.1,
    )
    assert out_of_scope.status is EntryBehaviorScoreStatus.OUT_OF_DOMAIN
    assert out_of_scope.selection_tendency is None
    assert "超出当前模型适用范围" in out_of_scope.message_zh

    in_scope = score_entry_behavior_features(
        result.model,
        samples[0].features,
        structural_similarity=expected,
    )
    assert in_scope.status is EntryBehaviorScoreStatus.COMPUTED
    assert in_scope.selection_tendency is not None
    assert 0.0 <= in_scope.selection_tendency <= 1.0


def test_all_zero_mad_indicators_return_failed_experiment_without_model():
    samples = tuple(
        replace(
            sample,
            features=tuple(
                replace(feature, value=1.0)
                for feature in sample.features
            ),
        )
        for sample in _typed_behavior_samples(60)
    )

    result = fit_entry_behavior_model(
        samples,
        request=EntryBehaviorTrainingRequest(
            setup_version_id="setup_version_no_stable",
            grouping_version_id="grouping_no_stable",
            direction="LONG",
            seed=43,
        ),
        app_version="1.6-test",
        experiment_id="experiment_no_stable",
        model_version_id="model_must_not_exist",
        created_at="2026-07-19T00:00:00+00:00",
    )

    assert result.status is EntryBehaviorExperimentStatus.FAILED
    assert result.failure is not None
    assert result.failure.code == "NO_STABLE_FEATURES"
    assert result.model is None


def test_nonconverged_solver_returns_failed_experiment_without_model(
    monkeypatch,
):
    class _NonConvergingLogisticRegression:
        def __init__(self, **_kwargs):
            pass

        def fit(self, _design, _labels):
            import warnings

            warnings.warn("did not converge", ConvergenceWarning)
            return self

    monkeypatch.setattr(
        behavior_training_engine,
        "LogisticRegression",
        _NonConvergingLogisticRegression,
    )

    result = fit_entry_behavior_model(
        _typed_behavior_samples(60),
        request=EntryBehaviorTrainingRequest(
            setup_version_id="setup_nonconverged",
            grouping_version_id="grouping_nonconverged",
            direction="LONG",
        ),
        app_version="1.6-test",
        experiment_id="experiment_nonconverged",
        model_version_id="model_must_not_exist",
        created_at="2026-07-19T00:00:00+00:00",
    )

    assert result.status is EntryBehaviorExperimentStatus.FAILED
    assert result.failure is not None
    assert result.failure.code == "NUMERICAL_FAILURE"
    assert result.model is None


def test_public_training_persists_failed_experiment_without_model(tmp_path):
    storage = StorageManager(tmp_path / "failed_entry_behavior.db")
    setup = _setup_version(storage)
    grouping = _grouping(storage, (BASE_TIME,))
    service = EntryBehaviorTrainingService(
        storage,
        app_version="1.6-test",
        clock=lambda: datetime(2026, 7, 19, tzinfo=UTC),
    )

    result = service.train(
        EntryBehaviorTrainingRequest(
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping.grouping_version_id,
            direction="LONG",
        )
    )

    assert result.status is EntryBehaviorExperimentStatus.FAILED
    assert result.failure is not None
    assert result.failure.code == "INSUFFICIENT_LABELS"
    assert service.get_result(result.experiment_id) == result
    assert service.list_models(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        direction="LONG",
    ) == ()
    with storage.connect() as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                "UPDATE entry_behavior_experiments SET status='COMPLETED' "
                "WHERE experiment_id=?",
                (result.experiment_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="completed experiment"):
            conn.execute(
                """
                INSERT INTO entry_behavior_model_versions (
                    model_version_id, experiment_id, setup_version_id,
                    grouping_version_id, direction, maturity,
                    training_cutoff_utc_ms, label_fingerprint,
                    model_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "invalid_model_for_failed_experiment",
                    result.experiment_id,
                    setup.setup_version_id,
                    grouping.grouping_version_id,
                    "LONG",
                    "EXPLORATORY",
                    0,
                    "invalid",
                    "{}",
                    "2026-07-19T00:00:00+00:00",
                ),
            )


def test_public_training_rejects_unknown_grouping_before_persistence(tmp_path):
    storage = StorageManager(tmp_path / "unknown_behavior_grouping.db")
    setup = _setup_version(storage)
    service = EntryBehaviorTrainingService(storage, app_version="1.6-test")

    with pytest.raises(KeyError, match="grouping"):
        service.train(
            EntryBehaviorTrainingRequest(
                setup_version_id=setup.setup_version_id,
                grouping_version_id="missing_grouping",
                direction="LONG",
            )
        )

    assert storage.fetch_table("entry_behavior_experiments") == []


def test_incomplete_feature_data_is_persisted_as_failed_experiment(tmp_path):
    storage = StorageManager(tmp_path / "incomplete_entry_behavior.db")
    setup = _setup_version(storage)
    grouping = _grouping(storage, (BASE_TIME,))
    receipt = EntryBlindReviewService(storage).enqueue_manual_position(
        manual_seed_id="behavior_sample_000",
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        symbol="BTCUSDT",
        direction="LONG",
        decision_time=BASE_TIME,
    )
    assert storage.insert_entry_judgment(
        {
            "judgment_id": "incomplete_behavior_judgment",
            "decision_event_id": receipt.decision_event_id,
            "version_number": 1,
            "phase": "BLIND",
            "label": "ENTRY",
            "reason_tags": (),
            "confidence": 3,
            "note": "",
            "previous_judgment_id": None,
            "eligible_for_primary_research": True,
            "created_at": BASE_TIME.isoformat(),
        }
    )
    service = EntryBehaviorTrainingService(storage, app_version="1.6-test")

    result = service.train(
        EntryBehaviorTrainingRequest(
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping.grouping_version_id,
            direction="LONG",
        )
    )

    assert result.status is EntryBehaviorExperimentStatus.FAILED
    assert result.failure is not None
    assert result.failure.code == "FEATURE_DATA_INCOMPLETE"
    assert result.model is None
    assert service.get_result(result.experiment_id) == result


def test_schema_12_upgrade_adds_immutable_behavior_tables_and_backup(tmp_path):
    db_path = tmp_path / "schema_12_entry_behavior.db"
    backup_dir = tmp_path / "backups"
    legacy = StorageManager(db_path, backup_dir=backup_dir)
    setup = _setup_version(legacy)
    with legacy.connect() as conn:
        conn.executescript(
            """
            DROP TABLE entry_behavior_model_versions;
            DROP TABLE entry_behavior_experiments;
            PRAGMA user_version=12;
            """
        )

    upgraded = StorageManager(db_path, backup_dir=backup_dir)

    assert upgraded.schema_version() == StorageManager.SCHEMA_VERSION
    assert upgraded.get_setup_version(setup.setup_version_id) == setup
    assert upgraded.fetch_table("entry_behavior_experiments") == []
    assert upgraded.fetch_table("entry_behavior_model_versions") == []
    assert list(
        backup_dir.glob(f"*v12_to_v{StorageManager.SCHEMA_VERSION}*.db")
    )


def test_latest_holdout_feature_perturbation_cannot_change_model_selection():
    samples = _typed_behavior_samples(100)
    perturbed = tuple(
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
    request = EntryBehaviorTrainingRequest(
        setup_version_id="setup_version_no_holdout_leakage",
        grouping_version_id="grouping_no_holdout_leakage",
        direction="LONG",
        seed=37,
    )

    original = fit_entry_behavior_model(
        samples,
        request=request,
        app_version="1.6-test",
        experiment_id="experiment_original",
        model_version_id="model_original",
        created_at="2026-07-19T00:00:00+00:00",
    )
    changed_test_only = fit_entry_behavior_model(
        perturbed,
        request=request,
        app_version="1.6-test",
        experiment_id="experiment_perturbed",
        model_version_id="model_perturbed",
        created_at="2026-07-19T00:00:00+00:00",
    )

    assert original.model is not None
    assert changed_test_only.model is not None
    assert original.model.manifest.test_sample_ids == tuple(
        sample.decision_event_id for sample in samples[80:]
    )
    assert original.model.manifest.selected_c == (
        changed_test_only.model.manifest.selected_c
    )
    assert original.model.research_threshold == (
        changed_test_only.model.research_threshold
    )
    assert original.model.intercept == changed_test_only.model.intercept
    assert original.model.stable_features == (
        changed_test_only.model.stable_features
    )
    assert original.model.manifest.test_metrics != (
        changed_test_only.model.manifest.test_metrics
    )


def test_fixed_seed_is_reproducible_and_candidate_scaling_is_clipped():
    samples = _typed_behavior_samples(100)
    request = EntryBehaviorTrainingRequest(
        setup_version_id="setup_version_reproducible",
        grouping_version_id="grouping_reproducible",
        direction="SHORT",
        seed=47,
    )
    arguments = {
        "request": request,
        "app_version": "1.6-test",
        "created_at": "2026-07-19T00:00:00+00:00",
        "leave_episode_out_scores": _leave_episode_out_scores(),
    }

    first = fit_entry_behavior_model(
        samples,
        experiment_id="experiment_reproducible_a",
        model_version_id="model_reproducible_a",
        **arguments,
    )
    second = fit_entry_behavior_model(
        samples,
        experiment_id="experiment_reproducible_b",
        model_version_id="model_reproducible_b",
        **arguments,
    )

    assert first.model is not None
    assert second.model is not None
    assert first.model.intercept == second.model.intercept
    assert first.model.stable_features == second.model.stable_features
    assert first.model.research_threshold == second.model.research_threshold
    assert first.model.manifest.regularization_path == (
        second.model.manifest.regularization_path
    )
    normalizations = {
        item.feature_id: item
        for item in first.model.manifest.normalizations
    }
    extreme = tuple(
        replace(
            feature,
            value=(
                normalizations[feature.feature_id].median
                + normalizations[feature.feature_id].scale * 1_000_000.0
            ),
        )
        if feature.feature_id in normalizations
        else feature
        for feature in samples[0].features
    )
    clipped = tuple(
        replace(
            feature,
            value=(
                normalizations[feature.feature_id].median
                + normalizations[feature.feature_id].scale * 5.0
            ),
        )
        if feature.feature_id in normalizations
        else feature
        for feature in samples[0].features
    )
    extreme_score = score_entry_behavior_features(
        first.model,
        extreme,
        structural_similarity=100.0,
    )
    clipped_score = score_entry_behavior_features(
        first.model,
        clipped,
        structural_similarity=100.0,
    )
    assert extreme_score.selection_tendency == clipped_score.selection_tendency
    with pytest.raises(ValueError, match="formula version"):
        score_entry_behavior_features(
            first.model,
            clipped,
            structural_similarity=100.0,
            formula_version="incompatible-formula",
        )


def test_training_universe_excludes_post_outcome_free_browse_and_uncertain(tmp_path):
    storage = StorageManager(tmp_path / "entry_behavior_universe.db")
    setup = _setup_version(storage)
    sample_times = tuple(
        BASE_TIME + timedelta(days=index * 2) for index in range(5)
    )
    grouping = _grouping(storage, sample_times)
    _store_blind_training_samples(
        storage,
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        sample_times=sample_times[:4],
    )
    eligible_before = storage.list_entry_behavior_training_events(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        direction="LONG",
    )
    first, second = eligible_before[:2]
    assert set(first) == {
        "decision_event_id",
        "source_sample_id",
        "episode_id",
        "symbol",
        "direction",
        "decision_cutoff_utc_ms",
        "blind_judgment_id",
        "blind_label",
    }
    assert storage.insert_entry_judgment(
        {
            "judgment_id": "post_outcome_relabel",
            "decision_event_id": first["decision_event_id"],
            "version_number": 2,
            "phase": "POST_OUTCOME",
            "label": "REJECT",
            "reason_tags": ("future_seen",),
            "confidence": 5,
            "note": "future outcome must not enter training",
            "previous_judgment_id": first["blind_judgment_id"],
            "eligible_for_primary_research": False,
            "created_at": sample_times[0].isoformat(),
        }
    )
    assert storage.exclude_entry_candidate(
        {
            "setup_version_id": setup.setup_version_id,
            "grouping_version_id": grouping.grouping_version_id,
            "source_sample_id": second["source_sample_id"],
            "reason": "FREE_BROWSE_REVEAL",
            "created_at": sample_times[1].isoformat(),
        }
    )
    uncertain_receipt = EntryBlindReviewService(
        storage
    ).enqueue_manual_position(
        manual_seed_id="behavior_sample_004",
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        symbol="BTCUSDT",
        direction="LONG",
        decision_time=sample_times[4],
    )
    assert storage.insert_entry_judgment(
        {
            "judgment_id": "uncertain_blind_judgment",
            "decision_event_id": uncertain_receipt.decision_event_id,
            "version_number": 1,
            "phase": "BLIND",
            "label": "UNCERTAIN",
            "reason_tags": ("uncertain",),
            "confidence": 2,
            "note": "",
            "previous_judgment_id": None,
            "eligible_for_primary_research": True,
            "created_at": sample_times[4].isoformat(),
        }
    )

    eligible_after = storage.list_entry_behavior_training_events(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        direction="LONG",
    )

    assert [row["source_sample_id"] for row in eligible_after] == [
        "behavior_sample_002",
        "behavior_sample_003",
    ]
    assert all(row["blind_label"] in {"ENTRY", "REJECT"} for row in eligible_after)
    assert all("confidence" not in row and "reason_tags" not in row for row in eligible_after)


def test_episode_that_interleaves_final_holdout_is_rejected():
    samples = list(_typed_behavior_samples(100))
    samples[-1] = replace(
        samples[-1],
        episode_id=samples[64].episode_id,
    )

    with pytest.raises(ValueError, match="final test"):
        fit_entry_behavior_model(
            samples,
            request=EntryBehaviorTrainingRequest(
                setup_version_id="setup_interleaved",
                grouping_version_id="grouping_interleaved",
                direction="LONG",
            ),
            app_version="1.6-test",
            experiment_id="experiment_interleaved",
            model_version_id="model_interleaved",
            created_at="2026-07-19T00:00:00+00:00",
        )


def _setup_version(storage: StorageManager):
    return SetupLibrary(storage).create_setup(
        CreateSetup(
            display_name="开仓选择倾向测试",
            version=SetupVersionSpec(
                direction=SetupDirection.LONG,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="只使用决策截止点及以前的完整 K 线。",
                timeframes=TimeframeProfile("1m", "5m", "15m"),
            ),
        )
    ).version


def _leave_episode_out_scores() -> tuple[LeaveEpisodeOutSimilarity, ...]:
    values = (40.0, 41.0, 45.0, 50.0, 55.0, 60.0, 65.0, 70.0, 80.0, 90.0)
    return tuple(
        LeaveEpisodeOutSimilarity(
            decision_event_id=f"positive_{index}",
            episode_id=f"positive_episode_{index}",
            reference_episode_ids=(
                f"reference_episode_{index}_a",
                f"reference_episode_{index}_b",
                f"reference_episode_{index}_c",
            ),
            similarity=value,
        )
        for index, value in enumerate(values)
    )


def _grouping(storage: StorageManager, sample_times: tuple[datetime, ...]):
    return MarketEpisodeService(storage).create_automatic_grouping(
        tuple(
            ResearchSampleWindow(
                sample_id=f"behavior_sample_{index:03d}",
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


def _store_blind_training_samples(
    storage: StorageManager,
    *,
    setup_version_id: str,
    grouping_version_id: str,
    sample_times: tuple[datetime, ...],
    start_index: int = 0,
) -> None:
    review = EntryBlindReviewService(storage)
    for index, cutoff in enumerate(sample_times, start=start_index):
        label = "ENTRY" if index % 2 == 0 else "REJECT"
        slope = 1.0 if label == "ENTRY" else -1.0
        _store_complete_history(storage, cutoff, slope=slope)
        receipt = review.enqueue_manual_position(
            manual_seed_id=f"behavior_sample_{index:03d}",
            setup_version_id=setup_version_id,
            grouping_version_id=grouping_version_id,
            symbol="BTCUSDT",
            direction="LONG",
            decision_time=cutoff,
        )
        inserted = storage.insert_entry_judgment(
            {
                "judgment_id": f"behavior_judgment_{index:03d}",
                "decision_event_id": receipt.decision_event_id,
                "version_number": 1,
                "phase": "BLIND",
                "label": label,
                "reason_tags": (),
                "confidence": 3,
                "note": "",
                "previous_judgment_id": None,
                "eligible_for_primary_research": True,
                "created_at": cutoff.isoformat(),
            }
        )
        assert inserted is True


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
                    "taker_buy_quote_volume": volume * close * (0.6 if slope > 0 else 0.4),
                    "source": "test_exchange",
                    "downloaded_at": cutoff.isoformat(),
                    "data_quality_status": "ok",
                }
            )
    storage.upsert_klines(rows)


def _typed_behavior_samples(count: int) -> tuple[EntryBehaviorSample, ...]:
    return tuple(
        EntryBehaviorSample(
            decision_event_id=f"typed_sample_{index:03d}",
            episode_id=f"typed_episode_{index:03d}",
            decision_cutoff_utc_ms=index * 60_000,
            label="ENTRY" if index % 2 == 0 else "REJECT",
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
                    ENTRY_BEHAVIOR_FEATURES
                )
            ),
        )
        for index in range(count)
    )
