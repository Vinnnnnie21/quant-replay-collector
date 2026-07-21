from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import StrEnum
import json
import math
from typing import Callable, Iterable, Mapping

import numpy as np

from .bootstrap import (
    DEFAULT_RESAMPLE_BATCH_SIZE,
    MAX_BATCH_WORK_ITEMS,
    MAX_RESAMPLE_WORK_ITEMS,
    validate_resampling_request,
)
from .cancellation import raise_if_research_cancelled
from .multiple_testing import benjamini_hochberg


ENTRY_OUTCOME_HORIZONS = (1, 3, 5, 10, 20)
ENTRY_MATCH_SENSITIVITY_THRESHOLDS = (70.0, 75.0, 80.0)
ENTRY_MATCH_PRIMARY_THRESHOLD = 75.0
ENTRY_OUTCOME_BOOTSTRAP_DRAWS = 5_000
ENTRY_OUTCOME_PERMUTATION_DRAWS = 10_000
ENTRY_OUTCOME_FORMULA_VERSION = "entry-outcome-comparison-v1"


class EntryOutcomeMetric(StrEnum):
    CLOSE_RETURN = "close_return"
    MFE = "mfe"
    MAE = "mae"


class EntryOutcomeEvidenceStage(StrEnum):
    INSUFFICIENT = "INSUFFICIENT"
    EXPLORATORY = "EXPLORATORY"
    FORMAL = "FORMAL"


class EntryOutcomeEvidenceStatus(StrEnum):
    INSUFFICIENT = "INSUFFICIENT"
    NO_RELIABLE_DIFFERENCE = "NO_RELIABLE_DIFFERENCE"
    DIFFERENCE_EVIDENCE = "DIFFERENCE_EVIDENCE"


@dataclass(frozen=True, slots=True)
class EntryOutcomeComparisonRequest:
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
class EntryDecisionForComparison:
    decision_event_id: str
    label: str
    setup_version_id: str
    grouping_version_id: str
    episode_id: str
    symbol: str
    direction: str
    decision_timeframe: str
    decision_cutoff_utc_ms: int
    blind_judgment_id: str | None = None

    def __post_init__(self) -> None:
        label = str(self.label).upper()
        direction = str(self.direction).upper()
        if label not in {"ENTRY", "REJECT"}:
            raise ValueError("comparison label must be ENTRY or REJECT")
        if direction not in {"LONG", "SHORT"}:
            raise ValueError("comparison direction must be LONG or SHORT")
        for field_name in (
            "decision_event_id",
            "setup_version_id",
            "grouping_version_id",
            "episode_id",
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
class EntryPairSimilarity:
    entry_decision_event_id: str
    reject_decision_event_id: str
    similarity: float

    def __post_init__(self) -> None:
        similarity = float(self.similarity)
        if not math.isfinite(similarity) or not 0.0 <= similarity <= 100.0:
            raise ValueError("pair similarity must be finite and between 0 and 100")
        object.__setattr__(self, "similarity", similarity)


@dataclass(frozen=True, slots=True)
class MatchedEntryPair:
    entry_decision_event_id: str
    reject_decision_event_id: str
    entry_episode_id: str
    reject_episode_id: str
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
class EntryPairOutcomeDifference:
    entry_decision_event_id: str
    reject_decision_event_id: str
    episode_id: str
    value: float
    counterparty_episode_id: str | None = None

    def __post_init__(self) -> None:
        number = float(self.value)
        if not math.isfinite(number):
            raise ValueError("paired outcome difference must be finite")
        object.__setattr__(self, "value", number)


@dataclass(frozen=True, slots=True)
class EntryEpisodeOutcomeDifference:
    episode_id: str
    value: float
    pair_count: int
    source_episode_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_episode_ids",
            tuple(str(item) for item in self.source_episode_ids),
        )


@dataclass(frozen=True, slots=True)
class EntryEpisodeDifferenceSummary:
    pair_count: int
    episode_count: int
    episodes: tuple[EntryEpisodeOutcomeDifference, ...]
    median_difference: float | None
    mean_difference: float | None
    rank_biserial: float | None


