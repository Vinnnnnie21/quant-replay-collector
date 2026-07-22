# Quant Replay Collector v1.6.0

Quant Replay Collector（QRC）是一款本地运行的交易回放和决策研究工具。它用逐根 K 线回放记录主观交易行为，再把开仓、平仓判断整理成可审计的研究样本。数据、标注、模型和报告默认只保存在用户电脑上。

*Quant Replay Collector (QRC) is a local trading replay and decision research tool. It records discretionary trading decisions through bar-by-bar replay, then turns entry and exit judgments into auditable research samples. Data, labels, models, and reports stay on the user's computer by default.*

v1.6.0 的重点是“决策研究”：建立策略模板，固定决策周期和两个更高周期背景，在隐藏来源和未来行情的情况下复查判断，再查看结构相似度、历史选择倾向和匹配后的后验差异。研究结果不是交易信号，不保证盈利，也不会触发真实交易。

*The focus of v1.6.0 is decision research: create a strategy template, fix one decision timeframe and two higher-timeframe contexts, review judgments without seeing their source or future prices, then inspect structural similarity, historical selection tendencies, and matched post-decision differences. Research results are not trading signals, do not guarantee a profit, and never trigger live trades.*

## 适用范围

*Scope*

QRC 适合希望系统记录和检查主观判断的研究者。当前版本可以：

*QRC is intended for researchers who want a structured record of their discretionary judgments. The current version can:*

- 回放本地或交易所公开 K 线，记录模拟开仓、全量平仓、止盈止损、标签和备注；
  *Replay local or publicly available exchange candles and record simulated entries, full exits, take-profit and stop-loss levels, labels, and notes;*
- 查看账户权益、交易明细、策略一致性、回测研究和时间序列分析；
  *Review account equity, trade details, strategy consistency, backtest research, and time-series analysis;*
- 为开仓和平仓建立独立的盲审样本；
  *Create separate blind-review samples for entries and exits;*
- 按市场级重叠区间生成“独立行情片段”，避免把相关样本当成多份独立证据；
  *Group overlapping market-wide intervals into independent market episodes so related samples are not counted as separate evidence;*
- 计算三周期结构相似度，生成正式盲审候选；
  *Calculate three-timeframe structural similarity and generate formal blind-review candidates;*
- 训练可解释的历史选择倾向模型，并按时间和独立行情片段验证；
  *Train interpretable historical selection-tendency models and validate them by time and independent market episode;*
- 对开仓/拒绝、立即平仓/继续持有做匹配后验比较；
  *Run matched post-decision comparisons for entry versus rejection and immediate exit versus holding;*
- 发布不可修改、可核验的研究版本报告。
  *Publish immutable, verifiable research-version reports.*

当前版本不连接交易所下单接口，不自动交易，不生成买卖信号，不承诺把经验转换成可交易策略。K 线中的主动成交字段只是成交活跃度代理，不是订单流、盘口深度或真实买卖压力。

*The current version does not connect to exchange order APIs, trade automatically, generate buy or sell signals, or claim that experience can be turned into a tradable strategy. Taker-side candle fields are only proxies for trading activity. They are not order flow, order-book depth, or actual buying and selling pressure.*

## 主要工作区

*Main workspaces*

| 工作区<br><sub>Workspace</sub> | 用途<br><sub>Purpose</sub> |
| --- | --- |
| 交易回放<br><sub>Trading replay</sub> | 逐根播放、单步、跳到末尾、切换周期、记录模拟开平仓和止盈止损<br><sub>Play bar by bar, step forward, jump to the end, switch timeframes, and record simulated entries, exits, take-profit, and stop-loss levels.</sub> |
| 交易绩效<br><sub>Trading performance</sub> | 查看权益曲线、已实现/浮动盈亏、交易明细和方向筛选<br><sub>Review the equity curve, realized and unrealized P&L, trade details, and direction filters.</sub> |
| 决策研究<br><sub>Decision research</sub> | 开仓研究和平仓研究共用一个入口，按五步自由切换<br><sub>Use one entry point for entry and exit research, with free navigation across five steps.</sub> |
| 策略一致性<br><sub>Strategy consistency</sub> | 检查样本结构、标签完整度和行为一致性，不评价盈利能力<br><sub>Check sample structure, label completeness, and behavioral consistency without judging profitability.</sub> |
| 回测研究<br><sub>Backtest research</sub> | 在明确费用、滑点和成交规则后验证候选规则<br><sub>Evaluate candidate rules under explicit fee, slippage, and fill assumptions.</sub> |
| USDT 溢价<br><sub>USDT premium</sub> | 保存和查看公开市场溢价样本<br><sub>Save and inspect public-market premium samples.</sub> |
| 历史研究结果<br><sub>Historical research results</sub> | 读取旧导出和历史报告<br><sub>Read earlier exports and historical reports.</sub> |
| 时间序列分析<br><sub>Time-series analysis</sub> | 查看收益分布、序列依赖、波动和尾部风险等统计特征<br><sub>Inspect return distributions, serial dependence, volatility, tail risk, and related statistics.</sub> |

