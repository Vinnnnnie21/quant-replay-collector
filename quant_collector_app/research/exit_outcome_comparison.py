from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from typing import Iterable, Mapping

from .entry_outcome_comparison import (
    ENTRY_MATCH_PRIMARY_THRESHOLD,
    ENTRY_MATCH_SENSITIVITY_THRESHOLDS,
    ENTRY_OUTCOME_HORIZONS,
    EntryDecisionForComparison,
    EntryEpisodeOutcomeDifference,
    EntryOutcomeEvidenceStage,
    EntryOutcomeEvidenceStatus,
    EntryOutcomeMetric,
    EntryOutcomePath,
    EntryOutcomeValue,
    EntryPairSimilarity,
    MatchedEntryPair,
    OutcomeBar,
    build_entry_outcome_matrix,
    calculate_entry_outcome_path,
    global_match_entry_reject,
)


EXIT_MATCH_PRIMARY_THRESHOLD = ENTRY_MATCH_PRIMARY_THRESHOLD
EXIT_MATCH_SENSITIVITY_THRESHOLDS = ENTRY_MATCH_SENSITIVITY_THRESHOLDS
EXIT_OUTCOME_HORIZONS = ENTRY_OUTCOME_HORIZONS
EXIT_OUTCOME_FORMULA_VERSION = "exit-outcome-comparison-v1"
ExitOutcomeMetric = EntryOutcomeMetric
ExitOutcomePath = EntryOutcomePath
ExitOutcomeValue = EntryOutcomeValue
ExitOutcomeEvidenceStage = EntryOutcomeEvidenceStage
ExitOutcomeEvidenceStatus = EntryOutcomeEvidenceStatus
ExitEpisodeOutcomeDifference = EntryEpisodeOutcomeDifference


@dataclass(frozen=True, slots=True)
class ExitOutcomeComparisonRequest:
    setup_version_id: str
    grouping_version_id: str
    direction: str
    random_seed: int = 20260720

    def __post_init__(self) -> None:
        direction = str(self.direction).upper()
        if direction not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT")
        if not str(self.setup_version_id or "").strip():
            raise ValueError("setup_version_id must not be empty")
        if not str(self.grouping_version_id or "").strip():
            raise ValueError("grouping_version_id must not be empty")
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "random_seed", int(self.random_seed))


@dataclass(frozen=True, slots=True)
class ExitDecisionForComparison:
    decision_event_id: str
    label: str
    setup_version_id: str
    grouping_version_id: str
    episode_id: str
    trade_id: str
    symbol: str
    direction: str
    decision_timeframe: str
    decision_cutoff_utc_ms: int
    blind_judgment_id: str | None = None

    def __post_init__(self) -> None:
        label = str(self.label).upper()
        direction = str(self.direction).upper()
        if label not in {"EXIT_NOW", "HOLD"}:
            raise ValueError("comparison label must be EXIT_NOW or HOLD")
        if direction not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT")
        for field_name in (
            "decision_event_id",
            "setup_version_id",
            "grouping_version_id",
            "episode_id",
            "trade_id",
            "symbol",
            "decision_timeframe",
        ):
            if not str(getattr(self, field_name) or "").strip():
                raise ValueError(f"{field_name} must not be empty")
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "symbol", str(self.symbol).upper())
        if self.blind_judgment_id is not None:
            judgment_id = str(self.blind_judgment_id).strip()
            if not judgment_id:
                raise ValueError("blind_judgment_id must not be empty")
            object.__setattr__(self, "blind_judgment_id", judgment_id)


@dataclass(frozen=True, slots=True)
class ExitPairSimilarity:
    exit_now_decision_event_id: str
    hold_decision_event_id: str
    similarity: float

    def __post_init__(self) -> None:
        similarity = float(self.similarity)
        if not math.isfinite(similarity) or not 0.0 <= similarity <= 100.0:
            raise ValueError("pair similarity must be finite and between 0 and 100")
        object.__setattr__(self, "similarity", similarity)


