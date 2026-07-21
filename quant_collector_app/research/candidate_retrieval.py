from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Callable, Generic, Sequence, TypeVar


T = TypeVar("T")
P = TypeVar("P")


class StructuralCandidateScanCancelled(RuntimeError):
    """Shared cooperative-cancellation boundary for candidate retrieval."""


@dataclass(frozen=True, slots=True)
class StructuralReference(Generic[P]):
    identity: str
    episode_identity: str
    payload: P


@dataclass(frozen=True, slots=True)
class StructuralPairEvaluation:
    similarity: float
    diversity_vector: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class RankedStructuralReference:
    identity: str
    episode_identity: str
    similarity: float


@dataclass(frozen=True, slots=True)
class StructuralRetrievalScore:
    similarity: float
    references: tuple[RankedStructuralReference, ...]
    diversity_vector: tuple[float, ...]


def rank_structural_candidate(
    references: Sequence[StructuralReference[P]],
    *,
    evaluate: Callable[[P], StructuralPairEvaluation | None],
    cancelled: Callable[[], bool] | None = None,
    cancellation_error: Callable[[], Exception] = StructuralCandidateScanCancelled,
    required_reference_count: int = 3,
) -> StructuralRetrievalScore | None:
    """Rank one candidate without allowing one evidence unit to dominate."""

    nearest_by_episode = {}
    for reference in references:
        if cancelled is not None and cancelled():
            raise cancellation_error()
        pair = evaluate(reference.payload)
        if pair is None:
            continue
        similarity = float(pair.similarity)
        vector = tuple(float(value) for value in pair.diversity_vector)
        if (
            not math.isfinite(similarity)
            or not 0.0 <= similarity <= 100.0
            or not vector
            or any(not math.isfinite(value) for value in vector)
        ):
            continue
        proposed = (
            similarity,
            reference.identity,
            vector,
        )
        previous = nearest_by_episode.get(reference.episode_identity)
        if previous is None or (-proposed[0], proposed[1]) < (
            -previous[0],
            previous[1],
        ):
            nearest_by_episode[reference.episode_identity] = proposed
    nearest = sorted(
        (
            (score, identity, episode_identity, vector)
            for episode_identity, (score, identity, vector)
            in nearest_by_episode.items()
        ),
        key=lambda item: (-item[0], item[1], item[2]),
    )[:required_reference_count]
    if len(nearest) < required_reference_count:
        return None
    ranked = tuple(
        RankedStructuralReference(identity, episode_identity, score)
        for score, identity, episode_identity, _vector in nearest
    )
    return StructuralRetrievalScore(
        similarity=math.fsum(item.similarity for item in ranked) / len(ranked),
        references=ranked,
        diversity_vector=_average_vectors(nearest),
    )


@dataclass(frozen=True, slots=True)
class StructuralCandidateSelection(Generic[T]):
    candidate: T
    selection_reason: str


def select_structural_candidate_batch(
    candidates: Sequence[T],
    *,
    identity: Callable[[T], str],
    episode_identity: Callable[[T], str],
    similarity: Callable[[T], float],
    completeness: Callable[[T], float],
    reference_count: Callable[[T], int],
    diversity_vector: Callable[[T], tuple[float, ...]],
    limit: int,
    maximum_size: int = 20,
    required_reference_count: int = 3,
) -> tuple[StructuralCandidateSelection[T], ...]:
    """Select a deterministic 70/30 batch with one item per evidence unit."""

    size = int(limit)
    if size < 1 or size > maximum_size:
        raise ValueError(
            f"formal candidate batch limit must be between 1 and {maximum_size}"
        )
    eligible = tuple(
        item
        for item in candidates
        if completeness(item) >= 1.0
        and reference_count(item) == required_reference_count
        and math.isfinite(similarity(item))
    )
    ordered = sorted(
        eligible,
        key=lambda item: (-similarity(item), identity(item)),
    )
    episode_best = []
    seen_episodes = set()
    for item in ordered:
        episode_id = episode_identity(item)
        if episode_id in seen_episodes:
            continue
        episode_best.append(item)
        seen_episodes.add(episode_id)
    target = min(size, len(episode_best))
    high_target = max(1, math.floor(target * 0.70 + 0.5)) if target else 0
    high = episode_best[:high_target]
    remaining = episode_best[high_target:]
    diverse = []
    while remaining and len(high) + len(diverse) < target:
        anchors = (*high, *diverse)
        choice = min(
            remaining,
            key=lambda item: (
                -_minimum_vector_distance(
                    diversity_vector(item),
                    tuple(diversity_vector(anchor) for anchor in anchors),
                ),
                -similarity(item),
                identity(item),
            ),
        )
        diverse.append(choice)
        remaining.remove(choice)
    selections = tuple(
        StructuralCandidateSelection(item, "HIGH_SIMILARITY") for item in high
    ) + tuple(
        StructuralCandidateSelection(item, "STRUCTURAL_DIVERSITY")
        for item in diverse
    )
    return tuple(
        sorted(
            selections,
            key=lambda item: hashlib.sha256(
                f"blind-display-v1|{identity(item.candidate)}".encode("utf-8")
            ).digest(),
        )
    )


def _minimum_vector_distance(
    candidate: tuple[float, ...],
    anchors: tuple[tuple[float, ...], ...],
) -> float:
    if not anchors:
        return math.inf
    distances = []
    for anchor in anchors:
        if len(candidate) != len(anchor):
            continue
        distances.append(
            math.sqrt(
                math.fsum(
                    (left - right) ** 2
                    for left, right in zip(candidate, anchor, strict=True)
                )
            )
        )
    return min(distances) if distances else 0.0


def _average_vectors(
    nearest: Sequence[tuple[float, str, str, tuple[float, ...]]],
) -> tuple[float, ...]:
    vectors = tuple(item[3] for item in nearest)
    lengths = {len(vector) for vector in vectors}
    if len(lengths) != 1:
        raise RuntimeError("candidate reference vectors are inconsistent")
    return tuple(
        math.fsum(vector[index] for vector in vectors) / len(vectors)
        for index in range(len(vectors[0]))
    )


__all__ = [
    "StructuralCandidateSelection",
    "StructuralCandidateScanCancelled",
    "RankedStructuralReference",
    "StructuralPairEvaluation",
    "StructuralReference",
    "StructuralRetrievalScore",
    "select_structural_candidate_batch",
    "rank_structural_candidate",
]
