# Quant Replay Collector Domain Context

## Product boundary

### Current delivery scope

Quant Replay Collector is currently a local desktop research tool. Its active scope is market-data collection, replay-based simulated trading, manually recorded trading events, research analysis, risk and time-series analysis, and USDT premium monitoring. It does not connect to live order APIs, place real orders, or manage real positions. Live trading may be reconsidered only as a separate future product decision after the existing research workflow is stable and reproducible.

### v1.6 research output boundary

v1.6 converts subjective decisions into a reproducible quantitative behavior profile and, when evidence permits, a testable strategy hypothesis. It does not call a behavior-model score or a matched event-study result a tradable quantitative strategy.

Each Setup version may produce a strategy-hypothesis card containing its direction and three-timeframe profile, reproducible market-structure indicators, entry and exit choice tendencies, stable behavior indicators and thresholds, model applicability range, complete matched outcome differences, evidence maturity, known gaps and the next samples required. Its status is limited to “仅行为画像”“探索性策略假设” or “待前瞻验证”.

A tradable strategy requires a later, separate validation stage that combines entry and exit rules, execution costs, position and risk rules, genuinely untouched forward data, portfolio interaction and failure monitoring. Those capabilities are outside v1.6 and are candidates for v1.7; they cannot be implied by renaming a research score as a signal.

### v1.6 preview delivery

v1.6 is developed through runnable local preview builds rather than one untestable integration batch. The order is `alpha.1 数据基础`、`alpha.2 决策样本`、`alpha.3 开仓研究闭环`、`beta.1 平仓研究闭环`、`rc.1 产品化验收`，then the final `v1.6.0`. Every preview must start successfully, migrate old databases safely, support cancellation for its background work, and preserve existing replay and analysis workflows.

The final version is not released until both entry and exit research pass their acceptance gates. Preview outputs are local evaluation artifacts and cannot be presented as stable strategy conclusions.

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

### K-line ancillary raw data（K 线附加原始数据）

行情源随 K 线返回、但不属于 OHLCV 的原始聚合字段。v1.6 持久化计价币成交额、成交笔数、主动买入基础币数量和主动买入成交额；研究层据此派生比例、平均值与异常程度。原始值必须保留，不能只保存当前公式生成的派生指标。

### Ancillary-data backfill（附加行情补齐）

为旧 K 线缓存重新获取缺失附加原始字段的后台任务。数据库升级保留原有 OHLCV，并将尚未获取的新增字段保持为空；应用不能把缺失值写成零，也不能在启动时静默重下全部历史数据。

进入研究区间时，系统检查并展示附加字段完整度，允许按需补齐当前区间；数据维护入口另提供可取消、可重试的全量历史补齐。补齐完成前，普通 K 线回放仍可使用，但依赖完整附加字段的结构相似度计算必须拒绝运行并给出中文原因。

研究页分别显示决策周期和两个更高周期的覆盖率、缺失 K 线数、缺失附加字段数及缺失时间段。“补齐当前研究区间”自动扩展到当前公式需要的历史预热窗口和后验观察窗口，不能要求用户手工推算应多下载多少根 K 线。

补齐任务必须可取消、可重试并显示当前周期、已完成区间和失败原因。已经成功保存的区间不因后续请求失败而回滚。补齐期间允许查看 K 线和进行人工样本复查，但相似候选生成、行为模型训练和正式后验匹配在所需字段不完整时拒绝运行，并指出缺失周期、字段和数量。

界面使用“计价币成交额”“成交笔数”“主动买入量”“主动买入成交额”等可核对名称，不把这些 K 线聚合字段命名为订单流、盘口深度或真实买卖压力。

### Aggressive-trade direction proxy（主动成交方向代理）

由 K 线聚合的主动买入量或成交额占比推导出的成交方向指标。主动卖出部分只能通过总量减主动买入量近似得到。它不包含订单簿档位、挂单变化、逐笔成交序列或买卖方账户数量，不能称为盘口深度、完整订单流或真实买卖压力。

缺少附加原始字段与字段值为零是不同的数据状态。研究计算不能把缺失值填成零，也不能跨越不同字段完整度或公式版本直接比较分数。

### Reproducible statistical result

A reproducible statistical result is one that produces the same output from the same input data, parameters and application version. Any randomized calculation uses a recorded random seed and records its simulation settings with the result; users may choose a different seed deliberately, but it is never implicit.

### Supported runtime environment

The stability hardening phase supports Windows 64-bit computers running Python 3.13 and a locked dependency set. Other operating systems, cloud deployment and unplanned runtime upgrades are outside the current support commitment.

### v1.6 implementation runtime

v1.6 continues to use Python 3.13, PySide6, SQLite, NumPy, pandas and scikit-learn as the supported product stack. QRC remains one local desktop application rather than introducing a separately deployed backend service. Research domain and calculation services stay independent of Qt widgets; the UI coordinates interaction and background work but does not own research formulas.

Database changes are append-only and backward compatible, dependencies remain locked, and long-running work uses the existing cancellable background-task lifecycle. Duplicate event-study implementations must be consolidated instead of adding another path inside a large UI module.

Rust is not a v1.6 rewrite target. It may be evaluated later only for a pure calculation kernel that still materially misses an explicit performance budget after profiling, vectorization, indexing and caching. A future Rust component cannot redefine the research domain model, persistence semantics or UI architecture.

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

交易数据管理是对本地模拟交易样本和绩效会话的人工整理能力。它可以按回放行情时间删除一个时间段内的交易样本，可以删除某一笔交易样本，也可以永久删除所选绩效会话及其专属记录；删除整个绩效会话后，该会话不再出现在任何会话目录中。同一品种、周期和回放时间范围内的剩余会话会重新生成连续显示序号。交易数据管理不删除行情 K 线或数据质量报告。

交易绩效会话是交易数据管理和交易回放续做的共同入口。管理界面按绩效会话列出交易样本；回放页只有在用户明确选择“继续绩效会话”后，才把该会话恢复为当前工作会话。

继续绩效会话是在原 `session_id` 上恢复回放上下文并追加交易、事件和资金曲线，不 clone、不复制、也不新建替代会话。仅在数据分析页查看历史绩效不会触发续做或改变当前播放器。