## 决策研究五步

*Five decision-research steps*

进入“数据分析 → 决策研究”，选择“开仓研究”或“平仓研究”。两个标签共用策略模板版本、方向、三周期和数据完整度上下文。

*Open “Data Analysis → Decision Research,” then choose “Entry Research” or “Exit Research.” Both tabs share the same strategy-template version, direction, three timeframes, and data-completeness context.*

1. **样本复查**：载入待确认种子，在三周期图表截止线前作出人工判断；保存后才能揭示真实来源和未来走势。
   *Sample review: load pending seeds and make a judgment using only the three charts up to the shared cutoff. The true source and future price path remain hidden until the judgment is saved.*
2. **相似候选**：浏览已揭示样本之间的结构分解，或在满足成熟度后扫描正式候选。未判断列表不显示单条分数和来源。
   *Similar candidates: inspect structural breakdowns between revealed samples, or scan formal candidates once the maturity gate is met. Pending items do not expose individual scores or sources.*
3. **行为模型**：用户主动训练“开仓选择倾向”或“立即平仓选择倾向”。分数描述历史选择相似性，不是盈利概率或交易信号。
   *Behavior model: explicitly train an “entry selection tendency” or “immediate-exit selection tendency” model. Its score describes similarity to past choices, not profit probability or a trading signal.*
4. **后验对比**：对结构相近的两类判断进行全局一对一匹配，完整保留显著和不显著的 15 项结果。
   *Outcome comparison: globally match two structurally similar judgment groups one to one, without reuse, and retain all 15 results whether significant or not.*
5. **版本报告**：查看当前草稿，主动发布不可变研究快照。新数据只会提示创建新版本，不会覆盖已发布报告。
   *Version report: review the current draft and explicitly publish an immutable research snapshot. New data only prompts you to create another version; it does not overwrite a published report.*

策略模板冻结方向、决策协议、决策规则和三个周期。周期必须是一个决策周期加两个严格更高且互不重复的背景周期。规则、方向或周期改变时应“保存为新版本”；重命名和归档不会改变旧版本含义。

*A strategy template version freezes its direction, decision protocol, decision rules, and three timeframes. It must contain one decision timeframe and two distinct, strictly higher context timeframes. Changes to rules, direction, or timeframes must be saved as a new version. Renaming or archiving a template does not change the meaning of earlier versions.*

## 界面截图

*Screenshots*

### 交易回放

*Trading replay*

![交易回放主界面 / Main trading replay window](docs/screenshots/qrc-home.png)

### 数据分析

*Data analysis*

![数据分析工作区 / Data analysis workspace](docs/screenshots/qrc-analysis-workspace.png)

### 决策研究（浅色）

*Decision research — light theme*

![浅色主题下的决策研究策略模板 / Strategy template in the light decision-research workspace](docs/screenshots/v1.6.0/01-light-1366x768-setup-editor.png)

### 决策研究（深色）

*Decision research — dark theme*

![深色主题下的决策研究人工判断 / Manual judgment in the dark decision-research workspace](docs/screenshots/v1.6.0/04-dark-1920x1080-manual-judgment.png)

截图使用合成数据，不包含真实账户、交易或数据库内容。

*The screenshots use synthetic data and contain no real account, trade, or database content.*

## 安装

*Installation*

### 使用 Windows 正式包

*Using the official Windows package*

