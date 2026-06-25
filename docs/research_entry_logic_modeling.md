# 用户开仓逻辑建模研究说明

本文记录 Quant Replay Collector 当前的 entry logic research 边界和使用方式。这个功能学习的是用户在深 V 反转做多场景中的开仓判断边界，不预测未来收益，不生成自动交易指令。

## 研究边界

entry logic research 服务于复盘和样本研究。它把用户的主观开仓判断拆成可保存、可复查、可导出的结构化对象：

- 候选 observation：宽松筛出值得人工查看的位置，不代表可以开仓。
- 人工标签：`human_decision`，不是 `future_return`。
- 决策时特征：只使用当时可见的 OHLCV 和滚动上下文。
- 后验标签：未来收益、MFE、MAE、止盈止损触发等字段单独保存，只用于报告和风险诊断。

允许对外呈现的研究分数是 `entry_logic_score`、`human_entry_similarity` 和 `setup_confidence`。PU 原型模块内部还会返回 `pu_entry_score` 方便评估排序，但报告和导出必须说明它只是相似度研究分数。任何分数都不得写成 `buy_signal`、买入信号、下单建议或未来收益判断。

本功能不接 Binance 实盘 API，不新增自动交易，不改回测下单逻辑。SQLite 只追加 `entry_annotations` 表，旧 session 和旧导出继续兼容。

## 术语

`human_decision` 有四个取值：

- `ENTRY`：用户在该决策时点会考虑开多，或历史样本中确实执行了对应开多动作。
- `REJECT`：用户明确认为该 setup 不该开仓。
- `UNCERTAIN`：信息不足、场景混杂，用户暂时不能判断。
- `UNLABELED`：尚未人工确认。未开仓、未入选或未复标样本不能自动当成负样本。

`decision_timing` 记录判断发生在当前 K 线收盘，还是下一根确认 K 线之后。默认不能读取 observation 之后的数据；只有 `NEXT_BAR_CONFIRMATION` 明确标记后，后续模块才能按确认时点解释。

## 已落地模块

`quant_collector_app/research/entry_annotations.py` 定义 `HumanDecision`、`DecisionTiming`、`EntryAnnotation` 和校验规则。它拒绝 `buy`、`sell`、`signal` 类命名，也拒绝把 `future_return`、`MFE`、`MAE`、`hit_tp`、`hit_sl` 放进 annotation。

`quant_collector_app/research/entry_observation_universe.py` 从 K 线生成宽松候选 observation。候选规则关注前序下跌、range、成交量、下影线等可见结构，只做筛选，不做交易建议。

`quant_collector_app/research/entry_context_features.py` 生成决策时可见特征，例如 prior return、趋势斜率、下跌结构、影线比例、成交量 z-score、波动和 ATR 比例。它不输出 future、fwd、MFE、MAE、hit_tp、hit_sl、pnl、profit、win 或交易信号字段。

`quant_collector_app/research/entry_outcome_labels.py` 生成后验 outcome labels，例如 `fwd_ret_*`、`mfe_10`、`mae_10`、`hit_tp_10`、`hit_sl_10`。这些字段不得作为 entry logic model 输入。

`quant_collector_app/research/temporal_validation.py` 提供 chronological split、walk-forward split、purge 和 embargo。金融时间序列不允许随机切分。

`quant_collector_app/time_series_analysis/entry_distribution_diagnostics.py` 输出 skewness、excess kurtosis、quantiles、tail concentration、ENTRY/REJECT 分布对比和按月漂移诊断。

`quant_collector_app/research/entry_logic_scoring.py` 用 ENTRY 样本的 median / IQR 原型给候选样本计算 `human_entry_similarity` 和 `setup_confidence`。它学习“像不像用户会开的 ENTRY”，不是收益预测。

`quant_collector_app/research/pu_entry_learning.py` 用轻量 Positive-Unlabeled 思路在 ENTRY 和 UNLABELED 之间做排序。REJECT 只能用于 holdout 评估或阈值参考，不会把所有 UNLABELED 当负样本。

`quant_collector_app/research/active_label_selection.py` 生成复标队列：高相似、边界不确定或形态更分散的 UNLABELED 候选优先给用户复核。