按时间段删除交易样本时，以开仓或平仓事件的回放行情时间是否落入时间段为准。任一事件命中就删除整笔交易样本；如果只是持仓过程跨过该时间段，但开仓和平仓事件都不在时间段内，则不删除。

TP/SL 的空值表示未设置。空值不是有效的 `0%` 止盈或止损；界面输入 `0` 时规范化为空值，保存为 `NULL`，恢复后仍显示为空。

## Position display

### Position card（持仓卡）

当前研究会话中一笔未平仓交易的展示单元。一个会话可同时有多张持仓卡；不将多空或不同开仓价的未平仓交易合并为单一方向或均价。

_Avoid_: 汇总持仓、混合持仓

## Decision-event research

### Decision research workspace（决策研究工作区）

数据分析页中研究主观开仓与平仓判断的唯一正式入口，使用“开仓研究”和“平仓研究”两个标签页。旧“事件研究”入口不再拥有独立页面状态或计算口径；保留兼容时只能跳转到决策研究工作区。

正式计算由一套决策研究服务提供，旧事件数据继续可读，但不能继续由重复的旧实现生成新结果。界面主标题使用能说明用途的“决策研究”，不单独使用含义不明的“事件研究”。

### Decision research workflow（决策研究流程）

开仓研究和平仓研究共用的五步工作流：样本复查、相似候选、行为模型、后验对比、版本报告。页面顶部持续显示当前 Setup 版本、方向、三层周期、样本数、独立行情片段数、行情数据完整度和研究成熟度；缺失附加行情时提供“补齐当前研究区间”操作。

两类研究共用流程骨架，但判断标签、持仓状态、后验指标和中文解释必须分别呈现，不能因为复用界面而混用开仓和平仓语义。

五个步骤是可自由进入的研究视图，不是必须顺序完成的向导。切换步骤时保留 Setup 版本、方向、三层周期和筛选条件。证据不足时仍显示目标页面、当前状态、缺失条件和距离门槛的差额；只禁用当前证据不允许执行的训练、正式推断或报告发布操作，不能把整个步骤隐藏或灰掉。

每一步使用“未准备”“可探索”“可正式研究”“已有版本”表达研究成熟度。成熟度描述数据和验证条件，不代表策略质量，也不能使用盈利语义色。

### Blinded review workspace（盲审工作台）

“样本复查”使用三栏工作台。左栏显示当前批次、样本列表和完成进度并允许折叠；中栏同时显示决策周期主图和下方并排的两个更高周期图；右栏显示人工判断、理由、信心等级、备注和保存操作。窗口宽度不足时优先折叠左栏，不能通过挤压主图和判断表单维持三栏。

三张图使用同一决策截止线和联动十字光标。保存前全部截断在决策时点，并隐藏样本来源、真实动作、相似度、模型分数和入队原因。保存后才在原图展开后续走势并把右栏切换为结果解释；原始盲态判断继续可见，后验复标必须创建单独版本，不能覆盖原记录。

### Formal blind-review queue（正式盲审队列）

“相似候选”首先展示候选总体数量、行情片段覆盖、数据完整度、相似度分布和批次构成，不把未判断候选做成按相似度排序的机会榜。正式批次由系统按照当前研究阶段规定的相似、边界和多样性比例生成；未判断候选只显示匿名批次编号和完成状态，不显示单条排名、相似度、参考样本或入队原因，也不允许用户手工挑选正式样本。

保存盲态判断后，系统才解锁该候选的总相似度、分组结构距离、三个参考样本、缺失项和入队原因。已揭示结果与未判断队列必须分区显示。

自由浏览候选只用于理解检索结果。任何在保存盲态判断前通过浏览模式揭示来源、评分或后验数据的候选都永久标记为已揭示，不能进入主要行为模型或正式匹配推断。

### Decision research localization（决策研究汉化）

决策研究中面向用户的标题、按钮、标签页、字段名、筛选项、图例、状态、警告、错误、空状态和报告正文统一使用中文。公式可以保留拉丁字母符号，但必须提供中文名称和符号说明；CSV、JSON 和数据库等机器接口继续使用稳定的英文标识，界面不能直接暴露这些内部值。

发布检查必须识别缺少 `zh_CN` 翻译键和直接显示内部枚举值的问题，不能只依靠人工走查判断是否完成汉化。

### Decision research design language（决策研究设计语言）

决策研究复用应用现有主题令牌、字体、字号、间距、语义色和通用交互组件，不建立只对数据分析页生效的独立视觉体系。开仓研究和平仓研究使用同一布局网格和组件规则，只在判断语义、持仓信息和后验指标确有差异时改变内容。

决策研究必须随应用主题切换正常显示。页面实现不能用页面私有的硬编码颜色、字号、圆角或间距绕过现有设计令牌。筛选栏、步骤导航、状态标签、指标卡、研究表格、图表容器、空状态和错误状态应由开仓研究和平仓研究共享。

绿色和红色只表达交易方向、价格涨跌或有明确定义的正负结果。相似度高或行为模型评分高不使用盈利绿色，避免被误解为交易信号；数据不足使用警告语义色，研究信息使用信息语义色，未完成和中性状态使用中性色。状态不能只靠颜色表达。

图表复用应用已有 K 线、坐标轴、网格和提示框样式并跟随主题。决策研究延续交易终端的紧凑信息密度，不改造成具有另一套留白和控件比例的网页式仪表盘。

### Decision research formula specification（决策研究公式规格）

决策研究公式、符号定义、数据截止点、缺失语义、选择理由、限制和数值算例的唯一中文说明文档。仓库文档与应用内“公式说明”入口读取同一公式版本，不能分别维护两套解释。

公式规格位于 `docs/research/v1.6-decision-research-formulas.md`。修改公式、权重、窗口或距离尺度必须更新规格并发布新公式版本，不能只修改代码。

### Research snapshot report（研究快照报告）

“版本报告”在应用内使用结构化中文页面展示。用户明确执行“发布研究快照”后生成不可变版本；新增行情、标注或模型只提示创建新版本，不能覆盖已发布报告。证据不足、未发现稳定指标或没有可靠差异也是允许发布的研究结果。