从 [v1.6.0 Release](https://github.com/Vinnnnnie21/quant-replay-collector/releases/tag/v1.6.0) 下载 `QRC-v1.6.0-Windows-x64.zip` 和 `checksums.txt`，核对 SHA-256 后完整解压。不要直接在压缩包内运行。打开解压目录中的 `QRC.exe`。

*Download `QRC-v1.6.0-Windows-x64.zip` and `checksums.txt` from the [v1.6.0 Release](https://github.com/Vinnnnnie21/quant-replay-collector/releases/tag/v1.6.0). Verify the SHA-256 checksum, extract the full archive, and run `QRC.exe` from the extracted directory. Do not run it from inside the ZIP file.*

正式包是 64 位 Windows onedir 版本。`QRC.exe` 依赖同目录下的 `_internal`，不能单独移走。

*The official package is a 64-bit Windows onedir build. `QRC.exe` depends on the adjacent `_internal` directory and must not be moved by itself.*

### 从源码启动

*Running from source*

要求 Windows x64、Python 3.13：

*Requirements: Windows x64 and Python 3.13.*

```powershell
git clone https://github.com/Vinnnnnie21/quant-replay-collector.git
cd quant-replay-collector
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\start.bat
```

排查启动错误时使用带控制台的入口：

*Use the console entry point when diagnosing startup errors:*

```powershell
.\.venv\Scripts\python.exe run_app.py
```

也可以使用包入口：

*You can also use the package entry point:*

```powershell
.\.venv\Scripts\python.exe -m quant_collector_app
```

## 从旧版本升级

*Upgrading from an earlier version*

升级前退出旧程序并备份数据。源码模式的数据通常在 `quant_collector_app\data`；正式便携包的数据在程序目录旁。至少备份 SQLite 数据库、行情缓存、设置和导出结果。

*Exit the old application and back up your data before upgrading. Source-mode data is normally stored in `quant_collector_app\data`; portable-package data is stored beside the application directory. Back up at least the SQLite database, market-data cache, settings, and exports.*

v1.6.0 当前支持数据库 schema 19。应用版本 `1.6.0` 与数据库 schema 是两套独立编号，不能互换。旧数据库启动时会先创建升级前备份，再执行只增迁移；迁移是单向的，旧程序不能保证读取已升级数据库。要回退程序，必须同时恢复升级前备份。

*v1.6.0 currently supports database schema 19. Application version `1.6.0` and the database schema are separate version numbers. When an older database is opened, QRC creates a pre-upgrade backup before applying additive migrations. Migration is one-way: an older application may not be able to read the upgraded database. Rolling back the application also requires restoring the pre-upgrade backup.*

不要把真实数据库交给 pytest，也不要在原库上手工执行迁移脚本。迁移验证应使用副本或合成数据库。

*Never give pytest a live database or run migration scripts manually against the original file. Validate migrations with a copy or a synthetic database.*

## 数据位置与备份

*Data locations and backups*

| 运行方式<br><sub>Run mode</sub> | 默认数据位置<br><sub>Default data location</sub> |
| --- | --- |
| 源码运行<br><sub>Source</sub> | `quant_collector_app\data` |
| 正式 onedir 包<br><sub>Official onedir package</sub> | `QRC.exe` 所在目录的 `data`<br><sub>The `data` directory beside `QRC.exe`</sub> |
| 测试或验收<br><sub>Tests or acceptance checks</sub> | 由 `QRC_RUNTIME_ROOT` 指向独立临时目录<br><sub>An isolated temporary directory selected through `QRC_RUNTIME_ROOT`</sub> |

SQLite 数据库、缓存、日志、导出和备份目录已被 Git 忽略。用户仍需自行备份；Git 不是数据备份工具。复制数据库前应正常退出程序，确认没有后台补齐、分析、导出或备份任务在运行。

*Git ignores SQLite databases, caches, logs, exports, and backup directories. You still need your own backups; Git is not a data-backup system. Exit the application normally and make sure no backfill, analysis, export, or backup task is running before copying the database.*

## 桌面快捷方式

*Desktop shortcut*

快捷方式脚本会先核对正式包 manifest、版本、原生启动门禁和 EXE 哈希。先执行 dry-run：

*The shortcut script checks the official package manifest, version, native startup gate, and EXE hash. Start with a dry run:*

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\create_desktop_shortcut.ps1 `
  -TargetPath "C:\Program Files\QRC-v1.6.0-Windows-x64\QRC.exe" `
  -ExpectedVersion "1.6.0" `
  -DryRun
```

确认输出中的 `TargetPath`、`ValidatedVersion` 和 `IconLocation` 后，去掉 `-DryRun` 再执行。脚本创建当前用户桌面的 `QRC.lnk`，不会修改系统执行策略。快捷方式和运行中的任务栏图标都使用 `quant_collector_app/assets/app_icon.ico`。

*Check `TargetPath`, `ValidatedVersion`, and `IconLocation` in the output. If they are correct, run the command again without `-DryRun`. The script creates `QRC.lnk` on the current user's desktop without changing the system execution policy. The shortcut and running taskbar icon both use `quant_collector_app/assets/app_icon.ico`.*

## 开发与测试

*Development and testing*

安装锁定依赖：

*Install the locked dependencies:*

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

常用检查：

*Common checks:*

```powershell
.\.venv\Scripts\python.exe -m compileall -q quant_collector_app tests scripts
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m quant_collector_app.self_check --core
.\.venv\Scripts\python.exe -m quant_collector_app.self_check --gui
.\.venv\Scripts\python.exe -m quant_collector_app.self_check --all
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest -q -m performance
git diff --check
```

pytest 缓存和临时文件统一放在 `.test-artifacts`，不会进入正式包。测试目录按职责分为 `unit`、`integration`、`gui`、`research`、`storage`、`migration`、`performance` 和 `release`；所有活跃测试仍采用 `test_*.py` 并在默认收集范围内。

*pytest caches and temporary files are kept under `.test-artifacts` and are excluded from the official package. Tests are grouped by responsibility under `unit`, `integration`, `gui`, `research`, `storage`, `migration`, `performance`, and `release`. Every active test still uses the `test_*.py` naming convention and remains in the default collection set.*

## Windows 构建

*Windows build*

```powershell
cd quant_collector_app
.\build_windows.bat
cd ..
```

构建脚本生成 `dist\QRC\QRC.exe`，并从 `quant_collector_app/version.py` 生成 Windows 文件版本 `1.6.0.0`。原生启动验证通过并更新 manifest 后，生成正式归档：

*The build script creates `dist\QRC\QRC.exe` and derives Windows file version `1.6.0.0` from `quant_collector_app/version.py`. After the native startup checks pass and the manifest is updated, create the official archive:*

```powershell
.\.venv\Scripts\python.exe scripts\package_windows_release.py `
  --root quant_collector_app\dist\QRC `
  --output-dir dist
```

输出文件为 `dist\QRC-v1.6.0-Windows-x64.zip`。完整发布步骤见 [发布说明](docs/release.md)。

*The output file is `dist\QRC-v1.6.0-Windows-x64.zip`. See [Release and build](docs/release.md) for the complete release procedure.*

## 目录结构

*Repository layout*

```text
quant_collector_app/   桌面应用、存储、研究服务和界面 / Desktop app, storage, research services, and UI
  analysis/            通用分析与数据质量 / Shared analysis and data quality
  backtesting/         研究型回测 / Research-oriented backtesting
  controllers/         Qt 后台任务和页面协调 / Qt background tasks and page coordination
  research/            决策研究领域计算 / Decision-research domain calculations
  services/            公开用例与跨模块编排 / Public use cases and cross-module orchestration
  storage_core/        SQLite 连接、迁移和 repository / SQLite connections, migrations, and repositories
  views/               PySide6 页面和组件 / PySide6 pages and components
docs/                   架构决策、产品规格和用户文档 / ADRs, product specifications, and user documentation
scripts/                自检、截图、清理、构建和发布脚本 / Self-check, screenshot, cleanup, build, and release scripts
tests/                  按职责分类的全部自动化测试 / Automated tests grouped by responsibility
```

## 隐私与已知限制

*Privacy and known limitations*

- QRC 默认不上传数据库、交易记录、标注或报告。网络只用于用户主动请求的公开行情和溢价数据。
  *QRC does not upload databases, trade records, labels, or reports by default. Network access is used only when the user explicitly requests public market or premium data.*
- v1.6.0 只研究全量平仓，不研究部分减仓比例。
  *v1.6.0 studies full exits only; partial-exit sizing is outside its scope.*
- 人工添加且没有关联原始策略模板的旧平仓可以浏览和补标，但不能进入正式模型。
  *Manually added historical exits without a link to their original strategy template can be viewed and annotated, but cannot enter a formal model.*
- 正式候选、模型和后验比较都有样本量、数据完整度和独立行情片段门槛。页面显示“证据不足”时不会用稀疏结果补成通过。
  *Formal candidates, models, and outcome comparisons all enforce sample-size, data-completeness, and independent-market-episode gates. When the page says “insufficient evidence,” QRC does not fill sparse results to make them pass.*
- 研究模型总结历史选择，不是在发现永久有效的市场规律。
  *Research models summarize historical choices; they do not discover permanently valid market rules.*
- 回测和后验路径未必包含所有真实交易成本，历史结果不代表未来表现。
  *Backtests and post-decision paths may omit some real trading costs. Historical results do not predict future performance.*

## 文档

*Documentation*

- [v1.6.0 中文操作教程](docs/USER_GUIDE_v1.6.0.md)
  *[v1.6.0 Chinese user guide](docs/USER_GUIDE_v1.6.0.md)*
- [v1.6.0 发布说明](docs/releases/v1.6.0/RELEASE_NOTES.md)
  *[v1.6.0 release notes](docs/releases/v1.6.0/RELEASE_NOTES.md)*
- [发布与构建](docs/release.md)
  *[Release and build](docs/release.md)*
- [测试说明](docs/testing.md)
  *[Testing](docs/testing.md)*
- [性能预算](docs/performance.md)
  *[Performance budgets](docs/performance.md)*
- [系统架构](docs/architecture.md)
  *[Architecture](docs/architecture.md)*
- [回测说明](docs/backtesting.md)
  *[Backtesting](docs/backtesting.md)*

## 许可证与风险声明

*License and risk notice*

项目采用 [MIT License](LICENSE)。QRC 是本地研究工具，不构成投资建议，不自动执行交易，不保证任何收益。所有交易和数据备份责任由用户自行承担。

*This project is licensed under the [MIT License](LICENSE). QRC is a local research tool, not investment advice. It does not execute trades automatically or guarantee returns. Users remain responsible for their trading decisions and data backups.*
