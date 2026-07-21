from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import math
from typing import Mapping, Sequence

import numpy as np

from .entry_context_features import EntryStructuralFeatureSnapshot


ENTRY_BEHAVIOR_FORMULA_VERSION = "decision-research-v1.6"
ENTRY_BEHAVIOR_FEATURE_VERSION = "entry-behavior-features-v1"
ENTRY_BEHAVIOR_C_GRID = (0.03, 0.1, 0.3, 1.0, 3.0)
ENTRY_BEHAVIOR_L1_RATIO = 0.5


class BehaviorModelTarget(str, Enum):
    ENTRY_SELECTION = "ENTRY_SELECTION"
    EXIT_SELECTION = "EXIT_SELECTION"


class EntryBehaviorExperimentStatus(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EntryBehaviorModelMaturity(str, Enum):
    EXPLORATORY = "EXPLORATORY"
    FORMAL = "FORMAL"


class EntryBehaviorScoreStatus(str, Enum):
    COMPUTED = "COMPUTED"
    OUT_OF_DOMAIN = "OUT_OF_DOMAIN"
    MODEL_NOT_FORMAL = "MODEL_NOT_FORMAL"


@dataclass(frozen=True, slots=True)
class EntryBehaviorTrainingRequest:
    setup_version_id: str
    grouping_version_id: str
    direction: str
    seed: int = 20260719
    target: BehaviorModelTarget = BehaviorModelTarget.ENTRY_SELECTION

    def __post_init__(self) -> None:
        for field_name in ("setup_version_id", "grouping_version_id"):
            if not str(getattr(self, field_name) or "").strip():
                raise ValueError(f"{field_name} must not be empty")
        direction = str(self.direction or "").strip().upper()
        if direction not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT")
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "seed", int(self.seed))
        object.__setattr__(self, "target", BehaviorModelTarget(self.target))


@dataclass(frozen=True, slots=True)
class BehaviorFeatureDefinition:
    feature_id: str
    name_zh: str
    timeframe_index: int
    group_name: str
    source_name: str


ENTRY_BEHAVIOR_FEATURES = (
    BehaviorFeatureDefinition(
        "decision_direction_efficiency_20",
        "决策周期20根方向效率",
        0,
        "trend_volatility",
        "direction_efficiency_20",
    ),
    BehaviorFeatureDefinition(
        "decision_adjusted_slope_20",
        "决策周期20根波动调整趋势",
        0,
        "trend_volatility",
        "adjusted_slope_20",
    ),
    BehaviorFeatureDefinition(
        "decision_range_position_20",
        "决策周期20根区间位置",
        0,
        "candle_shape",
        "range_position_20",
    ),
    BehaviorFeatureDefinition(
        "decision_volatility_level",
        "决策周期波动水平",
        0,
        "trend_volatility",
        "volatility_level",
    ),
    BehaviorFeatureDefinition(
        "decision_quote_activity_20",
        "决策周期计价币成交活跃度",
        0,
        "trading_activity",
        "quote_activity_20",
    ),
    BehaviorFeatureDefinition(
        "decision_aggressor_delta",
        "决策周期主动成交方向短中期差",
        0,
        "trading_activity",
        "aggressor_delta",
    ),
    BehaviorFeatureDefinition(
        "context_one_direction_efficiency_20",
        "第一高周期20根方向效率",
        1,
        "trend_volatility",
        "direction_efficiency_20",
    ),
    BehaviorFeatureDefinition(
        "context_one_ema_distance_20",
        "第一高周期20根均线距离",
        1,
        "trend_volatility",
        "ema_distance_20",
    ),
    BehaviorFeatureDefinition(
        "context_one_volatility_regime",
        "第一高周期波动状态",
        1,
        "trend_volatility",
        "volatility_regime",
    ),
    BehaviorFeatureDefinition(
        "context_two_direction_efficiency_20",
        "第二高周期20根方向效率",
        2,
        "trend_volatility",
        "direction_efficiency_20",
    ),
    BehaviorFeatureDefinition(
        "context_two_ema_distance_20",
        "第二高周期20根均线距离",
        2,
        "trend_volatility",
        "ema_distance_20",
    ),
    BehaviorFeatureDefinition(
        "context_two_volatility_regime",
        "第二高周期波动状态",
        2,
        "trend_volatility",
        "volatility_regime",
    ),
)