@dataclass(frozen=True, slots=True)
class EntryOutcomeInference:
    ci_low: float
    ci_high: float
    p_value: float
    random_seed: int
    bootstrap_draws: int
    permutation_draws: int


@dataclass(frozen=True, slots=True)
class EntryOutcomeMatrixCell:
    horizon_bars: int
    metric: EntryOutcomeMetric
    stage: EntryOutcomeEvidenceStage
    evidence_status: EntryOutcomeEvidenceStatus
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
    differences: tuple[EntryPairOutcomeDifference, ...]
    episodes: tuple[EntryEpisodeOutcomeDifference, ...]


@dataclass(frozen=True, slots=True)
class EntryOutcomeThresholdResult:
    similarity_threshold: float
    pairs: tuple[MatchedEntryPair, ...]
    matrix: tuple[EntryOutcomeMatrixCell, ...]

    @property
    def stage(self) -> EntryOutcomeEvidenceStage:
        if not self.matrix:
            return EntryOutcomeEvidenceStage.INSUFFICIENT
        return min(
            (cell.stage for cell in self.matrix),
            key=(
                EntryOutcomeEvidenceStage.INSUFFICIENT,
                EntryOutcomeEvidenceStage.EXPLORATORY,
                EntryOutcomeEvidenceStage.FORMAL,
            ).index,
        )


