# Quant Replay Collector / 量化回放采集器

Quant Replay Collector is a local Windows desktop research system for replaying crypto K-line data and turning discretionary chart-reading decisions into structured research samples. It is designed for review, annotation, dataset building and strategy research. It is not a live trading system, does not connect to Binance order APIs, does not place orders and does not provide investment advice.

Quant Replay Collector 是一个本地 Windows 桌面研究系统，用来回放加密货币 K 线，并把主观看盘决策整理成结构化研究样本。它面向复盘、标注、数据集构建和策略研究，不是实盘交易系统；它不连接 Binance 下单 API，不自动下单，也不提供投资建议。

## What The Project Can Do / 项目能做什么

The app lets you replay market data bar by bar, pause at important candles, record manual open/close decisions, attach event tags and write notes. This keeps the original discretionary decision close to the chart context where it happened, instead of turning it into a vague after-the-fact memory.

应用可以逐根回放市场 K 线，在关键 K 线处暂停，记录人工开仓和平仓决策，添加事件标签并写备注。这样做能把主观决策保留在它真实发生的图表上下文里，而不是事后只剩下模糊印象。

It turns replay observations into research artifacts: event windows, decision-time context features, post-event outcome labels, performance summaries, event-study tables, time-series diagnostics, backtest results and strategy-consistency reports. These exports are meant to help you study whether a repeated visual setup has stable behavior, enough samples and a clean research boundary.

它会把回放观察整理成研究文件：事件窗口、决策时特征、后验结果标签、绩效摘要、事件研究表、时间序列诊断、回测结果和策略一致性报告。这些导出内容用于研究一个反复出现的图形 setup 是否有稳定行为、样本量是否足够、研究边界是否干净。

It also provides a research-only backtesting path. Backtests use historical bars and declared strategy parameters to compare rule behavior with manual samples. They are diagnostic simulations, not trading recommendations, and their assumptions about fill timing, fees, slippage and holding rules must be reviewed before interpreting results.

项目也提供研究型回测路径。回测使用历史 K 线和声明好的策略参数，把规则行为和人工样本进行对比。它只是诊断性模拟，不是交易建议；成交时点、手续费、滑点和持仓规则这些假设，都需要在解读结果前先检查清楚。

## Research Method / 研究方法

The core research idea is simple: first record what the trader actually saw and decided, then extract only the information that was visible at that decision point, and only then compare the later outcome. This prevents future information from leaking into the input features and makes the exported dataset usable for later rule mining, event studies and model experiments.

核心研究思路很直接：先记录交易者当时看到了什么、做了什么判断；再只提取决策点之前已经可见的信息；最后再单独比较后续结果。这样可以避免把未来信息混进输入特征里，让导出的数据集能继续用于规则挖掘、事件研究和模型实验。

```text
replay K-lines
  -> mark manual decisions and chart events
  -> extract decision-time context features
  -> store post-event outcome labels separately
  -> audit data quality and leakage risk
  -> run event studies, backtests and consistency review
```

```text
回放 K 线
  -> 标记人工决策和图表事件
  -> 提取决策时可见特征
  -> 单独保存后验结果标签
  -> 审计数据质量和未来函数风险
  -> 运行事件研究、回测和一致性检查
```

## Entry Logic Research / 开仓逻辑研究

Entry Logic Research focuses on one narrower question: what does the user's long-entry judgment boundary look like in deep-V reversal setups? The supervised label is `human_decision`, not future return. `ENTRY` means the user would consider a long entry, `REJECT` means the setup is rejected, `UNCERTAIN` means the structure is unclear, and `UNLABELED` means the candidate still needs review.

开仓逻辑研究只关注一个更窄的问题：用户在深 V 反转做多场景里的开仓判断边界到底长什么样？监督标签是 `human_decision`，不是未来收益。`ENTRY` 表示用户会考虑开多，`REJECT` 表示拒绝该 setup，`UNCERTAIN` 表示结构不清晰，`UNLABELED` 表示候选点还没有复核。

Scores such as `human_entry_similarity` and `setup_confidence` are used to prioritize review and compare candidate setups with known manual decisions. They do not predict expected return, do not create buy/sell signals and should not be wired into live order execution.

`human_entry_similarity` 和 `setup_confidence` 这类分数只用于安排复核优先级，或者把候选 setup 和已有人工决策做相似度比较。它们不预测期望收益，不生成买卖信号，也不应该接入实盘下单。

## Research Boundaries / 研究边界

