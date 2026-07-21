from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .candidate_retrieval import (
    StructuralCandidateScanCancelled,
    select_structural_candidate_batch,
)

from .entry_blind_review import BlindReviewBatch


MIN_COMPLETE_ENTRY_REFERENCES = 10
MIN_ENTRY_REFERENCE_EPISODES = 5
REQUIRED_NEAREST_EPISODES = 3
MAX_FORMAL_BATCH_SIZE = 20


class CandidateScanStatus(StrEnum):
    NOT_READY = "NOT_READY"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class CandidateScanRequest:
    setup_version_id: str
    grouping_version_id: str
    direction: str
    candidate_limit: int = 5_000

    def __post_init__(self) -> None:
        for name in ("setup_version_id", "grouping_version_id"):
            value = str(getattr(self, name) or "").strip()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)
        direction = str(self.direction or "").upper()
        if direction not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT")
        object.__setattr__(self, "direction", direction)
        limit = int(self.candidate_limit)
        if limit < 1 or limit > 10_000:
            raise ValueError("candidate_limit must be between 1 and 10000")
        object.__setattr__(self, "candidate_limit", limit)


@dataclass(frozen=True, slots=True)
class CandidateMaturity:
    complete_entry_count: int
    entry_episode_count: int
    required_entry_count: int = MIN_COMPLETE_ENTRY_REFERENCES
    required_episode_count: int = MIN_ENTRY_REFERENCE_EPISODES

    @property
    def ready(self) -> bool:
        return (
            self.complete_entry_count >= self.required_entry_count
            and self.entry_episode_count >= self.required_episode_count
        )

    @property
    def missing_entry_count(self) -> int:
        return max(0, self.required_entry_count - self.complete_entry_count)

    @property
    def missing_episode_count(self) -> int:
        return max(0, self.required_episode_count - self.entry_episode_count)


@dataclass(frozen=True, slots=True)
class CandidateReference:
    decision_event_id: str
    episode_id: str
    similarity: float


@dataclass(frozen=True, slots=True)
class EntryCandidateScore:
    source_sample_id: str
    episode_id: str
    similarity: float
    references: tuple[CandidateReference, ...]
    completeness_ratio: float
    diversity_vector: tuple[float, ...]
    enqueue_reason: str = "STRUCTURAL_SIMILARITY"


@dataclass(frozen=True, slots=True)
class CandidateScanResult:
    scan_id: str
    setup_version_id: str
    grouping_version_id: str
    direction: str
    formula_version: str
    feature_version: str
    status: CandidateScanStatus
    maturity: CandidateMaturity
    candidate_universe_count: int
    unavailable_candidate_count: int
    candidates: tuple[EntryCandidateScore, ...]


@dataclass(frozen=True, slots=True)
class CandidateSimilarityDistribution:
    score_80_to_100: int
    score_60_to_under_80: int
    score_0_to_under_60: int


def candidate_similarity_distribution(
    candidates: tuple[EntryCandidateScore, ...],
) -> CandidateSimilarityDistribution:
    return CandidateSimilarityDistribution(
        score_80_to_100=sum(item.similarity >= 80.0 for item in candidates),
        score_60_to_under_80=sum(
            60.0 <= item.similarity < 80.0 for item in candidates
        ),
        score_0_to_under_60=sum(item.similarity < 60.0 for item in candidates),
    )


@dataclass(frozen=True, slots=True)
class CandidateScanOverview:
    """UI-safe aggregate that never contains per-candidate scores or sources."""

    scan_id: str
    setup_version_id: str
    grouping_version_id: str
    direction: str
    status: CandidateScanStatus
    maturity: CandidateMaturity
    candidate_universe_count: int
    usable_candidate_count: int
    unavailable_candidate_count: int
    episode_coverage_count: int
    similarity_distribution: CandidateSimilarityDistribution


def candidate_scan_overview(result: CandidateScanResult) -> CandidateScanOverview:
    return CandidateScanOverview(
        scan_id=result.scan_id,
        setup_version_id=result.setup_version_id,
        grouping_version_id=result.grouping_version_id,
        direction=result.direction,
        status=result.status,
        maturity=result.maturity,
        candidate_universe_count=result.candidate_universe_count,
        usable_candidate_count=len(result.candidates),
        unavailable_candidate_count=result.unavailable_candidate_count,
        episode_coverage_count=len(
            {candidate.episode_id for candidate in result.candidates}
        ),
        similarity_distribution=candidate_similarity_distribution(
            result.candidates
        ),
    )


class CandidateScanCancelled(StructuralCandidateScanCancelled):
    """Candidate scanning stopped cooperatively before publishing a result."""


@dataclass(frozen=True, slots=True)
class FormalCandidateBatch:
    batch: BlindReviewBatch
    high_similarity_count: int
    diverse_count: int


@dataclass(frozen=True, slots=True)
class FormalCandidateSelection:
    candidate: EntryCandidateScore
    selection_reason: str


def select_formal_candidate_batch(
    candidates: tuple[EntryCandidateScore, ...],
    *,
    limit: int = MAX_FORMAL_BATCH_SIZE,
) -> tuple[FormalCandidateSelection, ...]:
    selections = select_structural_candidate_batch(
        candidates,
        identity=lambda item: item.source_sample_id,
        episode_identity=lambda item: item.episode_id,
        similarity=lambda item: item.similarity,
        completeness=lambda item: item.completeness_ratio,
        reference_count=lambda item: len(item.references),
        diversity_vector=lambda item: item.diversity_vector,
        limit=limit,
        maximum_size=MAX_FORMAL_BATCH_SIZE,
        required_reference_count=REQUIRED_NEAREST_EPISODES,
    )
    return tuple(
        FormalCandidateSelection(item.candidate, item.selection_reason)
        for item in selections
    )


__all__ = [
    "CandidateMaturity",
    "CandidateReference",
    "CandidateScanCancelled",
    "CandidateScanRequest",
    "CandidateScanResult",
    "CandidateScanOverview",
    "CandidateSimilarityDistribution",
    "CandidateScanStatus",
    "EntryCandidateScore",
    "FormalCandidateBatch",
    "FormalCandidateSelection",
    "MAX_FORMAL_BATCH_SIZE",
    "MIN_COMPLETE_ENTRY_REFERENCES",
    "MIN_ENTRY_REFERENCE_EPISODES",
    "REQUIRED_NEAREST_EPISODES",
    "select_formal_candidate_batch",
    "candidate_scan_overview",
    "candidate_similarity_distribution",
]
