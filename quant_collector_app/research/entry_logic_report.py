from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..time_series_analysis.entry_distribution_diagnostics import (
    compare_entry_reject_distributions,
    compute_excess_kurtosis,
    compute_quantiles,
    compute_skewness,
    feature_bin_outcome_summary,
    feature_drift_by_period,
    outcome_time_series_diagnostics,
    quantile_feature_binning,
    tail_concentration,
)
from .entry_context_features import build_feature_quality_report
from .entry_rule_mining import mine_single_feature_rule_hypotheses


DECISIONS = ("ENTRY", "REJECT", "UNCERTAIN", "UNLABELED")
FORBIDDEN_INPUT_FIELDS = ("future_return", "fwd_ret", "MFE", "MAE", "hit_tp", "hit_sl", "pnl", "profit", "win")
FORBIDDEN_INPUT_TOKENS = ("future_return", "fwd_ret", "fwd_", "future", "mfe", "mae", "hit_tp", "hit_sl")
FORBIDDEN_INPUT_EXACT = {"pnl", "profit", "win"}
FORBIDDEN_SIGNAL_TOKENS = ("buy_signal", "sell_signal", "trade_signal")
RISK_STATEMENTS = [
    "模型输出不是交易信号。",
    "不构成投资建议。",
    "样本内结果不代表未来收益。",
    "Model output and rule hypotheses are not a trading signal.",
]


def _empty_frame(value: pd.DataFrame | None) -> pd.DataFrame:
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _annotation_overview(annotations_df: pd.DataFrame) -> dict[str, int]:
    counts = {decision: 0 for decision in DECISIONS}
    if annotations_df.empty or "human_decision" not in annotations_df.columns:
        return counts
    values = annotations_df["human_decision"].astype(str).str.upper().value_counts()
    for decision in DECISIONS:
        counts[decision] = int(values.get(decision, 0))
    return counts


def _sample_time_range(features_df: pd.DataFrame, metadata: dict[str, Any] | None) -> dict[str, Any]:
    result = {
        "symbol": None,
        "interval": None,
        "data_start": None,
        "data_end": None,
    }
    if metadata:
        result.update({key: metadata.get(key, result.get(key)) for key in result})
    if features_df.empty:
        return result
    if "symbol" in features_df.columns and features_df["symbol"].notna().any():
        result["symbol"] = str(features_df["symbol"].dropna().astype(str).iloc[0])
    if "interval" in features_df.columns and features_df["interval"].notna().any():
        result["interval"] = str(features_df["interval"].dropna().astype(str).iloc[0])
    if "bar_time" in features_df.columns:
        times = pd.to_datetime(features_df["bar_time"], errors="coerce")
        if times.notna().any():
            result["data_start"] = str(features_df.loc[times.idxmin(), "bar_time"])
            result["data_end"] = str(features_df.loc[times.idxmax(), "bar_time"])
    return result


def _iqr(values: pd.Series) -> float | None:
    clean = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        return None
    return float(clean.quantile(0.75) - clean.quantile(0.25))