@dataclass(frozen=True, slots=True)
class MatchedExitPair:
    exit_now_decision_event_id: str
    hold_decision_event_id: str
    exit_now_episode_id: str
    hold_episode_id: str
    symbol: str
    decision_timeframe: str
    similarity: float
    context_distance: float
    similarity_threshold: float

    def __post_init__(self) -> None:
        similarity = float(self.similarity)
        distance = float(self.context_distance)
        threshold = float(self.similarity_threshold)
        if not math.isfinite(similarity) or not 0.0 <= similarity <= 100.0:
            raise ValueError("matched similarity must be finite and between 0 and 100")
        if not math.isfinite(distance) or not 0.0 <= distance <= 1.0:
            raise ValueError("matched context distance must be between 0 and 1")
        if not math.isclose(
            distance,
            1.0 - similarity / 100.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("matched context distance is inconsistent with similarity")
        if not math.isfinite(threshold) or not 0.0 <= threshold <= 100.0:
            raise ValueError("matched similarity threshold must be between 0 and 100")
        object.__setattr__(self, "similarity", similarity)
        object.__setattr__(self, "context_distance", distance)
        object.__setattr__(self, "similarity_threshold", threshold)


@dataclass(frozen=True, slots=True)
class ExitPairOutcomeDifference:
    exit_now_decision_event_id: str
    hold_decision_event_id: str
    episode_id: str
    value: float
    counterparty_episode_id: str | None = None

    def __post_init__(self) -> None:
        value = float(self.value)
        if not math.isfinite(value):
            raise ValueError("paired outcome difference must be finite")
        object.__setattr__(self, "value", value)


@dataclass(frozen=True, slots=True)
class ExitOutcomeMatrixCell:
    horizon_bars: int
    metric: ExitOutcomeMetric
    stage: ExitOutcomeEvidenceStage
    evidence_status: ExitOutcomeEvidenceStatus
    pair_count: int
    episode_count: int
    median_difference: float | None
    mean_difference: float | None
    rank_biserial: float | None
    ci_low: float | None
    ci_high: float | None
    p_value: float | None
    q_value: float | None
    random_seed: int | None
    differences: tuple[ExitPairOutcomeDifference, ...]
    episodes: tuple[ExitEpisodeOutcomeDifference, ...]


@dataclass(frozen=True, slots=True)
class ExitOutcomeThresholdResult:
    similarity_threshold: float
    pairs: tuple[MatchedExitPair, ...]
    matrix: tuple[ExitOutcomeMatrixCell, ...]

    @property
    def stage(self) -> ExitOutcomeEvidenceStage:
        if not self.matrix:
            return ExitOutcomeEvidenceStage.INSUFFICIENT
        return min(
            (cell.stage for cell in self.matrix),
            key=(
                ExitOutcomeEvidenceStage.INSUFFICIENT,
                ExitOutcomeEvidenceStage.EXPLORATORY,
                ExitOutcomeEvidenceStage.FORMAL,
            ).index,
        )


@dataclass(frozen=True, slots=True)
class ExitOutcomeComparisonResult:
    comparison_id: str
    setup_version_id: str
    grouping_version_id: str
    direction: str
    formula_version: str
    feature_version: str
    random_seed: int
    eligible_decisions: tuple[ExitDecisionForComparison, ...]
    input_feature_fingerprint: str
    sensitivities: tuple[ExitOutcomeThresholdResult, ...]
    created_at: str
    research_target: str = "EXIT"

    def __post_init__(self) -> None:
        direction = str(self.direction).upper()
        if direction not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT")
        if self.research_target != "EXIT":
            raise ValueError("exit comparison research_target must be EXIT")
        if len(self.input_feature_fingerprint) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.input_feature_fingerprint
        ):
            raise ValueError("input feature fingerprint must be lowercase SHA-256")
        decisions = tuple(self.eligible_decisions)
        decision_by_id = {item.decision_event_id: item for item in decisions}
        if len(decision_by_id) != len(decisions):
            raise ValueError("eligible decision_event_id values must be unique")
        if decisions and any(item.blind_judgment_id is None for item in decisions):
            raise ValueError("eligible decisions require blind judgment identity")
        for decision in decisions:
            if (
                decision.setup_version_id != self.setup_version_id
                or decision.grouping_version_id != self.grouping_version_id
                or decision.direction != direction
            ):
                raise ValueError("eligible decision context does not match result")
        sensitivities = tuple(self.sensitivities)
        if tuple(item.similarity_threshold for item in sensitivities) != (
            EXIT_MATCH_SENSITIVITY_THRESHOLDS
        ):
            raise ValueError("result requires three preregistered sensitivities")
        expected_cells = tuple(
            (horizon, metric)
            for horizon in EXIT_OUTCOME_HORIZONS
            for metric in ExitOutcomeMetric
        )
        for sensitivity in sensitivities:
            if tuple(
                (cell.horizon_bars, cell.metric) for cell in sensitivity.matrix
            ) != expected_cells:
                raise ValueError("each sensitivity requires the complete 15-cell matrix")
            if any(
                pair.similarity_threshold != sensitivity.similarity_threshold
                for pair in sensitivity.pairs
            ):
                raise ValueError("matched pair threshold does not match sensitivity")
            used_exit_now: set[str] = set()
            used_hold: set[str] = set()
            for pair in sensitivity.pairs:
                exit_now = decision_by_id.get(pair.exit_now_decision_event_id)
                hold = decision_by_id.get(pair.hold_decision_event_id)
                if exit_now is None or hold is None:
                    raise ValueError("matched pair is outside eligible decision universe")
                if exit_now.label != "EXIT_NOW" or hold.label != "HOLD":
                    raise ValueError("matched pair label identity is invalid")
                if (
                    exit_now.episode_id != pair.exit_now_episode_id
                    or hold.episode_id != pair.hold_episode_id
                    or exit_now.symbol != pair.symbol
                    or hold.symbol != pair.symbol
                    or exit_now.decision_timeframe != pair.decision_timeframe
                    or hold.decision_timeframe != pair.decision_timeframe
                ):
                    raise ValueError("matched pair context differs from eligible decision")
                if pair.similarity < sensitivity.similarity_threshold:
                    raise ValueError("matched pair is below its similarity threshold")
                if (
                    pair.exit_now_decision_event_id in used_exit_now
                    or pair.hold_decision_event_id in used_hold
                ):
                    raise ValueError("matched pairs must not reuse a decision")
                used_exit_now.add(pair.exit_now_decision_event_id)
                used_hold.add(pair.hold_decision_event_id)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "random_seed", int(self.random_seed))
        object.__setattr__(self, "eligible_decisions", decisions)
        object.__setattr__(self, "sensitivities", sensitivities)

    @property
    def primary(self) -> ExitOutcomeThresholdResult:
        return next(
            item
            for item in self.sensitivities
            if item.similarity_threshold == EXIT_MATCH_PRIMARY_THRESHOLD
        )

    def matrix_records(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "comparison_id": self.comparison_id,
                "research_target": self.research_target,
                "similarity_threshold": self.primary.similarity_threshold,
                "horizon_bars": cell.horizon_bars,
                "metric": cell.metric.value,
                "stage": cell.stage.value,
                "evidence_status": cell.evidence_status.value,
                "pair_count": cell.pair_count,
                "episode_count": cell.episode_count,
                "median_difference": cell.median_difference,
                "mean_difference": cell.mean_difference,
                "rank_biserial": cell.rank_biserial,
                "ci_low": cell.ci_low,
                "ci_high": cell.ci_high,
                "p_value": cell.p_value,
                "q_value": cell.q_value,
            }
            for cell in self.primary.matrix
        )


