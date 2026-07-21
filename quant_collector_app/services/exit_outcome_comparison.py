from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
import hashlib
import json
import uuid
from typing import Any, Callable

try:
    from market_data.types import interval_to_ms
    from research.cancellation import raise_if_research_cancelled
    from research.exit_outcome_comparison import (
        EXIT_MATCH_SENSITIVITY_THRESHOLDS,
        EXIT_OUTCOME_FORMULA_VERSION,
        ExitDecisionForComparison,
        ExitOutcomeComparisonResult,
        ExitOutcomeThresholdResult,
        ExitPairSimilarity,
        OutcomeBar,
        build_exit_outcome_matrix,
        calculate_exit_outcome_path,
        global_match_exit_hold,
    )
    from research.exit_similarity import (
        EXIT_STRUCTURAL_FEATURE_VERSION,
        compare_exit_structural_snapshot_sets,
    )
    from services.exit_structural_context import load_exit_structural_context
except ImportError:  # pragma: no cover - package import path
    from ..market_data.types import interval_to_ms
    from ..research.cancellation import raise_if_research_cancelled
    from ..research.exit_outcome_comparison import (
        EXIT_MATCH_SENSITIVITY_THRESHOLDS,
        EXIT_OUTCOME_FORMULA_VERSION,
        ExitDecisionForComparison,
        ExitOutcomeComparisonResult,
        ExitOutcomeThresholdResult,
        ExitPairSimilarity,
        OutcomeBar,
        build_exit_outcome_matrix,
        calculate_exit_outcome_path,
        global_match_exit_hold,
    )
    from ..research.exit_similarity import (
        EXIT_STRUCTURAL_FEATURE_VERSION,
        compare_exit_structural_snapshot_sets,
    )
    from .exit_structural_context import load_exit_structural_context


_STORAGE_METHODS = (
    "fetch_klines_for_range",
    "get_episode_grouping",
    "get_exit_outcome_result",
    "get_setup_version",
    "list_exit_outcome_events",
    "save_exit_outcome_result",
)


def supports_exit_outcome_storage(storage: Any) -> bool:
    return storage is not None and all(
        callable(getattr(storage, method, None)) for method in _STORAGE_METHODS
    )


