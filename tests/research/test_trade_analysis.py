from __future__ import annotations

import pytest

from analytics.trade_analysis import analyze_trades


def test_empty_trades_safe():
    out = analyze_trades([], initial_equity=10000)
    assert out["total_trades"] == 0
    assert out["basis"] == "manual_replay_records"


def test_all_win_profit_factor_none():
    trades = [
        {"trade_id": "t1", "status": "CLOSED", "side": "LONG", "net_return_pct": 1.0},
        {"trade_id": "t2", "status": "CLOSED", "side": "LONG", "net_return_pct": 2.0},
    ]
    out = analyze_trades(trades)
    assert out["win_rate_pct"] == 100.0
    assert out["profit_factor"] is None


def test_all_loss_and_mixed_stats():
    trades = [
        {"trade_id": "t1", "status": "CLOSED", "side": "LONG", "net_return_pct": 2.0},
        {"trade_id": "t2", "status": "CLOSED", "side": "SHORT", "net_return_pct": -1.0},
        {"trade_id": "t3", "status": "OPEN", "side": "SHORT"},
    ]
    out = analyze_trades(trades)
    assert out["total_trades"] == 3
    assert out["closed_trades"] == 2
    assert out["open_trades"] == 1
    assert out["win_rate_pct"] == pytest.approx(50.0)
    assert out["profit_factor"] == pytest.approx(2.0)
    assert out["long_total_trades"] == 1
    assert out["short_total_trades"] == 1


def test_equity_metrics_and_drawdown():
    trades = [{"trade_id": "t1", "status": "CLOSED", "side": "LONG", "net_return_pct": -1.0}]
    equity = [
        {"equity_after": 11000, "equity_return_pct": 10.0},
        {"equity_after": 9000, "equity_return_pct": -18.18},
    ]
    out = analyze_trades(trades, equity, interval="1h", initial_equity=10000)
    assert out["max_drawdown_pct"] < 0
    assert out["time_sharpe"] is not None


def test_net_return_priority_and_final_return_fallback():
    trades = [
        {"trade_id": "t1", "status": "CLOSED", "side": "LONG", "net_return_pct": 1.0, "final_return_pct": 9.0},
        {"trade_id": "t2", "status": "CLOSED", "side": "LONG", "final_return_pct": -1.0},
    ]
    out = analyze_trades(trades)
    assert out["average_return_pct"] == pytest.approx(0.0)