def calculate_exit_outcome_path(
    *,
    direction: str,
    decision_cutoff_utc_ms: int,
    bars: Iterable[OutcomeBar],
    decision_interval_ms: int | None = None,
    actual_fill_price: float | None = None,
) -> ExitOutcomePath:
    """Calculate gross continuation from the common next-bar-open baseline."""

    return calculate_entry_outcome_path(
        direction=direction,
        decision_cutoff_utc_ms=decision_cutoff_utc_ms,
        bars=bars,
        decision_interval_ms=decision_interval_ms,
        actual_fill_price=actual_fill_price,
    )


def global_match_exit_hold(
    decisions: Iterable[ExitDecisionForComparison],
    pair_similarities: Iterable[ExitPairSimilarity],
    *,
    similarity_threshold: float = EXIT_MATCH_PRIMARY_THRESHOLD,
) -> tuple[MatchedExitPair, ...]:
    samples = tuple(decisions)
    generic_decisions = tuple(
        EntryDecisionForComparison(
            decision_event_id=item.decision_event_id,
            label="ENTRY" if item.label == "EXIT_NOW" else "REJECT",
            setup_version_id=item.setup_version_id,
            grouping_version_id=item.grouping_version_id,
            episode_id=item.episode_id,
            symbol=item.symbol,
            direction=item.direction,
            decision_timeframe=item.decision_timeframe,
            decision_cutoff_utc_ms=item.decision_cutoff_utc_ms,
            blind_judgment_id=item.blind_judgment_id,
        )
        for item in samples
    )
    generic_similarities = tuple(
        EntryPairSimilarity(
            item.exit_now_decision_event_id,
            item.hold_decision_event_id,
            item.similarity,
        )
        for item in pair_similarities
    )
    return tuple(
        MatchedExitPair(
            exit_now_decision_event_id=pair.entry_decision_event_id,
            hold_decision_event_id=pair.reject_decision_event_id,
            exit_now_episode_id=pair.entry_episode_id,
            hold_episode_id=pair.reject_episode_id,
            symbol=pair.symbol,
            decision_timeframe=pair.decision_timeframe,
            similarity=pair.similarity,
            context_distance=pair.context_distance,
            similarity_threshold=pair.similarity_threshold,
        )
        for pair in global_match_entry_reject(
            generic_decisions,
            generic_similarities,
            similarity_threshold=similarity_threshold,
        )
    )


