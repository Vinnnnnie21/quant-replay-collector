from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, Sequence


EPISODE_FORMULA_VERSION = "market_episode_interval_overlap_v1"


class TimeBoundary(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class EpisodeSource(StrEnum):
    AUTOMATIC = "AUTOMATIC"
    MANUAL_MERGE = "MANUAL_MERGE"
    MANUAL_SPLIT = "MANUAL_SPLIT"


@dataclass(frozen=True, slots=True)
class TimeRange:
    start: datetime
    end: datetime
    start_boundary: TimeBoundary = TimeBoundary.CLOSED
    end_boundary: TimeBoundary = TimeBoundary.CLOSED

    def __post_init__(self) -> None:
        start = _utc_datetime(self.start, "start")
        end = _utc_datetime(self.end, "end")
        start_boundary = TimeBoundary(self.start_boundary)
        end_boundary = TimeBoundary(self.end_boundary)
        if end < start:
            raise ValueError("time range end must not precede start")
        if end == start and (
            start_boundary is TimeBoundary.OPEN
            or end_boundary is TimeBoundary.OPEN
        ):
            raise ValueError("an open zero-length time range is empty")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "start_boundary", start_boundary)
        object.__setattr__(self, "end_boundary", end_boundary)


@dataclass(frozen=True, slots=True)
class ResearchSampleWindow:
    sample_id: str
    symbol: str
    timeframe: str
    feature_window: TimeRange
    outcome_window: TimeRange

    def __post_init__(self) -> None:
        for field_name in ("sample_id", "symbol", "timeframe"):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must not be empty")
            object.__setattr__(self, field_name, value)
        if not isinstance(self.feature_window, TimeRange):
            raise TypeError("feature_window must be a TimeRange")
        if not isinstance(self.outcome_window, TimeRange):
            raise TypeError("outcome_window must be a TimeRange")


@dataclass(frozen=True, slots=True)
class MarketEpisode:
    episode_id: str
    time_range: TimeRange
    members: tuple[ResearchSampleWindow, ...]
    source: EpisodeSource = EpisodeSource.AUTOMATIC

    def __post_init__(self) -> None:
        if not self.episode_id.strip():
            raise ValueError("episode_id must not be empty")
        if not self.members:
            raise ValueError("a market episode must contain at least one sample")
        sample_ids = tuple(member.sample_id for member in self.members)
        if len(set(sample_ids)) != len(sample_ids):
            raise ValueError("episode members must have unique sample ids")
        object.__setattr__(self, "source", EpisodeSource(self.source))


@dataclass(frozen=True, slots=True)
class EpisodeGrouping:
    grouping_version_id: str
    formula_version: str
    input_range: TimeRange
    episodes: tuple[MarketEpisode, ...]
    created_at: datetime
    source: EpisodeSource = EpisodeSource.AUTOMATIC
    parent_grouping_version_id: str | None = None

    def __post_init__(self) -> None:
        if not self.grouping_version_id.strip():
            raise ValueError("grouping_version_id must not be empty")
        if not self.formula_version.strip():
            raise ValueError("formula_version must not be empty")
        if not self.episodes:
            raise ValueError("an episode grouping must contain at least one episode")
        sample_ids = tuple(
            member.sample_id
            for episode in self.episodes
            for member in episode.members
        )
        if len(set(sample_ids)) != len(sample_ids):
            raise ValueError(
                "a sample may belong to only one episode per grouping version"
            )
        object.__setattr__(self, "created_at", _utc_datetime(self.created_at, "created_at"))
        object.__setattr__(self, "source", EpisodeSource(self.source))

    def episode_id_by_sample(self) -> dict[str, str]:
        return {
            member.sample_id: episode.episode_id
            for episode in self.episodes
            for member in episode.members
        }


@dataclass(frozen=True, slots=True)
class EpisodeAuditRecord:
    audit_id: str
    base_grouping_version_id: str
    result_grouping_version_id: str
    command_type: EpisodeSource
    episode_ids: tuple[str, ...]
    actor: str
    reason: str
    created_at: datetime
    sample_groups: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        command_type = EpisodeSource(self.command_type)
        if command_type is EpisodeSource.AUTOMATIC:
            raise ValueError(
                "automatic grouping does not create a manual correction audit"
            )
        object.__setattr__(self, "command_type", command_type)
        object.__setattr__(self, "actor", _required_text(self.actor, "actor"))
        object.__setattr__(self, "reason", _required_text(self.reason, "reason"))
        object.__setattr__(self, "created_at", _utc_datetime(self.created_at, "created_at"))


