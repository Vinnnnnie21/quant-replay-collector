from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .candidate_retrieval import StructuralCandidateScanCancelled
from .entry_blind_review import BlindReviewBatch


MIN_COMPLETE_EXIT_NOW_REFERENCES = 10
MIN_HOLDING_REFERENCE_EPISODES = 5
REQUIRED_NEAREST_HOLDING_EPISODES = 3
MAX_FORMAL_EXIT_BATCH_SIZE = 20


class ExitCandidateScanStatus(StrEnum):
    NOT_READY = "NOT_READY"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class ExitCandidateScanRequest:
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
class ExitCandidateMaturity:
    complete_exit_now_count: int
    holding_episode_count: int
    required_exit_now_count: int = MIN_COMPLETE_EXIT_NOW_REFERENCES
    required_holding_episode_count: int = MIN_HOLDING_REFERENCE_EPISODES

    @property
    def ready(self) -> bool:
        return (
            self.complete_exit_now_count >= self.required_exit_now_count
            and self.holding_episode_count
            >= self.required_holding_episode_count
        )

    @property
    def missing_exit_now_count(self) -> int:
        return max(0, self.required_exit_now_count - self.complete_exit_now_count)

    @property
    def missing_holding_episode_count(self) -> int:
        return max(
            0,
            self.required_holding_episode_count - self.holding_episode_count,
        )


@dataclass(frozen=True, slots=True)
class ExitCandidateReference:
    decision_event_id: str
    holding_episode_id: str
    similarity: float


@dataclass(frozen=True, slots=True)
class ExitCandidateScore:
    decision_event_id: str
    holding_episode_id: str
    similarity: float
    references: tuple[ExitCandidateReference, ...]
    completeness_ratio: float
    diversity_vector: tuple[float, ...]
    enqueue_reason: str = "STRUCTURAL_SIMILARITY"


@dataclass(frozen=True, slots=True)
class ExitCandidateScanResult:
    scan_id: str
    setup_version_id: str
    grouping_version_id: str
    direction: str
    formula_version: str
    feature_version: str
    status: ExitCandidateScanStatus
    maturity: ExitCandidateMaturity
    candidate_universe_count: int
    unavailable_candidate_count: int
    candidates: tuple[ExitCandidateScore, ...]


class ExitCandidateScanCancelled(StructuralCandidateScanCancelled):
    """Exit candidate scan stopped cooperatively at a safe boundary."""


@dataclass(frozen=True, slots=True)
class FormalExitCandidateBatch:
    batch: BlindReviewBatch
    high_similarity_count: int
    diverse_count: int


@dataclass(frozen=True, slots=True)
class ExitCandidateSimilarityDistribution:
    score_80_to_100: int
    score_60_to_under_80: int
    score_0_to_under_60: int


@dataclass(frozen=True, slots=True)
class ExitCandidateScanOverview:
    scan_id: str
    setup_version_id: str
    grouping_version_id: str
    direction: str
    status: ExitCandidateScanStatus
    maturity: ExitCandidateMaturity
    candidate_universe_count: int
    usable_candidate_count: int
    unavailable_candidate_count: int
    episode_coverage_count: int
    similarity_distribution: ExitCandidateSimilarityDistribution


def exit_candidate_scan_overview(
    result: ExitCandidateScanResult,
) -> ExitCandidateScanOverview:
    candidates = result.candidates
    return ExitCandidateScanOverview(
        scan_id=result.scan_id,
        setup_version_id=result.setup_version_id,
        grouping_version_id=result.grouping_version_id,
        direction=result.direction,
        status=result.status,
        maturity=result.maturity,
        candidate_universe_count=result.candidate_universe_count,
        usable_candidate_count=len(candidates),
        unavailable_candidate_count=result.unavailable_candidate_count,
        episode_coverage_count=len(
            {candidate.holding_episode_id for candidate in candidates}
        ),
        similarity_distribution=ExitCandidateSimilarityDistribution(
            score_80_to_100=sum(item.similarity >= 80.0 for item in candidates),
            score_60_to_under_80=sum(
                60.0 <= item.similarity < 80.0 for item in candidates
            ),
            score_0_to_under_60=sum(item.similarity < 60.0 for item in candidates),
        ),
    )


__all__ = [
    "ExitCandidateMaturity",
    "ExitCandidateReference",
    "ExitCandidateScanCancelled",
    "ExitCandidateScanRequest",
    "ExitCandidateScanResult",
    "ExitCandidateScanStatus",
    "ExitCandidateScore",
    "FormalExitCandidateBatch",
    "ExitCandidateScanOverview",
    "ExitCandidateSimilarityDistribution",
    "MAX_FORMAL_EXIT_BATCH_SIZE",
    "MIN_COMPLETE_EXIT_NOW_REFERENCES",
    "MIN_HOLDING_REFERENCE_EPISODES",
    "REQUIRED_NEAREST_HOLDING_EPISODES",
    "exit_candidate_scan_overview",
]
