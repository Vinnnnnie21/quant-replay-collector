from __future__ import annotations

import pandas as pd

from backtesting.engine import run_backtest
from backtesting.strategies import BaseStrategy, FeatureRuleLongStrategy, MovingAverageCrossStrategy
from backtesting.types import BacktestConfig, Signal


def _df(n=80):
    close = [120 - i * 0.2 for i in range(n)]
    for i in range(n // 2, n):
        close[i] = 100 + (i - n // 2) * 0.6
    return pd.DataFrame(
        {
            "bar_index": range(n),
            "open_time_bjt": pd.date_range("2026-01-01", periods=n, freq="min", tz="Asia/Shanghai"),
            "open": close,
            "high": [c + 0.5 for c in close],
            "low": [c - 0.5 for c in close],
            "close": close,
            "volume": [100.0] * n,
            "pre_ret_20": [-0.04] * n,
        }
    )


def _risk_df(side="LONG", second_high=101.0, second_low=99.0, second_close=100.0, start_bar=0, n=6):
    close = [100.0] * max(0, n)
    high = [101.0] * max(0, n)
    low = [99.0] * max(0, n)
    if n > 0:
        high[0] = 100.0
        low[0] = 100.0
    if n > 1:
        close[1] = second_close
        high[1] = second_high
        low[1] = second_low
    return pd.DataFrame(
        {
            "bar_index": range(start_bar, start_bar + n),
            "open_time_bjt": pd.date_range("2026-01-01", periods=n, freq="min", tz="Asia/Shanghai"),
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": [100.0] * n,
            "pre_ret_20": [-0.04] * n,
        }
    )


class OpenSideStrategy(BaseStrategy):
    def __init__(self, side="LONG"):
        self.side = side

    def on_bar(self, i, row, history, position):
        if i == 0 and position is None:
            return Signal.OPEN_LONG if self.side == "LONG" else Signal.OPEN_SHORT
        return Signal.HOLD


class LastBarOpenStrategy(BaseStrategy):
    def on_bar(self, i, row, history, position):
        if position is None:
            return Signal.OPEN_LONG
        return Signal.HOLD


def test_empty_df_safe():
    result = run_backtest(pd.DataFrame(), BaseStrategy(), BacktestConfig(), "BTCUSDT", "1m")
    assert result.trades.empty
    assert result.metrics["basis"] == "backtest_records"


def test_feature_rule_produces_trade_and_forced_close():
    strategy = FeatureRuleLongStrategy([{"column": "pre_ret_20", "op": "<=", "value": -0.03}], exit_bars=999)
    result = run_backtest(_df(10), strategy, BacktestConfig(), "BTCUSDT", "1m")
    assert len(result.trades) == 1
    assert bool(result.trades.iloc[0]["forced_exit"]) is True
    assert any("force-closed" in w for w in result.warnings)


def test_single_position_limit():
    strategy = FeatureRuleLongStrategy([{"column": "pre_ret_20", "op": "<=", "value": -0.03}], exit_bars=5)
    result = run_backtest(_df(20), strategy, BacktestConfig(single_position=True), "BTCUSDT", "1m")
    assert len(result.trades) <= 4


def test_fee_and_slippage_reduce_net_return():
    strategy = FeatureRuleLongStrategy([{"column": "pre_ret_20", "op": "<=", "value": -0.03}], exit_bars=3)
    no_cost = run_backtest(_df(5), strategy, BacktestConfig(fee_bps=0, slippage_bps=0), "BTCUSDT", "1m")
    with_cost = run_backtest(_df(5), strategy, BacktestConfig(fee_bps=10, slippage_bps=10), "BTCUSDT", "1m")
    assert with_cost.trades.iloc[0]["net_return_pct"] < no_cost.trades.iloc[0]["gross_return_pct"]


def test_long_stop_loss_uses_trigger_price_not_profitable_close():
    result = run_backtest(
        _risk_df(second_high=112, second_low=98, second_close=110),
        OpenSideStrategy("LONG"),
        BacktestConfig(fee_bps=0, slippage_bps=0, stop_loss_pct=1, signal_timing="on_close"),
        "BTCUSDT",
        "1m",
    )
    trade = result.trades.iloc[0]
    assert trade["exit_reason"] == "stop_loss"
    assert trade["exit_fill_price"] == 99.0
    assert trade["net_return_pct"] < 0


def test_long_take_profit_uses_trigger_price():
    result = run_backtest(
        _risk_df(second_high=103, second_low=99, second_close=90),
        OpenSideStrategy("LONG"),
        BacktestConfig(fee_bps=0, slippage_bps=0, take_profit_pct=2, signal_timing="on_close"),
        "BTCUSDT",
        "1m",
    )
    trade = result.trades.iloc[0]
    assert trade["exit_reason"] == "take_profit"
    assert trade["exit_fill_price"] == 102.0
    assert trade["net_return_pct"] > 0


def test_short_stop_loss_uses_trigger_price_not_profitable_close():
    result = run_backtest(
        _risk_df(second_high=102, second_low=80, second_close=80),
        OpenSideStrategy("SHORT"),
        BacktestConfig(fee_bps=0, slippage_bps=0, stop_loss_pct=1, signal_timing="on_close"),
        "BTCUSDT",
        "1m",
    )
    trade = result.trades.iloc[0]
    assert trade["exit_reason"] == "stop_loss"
    assert trade["exit_fill_price"] == 101.0
    assert trade["net_return_pct"] < 0


def test_short_take_profit_uses_trigger_price():
    result = run_backtest(
        _risk_df(second_high=100, second_low=97, second_close=110),
        OpenSideStrategy("SHORT"),
        BacktestConfig(fee_bps=0, slippage_bps=0, take_profit_pct=2, signal_timing="on_close"),
        "BTCUSDT",
        "1m",
    )
    trade = result.trades.iloc[0]
    assert trade["exit_reason"] == "take_profit"
    assert trade["exit_fill_price"] == 98.0
    assert trade["net_return_pct"] > 0


def test_same_bar_stop_loss_before_take_profit():
    result = run_backtest(
        _risk_df(second_high=102, second_low=98, second_close=101),
        OpenSideStrategy("LONG"),
        BacktestConfig(fee_bps=0, slippage_bps=0, stop_loss_pct=1, take_profit_pct=1, signal_timing="on_close"),
        "BTCUSDT",
        "1m",
    )
    trade = result.trades.iloc[0]
    assert trade["exit_reason"] == "stop_loss"
    assert trade["exit_fill_price"] == 99.0


def test_same_bar_take_first_priority_selects_take_profit():
    result = run_backtest(
        _risk_df(second_high=102, second_low=98, second_close=101),
        OpenSideStrategy("LONG"),
        BacktestConfig(
            fee_bps=0,
            slippage_bps=0,
            stop_loss_pct=1,
            take_profit_pct=1,
            stop_take_priority="take_first",
            signal_timing="on_close",
        ),
        "BTCUSDT",
        "1m",
    )
    assert result.trades.iloc[0]["exit_reason"] == "take_profit"
    assert result.trades.iloc[0]["exit_fill_price"] == 101.0


def test_risk_exit_still_applies_fee_and_slippage():
    result = run_backtest(
        _risk_df(second_high=104, second_low=99, second_close=90),
        OpenSideStrategy("LONG"),
        BacktestConfig(fee_bps=10, slippage_bps=10, take_profit_pct=2, signal_timing="on_close"),
        "BTCUSDT",
        "1m",
    )
    trade = result.trades.iloc[0]
    assert trade["exit_reason"] == "take_profit"
    assert trade["exit_fill_price"] < trade["exit_price_raw"]
    assert trade["net_return_pct"] < trade["gross_return_pct"]


def test_equity_curve_contains_mark_to_market_unrealized_pnl():
    df = _risk_df(n=4)
    df.loc[1, "close"] = 105.0
    result = run_backtest(
        df,
        OpenSideStrategy("LONG"),
        BacktestConfig(fee_bps=0, slippage_bps=0, signal_timing="on_close"),
        "BTCUSDT",
        "1m",
    )
    assert "unrealized_pnl" in result.equity_curve.columns
    assert result.equity_curve.iloc[1]["unrealized_pnl"] > 0


def test_taker_fee_and_funding_are_included_in_net_pnl():
    without_cost = run_backtest(
        _risk_df(n=4),
        OpenSideStrategy("LONG"),
        BacktestConfig(fee_bps=0, slippage_bps=0, signal_timing="on_close"),
        "BTCUSDT",
        "1m",
    )
    with_cost = run_backtest(
        _risk_df(n=4),
        OpenSideStrategy("LONG"),
        BacktestConfig(
            fee_bps=0,
            taker_fee_bps=10,
            funding_fee_bps=5,
            slippage_bps=0,
            signal_timing="on_close",
        ),
        "BTCUSDT",
        "1m",
    )
    trade = with_cost.trades.iloc[0]
    assert trade["funding_pnl_quote"] < 0
    assert trade["net_pnl_quote"] < without_cost.trades.iloc[0]["net_pnl_quote"]


def test_exit_bars_uses_internal_index_when_bar_index_starts_at_100():
    result = run_backtest(
        _risk_df(start_bar=100, n=20),
        FeatureRuleLongStrategy([{"column": "pre_ret_20", "op": "<=", "value": -0.03}], exit_bars=5),
        BacktestConfig(fee_bps=0, slippage_bps=0, signal_timing="on_close"),
        "BTCUSDT",
        "1m",
    )
    trade = result.trades.iloc[0]
    assert trade["holding_bars"] == 5
    assert trade["exit_bar_index"] == 104
    assert bool(trade["forced_exit"]) is False


def test_next_open_signal_executes_on_next_bar_open():
    df = _risk_df(second_high=111, second_low=99, second_close=107, n=4)
    df.loc[0, "open"] = 90.0
    df.loc[0, "close"] = 105.0
    df.loc[1, "open"] = 101.0
    result = run_backtest(
        df,
        OpenSideStrategy("LONG"),
        BacktestConfig(fee_bps=0, slippage_bps=0, signal_timing="next_open"),
        "BTCUSDT",
        "1m",
    )
    trade = result.trades.iloc[0]
    assert trade["signal_bar_index"] == 0
    assert trade["execution_bar_index"] == 1
    assert trade["entry_fill_price"] == 101.0


def test_on_close_signal_executes_on_current_close_even_if_fill_mode_open():
    df = _risk_df(second_high=101, second_low=99, second_close=100, n=3)
    df.loc[0, "open"] = 90.0
    df.loc[0, "close"] = 105.0
    result = run_backtest(
        df,
        OpenSideStrategy("LONG"),
        BacktestConfig(fee_bps=0, slippage_bps=0, fill_mode="OPEN", signal_timing="on_close"),
        "BTCUSDT",
        "1m",
    )
    trade = result.trades.iloc[0]
    assert trade["entry_fill_price"] == 105.0
    assert any("forces strategy fills to CLOSE" in w for w in result.warnings)


def test_strategy_cannot_see_current_close_then_fill_current_open():
    df = _risk_df(second_high=111, second_low=99, second_close=107, n=4)
    df.loc[0, "open"] = 90.0
    df.loc[0, "close"] = 105.0
    df.loc[1, "open"] = 101.0
    result = run_backtest(
        df,
        OpenSideStrategy("LONG"),
        BacktestConfig(fee_bps=0, slippage_bps=0, fill_mode="OPEN"),
        "BTCUSDT",
        "1m",
    )
    trade = result.trades.iloc[0]
    assert trade["entry_fill_price"] == 101.0
    assert trade["entry_fill_price"] != 90.0


def test_last_bar_open_signal_is_ignored_in_next_open_mode():
    result = run_backtest(
        _risk_df(n=1),
        LastBarOpenStrategy(),
        BacktestConfig(fee_bps=0, slippage_bps=0),
        "BTCUSDT",
        "1m",
    )
    assert result.trades.empty
    assert any("last-bar open signal ignored" in w for w in result.warnings)


def test_strategy_cannot_see_future_data():
    class FutureCheckStrategy(BaseStrategy):
        def on_bar(self, i, row, history, position):
            assert len(history) == i + 1
            return Signal.HOLD

    run_backtest(_df(10), FutureCheckStrategy(), BacktestConfig(), "BTCUSDT", "1m")


def test_ma_strategy_metrics_present():
    result = run_backtest(_df(120), MovingAverageCrossStrategy(3, 8, "LONG_ONLY"), BacktestConfig(), "BTCUSDT", "1m")
    assert len(result.trades) >= 1
    for key in ["win_rate_pct", "profit_factor", "max_drawdown_pct", "trade_sharpe"]:
        assert key in result.metrics
