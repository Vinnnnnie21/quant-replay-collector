from __future__ import annotations

import json
import math
import operator
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_FEATURE_COLS = [
    "pre_ret_20",
    "pre_max_drawdown_20",
    "event_lower_wick_ratio",
    "event_close_position",
    "event_volume_ratio_20",
    "event_body_ratio",
    "capitulation_score",
]

OPS = {
    "<=": operator.le,
    ">=": operator.ge,
    "<": operator.lt,
    ">": operator.gt,
    "==": operator.eq,
}


def _condition_mask(df: pd.DataFrame, condition: dict[str, Any]) -> pd.Series:
    col = condition.get("column")
    op = condition.get("op")
    value = condition.get("value")
    if col not in df.columns:
        raise ValueError(f"非法字段：{col}")
    if op not in OPS:
        raise ValueError(f"非法操作符：{op}")
    left = pd.to_numeric(df[col], errors="coerce") if op != "==" else df[col]
    return OPS[op](left, value).fillna(False)


def _rule_text(conditions: list[dict[str, Any]]) -> str:
    return " AND ".join(f"{c['column']} {c['op']} {c['value']:.6g}" if isinstance(c.get("value"), (int, float)) else f"{c['column']} {c['op']} {c.get('value')}" for c in conditions)


def evaluate_rule(df: pd.DataFrame, conditions: list[dict[str, Any]], label_col: str) -> dict[str, Any]:
    if df is None or df.empty:
        return {"rule_text": _rule_text(conditions), "sample_count": 0, "coverage_pct": 0.0, "low_sample_warning": True, "warning_text": "空数据"}
    if label_col not in df.columns:
        raise ValueError(f"非法标签字段：{label_col}")
    mask = pd.Series(True, index=df.index)
    for cond in conditions:
        mask &= _condition_mask(df, cond)
    subset = df[mask].copy()
    label = pd.to_numeric(subset[label_col], errors="coerce")
    mfe = pd.to_numeric(subset.get("mfe_10"), errors="coerce") if "mfe_10" in subset else pd.Series(dtype=float)
    mae = pd.to_numeric(subset.get("mae_10"), errors="coerce") if "mae_10" in subset else pd.Series(dtype=float)
    avg_mfe = float(mfe.mean()) if len(mfe.dropna()) else None
    avg_mae = float(mae.mean()) if len(mae.dropna()) else None
    rr = abs(avg_mfe / avg_mae) if avg_mfe is not None and avg_mae not in (None, 0) else None
    count = int(len(subset))
    return {
        "rule_text": _rule_text(conditions),
        "conditions_json": json.dumps(conditions, ensure_ascii=False),
        "sample_count": count,
        "coverage_pct": count / max(len(df), 1) * 100.0,
        "label_mean": float(label.mean()) if len(label.dropna()) else None,
        "label_median": float(label.median()) if len(label.dropna()) else None,
        "win_rate_pct": float((label > 0).mean() * 100.0) if len(label.dropna()) else None,
        "avg_mfe_10": avg_mfe,
        "avg_mae_10": avg_mae,
        "risk_reward_proxy": rr,
        "low_sample_warning": bool(count < 30),
        "warning_text": "candidate hypothesis; not a trading signal" if count >= 30 else "样本不足；candidate hypothesis; not a trading signal",
    }


def _threshold_conditions(df: pd.DataFrame, feature: str) -> list[dict[str, Any]]:
    series = pd.to_numeric(df[feature], errors="coerce").dropna()
    if len(series) < 2 or series.nunique() < 2:
        return []
    values = sorted(set(float(v) for v in series.quantile([0.2, 0.4, 0.6, 0.8]).dropna().tolist()))
    conditions = []
    for value in values:
        conditions.append({"column": feature, "op": "<=", "value": value})
        conditions.append({"column": feature, "op": ">=", "value": value})
    return conditions


def generate_candidate_rules(
    df: pd.DataFrame,
    feature_cols: list[str] | None = None,
    label_col: str = "fwd_ret_10_side_adj",
    min_samples: int = 30,
) -> pd.DataFrame:
    if df is None or df.empty or label_col not in df.columns:
        return pd.DataFrame()
    feature_cols = feature_cols or [c for c in DEFAULT_FEATURE_COLS if c in df.columns]
    single_conditions = []
    for feature in feature_cols:
        single_conditions.extend(_threshold_conditions(df, feature))
    rows = []
    for cond in single_conditions:
        try:
            rows.append(evaluate_rule(df, [cond], label_col))
        except ValueError:
            continue
    for c1, c2 in combinations(single_conditions, 2):
        if c1["column"] == c2["column"]:
            continue
        try:
            rows.append(evaluate_rule(df, [c1, c2], label_col))
        except ValueError:
            continue
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    out = out[out["sample_count"] >= int(min_samples)].copy()
    if out.empty:
        return pd.DataFrame(columns=list(rows[0].keys()))
    out["_score"] = pd.to_numeric(out["win_rate_pct"], errors="coerce").fillna(0) + pd.to_numeric(out["label_mean"], errors="coerce").fillna(0) * 100.0
    out = out.sort_values(["_score", "sample_count"], ascending=[False, False]).drop(columns=["_score"]).reset_index(drop=True)
    return out

