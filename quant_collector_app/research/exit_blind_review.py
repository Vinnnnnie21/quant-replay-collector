from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

try:
    from research.entry_blind_review import (
        BlindBatchItem,
        BlindReviewBatch,
        BlindedTimeframeChart,
        ReviewPhase,
        ReviewStatus,
        RevealedCandidateAudit,
        RevealedCandidateReference,
    )
except ImportError:  # pragma: no cover - package import path
    from .entry_blind_review import (
        BlindBatchItem,
        BlindReviewBatch,
        BlindedTimeframeChart,
        ReviewPhase,
        ReviewStatus,
        RevealedCandidateAudit,
        RevealedCandidateReference,
    )


class ExitSeedSource(StrEnum):
    ACTUAL_CLOSE = "ACTUAL_CLOSE"
    MANUAL_POSITION = "MANUAL_POSITION"


class OriginalExitAction(StrEnum):
    FULL_CLOSE = "FULL_CLOSE"
    NONE = "NONE"


class ExitJudgmentLabel(StrEnum):
    EXIT_NOW = "EXIT_NOW"
    HOLD = "HOLD"
    UNCERTAIN = "UNCERTAIN"


class ExitReviewLabelState(StrEnum):
    UNLABELED = "UNLABELED"
    EXIT_NOW = "EXIT_NOW"
    HOLD = "HOLD"
    UNCERTAIN = "UNCERTAIN"


EXIT_REASONS_BY_LABEL = {
    ExitJudgmentLabel.EXIT_NOW: (
        "giveback",
        "trend_failure",
        "target_reached",
        "risk_limit",
        "time_limit",
        "manual_review",
        "other",
    ),
    ExitJudgmentLabel.HOLD: (
        "trend_intact",
        "room_remaining",
        "risk_acceptable",
        "manual_review",
        "other",
    ),
    ExitJudgmentLabel.UNCERTAIN: (
        "data_quality_warning",
        "manual_review",
        "other",
    ),
}


class OptionalRiskLevelStatus(StrEnum):
    SET = "SET"
    NOT_SET = "NOT_SET"
    MISSING = "MISSING"


EXIT_REASON_TAGS = frozenset(
    reason
    for reasons in EXIT_REASONS_BY_LABEL.values()
    for reason in reasons
)


@dataclass(frozen=True, slots=True)
class ExitBlindJudgmentInput:
    label: ExitJudgmentLabel | str
    reason_tags: tuple[str, ...]
    confidence: int
    note: str = ""

    def __post_init__(self) -> None:
        try:
            label = (
                self.label
                if isinstance(self.label, ExitJudgmentLabel)
                else ExitJudgmentLabel(str(self.label).upper())
            )
        except ValueError as exc:
            raise ValueError(f"Unsupported exit judgment: {self.label}") from exc
        if isinstance(self.confidence, bool):
            raise ValueError("confidence must be between 1 and 5")
        confidence = int(self.confidence)
        if confidence < 1 or confidence > 5:
            raise ValueError("confidence must be between 1 and 5")
        reasons = tuple(str(reason).strip().lower() for reason in self.reason_tags)
        if not reasons:
            raise ValueError("reason_tags must contain at least one reason")
        allowed_reasons = frozenset(EXIT_REASONS_BY_LABEL[label])
        invalid = tuple(reason for reason in reasons if reason not in allowed_reasons)
        if invalid:
            raise ValueError(f"Unsupported reason_tags: {list(invalid)}")
        if not isinstance(self.note, str):
            raise ValueError("note must be a string")
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "reason_tags", reasons)


@dataclass(frozen=True, slots=True)
class ExitSeedReceipt:
    decision_event_id: str
    status: ReviewStatus


@dataclass(frozen=True, slots=True)
class ExitPositionSnapshot:
    anonymous_position_id: str
    actual_entry_price: float | None
    entry_atr20: float | None
    entry_bar_index: int | None
    decision_bar_index: int | None
    take_profit_status: OptionalRiskLevelStatus
    take_profit_price: float | None
    stop_loss_status: OptionalRiskLevelStatus
    stop_loss_price: float | None


@dataclass(frozen=True, slots=True)
class AccountPressureSnapshot:
    equity_before_decision: float | None
    position_notional_quote: float | None
    position_equity_ratio: float | None
    total_open_notional_quote: float | None
    total_exposure_ratio: float | None
    open_position_count: int
    account_drawdown_pct: float | None
    leverage: float | None = None
    margin_quote: float | None = None
    liquidation_price: float | None = None


@dataclass(frozen=True, slots=True)
class ExitJudgmentVersion:
    judgment_id: str
    decision_event_id: str
    version_number: int
    phase: ReviewPhase
    label: ExitJudgmentLabel
    reason_tags: tuple[str, ...]
    confidence: int
    note: str
    previous_judgment_id: str | None
    eligible_for_primary_research: bool
    created_at: str


@dataclass(frozen=True, slots=True)
class BlindedExitReviewItem:
    blind_item_id: str
    setup_version_id: str
    symbol: str
    direction: str
    decision_cutoff_utc_ms: int
    charts: tuple[BlindedTimeframeChart, ...]
    position: ExitPositionSnapshot
    account_pressure: AccountPressureSnapshot
    setup_link_status: str
    eligible_for_formal_research: bool
    status: ReviewStatus
    judgment: ExitJudgmentVersion | None

    @property
    def label_state(self) -> ExitReviewLabelState:
        if self.judgment is None:
            return ExitReviewLabelState.UNLABELED
        return ExitReviewLabelState(self.judgment.label.value)


@dataclass(frozen=True, slots=True)
class RevealedOriginalExitAction:
    seed_source: ExitSeedSource
    original_action: OriginalExitAction
    source_event_id: str | None
    action_time_utc_ms: int | None
    timing_approximate: bool
    realized_pnl_quote: float | None


@dataclass(frozen=True, slots=True)
class RevealedExitReviewItem:
    blind_item_id: str
    decision_event_id: str
    status: ReviewStatus
    original: RevealedOriginalExitAction
    blind_judgment: ExitJudgmentVersion
    future_charts: tuple[BlindedTimeframeChart, ...]
    revealed_at: str
    candidate_audit: RevealedCandidateAudit | None = None
    account_pressure: AccountPressureSnapshot | None = None


__all__ = [
    "AccountPressureSnapshot",
    "BlindBatchItem",
    "BlindReviewBatch",
    "BlindedExitReviewItem",
    "EXIT_REASON_TAGS",
    "EXIT_REASONS_BY_LABEL",
    "ExitBlindJudgmentInput",
    "ExitJudgmentLabel",
    "ExitJudgmentVersion",
    "ExitPositionSnapshot",
    "ExitReviewLabelState",
    "ExitSeedReceipt",
    "ExitSeedSource",
    "OptionalRiskLevelStatus",
    "OriginalExitAction",
    "RevealedExitReviewItem",
    "RevealedCandidateAudit",
    "RevealedCandidateReference",
    "RevealedOriginalExitAction",
]
