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
    from views.i18n_bindings import (
        add_combo_item,
        add_tab,
        bind_combo_item,
        bind_group_title,
        bind_placeholder,
        bind_plain_text,
        bind_table_headers,
        bind_tab,
        bind_text,
        bind_tooltip,
    )
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
    from .i18n_bindings import (
        add_combo_item,
        add_tab,
        bind_combo_item,
        bind_group_title,
        bind_placeholder,
        bind_plain_text,
        bind_table_headers,
        bind_tab,
        bind_text,
        bind_tooltip,
    )
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


def _bind_empty_state(
    frame: QtWidgets.QFrame,
    title_key: str,
    body_key: str,
    translator,
) -> None:
    labels = frame.findChildren(QtWidgets.QLabel, options=QtCore.Qt.FindDirectChildrenOnly)
    if len(labels) >= 2:
        bind_text(labels[0], title_key, translator)
        bind_text(labels[1], body_key, translator)


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
    root.setContentsMargins(SPACING["sm"], SPACING["sm"], SPACING["sm"], SPACING["sm"])
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
    self.headerTitleLabel = QtWidgets.QLabel(f"Quant Replay Collector v{APP_VERSION}")
    self.headerTitleLabel.setProperty("role", "appTitle")
    self.headerTitleLabel.setMinimumWidth(190)
    self.headerTitleLabel.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Preferred)
    apply_header_logo(
        self.headerLogoLabel,
        getattr(self, "theme_settings", None),
        size=self.headerTitleLabel.fontMetrics().height(),
    )
    header_l.addWidget(self.headerLogoLabel)
    header_l.addWidget(self.headerTitleLabel)

    self.headerMetricLabels = {}
    self.btnReplayWorkspace = QtWidgets.QPushButton(self.tr("trading_replay"))
    self.btnReplayWorkspace.setProperty("role", "workspaceNavButton")
    self.btnReplayWorkspace.setCheckable(True)
    self.btnReplayWorkspace.setChecked(True)
    self.btnAnalysisWorkspace = QtWidgets.QPushButton(self.tr("data_analysis"))
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

    self.headerEquityValue = QtWidgets.QLabel(
        self.tr("ui.header_equity").format(value="-")
    )
    self.headerEquityValue.setProperty("role", "marketMetric")
    self.headerReturnValue = QtWidgets.QLabel(
        self.tr("ui.header_return").format(value="-")
    )
    self.headerReturnValue.setProperty("role", "marketMetric")

    self.headerSymbolValue = _hidden_header_label(header, DEFAULT_SYMBOL)
    self.headerIntervalValue = _hidden_header_label(header, DEFAULT_INTERVAL)
    self.headerDisplayIntervalValue = self.headerIntervalValue
    self.headerSampleIntervalValue = _hidden_header_label(header, f"sample {DEFAULT_INTERVAL}")
    self.headerTimeValue = _hidden_header_label(header)
    self.headerOhlcValue = _hidden_header_label(header)
    self.headerCloseValue = self.headerOhlcValue
    self.headerDeltaValue = _hidden_header_label(header)

    self.headerPlayBadge = QtWidgets.QLabel(f"● {self.tr('paused')}")
    self.headerPlayBadge.setProperty("role", "headerState")
    self.headerPlayBadge.setMinimumWidth(54)
    self.headerPlayBadge.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Preferred)
    self.headerPlayBadge.setAlignment(QtCore.Qt.AlignCenter)
    self.headerViewBadge = QtWidgets.QLabel(self.tr("free_view"))
    self.headerViewBadge.setProperty("role", "headerState")
    self.headerViewBadge.setMinimumWidth(68)
    self.headerViewBadge.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Preferred)
    self.headerViewBadge.setAlignment(QtCore.Qt.AlignCenter)
    self.headerSessionBadge = QtWidgets.QLabel()
    bind_text(self.headerSessionBadge, "ui.session_empty", self.tr)
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

    data_box, data_l = _card(self.tr("ui.market"))
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

    self.startDate = DatePicker(language=self.current_language)
    self.startDate.setObjectName("startDate")
    self.startDate.setDate(QtCore.QDate.currentDate().addDays(-2))

    self.endDate = DatePicker(language=self.current_language)
    self.endDate.setObjectName("endDate")
    self.endDate.setDate(QtCore.QDate.currentDate())
    bind_date_range(self.startDate, self.endDate)

    form.addRow(self.tr("symbol"), self.symbolBox)
    form.addRow(self.tr("ui.interval"), self.intervalBox)
    form.addRow(self.tr("ui.start"), self.startDate)
    form.addRow(self.tr("ui.end"), self.endDate)
    data_l.addLayout(form)
    self.btnApplyMarket = QtWidgets.QPushButton(self.tr("apply_market"))
    self.btnApplyMarket.setProperty("role", "primaryButton")
    self.btnLoadData = self.btnApplyMarket
    data_l.addWidget(self.btnApplyMarket)
    self.marketDirtyHint = QtWidgets.QLabel(self.tr("market_params_dirty_hint"))
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
    self.symbolSearchEdit.setPlaceholderText(self.tr("ui.search_symbol_placeholder"))
    self.symbolList = QtWidgets.QListWidget()
    self.symbolList.setMaximumHeight(140)
    self.symbolList.addItems(BINANCE_TOP_MARKET_CAP_SYMBOLS)
    self.symbolPanel.setVisible(False)
    symbol_panel_l.addWidget(self.symbolSearchEdit)
    symbol_panel_l.addWidget(self.symbolList)
    data_l.addWidget(self.symbolPanel)
    sidebar_l.addWidget(data_box)

    replay_box, replay_l = _card(self.tr("replay_control"))
    replay_box.setObjectName("replaySection")
    self.replayBox = replay_box
    self.btnLoadPlay = QtWidgets.QPushButton(f"{self.tr('play')} (Space)")
    self.btnStep = QtWidgets.QPushButton(f"{self.tr('step_next')} (→)")
    self.btnToEnd = QtWidgets.QPushButton(self.tr("jump_to_end"))
    self.btnFollow = QtWidgets.QPushButton(f"{self.tr('follow_latest')} (F)")
    self.btnResetView = QtWidgets.QPushButton(f"{self.tr('reset_view')} (K)")
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
    self.speedLabel = QtWidgets.QLabel(
        self.tr("ui.speed_format").format(speed=1.0)
    )
    self.speedLabel.setProperty("role", "muted")
    self.speedSlider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
    self.speedSlider.setMinimum(0)
    self.speedSlider.setMaximum(6)
    self.speedSlider.setValue(3)
    replay_l.addWidget(self.speedLabel)
    replay_l.addWidget(self.speedSlider)
    sidebar_l.addWidget(replay_box)

    trade_box, trade_l = _card(self.tr("trade_actions"))
    trade_box.setObjectName("tradeSection")
    self.tradeBox = trade_box
    trade_grid = QtWidgets.QGridLayout()
    trade_grid.setContentsMargins(0, 0, 0, 0)
    trade_grid.setHorizontalSpacing(SPACING["sm"])
    trade_grid.setVerticalSpacing(SPACING["sm"])
    self.btnOpenLong = QtWidgets.QPushButton(f"{self.tr('open_long')} (B)")
    self.btnCloseLong = QtWidgets.QPushButton(f"{self.tr('close_long')} (C)")
    self.btnOpenShort = QtWidgets.QPushButton(f"{self.tr('open_short')} (S)")
    self.btnCloseShort = QtWidgets.QPushButton(f"{self.tr('close_short')} (X)")
    self.btnUndo = QtWidgets.QPushButton(self.tr("undo"))
    self.btnRedo = QtWidgets.QPushButton(self.tr("redo"))
    self.btnClearTradeRecords = QtWidgets.QPushButton(self.tr("clear_trade_records"))
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

    danger_box, danger_l = _card(self.tr("trade_data_management_title"))
    danger_box.setObjectName("dangerSection")
    self.dangerBox = danger_box
    self.btnToggleDanger = QtWidgets.QToolButton()
    self.btnToggleDanger.setText(self.tr("trade_data_management_title"))
    self.btnToggleDanger.setCheckable(True)
    self.btnToggleDanger.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
    self.btnToggleDanger.setProperty("role", "compactButton")
    self.dangerActions = QtWidgets.QWidget()
    danger_actions_l = QtWidgets.QVBoxLayout(self.dangerActions)
    danger_actions_l.setContentsMargins(0, 0, 0, 0)
    danger_actions_l.setSpacing(SPACING["sm"])

    self.tradeManagementSessionLabel = QtWidgets.QLabel(
        self.tr("trade_data_management_session_group")
    )
    self.tradeManagementSessionLabel.setProperty("role", "sectionLabel")
    danger_actions_l.addWidget(self.tradeManagementSessionLabel)
    self.tradeManagementSessionBox = QtWidgets.QComboBox()
    self.tradeManagementSessionBox.setObjectName("tradeManagementSessionBox")
    danger_actions_l.addWidget(self.tradeManagementSessionBox)
    self.tradeManagementSessionTradeTable = QtWidgets.QTableWidget(0, 11)
    self.tradeManagementSessionTradeTable.setObjectName("tradeManagementSessionTradeTable")
    self.tradeManagementSessionTradeTable.setHorizontalHeaderLabels(
        [
            self.tr("symbol"),
            self.tr("ui.side"),
            self.tr("ui.net_return_pct"),
            self.tr("ui.net_pnl"),
            self.tr("ui.trade"),
            self.tr("ui.entry_time"),
            self.tr("ui.exit_time"),
            self.tr("ui.entry_price"),
            self.tr("ui.exit_price"),
            self.tr("ui.quantity"),
            self.tr("ui.status"),
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
    self.btnDeleteSessionTrade = QtWidgets.QPushButton(
        self.tr("delete_selected_trade_title")
    )
    self.btnDeleteSessionTrade.setProperty("role", "dangerGhostButton")
    self.btnDeletePerformanceSession = QtWidgets.QPushButton(
        self.tr("delete_performance_session_title")
    )
    self.btnDeletePerformanceSession.setProperty("role", "dangerGhostButton")
    danger_actions_l.addWidget(self.tradeManagementSessionTradeTable)
    danger_actions_l.addWidget(self.btnDeleteSessionTrade)
    danger_actions_l.addWidget(self.btnDeletePerformanceSession)

    self.tradeManagementRangeLabel = QtWidgets.QLabel(
        self.tr("trade_data_management_range_group")
    )
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
    self.tradeManagementStart.setLocale(
        QtCore.QLocale(
            QtCore.QLocale.English if self.current_language == "en_US" else QtCore.QLocale.Chinese,
            QtCore.QLocale.UnitedStates if self.current_language == "en_US" else QtCore.QLocale.China,
        )
    )
    replay_time_zone = QtCore.QTimeZone(b"Asia/Shanghai")
    self.tradeManagementStart.setTimeZone(replay_time_zone)
    self.tradeManagementStart.setDateTime(
        QtCore.QDateTime(self.startDate.date(), QtCore.QTime(0, 0), replay_time_zone)
    )
    self.tradeManagementEnd = QtWidgets.QDateTimeEdit()
    self.tradeManagementEnd.setObjectName("tradeManagementEnd")
    self.tradeManagementEnd.setCalendarPopup(True)
    self.tradeManagementEnd.setDisplayFormat("yyyy-MM-dd HH:mm")
    self.tradeManagementEnd.setLocale(self.tradeManagementStart.locale())
    self.tradeManagementEnd.setTimeZone(replay_time_zone)
    self.tradeManagementEnd.setDateTime(
        QtCore.QDateTime(
            self.endDate.date().addDays(1), QtCore.QTime(0, 0), replay_time_zone
        )
    )
    self.tradeManagementStartLabel = QtWidgets.QLabel(self.tr("ui.start"))
    self.tradeManagementEndLabel = QtWidgets.QLabel(self.tr("ui.end"))
    range_form.addRow(self.tradeManagementStartLabel, self.tradeManagementStart)
    range_form.addRow(self.tradeManagementEndLabel, self.tradeManagementEnd)
    danger_actions_l.addLayout(range_form)
    self.btnPreviewTradeRange = QtWidgets.QPushButton(
        self.tr("trade_data_management_preview_range")
    )
    self.btnPreviewTradeRange.setProperty("role", "secondaryButton")
    danger_actions_l.addWidget(self.btnPreviewTradeRange)
    self.tradeManagementPreviewLabel = QtWidgets.QLabel(
        self.tr("trade_data_management_preview_initial")
    )
    self.tradeManagementPreviewLabel.setProperty("role", "muted")
    self.tradeManagementPreviewLabel.setWordWrap(True)
    danger_actions_l.addWidget(self.tradeManagementPreviewLabel)
    self.tradeManagementCandidateBox = QtWidgets.QComboBox()
    self.tradeManagementCandidateBox.setObjectName("tradeManagementCandidateBox")
    danger_actions_l.addWidget(self.tradeManagementCandidateBox)
    self.btnDeleteSelectedTrade = QtWidgets.QPushButton(
        self.tr("delete_selected_trade_title")
    )
    self.btnDeleteTradeRange = QtWidgets.QPushButton(self.tr("delete_trade_range_title"))
    for button in (self.btnDeleteSelectedTrade, self.btnDeleteTradeRange):
        button.setProperty("role", "dangerGhostButton")
        danger_actions_l.addWidget(button)
    danger_actions_l.addWidget(self.btnClearTradeRecords)
    self.dangerActions.setVisible(False)
    danger_l.addWidget(self.btnToggleDanger)
    danger_l.addWidget(self.dangerActions)
    sidebar_l.addWidget(danger_box)

    exec_box, exec_l = _card(self.tr("execution_cost_settings"))
    exec_box.setObjectName("executionSection")
    exec_box.setMinimumWidth(0)
    exec_box.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
    exec_form = QtWidgets.QFormLayout()
    exec_form.setContentsMargins(0, 0, 0, 0)
    exec_form.setSpacing(SPACING["sm"])
    exec_form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
    self.fillModeBox = QtWidgets.QComboBox()
    for mode in FILL_MODES:
        self.fillModeBox.addItem(self.tr(f"ui.fill_mode.{mode.lower()}"), mode)
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
    self.takeProfitPctSpin.setPlaceholderText(self.tr("none"))
    self.stopLossPctSpin = NullablePercentInput()
    self.stopLossPctSpin.setObjectName("stopLossPctInput")
    self.stopLossPctSpin.setPlaceholderText(self.tr("none"))
    exec_form.addRow(self.tr("ui.execution_mode"), self.fillModeBox)
    exec_form.addRow(self.tr("ui.fee_bps"), self.feeBpsSpin)
    exec_form.addRow(self.tr("ui.slippage_bps"), self.slippageBpsSpin)
    self.tradeNotionalLabel = QtWidgets.QLabel(self.tr("ui.trade_notional"))
    self.tradeNotionalLabel.setMinimumWidth(
        self.tradeNotionalLabel.fontMetrics().horizontalAdvance(self.tradeNotionalLabel.text())
    )
    self.tradeNotionalLabel.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)
    exec_form.addRow(self.tradeNotionalLabel, self.tradeNotionalSpin)
    exec_form.addRow(self.tr("ui.initial_equity"), self.initialEquitySpin)
    exec_form.addRow(self.tr("ui.take_profit_pct"), self.takeProfitPctSpin)
    exec_form.addRow(self.tr("ui.stop_loss_pct"), self.stopLossPctSpin)
    exec_l.addLayout(exec_form)
    self.executionSettingsBox = exec_box
    self.executionSettingsBox.setVisible(True)

    tag_box, tag_l = _card(self.tr("event_tags_notes"))
    tag_box.setObjectName("tagSection")
    self.tagBox = tag_box
    self.tag_checks = []
    tag_grid = QtWidgets.QGridLayout()
    tag_grid.setHorizontalSpacing(SPACING["sm"])
    tag_grid.setVerticalSpacing(SPACING["sm"])
    event_tag_keys = (
        "deep_v_reversal",
        "long_lower_wick",
        "volume_spike",
        "panic_wick",
        "reclaim_prior_low",
        "second_bottom",
        "false_breakout",
        "acceleration_exhaustion",
        "high_conviction",
        "other",
    )
    for idx, (tag, tag_key) in enumerate(zip(EVENT_TAGS, event_tag_keys)):
        cb = QtWidgets.QCheckBox(self.tr(f"ui.event_tag.{tag_key}"))
        cb.setProperty("eventTagValue", tag)
        bind_text(cb, f"ui.event_tag.{tag_key}", self.tr)
        cb.setProperty("role", "tagChip")
        self.tag_checks.append(cb)
        tag_grid.addWidget(cb, idx // 2, idx % 2)
    tag_l.addLayout(tag_grid)
    self.noteEdit = QtWidgets.QPlainTextEdit()
    self.noteEdit.setObjectName("noteEdit")
    self.noteEdit.setPlaceholderText(self.tr("ui.note_placeholder"))
    self.noteEdit.setFixedHeight(82)
    self.eventHintLabel = QtWidgets.QLabel(self.tr("ui.event_edit_hint"))
    self.eventHintLabel.setProperty("role", "muted")
    self.eventHintLabel.setWordWrap(True)
    self.btnApplyEventMeta = QtWidgets.QPushButton(self.tr("ui.save_event"))
    self.btnApplyEventMeta.setProperty("role", "secondaryButton")
    tag_l.addWidget(self.noteEdit)
    tag_l.addWidget(self.eventHintLabel)
    tag_l.addWidget(self.btnApplyEventMeta)
    sidebar_l.addWidget(tag_box)

    export_box, export_l = _card(self.tr("tools"))
    export_box.setObjectName("toolsSection")
    self.toolsBox = export_box
    self.btnExport = QtWidgets.QPushButton(f"{self.tr('export_session')} (E)")
    self.btnAnalysis = self.btnAnalysisWorkspace
    self.btnSettings = QtWidgets.QPushButton(self.tr("settings"))
    self.btnTheme = self.btnSettings
    self.btnExport.setProperty("role", "primaryButton")
    self.btnSettings.setProperty("role", "secondaryButton")
    export_l.addWidget(self.btnExport)
    export_l.addWidget(self.btnSettings)
    sidebar_l.addWidget(export_box)
    sidebar_l.addStretch(1)
    sidebar_scroll.setWidget(sidebar_content)
    left_l.addWidget(sidebar_scroll)

    self.btnExport.setText(self.tr("export_session"))
    self.btnExport.setProperty("role", "headerAction")
    self.btnSettings.setProperty("role", "headerAction")
    self.btnToggleRightPanel = QtWidgets.QToolButton()
    self.btnToggleRightPanel.setText(self.tr("ui.panel"))
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
    for label_key, control in (("symbol", self.symbolBox),):
        label = QtWidgets.QLabel()
        bind_text(label, label_key, self.tr)
        label.setProperty("role", "muted")
        market_toolbar_l.addWidget(label)
        market_toolbar_l.addWidget(control)
    for label_key, control in (
        ("ui.start", self.startDate),
        ("ui.end", self.endDate),
    ):
        label = QtWidgets.QLabel()
        bind_text(label, label_key, self.tr)
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
    self.replayPerformanceSessionLabel = QtWidgets.QLabel(self.tr("performance_session"))
    self.replayPerformanceSessionLabel.setProperty("role", "muted")
    self.replayPerformanceSessionBox = QtWidgets.QComboBox()
    self.replayPerformanceSessionBox.setObjectName("replayPerformanceSessionBox")
    self.replayPerformanceSessionBox.setMinimumWidth(0)
    self.replayPerformanceSessionBox.setMaximumWidth(260)
    self.replayPerformanceSessionBox.setSizePolicy(
        QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed
    )
    self.btnContinuePerformanceSession = QtWidgets.QPushButton(
        self.tr("continue_performance_session")
    )
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
    self.chartSectionLabel = QtWidgets.QLabel(self.tr("ui.chart_replay"))
    self.chartSectionLabel.setProperty("role", "toolbarTitle")
    toolbar_l.addWidget(self.chartSectionLabel)
    self.status = QtWidgets.QLabel(self.tr("ui.no_market_data"))
    self.status.setProperty("role", "tiny")
    self.status.setMinimumWidth(0)
    self.status.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
    toolbar_l.addWidget(self.status, stretch=1)
    self.btnToggleBottomPanel = QtWidgets.QToolButton()
    self.btnToggleBottomPanel.setText(self.tr("ui.collapse_results"))
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
        self.tr("ui.trade_id"), self.tr("ui.side"), self.tr("ui.entry_time"),
        self.tr("ui.proxy_price"), self.tr("ui.fill_price"), self.tr("ui.fees"),
        self.tr("ui.notional"), self.tr("ui.candle"), self.tr("ui.status"),
        self.tr("ui.execution_mode"),
    ])
    self._setup_table(self.openTradesTable)

    self.closedTradesTable = QtWidgets.QTableWidget()
    self.closedTradesTable.setColumnCount(13)
    self.closedTradesTable.setHorizontalHeaderLabels([
        self.tr("ui.trade_id"), self.tr("ui.side"), self.tr("ui.entry_time"),
        self.tr("ui.exit_time"), self.tr("ui.entry_fill"), self.tr("ui.exit_fill"),
        self.tr("ui.gross_return_pct"), self.tr("ui.net_return_pct"),
        self.tr("ui.fees"), self.tr("ui.net_pnl"), self.tr("ui.holding_bars"),
        self.tr("ui.status"), self.tr("ui.execution_mode"),
    ])
    self._setup_table(self.closedTradesTable)

    self.eventTable = QtWidgets.QTableWidget()
    self.eventTable.setColumnCount(8)
    self.eventTable.setHorizontalHeaderLabels([
        self.tr("ui.event_id"), self.tr("ui.trade_id"), self.tr("ui.event"),
        self.tr("ui.side"), self.tr("ui.bar_time"), self.tr("ui.proxy_price"),
        self.tr("ui.tags"), self.tr("ui.note"),
    ])
    self._setup_table(self.eventTable)
    self.eventFilterTag = QtWidgets.QComboBox()
    self.eventFilterTag.addItem(self.tr("ui.all_tags"), "")
    for tag, tag_key in zip(EVENT_TAGS, event_tag_keys):
        self.eventFilterTag.addItem(self.tr(f"ui.event_tag.{tag_key}"), tag)
    self.eventFilterSide = QtWidgets.QComboBox()
    self.eventFilterSide.addItem(self.tr("ui.all_sides"), "")
    self.eventFilterSide.addItem(self.tr("ui.long"), "LONG")
    self.eventFilterSide.addItem(self.tr("ui.short"), "SHORT")
    self.eventFilterType = QtWidgets.QComboBox()
    self.eventFilterType.addItem(self.tr("ui.all_events"), "")
    self.eventFilterType.addItem(self.tr("ui.open"), "OPEN")
    self.eventFilterType.addItem(self.tr("ui.close"), "CLOSE")
    event_filters = QtWidgets.QHBoxLayout()
    event_filters.setSpacing(SPACING["sm"])
    event_filters.addWidget(self.eventFilterTag)
    event_filters.addWidget(self.eventFilterSide)
    event_filters.addWidget(self.eventFilterType)
    self.legacyResearchCompatContainer = QtWidgets.QWidget(
        self.replayWorkspace
    )
    self.legacyResearchCompatContainer.hide()
    self.eventTab = QtWidgets.QWidget(self.legacyResearchCompatContainer)
    event_tab_layout = QtWidgets.QVBoxLayout(self.eventTab)
    event_tab_layout.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
    event_tab_layout.setSpacing(SPACING["sm"])
    event_tab_layout.addLayout(event_filters)
    event_tab_layout.addWidget(self.eventTable)

    self.performanceText = QtWidgets.QPlainTextEdit()
    self.performanceText.setReadOnly(True)
    self.performanceText.setMinimumHeight(140)
    self.performanceText.setPlainText(self.tr("ui.performance_initial"))

    self.equityTable = QtWidgets.QTableWidget()
    self.equityTable.setColumnCount(8)
    self.equityTable.setHorizontalHeaderLabels([
        self.tr("ui.sequence"), self.tr("ui.candle_or_trade"),
        self.tr("ui.realized"), self.tr("ui.unrealized_pnl"),
        self.tr("ui.position_or_fees"), self.tr("ui.equity"),
        self.tr("ui.return_pct"), self.tr("ui.drawdown_pct"),
    ])
    self._setup_table(self.equityTable)

    self.eventStudyTable = QtWidgets.QTableWidget(
        self.legacyResearchCompatContainer
    )
    self.eventStudyTable.setColumnCount(9)
    self.eventStudyTable.setHorizontalHeaderLabels([
        self.tr("ui.tags"), self.tr("ui.event"), self.tr("ui.side"),
        self.tr("ui.sample_count"), self.tr("ui.forward_1_mean"),
        self.tr("ui.forward_3_mean"), self.tr("ui.forward_5_mean"),
        self.tr("ui.forward_10_mean"), self.tr("ui.forward_1_win_rate"),
    ])
    self._setup_table(self.eventStudyTable)

    self.datasetText = QtWidgets.QPlainTextEdit()
    self.datasetText.setReadOnly(True)
    self.datasetText.setMinimumHeight(140)
    self.datasetText.setPlainText(self.tr("ui.dataset_initial"))

    bottom_tabs = QtWidgets.QTabWidget()
    bottom_tabs.setObjectName("bottomTabs")
    bottom_tabs.setMinimumHeight(155)
    self.bottomTabs = bottom_tabs
    trade_tabs = QtWidgets.QTabWidget()
    self.tradeResultsTabs = trade_tabs
    trade_tabs.addTab(_table_box(self.openTradesTable), self.tr("current_positions"))
    trade_tabs.addTab(_table_box(self.closedTradesTable), self.tr("ui.trade_history"))
    self.tradeResultsStack = QtWidgets.QStackedWidget()
    self.emptyTradeResults = _empty_state(
        self.tr("ui.empty.no_trade_samples"), self.tr("ui.empty.trade_samples_body")
    )
    self.tradeResultsStack.addWidget(self.emptyTradeResults)
    self.tradeResultsStack.addWidget(trade_tabs)
    self.decisionResearchRedirect = _empty_state(
        self.tr("decision_research.redirect.title"),
        self.tr("decision_research.redirect.body"),
    )
    self.btnOpenDecisionResearch = QtWidgets.QPushButton()
    self.btnOpenDecisionResearch.setProperty("role", "primaryButton")
    self.decisionResearchRedirect.layout().insertWidget(
        self.decisionResearchRedirect.layout().count() - 1,
        self.btnOpenDecisionResearch,
        alignment=QtCore.Qt.AlignCenter,
    )
    bind_text(
        self.btnOpenDecisionResearch,
        "decision_research.redirect.open",
        self.tr,
    )
    self.equityStack = _stacked_empty_table(
        self.tr("ui.empty.no_account_returns"),
        self.tr("ui.empty.account_returns_body"),
        self.equityTable,
    )
    self.performanceStack = QtWidgets.QStackedWidget()
    self.emptyPerformance = _empty_state(
        self.tr("ui.empty.no_performance"), self.tr("ui.empty.performance_body")
    )
    self.performanceStack.addWidget(self.emptyPerformance)
    self.performanceStack.addWidget(self.performanceText)
    self.datasetStack = QtWidgets.QStackedWidget()
    self.emptyDataset = _empty_state(
        self.tr("ui.empty.no_sample_overview"), self.tr("ui.empty.sample_overview_body")
    )
    self.datasetStack.addWidget(self.emptyDataset)
    self.datasetStack.addWidget(self.datasetText)
    bottom_tabs.addTab(self.tradeResultsStack, self.tr("ui.positions_and_trades"))
    bottom_tabs.addTab(self.equityStack, self.tr("ui.account_returns"))
    bottom_tabs.addTab(self.performanceStack, self.tr("ui.performance_statistics"))
    bottom_tabs.addTab(
        self.decisionResearchRedirect,
        self.tr("decision_research.redirect.title"),
    )
    bottom_tabs.addTab(self.datasetStack, self.tr("ui.sample_overview"))

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
    for text_key, tooltip_key in (
        ("ui.trade_short", "ui.trade"),
        ("ui.status_short", "ui.status"),
        ("ui.annotate_short", "ui.annotate"),
    ):
        button = QtWidgets.QToolButton()
        button.setText(self.tr(text_key))
        button.setToolTip(self.tr(tooltip_key))
        button.setProperty("i18nTextKey", text_key)
        button.setProperty("i18nToolTipKey", tooltip_key)
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
    trade_position_title = QtWidgets.QLabel(self.tr("current_positions"))
    trade_position_title.setProperty("role", "sectionTitle")
    trade_position_l.addWidget(trade_position_title)
    self.tradePositionEmptyState = _empty_state(
        self.tr("ui.empty.no_position"),
        self.tr("ui.empty.position_trade_body"),
        compact=True,
    )
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
    title_position = QtWidgets.QLabel(self.tr("ui.current_status"))
    title_position.setProperty("role", "sectionTitle")
    position_l.addWidget(title_position)
    self.positionEmptyState = _empty_state(
        self.tr("ui.empty.no_position"),
        self.tr("ui.empty.position_status_body"),
        compact=True,
    )
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
    for label_key, value in (
        ("ui.side", self.positionSideValue),
        ("ui.quantity", self.positionQtyValue),
        ("ui.entry_price", self.positionEntryValue),
        ("ui.current_price", self.positionCurrentValue),
        ("ui.unrealized_pnl", self.positionPnlValue),
        ("ui.unrealized_return", self.positionPnlPctValue),
    ):
        row = _value_row(self.tr(label_key), value)
        bind_text(row.nameLabel, label_key, self.tr)
        position_details_l.addWidget(row)
    self.positionDetails.setVisible(False)
    position_l.addWidget(self.positionDetails)
    self.openPositionsMiniTable = QtWidgets.QTableWidget()
    self.openPositionsMiniTable.setColumnCount(6)
    self.openPositionsMiniTable.setHorizontalHeaderLabels([
        self.tr("ui.trade"), self.tr("ui.side"), self.tr("ui.entry"),
        self.tr("ui.unrealized_pnl"), "TP", "SL",
    ])
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
    account_title = QtWidgets.QLabel(self.tr("ui.account_overview"))
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
    for label_key, value in (
        ("ui.current_equity", self.accountEquityValue),
        ("ui.total_return", self.accountReturnValue),
        ("ui.total_pnl", self.accountPnlValue),
        ("ui.win_rate", self.accountWinRateValue),
        ("ui.sharpe_ratio", self.accountSharpeValue),
        ("ui.profit_factor", self.accountProfitFactorValue),
        ("ui.payoff_ratio", self.accountPayoffValue),
        ("ui.max_drawdown", self.accountMaxDrawdownValue),
    ):
        row = _value_row(self.tr(label_key), value)
        bind_text(row.nameLabel, label_key, self.tr)
        account_l.addWidget(row)
    overview_l.addWidget(account_card)

    recent_card = QtWidgets.QFrame()
    recent_card.setObjectName("recentEventsCard")
    recent_card.setProperty("role", "statusBlock")
    recent_l = QtWidgets.QVBoxLayout(recent_card)
    recent_l.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
    recent_l.setSpacing(SPACING["sm"])
    recent_title = QtWidgets.QLabel(self.tr("ui.recent_events"))
    recent_title.setProperty("role", "sectionTitle")
    recent_l.addWidget(recent_title)
    self.recentEventsEmptyState = _empty_state(
        self.tr("ui.empty.no_events"), self.tr("ui.empty.events_body"), compact=True
    )
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
    self.candleTitleLabel = QtWidgets.QLabel(self.tr("current_bar_details"))
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
        ("time", self.tr("bar_time"), self.barTimeValue),
        ("open", self.tr("bar_open"), self.barOpenValue),
        ("high", self.tr("bar_high"), self.barHighValue),
        ("low", self.tr("bar_low"), self.barLowValue),
        ("close", self.tr("bar_close"), self.barCloseValue),
        ("volume", self.tr("bar_volume"), self.barVolumeValue),
        ("index", self.tr("bar_index"), self.barIndexValue),
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
    self.btnToggleDetail = QtWidgets.QPushButton(self.tr("ui.hide_details"))
    self.btnToggleDetail.setCheckable(True)
    self.btnToggleDetail.setProperty("role", "secondaryButton")
    self.detailText = QtWidgets.QPlainTextEdit()
    self.detailText.setReadOnly(True)
    self.detailText.setPlainText(self.tr("ui.no_details"))
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

    tabs.addTab(trade_scroll, self.tr("ui.trade"))
    tabs.addTab(overview_scroll, self.tr("ui.status"))
    tabs.addTab(annotation_scroll, self.tr("ui.annotate"))
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
    self.premiumStatus = QtWidgets.QLabel(self.tr("ui.premium_waiting"))
    self.premiumStatus.setProperty("role", "pill")
    self.premiumStats = QtWidgets.QPlainTextEdit()
    self.premiumStats.setReadOnly(True)
    self.premiumStats.setMaximumHeight(110)
    self.premiumStats.setPlainText("-")
    self.premiumPlot = _ManagedPlotWidget()
    self.premiumPlot.showGrid(x=True, y=True, alpha=0.14)
    self.premiumPlot.addLegend(offset=(8, 8))
    self.premiumBuyCurve = self.premiumPlot.plot([], [], pen=pg.mkPen(COLORS["success"], width=1.5, style=QtCore.Qt.DashLine), symbol="o", symbolSize=4, name=self.tr("ui.premium_buy"))
    self.premiumSellCurve = self.premiumPlot.plot([], [], pen=pg.mkPen(COLORS["danger"], width=1.5, style=QtCore.Qt.DotLine), symbol="t", symbolSize=4, name=self.tr("ui.premium_sell"))
    self.premiumAvgCurve = self.premiumPlot.plot([], [], pen=pg.mkPen(COLORS["chart_axis"], width=1.8), symbol="s", symbolSize=4, name=self.tr("ui.premium_average"))
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
        self.btnToggleRightPanel.setText(
            self.tr("ui.collapse_panel") if visible else self.tr("ui.expand_panel")
        )

    self._set_right_panel_expanded = set_right_panel_visible

    self.btnToggleRightPanel.toggled.connect(set_right_panel_visible)

    def set_bottom_panel_collapsed(collapsed: bool) -> None:
        bottom_tabs.setVisible(not collapsed)
        self.btnToggleBottomPanel.setText(
            self.tr("ui.expand_results") if collapsed else self.tr("ui.collapse_results")
        )

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
    log_title = QtWidgets.QLabel(self.tr("ui.operation_log"))
    log_title.setProperty("role", "sectionTitle")
    self.logSummaryLabel = QtWidgets.QLabel(self.tr("ui.no_operations"))
    self.logSummaryLabel.setProperty("role", "tiny")
    self.logSummaryLabel.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
    self.btnToggleLog = QtWidgets.QPushButton(self.tr("ui.expand_log"))
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

    # Bind static UI copy to resource keys so language changes do not rebuild
    # the window or disturb the replay/session state.
    for widget, key, suffix in (
        (self.btnReplayWorkspace, "trading_replay", ""),
        (self.btnAnalysisWorkspace, "data_analysis", ""),
        (self.btnApplyMarket, "apply_market", ""),
        (self.marketDirtyHint, "market_params_dirty_hint", ""),
        (self.symbolSearchEdit, "ui.search_symbol_placeholder", ""),
        (self.btnLoadPlay, "play", " (Space)"),
        (self.btnStep, "step_next", " (→)"),
        (self.btnToEnd, "jump_to_end", ""),
        (self.btnFollow, "follow_latest", " (F)"),
        (self.btnResetView, "reset_view", " (K)"),
        (self.btnOpenLong, "open_long", " (B)"),
        (self.btnCloseLong, "close_long", " (C)"),
        (self.btnOpenShort, "open_short", " (S)"),
        (self.btnCloseShort, "close_short", " (X)"),
        (self.btnUndo, "undo", ""),
        (self.btnRedo, "redo", ""),
        (self.btnClearTradeRecords, "clear_trade_records", ""),
        (self.btnToggleDanger, "trade_data_management_title", ""),
        (self.tradeManagementSessionLabel, "trade_data_management_session_group", ""),
        (self.btnDeleteSessionTrade, "delete_selected_trade_title", ""),
        (self.btnDeletePerformanceSession, "delete_performance_session_title", ""),
        (self.tradeManagementRangeLabel, "trade_data_management_range_group", ""),
        (self.tradeManagementStartLabel, "ui.start", ""),
        (self.tradeManagementEndLabel, "ui.end", ""),
        (self.btnPreviewTradeRange, "trade_data_management_preview_range", ""),
        (self.tradeManagementPreviewLabel, "trade_data_management_preview_initial", ""),
        (self.btnDeleteSelectedTrade, "delete_selected_trade_title", ""),
        (self.btnDeleteTradeRange, "delete_trade_range_title", ""),
        (self.tradeNotionalLabel, "ui.trade_notional", ""),
        (self.eventHintLabel, "ui.event_edit_hint", ""),
        (self.btnApplyEventMeta, "ui.save_event", ""),
        (self.btnExport, "export_session", " (E)"),
        (self.btnSettings, "settings", ""),
        (self.btnToggleRightPanel, "ui.panel", ""),
        (self.replayPerformanceSessionLabel, "performance_session", ""),
        (self.btnContinuePerformanceSession, "continue_performance_session", ""),
        (self.chartSectionLabel, "ui.chart_replay", ""),
        (self.btnToggleBottomPanel, "ui.collapse_results", ""),
        (trade_position_title, "current_positions", ""),
        (title_position, "ui.current_status", ""),
        (account_title, "ui.account_overview", ""),
        (recent_title, "ui.recent_events", ""),
        (self.candleTitleLabel, "current_bar_details", ""),
        (self.btnToggleDetail, "ui.hide_details", ""),
        (self.premiumStatus, "ui.premium_waiting", ""),
        (log_title, "ui.operation_log", ""),
        (self.logSummaryLabel, "ui.no_operations", ""),
        (self.btnToggleLog, "ui.expand_log", ""),
    ):
        if isinstance(widget, (QtWidgets.QLineEdit, QtWidgets.QPlainTextEdit)) and key == "ui.search_symbol_placeholder":
            bind_placeholder(widget, key, self.tr)
        else:
            bind_text(widget, key, self.tr, suffix=suffix)

    bind_tooltip(self.btnResetView, "reset_view_hint", self.tr)
    bind_placeholder(self.noteEdit, "ui.note_placeholder", self.tr)
    bind_placeholder(self.takeProfitPctSpin, "none", self.tr)
    bind_placeholder(self.stopLossPctSpin, "none", self.tr)
    bind_plain_text(self.performanceText, "ui.performance_initial", self.tr)
    bind_plain_text(self.datasetText, "ui.dataset_initial", self.tr)
    bind_plain_text(self.detailText, "ui.no_details", self.tr)

    for group, key in (
        (data_box, "market_data"),
        (replay_box, "replay_control"),
        (trade_box, "trade_actions"),
        (danger_box, "trade_data_management_title"),
        (exec_box, "execution_cost_settings"),
        (tag_box, "event_tags_notes"),
        (export_box, "tools"),
    ):
        bind_group_title(group, key, self.tr)

    for layout, field, key in (
        (form, self.symbolBox, "symbol"),
        (form, self.intervalBox, "ui.interval"),
        (form, self.startDate, "ui.start"),
        (form, self.endDate, "ui.end"),
        (exec_form, self.fillModeBox, "ui.execution_mode"),
        (exec_form, self.feeBpsSpin, "ui.fee_bps"),
        (exec_form, self.slippageBpsSpin, "ui.slippage_bps"),
        (exec_form, self.initialEquitySpin, "ui.initial_equity"),
        (exec_form, self.takeProfitPctSpin, "ui.take_profit_pct"),
        (exec_form, self.stopLossPctSpin, "ui.stop_loss_pct"),
    ):
        label = layout.labelForField(field)
        if label is not None:
            bind_text(label, key, self.tr)

    for table, keys in (
        (self.tradeManagementSessionTradeTable, (
            "symbol", "ui.side", "ui.net_return_pct", "ui.net_pnl", "ui.trade",
            "ui.entry_time", "ui.exit_time", "ui.entry_price", "ui.exit_price",
            "ui.quantity", "ui.status",
        )),
        (self.openTradesTable, (
            "ui.trade_id", "ui.side", "ui.entry_time", "ui.proxy_price", "ui.fill_price",
            "ui.fees", "ui.notional", "ui.candle", "ui.status", "ui.execution_mode",
        )),
        (self.closedTradesTable, (
            "ui.trade_id", "ui.side", "ui.entry_time", "ui.exit_time", "ui.entry_fill",
            "ui.exit_fill", "ui.gross_return_pct", "ui.net_return_pct", "ui.fees",
            "ui.net_pnl", "ui.holding_bars", "ui.status", "ui.execution_mode",
        )),
        (self.eventTable, (
            "ui.event_id", "ui.trade_id", "ui.event", "ui.side", "ui.bar_time",
            "ui.proxy_price", "ui.tags", "ui.note",
        )),
        (self.equityTable, (
            "ui.sequence", "ui.candle_or_trade", "ui.realized", "ui.unrealized_pnl",
            "ui.position_or_fees", "ui.equity", "ui.return_pct", "ui.drawdown_pct",
        )),
        (self.eventStudyTable, (
            "ui.tags", "ui.event", "ui.side", "ui.sample_count", "ui.forward_1_mean",
            "ui.forward_3_mean", "ui.forward_5_mean", "ui.forward_10_mean",
            "ui.forward_1_win_rate",
        )),
        (self.openPositionsMiniTable, (
            "ui.trade", "ui.side", "ui.entry", "ui.unrealized_pnl", "", "",
        )),
    ):
        bind_table_headers(table, keys, self.tr)

    for tab_widget, page, key in (
        (trade_tabs, trade_tabs.widget(0), "current_positions"),
        (trade_tabs, trade_tabs.widget(1), "ui.trade_history"),
        (bottom_tabs, self.tradeResultsStack, "ui.positions_and_trades"),
        (bottom_tabs, self.equityStack, "ui.account_returns"),
        (bottom_tabs, self.performanceStack, "ui.performance_statistics"),
        (
            bottom_tabs,
            self.decisionResearchRedirect,
            "decision_research.redirect.title",
        ),
        (bottom_tabs, self.datasetStack, "ui.sample_overview"),
        (tabs, trade_scroll, "ui.trade"),
        (tabs, overview_scroll, "ui.status"),
        (tabs, annotation_scroll, "ui.annotate"),
    ):
        bind_tab(tab_widget, page, key, self.tr)

    for empty_state, title_key, body_key in (
        (self.tradePositionEmptyState, "ui.empty.no_position", "ui.empty.position_trade_body"),
        (self.positionEmptyState, "ui.empty.no_position", "ui.empty.position_status_body"),
        (self.recentEventsEmptyState, "ui.empty.no_events", "ui.empty.events_body"),
        (self.emptyTradeResults, "ui.empty.no_trade_samples", "ui.empty.trade_samples_body"),
        (
            self.decisionResearchRedirect,
            "decision_research.redirect.title",
            "decision_research.redirect.body",
        ),
        (self.equityStack.widget(0), "ui.empty.no_account_returns", "ui.empty.account_returns_body"),
        (self.emptyPerformance, "ui.empty.no_performance", "ui.empty.performance_body"),
        (self.emptyDataset, "ui.empty.no_sample_overview", "ui.empty.sample_overview_body"),
    ):
        _bind_empty_state(empty_state, title_key, body_key, self.tr)

    for index, mode in enumerate(FILL_MODES):
        bind_combo_item(self.fillModeBox, index, f"ui.fill_mode.{mode.lower()}", self.tr)
    filter_bindings = (
        (self.eventFilterTag, ("ui.all_tags", *(f"ui.event_tag.{key}" for key in event_tag_keys))),
        (self.eventFilterSide, ("ui.all_sides", "ui.long", "ui.short")),
        (self.eventFilterType, ("ui.all_events", "ui.open", "ui.close")),
    )
    for combo, keys in filter_bindings:
        for index, key in enumerate(keys):
            bind_combo_item(combo, index, key, self.tr)

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
