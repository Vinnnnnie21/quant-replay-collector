from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
import hashlib
import json
from typing import Any, Sequence

try:
    from market_data.types import interval_to_ms
    from research.market_episodes import (
        EPISODE_FORMULA_VERSION,
        EpisodeAuditSummary,
        MarketEpisodeService,
        ResearchSampleWindow,
        TimeRange,
    )
    from research.research_snapshot import (
        HypothesisCard,
        HypothesisStatus,
        ResearchSnapshotContent,
        ResearchSnapshotInput,
        ResearchSnapshotVersions,
    )
    from app_config import APP_VERSION
except ImportError:  # pragma: no cover - package import path
    from ..market_data.types import interval_to_ms
    from ..research.market_episodes import (
        EPISODE_FORMULA_VERSION,
        EpisodeAuditSummary,
        MarketEpisodeService,
        ResearchSampleWindow,
        TimeRange,
    )
    from ..research.research_snapshot import (
        HypothesisCard,
        HypothesisStatus,
        ResearchSnapshotContent,
        ResearchSnapshotInput,
        ResearchSnapshotVersions,
    )
    from ..app_config import APP_VERSION


RESEARCH_MODES = ("entry", "exit")
FEATURE_LOOKBACK_BARS = 60
OUTCOME_HORIZON_BARS = 20
SNAPSHOT_RANDOM_SEED = 20260719
SNAPSHOT_FORMULA_VERSION = "decision-research-v1.6"
SNAPSHOT_FEATURE_VERSION = "decision-feature-v1.6"


@dataclass(frozen=True, slots=True)
class DecisionResearchRequest:
    session_id: str
    setup_version_id: str
    mode: str
    symbol: str
    timeframes: tuple[str, str, str]
    start_time_utc_ms: int
    end_time_utc_ms: int

    def __post_init__(self) -> None:
        for name in ("session_id", "setup_version_id", "symbol"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)
        mode = str(self.mode).strip().lower()
        if mode not in RESEARCH_MODES:
            raise ValueError(f"unsupported decision research mode: {mode}")
        object.__setattr__(self, "mode", mode)
        if len(self.timeframes) != 3:
            raise ValueError("decision research requires three timeframes")
        if int(self.end_time_utc_ms) < int(self.start_time_utc_ms):
            raise ValueError("research range end must not precede start")


@dataclass(frozen=True, slots=True)
class DecisionResearchContext:
    request: DecisionResearchRequest
    revision: int
    status: str
    grouping_version_id: str | None
    episode_summary: EpisodeAuditSummary | None
    sample_count: int