def build_exit_outcome_matrix(
    pairs: Iterable[MatchedExitPair],
    outcomes_by_event: Mapping[str, ExitOutcomePath],
    *,
    random_seed: int,
    bootstrap_draws: int = 5_000,
    permutation_draws: int = 10_000,
    cancelled=None,
) -> tuple[ExitOutcomeMatrixCell, ...]:
    selected_pairs = tuple(pairs)
    # The shared inference engine computes first-label minus second-label.
    # Reversing only the generic adapter yields the registered HOLD-EXIT_NOW
    # direction without duplicating bootstrap, sign-flip, or BH code.
    generic_pairs = tuple(
        MatchedEntryPair(
            entry_decision_event_id=pair.hold_decision_event_id,
            reject_decision_event_id=pair.exit_now_decision_event_id,
            entry_episode_id=pair.hold_episode_id,
            reject_episode_id=pair.exit_now_episode_id,
            symbol=pair.symbol,
            decision_timeframe=pair.decision_timeframe,
            similarity=pair.similarity,
            context_distance=pair.context_distance,
            similarity_threshold=pair.similarity_threshold,
        )
        for pair in selected_pairs
    )
    generic_cells = build_entry_outcome_matrix(
        generic_pairs,
        outcomes_by_event,
        random_seed=random_seed,
        bootstrap_draws=bootstrap_draws,
        permutation_draws=permutation_draws,
        cancelled=cancelled,
    )
    return tuple(
        ExitOutcomeMatrixCell(
            horizon_bars=cell.horizon_bars,
            metric=cell.metric,
            stage=cell.stage,
            evidence_status=cell.evidence_status,
            pair_count=cell.pair_count,
            episode_count=cell.episode_count,
            median_difference=cell.median_difference,
            mean_difference=cell.mean_difference,
            rank_biserial=cell.rank_biserial,
            ci_low=cell.ci_low,
            ci_high=cell.ci_high,
            p_value=cell.p_value,
            q_value=cell.q_value,
            random_seed=cell.random_seed,
            differences=tuple(
                ExitPairOutcomeDifference(
                    exit_now_decision_event_id=item.reject_decision_event_id,
                    hold_decision_event_id=item.entry_decision_event_id,
                    episode_id=item.episode_id,
                    value=item.value,
                    counterparty_episode_id=item.counterparty_episode_id,
                )
                for item in cell.differences
            ),
            episodes=cell.episodes,
        )
        for cell in generic_cells
    )


