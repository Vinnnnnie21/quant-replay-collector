from __future__ import annotations

import pandas as pd

from backtesting.deep_v_reversal import DeepVReversalStrategy, evaluate_deep_v_entry
from backtesting.engine import run_backtest
from backtesting.parameter_schema import StrategyRuleParams
from backtesting.types import BacktestConfig, Signal


def _params(**overrides):
    values = {
        "trend_lookback": 5,
        "drop_lookback": 5,
        "min_drop_pct": 0.02,
        "volume_lookback": 5,
        "volume_spike_multiple": 2.0,
        "lower_shadow_min_ratio": 0.45,
        "bullish_next_candle_min_body_ratio": 0.6,
        "uptrend_lookback": 10,
    }
    values.update(overrides)
    return StrategyRuleParams(**values).validate()


def _pinbar_history():
    rows = []
    for idx in range(20):
        close = 110.0 - idx * 0.5
        rows.append(
            {
                "bar_index": idx,
                "open_time_bjt": pd.Timestamp("2026-01-01 09:00", tz="Asia/Shanghai") + pd.Timedelta(minutes=idx),
                "open": close + 0.2,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 100.0,
            }
        )
    rows.append(
        {
            "bar_index": 20,
            "open_time_bjt": pd.Timestamp("2026-01-01 09:20", tz="Asia/Shanghai"),
            "open": 99.0,
            "high": 101.0,
            "low": 94.0,
            "close": 100.0,
            "volume": 350.0,
        }
    )
    return pd.DataFrame(rows)


def _confirmation_history():
    setup = _pinbar_history()
    setup.loc[setup.index[-1], ["open", "high", "low", "close"]] = [100.0, 100.5, 98.8, 99.0]
    confirmation = {
        "bar_index": 21,
        "open_time_bjt": pd.Timestamp("2026-01-01 09:21", tz="Asia/Shanghai"),
        "open": 99.0,
        "high": 104.5,
        "low": 98.8,
        "close": 104.0,
        "volume": 130.0,
    }
    return pd.concat([setup, pd.DataFrame([confirmation])], ignore_index=True)


def test_deep_v_pinbar_requires_drop_volume_and_long_lower_shadow():
    history = _pinbar_history()
    decision = evaluate_deep_v_entry(history, _params())

    assert decision.should_open_long is True
    assert decision.reason == "pinbar_close"

    no_volume = history.copy()
    no_volume.loc[no_volume.index[-1], "volume"] = 100.0
    assert evaluate_deep_v_entry(no_volume, _params()).should_open_long is False

    no_drop = history.copy()
    no_drop.loc[:, "close"] = 100.0
    assert evaluate_deep_v_entry(no_drop, _params()).should_open_long is False


def test_confirmation_bar_only_triggers_after_confirmation_is_visible():
    history = _confirmation_history()

    before_confirmation = evaluate_deep_v_entry(history.iloc[:-1], _params())
    after_confirmation = evaluate_deep_v_entry(history, _params())

    assert before_confirmation.should_open_long is False
    assert after_confirmation.should_open_long is True
    assert after_confirmation.reason == "confirmation_bar"
    assert after_confirmation.signal_bar_index == 21


def test_strategy_is_long_only_and_enforces_cooldown_and_overlap_guard():
    history = _pinbar_history()
    strategy = DeepVReversalStrategy(_params(cooldown_bars=2, allow_overlap_positions=False))
    row = history.iloc[-1]

    assert strategy.on_bar(20, row, history, None) == Signal.OPEN_LONG
    assert strategy.on_bar(21, row, history, None) == Signal.HOLD
    assert strategy.on_bar(23, row, history, None) == Signal.OPEN_LONG
    assert strategy.on_bar(24, row, history, {"side": "LONG"}) == Signal.HOLD
    assert Signal.OPEN_SHORT not in {
        strategy.on_bar(25, row, history, None),
        strategy.on_bar(26, row, history, None),
    }


def test_next_open_entry_executes_after_signal_bar():
    history = _pinbar_history()
    next_bar = history.iloc[-1].to_dict()
    next_bar.update(
        {
            "bar_index": 21,
            "open_time_bjt": pd.Timestamp("2026-01-01 09:21", tz="Asia/Shanghai"),
            "open": 102.0,
            "high": 103.0,
            "low": 101.0,
            "close": 102.5,
            "volume": 100.0,
        }
    )
    data = pd.concat([history, pd.DataFrame([next_bar])], ignore_index=True)

    result = run_backtest(
        data,
        DeepVReversalStrategy(_params()),
        BacktestConfig(fee_bps=0, slippage_bps=0, signal_timing="next_open"),
        "BTCUSDT",
        "1m",
    )

    trade = result.trades.iloc[0]
    assert trade["entry_signal_bar_index"] == 20
    assert trade["entry_execution_bar_index"] == 21
    assert trade["entry_fill_price"] == 102.0


def test_deep_v_entry_ignores_outcome_and_future_columns():
    visible = _pinbar_history()
    optimistic = visible.assign(
        fwd_ret_10=999.0,
        mfe_10=999.0,
        mae_10=999.0,
        hit_tp=1,
        hit_sl=0,
        future_high=999999.0,
        future_low=0.0,
    )
    pessimistic = visible.assign(
        fwd_ret_10=-999.0,
        mfe_10=-999.0,
        mae_10=-999.0,
        hit_tp=0,
        hit_sl=1,
        future_high=0.0,
        future_low=-999999.0,
    )

    assert evaluate_deep_v_entry(optimistic, _params()) == evaluate_deep_v_entry(pessimistic, _params())
