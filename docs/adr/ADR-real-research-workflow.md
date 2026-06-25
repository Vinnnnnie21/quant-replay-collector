# ADR: Real Personal Research Workflow

- Status: Accepted
- Date: 2026-06-20
- Scope: research operating model and documentation only

## Context

Quant Replay Collector 不再以 GitHub 展示为主要目标。新的主目标是用户本人长期研究自己的深 V 反转做多开仓逻辑。

现有系统已经具备回放、交易记录、标注、导出、回测、分析、SQLite 兼容和 entry logic research 模块。下一步不该把它改成自动交易工具，也不该把研究评分包装成预测买点。

真实问题是：用户在什么样的市场结构下会判断“这里可以考虑开多”，这个判断边界能不能被保存、复查、统计诊断、半监督复标，并在长期使用中逐步稳定下来。

## Decision

Quant Replay Collector 的研究路线改为个人长期统计学习工作流。

entry logic research 继续作为研究层，不成为交易层。模型标签仍是 `human_decision`，不是 `future_return`。公开报告和导出中允许的分数字段是 `entry_logic_score`、`human_entry_similarity` 和 `setup_confidence`。内部 PU 排序可使用 `pu_entry_score`，但必须写明它只是相似度研究分数。

`buy_signal`、`sell_signal`、自动下单、实盘交易 API 和把 review queue 当开仓列表，都不属于本路线。

## Preserved System

本 ADR 不要求删除或重写任何旧模块。

保留：

- replay 和交易记录流程
- 现有人工标注与导出
- `research/`
- `analysis/`
- `backtesting/`
- `time_series_analysis/`
- `strategy_consistency/`
- `exporter.py`
- `dataset_builder.py`
- `storage.py`
- `api_server.py`
- SQLite 旧 session 兼容
- 现有 tests
- 已实现的 entry logic research 模块

`main_app.py` 不做大规模拆分。UI 后续只接最小研究入口或报告入口，耗时任务继续走 worker。

## Workflow Contract

一次完整研究流程按这个顺序组织：

1. 下载或更新历史 K 线数据，只作为本地研究数据。
2. 回放行情，按当时可见信息观察。
3. 用 observation universe 宽松筛候选。
4. 用户人工标注 `ENTRY`、`REJECT`、`UNCERTAIN` 或保留 `UNLABELED`。
5. 用 active learning 复标高相似、边界不确定或形态分散的候选。
6. 生成 context features。
7. 单独生成 outcome labels。
8. 用 chronological split 或 walk-forward split 划分样本。
9. 应用 purge 和 embargo。
10. 做分布、厚尾、自相关和漂移诊断。
11. 用 prototype / PU scoring 给 `UNLABELED` 候选排序。
12. 保存实验 manifest。
13. 导出 Markdown / JSON 报告并复盘。

这个顺序不是为了证明策略能赚钱，而是为了让人工判断边界可复现。

## Label Semantics

`ENTRY`：用户在决策点会考虑开多。

`REJECT`：用户明确认为这个 setup 不该开仓。

`UNCERTAIN`：用户认为信息不足，暂时不能做明确判断。

`UNLABELED`：候选还没有被人工确认。它不是负样本，也不是 `REJECT`。

`human_decision` 是人的判断标签。它不能由未来收益自动生成，也不能由是否开仓自动推断。

## Bar Index Semantics

`setup_bar_index` 是形态锚点。它标记深 V 候选结构出现的位置，例如放量下跌结束 K 线、长下影 K 线或反转结构核心 K 线。

`decision_bar_index` 是决策时最后可见的 K 线。模型输入只能读到这里。

当 `decision_timing == CURRENT_BAR_CLOSE`，两者通常相同。当 `decision_timing == NEXT_BAR_CONFIRMATION`，用户等待下一根确认 K 线，`decision_bar_index` 可以晚于 `setup_bar_index`。

