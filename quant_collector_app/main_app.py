from __future__ import annotations

import json
import math
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from app_config import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_INTERVAL,
    DEFAULT_SYMBOL,
    DEFAULT_INITIAL_EQUITY,
    DEFAULT_TRADE_NOTIONAL,
    DEFAULT_FEE_BPS,
    DEFAULT_SLIPPAGE_BPS,
    DEFAULT_FILL_MODE,
    EVENT_TAGS,
    BINANCE_TOP_MARKET_CAP_SYMBOLS,
    BJT,
    EXPORT_DIR,
    DEFAULT_THEME,
    THEME_PRESETS,
    load_theme_settings,
    save_theme_settings,
)
from app_logger import get_logger, install_exception_hook
from app_i18n import tr as i18n_tr
from app_settings import load_app_settings, save_app_settings
from execution import ExecutionSettings, FILL_MODES
from market_data import (
    LoadRequest,
    bjt_now_iso,
    clamp,
)
from premium_monitor import PremiumWorker
from premium_controller import PremiumController
from replay_controller import ReplayController
from state import AppState
from startup import bootstrap_runtime_dirs, configure_logging
from storage import StorageManager
from views.candlestick_item import CandlestickItem
from views.chart_axis import IndexTimeAxis
from trade_controller import TradeController
from views.chart_view import visible_bar_bounds
from views.k_view_box import KViewBox
from views.theme_dialog import ThemeDialog
from views.volume_item import VolumeItem
from workers.loader_worker import LoaderWorker
from ui_style import (
    COLORS,
    SPACING,
    build_app_qss,
    style_danger_button,
    style_primary_button,
    style_secondary_button,
    style_success_button,
)


ROLE_ID = QtCore.Qt.UserRole
logger = get_logger(__name__)


@dataclass
class ActionCommand:
    name: str
    do_fn: Callable[[], None]
    undo_fn: Callable[[], None]

    def do(self):
        self.do_fn()

    def undo(self):
        self.undo_fn()


