from __future__ import annotations

import pytest

from performance import build_performance_summary, flatten_performance_summary


def trade(trade_id: str, side: str, status: str, final_return_pct=None, holding_bars=None):
    return {
        "trade_id": trade_id,
        "side": side,
        "status": status,
        "final_return_pct": final_return_pct,
        "holding_bars": holding_bars,
        "created_at": f"2026-01-01T00:00:0{trade_id[-1]}+08:00",
        "updated_at": f"2026-01-01T00:01:0{trade_id[-1]}+08:00",
    }


def test_empty_trades():
    summary = build_performance_summary([])

    assert summary["total_trades"] == 0
    assert summary["closed_trades"] == 0
    assert summary["open_trades"] == 0
    assert summary["win_rate_pct"] is None
    assert summary["average_return_pct"] is None
    assert summary["max_profit_pct"] is None
    assert summary["max_loss_pct"] is None
    assert summary["average_holding_bars"] is None
    assert summary["recent_trade_result"] == "暂无交易"


def test_single_winning_trade_uses_final_return_pct():
    summary = build_performance_summary([
        trade("trd_1", "LONG", "CLOSED", final_return_pct=2.5, holding_bars=4)
    ])

    assert summary["total_trades"] == 1
    assert summary["closed_trades"] == 1
    assert summary["open_trades"] == 0
    assert summary["win_rate_pct"] == pytest.approx(100.0)
    assert summary["average_return_pct"] == pytest.approx(2.5)
    assert summary["max_profit_pct"] == pytest.approx(2.5)
    assert summary["max_loss_pct"] is None
    assert summary["average_holding_bars"] == pytest.approx(4.0)


def test_single_losing_trade_uses_final_return_pct():
    summary = build_performance_summary([
        trade("trd_1", "SHORT", "CLOSED", final_return_pct=-1.25, holding_bars=3)
    ])

    assert summary["win_rate_pct"] == pytest.approx(0.0)
    assert summary["average_return_pct"] == pytest.approx(-1.25)
    assert summary["max_profit_pct"] is None
    assert summary["max_loss_pct"] == pytest.approx(-1.25)
    assert summary["average_holding_bars"] == pytest.approx(3.0)


def test_mixed_wins_losses_and_open_trade():
    summary = build_performance_summary([
        trade("trd_1", "LONG", "CLOSED", final_return_pct=3.0, holding_bars=5),
        trade("trd_2", "SHORT", "CLOSED", final_return_pct=-1.0, holding_bars=2),
        trade("trd_3", "LONG", "OPEN", final_return_pct=None, holding_bars=None),
    ])

    assert summary["total_trades"] == 3
    assert summary["closed_trades"] == 2
    assert summary["open_trades"] == 1
    assert summary["win_rate_pct"] == pytest.approx(50.0)
    assert summary["average_return_pct"] == pytest.approx(1.0)
    assert summary["max_profit_pct"] == pytest.approx(3.0)
    assert summary["max_loss_pct"] == pytest.approx(-1.0)
    assert summary["average_holding_bars"] == pytest.approx(3.5)


def test_long_short_side_breakdown():
    summary = build_performance_summary([
        trade("trd_1", "LONG", "CLOSED", final_return_pct=2.0, holding_bars=4),
        trade("trd_2", "LONG", "OPEN"),
        trade("trd_3", "SHORT", "CLOSED", final_return_pct=-3.0, holding_bars=6),
    ])
    flat = flatten_performance_summary(summary)

    assert summary["by_side"]["LONG"]["total_trades"] == 2
    assert summary["by_side"]["LONG"]["closed_trades"] == 1
    assert summary["by_side"]["LONG"]["open_trades"] == 1
    assert summary["by_side"]["LONG"]["win_rate_pct"] == pytest.approx(100.0)
    assert summary["by_side"]["SHORT"]["total_trades"] == 1
    assert summary["by_side"]["SHORT"]["closed_trades"] == 1
    assert summary["by_side"]["SHORT"]["win_rate_pct"] == pytest.approx(0.0)
    assert flat["long_average_return_pct"] == pytest.approx(2.0)
    assert flat["short_average_return_pct"] == pytest.approx(-3.0)
