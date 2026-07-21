from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
import uuid
from typing import Any, Callable

try:
    from research.entry_blind_review import BlindBatchItem, BlindReviewBatch, ReviewStatus
    from research.candidate_retrieval import (
        StructuralPairEvaluation,
        StructuralReference,
        rank_structural_candidate,
        select_structural_candidate_batch,
    )
    from research.exit_candidate_generation import (
        ExitCandidateMaturity,
        ExitCandidateReference,
        ExitCandidateScanCancelled,
        ExitCandidateScanRequest,
        ExitCandidateScanResult,
        ExitCandidateScanStatus,
        ExitCandidateScore,
        FormalExitCandidateBatch,
        MAX_FORMAL_EXIT_BATCH_SIZE,
        REQUIRED_NEAREST_HOLDING_EPISODES,
    )
    from research.exit_similarity import (
        EXIT_SIMILARITY_FORMULA_VERSION,
        EXIT_STRUCTURAL_FEATURE_VERSION,
        compare_exit_structural_snapshot_sets,
    )
    from research.market_episodes import MarketEpisodeService
    from services.exit_structural_context import load_exit_structural_context
except ImportError:  # pragma: no cover - package import path
    from ..research.entry_blind_review import BlindBatchItem, BlindReviewBatch, ReviewStatus
    from ..research.candidate_retrieval import (
        StructuralPairEvaluation,
        StructuralReference,
        rank_structural_candidate,
        select_structural_candidate_batch,
    )
    from ..research.exit_candidate_generation import (
        ExitCandidateMaturity,
        ExitCandidateReference,
        ExitCandidateScanCancelled,
        ExitCandidateScanRequest,
        ExitCandidateScanResult,
        ExitCandidateScanStatus,
        ExitCandidateScore,
        FormalExitCandidateBatch,
        MAX_FORMAL_EXIT_BATCH_SIZE,
        REQUIRED_NEAREST_HOLDING_EPISODES,
    )
    from ..research.exit_similarity import (
        EXIT_SIMILARITY_FORMULA_VERSION,
        EXIT_STRUCTURAL_FEATURE_VERSION,
        compare_exit_structural_snapshot_sets,
    )
    from ..research.market_episodes import MarketEpisodeService
    from .exit_structural_context import load_exit_structural_context


_STORAGE_METHODS = (
    "get_episode_grouping",
    "get_setup_version",
    "fetch_klines_for_range",
    "list_confirmed_exit_candidate_references",
    "list_exit_candidate_observations",
    "get_exit_candidate_scan",
    "save_exit_candidate_scan",
    "create_exit_candidate_batch",
    "exclude_exit_candidate",
    "list_batched_exit_candidate_ids",
    "list_exit_candidate_exclusions",
)


def supports_exit_candidate_storage(storage: Any) -> bool:
    return storage is not None and all(
        callable(getattr(storage, method, None)) for method in _STORAGE_METHODS
    )


