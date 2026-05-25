from __future__ import annotations

import json
import math
import operator
from typing import Any

import numpy as np
import pandas as pd

from .profile import StrategyProfile, profile_to_dict
from .scoring import (
    apply_score_caps,
    profile_completeness_score,
    rounded_components,
    sample_sufficiency_score,
    score_interpretation,
)


FORBIDDEN_PREFIXES = ("fwd_", "post_", "future", "label", "exit", "pnl")
FORBIDDEN_TOKENS = (
    "mfe",
    "mae",
    "manual_trade_final",
    "manual_trade_holding",
    "net_return_pct",
    "gross_return_pct",
    "final_return_pct",
    "pnl",
    "exit_return",
)
DEFAULT_CONTEXT_FEATURES = [
    "pre_ret_5",
    "pre_ret_10",
    "pre_ret_20",
    "pre_max_drawdown_20",
    "pre_volatility_20",
    "volatility_regime",
    "trend_regime",
    "event_lower_wick_ratio",
    "event_close_position",
    "event_volume_ratio_20",
    "close_position",
    "volume_zscore_20",
]
GENERIC_TAGS = {"其他", "其它", "other", "others", "test", "selfcheck", "unknown", "none", "未分类"}
OPS = {"<=": operator.le, ">=": operator.ge, "<": operator.lt, ">": operator.gt, "==": operator.eq}


def _is_forbidden_column(name: str) -> bool:
    lower = str(name or "").lower()
    return lower.startswith(FORBIDDEN_PREFIXES) or any(token in lower for token in FORBIDDEN_TOKENS)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return value


def _to_df(value: pd.DataFrame | None) -> pd.DataFrame:
    return value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _parse_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    try:
        if pd.isna(value):
            return []
    except Exception:
        pass
    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except (TypeError, json.JSONDecodeError):
        pass
    return [part.strip() for part in text.replace("，", ";").replace(",", ";").split(";") if part.strip()]


def _tag_series(events: pd.DataFrame) -> list[list[str]]:
    column = "label_tags_json" if "label_tags_json" in events.columns else "label_tags" if "label_tags" in events.columns else None
    return [_parse_tags(value) for value in events[column].tolist()] if column else [[] for _ in range(len(events))]


