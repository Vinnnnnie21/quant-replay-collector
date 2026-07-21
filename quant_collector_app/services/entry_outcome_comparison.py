from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import hashlib
import uuid
from typing import Any, Callable

try:
    from market_data.types import interval_to_ms
    from research.cancellation import raise_if_research_cancelled
    from research.entry_context_features import (
        ENTRY_STRUCTURAL_FEATURE_VERSION,
        EntryStructuralFeatureSnapshot,
    )
    from research.entry_outcome_comparison import (
        ENTRY_MATCH_SENSITIVITY_THRESHOLDS,
        ENTRY_OUTCOME_FORMULA_VERSION,
        EntryDecisionForComparison,
        EntryOutcomeComparisonResult,
        EntryOutcomePath,
        EntryOutcomeThresholdResult,
        EntryPairSimilarity,
        OutcomeBar,
        build_entry_outcome_matrix,
        calculate_entry_outcome_path,
        global_match_entry_reject,
    )
    from research.entry_similarity import compare_entry_structural_snapshot_sets
    from services.entry_structural_similarity import (
        feature_snapshot_fingerprint,
        load_entry_structural_snapshots,
    )
except ImportError:  # pragma: no cover - package import path
    from ..market_data.types import interval_to_ms
    from ..research.cancellation import raise_if_research_cancelled
    from ..research.entry_context_features import (
        ENTRY_STRUCTURAL_FEATURE_VERSION,
        EntryStructuralFeatureSnapshot,
    )
    from ..research.entry_outcome_comparison import (
        ENTRY_MATCH_SENSITIVITY_THRESHOLDS,
        ENTRY_OUTCOME_FORMULA_VERSION,
        EntryDecisionForComparison,
        EntryOutcomeComparisonResult,
        EntryOutcomePath,
        EntryOutcomeThresholdResult,
        EntryPairSimilarity,
        OutcomeBar,
        build_entry_outcome_matrix,
        calculate_entry_outcome_path,
        global_match_entry_reject,
    )
    from ..research.entry_similarity import (
        compare_entry_structural_snapshot_sets,
    )
    from .entry_structural_similarity import (
        feature_snapshot_fingerprint,
        load_entry_structural_snapshots,
    )


_STORAGE_METHODS = (
    "fetch_klines_for_range",
    "get_entry_outcome_result",
    "get_episode_grouping",
    "get_setup_version",
    "list_entry_outcome_events",
    "save_entry_outcome_result",
)


def supports_entry_outcome_storage(storage: Any) -> bool:
    return storage is not None and all(
        callable(getattr(storage, method, None)) for method in _STORAGE_METHODS
    )