`quant_collector_app/research/entry_experiment_registry.py` 保存实验 manifest：参数、数据范围、feature_cols、split 方案、模型类型、指标、报告路径和 warning。它用于复现研究，不是上线模型注册表。

`quant_collector_app/research/entry_logic_report.py` 生成 Markdown / JSON 报告，包含标注概览、特征分布、ENTRY vs REJECT 差异、相似度摘要、review queue、时间切分和泄漏检查。

## 数据流

```text
OHLCV
  -> entry_observation_universe
  -> entry_annotations(human_decision)
  -> entry_context_features
  -> temporal_validation
  -> entry_logic_scoring / pu_entry_learning
  -> active_label_selection
  -> entry_logic_report

OHLCV + observation_universe
  -> entry_outcome_labels
  -> post-hoc report diagnostics only
```

核心规则：context features 和 outcome labels 物理隔离。任何包含 `future_return`、`fwd_ret`、`MFE`、`MAE`、`hit_tp`、`hit_sl`、`pnl`、`profit`、`win` 的字段都不能进入 entry logic scoring 输入。

## 时间序列切分

chronological split 按时间顺序切分 train / validation / test。walk-forward split 用滚动训练窗口和后续验证/测试窗口模拟研究迭代。

`purge` 移除训练和测试边界附近会共享未来标签窗口的样本。`embargo` 在边界后留出隔离区，降低相邻样本污染。这样做不能保证未来表现，只是减少评估泄漏。

## 半监督和主动学习

半监督阶段只用 pandas / numpy。当前实现先用人工 `ENTRY` 估计原型，再对 `UNLABELED` 候选计算相似度。PU 模块估计正例先验和正例密度排序，但不把未开仓或未标注样本直接当负样本。

active learning 的作用是减少人工复标成本：

- `high_similarity`：优先找最像 ENTRY 的 UNLABELED。
- `uncertain`：优先找分数在中间区间、最需要人工判断的样本。
- `diverse`：优先覆盖不同候选形态，避免重复标同一类行情。

这些队列只说明“值得复核”，不是开仓提示。

## 导出和报告

普通 session 导出会保留旧 CSV / JSON / Markdown / Parquet 文件，并可追加 entry logic research 文件：

- `entry_annotations.csv`
- `entry_observation_universe.csv`
- `entry_context_features.csv`
- `entry_outcome_labels.csv`
- `entry_logic_scores.csv`
- `entry_review_queue.csv`
- `entry_logic_report.md`
- `entry_logic_report.json`

`data_dictionary.md` 会说明 `entry_context_features` 是模型输入候选，`entry_outcome_labels` 不得作为模型输入。没有 entry logic 数据时，导出空表和带 warning 的报告，不应让旧导出失败。

在 UI 中，数据分析页的 `Entry Logic Research` tab 只提供最小入口：生成报告、加载标注数量和 top-k review queue、导出 Markdown / JSON。耗时任务走现有后台导出任务，不阻塞主线程，也不接交易按钮。

## 测试

核心验证命令：

```powershell
python -m compileall -q quant_collector_app tests
python -m pytest -q
```

entry logic 相关重点测试：

```powershell
python -m pytest -q tests/test_entry_annotations.py
python -m pytest -q tests/test_entry_observation_universe.py
python -m pytest -q tests/test_entry_context_features.py
python -m pytest -q tests/test_entry_outcome_labels.py
python -m pytest -q tests/test_temporal_validation.py
python -m pytest -q tests/test_entry_logic_scoring.py
python -m pytest -q tests/test_pu_entry_learning.py
python -m pytest -q tests/test_active_label_selection.py
python -m pytest -q tests/test_entry_logic_report.py
python -m pytest -q tests/test_exporter_entry_logic.py
python -m pytest -q tests/test_storage_entry_annotations.py
python -m pytest -q tests/test_entry_logic_research_pipeline.py
```

发布前还要运行：

```powershell
python scripts/clean_release.py --output dist/QuantReplayCollector-v1.4.1-Clean
python scripts/check_release_clean.py dist/QuantReplayCollector-v1.4.1-Clean
```

## 风险声明

entry logic research 的输出不是交易信号，不构成投资建议，不证明策略盈利。样本内相似度、后验收益分布、review queue 和实验报告只能用于复盘、标注效率和研究诊断。任何实盘决策都不应由本模块自动触发。
