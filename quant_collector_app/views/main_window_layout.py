from __future__ import annotations

import importlib

import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

try:
    from app_icon import apply_header_logo
    from app_config import (
        APP_VERSION,
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
        COLORS,
        SPACING,
    )
    from views.candlestick_item import CandlestickItem
    from views.chart_axis import CurrentPriceAxis, IndexTimeAxis
    from views.date_picker import DatePicker, bind_date_range
    from views.nullable_percent_input import NullablePercentInput
    from views.k_view_box import KViewBox
    from views.high_refresh_viewport import configure_high_refresh_viewport, verify_high_refresh_viewport
    from views.plot_lifecycle import (
        close_parent_owned_graphics_view,
        prepare_plot_for_shutdown,
    )
    from views.volume_item import VolumeItem
    from views.wheel_guard import install_no_wheel_on_value_inputs
except ImportError:  # pragma: no cover - package import path
    from ..app_icon import apply_header_logo
    from ..app_config import (
        APP_VERSION,
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
        COLORS,
        SPACING,
    )
    from .candlestick_item import CandlestickItem
    from .chart_axis import CurrentPriceAxis, IndexTimeAxis
    from .date_picker import DatePicker, bind_date_range
    from .nullable_percent_input import NullablePercentInput
    from .k_view_box import KViewBox
    from .high_refresh_viewport import configure_high_refresh_viewport, verify_high_refresh_viewport
    from .plot_lifecycle import (
        close_parent_owned_graphics_view,
        prepare_plot_for_shutdown,
    )
    from .volume_item import VolumeItem
    from .wheel_guard import install_no_wheel_on_value_inputs


class _DisabledPlotMenu(QtCore.QObject):
    """Non-visual close sentinel for PlotItems whose menus are disabled."""

    def __init__(self, owner: QtWidgets.QWidget) -> None:
        super().__init__(owner)
        self._enabled = False

    def setEnabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    def isEnabled(self) -> bool:
        return self._enabled

    def hide(self) -> None:
        return None

    def actions(self) -> list:
        return []


class _PlotMenuBuildStub(QtCore.QObject):
    """Satisfy PlotItem setup when its context menu is permanently disabled."""

    def __init__(self, *_args, **_kwargs) -> None:
        super().__init__()
        self._actions: list[QtWidgets.QWidgetAction] = []
        self._children: list[_PlotMenuBuildStub] = []

    def addMenu(self, _name: str) -> "_PlotMenuBuildStub":
        child = _PlotMenuBuildStub()
        child.setParent(self)
        self._children.append(child)
        return child

    def addAction(self, action: QtWidgets.QWidgetAction) -> None:
        self._actions.append(action)

    def actions(self) -> list[QtWidgets.QWidgetAction]:
        return list(self._actions)

    def hide(self) -> None:
        return None


def _build_disabled_plot_item(**kwargs) -> pg.PlotItem:
    """Construct a menu-disabled PlotItem without allocating a native QMenu."""

    plot_item_module = importlib.import_module(
        "pyqtgraph.graphicsItems.PlotItem.PlotItem"
    )
    qt_widgets = plot_item_module.QtWidgets
    native_qmenu = qt_widgets.QMenu
    qt_widgets.QMenu = _PlotMenuBuildStub
    try:
        return pg.PlotItem(enableMenu=False, **kwargs)
    finally:
        qt_widgets.QMenu = native_qmenu


def _replace_disabled_plot_menu(plot: pg.PlotItem, owner: QtWidgets.QWidget) -> None:
    """Replace the unused menu without scheduling competing Qt deletion."""

    native_menu = plot.ctrlMenu
    native_menu.hide()
    plot.ctrlMenu = _DisabledPlotMenu(owner)
    plot.setMenuEnabled(False, None)


class _ManagedGraphicsLayoutWidget(pg.GraphicsLayoutWidget):
    """Run pyqtgraph's explicit cleanup protocol after close is accepted."""

    def __init__(self, owner: QtWidgets.QWidget) -> None:
        super().__init__(owner)
        self._managed_plots: tuple[pg.PlotItem, ...] = ()

    def manage_plots(self, *plots: pg.PlotItem) -> None:
        self._managed_plots = tuple(plots)

    def shutdown(self) -> None:
        if self.closed:
            return
        managed_plots = self._managed_plots
        for plot in managed_plots:
            menu = getattr(plot, "ctrlMenu", None)
            if menu is not None:
                menu.hide()
            # PlotItem.close() contains pyqtgraph's PySide-specific teardown
            # and its AxisItem cleanup requires a live scene. Run it before
            # detaching the now-empty PlotItem from GraphicsLayout.
            prepare_plot_for_shutdown(plot)
            plot.close()
            self.ci.removeItem(plot)
        close_parent_owned_graphics_view(self)
        self._managed_plots = ()


class _ManagedPlotWidget(pg.PlotWidget):
    """Own PlotItem menus and use pyqtgraph's explicit close protocol once."""

    def __init__(
        self,
        parent: QtWidgets.QWidget | None = None,
        *,
        background="default",
        plotItem: pg.PlotItem | None = None,
        **kwargs,
    ) -> None:
        plot_item = plotItem or _build_disabled_plot_item(**kwargs)
        super().__init__(parent=parent, background=background, plotItem=plot_item)
        _replace_disabled_plot_menu(self.plotItem, self)

    def shutdown(self) -> None:
        plot = self.plotItem
        if plot is None:
            return
        menu = plot.ctrlMenu
        if menu is not None:
            menu.hide()
        prepare_plot_for_shutdown(plot)
        plot.close()
        self.plotItem = None
        close_parent_owned_graphics_view(self)

    def close(self) -> bool:
        # pyqtgraph's PlotWidget.close() assumes plotItem is still present.
        # Explicit shutdown clears it, while Qt/pytest may legitimately close
        # the wrapper again during parent teardown.
        if self.plotItem is None:
            return bool(QtWidgets.QWidget.close(self))
        return bool(super().close())


def _card(title_text: str) -> tuple[QtWidgets.QGroupBox, QtWidgets.QVBoxLayout]:
    box = QtWidgets.QGroupBox(title_text)
    box.setProperty("role", "sideSection")
    box.setAttribute(QtCore.Qt.WA_StyledBackground, True)
    layout = QtWidgets.QVBoxLayout(box)
    layout.setContentsMargins(0, SPACING["sm"], 0, SPACING["sm"])
    layout.setSpacing(SPACING["sm"])
    return box, layout


def _hidden_header_label(parent: QtWidgets.QWidget, text: str = "-") -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text, parent)
    label.hide()
    return label


