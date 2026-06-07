from __future__ import annotations

import pandas as pd
import pytest

from backtesting.result_summary import summarize_backtest_result


def _trades():
    return pd.DataFrame(
        [
            {
                "status": "CLOSED",
                "side": "LONG",
                "net_return_pct": 2.0,
                "holding_bars": 5,
                "entry_fee_quote": 0.4,
                "exit_fee_quote": 0.5,
                "quantity": 10.0,
                "entry_price_raw": 100.0,
                "entry_fill_price": 100.1,
                "exit_price_raw": 102.2,
                "exit_fill_price": 102.1,
            },
            {
                "status": "CLOSED",
                "side": "LONG",
                "net_return_pct": -1.0,
                "holding_bars": 9,
                "entry_fee_quote": 0.4,
                "exit_fee_quote": 0.4,
                "quantity": 10.0,
                "entry_price_raw": 100.0,
                "entry_fill_price": 100.1,
                "exit_price_raw": 99.1,
                "exit_fill_price": 99.0,
            },
        ]
    )


def test_backtest_summary_reports_performance_holding_cost_and_drawdown():
    equity = pd.DataFrame({"equity_after": [10000.0, 10200.0, 10098.0]})

    summary = summarize_backtest_result(_trades(), equity, initial_equity=10000.0)

    assert summary["total_trades"] == 2
    assert summary["closed_trades"] == 2
    assert summary["win_rate"] == pytest.approx(50.0)
    assert summary["avg_return"] == pytest.approx(0.5)
    assert summary["median_return"] == pytest.approx(0.5)
    assert summary["total_return"] == pytest.approx(0.98)
    assert summary["max_drawdown"] == pytest.approx(-1.0)
    assert summary["profit_factor"] == pytest.approx(2.0)
    assert summary["expectancy"] == pytest.approx(0.5)
    assert summary["avg_holding_bars"] == pytest.approx(7.0)
    assert summary["max_holding_bars"] == 9
    assert summary["fee_total"] == pytest.approx(1.7)
    assert summary["slippage_total"] == pytest.approx(4.0)


def test_backtest_summary_is_safe_for_zero_trades():
    summary = summarize_backtest_result(pd.DataFrame(), pd.DataFrame(), initial_equity=10000.0)

    assert summary["total_trades"] == 0
    assert summary["closed_trades"] == 0
    assert summary["fee_total"] == 0.0
    assert summary["slippage_total"] == 0.0
    assert summary["win_rate"] is None
