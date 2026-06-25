from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..time_series_analysis.entry_distribution_diagnostics import (
    compare_entry_reject_distributions,
    compute_excess_kurtosis,
    compute_quantiles,
    compute_skewness,
    outcome_time_series_diagnostics,
    tail_concentration,
)


DECISIONS = ("ENTRY", "REJECT", "UNCERTAIN", "UNLABELED")
OUTCOME_TOKENS = ("fwd_ret", "mfe", "mae", "hit_tp", "hit_sl", "excursion")
SIGNAL_TOKENS = ("buy_signal", "sell_signal", "trade_signal")
RISK_STATEMENTS = (
    "本报告用于复盘用户自己的开仓判断变化，不是交易信号。",
    "本报告不构成投资建议。",
    "后验结果不代表未来收益。",
    "review queue 是复标队列，不是开仓列表。",
)


def build_weekly_research_report(
    *,
    week_start: str | datetime | None = None,
    week_end: str | datetime | None = None,
    annotations_df: pd.DataFrame | None = None,
    annotation_history_df: pd.DataFrame | None = None,
    features_df: pd.DataFrame | None = None,
    previous_features_df: pd.DataFrame | None = None,
    outcomes_df: pd.DataFrame | None = None,
    scores_df: pd.DataFrame | None = None,
    previous_scores_df: pd.DataFrame | None = None,
    review_queue_df: pd.DataFrame | None = None,
    feature_cols: list[str] | None = None,
    outcome_cols: list[str] | None = None,
    top_k: int = 10,
) -> dict[str, Any]:
    annotations = _empty_frame(annotations_df)
    history = _empty_frame(annotation_history_df)
    features = _empty_frame(features_df)
    previous_features = _empty_frame(previous_features_df)
    outcomes = _empty_frame(outcomes_df)
    scores = _empty_frame(scores_df)
    previous_scores = _empty_frame(previous_scores_df)
    review_queue = _empty_frame(review_queue_df)
    start = _to_timestamp(week_start)
    end = _to_timestamp(week_end)
    previous_start, previous_end = _previous_window(start, end)
    safe_features = _safe_feature_cols(feature_cols or [], features)
    safe_outcomes = _safe_outcome_cols(outcome_cols or [], outcomes)

    weekly_annotations = _filter_time_range(annotations, "created_at", start, end)
    previous_annotations = _filter_time_range(annotations, "created_at", previous_start, previous_end)
    weekly_features = _features_for_annotations(features, weekly_annotations)
    previous_window_features = _features_for_annotations(features, previous_annotations)
    if previous_window_features.empty and not previous_features.empty:
        previous_window_features = previous_features

    warnings: list[str] = []
    if all(frame.empty for frame in (weekly_annotations, weekly_features, outcomes, scores, review_queue)):
        warnings.append("empty_week_data")

    drift_summary = _feature_drift(previous_window_features, weekly_features, safe_features)
    warnings.extend(drift_summary["warnings"])

    outcome_summary = _posterior_outcome_summary(outcomes, safe_outcomes)
    if outcome_summary and any(item.get("tail_warning") for item in outcome_summary):
        warnings.append("outcome_tail_warning")
    time_series = _outcome_time_series(outcomes, safe_outcomes)
    warnings.extend(time_series["warnings"])

    entry_reject = _entry_reject_difference(weekly_annotations, weekly_features, safe_features)
    if not entry_reject:
        warnings.append("entry_reject_sample_insufficient")

    report = {
        "title": "Weekly Entry Logic Research Report",
        "week_start": _timestamp_text(start),
        "week_end": _timestamp_text(end),
        "weekly_annotation_summary": {
            "new_annotation_count": int(len(weekly_annotations)),
            "decision_counts": _decision_counts(weekly_annotations),
            "previous_decision_counts": _decision_counts(previous_annotations),
            "decision_count_delta": _decision_delta(weekly_annotations, previous_annotations),
            "modification_count": _modification_count(history, start, end),
        },
        "reason_tag_summary": _reason_tag_summary(weekly_annotations),
        "entry_feature_distribution": _entry_feature_distribution(weekly_annotations, weekly_features, safe_features),
        "entry_reject_difference": entry_reject,
        "feature_drift": drift_summary["rows"],
        "similarity_score_distribution": _score_distribution(scores, previous_scores),
        "review_queue_summary": _review_queue_summary(review_queue, weekly_annotations),
        "posterior_outcome_risk_summary": outcome_summary,
        "outcome_time_series_diagnostics": time_series["rows"],
        "manual_review_samples": _manual_review_samples(
            weekly_annotations,
            scores,
            review_queue,
            high_similarity_threshold=0.8,
            low_similarity_threshold=0.3,
            top_k=top_k,
        ),
        "feature_cols_used": safe_features,
        "outcome_cols_posterior_only": safe_outcomes,
        "leakage_policy": {
            "context_features_only": True,
            "outcome_labels_role": "posterior_only_not_model_input",
        },
        "risk_statements": list(RISK_STATEMENTS),
        "warnings": sorted(set(warnings)),
    }
    return _remove_signal_names(_json_safe(report))


