from __future__ import annotations

from dataclasses import replace
import json
from time import perf_counter

import pytest

from app_config import APP_VERSION
from research.candidate_retrieval import (
    StructuralCandidateScanCancelled,
    StructuralPairEvaluation,
    StructuralReference,
    rank_structural_candidate,
)
from research.entry_behavior_model import EntryBehaviorTrainingRequest
from research.entry_behavior_training import fit_entry_behavior_model
from research.entry_outcome_comparison import (
    EntryOutcomeMetric,
    EntryOutcomePath,
    EntryOutcomeValue,
    MatchedEntryPair,
    build_entry_outcome_matrix,
)
from services.research_snapshots import ResearchSnapshotCancelled
from tests.research.test_entry_behavior_training import _typed_behavior_samples
from tests.research.test_research_snapshot import _valid_snapshot_service_and_input


SIX_MONTH_1M_BARS = 270_000
V16_FROZEN_BUDGET_SECONDS = {
    "candidate_scan": 5.0,
    "behavior_training": 30.0,
    "matched_outcomes": 15.0,
    "snapshot_report": 5.0,
    "cooperative_cancel": 1.0,
}


@pytest.mark.performance
def test_v16_decision_research_reference_budgets(tmp_path):
    timings: dict[str, float] = {}

    references = tuple(
        StructuralReference(
            identity=f"reference_{index:06d}",
            episode_identity=f"episode_{index:06d}",
            payload=index,
        )
        for index in range(SIX_MONTH_1M_BARS)
    )
    started = perf_counter()
    ranked = rank_structural_candidate(
        references,
        evaluate=lambda index: StructuralPairEvaluation(
            similarity=100.0 - (index % 1_000) / 1_000.0,
            diversity_vector=(float(index % 7), float(index % 11)),
        ),
    )
    timings["candidate_scan"] = perf_counter() - started
    assert ranked is not None
    assert len(ranked.references) == 3

    samples = _typed_behavior_samples(100)
    training_request = EntryBehaviorTrainingRequest(
        setup_version_id="setup_version_benchmark",
        grouping_version_id="grouping_version_benchmark",
        direction="LONG",
        seed=20260719,
    )
    started = perf_counter()
    training = fit_entry_behavior_model(
        samples,
        request=training_request,
        app_version=APP_VERSION,
        experiment_id="experiment_benchmark",
        model_version_id="model_benchmark",
        created_at="2026-07-19T00:00:00+00:00",
    )
    timings["behavior_training"] = perf_counter() - started
    assert training.model is not None

    pair_template = MatchedEntryPair(
        entry_decision_event_id="entry_0",
        reject_decision_event_id="reject_0",
        entry_episode_id="entry_episode_0",
        reject_episode_id="reject_episode_0",
        symbol="BTCUSDT",
        decision_timeframe="1m",
        similarity=90.0,
        context_distance=0.1,
        similarity_threshold=75.0,
    )
    pairs = tuple(
        replace(
            pair_template,
            entry_decision_event_id=f"entry_{index}",
            reject_decision_event_id=f"reject_{index}",
            entry_episode_id=f"entry_episode_{index % 10}",
            reject_episode_id=f"reject_episode_{index % 10}",
        )
        for index in range(30)
    )

    def outcome_path(value: float) -> EntryOutcomePath:
        return EntryOutcomePath(
            direction="LONG",
            execution_price=100.0,
            outcomes=tuple(
                EntryOutcomeValue(horizon, metric, value)
                for horizon in (1, 3, 5, 10, 20)
                for metric in EntryOutcomeMetric
            ),
        )

    outcomes = {
        **{
            f"entry_{index}": outcome_path(0.01 * (1 + index % 10))
            for index in range(30)
        },
        **{f"reject_{index}": outcome_path(0.0) for index in range(30)},
    }
    started = perf_counter()
    matrix = build_entry_outcome_matrix(
        pairs,
        outcomes,
        random_seed=20260719,
    )
    timings["matched_outcomes"] = perf_counter() - started
    assert len(matrix) == 15

    snapshot_service, snapshot_input, _storage = (
        _valid_snapshot_service_and_input(tmp_path / "publish")
    )
    started = perf_counter()
    publication = snapshot_service.publish(
        snapshot_input,
        created_at="2026-07-19T00:00:00+00:00",
    )
    timings["snapshot_report"] = perf_counter() - started
    assert (publication.directory / "research_report.md").exists()

    cancellation_checks = 0

    def cancel_candidate() -> bool:
        nonlocal cancellation_checks
        cancellation_checks += 1
        return cancellation_checks >= 1_000

    started = perf_counter()
    with pytest.raises(StructuralCandidateScanCancelled):
        rank_structural_candidate(
            references,
            evaluate=lambda index: StructuralPairEvaluation(
                similarity=90.0,
                diversity_vector=(float(index),),
            ),
            cancelled=cancel_candidate,
        )
    with pytest.raises(InterruptedError):
        fit_entry_behavior_model(
            samples,
            request=training_request,
            app_version=APP_VERSION,
            experiment_id="experiment_cancelled",
            model_version_id="model_cancelled",
            created_at="2026-07-19T00:00:00+00:00",
            cancelled=lambda: True,
        )
    cancelled_service, cancelled_input, _cancelled_storage = (
        _valid_snapshot_service_and_input(tmp_path / "cancel")
    )
    with pytest.raises(ResearchSnapshotCancelled):
        cancelled_service.publish(
            cancelled_input,
            created_at="2026-07-19T00:00:00+00:00",
            cancelled=lambda: True,
        )
    timings["cooperative_cancel"] = perf_counter() - started

    print(json.dumps(timings, sort_keys=True), flush=True)
    for task, seconds in timings.items():
        assert seconds < V16_FROZEN_BUDGET_SECONDS[task], (
            task,
            seconds,
            V16_FROZEN_BUDGET_SECONDS[task],
        )
