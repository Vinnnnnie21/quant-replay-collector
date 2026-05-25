# 金融时间序列诊断

`time_series_analysis` 分析的是行情序列本身，不是用户标记的事件是否有效。事件研究和时间序列诊断在界面与报告中分开呈现。

## 方法对应

实现采用金融时间序列分析中的基础、可审计方法：

- 收益率与分布：`simple_return`、`log_return`、偏度、超额峰度、Jarque-Bera 正态性诊断和厚尾提示。
- 序列依赖：ACF、可选 PACF、Ljung-Box 白噪声诊断；同时检查平方收益和绝对收益的依赖。
- 波动率：滚动波动率、已实现波动率、EWMA 波动率、波动状态和 ARCH-effect proxy。
- 尾部风险：历史、正态和 EWMA 口径的 VaR / Expected Shortfall，以及最大回撤。
- 短周期 K 线警告：负的一阶收益自相关、零收益比例和成交量集中度只能作为微观结构 proxy。
- 多品种共同变动：相关矩阵、滚动相关和 PCA 第一共同因子 proxy。

这里没有实现完整 GARCH 极大似然估计、逐笔订单簿价差估计、复杂因果模型或涨跌预测器。

## 收益率口径

CSV 同时保存 simple return 与 log return。分布、自相关、波动率和风险诊断默认使用 log return。价格水平不直接用于相关性结论。

`annualized_log_return` 为 `mean(log_return) * periods_per_year`，表示年化连续复利收益。`annualized_return` 为 `exp(annualized_log_return) - 1`，表示由对数收益换算后的简单年化收益。两者不能混用。

## 输出

`time_series_summary.json` 新增：

- `distribution_diagnostics`
- `autocorrelation_diagnostics`
- `volatility_diagnostics`
- `risk_metrics`
- `microstructure_diagnostics`
- `factor_model`（提供多品种重叠收益时）

原有 `return_distribution`、`regime_distribution` 和 baseline 键保留，避免破坏既有导出消费者。

`time_series_report.md` 默认中文，可通过 `language="en_US"` 生成英文版本。

Jarque-Bera 统计量渐近服从自由度为 2 的卡方分布，因此其 p 值可使用 `exp(-statistic / 2)` 的闭式 survival function。Ljung-Box 在 `scipy` 可用时使用卡方 survival function；缺少 `scipy` 时返回近似 p 值并标记 `p_value_method="normal_approximation"`，该结果仅供诊断参考。

## 风险解释

VaR / ES 使用损失口径，正数表示损失。VaR 只表示阈值；超过阈值后的损失需要用 ES 辅助观察。两者均不是收益预测或交易信号。

对于 `1m`、`3m`、`5m` K 线，没有逐笔成交与 bid/ask 数据时，系统只报告噪声 proxy，不能估计真实 bid-ask spread。`bid_ask_bounce_proxy` 使用 lag-1 return autocorrelation `< -0.15` 的经验阈值，只提示可能存在高频噪声，不是价差估计。

PCA factor model 需要至少两个品种的重叠收益矩阵。单品种 K 线只会返回不可用提示，不能据此估计共同市场因子。

## 数据限制

若导出的来源为 `event_windows_only`，序列是事件周围的片段集合，不代表完整市场时间序列；跨窗口收益被故意禁止。这种输出适合局部诊断，不适合宣称全时段市场性质。
