from __future__ import annotations

import pandas as pd

from analysis.label_builder import build_strategy_labels


def test_win_labels():
    out = build_strategy_labels(pd.DataFrame({"event_id": ["e1"], "fwd_ret_5_side_adj": [0.01], "fwd_ret_10_side_adj": [0.02]}))
    assert bool(out.loc[0, "label_win_5"]) is True
    assert bool(out.loc[0, "label_strong_rebound_10"]) is True


def test_failed_reversal_label():
    out = build_strategy_labels(pd.DataFrame({"event_id": ["e1"], "fwd_ret_10_side_adj": [-0.001], "mae_10": [-0.01]}))
    assert bool(out.loc[0, "label_failed_reversal_10"]) is True


def test_good_trade_label():
    out = build_strategy_labels(pd.DataFrame({"event_id": ["e1"], "mfe_10": [0.01], "mae_10": [-0.003]}))
    assert bool(out.loc[0, "label_good_trade_10"]) is True


def test_nan_and_zero_mae_safe():
    out = build_strategy_labels(pd.DataFrame({"event_id": ["e1", "e2"], "mfe_10": [0.01, None], "mae_10": [0.0, None]}))
    assert out["mfe_mae_ratio_10"].isna().all()


def test_missing_mfe_or_mae_columns_safe():
    out = build_strategy_labels(pd.DataFrame({"event_id": ["e1"], "fwd_ret_10_side_adj": [0.01]}))
    assert out["mfe_mae_ratio_10"].isna().all()