导出包包含中文 Markdown 总报告、使用稳定英文键的 JSON manifest、完整样本与系数和验证及 15 项后验结果的 CSV、报告图表 PNG，以及公式版本、应用版本、数据范围、随机种子和文件哈希。报告固定覆盖研究对象、数据质量、标签来源与排除项、相似检索、行为模型、后验对比、限制和版本审计。

界面区分可刷新的“当前草稿”和不可修改的“已发布版本”。v1.6 不引入 PDF 渲染链；以后需要 PDF 时只能从同一不可变快照生成，不能重新计算一套结果。

### Decision event（决策事件）

用户在回放行情时间轴上对一笔交易作出开仓或平仓决定的研究观察点。决策事件必须是开仓决策事件或平仓决策事件，不能用含义不明的“事件”混称两者。

### Entry decision event（开仓决策事件）

用户依据决策时可见信息决定建立一笔独立模拟持仓的决策事件。它用于研究用户为什么入场以及入场后的价格路径，不等同于买入信号。

### Research execution price（研究执行价）

开仓事件研究为 `ENTRY` 与 `REJECT` 统一设定的反事实起点，即决策截止点之后下一根决策周期 K 线的开盘价。后验路径从该价格开始计算；多单价格上涨为正，空单价格下跌为正。缺少下一根 K 线时，后验结果不可用。

研究执行价不替代实际模拟交易成交价。真实成交与真实盈亏属于交易绩效，统一研究执行价属于决策事件的反事实比较，两套结果必须分开命名和展示。

### Entry outcome horizons（开仓后验观察窗口）

开仓事件研究固定观察研究执行后的 1、3、5、10、20 根决策周期 K 线。每个窗口计算方向调整后的期末收盘收益、最大有利变动 `MFE` 和最大不利变动 `MAE`；不同 Setup 不能根据历史结果单独挑选窗口。

这些固定窗口描述入场后的价格路径，不决定实际持有时间。更长持有与具体离场时点由平仓决策研究处理。

### Gross event path（未扣成本事件路径）

开仓事件研究从研究执行价计算的方向调整价格路径，不扣除手续费、滑点或资金费率。它回答判断发生后市场如何运动，不回答某个执行方案的净盈利。

成本只进入带有不可变成本配置版本的策略验证；实际交易绩效继续使用真实模拟成交和已记录成本。修改成本配置不能改变历史事件研究的 MFE、MAE 或方向调整收益。

### Human entry decision（人工开仓判断）

用户对一个候选开仓位置是否符合自己主观开仓标准的判断。人工开仓判断不等同于实际开仓动作；实际开仓可以作为待确认的 `ENTRY` 样本，但允许复盘后纠正。

### Blinded decision annotation（盲态决策标注）

用户只能看到决策截止点及此前三层周期行情、持仓状态和当时可见信息时保存的人工开仓或平仓判断。保存前隐藏未来 K 线、后验收益、MFE、MAE、最终盈亏和未来交易标记；保存后才允许主动揭示后续走势。

盲标阶段还必须隐藏候选来源、是否真实发生过交易、结构相似度、行为模型分数和进入队列的原因。用户保存判断后，系统才揭示来源、评分和后续走势，避免真实动作或模型建议诱导人工标签。

### Post-outcome relabel（后验复标）

用户揭示后续走势后创建或修改的人工判断。后验复标保留用途和审计记录，可以用于复盘描述，但不能进入主要行为模型或正式匹配推断。实际开仓和平仓动作的原始时点事实继续保留，后来的人工判断以新版本记录，不能覆盖原始动作。

### Decision cutoff（决策信息截止点）

人工判断发生时允许研究特征读取到的最后时点。v1.6 的决策信息截止点必须是某根完整 K 线的收盘；任何特征、相似检索或规则归纳都不能读取该时点之后的数据。

### Current-bar-close decision（当前 K 线收盘判断）

Setup 形态和人工判断在同一根完整 K 线收盘后成立。Setup K 线与判断 K 线是同一根 K 线。

### Next-bar-confirmation decision（下一根 K 线确认判断）

Setup 形态出现后，等待至少一根后续 K 线完整收盘再作人工判断。Setup K 线早于判断 K 线；研究特征可以读取到判断 K 线收盘，但不能把确认前的信息当作已知。

### Intrabar timing approximation（盘中时点近似）

实际订单发生在 K 线内部、但缺少逐笔或盘中快照数据时，将决策信息截止点映射到成交前最后一根完整 K 线，并明确标记为时点近似。系统不能用该根 K 线最终的高、低、收、成交量伪造当时可见信息。

### Setup type（Setup 类型）

用户认为候选位置所属的主要交易形态，每个人工开仓判断至多选择一个 Setup 类型。Setup 类型回答“这是什么机会”，不混入判断理由、市场状态或信心程度。

### Setup library（Setup 库）

用户维护的 Setup 类型目录。Setup 可以新增、重命名或归档；已被研究样本引用的 Setup 即使归档也保留其历史身份，不能因目录整理而改变旧样本含义。

### Setup version（Setup 版本）

Setup 判断协议在一个时期内不可变的版本身份。改变判断条件会创建新版本，历史样本继续引用原版本；只有经过明确复标，样本才可以迁移到新版本。

### Timeframe profile（三层周期画像）

一个 Setup 版本固定使用的周期组合，由一个决策周期和两个更高周期背景组成。决策周期用于定位 Setup、作出人工判断和生成候选；两个更高周期只提供决策时已完成 K 线的趋势、波动、位置与成交背景，不能改变决策截止点。

创建 Setup 版本时，系统根据决策周期推荐两个严格递增且受行情源支持的高周期，用户可以在保存前修改。不同三层周期画像的样本和结构相似度不能混算；保存后更换任一周期会改变 Setup 判断协议，必须创建新的 Setup 版本。

在相似检索阶段，两个高周期背景只作为结构相似度的软性组成部分；背景不同可以降低排名，但不能直接淘汰候选。高周期条件只有经过人工判断样本归纳和样本外验证，才可以成为候选策略的硬规则。

v1.6 的市场结构周期差异权重为：决策周期 60%、第一个高周期 25%、第二个高周期 15%。三层市场结构合计占总差异的 90%，日历时间差异独立占 10%。权重属于相似度公式版本；修改权重必须发布新公式版本，旧版本分数不能与新版本直接比较。

### Decision reason（判断理由）

