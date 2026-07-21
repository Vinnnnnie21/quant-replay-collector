from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
import uuid
from typing import Any, Callable

try:
    from market_data.types import interval_to_ms
    from research.candidate_retrieval import (
        StructuralPairEvaluation,
        StructuralReference,
        rank_structural_candidate,
    )
    from research.entry_candidate_generation import (
        CandidateMaturity,
        CandidateReference,
        CandidateScanCancelled,
        CandidateScanRequest,
        CandidateScanResult,
        CandidateScanStatus,
        EntryCandidateScore,
        FormalCandidateBatch,
        select_formal_candidate_batch,
        REQUIRED_NEAREST_EPISODES,
    )
    from research.entry_context_features import (
        ENTRY_STRUCTURAL_FEATURE_VERSION,
        EntryStructuralFeatureSnapshot,
    )
    from research.entry_similarity import (
        ENTRY_SIMILARITY_FORMULA_VERSION,
        compare_entry_structural_snapshot_sets,
        structural_snapshot_set_is_complete,
    )
    from research.market_episodes import MarketEpisodeService
    from services.entry_structural_similarity import load_entry_structural_snapshots
except ImportError:  # pragma: no cover - package import path
    from ..market_data.types import interval_to_ms
    from ..research.candidate_retrieval import (
        StructuralPairEvaluation,
        StructuralReference,
        rank_structural_candidate,
    )
    from ..research.entry_candidate_generation import (
        CandidateMaturity,
        CandidateReference,
        CandidateScanCancelled,
        CandidateScanRequest,
        CandidateScanResult,
        CandidateScanStatus,
        EntryCandidateScore,
        FormalCandidateBatch,
        select_formal_candidate_batch,
        REQUIRED_NEAREST_EPISODES,
    )
    from ..research.entry_context_features import (
        ENTRY_STRUCTURAL_FEATURE_VERSION,
        EntryStructuralFeatureSnapshot,
    )
    from ..research.entry_similarity import (
        ENTRY_SIMILARITY_FORMULA_VERSION,
        compare_entry_structural_snapshot_sets,
        structural_snapshot_set_is_complete,
    )
    from ..research.market_episodes import MarketEpisodeService
    from .entry_structural_similarity import load_entry_structural_snapshots


_STORAGE_METHODS = (
    "fetch_klines_for_range",
    "get_setup_version",
    "get_episode_grouping",
    "list_entry_candidate_observations",
    "list_confirmed_entry_reference_events",
    "save_entry_candidate_scan",
    "get_entry_candidate_scan",
    "create_entry_candidate_batch",
    "exclude_entry_candidate",
    "list_entry_candidate_exclusions",
    "list_batched_entry_candidate_ids",
)


def supports_entry_candidate_storage(storage: Any) -> bool:
    return storage is not None and all(
        callable(getattr(storage, method, None)) for method in _STORAGE_METHODS
    )


