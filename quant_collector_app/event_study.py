from __future__ import annotations

import json
from typing import Any

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
        }
        for col in RET_COLUMNS:
            if col not in group.columns:
                continue
            series = pd.to_numeric(group[col], errors="coerce").dropna()
            row[f"{col}_mean"] = float(series.mean()) if len(series) else None
            row[f"{col}_median"] = float(series.median()) if len(series) else None
            row[f"{col}_win_rate_pct"] = float((series > 0).mean() * 100.0) if len(series) else None
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["label_tag", "event_type", "side"]).reset_index(drop=True)
