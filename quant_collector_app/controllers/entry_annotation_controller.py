from __future__ import annotations

from dataclasses import dataclass
from typing import Any


METADATA_COLUMNS = {
    "observation_id",
    "review_id",
    "review_reason",
    "review_mode",
    "review_queue_version",
    "session_id",
    "symbol",
    "interval",
    "bar_index",
    "bar_time",
    "setup_bar_index",
    "decision_bar_index",
    "setup_bar_time",
    "decision_bar_time",
    "decision_timing",
    "candidate_source",
    "candidate_reason",
    "data_version",
    "annotation_version",
}


@dataclass(frozen=True)
class AnnotationSaveResult:
    ok: bool
    message: str
    annotation: dict[str, Any] | None = None
    completed_observation_id: str | None = None


def entry_review_shortcut_action(sequence: str) -> tuple[str, str | int] | None:
    key = str(sequence or "").strip().upper()
    if key in {"E", "R", "U"}:
        return ("decision", {"E": "ENTRY", "R": "REJECT", "U": "UNCERTAIN"}[key])
    if key == "N":
        return ("navigate", "next")
    if key == "B":
        return ("navigate", "previous")
    if key in {"1", "2", "3", "4", "5"}:
        return ("confidence", int(key))
    return None


class EntryAnnotationController:
    """Pure logic controller for entry review queue annotation."""

    def __init__(self, service: Any) -> None:
        self._service = service
        self.review_queue: list[dict[str, Any]] = []
        self.current_index = 0
        self.confidence = 3

    def load_review_queue(self, rows: list[dict[str, Any]]) -> None:
        self.review_queue = [dict(row) for row in rows]
        self.current_index = 0

    def current_candidate(self) -> dict[str, Any] | None:
        if not self.review_queue:
            return None
        self.current_index = max(0, min(self.current_index, len(self.review_queue) - 1))
        return self.review_queue[self.current_index]

    def current_candidate_detail(self) -> dict[str, Any]:
        candidate = self.current_candidate()
        if candidate is None:
            return {"message": "No review candidate"}
        return {
            "observation_id": candidate.get("observation_id"),
            "symbol": candidate.get("symbol"),
            "interval": candidate.get("interval"),
            "setup_bar_index": _int_or_none(candidate.get("setup_bar_index")),
            "decision_bar_index": self.current_jump_bar_index(),
            "decision_timing": candidate.get("decision_timing") or "CURRENT_BAR_CLOSE",
            "candidate_reason": candidate.get("candidate_reason") or candidate.get("review_reason"),
            "context_features": _context_features(candidate),
        }

    def current_jump_bar_index(self) -> int | None:
        candidate = self.current_candidate()
        if candidate is None:
            return None
        return _int_or_none(candidate.get("decision_bar_index", candidate.get("bar_index")))

    def move_next(self) -> dict[str, Any] | None:
        if self.review_queue:
            self.current_index = min(len(self.review_queue) - 1, self.current_index + 1)
        return self.current_candidate()

    def move_previous(self) -> dict[str, Any] | None:
        if self.review_queue:
            self.current_index = max(0, self.current_index - 1)
        return self.current_candidate()

    def set_confidence(self, value: int) -> int:
        confidence = int(value)
        if confidence < 1 or confidence > 5:
            raise ValueError("confidence must be between 1 and 5")
        self.confidence = confidence
        return self.confidence

    def handle_shortcut(self, sequence: str) -> tuple[str, str | int] | None:
        action = entry_review_shortcut_action(sequence)
        if action is None:
            return None
        action_type, value = action
        if action_type == "navigate" and value == "next":
            self.move_next()
        elif action_type == "navigate" and value == "previous":
            self.move_previous()
        elif action_type == "confidence":
            self.set_confidence(int(value))
        return action

    def save_current_annotation(
        self,
        human_decision: str,
        *,
        confidence: int | None = None,
        reason_tags: list[str] | None = None,
        note: str = "",
        session_id: str | None = None,
    ) -> AnnotationSaveResult:
        candidate = self.current_candidate()
        if candidate is None:
            raise ValueError("No review candidate")
        try:
            annotation = self._service.save_or_update_annotation(
                candidate,
                human_decision=human_decision,
                confidence=self.confidence if confidence is None else int(confidence),
                reason_tags=list(reason_tags or []),
                note=note,
                session_id=session_id,
            )
        except Exception as exc:
            return AnnotationSaveResult(False, f"{type(exc).__name__}: {exc}")
        completed_id = str(candidate.get("observation_id") or "")
        self._remove_current_candidate()
        return AnnotationSaveResult(True, "annotation_saved", annotation, completed_id)

    def _remove_current_candidate(self) -> None:
        if not self.review_queue:
            return
        del self.review_queue[self.current_index]
        if self.current_index >= len(self.review_queue):
            self.current_index = max(0, len(self.review_queue) - 1)


def _context_features(candidate: dict[str, Any]) -> dict[str, Any]:
    features: dict[str, Any] = {}
    for key, value in candidate.items():
        name = str(key)
        if name in METADATA_COLUMNS:
            continue
        lowered = name.lower()
        if any(token in lowered for token in ("future", "fwd", "mfe", "mae", "hit_tp", "hit_sl", "buy_signal", "sell_signal")):
            continue
        parsed = _numeric_value(value)
        if parsed is not None:
            features[name] = parsed
    return features


def _numeric_value(value: Any) -> float | int | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


__all__ = [
    "AnnotationSaveResult",
    "EntryAnnotationController",
    "entry_review_shortcut_action",
]