EXIT_BEHAVIOR_FEATURES = (
    BehaviorFeatureDefinition(
        "exit_decision_direction_efficiency_20",
        "平仓决策周期20根方向效率",
        0,
        "trend_volatility",
        "direction_efficiency_20",
    ),
    BehaviorFeatureDefinition(
        "exit_decision_adjusted_slope_20",
        "平仓决策周期20根波动调整趋势",
        0,
        "trend_volatility",
        "adjusted_slope_20",
    ),
    BehaviorFeatureDefinition(
        "exit_decision_range_position_20",
        "平仓决策周期20根区间位置",
        0,
        "candle_shape",
        "range_position_20",
    ),
    BehaviorFeatureDefinition(
        "exit_context_direction_efficiency_20",
        "平仓第一高周期20根方向效率",
        1,
        "trend_volatility",
        "direction_efficiency_20",
    ),
    BehaviorFeatureDefinition(
        "position_unrealized_atr",
        "方向调整浮动位置",
        -1,
        "position_state",
        "unrealized_atr",
    ),
    BehaviorFeatureDefinition(
        "position_mfe_atr",
        "持仓最大有利位置",
        -1,
        "position_state",
        "mfe_atr",
    ),
    BehaviorFeatureDefinition(
        "position_mae_atr",
        "持仓最大不利位置",
        -1,
        "position_state",
        "mae_atr",
    ),
    BehaviorFeatureDefinition(
        "position_giveback_atr",
        "持仓利润回撤",
        -1,
        "position_state",
        "giveback_atr",
    ),
    BehaviorFeatureDefinition(
        "position_range_position",
        "持仓有利不利区间位置",
        -1,
        "position_state",
        "range_position",
    ),
    BehaviorFeatureDefinition(
        "position_log_holding_bars",
        "持有根数对数",
        -1,
        "position_state",
        "log_holding_bars",
    ),
    BehaviorFeatureDefinition(
        "position_log_bars_since_mfe",
        "距最近最大有利位置根数对数",
        -1,
        "position_state",
        "log_bars_since_mfe",
    ),
    BehaviorFeatureDefinition(
        "position_log_bars_since_mae",
        "距最近最大不利位置根数对数",
        -1,
        "position_state",
        "log_bars_since_mae",
    ),
)


@dataclass(frozen=True, slots=True)
class BehaviorModelProfile:
    target: BehaviorModelTarget
    positive_label: str
    negative_label: str
    feature_version: str
    feature_definitions: tuple[BehaviorFeatureDefinition, ...]
    episode_kind: str
    insufficient_labels_message_zh: str


ENTRY_BEHAVIOR_PROFILE = BehaviorModelProfile(
    target=BehaviorModelTarget.ENTRY_SELECTION,
    positive_label="ENTRY",
    negative_label="REJECT",
    feature_version=ENTRY_BEHAVIOR_FEATURE_VERSION,
    feature_definitions=ENTRY_BEHAVIOR_FEATURES,
    episode_kind="MARKET",
    insufficient_labels_message_zh="开仓和拒绝样本各至少需要 30 条。",
)

EXIT_BEHAVIOR_PROFILE = BehaviorModelProfile(
    target=BehaviorModelTarget.EXIT_SELECTION,
    positive_label="EXIT_NOW",
    negative_label="HOLD",
    feature_version="exit-behavior-features-v1",
    feature_definitions=EXIT_BEHAVIOR_FEATURES,
    episode_kind="HOLDING",
    insufficient_labels_message_zh="立即平仓和继续持有样本各至少需要 30 条。",
)


def behavior_model_profile(target: BehaviorModelTarget) -> BehaviorModelProfile:
    normalized = BehaviorModelTarget(target)
    return (
        ENTRY_BEHAVIOR_PROFILE
        if normalized is BehaviorModelTarget.ENTRY_SELECTION
        else EXIT_BEHAVIOR_PROFILE
    )


@dataclass(frozen=True, slots=True)
class BehaviorFeatureValue:
    feature_id: str
    name_zh: str
    value: float


@dataclass(frozen=True, slots=True)
class EntryBehaviorSample:
    decision_event_id: str
    episode_id: str
    decision_cutoff_utc_ms: int
    label: str
    features: tuple[BehaviorFeatureValue, ...]


@dataclass(frozen=True, slots=True)
class LeaveEpisodeOutSimilarity:
    decision_event_id: str
    episode_id: str
    reference_episode_ids: tuple[str, str, str]
    similarity: float

    def __post_init__(self) -> None:
        if not self.decision_event_id or not self.episode_id:
            raise ValueError("leave-episode-out identity must not be empty")
        references = tuple(str(item) for item in self.reference_episode_ids)
        if len(references) != 3 or len(set(references)) != 3:
            raise ValueError(
                "leave-episode-out similarity requires three reference episodes"
            )
        if self.episode_id in references:
            raise ValueError(
                "leave-episode-out references must exclude the sample episode"
            )
        similarity = float(self.similarity)
        if not math.isfinite(similarity) or not 0.0 <= similarity <= 100.0:
            raise ValueError(
                "leave-episode-out similarity must be finite in [0, 100]"
            )
        object.__setattr__(self, "reference_episode_ids", references)
        object.__setattr__(self, "similarity", similarity)