class MainWindow(QtWidgets.QMainWindow):
    requestLoad = QtCore.Signal(object)
    requestPremium = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1820, 980)

        self.storage = StorageManager()
        self.trade_controller = TradeController(self.storage, export_version=APP_VERSION)
        self.exporter = None
        self.export_controller = None
        self.premium_controller = PremiumController()
        self.replay_controller = ReplayController()
        self.app_state = AppState()
        self._export_thread = None
        self._export_worker = None
        self._export_success_callback = None

        self.df = pd.DataFrame()
        self.cursor = 0
        self._drawn_n = -1
        self._last_cursor_for_series = -1
        self._accum = 0.0
        self._last_tick = QtCore.QElapsedTimer()
        self._last_tick.start()
        self.playing = False
        self.follow_latest = False
        self.user_view_lock = False
        self.last_user_interaction = 0.0
        self.window_bars = 140
        self.pad_right = 8
        self._base_bars_per_sec = 1.0
        self.manual_xrange: tuple[float, float] | None = None
        self._programmatic_view_update = False
        self._loading_data = False
        self._render_dirty = True
        self.theme_settings = load_theme_settings()
        self.app_settings = load_app_settings()
        self.current_language = str(self.app_settings.get("language") or "zh_CN")

        self.session_id = None
        self.restoring_session_id = None
        self.restore_snapshot_pending = False

        self.trades: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.undo_stack: list[ActionCommand] = []
        self.redo_stack: list[ActionCommand] = []
        self._is_replaying_history = False
        self._event_by_id: dict[str, dict[str, Any]] = {}
        self._trade_by_id: dict[str, dict[str, Any]] = {}
        self._shortcuts: list[QtGui.QShortcut] = []
        self._analysis_workspace = None

        self.loader_thread = QtCore.QThread(self)
        self.loader = LoaderWorker()
        self.loader.moveToThread(self.loader_thread)
        self.loader_thread.start()

        self.premium_thread = QtCore.QThread(self)
        self.premium_worker = PremiumWorker()
        self.premium_worker.moveToThread(self.premium_thread)
        self.premium_thread.start()

        self._build_ui()
        self._connect()
        self._install_theme()
        self.apply_theme(self.theme_settings)

        self.timer = QtCore.QTimer(self)
        self.timer.setTimerType(QtCore.Qt.PreciseTimer)
        self.timer.timeout.connect(self.on_timer)
        self.timer.start(16)

        self.autosave_timer = QtCore.QTimer(self)
        self.autosave_timer.timeout.connect(self.persist_session_state)
        self.autosave_timer.start(2000)

        self.premium_timer = QtCore.QTimer(self)
        self.premium_timer.timeout.connect(self.request_premium_sample)
        self.premium_timer.start(30_000)
        self.request_premium_sample()

        self._restore_latest_session_if_any()

    def closeEvent(self, event: QtGui.QCloseEvent):
        try:
            self.persist_session_state()
        except Exception:
            logger.exception("关闭窗口时保存会话失败")
            pass
        try:
            self.loader.abort()
        except Exception:
            pass
        for t in (self.loader_thread, self.premium_thread):
            try:
                t.quit()
                t.wait(1000)
            except Exception:
                pass
        if self._export_thread is not None:
            try:
                self._export_worker.cancel()
                self._export_thread.quit()
                self._export_thread.wait(1000)
            except Exception:
                pass
        super().closeEvent(event)

    # ---------- UI ----------
    def _build_ui(self):
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
        self.btnResetView = QtWidgets.QPushButton("重置视图 (K)")
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
            self.fillModeBox.addItem(self._fill_mode_label(mode), mode)
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

    def _setup_table(self, table: QtWidgets.QTableWidget):
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.verticalHeader().setDefaultSectionSize(28)
        header = table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setDefaultAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        header.setMinimumSectionSize(72)
        header.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)

    def tr(self, key: str, default: str | None = None) -> str:
        return i18n_tr(key, self.current_language, default)

    def apply_language(self, language: str):
        self.current_language = str(language or "zh_CN")
        settings = load_app_settings()
        settings["language"] = self.current_language
        save_app_settings(settings)
        self.retranslate_ui()
        for attr in ("_analysis_workspace",):
            widget = getattr(self, attr, None)
            if widget is not None and hasattr(widget, "retranslate_ui"):
                widget.retranslate_ui()

    def retranslate_ui(self):
        if not hasattr(self, "btnExport"):
            return
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION} - {self.tr('trading_replay')}")
        for key, label in getattr(self, "headerMetricLabels", {}).items():
            label.setText(self.tr(key))
        for widget_name, key in (
            ("dataBox", "market_data"),
            ("replayBox", "replay_control"),
            ("tradeBox", "trade_actions"),
            ("tagBox", "event_tags_notes"),
            ("toolsBox", "tools"),
        ):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.setTitle(self.tr(key))
        self.btnStep.setText(f"{self.tr('step_next')} (→)")
        self.btnToEnd.setText(self.tr("jump_to_end"))
        self.btnFollow.setText(f"{self.tr('follow_latest')} (F)")
        self.btnResetView.setText(f"{self.tr('reset_view')} (K)")
        self.btnOpenLong.setText(f"{self.tr('open_long')} (B)")
        self.btnOpenShort.setText(f"{self.tr('open_short')} (S)")
        self.btnCloseLong.setText(f"{self.tr('close_long')} (C)")
        self.btnCloseShort.setText(f"{self.tr('close_short')} (X)")
        self.btnUndo.setText(f"{self.tr('undo')} (Ctrl+Z)")
        self.btnRedo.setText(f"{self.tr('redo')} (Ctrl+Y)")
        self.btnClearTradeRecords.setText(self.tr("clear_trade_records"))
        self.btnExport.setText(f"{self.tr('export_session')} (E)")
        self.btnAnalysis.setText(self.tr("data_analysis"))
        self.btnSettings.setText(self.tr("settings"))
        self.rightTabs.setTabText(self.rightTabs.indexOf(self.openTradesTable), self.tr("current_positions"))
        self.rightTabs.setTabText(self.rightTabs.indexOf(self.eventTab), self.tr("events"))
        self.rightTabs.setTabText(self.rightTabs.indexOf(self.detailBox), self.tr("details"))
        if hasattr(self, "backtestPanel") and hasattr(self.backtestPanel, "retranslate_ui"):
            self.backtestPanel.retranslate_ui()
        if hasattr(self, "strategyConsistencyPanel") and hasattr(self.strategyConsistencyPanel, "retranslate_ui"):
            self.strategyConsistencyPanel.retranslate_ui()
        self._update_header()
        self._update_load_play_button()

    def _add_shortcut(self, sequence, handler):
        shortcut = QtGui.QShortcut(QtGui.QKeySequence(sequence), self)
        shortcut.setContext(QtCore.Qt.WindowShortcut)

        def guarded_handler():
            if self._focus_is_text_entry():
                return
            handler()

        shortcut.activated.connect(guarded_handler)
        self._shortcuts.append(shortcut)
        return shortcut

    def _focus_is_text_entry(self) -> bool:
        widget = QtWidgets.QApplication.focusWidget()
        text_widgets = (
            QtWidgets.QLineEdit,
            QtWidgets.QTextEdit,
            QtWidgets.QPlainTextEdit,
            QtWidgets.QSpinBox,
            QtWidgets.QDoubleSpinBox,
            QtWidgets.QComboBox,
            QtWidgets.QDateEdit,
        )
        while widget is not None:
            if isinstance(widget, text_widgets):
                return True
            widget = widget.parentWidget()
        return False

    def eventFilter(self, obj, event):
        if obj is getattr(self, "symbolBox", None) and event.type() == QtCore.QEvent.MouseButtonPress:
            self.toggle_symbol_panel(not self.symbolPanel.isVisible())
            return True
        return super().eventFilter(obj, event)

    def _install_theme(self):
        QtWidgets.QApplication.instance().setStyle("Fusion")
        pg.setConfigOptions(antialias=False)

    def _set_widget_role(self, widget: QtWidgets.QWidget, role: str):
        widget.setProperty("role", role)
        style = widget.style()
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)
        widget.update()

    def apply_theme(self, theme: dict):
        self.theme_settings = dict(DEFAULT_THEME)
        self.theme_settings.update(theme or {})
        if self.theme_settings.get("name") not in THEME_PRESETS:
            self.theme_settings["name"] = DEFAULT_THEME.get("name", "交易暗色")
        app = QtWidgets.QApplication.instance()
        pal = QtGui.QPalette()
        pal.setColor(QtGui.QPalette.Window, QtGui.QColor(self.theme_settings['window_bg']))
        pal.setColor(QtGui.QPalette.WindowText, QtGui.QColor(self.theme_settings['text']))
        pal.setColor(QtGui.QPalette.Base, QtGui.QColor(self.theme_settings['base_bg']))
        pal.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(self.theme_settings['panel_bg']))
        pal.setColor(QtGui.QPalette.Text, QtGui.QColor(self.theme_settings['text']))
        pal.setColor(QtGui.QPalette.Button, QtGui.QColor(self.theme_settings['panel_bg']))
        pal.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(self.theme_settings['text']))
        pal.setColor(QtGui.QPalette.Highlight, QtGui.QColor(45, 125, 255))
        pal.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(0, 0, 0))
        app.setPalette(pal)

        self.setStyleSheet(build_app_qss(self.theme_settings))

        grid_alpha = max(0.0, min(1.0, self.theme_settings['grid_alpha'] / 100.0))
        try:
            self.glw.setBackground(self.theme_settings['base_bg'])
        except Exception:
            pass

        for plot in (self.pricePlot, self.volPlot):
            vb = plot.getViewBox()
            if vb is not None and hasattr(vb, 'setBackgroundColor'):
                try:
                    vb.setBackgroundColor(self.theme_settings['base_bg'])
                except Exception:
                    pass
            plot.showGrid(x=True, y=True, alpha=grid_alpha)
            for side in ('left', 'bottom', 'right', 'top'):
                ax = plot.getAxis(side)
                if ax is not None:
                    ax.setPen(pg.mkPen(self.theme_settings['axis']))
                    ax.setTextPen(pg.mkPen(self.theme_settings['axis']))

        try:
            self.premiumPlot.setBackground(self.theme_settings['base_bg'])
        except Exception:
            pass
        self.premiumPlot.showGrid(x=True, y=True, alpha=grid_alpha)
        premium_item = self.premiumPlot.getPlotItem() if hasattr(self.premiumPlot, 'getPlotItem') else None
        if premium_item is not None:
            for side in ('left', 'bottom', 'right', 'top'):
                ax = premium_item.getAxis(side)
                if ax is not None:
                    ax.setPen(pg.mkPen(self.theme_settings['axis']))
                    ax.setTextPen(pg.mkPen(self.theme_settings['axis']))

        self.candleItem._pen_up = pg.mkPen(self.theme_settings['candle_up'])
        self.candleItem._pen_dn = pg.mkPen(self.theme_settings['candle_down'])
        self.candleItem._brush_up = pg.mkBrush(self.theme_settings['candle_up'])
        self.candleItem._brush_dn = pg.mkBrush(self.theme_settings['candle_down'])
        self.candleItem._wick_pen = pg.mkPen(self.theme_settings['wick'])
        self.volItem._brush_up = pg.mkBrush(self.theme_settings['volume_up'])
        self.volItem._brush_dn = pg.mkBrush(self.theme_settings['volume_down'])
        self.scatter_open_long.setBrush(pg.mkBrush(self.theme_settings['candle_up']))
        self.scatter_open_long.setPen(pg.mkPen(self.theme_settings['candle_up']))
        self.scatter_open_short.setBrush(pg.mkBrush(self.theme_settings['premium_sell']))
        self.scatter_open_short.setPen(pg.mkPen(self.theme_settings['premium_sell']))
        self.scatter_close_long.setBrush(pg.mkBrush('#26C6DA'))
        self.scatter_close_long.setPen(pg.mkPen('#26C6DA'))
        self.scatter_close_short.setBrush(pg.mkBrush(self.theme_settings['premium_avg']))
        self.scatter_close_short.setPen(pg.mkPen(self.theme_settings['premium_avg']))
        self.premiumBuyCurve.setPen(pg.mkPen(self.theme_settings['premium_buy'], width=1.5, style=QtCore.Qt.DashLine))
        self.premiumSellCurve.setPen(pg.mkPen(self.theme_settings['premium_sell'], width=1.5, style=QtCore.Qt.DotLine))
        self.premiumAvgCurve.setPen(pg.mkPen(self.theme_settings['premium_avg'], width=1.8))
        self.candleItem._rebuild()
        self.volItem._rebuild()
        self._update_header()
        save_theme_settings(self.theme_settings)
        self._render(force=True)

    def open_theme_dialog(self):
        dlg = ThemeDialog(self.theme_settings, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self.apply_theme(dlg.get_theme())
            self._log('已应用主题设置。')

    def open_settings_dialog(self):
        from settings_dialog import SettingsDialog

        dlg = SettingsDialog(self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._update_header()
            self._log("已应用设置。")

    def open_analysis_workspace(self):
        from analysis_workspace import AnalysisWorkspace

        if self.backtestPanel is None:
            from backtest_panel import BacktestPanel

            self.backtestPanel = BacktestPanel(self)
        if self.strategyConsistencyPanel is None:
            from strategy_consistency_panel import StrategyConsistencyPanel

            self.strategyConsistencyPanel = StrategyConsistencyPanel(self)
        if not hasattr(self, "_analysis_workspace") or self._analysis_workspace is None:
            self._analysis_workspace = AnalysisWorkspace(self)
        try:
            self._analysis_workspace.refresh()
        except Exception as exc:
            self._log(f"数据分析页刷新失败：{type(exc).__name__}: {exc}")
        self._analysis_workspace.show()
        self._analysis_workspace.raise_()
        self._analysis_workspace.activateWindow()

    def toggle_detail_panel(self, hidden: bool):
        self.detailText.setVisible(not hidden)
        self.btnToggleDetail.setText('显示详情' if hidden else '隐藏详情')

    def toggle_log_drawer(self, collapsed: bool):
        self.log.setVisible(not collapsed)
        self.logDrawer.setMaximumHeight(48 if collapsed else 170)
        self.btnToggleLog.setText("展开" if collapsed else "折叠")

    def toggle_symbol_panel(self, expanded: bool):
        self.symbolPanel.setVisible(expanded)
        if expanded:
            self.symbolSearchEdit.setFocus()

    def filter_symbol_list(self, text: str):
        keyword = text.strip().upper()
        self.symbolList.clear()
        for symbol in BINANCE_TOP_MARKET_CAP_SYMBOLS:
            if not keyword or keyword in symbol:
                self.symbolList.addItem(symbol)

    def on_symbol_item_selected(self, item: QtWidgets.QListWidgetItem):
        if item is not None:
            self._set_symbol_value(item.text())
            self.toggle_symbol_panel(False)

    def _set_symbol_value(self, symbol: str):
        value = str(symbol or "").strip().upper()
        if not value:
            return
        if self.symbolBox.findText(value, QtCore.Qt.MatchFixedString) < 0:
            self.symbolBox.addItem(value)
        self.symbolBox.setCurrentText(value)

    @staticmethod
    def _fill_mode_label(mode: Any) -> str:
        labels = {
            "MID": "中间价",
            "CLOSE": "收盘价",
            "OPEN": "开盘价",
        }
        return labels.get(str(mode or "").upper(), str(mode or ""))

    def _fill_mode_value(self) -> str:
        data = self.fillModeBox.currentData()
        value = data if data is not None else self.fillModeBox.currentText()
        return str(value or DEFAULT_FILL_MODE).strip().upper()

    def _set_fill_mode_value(self, mode: Any):
        value = str(mode or DEFAULT_FILL_MODE).strip().upper()
        for idx in range(self.fillModeBox.count()):
            if str(self.fillModeBox.itemData(idx) or "").upper() == value:
                self.fillModeBox.setCurrentIndex(idx)
                return
        self.fillModeBox.addItem(self._fill_mode_label(value), value)
        self.fillModeBox.setCurrentIndex(self.fillModeBox.count() - 1)

    @staticmethod
    def _side_label(side: Any) -> str:
        return {"LONG": "多", "SHORT": "空"}.get(str(side or "").upper(), str(side or ""))

    @staticmethod
    def _status_label(status: Any) -> str:
        return {"OPEN": "未平仓", "CLOSED": "已平仓"}.get(str(status or "").upper(), str(status or ""))

    @staticmethod
    def _event_type_label(event_type: Any) -> str:
        return {"OPEN": "开仓", "CLOSE": "平仓"}.get(str(event_type or "").upper(), str(event_type or ""))

    def on_price_view_range_changed(self, _viewbox, view_range):
        if self._programmatic_view_update:
            return
        try:
            x0, x1 = view_range[0]
        except Exception:
            return
        if not (math.isfinite(x0) and math.isfinite(x1) and x1 > x0):
            return
        self.manual_xrange = (float(x0), float(x1))
        self._render_dirty = True

    def _connect(self):
        self.btnLoadPlay.clicked.connect(self.load_or_toggle_play)
        self.btnStep.clicked.connect(self.step_once)
        self.btnToEnd.clicked.connect(self.jump_to_end)
        self.btnFollow.clicked.connect(self.toggle_follow)
        self.btnResetView.clicked.connect(self.reset_view)
        self.btnExport.clicked.connect(self.export_session)
        self.btnAnalysis.clicked.connect(self.open_analysis_workspace)
        self.btnSettings.clicked.connect(self.open_settings_dialog)
        self.btnOpenLong.clicked.connect(lambda: self.request_open_trade("LONG"))
        self.btnOpenShort.clicked.connect(lambda: self.request_open_trade("SHORT"))
        self.btnCloseLong.clicked.connect(lambda: self.request_close_trade("LONG"))
        self.btnCloseShort.clicked.connect(lambda: self.request_close_trade("SHORT"))
        self.btnUndo.clicked.connect(self.undo)
        self.btnRedo.clicked.connect(self.redo)
        self.btnClearTradeRecords.clicked.connect(self.confirm_clear_trade_records)
        self.btnApplyEventMeta.clicked.connect(self.apply_labels_to_selected_event)
        self.symbolSearchEdit.textChanged.connect(self.filter_symbol_list)
        self.symbolList.itemClicked.connect(self.on_symbol_item_selected)
        self.symbolList.itemActivated.connect(self.on_symbol_item_selected)
        self.symbolBox.currentTextChanged.connect(lambda _: self._update_header())
        self.intervalBox.currentTextChanged.connect(lambda _: self._update_header())
        self.speedSlider.valueChanged.connect(self.on_speed_changed)
        for widget in (self.fillModeBox, self.feeBpsSpin, self.slippageBpsSpin, self.tradeNotionalSpin, self.initialEquitySpin):
            try:
                widget.valueChanged.connect(self.on_execution_settings_changed)
            except AttributeError:
                widget.currentTextChanged.connect(self.on_execution_settings_changed)
        self.requestLoad.connect(self.loader.load, QtCore.Qt.QueuedConnection)
        self.loader.progress.connect(self.on_load_progress)
        self.loader.finished.connect(self.on_loaded)
        self.requestPremium.connect(self.premium_worker.fetch_once, QtCore.Qt.QueuedConnection)
        self.premium_worker.finished.connect(self.on_premium_sample)
        self.vb_price.userInteracted.connect(self.on_user_interaction)
        self.vb_vol.userInteracted.connect(self.on_user_interaction)
        self.vb_price.sigXRangeChanged.connect(self.on_price_view_range_changed)
        self.openTradesTable.itemSelectionChanged.connect(self.on_open_trade_selected)
        self.closedTradesTable.itemSelectionChanged.connect(self.on_closed_trade_selected)
        self.eventTable.itemSelectionChanged.connect(self.on_event_selected)
        self.eventFilterTag.currentTextChanged.connect(lambda _text: self._refresh_tables())
        self.eventFilterSide.currentIndexChanged.connect(lambda _index: self._refresh_tables())
        self.eventFilterType.currentIndexChanged.connect(lambda _index: self._refresh_tables())
        self.openTradesTable.itemDoubleClicked.connect(lambda item: self.jump_to_trade_row(item))
        self.closedTradesTable.itemDoubleClicked.connect(lambda item: self.jump_to_trade_row(item))
        self.eventTable.itemDoubleClicked.connect(lambda item: self.jump_to_event_row(item))
        self.btnToggleDetail.toggled.connect(self.toggle_detail_panel)
        self.btnToggleLog.toggled.connect(self.toggle_log_drawer)

    # ---------- Session ----------
    def _restore_latest_session_if_any(self):
        last = self.storage.get_latest_session()
        if not last:
            self.session_id = self._new_id("sess")
            return
        try:
            self.restoring_session_id = last["session_id"]
            self.session_id = last["session_id"]
            if last.get("symbol"):
                self._set_symbol_value(last["symbol"])
            if last.get("interval"):
                self.intervalBox.setCurrentText(last["interval"])
            if last.get("start_date_bjt"):
                self.startDate.setDate(QtCore.QDate.fromString(last["start_date_bjt"], "yyyy-MM-dd"))
            if last.get("end_date_bjt"):
                self.endDate.setDate(QtCore.QDate.fromString(last["end_date_bjt"], "yyyy-MM-dd"))
            self.follow_latest = bool(last.get("follow_latest", 0))
            speed = float(last.get("speed") or 1.0)
            self.speedSlider.setValue(max(1, min(1000, int(speed * 10))))
            self.initialEquitySpin.setValue(float(last.get("initial_equity") or DEFAULT_INITIAL_EQUITY))
            self.tradeNotionalSpin.setValue(float(last.get("trade_notional") or DEFAULT_TRADE_NOTIONAL))
            self.feeBpsSpin.setValue(float(last.get("fee_bps") or DEFAULT_FEE_BPS))
            self.slippageBpsSpin.setValue(float(last.get("slippage_bps") or DEFAULT_SLIPPAGE_BPS))
            self._set_fill_mode_value(last.get("fill_mode") or DEFAULT_FILL_MODE)
            self.restore_snapshot_pending = True
            self._log(f"发现历史会话，准备恢复 会话ID={self.session_id}")
            QtCore.QTimer.singleShot(100, lambda: self.load_data(restore=True))
        except Exception as e:
            logger.exception("恢复历史会话失败")
            self._log(f"恢复会话失败：{type(e).__name__}: {e}")
            self.session_id = self._new_id("sess")

    def persist_session_state(self):
        if not self.session_id:
            return
        latest_session = self.storage.get_latest_session()
        if latest_session and latest_session.get("session_id") == self.session_id:
            last_opened_at = latest_session.get("last_opened_at") or bjt_now_iso()
        else:
            last_opened_at = bjt_now_iso()
        self.storage.upsert_session(
            {
                "session_id": self.session_id,
                "symbol": self.symbolBox.currentText().strip().upper(),
                "interval": self.intervalBox.currentText().strip(),
                "start_date_bjt": self.startDate.date().toString("yyyy-MM-dd"),
                "end_date_bjt": self.endDate.date().toString("yyyy-MM-dd"),
                "cursor_bar_index": int(self.cursor),
                "follow_latest": 1 if self.follow_latest else 0,
                "speed": self.current_speed(),
                "last_opened_at": last_opened_at,
                "last_saved_at": bjt_now_iso(),
                "app_version": APP_VERSION,
                "initial_equity": float(self.initialEquitySpin.value()),
                "trade_notional": float(self.tradeNotionalSpin.value()),
                "fee_bps": float(self.feeBpsSpin.value()),
                "slippage_bps": float(self.slippageBpsSpin.value()),
                "fill_mode": self._fill_mode_value(),
            }
        )

    def confirm_clear_trade_records(self):
        if self._loading_data or self.app_state.export.running:
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("clear_trade_records_title"),
                self.tr("clear_trade_records_busy"),
            )
            return
        response = QtWidgets.QMessageBox.warning(
            self,
            self.tr("clear_trade_records_title"),
            self.tr("clear_trade_records_warning"),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
            QtWidgets.QMessageBox.Cancel,
        )
        if response != QtWidgets.QMessageBox.Yes:
            return
        phrase, accepted = QtWidgets.QInputDialog.getText(
            self,
            self.tr("clear_trade_records_title"),
            self.tr("clear_trade_records_phrase_prompt"),
        )
        if not accepted:
            return
        if phrase.strip() != self.tr("clear_trade_records_phrase"):
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("clear_trade_records_title"),
                self.tr("clear_trade_records_phrase_mismatch"),
            )
            return
        try:
            deleted = self.storage.clear_manual_research_records()
        except Exception as exc:
            self._operation_error(self.tr("clear_trade_records_failed"), exc)
            return

        self.playing = False
        self._accum = 0.0
        self.trades.clear()
        self.events.clear()
        self._trade_by_id.clear()
        self._event_by_id.clear()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.restoring_session_id = None
        self.restore_snapshot_pending = False
        self.session_id = self._new_id("sess")
        for checkbox in self.tag_checks:
            checkbox.setChecked(False)
        self.noteEdit.clear()
        self.detailText.setPlainText(self.tr("none"))
        self.replay_controller.load_state(self.cursor, False, self.follow_latest, 0.0)
        self.persist_session_state()
        self._sync_markers()
        self._refresh_tables()
        self._render_dirty = True
        self._render(force=True)
        if self._analysis_workspace is not None:
            try:
                self._analysis_workspace.refresh()
            except Exception:
                logger.exception("Failed to refresh analysis workspace after clearing trade samples")
        message = self.tr("clear_trade_records_done").format(**deleted)
        self._log(message)
        QtWidgets.QMessageBox.information(self, self.tr("clear_trade_records_title"), message)

    def _new_id(self, prefix: str):
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    # ---------- Data load ----------
    def _normalized_symbol(self) -> str | None:
        symbol = self.symbolBox.currentText().strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{3,30}", symbol):
            QtWidgets.QMessageBox.warning(self, "品种格式错误", "品种只能包含大写字母和数字，例如 BTCUSDT。")
            return None
        return symbol

    def load_data(self, restore: bool = False, use_cache: bool | None = None):
        self.playing = False
        self._accum = 0.0
        self.replay_controller.load_state(self.cursor, False, self.follow_latest, 0.0)
        symbol = self._normalized_symbol()
        if symbol is None:
            return
        self._set_symbol_value(symbol)
        interval = self.intervalBox.currentText().strip()
        d0 = self.startDate.date()
        d1 = self.endDate.date()
        if d0 > d1:
            QtWidgets.QMessageBox.warning(self, "日期范围错误", "开始日期不能晚于结束日期。")
            return
        start_dt = QtCore.QDateTime(d0, QtCore.QTime(0, 0)).toPython().replace(tzinfo=BJT)
        end_dt = QtCore.QDateTime(d1, QtCore.QTime(23, 59, 59)).toPython().replace(tzinfo=BJT)
        use_cache = bool(restore) if use_cache is None else bool(use_cache)

        if restore and self.restoring_session_id:
            self.session_id = self.restoring_session_id
        else:
            self.session_id = self._new_id("sess")
            self.trades.clear()
            self.events.clear()
            self._trade_by_id.clear()
            self._event_by_id.clear()
            self.undo_stack.clear()
            self.redo_stack.clear()
            self.restore_snapshot_pending = False

        self.persist_session_state()
        self.status.setText(f"{symbol} {interval} 加载中...")
        self._loading_data = True
        self.app_state.data_load.loading = True
        self.app_state.data_load.status_message = f"Loading {symbol} {interval}"
        self._update_load_play_button()
        self._update_header()
        self.requestLoad.emit(LoadRequest(symbol=symbol, interval=interval, start_dt_bjt=start_dt, end_dt_bjt=end_dt, use_cache=use_cache))

    def on_load_progress(self, message: str):
        self.app_state.data_load.status_message = message
        self.status.setText(message)
        self._log(message)

    def on_loaded(self, df: pd.DataFrame, message: str):
        self._loading_data = False
        self.app_state.data_load.loading = False
        self._log(message)
        if message.startswith("加载失败"):
            logger.error("数据加载失败：%s", message)
        elif "在线刷新失败" in message or "缓存不可用" in message:
            logger.warning("数据加载警告：%s", message)
        incoming_attrs = dict(getattr(df, "attrs", {}))
        self.df = df.reset_index(drop=True) if isinstance(df, pd.DataFrame) else pd.DataFrame()
        self.df.attrs.update(incoming_attrs)
        self.app_state.data_load.bar_count = len(self.df)
        self.app_state.data_load.source = str(self.df.attrs.get("data_source", "-"))
        quality_report = self.df.attrs.get("data_quality_report", {})
        self.app_state.data_load.quality_status = (
            str(quality_report.get("data_quality_status", "-")) if isinstance(quality_report, dict) else "-"
        )
        self.cursor = 0
        self._drawn_n = -1
        self._last_cursor_for_series = -1
        self._accum = 0.0
        self.replay_controller.reset()
        self.replay_controller.follow_latest = self.follow_latest
        self._render_dirty = True

        if self.df.empty and message.startswith("加载失败"):
            QtWidgets.QMessageBox.critical(self, "K线加载失败", message)
        elif not self.df.empty:
            self._persist_loaded_market_data()

        if len(self.df):
            self.axis_price.set_times(self.df["open_time_bjt"].to_numpy())
            self.axis_vol.set_times(self.df["open_time_bjt"].to_numpy())
        else:
            self.axis_price.set_times([])
            self.axis_vol.set_times([])

        if not self.restore_snapshot_pending:
            self.trades.clear()
            self.events.clear()
            self._trade_by_id.clear()
            self._event_by_id.clear()
            self._refresh_tables()

        try:
            self.vb_price.disableAutoRange()
            self.vb_vol.disableAutoRange()
        except Exception:
            pass

        self._rebuild_items()
        default_span = min(self.window_bars, max(40, min(len(self.df), 80))) if len(self.df) else 40
        self.manual_xrange = (-0.5, max(20.0, float(default_span)))
        self._set_xrange(*self.manual_xrange, force=True)
        self.status.setText(f"{self.symbolBox.currentText().strip().upper()} {self.intervalBox.currentText().strip()} K线={len(self.df)}")
        self._update_load_play_button()
        self._render(force=True)

        if self.restore_snapshot_pending and self.session_id:
            self.restore_snapshot_pending = False
            _, trades, events = self.storage.load_session_snapshot(self.session_id)
            self.trades = trades
            self.events = events
            self._trade_by_id = {t["trade_id"]: t for t in self.trades}
            self._event_by_id = {e["event_id"]: e for e in self.events}
            latest_session = self.storage.get_latest_session()
            if latest_session and latest_session.get("session_id") == self.session_id:
                self.cursor = int(latest_session.get("cursor_bar_index") or 0)
                self.follow_latest = bool(latest_session.get("follow_latest") or 0)
                self.replay_controller.load_state(self.cursor, False, self.follow_latest)
            self._sync_equity_curve()
            self._refresh_tables()
            self._render(force=True)
            self._log(f"已恢复交易={len(self.trades)}，事件={len(self.events)}")

    def _persist_loaded_market_data(self):
        report = self.df.attrs.get("data_quality_report")
        source = str(self.df.attrs.get("data_source") or "unknown")
        if not isinstance(report, dict):
            return
        try:
            self.storage.save_data_quality_report({**report, "report_json": json.dumps(report, ensure_ascii=False)})
            downloaded_at = report.get("created_at")
            quality_status = report.get("data_quality_status")
            self.storage.upsert_klines(
                {
                    "symbol": self.symbolBox.currentText().strip().upper(),
                    "interval": self.intervalBox.currentText().strip(),
                    "open_time_utc_ms": int(row["open_time_ms"]),
                    "open_time_bjt": pd.to_datetime(row["open_time_bjt"]).isoformat(),
                    "close_time_utc_ms": int(row["close_time_ms"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                    "source": source,
                    "downloaded_at": downloaded_at,
                    "data_quality_status": quality_status,
                }
                for _, row in self.df.iterrows()
            )
        except Exception as exc:
            logger.exception("Kline quality persistence failed.")
            self._log(f"数据质量记录保存失败：{type(exc).__name__}: {exc}")

    # ---------- Playback ----------
    def load_or_toggle_play(self):
        if self._loading_data:
            return
        if self.df.empty:
            self.load_data()
        else:
            self.toggle_play()

    def _update_load_play_button(self):
        if not hasattr(self, "btnLoadPlay"):
            return
        if self._loading_data:
            self.btnLoadPlay.setText(self.tr("loading"))
            self.btnLoadPlay.setEnabled(False)
        elif self.df.empty:
            self.btnLoadPlay.setText(self.tr("load_klines"))
            self.btnLoadPlay.setEnabled(True)
        elif self.playing:
            self.btnLoadPlay.setText(f"{self.tr('pause')} (Space)")
            self.btnLoadPlay.setEnabled(True)
        else:
            self.btnLoadPlay.setText(f"{self.tr('play')} (Space)")
            self.btnLoadPlay.setEnabled(True)

    def on_speed_changed(self, value: int):
        self.speedLabel.setText(f"速度: {self.current_speed():.1f}x")

    def current_speed(self):
        return max(0.1, float(self.speedSlider.value()) / 10.0)

    def execution_settings(self) -> ExecutionSettings:
        return self.trade_controller.execution_settings(
            self._fill_mode_value(),
            self.feeBpsSpin.value(),
            self.slippageBpsSpin.value(),
            self.tradeNotionalSpin.value(),
        )

    def on_execution_settings_changed(self, *_):
        try:
            self.persist_session_state()
            self._sync_equity_curve()
            self._refresh_tables()
        except Exception as e:
            self._log(f"更新模拟成交参数失败：{type(e).__name__}: {e}")

    def _sync_equity_curve(self):
        from accounting import build_equity_curve

        if not self.session_id:
            return
        rows = build_equity_curve(
            self.trades,
            self.session_id,
            float(self.initialEquitySpin.value()),
            float(self.tradeNotionalSpin.value()),
        )
        self.trade_controller.replace_equity_curve(self.session_id, rows)

    def on_timer(self):
        if len(self.df) == 0:
            return
        elapsed = self._last_tick.restart() / 1000.0
        try:
            self.replay_controller.load_state(self.cursor, self.playing, self.follow_latest, self._accum)
            changed = self.replay_controller.tick(elapsed, len(self.df), self.current_speed(), self._base_bars_per_sec)
            self.cursor = self.replay_controller.cursor
            self.playing = self.replay_controller.playing
            self._accum = self.replay_controller.accumulated_bars
            if changed or self.cursor != self._last_cursor_for_series:
                self._rebuild_items()
                self._last_cursor_for_series = int(self.cursor)
                self._render_dirty = True
            self._render(force=False)
        except Exception as e:
            logger.exception("播放定时器异常")
            self._log(f"timer异常：{type(e).__name__}: {e}")
            self.playing = False

    def toggle_play(self):
        if len(self.df) == 0:
            return
        self.replay_controller.load_state(self.cursor, self.playing, self.follow_latest, self._accum)
        self.playing = self.replay_controller.toggle_play(len(self.df))
        self._log("播放" if self.playing else "暂停")
        self._last_tick.restart()
        self._update_load_play_button()
        self._render_dirty = True
        self._render(force=False)

    def step_once(self):
        if len(self.df) == 0:
            return
        self.replay_controller.load_state(self.cursor, self.playing, self.follow_latest, self._accum)
        self.cursor = self.replay_controller.step(len(self.df))
        self.playing = self.replay_controller.playing
        self._accum = self.replay_controller.accumulated_bars
        self._rebuild_items()
        self._last_cursor_for_series = int(self.cursor)
        self._update_load_play_button()
        self._render(force=True)

    def jump_to_end(self):
        if len(self.df) == 0:
            return
        self.replay_controller.load_state(self.cursor, self.playing, self.follow_latest, self._accum)
        self.cursor = self.replay_controller.jump_end(len(self.df))
        self._rebuild_items(n=len(self.df))
        self._last_cursor_for_series = int(self.cursor)
        self.user_view_lock = False
        self.playing = self.replay_controller.playing
        self._update_load_play_button()
        self._render(force=True)

    def toggle_follow(self):
        self.replay_controller.load_state(self.cursor, self.playing, self.follow_latest, self._accum)
        self.follow_latest = self.replay_controller.toggle_follow()
        self._log(f"跟随最新：{'开启' if self.follow_latest else '关闭'}")
        if self.follow_latest:
            self.user_view_lock = False
            curr = self._current_xrange()
            if curr is not None:
                self.manual_xrange = curr
        self._render(force=True)

    def on_user_interaction(self):
        self.user_view_lock = True
        self.last_user_interaction = QtCore.QDateTime.currentMSecsSinceEpoch() / 1000.0
        if self.follow_latest:
            self.follow_latest = False
            self._log("检测到手动缩放/拖动，已自动退出跟随最新。")

    def reset_view(self):
        if len(self.df) == 0:
            return
        span = min(self.window_bars, max(40, min(len(self.df), 120)))
        x1 = float(min(self.cursor + self.pad_right, len(self.df) - 1 + self.pad_right))
        x0 = max(0.0, x1 - span)
        self.manual_xrange = (x0, x1)
        self.user_view_lock = False
        self._set_xrange(x0, x1, force=True)
        self._render(force=True)
        self._log("已重置视图。")

    def _rebuild_items(self, n=None):
        if self.df.empty:
            self.candleItem.set_data(np.array([]), np.array([]), np.array([]), np.array([]), np.array([]))
            self.volItem.set_data(np.array([]), np.array([]), np.array([]))
            self._drawn_n = 0
            return
        n = int(clamp((self.cursor + 1) if n is None else n, 0, len(self.df)))
        if self._drawn_n == n and n <= 2000:
            return
        start, end = visible_bar_bounds(n, self._current_xrange())
        d = self.df.iloc[start:end]
        x = np.arange(start, end, dtype=float)
        o = d["open"].to_numpy(dtype=float)
        h = d["high"].to_numpy(dtype=float)
        l = d["low"].to_numpy(dtype=float)
        c = d["close"].to_numpy(dtype=float)
        v = d["volume"].to_numpy(dtype=float)
        up = c >= o
        self.candleItem.set_data(x, o, h, l, c)
        self.volItem.set_data(x, v, up)
        self._drawn_n = n

    def _current_xrange(self):
        try:
            (x0, x1), _ = self.vb_price.viewRange()
            if math.isfinite(x0) and math.isfinite(x1) and x1 > x0:
                return float(x0), float(x1)
        except Exception:
            pass
        return None

    def _set_xrange(self, x0: float, x1: float, force: bool = False):
        x0, x1 = self._clamp_xrange(x0, x1)
        current = self._current_xrange()
        if (not force) and current is not None and abs(current[0] - x0) < 1e-6 and abs(current[1] - x1) < 1e-6:
            return
        self._programmatic_view_update = True
        try:
            self.pricePlot.setXRange(x0, x1, padding=0.0)
        finally:
            self._programmatic_view_update = False
        self.manual_xrange = (x0, x1)

    def _clamp_xrange(self, x0: float, x1: float):
        if self.df.empty:
            return x0, x1
        span = max(3.0, x1 - x0)
        xmin = 0.0
        xmax = max(float(self.cursor) + self.pad_right, span)
        if x0 < xmin:
            x0 = xmin
            x1 = x0 + span
        if x1 > xmax:
            x1 = xmax
            x0 = x1 - span
        if x0 < xmin:
            x0 = xmin
        return x0, x1

    def _soft_follow_should_apply(self):
        if not self.follow_latest or self.df.empty:
            return False
        now = QtCore.QDateTime.currentMSecsSinceEpoch() / 1000.0
        if self.user_view_lock and (now - self.last_user_interaction) < 1.2:
            (x0, x1), _ = self.vb_price.viewRange()
            return x1 >= (self.cursor - 6)
        return True

    def _autoscale_y(self, x0, x1):
        if self.df.empty or self.cursor < 0:
            return
        available_n = self.cursor + 1
        i0 = int(clamp(math.floor(x0), 0, available_n - 1))
        i1 = int(clamp(math.ceil(x1), 0, available_n - 1))
        if i1 <= i0:
            i1 = min(available_n - 1, i0 + 1)
        visible = self.df.iloc[i0:i1 + 1]
        if visible.empty:
            return
        lmin = float(visible["low"].min())
        hmax = float(visible["high"].max())
        if abs(hmax - lmin) < 1e-9:
            hmax += 1.0
            lmin -= 1.0
        self.pricePlot.setYRange(lmin, hmax, padding=0.0)
        vmax = float(visible["volume"].max()) if len(visible) else 1.0
        self.volPlot.setYRange(0.0, max(vmax, 1.0), padding=0.0)

    def _sync_markers(self):
        cur = self.cursor
        open_long, open_short, close_long, close_short = [], [], [], []
        for ev in self.events:
            idx = ev.get("bar_index")
            if idx is None or idx > cur or idx >= len(self.df):
                continue
            if ev["event_type"] == "OPEN" and ev["side"] == "LONG":
                open_long.append((idx, float(self.df.iloc[idx]["low"])))
            elif ev["event_type"] == "OPEN" and ev["side"] == "SHORT":
                open_short.append((idx, float(self.df.iloc[idx]["high"])))
            elif ev["event_type"] == "CLOSE" and ev["side"] == "LONG":
                close_long.append((idx, float(self.df.iloc[idx]["high"])))
            elif ev["event_type"] == "CLOSE" and ev["side"] == "SHORT":
                close_short.append((idx, float(self.df.iloc[idx]["low"])))

        self.scatter_open_long.setData(pos=np.array(open_long) if open_long else np.empty((0, 2), dtype=float))
        self.scatter_open_short.setData(pos=np.array(open_short) if open_short else np.empty((0, 2), dtype=float))
        self.scatter_close_long.setData(pos=np.array(close_long) if close_long else np.empty((0, 2), dtype=float))
        self.scatter_close_short.setData(pos=np.array(close_short) if close_short else np.empty((0, 2), dtype=float))

    def _update_header(self):
        if not hasattr(self, "headerSymbolValue"):
            return
        symbol = self.symbolBox.currentText().strip().upper() if hasattr(self, "symbolBox") else DEFAULT_SYMBOL
        interval = self.intervalBox.currentText().strip() if hasattr(self, "intervalBox") else DEFAULT_INTERVAL
        total = max(0, len(self.df) - 1)
        close_text = "-"
        time_text = "-"
        if not self.df.empty:
            idx = int(clamp(self.cursor, 0, len(self.df) - 1))
            row = self.df.iloc[idx]
            close_text = self._fmt_num(row.get("close"))
            time_text = pd.to_datetime(row.get("open_time_bjt")).tz_convert(BJT).strftime("%m-%d %H:%M")
        self.headerSymbolValue.setText(symbol or "-")
        self.headerIntervalValue.setText(interval or "-")
        self.headerCloseValue.setText(close_text)
        self.headerTimeValue.setText(time_text)
        self.headerCursorValue.setText(f"{self.cursor} / {total}")
        self.headerPlayBadge.setText(self.tr("playing") if self.playing else self.tr("paused"))
        self._set_widget_role(self.headerPlayBadge, "pillLive" if self.playing else "pillMuted")
        self.headerViewBadge.setText(self.tr("follow_latest") if self.follow_latest else self.tr("free_view"))
        self._set_widget_role(self.headerViewBadge, "pillLive" if self.follow_latest else "pill")
        short_session = self._short_id(self.session_id) if self.session_id else "-"
        self.headerSessionBadge.setText(f"{self.tr('session')} {short_session}")
        self._update_load_play_button()

    def _render(self, force=False):
        if not force and not self._render_dirty:
            return
        if self.df.empty:
            self._update_header()
            self._render_dirty = False
            return
        if len(self.df) > 2000:
            self._rebuild_items()
        current = self._current_xrange()
        if self.follow_latest:
            if current is not None:
                span = max(5.0, current[1] - current[0])
            elif self.manual_xrange is not None:
                span = max(5.0, self.manual_xrange[1] - self.manual_xrange[0])
            else:
                span = float(min(self.window_bars, max(40, len(self.df))))
            vx1 = float(self.cursor + self.pad_right)
            vx0 = vx1 - span
            vx0, vx1 = self._clamp_xrange(vx0, vx1)
            self._set_xrange(vx0, vx1, force=force)
        else:
            if self.manual_xrange is None:
                if current is not None:
                    self.manual_xrange = current
                else:
                    span = float(min(self.window_bars, max(40, len(self.df))))
                    vx1 = float(min(self.cursor + self.pad_right, len(self.df) - 1 + self.pad_right))
                    self.manual_xrange = (max(0.0, vx1 - span), vx1)
            vx0, vx1 = self._clamp_xrange(*self.manual_xrange)
            self.manual_xrange = (vx0, vx1)
            if force and (current is None or abs(current[0] - vx0) > 1e-6 or abs(current[1] - vx1) > 1e-6):
                self._set_xrange(vx0, vx1, force=True)
        self._autoscale_y(vx0, vx1)
        self._sync_markers()
        self._update_current_price_line(vx0, vx1)
        bar_time = self.df.iloc[int(clamp(self.cursor, 0, len(self.df) - 1))]["open_time_bjt"]
        bar_time = pd.to_datetime(bar_time).tz_convert(BJT).strftime("%Y-%m-%d %H:%M:%S")
        bar = self.df.iloc[int(clamp(self.cursor, 0, len(self.df) - 1))]
        report = self.df.attrs.get("data_quality_report", {})
        data_source = self.df.attrs.get("data_source", "-")
        quality = report.get("data_quality_status", "-") if isinstance(report, dict) else "-"
        self.status.setText(
            f"{self.symbolBox.currentText().strip().upper()} {self.intervalBox.currentText().strip()} | "
            f"{'播放' if self.playing else '暂停'} | 速度 x{self.current_speed():.1f} | "
            f"cursor={self.cursor}/{max(0, len(self.df) - 1)} | {bar_time} BJT | "
            f"O={self._fmt_num(bar.get('open'))} H={self._fmt_num(bar.get('high'))} "
            f"L={self._fmt_num(bar.get('low'))} C={self._fmt_num(bar.get('close'))} | "
            f"源={data_source} 质量={quality} 样本={len(self.events)} 会话={self._short_id(self.session_id) if self.session_id else '-'} | "
            f"{'跟随最新' if self.follow_latest else '自由浏览'}"
        )
        self._update_header()
        self._render_dirty = False

    # ---------- Trade / Event ----------
    def current_bar(self):
        if self.df.empty:
            return None
        return self.df.iloc[int(clamp(self.cursor, 0, len(self.df) - 1))]

    def current_tags_and_note(self):
        tags = [cb.text() for cb in self.tag_checks if cb.isChecked()]
        note = self.noteEdit.toPlainText().strip()
        return tags, note

    def _selected_id_from_table(self, table: QtWidgets.QTableWidget):
        selection = table.selectionModel()
        if selection is None:
            return None
        rows = selection.selectedRows()
        if len(rows) != 1:
            return None
        row = rows[0].row()
        if row < 0 or row >= table.rowCount():
            return None
        item = table.item(row, 0)
        return item.data(ROLE_ID) if item else None

    def _operation_error(self, title: str, exc: Exception):
        message = f"{type(exc).__name__}: {exc}"
        logger.exception("%s：%s", title, exc)
        self._log(f"{title}：{message}")
        QtWidgets.QMessageBox.critical(self, title, message)

    def request_open_trade(self, side: str):
        if self.df.empty:
            return
        if side not in {"LONG", "SHORT"}:
            self._log(f"忽略未知开仓方向：{side}")
            return
        if not self.session_id:
            self.session_id = self._new_id("sess")
            self.persist_session_state()
        bar = self.current_bar()
        if bar is None or "bar_index" not in bar:
            self._log("开仓失败：当前K线无效。")
            return
        tags, note = self.current_tags_and_note()
        event_id = self._new_id("evt")
        trade_id = self._new_id("trd")
        transaction = self.trade_controller.prepare_open(
            self.df,
            bar,
            event_idx=int(bar["bar_index"]),
            session_id=self.session_id,
            symbol=self.symbolBox.currentText().strip().upper(),
            interval=self.intervalBox.currentText().strip(),
            side=side,
            event_id=event_id,
            trade_id=trade_id,
            label_tags=tags,
            note=note,
            settings=self.execution_settings(),
            now_iso=bjt_now_iso(),
        )
        trade_row = transaction.trade_row
        event_row = transaction.event_row

        def do():
            self.trade_controller.commit_open(transaction)
            self._trade_by_id[trade_id] = dict(trade_row)
            self._event_by_id[event_id] = dict(event_row)
            self.trades.append(self._trade_by_id[trade_id])
            self.events.append(self._event_by_id[event_id])
            self._refresh_tables()
            self._render(force=True)
            self._log(f"开{('多' if side == 'LONG' else '空')}：交易ID={trade_id}")

        def undo():
            self.trade_controller.undo_open(transaction)
            self.trades = [t for t in self.trades if t["trade_id"] != trade_id]
            self.events = [e for e in self.events if e["event_id"] != event_id]
            self._trade_by_id.pop(trade_id, None)
            self._event_by_id.pop(event_id, None)
            self._refresh_tables()
            self._render(force=True)
            self._log(f"撤销开仓：交易ID={trade_id}")

        self.execute_command(ActionCommand(name=f"open_{side.lower()}", do_fn=do, undo_fn=undo))

    def request_close_trade(self, expected_side: str):
        if expected_side not in {"LONG", "SHORT"}:
            self._log(f"忽略未知平仓方向：{expected_side}")
            return
        trade = self.selected_open_trade(verify_db=True)
        if not trade:
            QtWidgets.QMessageBox.warning(self, "未选择仓位", "请先在“未平仓”列表中选中一笔仓位。")
            return
        if trade.get("status") != "OPEN":
            QtWidgets.QMessageBox.warning(self, "仓位状态错误", "当前选中的交易不是未平仓状态，请刷新或重新选择。")
            self._log(f"平仓被拒绝：交易ID={trade.get('trade_id')} 状态={self._status_label(trade.get('status'))}")
            return
        if trade["side"] != expected_side:
            QtWidgets.QMessageBox.warning(self, "方向不匹配", f"当前选中仓位方向为 {trade['side']}，不能执行本次平仓。")
            return
        bar = self.current_bar()
        if bar is None:
            return
        tags, note = self.current_tags_and_note()
        event_id = self._new_id("evt")
        bar_index = int(bar["bar_index"])
        entry_bar_index = int(trade["entry_bar_index"])
        if bar_index < entry_bar_index:
            QtWidgets.QMessageBox.warning(self, "平仓位置错误", "平仓K线不能早于开仓K线。请先跳到开仓之后的位置。")
            return
        transaction = self.trade_controller.prepare_close(
            self.df,
            bar,
            event_idx=bar_index,
            trade=trade,
            event_id=event_id,
            label_tags=tags,
            note=note,
            fallback_settings=self.execution_settings(),
            now_iso=bjt_now_iso(),
        )
        event_row = transaction.event_row
        close_update = transaction.close_update
        old_trade = transaction.original_trade

        def do():
            self.trade_controller.commit_close(transaction)
            self._event_by_id[event_id] = dict(event_row)
            self.events.append(self._event_by_id[event_id])
            trade.update(close_update)
            self._trade_by_id[trade["trade_id"]] = trade
            self._sync_equity_curve()
            self._refresh_tables()
            self._render(force=True)
            self._log(f"平{('多' if trade['side'] == 'LONG' else '空')}：交易ID={trade['trade_id']}")

        def undo():
            self.trade_controller.undo_close(transaction, bjt_now_iso())
            self.events = [e for e in self.events if e["event_id"] != event_id]
            self._event_by_id.pop(event_id, None)
            trade.clear()
            trade.update(old_trade)
            self._trade_by_id[trade["trade_id"]] = trade
            self._sync_equity_curve()
            self._refresh_tables()
            self._render(force=True)
            self._log(f"撤销平仓：交易ID={trade['trade_id']}")

        self.execute_command(ActionCommand(name=f"close_{expected_side.lower()}", do_fn=do, undo_fn=undo))

    def selected_open_trade(self, verify_db: bool = False):
        trade_id = self._selected_id_from_table(self.openTradesTable)
        if not trade_id:
            return None
        trade = self._trade_by_id.get(trade_id)
        if not trade:
            self._log(f"选择的未平仓交易不在内存索引中：交易ID={trade_id}")
            return None
        if trade.get("status") != "OPEN":
            self._log(f"选择的交易不是未平仓状态：交易ID={trade_id} 状态={self._status_label(trade.get('status'))}")
            return None
        if verify_db:
            db_trade = self.trade_controller.fetch_trade(trade_id)
            if not db_trade:
                self._log(f"SQLite 中找不到选中的交易：交易ID={trade_id}")
                return None
            if db_trade.get("status") != "OPEN":
                self._log(f"SQLite 中选中交易不是未平仓：交易ID={trade_id} 状态={self._status_label(db_trade.get('status'))}")
                return None
            if db_trade.get("session_id") != self.session_id:
                self._log(f"选中交易不属于当前会话：交易ID={trade_id}")
                return None
        return trade

    def on_open_trade_selected(self):
        trade = self.selected_open_trade()
        if trade:
            self.detailText.setPlainText(self._format_trade_detail(trade))
        else:
            self.detailText.setPlainText("无")

    def on_closed_trade_selected(self):
        trade_id = self._selected_id_from_table(self.closedTradesTable)
        if not trade_id:
            return
        trade = self._trade_by_id.get(trade_id)
        if trade:
            self.detailText.setPlainText(self._format_trade_detail(trade))

    def on_event_selected(self):
        event_id = self._selected_id_from_table(self.eventTable)
        if not event_id:
            return
        event = self._event_by_id.get(event_id)
        if not event:
            self._log(f"选择的事件不在内存索引中：事件ID={event_id}")
            return
        self.detailText.setPlainText(self._format_event_detail(event))
        for cb in self.tag_checks:
            cb.setChecked(cb.text() in event.get("label_tags", []))
        self.noteEdit.setPlainText(event.get("note") or "")

    def _format_trade_detail(self, trade: dict[str, Any]) -> str:
        net_return = trade.get("net_return_pct") if trade.get("net_return_pct") is not None else trade.get("final_return_pct")
        lines = [
            "交易详情",
            "",
            f"交易ID        : {trade.get('trade_id') or ''}",
            f"方向          : {self._side_label(trade.get('side'))}",
            f"状态          : {self._status_label(trade.get('status'))}",
            f"入场时间      : {trade.get('entry_bar_time_bjt') or ''}",
            f"出场时间      : {trade.get('exit_bar_time_bjt') or ''}",
            f"入场成交价    : {self._fmt_num(trade.get('entry_fill_price') if trade.get('entry_fill_price') is not None else trade.get('entry_price_proxy'))}",
            f"出场成交价    : {self._fmt_num(trade.get('exit_fill_price') if trade.get('exit_fill_price') is not None else trade.get('exit_price_proxy'))}",
            f"代理收益      : {self._fmt_num(trade.get('final_return_pct'))}%",
            f"净收益        : {self._fmt_num(net_return)}%",
            f"净盈亏        : {self._fmt_num(trade.get('net_pnl_quote'))}",
            f"持仓K线数     : {trade.get('holding_bars') if trade.get('holding_bars') is not None else ''}",
            f"成交模式      : {self._fill_mode_label(trade.get('fill_mode'))}",
        ]
        return "\n".join(lines)

    def _format_event_detail(self, event: dict[str, Any]) -> str:
        labels = event.get("label_tags", [])
        if isinstance(labels, str):
            labels = [labels]
        lines = [
            "事件详情",
            "",
            f"事件ID        : {event.get('event_id') or ''}",
            f"交易ID        : {event.get('trade_id') or ''}",
            f"事件类型      : {self._event_type_label(event.get('event_type'))}",
            f"方向          : {self._side_label(event.get('side'))}",
            f"K线时间       : {event.get('bar_open_time_bjt') or ''}",
            f"代理价格      : {self._fmt_num(event.get('price_proxy'))}",
            f"标签          : {', '.join(labels)}",
            "",
            "备注",
            event.get("note") or "",
        ]
        return "\n".join(lines)

    def apply_labels_to_selected_event(self):
        event_id = self._selected_id_from_table(self.eventTable)
        if not event_id:
            QtWidgets.QMessageBox.warning(self, "未选择事件", "请先在“事件”表中选中一条事件记录。")
            return
        event = self._event_by_id.get(event_id)
        if not event:
            self._log(f"更新事件标签失败：内存中找不到事件ID={event_id}")
            QtWidgets.QMessageBox.warning(self, "事件状态错误", "当前选中的事件不存在，请刷新或重新选择。")
            return
        if not self.storage.fetch_event(event_id):
            self._log(f"更新事件标签失败：SQLite 中找不到事件ID={event_id}")
            QtWidgets.QMessageBox.warning(self, "事件状态错误", "SQLite 中找不到当前事件，请重新加载会话。")
            return
        new_tags, new_note = self.current_tags_and_note()
        old_tags = list(event.get("label_tags", []))
        old_note = event.get("note") or ""
        if old_tags == new_tags and old_note == new_note:
            return

        def do():
            self.storage.update_event_labels(event_id, new_tags, new_note)
            event["label_tags"] = list(new_tags)
            event["note"] = new_note
            self._refresh_tables()
            self._log(f"已更新事件标签：{event_id}")

        def undo():
            self.storage.update_event_labels(event_id, old_tags, old_note)
            event["label_tags"] = list(old_tags)
            event["note"] = old_note
            self._refresh_tables()
            self._log(f"撤销事件标签更新：{event_id}")

        self.execute_command(ActionCommand(name="event_meta_update", do_fn=do, undo_fn=undo))

    # ---------- Undo / redo ----------
    def execute_command(self, command: ActionCommand):
        try:
            command.do()
        except Exception as e:
            self._operation_error("操作失败", e)
            return False
        self.undo_stack.append(command)
        self.redo_stack.clear()
        return True

    def undo(self):
        if not self.undo_stack:
            return
        cmd = self.undo_stack[-1]
        try:
            cmd.undo()
        except Exception as e:
            self._operation_error("撤销失败", e)
            return
        self.undo_stack.pop()
        self.redo_stack.append(cmd)

    def redo(self):
        if not self.redo_stack:
            return
        cmd = self.redo_stack[-1]
        try:
            cmd.do()
        except Exception as e:
            self._operation_error("重做失败", e)
            return
        self.redo_stack.pop()
        self.undo_stack.append(cmd)

    # ---------- Tables / selection ----------
    def _refresh_tables(self):
        tables = (
            self.openTradesTable,
            self.closedTradesTable,
            self.eventTable,
            self.equityTable,
            self.eventStudyTable,
        )
        old_signal_state = {table: table.blockSignals(True) for table in tables}
        try:
            for table in tables:
                table.clearSelection()
                table.setCurrentCell(-1, -1)
            self._populate_tables()
        finally:
            for table, old_state in old_signal_state.items():
                table.blockSignals(old_state)
        self._refresh_performance_summary()

    def _populate_tables(self):
        open_trades = [t for t in self.trades if t.get("status") == "OPEN"]
        closed_trades = [t for t in self.trades if t.get("status") == "CLOSED"]
        open_trades.sort(key=lambda x: x.get("created_at") or "")
        closed_trades.sort(key=lambda x: x.get("updated_at") or "")
        self.openTradesTable.setRowCount(len(open_trades))
        for r, t in enumerate(open_trades):
            values = [
                t["trade_id"], self._side_label(t.get("side")), t.get("entry_bar_time_bjt") or "",
                self._fmt_num(t.get("entry_price_proxy")),
                self._fmt_num(t.get("entry_fill_price") if t.get("entry_fill_price") is not None else t.get("entry_price_proxy")),
                self._fmt_num(t.get("entry_fee_quote")),
                self._fmt_num(t.get("notional_quote")),
                t.get("entry_bar_index"), self._status_label(t.get("status")), self._fill_mode_label(t.get("fill_mode")),
            ]
            for c, v in enumerate(values):
                item = self._make_table_item(
                    v,
                    role_id=t["trade_id"] if c == 0 else None,
                    numeric=c in {3, 4, 5, 6, 7},
                    short_id=c == 0,
                )
                self.openTradesTable.setItem(r, c, item)

        self.closedTradesTable.setRowCount(len(closed_trades))
        for r, t in enumerate(closed_trades):
            total_fee = (self._safe_float(t.get("entry_fee_quote")) + self._safe_float(t.get("exit_fee_quote")))
            net_return = t.get("net_return_pct") if t.get("net_return_pct") is not None else t.get("final_return_pct")
            values = [
                t["trade_id"], self._side_label(t.get("side")), t.get("entry_bar_time_bjt") or "", t.get("exit_bar_time_bjt") or "",
                self._fmt_num(t.get("entry_fill_price") if t.get("entry_fill_price") is not None else t.get("entry_price_proxy")),
                self._fmt_num(t.get("exit_fill_price") if t.get("exit_fill_price") is not None else t.get("exit_price_proxy")),
                self._fmt_num(t.get("gross_return_pct") if t.get("gross_return_pct") is not None else t.get("final_return_pct")),
                self._fmt_num(net_return),
                self._fmt_num(total_fee),
                self._fmt_num(t.get("net_pnl_quote")),
                t.get("holding_bars"), self._status_label(t.get("status")), self._fill_mode_label(t.get("fill_mode")),
            ]
            for c, v in enumerate(values):
                item = self._make_table_item(
                    v,
                    role_id=t["trade_id"] if c == 0 else None,
                    numeric=c in {4, 5, 6, 7, 8, 9, 10},
                    pnl=c in {6, 7, 9},
                    short_id=c == 0,
                )
                self.closedTradesTable.setItem(r, c, item)

        self.events.sort(key=lambda x: x.get("created_at") or "")
        visible_events = list(self.events)
        selected_tag = self.eventFilterTag.currentText() if hasattr(self, "eventFilterTag") else "全部标签"
        selected_side = self.eventFilterSide.currentData() if hasattr(self, "eventFilterSide") else ""
        selected_type = self.eventFilterType.currentData() if hasattr(self, "eventFilterType") else ""
        if selected_tag and selected_tag != "全部标签":
            visible_events = [e for e in visible_events if selected_tag in (e.get("label_tags") or [])]
        if selected_side:
            visible_events = [e for e in visible_events if e.get("side") == selected_side]
        if selected_type:
            visible_events = [e for e in visible_events if e.get("event_type") == selected_type]
        self.eventTable.setRowCount(len(visible_events))
        for r, e in enumerate(visible_events):
            values = [
                e["event_id"], e["trade_id"], self._event_type_label(e.get("event_type")), self._side_label(e.get("side")),
                e.get("bar_open_time_bjt") or "", self._fmt_num(e.get("price_proxy")),
                ", ".join(e.get("label_tags", [])), e.get("note") or "",
            ]
            for c, v in enumerate(values):
                item = self._make_table_item(
                    v,
                    role_id=e["event_id"] if c == 0 else None,
                    numeric=c in {5},
                    short_id=c in {0, 1},
                )
                self.eventTable.setItem(r, c, item)

        equity_rows = self._current_equity_rows()
        self._populate_equity_table(equity_rows)
        self._populate_event_study_table()
        self._refresh_dataset_summary()

    def _make_table_item(
        self,
        value: Any,
        role_id: Any = None,
        numeric: bool = False,
        pnl: bool = False,
        short_id: bool = False,
    ) -> QtWidgets.QTableWidgetItem:
        display = self._short_id(value) if short_id else ("" if value is None else str(value))
        item = QtWidgets.QTableWidgetItem(display)
        if role_id is not None:
            item.setData(ROLE_ID, role_id)
        if numeric:
            item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        if pnl:
            number = self._safe_float(value, default=float("nan"))
            if math.isfinite(number):
                if number > 0:
                    item.setForeground(QtGui.QBrush(QtGui.QColor(COLORS["green"])))
                elif number < 0:
                    item.setForeground(QtGui.QBrush(QtGui.QColor(COLORS["red"])))
        return item

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            out = float(value)
        except (TypeError, ValueError):
            return default
        return out if math.isfinite(out) else default

    def _current_equity_rows(self) -> list[dict[str, Any]]:
        from accounting import build_equity_curve

        return build_equity_curve(
            self.trades,
            self.session_id or "",
            float(self.initialEquitySpin.value()),
            float(self.tradeNotionalSpin.value()),
        )

    def _populate_equity_table(self, equity_rows: list[dict[str, Any]]):
        self.equityTable.setRowCount(len(equity_rows))
        for r, row in enumerate(equity_rows):
            values = [
                row.get("sequence_no") or r + 1,
                row.get("trade_id") or "",
                self._fmt_num(row.get("equity_before")),
                self._fmt_num(row.get("realized_net_pnl")),
                self._fmt_num(row.get("realized_fee")),
                self._fmt_num(row.get("equity_after")),
                self._fmt_num(row.get("equity_return_pct")),
                self._fmt_num(row.get("drawdown_pct")),
            ]
            for c, v in enumerate(values):
                item = self._make_table_item(
                    v,
                    role_id=row.get("trade_id") if c == 1 else None,
                    numeric=c in {0, 2, 3, 4, 5, 6, 7},
                    pnl=c in {3, 6, 7},
                    short_id=c == 1,
                )
                self.equityTable.setItem(r, c, item)

    def _feature_rows_for_session(self) -> list[dict[str, Any]]:
        if not self.session_id:
            return []
        try:
            return self.storage.fetch_table("event_features", "session_id=?", (self.session_id,))
        except Exception as e:
            self._log(f"读取事件特征失败：{type(e).__name__}: {e}")
            return []

    def _event_rows_for_study(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for event in self.events:
            row = dict(event)
            if not row.get("label_tags_json"):
                row["label_tags_json"] = json.dumps(row.get("label_tags") or [], ensure_ascii=False)
            rows.append(row)
        return rows

    def _populate_event_study_table(self):
        from event_study import build_event_study_summary

        try:
            summary = build_event_study_summary(
                pd.DataFrame(self._event_rows_for_study()),
                pd.DataFrame(self._feature_rows_for_session()),
            )
        except Exception as e:
            self._log(f"事件研究统计失败：{type(e).__name__}: {e}")
            summary = pd.DataFrame()

        self.eventStudyTable.setRowCount(len(summary))
        for r, row in summary.iterrows():
            values = [
                row.get("label_tag") or "",
                row.get("event_type") or "",
                row.get("side") or "",
                int(row.get("sample_count") or 0),
                self._fmt_num(row.get("fwd_ret_1_mean")),
                self._fmt_num(row.get("fwd_ret_3_mean")),
                self._fmt_num(row.get("fwd_ret_5_mean")),
                self._fmt_num(row.get("fwd_ret_10_mean")),
                self._fmt_num(row.get("fwd_ret_1_win_rate_pct")),
            ]
            for c, v in enumerate(values):
                self.eventStudyTable.setItem(
                    r,
                    c,
                    self._make_table_item(v, numeric=c >= 3, pnl=c in {4, 5, 6, 7, 8}),
                )

    def _refresh_dataset_summary(self):
        from dataset_builder import build_ml_datasets

        try:
            features = pd.DataFrame(self._feature_rows_for_session())
            datasets = build_ml_datasets(features)
            ml_features = datasets["ml_features"]
            ml_labels = datasets["ml_labels"]
            sample_index = datasets["sample_index"]
            blocked = ["未来收益字段", "事件后窗口字段", "最大有利/不利波动", "人工交易结果字段"]
            text = "\n".join([
                f"当前会话事件特征行数: {len(features)}",
                f"特征表行/列: {len(ml_features)} / {len(ml_features.columns)}",
                f"标签表行/列: {len(ml_labels)} / {len(ml_labels.columns)}",
                f"样本索引行/列: {len(sample_index)} / {len(sample_index.columns)}",
                f"已隔离未来/结果字段: {', '.join(blocked)}",
            ])
            self.datasetText.setPlainText(text)
        except Exception as e:
            self.datasetText.setPlainText(f"机器学习样本摘要生成失败：{type(e).__name__}: {e}")
            self._log(f"机器学习样本摘要生成失败：{type(e).__name__}: {e}")

    def _refresh_performance_summary(self):
        from performance import build_performance_summary, format_performance_report

        if not hasattr(self, "performanceText"):
            return
        try:
            equity_rows = self._current_equity_rows()
            summary = build_performance_summary(self.trades, equity_rows, float(self.initialEquitySpin.value()))
            self.performanceText.setPlainText(format_performance_report(summary))
        except Exception as e:
            self.performanceText.setPlainText(f"统计生成失败：{type(e).__name__}: {e}")
            self._log(f"交易绩效统计生成失败：{type(e).__name__}: {e}")

    def jump_to_trade_row(self, item: QtWidgets.QTableWidgetItem):
        trade_id = self.sender().item(item.row(), 0).data(ROLE_ID)
        trade = self._trade_by_id.get(trade_id)
        if not trade:
            return
        idx = trade.get("entry_bar_index") if trade.get("status") == "OPEN" else trade.get("exit_bar_index") or trade.get("entry_bar_index")
        self.jump_to_bar(int(idx))

    def jump_to_event_row(self, item: QtWidgets.QTableWidgetItem):
        event_id = self.eventTable.item(item.row(), 0).data(ROLE_ID)
        event = self._event_by_id.get(event_id)
        if event:
            self.jump_to_bar(int(event["bar_index"]))

    def jump_to_bar(self, bar_index: int):
        if self.df.empty:
            return
        self.cursor = int(clamp(bar_index, 0, len(self.df) - 1))
        self._rebuild_items()
        self._last_cursor_for_series = int(self.cursor)
        (x0, x1), _ = self.vb_price.viewRange()
        span = max(20.0, x1 - x0 if math.isfinite(x0) and math.isfinite(x1) and x1 > x0 else self.window_bars)
        x0 = max(0.0, self.cursor - span / 2.0)
        x1 = x0 + span
        self.pricePlot.setXRange(x0, x1, padding=0.0)
        self.volPlot.setXRange(x0, x1, padding=0.0)
        self._render(force=True)

    # ---------- Export ----------
    def _ensure_export_controller(self):
        if self.export_controller is None:
            from export_controller import ExportController
            from exporter import Exporter

            self.exporter = Exporter(self.storage)
            self.export_controller = ExportController(self.exporter)
        return self.export_controller

    def export_session(self):
        if not self.session_id:
            return
        target = QtWidgets.QFileDialog.getExistingDirectory(self, "选择导出目录", str(EXPORT_DIR))
        if not target:
            return
        self.start_export_task(Path(target), language=self.current_language)

    def start_export_task(
        self,
        target: Path,
        on_success=None,
        language: str | None = None,
        selected_label: str = "fwd_ret_10_side_adj",
    ):
        if not self.session_id or self.app_state.export.running:
            return False
        from workers.export_worker import ExportWorker

        self.app_state.export.running = True
        self.app_state.export.last_error = None
        self._export_success_callback = on_success
        self.btnExport.setEnabled(False)
        self.status.setText("Exporting session data...")
        self._export_thread = QtCore.QThread(self)
        self._export_worker = ExportWorker(
            self.storage.db_path,
            self.session_id,
            target,
            language or self.current_language,
            selected_label,
        )
        self._export_worker.moveToThread(self._export_thread)
        self._export_thread.started.connect(self._export_worker.run)
        self._export_worker.progress.connect(self.status.setText)
        self._export_worker.finished.connect(self._on_export_finished)
        self._export_worker.failed.connect(self._on_export_failed)
        self._export_worker.cancelled.connect(self._on_export_cancelled)
        self._export_thread.start()
        return True

    @QtCore.Slot(str, object, float)
    def _on_export_finished(self, output_dir: str, warnings: list, elapsed: float):
        self.app_state.export.output_dir = output_dir
        self._log(f"Export completed in {elapsed:.2f}s: {output_dir}")
        callback = self._export_success_callback
        self._finish_export_task()
        if callback is not None:
            callback(Path(output_dir))
        QtWidgets.QMessageBox.information(self, "Export completed", f"Files written to:\n{output_dir}")

    @QtCore.Slot(str, float)
    def _on_export_failed(self, error: str, elapsed: float):
        self.app_state.export.last_error = error
        logger.error("Export failed after %.2fs: %s", elapsed, error)
        self._log(f"Export failed: {error}")
        self._finish_export_task()
        QtWidgets.QMessageBox.critical(self, "Export failed", error)

    @QtCore.Slot()
    def _on_export_cancelled(self):
        self._log("Export cancelled.")
        self._finish_export_task()

    def _finish_export_task(self):
        self.app_state.export.running = False
        self._export_success_callback = None
        self.btnExport.setEnabled(True)
        if self._export_thread is not None:
            self._export_thread.quit()
            self._export_thread.wait(1000)
            self._export_worker.deleteLater()
            self._export_thread.deleteLater()
        self._export_worker = None
        self._export_thread = None

    # ---------- Premium ----------
    def request_premium_sample(self):
        if not self.premium_controller.begin_sample():
            return
        self.requestPremium.emit()

    def on_premium_sample(self, row: dict[str, Any]):
        self.premium_controller.complete_sample(row, self.storage)
        if row["sample_status"] == "OK":
            self._set_widget_role(self.premiumStatus, "pillLive")
            self.premiumStatus.setText(
                f"最近采样：{row['sample_time_bjt']} | 状态：OK | 汇率源：{row.get('fx_source') or '-'}"
            )
            self.premiumStats.setPlainText(
                f"P2P买价：{row['p2p_buy_price_cny']:.4f}  买入溢价：{row['buy_premium_pct']:+.2f}%\n"
                f"P2P卖价：{row['p2p_sell_price_cny']:.4f}  卖出溢价：{row['sell_premium_pct']:+.2f}%\n"
                f"P2P均价：{row['p2p_avg_price_cny']:.4f}  均价溢价：{row['avg_premium_pct']:+.2f}%\n"
                f"USD/CNY：{row['usd_cny_rate']:.4f}"
            )
        else:
            self._set_widget_role(self.premiumStatus, "pillWarning")
            self.premiumStatus.setText(f"最近采样：{row['sample_time_bjt']} | 状态：ERROR")
            self.premiumStats.setPlainText(row.get("error_message") or "采样失败")
        self._refresh_premium_plot()

    def _refresh_premium_plot(self):
        rows = self.storage.fetch_table("usdt_premium_history")
        if not rows:
            self.premiumBuyCurve.setData([], [])
            self.premiumSellCurve.setData([], [])
            self.premiumAvgCurve.setData([], [])
            return
        df = pd.DataFrame(rows).tail(240)
        df = df[df["sample_status"] == "OK"].copy()
        if df.empty:
            self.premiumBuyCurve.setData([], [])
            self.premiumSellCurve.setData([], [])
            self.premiumAvgCurve.setData([], [])
            return
        x = np.arange(len(df), dtype=float)
        self.premiumBuyCurve.setData(x, df["buy_premium_pct"].astype(float).to_numpy())
        self.premiumSellCurve.setData(x, df["sell_premium_pct"].astype(float).to_numpy())
        self.premiumAvgCurve.setData(x, df["avg_premium_pct"].astype(float).to_numpy())

    def _update_current_price_line(self, vx0: float, vx1: float):
        if self.df.empty:
            self.currentPriceLine.hide()
            self.currentPriceLabel.hide()
            return
        idx = int(clamp(self.cursor, 0, len(self.df) - 1))
        row = self.df.iloc[idx]
        price = float(row["close"])
        prev_close = float(self.df.iloc[max(0, idx - 1)]["close"]) if idx > 0 else price
        up = price >= prev_close
        line_color = self.theme_settings['current_price_up'] if up else self.theme_settings['current_price_down']
        text_color = self.theme_settings['current_price_label_text']
        self.currentPriceLine.setPen(pg.mkPen(line_color, style=QtCore.Qt.DashLine, width=1))
        self.currentPriceLine.setValue(price)
        label_x = vx1 - max(0.05, (vx1 - vx0) * 0.006)
        self.currentPriceLabel.setColor(text_color)
        try:
            self.currentPriceLabel.fill = pg.mkBrush(line_color)
            self.currentPriceLabel.border = pg.mkPen(line_color)
            self.currentPriceLabel.update()
        except Exception:
            pass
        self.currentPriceLabel.setText(f"{price:.4f}")
        self.currentPriceLabel.setPos(label_x, price)
        self.currentPriceLine.show()
        self.currentPriceLabel.show()

    # ---------- Utils ----------
    def _short_id(self, value: Any, keep: int = 8) -> str:
        text = "" if value is None else str(value)
        if len(text) <= keep + 4:
            return text
        prefix = text.split("_", 1)[0]
        if "_" in text and len(prefix) <= 5:
            return f"{prefix}_{text[-keep:]}"
        return text[-keep:]

    def _fmt_num(self, value):
        if value is None:
            return ""
        try:
            v = float(value)
            return f"{v:.6f}" if abs(v) < 1000 else f"{v:.2f}"
        except Exception:
            return str(value)

    def _log(self, message: str):
        logger.info(message)
        self.log.appendPlainText(f"[{bjt_now_iso()}] {message}")


def main():
    bootstrap_runtime_dirs()
    log_path = configure_logging()
    install_exception_hook()
    logger.info("启动 %s v%s，日志文件=%s", APP_NAME, APP_VERSION, log_path)
    try:
        app = QtWidgets.QApplication(sys.argv)
        win = MainWindow()
        win.show()
        sys.exit(app.exec())
    except Exception:
        logger.exception("程序启动或运行失败")
        raise


if __name__ == "__main__":
    main()
