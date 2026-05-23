# 策略一致性验证

## 模块目标

`strategy_consistency` 用来判断人工交易样本是否大致来自同一套交易逻辑。

它解决的是输入质量问题。不是判断策略能不能赚钱。

如果交易样本本身很混乱，后续特征分析、候选规则、回测和 LLM 解读都可能挖出假规律。

## StrategyProfile 字段

- `strategy_id`：策略档案 ID。
- `name`：策略名称。
- `description`：策略说明。
- `expected_direction`：期望方向，支持 `LONG_ONLY`、`SHORT_ONLY`、`BOTH`。
- `expected_market_state`：期望市场状态，如 `AFTER_DROP`、`REVERSAL`。
- `required_tags`：期望出现的标签。
- `forbidden_tags`：不应出现的标签。
- `expected_entry_features`：期望满足的入场前/入场当下特征。
- `max_missing_note_pct`：备注缺失率阈值。
- `min_sample_count`：最低样本量。

默认档案是“大跌后的反转 K 线做多”。

## 一致性评分组成

总分 100。

- 样本数量充足度：15 分
- 方向一致性：15 分
- 市场状态一致性：20 分
- 相似场景动作一致性：20 分
- 标签一致性：15 分
- 时间稳定性：15 分

解释：

- `>= 80`：可以进入后续分析。
- `60-80`：需要人工复核。
- `< 60`：不适合直接规则挖掘。

## 相似场景动作一致性

模块会用事件前和事件当下特征做标准化欧氏距离。

默认特征包括：

- `pre_ret_20`
- `pre_max_drawdown_20`
- `pre_volatility_20`
- `event_lower_wick_ratio`
- `event_close_position`
- `event_volume_ratio_20`
- `event_body_ratio`
- `capitulation_score`

相似样本如果经常对应不同方向或不同动作，说明交易行为不稳定。

## 时间稳定性

样本会按顺序分成 early / middle / late 三段。

检查方向、标签、主要特征均值是否明显漂移。

如果前期和后期交易逻辑不同，系统会提示漂移风险。

## 选择性标注偏差

只标成功案例，不标失败案例，会让规则挖掘严重失真。

如果平仓/失败样本明显不足，报告会提示可能存在选择性标注偏差。

## 如何解释报告

报告只能回答一个问题：

这些样本是否足够像同一套策略。

它不能回答：

- 策略是否赚钱。
- 策略是否能实盘。
- 参数是否最优。
- 下一笔该不该交易。

## 限制

- 不能证明策略赚钱。
- 不能替代样本外验证。
- 不能识别所有主观交易逻辑。
- 样本少时不可靠。
- K 线级数据无法还原真实盘口和成交路径。
