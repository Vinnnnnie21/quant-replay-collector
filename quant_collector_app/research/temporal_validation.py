
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

import pandas as pd

DEFAULT_LABEL_HORIZON_BARS = 1


@dataclass
class SplitResult:
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    summary: dict[str, Any]
    warnings: list[str]

    def __getitem__(self, key: str) -> Any:
        if key == "train":
            return self.train
        if key in {"validation", "val"}:
            return self.validation
        if key == "test":
            return self.test
        if key == "summary":
            return self.summary
        if key == "warnings":
            return self.warnings
        if key == "split_method":
            return self.summary.get("split_method")
        if key == "integrity_report":
            return self.summary.get("integrity_report", self.summary)
        raise KeyError(key)

    def as_dict(self) -> dict[str, Any]:
        return {
            "train": self.train,
            "val": self.validation,
            "validation": self.validation,
            "test": self.test,
            "summary": self.summary,
            "warnings": self.warnings,
            "split_method": self.summary.get("split_method"),
            "integrity_report": self.summary.get("integrity_report", self.summary),
        }


@dataclass
class WalkForwardSplitResult:
    folds: list[SplitResult]
    summary: dict[str, Any]
    warnings: list[str]

    def __iter__(self) -> Iterator[SplitResult]:
        return iter(self.folds)

    def __len__(self) -> int:
        return len(self.folds)

    def __getitem__(self, index: int) -> SplitResult:
        return self.folds[index]


def _resolve_bar_col(df: pd.DataFrame) -> str:
    if not isinstance(df, pd.DataFrame):
        raise ValueError("df must be a pandas DataFrame")
    if "decision_bar_index" in df.columns:
        column = "decision_bar_index"
    elif "bar_index" in df.columns:
        column = "bar_index"
    else:
        raise ValueError("DataFrame must contain decision_bar_index or bar_index")
    values = pd.to_numeric(df[column], errors="coerce")
    if values.isna().any():
        raise ValueError(f"{column} must not contain NaN")
    return column


def ensure_label_window(
    df: pd.DataFrame,
    horizon_bars: int,
    bar_col: str | None = None,
    label_start_col: str = "label_start_bar",
    label_end_col: str = "label_end_bar",
    *,
    allow_overwrite: bool = False,
) -> pd.DataFrame:
    horizon = int(horizon_bars)
    if horizon <= 0:
        raise ValueError("horizon_bars must be positive")
    if not isinstance(df, pd.DataFrame):
        raise ValueError("df must be a pandas DataFrame")
    output = df.copy()
    resolved_bar_col = bar_col or _resolve_bar_col(output)
    if resolved_bar_col not in output.columns:
        raise ValueError(f"Missing bar column: {resolved_bar_col}")
    has_window = label_start_col in output.columns and label_end_col in output.columns
    if has_window and not allow_overwrite:
        _validate_label_window_columns(output, label_start_col, label_end_col)
        return output
    bars = pd.to_numeric(output[resolved_bar_col], errors="coerce")
    if bars.isna().any():
        raise ValueError(f"{resolved_bar_col} must be numeric")
    output[label_start_col] = (bars + 1).astype(int)
    output[label_end_col] = (bars + horizon).astype(int)
    return output


def windows_overlap(start_a: Any, end_a: Any, start_b: Any, end_b: Any) -> bool:
    """Closed-interval overlap check; missing values return False."""
    values = (start_a, end_a, start_b, end_b)
    if any(_is_missing(value) for value in values):
        return False
    a_start, a_end, b_start, b_end = (float(value) for value in values)
    return max(a_start, b_start) <= min(a_end, b_end)


def _ordered_samples(data: pd.DataFrame, bar_col: str | None = None) -> pd.DataFrame:
    if not isinstance(data, pd.DataFrame):
        raise ValueError("data must be a pandas DataFrame")
    if "observation_id" not in data.columns:
        raise ValueError("Missing required columns: observation_id")
    resolved_bar_col = bar_col or _resolve_bar_col(data)
    if resolved_bar_col not in data.columns:
        raise ValueError(f"Missing bar column: {resolved_bar_col}")
    values = pd.to_numeric(data[resolved_bar_col], errors="coerce")
    if values.isna().any():
        raise ValueError(f"{resolved_bar_col} must be numeric")
    output = data.copy()
    output["_temporal_validation_input_order"] = range(len(output))
    sort_columns = [resolved_bar_col]
    if "bar_time" in output.columns:
        sort_columns.append("bar_time")
    sort_columns.extend(["observation_id", "_temporal_validation_input_order"])
    output = output.sort_values(sort_columns, kind="stable")
    output = output.drop(columns=["_temporal_validation_input_order"])
    return output.reset_index(drop=True).copy()


