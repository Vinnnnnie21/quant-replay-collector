# Quant Replay Collector

## 项目简介

Quant Replay Collector 是一个面向加密货币交易训练、手动回放、交易事件采集和量化样本导出的桌面工具。它不是普通看盘软件，而是用于在 Binance Futures K 线回放过程中记录交易行为、抽取事件窗口、生成结构化特征数据，并支持后续复盘、策略研究和机器学习样本整理。

当前项目以本地桌面应用为主，重点是稳定的数据采集流程、可恢复的训练会话、可解释的事件标签和可导出的研究数据。

## 为什么做这个项目

很多交易复盘工具只停留在“看图”和“回放”，但手动交易训练真正有价值的部分往往是行为数据本身：

- 什么时候开仓、平仓；
- 当时的 K 线结构、成交量和前序走势是什么；
- 交易者主观判断使用了哪些标签；
- 后续 1、3、5、10 根 K 线的表现如何；
- 这些事件能否被导出为后续分析样本。

这个项目尝试把手动训练过程变成结构化数据采集过程。它既可以用于复盘交易行为，也可以作为量化研究样本生成工具的原型。

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
│  ├─ market_data.py         # Binance K 线加载、缓存、绘图项、特征计算
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
│  ├─ 开始.bat               # Windows 开发运行脚本
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
开始.bat
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

```bash
python -m pytest -q
```

也可以在 `quant_collector_app/` 下运行轻量自检：

```bash
python self_check.py
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

数据库属于本地运行数据，默认不提交到 GitHub。

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

这样拆分是为了避免在后续建模时误把未来收益或未来窗口数据当作输入特征。

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

## 截图占位说明

后续项目截图建议放在：

```text
docs/screenshots/
```

建议至少补充：

- 主界面 K 线回放截图；
- 开仓/平仓事件标记截图；
- 事件标签和备注截图；
- 导出数据目录截图；
- USDT 溢价率面板截图。

## GitHub 展示亮点

- 把手动交易训练过程结构化为可分析数据，而不是只做视觉回放。
- 事件标签、备注、窗口抽取和特征计算形成完整样本链路。
- 导出数据区分建模输入、标签和完整原始数据，降低未来函数误用风险。
- 模拟成交、手续费、滑点和权益曲线让手动回放更接近可复盘研究口径。
- 事件研究和 ML 样本拆分为后续量化研究保留清晰数据链路。
- 本地 SQLite 持久化支持会话恢复和复盘数据积累。
- 保留 PySide6 桌面应用形态，适合 Windows 用户直接运行和打包。
- 后续可以自然扩展到策略研究、统计报表和机器学习样本管理。

## 后续路线图

- 增加复盘报表导出，例如 HTML 或 Markdown 报告。
- 增加更完整的缓存校验和数据源状态提示。
- 增加更系统的自动化测试，覆盖 GUI 外的交易、导出、权益和事件研究主链路。
- 补充 GitHub 截图和示例导出数据。

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

`strategy_consistency` 模块用于判断人工交易样本是否来自同一套相对稳定的交易逻辑。

它不是盈利证明。它只判断样本是否适合继续做特征分析、规则挖掘、回测和 LLM 解读。

如果交易者没有固定策略，只是随机开仓，系统会提示样本不适合直接挖掘规则。这样可以降低 garbage in, garbage out 的风险。

当前默认策略档案是“大跌后的反转 K 线做多”。审计会检查：

- 方向是否集中在 LONG。
- 标签是否稳定。
- 备注是否缺失过多。
- 入场前市场状态是否接近“大跌后”。
- 相似 K 线场景下，人工动作是否一致。
- early / middle / late 三段样本是否出现明显漂移。

一致性评分解释：

- `>= 80`：样本一致性较好，可以进入后续分析。
- `60-80`：需要人工复核标签、样本定义和失败样本覆盖。
- `< 60`：不适合直接规则挖掘。

常见 warning：

- 样本量不足。
- LONG / SHORT 混杂。
- 大量事件没有标签。
- 大量事件没有备注。
- 相似场景下动作冲突。
- 可能缺少失败样本，存在选择性标注偏差。

低一致性样本不应直接拿去训练、回测或交给大模型解释。否则系统可能会把混乱交易记录解释成一个看似稳定、实则无效的“策略”。

导出目录会新增：

- `strategy_consistency.json`
- `strategy_consistency_report.md`

说明：一致性审计 UI 已支持主要入口中英文切换；导出的 Markdown 报告当前主要为中文，完整英文报告后续完善。

详细说明见 `docs/strategy_consistency.md`。

## 时间序列分析与市场状态诊断

项目新增 `time_series_analysis/`，用于统计收益率分布、波动率状态、趋势状态、自相关和随机基准。

当前导出会生成：

- `time_series_returns.csv`
- `time_series_regimes.csv`
- `time_series_summary.json`
- `time_series_report.md`

注意：当前 exporter 主要基于 `event_windows_long` 构建局部事件窗口级分析，`source=event_windows_only`。这不是完整 session 市场分布，不能当作交易信号或因果结论。

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

## UI Roadmap

- 完整中英文国际化。
- 更完整的数据分析 Dashboard。
- 更专业的策略报告页。
