from __future__ import annotations

import json
import math
import operator
from typing import Any

import numpy as np
import pandas as pd

from .profile import StrategyProfile, default_reversal_long_profile, profile_to_dict


FORBIDDEN_PREFIXES = ("fwd_", "post_")
FORBIDDEN_TOKENS = (
    "mfe",
    "mae",
    "manual_trade_final",
    "manual_trade_holding",
    "net_return_pct",
    "gross_return_pct",
    "final_return_pct",
)
DEFAULT_CONTEXT_FEATURES = [
    "pre_ret_20",
    "pre_max_drawdown_20",
    "pre_volatility_20",
    "event_lower_wick_ratio",
    "event_close_position",
    "event_volume_ratio_20",
    "event_body_ratio",
    "capitulation_score",
]
GENERIC_TAGS = {"其他", "其它", "other", "others", "test", "selfcheck", "unknown", "none", "未分类"}
RECOMMENDATION_RANK = {
    "not_suitable_for_rule_mining": 0,
    "needs_manual_review": 1,
    "suitable_for_analysis": 2,
}
OPS = {
    "<=": operator.le,
    ">=": operator.ge,
    "<": operator.lt,
    ">": operator.gt,
    "==": operator.eq,
}


def _is_forbidden_column(name: str) -> bool:
    lower = str(name or "").lower()
    return lower.startswith(FORBIDDEN_PREFIXES) or any(token in lower for token in FORBIDDEN_TOKENS)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        out = float(value)
        return out if math.isfinite(out) else None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
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
        return [str(x).strip() for x in value if str(x).strip()]
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
            return [str(x).strip() for x in parsed if str(x).strip()]
        if parsed:
            return [str(parsed).strip()]
    except Exception:
        pass
    return [p.strip() for p in text.replace("；", ";").replace(",", ";").split(";") if p.strip()]


def _tag_series(events: pd.DataFrame) -> list[list[str]]:
    if events.empty:
        return []
    col = "label_tags_json" if "label_tags_json" in events.columns else ("label_tags" if "label_tags" in events.columns else None)
    if col is None:
        return [[] for _ in range(len(events))]
    return [_parse_tags(v) for v in events[col].tolist()]


