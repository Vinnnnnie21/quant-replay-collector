# Quant Replay Collector

Quant Replay Collector is a desktop research tool for transforming discretionary chart-based trading observations into structured quantitative research samples.

Many discretionary traders, especially technical-analysis traders, rely on visual patterns such as sharp selloffs, panic wicks, long shadows, volume absorption, breakdown recovery, and reversal candles. These concepts are intuitive to human traders, but difficult to define directly as quantitative rules.

Quant Replay Collector provides a workflow for replaying cryptocurrency K-line data, recording manual trading decisions, tagging subjective chart patterns, extracting event windows, computing structured features, auditing strategy consistency, and exporting research-ready datasets for event studies, backtesting, and machine learning preparation.

The goal is not to claim that a strategy is profitable. The goal is to make subjective trading behavior observable, measurable, auditable, and testable.

> This is a research and replay tool, not a live trading system. Backtest results and AI summaries do not represent investment advice or future performance.

## v1.4.0 Dynamic Timeframe & Research Dataset Release

Version `1.4.0` extends replay research without turning the product into a live trading system:

- Dynamic timeframe switching with timestamp anchoring keeps the main chart near the current market time when changing intervals.
- Display interval and sample interval are separated so existing trade samples are not silently recorded against a different bar index.
- Multi-timeframe read-only context shows higher-timeframe state without changing the primary replay session.
- Research schema supports an observation universe and strategy samples for later behavior analysis.
- Context features and outcome labels are physically separated to reduce future-data leakage risk.
- Matched baseline and behavior model outputs support descriptive comparison against similar observed states.
- Rule validation includes FDR adjustment, purged chronological split, embargo handling and out-of-sample degradation gates.

The tool does not connect to Binance order APIs, does not place live orders and does not provide investment advice.

### Retained Stability Foundations

- Stable launch entry points: `python run_app.py`, `python -m quant_collector_app`, and the existing `cd quant_collector_app && python main_app.py`.
- Versioned SQLite migration using `PRAGMA user_version`, with `PRAGMA foreign_keys=ON` enabled per connection and a five-second busy timeout. This does not assert that every legacy table has a declared foreign-key constraint.
- Persistent market-data provenance and data-quality audit records.
- Reusable Binance Futures market-data HTTP sessions, bounded retry/backoff, cache fallback and cache manifest files.
- Rendering remains throttled for large chart histories.
- Replay, premium sampling and export orchestration retain isolated controller boundaries; the PySide6/pyqtgraph desktop stack is unchanged.

### Data Quality Audit

Every online download or cache load is evaluated before use. The report records expected and actual bars, missing and duplicate bars, invalid OHLC rows, ordering status, time coverage, source and creation time. Rows with impossible OHLC relationships are excluded from the usable frame and recorded as invalid. Downloaded CSV caches receive a sibling `.manifest.json` containing the source and quality report.

Quality results are stored in SQLite and exposed in the application status line with the data source, quality status, sample count and current session identifier.

### SQLite Schema

`StorageManager` upgrades existing local databases in place and does not remove user samples. Schema version `2` adds:

- `klines`, keyed by `(symbol, interval, open_time_utc_ms)`.
- `data_quality_reports`, keyed by `report_id`.

Existing `sessions`, `trades`, `trade_events`, `event_windows`, `event_features`, `account_equity` and `usdt_premium_history` tables remain supported.

Schema version `3` adds read-path indexes for session, symbol, interval, trade and event-time queries. Connections run with WAL mode, `PRAGMA foreign_keys=ON`, normal synchronous mode and a five-second busy timeout. Legacy databases are upgraded conservatively; complete declared foreign-key coverage is not claimed.

### Performance And Stability Diagnostics

The desktop launcher defers export, analysis, backtest and strategy-consistency imports until those tools are opened. The readonly local API is not imported or started by desktop startup. Data exports started from the main window or research page run in a background worker. Large chart histories are reduced to the visible region plus a small margin before plot items are rebuilt.

Run local diagnostics:

```powershell
python scripts/profile_startup.py
python scripts/profile_imports.py
python scripts/profile_runtime.py
```

Reports are written to `performance_reports/`. A missing GUI dependency or unavailable Qt platform is recorded as an explicit failed probe rather than terminating the script without a report.

`python quant_collector_app/self_check.py` now includes runtime directory, SQLite connection and required dependency health checks. Invalid app or theme settings are ignored safely, with a `.broken.json` backup preserved for diagnosis.

