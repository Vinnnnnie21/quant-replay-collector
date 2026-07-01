# Quant Replay Collector / 量化回放采集器

Quant Replay Collector is a Windows desktop research tool for replaying crypto K-line data and turning discretionary chart observations into structured, auditable, exportable research samples. It is built for review, annotation and research, not live execution. It does not connect to Binance order APIs, place trades, or provide investment advice.

Quant Replay Collector 是一个 Windows 桌面研究工具，用来回放加密货币 K 线，并把主观看盘判断整理成可记录、可审计、可导出的研究样本。它服务于复盘、标注和研究，不是实盘交易系统；它不连接 Binance 下单 API，不自动下单，也不提供投资建议。

## Screenshots / 截图

The screenshots below show the main replay workspace, the research analysis workspace and the strategy consistency panel. Replace these files when the UI changes so the GitHub project page reflects the current product.

下面的截图展示主回放工作区、研究分析工作区和策略一致性面板。界面变化后，直接替换这些图片文件，GitHub 首页就会显示新的项目状态。

![Main replay workspace / 主回放工作区](docs/screenshots/main_ui.png)

![Research analysis workspace / 研究分析工作区](docs/screenshots/analysis_workspace.png)

![Strategy consistency panel / 策略一致性面板](docs/screenshots/strategy_consistency.png)

## What It Does / 项目能做什么

Quant Replay Collector supports bar-by-bar market replay, manual trade and event annotation, decision-time feature extraction, post-event outcome labeling, research artifact export, event studies, factor checks, time-series diagnostics, research-only backtests and strategy-consistency review. Its purpose is to make subjective trading behavior observable and testable, not to turn research output into live orders.

Quant Replay Collector 支持逐根 K 线回放、人工交易和事件标注、决策时特征提取、后验结果标签隔离、研究文件导出、事件研究、因子检查、时间序列诊断、研究型回测和策略一致性审计。它的目标是让主观交易行为变得可观察、可复查、可测试，而不是把研究结果直接变成实盘下单。

## Current Scope / 当前范围

Current version: `1.4.1`. SQLite schema: `6`. The desktop stack is PySide6, pyqtgraph, pandas and numpy. The primary runtime environment is Windows PowerShell. Local runtime data is stored under `quant_collector_app/data/`, `quant_collector_app/logs/` and cache/export directories. Exported statistics, scores and reports are research evidence only.

当前版本是 `1.4.1`，SQLite schema 是 `6`。桌面技术栈是 PySide6、pyqtgraph、pandas 和 numpy。主要运行环境是 Windows PowerShell。本地运行数据保存在 `quant_collector_app/data/`、`quant_collector_app/logs/` 以及缓存和导出目录。导出的统计、分数和报告只能作为研究证据。

## Install / 安装

Create a virtual environment from the repository root and install the declared dependencies. If `.venv` already exists, rerun only the final install command.

在仓库根目录创建虚拟环境并安装依赖。如果 `.venv` 已经存在，只需要重新执行最后一条安装命令。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run / 运行

Launch the desktop app from the repository root. The package entry point is equivalent and is useful when you want to verify the installed package path.

从仓库根目录启动桌面应用。包入口和 `run_app.py` 等价，适合用来确认包路径和依赖环境是否正常。

```powershell
.\.venv\Scripts\python.exe run_app.py
.\.venv\Scripts\python.exe -m quant_collector_app
```

## Research Workflow / 研究流程

A typical research pass starts with replay and annotation, then extracts decision-time features, keeps post-event outcome labels physically separate, and finally runs analysis, export, backtesting and consistency review. Research models may only use data visible at the decision point. Forward returns, MFE, MAE, win/loss and stop/take outcomes are for audit and reporting only.

典型研究流程是先回放和标注，再提取决策时可见特征，把后验结果标签单独隔离，最后做分析、导出、回测和一致性检查。研究模型只能使用决策点之前已经可见的数据。未来收益、MFE、MAE、胜负和止盈止损结果只能用于审计和报告。