def _tag_counts(tags_per_row: list[list[str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for tags in tags_per_row:
        for tag in tags:
            counts[tag] = counts.get(tag, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _entropy(counts: dict[str, int]) -> float:
    total = sum(counts.values())
    if total <= 0:
        return 0.0
    out = 0.0
    for count in counts.values():
        p = count / total
        if p > 0:
            out -= p * math.log2(p)
    return float(out)


def _pct(part: int | float, whole: int | float) -> float:
    return float(part) / float(whole) * 100.0 if whole else 0.0


def _num(df: pd.DataFrame, column: str) -> pd.Series:
    if df.empty or column not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[column], errors="coerce")


def _mean(df: pd.DataFrame, column: str) -> float | None:
    s = _num(df, column).dropna()
    return float(s.mean()) if not s.empty else None


def _median(df: pd.DataFrame, column: str) -> float | None:
    s = _num(df, column).dropna()
    return float(s.median()) if not s.empty else None


def _profile_feature_match_stats(features: pd.DataFrame, profile: StrategyProfile) -> dict[str, Any]:
    specs = profile.expected_entry_features or {}
    empty = {
        "profile_feature_match_pct": None,
        "profile_feature_match_any_pct": None,
        "profile_feature_match_all_pct": None,
        "profile_feature_condition_hit_rates": {},
    }
    if not specs or features.empty:
        return empty

    masks = []
    condition_rates: dict[str, float] = {}
    for col, spec in specs.items():
        if _is_forbidden_column(col):
            raise ValueError(f"Forbidden result/future field used in strategy consistency profile: {col}")
        if col not in features.columns:
            continue
        op = OPS.get(str(spec.get("op") or ""))
        if op is None:
            continue
        try:
            target = float(spec.get("value"))
        except Exception:
            continue
        series = pd.to_numeric(features[col], errors="coerce")
        valid = series.notna()
        if not valid.any():
            continue
        mask = op(series, target).where(valid, False).astype(bool)
        masks.append(mask)
        condition_rates[col] = float(mask[valid].mean() * 100.0)

    if not masks:
        return empty
    matrix = pd.concat(masks, axis=1).fillna(False)
    return {
        "profile_feature_match_pct": float(np.mean(list(condition_rates.values()))),
        "profile_feature_match_any_pct": float(matrix.any(axis=1).mean() * 100.0),
        "profile_feature_match_all_pct": float(matrix.all(axis=1).mean() * 100.0),
        "profile_feature_condition_hit_rates": condition_rates,
    }


def _label_score_detail(
    sample_count: int,
    tag_counts: dict[str, int],
    required_tag_coverage_pct: float,
    untagged_pct: float,
    forbidden_tag_hit_count: int,
) -> dict[str, Any]:
    if sample_count <= 0:
        return {
            "required_tag_score_pct": 0.0,
            "tagged_score_pct": 0.0,
            "meaningful_top_tag_score_pct": 0.0,
            "forbidden_tag_penalty_pct": 0.0,
            "label_score_pct": 0.0,
            "label_score_points": 0.0,
        }
    meaningful = {k: v for k, v in tag_counts.items() if str(k).strip().lower() not in GENERIC_TAGS}
    meaningful_top = max(meaningful.values()) if meaningful else 0
    required_score = max(0.0, min(100.0, float(required_tag_coverage_pct)))
    tagged_score = max(0.0, min(100.0, 100.0 - float(untagged_pct)))
    meaningful_top_score = max(0.0, min(100.0, _pct(meaningful_top, sample_count)))
    forbidden_penalty = min(100.0, _pct(forbidden_tag_hit_count, sample_count) * 2.0)
    label_score_pct = max(
        0.0,
        min(
            100.0,
            required_score * 0.60
            + tagged_score * 0.30
            + meaningful_top_score * 0.10
            - forbidden_penalty,
        ),
    )
    return {
        "required_tag_score_pct": round(required_score, 2),
        "tagged_score_pct": round(tagged_score, 2),
        "meaningful_top_tag_score_pct": round(meaningful_top_score, 2),
        "forbidden_tag_penalty_pct": round(forbidden_penalty, 2),
        "label_score_pct": round(label_score_pct, 2),
        "label_score_points": round(15.0 * label_score_pct / 100.0, 2),
    }


def _direction_consistency(events: pd.DataFrame, profile: StrategyProfile) -> tuple[int, int, float]:
    if events.empty or "side" not in events.columns:
        return 0, 0, 0.0
    sides = events["side"].fillna("").astype(str).str.upper()
    long_count = int((sides == "LONG").sum())
    short_count = int((sides == "SHORT").sum())
    expected = str(profile.expected_direction or "BOTH").upper()
    if expected == "LONG_ONLY":
        return long_count, short_count, _pct(long_count, len(events))
    if expected == "SHORT_ONLY":
        return long_count, short_count, _pct(short_count, len(events))
    return long_count, short_count, _pct(max(long_count, short_count), len(events))


def _merge_events_features(events: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    base = events.reset_index(drop=True).copy()
    if features.empty:
        return base
    if "event_id" in base.columns and "event_id" in features.columns:
        suffix_cols = [c for c in features.columns if c in base.columns and c != "event_id"]
        merged = base.merge(features, on="event_id", how="left", suffixes=("", "_feature"))
        for col in suffix_cols:
            fcol = f"{col}_feature"
            if fcol in merged.columns:
                merged[col] = merged[col].where(merged[col].notna(), merged[fcol])
                merged = merged.drop(columns=[fcol])
        return merged
    joined = base.copy()
    for col in features.columns:
        if col not in joined.columns and len(features) == len(joined):
            joined[col] = features[col].reset_index(drop=True)
    return joined


def _similar_context_agreement(df: pd.DataFrame, max_neighbors: int) -> tuple[float | None, int, list[dict[str, Any]], str | None]:
    cols = [c for c in DEFAULT_CONTEXT_FEATURES if c in df.columns and not _is_forbidden_column(c)]
    if len(cols) < 3 or df.empty or "side" not in df.columns:
        return None, 0, [], "fewer than 3 usable context features"
    work = df[["event_id", "event_type", "side", *cols]].copy()
    for col in cols:
        work[col] = pd.to_numeric(work[col], errors="coerce")
    work = work.dropna(subset=cols).reset_index(drop=True)
    if len(work) < 3:
        return None, int(len(work)), [], "not enough complete rows for neighbor comparison"
    x = work[cols].to_numpy(dtype=float)
    std = x.std(axis=0)
    std[std == 0] = 1.0
    x = (x - x.mean(axis=0)) / std
    actions = (work["event_type"].fillna("OPEN").astype(str).str.upper() + "_" + work["side"].fillna("").astype(str).str.upper()).tolist()
    agreements = []
    conflicts = []
    k = max(1, min(int(max_neighbors), len(work) - 1))
    for i in range(len(work)):
        dist = np.sqrt(((x - x[i]) ** 2).sum(axis=1))
        order = np.argsort(dist)
        neighbors = [int(j) for j in order if int(j) != i][:k]
        same = sum(1 for j in neighbors if actions[j] == actions[i])
        agreements.append(same / len(neighbors) if neighbors else np.nan)
        for j in neighbors:
            if actions[j] != actions[i] and len(conflicts) < 10:
                conflicts.append(
                    {
                        "event_id": str(work.iloc[i].get("event_id", "")),
                        "neighbor_event_id": str(work.iloc[j].get("event_id", "")),
                        "action": actions[i],
                        "neighbor_action": actions[j],
                        "distance": float(dist[j]),
                    }
                )
                break
    series = pd.Series(agreements).dropna()
    if series.empty:
        return None, int(len(work)), conflicts, "no comparable neighbor rows"
    return float(series.mean() * 100.0), int(len(work)), conflicts, None


def _time_stability(df: pd.DataFrame, tags_per_row: list[list[str]]) -> tuple[dict[str, Any], bool, bool, bool]:
    if df.empty:
        return {}, False, False, False
    reset = df.reset_index(drop=True)
    n = len(reset)
    cut1 = n // 3
    cut2 = (n * 2) // 3
    parts = [reset.iloc[:cut1].copy(), reset.iloc[cut1:cut2].copy(), reset.iloc[cut2:].copy()]
    names = ["early", "middle", "late"]
    feature_shift: dict[str, Any] = {}
    feature_drift = False
    for col in [c for c in DEFAULT_CONTEXT_FEATURES if c in reset.columns]:
        means = []
        for part in parts:
            s = pd.to_numeric(part[col], errors="coerce").dropna()
            means.append(float(s.mean()) if not s.empty else None)
        valid = [m for m in means if m is not None]
        if len(valid) >= 2:
            spread = max(valid) - min(valid)
            scale = abs(float(np.mean(valid))) + 1e-9
            if abs(spread / scale) > 1.0 and abs(spread) > 0.02:
                feature_drift = True
        feature_shift[col] = dict(zip(names, means))
    direction_drift = False
    if "side" in reset.columns and len(reset) >= 6:
        ratios = []
        for part in parts:
            sides = part["side"].fillna("").astype(str).str.upper()
            ratios.append(_pct(int((sides == "LONG").sum()), len(part)))
        direction_drift = max(ratios) - min(ratios) > 40.0
    tag_drift = False
    if tags_per_row and len(tags_per_row) == len(reset) and len(reset) >= 6:
        top_tags = []
        start = 0
        for part in parts:
            end = start + len(part)
            counts = _tag_counts(tags_per_row[start:end])
            top_tags.append(next(iter(counts.keys()), None))
            start = end
        tag_drift = len(set([t for t in top_tags if t])) > 1
    return feature_shift, direction_drift, tag_drift, feature_drift


def _recommendation(score: float) -> str:
    if score >= 80.0:
        return "suitable_for_analysis"
    if score >= 60.0:
        return "needs_manual_review"
    return "not_suitable_for_rule_mining"


def _min_recommendation(current: str, cap: str) -> str:
    return current if RECOMMENDATION_RANK.get(current, 0) <= RECOMMENDATION_RANK.get(cap, 0) else cap


def _downgrade_one(current: str) -> str:
    if current == "suitable_for_analysis":
        return "needs_manual_review"
    if current == "needs_manual_review":
        return "not_suitable_for_rule_mining"
    return current


def apply_consistency_gates(result: dict, profile: StrategyProfile) -> dict:
    out = dict(result or {})
    failures: list[str] = []
    recommendation = str(out.get("recommendation") or "not_suitable_for_rule_mining")
    sample_count = int(out.get("sample_count") or 0)
    direction_pct = float(out.get("direction_consistency_pct") or 0.0)
    untagged_pct = float(out.get("untagged_pct") or 0.0)
    missing_note_pct = float(out.get("missing_note_pct") or 0.0)
    similar_pct = out.get("similar_context_agreement_pct")
    forbidden_hits = int(out.get("forbidden_tag_hit_count") or 0)
    expected_direction = str(profile.expected_direction or "BOTH").upper()

    if sample_count < int(profile.min_sample_count):
        failures.append(f"sample_count below min_sample_count: {sample_count} < {profile.min_sample_count}")
        recommendation = _min_recommendation(recommendation, "needs_manual_review")
    if expected_direction in {"LONG_ONLY", "SHORT_ONLY"} and direction_pct < 70.0:
        failures.append(f"direction_consistency_pct below hard floor for {expected_direction}: {direction_pct:.2f} < 70")
        recommendation = "not_suitable_for_rule_mining"
    if untagged_pct > 60.0:
        failures.append(f"untagged_pct too high: {untagged_pct:.2f} > 60")
        recommendation = _min_recommendation(recommendation, "needs_manual_review")
    if missing_note_pct > float(profile.max_missing_note_pct):
        failures.append(f"missing_note_pct above profile limit: {missing_note_pct:.2f} > {profile.max_missing_note_pct}")
        recommendation = _min_recommendation(recommendation, "needs_manual_review")
    if similar_pct is not None and float(similar_pct) < 60.0:
        failures.append(f"similar_context_agreement_pct too low: {float(similar_pct):.2f} < 60")
        recommendation = _min_recommendation(recommendation, "needs_manual_review")
    if bool(out.get("possible_selection_bias_warning")):
        failures.append("possible_selection_bias_warning is true")
        recommendation = _min_recommendation(recommendation, "needs_manual_review")
    if forbidden_hits > 0:
        failures.append(f"forbidden_tag_hit_count > 0: {forbidden_hits}")
        recommendation = _downgrade_one(recommendation)

    out["gate_failures"] = failures
    out["recommendation"] = recommendation
    return out


def _empty_result(profile: StrategyProfile) -> dict:
    result = {
        "sample_count": 0,
        "open_event_count": 0,
        "close_event_count": 0,
        "long_count": 0,
        "short_count": 0,
        "direction_consistency_pct": 0.0,
        "untagged_pct": 0.0,
        "missing_note_pct": 0.0,
        "top_tags": {},
        "top_tag_coverage_pct": 0.0,
        "label_entropy": 0.0,
        "required_tag_coverage_pct": 0.0,
        "forbidden_tag_hit_count": 0,
        "label_score_detail": _label_score_detail(0, {}, 0.0, 0.0, 0),
        "profile_feature_match_pct": None,
        "profile_feature_match_any_pct": None,
        "profile_feature_match_all_pct": None,
        "similar_context_agreement_pct": None,
        "neighbor_sample_count": 0,
        "conflict_examples": [],
        "early_mid_late_feature_shift": {},
        "low_sample_warning": True,
        "mixed_direction_warning": False,
        "high_untagged_warning": False,
        "high_missing_note_warning": False,
        "possible_random_trading_warning": False,
        "possible_selection_bias_warning": True,
        "direction_drift_warning": False,
        "tag_drift_warning": False,
        "feature_drift_warning": False,
        "strategy_consistency_score": 0.0,
        "score_components": {},
        "recommendation": "not_suitable_for_rule_mining",
        "profile": profile_to_dict(profile),
        "warnings": ["no events available"],
        "notice": "Strategy consistency does not mean strategy profitability.",
    }
    return apply_consistency_gates(result, profile)


def analyze_strategy_consistency(
    events: pd.DataFrame,
    features: pd.DataFrame,
    trades: pd.DataFrame | None = None,
    profile: StrategyProfile | None = None,
    max_neighbors: int = 5,
) -> dict:
    events = _to_df(events)
    features = _to_df(features)
    trades = _to_df(trades)
    profile = profile or default_reversal_long_profile()

    for col in profile.expected_entry_features:
        if _is_forbidden_column(col):
            raise ValueError(f"Forbidden result/future field used in strategy consistency profile: {col}")
    used_cols = [c for c in DEFAULT_CONTEXT_FEATURES if c in features.columns]
    bad_used = [c for c in used_cols if _is_forbidden_column(c)]
    if bad_used:
        raise ValueError(f"Forbidden result/future fields used in consistency calculation: {bad_used}")

    if events.empty:
        return _json_safe(_empty_result(profile))

    event_type = events.get("event_type", pd.Series([""] * len(events))).fillna("").astype(str).str.upper()
    open_events = events[event_type.isin(["OPEN", "OPEN_LONG", "OPEN_SHORT"])].copy()
    if open_events.empty:
        open_events = events.copy()
    close_count = int(event_type.str.contains("CLOSE").sum())
    sample_count = int(len(open_events))

    merged = _merge_events_features(open_events, features)
    tags_per_row = _tag_series(open_events)
    tag_counts = _tag_counts(tags_per_row)
    tagged_rows = sum(1 for tags in tags_per_row if tags)
    untagged_pct = 100.0 - _pct(tagged_rows, sample_count)
    top_count = max(tag_counts.values()) if tag_counts else 0
    required_hits = sum(1 for tags in tags_per_row if set(tags) & set(profile.required_tags))
    forbidden_hits = sum(1 for tags in tags_per_row if set(tags) & set(profile.forbidden_tags))
    required_tag_coverage_pct = _pct(required_hits, sample_count)
    notes = open_events.get("note", pd.Series([""] * sample_count)).fillna("").astype(str).str.strip()
    missing_note_pct = _pct(int((notes == "").sum()), sample_count)

    long_count, short_count, direction_pct = _direction_consistency(open_events, profile)
    pre_ret = _num(merged, "pre_ret_20")
    match_stats = _profile_feature_match_stats(merged, profile)
    feature_match_all = match_stats["profile_feature_match_all_pct"]
    feature_match_any = match_stats["profile_feature_match_any_pct"]
    similar_pct, neighbor_count, conflicts, neighbor_warning = _similar_context_agreement(merged, max_neighbors)
    feature_shift, direction_drift, tag_drift, feature_drift = _time_stability(merged, tags_per_row)

    low_sample = sample_count < int(profile.min_sample_count)
    mixed_direction = direction_pct < 80.0 if str(profile.expected_direction).upper() in {"LONG_ONLY", "SHORT_ONLY"} else False
    high_untagged = untagged_pct > 50.0
    high_missing_note = missing_note_pct > float(profile.max_missing_note_pct)
    selection_bias = close_count < max(1, int(sample_count * 0.3))

    sample_score = 15.0 * min(sample_count / max(1, int(profile.min_sample_count)), 1.0)
    direction_score = 15.0 * direction_pct / 100.0
    fallback_market_pct = _pct(int((pre_ret < 0).sum()), int(pre_ret.notna().sum())) if int(pre_ret.notna().sum()) else 0.0
    market_pct = feature_match_all if feature_match_all is not None else fallback_market_pct
    market_score = 20.0 * float(market_pct or 0.0) / 100.0
    neighbor_score = 20.0 * ((similar_pct or 0.0) / 100.0) if similar_pct is not None else 5.0
    label_detail = _label_score_detail(sample_count, tag_counts, required_tag_coverage_pct, untagged_pct, forbidden_hits)
    tag_score = float(label_detail["label_score_points"])
    time_score = 15.0
    for flag in (direction_drift, tag_drift, feature_drift):
        if flag:
            time_score -= 5.0
    time_score = max(0.0, time_score)

    components = {
        "sample_count": sample_score,
        "direction_consistency": direction_score,
        "market_state_consistency": market_score,
        "similar_context_agreement": neighbor_score,
        "label_consistency": tag_score,
        "time_stability": time_score,
    }
    score = float(sum(components.values()))
    random_warning = score < 60.0 or (high_untagged and mixed_direction)

    warnings = []
    if low_sample:
        warnings.append("sample count is below profile minimum")
    if mixed_direction:
        warnings.append("direction is mixed relative to profile expectation")
    if high_untagged:
        warnings.append("many events have no tags")
    if high_missing_note:
        warnings.append("many events have no notes")
    if neighbor_warning:
        warnings.append(neighbor_warning)
    if random_warning:
        warnings.append("samples may not come from one stable trading logic")
    if selection_bias:
        warnings.append("possible selection bias: close/failed samples may be underrepresented")

    result = {
        "sample_count": sample_count,
        "open_event_count": int(event_type.str.contains("OPEN").sum()),
        "close_event_count": close_count,
        "long_count": long_count,
        "short_count": short_count,
        "direction_consistency_pct": direction_pct,
        "untagged_pct": untagged_pct,
        "missing_note_pct": missing_note_pct,
        "top_tags": dict(list(tag_counts.items())[:20]),
        "top_tag_coverage_pct": _pct(top_count, sample_count),
        "label_entropy": _entropy(tag_counts),
        "required_tag_coverage_pct": required_tag_coverage_pct,
        "forbidden_tag_hit_count": forbidden_hits,
        "label_score_detail": label_detail,
        "pre_ret_20_mean": _mean(merged, "pre_ret_20"),
        "pre_ret_20_median": _median(merged, "pre_ret_20"),
        "pre_ret_20_negative_pct": _pct(int((pre_ret < 0).sum()), int(pre_ret.notna().sum())),
        "pre_max_drawdown_20_mean": _mean(merged, "pre_max_drawdown_20"),
        "event_lower_wick_ratio_mean": _mean(merged, "event_lower_wick_ratio"),
        "event_volume_ratio_20_mean": _mean(merged, "event_volume_ratio_20"),
        **match_stats,
        "similar_context_agreement_pct": similar_pct,
        "neighbor_sample_count": neighbor_count,
        "conflict_examples": conflicts[:10],
        "early_mid_late_feature_shift": feature_shift,
        "direction_drift_warning": direction_drift,
        "tag_drift_warning": tag_drift,
        "feature_drift_warning": feature_drift,
        "low_sample_warning": low_sample,
        "mixed_direction_warning": mixed_direction,
        "high_untagged_warning": high_untagged,
        "high_missing_note_warning": high_missing_note,
        "possible_random_trading_warning": random_warning,
        "possible_selection_bias_warning": selection_bias,
        "strategy_consistency_score": round(score, 2),
        "score_components": {k: round(v, 2) for k, v in components.items()},
        "recommendation": _recommendation(score),
        "profile": profile_to_dict(profile),
        "warnings": warnings,
        "notice": "Strategy consistency does not mean strategy profitability.",
    }
    return _json_safe(apply_consistency_gates(result, profile))