def _copy_sorted_if_possible(frame: pd.DataFrame, bar_col: str | None = None) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    if "observation_id" in frame.columns and ("decision_bar_index" in frame.columns or "bar_index" in frame.columns):
        return _ordered_samples(frame, bar_col=bar_col)
    return frame.reset_index(drop=True).copy()


def _validate_label_window_columns(frame: pd.DataFrame, label_start_col: str, label_end_col: str) -> None:
    starts = pd.to_numeric(frame[label_start_col], errors="coerce")
    ends = pd.to_numeric(frame[label_end_col], errors="coerce")
    if starts.isna().any() or ends.isna().any():
        raise ValueError("label window columns must be numeric and non-null")
    if (ends < starts).any():
        raise ValueError("label_end_bar must be greater than or equal to label_start_bar")


def _is_missing(value: Any) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def purge_train_against_eval(
    train_df: pd.DataFrame,
    eval_df: pd.DataFrame,
    label_start_col: str = "label_start_bar",
    label_end_col: str = "label_end_bar",
) -> tuple[pd.DataFrame, dict[str, int]]:
    train = _copy_sorted_if_possible(train_df)
    evaluation = _copy_sorted_if_possible(eval_df)
    summary = {
        "original_train_count": int(len(train)),
        "eval_count": int(len(evaluation)),
        "purged_count": 0,
        "remaining_train_count": int(len(train)),
    }
    if train.empty or evaluation.empty:
        return train.reset_index(drop=True).copy(), summary
    for frame_name, frame in (("train_df", train), ("eval_df", evaluation)):
        missing = [column for column in (label_start_col, label_end_col) if column not in frame.columns]
        if missing:
            raise ValueError(f"{frame_name} missing label window columns: {', '.join(missing)}")
        _validate_label_window_columns(frame, label_start_col, label_end_col)
    eval_windows = list(zip(evaluation[label_start_col].tolist(), evaluation[label_end_col].tolist()))
    remove = []
    for _, row in train.iterrows():
        overlaps = any(
            windows_overlap(row[label_start_col], row[label_end_col], eval_start, eval_end)
            for eval_start, eval_end in eval_windows
        )
        remove.append(overlaps)
    remove_mask = pd.Series(remove, index=train.index)
    purged = train.loc[~remove_mask].reset_index(drop=True).copy()
    summary["purged_count"] = int(remove_mask.sum())
    summary["remaining_train_count"] = int(len(purged))
    return purged, summary


