from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6 import QtWidgets

try:
    from research.market_episodes import EpisodeAuditSummary
except ImportError:  # pragma: no cover - package import path
    from ..research.market_episodes import EpisodeAuditSummary


Translator = Callable[[str], str]


@dataclass(frozen=True, slots=True)
class EpisodeMergeRequest:
    episode_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class EpisodeSplitRequest:
    episode_id: str
    sample_groups: tuple[tuple[str, ...], ...]
    reason: str


EpisodeCorrectionRequest = EpisodeMergeRequest | EpisodeSplitRequest


def request_episode_correction(
    parent: QtWidgets.QWidget,
    summary: EpisodeAuditSummary,
    translate: Translator,
) -> EpisodeCorrectionRequest | None:
    merge_label = translate("decision_research.episode.correction.merge")
    split_label = translate("decision_research.episode.correction.split")
    operation, accepted = QtWidgets.QInputDialog.getItem(
        parent,
        translate("decision_research.episode.correction.title"),
        translate("decision_research.episode.correction.operation"),
        (merge_label, split_label),
        0,
        False,
    )
    if not accepted:
        return None
    if operation == merge_label:
        return _request_merge(parent, summary, translate)
    return _request_split(parent, summary, translate)


def _request_merge(
    parent: QtWidgets.QWidget,
    summary: EpisodeAuditSummary,
    translate: Translator,
) -> EpisodeMergeRequest | None:
    if len(summary.composition) < 2:
        raise ValueError(
            translate("decision_research.episode.correction.merge_requires_two")
        )
    value, accepted = QtWidgets.QInputDialog.getText(
        parent,
        translate("decision_research.episode.correction.title"),
        translate("decision_research.episode.correction.merge_ids"),
        text=", ".join(item.episode_id for item in summary.composition),
    )
    if not accepted:
        return None
    episode_ids = tuple(part.strip() for part in value.split(",") if part.strip())
    reason = _request_reason(parent, translate)
    if reason is None:
        return None
    return EpisodeMergeRequest(episode_ids=episode_ids, reason=reason)


def _request_split(
    parent: QtWidgets.QWidget,
    summary: EpisodeAuditSummary,
    translate: Translator,
) -> EpisodeSplitRequest | None:
    candidates = tuple(
        item for item in summary.composition if len(item.sample_ids) >= 2
    )
    if not candidates:
        raise ValueError(
            translate("decision_research.episode.correction.split_requires_two")
        )
    episode_id, accepted = QtWidgets.QInputDialog.getItem(
        parent,
        translate("decision_research.episode.correction.title"),
        translate("decision_research.episode.correction.split_episode"),
        tuple(item.episode_id for item in candidates),
        0,
        False,
    )
    if not accepted:
        return None
    selected = next(item for item in candidates if item.episode_id == episode_id)
    default_groups = (
        f"{selected.sample_ids[0]} | " + ", ".join(selected.sample_ids[1:])
    )
    value, accepted = QtWidgets.QInputDialog.getText(
        parent,
        translate("decision_research.episode.correction.title"),
        translate("decision_research.episode.correction.split_groups"),
        text=default_groups,
    )
    if not accepted:
        return None
    groups = tuple(
        tuple(part.strip() for part in group.split(",") if part.strip())
        for group in value.split("|")
        if group.strip()
    )
    reason = _request_reason(parent, translate)
    if reason is None:
        return None
    return EpisodeSplitRequest(
        episode_id=str(episode_id),
        sample_groups=groups,
        reason=reason,
    )


def _request_reason(
    parent: QtWidgets.QWidget,
    translate: Translator,
) -> str | None:
    reason, accepted = QtWidgets.QInputDialog.getText(
        parent,
        translate("decision_research.episode.correction.title"),
        translate("decision_research.episode.correction.reason"),
    )
    if not accepted:
        return None
    normalized = reason.strip()
    if not normalized:
        raise ValueError(
            translate("decision_research.episode.correction.reason_required")
        )
    return normalized


__all__ = [
    "EpisodeCorrectionRequest",
    "EpisodeMergeRequest",
    "EpisodeSplitRequest",
    "request_episode_correction",
]