class EntryCandidateGenerationService:
    """Scan a bounded persisted universe without exposing outcomes or random picks."""

    def __init__(self, storage: Any) -> None:
        if not supports_entry_candidate_storage(storage):
            raise TypeError("storage does not implement the entry candidate contract")
        self._storage = storage
        self._episodes = MarketEpisodeService(storage)

    def scan(
        self,
        request: CandidateScanRequest,
        *,
        cancelled: Callable[[], bool] | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> CandidateScanResult:
        if not isinstance(request, CandidateScanRequest):
            raise TypeError("request must be CandidateScanRequest")
        setup = self._storage.get_setup_version(request.setup_version_id)
        if setup is None:
            raise KeyError(f"Unknown Setup version: {request.setup_version_id}")
        if setup.direction.value != request.direction:
            raise ValueError("candidate direction does not match the Setup version")
        grouping = self._episodes.get_grouping(request.grouping_version_id)
        _raise_if_cancelled(cancelled)
        reference_rows = self._storage.list_confirmed_entry_reference_events(
            setup_version_id=request.setup_version_id,
            grouping_version_id=request.grouping_version_id,
            direction=request.direction,
        )
        complete_references = []
        for row in reference_rows:
            _raise_if_cancelled(cancelled)
            snapshots = load_entry_structural_snapshots(
                self._storage,
                row,
                setup.timeframes.as_tuple(),
            )
            if structural_snapshot_set_is_complete(snapshots):
                complete_references.append((row, snapshots))
        ranked_references = tuple(
            StructuralReference(
                identity=str(row["decision_event_id"]),
                episode_identity=str(row["episode_id"]),
                payload=(row, snapshots),
            )
            for row, snapshots in complete_references
        )
        maturity = CandidateMaturity(
            complete_entry_count=len(complete_references),
            entry_episode_count=len(
                {str(row["episode_id"]) for row, _snapshots in complete_references}
            ),
        )
        scan_id = _scan_id(request)
        candidates = self._storage.list_entry_candidate_observations(
            setup_version_id=request.setup_version_id,
            limit=request.candidate_limit,
        )
        if not maturity.ready:
            _raise_if_cancelled(cancelled)
            return self._publish(CandidateScanResult(
                scan_id=scan_id,
                setup_version_id=request.setup_version_id,
                grouping_version_id=request.grouping_version_id,
                direction=request.direction,
                formula_version=ENTRY_SIMILARITY_FORMULA_VERSION,
                feature_version=ENTRY_STRUCTURAL_FEATURE_VERSION,
                status=CandidateScanStatus.NOT_READY,
                maturity=maturity,
                candidate_universe_count=len(candidates),
                unavailable_candidate_count=0,
                candidates=(),
            ))
        candidate_assignments = self._episodes.resolve_episode_ids(
            grouping.grouping_version_id,
            tuple(str(row["sample_id"]) for row in candidates),
        ) if candidates else ()
        episode_by_sample = {
            assignment.sample_id: assignment.episode_id
            for assignment in candidate_assignments
        }
        scored: list[EntryCandidateScore] = []
        unavailable = 0
        total = len(candidates)
        for index, row in enumerate(candidates, start=1):
            _raise_if_cancelled(cancelled)
            cutoff_ms = _candidate_cutoff_ms(
                row,
                setup.timeframes.decision,
            )
            candidate_event = {
                "decision_event_id": str(row["sample_id"]),
                "symbol": str(row["symbol"]),
                "decision_cutoff_utc_ms": cutoff_ms,
            }
            candidate_snapshots = load_entry_structural_snapshots(
                self._storage,
                candidate_event,
                setup.timeframes.as_tuple(),
            )
            ranked = rank_structural_candidate(
                ranked_references,
                evaluate=lambda payload: _pair_evaluation(
                    candidate_event,
                    candidate_snapshots,
                    payload,
                ),
                cancelled=cancelled,
                cancellation_error=lambda: CandidateScanCancelled(
                    "entry candidate scan cancelled at a safe boundary"
                ),
                required_reference_count=REQUIRED_NEAREST_EPISODES,
            )
            if ranked is None:
                unavailable += 1
            else:
                references = tuple(
                    CandidateReference(
                        decision_event_id=item.identity,
                        episode_id=item.episode_identity,
                        similarity=item.similarity,
                    )
                    for item in ranked.references
                )
                scored.append(
                    EntryCandidateScore(
                        source_sample_id=str(row["sample_id"]),
                        episode_id=episode_by_sample[str(row["sample_id"])],
                        similarity=ranked.similarity,
                        references=references,
                        completeness_ratio=1.0,
                        diversity_vector=ranked.diversity_vector,
                    )
                )
            if progress is not None:
                progress(index, total)
        ordered = tuple(
            sorted(scored, key=lambda item: (-item.similarity, item.source_sample_id))
        )
        _raise_if_cancelled(cancelled)
        return self._publish(CandidateScanResult(
            scan_id=scan_id,
            setup_version_id=request.setup_version_id,
            grouping_version_id=request.grouping_version_id,
            direction=request.direction,
            formula_version=ENTRY_SIMILARITY_FORMULA_VERSION,
            feature_version=ENTRY_STRUCTURAL_FEATURE_VERSION,
            status=CandidateScanStatus.COMPLETED,
            maturity=maturity,
            candidate_universe_count=total,
            unavailable_candidate_count=unavailable,
            candidates=ordered,
        ))

    def get_scan(self, scan_id: str) -> CandidateScanResult | None:
        row = self._storage.get_entry_candidate_scan(str(scan_id))
        if row is None:
            return None
        return _result_from_dict(json.loads(row["result_json"]))

    def create_blind_review_batch(
        self,
        *,
        scan_id: str,
        limit: int = 20,
    ) -> FormalCandidateBatch:
        from research.entry_blind_review import BlindBatchItem, BlindReviewBatch, ReviewStatus

        size = int(limit)
        if size < 1 or size > 20:
            raise ValueError("formal candidate batch limit must be between 1 and 20")
        scan = self.get_scan(scan_id)
        if scan is None:
            raise KeyError(f"Unknown candidate scan: {scan_id}")
        if scan.status is not CandidateScanStatus.COMPLETED:
            raise ValueError("candidate scan is not ready for a formal batch")
        excluded = set(
            self._storage.list_entry_candidate_exclusions()
        )
        used = set(
            self._storage.list_batched_entry_candidate_ids(
                setup_version_id=scan.setup_version_id,
                grouping_version_id=scan.grouping_version_id,
            )
        )
        eligible = tuple(
            item for item in scan.candidates
            if item.source_sample_id not in excluded
            and item.source_sample_id not in used
        )
        selections = select_formal_candidate_batch(eligible, limit=size)
        if not selections:
            raise ValueError("no eligible candidates remain for a formal batch")
        selected = tuple(
            (item.candidate, item.selection_reason) for item in selections
        )
        observations = {
            str(row["sample_id"]): row
            for row in self._storage.list_entry_candidate_observations(
                setup_version_id=scan.setup_version_id,
                limit=10_000,
            )
        }
        setup = self._storage.get_setup_version(scan.setup_version_id)
        assert setup is not None
        created_at = datetime.now(UTC).isoformat(timespec="microseconds")
        batch_id = "entry_batch_" + uuid.uuid4().hex
        items = []
        for index, (candidate, reason) in enumerate(selected):
            observation = observations[candidate.source_sample_id]
            cutoff = _candidate_cutoff_ms(
                observation,
                setup.timeframes.decision,
            )
            event_id = "entry_decision_" + hashlib.sha256(
                f"{scan.scan_id}|{candidate.source_sample_id}".encode("utf-8")
            ).hexdigest()[:24]
            blind_id = "blind_item_" + hashlib.sha256(
                f"{batch_id}|{event_id}".encode("utf-8")
            ).hexdigest()[:24]
            items.append(
                {
                    "source_sample_id": candidate.source_sample_id,
                    "blind_item_id": blind_id,
                    "display_order": index,
                    "selection_reason": reason,
                    "event": {
                        "decision_event_id": event_id,
                        "source_sample_id": candidate.source_sample_id,
                        "setup_version_id": scan.setup_version_id,
                        "grouping_version_id": scan.grouping_version_id,
                        "episode_id": candidate.episode_id,
                        "session_id": observation.get("session_id"),
                        "symbol": observation["symbol"],
                        "direction": scan.direction,
                        "decision_timeframe": setup.timeframes.decision,
                        "context_timeframe_one": setup.timeframes.context_one,
                        "context_timeframe_two": setup.timeframes.context_two,
                        "decision_cutoff_utc_ms": cutoff,
                        "decision_bar_open_time_utc_ms": cutoff - interval_to_ms(setup.timeframes.decision),
                        "created_at": created_at,
                    },
                }
            )
        self._storage.create_entry_candidate_batch(
            batch={
                "batch_id": batch_id,
                "scan_id": scan.scan_id,
                "setup_version_id": scan.setup_version_id,
                "grouping_version_id": scan.grouping_version_id,
                "high_similarity_count": sum(item["selection_reason"] == "HIGH_SIMILARITY" for item in items),
                "diverse_count": sum(item["selection_reason"] == "STRUCTURAL_DIVERSITY" for item in items),
                "created_at": created_at,
            },
            items=items,
        )
        batch = BlindReviewBatch(
            batch_id=batch_id,
            setup_version_id=scan.setup_version_id,
            grouping_version_id=scan.grouping_version_id,
            items=tuple(
                BlindBatchItem(item["blind_item_id"], ReviewStatus.PENDING_CONFIRMATION)
                for item in items
            ),
        )
        return FormalCandidateBatch(
            batch=batch,
            high_similarity_count=sum(reason == "HIGH_SIMILARITY" for _candidate, reason in selected),
            diverse_count=sum(reason == "STRUCTURAL_DIVERSITY" for _candidate, reason in selected),
        )

    def reveal_candidate_in_free_browse(
        self,
        *,
        scan_id: str,
        source_sample_id: str,
    ) -> EntryCandidateScore:
        scan = self.get_scan(scan_id)
        if scan is None:
            raise KeyError(f"Unknown candidate scan: {scan_id}")
        candidate = next(
            (
                item for item in scan.candidates
                if item.source_sample_id == str(source_sample_id)
            ),
            None,
        )
        if candidate is None:
            raise KeyError("Unknown candidate in scan")
        self._storage.exclude_entry_candidate(
            {
                "setup_version_id": scan.setup_version_id,
                "grouping_version_id": scan.grouping_version_id,
                "source_sample_id": candidate.source_sample_id,
                "reason": "FREE_BROWSE_REVEAL",
                "created_at": datetime.now(UTC).isoformat(timespec="microseconds"),
            }
        )
        return candidate

    def _publish(self, result: CandidateScanResult) -> CandidateScanResult:
        payload = json.dumps(
            asdict(result),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        self._storage.save_entry_candidate_scan(
            scan={
                "scan_id": result.scan_id,
                "setup_version_id": result.setup_version_id,
                "grouping_version_id": result.grouping_version_id,
                "direction": result.direction,
                "formula_version": result.formula_version,
                "feature_version": result.feature_version,
                "status": result.status.value,
                "result_json": payload,
                "created_at": datetime.now(UTC).isoformat(timespec="microseconds"),
            },
            candidates=(
                {
                    "source_sample_id": item.source_sample_id,
                    "episode_id": item.episode_id,
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

def _pair_similarity(
    candidate_event: dict[str, Any],
    candidate_snapshots: tuple[EntryStructuralFeatureSnapshot, ...],
    reference_event: dict[str, Any],
    reference_snapshots: tuple[EntryStructuralFeatureSnapshot, ...],
) -> tuple[float, tuple[float, ...]] | None:
    comparison = compare_entry_structural_snapshot_sets(
        candidate_snapshots,
        reference_snapshots,
        left_cutoff_utc_ms=int(candidate_event["decision_cutoff_utc_ms"]),
        right_cutoff_utc_ms=int(reference_event["decision_cutoff_utc_ms"]),
    )
    if comparison.aggregate is None:
        return None
    vector = tuple(
        float(group.distance)
        for timeframe in comparison.timeframes
        for group in timeframe.groups
        if group.distance is not None
    )
    return comparison.aggregate.similarity, vector


def _pair_evaluation(
    candidate_event: dict[str, Any],
    candidate_snapshots: tuple[EntryStructuralFeatureSnapshot, ...],
    payload,
) -> StructuralPairEvaluation | None:
    reference_event, reference_snapshots = payload
    pair = _pair_similarity(
        candidate_event,
        candidate_snapshots,
        reference_event,
        reference_snapshots,
    )
    if pair is None:
        return None
    similarity, vector = pair
    return StructuralPairEvaluation(similarity, vector)


def _raise_if_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise CandidateScanCancelled("entry candidate scan cancelled at a safe boundary")


def _utc_ms(value: Any) -> int:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("candidate event_time_bjt must include an explicit timezone")
    return int(parsed.astimezone(UTC).timestamp() * 1_000)


def _candidate_cutoff_ms(
    observation: dict[str, Any],
    decision_interval: str,
) -> int:
    interval = str(observation.get("interval") or "")
    if interval != str(decision_interval):
        raise ValueError(
            "candidate interval does not match the Setup decision timeframe"
        )
    return _utc_ms(observation["event_time_bjt"]) + interval_to_ms(interval)


def _scan_id(request: CandidateScanRequest) -> str:
    return "entry_candidate_scan_" + uuid.uuid4().hex


def _result_from_dict(value: dict[str, Any]) -> CandidateScanResult:
    maturity_value = value["maturity"]
    return CandidateScanResult(
        scan_id=value["scan_id"],
        setup_version_id=value["setup_version_id"],
        grouping_version_id=value["grouping_version_id"],
        direction=value["direction"],
        formula_version=value["formula_version"],
        feature_version=value["feature_version"],
        status=CandidateScanStatus(value["status"]),
        maturity=CandidateMaturity(**maturity_value),
        candidate_universe_count=int(value["candidate_universe_count"]),
        unavailable_candidate_count=int(value["unavailable_candidate_count"]),
        candidates=tuple(
            EntryCandidateScore(
                source_sample_id=item["source_sample_id"],
                episode_id=item["episode_id"],
                similarity=float(item["similarity"]),
                references=tuple(
                    CandidateReference(
                        decision_event_id=reference["decision_event_id"],
                        episode_id=reference["episode_id"],
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
    "CandidateScanRequest",
    "CandidateScanStatus",
    "EntryCandidateGenerationService",
    "supports_entry_candidate_storage",
]