@dataclass(frozen=True, slots=True)
class FeatureNormalization:
    feature_id: str
    name_zh: str
    median: float
    mad: float
    scale: float


@dataclass(frozen=True, slots=True)
class StableBehaviorFeature:
    feature_id: str
    name_zh: str
    coefficient: float
    nonzero_fold_count: int
    fold_count: int
    fold_coefficient_min: float
    fold_coefficient_max: float


@dataclass(frozen=True, slots=True)
class FoldRegularizationEvaluation:
    c_value: float
    balanced_log_loss: float
    nonzero_count: int
    coefficients: tuple[tuple[str, float], ...]
    validation_probabilities: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class RegularizationPathSummary:
    c_value: float
    mean_balanced_log_loss: float
    standard_error: float
    maximum_nonzero_count: int


@dataclass(frozen=True, slots=True)
class ResearchThresholdCandidate:
    threshold: float
    mean_recall: float
    minimum_fold_recall: float
    mean_precision: float


@dataclass(frozen=True, slots=True)
class BehaviorModelMetrics:
    sample_count: int
    label_counts: tuple[tuple[str, int], ...]
    episode_counts: tuple[tuple[str, int], ...]
    balanced_log_loss: float
    brier_score: float
    recall: float | None
    precision: float | None


@dataclass(frozen=True, slots=True)
class TemporalFoldAudit:
    fold_index: int
    train_episode_ids: tuple[str, ...]
    validation_episode_ids: tuple[str, ...]
    train_sample_ids: tuple[str, ...]
    validation_sample_ids: tuple[str, ...]
    train_end_utc_ms: int
    validation_start_utc_ms: int
    validation_end_utc_ms: int
    normalizations: tuple[FeatureNormalization, ...]
    validation_labels: tuple[int, ...]
    label_counts: tuple[tuple[str, int], ...]
    class_weights: tuple[tuple[str, float], ...]
    regularization_evaluations: tuple[FoldRegularizationEvaluation, ...]


@dataclass(frozen=True, slots=True)
class EntryBehaviorFailure:
    code: str
    message_zh: str


@dataclass(frozen=True, slots=True)
class EntryBehaviorModelManifest:
    formula_version: str
    feature_version: str
    app_version: str
    seed: int
    label_counts: tuple[tuple[str, int], ...]
    sample_ids: tuple[str, ...]
    episode_ids: tuple[str, ...]
    data_start_utc_ms: int
    data_end_utc_ms: int
    feature_limit: int
    selected_c: float
    l1_ratio: float
    normalizations: tuple[FeatureNormalization, ...]
    temporal_folds: tuple[TemporalFoldAudit, ...]
    regularization_path: tuple[RegularizationPathSummary, ...]
    threshold_candidates: tuple[ResearchThresholdCandidate, ...]
    threshold_selection: ResearchThresholdCandidate | None
    validation_metrics: BehaviorModelMetrics
    test_episode_ids: tuple[str, ...]
    test_sample_ids: tuple[str, ...]
    test_metrics: BehaviorModelMetrics
    leave_episode_out_scores: tuple[LeaveEpisodeOutSimilarity, ...]
    dependency_versions: Mapping[str, str]
    label_fingerprint: str
    target: BehaviorModelTarget = BehaviorModelTarget.ENTRY_SELECTION
    positive_label: str = "ENTRY"
    negative_label: str = "REJECT"
    episode_kind: str = "MARKET"

    def __post_init__(self) -> None:
        target = BehaviorModelTarget(self.target)
        profile = behavior_model_profile(target)
        if (self.positive_label, self.negative_label) != (
            profile.positive_label,
            profile.negative_label,
        ):
            raise ValueError("behavior manifest labels must match its target")
        if self.episode_kind != profile.episode_kind:
            raise ValueError(
                "behavior manifest episode kind must match its target"
            )
        object.__setattr__(self, "target", target)


