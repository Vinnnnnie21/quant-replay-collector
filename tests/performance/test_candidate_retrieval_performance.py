from __future__ import annotations

import pytest

from research.candidate_retrieval import (
    StructuralPairEvaluation,
    StructuralReference,
    rank_structural_candidate,
)


def test_shared_candidate_ranking_rejects_non_finite_pair_results():
    references = tuple(
        StructuralReference(
            identity=f"reference_{index}",
            episode_identity=f"episode_{index}",
            payload=index,
        )
        for index in range(3)
    )

    ranked = rank_structural_candidate(
        references,
        evaluate=lambda index: StructuralPairEvaluation(
            similarity=float("nan") if index == 0 else 80.0 + index,
            diversity_vector=(0.1, 0.2),
        ),
    )

    assert ranked is None


@pytest.mark.performance
def test_shared_candidate_ranking_scans_references_once_without_pairwise_expansion():
    reference_count = 50_000
    evaluations = 0
    references = tuple(
        StructuralReference(
            identity=f"reference_{index:05d}",
            episode_identity=f"episode_{index:05d}",
            payload=index,
        )
        for index in range(reference_count)
    )

    def evaluate(index: int) -> StructuralPairEvaluation:
        nonlocal evaluations
        evaluations += 1
        return StructuralPairEvaluation(
            similarity=100.0 - (index % 100) / 100.0,
            diversity_vector=(float(index % 7), float(index % 11)),
        )

    ranked = rank_structural_candidate(references, evaluate=evaluate)

    assert ranked is not None
    assert evaluations == reference_count
    assert len(ranked.references) == 3
