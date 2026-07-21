from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Sequence
import uuid

try:
    from app_config import APP_VERSION
    from research.entry_behavior_model import (
        BehaviorModelTarget,
        BehaviorModelVersion,
        BehaviorTrainingRequest,
        BehaviorTrainingResult,
        BehaviorTrainingSample,
        LeaveEpisodeOutSimilarity,
        behavior_model_profile,
        entry_behavior_label_fingerprint,
        extract_entry_behavior_features,
    )
    from research.entry_similarity import (
        compare_entry_structural_snapshot_sets,
    )
    from research.exit_behavior_features import (
        ExitPositionStateSnapshot,
        build_exit_position_state,
        exit_position_state_distance,
        extract_exit_behavior_features,
    )
    from research.entry_context_features import EntryStructuralFeatureSnapshot
    from services.entry_structural_similarity import (
        load_entry_structural_snapshots,
    )
except ImportError:  # pragma: no cover - package import path
    from ..app_config import APP_VERSION
    from ..research.entry_behavior_model import (
        BehaviorModelTarget,
        BehaviorModelVersion,
        BehaviorTrainingRequest,
        BehaviorTrainingResult,
        BehaviorTrainingSample,
        LeaveEpisodeOutSimilarity,
        behavior_model_profile,
        entry_behavior_label_fingerprint,
        extract_entry_behavior_features,
    )
    from ..research.entry_similarity import (
        compare_entry_structural_snapshot_sets,
    )
    from ..research.exit_behavior_features import (
        ExitPositionStateSnapshot,
        build_exit_position_state,
        exit_position_state_distance,
        extract_exit_behavior_features,
    )
    from ..research.entry_context_features import (
        EntryStructuralFeatureSnapshot,
    )
    from .entry_structural_similarity import load_entry_structural_snapshots


_STORAGE_METHODS = (
    "fetch_klines_for_range",
    "get_behavior_model_version",
    "get_behavior_training_result",
    "get_episode_grouping",
    "get_setup_version",
    "list_behavior_model_versions",
    "list_behavior_training_events",
    "save_behavior_training_result",
)


