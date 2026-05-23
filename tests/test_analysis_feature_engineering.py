from __future__ import annotations

import pandas as pd

from analysis.feature_engineering import build_enhanced_event_features


def _windows(include_post: bool = True):
    rows = []
    offsets = list(range(-10, 1)) + ([1, 2] if include_post else [])
    for offset in offsets:
        rows.append(
            {
                "event_id": "e1",
                "offset": offset,
                "open": 100 + offset,
                "high": 102 + offset,
                "low": 98 + offset,
                "close": 101 + offset if offset == 0 else 99 + offset,
                "volume": 100 if offset < 0 else 300,
            }
        )
    return pd.DataFrame(rows)


def _events():
    return pd.DataFrame({"event_id": ["e1"], "trade_id": ["t1"], "event_type": ["OPEN"], "side": ["LONG"], "symbol": ["BTCUSDT"], "interval": ["1m"]})


def test_enhanced_features_normal_window():
    out = build_enhanced_event_features(_windows(), _events())
    assert len(out) == 1
    assert "capitulation_score" in out.columns


def test_missing_pre_20_does_not_crash():
    out = build_enhanced_event_features(_windows(include_post=False), _events())
    assert len(out) == 1


def test_event_close_position_and_lower_wick():
    out = build_enhanced_event_features(_windows(), _events()).iloc[0]
    assert round(out["event_close_position"], 6) == 0.75
    assert round(out["event_lower_wick_ratio"], 6) == 0.5


def test_does_not_use_post_window():
    with_post = build_enhanced_event_features(_windows(True), _events())
    without_post = build_enhanced_event_features(_windows(False), _events())
    assert with_post["event_close_position"].iloc[0] == without_post["event_close_position"].iloc[0]


def test_no_future_columns():
    out = build_enhanced_event_features(_windows(), _events())
    assert not any(c.startswith(("post_", "fwd_")) for c in out.columns)

