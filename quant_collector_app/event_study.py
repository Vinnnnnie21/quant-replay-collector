from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd


RET_COLUMNS = [
    "fwd_ret_1",
    "fwd_ret_3",
    "fwd_ret_5",
    "fwd_ret_10",
    "fwd_ret_1_side_adj",
    "fwd_ret_3_side_adj",
    "fwd_ret_5_side_adj",
    "fwd_ret_10_side_adj",
    "mfe_10",
    "mae_10",
]


def _parse_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if str(v)]
    if value is None or value == "":
        return ["UNTAGGED"]
    try:
        parsed = json.loads(value)
    except Exception:
        parsed = [value]
    if not isinstance(parsed, list):
        parsed = [parsed]
    tags = [str(v) for v in parsed if str(v)]
    return tags or ["UNTAGGED"]


def _bootstrap_mean_ci(series: pd.Series, draws: int = 1000) -> tuple[float | None, float | None]:
    values = pd.to_numeric(series, errors="coerce").dropna().to_numpy(dtype=float)
    if not len(values):
        return None, None
    rng = np.random.default_rng(42)
    samples = rng.choice(values, size=(draws, len(values)), replace=True).mean(axis=1)
    low, high = np.quantile(samples, [0.025, 0.975])
    return float(low), float(high)


def build_event_study_summary(events: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    base_columns = ["label_tag", "event_type", "side", "sample_count"]
    if events.empty or features.empty or "event_id" not in events.columns or "event_id" not in features.columns:
        return pd.DataFrame(columns=base_columns)

    event_cols = [c for c in ["event_id", "event_type", "side", "label_tags_json"] if c in events.columns]
    feature_cols = ["event_id", *[c for c in RET_COLUMNS if c in features.columns]]
    df = events[event_cols].merge(features[feature_cols], on="event_id", how="inner")
    if df.empty:
        return pd.DataFrame(columns=base_columns)

    df["label_tag"] = df.get("label_tags_json", "").apply(_parse_tags)
    df = df.explode("label_tag")

    rows: list[dict[str, Any]] = []
    group_cols = ["label_tag", "event_type", "side"]
    for keys, group in df.groupby(group_cols, dropna=False):
        label_tag, event_type, side = keys
        row: dict[str, Any] = {
            "label_tag": label_tag,
            "event_type": event_type,
            "side": side,
            "sample_count": int(len(group)),
            "small_sample_warning": bool(len(group) < 30),
            "warning_text": (
                "Small sample: descriptive output only; candidate hypothesis, not a trading signal."
                if len(group) < 30
                else "Candidate hypothesis, not a trading signal."
            ),
        }
        for col in RET_COLUMNS:
            if col not in group.columns:
                continue
            series = pd.to_numeric(group[col], errors="coerce").dropna()
            row[f"{col}_mean"] = float(series.mean()) if len(series) else None
            row[f"{col}_median"] = float(series.median()) if len(series) else None
            row[f"{col}_std"] = float(series.std(ddof=1)) if len(series) > 1 else None
            row[f"{col}_q25"] = float(series.quantile(0.25)) if len(series) else None
            row[f"{col}_q75"] = float(series.quantile(0.75)) if len(series) else None
            row[f"{col}_win_rate_pct"] = float((series > 0).mean() * 100.0) if len(series) else None
            low, high = _bootstrap_mean_ci(series)
            row[f"{col}_mean_ci95_low"] = low
            row[f"{col}_mean_ci95_high"] = high
        rows.append(row)
    result = pd.DataFrame(rows).sort_values(["label_tag", "event_type", "side"]).reset_index(drop=True)
    result["multiple_testing_warning"] = (
        "Multiple groups or candidate rules require out-of-sample validation; comparisons are exploratory."
        if len(result) > 1
        else "Candidate hypothesis, not a trading signal."
    )
    return result