任何特征工程都必须以 `decision_bar_index` 作为可见信息边界。`setup_bar_index` 不能被用来读取确认 K 线之后的数据。

## Feature And Outcome Boundary

`context features` 是模型输入候选，只能使用决策时可见数据。它们描述结构、趋势、成交量、波动和位置。

`outcome labels` 是后验诊断字段，只能用于报告、风险诊断和结果对照。它们可以包含未来收益、MFE、MAE、TP/SL 命中和路径结果，但不能进入 scoring 输入。

如果 `fwd_ret`、`future_return`、`MFE`、`MAE`、`hit_tp`、`hit_sl`、`pnl`、`profit` 或 `win` 出现在 context features 或评分输入中，本次实验无效。

## Temporal Validation

金融时间序列不能随机切分。随机切分会破坏时间顺序，把同一行情阶段的相邻样本分到训练和测试里，还可能让重叠 outcome window 泄漏。

本路线只接受：

- chronological split
- walk-forward split
- purge
- embargo

purge 处理重叠标签窗口。embargo 处理切分边界后的近邻污染。两者是防泄漏措施，不是未来收益保证。

## Semi-Supervised Scope

半监督学习只用于候选排序和复标辅助。

ENTRY prototype 和 PU ranking 的问题是：哪些 `UNLABELED` 候选更像用户历史上会标成 `ENTRY` 的样本。它不回答未来会不会涨，也不回答是否应该下单。

`REJECT` 可以用于 holdout 评估、阈值参考或诊断，但不能把全部 `UNLABELED` 当负样本训练。

当前实现保持轻量，只使用 pandas / numpy。sklearn、torch、tensorflow、xgboost 不进入本阶段。

## Experiment Reproducibility

每次实验必须保存 manifest。manifest 至少记录：

- 实验 id、创建时间、应用版本
- symbol、interval、data_start、data_end
- 数据来源、缓存版本或 hash
- observation universe 参数
- annotation_version 和各类 `human_decision` 数量
- feature_version、feature_cols、lookback windows
- outcome horizon、TP/SL 假设和末尾 horizon 不足处理
- split_method、时间窗口、purge_bars、embargo_bars
- model_type 和 model_params
- scoring 摘要、诊断指标和 warning
- report、scores、review queue、data dictionary 等 artifact paths

没有 manifest 的实验不能作为长期研究依据。

## Non-Evidence

这些结果不能直接宣传为策略有效性证明：

- 样本内高分
- review queue 排名
- ENTRY 样本历史收益较好
- 单次回测结果
- 某个特征在 ENTRY / REJECT 间差异明显
- 小样本 precision@k
- 未做 purge / embargo 的评估
- 用户记忆中的少数成功案例

它们只说明“值得继续查”，不说明“未来会赚钱”。

## Consequences

好处：

- 研究目标更贴近日常真实使用。
- 标注、特征、结果、切分、评分和报告的边界更清楚。
- 长期数据积累后，可以复查用户判断边界是否稳定。
- 后续 UI 扩展可以围绕报告和复标队列做小步迭代。

代价：

- 短期不会产生“自动买点”这类展示效果。
- 用户需要持续标注和复标。
- 小样本阶段很多统计结果只能作为提示，不能外推。

## Deferred Work

后续实施阶段按这个顺序推进：

1. 把日常报告入口做得更顺手，但不重做 UI。
2. 给 `setup_bar_index` / `decision_bar_index` 增加统一字段约定和兼容迁移方案。
3. 做标注质量面板：标签数量、冲突样本、长期 `UNCERTAIN`、reason_tags 分布。
4. 扩展实验 registry，保存更完整的数据版本和 artifact 索引。
5. 增加月度研究报告模板。
6. 做 episode-aware grouping，减少同一行情段重复样本对评估的影响。
7. 只在边界稳定后，再考虑更复杂的统计模型。重依赖仍需单独 ADR。