### Clean Release

Build a distribution directory without local caches, databases, logs, settings, Python cache directories or backup folders:

```powershell
python scripts/clean_release.py --output dist/QuantReplayCollector-v1.4.0-Clean
python scripts/check_release_clean.py dist/QuantReplayCollector-v1.4.0-Clean
```

The clean directory contains source code, documentation, tests, launcher files and audit reports named `clean_release_report.json` and `clean_release_report.md`. `check_release_clean.py` must pass before a package is uploaded. Local runtime data in the working directory is not deleted. Virtual environments, prior `dist` output, performance reports, databases, cache, exports, logs, local settings and backup folders are not copied.

### Feature And Label Separation

Enhanced features include log returns, realized volatility, ATR-normalised candle measures, volume/range z-scores, previous-range breaks, trend slope, volatility regime and time-of-day bucket. These features use only the event bar and earlier bars.

`feature_registry.csv` documents model-input eligibility and leakage risk. Forward returns, post-event windows, MFE, MAE and manual final outcomes remain label/research-result fields and are excluded from model-input datasets and feature-rule strategy conditions.

### Event Studies And Backtests

Event-study exports group by label, direction and event type. They now provide count, mean, median, standard deviation, quartiles, win rate and bootstrap 95% confidence intervals. Samples below 30 are explicitly marked as small; comparisons across candidate rules carry a multiple-testing warning. Candidate rules are hypotheses, not trading signals.

Backtests support mark-to-market equity, unrealised PnL, maker/taker fee configuration, optional funding cost/rate input, maximum holding bars, short disabling, `on_close` versus `next_open` signal timing, and configurable same-bar stop/take resolution (`stop_first`, `take_first`, `conservative`). Strategies only receive data through the current bar. Backtests are simplified research simulations; fill assumptions, funding timing, liquidity and intrabar ordering can materially change results.

The research workspace displays data audit, event study, factor binning, factor IC, candidate rules, walk-forward validation and the report in separate tables/tabs. It presents generated research output; it does not convert exploratory findings into trading instructions.

### Research Localization And Time-Series Diagnostics

The Research Analysis workspace defaults to Chinese and retains an English mode. Research and time-series reports accept `language="zh_CN"` or `language="en_US"`; CSV and JSON field names remain stable for downstream use.

Research Analysis evaluates annotated events, labels, feature relationships and walk-forward degradation. Time-Series Diagnostics evaluates the market series itself: log-return distribution, Jarque-Bera normality diagnostics, ACF/Ljung-Box checks, volatility clustering proxies, EWMA volatility, VaR/Expected Shortfall, short-interval microstructure proxies and optional multi-symbol PCA factor summaries.

Strategy Consistency v2 is a behavior audit, not a profitability score. Declared long-only or short-only behavior is not penalised for lacking the opposite side. Missing strategy definitions, small closed-trade samples, missing tags, missing risk/exit metadata, failed data quality, or failed leakage audit limit or invalidate the score.

The time-series methodology is limited to explanatory diagnostics commonly used in financial time-series analysis. Diagnostics default to log return; annualized continuous-compounding return is distinct from converted simple annualized return. Ljung-Box is a dependence diagnostic, not a prediction claim. Microstructure results are proxies without tick/order-book data, and PCA factors require multi-symbol return matrices. VaR and Expected Shortfall are risk measures, not return forecasts. Candidate rules are not trading signals.

### Verification

From the repository root, after installing `quant_collector_app/requirements.txt`:

```powershell
$env:PYTHONPATH = ".;quant_collector_app"
python -m compileall quant_collector_app scripts
python -m pytest -q
python quant_collector_app/self_check.py --core
```

See `docs/testing.md` for the full local release-validation command set.

Quant Replay Collector does not connect to Binance order APIs and does not execute live trades. It is a local research tool. Its outputs do not constitute investment advice.

## 项目简介

Quant Replay Collector 是一个面向主观交易策略量化研究的桌面工具，用于将“看图交易”中的主观判断转化为可记录、可统计、可验证的结构化研究样本。

许多主观交易者，尤其是技术分析流派的交易者，经常依赖图像化和经验化判断，例如“大跌后反转”“大涨后回落”“长上影线”“长下影线”“插针”“放量承接”“跌破后收回”等。

这些判断在人工交易中很常见，但很难直接写成量化规则。比如：

