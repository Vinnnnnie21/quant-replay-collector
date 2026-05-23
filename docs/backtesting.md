# Backtesting Guide

Quant Replay Collector 的回测模块只用于研究。它不是实盘交易系统，也不会连接交易所下单。

## BacktestConfig

`BacktestConfig` 控制回测资金和成交假设：

- `initial_equity`
- `notional_quote`
- `fee_bps`
- `slippage_bps`
- `fill_mode`
- `allow_short`
- `single_position`
- `max_bars_hold`
- `stop_loss_pct`
- `take_profit_pct`

手续费、滑点和成交价模式会影响 `net_return_pct`。报告必须同时区分 gross 和 net。

## Strategy 接口

策略需要实现：

```python
def on_bar(self, i, row, history, position):
    return "HOLD"
```

`history` 只包含当前 bar 和历史 bar。策略不能读取未来 K 线。

## 内置策略

`MovingAverageCrossStrategy`

- `fast_window`
- `slow_window`
- `direction`

`FeatureRuleLongStrategy`

- `conditions`
- `exit_bars`
- `stop_loss_pct`
- `take_profit_pct`

Feature Rule 禁止使用未来字段，例如 `fwd_*`、`post_*`、`mfe`、`mae`、`manual_trade_final`。

## 如何新增策略

继承 `BaseStrategy`，实现 `on_bar`。返回值只能是：

- `HOLD`
- `OPEN_LONG`
- `OPEN_SHORT`
- `CLOSE_LONG`
- `CLOSE_SHORT`

不要在策略里访问完整未来数据。不要写下单 API。

## 参数扫描

`grid_search` 接收 `param_grid`，对每组参数运行一次回测，输出收益、胜率、Profit Factor、Sharpe、最大回撤等指标。

参数组合默认最多 300 组。组合太多时结果更容易过拟合。

## 样本外验证

`walk_forward_grid_search` 使用 train / validation / test：

- train 用于跑参数扫描。
- validation 用于选择参数。
- test 只做最终评估。

不能用 test set 调参。否则样本外验证失效。

## 指标解释

Sharpe 衡量平均收益相对波动的比例。加密货币 24/7 交易，年化周期按 K 线 interval 推断。

Sortino 只惩罚下行波动。

Profit Factor 是盈利总和除以亏损绝对值。全胜时返回 `None`，不返回无穷大。

Max Drawdown 是权益从峰值回落的最大比例，使用负数百分比表示。

这些指标只描述历史样本表现，不代表未来收益。
