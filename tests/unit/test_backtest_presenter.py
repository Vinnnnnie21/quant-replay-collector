from __future__ import annotations

import pandas as pd

from app_i18n import tr
from presenters.backtest_presenter import (
    COMPARISON_COLUMNS,
    EQUITY_COLUMNS,
    TRADE_COLUMNS,
    comparison_rows,
    equity_rows,
    format_errors,
    format_summary,
    localize_warnings,
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


def test_presenter_localizes_known_engine_warnings_for_chinese_ui():
    warning = "Backtest result is for research only and does not represent live trading returns."

    text = format_summary(
        {"total_trades": 1},
        warnings=[warning],
        translator=lambda key: tr(key, "zh_CN"),
    )

    assert warning not in text
    assert "回测结果仅用于研究" in text


def test_presenter_localizes_known_validation_errors_for_chinese_ui():
    error = "No analysis candidate parameters are available."

    text = format_errors(
        [error],
        translator=lambda key: tr(key, "zh_CN"),
    )

    assert error not in text
    assert "没有可用的分析候选参数" in text


def test_presenter_localizes_walk_forward_warnings_for_chinese_ui():
    warnings = [
        "sample size is small for train/validation/test split",
        "Parameters are selected on validation only; test is evaluated once.",
        "Parameter scan results are candidate hypotheses and may be overfit.",
        "Best train params differ from selected validation params.",
        "Test performance is materially weaker than validation; overfit risk is high.",
        "parameter combinations truncated from 500 to 300",
    ]

    localized = localize_warnings(
        warnings,
        translator=lambda key: tr(key, "zh_CN"),
    )

    assert all(not any("a" <= char.lower() <= "z" for char in value) for value in localized)
    assert localized[-1] == "参数组合已从 500 个截断为 300 个。"