- 多大算“大跌”？
- 多长才算“长影线”？
- 什么样的成交量变化才算“放量”？
- 什么样的 K 线结构才算“反转”？
- 哪些主观判断真的和后续收益有关？
- 一个交易者的样本是否来自同一套稳定策略，而不是随机交易？

本工具的目标不是直接生成一个“赚钱策略”，而是提供一个结构化研究流程：

```text
K 线回放
→ 人工交易/事件标注
→ 事件窗口抽取
→ 特征计算
→ 策略一致性审计
→ 事件研究
→ 回测与参数扫描
→ 时间序列诊断
→ 数据导出与 AI 研究摘要
```

## Screenshots

### Main Replay Interface
![Main UI](docs/screenshots/main_ui.png)

### Analysis Workspace
![Analysis Workspace](docs/screenshots/analysis_workspace.png)

### Strategy Consistency Audit
![Strategy Consistency](docs/screenshots/strategy_consistency.png)

## Why This Project

Many discretionary traders, especially those who rely on technical analysis, make decisions based on visual and experience-driven patterns such as “sharp selloff”, “panic wick”, “long lower shadow”, “volume absorption”, or “reversal after breakdown”.

These concepts are common in manual trading, but they are difficult to convert directly into quantitative rules. For example:

- How large is a “sharp drop”?
- How long is a “long wick”?
- What level of volume increase counts as “high volume”?
- Which reversal patterns are actually followed by favorable returns?
- Are the collected trades generated by a consistent strategy, or by random discretionary behavior?

Quant Replay Collector is designed to bridge this gap.

Instead of forcing subjective trading ideas into predefined rules immediately, the tool allows users to replay K-line data, annotate trading events, record labels and notes, extract event windows, compute structured features, audit strategy consistency, and export research-ready datasets.

The core idea is to transform discretionary chart-based observations into structured, testable, and auditable quantitative research samples.

## 为什么做这个项目

传统的 K 线回放工具主要解决“看行情”和“复盘”的问题，但很多主观交易策略真正有价值的部分，并不只是行情本身，而是交易者在特定市场结构下做出的判断。

例如，当交易者说“这里是大跌后的恐慌针，可以考虑反转做多”时，这句话里面包含了多个模糊概念：

- 大跌：跌多少才算大？
- 恐慌针：下影线多长才算有效？
- 放量：成交量相对什么基准放大？
- 反转：是收回关键位置，还是出现特定 K 线结构？
- 做多：是立刻入场，还是等待下一根确认？
- 有效：看未来 3 根、10 根还是 20 根 K 线？

如果这些判断只停留在主观语言中，就很难被验证，也很难转化为稳定策略。

Quant Replay Collector 的设计目标，是让交易者在回放过程中记录自己的真实判断，并把这些判断转化为结构化事件样本。系统会围绕每个事件抽取前后 K 线窗口，计算价格结构、影线比例、成交量变化、波动率、前序收益、未来表现等特征，并进一步做策略一致性审计、事件研究、回测和时间序列分析。

这使得交易者可以逐步回答：

- 我的主观策略是否真的一致？
- 我标注的“大跌”“插针”“长影线”是否有稳定的量化特征？
- 成功样本和失败样本之间是否存在可解释差异？
- 这些特征能否形成候选规则？
- 候选规则在样本外是否仍然有效？
- 当前结论是否可能来自样本偏差、过拟合或未来函数？

因此，本项目更关注研究过程的严谨性，而不是展示一个漂亮但不可靠的收益曲线。

## 核心功能

- Binance 永续合约 K 线加载，支持常见周期，例如 `1m`、`5m`、`15m`、`1h`、`4h`。
- 本地 CSV 缓存，网络刷新失败时可回退到已有缓存。
- K 线回放控制：播放、暂停、单步、跳到末尾、自由缩放/拖动、跟随最新。
- 手动交易训练：开多、开空、平多、平空。
- 模拟成交参数：成交价模式、手续费 bps、滑点 bps、每笔名义金额和初始权益。
- 撤销/重做当前运行期内的交易和标签操作。
- 事件标签和备注记录，例如深 V 反转、长下影、放量、假突破等。
- 事件窗口抽取：默认保存事件前 20 根、事件后 20 根 K 线。
- 事件特征计算：K 线实体、上下影线、波动、成交量比例、前序收益、未来收益标签等。
- SQLite 本地持久化：会话、交易、事件、特征、窗口和 USDT 溢价记录。
- 最近会话恢复和交易记录恢复。
- CSV / Parquet 导出，用于后续量化分析、事件研究、复盘和机器学习样本整理。
- 账户权益曲线和标准绩效统计：净收益、Profit Factor、Expectancy、最大回撤等。
- USDT/CNY P2P 溢价率采样与图表展示。
- Windows 启动脚本和 PyInstaller 打包脚本。