def _value_row(label: str, value_widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
    row = QtWidgets.QWidget()
    layout = QtWidgets.QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(SPACING["sm"])
    name = QtWidgets.QLabel(label)
    name.setProperty("role", "muted")
    row.nameLabel = name
    layout.addWidget(name)
    layout.addStretch(1)
    layout.addWidget(value_widget)
    return row


def _metric_label(text: str = "-") -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setProperty("role", "statusValue")
    label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
    label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
    return label


def _table_box(table: QtWidgets.QTableWidget) -> QtWidgets.QWidget:
    box = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(table)
    return box


def _empty_state(title: str, body: str, *, compact: bool = False) -> QtWidgets.QFrame:
    frame = QtWidgets.QFrame()
    frame.setProperty("role", "emptyState")
    layout = QtWidgets.QVBoxLayout(frame)
    margin = SPACING["md"] if compact else SPACING["lg"]
    layout.setContentsMargins(margin, margin, margin, margin)
    layout.setSpacing(SPACING["xs"])
    if not compact:
        layout.addStretch(1)
    title_label = QtWidgets.QLabel(title)
    title_label.setProperty("role", "emptyTitle")
    title_label.setAlignment(QtCore.Qt.AlignCenter)
    body_label = QtWidgets.QLabel(body)
    body_label.setProperty("role", "emptyText")
    body_label.setWordWrap(True)
    body_label.setAlignment(QtCore.Qt.AlignCenter)
    layout.addWidget(title_label)
    layout.addWidget(body_label)
    if not compact:
        layout.addStretch(1)
    else:
        frame.setMaximumHeight(82)
    return frame


def _stacked_empty_table(title: str, body: str, table: QtWidgets.QTableWidget) -> QtWidgets.QStackedWidget:
    stack = QtWidgets.QStackedWidget()
    stack.addWidget(_empty_state(title, body))
    stack.addWidget(_table_box(table))
    return stack


def build_main_window_ui(self) -> None:
    # An accepted close must release the complete Qt/pyqtgraph object tree.
    # SafeShutdownCoordinator still controls acceptance; ignored close events
    # do not trigger deletion.
    self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
    central = QtWidgets.QWidget()
    central.setObjectName("appRoot")
    self.setCentralWidget(central)
    root = QtWidgets.QVBoxLayout(central)
    root.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
    root.setSpacing(SPACING["md"])

    # ---------- Header ----------
    header = QtWidgets.QFrame()
    header.setObjectName("headerBar")
    header.setProperty("role", "header")
    self.headerBar = header
    header.setFixedHeight(52)
    header_l = QtWidgets.QHBoxLayout(header)
    header_l.setContentsMargins(SPACING["lg"], SPACING["xs"], SPACING["lg"], SPACING["xs"])
    header_l.setSpacing(SPACING["sm"])

    self.headerLogoLabel = QtWidgets.QLabel()
    self.headerLogoLabel.setProperty("role", "headerLogo")
    apply_header_logo(self.headerLogoLabel, getattr(self, "theme_settings", None))
    header_l.addWidget(self.headerLogoLabel)
    self.headerTitleLabel = QtWidgets.QLabel(f"Quant Replay Collector v{APP_VERSION}")
    self.headerTitleLabel.setProperty("role", "appTitle")
    self.headerTitleLabel.setMinimumWidth(190)
    self.headerTitleLabel.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Preferred)
    header_l.addWidget(self.headerTitleLabel)

    self.headerMetricLabels = {}
    self.btnReplayWorkspace = QtWidgets.QPushButton("行情回放")
    self.btnReplayWorkspace.setProperty("role", "workspaceNavButton")
    self.btnReplayWorkspace.setCheckable(True)
    self.btnReplayWorkspace.setChecked(True)
    self.btnAnalysisWorkspace = QtWidgets.QPushButton("数据分析")
    self.btnAnalysisWorkspace.setProperty("role", "workspaceNavButton")
    self.btnAnalysisWorkspace.setCheckable(True)
    self.workspaceNavGroup = QtWidgets.QButtonGroup(header)
    self.workspaceNavGroup.setExclusive(True)
    self.workspaceNavGroup.addButton(self.btnReplayWorkspace, 0)
    self.workspaceNavGroup.addButton(self.btnAnalysisWorkspace, 1)
    header_l.addWidget(self.btnReplayWorkspace)
    header_l.addWidget(self.btnAnalysisWorkspace)

    self.headerMainLabel = QtWidgets.QLabel(f"{DEFAULT_SYMBOL} · {DEFAULT_INTERVAL} · - · O - H - L - C -")
    self.headerMainLabel.setProperty("role", "marketSummary")
    # This is intentionally compact: detailed candle data stays in the replay
    # toolbar, so the market identity remains visible beside the account metrics.
    self.headerMainLabel.setMinimumWidth(180)
    self.headerMainLabel.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Preferred)
    self.headerMainLabel.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
    header_l.addStretch(1)

    self.headerEquityValue = QtWidgets.QLabel("权益 -")
    self.headerEquityValue.setProperty("role", "marketMetric")
    self.headerReturnValue = QtWidgets.QLabel("收益 -")
    self.headerReturnValue.setProperty("role", "marketMetric")

    self.headerSymbolValue = _hidden_header_label(header, DEFAULT_SYMBOL)
    self.headerIntervalValue = _hidden_header_label(header, DEFAULT_INTERVAL)
    self.headerDisplayIntervalValue = self.headerIntervalValue
    self.headerSampleIntervalValue = _hidden_header_label(header, f"sample {DEFAULT_INTERVAL}")
    self.headerTimeValue = _hidden_header_label(header)
    self.headerOhlcValue = _hidden_header_label(header)
    self.headerCloseValue = self.headerOhlcValue
    self.headerDeltaValue = _hidden_header_label(header)

    self.headerPlayBadge = QtWidgets.QLabel("● 暂停")
    self.headerPlayBadge.setProperty("role", "headerState")
    self.headerPlayBadge.setMinimumWidth(54)
    self.headerPlayBadge.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Preferred)
    self.headerPlayBadge.setAlignment(QtCore.Qt.AlignCenter)
    self.headerViewBadge = QtWidgets.QLabel("自由浏览")
    self.headerViewBadge.setProperty("role", "headerState")
    self.headerViewBadge.setMinimumWidth(68)
    self.headerViewBadge.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Preferred)
    self.headerViewBadge.setAlignment(QtCore.Qt.AlignCenter)
    self.headerSessionBadge = QtWidgets.QLabel("session -")
    self.headerSessionBadge.setProperty("role", "headerSession")
    self.headerSessionBadge.setMinimumWidth(88)
    self.headerSessionBadge.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Preferred)
    self.headerSessionBadge.setAlignment(QtCore.Qt.AlignCenter)
    header_l.addWidget(self.headerPlayBadge)
    header_l.addWidget(self.headerViewBadge)
    header_l.addWidget(self.headerSessionBadge)
    root.addWidget(header)

    self.workspaceStack = QtWidgets.QStackedWidget()
    self.workspaceStack.setObjectName("workspaceStack")
    self.replayWorkspace = QtWidgets.QWidget()
    self.replayWorkspace.setObjectName("replayWorkspace")
    replay_workspace_l = QtWidgets.QVBoxLayout(self.replayWorkspace)
    replay_workspace_l.setContentsMargins(0, 0, 0, 0)
    replay_workspace_l.setSpacing(SPACING["sm"])
    self.workspaceStack.addWidget(self.replayWorkspace)
    root.addWidget(self.workspaceStack, stretch=1)

    # ---------- Main body ----------
    body = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
    body.setChildrenCollapsible(True)
    body.setHandleWidth(4)
    self.bodySplitter = body
    replay_workspace_l.addWidget(body, stretch=1)

    # ---------- Left sidebar ----------
    left = QtWidgets.QFrame()
    left.setObjectName("leftSidebar")
    left.setProperty("role", "sidebar")
    self.leftSidebar = left
    left.setMinimumWidth(260)
    left.setMaximumWidth(300)
    left_l = QtWidgets.QVBoxLayout(left)
    left_l.setContentsMargins(SPACING["sm"], SPACING["sm"], SPACING["sm"], SPACING["sm"])
    left_l.setSpacing(SPACING["md"])

    sidebar_scroll = QtWidgets.QScrollArea()
    sidebar_scroll.setObjectName("sidebarScroll")
    sidebar_scroll.setWidgetResizable(True)
    sidebar_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
    sidebar_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    sidebar_scroll.viewport().setObjectName("sidebarScrollViewport")
    sidebar_scroll.viewport().setAutoFillBackground(False)
    sidebar_scroll.viewport().setStyleSheet("background: transparent;")
    sidebar_content = QtWidgets.QWidget()
    sidebar_content.setObjectName("sidebarContent")
    sidebar_content.setProperty("role", "transparent")
    sidebar_l = QtWidgets.QVBoxLayout(sidebar_content)
    sidebar_l.setContentsMargins(SPACING["xs"], SPACING["xs"], SPACING["xs"], SPACING["xs"])
    sidebar_l.setSpacing(SPACING["lg"])

    data_box, data_l = _card("市场")
    data_box.setObjectName("marketSection")
    self.dataBox = data_box
    form = QtWidgets.QFormLayout()
    form.setLabelAlignment(QtCore.Qt.AlignLeft)
    form.setFormAlignment(QtCore.Qt.AlignTop)
    form.setSpacing(SPACING["sm"])
    self.symbolBox = QtWidgets.QComboBox()
    self.symbolBox.setObjectName("symbolBox")
    self.symbolBox.setProperty("role", "symbolSelector")
    self.symbolBox.setEditable(False)
    self.symbolBox.addItems(BINANCE_TOP_MARKET_CAP_SYMBOLS)
    self.symbolBox.setCurrentText(DEFAULT_SYMBOL)
    self.symbolBox.installEventFilter(self)
    self.intervalBox = QtWidgets.QComboBox()
    self.intervalBox.addItems(["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"])
    self.intervalBox.setCurrentText(DEFAULT_INTERVAL)

    self.startDate = DatePicker()
    self.startDate.setObjectName("startDate")
    self.startDate.setDate(QtCore.QDate.currentDate().addDays(-2))

    self.endDate = DatePicker()
    self.endDate.setObjectName("endDate")
    self.endDate.setDate(QtCore.QDate.currentDate())
    bind_date_range(self.startDate, self.endDate)

    form.addRow("品种", self.symbolBox)
    form.addRow("周期", self.intervalBox)
    form.addRow("开始", self.startDate)
    form.addRow("结束", self.endDate)
    data_l.addLayout(form)
    self.btnApplyMarket = QtWidgets.QPushButton("应用行情")
    self.btnApplyMarket.setProperty("role", "primaryButton")
    self.btnLoadData = self.btnApplyMarket
    data_l.addWidget(self.btnApplyMarket)
    self.marketDirtyHint = QtWidgets.QLabel("行情参数已更改，请应用")
    self.marketDirtyHint.setProperty("role", "tiny")
    self.marketDirtyHint.setWordWrap(True)
    self.marketDirtyHint.hide()
    data_l.addWidget(self.marketDirtyHint)

    self.symbolPanel = QtWidgets.QFrame()
    self.symbolPanel.setProperty("role", "metricBlock")
    symbol_panel_l = QtWidgets.QVBoxLayout(self.symbolPanel)
    symbol_panel_l.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
    symbol_panel_l.setSpacing(SPACING["sm"])
    self.symbolSearchEdit = QtWidgets.QLineEdit()
    self.symbolSearchEdit.setProperty("role", "searchInput")
    self.symbolSearchEdit.setPlaceholderText("搜索品种，例如 BTC、ETH、1000PEPE")
    self.symbolList = QtWidgets.QListWidget()
    self.symbolList.setMaximumHeight(140)
    self.symbolList.addItems(BINANCE_TOP_MARKET_CAP_SYMBOLS)
    self.symbolPanel.setVisible(False)
    symbol_panel_l.addWidget(self.symbolSearchEdit)
    symbol_panel_l.addWidget(self.symbolList)
    data_l.addWidget(self.symbolPanel)
    sidebar_l.addWidget(data_box)

    replay_box, replay_l = _card("回放控制")
    replay_box.setObjectName("replaySection")
    self.replayBox = replay_box
    self.btnLoadPlay = QtWidgets.QPushButton("播放 / 暂停")
    self.btnStep = QtWidgets.QPushButton("下一根 (→)")
    self.btnToEnd = QtWidgets.QPushButton("跳到末尾")
    self.btnFollow = QtWidgets.QPushButton("跟随最新 (F)")
    self.btnResetView = QtWidgets.QPushButton("重置缩放 (K)")
    self.btnLoadPlay.setProperty("role", "primaryButton")
    for btn in (self.btnStep, self.btnToEnd, self.btnFollow, self.btnResetView):
        btn.setProperty("role", "secondaryButton")
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
    self.speedSlider.setMinimum(0)
    self.speedSlider.setMaximum(6)
    self.speedSlider.setValue(3)
    replay_l.addWidget(self.speedLabel)
    replay_l.addWidget(self.speedSlider)
    sidebar_l.addWidget(replay_box)

    trade_box, trade_l = _card("交易操作")
    trade_box.setObjectName("tradeSection")
    self.tradeBox = trade_box
    trade_grid = QtWidgets.QGridLayout()
    trade_grid.setContentsMargins(0, 0, 0, 0)
    trade_grid.setHorizontalSpacing(SPACING["sm"])
    trade_grid.setVerticalSpacing(SPACING["sm"])
    self.btnOpenLong = QtWidgets.QPushButton("开多 (B)")
    self.btnCloseLong = QtWidgets.QPushButton("平多 (C)")
    self.btnOpenShort = QtWidgets.QPushButton("开空 (S)")
    self.btnCloseShort = QtWidgets.QPushButton("平空 (X)")
    self.btnUndo = QtWidgets.QPushButton("撤销")
    self.btnRedo = QtWidgets.QPushButton("重做")
    self.btnClearTradeRecords = QtWidgets.QPushButton("清空交易样本")
    for btn in (self.btnOpenLong, self.btnCloseLong):
        btn.setProperty("role", "successButton")
    for btn in (self.btnOpenShort, self.btnCloseShort, self.btnClearTradeRecords):
        btn.setProperty("role", "dangerButton")
    for btn in (self.btnUndo, self.btnRedo):
        btn.setProperty("role", "secondaryButton")
    self.btnClearTradeRecords.setProperty("role", "dangerGhostButton")
    trade_grid.addWidget(self.btnOpenLong, 0, 0)
    trade_grid.addWidget(self.btnCloseLong, 0, 1)
    trade_grid.addWidget(self.btnOpenShort, 1, 0)
    trade_grid.addWidget(self.btnCloseShort, 1, 1)
    trade_grid.addWidget(self.btnUndo, 2, 0)
    trade_grid.addWidget(self.btnRedo, 2, 1)
    trade_l.addLayout(trade_grid)
    sidebar_l.addWidget(trade_box)

    danger_box, danger_l = _card("交易数据管理")
    danger_box.setObjectName("dangerSection")
    self.dangerBox = danger_box
    self.btnToggleDanger = QtWidgets.QToolButton()
    self.btnToggleDanger.setText("交易数据管理")
    self.btnToggleDanger.setCheckable(True)
    self.btnToggleDanger.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
    self.btnToggleDanger.setProperty("role", "compactButton")
    self.dangerActions = QtWidgets.QWidget()
    danger_actions_l = QtWidgets.QVBoxLayout(self.dangerActions)
    danger_actions_l.setContentsMargins(0, 0, 0, 0)
    danger_actions_l.setSpacing(SPACING["sm"])

    self.tradeManagementSessionLabel = QtWidgets.QLabel("按绩效会话")
    self.tradeManagementSessionLabel.setProperty("role", "sectionLabel")
    danger_actions_l.addWidget(self.tradeManagementSessionLabel)
    self.tradeManagementSessionBox = QtWidgets.QComboBox()
    self.tradeManagementSessionBox.setObjectName("tradeManagementSessionBox")
    danger_actions_l.addWidget(self.tradeManagementSessionBox)
    self.tradeManagementSessionTradeTable = QtWidgets.QTableWidget(0, 10)
    self.tradeManagementSessionTradeTable.setObjectName("tradeManagementSessionTradeTable")
    self.tradeManagementSessionTradeTable.setHorizontalHeaderLabels(
        [
            "交易",
            "品种",
            "方向",
            "开仓时间",
            "平仓时间",
            "开仓价",
            "平仓价",
            "数量",
            "PnL",
            "状态",
        ]
    )
    self.tradeManagementSessionTradeTable.setEditTriggers(
        QtWidgets.QAbstractItemView.NoEditTriggers
    )
    self.tradeManagementSessionTradeTable.setSelectionBehavior(
        QtWidgets.QAbstractItemView.SelectRows
    )
    self.tradeManagementSessionTradeTable.setSelectionMode(
        QtWidgets.QAbstractItemView.SingleSelection
    )
    self.tradeManagementSessionTradeTable.verticalHeader().setVisible(False)
    self.tradeManagementSessionTradeTable.setMinimumHeight(132)
    self.tradeManagementSessionTradeTable.setMaximumHeight(180)
    self.btnDeleteSessionTrade = QtWidgets.QPushButton("删除选中交易样本")
    self.btnDeleteSessionTrade.setProperty("role", "dangerGhostButton")
    danger_actions_l.addWidget(self.tradeManagementSessionTradeTable)
    danger_actions_l.addWidget(self.btnDeleteSessionTrade)

    self.tradeManagementRangeLabel = QtWidgets.QLabel("按回放时间段")
    self.tradeManagementRangeLabel.setProperty("role", "sectionLabel")
    danger_actions_l.addWidget(self.tradeManagementRangeLabel)
    range_form = QtWidgets.QFormLayout()
    range_form.setContentsMargins(0, 0, 0, 0)
    range_form.setSpacing(SPACING["sm"])
    range_form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
    self.tradeManagementStart = QtWidgets.QDateTimeEdit()
    self.tradeManagementStart.setObjectName("tradeManagementStart")
    self.tradeManagementStart.setCalendarPopup(True)
    self.tradeManagementStart.setDisplayFormat("yyyy-MM-dd HH:mm")
    self.tradeManagementStart.setDateTime(
        QtCore.QDateTime(self.startDate.date(), QtCore.QTime(0, 0))
    )
    self.tradeManagementEnd = QtWidgets.QDateTimeEdit()
    self.tradeManagementEnd.setObjectName("tradeManagementEnd")
    self.tradeManagementEnd.setCalendarPopup(True)
    self.tradeManagementEnd.setDisplayFormat("yyyy-MM-dd HH:mm")
    self.tradeManagementEnd.setDateTime(
        QtCore.QDateTime(self.endDate.date().addDays(1), QtCore.QTime(0, 0))
    )
    self.tradeManagementStartLabel = QtWidgets.QLabel("开始")
    self.tradeManagementEndLabel = QtWidgets.QLabel("结束")
    range_form.addRow(self.tradeManagementStartLabel, self.tradeManagementStart)
    range_form.addRow(self.tradeManagementEndLabel, self.tradeManagementEnd)
    danger_actions_l.addLayout(range_form)
    self.btnPreviewTradeRange = QtWidgets.QPushButton("预览时间段")
    self.btnPreviewTradeRange.setProperty("role", "secondaryButton")
    danger_actions_l.addWidget(self.btnPreviewTradeRange)
    self.tradeManagementPreviewLabel = QtWidgets.QLabel("尚未预览")
    self.tradeManagementPreviewLabel.setProperty("role", "muted")
    self.tradeManagementPreviewLabel.setWordWrap(True)
    danger_actions_l.addWidget(self.tradeManagementPreviewLabel)
    self.tradeManagementCandidateBox = QtWidgets.QComboBox()
    self.tradeManagementCandidateBox.setObjectName("tradeManagementCandidateBox")
    danger_actions_l.addWidget(self.tradeManagementCandidateBox)
    self.btnDeleteSelectedTrade = QtWidgets.QPushButton("删除选中交易样本")
    self.btnDeleteTradeRange = QtWidgets.QPushButton("删除时间段交易数据")
    for button in (self.btnDeleteSelectedTrade, self.btnDeleteTradeRange):
        button.setProperty("role", "dangerGhostButton")
        danger_actions_l.addWidget(button)
    danger_actions_l.addWidget(self.btnClearTradeRecords)
    self.dangerActions.setVisible(False)
    danger_l.addWidget(self.btnToggleDanger)
    danger_l.addWidget(self.dangerActions)
    sidebar_l.addWidget(danger_box)

    exec_box, exec_l = _card("交易成本设置")
    exec_box.setObjectName("executionSection")
    exec_box.setMinimumWidth(0)
    exec_box.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
    exec_form = QtWidgets.QFormLayout()
    exec_form.setContentsMargins(0, 0, 0, 0)
    exec_form.setSpacing(SPACING["sm"])
    exec_form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
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
    self.takeProfitPctSpin = NullablePercentInput()
    self.takeProfitPctSpin.setObjectName("takeProfitPctInput")
    self.stopLossPctSpin = NullablePercentInput()
    self.stopLossPctSpin.setObjectName("stopLossPctInput")
    exec_form.addRow("成交模式", self.fillModeBox)
    exec_form.addRow("手续费 bps", self.feeBpsSpin)
    exec_form.addRow("滑点 bps", self.slippageBpsSpin)
    self.tradeNotionalLabel = QtWidgets.QLabel("每笔名义金额")
    self.tradeNotionalLabel.setMinimumWidth(
        self.tradeNotionalLabel.fontMetrics().horizontalAdvance(self.tradeNotionalLabel.text())
    )
    self.tradeNotionalLabel.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)
    exec_form.addRow(self.tradeNotionalLabel, self.tradeNotionalSpin)
    exec_form.addRow("初始权益", self.initialEquitySpin)
    exec_form.addRow("止盈 %", self.takeProfitPctSpin)
    exec_form.addRow("止损 %", self.stopLossPctSpin)
    exec_l.addLayout(exec_form)
    self.executionSettingsBox = exec_box
    self.executionSettingsBox.setVisible(True)

    tag_box, tag_l = _card("快捷标注")
    tag_box.setObjectName("tagSection")
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
    self.noteEdit.setObjectName("noteEdit")
    self.noteEdit.setPlaceholderText("备注会写入选中事件，或随下一次开仓/平仓事件保存。")
    self.noteEdit.setFixedHeight(82)
    self.eventHintLabel = QtWidgets.QLabel("先选择事件可编辑标签；未选择事件时，当前标签随下一次交易事件写入。")
    self.eventHintLabel.setProperty("role", "muted")
    self.eventHintLabel.setWordWrap(True)
    self.btnApplyEventMeta = QtWidgets.QPushButton("保存事件")
    self.btnApplyEventMeta.setProperty("role", "secondaryButton")
    tag_l.addWidget(self.noteEdit)
    tag_l.addWidget(self.eventHintLabel)
    tag_l.addWidget(self.btnApplyEventMeta)
    sidebar_l.addWidget(tag_box)

    export_box, export_l = _card("工具")
    export_box.setObjectName("toolsSection")
    self.toolsBox = export_box
    self.btnExport = QtWidgets.QPushButton("导出会话 (E)")
    self.btnAnalysis = self.btnAnalysisWorkspace
    self.btnSettings = QtWidgets.QPushButton("设置")
    self.btnTheme = self.btnSettings
    self.btnExport.setProperty("role", "primaryButton")
    self.btnSettings.setProperty("role", "secondaryButton")
    export_l.addWidget(self.btnExport)
    export_l.addWidget(self.btnSettings)
    sidebar_l.addWidget(export_box)
    sidebar_l.addStretch(1)
    sidebar_scroll.setWidget(sidebar_content)
    left_l.addWidget(sidebar_scroll)

    self.btnExport.setText("导出")
    self.btnExport.setProperty("role", "headerAction")
    self.btnSettings.setProperty("role", "headerAction")
    self.btnToggleRightPanel = QtWidgets.QToolButton()
    self.btnToggleRightPanel.setText("面板")
    self.btnToggleRightPanel.setCheckable(True)
    self.btnToggleRightPanel.setChecked(True)
    self.btnToggleRightPanel.setProperty("role", "headerActionAccent")
    header_l.addWidget(self.btnExport)
    header_l.addWidget(self.btnSettings)
    header_l.addWidget(self.btnToggleRightPanel)

    # ---------- Central workspace ----------
    center = QtWidgets.QWidget()
    center.setObjectName("centerWorkspace")
    center.setProperty("role", "transparent")
    center_l = QtWidgets.QVBoxLayout(center)
    center_l.setContentsMargins(0, 0, 0, 0)
    center_l.setSpacing(0)
    self.centerSplitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
    self.centerSplitter.setChildrenCollapsible(False)
    self.centerSplitter.setHandleWidth(4)
    center_l.addWidget(self.centerSplitter)

    chart_panel = QtWidgets.QFrame()
    chart_panel.setObjectName("chartCard")
    chart_panel.setProperty("role", "chartCard")
    self.chartCard = chart_panel
    chart_l = QtWidgets.QVBoxLayout(chart_panel)
    chart_l.setContentsMargins(SPACING["md"], SPACING["sm"], SPACING["md"], SPACING["md"])
    chart_l.setSpacing(SPACING["sm"])

    market_toolbar = QtWidgets.QFrame()
    market_toolbar.setObjectName("marketToolbar")
    market_toolbar.setProperty("role", "workspaceToolbar")
    market_toolbar_l = QtWidgets.QHBoxLayout(market_toolbar)
    market_toolbar_l.setContentsMargins(SPACING["sm"], SPACING["xs"], SPACING["sm"], SPACING["xs"])
    market_toolbar_l.setSpacing(SPACING["sm"])
    for label_text, control in (("品种", self.symbolBox),):
        label = QtWidgets.QLabel(label_text)
        label.setProperty("role", "muted")
        market_toolbar_l.addWidget(label)
        market_toolbar_l.addWidget(control)
    for label_text, control in (("开始", self.startDate), ("结束", self.endDate)):
        label = QtWidgets.QLabel(label_text)
        label.setProperty("role", "muted")
        market_toolbar_l.addWidget(label)
        market_toolbar_l.addWidget(control)
    market_toolbar_l.addWidget(self.btnApplyMarket)
    market_toolbar_l.addWidget(self.headerMainLabel, 1)
    market_toolbar_l.addWidget(self.headerEquityValue)
    market_toolbar_l.addWidget(self.headerReturnValue)
    market_toolbar_l.addWidget(self.marketDirtyHint)
    market_toolbar_l.addStretch(1)
    chart_l.addWidget(market_toolbar)
    chart_l.addWidget(self.symbolPanel)

    replay_toolbar = QtWidgets.QFrame()
    replay_toolbar.setObjectName("replayToolbar")
    replay_toolbar.setProperty("role", "workspaceToolbar")
    replay_toolbar_l = QtWidgets.QHBoxLayout(replay_toolbar)
    replay_toolbar_l.setContentsMargins(SPACING["sm"], SPACING["xs"], SPACING["sm"], SPACING["xs"])
    replay_toolbar_l.setSpacing(SPACING["sm"])
    replay_toolbar_l.addWidget(self.btnLoadPlay)
    replay_toolbar_l.addWidget(self.btnStep)
    replay_toolbar_l.addWidget(self.btnToEnd)
    replay_toolbar_l.addWidget(self.btnFollow)
    replay_toolbar_l.addWidget(self.btnResetView)
    self.replayPerformanceSessionLabel = QtWidgets.QLabel("绩效会话")
    self.replayPerformanceSessionLabel.setProperty("role", "muted")
    self.replayPerformanceSessionBox = QtWidgets.QComboBox()
    self.replayPerformanceSessionBox.setObjectName("replayPerformanceSessionBox")
    self.replayPerformanceSessionBox.setMinimumWidth(0)
    self.replayPerformanceSessionBox.setMaximumWidth(260)
    self.replayPerformanceSessionBox.setSizePolicy(
        QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed
    )
    self.btnContinuePerformanceSession = QtWidgets.QPushButton("继续绩效会话")
    self.btnContinuePerformanceSession.setProperty("role", "secondaryButton")
    self.btnContinuePerformanceSession.setMaximumWidth(130)
    self.btnContinuePerformanceSession.setSizePolicy(
        QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed
    )
    replay_toolbar_l.addWidget(self.replayPerformanceSessionLabel)
    replay_toolbar_l.addWidget(self.replayPerformanceSessionBox, 1)
    replay_toolbar_l.addWidget(self.btnContinuePerformanceSession)
    replay_toolbar_l.addWidget(self.speedLabel)
    self.speedSlider.setFixedWidth(128)
    replay_toolbar_l.addWidget(self.speedSlider)
    chart_l.addWidget(replay_toolbar)
    chart_toolbar = QtWidgets.QFrame()
    chart_toolbar.setObjectName("chartToolbar")
    chart_toolbar.setProperty("role", "chartToolbar")
    toolbar_l = QtWidgets.QHBoxLayout(chart_toolbar)
    toolbar_l.setContentsMargins(SPACING["sm"], SPACING["xs"], SPACING["sm"], SPACING["xs"])
    toolbar_l.setSpacing(SPACING["sm"])
    self.chartSectionLabel = QtWidgets.QLabel("行情回放")
    self.chartSectionLabel.setProperty("role", "toolbarTitle")
    toolbar_l.addWidget(self.chartSectionLabel)
    self.status = QtWidgets.QLabel("未加载数据")
    self.status.setProperty("role", "tiny")
    self.status.setMinimumWidth(0)
    self.status.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
    toolbar_l.addWidget(self.status, stretch=1)
    self.btnToggleBottomPanel = QtWidgets.QToolButton()
    self.btnToggleBottomPanel.setText("收起结果")
    self.btnToggleBottomPanel.setCheckable(True)
    self.btnToggleBottomPanel.setProperty("role", "compactButton")
    toolbar_l.addWidget(self.btnToggleBottomPanel)
    self.chartIntervalButtons = {}
    for index in range(self.intervalBox.count()):
        text = self.intervalBox.itemText(index)
        chip = QtWidgets.QPushButton(text)
        chip.setProperty("role", "intervalChip")
        chip.setCheckable(True)
        chip_width = max(34, chip.fontMetrics().horizontalAdvance(text) + 18)
        chip.setFixedWidth(chip_width)
        chip.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)
        self.chartIntervalButtons[text] = chip
        toolbar_l.addWidget(chip)
    chart_l.addWidget(chart_toolbar)

    self.glw = _ManagedGraphicsLayoutWidget(self)
    render_backend = str(getattr(self, "app_settings", {}).get("render_backend") or "hardware")
    self._chart_uses_opengl = configure_high_refresh_viewport(self.glw, backend=render_backend)
    if self._chart_uses_opengl:
        def verify_chart_viewport():
            self._chart_uses_opengl = verify_high_refresh_viewport(self.glw)

        QtCore.QTimer.singleShot(250, verify_chart_viewport)
    self.glw.setMinimumHeight(320)
    chart_l.addWidget(self.glw, stretch=1)

    self.axis_price = IndexTimeAxis("bottom")
    self.axis_vol = IndexTimeAxis("bottom")
    self.axis_current_price = CurrentPriceAxis("right")
    self.vb_price = KViewBox()
    self.vb_vol = KViewBox()
    self.pricePlot = _build_disabled_plot_item(
        viewBox=self.vb_price,
        axisItems={"bottom": self.axis_price, "right": self.axis_current_price},
    )
    self.volPlot = _build_disabled_plot_item(
        viewBox=self.vb_vol,
        axisItems={"bottom": self.axis_vol},
    )
    self.glw.addItem(self.pricePlot, row=0, col=0)
    self.glw.addItem(self.volPlot, row=1, col=0)
    # Replace the disabled menu while PlotItem is intact. Releasing the original
    # Python wrapper is sufficient; a competing DeferredDelete request can race
    # the parent/graphics teardown on Windows.
    _replace_disabled_plot_menu(self.pricePlot, self.glw)
    _replace_disabled_plot_menu(self.volPlot, self.glw)
    self.glw.manage_plots(self.pricePlot, self.volPlot)
    self.volPlot.setXLink(self.pricePlot)
    self.volPlot.setMaximumHeight(170)
    self.pricePlot.showAxis("right")
    self.pricePlot.getAxis("right").linkToView(self.vb_price)
    self.pricePlot.getAxis("right").setStyle(showValues=True)
    self.pricePlot.showGrid(x=True, y=True, alpha=0.14)
    self.volPlot.showGrid(x=True, y=True, alpha=0.14)
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

    self.currentPriceLine = pg.InfiniteLine(
        angle=0,
        movable=False,
        pen=pg.mkPen(COLORS["chart_crosshair"], style=QtCore.Qt.DashLine, width=1),
    )
    self.pricePlot.addItem(self.currentPriceLine, ignoreBounds=True)

    self.candleItem = CandlestickItem()
    self.volItem = VolumeItem()
    self.currentPriceLine.setZValue(-10)
    self.candleItem.setZValue(0)
    self.pricePlot.addItem(self.candleItem)
    self.volPlot.addItem(self.volItem)

    self.scatter_open_long = pg.ScatterPlotItem(symbol="t1", size=14, brush=pg.mkBrush(COLORS["chart_up"]), pen=pg.mkPen(COLORS["chart_up"]))
    self.scatter_open_short = pg.ScatterPlotItem(symbol="t", size=14, brush=pg.mkBrush(COLORS["chart_down"]), pen=pg.mkPen(COLORS["chart_down"]))
    self.scatter_close_long = pg.ScatterPlotItem(symbol="x", size=12, brush=pg.mkBrush(COLORS["marker_close_long"]), pen=pg.mkPen(COLORS["marker_close_long"]))
    self.scatter_close_short = pg.ScatterPlotItem(symbol="x", size=12, brush=pg.mkBrush(COLORS["marker_close_short"]), pen=pg.mkPen(COLORS["marker_close_short"]))
    for item in (self.scatter_open_long, self.scatter_open_short, self.scatter_close_long, self.scatter_close_short):
        self.pricePlot.addItem(item)

    # Result tables are built before the bottom tabs so existing presenters keep the same targets.
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
    self.closedTradesTable.setHorizontalHeaderLabels([
        "\u4ea4\u6613ID", "\u65b9\u5411", "\u5f00\u4ed3\u65f6\u95f4", "\u5e73\u4ed3\u65f6\u95f4", "\u5f00\u4ed3\u6210\u4ea4", "\u5e73\u4ed3\u6210\u4ea4",
        "\u6bdb\u6536\u76ca%", "\u51c0\u6536\u76ca%", "\u624b\u7eed\u8d39", "\u51c0\u76c8\u4e8f", "\u6301\u4ed3K\u7ebf", "\u72b6\u6001", "\u6210\u4ea4\u6a21\u5f0f",
    ])

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
    event_filters.setSpacing(SPACING["sm"])
    event_filters.addWidget(self.eventFilterTag)
    event_filters.addWidget(self.eventFilterSide)
    event_filters.addWidget(self.eventFilterType)
    self.eventTab = QtWidgets.QWidget()
    event_tab_layout = QtWidgets.QVBoxLayout(self.eventTab)
    event_tab_layout.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
    event_tab_layout.setSpacing(SPACING["sm"])
    event_tab_layout.addLayout(event_filters)
    event_tab_layout.addWidget(self.eventTable)

    self.performanceText = QtWidgets.QPlainTextEdit()
    self.performanceText.setReadOnly(True)
    self.performanceText.setMinimumHeight(140)
    self.performanceText.setPlainText("暂无绩效统计")

    self.equityTable = QtWidgets.QTableWidget()
    self.equityTable.setColumnCount(8)
    self.equityTable.setHorizontalHeaderLabels([
        "序号", "K线/交易", "已实现", "浮盈亏", "持仓/费用", "权益", "收益%", "回撤%",
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
    self.datasetText.setMinimumHeight(140)
    self.datasetText.setPlainText("暂无机器学习样本信息。导出后会生成特征表、标签表和样本索引。")

    bottom_tabs = QtWidgets.QTabWidget()
    bottom_tabs.setObjectName("bottomTabs")
    bottom_tabs.setMinimumHeight(155)
    self.bottomTabs = bottom_tabs
    trade_tabs = QtWidgets.QTabWidget()
    self.tradeResultsTabs = trade_tabs
    trade_tabs.addTab(_table_box(self.openTradesTable), "当前持仓")
    trade_tabs.addTab(_table_box(self.closedTradesTable), "成交历史")
    self.tradeResultsStack = QtWidgets.QStackedWidget()
    self.emptyTradeResults = _empty_state("暂无交易样本", "回放中开仓或平仓后，这里会显示记录")
    self.tradeResultsStack.addWidget(self.emptyTradeResults)
    self.tradeResultsStack.addWidget(trade_tabs)
    event_research_tabs = QtWidgets.QTabWidget()
    self.eventResearchTabs = event_research_tabs
    event_research_tabs.addTab(_table_box(self.eventStudyTable), "事件研究统计")
    event_research_tabs.addTab(self.eventTab, "事件列表")
    self.eventResearchStack = QtWidgets.QStackedWidget()
    self.emptyEventStudy = _empty_state("暂无事件研究", "标注事件后可查看未来收益统计")
    self.eventResearchStack.addWidget(self.emptyEventStudy)
    self.eventResearchStack.addWidget(event_research_tabs)
    self.equityStack = _stacked_empty_table("暂无账户收益", "平仓后这里会显示权益曲线和回撤记录", self.equityTable)
    self.performanceStack = QtWidgets.QStackedWidget()
    self.emptyPerformance = _empty_state("暂无绩效统计", "平仓后生成胜率、盈亏比和回撤")
    self.performanceStack.addWidget(self.emptyPerformance)
    self.performanceStack.addWidget(self.performanceText)
    self.datasetStack = QtWidgets.QStackedWidget()
    self.emptyDataset = _empty_state("暂无样本概览", "导出或刷新研究样本后，这里会显示特征、标签和样本索引摘要")
    self.datasetStack.addWidget(self.emptyDataset)
    self.datasetStack.addWidget(self.datasetText)
    bottom_tabs.addTab(self.tradeResultsStack, "持仓与成交")
    bottom_tabs.addTab(self.equityStack, "账户收益")
    bottom_tabs.addTab(self.performanceStack, "绩效统计")
    bottom_tabs.addTab(self.eventResearchStack, "事件研究")
    bottom_tabs.addTab(self.datasetStack, "样本概览")

    self.centerSplitter.addWidget(chart_panel)
    self.centerSplitter.addWidget(bottom_tabs)
    self.centerSplitter.setStretchFactor(0, 5)
    self.centerSplitter.setStretchFactor(1, 1)
    self.centerSplitter.setSizes([720, 220])

    # ---------- Right sidebar ----------
    right = QtWidgets.QFrame()
    right.setObjectName("rightPanel")
    right.setProperty("role", "rightPanel")
    self.rightPanel = right
    right.setMinimumWidth(300)
    right.setMaximumWidth(460)
    right_l = QtWidgets.QVBoxLayout(right)
    right_l.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
    right_l.setSpacing(SPACING["sm"])

    tabs = QtWidgets.QTabWidget()
    self.rightTabs = tabs

    right_rail = QtWidgets.QFrame()
    right_rail.setObjectName("rightPanelRail")
    right_rail.setProperty("role", "rightRail")
    right_rail_l = QtWidgets.QVBoxLayout(right_rail)
    right_rail_l.setContentsMargins(4, 8, 4, 8)
    right_rail_l.setSpacing(SPACING["sm"])
    self.rightRailButtons = []
    for text, tooltip in (("交", "交易"), ("态", "状态"), ("标", "标注")):
        button = QtWidgets.QToolButton()
        button.setText(text)
        button.setToolTip(tooltip)
        button.setProperty("role", "compactButton")
        button.setFixedSize(34, 34)
        right_rail_l.addWidget(button)
        self.rightRailButtons.append(button)
    right_rail_l.addStretch(1)
    right_rail.hide()
    self.rightPanelRail = right_rail
    right_l.addWidget(right_rail, stretch=1)

    trade_page = QtWidgets.QWidget()
    trade_page.setObjectName("rightTradePage")
    trade_page.setProperty("role", "tabPage")
    trade_page_l = QtWidgets.QVBoxLayout(trade_page)
    trade_page_l.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
    trade_page_l.setSpacing(SPACING["md"])

    trade_position_card = QtWidgets.QFrame()
    trade_position_card.setObjectName("tradeCurrentPositionCard")
    trade_position_card.setProperty("role", "statusBlock")
    trade_position_l = QtWidgets.QVBoxLayout(trade_position_card)
    trade_position_l.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
    trade_position_l.setSpacing(SPACING["sm"])
    trade_position_title = QtWidgets.QLabel("当前持仓")
    trade_position_title.setProperty("role", "sectionTitle")
    trade_position_l.addWidget(trade_position_title)
    self.tradePositionEmptyState = _empty_state("无持仓", "开仓后在此显示当前持仓", compact=True)
    self.tradePositionEmptyHost = QtWidgets.QWidget()
    trade_empty_l = QtWidgets.QVBoxLayout(self.tradePositionEmptyHost)
    trade_empty_l.setContentsMargins(0, 0, 0, 0)
    trade_empty_l.addStretch(1)
    trade_empty_l.addWidget(self.tradePositionEmptyState)
    trade_empty_l.addStretch(1)
    trade_position_l.addWidget(self.tradePositionEmptyHost, 1)
    self.tradePositionScroll = QtWidgets.QScrollArea()
    self.tradePositionScroll.setObjectName("tradePositionScroll")
    self.tradePositionScroll.setWidgetResizable(True)
    self.tradePositionScroll.setFrameShape(QtWidgets.QFrame.NoFrame)
    self.tradePositionScroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    self.tradePositionScroll.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.AdjustIgnored)
    self.tradePositionCards = QtWidgets.QWidget()
    self.tradePositionCards.setObjectName("tradePositionCards")
    self.tradePositionCardsLayout = QtWidgets.QVBoxLayout(self.tradePositionCards)
    self.tradePositionCardsLayout.setContentsMargins(0, 0, 0, 0)
    self.tradePositionCardsLayout.setSpacing(SPACING["sm"])
    self.tradePositionScroll.setWidget(self.tradePositionCards)
    self.tradePositionScroll.hide()
    trade_position_l.addWidget(self.tradePositionScroll, 1)
    trade_position_card.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
    self.tradeCurrentPositionCard = trade_position_card
    trade_page_l.addWidget(trade_position_card, 1)
    for section in (trade_box, exec_box, danger_box):
        section.setProperty("role", "embeddedSection")
        trade_page_l.addWidget(section)
    trade_scroll = QtWidgets.QScrollArea()
    trade_scroll.setObjectName("rightTradeScroll")
    trade_scroll.setWidgetResizable(True)
    trade_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
    trade_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    trade_scroll.setWidget(trade_page)
    self.rightTradePage = trade_scroll

    overview = QtWidgets.QWidget()
    overview.setObjectName("rightOverviewPage")
    overview.setProperty("role", "tabPage")
    overview.setMinimumWidth(0)
    overview.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
    overview_l = QtWidgets.QVBoxLayout(overview)
    overview_l.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
    overview_l.setSpacing(SPACING["md"])

    position_card = QtWidgets.QFrame()
    position_card.setObjectName("currentStatusCard")
    position_card.setProperty("role", "statusBlock")
    self.currentStatusCard = position_card
    position_l = QtWidgets.QVBoxLayout(position_card)
    position_l.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
    position_l.setSpacing(SPACING["sm"])
    title_position = QtWidgets.QLabel("当前状态")
    title_position.setProperty("role", "sectionTitle")
    position_l.addWidget(title_position)
    self.positionEmptyState = _empty_state("无持仓", "开仓后显示数量、入场价和浮动盈亏", compact=True)
    position_l.addWidget(self.positionEmptyState)
    self.positionDetails = QtWidgets.QWidget()
    position_details_l = QtWidgets.QVBoxLayout(self.positionDetails)
    position_details_l.setContentsMargins(0, 0, 0, 0)
    position_details_l.setSpacing(SPACING["sm"])
    self.positionSideValue = _metric_label()
    self.positionQtyValue = _metric_label()
    self.positionEntryValue = _metric_label()
    self.positionCurrentValue = _metric_label()
    self.positionPnlValue = _metric_label()
    self.positionPnlPctValue = _metric_label()
    for label, value in (
        ("方向", self.positionSideValue),
        ("数量", self.positionQtyValue),
        ("入场价", self.positionEntryValue),
        ("当前价", self.positionCurrentValue),
        ("浮动盈亏", self.positionPnlValue),
        ("未实现盈亏率", self.positionPnlPctValue),
    ):
        position_details_l.addWidget(_value_row(label, value))
    self.positionDetails.setVisible(False)
    position_l.addWidget(self.positionDetails)
    self.openPositionsMiniTable = QtWidgets.QTableWidget()
    self.openPositionsMiniTable.setColumnCount(6)
    self.openPositionsMiniTable.setHorizontalHeaderLabels(["交易", "方向", "入场", "浮盈亏", "TP", "SL"])
    self.openPositionsMiniTable.verticalHeader().setVisible(False)
    self.openPositionsMiniTable.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    self.openPositionsMiniTable.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    self.openPositionsMiniTable.setAlternatingRowColors(True)
    self.openPositionsMiniTable.setMinimumWidth(0)
    self.openPositionsMiniTable.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
    self.openPositionsMiniTable.setMaximumHeight(132)
    self.openPositionsMiniTable.horizontalHeader().setMinimumSectionSize(28)
    self.openPositionsMiniTable.horizontalHeader().setDefaultSectionSize(46)
    self.openPositionsMiniTable.setColumnWidth(0, 132)
    self.openPositionsMiniTable.horizontalHeader().setStretchLastSection(True)
    self.openPositionsMiniTable.setVisible(False)
    position_l.addWidget(self.openPositionsMiniTable)
    overview_l.addWidget(position_card)

    account_card = QtWidgets.QFrame()
    account_card.setObjectName("accountOverviewCard")
    account_card.setProperty("role", "statusBlock")
    self.accountOverviewCard = account_card
    account_l = QtWidgets.QVBoxLayout(account_card)
    account_l.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
    account_l.setSpacing(SPACING["sm"])
    account_title = QtWidgets.QLabel("账户总览")
    account_title.setProperty("role", "sectionTitle")
    account_l.addWidget(account_title)
    self.accountEquityValue = _metric_label()
    self.accountReturnValue = _metric_label()
    self.accountPnlValue = _metric_label()
    self.accountWinRateValue = _metric_label()
    self.accountSharpeValue = _metric_label()
    self.accountProfitFactorValue = _metric_label()
    self.accountPayoffValue = _metric_label()
    self.accountMaxDrawdownValue = _metric_label()
    for label, value in (
        ("当前权益", self.accountEquityValue),
        ("总收益率", self.accountReturnValue),
        ("总盈亏", self.accountPnlValue),
        ("总胜率", self.accountWinRateValue),
        ("夏普比率", self.accountSharpeValue),
        ("利润因子", self.accountProfitFactorValue),
        ("盈亏比", self.accountPayoffValue),
        ("最大回撤", self.accountMaxDrawdownValue),
    ):
        account_l.addWidget(_value_row(label, value))
    overview_l.addWidget(account_card)

    recent_card = QtWidgets.QFrame()
    recent_card.setObjectName("recentEventsCard")
    recent_card.setProperty("role", "statusBlock")
    recent_l = QtWidgets.QVBoxLayout(recent_card)
    recent_l.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
    recent_l.setSpacing(SPACING["sm"])
    recent_title = QtWidgets.QLabel("最近事件")
    recent_title.setProperty("role", "sectionTitle")
    recent_l.addWidget(recent_title)
    self.recentEventsEmptyState = _empty_state("暂无事件", "标注或交易后显示在这里", compact=True)
    recent_l.addWidget(self.recentEventsEmptyState)
    self.recentEventsList = QtWidgets.QWidget()
    self.recentEventsList.setProperty("role", "softPanel")
    self.recentEventsListLayout = QtWidgets.QVBoxLayout(self.recentEventsList)
    self.recentEventsListLayout.setContentsMargins(0, 0, 0, 0)
    self.recentEventsListLayout.setSpacing(SPACING["sm"])
    self.recentEventsList.setVisible(False)
    recent_l.addWidget(self.recentEventsList)
    overview_l.addWidget(recent_card)

    candle_card = QtWidgets.QFrame()
    candle_card.setObjectName("currentCandleCard")
    candle_card.setProperty("role", "statusBlock")
    candle_l = QtWidgets.QVBoxLayout(candle_card)
    candle_l.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
    candle_l.setSpacing(SPACING["sm"])
    self.candleTitleLabel = QtWidgets.QLabel("当前K线详情")
    self.candleTitleLabel.setProperty("role", "sectionTitle")
    candle_l.addWidget(self.candleTitleLabel)
    self.barTimeValue = _metric_label()
    self.barOpenValue = _metric_label()
    self.barHighValue = _metric_label()
    self.barLowValue = _metric_label()
    self.barCloseValue = _metric_label()
    self.barVolumeValue = _metric_label()
    self.barIndexValue = _metric_label()
    self.barDetailLabels = {}
    for key, label, value in (
        ("time", "时间", self.barTimeValue),
        ("open", "开盘价", self.barOpenValue),
        ("high", "最高价", self.barHighValue),
        ("low", "最低价", self.barLowValue),
        ("close", "收盘价", self.barCloseValue),
        ("volume", "成交量", self.barVolumeValue),
        ("index", "K线序号", self.barIndexValue),
    ):
        row = _value_row(label, value)
        self.barDetailLabels[key] = row.nameLabel
        candle_l.addWidget(row)
    overview_l.addWidget(candle_card)

    overview_scroll = QtWidgets.QScrollArea()
    overview_scroll.setObjectName("rightOverviewScroll")
    overview_scroll.setWidgetResizable(True)
    overview_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
    overview_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    overview_scroll.setWidget(overview)
    self.rightOverviewScroll = overview_scroll
    self.multiTimeframePanel = MultiTimeframePanel(
        language=self.current_language,
        parent=self,
        start_worker=bool(getattr(self, "_start_multi_timeframe_worker", True)),
        lifecycle=getattr(self, "task_lifecycle", None),
    )
    self.backtestPanel = None
    self.strategyConsistencyPanel = None

    detail_box = QtWidgets.QFrame()
    detail_box.setObjectName("detailCard")
    detail_box.setProperty("role", "statusBlock")
    self.detailBox = detail_box
    detail_l = QtWidgets.QVBoxLayout(detail_box)
    detail_l.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
    detail_l.setSpacing(SPACING["sm"])
    self.btnToggleDetail = QtWidgets.QPushButton("隐藏详情")
    self.btnToggleDetail.setCheckable(True)
    self.btnToggleDetail.setProperty("role", "secondaryButton")
    self.detailText = QtWidgets.QPlainTextEdit()
    self.detailText.setReadOnly(True)
    self.detailText.setPlainText("无")
    self.detailText.setMinimumHeight(220)
    detail_l.addWidget(self.btnToggleDetail)
    detail_l.addWidget(self.detailText)
    overview_l.addWidget(self.multiTimeframePanel)
    overview_l.addWidget(detail_box)
    overview_l.addStretch(1)

    annotation_page = QtWidgets.QWidget()
    annotation_page.setObjectName("rightAnnotationPage")
    annotation_page.setProperty("role", "tabPage")
    annotation_page_l = QtWidgets.QVBoxLayout(annotation_page)
    annotation_page_l.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
    annotation_page_l.setSpacing(SPACING["md"])
    tag_box.setProperty("role", "embeddedSection")
    annotation_page_l.addWidget(tag_box)
    annotation_page_l.addStretch(1)
    annotation_scroll = QtWidgets.QScrollArea()
    annotation_scroll.setObjectName("rightAnnotationScroll")
    annotation_scroll.setWidgetResizable(True)
    annotation_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
    annotation_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    annotation_scroll.setWidget(annotation_page)
    self.rightAnnotationPage = annotation_scroll

    tabs.addTab(trade_scroll, "交易")
    tabs.addTab(overview_scroll, "状态")
    tabs.addTab(annotation_scroll, "标注")
    tabs.setCurrentWidget(trade_scroll)
    right_l.addWidget(tabs, stretch=1)
    for index, button in enumerate(self.rightRailButtons):
        button.clicked.connect(lambda _checked=False, tab_index=index: (
            tabs.setCurrentIndex(tab_index),
            self.btnToggleRightPanel.setChecked(True),
        ))

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
    self.premiumPlot = _ManagedPlotWidget()
    self.premiumPlot.showGrid(x=True, y=True, alpha=0.14)
    self.premiumPlot.addLegend(offset=(8, 8))
    self.premiumBuyCurve = self.premiumPlot.plot([], [], pen=pg.mkPen(COLORS["success"], width=1.5, style=QtCore.Qt.DashLine), symbol="o", symbolSize=4, name="买入溢价")
    self.premiumSellCurve = self.premiumPlot.plot([], [], pen=pg.mkPen(COLORS["danger"], width=1.5, style=QtCore.Qt.DotLine), symbol="t", symbolSize=4, name="卖出溢价")
    self.premiumAvgCurve = self.premiumPlot.plot([], [], pen=pg.mkPen(COLORS["chart_axis"], width=1.8), symbol="s", symbolSize=4, name="均价溢价")
    premium_l.addWidget(self.premiumStatus)
    premium_l.addWidget(self.premiumStats)
    premium_l.addWidget(self.premiumPlot, stretch=1)

    body.addWidget(center)
    body.addWidget(right)
    body.setStretchFactor(0, 1)
    body.setStretchFactor(1, 0)
    body.setSizes([1180, 360])
    left.hide()

    self._expanded_right_panel_width = 360

    def set_right_panel_visible(visible: bool) -> None:
        visible = bool(visible)
        if visible:
            right.setMinimumWidth(300)
            right.setMaximumWidth(460)
            right_rail.hide()
            tabs.show()
            body.setSizes([max(1, body.width() - self._expanded_right_panel_width), self._expanded_right_panel_width])
        else:
            sizes = body.sizes()
            if len(sizes) == 2 and sizes[1] >= 300:
                self._expanded_right_panel_width = max(300, min(460, sizes[1]))
            tabs.hide()
            right_rail.show()
            right.setMinimumWidth(48)
            right.setMaximumWidth(48)
            body.setSizes([max(1, body.width() - 48), 48])
        self.btnToggleRightPanel.setText("收起面板" if visible else "展开面板")

    self._set_right_panel_expanded = set_right_panel_visible

    self.btnToggleRightPanel.toggled.connect(set_right_panel_visible)

    def set_bottom_panel_collapsed(collapsed: bool) -> None:
        bottom_tabs.setVisible(not collapsed)
        self.btnToggleBottomPanel.setText("展开结果" if collapsed else "收起结果")

    self.btnToggleBottomPanel.toggled.connect(set_bottom_panel_collapsed)

    # ---------- Collapsible log drawer ----------
    self.logDrawer = QtWidgets.QFrame()
    self.logDrawer.setObjectName("logDrawer")
    self.logDrawer.setProperty("role", "logDrawer")
    self.logDrawer.setMinimumHeight(32)
    self.logDrawer.setMaximumHeight(36)
    log_l = QtWidgets.QVBoxLayout(self.logDrawer)
    log_l.setContentsMargins(SPACING["md"], 2, SPACING["md"], 2)
    log_l.setSpacing(2)
    log_header = QtWidgets.QHBoxLayout()
    log_header.setSpacing(SPACING["sm"])
    log_title = QtWidgets.QLabel("操作日志")
    log_title.setProperty("role", "sectionTitle")
    self.logSummaryLabel = QtWidgets.QLabel("暂无操作")
    self.logSummaryLabel.setProperty("role", "tiny")
    self.logSummaryLabel.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
    self.btnToggleLog = QtWidgets.QPushButton("展开日志")
    self.btnToggleLog.setProperty("role", "compactButton")
    self.btnToggleLog.setCheckable(True)
    self.btnToggleLog.setChecked(True)
    log_header.addWidget(log_title)
    log_header.addWidget(self.logSummaryLabel, stretch=1)
    log_header.addWidget(self.btnToggleLog)
    self.log = QtWidgets.QPlainTextEdit()
    self.log.setProperty("role", "logText")
    self.log.setReadOnly(True)
    self.log.setMaximumBlockCount(3000)
    self.log.setMaximumHeight(160)
    self.log.setVisible(False)
    log_l.addLayout(log_header)
    log_l.addWidget(self.log)
    replay_workspace_l.addWidget(self.logDrawer)

    self._add_shortcut("Space", self.toggle_play)
    self._add_shortcut(QtCore.Qt.Key_Left, self.speed_down)
    self._add_shortcut(QtCore.Qt.Key_Right, self.speed_up)
    self._add_shortcut("Shift+Right", self.step_once)
    self._add_shortcut("F", self.toggle_follow)
    self._add_shortcut("B", lambda: self.request_open_trade("LONG"))
    self._add_shortcut("S", lambda: self.request_open_trade("SHORT"))
    self._add_shortcut("C", lambda: self.request_close_trade("LONG"))
    self._add_shortcut("X", lambda: self.request_close_trade("SHORT"))
    self._add_shortcut("Ctrl+Z", self.undo)
    self._add_shortcut("Ctrl+Y", self.redo)
    self._add_shortcut("E", self.export_session)
    self._add_shortcut("K", self.reset_view)
    install_no_wheel_on_value_inputs(self)
    self._update_header()
    self._update_load_play_button()
    self.retranslate_ui()


__all__ = ["build_main_window_ui"]
