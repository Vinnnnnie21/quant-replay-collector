# Backtesting

Quant Replay Collector uses backtesting for research-only historical simulation. It provides no live trading, automatic order execution or trading signals. It provides no investment advice. Results describe the selected historical sample and do not predict future returns.

## Workflow

The current workflow is:

1. Load market K-lines for a symbol and interval.
2. Select a backtest date range.
3. Load default `StrategyRuleParams`, enter parameters manually, or apply mapped analysis thresholds.
4. Review the parameters and run `BacktestService`.
5. Inspect the summary, rule trades, equity curve, warnings and optional manual-vs-rule comparison.

The backtest panel is a minimal functional interface. It is not an execution terminal.

## StrategyRuleParams

`StrategyRuleParams` is the reproducible parameter contract for the current `deep_v_reversal` workflow.

Current capability limits are explicit:

- `strategy_name`: `deep_v_reversal`
- `direction`: `long_only`
- `exit_mode`: `tp_sl_timeout`
- `allow_overlap_positions`: `False`
- `entry_mode`: `next_open` or `confirmation_next_open`

Unsupported strategy names, short or both-side directions, other exit modes and overlapping positions are rejected rather than silently mapped to Deep V behavior.

The remaining fields describe the hypothesis and simulation assumptions:

- Trend and drop context: `trend_lookback`, `drop_lookback`, `min_drop_pct`
- Volume condition: `volume_lookback`, `volume_spike_multiple`
- Reversal shape: `lower_shadow_min_ratio`, `bullish_next_candle_min_body_ratio`, `rebound_confirm_bars`
- Optional regime filter: `regime_filter`, `uptrend_lookback`, `uptrend_min_return_pct`
- Exit assumptions: `take_profit_pct`, `stop_loss_pct`, `max_holding_bars`
- Cost and sizing assumptions: `fee_bps`, `slippage_bps`, `notional_per_trade`
- Entry spacing: `cooldown_bars`

Percentage-like thresholds use decimal fractions. For example, `0.02` means two percent.

## Date Range

`BacktestDateRange` contains:

- `symbol`
- `interval`
- `start`
- `end`

Filtering uses K-line `open_time_bjt` and the half-open interval `[start, end)`. `start` must be earlier than `end`.

The date-range layer returns an explicit error or status when:

- the requested range is invalid;
- no rows exist in the selected range;
- the selected range has too few bars for the configured lookbacks;
- the currently loaded data does not cover the requested range;
- the selected symbol or interval does not match the currently loaded K-lines.

The current backtest panel does not automatically reload another symbol or interval.

## Parameter Sources

Parameters can come from:

- defaults;
- manual input in the backtest panel;
- mapped analysis output.

The current analysis-to-backtest mapping is:

| Analysis output | StrategyRuleParams field |
| --- | --- |
| `drop_pct_threshold` | `min_drop_pct` |
| `volume_spike_threshold` | `volume_spike_multiple` |
| `lower_shadow_ratio` | `lower_shadow_min_ratio` |
| `next_candle_body_ratio` | `bullish_next_candle_min_body_ratio` |
| `trend_window` | `trend_lookback` |
| `future_window` | `max_holding_bars` |
| `tp_threshold` | `take_profit_pct` |
| `sl_threshold` | `stop_loss_pct` |

`future_window` is retained as a legacy analysis field name. It maps only to the exit timeout `max_holding_bars`; it is not an entry feature. Analysis outcome fields are rejected from the mapping.

## Deep V Entry And Lookahead Boundary

The Deep V entry rule may use only the current bar and historical OHLCV or rolling context available at the decision time. It does not use:

- `fwd_ret`;
- MFE or MAE;
- `hit_tp` or `hit_sl`;
- `outcome_labels`;
- future high or low values;
- final manual-trade returns.

Normal Deep V detection enters at the next bar open. If a bullish confirmation bar is required, confirmation is evaluated only after that bar is visible, and entry occurs at the following open. The confirmation bar is not used to claim an earlier fill.

Take-profit, stop-loss and timeout assumptions affect exit simulation only. They are not entry conditions.

## BacktestService Output

`BacktestService` is Qt-free orchestration. It validates parameters and data, slices the requested date range, runs the Deep V rule and returns:

- `summary`;
- `trades`;
- `equity_curve`;
- `warnings`;
- `errors`;
- optional `manual_vs_rule_comparison`.

The summary includes trade counts, win rate, average and median return, total return, maximum drawdown, profit factor, expectancy, holding-bar statistics, fees, slippage and exit-reason counts.

## Manual-vs-Rule Comparison

Manual-vs-rule comparison is descriptive only. It compares manual and simulated rule entry bars after the rule backtest has completed.

Manual trades never become rule entry conditions and do not influence rule signals. The comparison reports counts, overlapping entry bars, manual-only bars, rule-only bars, average returns, win rates and overlap ratio.

When manual-trade rows contain `symbol` and `interval`, the comparison filters them to the requested market. Legacy rows without these fields cannot be market-filtered reliably; treat such comparisons cautiously.

## Limits

- No Binance live-order API is used.
- No automatic orders are placed.
- Backtest results are not investment advice.
- Sample-internal performance does not establish future profitability.
- Parameter scans or selected thresholds are not out-of-sample validation.
- Intrabar TP/SL ordering, liquidity, slippage and fees can materially change results.