```text
load/replay K-lines
  -> mark trades, events and observations
  -> extract decision-time context features
  -> keep post-event outcome labels separate
  -> analyze, export, backtest and review consistency
```

```text
加载/回放 K 线
  -> 标记交易、事件和观察点
  -> 提取决策时可见特征
  -> 隔离后验结果标签
  -> 分析、导出、回测并检查一致性
```

## Entry Logic Research / 开仓逻辑研究

Entry Logic Research studies the user's long-entry judgment boundary in deep-V reversal setups. The supervised label is `human_decision`, not future return. `ENTRY` means the user would consider a long entry, `REJECT` means the user rejects the setup, `UNCERTAIN` means the setup is unclear, and `UNLABELED` means the candidate has not been reviewed. Scores such as `human_entry_similarity` and `setup_confidence` are review-prioritization signals, not trading instructions.

Entry Logic Research 研究的是用户在深 V 反转做多场景中的开仓判断边界。监督标签是 `human_decision`，不是未来收益。`ENTRY` 表示用户会考虑开多，`REJECT` 表示用户拒绝该 setup，`UNCERTAIN` 表示结构不清晰，`UNLABELED` 表示候选点尚未复核。`human_entry_similarity` 和 `setup_confidence` 这类分数只用于排序复核优先级，不是交易指令。

## Validate / 验证

Run validation through the project virtual environment so the checks use the same dependencies as the desktop app. `verify_before_push.bat` runs the local pre-push release gate.

使用项目虚拟环境运行验证，避免误用缺少依赖的系统 Python。`verify_before_push.bat` 会运行发布前的本地门禁。

```powershell
.\.venv\Scripts\python.exe -m compileall -q quant_collector_app tests
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m quant_collector_app.self_check --core
.\.venv\Scripts\python.exe scripts\clean_release.py --output dist\QuantReplayCollector-CI
.\.venv\Scripts\python.exe scripts\check_release_clean.py dist\QuantReplayCollector-CI
```

## Clean Release Policy / 干净发布策略

`scripts/clean_release.py` builds a public source package and excludes local runtime state: virtual environments, previous `dist/` output, local SQLite databases, logs, caches, exports, settings, Python cache directories, backup folders, local agent workflow files and performance-report directories. The generated directory includes `clean_release_report.json` and `clean_release_report.md`; run `scripts/check_release_clean.py` on that directory before uploading any release artifact.

`scripts/clean_release.py` 会生成公开源码包，并排除本地运行状态：虚拟环境、旧 `dist/` 输出、本地 SQLite 数据库、日志、缓存、导出文件、本地设置、Python 缓存目录、备份目录、本地 agent 工作流文件和性能报告目录。生成目录会包含 `clean_release_report.json` 和 `clean_release_report.md`；上传任何发布包之前，都要先对生成目录运行 `scripts/check_release_clean.py`。

## Project Layout / 项目结构

The main source code lives under `quant_collector_app/`. UI widgets and presentation helpers live under `quant_collector_app/views/`. Research modules live under `quant_collector_app/research/`, research-only backtesting lives under `quant_collector_app/backtesting/`, SQLite migrations and repositories live under `quant_collector_app/storage_core/`, release and diagnostic tooling lives under `scripts/`, tests live under `tests/`, and longer explanations live under `docs/`.

主要源码在 `quant_collector_app/`。UI 组件和展示辅助代码在 `quant_collector_app/views/`。研究模块在 `quant_collector_app/research/`，研究型回测在 `quant_collector_app/backtesting/`，SQLite 迁移和仓储层在 `quant_collector_app/storage_core/`，发布与诊断工具在 `scripts/`，测试在 `tests/`，更完整的说明文档在 `docs/`。

## Documentation / 文档

Read the architecture, backtesting, research workflow, daily research workflow, entry logic research, strategy consistency, testing and release hygiene notes for deeper context.

更深入的项目背景可以阅读架构、回测、研究流程、每日研究流程、开仓逻辑研究、策略一致性、测试和发布卫生文档。

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