## 技术栈

- Python 3
- PySide6：桌面 GUI
- pyqtgraph：K 线图、成交量图、实时曲线展示
- pandas / numpy：K 线数据处理、特征计算、导出整理
- SQLite：本地持久化存储
- requests：Binance K 线、Binance P2P 和汇率接口请求
- PyInstaller：Windows EXE 打包

## 项目结构

```text
Trading/
├─ README.md
├─ .gitignore
├─ quant_collector_app/
│  ├─ main_app.py            # 主入口、UI、回放、交易操作、会话恢复
│  ├─ market_data/           # HTTP、缓存、清洗、质量审计和数据特征（不依赖 Qt）
│  ├─ views/                 # pyqtgraph 绘图组件与轻量视图辅助
│  ├─ workers/               # K线加载和导出后台任务
│  ├─ services/              # 市场数据、导出与分析任务入口
│  ├─ storage.py             # SQLite 表结构与读写逻辑
│  ├─ exporter.py            # CSV / Parquet 导出
│  ├─ execution.py           # 模拟成交价、手续费、滑点和净收益计算
│  ├─ accounting.py          # 账户权益曲线计算
│  ├─ performance.py         # 绩效统计
│  ├─ event_study.py         # 事件研究汇总
│  ├─ dataset_builder.py     # 机器学习样本拆分和未来函数防护
│  ├─ app_config.py          # 应用配置、路径、主题、API 地址
│  ├─ premium_monitor.py     # USDT 溢价率采样
│  ├─ requirements.txt       # Python 依赖
│  ├─ README.txt             # 简短运行说明
│  ├─ start.bat               # Windows 开发运行脚本
│  ├─ build_windows.bat      # Windows 打包脚本
│  └─ data/                  # 本地数据库、缓存、导出目录（不提交 GitHub）
├─ docs/
│  └─ screenshots/           # 截图占位目录，后续放置界面截图
└─ backup_old/               # 历史版本归档，上传前建议人工检查
```

## 快速开始

### 方式一：Windows 脚本启动

进入 `quant_collector_app/`，双击：

```text
start.bat
```

该脚本会检查运行依赖，缺少依赖时自动执行：

```bash
python -m pip install -r requirements.txt
```

然后启动：

```bash
python main_app.py
```

### 方式二：命令行启动

```bash
cd quant_collector_app
python -m pip install -r requirements.txt
python main_app.py
```

### Windows 打包 EXE

在 Windows 下进入 `quant_collector_app/`，双击：

```text
build_windows.bat
```

脚本会安装依赖并执行 PyInstaller 打包。当前打包目标是单文件窗口程序：

```bash
python -m PyInstaller --noconfirm --clean --onefile --windowed --name QuantReplayCollector --add-data "README.txt;." main_app.py
```

### 测试和自检

在项目根目录运行：

```powershell
$env:PYTHONPATH = ".;quant_collector_app"
python -m compileall quant_collector_app scripts
python -m pytest -q
python quant_collector_app/self_check.py --core
```

## 数据源说明：Binance Futures Kline API

K 线数据来自 Binance Futures Kline API：

```text
https://fapi.binance.com/fapi/v1/klines
```

程序会根据用户选择的交易对、周期和日期范围请求 K 线，并将时间转换为北京时间。当前缓存文件默认保存在：

```text
quant_collector_app/data/cache/
```

缓存目录不会提交到 GitHub。点击“加载/刷新”时，程序会优先尝试联网刷新；如果网络失败且存在同日期缓存，会回退读取本地缓存。

## 本地数据库说明：SQLite

程序使用 SQLite 做本地持久化，默认数据库路径：

```text
quant_collector_app/data/quant_replay.db
```

主要数据表包括：

- `sessions`：回放会话、品种、周期、日期范围、当前进度、速度等。
- `trades`：手动交易记录，包括方向、开仓/平仓时间、代理价格、收益等。
- `trade_events`：开仓/平仓事件、标签和备注。
- `event_windows`：事件前 20 根、事件后 20 根 K 线窗口。
- `event_features`：事件特征和标签字段。
- `usdt_premium_history`：USDT/CNY 溢价采样记录。