@dataclass(frozen=True, slots=True)
class EntryBehaviorModelVersion:
    model_version_id: str
    experiment_id: str
    setup_version_id: str
    grouping_version_id: str
    direction: str
    maturity: EntryBehaviorModelMaturity
    intercept: float
    stable_features: tuple[StableBehaviorFeature, ...]
    research_threshold: float | None
    applicability_threshold: float | None
    created_at: str
    manifest: EntryBehaviorModelManifest
    target: BehaviorModelTarget = BehaviorModelTarget.ENTRY_SELECTION

    def __post_init__(self) -> None:
        target = BehaviorModelTarget(self.target)
        if self.manifest.target is not target:
            raise ValueError("behavior model target must match its manifest target")
        object.__setattr__(self, "target", target)


@dataclass(frozen=True, slots=True)
class EntryBehaviorTrainingResult:
    experiment_id: str
    setup_version_id: str
    grouping_version_id: str
    direction: str
    status: EntryBehaviorExperimentStatus
    created_at: str
    failure: EntryBehaviorFailure | None
    model: EntryBehaviorModelVersion | None
    target: BehaviorModelTarget = BehaviorModelTarget.ENTRY_SELECTION

    def __post_init__(self) -> None:
        target = BehaviorModelTarget(self.target)
        status = EntryBehaviorExperimentStatus(self.status)
        if self.model is not None and self.model.target is not target:
            raise ValueError("behavior result target must match its model target")
        if status is EntryBehaviorExperimentStatus.COMPLETED:
            if self.failure is not None or self.model is None:
                raise ValueError(
                    "completed behavior result requires a model and no failure"
                )
        elif self.failure is None or self.model is not None:
            raise ValueError(
                "failed behavior result requires a failure and no model"
            )
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "target", target)


@dataclass(frozen=True, slots=True)
class EntryBehaviorScoreResult:
    model_version_id: str
    status: EntryBehaviorScoreStatus
    selection_tendency: float | None
    meets_research_threshold: bool | None
    structural_similarity: float
    applicability_threshold: float | None
    message_zh: str


def extract_entry_behavior_features(
    snapshots: Sequence[EntryStructuralFeatureSnapshot],
) -> tuple[BehaviorFeatureValue, ...]:
    if len(snapshots) != 3:
        raise ValueError("entry behavior features require exactly three timeframes")
    values: list[BehaviorFeatureValue] = []
    unavailable: list[str] = []
    for definition in ENTRY_BEHAVIOR_FEATURES:
        source = (
            snapshots[definition.timeframe_index]
            .group(definition.group_name)
            .feature(definition.source_name)
        )
        if not source.available or len(source.values) != 1:
            unavailable.append(
                f"{definition.feature_id}:{source.unavailable_reason or 'not_scalar'}"
            )
            continue
        value = float(source.values[0])
        if not math.isfinite(value):
            unavailable.append(f"{definition.feature_id}:non_finite_value")
            continue
        values.append(
            BehaviorFeatureValue(
                feature_id=definition.feature_id,
                name_zh=definition.name_zh,
                value=value,
            )
        )
    if unavailable:
        raise ValueError("行为模型指标不可计算：" + "；".join(unavailable))
    return tuple(values)


def score_behavior_features(
    model: EntryBehaviorModelVersion,
    features: Sequence[BehaviorFeatureValue],
    *,
    structural_similarity: float,
    formula_version: str = ENTRY_BEHAVIOR_FORMULA_VERSION,
) -> EntryBehaviorScoreResult:
    if str(formula_version) != model.manifest.formula_version:
        raise ValueError("behavior model formula version is incompatible")
    similarity = float(structural_similarity)
    if not math.isfinite(similarity) or not 0.0 <= similarity <= 100.0:
        raise ValueError(
            "structural_similarity must be a finite value in [0, 100]"
        )
    applicability_threshold = model.applicability_threshold
    if (
        model.maturity is not EntryBehaviorModelMaturity.FORMAL
        or applicability_threshold is None
    ):
        return EntryBehaviorScoreResult(
            model_version_id=model.model_version_id,
            status=EntryBehaviorScoreStatus.MODEL_NOT_FORMAL,
            selection_tendency=None,
            meets_research_threshold=None,
            structural_similarity=similarity,
            applicability_threshold=applicability_threshold,
            message_zh="当前版本尚未满足正式模型条件，只能查看验证记录。",
        )
    if similarity < applicability_threshold:
        score_name = (
            "开仓选择倾向"
            if model.target is BehaviorModelTarget.ENTRY_SELECTION
            else "立即平仓选择倾向"
        )
        return EntryBehaviorScoreResult(
            model_version_id=model.model_version_id,
            status=EntryBehaviorScoreStatus.OUT_OF_DOMAIN,
            selection_tendency=None,
            meets_research_threshold=None,
            structural_similarity=similarity,
            applicability_threshold=applicability_threshold,
            message_zh=(
                f"超出当前模型适用范围，不生成正式{score_name}分数。"
            ),
        )
    raw_values = {
        item.feature_id: float(item.value) for item in features
    }
    normalizations = {
        item.feature_id: item for item in model.manifest.normalizations
    }
    linear = model.intercept
    for stable in model.stable_features:
        if stable.feature_id not in raw_values:
            raise ValueError(
                f"behavior score is missing {stable.feature_id}"
            )
        value = raw_values[stable.feature_id]
        if not math.isfinite(value):
            raise ValueError("behavior score feature is non-finite")
        normalization = normalizations[stable.feature_id]
        standardized = float(
            np.clip(
                (value - normalization.median) / normalization.scale,
                -5.0,
                5.0,
            )
        )
        linear += stable.coefficient * standardized
    tendency = (
        1.0 / (1.0 + math.exp(-linear))
        if linear >= 0.0
        else math.exp(linear) / (1.0 + math.exp(linear))
    )
    return EntryBehaviorScoreResult(
        model_version_id=model.model_version_id,
        status=EntryBehaviorScoreStatus.COMPUTED,
        selection_tendency=tendency,
        meets_research_threshold=(
            None
            if model.research_threshold is None
            else tendency >= model.research_threshold
        ),
        structural_similarity=similarity,
        applicability_threshold=applicability_threshold,
        message_zh=(
            "已按模型版本计算开仓选择倾向。"
            if model.target is BehaviorModelTarget.ENTRY_SELECTION
            else "已按模型版本计算立即平仓选择倾向。"
        ),
    )


