from __future__ import annotations

import pandas as pd

from presenters.backtest_presenter import (
    COMPARISON_COLUMNS,
    EQUITY_COLUMNS,
    TRADE_COLUMNS,
    comparison_rows,
    equity_rows,
    format_errors,
    format_summary,
    trade_rows,
)


def test_presenter_formats_summary_tables_comparison_and_errors_without_qt():
    summary_text = format_summary(
        {"total_trades": 1, "win_rate": 50.0, "total_return": 2.5},
        warnings=["research only"],
    )
    zero_text = format_summary({"total_trades": 0})
    trades = trade_rows(
        pd.DataFrame(
            [
                {
                    "entry_bar_index": 10,
                    "entry_time": "2026-01-01T09:00:00+08:00",
                    "entry_price": 100,
                    "exit_bar_index": 12,
                    "exit_time": "2026-01-01T09:10:00+08:00",
                    "exit_price": 102,
                    "side": "LONG",
                    "return_pct": 2.0,
                    "pnl": 20,
                    "exit_reason": "take_profit",
                    "holding_bars": 2,
                    "fee": 1,
                    "slippage": 0.5,
                }
            ]
        )
    )
    equity = equity_rows(pd.DataFrame([{"bar_index": 10, "time": "t", "equity": 10020, "drawdown": 0}]))
    comparison = comparison_rows(
        {
            "manual_trade_count": 2,
            "rule_trade_count": 1,
            "overlap_entry_bars": [10],
            "manual_only_bars": [20],
            "rule_only_bars": [],
            "overlap_ratio": 0.5,
        }
    )

    assert "total_trades: 1" in summary_text
    assert "research only" in summary_text
    assert "No rule trades" in zero_text
    assert set(trades[0]) == set(TRADE_COLUMNS)
    assert trades[0]["side"] == "LONG"
    assert set(equity[0]) == set(EQUITY_COLUMNS)
    assert [row["metric"] for row in comparison] == list(COMPARISON_COLUMNS)
    assert "bad input" in format_errors(["bad input"])