class ExitOutcomeComparisonService:
    """Match exit judgments on cutoff-time structure, then join outcomes."""

    def __init__(
        self,
        storage: Any,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not supports_exit_outcome_storage(storage):
            raise TypeError(
                "storage does not implement the exit outcome comparison contract"
            )
        self._storage = storage
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (
            lambda: "exit_outcome_" + uuid.uuid4().hex
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
    ) -> ExitOutcomeComparisonResult:
        normalized_direction = _direction(direction)
        setup = self._storage.get_setup_version(_required(setup_version_id))
        if setup is None:
            raise KeyError(f"Unknown Setup version: {setup_version_id}")
        if setup.direction.value != normalized_direction:
            raise ValueError("comparison direction does not match the Setup version")
        grouping_id = _required(grouping_version_id)
        if self._storage.get_episode_grouping(grouping_id) is None:
            raise KeyError(f"Unknown episode grouping: {grouping_version_id}")
        rows = self._storage.list_exit_outcome_events(
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping_id,
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
        total_pairs = sum(
            1
            for exit_now in decisions
            for hold in decisions
            if exit_now.label == "EXIT_NOW"
            and hold.label == "HOLD"
            and (exit_now.symbol, exit_now.decision_timeframe)
            == (hold.symbol, hold.decision_timeframe)
        )
        total_work = len(rows) + total_pairs + len(rows)
        completed = 0
        contexts = {}
        for row in rows:
            raise_if_research_cancelled(cancelled)
            contexts[str(row["decision_event_id"])] = load_exit_structural_context(
                self._storage,
                row,
                expected_timeframes,
            )
            completed += 1
            _progress(progress, completed, total_work)
        fingerprint = _input_feature_fingerprint(contexts)

        # Freeze the complete distance table before reading any post-cutoff bar.
        pair_similarities = []
        exit_now_decisions = tuple(
            item for item in decisions if item.label == "EXIT_NOW"
        )
        hold_decisions = tuple(item for item in decisions if item.label == "HOLD")
        for exit_now in exit_now_decisions:
            for hold in hold_decisions:
                if (exit_now.symbol, exit_now.decision_timeframe) != (
                    hold.symbol,
                    hold.decision_timeframe,
                ):
                    continue
                raise_if_research_cancelled(cancelled)
                exit_market, exit_position = contexts[
                    exit_now.decision_event_id
                ]
                hold_market, hold_position = contexts[hold.decision_event_id]
                comparison = compare_exit_structural_snapshot_sets(
                    exit_market,
                    hold_market,
                    left_position=exit_position,
                    right_position=hold_position,
                    left_cutoff_utc_ms=exit_now.decision_cutoff_utc_ms,
                    right_cutoff_utc_ms=hold.decision_cutoff_utc_ms,
                )
                if comparison.aggregate is not None:
                    pair_similarities.append(
                        ExitPairSimilarity(
                            exit_now.decision_event_id,
                            hold.decision_event_id,
                            comparison.aggregate.similarity,
                        )
                    )
                completed += 1
                _progress(progress, completed, total_work)
        matches_by_threshold = tuple(
            (
                threshold,
                global_match_exit_hold(
                    decisions,
                    pair_similarities,
                    similarity_threshold=threshold,
                ),
            )
            for threshold in EXIT_MATCH_SENSITIVITY_THRESHOLDS
        )
        matched_ids = {
            event_id
            for _threshold, pairs in matches_by_threshold
            for pair in pairs
            for event_id in (
                pair.exit_now_decision_event_id,
                pair.hold_decision_event_id,
            )
        }
        decision_by_id = {item.decision_event_id: item for item in decisions}
        outcomes_by_event = {}
        for row in rows:
            event_id = str(row["decision_event_id"])
            if event_id in matched_ids:
                outcomes_by_event[event_id] = self._load_outcome_path(
                    decision_by_id[event_id],
                    cancelled=cancelled,
                )
            completed += 1
            _progress(progress, completed, total_work)
        sensitivities = tuple(
            ExitOutcomeThresholdResult(
                similarity_threshold=threshold,
                pairs=pairs,
                matrix=build_exit_outcome_matrix(
                    pairs,
                    outcomes_by_event,
                    random_seed=int(random_seed),
                    cancelled=cancelled,
                ),
            )
            for threshold, pairs in matches_by_threshold
        )
        raise_if_research_cancelled(cancelled)
        result = ExitOutcomeComparisonResult(
            comparison_id=_required(self._id_factory()),
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping_id,
            direction=normalized_direction,
            formula_version=EXIT_OUTCOME_FORMULA_VERSION,
            feature_version=EXIT_STRUCTURAL_FEATURE_VERSION,
            random_seed=int(random_seed),
            eligible_decisions=decisions,
            input_feature_fingerprint=fingerprint,
            sensitivities=sensitivities,
            created_at=_iso_utc(self._clock()),
        )
        self._storage.save_exit_outcome_result(result)
        return result

    def get_result(self, comparison_id: str) -> ExitOutcomeComparisonResult | None:
        return self._storage.get_exit_outcome_result(_required(comparison_id))

    def _load_outcome_path(
        self,
        decision: ExitDecisionForComparison,
        *,
        cancelled: Callable[[], bool] | None,
    ):
        interval_ms = interval_to_ms(decision.decision_timeframe)
        rows = self._storage.fetch_klines_for_range(
            symbol=decision.symbol,
            interval=decision.decision_timeframe,
            start_time_utc_ms=decision.decision_cutoff_utc_ms + 1,
            end_time_utc_ms=decision.decision_cutoff_utc_ms + 1 + interval_ms * 19,
            cancelled=cancelled,
        )
        raise_if_research_cancelled(cancelled)
        return calculate_exit_outcome_path(
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


def _decision(row: dict[str, Any]) -> ExitDecisionForComparison:
    return ExitDecisionForComparison(
        decision_event_id=str(row["decision_event_id"]),
        label=str(row["blind_label"]),
        setup_version_id=str(row["setup_version_id"]),
        grouping_version_id=str(row["grouping_version_id"]),
        episode_id=str(row["episode_id"]),
        trade_id=str(row["trade_id"]),
        symbol=str(row["symbol"]),
        direction=str(row["direction"]),
        decision_timeframe=str(row["decision_timeframe"]),
        decision_cutoff_utc_ms=int(row["decision_cutoff_utc_ms"]),
        blind_judgment_id=str(row["blind_judgment_id"]),
    )


def _input_feature_fingerprint(contexts: dict[str, tuple[Any, Any]]) -> str:
    rows = []
    for event_id in sorted(contexts):
        market, position = contexts[event_id]
        rows.append(
            {
                "decision_event_id": event_id,
                "market": _json_value(market),
                "position": _json_value(position),
            }
        )
    payload = json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_value(value: Any):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if hasattr(value, "__dict__"):
        return {
            str(key): _json_value(item)
            for key, item in vars(value).items()
        }
    return value


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


def _progress(callback, completed: int, total: int) -> None:
    if callback is not None:
        callback(completed, total)


__all__ = [
    "ExitOutcomeComparisonService",
    "supports_exit_outcome_storage",
]
