from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

try:
    from research.entry_annotations import ALLOWED_REASON_TAGS
except ImportError:  # pragma: no cover - package import path
    from .entry_annotations import ALLOWED_REASON_TAGS


class EntrySeedSource(StrEnum):
    ACTUAL_OPEN = "ACTUAL_OPEN"
    MANUAL_POSITION = "MANUAL_POSITION"
    SIMILAR_CANDIDATE = "SIMILAR_CANDIDATE"


class OriginalEntryAction(StrEnum):
    OPEN_LONG = "OPEN_LONG"
    OPEN_SHORT = "OPEN_SHORT"
    NONE = "NONE"


class EntryJudgmentLabel(StrEnum):
    ENTRY = "ENTRY"
    REJECT = "REJECT"
    UNCERTAIN = "UNCERTAIN"


ENTRY_REASONS_BY_LABEL = {
    EntryJudgmentLabel.ENTRY: (
        "long_lower_shadow",
        "volume_spike",
        "bullish_confirmation",
        "trend_context",
        "manual_review",
        "other",
    ),
    EntryJudgmentLabel.REJECT: (
        "insufficient_confirmation",
        "weak_volume",
        "no_confirmation",
        "choppy_context",
        "too_late",
        "risk_too_wide",
        "mixed_setup",
        "other",
    ),
    EntryJudgmentLabel.UNCERTAIN: (
        "mixed_setup",
        "data_quality_warning",
        "manual_review",
        "other",
    ),
}


class ReviewPhase(StrEnum):
    BLIND = "BLIND"
    POST_OUTCOME = "POST_OUTCOME"


class ReviewStatus(StrEnum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    JUDGED_BLIND = "JUDGED_BLIND"
    REVEALED = "REVEALED"


@dataclass(frozen=True, slots=True)
class BlindJudgmentInput:
    label: EntryJudgmentLabel | str
    reason_tags: tuple[str, ...]
    confidence: int
    note: str = ""

    def __post_init__(self) -> None:
        try:
            label = (
                self.label
                if isinstance(self.label, EntryJudgmentLabel)
                else EntryJudgmentLabel(str(self.label).upper())
            )
        except ValueError as exc:
            raise ValueError(f"Unsupported entry judgment: {self.label}") from exc
        if isinstance(self.confidence, bool):
            raise ValueError("confidence must be between 1 and 5")
        confidence = int(self.confidence)
        if confidence < 1 or confidence > 5:
            raise ValueError("confidence must be between 1 and 5")
        reasons = tuple(str(reason).strip().lower() for reason in self.reason_tags)
        invalid = tuple(reason for reason in reasons if reason not in ALLOWED_REASON_TAGS)
        if invalid:
            raise ValueError(f"Unsupported reason_tags: {list(invalid)}")
        if not isinstance(self.note, str):
            raise ValueError("note must be a string")
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "reason_tags", reasons)


@dataclass(frozen=True, slots=True)
class EntrySeedReceipt:
    decision_event_id: str
    status: ReviewStatus


@dataclass(frozen=True, slots=True)
class BlindBatchItem:
    blind_item_id: str
    status: ReviewStatus


@dataclass(frozen=True, slots=True)
class BlindReviewBatch:
    batch_id: str
    setup_version_id: str
    grouping_version_id: str
    items: tuple[BlindBatchItem, ...]


@dataclass(frozen=True, slots=True)
class BlindedKline:
    open_time_utc_ms: int
    close_time_utc_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class BlindedTimeframeChart:
    interval: str
    cutoff_time_utc_ms: int
    bars: tuple[BlindedKline, ...]


@dataclass(frozen=True, slots=True)
class EntryJudgmentVersion:
    judgment_id: str
    decision_event_id: str
    version_number: int
    phase: ReviewPhase
    label: EntryJudgmentLabel
    reason_tags: tuple[str, ...]
    confidence: int
    note: str
    previous_judgment_id: str | None
    eligible_for_primary_research: bool
    created_at: str


@dataclass(frozen=True, slots=True)
class BlindedEntryReviewItem:
    blind_item_id: str
    decision_event_id: str
    setup_version_id: str
    symbol: str
    direction: str
    decision_cutoff_utc_ms: int
    charts: tuple[BlindedTimeframeChart, ...]
    status: ReviewStatus
    judgment: EntryJudgmentVersion | None


@dataclass(frozen=True, slots=True)
class RevealedOriginalEntryAction:
    seed_source: EntrySeedSource
    original_action: OriginalEntryAction
    source_event_id: str | None
    action_time_utc_ms: int | None
    timing_approximate: bool


@dataclass(frozen=True, slots=True)
class RevealedCandidateReference:
    decision_event_id: str
    episode_id: str
    similarity: float


@dataclass(frozen=True, slots=True)
class RevealedCandidateAudit:
    similarity: float
    group_distances: tuple[float, ...]
    references: tuple[RevealedCandidateReference, ...]
    enqueue_reason: str
    selection_reason: str
    research_target: str = "ENTRY"
    position_distance: float | None = None


@dataclass(frozen=True, slots=True)
class RevealedEntryReviewItem:
    blind_item_id: str
    decision_event_id: str
    status: ReviewStatus
    original: RevealedOriginalEntryAction
    blind_judgment: EntryJudgmentVersion
    future_charts: tuple[BlindedTimeframeChart, ...]
    revealed_at: str
    candidate_audit: RevealedCandidateAudit | None = None


__all__ = [
    "ENTRY_REASONS_BY_LABEL",
    "BlindBatchItem",
    "BlindJudgmentInput",
    "BlindReviewBatch",
    "BlindedEntryReviewItem",
    "BlindedKline",
    "BlindedTimeframeChart",
    "EntryJudgmentLabel",
    "EntryJudgmentVersion",
    "EntrySeedReceipt",
    "EntrySeedSource",
    "OriginalEntryAction",
    "RevealedEntryReviewItem",
    "RevealedCandidateAudit",
    "RevealedCandidateReference",
    "RevealedOriginalEntryAction",
    "ReviewPhase",
    "ReviewStatus",
]