Input features and outcome labels are physically separated. Decision-time features may use only current and historical OHLCV/context data. Forward returns, MFE, MAE, win/loss, manual final outcome, stop/take results and post-event windows belong to labels, reports or audits, not to model inputs.

输入特征和结果标签是物理隔离的。决策时特征只能使用当前和历史 OHLCV 及上下文数据。未来收益、MFE、MAE、胜负、人工最终结果、止盈止损结果和事件后的窗口数据，只能进入标签、报告或审计，不能进入模型输入。

This boundary is the main reason the project is useful: it preserves the trader's subjective judgment while still making the later analysis reproducible. If a rule looks good only because future data leaked into the input, it is not a research finding.

这个边界是项目有用的关键：它保留了交易者的主观判断，同时让后续分析可以复现。如果一条规则看起来有效只是因为未来数据混进了输入，那就不是有效研究结论。

## Screenshots / 截图

The screenshots below show the main replay workspace, the research analysis workspace and the strategy consistency panel.

下面的截图展示主回放工作区、研究分析工作区和策略一致性面板。

![Main replay workspace / 主回放工作区](docs/screenshots/main_ui.png)

![Research analysis workspace / 研究分析工作区](docs/screenshots/analysis_workspace.png)

![Strategy consistency panel / 策略一致性面板](docs/screenshots/strategy_consistency.png)

## Install And Run / 安装和运行

Use the project virtual environment from the repository root. The root `requirements.txt` points to the application dependency list.

在仓库根目录使用项目虚拟环境。根目录的 `requirements.txt` 会指向应用依赖清单。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_app.py
```

You can also start the package entry point directly.

也可以直接使用包入口启动。

```powershell
.\.venv\Scripts\python.exe -m quant_collector_app
```

## Validate Before Publishing / 发布前验证

Run the same checks through `.venv` before publishing code or release artifacts. The clean release scripts build and inspect a public source package that excludes databases, logs, caches, virtual environments, backup folders, previous `dist/` output and local agent files.

发布代码或发布包之前，用 `.venv` 跑同一套检查。干净发布脚本会生成并检查公开源码包，排除数据库、日志、缓存、虚拟环境、备份目录、旧 `dist/` 输出和本地 agent 文件。

```powershell
.\.venv\Scripts\python.exe -m compileall -q quant_collector_app tests
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m quant_collector_app.self_check --core
.\.venv\Scripts\python.exe scripts\clean_release.py --output dist\QuantReplayCollector-CI
.\.venv\Scripts\python.exe scripts\check_release_clean.py dist\QuantReplayCollector-CI
```

## Project Structure / 项目结构

The main app code lives under `quant_collector_app/`. UI widgets are under `quant_collector_app/views/`. Research modules are under `quant_collector_app/research/`. Research-only backtesting is under `quant_collector_app/backtesting/`. SQLite migrations and repositories are under `quant_collector_app/storage_core/`. Release and diagnostic tools live in `scripts/`, tests live in `tests/`, and long-form documentation lives in `docs/`.

主要应用代码在 `quant_collector_app/`。UI 组件在 `quant_collector_app/views/`。研究模块在 `quant_collector_app/research/`。研究型回测在 `quant_collector_app/backtesting/`。SQLite 迁移和仓储层在 `quant_collector_app/storage_core/`。发布与诊断工具在 `scripts/`，测试在 `tests/`，长文档在 `docs/`。

## Documentation / 文档

Read these documents for implementation details and research methodology.

实现细节和研究方法可以继续阅读这些文档。

- [Architecture](docs/architecture.md) / [架构](docs/architecture.md)
- [Backtesting](docs/backtesting.md) / [回测](docs/backtesting.md)
- [Research workflow](docs/research_workflow.md) / [研究流程](docs/research_workflow.md)
- [Daily research workflow](docs/research_daily_workflow.md) / [每日研究流程](docs/research_daily_workflow.md)
- [Entry logic research](docs/research_entry_logic_modeling.md) / [开仓逻辑研究](docs/research_entry_logic_modeling.md)
- [Strategy consistency](docs/strategy_consistency.md) / [策略一致性](docs/strategy_consistency.md)
- [Testing](docs/testing.md) / [测试](docs/testing.md)
- [Release hygiene](docs/release.md) / [发布卫生](docs/release.md)

## License / 许可证

This project uses the MIT license. See [LICENSE](LICENSE).

本项目使用 MIT 许可证，详见 [LICENSE](LICENSE)。