def exit_outcome_result_to_json(result: ExitOutcomeComparisonResult) -> str:
    return json.dumps(
        asdict(result),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def exit_outcome_result_from_json(payload: str) -> ExitOutcomeComparisonResult:
    raw = json.loads(payload)
    sensitivities = []
    for sensitivity in raw["sensitivities"]:
        cells = []
        for cell in sensitivity["matrix"]:
            cells.append(
                ExitOutcomeMatrixCell(
                    horizon_bars=int(cell["horizon_bars"]),
                    metric=ExitOutcomeMetric(cell["metric"]),
                    stage=ExitOutcomeEvidenceStage(cell["stage"]),
                    evidence_status=ExitOutcomeEvidenceStatus(
                        cell["evidence_status"]
                    ),
                    pair_count=int(cell["pair_count"]),
                    episode_count=int(cell["episode_count"]),
                    median_difference=cell["median_difference"],
                    mean_difference=cell["mean_difference"],
                    rank_biserial=cell["rank_biserial"],
                    ci_low=cell["ci_low"],
                    ci_high=cell["ci_high"],
                    p_value=cell["p_value"],
                    q_value=cell["q_value"],
                    random_seed=cell["random_seed"],
                    differences=tuple(
                        ExitPairOutcomeDifference(**item)
                        for item in cell["differences"]
                    ),
                    episodes=tuple(
                        EntryEpisodeOutcomeDifference(**item)
                        for item in cell["episodes"]
                    ),
                )
            )
        sensitivities.append(
            ExitOutcomeThresholdResult(
                similarity_threshold=float(sensitivity["similarity_threshold"]),
                pairs=tuple(MatchedExitPair(**item) for item in sensitivity["pairs"]),
                matrix=tuple(cells),
            )
        )
    return ExitOutcomeComparisonResult(
        comparison_id=str(raw["comparison_id"]),
        setup_version_id=str(raw["setup_version_id"]),
        grouping_version_id=str(raw["grouping_version_id"]),
        direction=str(raw["direction"]),
        formula_version=str(raw["formula_version"]),
        feature_version=str(raw["feature_version"]),
        random_seed=int(raw["random_seed"]),
        eligible_decisions=tuple(
            ExitDecisionForComparison(**item) for item in raw["eligible_decisions"]
        ),
        input_feature_fingerprint=str(raw["input_feature_fingerprint"]),
        sensitivities=tuple(sensitivities),
        created_at=str(raw["created_at"]),
        research_target=str(raw.get("research_target", "EXIT")),
    )


__all__ = [
    "EXIT_MATCH_PRIMARY_THRESHOLD",
    "EXIT_MATCH_SENSITIVITY_THRESHOLDS",
    "EXIT_OUTCOME_FORMULA_VERSION",
    "EXIT_OUTCOME_HORIZONS",
    "ExitDecisionForComparison",
    "ExitEpisodeOutcomeDifference",
    "ExitOutcomeComparisonRequest",
    "ExitOutcomeComparisonResult",
    "ExitOutcomeEvidenceStage",
    "ExitOutcomeEvidenceStatus",
    "ExitOutcomeMatrixCell",
    "ExitOutcomeMetric",
    "ExitOutcomePath",
    "ExitOutcomeThresholdResult",
    "ExitPairOutcomeDifference",
    "ExitPairSimilarity",
    "MatchedExitPair",
    "OutcomeBar",
    "build_exit_outcome_matrix",
    "calculate_exit_outcome_path",
    "exit_outcome_result_from_json",
    "exit_outcome_result_to_json",
    "global_match_exit_hold",
]