@dataclass(frozen=True, slots=True)
class EpisodeComposition:
    episode_id: str
    time_range: TimeRange
    sample_ids: tuple[str, ...]
    symbols: tuple[str, ...]
    timeframes: tuple[str, ...]
    source: EpisodeSource


@dataclass(frozen=True, slots=True)
class EpisodeAuditSummary:
    grouping_version_id: str
    formula_version: str
    grouping_source: EpisodeSource
    episode_count: int
    sample_count: int
    composition: tuple[EpisodeComposition, ...]
    can_correct: bool


@dataclass(frozen=True, slots=True)
class EpisodeAssignment:
    grouping_version_id: str
    sample_id: str
    episode_id: str


@dataclass(frozen=True, slots=True)
class EpisodeIsolatedBatch:
    grouping_version_id: str
    sample_ids: tuple[str, ...]


class EpisodeResolver(Protocol):
    def resolve_episode_ids(
        self,
        grouping_version_id: str,
        sample_ids: Sequence[str],
    ) -> tuple[EpisodeAssignment, ...]: ...


class EpisodeStorage(Protocol):
    def save_episode_grouping(self, grouping: EpisodeGrouping) -> None: ...

    def get_episode_grouping(self, grouping_version_id: str) -> EpisodeGrouping | None: ...

    def save_episode_revision(
        self,
        grouping: EpisodeGrouping,
        audit: EpisodeAuditRecord,
    ) -> None: ...

    def list_episode_audit(self, grouping_version_id: str) -> tuple[EpisodeAuditRecord, ...]: ...