def _tag_counts(tags_per_row: list[list[str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for tags in tags_per_row:
        for tag in tags:
            counts[tag] = counts.get(tag, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _pct(part: int | float, whole: int | float) -> float:
    return float(part) / float(whole) * 100.0 if whole else 0.0


def _entropy(counts: dict[str, int]) -> float:
    total = sum(counts.values())
    if not total:
        return 0.0
    return float(-sum((count / total) * math.log2(count / total) for count in counts.values() if count))


def _num(df: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(df[column], errors="coerce") if column in df.columns else pd.Series(dtype=float)


def _mean(df: pd.DataFrame, column: str) -> float | None:
    values = _num(df, column).dropna()
    return float(values.mean()) if not values.empty else None


def _median(df: pd.DataFrame, column: str) -> float | None:
    values = _num(df, column).dropna()
    return float(values.median()) if not values.empty else None


def _merge_events_features(events: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    if events.empty or features.empty:
        return events.copy()
    if "event_id" in events.columns and "event_id" in features.columns:
        return events.merge(features, on="event_id", how="left", suffixes=("", "_feature"))
    result = events.reset_index(drop=True).copy()
    if len(result) == len(features):
        for column in features.columns:
            if column not in result.columns:
                result[column] = features[column].reset_index(drop=True)
    return result


def _profile_feature_match_stats(features: pd.DataFrame, profile: StrategyProfile) -> dict[str, Any]:
    empty = {
        "profile_feature_match_pct": None,
        "profile_feature_match_any_pct": None,
        "profile_feature_match_all_pct": None,
        "profile_feature_condition_hit_rates": {},
    }
    if features.empty or not profile.expected_entry_features:
        return empty
    masks: list[pd.Series] = []
    rates: dict[str, float] = {}
    for column, specification in profile.expected_entry_features.items():
        if _is_forbidden_column(column):
            raise ValueError(f"Forbidden result/future field used in strategy consistency profile: {column}")
        if column not in features.columns:
            continue
        comparison = OPS.get(str(specification.get("op", "")))
        if comparison is None:
            continue
        try:
            target = float(specification["value"])
        except (KeyError, TypeError, ValueError):
            continue
        values = pd.to_numeric(features[column], errors="coerce")
        valid = values.notna()
        if not valid.any():
            continue
        mask = comparison(values, target).where(valid, False).astype(bool)
        masks.append(mask)
        rates[column] = float(mask[valid].mean() * 100.0)
    if not masks:
        return empty
    matrix = pd.concat(masks, axis=1).fillna(False)
    return {
        "profile_feature_match_pct": float(np.mean(list(rates.values()))),
        "profile_feature_match_any_pct": float(matrix.any(axis=1).mean() * 100.0),
        "profile_feature_match_all_pct": float(matrix.all(axis=1).mean() * 100.0),
        "profile_feature_condition_hit_rates": rates,
    }


def _label_score_detail(
    sample_count: int,
    tag_counts: dict[str, int],
    required_tag_coverage_pct: float,
    untagged_pct: float,
    forbidden_tag_hit_count: int,
) -> dict[str, float]:
    if not sample_count:
        return {
            "required_tag_score_pct": 0.0,
            "tagged_score_pct": 0.0,
            "meaningful_top_tag_score_pct": 0.0,
            "forbidden_tag_penalty_pct": 0.0,
            "label_score_pct": 0.0,
            "label_score_points": 0.0,
        }
    meaningful = {tag: count for tag, count in tag_counts.items() if tag.strip().lower() not in GENERIC_TAGS}
    top_coverage = _pct(max(meaningful.values(), default=0), sample_count)
    penalty = min(100.0, _pct(forbidden_tag_hit_count, sample_count) * 2.0)
    percentage = max(
        0.0,
        min(100.0, required_tag_coverage_pct * 0.55 + (100.0 - untagged_pct) * 0.30 + top_coverage * 0.15 - penalty),
    )
    return {
        "required_tag_score_pct": round(required_tag_coverage_pct, 2),
        "tagged_score_pct": round(100.0 - untagged_pct, 2),
        "meaningful_top_tag_score_pct": round(top_coverage, 2),
        "forbidden_tag_penalty_pct": round(penalty, 2),
        "label_score_pct": round(percentage, 2),
        "label_score_points": round(15.0 * percentage / 100.0, 2),
    }


def _direction_metrics(open_events: pd.DataFrame, profile: StrategyProfile | None) -> tuple[int, int, float, float, list[str]]:
    sides = open_events.get("side", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
    long_count = int((sides == "LONG").sum())
    short_count = int((sides == "SHORT").sum())
    count = len(open_events)
    concentration = _pct(max(long_count, short_count), count)
    allowed = set(profile.allowed_sides or []) if profile else set()
    warnings: list[str] = []
    if not allowed:
        if count:
            warnings.append("direction discipline cannot be fully evaluated without a strategy profile")
        if concentration >= 95.0 and count:
            warnings.append("side_concentration: direction preference is observed but no allowed_sides is declared")
            return long_count, short_count, concentration, 3.0, warnings
        return long_count, short_count, concentration, 4.0 if count else 0.0, warnings
    compliant = int(sides.isin(allowed).sum())
    compliance = _pct(compliant, count)
    if allowed == {"LONG", "SHORT"} and count and (not long_count or not short_count):
        warnings.append("directional_coverage_warning: profile declares both sides but only one side is observed")
        return long_count, short_count, compliance, 6.0, warnings
    if compliant < count:
        warnings.append("direction violation: trades outside allowed_sides were observed")
    return long_count, short_count, compliance, 10.0 * compliance / 100.0, warnings


def _similar_context_agreement(df: pd.DataFrame, max_neighbors: int) -> tuple[float | None, int, list[dict[str, Any]], str | None]:
    columns = [column for column in DEFAULT_CONTEXT_FEATURES if column in df.columns and not _is_forbidden_column(column)]
    numeric_columns = [column for column in columns if pd.api.types.is_numeric_dtype(df[column])]
    if len(numeric_columns) < 3 or df.empty or "side" not in df.columns:
        return None, 0, [], "fewer than 3 usable context features"
    event_id = df.get("event_id", pd.Series([""] * len(df), index=df.index))
    event_type = df.get("event_type", pd.Series(["OPEN"] * len(df), index=df.index))
    work = pd.DataFrame({"event_id": event_id, "event_type": event_type, "side": df["side"]})
    for column in numeric_columns:
        work[column] = pd.to_numeric(df[column], errors="coerce")
    work = work.dropna(subset=numeric_columns).reset_index(drop=True)
    if len(work) < 3:
        return None, int(len(work)), [], "not enough complete rows for neighbor comparison"
    values = work[numeric_columns].to_numpy(dtype=float)
    scale = values.std(axis=0)
    scale[scale == 0] = 1.0
    standardized = (values - values.mean(axis=0)) / scale
    actions = (work["event_type"].astype(str).str.upper() + "_" + work["side"].astype(str).str.upper()).tolist()
    agreements: list[float] = []
    conflicts: list[dict[str, Any]] = []
    neighbor_count = max(1, min(int(max_neighbors), len(work) - 1))
    for row in range(len(work)):
        distances = np.sqrt(((standardized - standardized[row]) ** 2).sum(axis=1))
        neighbors = [int(index) for index in np.argsort(distances) if int(index) != row][:neighbor_count]
        agreements.append(sum(actions[index] == actions[row] for index in neighbors) / len(neighbors))
        conflict = next((index for index in neighbors if actions[index] != actions[row]), None)
        if conflict is not None and len(conflicts) < 10:
            conflicts.append(
                {
                    "event_id": str(work.iloc[row]["event_id"]),
                    "neighbor_event_id": str(work.iloc[conflict]["event_id"]),
                    "action": actions[row],
                    "neighbor_action": actions[conflict],
                    "distance": float(distances[conflict]),
                }
            )
    return float(np.mean(agreements) * 100.0), int(len(work)), conflicts, None


def _time_stability(df: pd.DataFrame, tags_per_row: list[list[str]]) -> tuple[dict[str, Any], bool, bool, bool]:
    if len(df) < 6:
        return {}, False, False, False
    reset = df.reset_index(drop=True)
    index_parts = np.array_split(np.arange(len(reset)), 3)
    parts = [reset.iloc[indexes].copy() for indexes in index_parts]
    feature_shift: dict[str, Any] = {}
    feature_drift = False
    for column in [name for name in DEFAULT_CONTEXT_FEATURES if name in df.columns]:
        means = [float(pd.to_numeric(part[column], errors="coerce").mean()) for part in parts]
        valid = [value for value in means if math.isfinite(value)]
        feature_shift[column] = dict(zip(["early", "middle", "late"], means))
        if len(valid) >= 2 and max(valid) - min(valid) > max(0.02, abs(float(np.mean(valid)))):
            feature_drift = True
    ratios = [_pct(int((part.get("side", pd.Series(dtype=str)).astype(str).str.upper() == "LONG").sum()), len(part)) for part in parts]
    direction_drift = max(ratios) - min(ratios) > 40.0
    top_tags = []
    start = 0
    for part in parts:
        end = start + len(part)
        top_tags.append(next(iter(_tag_counts(tags_per_row[start:end])), None))
        start = end
    tag_drift = len({tag for tag in top_tags if tag}) > 1
    return feature_shift, direction_drift, tag_drift, feature_drift


def _closed_trade_count(trades: pd.DataFrame, close_event_count: int) -> int:
    if not trades.empty and "status" in trades.columns:
        return int((trades["status"].fillna("").astype(str).str.upper() == "CLOSED").sum())
    return close_event_count


def _has_exit_metadata(trades: pd.DataFrame) -> bool:
    for column in ("exit_reason", "exit_event_type", "close_reason"):
        if column in trades.columns and trades[column].fillna("").astype(str).str.strip().ne("").any():
            return True
    return False


def _risk_metadata(profile: StrategyProfile | None, trades: pd.DataFrame) -> bool:
    if profile and profile.risk_model and (profile.stop_loss_pct is not None or profile.take_profit_pct is not None):
        return True
    return all(column in trades.columns and trades[column].notna().any() for column in ("fee_bps", "slippage_bps"))


def apply_consistency_gates(result: dict, profile: StrategyProfile | None) -> dict:
    output = dict(result)
    failures: list[str] = []
    if int(output.get("sample_count", 0)) < int((profile.min_sample_count if profile else 30)):
        failures.append("sample_count below min_sample_count")
    allowed = set(profile.allowed_sides or []) if profile else set()
    if len(allowed) == 1 and float(output.get("direction_consistency_pct", 0.0)) < 70.0:
        failures.append("direction_consistency_pct below hard floor for declared allowed_sides")
    if float(output.get("untagged_pct", 0.0)) > 60.0:
        failures.append("untagged_pct too high")
    if profile and float(output.get("missing_note_pct", 0.0)) > float(profile.max_missing_note_pct):
        failures.append("missing_note_pct above profile limit")
    if bool(output.get("possible_selection_bias_warning")):
        failures.append("possible_selection_bias_warning is true")
    if int(output.get("forbidden_tag_hit_count", 0)) > 0:
        failures.append("forbidden_tag_hit_count > 0")
    output["gate_failures"] = failures
    if output.get("total_score") is None:
        output["recommendation"] = "invalid_due_to_leakage"
    elif failures and output.get("recommendation") == "suitable_for_analysis":
        output["recommendation"] = "needs_manual_review"
    if any("direction_consistency_pct" in failure for failure in failures):
        output["recommendation"] = "not_suitable_for_rule_mining"
    return output


def analyze_strategy_consistency(
    events: pd.DataFrame,
    features: pd.DataFrame,
    trades: pd.DataFrame | None = None,
    profile: StrategyProfile | None = None,
    max_neighbors: int = 5,
    leakage_audit_status: str = "PASS",
    data_quality_status: str = "PASS",
) -> dict:
    profile_provided = profile is not None
    active_profile = profile or StrategyProfile(name="Unspecified Strategy")
    events = _to_df(events)
    features = _to_df(features)
    trades = _to_df(trades)
    for column in active_profile.expected_entry_features:
        if _is_forbidden_column(column):
            raise ValueError(f"Forbidden result/future field used in strategy consistency profile: {column}")

    event_types = events.get("event_type", pd.Series([""] * len(events))).fillna("").astype(str).str.upper()
    opens = events[event_types.isin(["OPEN", "OPEN_LONG", "OPEN_SHORT"])].copy()
    if opens.empty and not events.empty:
        opens = events.copy()
    close_count = int(event_types.str.contains("CLOSE").sum())
    closed_trades = _closed_trade_count(trades, close_count)
    sample_count = int(len(opens))
    merged = _merge_events_features(opens, features)
    tags_per_row = _tag_series(opens)
    tag_counts = _tag_counts(tags_per_row)
    tagged_rows = sum(bool(tags) for tags in tags_per_row)
    untagged_pct = 100.0 - _pct(tagged_rows, sample_count)
    required = set(active_profile.required_entry_tags or active_profile.required_tags)
    required_hits = sum(bool(set(tags) & required) for tags in tags_per_row) if required else tagged_rows
    forbidden_hits = sum(bool(set(tags) & set(active_profile.forbidden_tags)) for tags in tags_per_row)
    required_tag_coverage_pct = _pct(required_hits, sample_count)
    note_values = opens.get("note", pd.Series([""] * sample_count)).fillna("").astype(str).str.strip()
    missing_note_pct = _pct(int((note_values == "").sum()), sample_count)
    label_detail = _label_score_detail(sample_count, tag_counts, required_tag_coverage_pct, untagged_pct, forbidden_hits)

    long_count, short_count, direction_pct, direction_score, direction_warnings = _direction_metrics(opens, active_profile if profile_provided else None)
    match_stats = _profile_feature_match_stats(merged, active_profile)
    similar_pct, neighbor_count, conflicts, neighbor_warning = _similar_context_agreement(merged, max_neighbors)
    feature_shift, direction_drift, tag_drift, feature_drift = _time_stability(merged, tags_per_row)
    selection_bias = sample_count > 0 and close_count < max(1, int(sample_count * 0.3))
    has_labels = tagged_rows > 0
    has_risk = _risk_metadata(active_profile if profile_provided else None, trades)
    has_exit = _has_exit_metadata(trades)

    setup_basis = similar_pct if similar_pct is not None else match_stats["profile_feature_match_all_pct"]
    setup_score = 5.0 if setup_basis is None else 10.0 * float(setup_basis) / 100.0
    risk_score = 0.0
    if has_risk:
        risk_score = 10.0
        if not trades.empty and all(column in trades.columns for column in ("fee_bps", "slippage_bps")):
            risk_score = 15.0
    exit_score = 10.0 if has_exit else 4.0 if close_count else 0.0
    stability_score = 10.0 - 2.5 * sum((direction_drift, tag_drift, feature_drift, selection_bias))
    quality_score = 5.0 if leakage_audit_status.upper() == "PASS" and data_quality_status.upper() in {"PASS", "OK"} else 0.0
    components = rounded_components(
        {
            "sample_sufficiency": sample_sufficiency_score(closed_trades),
            "profile_completeness": profile_completeness_score(active_profile, profile_provided),
            "entry_tag_consistency": label_detail["label_score_points"],
            "direction_discipline": direction_score,
            "entry_setup_consistency": setup_score,
            "risk_execution_discipline": risk_score,
            "exit_discipline": exit_score,
            "result_stability": max(0.0, stability_score),
            "data_quality_audit": quality_score,
        }
    )
    raw_score = round(sum(components.values()), 2)
    total_score, caps = apply_score_caps(
        raw_score,
        profile_provided=profile_provided,
        closed_trades=closed_trades,
        has_labels=has_labels,
        has_risk_metadata=has_risk,
        has_exit_metadata=has_exit,
        leakage_audit_status=leakage_audit_status,
        data_quality_status=data_quality_status,
    )
    warnings = list(direction_warnings)
    if closed_trades < 30:
        warnings.append("closed trade sample is insufficient for a strong consistency conclusion")
    if not profile_provided:
        warnings.append("no StrategyProfile is declared; direction concentration is descriptive only")
    if not has_labels:
        warnings.append("entry labels are missing")
    if not has_risk:
        warnings.append("risk metadata is missing")
    if not has_exit:
        warnings.append("exit reason metadata is missing")
    if neighbor_warning:
        warnings.append(neighbor_warning)
    if selection_bias:
        warnings.append("possible selection bias: close/failed samples may be underrepresented")
    warnings.extend(caps)
    suggested_actions = []
    if not profile_provided:
        suggested_actions.append("declare a StrategyProfile before interpreting consistency")
    if not has_risk:
        suggested_actions.append("record fee, slippage and risk rules")
    if not has_exit:
        suggested_actions.append("record exit reasons or exit event types")
    if total_score is None:
        suggested_actions.append("repair leakage audit failures before scoring")

    result = {
        "model_version": "v2",
        "sample_count": sample_count,
        "open_event_count": int(event_types.str.contains("OPEN").sum()),
        "close_event_count": close_count,
        "closed_trade_count": closed_trades,
        "long_count": long_count,
        "short_count": short_count,
        "side_concentration_pct": _pct(max(long_count, short_count), sample_count),
        "direction_consistency_pct": direction_pct,
        "untagged_pct": untagged_pct,
        "missing_note_pct": missing_note_pct,
        "top_tags": dict(list(tag_counts.items())[:20]),
        "top_tag_coverage_pct": _pct(max(tag_counts.values(), default=0), sample_count),
        "label_entropy": _entropy(tag_counts),
        "required_tag_coverage_pct": required_tag_coverage_pct,
        "forbidden_tag_hit_count": forbidden_hits,
        "label_score_detail": label_detail,
        "pre_ret_20_mean": _mean(merged, "pre_ret_20"),
        "pre_ret_20_median": _median(merged, "pre_ret_20"),
        "pre_ret_20_negative_pct": _pct(int((_num(merged, "pre_ret_20") < 0).sum()), int(_num(merged, "pre_ret_20").notna().sum())),
        "pre_max_drawdown_20_mean": _mean(merged, "pre_max_drawdown_20"),
        "event_lower_wick_ratio_mean": _mean(merged, "event_lower_wick_ratio"),
        "event_volume_ratio_20_mean": _mean(merged, "event_volume_ratio_20"),
        **match_stats,
        "similar_context_agreement_pct": similar_pct,
        "neighbor_sample_count": neighbor_count,
        "conflict_examples": conflicts,
        "early_mid_late_feature_shift": feature_shift,
        "direction_drift_warning": direction_drift,
        "tag_drift_warning": tag_drift,
        "feature_drift_warning": feature_drift,
        "low_sample_warning": closed_trades < 30,
        "mixed_direction_warning": any("direction violation" in warning for warning in direction_warnings),
        "directional_coverage_warning": any("directional_coverage_warning" in warning for warning in direction_warnings),
        "high_untagged_warning": untagged_pct > 50.0,
        "high_missing_note_warning": missing_note_pct > active_profile.max_missing_note_pct,
        "possible_random_trading_warning": total_score is None or total_score < 60.0,
        "possible_selection_bias_warning": selection_bias,
        "leakage_audit_status": leakage_audit_status,
        "data_quality_status": data_quality_status,
        "raw_score": raw_score,
        "total_score": total_score,
        "strategy_consistency_score": total_score,
        "component_scores": components,
        "score_components": components,
        "caps_applied": caps,
        "recommendation": "invalid_due_to_leakage" if total_score is None else "suitable_for_analysis" if total_score >= 80 else "needs_manual_review" if total_score >= 60 else "not_suitable_for_rule_mining",
        "interpretation": score_interpretation(total_score),
        "suggested_actions": suggested_actions,
        "profile": profile_to_dict(active_profile) if profile_provided else None,
        "warnings": warnings,
        "notice": "Strategy consistency measures repeatability, not profitability. Long-only or short-only behavior is not a consistency fault unless the declared profile requires both sides.",
        "result_stability_interpretation": "This is a behavioral stability proxy, not a full out-of-sample performance validation.",
    }
    return _json_safe(apply_consistency_gates(result, active_profile if profile_provided else None))
