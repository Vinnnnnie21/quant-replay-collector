from __future__ import annotations

from typing import Any, Callable

from PySide6 import QtCore, QtWidgets
import pyqtgraph as pg

try:
    from app_i18n import tr
    from presenters.backtest_equity_curve import (
        BacktestEquityCurveModel,
        EquityCurveSeries,
        build_backtest_equity_curve_model,
    )
    from ui_style import SPACING, normalize_theme_settings
    from views.plot_readability import apply_readable_plot_text, make_bold
    from views.plot_lifecycle import close_parent_owned_graphics_view, prepare_plot_for_shutdown
except ImportError:  # pragma: no cover - package import path
    from ..app_i18n import tr
    from ..presenters.backtest_equity_curve import (
        BacktestEquityCurveModel,
        EquityCurveSeries,
        build_backtest_equity_curve_model,
    )
    from ..ui_style import SPACING, normalize_theme_settings
    from .plot_readability import apply_readable_plot_text, make_bold
    from .plot_lifecycle import close_parent_owned_graphics_view, prepare_plot_for_shutdown


class _ManagedBacktestPlotWidget(pg.PlotWidget):
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


class BacktestEquityCurveWidget(QtWidgets.QFrame):
    strategyEntryClicked = QtCore.Signal(int)

    def __init__(
        self,
        *,
        language_provider: Callable[[], str],
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._language_provider = language_provider
        self._theme = normalize_theme_settings(None)
        self._last_model = BacktestEquityCurveModel(
            strategy=_empty_series(),
            random_baseline=_empty_series(),
            initial_equity=None,
            random_baseline_status="",
        )
        self.setProperty("role", "statusBlock")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(SPACING["sm"], SPACING["sm"], SPACING["sm"], SPACING["sm"])
        layout.setSpacing(SPACING["xs"])

        self.titleLabel = QtWidgets.QLabel()
        self.titleLabel.setProperty("role", "sectionTitle")
        make_bold(self.titleLabel, point_size=12)
        self.plot = _ManagedBacktestPlotWidget(
            self,
            axisItems={"bottom": pg.DateAxisItem(orientation="bottom")},
        )
        self.plot.setMinimumHeight(280)
        self.plot.setMouseEnabled(x=True, y=True)
        self.plot.setAntialiasing(True)
        self.stateLabel = QtWidgets.QLabel(self.plot)
        self.stateLabel.setProperty("role", "mutedText")
        self.stateLabel.setAlignment(QtCore.Qt.AlignCenter)
        self.stateLabel.setWordWrap(True)
        self.stateLabel.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.stateLabel.setGeometry(self.plot.rect())
        self.stateLabel.hide()
        self.plot.installEventFilter(self)

        self.legend = self.plot.addLegend(offset=(8, 8))
        self.strategyCurve = self.plot.plot([], [])
        self.randomBaselineCurve = self.plot.plot([], [])
        self.strategyEntryMarkers = pg.ScatterPlotItem(size=10, pxMode=True)
        self.initialEquityLine = pg.InfiniteLine(angle=0)
        self.initialEquityLegendItem = pg.PlotDataItem([], [])
        self.plot.addItem(self.strategyEntryMarkers)
        self.plot.addItem(self.initialEquityLine)
        self.plot.addItem(self.initialEquityLegendItem)
        layout.addWidget(self.titleLabel)
        layout.addWidget(self.plot)
        self.retranslate_ui()
        self.apply_theme(None)
        self.strategyEntryMarkers.sigClicked.connect(self._on_strategy_entry_clicked)
        self.clear()

    def set_result(self, result: Any, *, initial_equity: float | None = None) -> None:
        self.set_model(
            build_backtest_equity_curve_model(result, initial_equity=initial_equity)
        )

    def set_model(self, model: BacktestEquityCurveModel) -> None:
        self._last_model = model
        self.strategyCurve.setData(list(model.strategy.x), list(model.strategy.y))
        self.strategyCurve.setVisible(model.strategy.has_data)
        self.randomBaselineCurve.setData(
            list(model.random_baseline.x),
            list(model.random_baseline.y),
        )
        self.randomBaselineCurve.setVisible(model.random_baseline.has_data)
        self.strategyEntryMarkers.setData(
            [
                {"pos": (point.x, point.y), "data": point.trade_index}
                for point in model.strategy_entries
            ]
        )
        if model.initial_equity is None:
            self.initialEquityLine.hide()
        else:
            self.initialEquityLine.setValue(float(model.initial_equity))
            self.initialEquityLine.show()
        self._show_state_label(not model.strategy.has_data)
        self._fit_model_range(model)
        self._show_auto_button()

    def clear(self) -> None:
        self.set_model(
            BacktestEquityCurveModel(
                strategy=_empty_series(),
                random_baseline=_empty_series(),
                initial_equity=None,
                random_baseline_status="",
            )
        )

    def retranslate_ui(self) -> None:
        language = self._language_provider()
        self.titleLabel.setText(tr("backtest.equity_curve.title", language))
        self.stateLabel.setText(tr("backtest.equity_curve.empty", language))
        self.plot.getPlotItem().setLabel(
            "left",
            tr("backtest.equity_curve.y_axis", language),
        )
        self.plot.getPlotItem().setLabel(
            "bottom",
            tr("backtest.equity_curve.x_axis", language),
        )
        self._refresh_legend_labels()

    def apply_theme(self, theme: dict | None) -> None:
        self._theme = normalize_theme_settings(theme)
        grid_alpha = max(0.0, min(1.0, self._theme["grid_alpha"] / 100.0))
        self.plot.setBackground(self._theme["chart_bg"])
        self.plot.showGrid(x=True, y=True, alpha=grid_alpha)
        plot_item = self.plot.getPlotItem()
        for side in ("left", "bottom", "right", "top"):
            axis = plot_item.getAxis(side)
            if axis is not None:
                axis.setPen(pg.mkPen(self._theme["chart_axis"]))
                axis.setTextPen(pg.mkPen(self._theme["chart_axis"]))
        self.strategyCurve.setPen(pg.mkPen(self._theme["success"], width=2))
        self.randomBaselineCurve.setPen(pg.mkPen(self._theme["info"], width=1.8))
        self.strategyEntryMarkers.setPen(pg.mkPen(self._theme["success"], width=1))
        self.strategyEntryMarkers.setBrush(pg.mkBrush(self._theme["success"]))
        self.strategyEntryMarkers.setSymbol("o")
        initial_pen = pg.mkPen(self._theme["text_tertiary"], style=QtCore.Qt.DashLine)
        self.initialEquityLine.setPen(initial_pen)
        self.initialEquityLegendItem.setPen(initial_pen)
        self.stateLabel.setStyleSheet(
            f"color: {self._theme['text_secondary']}; background: transparent;"
        )
        apply_readable_plot_text(self.plot, self._theme)
        self._apply_legend_theme()

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if watched is self.plot and event.type() == QtCore.QEvent.Resize:
            self.stateLabel.setGeometry(self.plot.rect())
        return super().eventFilter(watched, event)

    def _show_state_label(self, visible: bool) -> None:
        if visible:
            self.stateLabel.show()
        else:
            self.stateLabel.hide()

    def _show_auto_button(self) -> None:
        plot_item = self.plot.getPlotItem()
        plot_item.mouseHovering = True
        plot_item.showButtons()
        plot_item.updateButtons()

    def _on_strategy_entry_clicked(self, _plot, points, _event) -> None:
        if not points:
            return
        try:
            trade_index = int(points[0].data())
        except (TypeError, ValueError):
            return
        self.strategyEntryClicked.emit(trade_index)

    def _refresh_legend_labels(self) -> None:
        language = self._language_provider()
        self.legend.clear()
        self.legend.addItem(
            self.strategyCurve,
            tr("backtest.equity_curve.strategy", language),
        )
        self.legend.addItem(
            self.randomBaselineCurve,
            tr("backtest.equity_curve.random_baseline", language),
        )
        self.legend.addItem(
            self.initialEquityLegendItem,
            tr("backtest.equity_curve.initial_equity", language),
        )
        self._apply_legend_theme()

    def _apply_legend_theme(self) -> None:
        if not hasattr(self, "legend"):
            return
        for _sample, label in self.legend.items:
            label.setText(
                label.text,
                color=self._theme["text_secondary"],
                size="11pt",
                bold=True,
            )

    def _fit_model_range(self, model: BacktestEquityCurveModel) -> None:
        x_values = [*model.strategy.x, *model.random_baseline.x]
        y_values = [*model.strategy.y, *model.random_baseline.y]
        if model.initial_equity is not None:
            y_values.append(float(model.initial_equity))
        if x_values:
            left = min(x_values)
            right = max(x_values)
            if left == right:
                left -= 1.0
                right += 1.0
            self.plot.setXRange(left, right, padding=0.03)
        if y_values:
            low = min(y_values)
            high = max(y_values)
            span = max(1e-6, high - low)
            self.plot.setYRange(low - span * 0.08, high + span * 0.08, padding=0.0)

    def shutdown(self) -> None:
        self.plot.shutdown()

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)


def _empty_series():
    return EquityCurveSeries((), ())


__all__ = ["BacktestEquityCurveWidget"]