## 导出数据说明：CSV / Parquet

点击“一键导出”后，程序会将当前 session 相关数据导出到用户选择的目录。默认导出目录为：

```text
quant_collector_app/data/exports/
```

导出内容包括：

- `trades.csv` / `trades.parquet`：交易记录。
- `trade_events.csv` / `trade_events.parquet`：事件记录和标签。
- `event_windows_long.csv` / `event_windows_long.parquet`：事件窗口长表，默认每个事件保存前 20 根、事件当根、后 20 根，共 41 行。
- `event_features.csv` / `event_features.parquet`：默认建模输入特征，不包含未来收益字段。
- `event_labels.csv` / `event_labels.parquet`：未来收益、MFE/MAE、人工交易结果等标签字段。
- `event_features_full.csv` / `event_features_full.parquet`：完整事件特征数据。
- `event_wide.csv` / `event_wide.parquet`：事件窗口宽表，不包含 `post_*` 未来窗口字段。
- `event_wide_full.csv` / `event_wide_full.parquet`：完整事件窗口宽表。
- `account_equity.csv` / `account_equity.parquet`：基于模拟成交和已平仓交易生成的账户权益曲线。
- `performance_summary.csv` / `performance_summary.json`：交易绩效摘要。
- `event_study_summary.csv` / `event_study_summary.parquet`：按标签、方向和事件类型分组的事件研究结果。
- `ml_features.csv` / `ml_features.parquet`：移除未来收益、MFE/MAE、post 窗口和人工结果后的建模输入候选。
- `ml_labels.csv` / `ml_labels.parquet`：未来收益和人工结果标签。
- `sample_index.csv` / `sample_index.parquet`：样本索引和元信息。
- `usdt_premium_history.csv` / `usdt_premium_history.parquet`：USDT 溢价历史。
- `export_manifest.json`：导出版本、session、品种、周期、行数和文件清单。
- `data_dictionary.md`：导出文件用途和字段说明。

## 快捷键说明

| 快捷键 | 功能 |
| --- | --- |
| `Space` | 播放 / 暂停 |
| `→` | 下一根 K 线 |
| `F` | 开启 / 关闭跟随最新 |
| `B` | 开多 |
| `S` | 开空 |
| `C` | 平多 |
| `X` | 平空 |
| `Ctrl+Z` | 撤销 |
| `Ctrl+Y` | 重做 |
| `E` | 一键导出 |
| `K` | 重置视图 |

在文本输入框、备注框、下拉框等输入控件中，快捷键会被保护，避免打字时误触交易操作。

## 风险声明

本项目仅用于交易训练、行为复盘和量化研究样本整理，不构成任何投资建议。加密货币市场波动较大，任何基于本项目生成的数据、标签、统计或分析结果，都不应被视为买卖建议或收益保证。

## 主观策略量化研究方向

当前项目的核心使用场景是把主观交易判断变成可统计、可复查、可导出的结构化样本。重点研究对象是“大跌后的反转 K 线做多”。

这类策略里的“大跌”“恐慌针”“放量承接”“跌破后收回”“反转 K 线”都不是天然清晰的量化规则。项目不直接假装这些概念已经有标准答案，而是先让用户在回放中人工标注样本，再抽取事件前后 K 线窗口，生成特征和结果标签，最后用统计结果反推可验证边界。

研究流程：

- 人工回放并记录开仓点、观察点、失败点、事件标签和备注。
- 保存事件前 20 根、事件后 20 根 K 线窗口。
- 只用事件前和事件当根 K 线生成输入特征。
- 把未来收益、MFE、MAE、人工交易结果放入标签表，不混入模型输入。
- 通过分箱分析和候选规则挖掘，寻找“主观概念”对应的数值区间。
- 后续再做样本外验证和规则回测。

## 新增分析模块

`quant_collector_app/analysis/` 提供一组可以脱离 UI 单独测试的统计模块：

