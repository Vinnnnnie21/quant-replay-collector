from __future__ import annotations

from typing import Any

try:
    from research.entry_blind_review import (
        BlindBatchItem,
        BlindReviewBatch,
        RevealedCandidateAudit,
    )
    from research.exit_blind_review import (
        BlindedExitReviewItem,
        EXIT_REASONS_BY_LABEL,
        ExitBlindJudgmentInput,
        ExitJudgmentLabel,
        ExitJudgmentVersion,
        RevealedExitReviewItem,
    )
except ImportError:  # pragma: no cover - package import path
    from ..research.entry_blind_review import (
        BlindBatchItem,
        BlindReviewBatch,
        RevealedCandidateAudit,
    )
    from ..research.exit_blind_review import (
        BlindedExitReviewItem,
        EXIT_REASONS_BY_LABEL,
        ExitBlindJudgmentInput,
        ExitJudgmentLabel,
        ExitJudgmentVersion,
        RevealedExitReviewItem,
    )


class ExitBlindReviewController:
    """Stateful Qt-facing controller for full-position exit review."""

    review_kind = "exit"
    judgment_labels = tuple(label.value for label in ExitJudgmentLabel)
    reason_tags_by_label = {
        label.value: reasons
        for label, reasons in EXIT_REASONS_BY_LABEL.items()
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

    def select_item(self, index: int) -> BlindedExitReviewItem:
        if self.batch is None or not self.batch.items:
            raise ValueError("No exit blind-review batch is loaded")
        selected = int(index)
        if selected < 0 or selected >= len(self.batch.items):
            raise IndexError("exit blind-review item index is out of range")
        self.current_index = selected
        return self.current_item()

    def current_item(self) -> BlindedExitReviewItem:
        if self.batch is None or not self.batch.items:
            raise ValueError("No exit blind-review item is available")
        item = self.batch.items[self.current_index]
        return self._service.get_blinded_item(
            batch_id=self.batch.batch_id,
            blind_item_id=item.blind_item_id,
        )

    def make_judgment(
        self,
        *,
        label: str,
        reason_tags: tuple[str, ...],
        confidence: int,
        note: str,
    ) -> ExitBlindJudgmentInput:
        return ExitBlindJudgmentInput(
            label=label,
            reason_tags=reason_tags,
            confidence=confidence,
            note=note,
        )

    def save_blind_judgment(
        self,
        judgment: ExitBlindJudgmentInput,
    ) -> ExitJudgmentVersion:
        item = self._current_batch_item()
        return self._service.save_blind_judgment(
            batch_id=self.batch.batch_id,
            blind_item_id=item.blind_item_id,
            judgment=judgment,
        )

    def reveal_current(self) -> RevealedExitReviewItem:
        item = self._current_batch_item()
        return self._service.reveal(
            batch_id=self.batch.batch_id,
            blind_item_id=item.blind_item_id,
        )

    def candidate_audit_current(self) -> RevealedCandidateAudit | None:
        item = self._current_batch_item()
        batch = self.batch
        if batch is None:  # guarded by _current_batch_item
            raise RuntimeError("Exit review batch state is inconsistent")
        return self._service.get_candidate_audit_for_batch_item_after_judgment(
            batch_id=batch.batch_id,
            blind_item_id=item.blind_item_id,
        )

    def relabel_current(
        self,
        judgment: ExitBlindJudgmentInput,
    ) -> ExitJudgmentVersion:
        item = self._current_batch_item()
        batch = self.batch
        if batch is None:  # guarded by _current_batch_item
            raise RuntimeError("Exit review batch state is inconsistent")
        return self._service.relabel_batch_item_after_reveal(
            batch_id=batch.batch_id,
            blind_item_id=item.blind_item_id,
            judgment=judgment,
        )

    def _current_batch_item(self) -> BlindBatchItem:
        if self.batch is None or not self.batch.items:
            raise ValueError("No exit blind-review item is available")
        return self.batch.items[self.current_index]


__all__ = ["ExitBlindReviewController"]
