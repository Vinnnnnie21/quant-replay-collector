from __future__ import annotations

import json
import math

import pandas as pd

from .bootstrap import bootstrap_mean_ci


def _tags(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value] or ["UNTAGGED"]
    try:
        parsed = json.loads(str(value))
    except Exception:
        parsed = [value] if value not in (None, "") else ["UNTAGGED"]
    if not isinstance(parsed, list):
        parsed = [parsed]
    return [str(item) for item in parsed] or ["UNTAGGED"]


def _stats(values: pd.Series) -> dict:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    ci = bootstrap_mean_ci(numeric)
    positive = numeric[numeric > 0]
    negative = numeric[numeric < 0]
    ratio = (
        float(positive.mean() / abs(negative.mean()))
        if len(positive) and len(negative) and float(negative.mean()) != 0
        else math.nan
    )
    return {
        "sample_count": int(len(numeric)),
        "mean": float(numeric.mean()) if len(numeric) else math.nan,
        "median": float(numeric.median()) if len(numeric) else math.nan,
        "std": float(numeric.std(ddof=1)) if len(numeric) > 1 else math.nan,
        "q05": float(numeric.quantile(0.05)) if len(numeric) else math.nan,
        "q25": float(numeric.quantile(0.25)) if len(numeric) else math.nan,
        "q75": float(numeric.quantile(0.75)) if len(numeric) else math.nan,
        "q95": float(numeric.quantile(0.95)) if len(numeric) else math.nan,
        "win_rate": float((numeric > 0).mean() * 100.0) if len(numeric) else math.nan,
        "profit_loss_ratio": ratio,
        "bootstrap_ci_low": ci["ci_low"],
        "bootstrap_ci_high": ci["ci_high"],
        "small_sample_warning": (
            "severe: n < 30; no strong conclusion"
            if len(numeric) < 30
            else ("exploratory only: n < 100" if len(numeric) < 100 else "")
        ),
    }


def build_event_study(
    features: pd.DataFrame,
    labels: pd.DataFrame,
    events: pd.DataFrame | None = None,
    label: str = "fwd_ret_10_side_adj",
) -> pd.DataFrame:
    if features.empty or labels.empty or label not in labels.columns:
        return pd.DataFrame()
    samples = features.merge(labels[["event_id", label]], on="event_id", how="inner")
    events = events.copy() if isinstance(events, pd.DataFrame) else pd.DataFrame()
    if not events.empty and "event_id" in events.columns:
        event_columns = [column for column in ["event_id", "label_tags_json"] if column in events.columns]
        samples = samples.merge(events[event_columns], on="event_id", how="left")
    samples["label_tag"] = samples.get("label_tags_json", pd.Series("UNTAGGED", index=samples.index)).apply(_tags)
    samples = samples.explode("label_tag")
    groupings = [
        ["label_tag"],
        ["event_type"],
        ["side"],
        ["symbol"],
        ["interval"],
        ["volatility_regime"],
        ["trend_regime"],
        ["time_session"],
        ["label_tag", "side"],
        ["label_tag", "side", "volatility_regime"],
    ]
    rows = []
    for grouping in groupings:
        if not all(column in samples.columns for column in grouping):
            continue
        for keys, group in samples.groupby(grouping, dropna=False):
            keys = keys if isinstance(keys, tuple) else (keys,)
            row = {
                "group_by": " + ".join(grouping),
                "label": label,
                **{column: value for column, value in zip(grouping, keys)},
                **_stats(group[label]),
            }
            rows.append(row)
    return pd.DataFrame(rows)
