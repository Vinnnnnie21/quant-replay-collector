from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
import pandas as pd
from typing import Any

try:
    from market_data.types import interval_to_ms
    from research.entry_context_features import (
        ENTRY_STRUCTURAL_FEATURE_VERSION,
        ENTRY_STRUCTURAL_HISTORY_BARS,
        EntryStructuralFeatureSnapshot,
        build_entry_structural_feature_snapshot,
    )
    from research.entry_similarity import (
        ENTRY_SIMILARITY_FORMULA_VERSION,
        EntrySimilarityResult,
        SimilarityStatus,
        SimilarityUsage,
        compare_entry_structural_snapshot_sets,
        entry_similarity_result_from_dict,
    )
except ImportError:  # pragma: no cover - package import path
    from ..market_data.types import interval_to_ms
    from ..research.entry_context_features import (
        ENTRY_STRUCTURAL_FEATURE_VERSION,
        ENTRY_STRUCTURAL_HISTORY_BARS,
        EntryStructuralFeatureSnapshot,
        build_entry_structural_feature_snapshot,
    )
    from ..research.entry_similarity import (
        ENTRY_SIMILARITY_FORMULA_VERSION,
        EntrySimilarityResult,
        SimilarityStatus,
        SimilarityUsage,
        compare_entry_structural_snapshot_sets,
        entry_similarity_result_from_dict,
    )


_STORAGE_METHODS = (
    "fetch_klines_for_range",
    "get_entry_decision_event",
    "get_entry_review_reveal",
    "get_entry_similarity_audit",
    "get_setup_version",
    "list_revealed_entry_decision_events",
    "save_entry_similarity_audit",
)


def supports_entry_similarity_storage(storage: Any) -> bool:
    return storage is not None and all(
        callable(getattr(storage, method, None))
        for method in _STORAGE_METHODS
    )


@dataclass(frozen=True, slots=True)
class BrowsableEntrySample:
    decision_event_id: str
    symbol: str
    direction: str
    decision_cutoff_utc_ms: int
    revealed: bool


