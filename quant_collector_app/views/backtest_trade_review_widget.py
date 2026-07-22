from __future__ import annotations

from typing import Any, Callable

from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg

try:
    from app_i18n import tr
    from presenters.backtest_trade_review import (
        BacktestTradeReviewModel,
        build_backtest_trade_review_model,
    )
    from ui_style import SPACING, normalize_theme_settings
    from views.candlestick_item import CandlestickItem
    from views.plot_readability import apply_readable_plot_text, make_bold
    from views.plot_lifecycle import close_parent_owned_graphics_view, prepare_plot_for_shutdown
    from views.volume_item import VolumeItem
except ImportError:  # pragma: no cover - package import path
    from ..app_i18n import tr
    from ..presenters.backtest_trade_review import (
        BacktestTradeReviewModel,
        build_backtest_trade_review_model,
    )
    from ..ui_style import SPACING, normalize_theme_settings
    from .candlestick_item import CandlestickItem
    from .plot_readability import apply_readable_plot_text, make_bold
    from .plot_lifecycle import close_parent_owned_graphics_view, prepare_plot_for_shutdown
    from .volume_item import VolumeItem


class _ManagedBacktestReviewPlotWidget(pg.PlotWidget):
    def __init__(
        self,
        parent: QtWidgets.QWidget | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(parent=parent, **kwargs)
        menu = self.plotItem.ctrlMenu
        menu.setParent(self)
        menu.hide()

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
        if self.plotItem is None:
            return bool(QtWidgets.QWidget.close(self))
        return bool(super().close())


class BacktestTradeReviewWidget(QtWidgets.QFrame):
    def __init__(
        self,
        *,
        language_provider: Callable[[], str],
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._language_provider = language_provider
        self._theme = normalize_theme_settings(None)
        self._last_model = BacktestTradeReviewModel(
            klines=build_backtest_trade_review_model(None, None).klines,
            trades=(),
        )
        self.selectedTradeIndex = -1
        self.setProperty("role", "statusBlock")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(SPACING["sm"], SPACING["sm"], SPACING["sm"], SPACING["sm"])
        layout.setSpacing(SPACING["xs"])

        self.titleLabel = QtWidgets.QLabel()
        self.titleLabel.setProperty("role", "sectionTitle")
        make_bold(self.titleLabel, point_size=12)
        self.emptyLabel = QtWidgets.QLabel()
        self.emptyLabel.setProperty("role", "mutedText")
        self.emptyLabel.setWordWrap(True)

        navigation = QtWidgets.QHBoxLayout()
        self.btnPrevEntry = QtWidgets.QPushButton()
        self.btnNextEntry = QtWidgets.QPushButton()
        self.btnPrevExit = QtWidgets.QPushButton()
        self.btnNextExit = QtWidgets.QPushButton()
        for button in (
            self.btnPrevEntry,
            self.btnNextEntry,
            self.btnPrevExit,
            self.btnNextExit,
        ):
            button.setProperty("role", "secondaryButton")
            navigation.addWidget(button)
        navigation.addStretch(1)

        self.tradeListToggle = QtWidgets.QToolButton()
        self.tradeListToggle.setCheckable(True)
        self.tradeListToggle.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.tradeListToggle.setArrowType(QtCore.Qt.RightArrow)
        self.tradeListToggle.setProperty("role", "secondaryButton")
        navigation.addWidget(self.tradeListToggle)

        self.tradeTable = QtWidgets.QTableWidget()
        self.tradeTable.setColumnCount(8)
        self.tradeTable.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tradeTable.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.tradeTable.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.tradeTable.setVisible(False)

        self.pricePlot = _ManagedBacktestReviewPlotWidget(self)
        self.pricePlot.setMinimumHeight(320)
        self.pricePlot.setMouseEnabled(x=True, y=True)
        self.pricePlot.getPlotItem().hideAxis("bottom")
        self.volumePlot = _ManagedBacktestReviewPlotWidget(
            self,
            axisItems={"bottom": pg.DateAxisItem(orientation="bottom")},
        )
        self.volumePlot.setMinimumHeight(120)
        self.volumePlot.setMouseEnabled(x=True, y=True)
        self.volumePlot.setXLink(self.pricePlot)

        self.candles = CandlestickItem()
        self.volumes = VolumeItem()
        self.entryMarkers = pg.ScatterPlotItem(size=14, pxMode=True)
        self.exitMarkers = pg.ScatterPlotItem(size=12, pxMode=True)
        self.randomBaselineMarkers = pg.ScatterPlotItem(size=0, pxMode=True)
        self.selectedEntryMarker = pg.ScatterPlotItem(size=18, pxMode=True)
        self.selectedExitMarker = pg.ScatterPlotItem(size=16, pxMode=True)
        self.holdingRegion = pg.LinearRegionItem(
            values=(0.0, 0.0),
            orientation=pg.LinearRegionItem.Vertical,
            movable=False,
        )
        self.holdingRegion.setZValue(-10)
        self.pricePlot.addItem(self.candles)
        self.pricePlot.addItem(self.holdingRegion)
        self.pricePlot.addItem(self.entryMarkers)
        self.pricePlot.addItem(self.exitMarkers)
        self.pricePlot.addItem(self.randomBaselineMarkers)
        self.pricePlot.addItem(self.selectedEntryMarker)
        self.pricePlot.addItem(self.selectedExitMarker)
        self.volumePlot.addItem(self.volumes)

        layout.addWidget(self.titleLabel)
        layout.addWidget(self.emptyLabel)
        layout.addLayout(navigation)
        layout.addWidget(self.tradeTable)
        layout.addWidget(self.pricePlot, stretch=3)
        layout.addWidget(self.volumePlot, stretch=1)
        self.tradeListToggle.toggled.connect(self._toggle_trade_table)
        self.tradeTable.cellClicked.connect(lambda row, _column: self.select_trade(row))
        self.btnPrevEntry.clicked.connect(lambda: self._navigate(-1, "entry"))
        self.btnNextEntry.clicked.connect(lambda: self._navigate(1, "entry"))
        self.btnPrevExit.clicked.connect(lambda: self._navigate(-1, "exit"))
        self.btnNextExit.clicked.connect(lambda: self._navigate(1, "exit"))
        self.retranslate_ui()
        self.apply_theme(None)
        self.clear()

    def set_result(self, market_df: Any, result: Any) -> None:
        self.set_model(build_backtest_trade_review_model(market_df, result))

    def set_model(self, model: BacktestTradeReviewModel) -> None:
        self._last_model = model
        self.selectedTradeIndex = -1
        klines = model.klines
        if not klines.has_data:
            self.candles.set_data([], [], [], [], [])
            self.volumes.set_data([], [], [])
            self.entryMarkers.setData([])
            self.exitMarkers.setData([])
            self.randomBaselineMarkers.setData([])
            self.selectedEntryMarker.setData([])
            self.selectedExitMarker.setData([])
            self.holdingRegion.hide()
            self._populate_trade_table()
            self.emptyLabel.show()
            self._show_auto_button()
            return

        width = self._bar_width()
        self.candles.set_data(
            klines.x,
            klines.opening,
            klines.high,
            klines.low,
            klines.close,
            width,
            data_version=(len(klines.x), klines.x[-1]),
        )
        self.volumes.set_data(
            klines.x,
            klines.volume,
            klines.upmask,
            width,
            data_version=(len(klines.x), klines.x[-1]),
        )
        self.entryMarkers.setData(
            [
                {
                    "pos": (trade.entry_x, trade.entry_price),
                    "data": trade.trade_index,
                    "symbol": self._entry_symbol(trade.side),
                    "brush": self._entry_brush(trade.side),
                    "pen": self._entry_pen(trade.side),
                }
                for trade in model.trades
            ]
        )
        self.exitMarkers.setData(
            [
                {
                    "pos": (trade.exit_x, trade.exit_price),
                    "data": trade.trade_index,
                    "symbol": "x",
                    "brush": self._exit_brush(trade.side),
                    "pen": self._exit_pen(trade.side),
                }
                for trade in model.trades
                if trade.exit_x is not None and trade.exit_price is not None
            ]
        )
        self.randomBaselineMarkers.setData([])
        self.selectedEntryMarker.setData([])
        self.selectedExitMarker.setData([])
        self.holdingRegion.hide()
        self._populate_trade_table()
        self.emptyLabel.setVisible(not model.trades)
        self._auto_scale_charts()
        if model.trades:
            self.select_trade(0)

    def clear(self) -> None:
        self.set_model(build_backtest_trade_review_model(None, None))

    def retranslate_ui(self) -> None:
        language = self._language_provider()
        self.titleLabel.setText(tr("backtest.trade_review.title", language))
        self.emptyLabel.setText(tr("backtest.trade_review.empty", language))
        self.pricePlot.getPlotItem().setLabel(
            "left",
            tr("backtest.trade_review.price_axis", language),
        )
        self.volumePlot.getPlotItem().setLabel(
            "left",
            tr("backtest.trade_review.volume_axis", language),
        )
        self.volumePlot.getPlotItem().setLabel(
            "bottom",
            tr("backtest.trade_review.x_axis", language),
        )
        self.btnPrevEntry.setText(tr("backtest.trade_review.prev_entry", language))
        self.btnNextEntry.setText(tr("backtest.trade_review.next_entry", language))
        self.btnPrevExit.setText(tr("backtest.trade_review.prev_exit", language))
        self.btnNextExit.setText(tr("backtest.trade_review.next_exit", language))
        self.tradeListToggle.setText(tr("backtest.trade_review.trade_list", language))
        self.tradeTable.setHorizontalHeaderLabels(
            [
                tr("backtest.trade_review.column.entry_time", language),
                tr("backtest.trade_review.column.entry_price", language),
                tr("backtest.trade_review.column.exit_time", language),
                tr("backtest.trade_review.column.exit_price", language),
                tr("backtest.trade_review.column.return_pct", language),
                tr("backtest.trade_review.column.pnl", language),
                tr("backtest.trade_review.column.holding_bars", language),
                tr("backtest.trade_review.column.exit_reason", language),
            ]
        )

    def apply_theme(self, theme: dict | None) -> None:
        self._theme = normalize_theme_settings(theme)
        grid_alpha = max(0.0, min(1.0, self._theme["grid_alpha"] / 100.0))
        for chart in (self.pricePlot, self.volumePlot):
            chart.setBackground(self._theme["chart_bg"])
            chart.showGrid(x=True, y=True, alpha=grid_alpha)
            plot_item = chart.getPlotItem()
            for side in ("left", "bottom", "right", "top"):
                axis = plot_item.getAxis(side)
                if axis is not None:
                    axis.setPen(pg.mkPen(self._theme["chart_axis"]))
                    axis.setTextPen(pg.mkPen(self._theme["chart_axis"]))
        self.candles.set_style(
            self._theme["chart_up"],
            self._theme["chart_down"],
            self._theme["chart_wick"],
        )
        self.volumes.set_style(
            self._theme["chart_volume_up"],
            self._theme["chart_volume_down"],
        )
        self.entryMarkers.setPen(self._entry_pen("LONG"))
        self.entryMarkers.setBrush(self._entry_brush("LONG"))
        self.entryMarkers.setSymbol("t1")
        self.exitMarkers.setPen(self._exit_pen("LONG"))
        self.exitMarkers.setBrush(self._exit_brush("LONG"))
        self.exitMarkers.setSymbol("x")
        self.selectedEntryMarker.setPen(pg.mkPen(self._theme["warning"], width=2))
        self.selectedEntryMarker.setBrush(pg.mkBrush(self._theme["warning"]))
        self.selectedEntryMarker.setSymbol("t1")
        self.selectedExitMarker.setPen(pg.mkPen(self._theme["warning"], width=2))
        self.selectedExitMarker.setBrush(pg.mkBrush(self._theme["warning"]))
        self.selectedExitMarker.setSymbol("x")
        color = QtGui.QColor(self._theme["warning"])
        color.setAlpha(45)
        self.holdingRegion.setBrush(pg.mkBrush(color))
        for line in self.holdingRegion.lines:
            line.setPen(pg.mkPen(self._theme["warning"]))
        self.emptyLabel.setStyleSheet(
            f"color: {self._theme['text_secondary']}; background: transparent;"
        )
        apply_readable_plot_text(self.pricePlot, self._theme)
        apply_readable_plot_text(self.volumePlot, self._theme)

    def current_trade(self):
        if self.selectedTradeIndex < 0:
            return None
        if self.selectedTradeIndex >= len(self._last_model.trades):
            return None
        return self._last_model.trades[self.selectedTradeIndex]

    def visible_bar_window(self) -> tuple[int, int] | None:
        klines = self._last_model.klines
        if not klines.has_data:
            return None
        left, right = self.pricePlot.getPlotItem().vb.viewRange()[0]
        indexes = [
            index
            for index, value in enumerate(klines.x)
            if left <= value <= right
        ]
        if not indexes:
            return None
        return klines.bar_indices[indexes[0]], klines.bar_indices[indexes[-1]]

    def select_trade(self, trade_index: int) -> None:
        if trade_index < 0 or trade_index >= len(self._last_model.trades):
            return
        self.selectedTradeIndex = int(trade_index)
        trade = self._last_model.trades[self.selectedTradeIndex]
        self.tradeTable.selectRow(self.selectedTradeIndex)
        self.selectedEntryMarker.setSymbol(self._entry_symbol(trade.side))
        self.selectedEntryMarker.setData(
            [{"pos": (trade.entry_x, trade.entry_price), "data": trade.trade_index}]
        )
        if trade.exit_x is None or trade.exit_price is None:
            self.selectedExitMarker.setData([])
            self.holdingRegion.hide()
        else:
            self.selectedExitMarker.setSymbol("x")
            self.selectedExitMarker.setData(
                [{"pos": (trade.exit_x, trade.exit_price), "data": trade.trade_index}]
            )
            self.holdingRegion.setRegion((trade.entry_x, trade.exit_x))
            self.holdingRegion.show()
        self._jump_to_trade(trade)

    def _toggle_trade_table(self, checked: bool) -> None:
        self.tradeTable.setVisible(bool(checked))
        self.tradeListToggle.setArrowType(
            QtCore.Qt.DownArrow if checked else QtCore.Qt.RightArrow
        )

    def _populate_trade_table(self) -> None:
        self.tradeTable.setRowCount(len(self._last_model.trades))
        for row, trade in enumerate(self._last_model.trades):
            values = (
                trade.entry_time,
                trade.entry_price,
                trade.exit_time,
                trade.exit_price,
                trade.return_pct,
                trade.pnl,
                trade.holding_bars,
                trade.exit_reason,
            )
            for column, value in enumerate(values):
                text = "" if value is None else str(value)
                self.tradeTable.setItem(row, column, QtWidgets.QTableWidgetItem(text))
        self.tradeTable.resizeColumnsToContents()

    def _navigate(self, step: int, point_type: str) -> None:
        if not self._last_model.trades:
            return
        current_trade = self.current_trade()
        if current_trade is not None:
            current_x = (
                current_trade.exit_x
                if point_type == "exit" and current_trade.exit_x is not None
                else current_trade.entry_x
            )
        else:
            left, right = self.pricePlot.getPlotItem().vb.viewRange()[0]
            current_x = (left + right) / 2.0
        points = []
        for trade in self._last_model.trades:
            point_x = trade.exit_x if point_type == "exit" else trade.entry_x
            if point_x is None:
                continue
            points.append((point_x, trade.trade_index))
        if not points:
            return
        points.sort()
        if step < 0:
            candidates = [item for item in points if item[0] < current_x]
            self.select_trade(candidates[-1][1] if candidates else points[0][1])
        else:
            candidates = [item for item in points if item[0] > current_x]
            self.select_trade(candidates[0][1] if candidates else points[-1][1])

    def _jump_to_trade(self, trade) -> None:
        left, right = self._window_for_trade(trade)
        self.pricePlot.setXRange(left, right, padding=0.0)
        self._fit_price_y_range(left, right)
        self._fit_volume_y_range(left, right)
        self._show_auto_button()

    def _window_for_trade(self, trade) -> tuple[float, float]:
        klines = self._last_model.klines
        positions = {bar_index: index for index, bar_index in enumerate(klines.bar_indices)}
        entry_position = positions.get(trade.entry_bar_index, 0)
        exit_position = (
            positions.get(trade.exit_bar_index)
            if trade.exit_bar_index is not None
            else entry_position
        )
        left_position = max(0, entry_position - 80)
        right_position = min(len(klines.x) - 1, entry_position + 80)
        if exit_position is not None and (
            exit_position < left_position or exit_position > right_position
        ):
            left_position = max(0, min(entry_position, exit_position) - 20)
            right_position = min(len(klines.x) - 1, max(entry_position, exit_position) + 20)
        width = self._bar_width()
        return klines.x[left_position] - width, klines.x[right_position] + width

    def _fit_price_y_range(self, left: float, right: float) -> None:
        klines = self._last_model.klines
        indexes = [
            index
            for index, value in enumerate(klines.x)
            if left <= value <= right
        ]
        if not indexes:
            return
        low = min(klines.low[index] for index in indexes)
        high = max(klines.high[index] for index in indexes)
        span = max(1e-6, high - low)
        self.pricePlot.setYRange(low - span * 0.08, high + span * 0.08, padding=0.0)

    def _fit_volume_y_range(self, left: float, right: float) -> None:
        klines = self._last_model.klines
        values = [
            klines.volume[index]
            for index, value in enumerate(klines.x)
            if left <= value <= right
        ]
        if not values:
            return
        self.volumePlot.setYRange(0.0, max(1e-6, max(values) * 1.08), padding=0.0)

    def _auto_scale_charts(self) -> None:
        klines = self._last_model.klines
        if not klines.has_data:
            return
        width = self._bar_width()
        self.pricePlot.setXRange(klines.x[0] - width, klines.x[-1] + width, padding=0.02)
        low = min(klines.low)
        high = max(klines.high)
        price_span = max(1e-6, high - low)
        self.pricePlot.setYRange(
            low - price_span * 0.08,
            high + price_span * 0.08,
            padding=0.0,
        )
        volume_high = max(0.0, max(klines.volume))
        self.volumePlot.setYRange(0.0, max(1e-6, volume_high * 1.08), padding=0.0)
        self._show_auto_button()

    def _show_auto_button(self) -> None:
        plot_item = self.volumePlot.getPlotItem()
        plot_item.mouseHovering = True
        plot_item.showButtons()
        plot_item.updateButtons()

    def _bar_width(self) -> float:
        x_values = self._last_model.klines.x
        if len(x_values) >= 2:
            return max(0.001, abs(x_values[1] - x_values[0]) * 0.7)
        return 0.7

    def _entry_symbol(self, side: str) -> str:
        return "t" if str(side).upper().startswith("SHORT") else "t1"

    def _entry_pen(self, side: str):
        color = (
            self._theme["premium_sell"]
            if str(side).upper().startswith("SHORT")
            else self._theme["chart_up"]
        )
        return pg.mkPen(color)

    def _entry_brush(self, side: str):
        color = (
            self._theme["premium_sell"]
            if str(side).upper().startswith("SHORT")
            else self._theme["chart_up"]
        )
        return pg.mkBrush(color)

    def _exit_pen(self, side: str):
        color = (
            self._theme["marker_close_short"]
            if str(side).upper().startswith("SHORT")
            else self._theme["marker_close_long"]
        )
        return pg.mkPen(color)

    def _exit_brush(self, side: str):
        color = (
            self._theme["marker_close_short"]
            if str(side).upper().startswith("SHORT")
            else self._theme["marker_close_long"]
        )
        return pg.mkBrush(color)

    def shutdown(self) -> None:
        self.pricePlot.shutdown()
        self.volumePlot.shutdown()

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)


__all__ = ["BacktestTradeReviewWidget"]