class EntryBehaviorTrainingCancelled(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EntryBehaviorModelFreshness:
    model_version_id: str
    needs_retraining: bool
    trained_label_count: int
    current_label_count: int
    new_label_count: int
    message_zh: str


@dataclass(frozen=True, slots=True)
class _BehaviorTrainingObservation:
    sample: BehaviorTrainingSample
    market_snapshots: tuple[EntryStructuralFeatureSnapshot, ...]
    position_state: ExitPositionStateSnapshot | None


def supports_behavior_training_storage(storage: Any) -> bool:
    return storage is not None and all(
        callable(getattr(storage, method, None))
        for method in _STORAGE_METHODS
    )


class BehaviorTrainingService:
    """Train and atomically publish one immutable decision-behavior snapshot."""

    def __init__(
        self,
        storage: Any,
        *,
        app_version: str = APP_VERSION,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not supports_behavior_training_storage(storage):
            raise TypeError(
                "storage does not implement the behavior training contract"
            )
        self._storage = storage
        self._app_version = str(app_version or APP_VERSION)
        self._clock = clock or (lambda: datetime.now(UTC))

    def train(
        self,
        request: BehaviorTrainingRequest,
        *,
        cancelled: Callable[[], bool] | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> BehaviorTrainingResult:
        try:
            from startup import mark_startup_stage
        except ImportError:  # pragma: no cover - package import path
            from ..startup import mark_startup_stage
        mark_startup_stage("heavy_research_dependencies_load_start")
        try:
            from research.entry_behavior_training import (
                failed_behavior_training_result,
                fit_behavior_model,
            )
        except ImportError:  # pragma: no cover - package import path
            from ..research.entry_behavior_training import (
                failed_behavior_training_result,
                fit_behavior_model,
            )
        mark_startup_stage(
            "heavy_research_dependencies_load_end",
            flush=True,
        )
        if not isinstance(request, BehaviorTrainingRequest):
            raise TypeError("request must be BehaviorTrainingRequest")
        setup = self._storage.get_setup_version(request.setup_version_id)
        if setup is None:
            raise KeyError(f"Unknown Setup version: {request.setup_version_id}")
        if setup.direction.value != request.direction:
            raise ValueError("training direction does not match the Setup version")
        if self._storage.get_episode_grouping(
            request.grouping_version_id
        ) is None:
            raise KeyError(
                f"Unknown episode grouping: {request.grouping_version_id}"
            )
        rows = self._storage.list_behavior_training_events(
            target=request.target,
            setup_version_id=request.setup_version_id,
            grouping_version_id=request.grouping_version_id,
            direction=request.direction,
        )
        created_at = _iso_utc(self._clock())
        prefix = (
            "entry"
            if request.target is BehaviorModelTarget.ENTRY_SELECTION
            else "exit"
        )
        experiment_id = f"{prefix}_behavior_experiment_" + uuid.uuid4().hex
        model_version_id = f"{prefix}_behavior_model_" + uuid.uuid4().hex
        samples: list[BehaviorTrainingSample] = []
        samples_with_snapshots = []
        total = len(rows)
        for index, row in enumerate(rows, start=1):
            _raise_if_cancelled(cancelled)
            snapshots = load_entry_structural_snapshots(
                self._storage,
                row,
                setup.timeframes.as_tuple(),
            )
            position_state = None
            try:
                if request.target is BehaviorModelTarget.EXIT_SELECTION:
                    position_rows = _load_exit_position_rows(
                        self._storage,
                        row,
                    )
                    position_state = build_exit_position_state(
                        position_rows,
                        direction=str(row["direction"]),
                        actual_entry_price=row["actual_entry_price"],
                        entry_atr20=row["entry_atr20"],
                        take_profit_status=row["take_profit_status"],
                        take_profit_price=row.get("take_profit_price"),
                        stop_loss_status=row["stop_loss_status"],
                        stop_loss_price=row.get("stop_loss_price"),
                    )
                    features = extract_exit_behavior_features(
                        snapshots,
                        position_state,
                    )
                else:
                    features = extract_entry_behavior_features(snapshots)
            except ValueError:
                result = failed_behavior_training_result(
                    request,
                    experiment_id=experiment_id,
                    created_at=created_at,
                    code="FEATURE_DATA_INCOMPLETE",
                    message_zh=(
                        "训练样本的截止点前行情指标不完整；请先补齐研究区间。"
                    ),
                )
                self._storage.save_behavior_training_result(result)
                return result
            sample = BehaviorTrainingSample(
                decision_event_id=str(row["decision_event_id"]),
                episode_id=_training_episode_id(row, request.target),
                decision_cutoff_utc_ms=int(row["decision_cutoff_utc_ms"]),
                label=str(row["blind_label"]),
                features=features,
            )
            samples.append(sample)
            samples_with_snapshots.append(
                _BehaviorTrainingObservation(
                    sample=sample,
                    market_snapshots=snapshots,
                    position_state=position_state,
                )
            )
            if progress is not None:
                progress(index, total)
        try:
            result = fit_behavior_model(
                samples,
                request=request,
                app_version=self._app_version,
                experiment_id=experiment_id,
                model_version_id=model_version_id,
                created_at=created_at,
                cancelled=cancelled,
                leave_episode_out_scores=_leave_episode_out_scores(
                    samples_with_snapshots,
                    target=request.target,
                    cancelled=cancelled,
                ),
            )
        except InterruptedError as exc:
            raise EntryBehaviorTrainingCancelled(str(exc)) from exc
        _raise_if_cancelled(cancelled)
        self._storage.save_behavior_training_result(result)
        return result

    def get_result(
        self,
        experiment_id: str,
        *,
        target: BehaviorModelTarget = BehaviorModelTarget.ENTRY_SELECTION,
    ) -> BehaviorTrainingResult | None:
        return self._storage.get_behavior_training_result(
            str(experiment_id),
            target=target,
        )

    def get_model(
        self,
        model_version_id: str,
        *,
        target: BehaviorModelTarget = BehaviorModelTarget.ENTRY_SELECTION,
    ) -> BehaviorModelVersion | None:
        return self._storage.get_behavior_model_version(
            str(model_version_id),
            target=target,
        )

    def list_models(
        self,
        *,
        target: BehaviorModelTarget = BehaviorModelTarget.ENTRY_SELECTION,
        setup_version_id: str,
        grouping_version_id: str,
        direction: str,
    ) -> tuple[BehaviorModelVersion, ...]:
        return self._storage.list_behavior_model_versions(
            target=target,
            setup_version_id=str(setup_version_id),
            grouping_version_id=str(grouping_version_id),
            direction=str(direction).upper(),
        )

    def model_freshness(
        self,
        model_version_id: str,
        *,
        target: BehaviorModelTarget = BehaviorModelTarget.ENTRY_SELECTION,
    ) -> EntryBehaviorModelFreshness:
        model = self.get_model(model_version_id, target=target)
        if model is None:
            raise KeyError(f"Unknown behavior model: {model_version_id}")
        rows = self._storage.list_behavior_training_events(
            target=model.target,
            setup_version_id=model.setup_version_id,
            grouping_version_id=model.grouping_version_id,
            direction=model.direction,
        )
        fingerprint = entry_behavior_label_fingerprint(
            tuple(
                (
                    str(row["decision_event_id"]),
                    _training_episode_id(row, model.target),
                    int(row["decision_cutoff_utc_ms"]),
                    str(row["blind_label"]),
                )
                for row in rows
            )
        )
        trained_count = len(model.manifest.sample_ids)
        current_count = len(rows)
        needs_retraining = (
            fingerprint != model.manifest.label_fingerprint
        )
        return EntryBehaviorModelFreshness(
            model_version_id=model.model_version_id,
            needs_retraining=needs_retraining,
            trained_label_count=trained_count,
            current_label_count=current_count,
            new_label_count=max(0, current_count - trained_count),
            message_zh=(
                "有新的合格盲态标签；旧模型保持不变，可由用户发起新训练。"
                if needs_retraining
                else "模型已包含当前全部合格盲态标签。"
            ),
        )


def _raise_if_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise EntryBehaviorTrainingCancelled(
            "behavior-model training cancelled at a safe boundary"
        )


def _training_episode_id(
    row: dict[str, Any],
    target: BehaviorModelTarget,
) -> str:
    field_name = (
        "episode_id"
        if target is BehaviorModelTarget.ENTRY_SELECTION
        else "holding_episode_id"
    )
    episode_id = str(row.get(field_name) or "").strip()
    if not episode_id:
        raise ValueError(f"behavior training row is missing {field_name}")
    return episode_id


def _load_exit_position_rows(
    storage: Any,
    row: dict[str, Any],
) -> list[dict[str, Any]]:
    entry_time_value = row.get("entry_real_time_bjt") or row.get(
        "entry_bar_time_bjt"
    )
    if not entry_time_value:
        raise ValueError("平仓训练样本缺少实际开仓时间。")
    entry_time = datetime.fromisoformat(str(entry_time_value))
    if entry_time.tzinfo is None or entry_time.utcoffset() is None:
        raise ValueError("平仓训练样本的实际开仓时间必须包含时区。")
    return storage.fetch_klines_for_range(
        symbol=str(row["symbol"]),
        interval=str(row["decision_timeframe"]),
        start_time_utc_ms=int(entry_time.timestamp() * 1_000),
        end_time_utc_ms=int(row["decision_cutoff_utc_ms"]) - 1,
    )


def _leave_episode_out_scores(
    observations: Sequence[_BehaviorTrainingObservation],
    *,
    target: BehaviorModelTarget,
    cancelled: Callable[[], bool] | None,
) -> tuple[LeaveEpisodeOutSimilarity, ...]:
    profile = behavior_model_profile(target)
    positives = tuple(
        observation
        for observation in observations
        if observation.sample.label == profile.positive_label
    )
    if len({item.sample.episode_id for item in positives}) < 10:
        return ()
    nearest_by_sample: dict[str, dict[str, float]] = {
        item.sample.decision_event_id: {} for item in positives
    }
    for left_index, left_item in enumerate(positives):
        left = left_item.sample
        for right_index in range(left_index + 1, len(positives)):
            right_item = positives[right_index]
            right = right_item.sample
            if right.episode_id == left.episode_id:
                continue
            _raise_if_cancelled(cancelled)
            comparison = compare_entry_structural_snapshot_sets(
                left_item.market_snapshots,
                right_item.market_snapshots,
                left_cutoff_utc_ms=left.decision_cutoff_utc_ms,
                right_cutoff_utc_ms=right.decision_cutoff_utc_ms,
            )
            if comparison.aggregate is None:
                continue
            if target is BehaviorModelTarget.EXIT_SELECTION:
                if (
                    left_item.position_state is None
                    or right_item.position_state is None
                ):
                    continue
                position_distance = exit_position_state_distance(
                    left_item.position_state,
                    right_item.position_state,
                )
                total_distance = (
                    0.50 * comparison.aggregate.market_distance
                    + 0.40 * position_distance
                    + 0.10 * comparison.aggregate.calendar_distance
                )
                similarity = 100.0 * (1.0 - total_distance)
            else:
                similarity = comparison.aggregate.similarity
            _retain_top_episode_score(
                nearest_by_sample[left.decision_event_id],
                right.episode_id,
                similarity,
            )
            _retain_top_episode_score(
                nearest_by_sample[right.decision_event_id],
                left.episode_id,
                similarity,
            )
    scores = []
    for observation in positives:
        sample = observation.sample
        nearest = sorted(
            nearest_by_sample[sample.decision_event_id].items(),
            key=lambda item: (-item[1], item[0]),
        )[:3]
        if len(nearest) == 3:
            scores.append(
                LeaveEpisodeOutSimilarity(
                    decision_event_id=sample.decision_event_id,
                    episode_id=sample.episode_id,
                    reference_episode_ids=tuple(
                        episode_id for episode_id, _score in nearest
                    ),
                    similarity=(
                        sum(score for _episode_id, score in nearest) / 3.0
                    ),
                )
            )
    return tuple(scores)


def _retain_top_episode_score(
    scores: dict[str, float],
    episode_id: str,
    similarity: float,
) -> None:
    scores[episode_id] = max(
        float(similarity),
        scores.get(episode_id, -1.0),
    )
    if len(scores) <= 3:
        return
    retained = sorted(
        scores.items(),
        key=lambda item: (-item[1], item[0]),
    )[:3]
    scores.clear()
    scores.update(retained)


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("behavior training clock must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


__all__ = [
    "BehaviorTrainingService",
    "EntryBehaviorModelFreshness",
    "EntryBehaviorTrainingCancelled",
    "EntryBehaviorTrainingService",
    "supports_behavior_training_storage",
    "supports_entry_behavior_training_storage",
]


# Compatibility name retained for existing entry-model callers.
EntryBehaviorTrainingService = BehaviorTrainingService
supports_entry_behavior_training_storage = supports_behavior_training_storage
