from __future__ import annotations

import numpy as np
import pandas as pd


OUTPUT_COLUMNS = [
    "event_id",
    "label_win_5",
    "label_win_10",
    "label_strong_rebound_10",
    "label_failed_reversal_10",
    "label_good_trade_10",
    "label_bad_trade_10",
    "mfe_mae_ratio_10",
]


def _num_col(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype="float64")
    return pd.to_numeric(df[column], errors="coerce")


def build_strategy_labels(labels: pd.DataFrame) -> pd.DataFrame:
    df = labels.copy() if isinstance(labels, pd.DataFrame) else pd.DataFrame()
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    out = pd.DataFrame()
    out["event_id"] = df["event_id"] if "event_id" in df.columns else pd.Series(range(len(df)), index=df.index).astype(str)
    fwd5 = _num_col(df, "fwd_ret_5_side_adj")
    fwd10 = _num_col(df, "fwd_ret_10_side_adj")
    mfe10 = _num_col(df, "mfe_10")
    mae10 = _num_col(df, "mae_10")
    out["label_win_5"] = fwd5 > 0
    out["label_win_10"] = fwd10 > 0
    out["label_strong_rebound_10"] = fwd10 > 0.005
    out["label_failed_reversal_10"] = (mae10 < -0.006) & (fwd10 <= 0)
    out["label_good_trade_10"] = (mfe10 > 0.008) & (mae10 > -0.004)
    out["label_bad_trade_10"] = mae10 < -0.008
    ratio = (mfe10 / mae10).abs()
    ratio = ratio.replace([np.inf, -np.inf], np.nan)
    out["mfe_mae_ratio_10"] = ratio
    return out.reindex(columns=OUTPUT_COLUMNS)