用户作出人工开仓判断时明确注意到的依据，一个判断可以有多个判断理由。判断理由记录用户当时为什么接受、拒绝或无法确定，不替代系统计算的客观指标。

判断理由是等待客观特征解释的研究标签，不是结构相似度或开仓倾向模型的候选输入。系统可以比较勾选与未勾选某理由时的客观指标分布，尝试形成量化映射；证据不足时必须报告尚未发现稳定映射，不能强行生成阈值。自由备注在 v1.6 只供人工阅读，不使用自然语言模型自动提取规则。

### Reason-quantization maturity（理由量化成熟度）

同一 Setup 版本、交易方向和人工判断结果内，某个判断理由从描述性标签发展为候选量化阈值的证据阶段。少于 10 个勾选和 10 个未勾选样本时不生成映射；两组各达到 10 个且各覆盖至少 5 个独立行情片段时，只展示探索性分布与差异；两组各达到 30 个并保留时间上更晚的验证区间后，才允许提出候选阈值。

候选阈值通过样本外验证前不能成为策略规则。不同人工判断结果之间不能混合比较来夸大某个理由的量化差异。

### Decision confidence（信心程度）

用户对本次人工开仓判断确定程度的有序等级。信心程度描述主观把握，不代表后验胜率、预期收益或策略有效性。

信心程度不改变结构相似度，也不作为开仓倾向模型的样本权重。它只用于按信心分层比较行为与结果、优先复查低信心或后来改标的样本，以及检查主观信心是否具有稳定校准关系。

### Market state（市场状态）

决策时可见行情所处的趋势、波动、成交和时间环境。市场状态由可复现的行情数据计算，不要求用户重复手工标注。

### ENTRY（考虑开仓）

用户认为候选位置符合自己的开仓标准，即使当时没有实际建立持仓。`ENTRY` 是人工判断标签，不是买入信号，也不是未来收益标签。

### REJECT（拒绝开仓）

用户检查候选位置后明确认为它不符合自己的开仓标准。没有实际开仓、没有检查或没有标注都不能自动推断为 `REJECT`。

### UNCERTAIN（暂不确定）

用户已检查候选位置，但当前信息不足或判断边界不清，暂时不能给出 `ENTRY` 或 `REJECT`。

`UNCERTAIN` 不编码为数值中间标签，也不参与开仓倾向模型训练。它作为判断边界样本优先进入复查；复查后若改为 `ENTRY` 或 `REJECT`，新标注成为当前有效判断，旧标注保留为审计记录。

### UNLABELED（尚未标注）

候选位置尚未经过人工判断。`UNLABELED` 不是负样本，不表示用户拒绝开仓。

### Entry candidate observation（候选开仓位置）

在决策时可见信息中值得用户复查的市场位置。候选开仓位置可以来自实际开仓、用户手工加入或行为相似检索；进入候选集合不表示它符合开仓标准。

### Behavior-similar candidate（行为相似候选）

因决策时市场结构与同一 Setup 版本下已确认的 `ENTRY` 样本相似而被检索出的 `UNLABELED` 候选开仓位置。相似性只决定复查优先级，不是买入信号，也不能自动生成 `ENTRY`。

### Structural similarity score（结构相似度）

候选位置与同一 Setup 版本、同一交易方向下已确认 `ENTRY` 样本在决策时可见市场结构上的接近程度，取值为 0～100。v1.6 使用可复算的归一化指标距离：三层周期分别汇总价格路径、K 线形态与位置、趋势与波动、成交活跃度四组等权差异，再按 60%、25%、15% 合并；日历时间独立占总差异的 10%。候选最终与最近三个 `ENTRY` 的相似程度合并为检索分数。

结构相似度只用于检索和排列复标队列，不是概率、胜率、开仓倾向或策略有效性。特征不完整时不能把缺失值当作零，不同特征版本的分数不能直接比较。

### Fixed feature-distance scale（固定特征距离尺度）

结构相似度将每项差异映射到固定的 `[0, 1]` 范围，不根据当前样本集合重新拟合缩放参数。自然有界指标按完整取值宽度缩放；ATR 单位指标相差 4 个 ATR 记为完全不同；对数倍数指标相差 4 倍记为完全不同；循环时间距离直接使用其 `[0, 1]` 值。

固定尺度属于相似度公式版本，使新增样本不会重写旧候选之间的距离。中位数/MAD 标准化只用于开仓倾向模型，并且只能在训练集上拟合，不能反向改变结构相似度。

### Similarity feature-completeness gate（相似特征完整度门槛）

结构相似度要求三层周期中的每个市场结构组至少有 80% 指标可计算。通过门槛后，只在候选与参考样本共同可用的指标上计算组内平均，并将该组可用指标的权重重新归一化；任一组低于门槛时拒绝生成分数，并展示具体缺失原因。

只有通过该门槛的 `ENTRY` 才计入相似检索阶段要求的已确认样本数和独立行情片段数。缺失特征、零值和不可计算是不同状态，不能互相替代。

### Episode-diverse nearest references（跨片段最近参考）

候选位置生成结构相似度时使用的三个参考 `ENTRY`，必须来自三个不同的独立行情片段。系统先在每个片段内保留与候选最相似的一个 `ENTRY`，再选择距离最近的三个片段并对其相似度取算术平均。

同一行情片段不能重复增加参考权重。系统必须展示三个参考样本及各自分数；不足三个合格独立参考片段时不生成正式结构相似度。

### Similarity lookback scales（相似检索回看尺度）

v1.6 在三层周期画像的每个周期上使用固定的 5、20、60 根 K 线尺度：5 根描述最近触发动作，20 根描述局部 Setup 结构，60 根描述趋势与波动环境。具体指标只使用有明确含义的尺度，不要求每项指标在三个尺度上机械重复。

回看尺度属于相似度公式版本，不能由单个 Setup 为迎合历史结果而修改。改变尺度需要发布新公式版本并重新验证，旧版本分数不能与新版本直接比较。

### ATR-normalized anchor path（ATR 归一化锚点路径）

价格路径组使用的顺序特征。5 根窗口保留 5 个收盘点，20 根窗口等距压缩为 10 个点，60 根窗口等距压缩为 15 个点。每个锚点表示相对窗口起点的对数价格变化除以该窗口 ATR 百分比，因此不同品种和价格阶段可以按自身波动单位比较。

