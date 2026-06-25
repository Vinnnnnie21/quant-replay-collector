from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

try:
    from app_config import APP_VERSION
    from research.entry_annotations import (
        DecisionTiming,
        EntryAnnotation,
        HumanDecision,
        build_entry_annotation_id,
    )
except ImportError:  # pragma: no cover - package import path
    from ..app_config import APP_VERSION
    from ..research.entry_annotations import (
        DecisionTiming,
        EntryAnnotation,
        HumanDecision,
        build_entry_annotation_id,
    )


class EntryResearchService:
    """Small service boundary for entry logic annotation persistence."""

    def __init__(self, *, repository: Any, app_version: str = APP_VERSION) -> None:
        self._repository = repository
        self._app_version = str(app_version or APP_VERSION)

    def save_annotation(
        self,
        candidate: dict[str, Any],
        *,
        human_decision: str,
        confidence: int,
        reason_tags: list[str] | None = None,
        note: str = "",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return self.save_or_update_annotation(
            candidate,
            human_decision=human_decision,
            confidence=confidence,
            reason_tags=reason_tags,
            note=note,
            session_id=session_id,
        )

    def save_or_update_annotation(
        self,
        candidate: dict[str, Any],
        *,
        human_decision: str,
        confidence: int,
        reason_tags: list[str] | None = None,
        note: str = "",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Validate and persist an annotation through the update-aware repository path."""
        if not isinstance(candidate, dict):
            raise ValueError("candidate must be a mapping")
        decision = HumanDecision(str(human_decision).upper())
        timing = _decision_timing(candidate)
        decision_bar_index = _int_or_none(candidate.get("decision_bar_index", candidate.get("bar_index")))
        setup_bar_index = _setup_bar_index(candidate, timing, decision_bar_index)
        now = datetime.now(UTC).isoformat(timespec="seconds")
        session_id_value = str(session_id or candidate.get("session_id") or "")
        observation_id = _optional_text(candidate.get("observation_id"))
        annotation_id = _optional_text(candidate.get("annotation_id")) or build_entry_annotation_id(
            session_id=session_id_value,
            symbol=str(candidate.get("symbol") or ""),
            interval=str(candidate.get("interval") or ""),
            decision_bar_index=decision_bar_index,
            observation_id=observation_id,
            created_at=now,
        )
        payload = EntryAnnotation(
            annotation_id=annotation_id,
            observation_id=observation_id,
            session_id=session_id_value,
            symbol=str(candidate.get("symbol") or ""),
            interval=str(candidate.get("interval") or ""),
            bar_index=decision_bar_index,
            bar_time=_optional_text(candidate.get("bar_time") or candidate.get("decision_bar_time")),
            setup_bar_index=setup_bar_index,
            decision_bar_index=decision_bar_index,
            setup_bar_time=_optional_text(candidate.get("setup_bar_time")),
            decision_bar_time=_optional_text(candidate.get("decision_bar_time") or candidate.get("bar_time")),
            human_decision=decision,
            confidence=confidence,
            reason_tags=list(reason_tags or []),
            note=str(note or ""),
            decision_timing=timing,
            annotation_version=str(candidate.get("annotation_version") or "entry_annotations_v1"),
            created_at=now,
            updated_at=now,
            is_active=True,
            superseded_by=None,
            app_version=self._app_version,
        ).to_dict()
        if hasattr(self._repository, "save_or_update_annotation"):
            saved = self._repository.save_or_update_annotation(payload)
            return dict(saved or payload)
        self._repository.save_entry_annotation(payload)
        return payload


def _decision_timing(candidate: dict[str, Any]) -> DecisionTiming:
    raw = candidate.get("decision_timing") or "CURRENT_BAR_CLOSE"
    return DecisionTiming(str(raw).upper())


def _setup_bar_index(candidate: dict[str, Any], timing: DecisionTiming, decision_bar_index: int | None) -> int | None:
    value = _int_or_none(candidate.get("setup_bar_index"))
    if value is not None:
        return value
    if timing is DecisionTiming.NEXT_BAR_CONFIRMATION and decision_bar_index is not None:
        return decision_bar_index - 1
    return decision_bar_index


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


__all__ = ["EntryResearchService"]