class DecisionResearchCoordinator:
    """Own the versioned context shared by all decision-research steps."""

    def __init__(self, storage: Any) -> None:
        required = (
            "get_setup_version",
            "list_observation_samples",
            "list_trade_events_for_session",
            "save_episode_grouping",
            "get_episode_grouping",
            "save_episode_revision",
            "list_episode_audit",
        )
        if storage is None or any(
            not callable(getattr(storage, name, None)) for name in required
        ):
            raise TypeError("storage does not implement decision research coordination")
        self._storage = storage
        self._episodes = MarketEpisodeService(storage)
        self._revision = 0

    def open(
        self,
        request: DecisionResearchRequest,
        *,
        now: datetime | None = None,
    ) -> DecisionResearchContext:
        if not isinstance(request, DecisionResearchRequest):
            raise TypeError("request must be DecisionResearchRequest")
        setup_version = self._storage.get_setup_version(
            request.setup_version_id
        )
        if setup_version is None:
            raise KeyError(
                f"unknown setup version: {request.setup_version_id}"
            )
        if tuple(request.timeframes) != (
            setup_version.timeframes.decision,
            setup_version.timeframes.context_one,
            setup_version.timeframes.context_two,
        ):
            raise ValueError("request timeframes do not match the immutable setup version")

        windows = self._sample_windows(request, setup_version.direction.value)
        self._revision += 1
        if not windows:
            return DecisionResearchContext(
                request=request,
                revision=self._revision,
                status="empty",
                grouping_version_id=None,
                episode_summary=None,
                sample_count=0,
            )
        grouping = self._episodes.create_automatic_grouping(
            windows,
            created_at=_as_utc(now or datetime.now(UTC)),
        )
        summary = self._episodes.audit_summary(grouping.grouping_version_id)
        return DecisionResearchContext(
            request=request,
            revision=self._revision,
            status="ready",
            grouping_version_id=grouping.grouping_version_id,
            episode_summary=summary,
            sample_count=summary.sample_count,
        )

    def is_current(self, revision: int) -> bool:
        return int(revision) == self._revision

    def merge_episodes(
        self,
        context: DecisionResearchContext,
        episode_ids: Sequence[str],
        *,
        actor: str,
        reason: str,
        now: datetime | None = None,
    ) -> DecisionResearchContext:
        self._require_current_context(context)
        if context.grouping_version_id is None:
            raise ValueError("an episode grouping is required before correction")
        grouping = self._episodes.merge_episodes(
            context.grouping_version_id,
            episode_ids,
            actor=actor,
            reason=reason,
            created_at=_as_utc(now or datetime.now(UTC)),
        )
        return self._context_for_grouping(context.request, grouping.grouping_version_id)

    def split_episode(
        self,
        context: DecisionResearchContext,
        episode_id: str,
        sample_groups: Sequence[Sequence[str]],
        *,
        actor: str,
        reason: str,
        now: datetime | None = None,
    ) -> DecisionResearchContext:
        self._require_current_context(context)
        if context.grouping_version_id is None:
            raise ValueError("an episode grouping is required before correction")
        grouping = self._episodes.split_episode(
            context.grouping_version_id,
            episode_id,
            sample_groups,
            actor=actor,
            reason=reason,
            created_at=_as_utc(now or datetime.now(UTC)),
        )
        return self._context_for_grouping(context.request, grouping.grouping_version_id)

    def _context_for_grouping(
        self,
        request: DecisionResearchRequest,
        grouping_version_id: str,
    ) -> DecisionResearchContext:
        summary = self._episodes.audit_summary(grouping_version_id)
        self._revision += 1
        return DecisionResearchContext(
            request=request,
            revision=self._revision,
            status="ready",
            grouping_version_id=grouping_version_id,
            episode_summary=summary,
            sample_count=summary.sample_count,
        )

    def _require_current_context(self, context: DecisionResearchContext) -> None:
        if not isinstance(context, DecisionResearchContext):
            raise TypeError("context must be DecisionResearchContext")
        if not self.is_current(context.revision):
            raise ValueError("decision research context is stale")

    def _sample_windows(
        self,
        request: DecisionResearchRequest,
        setup_direction: str,
    ) -> tuple[ResearchSampleWindow, ...]:
        observation_rows = self._storage.list_observation_samples(
            session_id=request.session_id,
            profile_id=request.setup_version_id,
        )
        event_type = "OPEN" if request.mode == "entry" else "CLOSE"
        event_rows = self._storage.list_trade_events_for_session(
            request.session_id,
            event_types=(event_type,),
        )
        windows: list[ResearchSampleWindow] = []
        seen: set[str] = set()
        rows = [
            {
                **row,
                "sample_id": row.get("event_id"),
                "event_time_bjt": (
                    row.get("bar_open_time_bjt")
                    or row.get("real_key_time_bjt")
                ),
                "user_action": (
                    f"{event_type}_{str(row.get('side') or '').upper()}"
                ),
            }
            for row in event_rows
        ]
        rows.extend(observation_rows)
        for row in rows:
            sample_id = str(
                row.get("linked_event_id") or row.get("sample_id") or ""
            ).strip()
            if not sample_id or sample_id in seen:
                continue
            if str(row.get("symbol") or "").strip().upper() != request.symbol.upper():
                continue
            direction = str(row.get("side") or "").strip().upper()
            if direction and direction != setup_direction:
                continue
            action = str(row.get("user_action") or "").strip().upper()
            if not _action_matches_mode(action, request.mode):
                continue
            decision_time = _parse_datetime(row.get("event_time_bjt"))
            decision_ms = int(decision_time.timestamp() * 1_000)
            if not (
                request.start_time_utc_ms
                <= decision_ms
                <= request.end_time_utc_ms
            ):
                continue
            interval = str(row.get("interval") or request.timeframes[0])
            step = timedelta(milliseconds=interval_to_ms(interval))
            windows.append(
                ResearchSampleWindow(
                    sample_id=sample_id,
                    symbol=request.symbol.upper(),
                    timeframe=interval,
                    feature_window=TimeRange(
                        decision_time - step * (FEATURE_LOOKBACK_BARS - 1),
                        decision_time,
                    ),
                    outcome_window=TimeRange(
                        decision_time + step,
                        decision_time + step * OUTCOME_HORIZON_BARS,
                    ),
                )
            )
            seen.add(sample_id)
        return tuple(windows)