def score_entry_behavior_features(
    model: EntryBehaviorModelVersion,
    features: Sequence[BehaviorFeatureValue],
    *,
    structural_similarity: float,
    formula_version: str = ENTRY_BEHAVIOR_FORMULA_VERSION,
) -> EntryBehaviorScoreResult:
    if model.target is not BehaviorModelTarget.ENTRY_SELECTION:
        raise ValueError("entry behavior adapter only accepts entry models")
    return score_behavior_features(
        model,
        features,
        structural_similarity=structural_similarity,
        formula_version=formula_version,
    )


def entry_behavior_label_fingerprint(
    records: Sequence[tuple[str, str, int, str]],
) -> str:
    payload = "\n".join(
        f"{event_id}|{episode_id}|{int(cutoff)}|{label}"
        for event_id, episode_id, cutoff, label in records
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "BehaviorModelVersion",
    "BehaviorModelProfile",
    "BehaviorModelTarget",
    "BehaviorTrainingResult",
    "BehaviorTrainingRequest",
    "BehaviorTrainingSample",
    "ENTRY_BEHAVIOR_C_GRID",
    "ENTRY_BEHAVIOR_FEATURE_VERSION",
    "ENTRY_BEHAVIOR_FEATURES",
    "ENTRY_BEHAVIOR_FORMULA_VERSION",
    "ENTRY_BEHAVIOR_L1_RATIO",
    "ENTRY_BEHAVIOR_PROFILE",
    "EXIT_BEHAVIOR_FEATURES",
    "EXIT_BEHAVIOR_PROFILE",
    "BehaviorFeatureDefinition",
    "BehaviorFeatureValue",
    "BehaviorModelMetrics",
    "EntryBehaviorExperimentStatus",
    "EntryBehaviorFailure",
    "EntryBehaviorModelManifest",
    "EntryBehaviorModelMaturity",
    "EntryBehaviorModelVersion",
    "EntryBehaviorSample",
    "EntryBehaviorScoreResult",
    "EntryBehaviorScoreStatus",
    "EntryBehaviorTrainingRequest",
    "EntryBehaviorTrainingResult",
    "FeatureNormalization",
    "FoldRegularizationEvaluation",
    "LeaveEpisodeOutSimilarity",
    "RegularizationPathSummary",
    "ResearchThresholdCandidate",
    "StableBehaviorFeature",
    "TemporalFoldAudit",
    "behavior_model_profile",
    "entry_behavior_label_fingerprint",
    "extract_entry_behavior_features",
    "score_entry_behavior_features",
    "score_behavior_features",
]


# Stable generic names for the shared engine.  The Entry-prefixed names remain
# compatibility aliases for callers and persisted v1.6 entry-model payloads.
BehaviorTrainingRequest = EntryBehaviorTrainingRequest
BehaviorTrainingSample = EntryBehaviorSample
BehaviorTrainingResult = EntryBehaviorTrainingResult
BehaviorModelVersion = EntryBehaviorModelVersion
