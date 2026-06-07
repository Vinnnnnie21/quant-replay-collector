from __future__ import annotations

import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

try:
    from app_config import (
        BINANCE_TOP_MARKET_CAP_SYMBOLS,
        DEFAULT_FEE_BPS,
        DEFAULT_FILL_MODE,
        DEFAULT_INITIAL_EQUITY,
        DEFAULT_INTERVAL,
        DEFAULT_SLIPPAGE_BPS,
        DEFAULT_SYMBOL,
        DEFAULT_TRADE_NOTIONAL,
        EVENT_TAGS,
    )
    from execution import FILL_MODES
    from multi_timeframe_panel import MultiTimeframePanel
    from presenters.formatters import fill_mode_label
    from ui_style import (
        SPACING,
        style_danger_button,
        style_primary_button,
        style_secondary_button,
        style_success_button,
    )
    from views.candlestick_item import CandlestickItem
    from views.chart_axis import IndexTimeAxis
    from views.k_view_box import KViewBox
    from views.volume_item import VolumeItem
except ImportError:  # pragma: no cover - package import path
    from ..app_config import (
        BINANCE_TOP_MARKET_CAP_SYMBOLS,
        DEFAULT_FEE_BPS,
        DEFAULT_FILL_MODE,
        DEFAULT_INITIAL_EQUITY,
        DEFAULT_INTERVAL,
        DEFAULT_SLIPPAGE_BPS,
        DEFAULT_SYMBOL,
        DEFAULT_TRADE_NOTIONAL,
        EVENT_TAGS,
    )
    from ..execution import FILL_MODES
    from ..multi_timeframe_panel import MultiTimeframePanel
    from ..presenters.formatters import fill_mode_label
    from ..ui_style import (
        SPACING,
        style_danger_button,
        style_primary_button,
        style_secondary_button,
        style_success_button,
    )
    from .candlestick_item import CandlestickItem
    from .chart_axis import IndexTimeAxis
    from .k_view_box import KViewBox
    from .volume_item import VolumeItem