def render_weekly_research_markdown(report: dict[str, Any]) -> str:
    summary = report.get("weekly_annotation_summary") or {}
    decision_counts = summary.get("decision_counts") or {}
    lines = [
        "# Weekly Entry Logic Research Report",
        "",
        f"- week_start: {report.get('week_start') or '-'}",
        f"- week_end: {report.get('week_end') or '-'}",
        "",
        "## 标注变化",
        "",
        f"- 本周新增标注: {summary.get('new_annotation_count', 0)}",
        f"- 标注修改次数: {summary.get('modification_count', 0)}",
    ]
    for decision in DECISIONS:
        lines.append(f"- {decision}: {decision_counts.get(decision, 0)}")

    lines.extend(["", "## reason_tags", ""])
    tags = report.get("reason_tag_summary") or []
    if tags:
        lines.extend(f"- {row['reason_tag']}: {row['count']}" for row in tags)
    else:
        lines.append("- 本周没有可统计的 reason_tags。")

    lines.extend(["", "## ENTRY 样本关键特征", ""])
    entry_features = report.get("entry_feature_distribution") or []
    if entry_features:
        for row in entry_features:
            lines.append(
                f"- {row['feature']}: n={row['n']}, median={row['median']}, "
                f"IQR={row['iqr']}, skewness={row['skewness']}, excess_kurtosis={row['excess_kurtosis']}"
            )
    else:
        lines.append("- 本周 ENTRY 样本不足，无法稳定统计。")

    lines.extend(["", "## ENTRY vs REJECT 差异变化", ""])
    differences = report.get("entry_reject_difference") or []
    if differences:
        for row in differences:
            lines.append(
                f"- {row['feature']}: ENTRY median={row.get('entry_median')}, "
                f"REJECT median={row.get('reject_median')}, diff={row.get('median_diff_entry_minus_reject')}"
            )
    else:
        lines.append("- ENTRY / REJECT 对照样本不足。")

    lines.extend(["", "## 上周与本周 drift", ""])
    drift = report.get("feature_drift") or []
    if drift:
        for row in drift:
            lines.append(
                f"- {row['feature']}: previous_median={row.get('previous_median')}, "
                f"current_median={row.get('current_median')}, warning={row.get('drift_warning')}"
            )
    else:
        lines.append("- drift 样本不足。")

    lines.extend(["", "## human_entry_similarity", ""])
    score_summary = report.get("similarity_score_distribution") or {}
    lines.append(
        f"- 本周 n={score_summary.get('current', {}).get('n', 0)}, "
        f"median={score_summary.get('current', {}).get('median')}"
    )
    lines.append(
        f"- 上周 n={score_summary.get('previous', {}).get('n', 0)}, "
        f"median={score_summary.get('previous', {}).get('median')}"
    )

    queue = report.get("review_queue_summary") or {}
    lines.extend(["", "## review queue 完成率", ""])
    lines.append(
        f"- completed={queue.get('completed_count', 0)}, total={queue.get('total_count', 0)}, "
        f"completion_rate={queue.get('completion_rate')}"
    )

    lines.extend(["", "## 后验 outcome labels 风险摘要", ""])
    outcomes = report.get("posterior_outcome_risk_summary") or []
    if outcomes:
        for row in outcomes:
            lines.append(
                f"- {row['outcome_col']}: median={row.get('median')}, skewness={row.get('skewness')}, "
                f"excess_kurtosis={row.get('excess_kurtosis')}, tail_warning={row.get('tail_warning')}"
            )
    else:
        lines.append("- 未提供后验 outcome labels，或样本不足。")

    lines.extend(["", "## 本周需要人工复查的样本", ""])
    review = report.get("manual_review_samples") or {}
    for key, rows in review.items():
        lines.append(f"- {key}: {', '.join(str(row.get('observation_id')) for row in rows) if rows else '-'}")

    lines.extend(["", "## 风险声明", ""])
    lines.extend(f"- {statement}" for statement in report.get("risk_statements", RISK_STATEMENTS))
    if report.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in report["warnings"])
    return "\n".join(lines) + "\n"