class EntryOutcomeComparisonService:
    """Build one audited comparison without exposing outcomes to matching."""

    def __init__(
        self,
        storage: Any,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not supports_entry_outcome_storage(storage):
            raise TypeError(
                "storage does not implement the entry outcome comparison contract"
            )
        self._storage = storage
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (
            lambda: "entry_outcome_" + uuid.uuid4().hex
        )

    def run(
        self,
        *,
        setup_version_id: str,
        grouping_version_id: str,
        direction: str,
        random_seed: int,
        cancelled: Callable[[], bool] | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> EntryOutcomeComparisonResult:
        normalized_direction = _direction(direction)
        setup = self._storage.get_setup_version(_required(setup_version_id))
        if setup is None:
            raise KeyError(f"Unknown Setup version: {setup_version_id}")
        if setup.direction.value != normalized_direction:
            raise ValueError("comparison direction does not match the Setup version")
        if self._storage.get_episode_grouping(
            _required(grouping_version_id)
        ) is None:
            raise KeyError(f"Unknown episode grouping: {grouping_version_id}")
        rows = self._storage.list_entry_outcome_events(
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping_version_id,
            direction=normalized_direction,
        )
        decisions = tuple(_decision(row) for row in rows)
        expected_timeframes = setup.timeframes.as_tuple()
        for row in rows:
            actual_timeframes = (
                str(row["decision_timeframe"]),
                str(row["context_timeframe_one"]),
                str(row["context_timeframe_two"]),
            )
            if actual_timeframes != expected_timeframes:
                raise ValueError(
                    "decision event timeframe profile does not match the Setup version"
                )
        by_id = {item.decision_event_id: item for item in decisions}
        strata_counts = Counter(
            (item.symbol, item.decision_timeframe, item.label)
            for item in decisions
        )
        total_pairs = sum(
            count * strata_counts.get((symbol, timeframe, "REJECT"), 0)
            for (symbol, timeframe, label), count in strata_counts.items()
            if label == "ENTRY"
        )
        total_work = len(rows) + total_pairs + len(rows)
        completed = 0
        snapshots = {}
        for row in rows:
            raise_if_research_cancelled(cancelled)
            snapshots[str(row["decision_event_id"])] = (
                load_entry_structural_snapshots(
                    self._storage,
                    row,
                    expected_timeframes,
                )
            )
            completed += 1
            _progress(progress, completed, total_work)
        input_feature_fingerprint = _input_feature_fingerprint(snapshots)

        # This entire score table is frozen before a single post-cutoff bar is
        # read. Matching therefore cannot depend on returns, MFE or MAE.
        pair_similarities = []
        entries = tuple(item for item in decisions if item.label == "ENTRY")
        rejects = tuple(item for item in decisions if item.label == "REJECT")
        for entry in entries:
            for reject in rejects:
                if (entry.symbol, entry.decision_timeframe) != (
                    reject.symbol,
                    reject.decision_timeframe,
                ):
                    continue
                raise_if_research_cancelled(cancelled)
                comparison = compare_entry_structural_snapshot_sets(
                    snapshots[entry.decision_event_id],
                    snapshots[reject.decision_event_id],
                    left_cutoff_utc_ms=entry.decision_cutoff_utc_ms,
                    right_cutoff_utc_ms=reject.decision_cutoff_utc_ms,
                )
                if comparison.aggregate is not None:
                    pair_similarities.append(
                        EntryPairSimilarity(
                            entry.decision_event_id,
                            reject.decision_event_id,
                            comparison.aggregate.similarity,
                        )
                    )
                completed += 1
                _progress(progress, completed, total_work)

        matches_by_threshold = tuple(
            (
                threshold,
                global_match_entry_reject(
                    decisions,
                    pair_similarities,
                    similarity_threshold=threshold,
                ),
            )
            for threshold in ENTRY_MATCH_SENSITIVITY_THRESHOLDS
        )
        matched_ids = {
            event_id
            for _threshold, pairs in matches_by_threshold
            for pair in pairs
            for event_id in (
                pair.entry_decision_event_id,
                pair.reject_decision_event_id,
            )
        }
        outcomes_by_event = {}
        for row in rows:
            event_id = str(row["decision_event_id"])
            if event_id in matched_ids:
                outcomes_by_event[event_id] = self._load_outcome_path(
                    by_id[event_id],
                    cancelled=cancelled,
                )
            completed += 1
            _progress(progress, completed, total_work)
        sensitivities = tuple(
            EntryOutcomeThresholdResult(
                similarity_threshold=threshold,
                pairs=pairs,
                matrix=build_entry_outcome_matrix(
                    pairs,
                    outcomes_by_event,
                    random_seed=int(random_seed),
                    cancelled=cancelled,
                ),
            )
            for threshold, pairs in matches_by_threshold
        )
        raise_if_research_cancelled(cancelled)
        result = EntryOutcomeComparisonResult(
            comparison_id=_required(self._id_factory()),
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping_version_id,
            direction=normalized_direction,
            formula_version=ENTRY_OUTCOME_FORMULA_VERSION,
            feature_version=ENTRY_STRUCTURAL_FEATURE_VERSION,
            random_seed=int(random_seed),
            eligible_decisions=decisions,
            input_feature_fingerprint=input_feature_fingerprint,
            sensitivities=sensitivities,
            created_at=_iso_utc(self._clock()),
        )
        self._storage.save_entry_outcome_result(result)
        return result

    def get_result(
        self,
        comparison_id: str,
    ) -> EntryOutcomeComparisonResult | None:
        return self._storage.get_entry_outcome_result(_required(comparison_id))

    def _load_outcome_path(
        self,
        decision: EntryDecisionForComparison,
        *,
        cancelled: Callable[[], bool] | None,
    ) -> EntryOutcomePath:
        interval_ms = interval_to_ms(decision.decision_timeframe)
        rows = self._storage.fetch_klines_for_range(
            symbol=decision.symbol,
            interval=decision.decision_timeframe,
            start_time_utc_ms=decision.decision_cutoff_utc_ms + 1,
            end_time_utc_ms=(
                decision.decision_cutoff_utc_ms + 1 + interval_ms * 19
            ),
            cancelled=cancelled,
        )
        raise_if_research_cancelled(cancelled)
        return calculate_entry_outcome_path(
            direction=decision.direction,
            decision_cutoff_utc_ms=decision.decision_cutoff_utc_ms,
            decision_interval_ms=interval_ms,
            bars=tuple(
                OutcomeBar(
                    open_time_utc_ms=int(row["open_time_utc_ms"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                )
                for row in rows
            ),
        )


def _decision(row: dict[str, Any]) -> EntryDecisionForComparison:
    return EntryDecisionForComparison(
        decision_event_id=str(row["decision_event_id"]),
        label=str(row["blind_label"]),
        setup_version_id=str(row["setup_version_id"]),
        grouping_version_id=str(row["grouping_version_id"]),
        episode_id=str(row["episode_id"]),
        symbol=str(row["symbol"]),
        direction=str(row["direction"]),
        decision_timeframe=str(row["decision_timeframe"]),
        decision_cutoff_utc_ms=int(row["decision_cutoff_utc_ms"]),
        blind_judgment_id=str(row["blind_judgment_id"]),
    )


def _required(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("research identifier must not be empty")
    return normalized


def _direction(value: str) -> str:
    normalized = _required(value).upper()
    if normalized not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    return normalized


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _progress(
    callback: Callable[[int, int], None] | None,
    completed: int,
    total: int,
) -> None:
    if callback is not None:
        callback(completed, total)


def _input_feature_fingerprint(
    snapshots_by_event: dict[
        str,
        tuple[EntryStructuralFeatureSnapshot, ...],
    ],
) -> str:
    rows = (
        f"{event_id}:{feature_snapshot_fingerprint(snapshots_by_event[event_id])}"
        for event_id in sorted(snapshots_by_event)
    )
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


__all__ = [
    "EntryOutcomeComparisonService",
    "supports_entry_outcome_storage",
]
