# 真实研究日常工作流

Quant Replay Collector 的主目标从 GitHub 展示，转为用户本人长期使用的统计学习研究工具。它研究的是深 V 反转做多场景里的人工开仓判断：什么样的候选形态会被用户标成 `ENTRY`，什么样的候选会被拒绝或保留观察。

这个工具不做自动交易，不预测未来收益，不生成买卖信号。`review queue` 只是复标队列，不是开仓列表。

## 保留边界

现有回放、交易记录、标注、导出、回测、分析、SQLite 兼容和测试都保留。`main_app.py` 仍是 Qt 壳层，不承接新的研究逻辑。`research/`、`time_series_analysis/`、`backtesting/`、`strategy_consistency/`、`exporter.py`、`dataset_builder.py`、`storage.py` 和已有 entry logic research 模块继续按原语义工作。

新的工作流只把这些能力组织成长期研究流程：

- 回放模块：还原当时的盘面和人工判断过程。
- `entry_observation_universe`：宽松筛出值得看的候选 observation。
- `entry_annotations`：保存 `human_decision` 和标注理由。
- `entry_context_features`：生成决策时可见的输入特征。
- `entry_outcome_labels`：单独生成后验结果标签。
- `temporal_validation`：做 chronological split、walk-forward split、purge 和 embargo。
- `entry_distribution_diagnostics`：检查分布、厚尾、漂移和样本质量。
- `entry_logic_scoring` / `pu_entry_learning`：给未标注候选排序，辅助复标。
- `active_label_selection`：生成复标队列。
- `entry_experiment_registry`：保存实验 manifest。
- `entry_logic_report`：生成 Markdown / JSON 复盘报告。

## 标签定义

`ENTRY`：用户在该决策点会考虑开多，或历史样本中确实执行过对应开多动作。它是人的判断标签，不是未来收益标签。

`REJECT`：用户明确认为该 setup 不该开仓。它不是“价格后来没涨”的同义词。

`UNCERTAIN`：信息不足、结构不干净、需要等待确认，用户暂时不给出明确开仓或拒绝判断。

`UNLABELED`：候选尚未人工检查。未开仓、未入选、未复标样本不能直接当成负样本。

## setup_bar_index 与 decision_bar_index

`setup_bar_index` 是候选形态锚点。它通常指大跌结束、长下影、放量恐慌或反转结构出现的那根 K 线。

`decision_bar_index` 是用户真正做判断时最后可见的 K 线。

两者可以相同，也可以不同：

- `CURRENT_BAR_CLOSE`：用户在 setup bar 收盘后判断，`setup_bar_index == decision_bar_index`。
- `NEXT_BAR_CONFIRMATION`：用户等待下一根大阳确认，`decision_bar_index` 可以是 `setup_bar_index + 1`。

特征只能读到 `decision_bar_index` 及以前的数据。`setup_bar_index` 只是形态定位，不能成为读取未来 K 线的理由。后验 outcome labels 只能在决策点之后计算，并且不得进入模型输入。

## 单次研究数据流

1. 下载或更新历史 K 线数据，保存本地缓存和数据范围。这里指研究数据，不接 Binance 实盘下单 API。
2. 进入回放，按真实观察顺序查看行情，不在标注时偷看未来走势。
3. 用 observation universe 宽松筛出候选点。候选规则只回答“值得看吗”，不回答“该不该开仓”。
4. 用户人工标注 `ENTRY`、`REJECT`、`UNCERTAIN` 或保留 `UNLABELED`，并记录 confidence、reason_tags、note 和 decision_timing。
5. 对高相似、边界不确定、形态分散的候选做复标。复标优先解决标签边界，不追求一次性覆盖全部历史。
6. 生成 context features，只使用 `decision_bar_index` 及以前可见的 K 线结构、趋势、成交量、波动和位置特征。
7. 生成 outcome labels，单独保存 `fwd_ret`、MFE、MAE、TP/SL 命中等后验字段，用于报告诊断。
8. 做 chronological split 或 walk-forward split，并按 horizon 设置 purge 和 embargo。
9. 做统计诊断，检查 ENTRY / REJECT / UNLABELED 的特征分布、偏度、超额峰度、分位数、厚尾、ACF、Ljung-Box 和时间漂移。
10. 用 ENTRY prototype、PU ranking 和 active learning 给 UNLABELED 候选排序。分数命名只能使用 `entry_logic_score`、`human_entry_similarity`、`setup_confidence` 或内部 `pu_entry_score`。
11. 保存实验 manifest，记录数据版本、标注版本、feature_cols、split、参数、指标、报告路径和 warning。
12. 生成 Markdown / JSON 报告，复盘标签边界、特征画像、评分排序和风险声明。

## context features 与 outcome labels

`entry_context_features` 是模型输入候选。它只能包含决策时可见的信息，例如 prior return、trend slope、drop from recent high、lower shadow、range、volume z-score、ATR、recent high/low distance。

