from __future__ import annotations

import pandas as pd

from research.factor_library import FeatureFactory
from research.label_registry import LabelFactory


def research_input(sample_count: int = 40):
    windows = []
    events = []
    trades = []
    for event_number in range(sample_count):
        event_id = f"e{event_number}"
        trade_id = f"t{event_number}"
        side = "LONG" if event_number % 2 == 0 else "SHORT"
        event_time = pd.Timestamp("2026-01-01", tz="Asia/Shanghai") + pd.Timedelta(minutes=event_number)
        events.append(
            {
                "event_id": event_id,
                "trade_id": trade_id,
                "session_id": "s1",
                "event_type": "OPEN",
                "side": side,
                "symbol": "BTCUSDT",
                "interval": "1m",
                "bar_open_time_bjt": event_time.isoformat(),
                "label_tags_json": '["reversal"]',
            }
        )
        trades.append(
            {
                "trade_id": trade_id,
                "status": "CLOSED",
                "net_return_pct": 1.0 if event_number % 3 else -1.0,
                "holding_bars": 10,
            }
        )
        direction = 1 if side == "LONG" else -1
        for offset in range(-20, 21):
            close = 100.0 + offset * (0.03 + event_number / 10000)
            if offset > 0:
                close = 100.0 + direction * offset * (0.04 if event_number % 3 else -0.03)
            windows.append(
                {
                    "event_id": event_id,
                    "offset": offset,
                    "bar_open_time_bjt": (event_time + pd.Timedelta(minutes=offset)).isoformat(),
                    "open": close - 0.1,
                    "high": close + 0.5,
                    "low": close - 0.5,
                    "close": close,
                    "volume": 100 + event_number + abs(offset),
                }
            )
    return pd.DataFrame(windows), pd.DataFrame(events), pd.DataFrame(trades)


def test_feature_factory_never_emits_label_or_future_fields():
    windows, events, _trades = research_input(3)
    features = FeatureFactory().build(windows, events)
    blocked = ("fwd_", "mfe", "mae", "post_", "future", "manual_trade_final", "exit", "pnl", "label")
    assert not [column for column in features.columns if column.lower().startswith(blocked)]
    assert "lower_wick_atr_ratio" in features.columns


def test_label_factory_allows_future_and_manual_result_fields():
    windows, events, trades = research_input(3)
    labels = LabelFactory().build(windows, events, trades)
    assert {"fwd_ret_10", "fwd_ret_10_side_adj", "mfe_10", "mae_10", "manual_return"} <= set(labels.columns)
    assert labels["manual_return"].notna().all()