class MarketEpisodeService:
    def __init__(self, storage: EpisodeStorage):
        self._storage = storage

    def create_automatic_grouping(
        self,
        samples: Sequence[ResearchSampleWindow],
        *,
        created_at: datetime,
    ) -> EpisodeGrouping:
        normalized = tuple(samples)
        if not normalized:
            raise ValueError("at least one research sample window is required")
        sample_ids = [sample.sample_id for sample in normalized]
        if len(set(sample_ids)) != len(sample_ids):
            raise ValueError("sample_id values must be unique within a grouping")
        episodes = _group_overlapping_samples(normalized)
        input_range = _covering_range(
            tuple(
                time_range
                for sample in normalized
                for time_range in (sample.feature_window, sample.outcome_window)
            )
        )
        fingerprint = _automatic_fingerprint(normalized)
        grouping = EpisodeGrouping(
            grouping_version_id=f"egv_{fingerprint[:24]}",
            formula_version=EPISODE_FORMULA_VERSION,
            input_range=input_range,
            episodes=episodes,
            created_at=created_at,
        )
        self._storage.save_episode_grouping(grouping)
        return self.get_grouping(grouping.grouping_version_id)

    def get_grouping(self, grouping_version_id: str) -> EpisodeGrouping:
        grouping = self._storage.get_episode_grouping(grouping_version_id)
        if grouping is None:
            raise KeyError(f"unknown episode grouping version: {grouping_version_id}")
        return grouping

    def merge_episodes(
        self,
        base_grouping_version_id: str,
        episode_ids: Sequence[str],
        *,
        actor: str,
        reason: str,
        created_at: datetime,
    ) -> EpisodeGrouping:
        base = self.get_grouping(base_grouping_version_id)
        selected_ids = tuple(sorted(set(str(item) for item in episode_ids)))
        if len(selected_ids) < 2:
            raise ValueError("manual merge requires at least two distinct episode ids")
        selected = tuple(episode for episode in base.episodes if episode.episode_id in selected_ids)
        if len(selected) != len(selected_ids):
            raise ValueError("manual merge contains an unknown episode id")
        members = tuple(
            sorted(
                (member for episode in selected for member in episode.members),
                key=lambda item: item.sample_id,
            )
        )
        command_payload = {
            "base_grouping_version_id": base.grouping_version_id,
            "command_type": EpisodeSource.MANUAL_MERGE.value,
            "episode_ids": selected_ids,
        }
        command_hash = _hash_payload(command_payload)
        merged = MarketEpisode(
            episode_id=f"ep_{command_hash[:24]}",
            time_range=_covering_range(
                tuple(
                    window
                    for member in members
                    for window in (member.feature_window, member.outcome_window)
                )
            ),
            members=members,
            source=EpisodeSource.MANUAL_MERGE,
        )
        untouched = tuple(episode for episode in base.episodes if episode.episode_id not in selected_ids)
        corrected = EpisodeGrouping(
            grouping_version_id=f"egv_{command_hash[:24]}",
            formula_version=base.formula_version,
            input_range=base.input_range,
            episodes=tuple(
                sorted((*untouched, merged), key=lambda item: (item.time_range.start, item.episode_id))
            ),
            created_at=created_at,
            source=EpisodeSource.MANUAL_MERGE,
            parent_grouping_version_id=base.grouping_version_id,
        )
        audit = EpisodeAuditRecord(
            audit_id=f"epa_{command_hash[:24]}",
            base_grouping_version_id=base.grouping_version_id,
            result_grouping_version_id=corrected.grouping_version_id,
            command_type=EpisodeSource.MANUAL_MERGE,
            episode_ids=selected_ids,
            actor=_required_text(actor, "actor"),
            reason=_required_text(reason, "reason"),
            created_at=created_at,
        )
        self._storage.save_episode_revision(corrected, audit)
        return self.get_grouping(corrected.grouping_version_id)

    def list_audit(self, grouping_version_id: str) -> tuple[EpisodeAuditRecord, ...]:
        records = self._storage.list_episode_audit(grouping_version_id)
        if not records:
            return ()
        if records[-1].result_grouping_version_id != grouping_version_id:
            raise ValueError("episode audit history does not end at the requested version")
        for previous, current in zip(records, records[1:]):
            if previous.result_grouping_version_id != current.base_grouping_version_id:
                raise ValueError("episode audit history contains a broken parent chain")
        result_ids = tuple(record.result_grouping_version_id for record in records)
        if (
            len(set(result_ids)) != len(result_ids)
            or records[0].base_grouping_version_id in result_ids
        ):
            raise ValueError("episode audit history contains a cycle")
        return records

    def audit_summary(self, grouping_version_id: str) -> EpisodeAuditSummary:
        grouping = self.get_grouping(grouping_version_id)
        composition = tuple(
            EpisodeComposition(
                episode_id=episode.episode_id,
                time_range=episode.time_range,
                sample_ids=tuple(member.sample_id for member in episode.members),
                symbols=tuple(sorted({member.symbol for member in episode.members})),
                timeframes=tuple(sorted({member.timeframe for member in episode.members})),
                source=episode.source,
            )
            for episode in grouping.episodes
        )
        return EpisodeAuditSummary(
            grouping_version_id=grouping.grouping_version_id,
            formula_version=grouping.formula_version,
            grouping_source=grouping.source,
            episode_count=len(grouping.episodes),
            sample_count=sum(len(episode.members) for episode in grouping.episodes),
            composition=composition,
            can_correct=bool(grouping.episodes),
        )

    def resolve_episode_ids(
        self,
        grouping_version_id: str,
        sample_ids: Sequence[str],
    ) -> tuple[EpisodeAssignment, ...]:
        requested = tuple(str(sample_id) for sample_id in sample_ids)
        episode_by_sample = self.get_grouping(grouping_version_id).episode_id_by_sample()
        missing = tuple(sample_id for sample_id in requested if sample_id not in episode_by_sample)
        if missing:
            raise KeyError(
                "samples are not members of episode grouping "
                f"{grouping_version_id}: {', '.join(missing)}"
            )
        return tuple(
            EpisodeAssignment(
                grouping_version_id=grouping_version_id,
                sample_id=sample_id,
                episode_id=episode_by_sample[sample_id],
            )
            for sample_id in requested
        )

    def build_isolated_batches(
        self,
        grouping_version_id: str,
        sample_ids: Sequence[str],
        *,
        batch_size: int,
    ) -> tuple[EpisodeIsolatedBatch, ...]:
        size = int(batch_size)
        if size <= 0:
            raise ValueError("batch_size must be positive")
        requested = tuple(str(sample_id) for sample_id in sample_ids)
        if len(set(requested)) != len(requested):
            raise ValueError("blind review batches require unique sample ids")
        assignments = self.resolve_episode_ids(grouping_version_id, requested)
        queues: dict[str, deque[str]] = {}
        for assignment in assignments:
            queues.setdefault(assignment.episode_id, deque()).append(
                assignment.sample_id
            )
        episode_ids = tuple(queues)
        batches = []
        cursor = 0
        remaining = len(assignments)
        while remaining:
            selected: list[str] = []
            checked = 0
            while len(selected) < size and checked < len(episode_ids):
                episode_id = episode_ids[(cursor + checked) % len(episode_ids)]
                if queues[episode_id]:
                    selected.append(queues[episode_id].popleft())
                    remaining -= 1
                checked += 1
            cursor = (cursor + checked) % len(episode_ids)
            batches.append(
                EpisodeIsolatedBatch(
                    grouping_version_id=grouping_version_id,
                    sample_ids=tuple(selected),
                )
            )
        return tuple(batches)

    def split_episode(
        self,
        base_grouping_version_id: str,
        episode_id: str,
        sample_groups: Sequence[Sequence[str]],
        *,
        actor: str,
        reason: str,
        created_at: datetime,
    ) -> EpisodeGrouping:
        base = self.get_grouping(base_grouping_version_id)
        selected = next(
            (episode for episode in base.episodes if episode.episode_id == episode_id),
            None,
        )
        if selected is None:
            raise ValueError("manual split contains an unknown episode id")
        normalized_groups = tuple(
            sorted(
                (tuple(sorted(set(str(item) for item in group))) for group in sample_groups),
                key=lambda group: group,
            )
        )
        if len(normalized_groups) < 2 or any(not group for group in normalized_groups):
            raise ValueError("manual split requires at least two non-empty sample groups")
        flattened = tuple(sample_id for group in normalized_groups for sample_id in group)
        expected = tuple(sorted(member.sample_id for member in selected.members))
        if len(set(flattened)) != len(flattened) or tuple(sorted(flattened)) != expected:
            raise ValueError("manual split groups must partition every episode sample exactly once")
        command_payload = {
            "base_grouping_version_id": base.grouping_version_id,
            "command_type": EpisodeSource.MANUAL_SPLIT.value,
            "episode_id": selected.episode_id,
            "sample_groups": normalized_groups,
        }
        command_hash = _hash_payload(command_payload)
        members_by_id = {member.sample_id: member for member in selected.members}
        replacements = []
        for group in normalized_groups:
            members = tuple(members_by_id[sample_id] for sample_id in group)
            episode_hash = _hash_payload(
                {
                    "command_hash": command_hash,
                    "sample_ids": group,
                }
            )
            replacements.append(
                MarketEpisode(
                    episode_id=f"ep_{episode_hash[:24]}",
                    time_range=_covering_range(
                        tuple(
                            window
                            for member in members
                            for window in (member.feature_window, member.outcome_window)
                        )
                    ),
                    members=members,
                    source=EpisodeSource.MANUAL_SPLIT,
                )
            )
        untouched = tuple(episode for episode in base.episodes if episode.episode_id != selected.episode_id)
        corrected = EpisodeGrouping(
            grouping_version_id=f"egv_{command_hash[:24]}",
            formula_version=base.formula_version,
            input_range=base.input_range,
            episodes=tuple(
                sorted((*untouched, *replacements), key=lambda item: (item.time_range.start, item.episode_id))
            ),
            created_at=created_at,
            source=EpisodeSource.MANUAL_SPLIT,
            parent_grouping_version_id=base.grouping_version_id,
        )
        audit = EpisodeAuditRecord(
            audit_id=f"epa_{command_hash[:24]}",
            base_grouping_version_id=base.grouping_version_id,
            result_grouping_version_id=corrected.grouping_version_id,
            command_type=EpisodeSource.MANUAL_SPLIT,
            episode_ids=(selected.episode_id,),
            sample_groups=normalized_groups,
            actor=_required_text(actor, "actor"),
            reason=_required_text(reason, "reason"),
            created_at=created_at,
        )
        self._storage.save_episode_revision(corrected, audit)
        return self.get_grouping(corrected.grouping_version_id)