三个尺度分别计算平均差异后等权合并，长窗口不会因锚点更多而获得更高权重。v1.6 不使用动态时间规整或 K 线图片嵌入来改变路径发生顺序。

### Candle-shape and range-position features（K 线形态与区间位置特征）

结构相似度的第二组特征。判断 K 线记录有向实体占比、上下影线占比和相对 ATR 的振幅；最近 5 根记录阳线比例、实体方向净值和最大上下影线；20 根与 60 根窗口分别记录当前收盘价在区间高低点中的相对位置。

K 线振幅或区间宽度为零时，相应比例属于不可计算，不能写成零。该组描述蜡烛几何与所处位置，不替代价格路径组的先后顺序。

### Trend and volatility features（趋势与波动特征）

结构相似度的第三组特征。20 根与 60 根窗口分别计算有方向的价格效率、波动调整后的对数价格回归斜率，以及收盘价相对 EMA 的 ATR 距离；波动状态记录 `ATR20 / 收盘价`、`ATR5 / ATR20` 和 `ATR20 / ATR60`。

v1.6 的 `ATR(W)` 是最近 W 根真实波幅 `TR` 的简单平均；不使用依赖更早初始值的递归平滑。方向效率描述趋势是否连续，回归斜率描述单位波动下的方向强度，二者不能混称。

### Trading-activity and aggressor features（成交活跃度与主动成交方向特征）

结构相似度的第四组特征。当前计价币成交额和成交笔数分别与此前 20 根、60 根中位数比较；单笔平均成交额与此前 20 根中位数比较；主动买入成交额占比转换为范围 `[-1, 1]` 的方向代理，并记录当前值、最近 5 根均值、20 根均值和短中期差值。

主动买入基础币数量保留用于原始数据核对，但不与主动买入成交额重复进入相似度。成交额或成交笔数小于等于零时，相关指标属于不可计算，不能加入极小常数伪造有限结果。

### Calendar-time distance（日历时间差异）

独立于三层市场结构、只计算一次的时间差异，使用北京时间。日内时间采用跨午夜的循环分钟距离，星期采用七天循环距离，工作日与周末不一致记为完全不同；三项分别占日历时间差异的 60%、20%、20%。

日历时间差异占结构相似度总差异的 10%。v1.6 不预设亚洲盘、欧洲盘或美国盘硬标签，也不根据固定时钟伪造资金费率事件。

### Entry tendency score（开仓倾向分）

Setup 版本达到规则归纳阶段后，由已确认的 `ENTRY` 和 `REJECT` 样本训练出的可解释行为模型分数。它描述某个候选符合用户历史开仓判断的程度，不表示未来盈利概率；模型训练、阈值选择和展示必须与结构相似度分开。

界面对该分数使用“开仓选择倾向”，平仓模型对应使用“立即平仓选择倾向”。不得命名为上涨概率、下跌概率、盈利概率、胜率或买卖信号；页面持续说明它描述过去的人工选择规律，不代表未来收益。v1.6 不把行为倾向送入实盘页面、自动下单或买卖提醒。

### Entry behavior model（开仓行为模型）

v1.6 使用 scikit-learn 求解的弹性网正则逻辑回归，以明确的 `ENTRY = 1`、`REJECT = 0` 为目标生成开仓倾向分。L1 惩罚用于压缩无用指标，L2 惩罚用于减轻相关指标之间的不稳定竞争；每个非零系数必须能映射回中文指标名称和影响方向。

v1.6 不使用随机森林、梯度提升树或神经网络等黑盒模型，也不自行实现数值优化器。模型依赖、超参数、训练数据范围、特征版本和随机种子必须随结果记录。

### Entry behavior model version（开仓行为模型版本）

由用户明确触发训练后生成的不可变研究快照。版本保存 Setup 版本、参考样本与独立行情片段、公式和特征版本、训练与验证范围、标准化参数、正则参数、模型系数、研究阈值、应用版本和随机种子。

新增或修改人工判断只产生“可训练新版本”提示，不自动修改或覆盖既有模型。旧模型、候选分数和报告继续保留；重新训练始终创建新版本，以便复算和比较变化来源。

### Training-only robust normalization（仅训练集稳健标准化）

行为模型在每个时间验证折中，只使用训练区间的中位数和 MAD 标准化特征，并将结果截断到 `[-5, 5]`。`MAD = 0` 的指标从该折模型中删除，不能添加极小常数制造差异；验证、测试和后续候选只能复用该折保存的标准化参数。

标准化参数属于模型版本。任何使用验证期、测试期或全量数据拟合缩放参数的结果都存在信息泄漏，不能作为有效研究结果。

### Class-balanced behavior loss（类别平衡行为损失）

`ENTRY` 与 `REJECT` 数量不同时，行为模型分别使用 `总样本数 / (2 × 该类样本数)` 作为类别损失权重，使两类对训练目标的总贡献相同。每条人工判断仍只出现一次；v1.6 不删除多数类、不复制少数类，也不使用 SMOTE 等方法合成交易结构。

训练报告必须展示两类原始样本数、损失权重和独立行情片段分布，不能只展示平衡后的模型指标。

### Episode-pure temporal validation（行情片段隔离的时间验证）

开仓行为模型按独立行情片段和时间顺序验证，不使用随机拆分。同一片段不能跨越训练、验证或测试集合；较早数据至少进行 3 折扩展窗口验证，最新连续 20% 的片段保留为一次性最终测试集。

达到 30 个 `ENTRY` 和 30 个 `REJECT` 只允许生成探索性行为模型。最终测试集还必须至少包含 10 个 `ENTRY`、10 个 `REJECT`，且两类各覆盖至少 5 个独立行情片段，才能进入验证阶段。测试结果一旦用于修改特征、参数或阈值，该测试集即成为开发数据，必须等待更晚数据作为新的最终测试集。

### Behavior-model regularization selection（行为模型正则选择）

弹性网逻辑回归固定使用 `L1/L2 混合比例 = 0.5`，只在 `C = 0.03、0.1、0.3、1、3` 中选择正则强度。模型以扩展窗口验证的类别平衡对数损失为依据，并在最佳平均损失的一个标准误差范围内选择正则最强、非零指标最少且满足指标数量上限的候选。