`entry_outcome_labels` 是后验研究标签。它可以包含 `fwd_ret_*`、`mfe_*`、`mae_*`、`hit_tp_*`、`hit_sl_*` 和路径结果，但只能用于报告、风险诊断和结果对照。

这些字段不得进入 context features 或 scoring 输入：

- `future_return`
- `fwd_ret`
- `MFE` / `mfe`
- `MAE` / `mae`
- `hit_tp`
- `hit_sl`
- `pnl`
- `profit`
- `win`

如果实验发现这些字段混入输入，实验应标记为无效。

## 时间序列切分

金融时间序列不能随机切分。随机切分会把相邻行情、同一波行情的前后片段、重叠 outcome window 分散到训练和测试里，看起来像泛化，实际可能只是信息泄漏。

研究默认使用：

- chronological split：按时间顺序划分 train / validation / test。
- walk-forward split：用滚动训练窗口和后续验证窗口模拟持续研究。
- purge：移除边界附近会共享未来标签窗口的样本。
- embargo：在边界后留出隔离区，减少近邻样本污染。

这只能降低评估污染，不能证明策略未来有效。

## 半监督和主动学习

半监督学习只做候选排序和复标辅助。当前阶段只用 pandas / numpy，不引入 sklearn、torch、tensorflow 或 xgboost。

PU 思路把人工 `ENTRY` 当正例画像，再对 `UNLABELED` 估计相似度。`REJECT` 可以用于 holdout 评估或阈值参考，但不能把所有 `UNLABELED` 当负样本。

active learning 的输出是“哪些候选更值得用户复标”：

- `high_similarity`：最像历史 ENTRY 的未标注候选。
- `uncertain`：分数处于边界区间，最需要人工判断的候选。
- `diverse`：覆盖不同候选形态，避免反复标同一种结构。

这些队列不能被写成开仓列表，也不能当成交易建议。

## 实验必须保存的信息

每次实验都应保存 manifest。最少包含：

- `experiment_id`
- `created_at`
- `app_version`
- `symbol`
- `interval`
- `data_start`
- `data_end`
- 数据来源、缓存版本或数据 hash
- observation universe 参数
- `annotation_version`
- ENTRY / REJECT / UNCERTAIN / UNLABELED 数量
- `feature_version`
- `feature_cols`
- lookback windows
- outcome horizon、TP/SL 假设和不足 horizon 的处理方式
- `split_method`
- train / validation / test 时间范围
- `purge_bars`
- `embargo_bars`
- `model_type`
- `model_params`
- metrics
- warning，例如小样本、标签不足、时间泄漏风险、分布漂移
- artifact paths，例如 scores、review queue、Markdown 报告、JSON 报告、data dictionary

实验 manifest 的目的只有一个：以后能复现当时怎么得出这个研究结果。

## 不能直接当成策略有效性证明的结果

下面这些都不能单独证明策略有效：

- 样本内 `human_entry_similarity` 很高。
- review queue 排名靠前。
- ENTRY 样本的后验收益分布更好。
- ENTRY vs REJECT 某个特征差异明显。
- 单次回测赚钱。
- 未做 purge / embargo 的测试表现。
- 小样本上的高 precision@k。
- 用户记忆中的少数成功案例。

这些结果只能作为复盘材料、假设线索或下一轮标注的依据。策略有效性需要更严格的样本外验证、稳定性检查和人工复核。

## 每日、每周、每月使用节奏

每日：

- 更新历史 K 线数据。
- 回放一小段市场，不追求覆盖全部行情。
- 标注新的候选 observation，重点记录拒绝理由和不确定原因。
- 处理少量 active learning review queue。
- 导出当天 Markdown / JSON 报告，记录异常样本。

每周：

- 重新生成 context features 和 outcome labels。
- 检查 ENTRY / REJECT / UNLABELED 分布、样本数量和 reason_tags。
- 跑 chronological 或 walk-forward 诊断。
- 用 prototype / PU scoring 生成下周复标队列。
- 复查高分但被拒绝、低分但被标 ENTRY、长期 `UNCERTAIN` 的样本。

每月：

- 冻结一次数据版本、标注版本和 feature_cols。
- 保存完整实验 manifest。
- 对比不同月份的分布漂移和评分稳定性。
- 检查 outcome labels，但不把后验表现当成模型输入。
- 修订标注协议、reason_tags 和复标计划。
- 归档报告，保留能解释判断边界变化的样本截图或备注。

## 完成标准

一个研究周期完成，不是因为模型分数提高，而是因为以下内容能被复查：

- 数据版本明确。
- 标注边界明确。
- 输入特征没有未来函数。
- outcome labels 单独保存。
- 时间切分可复现。
- review queue 没被当成交易建议。
- 实验 manifest 和报告能解释本次研究怎么做、有哪些风险、哪些结论不能外推。