def _feature_distribution(features_df: pd.DataFrame, feature_cols: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for feature in feature_cols:
        if feature not in features_df.columns:
            continue
        clean = pd.to_numeric(features_df[feature], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        quantiles = compute_quantiles(clean)
        rows.append(
            {
                "feature": feature,
                "n": int(len(clean)),
                "median": float(clean.median()) if len(clean) else None,
                "iqr": _iqr(clean),
                "skewness": compute_skewness(clean),
                "excess_kurtosis": compute_excess_kurtosis(clean),
                "quantiles": quantiles,
            }
        )
    return rows


def _entry_reject_summary(
    annotations_df: pd.DataFrame,
    features_df: pd.DataFrame,
    feature_cols: list[str],
) -> list[dict[str, Any]]:
    if annotations_df.empty or features_df.empty:
        return []
    if "observation_id" not in annotations_df.columns or "observation_id" not in features_df.columns:
        return []
    merged = features_df.merge(annotations_df[["observation_id", "human_decision"]], on="observation_id", how="inner")
    merged["human_decision"] = merged["human_decision"].astype(str).str.upper()
    rows: list[dict[str, Any]] = []
    for feature in feature_cols:
        if feature not in merged.columns:
            continue
        entry = pd.to_numeric(merged.loc[merged["human_decision"] == "ENTRY", feature], errors="coerce").dropna()
        reject = pd.to_numeric(merged.loc[merged["human_decision"] == "REJECT", feature], errors="coerce").dropna()
        entry_median = float(entry.median()) if len(entry) else None
        reject_median = float(reject.median()) if len(reject) else None
        rows.append(
            {
                "feature": feature,
                "entry_n": int(len(entry)),
                "reject_n": int(len(reject)),
                "entry_median": entry_median,
                "reject_median": reject_median,
                "median_diff_entry_minus_reject": (
                    float(entry_median - reject_median)
                    if entry_median is not None and reject_median is not None
                    else None
                ),
            }
        )
    return rows


def _similarity_summary(scores_df: pd.DataFrame) -> dict[str, Any]:
    if scores_df.empty or "human_entry_similarity" not in scores_df.columns:
        return {"n": 0}
    scores = pd.to_numeric(scores_df["human_entry_similarity"], errors="coerce").dropna()
    if scores.empty:
        return {"n": 0}
    return {
        "metric": "human_entry_similarity",
        "n": int(len(scores)),
        "min": float(scores.min()),
        "median": float(scores.median()),
        "max": float(scores.max()),
        "q25": float(scores.quantile(0.25)),
        "q75": float(scores.quantile(0.75)),
    }


def _queue_records(review_queue_df: pd.DataFrame, top_k: int) -> list[dict[str, Any]]:
    if review_queue_df.empty:
        return []
    safe_cols = [
        column
        for column in ("observation_id", "human_entry_similarity", "setup_confidence", "review_reason", "review_mode")
        if column in review_queue_df.columns
    ]
    return review_queue_df.loc[:, safe_cols].head(max(0, int(top_k))).to_dict(orient="records")


def _safe_feature_cols(feature_cols: list[str]) -> list[str]:
    safe: list[str] = []
    for feature in feature_cols:
        lowered = str(feature).lower()
        if any(token in lowered for token in FORBIDDEN_SIGNAL_TOKENS):
            continue
        exact_hit = any(
            lowered == token
            or lowered.startswith(f"{token}_")
            or lowered.endswith(f"_{token}")
            for token in FORBIDDEN_INPUT_EXACT
        )
        if any(token in lowered for token in FORBIDDEN_INPUT_TOKENS) or exact_hit:
            continue
        safe.append(str(feature))
    return safe


def _leakage_check(features_df: pd.DataFrame, feature_cols: list[str]) -> dict[str, Any]:
    names = set(str(column) for column in feature_cols)
    if not features_df.empty:
        names.update(str(column) for column in features_df.columns)
    forbidden_found: list[str] = []
    signal_name_count = 0
    for name in sorted(names):
        lowered = name.lower()
        if any(token in lowered for token in FORBIDDEN_SIGNAL_TOKENS):
            signal_name_count += 1
            continue
        exact_hit = any(
            lowered == token
            or lowered.startswith(f"{token}_")
            or lowered.endswith(f"_{token}")
            for token in FORBIDDEN_INPUT_EXACT
        )
        if any(token in lowered for token in FORBIDDEN_INPUT_TOKENS) or exact_hit:
            forbidden_found.append(name)
    return {
        "status": "FAIL" if forbidden_found or signal_name_count else "PASS",
        "forbidden_fields": list(FORBIDDEN_INPUT_FIELDS),
        "forbidden_input_columns_found": forbidden_found,
        "forbidden_signal_name_count": signal_name_count,
        "context_features_are_model_input_candidates": True,
        "outcome_labels_saved_separately": True,
    }


def _normalized_split_summary(split_summary: dict[str, Any] | list[dict[str, Any]] | None) -> dict[str, Any]:
    if isinstance(split_summary, list):
        folds = [item for item in split_summary if isinstance(item, dict)]
        return {
            "split_method": "walk_forward",
            "fold_count": len(folds),
            "train_count": int(sum(int(item.get("train_count", item.get("train", 0)) or 0) for item in folds)),
            "validation_count": int(
                sum(int(item.get("validation_count", item.get("val_count", item.get("val", 0))) or 0) for item in folds)
            ),
            "test_count": int(sum(int(item.get("test_count", item.get("test", 0)) or 0) for item in folds)),
            "unlabeled_scored_count": 0,
            "purged_count": int(sum(int(item.get("purged_count", 0) or 0) for item in folds)),
            "embargoed_count": int(sum(int(item.get("embargoed_count", 0) or 0) for item in folds)),
            "episode_leakage_count": int(sum(int(item.get("episode_leakage_count", 0) or 0) for item in folds)),
            "horizon_bars": None,
            "embargo_bars": None,
            "folds": folds,
        }
    raw = dict(split_summary or {})
    return {
        "split_method": raw.get("split_method") or raw.get("method"),
        "train_count": int(raw.get("train_count", raw.get("train", 0)) or 0),
        "validation_count": int(raw.get("validation_count", raw.get("val_count", raw.get("val", 0))) or 0),
        "test_count": int(raw.get("test_count", raw.get("test", 0)) or 0),
        "unlabeled_scored_count": int(raw.get("unlabeled_scored_count", 0) or 0),
        "purged_count": int(raw.get("purged_count", 0) or 0),
        "embargoed_count": int(raw.get("embargoed_count", 0) or 0),
        "episode_leakage_count": int(raw.get("episode_leakage_count", 0) or 0),
        "horizon_bars": raw.get("horizon_bars"),
        "embargo_bars": raw.get("embargo_bars"),
    }


def _dataset_summary(annotation_overview: dict[str, int], split_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        **{decision: int(annotation_overview.get(decision, 0)) for decision in DECISIONS},
        "train_count": int(split_summary.get("train_count", 0) or 0),
        "validation_count": int(split_summary.get("validation_count", 0) or 0),
        "test_count": int(split_summary.get("test_count", 0) or 0),
        "unlabeled_scored_count": int(split_summary.get("unlabeled_scored_count", 0) or 0),
        "training_decisions": ["ENTRY", "REJECT"],
        "unlabeled_used_for_training": False,
        "uncertain_used_for_training": False,
    }


def _feature_timing_summary(
    features_df: pd.DataFrame,
    metadata: dict[str, Any] | None,
    feature_quality: dict[str, Any],
) -> dict[str, Any]:
    attr_report = features_df.attrs.get("feature_quality_report", {}) if isinstance(features_df, pd.DataFrame) else {}
    feature_spec = features_df.attrs.get("feature_spec", {}) if isinstance(features_df, pd.DataFrame) else {}
    meta = dict(metadata or {})
    policy = (
        feature_quality.get("feature_timing_policy")
        or attr_report.get("feature_timing_policy")
        or meta.get("feature_timing_policy")
        or feature_spec.get("feature_timing_policy")
    )
    allow_confirmation = (
        attr_report.get("allow_confirmation_bar")
        if "allow_confirmation_bar" in attr_report
        else meta.get("allow_confirmation_bar", feature_spec.get("allow_confirmation_bar"))
    )
    return {
        "feature_timing_policy": policy,
        "allow_confirmation_bar": allow_confirmation,
        "current_bar_close_policy": "CURRENT_BAR_CLOSE: feature_cutoff_bar_index = decision_bar_index",
        "next_bar_confirmation_policy": (
            "NEXT_BAR_CONFIRMATION: allow_confirmation_bar=True uses decision_bar_index; "
            "allow_confirmation_bar=False uses setup_bar_index"
        ),
        "feature_cutoff_rule": "context features only use bars with bar_index <= feature_cutoff_bar_index",
        "max_feature_cutoff_bar_index": feature_quality.get("max_feature_cutoff_bar_index")
        or attr_report.get("max_feature_cutoff_bar_index"),
        "future_cutoff_violation_count": int(
            feature_quality.get("future_cutoff_violation_count", attr_report.get("future_cutoff_violation_count", 0)) or 0
        ),
    }


def _model_summary(metadata: dict[str, Any] | None) -> dict[str, Any]:
    meta = dict(metadata or {})
    return {
        "model_type": meta.get("model_type"),
        "selected_threshold": meta.get("selected_threshold", meta.get("threshold")),
        "threshold_tuning_metric": meta.get("threshold_tuning_metric"),
        "validation_metrics": meta.get("validation_metrics") or {},
        "frozen_test_metrics": meta.get("frozen_test_metrics") or meta.get("test_metrics") or {},
        "validation_policy": "validation tunes threshold",
        "test_policy": "test is frozen evaluation",
    }


def _review_queue_summary(review_queue_df: pd.DataFrame, metadata: dict[str, Any] | None, top_k: int) -> dict[str, Any]:
    config = dict((metadata or {}).get("review_queue_config") or {})
    queue_type = config.get("queue_type") or config.get("mode") or config.get("name")
    if queue_type is None and not review_queue_df.empty and "review_mode" in review_queue_df.columns:
        values = review_queue_df["review_mode"].dropna().astype(str)
        queue_type = values.iloc[0] if not values.empty else None
    return {
        "queue_type": queue_type,
        "top_k": int(config.get("top_k", top_k) or top_k),
        "candidate_count": int(len(review_queue_df)),
        "statement": "review_queue is a manual review queue, not a trade list",
    }

def build_entry_logic_report(
    *,
    annotations_df: pd.DataFrame | None = None,
    features_df: pd.DataFrame | None = None,
    outcomes_df: pd.DataFrame | None = None,
    scores_df: pd.DataFrame | None = None,
    review_queue_df: pd.DataFrame | None = None,
    split_summary: dict[str, Any] | list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
    feature_cols: list[str] | None = None,
    outcome_cols: list[str] | None = None,
    top_k: int = 10,
) -> dict[str, Any]:
    annotations = _empty_frame(annotations_df)
    features = _empty_frame(features_df)
    outcomes = _empty_frame(outcomes_df)
    scores = _empty_frame(scores_df)
    review_queue = _empty_frame(review_queue_df)
    selected_features = _safe_feature_cols(list(feature_cols or []))
    warnings: list[str] = []
    if annotations.empty and features.empty and scores.empty and review_queue.empty:
        warnings.append("empty_input")
    if metadata and metadata.get("data_quality_warnings"):
        warnings.extend(str(warning) for warning in metadata.get("data_quality_warnings", []))
    feature_quality = build_feature_quality_report(features, feature_cols=selected_features).to_dict()
    if feature_quality["forbidden_fields_detected"]:
        warnings.append("feature_quality: forbidden_fields_detected")
    if feature_quality["constant_feature_cols"]:
        warnings.append("feature_quality: constant_feature_cols")
    nan_columns = [column for column, ratio in feature_quality["nan_ratio_by_col"].items() if float(ratio) > 0.0]
    if nan_columns:
        warnings.append("feature_quality: nan_ratio_by_col")
    normalized_split_summary = _normalized_split_summary(split_summary)
    annotation_overview = _annotation_overview(annotations)
    dataset_summary = _dataset_summary(annotation_overview, normalized_split_summary)
    feature_timing_summary = _feature_timing_summary(features, metadata, feature_quality)
    model_summary = _model_summary(metadata)
    review_queue_summary = _review_queue_summary(review_queue, metadata, top_k)
    enhanced = _enhanced_diagnostics(
        annotations,
        features,
        outcomes,
        selected_features,
        list(outcome_cols or []),
        top_k,
    )
    warnings.extend(enhanced["warnings"])
    return {
        "title": "Entry Logic Research Report",
        "research_goal": "学习用户开仓逻辑，不是收益预测。",
        "annotation_overview": annotation_overview,
        "dataset_summary": dataset_summary,
        "sample_time_range": _sample_time_range(features, metadata),
        "feature_distribution": _feature_distribution(features, selected_features),
        "entry_reject_summary": enhanced["entry_reject_summary"] or _entry_reject_summary(annotations, features, selected_features),
        "feature_binning": enhanced["feature_binning"],
        "rule_hypotheses": enhanced["rule_hypotheses"],
        "posterior_outcome_by_bin": enhanced["posterior_outcome_by_bin"],
        "outcome_time_series_diagnostics": enhanced["outcome_time_series_diagnostics"],
        "drift_diagnostics": enhanced["drift_diagnostics"],
        "diagnostic_feature_cols": selected_features,
        "similarity_score_summary": _similarity_summary(scores),
        "review_queue_top_k": _queue_records(review_queue, top_k),
        "review_queue_summary": review_queue_summary,
        "split_summary": normalized_split_summary,
        "feature_timing_summary": feature_timing_summary,
        "model_summary": model_summary,
        "feature_quality_report": feature_quality,
        "leakage_check": {
            **_leakage_check(features, list(feature_cols or [])),
        },
        "risk_statements": list(RISK_STATEMENTS),
        "warnings": warnings,
    }


def _enhanced_diagnostics(
    annotations: pd.DataFrame,
    features: pd.DataFrame,
    outcomes: pd.DataFrame,
    feature_cols: list[str],
    outcome_cols: list[str],
    top_k: int,
) -> dict[str, Any]:
    result = {
        "entry_reject_summary": [],
        "feature_binning": [],
        "rule_hypotheses": [],
        "posterior_outcome_by_bin": [],
        "outcome_time_series_diagnostics": [],
        "drift_diagnostics": [],
        "warnings": [],
    }
    if not feature_cols or features.empty or annotations.empty:
        return result
    if "observation_id" not in features.columns or "observation_id" not in annotations.columns:
        return result
    merged = features.merge(annotations[["observation_id", "human_decision"]], on="observation_id", how="inner")
    if merged.empty:
        return result
    merged["human_decision"] = merged["human_decision"].astype(str).str.upper()
    if len(merged) < 20:
        result["warnings"].append(f"sample_size_warning: {len(merged)} labeled rows < 20")
    try:
        result["entry_reject_summary"] = _json_records(
            compare_entry_reject_distributions(merged, "human_decision", feature_cols)
        )
    except Exception as exc:
        result["warnings"].append(f"entry_reject_diagnostics_failed: {type(exc).__name__}: {exc}")
    try:
        result["feature_binning"] = _json_records(quantile_feature_binning(merged, "human_decision", feature_cols, q=4))
    except Exception as exc:
        result["warnings"].append(f"feature_binning_failed: {type(exc).__name__}: {exc}")
    try:
        rules = mine_single_feature_rule_hypotheses(
            features,
            annotations,
            feature_cols=feature_cols,
            min_samples=2,
        ).head(max(0, int(top_k)))
        result["rule_hypotheses"] = _json_records(rules)
        if not rules.empty and rules["sample_warning"].notna().any():
            result["warnings"].append("sample_size_warning: rule hypothesis sample count below 20")
    except Exception as exc:
        result["warnings"].append(f"rule_hypothesis_mining_failed: {type(exc).__name__}: {exc}")
    for feature in feature_cols:
        if feature not in features.columns:
            continue
        tail = tail_concentration(features[feature])
        if tail.get("heavy_tail_warning"):
            result["warnings"].append(f"heavy_tail_warning: {feature}")
    if "bar_time" in features.columns:
        try:
            drift = feature_drift_by_period(features, "bar_time", feature_cols, period="M")
            result["drift_diagnostics"] = _json_records(drift)
            if not drift.empty and drift.get("drift_warning", pd.Series(dtype=bool)).astype(bool).any():
                result["warnings"].append("drift_warning: feature distribution drift by period")
        except Exception as exc:
            result["warnings"].append(f"drift_diagnostics_failed: {type(exc).__name__}: {exc}")
    safe_outcomes = [column for column in outcome_cols if column in outcomes.columns and _is_outcome_column(column)]
    if safe_outcomes and not outcomes.empty:
        try:
            result["posterior_outcome_by_bin"] = _json_records(
                feature_bin_outcome_summary(
                    features,
                    annotations,
                    outcomes,
                    feature_cols=feature_cols,
                    outcome_cols=safe_outcomes,
                    q=4,
                )
            )
        except Exception as exc:
            result["warnings"].append(f"posterior_outcome_by_bin_failed: {type(exc).__name__}: {exc}")
        fwd_cols = [column for column in safe_outcomes if str(column).startswith("fwd_ret_")]
        if fwd_cols:
            try:
                result["outcome_time_series_diagnostics"] = _json_records(
                    outcome_time_series_diagnostics(outcomes, outcome_cols=fwd_cols, lags=10)
                )
            except Exception as exc:
                result["warnings"].append(f"outcome_time_series_diagnostics_failed: {type(exc).__name__}: {exc}")
    return result


def _is_outcome_column(column: str) -> bool:
    lowered = str(column).lower()
    return any(token in lowered for token in ("fwd_ret", "mfe", "mae", "hit_tp", "hit_sl", "excursion"))


def _json_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return []
    clean = df.replace({np.nan: None})
    return [_json_safe(record) for record in clean.to_dict(orient="records")]


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and np.isnan(value):
        return None
    if value is pd.NA:
        return None
    return value


def render_entry_logic_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Entry Logic Research Report",
        "",
        str(report.get("research_goal", "学习用户开仓逻辑，不是收益预测。")),
        "",
        "## 标注概览",
        "",
    ]
    overview = report.get("annotation_overview") or {}
    for decision in DECISIONS:
        lines.append(f"- {decision}: {overview.get(decision, 0)}")
    dataset = report.get("dataset_summary") or {}
    lines.extend(
        [
            "",
            "## Dataset Summary",
            "",
            f"- ENTRY count: {dataset.get('ENTRY', overview.get('ENTRY', 0))}",
            f"- REJECT count: {dataset.get('REJECT', overview.get('REJECT', 0))}",
            f"- UNCERTAIN count: {dataset.get('UNCERTAIN', overview.get('UNCERTAIN', 0))}",
            f"- UNLABELED count: {dataset.get('UNLABELED', overview.get('UNLABELED', 0))}",
            f"- train / validation / test count: {dataset.get('train_count', 0)} / {dataset.get('validation_count', 0)} / {dataset.get('test_count', 0)}",
            f"- unlabeled scored count: {dataset.get('unlabeled_scored_count', 0)}",
            "- UNLABELED not used for training.",
            "- UNCERTAIN not used for training or evaluation by default.",
        ]
    )
    sample_range = report.get("sample_time_range") or {}
    lines.extend(
        [
            "",
            "## 样本时间范围",
            "",
            f"- symbol: {sample_range.get('symbol') or '-'}",
            f"- interval: {sample_range.get('interval') or '-'}",
            f"- data_start: {sample_range.get('data_start') or '-'}",
            f"- data_end: {sample_range.get('data_end') or '-'}",
            "",
            "## 特征分布摘要",
            "",
        ]
    )
    feature_distribution = report.get("feature_distribution") or []
    if feature_distribution:
        for row in feature_distribution:
            lines.append(
                f"- {row['feature']}: median={row.get('median')}, IQR={row.get('iqr')}, "
                f"skewness={row.get('skewness')}, excess_kurtosis={row.get('excess_kurtosis')}"
            )
    else:
        lines.append("- 无可用特征分布。")
    lines.extend(["", "## ENTRY vs REJECT 差异摘要", ""])
    entry_reject = report.get("entry_reject_summary") or []
    if entry_reject:
        for row in entry_reject:
            lines.append(
                f"- {row['feature']}: ENTRY median={row.get('entry_median')}, "
                f"REJECT median={row.get('reject_median')}, diff={row.get('median_diff_entry_minus_reject')}"
            )
    else:
        lines.append("- 无可用 ENTRY vs REJECT 对照。")
    lines.extend(["", "## human_entry_similarity 分数摘要", ""])
    score_summary = report.get("similarity_score_summary") or {}
    if score_summary.get("n", 0):
        lines.append(
            f"- human_entry_similarity: n={score_summary.get('n')}, "
            f"median={score_summary.get('median')}, min={score_summary.get('min')}, max={score_summary.get('max')}"
        )
    else:
        lines.append("- 无可用 human_entry_similarity 分数。")
    model = report.get("model_summary") or {}
    lines.extend(
        [
            "",
            "## Model Summary",
            "",
            f"- model_type: {model.get('model_type') or '-'}",
            f"- selected_threshold: {model.get('selected_threshold')}",
            f"- validation tuning metric: {model.get('threshold_tuning_metric') or '-'}",
            "- validation tunes threshold.",
            "- test is frozen evaluation.",
            f"- validation_metrics: {model.get('validation_metrics') or {}}",
            f"- frozen_test_metrics: {model.get('frozen_test_metrics') or {}}",
        ]
    )
    lines.extend(["", "## Top-k 候选复标队列", ""])
    queue_summary = report.get("review_queue_summary") or {}
    lines.extend(
        [
            f"- queue_type: {queue_summary.get('queue_type') or '-'}",
            f"- top_k: {queue_summary.get('top_k') or '-'}",
            "- review_queue is a manual review queue, not a trade list.",
        ]
    )
    queue = report.get("review_queue_top_k") or []
    if queue:
        for row in queue:
            lines.append(
                f"- {row.get('observation_id')}: human_entry_similarity={row.get('human_entry_similarity')}, "
                f"review_reason={row.get('review_reason')}"
            )
    else:
        lines.append("- 未提供 review queue。")
    lines.extend(["", "## 时间切分摘要", ""])
    split = report.get("split_summary") or {}
    lines.extend(
        [
            f"- split_method: {split.get('split_method') or '-'}",
            f"- train / validation / test count: {split.get('train_count', 0)} / {split.get('validation_count', 0)} / {split.get('test_count', 0)}",
            f"- purged_count: {split.get('purged_count', 0)}",
            f"- embargoed_count: {split.get('embargoed_count', 0)}",
            f"- episode_leakage_count: {split.get('episode_leakage_count', 0)}",
            f"- horizon_bars: {split.get('horizon_bars')}",
            f"- embargo_bars: {split.get('embargo_bars')}",
        ]
    )
    feature_timing = report.get("feature_timing_summary") or {}
    lines.extend(
        [
            "",
            "## Feature Timing Summary",
            "",
            f"- feature_timing_policy: {feature_timing.get('feature_timing_policy') or '-'}",
            f"- allow_confirmation_bar: {feature_timing.get('allow_confirmation_bar')}",
            f"- CURRENT_BAR_CLOSE policy: {feature_timing.get('current_bar_close_policy')}",
            f"- NEXT_BAR_CONFIRMATION policy: {feature_timing.get('next_bar_confirmation_policy')}",
            f"- feature_cutoff_bar_index rule: {feature_timing.get('feature_cutoff_rule')}",
            f"- future_cutoff_violation_count: {feature_timing.get('future_cutoff_violation_count', 0)}",
        ]
    )
    lines.extend(
        [
            "",
            "## 泄漏检查",
            "",
            f"- 状态: {report.get('leakage_check', {}).get('status')}",
            f"- 禁止输入字段: {', '.join(report.get('leakage_check', {}).get('forbidden_fields', []))}",
            f"- 命中禁止输入字段: {', '.join(report.get('leakage_check', {}).get('forbidden_input_columns_found', [])) or '无'}",
            f"- 禁止交易信号命名数量: {report.get('leakage_check', {}).get('forbidden_signal_name_count', 0)}",
            "- context features do not contain outcome-label inputs.",
            "- outcome labels are saved separately for posterior analysis and reports.",
            "",
            "## 风险声明",
            "",
        ]
    )
    lines.extend(f"- {statement}" for statement in report.get("risk_statements", RISK_STATEMENTS))
    if report.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in report["warnings"])
    return "\n".join(lines) + "\n"


def write_entry_logic_report(
    markdown_path: str | Path,
    json_path: str | Path,
    report: dict[str, Any],
) -> dict[str, str]:
    markdown_target = Path(markdown_path)
    json_target = Path(json_path)
    markdown_target.parent.mkdir(parents=True, exist_ok=True)
    json_target.parent.mkdir(parents=True, exist_ok=True)
    markdown_target.write_text(render_entry_logic_markdown(report), encoding="utf-8")
    json_target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return {"markdown_path": str(markdown_target), "json_path": str(json_target)}


__all__ = ["build_entry_logic_report", "render_entry_logic_markdown", "write_entry_logic_report"]
