from __future__ import annotations

import pandas as pd

from dataset_builder import build_ml_datasets


def test_ml_features_exclude_future_and_label_columns():
    features = pd.DataFrame(
        [
            {
                "event_id": "evt_1",
                "session_id": "sess_1",
                "trade_id": "trd_1",
                "event_type": "OPEN",
                "side": "LONG",
                "symbol": "BTCUSDT",
                "interval": "1m",
                "price_proxy": 100.0,
                "pre_ret_3": 0.01,
                "fwd_ret_1": 0.02,
                "mfe_10": 0.03,
                "mae_10": -0.01,
                "manual_trade_final_return_pct": 1.5,
                "created_at": "2026-01-01T00:00:00+08:00",
            }
        ]
    )

    tables = build_ml_datasets(features)

    assert "price_proxy" in tables["ml_features"].columns
    assert "pre_ret_3" in tables["ml_features"].columns
    assert "fwd_ret_1" not in tables["ml_features"].columns
    assert "mfe_10" not in tables["ml_features"].columns
    assert "mae_10" not in tables["ml_features"].columns
    assert "manual_trade_final_return_pct" not in tables["ml_features"].columns
    assert "fwd_ret_1" in tables["ml_labels"].columns
    assert tables["sample_index"].iloc[0]["sample_id"] == "evt_1"
