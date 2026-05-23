from __future__ import annotations

import pandas as pd


LABEL_COLUMNS = [
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
    "manual_trade_final_return_pct",
    "manual_trade_holding_bars",
]

METADATA_COLUMNS = [
    "event_id",
    "session_id",
    "trade_id",
    "event_type",
    "side",
    "symbol",
    "interval",
    "created_at",
]

FORBIDDEN_FEATURE_PREFIXES = ("fwd_", "post_")
FORBIDDEN_FEATURE_EXACT = {
    "mfe_10",
    "mae_10",
    "manual_trade_final_return_pct",
    "manual_trade_holding_bars",
}


def is_future_or_label_column(column: str) -> bool:
    name = str(column)
    return name.startswith(FORBIDDEN_FEATURE_PREFIXES) or name in FORBIDDEN_FEATURE_EXACT


def build_ml_datasets(features: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if features.empty:
        return {
            "ml_features": pd.DataFrame(),
            "ml_labels": pd.DataFrame(),
            "sample_index": pd.DataFrame(),
        }

    metadata_cols = [c for c in METADATA_COLUMNS if c in features.columns]
    label_cols = [c for c in ["event_id", *LABEL_COLUMNS] if c in features.columns]
    feature_cols = [
        c
        for c in features.columns
        if c not in metadata_cols and not is_future_or_label_column(c)
    ]
    ml_features = features[[*metadata_cols, *feature_cols]].copy()
    ml_labels = features[label_cols].copy() if label_cols else pd.DataFrame()
    sample_index = features[metadata_cols].copy() if metadata_cols else pd.DataFrame()
    if "event_id" in sample_index.columns:
        sample_index["sample_id"] = sample_index["event_id"]
        cols = ["sample_id", *[c for c in sample_index.columns if c != "sample_id"]]
        sample_index = sample_index[cols]
    return {
        "ml_features": ml_features,
        "ml_labels": ml_labels,
        "sample_index": sample_index,
    }
