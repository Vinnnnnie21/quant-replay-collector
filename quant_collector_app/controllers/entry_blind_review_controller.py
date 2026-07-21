from __future__ import annotations

from typing import Any

try:
    from research.entry_blind_review import (
        BlindJudgmentInput,
        BlindReviewBatch,
        BlindedEntryReviewItem,
        ENTRY_REASONS_BY_LABEL,
        EntryJudgmentVersion,
        RevealedEntryReviewItem,
        RevealedCandidateAudit,
    )
except ImportError:  # pragma: no cover - package import path
    from ..research.entry_blind_review import (
        BlindJudgmentInput,
        BlindReviewBatch,
        BlindedEntryReviewItem,
        ENTRY_REASONS_BY_LABEL,
        EntryJudgmentVersion,
        RevealedEntryReviewItem,
        RevealedCandidateAudit,
    )


class EntryBlindReviewController:
    """Stateful UI controller over the blinded entry-review use cases."""

    review_kind = "entry"
    judgment_labels = ("ENTRY", "REJECT", "UNCERTAIN")
    reason_tags_by_label = {
        label.value: reasons
        for label, reasons in ENTRY_REASONS_BY_LABEL.items()
    }

    def __init__(self, service: Any) -> None:
        self._service = service
        self.batch: BlindReviewBatch | None = None
        self.current_index = 0

    def load_batch(
        self,
        *,
        setup_version_id: str,
        grouping_version_id: str,
    ) -> BlindReviewBatch:
        self.batch = self._service.create_batch(
            setup_version_id=setup_version_id,
            grouping_version_id=grouping_version_id,
        )
        self.current_index = 0
        return self.batch

    def load_existing_batch(self, batch: BlindReviewBatch) -> BlindReviewBatch:
        if not isinstance(batch, BlindReviewBatch):
            raise TypeError("batch must be BlindReviewBatch")
        self.batch = batch
        self.current_index = 0
        return batch

    def select_item(self, index: int) -> BlindedEntryReviewItem:
        if self.batch is None or not self.batch.items:
            raise ValueError("No blind-review batch is loaded")
        selected = int(index)
        if selected < 0 or selected >= len(self.batch.items):
            raise IndexError("blind-review item index is out of range")
        self.current_index = selected
        return self.current_item()

    def current_item(self) -> BlindedEntryReviewItem:
        if self.batch is None or not self.batch.items:
            raise ValueError("No blind-review item is available")
        item = self.batch.items[self.current_index]
        return self._service.get_blinded_item(
            batch_id=self.batch.batch_id,
            blind_item_id=item.blind_item_id,
        )

    def save_blind_judgment(
        self,
        judgment: BlindJudgmentInput,
    ) -> EntryJudgmentVersion:
        if self.batch is None or not self.batch.items:
            raise ValueError("No blind-review item is available")
        item = self.batch.items[self.current_index]
        return self._service.save_blind_judgment(
            batch_id=self.batch.batch_id,
            blind_item_id=item.blind_item_id,
            judgment=judgment,
        )

    def make_judgment(
        self,
        *,
        label: str,
        reason_tags: tuple[str, ...],
        confidence: int,
        note: str,
    ) -> BlindJudgmentInput:
        return BlindJudgmentInput(
            label=label,
            reason_tags=reason_tags,
            confidence=confidence,
            note=note,
        )

    def reveal_current(self) -> RevealedEntryReviewItem:
        if self.batch is None or not self.batch.items:
            raise ValueError("No blind-review item is available")
        item = self.batch.items[self.current_index]
        return self._service.reveal(
            batch_id=self.batch.batch_id,
            blind_item_id=item.blind_item_id,
        )

    def candidate_audit_current(self) -> RevealedCandidateAudit | None:
        current = self.current_item()
        return self._service.get_candidate_audit_after_judgment(
            current.decision_event_id
        )

    def relabel_current(
        self,
        judgment: BlindJudgmentInput,
    ) -> EntryJudgmentVersion:
        current = self.current_item()
        return self._service.relabel_after_reveal(
            decision_event_id=current.decision_event_id,
            judgment=judgment,
        )


__all__ = ["EntryBlindReviewController"]