@dataclass(frozen=True, slots=True)
class EntryOutcomeComparisonResult:
    comparison_id: str
    setup_version_id: str
    grouping_version_id: str
    direction: str
    formula_version: str
    feature_version: str
    random_seed: int
    eligible_decisions: tuple[EntryDecisionForComparison, ...]
    input_feature_fingerprint: str
    sensitivities: tuple[EntryOutcomeThresholdResult, ...]
    created_at: str

    def __post_init__(self) -> None:
        direction = str(self.direction).upper()
        if direction not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT")
        fingerprint = str(self.input_feature_fingerprint)
        if len(fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in fingerprint
        ):
            raise ValueError("input feature fingerprint must be lowercase SHA-256")
        decisions = tuple(self.eligible_decisions)
        decision_ids = tuple(item.decision_event_id for item in decisions)
        if len(set(decision_ids)) != len(decision_ids):
            raise ValueError("eligible decision_event_id values must be unique")
        decision_by_id = {
            item.decision_event_id: item for item in decisions
        }
        if decisions and any(
            item.blind_judgment_id is None for item in decisions
        ):
            raise ValueError("eligible decisions require blind judgment identity")
        for decision in decisions:
            if (
                decision.setup_version_id != self.setup_version_id
                or decision.grouping_version_id != self.grouping_version_id
                or decision.direction != direction
            ):
                raise ValueError("eligible decision context does not match result")
        sensitivities = tuple(self.sensitivities)
        if tuple(
            item.similarity_threshold for item in sensitivities
        ) != ENTRY_MATCH_SENSITIVITY_THRESHOLDS:
            raise ValueError("result requires three preregistered sensitivities")
        expected_cells = tuple(
            (horizon, metric)
            for horizon in ENTRY_OUTCOME_HORIZONS
            for metric in EntryOutcomeMetric
        )
        for sensitivity in sensitivities:
            actual_cells = tuple(
                (cell.horizon_bars, cell.metric) for cell in sensitivity.matrix
            )
            if actual_cells != expected_cells:
                raise ValueError("each sensitivity requires the complete 15-cell matrix")
            if any(
                pair.similarity_threshold != sensitivity.similarity_threshold
                for pair in sensitivity.pairs
            ):
                raise ValueError("matched pair threshold does not match sensitivity")
            used_entries: set[str] = set()
            used_rejects: set[str] = set()
            for pair in sensitivity.pairs:
                entry = decision_by_id.get(pair.entry_decision_event_id)
                reject = decision_by_id.get(pair.reject_decision_event_id)
                if entry is None or reject is None:
                    raise ValueError("matched pair is outside eligible decision universe")
                if entry.label != "ENTRY" or reject.label != "REJECT":
                    raise ValueError("matched pair label identity is invalid")
                if (
                    entry.episode_id != pair.entry_episode_id
                    or reject.episode_id != pair.reject_episode_id
                    or entry.symbol != pair.symbol
                    or reject.symbol != pair.symbol
                    or entry.decision_timeframe != pair.decision_timeframe
                    or reject.decision_timeframe != pair.decision_timeframe
                ):
                    raise ValueError("matched pair context differs from eligible decision")
                if pair.similarity < sensitivity.similarity_threshold:
                    raise ValueError("matched pair is below its similarity threshold")
                if (
                    pair.entry_decision_event_id in used_entries
                    or pair.reject_decision_event_id in used_rejects
                ):
                    raise ValueError("matched pairs must not reuse a decision")
                used_entries.add(pair.entry_decision_event_id)
                used_rejects.add(pair.reject_decision_event_id)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "random_seed", int(self.random_seed))
        object.__setattr__(self, "eligible_decisions", decisions)
        object.__setattr__(self, "sensitivities", sensitivities)

    @property
    def primary(self) -> EntryOutcomeThresholdResult:
        return next(
            item
            for item in self.sensitivities
            if item.similarity_threshold == ENTRY_MATCH_PRIMARY_THRESHOLD
        )

    def matrix_records(self) -> tuple[dict[str, object], ...]:
        """Return every primary cell with stable English machine keys."""

        return tuple(
            {
                "comparison_id": self.comparison_id,
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


@dataclass(frozen=True, slots=True)
class OutcomeBar:
    open_time_utc_ms: int
    open: float
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        prices = tuple(float(value) for value in (self.open, self.high, self.low, self.close))
        if not all(math.isfinite(value) and value > 0.0 for value in prices):
            raise ValueError("outcome bar prices must be finite and positive")
        if float(self.high) < max(float(self.open), float(self.low), float(self.close)):
            raise ValueError("outcome bar high is below another price")
        if float(self.low) > min(float(self.open), float(self.high), float(self.close)):
            raise ValueError("outcome bar low is above another price")


@dataclass(frozen=True, slots=True)
class EntryOutcomeValue:
    horizon_bars: int
    metric: EntryOutcomeMetric
    value: float


@dataclass(frozen=True, slots=True)
class EntryOutcomePath:
    direction: str
    execution_price: float | None
    outcomes: tuple[EntryOutcomeValue, ...]
    unavailable_reason: str | None = None

    @property
    def available(self) -> bool:
        return self.execution_price is not None

    def value(
        self,
        horizon_bars: int,
        metric: EntryOutcomeMetric | str,
    ) -> float | None:
        selected_metric = EntryOutcomeMetric(metric)
        return next(
            (
                item.value
                for item in self.outcomes
                if item.horizon_bars == int(horizon_bars)
                and item.metric is selected_metric
            ),
            None,
        )


def calculate_entry_outcome_path(
    *,
    direction: str,
    decision_cutoff_utc_ms: int,
    bars: Iterable[OutcomeBar],
    decision_interval_ms: int | None = None,
    actual_fill_price: float | None = None,
) -> EntryOutcomePath:
    """Calculate the fixed, gross post-decision path from the next bar open."""

    # The fill is accepted only so callers can keep the two price concepts
    # explicit. It must never become a fallback research execution price.
    _ = actual_fill_price
    normalized_direction = str(direction).upper()
    if normalized_direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    future = tuple(
        sorted(
            (
                bar
                for bar in bars
                if int(bar.open_time_utc_ms) > int(decision_cutoff_utc_ms)
            ),
            key=lambda bar: int(bar.open_time_utc_ms),
        )
    )
    if decision_interval_ms is not None:
        interval_ms = int(decision_interval_ms)
        if interval_ms <= 0:
            raise ValueError("decision_interval_ms must be positive")
        expected_open = int(decision_cutoff_utc_ms) + 1
        contiguous = []
        for bar in future:
            if int(bar.open_time_utc_ms) != expected_open:
                break
            contiguous.append(bar)
            expected_open += interval_ms
        future = tuple(contiguous)
    if not future:
        return EntryOutcomePath(
            direction=normalized_direction,
            execution_price=None,
            outcomes=(),
            unavailable_reason="next_decision_bar_missing",
        )
    execution_price = float(future[0].open)
    sign = 1.0 if normalized_direction == "LONG" else -1.0
    outcomes: list[EntryOutcomeValue] = []
    for horizon in ENTRY_OUTCOME_HORIZONS:
        if len(future) < horizon:
            continue
        window = future[:horizon]
        close_return = sign * (float(window[-1].close) / execution_price - 1.0)
        if normalized_direction == "LONG":
            mfe = max(float(bar.high) for bar in window) / execution_price - 1.0
            mae = min(float(bar.low) for bar in window) / execution_price - 1.0
        else:
            mfe = 1.0 - min(float(bar.low) for bar in window) / execution_price
            mae = 1.0 - max(float(bar.high) for bar in window) / execution_price
        outcomes.extend(
            (
                EntryOutcomeValue(horizon, EntryOutcomeMetric.CLOSE_RETURN, close_return),
                EntryOutcomeValue(horizon, EntryOutcomeMetric.MFE, mfe),
                EntryOutcomeValue(horizon, EntryOutcomeMetric.MAE, mae),
            )
        )
    return EntryOutcomePath(
        direction=normalized_direction,
        execution_price=execution_price,
        outcomes=tuple(outcomes),
    )


def global_match_entry_reject(
    decisions: Iterable[EntryDecisionForComparison],
    pair_similarities: Iterable[EntryPairSimilarity],
    *,
    similarity_threshold: float = 75.0,
) -> tuple[MatchedEntryPair, ...]:
    """Return deterministic maximum-cardinality, minimum-distance pairs."""

    threshold = float(similarity_threshold)
    if not math.isfinite(threshold) or not 0.0 <= threshold <= 100.0:
        raise ValueError("similarity_threshold must be between 0 and 100")
    samples = tuple(decisions)
    by_id = {sample.decision_event_id: sample for sample in samples}
    if len(by_id) != len(samples):
        raise ValueError("comparison decision_event_id values must be unique")
    if not samples:
        return ()
    for field_name in ("setup_version_id", "grouping_version_id", "direction"):
        if len({getattr(sample, field_name) for sample in samples}) != 1:
            raise ValueError(f"comparison requires one {field_name}")
    score_by_pair: dict[tuple[str, str], float] = {}
    for item in pair_similarities:
        key = (
            str(item.entry_decision_event_id),
            str(item.reject_decision_event_id),
        )
        if key in score_by_pair:
            raise ValueError("pair similarities must be unique")
        entry = by_id.get(key[0])
        reject = by_id.get(key[1])
        if entry is None or reject is None:
            raise ValueError("pair similarity references an unknown decision")
        if entry.label != "ENTRY" or reject.label != "REJECT":
            raise ValueError("pair similarity must link ENTRY to REJECT")
        if (entry.symbol, entry.decision_timeframe) != (
            reject.symbol,
            reject.decision_timeframe,
        ):
            continue
        score_by_pair[key] = item.similarity

    strata = sorted(
        {
            (sample.symbol, sample.decision_timeframe)
            for sample in samples
        }
    )
    matched: list[MatchedEntryPair] = []
    for symbol, timeframe in strata:
        entries = sorted(
            (
                sample
                for sample in samples
                if sample.label == "ENTRY"
                and (sample.symbol, sample.decision_timeframe)
                == (symbol, timeframe)
            ),
            key=lambda sample: sample.decision_event_id,
        )
        rejects = sorted(
            (
                sample
                for sample in samples
                if sample.label == "REJECT"
                and (sample.symbol, sample.decision_timeframe)
                == (symbol, timeframe)
            ),
            key=lambda sample: sample.decision_event_id,
        )
        matched.extend(
            _match_stratum(
                entries,
                rejects,
                score_by_pair,
                threshold,
            )
        )
    return tuple(
        sorted(
            matched,
            key=lambda pair: (
                pair.entry_decision_event_id,
                pair.reject_decision_event_id,
            ),
        )
    )


def classify_entry_outcome_evidence_stage(
    *,
    pair_count: int,
    episode_count: int,
) -> EntryOutcomeEvidenceStage:
    pairs = int(pair_count)
    episodes = int(episode_count)
    if pairs < 10 or episodes < 5:
        return EntryOutcomeEvidenceStage.INSUFFICIENT
    if pairs >= 30 and episodes >= 10:
        return EntryOutcomeEvidenceStage.FORMAL
    return EntryOutcomeEvidenceStage.EXPLORATORY


def aggregate_entry_episode_differences(
    differences: Iterable[EntryPairOutcomeDifference],
) -> EntryEpisodeDifferenceSummary:
    values = tuple(differences)
    parent: dict[str, str] = {}

    def find(episode_id: str) -> str:
        parent.setdefault(episode_id, episode_id)
        while parent[episode_id] != episode_id:
            parent[episode_id] = parent[parent[episode_id]]
            episode_id = parent[episode_id]
        return episode_id

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        root, child = sorted((left_root, right_root))
        parent[child] = root

    for item in values:
        primary_episode = str(item.episode_id)
        find(primary_episode)
        if item.counterparty_episode_id:
            union(primary_episode, str(item.counterparty_episode_id))
    grouped: dict[str, list[float]] = {}
    for item in values:
        grouped.setdefault(find(str(item.episode_id)), []).append(
            float(item.value)
        )
    members: dict[str, list[str]] = {}
    for episode_id in parent:
        members.setdefault(find(episode_id), []).append(episode_id)
    episodes = tuple(
        EntryEpisodeOutcomeDifference(
            episode_id=episode_id,
            value=float(np.median(grouped[episode_id])),
            pair_count=len(grouped[episode_id]),
            source_episode_ids=tuple(sorted(members[episode_id])),
        )
        for episode_id in sorted(grouped)
    )
    if not episodes:
        return EntryEpisodeDifferenceSummary(0, 0, (), None, None, None)
    episode_values = tuple(item.value for item in episodes)
    positive = sum(value > 0.0 for value in episode_values)
    negative = sum(value < 0.0 for value in episode_values)
    nonzero = positive + negative
    return EntryEpisodeDifferenceSummary(
        pair_count=len(values),
        episode_count=len(episodes),
        episodes=episodes,
        median_difference=float(np.median(episode_values)),
        mean_difference=math.fsum(episode_values) / len(episode_values),
        rank_biserial=(
            (positive - negative) / nonzero if nonzero else 0.0
        ),
    )


def infer_entry_episode_differences(
    summary: EntryEpisodeDifferenceSummary,
    *,
    random_seed: int,
    bootstrap_draws: int = ENTRY_OUTCOME_BOOTSTRAP_DRAWS,
    permutation_draws: int = ENTRY_OUTCOME_PERMUTATION_DRAWS,
    cancelled: Callable[[], bool] | None = None,
) -> EntryOutcomeInference:
    """Run bounded episode-level median bootstrap and sign-flip inference."""

    values = np.asarray(
        [item.value for item in summary.episodes],
        dtype=float,
    )
    if len(values) < 2 or not np.isfinite(values).all():
        raise ValueError("formal episode inference requires finite episode values")
    boot_count, _boot_budget, _boot_work = validate_resampling_request(
        "entry outcome cluster bootstrap",
        bootstrap_draws,
        len(values),
        max_work_items=MAX_RESAMPLE_WORK_ITEMS,
    )
    permutation_count, _perm_budget, _perm_work = validate_resampling_request(
        "entry outcome sign flip",
        permutation_draws,
        len(values),
        max_work_items=MAX_RESAMPLE_WORK_ITEMS,
    )
    seed = int(random_seed)
    bootstrap_seed, permutation_seed = np.random.SeedSequence(seed).spawn(2)
    bootstrap_rng = np.random.default_rng(bootstrap_seed)
    permutation_rng = np.random.default_rng(permutation_seed)
    bootstrap_batch = min(
        boot_count,
        DEFAULT_RESAMPLE_BATCH_SIZE,
        max(1, MAX_BATCH_WORK_ITEMS // len(values)),
    )
    bootstrap_statistics = np.empty(boot_count, dtype=float)
    raise_if_research_cancelled(cancelled)
    for start in range(0, boot_count, bootstrap_batch):
        stop = min(boot_count, start + bootstrap_batch)
        sampled = bootstrap_rng.choice(
            values,
            size=(stop - start, len(values)),
            replace=True,
        )
        bootstrap_statistics[start:stop] = np.median(sampled, axis=1)
        raise_if_research_cancelled(cancelled)
    ci_low, ci_high = np.quantile(bootstrap_statistics, (0.025, 0.975))

    observed = float(np.median(values))
    permutation_batch = min(
        permutation_count,
        DEFAULT_RESAMPLE_BATCH_SIZE,
        max(1, MAX_BATCH_WORK_ITEMS // len(values)),
    )
    exceedances = 0
    for start in range(0, permutation_count, permutation_batch):
        stop = min(permutation_count, start + permutation_batch)
        signs = permutation_rng.choice(
            np.asarray((-1.0, 1.0)),
            size=(stop - start, len(values)),
        )
        simulated = np.median(signs * values, axis=1)
        exceedances += int(np.count_nonzero(np.abs(simulated) >= abs(observed)))
        raise_if_research_cancelled(cancelled)
    return EntryOutcomeInference(
        ci_low=float(ci_low),
        ci_high=float(ci_high),
        p_value=float((exceedances + 1) / (permutation_count + 1)),
        random_seed=seed,
        bootstrap_draws=boot_count,
        permutation_draws=permutation_count,
    )


def adjust_entry_outcome_family(
    p_values: Iterable[float | None],
) -> tuple[float | None, ...]:
    values = tuple(p_values)
    if len(values) != 15:
        raise ValueError("entry outcome BH requires exactly 15 p-values")
    normalized: list[float] = []
    for value in values:
        if value is None:
            normalized.append(1.0)
            continue
        number = float(value)
        if not math.isfinite(number) or not 0.0 <= number <= 1.0:
            raise ValueError("entry outcome p-values must be between 0 and 1")
        normalized.append(number)
    adjusted = benjamini_hochberg(normalized, alpha=0.05)
    return tuple(
        None if original is None else float(row["q_value"])
        for original, row in zip(values, adjusted, strict=True)
    )


def classify_entry_outcome_evidence_status(
    *,
    stage: EntryOutcomeEvidenceStage,
    q_value: float | None,
    ci_low: float | None,
    ci_high: float | None,
) -> EntryOutcomeEvidenceStatus:
    if stage is not EntryOutcomeEvidenceStage.FORMAL:
        return EntryOutcomeEvidenceStatus.INSUFFICIENT
    interval_excludes_zero = bool(
        ci_low is not None
        and ci_high is not None
        and (float(ci_low) > 0.0 or float(ci_high) < 0.0)
    )
    if q_value is not None and float(q_value) < 0.05 and interval_excludes_zero:
        return EntryOutcomeEvidenceStatus.DIFFERENCE_EVIDENCE
    return EntryOutcomeEvidenceStatus.NO_RELIABLE_DIFFERENCE


def build_entry_outcome_matrix(
    pairs: Iterable[MatchedEntryPair],
    outcomes_by_event: Mapping[str, EntryOutcomePath],
    *,
    random_seed: int,
    bootstrap_draws: int = ENTRY_OUTCOME_BOOTSTRAP_DRAWS,
    permutation_draws: int = ENTRY_OUTCOME_PERMUTATION_DRAWS,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[EntryOutcomeMatrixCell, ...]:
    selected_pairs = tuple(pairs)
    provisional: list[EntryOutcomeMatrixCell] = []
    for horizon in ENTRY_OUTCOME_HORIZONS:
        for metric_index, metric in enumerate(EntryOutcomeMetric):
            differences = []
            for pair in selected_pairs:
                entry_path = outcomes_by_event.get(
                    pair.entry_decision_event_id
                )
                reject_path = outcomes_by_event.get(
                    pair.reject_decision_event_id
                )
                if entry_path is None or reject_path is None:
                    continue
                entry_value = entry_path.value(horizon, metric)
                reject_value = reject_path.value(horizon, metric)
                if entry_value is None or reject_value is None:
                    continue
                differences.append(
                    EntryPairOutcomeDifference(
                        entry_decision_event_id=(
                            pair.entry_decision_event_id
                        ),
                        reject_decision_event_id=(
                            pair.reject_decision_event_id
                        ),
                        episode_id=pair.entry_episode_id,
                        value=float(entry_value) - float(reject_value),
                        counterparty_episode_id=pair.reject_episode_id,
                    )
                )
            summary = aggregate_entry_episode_differences(differences)
            stage = classify_entry_outcome_evidence_stage(
                pair_count=summary.pair_count,
                episode_count=summary.episode_count,
            )
            inference = None
            if stage is EntryOutcomeEvidenceStage.FORMAL:
                cell_seed = int(
                    np.random.SeedSequence(
                        (int(random_seed), int(horizon), metric_index)
                    ).generate_state(1)[0]
                )
                inference = infer_entry_episode_differences(
                    summary,
                    random_seed=cell_seed,
                    bootstrap_draws=bootstrap_draws,
                    permutation_draws=permutation_draws,
                    cancelled=cancelled,
                )
            provisional.append(
                EntryOutcomeMatrixCell(
                    horizon_bars=horizon,
                    metric=metric,
                    stage=stage,
                    evidence_status=(
                        EntryOutcomeEvidenceStatus.INSUFFICIENT
                        if inference is None
                        else EntryOutcomeEvidenceStatus.NO_RELIABLE_DIFFERENCE
                    ),
                    pair_count=summary.pair_count,
                    episode_count=summary.episode_count,
                    median_difference=summary.median_difference,
                    mean_difference=summary.mean_difference,
                    rank_biserial=summary.rank_biserial,
                    ci_low=None if inference is None else inference.ci_low,
                    ci_high=None if inference is None else inference.ci_high,
                    p_value=None if inference is None else inference.p_value,
                    q_value=None,
                    random_seed=(
                        None if inference is None else inference.random_seed
                    ),
                    differences=tuple(differences),
                    episodes=summary.episodes,
                )
            )
    q_values = adjust_entry_outcome_family(
        cell.p_value for cell in provisional
    )
    cells = []
    for cell, q_value in zip(provisional, q_values, strict=True):
        status = classify_entry_outcome_evidence_status(
            stage=cell.stage,
            q_value=q_value,
            ci_low=cell.ci_low,
            ci_high=cell.ci_high,
        )
        cells.append(
            replace(
                cell,
                q_value=q_value,
                evidence_status=status,
            )
        )
    return tuple(cells)


def entry_outcome_result_to_json(
    result: EntryOutcomeComparisonResult,
) -> str:
    return json.dumps(
        asdict(result),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def entry_outcome_result_from_json(
    payload: str,
) -> EntryOutcomeComparisonResult:
    raw = json.loads(payload)
    sensitivities = []
    for sensitivity in raw["sensitivities"]:
        cells = []
        for cell in sensitivity["matrix"]:
            cells.append(
                EntryOutcomeMatrixCell(
                    horizon_bars=int(cell["horizon_bars"]),
                    metric=EntryOutcomeMetric(cell["metric"]),
                    stage=EntryOutcomeEvidenceStage(cell["stage"]),
                    evidence_status=EntryOutcomeEvidenceStatus(
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
                        EntryPairOutcomeDifference(**item)
                        for item in cell["differences"]
                    ),
                    episodes=tuple(
                        EntryEpisodeOutcomeDifference(**item)
                        for item in cell["episodes"]
                    ),
                )
            )
        sensitivities.append(
            EntryOutcomeThresholdResult(
                similarity_threshold=float(
                    sensitivity["similarity_threshold"]
                ),
                pairs=tuple(
                    MatchedEntryPair(**item)
                    for item in sensitivity["pairs"]
                ),
                matrix=tuple(cells),
            )
        )
    return EntryOutcomeComparisonResult(
        comparison_id=str(raw["comparison_id"]),
        setup_version_id=str(raw["setup_version_id"]),
        grouping_version_id=str(raw["grouping_version_id"]),
        direction=str(raw["direction"]),
        formula_version=str(raw["formula_version"]),
        feature_version=str(raw["feature_version"]),
        random_seed=int(raw["random_seed"]),
        eligible_decisions=tuple(
            EntryDecisionForComparison(**item)
            for item in raw["eligible_decisions"]
        ),
        input_feature_fingerprint=str(raw["input_feature_fingerprint"]),
        sensitivities=tuple(sensitivities),
        created_at=str(raw["created_at"]),
    )


def _match_stratum(
    entries: list[EntryDecisionForComparison],
    rejects: list[EntryDecisionForComparison],
    score_by_pair: dict[tuple[str, str], float],
    threshold: float,
) -> list[MatchedEntryPair]:
    if not entries or not rejects:
        return []
    rows_are_entries = len(entries) <= len(rejects)
    row_samples = entries if rows_are_entries else rejects
    column_samples = rejects if rows_are_entries else entries
    row_count = len(row_samples)
    real_column_count = len(column_samples)
    # One dummy column per row represents an unmatched decision. The penalty
    # exceeds the largest possible aggregate change in eligible distances, so
    # the assignment maximizes cardinality first and minimizes distance second.
    unmatched_cost = float(row_count + 1)
    ineligible_cost = unmatched_cost * 2.0
    costs = np.full(
        (row_count, real_column_count + row_count),
        unmatched_cost,
        dtype=float,
    )
    costs[:, :real_column_count] = ineligible_cost
    eligible: dict[tuple[int, int], float] = {}
    for row_index, row_sample in enumerate(row_samples):
        for column_index, column_sample in enumerate(column_samples):
            entry = row_sample if rows_are_entries else column_sample
            reject = column_sample if rows_are_entries else row_sample
            similarity = score_by_pair.get(
                (entry.decision_event_id, reject.decision_event_id)
            )
            if similarity is None or similarity < threshold:
                continue
            distance = 1.0 - similarity / 100.0
            eligible[(row_index, column_index)] = similarity
            costs[row_index, column_index] = distance
    row_indices, column_indices = _solve_assignment(costs)
    result = []
    for row_index, column_index in zip(
        row_indices.tolist(),
        column_indices.tolist(),
        strict=True,
    ):
        similarity = eligible.get((row_index, column_index))
        if similarity is None:
            continue
        row_sample = row_samples[row_index]
        column_sample = column_samples[column_index]
        entry = row_sample if rows_are_entries else column_sample
        reject = column_sample if rows_are_entries else row_sample
        result.append(
            MatchedEntryPair(
                entry_decision_event_id=entry.decision_event_id,
                reject_decision_event_id=reject.decision_event_id,
                entry_episode_id=entry.episode_id,
                reject_episode_id=reject.episode_id,
                symbol=entry.symbol,
                decision_timeframe=entry.decision_timeframe,
                similarity=similarity,
                context_distance=1.0 - similarity / 100.0,
                similarity_threshold=threshold,
            )
        )
    return result


def _solve_assignment(costs):
    """Keep SciPy outside the analysis-shell import path."""
    from scipy.optimize import linear_sum_assignment

    return linear_sum_assignment(costs)


__all__ = [
    "ENTRY_OUTCOME_HORIZONS",
    "ENTRY_MATCH_PRIMARY_THRESHOLD",
    "ENTRY_MATCH_SENSITIVITY_THRESHOLDS",
    "ENTRY_OUTCOME_BOOTSTRAP_DRAWS",
    "ENTRY_OUTCOME_FORMULA_VERSION",
    "ENTRY_OUTCOME_PERMUTATION_DRAWS",
    "EntryDecisionForComparison",
    "EntryOutcomeEvidenceStage",
    "EntryOutcomeEvidenceStatus",
    "EntryOutcomeMetric",
    "EntryOutcomeInference",
    "EntryOutcomeMatrixCell",
    "EntryOutcomeComparisonResult",
    "EntryOutcomeComparisonRequest",
    "EntryOutcomeThresholdResult",
    "EntryOutcomePath",
    "EntryOutcomeValue",
    "EntryPairSimilarity",
    "EntryPairOutcomeDifference",
    "EntryEpisodeDifferenceSummary",
    "EntryEpisodeOutcomeDifference",
    "MatchedEntryPair",
    "OutcomeBar",
    "calculate_entry_outcome_path",
    "aggregate_entry_episode_differences",
    "adjust_entry_outcome_family",
    "classify_entry_outcome_evidence_stage",
    "classify_entry_outcome_evidence_status",
    "build_entry_outcome_matrix",
    "global_match_entry_reject",
    "infer_entry_episode_differences",
    "entry_outcome_result_from_json",
    "entry_outcome_result_to_json",
]