- `data_audit.py`：审计导出表、样本量、重复 `event_id`、缺失值、标签完整性和未来函数泄漏风险。
- `feature_engineering.py`：生成 `enhanced_event_features`，围绕大跌、下影线、收回前低、放量和承接构建可解释特征。
- `label_builder.py`：从未来收益、MFE、MAE 构建策略研究标签，例如强反弹、失败反转、好交易、坏交易。
- `binning.py`：按特征分箱统计标签表现，帮助寻找量化边界。
- `rule_mining.py`：生成不超过两条件的候选规则。它只输出待验证假设，不输出交易信号。
- `report_writer.py`：生成 `strategy_research_report.md`，包含数据质量、事件研究、分箱结果、候选规则和风险声明。
- `llm_context.py`：为本地大模型或外部分析脚本生成压缩摘要上下文，不暴露完整数据库和完整 K 线。

导出时会新增这些研究文件：

- `analysis_audit.json`
- `analysis_audit.md`
- `enhanced_event_features.csv`
- `strategy_labels.csv`
- `feature_binning_summary.csv`
- `feature_binning_summary.json`
- `candidate_rules.csv`
- `candidate_rules.json`
- `strategy_research_report.md`

## 未来函数隔离

后续做机器学习或规则研究时，必须严格区分输入和结果。

不能进入 `ml_features.csv` 的字段包括：

- `post_*`
- `fwd_*`
- `mfe_10`
- `mae_10`
- `manual_trade_final_return_pct`
- `manual_trade_holding_bars`

这些字段只能出现在标签、复盘或研究报告中。把结果字段混进输入会造成未来函数污染，统计结果会失真。

## 本地只读 API

项目提供 `api_server.py`，用于给本地脚本、浏览器调试或本地大模型读取压缩后的分析摘要。

启动方式：

```bash
cd quant_collector_app
python api_server.py
```

默认地址：

```text
http://127.0.0.1:8765
```

主要端点：

- `GET /health`
- `GET /api/sessions`
- `GET /api/session/{session_id}/summary`
- `GET /api/session/{session_id}/llm-context`
- `POST /api/session/{session_id}/llm-analysis/mock`

安全边界：

- 只绑定 `127.0.0.1`。
- 只读接口。
- 不执行用户传入 SQL。
- 不修改数据库。
- 不返回数据库绝对路径。
- 不要暴露到公网。

## LLM 接入说明

`llm_client.py` 提供可选分析接口，默认 provider 是 `mock`，不会调用外部模型。

支持 provider：

- `mock`
- `openai`
- `custom_http`

真实外部调用默认关闭。需要外部模型时，应通过环境变量提供密钥，例如 `OPENAI_API_KEY` 或 `CUSTOM_LLM_API_KEY`。不要把密钥写进代码、README、日志或数据库。

大模型只能做这些事：

- 总结统计结果。
- 解释候选规则为什么值得继续验证。
- 指出样本量不足、选择偏差和未来函数风险。
- 提出下一步数据收集建议。

大模型不能做这些事：

- 给实时买卖建议。
- 保证盈利。
- 把样本内统计说成未来确定收益。
- 生成实盘下单指令。
- 直接读取完整 SQLite。
- 执行 SQL。
- 修改交易、事件、标签或数据库。

## 后续研究 Roadmap

- 增加“观察事件”和“失败事件”标注，补齐负样本。
- 做时间序列样本外验证，避免只在样本内挑规则。
- 增加规则回测模块，但仍然不接实盘下单。
- 输出更严格的数据质量报告。
- 增加多品种、多周期对比分析。

## 交易分析指标说明

项目新增 `analytics/` 模块，用于分析人工回放交易和回测交易。指标包括：

- 胜率、亏损率、平均收益、中位数收益、最大单笔盈利、最大单笔亏损。
- Profit Factor、Payoff Ratio、Expectancy、连续盈利/连续亏损。
- 权益曲线、总收益、最大回撤、Recovery Factor。
- Trade Sharpe、Trade Sortino、VaR、CVaR。
- LONG / SHORT 分方向统计。

如果只有交易级收益，只计算 `trade_sharpe`。只有存在连续权益曲线和 bar 周期时，才计算 `time_sharpe`。加密货币是 24/7 市场，年化周期按 K 线周期推断，不使用股票市场 252 交易日口径。

## 回测模块说明

项目新增 `backtesting/` 模块。它用于把研究得到的候选规则放进 K 线数据中做离线验证。

当前支持：

- `MovingAverageCrossStrategy`
- `FeatureRuleLongStrategy`
- 手续费 `fee_bps`
- 滑点 `slippage_bps`
- 成交价模式 `fill_mode`
- 名义金额 `notional_quote`
- 单仓位回测
- 强制最后平仓
- 回测结果导出

