from __future__ import annotations

import json
import math
import operator

import pandas as pd

from .validation import minimum_sample_gate, oos_degradation_gate

OPS = {"<=": operator.le, ">=": operator.ge, "<": operator.lt, ">": operator.gt, "==": operator.eq}


def _sort_time(data: pd.DataFrame, time_col: str) -> pd.DataFrame:
    result = data.copy()
    if time_col in result.columns:
        result["_sort_time"] = pd.to_datetime(result[time_col], errors="coerce")
        result = result.sort_values(["_sort_time"], kind="stable").drop(columns="_sort_time")
    return result.reset_index(drop=True)


def chronological_train_test_split(
    data: pd.DataFrame,
    train_ratio: float = 0.7,
    time_col: str = "event_time_bjt",
    purge_bars: int = 0,
    embargo_bars: int = 0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    sorted_data = _sort_time(data, time_col)
    if sorted_data.empty:
        return sorted_data.copy(), sorted_data.copy()
    split = min(len(sorted_data) - 1, max(1, int(len(sorted_data) * float(train_ratio)))) if len(sorted_data) > 1 else 1
    train_end = max(0, split - max(0, int(purge_bars)))
    test_start = min(len(sorted_data), split + max(0, int(embargo_bars)))
    return sorted_data.iloc[:train_end].copy(), sorted_data.iloc[test_start:].copy()


def walk_forward_splits(
    data: pd.DataFrame,
    n_splits: int = 3,
    train_ratio: float = 0.5,
    time_col: str = "event_time_bjt",
    purge_bars: int = 0,
    embargo_bars: int = 0,
) -> list[tuple[str, pd.DataFrame, pd.DataFrame]]:
    sorted_data = _sort_time(data, time_col)
    if len(sorted_data) < 2:
        return []
    initial = max(1, int(len(sorted_data) * float(train_ratio)))
    test_size = max(1, (len(sorted_data) - initial) // max(1, int(n_splits)))
    splits = []
    for index in range(max(1, int(n_splits))):
        train_end = initial + index * test_size
        test_end = len(sorted_data) if index == n_splits - 1 else min(len(sorted_data), train_end + test_size)
        if train_end >= len(sorted_data) or test_end <= train_end:
            break
        purged_train_end = max(0, train_end - max(0, int(purge_bars)))
        embargoed_test_start = min(test_end, train_end + max(0, int(embargo_bars)))
        train = sorted_data.iloc[:purged_train_end].copy()
        test = sorted_data.iloc[embargoed_test_start:test_end].copy()
        if train.empty or test.empty:
            continue
        splits.append((f"period_{index + 1}", train, test))
    return splits


def _mask(data: pd.DataFrame, conditions: list[dict]) -> pd.Series:
    mask = pd.Series(True, index=data.index)
    for condition in conditions:
        column = condition["column"]
        operation = condition["op"]
        if column not in data.columns or operation not in OPS:
            return pd.Series(False, index=data.index)
        left = pd.to_numeric(data[column], errors="coerce") if operation != "==" else data[column]
        mask &= OPS[operation](left, condition["value"]).fillna(False)
    return mask


def _metrics(data: pd.DataFrame, conditions: list[dict], label: str) -> dict:
    subset = data[_mask(data, conditions)]
    values = pd.to_numeric(subset.get(label), errors="coerce").dropna()
    return {
        "sample_count": int(len(values)),
        "mean": float(values.mean()) if len(values) else math.nan,
        "win_rate": float((values > 0).mean() * 100.0) if len(values) else math.nan,
    }


def evaluate_rule_on_split(
    train: pd.DataFrame,
    test: pd.DataFrame,
    rule_id: str,
    conditions: list[dict],
    label: str = "fwd_ret_10_side_adj",
    period: str = "period_1",
    time_col: str = "event_time_bjt",
    min_samples: int = 30,
    max_degradation_ratio: float = 0.5,
    purge_bars: int = 0,
    embargo_bars: int = 0,
) -> dict:
    train_metrics = _metrics(train, conditions, label)
    test_metrics = _metrics(test, conditions, label)
    train_mean, test_mean = train_metrics["mean"], test_metrics["mean"]
    degradation = (
        (train_mean - test_mean) / abs(train_mean) * 100.0
        if math.isfinite(train_mean) and train_mean != 0 and math.isfinite(test_mean)
        else math.nan
    )
    train_gate = minimum_sample_gate(train_metrics["sample_count"], min_samples)
    test_gate = minimum_sample_gate(test_metrics["sample_count"], min_samples)
    oos_gate = oos_degradation_gate(train_mean, test_mean, max_degradation_ratio)
    if not train_gate["passed"] or not test_gate["passed"]:
        validation_status = "rejected_low_sample"
    elif oos_gate["status"] == "unavailable":
        validation_status = "unavailable"
    elif not oos_gate["passed"]:
        validation_status = "rejected_oos_degradation"
    else:
        validation_status = "exploratory_candidate"
    def boundary(frame: pd.DataFrame, first: bool):
        if frame.empty or time_col not in frame.columns:
            return None
        return str(frame.iloc[0 if first else -1][time_col])
    return {
        "period": period,
        "train_start": boundary(train, True),
        "train_end": boundary(train, False),
        "test_start": boundary(test, True),
        "test_end": boundary(test, False),
        "rule_id": rule_id,
        "conditions_json": json.dumps(conditions, sort_keys=True),
        "train_sample_count": train_metrics["sample_count"],
        "test_sample_count": test_metrics["sample_count"],
        "train_mean": train_mean,
        "test_mean": test_mean,
        "train_win_rate": train_metrics["win_rate"],
        "test_win_rate": test_metrics["win_rate"],
        "degradation_pct": degradation,
        "degradation_ratio": oos_gate["degradation_ratio"],
        "validation_status": validation_status,
        "split_method": "purged_chronological_split",
        "purge_bars": int(purge_bars),
        "embargo_bars": int(embargo_bars),
        "split_spec_json": json.dumps(
            {
                "method": "purged_chronological_split",
                "purge_bars": int(purge_bars),
                "embargo_bars": int(embargo_bars),
                "time_col": time_col,
            },
            sort_keys=True,
        ),
        "warning": "insufficient test rule samples" if test_metrics["sample_count"] < 30 else "",
    }


def evaluate_factor_stability(
    data: pd.DataFrame,
    factor: str,
    label: str = "fwd_ret_10_side_adj",
    n_splits: int = 3,
) -> pd.DataFrame:
    rows = []
    for period, _train, test in walk_forward_splits(data, n_splits=n_splits):
        work = test[[factor, label]].apply(pd.to_numeric, errors="coerce").dropna()
        rows.append(
            {
                "period": period,
                "factor": factor,
                "sample_count": len(work),
                "rank_ic": float(work[factor].corr(work[label], method="spearman")) if len(work) >= 2 else math.nan,
            }
        )
    return pd.DataFrame(rows)


def build_walk_forward_results(
    samples: pd.DataFrame,
    rules: pd.DataFrame,
    label: str = "fwd_ret_10_side_adj",
    n_splits: int = 3,
    purge_bars: int | None = None,
    embargo_bars: int = 0,
    horizon_bars: int = 10,
    min_samples: int = 30,
    max_degradation_ratio: float = 0.5,
) -> pd.DataFrame:
    if samples.empty or rules.empty:
        return pd.DataFrame()
    effective_purge = max(int(horizon_bars), int(purge_bars) if purge_bars is not None else int(horizon_bars))
    rows = []
    for period, train, test in walk_forward_splits(
        samples,
        n_splits=n_splits,
        purge_bars=effective_purge,
        embargo_bars=embargo_bars,
    ):
        for _, rule in rules.iterrows():
            try:
                conditions = json.loads(rule.get("conditions_json") or "[]")
            except Exception:
                continue
            rows.append(
                evaluate_rule_on_split(
                    train,
                    test,
                    str(rule.get("rule_id")),
                    conditions,
                    label,
                    period,
                    min_samples=min_samples,
                    max_degradation_ratio=max_degradation_ratio,
                    purge_bars=effective_purge,
                    embargo_bars=embargo_bars,
                )
            )
    return pd.DataFrame(rows)