v1.6 不同时搜索大量混合比例、正则强度和模型家族。验证集上的微小提升不能优先于更简单、跨折更稳定的模型。

### Entry-tendency research threshold（开仓倾向研究阈值）

根据扩展窗口验证折选择、用于把连续开仓倾向分划为“更像开仓判断”的研究分界。候选阈值要求平均 `ENTRY` 召回率至少 80%，且每个验证折不得低于 70%；满足召回约束后优先选择平均精确率最高的阈值，表现相同时选择更高阈值。

没有阈值满足约束时，系统只展示连续分数并标记“尚无稳定阈值”。研究阈值必须在最终测试前冻结，只影响候选排序或研究分类，不能自动写入 `ENTRY`，也不是交易信号。

### Behavior-model applicability gate（行为模型适用范围门槛）

判断候选是否与行为模型学习过的 Setup 结构足够接近。每个已确认 `ENTRY` 排除其整个独立行情片段后，使用其他片段的 `ENTRY` 计算跨片段结构相似度；至少有 10 个合格 `ENTRY` 独立片段时，取这些分数的第 10 百分位作为门槛。

低于门槛的候选标记为“超出当前模型适用范围”，不生成正式开仓倾向分，也不能进入候选策略。它仍可由用户人工加入复查，以便发现行为边界或新的 Setup。

### Compact behavior feature set（紧凑行为特征集）

开仓倾向模型使用的少量、具备中文业务名称的客观指标集合。细粒度锚点路径只用于结构相似检索，不能把全部锚点坐标直接交给小样本行为模型；价格路径需要先归纳为区间涨跌、低点位置、修复幅度、方向效率等可解释指标。

行为模型可使用的指标数量上限为 `min(12, floor(min(ENTRY 数, REJECT 数) / 5))`。特征筛选只能在训练区间内部完成；刚达到 30 个 `ENTRY` 和 30 个 `REJECT` 时最多使用 6 项，样本增加后仍不得超过 12 项。

### Stable behavior feature（稳定行为指标）

在至少三分之二扩展窗口验证折中获得非零系数，并且所有入选折中的系数方向一致的紧凑行为指标。任一折发生系数正负反转时，该指标不能进入最终模型；最终模型只使用稳定指标重新拟合，并继续受指标数量和研究阈值门槛约束。

训练报告必须展示每项指标的入选频率、系数方向和跨折范围。没有稳定行为指标时，本次实验保存为“未发现稳定行为规律”，不能发布开仓行为模型版本。

### Behavior-model workspace（行为模型工作区）

行为模型页展示模型版本、训练截止时间、原始样本与独立行情片段数、验证状态和适用范围。稳定指标表使用中文指标名称，展示影响方向、标准化系数、跨折入选频率、符号稳定性和通俗解释；验证区展示时间外召回率、精确率、类别平衡对数损失、研究阈值和校准情况，并明确区分探索模型与正式模型。

没有稳定指标、没有可用阈值或超出适用范围都是正式研究结果，界面必须直接说明原因，不能用默认阈值或临时规则补成成功模型。单个候选的指标贡献只允许在人工判断保存并揭示后显示。

### Strategy effectiveness（策略有效性）

冻结候选规则或行为模型后，在时间上更晚且未参与归纳的数据上得到的收益、风险和稳定性证据。结构相似度高或开仓倾向分高都不能替代策略有效性验证。

### Review queue（复标队列）

系统从尚未确认的候选开仓位置中选出的有限复查清单，优先覆盖高相似、判断边界和不同结构。复标队列不是开仓列表。

### Blinded review batch（盲态复查批次）

一次最多包含 20 条且在保存判断前隐藏来源和评分的复查集合。未确认的真实交易种子和人工候选优先形成单独批次；只有相似检索时，自动批次按 70% 高相似和 30% 结构多样组成；行为模型可用后，按 50% 高相似、30% 阈值边界和 20% 结构多样组成。

同一独立行情片段在一批中最多出现一次。合格候选不足时缩小批次，不能通过随机 K 线或降低质量门槛补满；开仓和平仓复查共用该选择原则。

### Similarity readiness gate（相似检索就绪门槛）

判断一个 Setup 版本是否已有足够、完整且分布不过度集中的人工样本，可以开始生成行为相似候选。未通过门槛时，系统明确拒绝自动检索，只接受实际开仓种子和用户手工加入的候选。

### Research maturity stage（研究成熟度阶段）

同一 Setup 版本随人工样本积累逐步获得的研究权限。v1.6 采用以下初始安全门槛：

- **种子阶段**：少于 10 个已确认 `ENTRY`，只允许实际开仓种子和人工加入候选。
- **相似检索阶段**：至少 10 个已确认 `ENTRY`，且来自至少 5 个独立行情片段；只生成探索性的复标队列。
- **规则归纳阶段**：至少 30 个已确认 `ENTRY` 和 30 个已确认 `REJECT`，并且不能主要来自同一行情片段；允许归纳可解释的候选规则。
- **验证阶段**：必须保留一个时间上更晚、未参与归纳的样本区间。未通过样本外验证的结果仍是研究候选，不能称为有效策略。

这些数量是 v1.6 的可调整产品阈值，不代表统计充分性的永久结论。相邻 K 线或同一次市场波动中的多个标注不能直接当作相互独立的样本。

### Independent market episode（独立行情片段）

同一市场驱动下的一次连续交易机会，用于衡量人工样本是否真正来自不同市场经历。只要候选位置的特征回看窗口或结果观察窗口在实际时间上重叠，即使品种或 K 线周期不同，也默认归入同一行情片段，不能重复增加研究成熟度计数。

系统负责自动归组并展示归组依据；用户可以根据实际行情背景合并或拆分，但修改必须保留记录。独立行情片段是防止样本相关性虚增的研究分组，不是交易 Setup。

### Exit decision event（平仓决策事件）

用户决定结束一笔指定模拟持仓的决策事件。它用于研究用户为什么离场、离场避免的后续风险或错过的后续延续，不与开仓结果共用同一解释口径。

### Exit research execution price（研究平仓价）

平仓事件研究为 `EXIT_NOW` 与 `HOLD` 统一设定的反事实起点，即平仓判断截止点之后下一根决策周期 K 线的开盘价。实际模拟平仓价格与研究平仓价分开保存和展示，缺少下一根 K 线时后验结果不可用。

