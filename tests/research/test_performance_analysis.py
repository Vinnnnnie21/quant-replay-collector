from __future__ import annotations

import pytest

from performance_analysis import (
    build_performance_snapshot,
    performance_curve_end,
    smooth_curve_values,
    split_signed_curve,
)


def test_signed_curve_splits_exactly_at_baseline_crossings():
    segments = split_signed_curve([100.0, 110.0, 90.0, 105.0], baseline=100.0)

    assert segments == [
        ("positive", [(0.0, 100.0), (1.0, 110.0), (1.5, 100.0)]),
        ("negative", [(1.5, 100.0), (2.0, 90.0), (2.6666666666666665, 100.0)]),
        ("positive", [(2.6666666666666665, 100.0), (3.0, 105.0)]),
    ]


def test_performance_snapshot_separates_realized_and_unrealized_results():
    snapshot = build_performance_snapshot(
        equity_rows=[
            {"current_equity": 1000.0, "realized_net_pnl": 0.0, "unrealized_pnl": 0.0},
            {"current_equity": 990.0, "realized_net_pnl": -20.0, "unrealized_pnl": 10.0},
            {"current_equity": 1020.0, "realized_net_pnl": 10.0, "unrealized_pnl": 10.0},
        ],
        trades=[
            {"trade_id": "win", "status": "CLOSED", "net_pnl_quote": 30.0, "net_return_pct": 3.0},
            {"trade_id": "loss", "status": "CLOSED", "net_pnl_quote": -20.0, "net_return_pct": -2.0},
            {"trade_id": "open", "status": "OPEN", "notional_quote": 500.0},
        ],
        initial_equity=1000.0,
        default_notional=500.0,
    )

    assert snapshot["metrics"]["current_equity"] == 1020.0
    assert snapshot["metrics"]["total_pnl"] == 20.0
    assert snapshot["metrics"]["total_return_pct"] == 2.0
    assert snapshot["metrics"]["realized_pnl"] == 10.0
    assert snapshot["metrics"]["unrealized_pnl"] == 10.0
    assert snapshot["metrics"]["win_rate_pct"] == 50.0
    assert snapshot["distribution"]["gross_profit"] == 30.0
    assert snapshot["distribution"]["gross_loss"] == -20.0


def test_performance_curve_stops_after_cursor_or_last_trade_activity():
    trades = [
        {"entry_bar_index": 279, "exit_bar_index": 550},
        {"entry_bar_index": 1653, "exit_bar_index": 1728},
    ]

    assert performance_curve_end(trades, cursor=123, row_count=14_880) == 1729
    assert performance_curve_end(trades, cursor=2000, row_count=14_880) == 2001


def test_display_curve_uses_centered_smoothing_without_changing_endpoints():
    values = [100.0, 110.0, 90.0, 110.0, 90.0, 110.0, 100.0]

    smoothed = smooth_curve_values(values, window=5)

    assert smoothed[0] == 100.0
    assert smoothed[-1] == 100.0
    assert smoothed[3] == 102.0
    assert max(smoothed[1:-1]) < 110.0
    assert min(smoothed[1:-1]) > 90.0