def build_main_window_ui(self) -> None:
    central = QtWidgets.QWidget()
    self.setCentralWidget(central)
    root = QtWidgets.QVBoxLayout(central)
    root.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
    root.setSpacing(SPACING["md"])

    header = QtWidgets.QFrame()
    header.setProperty("role", "header")
    header.setFixedHeight(56)
    header_l = QtWidgets.QHBoxLayout(header)
    header_l.setContentsMargins(SPACING["lg"], SPACING["sm"], SPACING["lg"], SPACING["sm"])
    header_l.setSpacing(SPACING["lg"])

    title = QtWidgets.QLabel("Quant Replay Collector")
    title.setProperty("role", "appTitle")
    header_l.addWidget(title)

    self.headerMetricLabels = {}

    def metric_block(key: str, label: str, value: str):
        frame = QtWidgets.QFrame()
        frame.setProperty("role", "metricBlock")
        frame_l = QtWidgets.QVBoxLayout(frame)
        frame_l.setContentsMargins(SPACING["md"], SPACING["xs"], SPACING["md"], SPACING["xs"])
        frame_l.setSpacing(0)
        label_widget = QtWidgets.QLabel(label)
        label_widget.setProperty("role", "muted")
        value_widget = QtWidgets.QLabel(value)
        value_widget.setProperty("role", "metric")
        frame_l.addWidget(label_widget)
        frame_l.addWidget(value_widget)
        self.headerMetricLabels[key] = label_widget
        return frame, value_widget

    symbol_block, self.headerSymbolValue = metric_block("symbol", "品种", DEFAULT_SYMBOL)
    interval_block, self.headerIntervalValue = metric_block("time_interval", "周期", DEFAULT_INTERVAL)
    price_block, self.headerCloseValue = metric_block("price_close", "收盘价", "-")
    time_block, self.headerTimeValue = metric_block("kline_time", "K线时间", "-")
    cursor_block, self.headerCursorValue = metric_block("cursor_position", "位置", "0 / 0")
    for block in (symbol_block, interval_block, price_block, time_block, cursor_block):
        header_l.addWidget(block)

    header_l.addStretch(1)
    self.headerPlayBadge = QtWidgets.QLabel("暂停")
    self.headerPlayBadge.setProperty("role", "pillMuted")
    self.headerViewBadge = QtWidgets.QLabel("自由浏览")
    self.headerViewBadge.setProperty("role", "pill")
    self.headerSessionBadge = QtWidgets.QLabel("会话 -")
    self.headerSessionBadge.setProperty("role", "pill")
    header_l.addWidget(self.headerPlayBadge)
    header_l.addWidget(self.headerViewBadge)
    header_l.addWidget(self.headerSessionBadge)
    root.addWidget(header)

    body = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
    body.setChildrenCollapsible(False)
    root.addWidget(body, stretch=1)

    left = QtWidgets.QFrame()
    left.setProperty("role", "sidebar")
    left.setMinimumWidth(330)
    left.setMaximumWidth(380)
    left_l = QtWidgets.QVBoxLayout(left)
    left_l.setContentsMargins(SPACING["sm"], SPACING["sm"], SPACING["sm"], SPACING["sm"])
    left_l.setSpacing(SPACING["md"])

    sidebar_scroll = QtWidgets.QScrollArea()
    sidebar_scroll.setWidgetResizable(True)
    sidebar_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
    sidebar_content = QtWidgets.QWidget()
    sidebar_l = QtWidgets.QVBoxLayout(sidebar_content)
    sidebar_l.setContentsMargins(SPACING["xs"], SPACING["xs"], SPACING["xs"], SPACING["xs"])
    sidebar_l.setSpacing(SPACING["lg"])

    def new_card(title_text: str):
        box = QtWidgets.QGroupBox(title_text)
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(SPACING["lg"], SPACING["sm"], SPACING["lg"], SPACING["lg"])
        layout.setSpacing(SPACING["sm"])
        return box, layout

    data_box, data_l = new_card("行情数据")
    self.dataBox = data_box
    form = QtWidgets.QFormLayout()
    form.setLabelAlignment(QtCore.Qt.AlignLeft)
    form.setSpacing(SPACING["sm"])
    self.symbolBox = QtWidgets.QComboBox()
    self.symbolBox.setProperty("role", "symbolSelector")
    self.symbolBox.setEditable(False)
    self.symbolBox.addItems(BINANCE_TOP_MARKET_CAP_SYMBOLS)
    self.symbolBox.setCurrentText(DEFAULT_SYMBOL)
    self.symbolBox.installEventFilter(self)

    self.intervalBox = QtWidgets.QComboBox()
    self.intervalBox.addItems(["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"])
    self.intervalBox.setCurrentText(DEFAULT_INTERVAL)

    self.startDate = QtWidgets.QDateEdit()
    self.startDate.setCalendarPopup(True)
    self.startDate.setDate(QtCore.QDate.currentDate().addDays(-2))

    self.endDate = QtWidgets.QDateEdit()
    self.endDate.setCalendarPopup(True)
    self.endDate.setDate(QtCore.QDate.currentDate())

    form.addRow("当前品种", self.symbolBox)
    form.addRow("周期", self.intervalBox)
    form.addRow("开始日期", self.startDate)
    form.addRow("结束日期", self.endDate)
    data_l.addLayout(form)
    self.symbolPanel = QtWidgets.QFrame()
    self.symbolPanel.setProperty("role", "metricBlock")
    symbol_panel_l = QtWidgets.QVBoxLayout(self.symbolPanel)
    symbol_panel_l.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
    symbol_panel_l.setSpacing(SPACING["sm"])
    self.symbolSearchEdit = QtWidgets.QLineEdit()
    self.symbolSearchEdit.setPlaceholderText("搜索品种，例如 BTC、ETH、1000PEPE")
    self.symbolList = QtWidgets.QListWidget()
    self.symbolList.setMaximumHeight(140)
    self.symbolList.addItems(BINANCE_TOP_MARKET_CAP_SYMBOLS)
    self.symbolPanel.setVisible(False)
    symbol_panel_l.addWidget(self.symbolSearchEdit)
    symbol_panel_l.addWidget(self.symbolList)
    data_l.addWidget(self.symbolPanel)

    sidebar_l.addWidget(data_box)

    replay_box, replay_l = new_card("回放控制")
    self.replayBox = replay_box
    self.btnLoadPlay = QtWidgets.QPushButton("加载K线")
    self.btnStep = QtWidgets.QPushButton("下一根 (→)")
    self.btnToEnd = QtWidgets.QPushButton("跳到末尾")
    self.btnFollow = QtWidgets.QPushButton("跟随最新 (F)")
    self.btnResetView = QtWidgets.QPushButton("重置缩放 (K)")
    self.btnLoadPlay.setStyleSheet(style_primary_button())
    for btn in (self.btnStep, self.btnToEnd, self.btnFollow, self.btnResetView):
        btn.setStyleSheet(style_secondary_button())

    grid = QtWidgets.QGridLayout()
    grid.setHorizontalSpacing(SPACING["sm"])
    grid.setVerticalSpacing(SPACING["sm"])
    grid.addWidget(self.btnLoadPlay, 0, 0, 1, 2)
    grid.addWidget(self.btnStep, 1, 0)
    grid.addWidget(self.btnToEnd, 1, 1)
    grid.addWidget(self.btnFollow, 2, 0)
    grid.addWidget(self.btnResetView, 2, 1)
    replay_l.addLayout(grid)
    self.speedLabel = QtWidgets.QLabel("速度: 1.0x")
    self.speedLabel.setProperty("role", "muted")
    self.speedSlider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
    self.speedSlider.setMinimum(1)
    self.speedSlider.setMaximum(1000)
    self.speedSlider.setValue(10)
    replay_l.addWidget(self.speedLabel)
    replay_l.addWidget(self.speedSlider)
    sidebar_l.addWidget(replay_box)

    trade_box, trade_l = new_card("交易操作")
    self.tradeBox = trade_box
    trade_grid = QtWidgets.QGridLayout()
    trade_grid.setContentsMargins(0, 0, 0, 0)
    trade_grid.setHorizontalSpacing(SPACING["sm"])
    trade_grid.setVerticalSpacing(SPACING["sm"])
    self.btnOpenLong = QtWidgets.QPushButton("开多 (B)")
    self.btnOpenShort = QtWidgets.QPushButton("开空 (S)")
    self.btnCloseLong = QtWidgets.QPushButton("平多 (C)")
    self.btnCloseShort = QtWidgets.QPushButton("平空 (X)")
    self.btnUndo = QtWidgets.QPushButton("撤销 (Ctrl+Z)")
    self.btnRedo = QtWidgets.QPushButton("重做 (Ctrl+Y)")
    self.btnClearTradeRecords = QtWidgets.QPushButton("清空全部交易样本")
    self.btnOpenLong.setStyleSheet(style_success_button())
    self.btnOpenShort.setStyleSheet(style_danger_button())
    for btn in (self.btnCloseLong, self.btnCloseShort, self.btnUndo, self.btnRedo):
        btn.setStyleSheet(style_secondary_button())
    self.btnClearTradeRecords.setStyleSheet(style_danger_button())
    trade_grid.addWidget(self.btnOpenLong, 0, 0)
    trade_grid.addWidget(self.btnOpenShort, 0, 1)
    trade_grid.addWidget(self.btnCloseLong, 1, 0)
    trade_grid.addWidget(self.btnCloseShort, 1, 1)
    trade_grid.addWidget(self.btnUndo, 2, 0)
    trade_grid.addWidget(self.btnRedo, 2, 1)
    trade_grid.addWidget(self.btnClearTradeRecords, 3, 0, 1, 2)
    trade_l.addLayout(trade_grid)
    sidebar_l.addWidget(trade_box)

    exec_box, exec_l = new_card("交易成本设置")
    exec_form = QtWidgets.QFormLayout()
    exec_form.setContentsMargins(0, 0, 0, 0)
    exec_form.setSpacing(SPACING["sm"])
    self.fillModeBox = QtWidgets.QComboBox()
    for mode in FILL_MODES:
        self.fillModeBox.addItem(fill_mode_label(mode), mode)
    self._set_fill_mode_value(DEFAULT_FILL_MODE)
    self.feeBpsSpin = QtWidgets.QDoubleSpinBox()
    self.feeBpsSpin.setRange(0.0, 100.0)
    self.feeBpsSpin.setDecimals(2)
    self.feeBpsSpin.setValue(DEFAULT_FEE_BPS)
    self.slippageBpsSpin = QtWidgets.QDoubleSpinBox()
    self.slippageBpsSpin.setRange(0.0, 100.0)
    self.slippageBpsSpin.setDecimals(2)
    self.slippageBpsSpin.setValue(DEFAULT_SLIPPAGE_BPS)
    self.tradeNotionalSpin = QtWidgets.QDoubleSpinBox()
    self.tradeNotionalSpin.setRange(1.0, 1_000_000_000.0)
    self.tradeNotionalSpin.setDecimals(2)
    self.tradeNotionalSpin.setValue(DEFAULT_TRADE_NOTIONAL)
    self.initialEquitySpin = QtWidgets.QDoubleSpinBox()
    self.initialEquitySpin.setRange(1.0, 1_000_000_000.0)
    self.initialEquitySpin.setDecimals(2)
    self.initialEquitySpin.setValue(DEFAULT_INITIAL_EQUITY)
    exec_form.addRow("成交模式", self.fillModeBox)
    exec_form.addRow("手续费 bps", self.feeBpsSpin)
    exec_form.addRow("滑点 bps", self.slippageBpsSpin)
    exec_form.addRow("每笔名义金额", self.tradeNotionalSpin)
    exec_form.addRow("初始权益", self.initialEquitySpin)
    exec_l.addLayout(exec_form)
    self.executionSettingsBox = exec_box
    self.executionSettingsBox.setVisible(False)

    tag_box, tag_l = new_card("事件标签与备注")
    self.tagBox = tag_box
    self.tag_checks = []
    tag_grid = QtWidgets.QGridLayout()
    tag_grid.setHorizontalSpacing(SPACING["sm"])
    tag_grid.setVerticalSpacing(SPACING["sm"])
    for idx, tag in enumerate(EVENT_TAGS):
        cb = QtWidgets.QCheckBox(tag)
        cb.setProperty("role", "tagChip")
        self.tag_checks.append(cb)
        tag_grid.addWidget(cb, idx // 2, idx % 2)
    tag_l.addLayout(tag_grid)
    self.noteEdit = QtWidgets.QPlainTextEdit()
    self.noteEdit.setPlaceholderText("这条备注会写入选中的事件，或随新建的交易事件一起保存。")
    self.noteEdit.setFixedHeight(82)
    self.eventHintLabel = QtWidgets.QLabel("先选择事件可编辑标签；未选择事件时，当前标签会随下一次开仓或平仓写入。")
    self.eventHintLabel.setProperty("role", "muted")
    self.eventHintLabel.setWordWrap(True)
    self.btnApplyEventMeta = QtWidgets.QPushButton("应用标签 / 备注")
    self.btnApplyEventMeta.setStyleSheet(style_secondary_button())
    tag_l.addWidget(self.noteEdit)
    tag_l.addWidget(self.eventHintLabel)
    tag_l.addWidget(self.btnApplyEventMeta)
    sidebar_l.addWidget(tag_box)

    export_box, export_l = new_card("底部工具")
    self.toolsBox = export_box
    self.btnExport = QtWidgets.QPushButton("导出会话 (E)")
    self.btnAnalysis = QtWidgets.QPushButton("数据分析")
    self.btnSettings = QtWidgets.QPushButton("设置")
    self.btnTheme = self.btnSettings
    self.btnExport.setStyleSheet(style_primary_button())
    self.btnAnalysis.setStyleSheet(style_secondary_button())
    self.btnSettings.setStyleSheet(style_secondary_button())
    export_l.addWidget(self.btnExport)
    export_l.addWidget(self.btnAnalysis)
    export_l.addWidget(self.btnSettings)
    sidebar_l.addWidget(export_box)
    sidebar_l.addStretch(1)

    sidebar_scroll.setWidget(sidebar_content)
    left_l.addWidget(sidebar_scroll)

    center = QtWidgets.QFrame()
    center.setProperty("role", "chartCard")
    center_l = QtWidgets.QVBoxLayout(center)
    center_l.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
    center_l.setSpacing(SPACING["sm"])
    self.status = QtWidgets.QLabel("未加载数据")
    self.status.setProperty("role", "muted")
    center_l.addWidget(self.status)

    self.glw = pg.GraphicsLayoutWidget()
    center_l.addWidget(self.glw, stretch=1)

    self.axis_price = IndexTimeAxis('bottom')
    self.axis_vol = IndexTimeAxis('bottom')
    self.vb_price = KViewBox()
    self.vb_vol = KViewBox()
    self.pricePlot = self.glw.addPlot(row=0, col=0, viewBox=self.vb_price, axisItems={'bottom': self.axis_price})
    self.volPlot = self.glw.addPlot(row=1, col=0, viewBox=self.vb_vol, axisItems={'bottom': self.axis_vol})
    self.volPlot.setXLink(self.pricePlot)
    self.volPlot.setMaximumHeight(220)
    self.pricePlot.showGrid(x=True, y=True, alpha=0.25)
    self.volPlot.showGrid(x=True, y=True, alpha=0.25)
    self.pricePlot.hideButtons()
    self.volPlot.hideButtons()
    for plot in (self.pricePlot, self.volPlot):
        try:
            plot.buttonsHidden = True
            plot.autoBtn.hide()
            plot.autoBtn.setEnabled(False)
        except Exception:
            pass
        try:
            plot.getViewBox().enableAutoRange(x=False, y=False)
        except Exception:
            pass

    self.currentPriceLine = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen('#FF5252', style=QtCore.Qt.DashLine, width=1))
    self.currentPriceLabel = pg.TextItem(
        '',
        anchor=(1, 0.5),
        color='#06110c',
        fill=pg.mkBrush('#2fd182'),
        border=pg.mkPen('#2fd182'),
    )
    self.pricePlot.addItem(self.currentPriceLine, ignoreBounds=True)
    self.pricePlot.addItem(self.currentPriceLabel, ignoreBounds=True)

    self.candleItem = CandlestickItem()
    self.volItem = VolumeItem()
    self.pricePlot.addItem(self.candleItem)
    self.volPlot.addItem(self.volItem)

    self.scatter_open_long = pg.ScatterPlotItem(symbol='t1', size=14, brush=pg.mkBrush('#00C853'), pen=pg.mkPen('#00C853'))
    self.scatter_open_short = pg.ScatterPlotItem(symbol='t', size=14, brush=pg.mkBrush('#FF9800'), pen=pg.mkPen('#FF9800'))
    self.scatter_close_long = pg.ScatterPlotItem(symbol='x', size=12, brush=pg.mkBrush('#26C6DA'), pen=pg.mkPen('#26C6DA'))
    self.scatter_close_short = pg.ScatterPlotItem(symbol='x', size=12, brush=pg.mkBrush('#AB47BC'), pen=pg.mkPen('#AB47BC'))
    for item in (self.scatter_open_long, self.scatter_open_short, self.scatter_close_long, self.scatter_close_short):
        self.pricePlot.addItem(item)

    right = QtWidgets.QFrame()
    right.setProperty("role", "rightPanel")
    right_l = QtWidgets.QVBoxLayout(right)
    right_l.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
    right_l.setSpacing(SPACING["sm"])

    self.openTradesTable = QtWidgets.QTableWidget()
    self.openTradesTable.setColumnCount(10)
    self.openTradesTable.setHorizontalHeaderLabels([
        "交易ID", "方向", "入场时间", "代理价", "成交价",
        "手续费", "名义金额", "K线", "状态", "成交模式",
    ])
    self._setup_table(self.openTradesTable)

    self.closedTradesTable = QtWidgets.QTableWidget()
    self.closedTradesTable.setColumnCount(13)
    self.closedTradesTable.setHorizontalHeaderLabels([
        "交易ID", "方向", "入场", "出场", "入场成交", "出场成交",
        "毛收益%", "净收益%", "手续费", "净盈亏", "持仓K线", "状态", "成交模式",
    ])
    self._setup_table(self.closedTradesTable)

    self.eventTable = QtWidgets.QTableWidget()
    self.eventTable.setColumnCount(8)
    self.eventTable.setHorizontalHeaderLabels(["事件ID", "交易ID", "事件", "方向", "K线时间", "代理价", "标签", "备注"])
    self._setup_table(self.eventTable)
    self.eventFilterTag = QtWidgets.QComboBox()
    self.eventFilterTag.addItems(["全部标签", *EVENT_TAGS])
    self.eventFilterSide = QtWidgets.QComboBox()
    self.eventFilterSide.addItem("全部方向", "")
    self.eventFilterSide.addItem("多", "LONG")
    self.eventFilterSide.addItem("空", "SHORT")
    self.eventFilterType = QtWidgets.QComboBox()
    self.eventFilterType.addItem("全部事件", "")
    self.eventFilterType.addItem("开仓", "OPEN")
    self.eventFilterType.addItem("平仓", "CLOSE")
    event_filters = QtWidgets.QHBoxLayout()
    event_filters.addWidget(self.eventFilterTag)
    event_filters.addWidget(self.eventFilterSide)
    event_filters.addWidget(self.eventFilterType)
    self.eventTab = QtWidgets.QWidget()
    event_tab_layout = QtWidgets.QVBoxLayout(self.eventTab)
    event_tab_layout.setContentsMargins(0, 0, 0, 0)
    event_tab_layout.addLayout(event_filters)
    event_tab_layout.addWidget(self.eventTable)

    self.performanceText = QtWidgets.QPlainTextEdit()
    self.performanceText.setReadOnly(True)
    self.performanceText.setMinimumHeight(160)
    self.performanceText.setPlainText("暂无交易统计")

    self.equityTable = QtWidgets.QTableWidget()
    self.equityTable.setColumnCount(8)
    self.equityTable.setHorizontalHeaderLabels([
        "序号", "交易ID", "权益前", "净盈亏", "手续费", "权益后", "收益%", "回撤%",
    ])
    self._setup_table(self.equityTable)

    self.eventStudyTable = QtWidgets.QTableWidget()
    self.eventStudyTable.setColumnCount(9)
    self.eventStudyTable.setHorizontalHeaderLabels([
        "标签", "事件", "方向", "样本数", "未来1均值", "未来3均值", "未来5均值", "未来10均值", "未来1胜率",
    ])
    self._setup_table(self.eventStudyTable)

    self.datasetText = QtWidgets.QPlainTextEdit()
    self.datasetText.setReadOnly(True)
    self.datasetText.setMinimumHeight(160)
    self.datasetText.setPlainText("暂无机器学习样本信息。导出后会生成特征表、标签表和样本索引。")

    tabs = QtWidgets.QTabWidget()
    self.rightTabs = tabs
    tabs.addTab(self.openTradesTable, "当前仓位")
    tabs.addTab(self.eventTab, "事件")
    self.multiTimeframePanel = MultiTimeframePanel(language=self.current_language, parent=self)
    tabs.addTab(self.multiTimeframePanel, "多周期上下文")
    self.backtestPanel = None
    self.strategyConsistencyPanel = None

    detail_box = QtWidgets.QGroupBox("选中对象详情")
    self.detailBox = detail_box
    detail_l = QtWidgets.QVBoxLayout(detail_box)
    self.btnToggleDetail = QtWidgets.QPushButton("隐藏详情")
    self.btnToggleDetail.setCheckable(True)
    self.btnToggleDetail.setStyleSheet(style_secondary_button())
    self.detailText = QtWidgets.QPlainTextEdit()
    self.detailText.setReadOnly(True)
    self.detailText.setPlainText("无")
    self.detailText.setMinimumHeight(260)
    detail_l.addWidget(self.btnToggleDetail)
    detail_l.addWidget(self.detailText)
    tabs.addTab(detail_box, "详情")

    self.premiumBox = QtWidgets.QWidget()
    premium_l = QtWidgets.QVBoxLayout(self.premiumBox)
    premium_l.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
    premium_l.setSpacing(SPACING["sm"])
    self.premiumStatus = QtWidgets.QLabel("等待采样...")
    self.premiumStatus.setProperty("role", "pill")
    self.premiumStats = QtWidgets.QPlainTextEdit()
    self.premiumStats.setReadOnly(True)
    self.premiumStats.setMaximumHeight(110)
    self.premiumStats.setPlainText("-")
    self.premiumPlot = pg.PlotWidget()
    self.premiumPlot.showGrid(x=True, y=True, alpha=0.25)
    self.premiumPlot.addLegend(offset=(8, 8))
    self.premiumBuyCurve = self.premiumPlot.plot([], [], pen=pg.mkPen('#42A5F5', width=1.5, style=QtCore.Qt.DashLine), symbol='o', symbolSize=4, name='买入溢价')
    self.premiumSellCurve = self.premiumPlot.plot([], [], pen=pg.mkPen('#FFB300', width=1.5, style=QtCore.Qt.DotLine), symbol='t', symbolSize=4, name='卖出溢价')
    self.premiumAvgCurve = self.premiumPlot.plot([], [], pen=pg.mkPen('#AB47BC', width=1.8), symbol='s', symbolSize=4, name='均价溢价')
    premium_l.addWidget(self.premiumStatus)
    premium_l.addWidget(self.premiumStats)
    premium_l.addWidget(self.premiumPlot, stretch=1)
    right_l.addWidget(tabs, stretch=1)

    body.addWidget(left)
    body.addWidget(center)
    body.addWidget(right)
    body.setStretchFactor(0, 0)
    body.setStretchFactor(1, 2)
    body.setStretchFactor(2, 1)
    body.setSizes([350, 1040, 520])

    self.logDrawer = QtWidgets.QFrame()
    self.logDrawer.setProperty("role", "logDrawer")
    self.logDrawer.setMaximumHeight(170)
    log_l = QtWidgets.QVBoxLayout(self.logDrawer)
    log_l.setContentsMargins(SPACING["md"], SPACING["sm"], SPACING["md"], SPACING["md"])
    log_l.setSpacing(SPACING["sm"])
    log_header = QtWidgets.QHBoxLayout()
    log_title = QtWidgets.QLabel("操作日志")
    log_title.setProperty("role", "muted")
    self.btnToggleLog = QtWidgets.QPushButton("折叠")
    self.btnToggleLog.setStyleSheet(style_secondary_button())
    self.btnToggleLog.setCheckable(True)
    log_header.addWidget(log_title)
    log_header.addStretch(1)
    log_header.addWidget(self.btnToggleLog)
    self.log = QtWidgets.QPlainTextEdit()
    self.log.setReadOnly(True)
    self.log.setMaximumBlockCount(3000)
    self.log.setMaximumHeight(105)
    log_l.addLayout(log_header)
    log_l.addWidget(self.log)
    root.addWidget(self.logDrawer)

    self._add_shortcut("Space", self.toggle_play)
    self._add_shortcut(QtCore.Qt.Key_Right, self.step_once)
    self._add_shortcut("F", self.toggle_follow)
    self._add_shortcut("B", lambda: self.request_open_trade("LONG"))
    self._add_shortcut("S", lambda: self.request_open_trade("SHORT"))
    self._add_shortcut("C", lambda: self.request_close_trade("LONG"))
    self._add_shortcut("X", lambda: self.request_close_trade("SHORT"))
    self._add_shortcut("Ctrl+Z", self.undo)
    self._add_shortcut("Ctrl+Y", self.redo)
    self._add_shortcut("E", self.export_session)
    self._add_shortcut("K", self.reset_view)
    self._update_header()
    self._update_load_play_button()
    self.retranslate_ui()


__all__ = ["build_main_window_ui"]