### Exit continuation outcome（平仓后续持有结果）

从研究平仓价继续观察 1、3、5、10、20 根决策周期 K 线的方向调整价格路径。正收益表示继续持有后来有利，负收益表示现在平仓避免了后续损失；后续 MFE 表示错过的最大有利空间，后续 MAE 表示避开的最大不利空间，并记录两者首次出现的 K 线位置。

`EXIT_NOW` 与 `HOLD` 使用相同口径。平仓事件研究不扣交易成本，也不替代实际平仓绩效或带成本的策略验证。

### Matched exit-decision comparison（匹配平仓判断比较）

平仓事件研究对同一 Setup 版本、方向、品种和决策周期的 `EXIT_NOW/HOLD`，使用决策时市场结构与持仓状态执行一对一不重复匹配。它复用 75 分主门槛、70/80 分敏感性检查、`10 对/5 片段` 探索门槛、`30 对/10 片段` 推断门槛，以及行情片段聚类 Bootstrap、符号翻转和 15 项 BH 校正。

平仓判断优势统一定义为 `HOLD 后验结果 - EXIT_NOW 后验结果`。正数表示用户更常在后续有利的位置继续持有、在后续较差的位置退出；负数表示退出判断的方向可能相反。未匹配总体分布只作描述。

### Human exit decision（人工平仓判断）

用户在一笔指定模拟持仓仍然开放时，对当前是否应该结束该持仓的判断。实际平仓动作可以作为待确认的 `EXIT_NOW` 种子，但允许复盘后纠正；没有发生平仓不能自动推断为 `HOLD`。

### Exit research scope（平仓研究分区）

v1.6 的平仓研究按原始开仓所引用的 Setup 版本和交易方向分别建模，回答“对于这种入场逻辑，用户通常在什么持仓状态下退出”。不同开仓 Setup 或方向的 `EXIT_NOW/HOLD` 不能混合训练。

平仓判断复用该 Setup 版本的决策周期和两个高周期背景，不建立独立的平仓 Setup 库，也不在 v1.6 单独选择更低平仓周期。实际平仓发生在决策 K 线内部时，决策信息截止点映射到平仓前最后一根完整决策周期 K 线，并标记为盘中时点近似。

未关联开仓 Setup 版本的历史平仓可以浏览和补标，但在完成关联前不能进入正式平仓行为模型。

### EXIT_NOW（现在平仓）

用户检查当前持仓与行情后，认为应在当前决策截止点之后按统一研究执行规则结束整笔持仓。它是人工判断标签，不等同于已经发生的真实平仓。v1.6 不支持将部分减仓比例标记为 `EXIT_NOW`，也不训练分批退出模型。

### HOLD（继续持有）

用户检查当前持仓与行情后，明确认为现在不应平仓。只有实际完成复查后才能标记为 `HOLD`；持仓期间未操作、未检查的 K 线不是 `HOLD`。

平仓研究沿用 `UNCERTAIN` 表示已检查但暂不能确定，沿用 `UNLABELED` 表示尚未检查。二者都不进入明确的 `EXIT_NOW/HOLD` 行为模型训练。

### Exit behavior model（平仓行为模型）

以明确的 `EXIT_NOW = 1`、`HOLD = 0` 为目标，使用当前市场结构和持仓路径状态解释用户退出判断的弹性网逻辑回归。平仓模型复用开仓模型的紧凑指标数量上限、训练集稳健标准化、类别权重、正则选择、扩展窗口验证、稳定系数、研究阈值和不可变版本规则。

达到 30 个 `EXIT_NOW` 和 30 个 `HOLD` 只允许规则归纳；最终测试仍要求两类各至少 10 个样本和 5 个独立持仓行情片段。阈值优先保证 `EXIT_NOW` 平均召回率至少 80%、单折不低于 70%，但不能自动写入标签或生成平仓信号。

### Exit candidate observation（候选平仓位置）

一笔指定持仓仍处于开放状态时，当前市场结构和持仓状态都与同一开仓 Setup 版本、同一方向下已确认 `EXIT_NOW` 样本相似的复查位置。候选只决定复查优先级，不自动成为 `EXIT_NOW` 或平仓信号。

自动检索要求至少 10 个合格 `EXIT_NOW` 且覆盖至少 5 个独立持仓行情片段。未通过门槛时，只接受实际平仓产生的待确认种子和用户在开放持仓路径上手工加入的候选；普通未操作 K 线不能自动成为候选或 `HOLD`。

### Exit structural similarity（平仓结构相似度）

候选平仓位置与三个不同独立持仓行情片段中的已确认 `EXIT_NOW` 参考样本之间的接近程度。v1.6 的总差异由当前市场结构 50%、持仓状态 40% 和日历时间 10% 组成；市场结构沿用三层周期和四组指标，日历时间沿用北京时间循环距离。

平仓结构相似度只决定复查优先级，不是退出概率或平仓信号。权重与持仓状态特征属于平仓相似度公式版本，修改后必须创建新版本，旧分数不能直接比较。

三层周期的每个市场结构组和持仓状态组都必须至少有 80% 指标可比较。每个独立持仓行情片段最多保留一个参考，再选择三个不同片段中最接近的 `EXIT_NOW` 取算术平均；不足三个合格参考片段时不生成正式分数。只有通过完整度门槛的 `EXIT_NOW` 才计入平仓相似检索就绪门槛。

### Position-path state features（持仓路径状态特征）

平仓结构相似度中的持仓状态，以实际模拟开仓价和开仓决策时冻结的 `ATR20` 为基准。它记录当前方向调整浮动位置、开仓以来的 MFE 与 MAE、当前利润相对 MFE 的回撤、当前位于历史有利/不利区间中的位置、已持有 K 线数、距离最近一次 MFE/MAE 的根数，以及已设置止盈止损的 ATR 距离。

未设置止盈或止损与距离为零含义不同。持有时间使用对数倍数距离，ATR 单位与有界位置指标使用固定特征距离尺度；当前 ATR 不能替换开仓时冻结的 ATR，以免风险单位随持仓过程漂移。