def write_weekly_research_report(output_dir: str | Path, report: dict[str, Any]) -> dict[str, str]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    markdown_path = target / "weekly_research_report.md"
    json_path = target / "weekly_research_report.json"
    markdown_path.write_text(render_weekly_research_markdown(report), encoding="utf-8")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return {"markdown_path": str(markdown_path), "json_path": str(json_path)}


def _empty_frame(value: pd.DataFrame | None) -> pd.DataFrame:
    return value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _to_timestamp(value: str | datetime | None) -> pd.Timestamp | None:
    if value is None:
        return None
    timestamp = pd.to_datetime(value, errors="coerce", utc=True)
    return None if pd.isna(timestamp) else timestamp


def _timestamp_text(value: pd.Timestamp | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _previous_window(
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    if start is None or end is None:
        return None, None
    width = end - start
    return start - width, start


def _filter_time_range(
    df: pd.DataFrame,
    time_col: str,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
) -> pd.DataFrame:
    if df.empty or time_col not in df.columns or start is None or end is None:
        return df.copy() if start is None or end is None else df.iloc[0:0].copy()
    times = pd.to_datetime(df[time_col], errors="coerce", utc=True)
    mask = times.notna() & (times >= start) & (times < end)
    return df.loc[mask].copy()


def _safe_feature_cols(feature_cols: list[str], features: pd.DataFrame) -> list[str]:
    columns = feature_cols or [
        column
        for column in features.columns
        if column not in {"observation_id", "symbol", "interval", "bar_index", "bar_time"}
    ]
    safe: list[str] = []
    for column in columns:
        lowered = str(column).lower()
        if any(token in lowered for token in OUTCOME_TOKENS):
            continue
        if any(token in lowered for token in SIGNAL_TOKENS):
            continue
        if column in features.columns and column not in safe:
            safe.append(str(column))
    return safe


def _safe_outcome_cols(outcome_cols: list[str], outcomes: pd.DataFrame) -> list[str]:
    columns = outcome_cols or list(outcomes.columns)
    safe: list[str] = []
    for column in columns:
        lowered = str(column).lower()
        if any(token in lowered for token in OUTCOME_TOKENS) and column in outcomes.columns:
            safe.append(str(column))
    return safe


def _features_for_annotations(features: pd.DataFrame, annotations: pd.DataFrame) -> pd.DataFrame:
    if features.empty or annotations.empty or "observation_id" not in features.columns or "observation_id" not in annotations.columns:
        return pd.DataFrame(columns=features.columns)
    ids = set(annotations["observation_id"].astype(str))
    return features.loc[features["observation_id"].astype(str).isin(ids)].copy()


def _decision_counts(annotations: pd.DataFrame) -> dict[str, int]:
    counts = {decision: 0 for decision in DECISIONS}
    if annotations.empty or "human_decision" not in annotations.columns:
        return counts
    values = annotations["human_decision"].astype(str).str.upper().value_counts()
    for decision in DECISIONS:
        counts[decision] = int(values.get(decision, 0))
    return counts


def _decision_delta(current: pd.DataFrame, previous: pd.DataFrame) -> dict[str, int]:
    current_counts = _decision_counts(current)
    previous_counts = _decision_counts(previous)
    return {decision: current_counts[decision] - previous_counts[decision] for decision in DECISIONS}


def _modification_count(history: pd.DataFrame, start: pd.Timestamp | None, end: pd.Timestamp | None) -> int:
    weekly = _filter_time_range(history, "changed_at", start, end)
    if weekly.empty or "operation" not in weekly.columns:
        return 0
    operations = weekly["operation"].astype(str).str.upper()
    return int(operations.isin({"UPDATE", "SOFT_DELETE", "DELETE"}).sum())


def _reason_tag_summary(annotations: pd.DataFrame) -> list[dict[str, Any]]:
    if annotations.empty:
        return []
    counter: Counter[str] = Counter()
    for _, row in annotations.iterrows():
        for tag in _row_reason_tags(row):
            counter[str(tag)] += 1
    return [{"reason_tag": tag, "count": count} for tag, count in counter.most_common()]


def _row_reason_tags(row: pd.Series) -> list[str]:
    value = row.get("reason_tags")
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            return [value]
    json_value = row.get("reason_tags_json")
    if isinstance(json_value, str) and json_value.strip():
        try:
            parsed = json.loads(json_value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            return []
    return []


def _entry_feature_distribution(
    annotations: pd.DataFrame,
    features: pd.DataFrame,
    feature_cols: list[str],
) -> list[dict[str, Any]]:
    merged = _merge_features_annotations(features, annotations)
    if merged.empty:
        return []
    entry = merged.loc[merged["human_decision"].astype(str).str.upper() == "ENTRY"]
    rows: list[dict[str, Any]] = []
    for feature in feature_cols:
        stats = _numeric_stats(entry[feature] if feature in entry.columns else pd.Series(dtype=float))
        rows.append({"feature": feature, **stats})
    return rows


def _entry_reject_difference(
    annotations: pd.DataFrame,
    features: pd.DataFrame,
    feature_cols: list[str],
) -> list[dict[str, Any]]:
    merged = _merge_features_annotations(features, annotations)
    if merged.empty or not {"ENTRY", "REJECT"}.issubset(set(merged["human_decision"].astype(str).str.upper())):
        return []
    try:
        return _records(compare_entry_reject_distributions(merged, "human_decision", feature_cols))
    except Exception:
        return []


def _merge_features_annotations(features: pd.DataFrame, annotations: pd.DataFrame) -> pd.DataFrame:
    if features.empty or annotations.empty:
        return pd.DataFrame()
    if "observation_id" not in features.columns or "observation_id" not in annotations.columns:
        return pd.DataFrame()
    cols = ["observation_id", "human_decision"]
    return features.merge(annotations[cols], on="observation_id", how="inner")


def _feature_drift(
    previous_features: pd.DataFrame,
    current_features: pd.DataFrame,
    feature_cols: list[str],
) -> dict[str, Any]:
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    if previous_features.empty or current_features.empty or not feature_cols:
        return {"rows": rows, "warnings": ["drift_sample_insufficient"]}
    for feature in feature_cols:
        previous = _clean_numeric(previous_features[feature]) if feature in previous_features.columns else pd.Series(dtype=float)
        current = _clean_numeric(current_features[feature]) if feature in current_features.columns else pd.Series(dtype=float)
        if len(previous) < 2 or len(current) < 2:
            warnings.append(f"drift_sample_insufficient:{feature}")
            continue
        previous_median = float(previous.median())
        current_median = float(current.median())
        previous_iqr = float(previous.quantile(0.75) - previous.quantile(0.25))
        threshold = max(0.1, 3.0 * previous_iqr)
        drift_warning = abs(current_median - previous_median) > threshold
        if drift_warning:
            warnings.append(f"feature_drift_warning:{feature}")
        rows.append(
            {
                "feature": feature,
                "previous_n": int(len(previous)),
                "current_n": int(len(current)),
                "previous_median": previous_median,
                "current_median": current_median,
                "median_diff_current_minus_previous": float(current_median - previous_median),
                "drift_warning": bool(drift_warning),
            }
        )
    if not rows and not warnings:
        warnings.append("drift_sample_insufficient")
    return {"rows": rows, "warnings": warnings}


def _score_distribution(scores: pd.DataFrame, previous_scores: pd.DataFrame) -> dict[str, Any]:
    return {
        "metric": "human_entry_similarity",
        "current": _score_stats(scores),
        "previous": _score_stats(previous_scores),
        "median_delta_current_minus_previous": _median_delta(scores, previous_scores, "human_entry_similarity"),
    }


def _score_stats(scores: pd.DataFrame) -> dict[str, Any]:
    if scores.empty or "human_entry_similarity" not in scores.columns:
        return {"n": 0, "median": None, "q25": None, "q75": None}
    values = _clean_numeric(scores["human_entry_similarity"])
    if values.empty:
        return {"n": 0, "median": None, "q25": None, "q75": None}
    return {
        "n": int(len(values)),
        "median": float(values.median()),
        "q25": float(values.quantile(0.25)),
        "q75": float(values.quantile(0.75)),
    }


def _median_delta(current: pd.DataFrame, previous: pd.DataFrame, column: str) -> float | None:
    if current.empty or previous.empty or column not in current.columns or column not in previous.columns:
        return None
    current_values = _clean_numeric(current[column])
    previous_values = _clean_numeric(previous[column])
    if current_values.empty or previous_values.empty:
        return None
    return float(current_values.median() - previous_values.median())


def _review_queue_summary(review_queue: pd.DataFrame, annotations: pd.DataFrame) -> dict[str, Any]:
    if review_queue.empty:
        return {"total_count": 0, "completed_count": 0, "pending_count": 0, "completion_rate": None}
    total = int(len(review_queue))
    completed = 0
    if "queue_status" in review_queue.columns:
        completed = int(review_queue["queue_status"].astype(str).str.lower().isin({"completed", "done"}).sum())
    elif "completed_at" in review_queue.columns:
        completed = int(review_queue["completed_at"].notna().sum())
    elif "observation_id" in review_queue.columns and "observation_id" in annotations.columns:
        annotated = set(annotations["observation_id"].astype(str))
        completed = int(review_queue["observation_id"].astype(str).isin(annotated).sum())
    return {
        "total_count": total,
        "completed_count": completed,
        "pending_count": int(total - completed),
        "completion_rate": float(completed / total) if total else None,
    }


def _posterior_outcome_summary(outcomes: pd.DataFrame, outcome_cols: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for column in outcome_cols:
        if column not in outcomes.columns:
            continue
        values = _clean_numeric(outcomes[column])
        stats = _numeric_stats(values)
        tail = tail_concentration(values)
        rows.append(
            {
                "analysis_role": "posterior_only_not_model_input",
                "outcome_col": column,
                **stats,
                "quantiles": compute_quantiles(values),
                "tail_warning": bool(tail.get("heavy_tail_warning")),
            }
        )
    return rows


def _outcome_time_series(outcomes: pd.DataFrame, outcome_cols: list[str]) -> dict[str, Any]:
    fwd_cols = [column for column in outcome_cols if str(column).startswith("fwd_ret_")]
    if not fwd_cols or outcomes.empty:
        return {"rows": [], "warnings": ["outcome_time_series_sample_insufficient"]}
    try:
        rows = _records(outcome_time_series_diagnostics(outcomes, outcome_cols=fwd_cols, lags=10))
    except Exception as exc:
        return {"rows": [], "warnings": [f"outcome_time_series_failed:{type(exc).__name__}"]}
    warnings: list[str] = []
    for row in rows:
        if int(row.get("sample_count") or 0) < 11:
            warnings.append(f"outcome_time_series_sample_insufficient:{row.get('outcome_col')}")
        warnings.extend(str(item) for item in row.get("warnings") or [])
    return {"rows": rows, "warnings": sorted(set(warnings))}


def _manual_review_samples(
    annotations: pd.DataFrame,
    scores: pd.DataFrame,
    review_queue: pd.DataFrame,
    *,
    high_similarity_threshold: float,
    low_similarity_threshold: float,
    top_k: int,
) -> dict[str, list[dict[str, Any]]]:
    merged = pd.DataFrame()
    if not annotations.empty and not scores.empty and "observation_id" in annotations.columns and "observation_id" in scores.columns:
        merged = annotations[["observation_id", "human_decision"]].merge(
            scores[["observation_id", "human_entry_similarity"]],
            on="observation_id",
            how="inner",
        )
    high_reject = _sample_records(
        merged.loc[
            (merged.get("human_decision", pd.Series(dtype=str)).astype(str).str.upper() == "REJECT")
            & (pd.to_numeric(merged.get("human_entry_similarity"), errors="coerce") >= high_similarity_threshold)
        ]
        if not merged.empty
        else pd.DataFrame(),
        ascending=False,
        top_k=top_k,
    )
    low_entry = _sample_records(
        merged.loc[
            (merged.get("human_decision", pd.Series(dtype=str)).astype(str).str.upper() == "ENTRY")
            & (pd.to_numeric(merged.get("human_entry_similarity"), errors="coerce") <= low_similarity_threshold)
        ]
        if not merged.empty
        else pd.DataFrame(),
        ascending=True,
        top_k=top_k,
    )
    uncertain_source = review_queue if "human_entry_similarity" in review_queue.columns else scores
    uncertain = _uncertain_records(uncertain_source, top_k)
    return {
        "high_similarity_reject": high_reject,
        "low_similarity_entry": low_entry,
        "most_uncertain": uncertain,
    }


def _sample_records(df: pd.DataFrame, *, ascending: bool, top_k: int) -> list[dict[str, Any]]:
    if df.empty:
        return []
    ordered = df.assign(
        _score=pd.to_numeric(df["human_entry_similarity"], errors="coerce"),
        _id=df["observation_id"].astype(str),
    ).sort_values(["_score", "_id"], ascending=[ascending, True], kind="stable")
    return _records(ordered.drop(columns=["_score", "_id"]).head(max(0, int(top_k))))


def _uncertain_records(df: pd.DataFrame, top_k: int) -> list[dict[str, Any]]:
    if df.empty or "human_entry_similarity" not in df.columns or "observation_id" not in df.columns:
        return []
    ordered = df.assign(
        _distance=(pd.to_numeric(df["human_entry_similarity"], errors="coerce") - 0.5).abs(),
        _id=df["observation_id"].astype(str),
    ).sort_values(["_distance", "_id"], kind="stable")
    keep_cols = [column for column in ("observation_id", "human_entry_similarity", "review_reason", "queue_status") if column in ordered.columns]
    return _records(ordered[keep_cols].head(max(0, int(top_k))))


def _numeric_stats(values: Any) -> dict[str, Any]:
    clean = _clean_numeric(values)
    if clean.empty:
        return {"n": 0, "median": None, "iqr": None, "skewness": None, "excess_kurtosis": None}
    return {
        "n": int(len(clean)),
        "median": float(clean.median()),
        "iqr": float(clean.quantile(0.75) - clean.quantile(0.25)),
        "skewness": compute_skewness(clean),
        "excess_kurtosis": compute_excess_kurtosis(clean),
    }


def _clean_numeric(values: Any) -> pd.Series:
    return pd.to_numeric(pd.Series(values), errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return []
    return [_json_safe(record) for record in df.replace({np.nan: None}).to_dict(orient="records")]


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and np.isnan(value):
        return None
    if value is pd.NA:
        return None
    return value


def _remove_signal_names(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, nested in value.items():
            if any(token in str(key).lower() for token in SIGNAL_TOKENS):
                continue
            result[str(key)] = _remove_signal_names(nested)
        return result
    if isinstance(value, list):
        return [_remove_signal_names(item) for item in value]
    if isinstance(value, str) and any(token in value.lower() for token in SIGNAL_TOKENS):
        return ""
    return value


__all__ = [
    "build_weekly_research_report",
    "render_weekly_research_markdown",
    "write_weekly_research_report",
]