class ExitCandidateGenerationService:
    """Rank explicit open-position review points against confirmed exits."""

    def __init__(self, storage: Any) -> None:
        if not supports_exit_candidate_storage(storage):
            raise TypeError("storage does not implement the exit candidate contract")
        self._storage = storage
        self._episodes = MarketEpisodeService(storage)

    def scan(
        self,
        request: ExitCandidateScanRequest,
        *,
        cancelled: Callable[[], bool] | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> ExitCandidateScanResult:
        if not isinstance(request, ExitCandidateScanRequest):
            raise TypeError("request must be ExitCandidateScanRequest")
        setup = self._storage.get_setup_version(request.setup_version_id)
        if setup is None:
            raise KeyError(f"Unknown Setup version: {request.setup_version_id}")
        if setup.direction.value != request.direction:
            raise ValueError("candidate direction does not match the Setup version")
        self._episodes.get_grouping(request.grouping_version_id)
        _raise_if_cancelled(cancelled)
        reference_rows = self._confirmed_exit_now_rows(request)
        complete_references = []
        for row in reference_rows:
            _raise_if_cancelled(cancelled)
            prepared = self._prepare_event(row, setup.timeframes.as_tuple())
            if prepared is not None and self._is_complete(prepared):
                complete_references.append(prepared)
        maturity = ExitCandidateMaturity(
            complete_exit_now_count=len(complete_references),
            holding_episode_count=len(
                {
                    str(prepared[0]["trade_id"])
                    for prepared in complete_references
                }
            ),
        )
        ranked_references = tuple(
            StructuralReference(
                identity=str(prepared[0]["decision_event_id"]),
                episode_identity=str(prepared[0]["trade_id"]),
                payload=prepared,
            )
            for prepared in complete_references
        )
        candidate_rows = self._candidate_rows(request)
        _raise_if_cancelled(cancelled)
        if not maturity.ready:
            return self._publish(ExitCandidateScanResult(
                scan_id="exit_candidate_scan_" + uuid.uuid4().hex,
                setup_version_id=request.setup_version_id,
                grouping_version_id=request.grouping_version_id,
                direction=request.direction,
                formula_version=EXIT_SIMILARITY_FORMULA_VERSION,
                feature_version=EXIT_STRUCTURAL_FEATURE_VERSION,
                status=ExitCandidateScanStatus.NOT_READY,
                maturity=maturity,
                candidate_universe_count=len(candidate_rows),
                unavailable_candidate_count=0,
                candidates=(),
            ))
        scored = []
        unavailable = 0
        total = len(candidate_rows)
        for index, row in enumerate(candidate_rows, start=1):
            _raise_if_cancelled(cancelled)
            candidate = self._prepare_event(row, setup.timeframes.as_tuple())
            if candidate is None or not self._is_complete(candidate):
                unavailable += 1
            else:
                score = self._score_candidate(
                    candidate,
                    ranked_references,
                    cancelled=cancelled,
                )
                if score is None:
                    unavailable += 1
                else:
                    scored.append(score)
            if progress is not None:
                progress(index, total)
        _raise_if_cancelled(cancelled)
        return self._publish(ExitCandidateScanResult(
            scan_id="exit_candidate_scan_" + uuid.uuid4().hex,
            setup_version_id=request.setup_version_id,
            grouping_version_id=request.grouping_version_id,
            direction=request.direction,
            formula_version=EXIT_SIMILARITY_FORMULA_VERSION,
            feature_version=EXIT_STRUCTURAL_FEATURE_VERSION,
            status=ExitCandidateScanStatus.COMPLETED,
            maturity=maturity,
            candidate_universe_count=total,
            unavailable_candidate_count=unavailable,
            candidates=tuple(
                sorted(
                    scored,
                    key=lambda item: (-item.similarity, item.decision_event_id),
                )
            ),
        ))

    def get_scan(self, scan_id: str) -> ExitCandidateScanResult | None:
        row = self._storage.get_exit_candidate_scan(str(scan_id))
        if row is None:
            return None
        return _result_from_dict(json.loads(row["result_json"]))

    def create_blind_review_batch(
        self,
        *,
        scan_id: str,
        limit: int = MAX_FORMAL_EXIT_BATCH_SIZE,
    ) -> FormalExitCandidateBatch:
        scan = self.get_scan(scan_id)
        if scan is None:
            raise KeyError(f"Unknown exit candidate scan: {scan_id}")
        if scan.status is not ExitCandidateScanStatus.COMPLETED:
            raise ValueError("exit candidate scan is not ready for a formal batch")
        excluded = set(self._storage.list_exit_candidate_exclusions())
        used = set(
            self._storage.list_batched_exit_candidate_ids(
                setup_version_id=scan.setup_version_id,
                grouping_version_id=scan.grouping_version_id,
            )
        )
        eligible = tuple(
            candidate
            for candidate in scan.candidates
            if candidate.decision_event_id not in excluded
            and candidate.decision_event_id not in used
        )
        selections = select_structural_candidate_batch(
            eligible,
            identity=lambda item: item.decision_event_id,
            episode_identity=lambda item: item.holding_episode_id,
            similarity=lambda item: item.similarity,
            completeness=lambda item: item.completeness_ratio,
            reference_count=lambda item: len(item.references),
            diversity_vector=lambda item: item.diversity_vector,
            limit=limit,
            maximum_size=MAX_FORMAL_EXIT_BATCH_SIZE,
            required_reference_count=REQUIRED_NEAREST_HOLDING_EPISODES,
        )
        if not selections:
            raise ValueError("no eligible exit candidates remain for a formal batch")
        batch_id = "exit_batch_" + uuid.uuid4().hex
        created_at = datetime.now(UTC).isoformat(timespec="microseconds")
        items = tuple(
            {
                "blind_item_id": "exit_blind_item_"
                + hashlib.sha256(
                    f"{batch_id}|{selection.candidate.decision_event_id}".encode(
                        "utf-8"
                    )
                ).hexdigest()[:24],
                "decision_event_id": selection.candidate.decision_event_id,
                "display_order": index,
                "selection_reason": selection.selection_reason,
            }
            for index, selection in enumerate(selections)
        )
        high_count = sum(
            item["selection_reason"] == "HIGH_SIMILARITY" for item in items
        )
        diverse_count = sum(
            item["selection_reason"] == "STRUCTURAL_DIVERSITY" for item in items
        )
        self._storage.create_exit_candidate_batch(
            batch={
                "batch_id": batch_id,
                "scan_id": scan.scan_id,
                "setup_version_id": scan.setup_version_id,
                "grouping_version_id": scan.grouping_version_id,
                "high_similarity_count": high_count,
                "diverse_count": diverse_count,
                "created_at": created_at,
            },
            items=items,
        )
        batch = BlindReviewBatch(
            batch_id=batch_id,
            setup_version_id=scan.setup_version_id,
            grouping_version_id=scan.grouping_version_id,
            items=tuple(
                BlindBatchItem(
                    item["blind_item_id"],
                    ReviewStatus.PENDING_CONFIRMATION,
                )
                for item in items
            ),
        )
        return FormalExitCandidateBatch(batch, high_count, diverse_count)

    def reveal_candidate_in_free_browse(
        self,
        *,
        scan_id: str,
        decision_event_id: str,
    ) -> ExitCandidateScore:
        scan = self.get_scan(scan_id)
        if scan is None:
            raise KeyError(f"Unknown exit candidate scan: {scan_id}")
        event_id = str(decision_event_id)
        candidate = next(
            (
                item
                for item in scan.candidates
                if item.decision_event_id == event_id
            ),
            None,
        )
        if candidate is None:
            raise KeyError("Unknown exit candidate in scan")
        used = set(
            self._storage.list_batched_exit_candidate_ids(
                setup_version_id=scan.setup_version_id,
                grouping_version_id=scan.grouping_version_id,
            )
        )
        if event_id in used:
            raise PermissionError(
                "A formal blind-review candidate cannot be revealed in "
                "free browse"
            )
        self._storage.exclude_exit_candidate(
            {
                "setup_version_id": scan.setup_version_id,
                "grouping_version_id": scan.grouping_version_id,
                "decision_event_id": event_id,
                "reason": "FREE_BROWSE_REVEAL",
                "created_at": datetime.now(UTC).isoformat(
                    timespec="microseconds"
                ),
            }
        )
        return candidate

    def _publish(self, result: ExitCandidateScanResult) -> ExitCandidateScanResult:
        payload = json.dumps(
            asdict(result),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        self._storage.save_exit_candidate_scan(
            scan={
                "scan_id": result.scan_id,
                "setup_version_id": result.setup_version_id,
                "grouping_version_id": result.grouping_version_id,
                "direction": result.direction,
                "formula_version": result.formula_version,
                "feature_version": result.feature_version,
                "status": result.status.value,
                "result_json": payload,
                "created_at": datetime.now(UTC).isoformat(
                    timespec="microseconds"
                ),
            },
            candidates=(
                {
                    "decision_event_id": item.decision_event_id,
                    "holding_episode_id": item.holding_episode_id,
                    "similarity": item.similarity,
                    "completeness_ratio": item.completeness_ratio,
                    "references_json": json.dumps(
                        [asdict(reference) for reference in item.references],
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "diversity_vector_json": json.dumps(item.diversity_vector),
                    "enqueue_reason": item.enqueue_reason,
                }
                for item in result.candidates
            ),
        )
        return result

    def _candidate_rows(
        self,
        request: ExitCandidateScanRequest,
    ) -> tuple[dict[str, Any], ...]:
        return tuple(
            self._storage.list_exit_candidate_observations(
                setup_version_id=request.setup_version_id,
                grouping_version_id=request.grouping_version_id,
                direction=request.direction,
                limit=request.candidate_limit,
            )
        )

    def _prepare_event(
        self,
        event: dict[str, Any],
        intervals: tuple[str, str, str],
    ):
        try:
            market, state = load_exit_structural_context(
                self._storage,
                event,
                intervals,
            )
        except ValueError:
            return None
        return event, market, state

    @staticmethod
    def _is_complete(prepared) -> bool:
        event, market, state = prepared
        comparison = compare_exit_structural_snapshot_sets(
            market,
            market,
            left_position=state,
            right_position=state,
            left_cutoff_utc_ms=int(event["decision_cutoff_utc_ms"]),
            right_cutoff_utc_ms=int(event["decision_cutoff_utc_ms"]),
        )
        return comparison.aggregate is not None

    @staticmethod
    def _score_candidate(
        candidate,
        references,
        *,
        cancelled: Callable[[], bool] | None,
    ) -> ExitCandidateScore | None:
        event, market, state = candidate
        ranked = rank_structural_candidate(
            references,
            evaluate=lambda reference: _exit_pair_evaluation(
                event,
                market,
                state,
                reference,
            ),
            cancelled=cancelled,
            cancellation_error=lambda: ExitCandidateScanCancelled(
                "exit candidate scan cancelled at a safe boundary"
            ),
            required_reference_count=REQUIRED_NEAREST_HOLDING_EPISODES,
        )
        if ranked is None:
            return None
        references_result = tuple(
            ExitCandidateReference(
                item.identity,
                item.episode_identity,
                item.similarity,
            )
            for item in ranked.references
        )
        return ExitCandidateScore(
            decision_event_id=str(event["decision_event_id"]),
            holding_episode_id=str(event["trade_id"]),
            similarity=ranked.similarity,
            references=references_result,
            completeness_ratio=1.0,
            diversity_vector=ranked.diversity_vector,
        )

    def _confirmed_exit_now_rows(
        self,
        request: ExitCandidateScanRequest,
    ) -> tuple[dict[str, Any], ...]:
        return tuple(
            self._storage.list_confirmed_exit_candidate_references(
                setup_version_id=request.setup_version_id,
                grouping_version_id=request.grouping_version_id,
                direction=request.direction,
            )
        )


def _raise_if_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise ExitCandidateScanCancelled(
            "exit candidate scan cancelled at a safe boundary"
        )


def _exit_pair_evaluation(
    event,
    market,
    state,
    reference,
) -> StructuralPairEvaluation | None:
    reference_event, reference_market, reference_state = reference
    comparison = compare_exit_structural_snapshot_sets(
        market,
        reference_market,
        left_position=state,
        right_position=reference_state,
        left_cutoff_utc_ms=int(event["decision_cutoff_utc_ms"]),
        right_cutoff_utc_ms=int(reference_event["decision_cutoff_utc_ms"]),
    )
    if comparison.aggregate is None:
        return None
    vector = tuple(
        float(group.distance)
        for timeframe in comparison.timeframes
        for group in timeframe.groups
        if group.distance is not None
    ) + (float(comparison.position_distance),)
    return StructuralPairEvaluation(comparison.aggregate.similarity, vector)


def _result_from_dict(value: dict[str, Any]) -> ExitCandidateScanResult:
    maturity = ExitCandidateMaturity(**value["maturity"])
    return ExitCandidateScanResult(
        scan_id=value["scan_id"],
        setup_version_id=value["setup_version_id"],
        grouping_version_id=value["grouping_version_id"],
        direction=value["direction"],
        formula_version=value["formula_version"],
        feature_version=value["feature_version"],
        status=ExitCandidateScanStatus(value["status"]),
        maturity=maturity,
        candidate_universe_count=int(value["candidate_universe_count"]),
        unavailable_candidate_count=int(value["unavailable_candidate_count"]),
        candidates=tuple(
            ExitCandidateScore(
                decision_event_id=item["decision_event_id"],
                holding_episode_id=item["holding_episode_id"],
                similarity=float(item["similarity"]),
                references=tuple(
                    ExitCandidateReference(
                        decision_event_id=reference["decision_event_id"],
                        holding_episode_id=reference["holding_episode_id"],
                        similarity=float(reference["similarity"]),
                    )
                    for reference in item["references"]
                ),
                completeness_ratio=float(item["completeness_ratio"]),
                diversity_vector=tuple(item["diversity_vector"]),
                enqueue_reason=item["enqueue_reason"],
            )
            for item in value["candidates"]
        ),
    )


__all__ = [
    "ExitCandidateGenerationService",
    "supports_exit_candidate_storage",
]