class EntryStructuralSimilarityService:
    """Compute and audit one bounded free-browse structural comparison."""

    def __init__(self, storage: Any) -> None:
        if not supports_entry_similarity_storage(storage):
            raise TypeError(
                "storage does not implement the entry similarity contract"
            )
        self._storage = storage

    def compare_revealed_samples(
        self,
        left_decision_event_id: str,
        right_decision_event_id: str,
    ) -> EntrySimilarityResult:
        event_ids = tuple(
            sorted(
                (
                    _required_text(left_decision_event_id, "left_decision_event_id"),
                    _required_text(right_decision_event_id, "right_decision_event_id"),
                )
            )
        )
        if event_ids[0] == event_ids[1]:
            raise ValueError("entry similarity requires two distinct samples")
        events = tuple(
            self._storage.get_entry_decision_event(event_id)
            for event_id in event_ids
        )
        if any(event is None for event in events):
            raise KeyError("Unknown entry decision event")
        left, right = events
        assert left is not None and right is not None
        if any(
            self._storage.get_entry_review_reveal(event_id) is None
            for event_id in event_ids
        ):
            raise PermissionError(
                "entry similarity requires two revealed browse samples"
            )
        setup_version_id = str(left["setup_version_id"])
        direction = str(left["direction"])
        compatibility_reasons = []
        if right["setup_version_id"] != setup_version_id:
            compatibility_reasons.append("setup_version_mismatch")
        if right["direction"] != direction:
            compatibility_reasons.append("direction_mismatch")
        setup = self._storage.get_setup_version(setup_version_id)
        if setup is None:
            raise KeyError(f"Unknown Setup version: {setup_version_id}")
        intervals = setup.timeframes.as_tuple()
        event_intervals = (
            left["decision_timeframe"],
            left["context_timeframe_one"],
            left["context_timeframe_two"],
        )
        right_intervals = (
            right["decision_timeframe"],
            right["context_timeframe_one"],
            right["context_timeframe_two"],
        )
        if tuple(event_intervals) != intervals or tuple(right_intervals) != intervals:
            compatibility_reasons.append("timeframe_profile_mismatch")

        left_snapshots = load_entry_structural_snapshots(
            self._storage,
            left,
            intervals,
        )
        right_snapshots = load_entry_structural_snapshots(
            self._storage,
            right,
            intervals,
        )
        comparison = compare_entry_structural_snapshot_sets(
            left_snapshots,
            right_snapshots,
            left_cutoff_utc_ms=int(left["decision_cutoff_utc_ms"]),
            right_cutoff_utc_ms=int(right["decision_cutoff_utc_ms"]),
        )
        calendar = comparison.calendar
        timeframes = comparison.timeframes
        reasons = list(compatibility_reasons)
        reasons.extend(
            f"{item.interval}:{reason}"
            for item in timeframes
            for reason in item.unavailable_reasons
        )
        aggregate = (
            comparison.aggregate
            if not reasons
            else None
        )
        left_fingerprint = feature_snapshot_fingerprint(left_snapshots)
        right_fingerprint = feature_snapshot_fingerprint(right_snapshots)
        created_at = datetime.now(UTC).isoformat(timespec="microseconds")
        result_id = "entry_similarity_" + hashlib.sha256(
            "|".join(
                (
                    *event_ids,
                    ENTRY_SIMILARITY_FORMULA_VERSION,
                    ENTRY_STRUCTURAL_FEATURE_VERSION,
                    left_fingerprint,
                    right_fingerprint,
                )
            ).encode("utf-8")
        ).hexdigest()[:24]
        result = EntrySimilarityResult(
            result_id=result_id,
            left_decision_event_id=event_ids[0],
            right_decision_event_id=event_ids[1],
            setup_version_id=setup_version_id,
            direction=direction,
            formula_version=ENTRY_SIMILARITY_FORMULA_VERSION,
            feature_version=ENTRY_STRUCTURAL_FEATURE_VERSION,
            left_feature_fingerprint=left_fingerprint,
            right_feature_fingerprint=right_fingerprint,
            status=(
                SimilarityStatus.COMPUTED
                if aggregate is not None
                else SimilarityStatus.NOT_COMPUTABLE
            ),
            similarity=None if aggregate is None else aggregate.similarity,
            total_distance=None if aggregate is None else aggregate.total_distance,
            market_distance=None if aggregate is None else aggregate.market_distance,
            calendar=calendar,
            timeframes=timeframes,
            unavailable_reasons=tuple(reasons),
            usage=SimilarityUsage.FREE_BROWSE,
            eligible_for_formal_evidence=False,
            created_at=created_at,
        )
        payload = json.dumps(
            asdict(result),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        inserted = self._storage.save_entry_similarity_audit(
            {
                **asdict(result),
                "status": result.status.value,
                "usage": result.usage.value,
                "result_json": payload,
            }
        )
        if not inserted:
            stored = self.get_audit(result_id)
            if stored is None:
                raise RuntimeError("Entry similarity audit could not be persisted")
            return stored
        return result

    def list_browsable_samples(
        self,
        *,
        setup_version_id: str,
        direction: str,
        limit: int = 200,
    ) -> tuple[BrowsableEntrySample, ...]:
        bounded_limit = int(limit)
        if bounded_limit < 1 or bounded_limit > 500:
            raise ValueError("browsable sample limit must be between 1 and 500")
        normalized_direction = _required_text(direction, "direction").upper()
        if normalized_direction not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT")
        rows = self._storage.list_revealed_entry_decision_events(
            setup_version_id=_required_text(
                setup_version_id,
                "setup_version_id",
            ),
            direction=normalized_direction,
            limit=bounded_limit,
        )
        return tuple(
            BrowsableEntrySample(
                decision_event_id=str(row["decision_event_id"]),
                symbol=str(row["symbol"]),
                direction=str(row["direction"]),
                decision_cutoff_utc_ms=int(row["decision_cutoff_utc_ms"]),
                revealed=True,
            )
            for row in rows
        )

    def get_audit(self, result_id: str) -> EntrySimilarityResult | None:
        row = self._storage.get_entry_similarity_audit(
            _required_text(result_id, "result_id")
        )
        if row is None:
            return None
        return entry_similarity_result_from_dict(
            json.loads(row["result_json"])
        )



def load_entry_structural_snapshots(
    storage: Any,
    event: dict[str, Any],
    intervals: tuple[str, str, str],
) -> tuple[EntryStructuralFeatureSnapshot, ...]:
    """Read only closed pre-cutoff bars and build the canonical snapshots."""

    cutoff = int(event["decision_cutoff_utc_ms"])
    snapshots = []
    for interval in intervals:
        duration = interval_to_ms(interval)
        rows = storage.fetch_klines_for_range(
            symbol=event["symbol"],
            interval=interval,
            start_time_utc_ms=max(
                0,
                cutoff - duration * (ENTRY_STRUCTURAL_HISTORY_BARS + 1),
            ),
            end_time_utc_ms=cutoff - 1,
        )
        snapshots.append(
            build_entry_structural_feature_snapshot(
                pd.DataFrame(
                    rows,
                    columns=(
                        "open_time_utc_ms",
                        "close_time_utc_ms",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                        "quote_volume",
                        "trade_count",
                        "taker_buy_base_volume",
                        "taker_buy_quote_volume",
                    ),
                ),
                symbol=event["symbol"],
                interval=interval,
                cutoff_time_utc_ms=cutoff,
            )
        )
    return tuple(snapshots)


def feature_snapshot_fingerprint(
    snapshots: tuple[EntryStructuralFeatureSnapshot, ...],
) -> str:
    """Return a stable identity for one decision-time feature snapshot set."""

    payload = json.dumps(
        [asdict(snapshot) for snapshot in snapshots],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _required_text(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


__all__ = [
    "BrowsableEntrySample",
    "EntryStructuralSimilarityService",
    "feature_snapshot_fingerprint",
    "load_entry_structural_snapshots",
    "supports_entry_similarity_storage",
]