def apply_embargo_against_eval(
    train_df: pd.DataFrame,
    eval_df: pd.DataFrame,
    embargo_bars: int,
    bar_col: str | None = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    train = _copy_sorted_if_possible(train_df, bar_col=bar_col)
    evaluation = _copy_sorted_if_possible(eval_df, bar_col=bar_col)
    embargo = int(embargo_bars)
    summary = {
        "original_train_count": int(len(train)),
        "eval_count": int(len(evaluation)),
        "embargoed_count": 0,
        "remaining_train_count": int(len(train)),
        "embargo_bars": embargo,
    }
    if embargo <= 0 or train.empty or evaluation.empty:
        return train.reset_index(drop=True).copy(), summary
    train_bar_col = bar_col or _resolve_bar_col(train)
    eval_bar_col = bar_col or _resolve_bar_col(evaluation)
    train_bars = pd.to_numeric(train[train_bar_col], errors="coerce")
    eval_bars = pd.to_numeric(evaluation[eval_bar_col], errors="coerce")
    if train_bars.isna().any() or eval_bars.isna().any():
        raise ValueError("bar columns must be numeric")
    eval_min = float(eval_bars.min())
    eval_max = float(eval_bars.max())
    remove = train_bars.between(eval_min - embargo, eval_max + embargo, inclusive="both")
    kept = train.loc[~remove].reset_index(drop=True).copy()
    summary["embargoed_count"] = int(remove.sum())
    summary["remaining_train_count"] = int(len(kept))
    return kept, summary


def assign_episode_id(
    df: pd.DataFrame,
    max_gap_bars: int,
    bar_col: str | None = None,
    group_cols: list[str] | None = None,
) -> pd.DataFrame:
    gap = int(max_gap_bars)
    if gap < 0:
        raise ValueError("max_gap_bars must be non-negative")
    if not isinstance(df, pd.DataFrame):
        raise ValueError("df must be a pandas DataFrame")
    resolved_bar_col = bar_col or _resolve_bar_col(df)
    groups = list(group_cols) if group_cols is not None else [column for column in ("symbol", "interval") if column in df.columns]
    missing_groups = [column for column in groups if column not in df.columns]
    if missing_groups:
        raise ValueError(f"Missing group columns: {', '.join(missing_groups)}")
    ordered = _ordered_samples(df, bar_col=resolved_bar_col)
    output_frames: list[pd.DataFrame] = []
    if groups:
        grouped: Iterator[tuple[Any, pd.DataFrame]] = ordered.groupby(groups, sort=True, dropna=False)
    else:
        grouped = iter([(("global",), ordered)])
    for group_values, group in grouped:
        if not isinstance(group_values, tuple):
            group_values = (group_values,)
        prefix = _episode_prefix(groups, group_values)
        bars = pd.to_numeric(group[resolved_bar_col], errors="coerce").tolist()
        episode_numbers: list[int] = []
        current_episode = 0
        previous_bar: float | None = None
        for bar in bars:
            if previous_bar is None or float(bar) - previous_bar > gap:
                current_episode += 1
            episode_numbers.append(current_episode)
            previous_bar = float(bar)
        current = group.copy()
        current["episode_id"] = [f"{prefix}|ep_{number:06d}" for number in episode_numbers]
        output_frames.append(current)
    if not output_frames:
        output = ordered.copy()
        output["episode_id"] = pd.Series(dtype="object")
        return output
    return pd.concat(output_frames, ignore_index=True).reset_index(drop=True).copy()


def _episode_prefix(group_cols: list[str], group_values: tuple[Any, ...]) -> str:
    if not group_cols:
        return "global"
    return "|".join(str(value) for value in group_values)


def _remove_train_episode_leakage(train: pd.DataFrame, eval_frames: list[pd.DataFrame]) -> tuple[pd.DataFrame, int]:
    if train.empty or "episode_id" not in train.columns:
        return train.reset_index(drop=True).copy(), 0
    eval_episode_ids: set[str] = set()
    for evaluation in eval_frames:
        if "episode_id" in evaluation.columns:
            eval_episode_ids.update(evaluation["episode_id"].dropna().astype(str).tolist())
    if not eval_episode_ids:
        return train.reset_index(drop=True).copy(), 0
    remove = train["episode_id"].astype(str).isin(eval_episode_ids)
    return train.loc[~remove].reset_index(drop=True).copy(), int(remove.sum())


def validate_split_integrity(split: SplitResult | dict[str, Any], episode_col: str = "episode_id") -> dict[str, Any]:
    frames = _split_frames(split)
    warnings: list[str] = []
    ranges = {name: _bar_index_range(frame) for name, frame in frames.items()}
    order_violations = _time_order_violations(ranges)
    warnings.extend(order_violations)
    if any(len(frame) == 0 for frame in frames.values()):
        warnings.append("empty_split")
    duplicate_observation_count = _duplicate_observation_count(frames)
    if duplicate_observation_count:
        warnings.append("duplicate_observation_id_across_splits")
    episode_leakage_count = _episode_leakage_count(frames, episode_col=episode_col)
    if episode_leakage_count:
        warnings.append("episode_leakage")
    label_window_overlap_count, label_window_warning = _label_window_overlap_count(
        frames["train"],
        [frames["validation"], frames["test"]],
    )
    if label_window_warning:
        warnings.append(label_window_warning)
    if label_window_overlap_count:
        warnings.append("label_window_overlap")
    is_valid = not (
        order_violations
        or duplicate_observation_count
        or episode_leakage_count
        or label_window_overlap_count
        or any(len(frame) == 0 for frame in frames.values())
    )
    return {
        "is_valid": bool(is_valid),
        "status": "PASS" if is_valid else "FAIL",
        "train_count": int(len(frames["train"])),
        "validation_count": int(len(frames["validation"])),
        "val_count": int(len(frames["validation"])),
        "test_count": int(len(frames["test"])),
        "purged_count": int(_summary_value(split, "purged_count", 0)),
        "embargoed_count": int(_summary_value(split, "embargoed_count", 0)),
        "episode_leakage_count": int(episode_leakage_count),
        "duplicate_observation_count": int(duplicate_observation_count),
        "label_window_overlap_count": int(label_window_overlap_count),
        "bar_index_ranges": ranges,
        "warnings": list(dict.fromkeys(warnings)),
    }


def summarize_split(split: SplitResult | dict[str, Any]) -> dict[str, Any]:
    if isinstance(split, SplitResult):
        return dict(split.summary)
    report = validate_split_integrity(split)
    if "split_method" in split:
        report["split_method"] = str(split["split_method"])
    if "split_index" in split:
        report["split_index"] = int(split["split_index"])
    return report


def _split_frames(split: SplitResult | dict[str, Any]) -> dict[str, pd.DataFrame]:
    if isinstance(split, SplitResult):
        return {"train": split.train.copy(), "validation": split.validation.copy(), "test": split.test.copy()}
    if not isinstance(split, dict):
        raise ValueError("split must be a SplitResult or dict")
    missing = [name for name in ("train", "test") if name not in split]
    if "validation" not in split and "val" not in split:
        missing.append("validation")
    if missing:
        raise ValueError(f"Missing split keys: {', '.join(missing)}")
    validation_key = "validation" if "validation" in split else "val"
    frames = {"train": split["train"], "validation": split[validation_key], "test": split["test"]}
    for name, frame in frames.items():
        if not isinstance(frame, pd.DataFrame):
            raise ValueError(f"split[{name!r}] must be a pandas DataFrame")
    return {name: frame.copy() for name, frame in frames.items()}


def _bar_index_range(frame: pd.DataFrame) -> dict[str, int | None]:
    if frame.empty:
        return {"min": None, "max": None}
    column = _resolve_bar_col(frame)
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    if values.empty:
        return {"min": None, "max": None}
    return {"min": int(values.min()), "max": int(values.max())}


def _time_order_violations(ranges: dict[str, dict[str, int | None]]) -> list[str]:
    warnings: list[str] = []
    if ranges["train"]["max"] is not None and ranges["validation"]["min"] is not None:
        if ranges["train"]["max"] >= ranges["validation"]["min"]:
            warnings.append("train_validation_order")
    if ranges["validation"]["max"] is not None and ranges["test"]["min"] is not None:
        if ranges["validation"]["max"] >= ranges["test"]["min"]:
            warnings.append("validation_test_order")
    return warnings


def _duplicate_observation_count(frames: dict[str, pd.DataFrame]) -> int:
    id_to_splits: dict[str, set[str]] = {}
    for name, frame in frames.items():
        if "observation_id" not in frame.columns:
            continue
        for observation_id in frame["observation_id"].dropna().astype(str).tolist():
            id_to_splits.setdefault(observation_id, set()).add(name)
    return sum(1 for split_names in id_to_splits.values() if len(split_names) > 1)


def _episode_leakage_count(frames: dict[str, pd.DataFrame], *, episode_col: str) -> int:
    episode_to_splits: dict[str, set[str]] = {}
    for name, frame in frames.items():
        if episode_col not in frame.columns:
            continue
        for episode_id in frame[episode_col].dropna().astype(str).tolist():
            episode_to_splits.setdefault(episode_id, set()).add(name)
    return sum(1 for split_names in episode_to_splits.values() if len(split_names) > 1)


def _label_window_overlap_count(train: pd.DataFrame, eval_frames: list[pd.DataFrame]) -> tuple[int, str | None]:
    if train.empty:
        return 0, None
    if not _has_label_window(train):
        return 0, "label_windows_missing"
    evaluation = pd.concat([frame for frame in eval_frames if not frame.empty], ignore_index=True)
    if evaluation.empty:
        return 0, None
    if not _has_label_window(evaluation):
        return 0, "label_windows_missing"
    _validate_label_window_columns(train, "label_start_bar", "label_end_bar")
    _validate_label_window_columns(evaluation, "label_start_bar", "label_end_bar")
    eval_windows = list(zip(evaluation["label_start_bar"].tolist(), evaluation["label_end_bar"].tolist()))
    overlap_count = 0
    for _, row in train.iterrows():
        if any(windows_overlap(row["label_start_bar"], row["label_end_bar"], start, end) for start, end in eval_windows):
            overlap_count += 1
    return overlap_count, None


def _has_label_window(frame: pd.DataFrame) -> bool:
    return "label_start_bar" in frame.columns and "label_end_bar" in frame.columns


def _summary_value(split: SplitResult | dict[str, Any], key: str, default: Any) -> Any:
    if isinstance(split, SplitResult):
        return split.summary.get(key, default)
    if isinstance(split, dict):
        if key in split:
            value = split[key]
            if isinstance(value, pd.DataFrame):
                return len(value)
            return value
        if "summary" in split and isinstance(split["summary"], dict):
            return split["summary"].get(key, default)
    return default


def build_purged_chronological_split(
    df: pd.DataFrame,
    train_ratio: float,
    validation_ratio: float | None = None,
    test_ratio: float | None = None,
    *,
    val_ratio: float | None = None,
    horizon_bars: int | None = None,
    label_horizon_bars: int | None = None,
    feature_lookback_bars: int = 0,
    embargo_bars: int = 0,
    episode_gap_bars: int | None = None,
    max_gap_bars: int | None = None,
    enforce_episode_purity: bool = False,
    bar_col: str | None = None,
) -> SplitResult:
    resolved_validation_ratio = validation_ratio if validation_ratio is not None else val_ratio
    if resolved_validation_ratio is None or test_ratio is None:
        raise ValueError("validation_ratio and test_ratio are required")
    horizon = _resolve_horizon(horizon_bars, label_horizon_bars)
    ordered = _with_research_windows(
        df,
        horizon_bars=horizon,
        feature_lookback_bars=feature_lookback_bars,
        bar_col=bar_col,
    )
    gap = episode_gap_bars if episode_gap_bars is not None else max_gap_bars
    if gap is not None:
        ordered = assign_episode_id(ordered, max_gap_bars=gap, bar_col=bar_col)
    train, validation, test = _chronological_frames(
        ordered,
        train_ratio=float(train_ratio),
        validation_ratio=float(resolved_validation_ratio),
        test_ratio=float(test_ratio),
        bar_col=bar_col,
    )
    return _make_split_result(
        train,
        validation,
        test,
        split_method="purged_chronological",
        original_count=len(ordered),
        horizon_bars=horizon,
        embargo_bars=embargo_bars,
        episode_gap_bars=gap,
        enforce_episode_purity=enforce_episode_purity,
        bar_col=bar_col,
    )


def build_purged_walk_forward_splits(
    df: pd.DataFrame,
    train_window: int,
    validation_window: int | None = None,
    test_window: int | None = None,
    step: int | None = None,
    *,
    val_window: int | None = None,
    horizon_bars: int | None = None,
    label_horizon_bars: int | None = None,
    feature_lookback_bars: int = 0,
    embargo_bars: int = 0,
    episode_gap_bars: int | None = None,
    max_gap_bars: int | None = None,
    enforce_episode_purity: bool = False,
    bar_col: str | None = None,
) -> WalkForwardSplitResult:
    resolved_validation_window = validation_window if validation_window is not None else val_window
    if resolved_validation_window is None or test_window is None or step is None:
        raise ValueError("validation_window, test_window, and step are required")
    train_size = int(train_window)
    validation_size = int(resolved_validation_window)
    test_size = int(test_window)
    step_size = int(step)
    if min(train_size, validation_size, test_size, step_size) <= 0:
        raise ValueError("train_window, validation_window, test_window, and step must be positive")
    horizon = _resolve_horizon(horizon_bars, label_horizon_bars)
    ordered = _with_research_windows(
        df,
        horizon_bars=horizon,
        feature_lookback_bars=feature_lookback_bars,
        bar_col=bar_col,
    )
    gap = episode_gap_bars if episode_gap_bars is not None else max_gap_bars
    if gap is not None:
        ordered = assign_episode_id(ordered, max_gap_bars=gap, bar_col=bar_col)
    total_window = train_size + validation_size + test_size
    warnings: list[str] = []
    if len(ordered) < total_window:
        warnings.append("insufficient_samples_for_walk_forward")
        return WalkForwardSplitResult(
            folds=[],
            summary={
                "split_method": "purged_walk_forward",
                "original_count": int(len(ordered)),
                "fold_count": 0,
                "horizon_bars": horizon,
                "embargo_bars": int(embargo_bars),
                "warnings": warnings,
            },
            warnings=warnings,
        )
    folds: list[SplitResult] = []
    for fold_index, start in enumerate(range(0, len(ordered) - total_window + 1, step_size)):
        train_end = start + train_size
        validation_end = train_end + validation_size
        test_end = validation_end + test_size
        fold = _make_split_result(
            ordered.iloc[start:train_end].reset_index(drop=True).copy(),
            ordered.iloc[train_end:validation_end].reset_index(drop=True).copy(),
            ordered.iloc[validation_end:test_end].reset_index(drop=True).copy(),
            split_method="purged_walk_forward",
            original_count=total_window,
            horizon_bars=horizon,
            embargo_bars=embargo_bars,
            episode_gap_bars=gap,
            enforce_episode_purity=enforce_episode_purity,
            bar_col=bar_col,
            fold_index=fold_index,
        )
        folds.append(fold)
        warnings.extend(fold.warnings)
    summary = {
        "split_method": "purged_walk_forward",
        "original_count": int(len(ordered)),
        "fold_count": int(len(folds)),
        "train_window": train_size,
        "validation_window": validation_size,
        "test_window": test_size,
        "step": step_size,
        "horizon_bars": horizon,
        "embargo_bars": int(embargo_bars),
        "warnings": list(dict.fromkeys(warnings)),
    }
    return WalkForwardSplitResult(folds=folds, summary=summary, warnings=summary["warnings"])


def _make_split_result(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    test: pd.DataFrame,
    *,
    split_method: str,
    original_count: int,
    horizon_bars: int,
    embargo_bars: int,
    episode_gap_bars: int | None,
    enforce_episode_purity: bool,
    bar_col: str | None = None,
    fold_index: int | None = None,
) -> SplitResult:
    original_train_count = len(train)
    train_after_val, purge_val_summary = purge_train_against_eval(train, validation)
    train_after_test, purge_test_summary = purge_train_against_eval(train_after_val, test)
    eval_df = pd.concat([validation, test], ignore_index=True) if not validation.empty or not test.empty else train_after_test.iloc[0:0].copy()
    train_after_embargo, embargo_summary = apply_embargo_against_eval(
        train_after_test,
        eval_df,
        embargo_bars=embargo_bars,
        bar_col=bar_col,
    )
    episode_purged_count = 0
    final_train = train_after_embargo
    if enforce_episode_purity and "episode_id" in final_train.columns:
        final_train, episode_purged_count = _remove_train_episode_leakage(final_train, [validation, test])
    preliminary = SplitResult(
        train=final_train.reset_index(drop=True).copy(),
        validation=validation.reset_index(drop=True).copy(),
        test=test.reset_index(drop=True).copy(),
        summary={},
        warnings=[],
    )
    purged_count = int(purge_val_summary["purged_count"]) + int(purge_test_summary["purged_count"]) + int(episode_purged_count)
    embargoed_count = int(embargo_summary["embargoed_count"])
    base_summary = {
        "split_method": split_method,
        "original_count": int(original_count),
        "original_train_count": int(original_train_count),
        "train_count": int(len(preliminary.train)),
        "validation_count": int(len(preliminary.validation)),
        "val_count": int(len(preliminary.validation)),
        "test_count": int(len(preliminary.test)),
        "purged_count": purged_count,
        "embargoed_count": embargoed_count,
        "episode_leakage_count": 0,
        "horizon_bars": int(horizon_bars),
        "embargo_bars": int(embargo_bars),
        "episode_gap_bars": episode_gap_bars,
        "enforce_episode_purity": bool(enforce_episode_purity),
    }
    if fold_index is not None:
        base_summary["fold_index"] = int(fold_index)
        base_summary["fold_bar_ranges"] = {
            "train": _bar_index_range(train),
            "validation": _bar_index_range(validation),
            "test": _bar_index_range(test),
        }
    preliminary.summary.update(base_summary)
    integrity = validate_split_integrity(preliminary)
    summary = {**base_summary, **integrity, "integrity_report": integrity}
    summary["purged_count"] = purged_count
    summary["embargoed_count"] = embargoed_count
    summary["episode_leakage_count"] = int(integrity["episode_leakage_count"])
    warnings = list(dict.fromkeys(integrity["warnings"]))
    summary["warnings"] = warnings
    return SplitResult(
        train=preliminary.train,
        validation=preliminary.validation,
        test=preliminary.test,
        summary=summary,
        warnings=warnings,
    )


def chronological_train_val_test_split(
    data: pd.DataFrame,
    train_ratio: float,
    val_ratio: float,
    test_ratio: float,
) -> dict[str, pd.DataFrame]:
    ordered = _ordered_samples(data)
    train, validation, test = _chronological_frames(
        ordered,
        train_ratio=float(train_ratio),
        validation_ratio=float(val_ratio),
        test_ratio=float(test_ratio),
    )
    return {"train": train, "val": validation, "test": test}


def walk_forward_splits(
    data: pd.DataFrame,
    train_window: int,
    val_window: int,
    test_window: int,
    step: int,
) -> list[dict[str, pd.DataFrame]]:
    train_size = int(train_window)
    validation_size = int(val_window)
    test_size = int(test_window)
    step_size = int(step)
    if min(train_size, validation_size, test_size, step_size) <= 0:
        raise ValueError("train_window, val_window, test_window, and step must be positive")
    ordered = _ordered_samples(data)
    total_window = train_size + validation_size + test_size
    if len(ordered) < total_window:
        return []
    splits: list[dict[str, pd.DataFrame]] = []
    for start in range(0, len(ordered) - total_window + 1, step_size):
        train_end = start + train_size
        validation_end = train_end + validation_size
        test_end = validation_end + test_size
        splits.append(
            {
                "train": ordered.iloc[start:train_end].reset_index(drop=True).copy(),
                "val": ordered.iloc[train_end:validation_end].reset_index(drop=True).copy(),
                "test": ordered.iloc[validation_end:test_end].reset_index(drop=True).copy(),
            }
        )
    return splits


def apply_embargo(split: dict[str, pd.DataFrame], embargo_bars: int) -> dict[str, pd.DataFrame]:
    frames = _split_frames(split)
    validation, validation_summary = _drop_eval_boundary_rows(
        frames["train"],
        frames["validation"],
        embargo_bars=embargo_bars,
    )
    test, test_summary = _drop_eval_boundary_rows(
        frames["validation"],
        frames["test"],
        embargo_bars=embargo_bars,
    )
    embargoed_frames = []
    if validation_summary["embargoed_count"]:
        embargoed_frames.append(frames["validation"].iloc[: validation_summary["embargoed_count"]].copy())
    if test_summary["embargoed_count"]:
        embargoed_frames.append(frames["test"].iloc[: test_summary["embargoed_count"]].copy())
    embargoed = pd.concat(embargoed_frames, ignore_index=True) if embargoed_frames else frames["train"].iloc[0:0].copy()
    return {
        "train": frames["train"].reset_index(drop=True).copy(),
        "val": validation.reset_index(drop=True).copy(),
        "test": test.reset_index(drop=True).copy(),
        "embargoed": embargoed.reset_index(drop=True).copy(),
    }


def purge_overlapping_label_windows(samples: pd.DataFrame, horizon_bars: int) -> pd.DataFrame:
    working = ensure_label_window(samples, horizon_bars=horizon_bars)
    if working.empty:
        return working.copy()
    starts = pd.to_numeric(working["label_start_bar"], errors="coerce")
    ends = pd.to_numeric(working["label_end_bar"], errors="coerce")
    if starts.isna().any() or ends.isna().any():
        raise ValueError("label window columns must be numeric")
    kept_positions: list[int] = []
    last_end: float | None = None
    for position, (start, end) in enumerate(zip(starts.tolist(), ends.tolist())):
        if end < start:
            raise ValueError("label_end_bar must be greater than or equal to label_start_bar")
        if last_end is None or start > last_end:
            kept_positions.append(position)
            last_end = float(end)
    return working.iloc[kept_positions].reset_index(drop=True).copy()


def _resolve_horizon(horizon_bars: int | None, label_horizon_bars: int | None) -> int:
    horizon = horizon_bars if horizon_bars is not None else label_horizon_bars
    if horizon is None:
        horizon = DEFAULT_LABEL_HORIZON_BARS
    horizon = int(horizon)
    if horizon <= 0:
        raise ValueError("horizon_bars must be positive")
    return horizon


def _with_research_windows(
    data: pd.DataFrame,
    *,
    horizon_bars: int,
    feature_lookback_bars: int = 0,
    bar_col: str | None = None,
) -> pd.DataFrame:
    ordered = _ordered_samples(data, bar_col=bar_col)
    resolved_bar_col = bar_col or _resolve_bar_col(ordered)
    output = ensure_label_window(ordered, horizon_bars=horizon_bars, bar_col=resolved_bar_col)
    bars = pd.to_numeric(output[resolved_bar_col], errors="coerce")
    lookback = max(0, int(feature_lookback_bars))
    if "decision_bar_index" not in output.columns:
        output["decision_bar_index"] = bars.astype(int)
    if "feature_end_bar" not in output.columns:
        output["feature_end_bar"] = bars.astype(int)
    if "feature_start_bar" not in output.columns:
        output["feature_start_bar"] = (bars - lookback).astype(int)
    return output.reset_index(drop=True).copy()


def _chronological_frames(
    ordered: pd.DataFrame,
    *,
    train_ratio: float,
    validation_ratio: float,
    test_ratio: float,
    bar_col: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    count = len(ordered)
    if count < 3:
        raise ValueError("chronological split requires at least 3 samples")
    if abs(train_ratio + validation_ratio + test_ratio - 1.0) > 1e-9:
        raise ValueError("train_ratio, validation_ratio, and test_ratio must sum to 1.0")
    train_count = int(count * train_ratio)
    validation_count = int(count * validation_ratio)
    test_count = count - train_count - validation_count
    if min(train_count, validation_count, test_count) <= 0:
        raise ValueError("chronological split leaves an empty train, validation, or test set")
    ordered_again = _ordered_samples(ordered, bar_col=bar_col)
    train_end = train_count
    validation_end = train_end + validation_count
    return (
        ordered_again.iloc[:train_end].reset_index(drop=True).copy(),
        ordered_again.iloc[train_end:validation_end].reset_index(drop=True).copy(),
        ordered_again.iloc[validation_end:].reset_index(drop=True).copy(),
    )


def _drop_eval_boundary_rows(
    previous_df: pd.DataFrame,
    eval_df: pd.DataFrame,
    *,
    embargo_bars: int,
) -> tuple[pd.DataFrame, dict[str, int]]:
    embargo = int(embargo_bars)
    summary = {"embargoed_count": 0}
    if embargo <= 0 or previous_df.empty or eval_df.empty:
        return eval_df.reset_index(drop=True).copy(), summary
    previous_bar_col = _resolve_bar_col(previous_df)
    eval_bar_col = _resolve_bar_col(eval_df)
    previous_max = float(pd.to_numeric(previous_df[previous_bar_col], errors="coerce").max())
    eval_bars = pd.to_numeric(eval_df[eval_bar_col], errors="coerce")
    keep = eval_bars > previous_max + embargo
    summary["embargoed_count"] = int((~keep).sum())
    return eval_df.loc[keep].reset_index(drop=True).copy(), summary


__all__ = [
    "SplitResult",
    "WalkForwardSplitResult",
    "_resolve_bar_col",
    "apply_embargo",
    "apply_embargo_against_eval",
    "assign_episode_id",
    "build_purged_chronological_split",
    "build_purged_walk_forward_splits",
    "chronological_train_val_test_split",
    "ensure_label_window",
    "purge_overlapping_label_windows",
    "purge_train_against_eval",
    "summarize_split",
    "validate_split_integrity",
    "walk_forward_splits",
    "windows_overlap",
]