class ResearchSnapshotInputAssembler:
    """Assemble one reproducible draft from the current coordinated context."""

    def __init__(self, storage: Any) -> None:
        self._storage = storage

    def assemble(
        self,
        context: DecisionResearchContext,
        mode_state: Any,
        *,
        completeness_report: Any | None = None,
    ) -> ResearchSnapshotInput:
        if context.grouping_version_id is None:
            raise ValueError("an episode grouping is required for a research draft")
        comparison = self._comparison(mode_state.outcome_comparison_id)
        label_rows = self._label_rows(context, mode_state)
        label_counts = dict(
            sorted(Counter(str(row["blind_label"]) for row in label_rows).items())
        )
        label_payload = json.dumps(
            {"mode": context.request.mode, "rows": label_rows},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
        label_version = "blind-labels-" + hashlib.sha256(
            label_payload.encode("utf-8")
        ).hexdigest()[:16]
        candidate_summary = self._candidate_summary(
            context.request.mode,
            mode_state.candidate_run_id,
            stale="candidate_run" in mode_state.stale_dependencies,
        )
        model, model_summary = self._model_summary(
            context.request.mode,
            mode_state.behavior_snapshot_id,
            maturity=mode_state.maturity,
            error=mode_state.error,
            stale="behavior_snapshot" in mode_state.stale_dependencies,
        )
        formula_version = str(
            getattr(comparison, "formula_version", None)
            or getattr(getattr(model, "manifest", None), "formula_version", None)
            or candidate_summary.get("formula_version")
            or SNAPSHOT_FORMULA_VERSION
        )
        feature_version = str(
            getattr(comparison, "feature_version", None)
            or getattr(getattr(model, "manifest", None), "feature_version", None)
            or candidate_summary.get("feature_version")
            or SNAPSHOT_FEATURE_VERSION
        )
        model_ids = tuple(
            value
            for value in (mode_state.behavior_snapshot_id,)
            if value
        )
        comparison_ids = tuple(
            value
            for value in (mode_state.outcome_comparison_id,)
            if value
        )
        outcome_rows = self._outcome_rows(
            comparison,
            mode=context.request.mode,
        )
        stale = tuple(mode_state.stale_dependencies)
        summary = (
            f"当前{ '开仓' if context.request.mode == 'entry' else '平仓' }研究草稿；"
            f"行情片段 {context.episode_summary.episode_count} 个，"
            f"成熟度为 { {'mature': '成熟', 'not_ready': '未就绪'}.get(mode_state.maturity, '未知') }。"
        )
        return ResearchSnapshotInput(
            versions=ResearchSnapshotVersions(
                setup_version_id=context.request.setup_version_id,
                direction=str(mode_state.direction),
                timeframes=tuple(mode_state.timeframes),
                data_version=(
                    f"research-data-{context.request.start_time_utc_ms}-"
                    f"{context.request.end_time_utc_ms}"
                ),
                label_version=label_version,
                episode_version=context.grouping_version_id,
                formula_version=formula_version,
                feature_version=feature_version,
                model_version_ids=model_ids,
                matched_research_ids=comparison_ids,
                application_version=APP_VERSION,
                random_seed=SNAPSHOT_RANDOM_SEED,
                data_start_utc_ms=context.request.start_time_utc_ms,
                data_end_utc_ms=context.request.end_time_utc_ms,
            ),
            content=ResearchSnapshotContent(
                data_quality=self._data_quality(
                    mode_state.data_completeness,
                    completeness_report,
                ),
                label_audit={
                    "blind_batch_id": mode_state.blind_batch_id,
                    "status": (
                        "stale"
                        if "blind_batch" in stale
                        else "current"
                        if mode_state.blind_batch_id
                        else "not_run"
                    ),
                    "total_labels": len(label_rows),
                    "label_counts": label_counts,
                    "episode_count": len(
                        {str(row["episode_id"]) for row in label_rows}
                    ),
                    "source": "formal_blind_judgment",
                },
                similarity_summary=candidate_summary,
                model_summary=model_summary,
                sample_rows=tuple(
                    {
                        key: row.get(key)
                        for key in (
                            "decision_event_id",
                            "source_sample_id",
                            "episode_id",
                            "symbol",
                            "direction",
                            "decision_cutoff_utc_ms",
                            "blind_judgment_id",
                            "blind_label",
                        )
                    }
                    for row in label_rows
                ),
                coefficient_rows=self._coefficient_rows(model),
                validation_rows=self._validation_rows(model),
                outcome_rows=outcome_rows,
                limitations_zh=(
                    "当前报告是研究草稿，不是买卖信号或可交易策略。",
                    "失败、取消、证据不足和过期状态不会从报告中省略。",
                ),
                audit_notes_zh=(
                    f"研究模式：{context.request.mode}",
                    f"状态：{'已过期' if stale else '当前'}",
                ),
            ),
            hypothesis_card=HypothesisCard(
                status=HypothesisStatus.BEHAVIOR_PROFILE_ONLY,
                summary_zh=summary,
                evidence_zh=("当前仅形成可复算的行为画像草稿。",),
                next_evidence_zh=("需要独立前瞻数据继续验证。",),
            ),
        )

    def _label_rows(self, context, mode_state) -> list[dict[str, Any]]:
        target = (
            "ENTRY_SELECTION"
            if context.request.mode == "entry"
            else "EXIT_SELECTION"
        )
        return self._storage.list_behavior_training_events(
            target=target,
            setup_version_id=context.request.setup_version_id,
            grouping_version_id=context.grouping_version_id,
            direction=str(mode_state.direction),
        )

    def _candidate_summary(
        self,
        mode: str,
        scan_id: str | None,
        *,
        stale: bool,
    ) -> dict[str, Any]:
        if not scan_id:
            return {"candidate_run_id": None, "status": "not_run"}
        getter = (
            self._storage.get_entry_candidate_scan
            if mode == "entry"
            else self._storage.get_exit_candidate_scan
        )
        row = getter(scan_id)
        if row is None:
            raise KeyError(f"unknown candidate scan: {scan_id}")
        result = row.get("result_json")
        try:
            result_payload = json.loads(result) if result else {}
        except (TypeError, json.JSONDecodeError):
            result_payload = {"raw_status": row.get("status")}
        return {
            "candidate_run_id": scan_id,
            "status": "stale" if stale else str(row.get("status") or "complete"),
            "formula_version": row.get("formula_version"),
            "feature_version": row.get("feature_version"),
            "result": result_payload,
        }

    def _model_summary(
        self,
        mode: str,
        model_id: str | None,
        *,
        maturity: str,
        error: str | None,
        stale: bool,
    ) -> tuple[Any | None, dict[str, Any]]:
        if not model_id:
            return None, {
                "model_version_id": None,
                "status": "failed" if error else str(maturity),
                "error": error,
                "cancelled": False,
                "dependency_versions": {},
            }
        target = "ENTRY_SELECTION" if mode == "entry" else "EXIT_SELECTION"
        model = self._storage.get_behavior_model_version(
            model_id,
            target=target,
        )
        if model is None:
            raise KeyError(f"unknown behavior model: {model_id}")
        return model, {
            "model_version_id": model_id,
            "status": "stale" if stale else str(model.maturity.value).lower(),
            "error": error,
            "cancelled": False,
            "target": str(model.target.value),
            "stable_feature_count": len(model.stable_features),
            "research_threshold": model.research_threshold,
            "applicability_threshold": model.applicability_threshold,
            "dependency_versions": dict(model.manifest.dependency_versions),
        }

    @staticmethod
    def _data_quality(status: str, report: Any | None) -> dict[str, Any]:
        payload = {
            "status": str(status),
            "formula_version": str(
                getattr(report, "formula_version", "not_audited")
            ),
        }
        if report is not None:
            payload["timeframes"] = [
                _snapshot_value(timeframe) for timeframe in report.timeframes
            ]
        return payload

    @staticmethod
    def _coefficient_rows(model: Any | None) -> tuple[dict[str, Any], ...]:
        if model is None:
            return ()
        return tuple(asdict(feature) for feature in model.stable_features)

    @staticmethod
    def _validation_rows(model: Any | None) -> tuple[dict[str, Any], ...]:
        if model is None:
            return ()
        return tuple(
            {
                "fold_index": fold.fold_index,
                "train_episode_count": len(fold.train_episode_ids),
                "validation_episode_count": len(fold.validation_episode_ids),
                "train_sample_count": len(fold.train_sample_ids),
                "validation_sample_count": len(fold.validation_sample_ids),
                "train_end_utc_ms": fold.train_end_utc_ms,
                "validation_start_utc_ms": fold.validation_start_utc_ms,
                "validation_end_utc_ms": fold.validation_end_utc_ms,
            }
            for fold in model.manifest.temporal_folds
        )

    def _comparison(self, comparison_id: str | None) -> Any | None:
        if not comparison_id:
            return None
        result = self._storage.get_entry_outcome_result(comparison_id)
        if result is None:
            result = self._storage.get_exit_outcome_result(comparison_id)
        if result is None:
            raise KeyError(f"unknown outcome comparison: {comparison_id}")
        return result

    @staticmethod
    def _outcome_rows(
        comparison: Any | None,
        *,
        mode: str,
    ) -> tuple[dict[str, Any], ...]:
        if comparison is None:
            return tuple(
                {
                    "comparison_target": mode,
                    "horizon_bars": horizon,
                    "metric": metric,
                    "status": "unavailable",
                }
                for horizon in (1, 3, 5, 10, 20)
                for metric in ("CLOSE_RETURN", "MFE", "MAE")
            )
        matrix = getattr(getattr(comparison, "primary", None), "matrix", ())
        rows = []
        for cell in matrix:
            payload = asdict(cell)
            payload["metric"] = str(getattr(cell.metric, "value", cell.metric))
            payload["comparison_id"] = comparison.comparison_id
            rows.append(payload)
        return tuple(rows)


def _action_matches_mode(action: str, mode: str) -> bool:
    if mode == "entry":
        return action in {"OPEN_LONG", "OPEN_SHORT", "NO_ACTION"}
    return action in {"CLOSE_LONG", "CLOSE_SHORT", "HOLD"}


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _as_utc(value)
    text = str(value or "").strip()
    if not text:
        raise ValueError("research sample event_time_bjt must not be empty")
    return _as_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("decision research timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _snapshot_value(value: Any) -> Any:
    """Convert frozen DTOs without deepcopying read-only mapping proxies."""
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _snapshot_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {
            str(key): _snapshot_value(item)
            for key, item in value.items()
        }
    if isinstance(value, Enum):
        return _snapshot_value(value.value)
    if isinstance(value, (tuple, list)):
        return [_snapshot_value(item) for item in value]
    return value


__all__ = [
    "DecisionResearchContext",
    "DecisionResearchCoordinator",
    "DecisionResearchRequest",
    "ResearchSnapshotInputAssembler",
]