止盈和止损分别记录“是否设置”布尔特征。双方都设置时比较 ATR 距离；只有一方设置时配置差异为完全不同；双方都未设置时距离属于不适用而不是缺失。只有本应存在但无法读取的数据才降低特征完整度。

### Account-pressure context（账户压力环境）

平仓判断时可复现的持仓名义价值占决策前账户权益比例、全部开放持仓总敞口比例、同时开放持仓数量和账户回撤。它用于研究仓位或账户压力是否改变退出行为，不属于市场结构或主要平仓策略特征。

v1.6 记录并单独展示账户压力与 `EXIT_NOW/HOLD` 的关联，但不将其加入平仓结构相似度或主要平仓行为模型。缺少可靠保存的杠杆、保证金或强平信息时不能反推或伪造这些字段。

### Decision-event study（决策事件研究）

分别比较开仓决策事件或平仓决策事件的决策时市场状态与后验结果。它描述当前样本中的行为和结果差异，不研究完整行情序列，也不直接证明策略有效。

_Avoid_: 将开仓和平仓混在同一统计口径下的事件研究

### Matched entry-decision comparison（匹配开仓判断比较）

开仓事件研究的主要比较方式。`ENTRY` 与 `REJECT` 必须属于同一 Setup 版本、交易方向、品种和决策周期，并且只根据决策时可见结构特征寻找相近对照；匹配完成后才能连接后验收益、MFE 和 MAE。差异过大的样本保留但标记为缺少可比对照。

未匹配的总体分布和均值只作描述，不能作为主要行为差异结论。统计推断按独立行情片段聚合，同一行情中的多个判断不能重复增加独立证据数量。

### Entry-decision match caliper（开仓判断配对门槛）

匹配比较使用固定结构距离执行全局一对一最小距离配对，每个 `REJECT` 最多使用一次。主报告只接受两者结构相似度不低于 75 分的配对；70 分和 80 分门槛仅作为预先声明的敏感性检查，不能根据后验结果选择最好看的门槛。

报告必须展示匹配前后数量、未匹配原因和配对相似度分布。配对门槛属于研究公式版本，不能在查看结果后原地修改。

### Matched-event evidence stage（匹配事件证据阶段）

匹配开仓判断比较按合格配对数和独立行情片段数分级。少于 10 对或 5 个片段时为“证据不足”，只显示样本；达到 10 对和 5 个片段后为“探索性结果”；至少达到 30 对和 10 个片段后，才允许执行正式匹配推断。

正式匹配推断只描述当前样本中的决策后路径差异，不代表行为模型已经验证，也不代表策略有效。

### Episode-clustered matched inference（行情片段聚类匹配推断）

每对 `ENTRY/REJECT` 在同一后验指标和窗口上的差异先按独立行情片段取中位数，再以片段为重采样和置换单位。主报告展示片段级配对差中位数、5,000 次聚类 Bootstrap 的 95% 区间和配对秩二列相关；算术平均差只作极端值敏感性补充。

片段级符号翻转置换检验固定 10,000 次并记录随机种子。同一 Setup 版本和方向下，5 个窗口的方向调整收盘收益、MFE、MAE 共 15 项检验统一执行 Benjamini–Hochberg 校正；只有 `q < 0.05` 且 95% 区间不跨零，才标记为“当前样本存在差异证据”。

### Outcome-comparison workspace（后验对比工作区）

后验对比页完整展示固定的 `5 个观察窗口 × 收盘收益/MFE/MAE` 结果矩阵，不能默认选择或只突出表现最好的观察窗口。页面顶部显示可比样本对数、独立行情片段数、主匹配门槛、匹配平衡度和证据等级；每个矩阵单元显示效应方向、片段级中位数差、95% 区间和 BH 校正后的 `q` 值。

用户选择单元格后可以查看行情片段级差异分布、配对样本和 70、75、80 分相似门槛的敏感性结果。正式结论只使用“可比样本不足”“当前样本未发现可靠差异”“当前样本存在差异证据”三种中文状态，并使用研究信息语义色而不是交易通过/失败色。

未匹配原始均值只能放在“描述性结果”区域。版本报告必须包含全部 15 项匹配结果，不能只导出显著结果或最佳窗口；页面和报告持续说明判断后的价格路径差异不等于策略已经有效。

## Decision-event example dialogue

> 研究员：把“长下影开多”和“止盈平仓”放在同一张事件研究表里比较，可以吗？
>
> 开发者：不可以。前者是开仓决策事件，研究入场条件和入场后路径；后者是平仓决策事件，研究离场条件和离场后的延续或风险。
>
> 研究员：我当时没有开仓，可以把这个位置记成 `REJECT` 吗？
>
> 开发者：不能仅凭“没有开仓”推断。你复查后认为不符合标准才是 `REJECT`；符合标准但错过是 `ENTRY`，尚未检查则是 `UNLABELED`。
>
> 研究员：我把“深 V 反转、长下影、放量、主观高确定性”都勾成标签，可以吗？
>
> 开发者：要分开记录。“深 V 反转”是 Setup 类型；“长下影、放量”是判断理由；主观把握记录为信心程度；可计算的市场状态由系统生成。
>
> 研究员：我不再研究“假突破”，可以从 Setup 库里删除吗？
>
> 开发者：可以归档，让它不再用于新标注；已有样本仍保留对该 Setup 的历史引用。
>
> 研究员：我给“深 V 反转”增加了必须放量的条件，旧样本也自动按新条件解释吗？
>
> 开发者：不会。这是新的 Setup 版本；旧样本保留原版本，除非你明确重新标注。
>
> 研究员：系统找到了一个很像我历史开仓的位置，可以直接记成 `ENTRY` 吗？
>
> 开发者：不能。它只是行为相似候选，进入复标队列；只有你确认后才成为 `ENTRY`。
>
> 研究员：一个新 Setup 只有两三个样本，能先生成一些相似 K 线让我看看吗？
>
> 开发者：不能。它还没有通过相似检索就绪门槛；先积累并确认种子样本，系统不会为了产生结果而编造规律。

## Naming example dialogue

> 研究员：把 `sess_489825df` 改成 `2025-04-01—2025-05-01` 可以吗？
>
> 开发者：界面会显示 `BTCUSDT · 5m · 2025-04-01—2025-05-01`，内部仍保留唯一的 `session_id`，历史绩效和导出关联不会改变。
