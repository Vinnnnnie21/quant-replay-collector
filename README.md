# Quant Replay Collector v1.6.0

Quant Replay Collector（QRC）是一款本地运行的交易回放和决策研究工具。它用逐根 K 线回放记录主观交易行为，再把开仓、平仓判断整理成可审计的研究样本。数据、标注、模型和报告默认只保存在用户电脑上。

v1.6.0 的重点是“决策研究”：建立策略模板，固定决策周期和两个更高周期背景，在隐藏来源和未来行情的情况下复查判断，再查看结构相似度、历史选择倾向和匹配后的后验差异。研究结果不是交易信号，不保证盈利，也不会触发真实交易。

## 适用范围

QRC 适合希望系统记录和检查主观判断的研究者。当前版本可以：

- 回放本地或交易所公开 K 线，记录模拟开仓、全量平仓、止盈止损、标签和备注；
- 查看账户权益、交易明细、策略一致性、回测研究和时间序列诊断；
- 为开仓和平仓建立独立的盲审样本；
- 按市场级重叠区间生成“独立行情片段”，避免把相关样本当成多份独立证据；
- 计算三周期结构相似度，生成正式盲审候选；
- 训练可解释的历史选择倾向模型，并按时间和独立行情片段验证；
- 对开仓/拒绝、立即平仓/继续持有做匹配后验比较；
- 发布不可修改、可核验的研究版本报告。

当前版本不连接交易所下单接口，不自动交易，不生成买卖信号，不承诺把经验转换成可交易策略。K 线中的主动成交字段只是成交活跃度代理，不是订单流、盘口深度或真实买卖压力。

## 主要工作区

| 工作区 | 用途 |
| --- | --- |
| 交易回放 | 逐根播放、单步、跳到末尾、切换周期、记录模拟开平仓和止盈止损 |
| 交易绩效 | 查看权益曲线、已实现/浮动盈亏、交易明细和方向筛选 |
| 决策研究 | 开仓研究和平仓研究共用一个入口，按五步自由切换 |
| 策略一致性 | 检查样本结构、标签完整度和行为一致性，不评价盈利能力 |
| 回测研究 | 在明确费用、滑点和成交规则后验证候选规则 |
| USDT 溢价 | 保存和查看公开市场溢价样本 |
| 历史研究结果 | 读取旧导出和历史报告 |
| 时间序列诊断 | 查看收益分布、序列依赖、波动和尾部风险等统计特征 |

## 决策研究五步

进入“数据分析 → 决策研究”，选择“开仓研究”或“平仓研究”。两个标签共用策略模板版本、方向、三周期和数据完整度上下文。

1. **样本复查**：载入待确认种子，在三周期图表截止线前作出人工判断；保存后才能揭示真实来源和未来走势。
2. **相似候选**：浏览已揭示样本之间的结构分解，或在满足成熟度后扫描正式候选。未判断列表不显示单条分数和来源。
3. **行为模型**：用户主动训练“开仓选择倾向”或“立即平仓选择倾向”。分数描述历史选择相似性，不是盈利概率或交易信号。
4. **后验对比**：对结构相近的两类判断进行全局一对一匹配，完整保留显著和不显著的 15 项结果。
5. **版本报告**：查看当前草稿，主动发布不可变研究快照。新数据只会提示创建新版本，不会覆盖已发布报告。

策略模板冻结方向、决策协议、决策规则和三个周期。周期必须是一个决策周期加两个严格更高且互不重复的背景周期。规则、方向或周期改变时应“保存为新版本”；重命名和归档不会改变旧版本含义。

## 界面截图

### 交易回放

![交易回放主界面](docs/screenshots/qrc-home.png)

### 数据分析

![数据分析工作区](docs/screenshots/qrc-analysis-workspace.png)

### 决策研究（浅色）

![浅色主题下的决策研究策略模板](docs/screenshots/v1.6.0/01-light-1366x768-setup-editor.png)

### 决策研究（深色）

![深色主题下的决策研究人工判断](docs/screenshots/v1.6.0/04-dark-1920x1080-manual-judgment.png)

截图使用合成数据，不包含真实账户、交易或数据库内容。

## 安装

### 使用 Windows 正式包