class _DisjointSet:
    def __init__(self, size: int):
        self._parent = list(range(size))

    def find(self, item: int) -> int:
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != item:
            parent = self._parent[item]
            self._parent[item] = root
            item = parent
        return root

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self._parent[right_root] = left_root


def _group_overlapping_samples(
    samples: tuple[ResearchSampleWindow, ...],
) -> tuple[MarketEpisode, ...]:
    disjoint = _DisjointSet(len(samples))
    intervals = sorted(
        (
            (time_range, sample_index)
            for sample_index, sample in enumerate(samples)
            for time_range in (sample.feature_window, sample.outcome_window)
        ),
        key=lambda item: (
            item[0].start,
            item[0].start_boundary is TimeBoundary.OPEN,
            item[0].end,
            item[1],
        ),
    )
    component_members: set[int] = set()
    component_end: datetime | None = None
    component_end_boundary = TimeBoundary.OPEN
    for time_range, sample_index in intervals:
        if component_end is None or not _starts_before_component_ends(
            time_range,
            component_end,
            component_end_boundary,
        ):
            _union_members(disjoint, component_members)
            component_members = {sample_index}
            component_end = time_range.end
            component_end_boundary = time_range.end_boundary
            continue
        component_members.add(sample_index)
        if time_range.end > component_end:
            component_end = time_range.end
            component_end_boundary = time_range.end_boundary
        elif time_range.end == component_end and time_range.end_boundary is TimeBoundary.CLOSED:
            component_end_boundary = TimeBoundary.CLOSED
    _union_members(disjoint, component_members)

    grouped: dict[int, list[ResearchSampleWindow]] = {}
    for sample_index, sample in enumerate(samples):
        grouped.setdefault(disjoint.find(sample_index), []).append(sample)
    episodes = []
    for members in grouped.values():
        ordered_members = tuple(sorted(members, key=lambda item: item.sample_id))
        time_range = _covering_range(
            tuple(
                window
                for member in ordered_members
                for window in (member.feature_window, member.outcome_window)
            )
        )
        episode_payload = {
            "formula_version": EPISODE_FORMULA_VERSION,
            "sample_ids": [member.sample_id for member in ordered_members],
        }
        episode_hash = _hash_payload(episode_payload)
        episodes.append(
            MarketEpisode(
                episode_id=f"ep_{episode_hash[:24]}",
                time_range=time_range,
                members=ordered_members,
            )
        )
    return tuple(sorted(episodes, key=lambda item: (item.time_range.start, item.episode_id)))