回测逐 bar 执行，策略每次只能看到当前 bar 和历史 bar。禁止使用 `fwd_*`、`post_*`、`mfe`、`mae`、`manual_trade_final` 等未来/结果字段。

## 参数扫描和样本外验证

`backtesting/optimization.py` 提供：

- `time_series_split`
- `grid_search`
- `walk_forward_grid_search`

切分方式只按时间顺序，不随机打乱。流程是：

- train：跑参数扫描。
- validation：选择候选参数。
- test：只评估一次。

不能用 test set 调参。样本内最优参数不代表真实有效策略。

## 回测限制和风险

- 无订单簿。
- 无部分成交。
- 滑点是简化模型。
- K 线级成交不等于真实成交。
- 回测收益不代表实盘收益。
- 参数扫描容易过拟合。
- 候选规则只是研究假设，不是交易建议。
## 策略一致性验证

`strategy_consistency` v2 衡量交易行为是否符合一套已声明、可重复、可审计的规则。它不是盈利评分，也不是多空覆盖评分。

`StrategyProfile` 可声明允许方向、入场标签、风险约束、持仓/退出约束及适用品种和周期。声明 `allowed_sides=["LONG"]` 后只做多不会扣方向分；未声明方向时，单边集中只产生观察性 warning，不获得高奖励。

评分由样本充分性、策略定义完整度、入场标签、方向纪律、入场设置、风险执行、退出纪律、行为稳定性和数据质量组成。没有策略档案、样本太少、缺少标签/风险/退出元数据或数据质量失败会限制最高分；未来函数审计失败时评分无效。

只做多/只做空不是一致性问题。只有当策略声明要求双向交易时，方向覆盖不足才是问题。

导出目录会新增：

- `strategy_consistency.json`
- `strategy_consistency_report.md`

说明：一致性审计与研究分析界面支持中英文切换；研究报告和时间序列报告均可按 `zh_CN` 或 `en_US` 生成。

详细说明见 `docs/strategy_consistency.md`。

## 时间序列分析与市场状态诊断

`time_series_analysis/` 诊断行情序列本身，与标注事件的 Research Analysis 分开。默认采用 log return，输出分布/厚尾、Jarque-Bera、ACF/Ljung-Box、波动聚集 proxy、EWMA 波动率、VaR/ES、短周期微观结构 proxy 和可选多品种 PCA 因子摘要。

当前导出会生成：

- `time_series_returns.csv`
- `time_series_regimes.csv`
- `time_series_summary.json`
- `time_series_report.md`

注意：当前 exporter 主要基于 `event_windows_long` 构建局部事件窗口级分析，`source=event_windows_only`。这不是完整 session 市场分布。没有逐笔盘口数据时，系统不能估计真实 bid-ask spread。VaR / ES 是风险度量，不是收益预测或交易信号。

详细说明见 `docs/time_series_analysis.md`。

## UI 工作区说明

当前界面整理为三个入口：

- 交易回放页：默认主界面，只保留 K 线回放、开平仓、当前仓位、事件标签和备注。
- 数据分析页：集中查看已平仓交易、绩效、权益曲线、事件研究、策略一致性、回测研究、USDT 溢价和 AI 摘要入口。
- 设置中心：集中管理外观、语言、交易成本和 AI/API 配置。

这样做的目的很直接：交易时不要被研究面板干扰，复盘和研究时再进入数据分析页。

## 设置中心

设置中心包含：

- 外观：主题预设、K 线颜色、网格透明度、十字光标透明度。
- 语言：已预留 `zh_CN` / `en_US` 配置。当前只覆盖主要入口，完整国际化后续完善。
- 回放 / 交易成本：`fill_mode`、`fee_bps`、`slippage_bps`、`trade_notional`、`initial_equity`。
- AI / API：选择 `mock`、`openai`、`custom_http` provider，并显示本地只读 API 地址。

API Key 不在界面保存。外部模型密钥只从环境变量读取。

## 数据分析页

数据分析页集中放研究功能：

- 交易绩效：已平仓交易、绩效摘要、权益曲线。
- 事件研究：事件研究表和数据集摘要。
- 策略一致性：检查样本是否适合继续做规则挖掘。
- 回测研究：运行内置策略、参数扫描和样本外验证。
- USDT 溢价：查看最近采样和溢价曲线。
- AI 摘要：预留入口，导出后可通过本地 API 获取 LLM context。