从 [v1.6.0 Release](https://github.com/Vinnnnnie21/quant-replay-collector/releases/tag/v1.6.0) 下载 `QRC-v1.6.0-Windows-x64.zip` 和 `checksums.txt`，核对 SHA-256 后完整解压。不要直接在压缩包内运行。打开解压目录中的 `QRC.exe`。

正式包是 64 位 Windows onedir 版本。`QRC.exe` 依赖同目录下的 `_internal`，不能单独移走。

### 从源码启动

要求 Windows x64、Python 3.13：

```powershell
git clone https://github.com/Vinnnnnie21/quant-replay-collector.git
cd quant-replay-collector
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\start.bat
```

排查启动错误时使用带控制台的入口：

```powershell
.\.venv\Scripts\python.exe run_app.py
```

也可以使用包入口：

```powershell
.\.venv\Scripts\python.exe -m quant_collector_app
```

## 从旧版本升级

升级前退出旧程序并备份数据。源码模式的数据通常在 `quant_collector_app\data`；正式便携包的数据在程序目录旁。至少备份 SQLite 数据库、行情缓存、设置和导出结果。

v1.6.0 当前支持数据库 schema 19。应用版本 `1.6.0` 与数据库 schema 是两套独立编号，不能互换。旧数据库启动时会先创建升级前备份，再执行只增迁移；迁移是单向的，旧程序不能保证读取已升级数据库。要回退程序，必须同时恢复升级前备份。

不要把真实数据库交给 pytest，也不要在原库上手工执行迁移脚本。迁移验证应使用副本或合成数据库。

## 数据位置与备份

| 运行方式 | 默认数据位置 |
| --- | --- |
| 源码运行 | `quant_collector_app\data` |
| 正式 onedir 包 | `QRC.exe` 所在目录的 `data` |
| 测试或验收 | 由 `QRC_RUNTIME_ROOT` 指向独立临时目录 |

SQLite 数据库、缓存、日志、导出和备份目录已被 Git 忽略。用户仍需自行备份；Git 不是数据备份工具。复制数据库前应正常退出程序，确认没有后台补齐、分析、导出或备份任务在运行。

## 桌面快捷方式

快捷方式脚本会先核对正式包 manifest、版本、原生启动门禁和 EXE 哈希。先执行 dry-run：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\create_desktop_shortcut.ps1 `
  -TargetPath "C:\Program Files\QRC-v1.6.0-Windows-x64\QRC.exe" `
  -ExpectedVersion "1.6.0" `
  -DryRun
```

确认输出中的 `TargetPath`、`ValidatedVersion` 和 `IconLocation` 后，去掉 `-DryRun` 再执行。脚本创建当前用户桌面的 `QRC.lnk`，不会修改系统执行策略。快捷方式和运行中的任务栏图标都使用 `quant_collector_app/assets/app_icon.ico`。

## 开发与测试

安装锁定依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

常用检查：

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

## Windows 构建

```powershell
cd quant_collector_app
.\build_windows.bat
cd ..
```

构建脚本生成 `dist\QRC\QRC.exe`，并从 `quant_collector_app/version.py` 生成 Windows 文件版本 `1.6.0.0`。原生启动验证通过并更新 manifest 后，生成正式归档：

```powershell
.\.venv\Scripts\python.exe scripts\package_windows_release.py `
  --root quant_collector_app\dist\QRC `
  --output-dir dist
```

输出文件为 `dist\QRC-v1.6.0-Windows-x64.zip`。完整发布步骤见 [发布说明](docs/release.md)。

## 目录结构

```text
quant_collector_app/   桌面应用、存储、研究服务和界面
  analysis/            通用分析与数据质量
  backtesting/         研究型回测
  controllers/         Qt 后台任务和页面协调
  research/            决策研究领域计算
  services/            公开用例与跨模块编排
  storage_core/        SQLite 连接、迁移和 repository
  views/               PySide6 页面和组件
docs/                   架构决策、产品规格和用户文档
scripts/                自检、截图、清理、构建和发布脚本
tests/                  按职责分类的全部自动化测试
```

## 隐私与已知限制

- QRC 默认不上传数据库、交易记录、标注或报告。网络只用于用户主动请求的公开行情和溢价数据。
- v1.6.0 只研究全量平仓，不研究部分减仓比例。
- 人工添加且没有关联原始策略模板的旧平仓可以浏览和补标，但不能进入正式模型。
- 正式候选、模型和后验比较都有样本量、数据完整度和独立行情片段门槛。页面显示“证据不足”时不会用稀疏结果补成通过。
- 研究模型总结历史选择，不是在发现永久有效的市场规律。
- 回测和后验路径未必包含所有真实交易成本，历史结果不代表未来表现。

## 文档

- [v1.6.0 中文操作教程](docs/USER_GUIDE_v1.6.0.md)
- [v1.6.0 发布说明](docs/releases/v1.6.0/RELEASE_NOTES.md)
- [发布与构建](docs/release.md)
- [测试说明](docs/testing.md)
- [性能预算](docs/performance.md)
- [系统架构](docs/architecture.md)
- [回测说明](docs/backtesting.md)

## 许可证与风险声明

项目采用 [MIT License](LICENSE)。QRC 是本地研究工具，不构成投资建议，不自动执行交易，不保证任何收益。所有交易和数据备份责任由用户自行承担。