def _starts_before_component_ends(
    time_range: TimeRange,
    component_end: datetime,
    component_end_boundary: TimeBoundary,
) -> bool:
    if time_range.start < component_end:
        return True
    if time_range.start > component_end:
        return False
    return (
        time_range.start_boundary is TimeBoundary.CLOSED
        and component_end_boundary is TimeBoundary.CLOSED
    )


def _union_members(disjoint: _DisjointSet, members: set[int]) -> None:
    iterator = iter(members)
    representative = next(iterator, None)
    if representative is None:
        return
    for member in iterator:
        disjoint.union(representative, member)


def _covering_range(ranges: tuple[TimeRange, ...]) -> TimeRange:
    start = min(item.start for item in ranges)
    end = max(item.end for item in ranges)
    start_boundary = (
        TimeBoundary.CLOSED
        if any(item.start == start and item.start_boundary is TimeBoundary.CLOSED for item in ranges)
        else TimeBoundary.OPEN
    )
    end_boundary = (
        TimeBoundary.CLOSED
        if any(item.end == end and item.end_boundary is TimeBoundary.CLOSED for item in ranges)
        else TimeBoundary.OPEN
    )
    return TimeRange(start, end, start_boundary, end_boundary)


def _automatic_fingerprint(samples: tuple[ResearchSampleWindow, ...]) -> str:
    return _hash_payload(
        {
            "formula_version": EPISODE_FORMULA_VERSION,
            "samples": [_sample_payload(sample) for sample in sorted(samples, key=lambda item: item.sample_id)],
        }
    )


def _sample_payload(sample: ResearchSampleWindow) -> dict[str, object]:
    return {
        "sample_id": sample.sample_id,
        "symbol": sample.symbol,
        "timeframe": sample.timeframe,
        "feature_window": _range_payload(sample.feature_window),
        "outcome_window": _range_payload(sample.outcome_window),
    }


def _range_payload(time_range: TimeRange) -> dict[str, str]:
    return {
        "start": time_range.start.isoformat(),
        "end": time_range.end.isoformat(),
        "start_boundary": time_range.start_boundary.value,
        "end_boundary": time_range.end_boundary.value,
    }


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_datetime(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _required_text(value: str, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


__all__ = [
    "EPISODE_FORMULA_VERSION",
    "EpisodeGrouping",
    "EpisodeAuditRecord",
    "EpisodeAuditSummary",
    "EpisodeAssignment",
    "EpisodeIsolatedBatch",
    "EpisodeResolver",
    "EpisodeComposition",
    "EpisodeSource",
    "MarketEpisode",
    "MarketEpisodeService",
    "ResearchSampleWindow",
    "TimeBoundary",
    "TimeRange",
]
