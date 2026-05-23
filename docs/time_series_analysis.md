# 时间序列分析与市场状态诊断

## 模块目标

`time_series_analysis` 用来做基础金融时间序列统计。

它不生成交易信号。
它不证明策略有效。
它只帮助判断当前样本所在市场环境、收益分布、波动状态和随机基准口径。

## Return Distribution

`returns.py` 会从 K 线生成：

- simple_return
- log_return
- rolling_return_5 / 10 / 20
- rolling_volatility_20 / 50
- realized_volatility_20
- downside_volatility_20
- high_low_range_pct
- close_position
- volume_zscore_20
- return_zscore_20

`summarize_return_distribution()` 输出均值、中位数、标准差、偏度、峰度、分位数和自相关。

## Autocorrelation

当前输出：

- return autocorr lag 1 / 3 / 5
- squared return autocorr lag 1 / 5

收益率自相关用于观察短期惯性或均值回复。
平方收益自相关用于观察波动聚集。

这只是统计描述，不是交易信号。

## Volatility Regime / Trend Regime

`regime.py` 会生成：

- volatility_regime: low_vol / normal_vol / high_vol / extreme_vol
- trend_regime: uptrend / downtrend / range
- drawdown_pct
- rolling_return_50
- rolling_volatility_50
- trend_threshold
- regime_label

趋势阈值使用：

```text
trend_threshold = max(min_abs_threshold, vol_multiplier * rolling_volatility_50 * sqrt(window))
```

这样能把单根 bar 波动率缩放到同一窗口口径，再和 rolling_return 做比较。

## event_windows_only 的限制

当前 exporter 还不能读取完整 session K 线。
所以导出中的 `time_series_summary.json` 默认使用 `event_windows_long` 拼出局部事件窗口序列，标记为：

```text
source = event_windows_only
```

这不是完整市场分布。
它只代表被标注事件附近的局部样本。

不能把它解释成整个回放区间的市场状态。

## Baseline 口径

### event_label_resampling

`build_random_event_baseline()` 当前做的是事件标签重采样。

它从已有 `event_features` / labels 里抽样。
这不是完整随机市场事件基准。
它只能回答：“已标注事件内部的结果分布大概是什么样”。

如果样本本身有选择性偏差，这个 baseline 也会继承偏差。

### random_bar_forward_return

`build_random_bar_baseline()` 是为完整 K 线准备的随机 bar 基准。

它会从完整 K 线中随机抽 bar，并计算未来 horizon 根方向调整收益：

- LONG: `close[t+h] / close[t] - 1`
- SHORT: `close[t] / close[t+h] - 1`

当前 exporter 还没有完整 session K 线存储，所以这个函数主要作为后续接入点。

## 为什么时间序列统计不等于交易信号

收益分布、波动率状态、自相关和随机基准只是描述性统计。

它们不能说明某个点应该买入或卖出。
它们也不能证明某个策略有因果优势。

只有经过清晰规则、费用滑点、样本外验证和失败样本审计后，才有资格进入回测研究。

## Roadmap

- 保存完整 session K 线，用于真正 session-level 时间序列分析。
- 增加随机大跌基准，而不是只做全市场随机 bar。
- 按 regime 分层回测，比较不同市场状态下的规则稳定性。
- 增加事件窗口统计和完整市场统计的差异报告。
