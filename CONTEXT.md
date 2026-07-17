# Quant Replay Collector Domain Context

## Product boundary

### Current delivery scope

Quant Replay Collector is currently a local desktop research tool. Its active scope is market-data collection, replay-based simulated trading, manually recorded trading events, research analysis, risk and time-series analysis, and USDT premium monitoring. It does not connect to live order APIs, place real orders, or manage real positions. Live trading may be reconsidered only as a separate future product decision after the existing research workflow is stable and reproducible.

### Desktop launch entry（桌面启动入口）

`QRC` 是面向用户的 Windows 桌面启动名称。桌面入口启动当前发布包中的同一应用，不创建独立数据副本，也不改变本地研究数据的保存位置。应用窗口在深色界面使用黑底白色 logo，在浅色界面使用透明底黑色 logo；桌面启动入口使用固定、清晰可辨的 QRC 图标。

### Stability hardening phase

The current delivery phase adds no new business capabilities. It improves the reliability, responsiveness, data preservation and reproducibility of the existing local research workflow before future scope expansion.

### Safe shutdown

Safe shutdown is the required behavior when a user closes the application while local work is in progress. The application shows that it is safely saving or stopping the task, then exits only after active work has reached a safe stopping point. It does not default to force-terminating a task that may be writing research data.

### Background task lifecycle

Market-data loading, export, analysis refresh, premium sampling and multi-timeframe loading are background tasks. Each task follows the same small lifecycle: running, stop requested, completed, or failed. The lifecycle exists to keep the desktop application responsive and to make safe shutdown consistent; it is not a general-purpose task scheduler.

### Research data quality gate

Market-data collection may normalize, sort, deduplicate or exclude clearly invalid source rows only when it records the changes in a data-quality report. Backtesting, statistical analysis and strategy research require trustworthy input and must reject invalid ordering, duplicate bars, missing critical prices or non-finite values instead of silently continuing.

### Reproducible statistical result

A reproducible statistical result is one that produces the same output from the same input data, parameters and application version. Any randomized calculation uses a recorded random seed and records its simulation settings with the result; users may choose a different seed deliberately, but it is never implicit.

### Supported runtime environment

The stability hardening phase supports Windows 64-bit computers running Python 3.13 and a locked dependency set. Other operating systems, cloud deployment and unplanned runtime upgrades are outside the current support commitment.

### Local research data protection

Research data is stored locally. The application keeps 14 daily local database backups, creates an additional backup before a database upgrade, and writes settings atomically. Cloud synchronization is not part of the current delivery scope.

### Performance reference scenario

The standard scenario for evaluating responsiveness in the stability hardening phase is six months of one-minute market data. It represents ordinary local research use and does not imply a high-frequency, cloud-scale or live-trading workload.

### Incremental stabilization

Incremental stabilization improves the existing desktop application through small behavior-preserving changes. It extracts focused, testable responsibilities from existing large UI components without a full interface rewrite or a change to research semantics.

### Stabilization delivery order

The stability hardening phase is delivered in this order: protect running work and local data, protect research-result trust, protect responsiveness, then simplify internal structure. This order prioritizes avoiding crashes, loss and misleading research conclusions before optimization or refactoring.

## Application workspace

### Workspace（工作区）

应用内承载一组完整研究任务的功能区域。用户通过应用顶部导航在工作区之间切换，而不是打开彼此独立的窗口。工作区共享同一研究会话；切换工作区不表示创建新会话，也不应清空当前研究状态。

## Example dialogue

> 研究员：我想从行情回放查看这次会话的绩效。
>
> 开发者：切换到数据分析工作区即可；仍然是当前研究会话，不会弹出新窗口或重置回放状态。

## Research identity and display names

### Technical identifier（内部标识）

由系统生成、稳定且唯一的 `session_id` 或 `trade_id`，用于数据库关联、导出、恢复与绩效计算。内部标识不是面向用户的名称，不应以日期文本替代，也不应作为界面的主要标签展示。

### Session display name（会话显示名称）

研究会话在界面中的可读名称，由交易对、回放周期和数据时间范围组成，例如 `BTCUSDT · 5m · 2025-04-01—2025-05-01`。相同范围存在多个会话时追加顺序号，例如 `#2`。显示名称可以重复演进，不承担数据关联职责。

### Trade display name（交易显示名称）

单笔交易在界面中的可读名称，由方向、回放下单时间和会话内顺序号组成，例如 `多 · 2025-04-03 14:25 · #03`。回放下单时间指交易在历史行情时间轴上的执行时间，不是用户操作时的本机时间。

### Replay market time（回放行情时间）

历史行情中每根 K 线实际对应的时间。连续资金曲线以回放行情时间为横轴，交易事件标记落在各自的回放执行时间上；K 线序号和本机操作时间都不能替代该时间轴。

### Historical performance view（历史交易绩效视图）

历史交易绩效视图展示已保存研究会话的资金曲线、指标、交易分布和交易列表。它应按该会话自己的回放行情时间生成连续资金曲线，并可在后台独立读取该会话对应的 K 线数据；查看历史绩效不应要求主播放器先加载或播放同一时间段，也不应改变主播放器当前行情、游标或回放状态。
### Trade data management（交易数据管理）

交易数据管理是对本地模拟交易样本的人工整理能力。它可以按回放行情时间删除一个时间段内的交易样本，也可以在该时间段内删除某一笔交易样本；它不表示删除行情 K 线、数据质量报告或整个研究会话。

交易绩效会话是交易数据管理和交易回放续做的共同入口。管理界面按绩效会话列出交易样本；回放页只有在用户明确选择“继续绩效会话”后，才把该会话恢复为当前工作会话。

继续绩效会话是在原 `session_id` 上恢复回放上下文并追加交易、事件和资金曲线，不 clone、不复制、也不新建替代会话。仅在数据分析页查看历史绩效不会触发续做或改变当前播放器。

按时间段删除交易样本时，以开仓或平仓事件的回放行情时间是否落入时间段为准。任一事件命中就删除整笔交易样本；如果只是持仓过程跨过该时间段，但开仓和平仓事件都不在时间段内，则不删除。

TP/SL 的空值表示未设置。空值不是有效的 `0%` 止盈或止损；界面输入 `0` 时规范化为空值，保存为 `NULL`，恢复后仍显示为空。

## Position display

### Position card（持仓卡）

当前研究会话中一笔未平仓交易的展示单元。一个会话可同时有多张持仓卡；不将多空或不同开仓价的未平仓交易合并为单一方向或均价。

_Avoid_: 汇总持仓、混合持仓

## Naming example dialogue

> 研究员：把 `sess_489825df` 改成 `2025-04-01—2025-05-01` 可以吗？
>
> 开发者：界面会显示 `BTCUSDT · 5m · 2025-04-01—2025-05-01`，内部仍保留唯一的 `session_id`，历史绩效和导出关联不会改变。
