from __future__ import annotations

import pandas as pd
import pytest
from types import SimpleNamespace


QtWidgets = pytest.importorskip("PySide6.QtWidgets")
QtCore = pytest.importorskip("PySide6.QtCore")
QtGui = pytest.importorskip("PySide6.QtGui")
pytest.importorskip("pyqtgraph")

from backtest_panel import BacktestPanel
from controllers.backtest_controller import BacktestController
from backtesting.strategy_spec import StrategySpec
from services.backtest_service import BacktestServiceResult
from ui_style import LIGHT_THEME


def _send_wheel(widget: QtWidgets.QWidget) -> None:
    local = QtCore.QPointF(widget.rect().center())
    event = QtGui.QWheelEvent(
        local,
        QtCore.QPointF(widget.mapToGlobal(local.toPoint())),
        QtCore.QPoint(),
        QtCore.QPoint(0, -120),
        QtCore.Qt.NoButton,
        QtCore.Qt.NoModifier,
        QtCore.Qt.ScrollUpdate,
        False,
    )
    QtWidgets.QApplication.sendEvent(widget, event)


class _Service:
    def __init__(
        self,
        *,
        with_trade: bool = False,
        with_random_baseline: bool = False,
        random_status: str = "ready",
        equity_points: int = 1,
        trades: list[dict] | None = None,
    ) -> None:
        self.calls: list[dict] = []
        self.with_trade = with_trade
        self.with_random_baseline = with_random_baseline
        self.random_status = random_status
        self.equity_points = equity_points
        self.trades = trades

    def run(self, config, market_df, **kwargs):
        self.calls.append({"config": config, "market_df": market_df, **kwargs})
        trades = []
        if self.trades is not None:
            trades = list(self.trades)
        elif self.with_trade:
            trades.append(_trade(1, 2))
        random_baseline = pd.DataFrame()
        random_summary = {"status": "skipped", "warnings": ["random baseline skipped: fixture"]}
        if self.with_random_baseline:
            random_baseline = pd.DataFrame(
                [
                    {"bar_index": 1, "time": "2026-01-01 09:00:00+08:00", "equity": 9998, "drawdown": 0},
                    {"bar_index": 2, "time": "2026-01-01 09:05:00+08:00", "equity": 10004, "drawdown": 0},
                ]
            )
            random_summary = {"status": self.random_status, "random_seed": 7, "simulation_count": 100}
        warnings = [
            "Backtest result is for research only and does not represent live trading returns."
        ]
        if self.random_status in {"partial", "skipped"}:
            warnings.append(f"random baseline {self.random_status}: fixture")
        equity_curve = pd.DataFrame(
            [
                {"bar_index": 1, "time": "2026-01-01 09:00:00+08:00", "equity": 10000, "drawdown": 0},
                {"bar_index": 2, "time": "2026-01-01 09:05:00+08:00", "equity": 10010, "drawdown": 0},
            ][: self.equity_points]
        )
        return BacktestServiceResult(
            success=True,
            summary={
                "total_trades": len(trades),
                "closed_trades": len(trades),
                "avg_return": 0.25,
                "median_return": 0.1,
                "total_return": -1.5,
                "max_drawdown": -2.0,
                "expectancy": 0.2,
            },
            trades=pd.DataFrame(trades),
            equity_curve=equity_curve,
            manual_vs_rule_comparison={
                "manual_trade_count": 1,
                "rule_trade_count": 0,
                "overlap_entry_bars": [],
                "manual_only_bars": [1],
                "rule_only_bars": [],
                "overlap_ratio": 0.0,
            },
            warnings=warnings,
            errors=[],
            random_baseline_equity_curve=random_baseline,
            random_baseline_summary=random_summary,
        )


class _FailingService:
    def run(self, config, market_df, **kwargs):
        return BacktestServiceResult(
            success=False,
            summary={},
            trades=pd.DataFrame(),
            equity_curve=pd.DataFrame(),
            manual_vs_rule_comparison=None,
            warnings=[],
            errors=["fixture failure"],
        )


class _Host(QtWidgets.QWidget):
    current_language = "en_US"

    def __init__(self) -> None:
        super().__init__()
        self.df = pd.DataFrame({"close": [1.0]})
        self.trades = [{"entry_bar_index": 1}]
        self.symbolBox = QtWidgets.QComboBox()
        self.symbolBox.addItem("BTCUSDT")
        self.intervalBox = QtWidgets.QComboBox()
        self.intervalBox.addItem("5m")
        self._loaded_market_key = ("BTCUSDT", "5m", "2026-01-01", "2026-01-02")


class _ChineseHost(_Host):
    current_language = "zh_CN"


def _review_host() -> _Host:
    host = _Host()
    host.df = pd.DataFrame(
        {
            "bar_index": range(6),
            "open_time_bjt": pd.date_range(
                "2026-01-01 09:00:00",
                periods=6,
                freq="5min",
                tz="Asia/Shanghai",
            ),
            "open": [100, 101, 102, 101, 103, 104],
            "high": [102, 103, 104, 103, 105, 106],
            "low": [99, 100, 101, 100, 102, 103],
            "close": [101, 102, 101, 103, 104, 105],
            "volume": [10, 12, 11, 15, 13, 14],
        }
    )
    return host


def _review_host_with_bars(count: int) -> _Host:
    host = _Host()
    host.df = pd.DataFrame(
        {
            "bar_index": range(count),
            "open_time_bjt": pd.date_range(
                "2026-01-01 09:00:00",
                periods=count,
                freq="5min",
                tz="Asia/Shanghai",
            ),
            "open": [100 + index * 0.1 for index in range(count)],
            "high": [101 + index * 0.1 for index in range(count)],
            "low": [99 + index * 0.1 for index in range(count)],
            "close": [100.5 + index * 0.1 for index in range(count)],
            "volume": [10 + (index % 7) for index in range(count)],
        }
    )
    return host


def _trade(entry_bar: int, exit_bar: int) -> dict:
    return {
        "entry_bar_index": entry_bar,
        "entry_time": f"t{entry_bar}",
        "entry_price": 100 + entry_bar * 0.1,
        "exit_bar_index": exit_bar,
        "exit_time": f"t{exit_bar}",
        "exit_price": 100 + exit_bar * 0.1,
        "side": "LONG",
        "return_pct": 1,
        "pnl": 10,
        "exit_reason": "take_profit",
        "holding_bars": exit_bar - entry_bar,
        "fee": 0,
        "slippage": 0,
    }


def _loss_trade(entry_bar: int, exit_bar: int) -> dict:
    trade = _trade(entry_bar, exit_bar)
    trade.update({"return_pct": -2.5, "pnl": -25})
    return trade


def _item_color(item: QtWidgets.QTableWidgetItem) -> QtGui.QColor:
    return item.data(QtCore.Qt.ForegroundRole).color()


def test_chinese_backtest_panel_has_no_english_action_labels_or_raw_field_keys():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _ChineseHost()
    panel = BacktestPanel(host, controller=BacktestController(service=_Service()))
    try:
        visible_texts: list[str] = []
        for widget in panel.findChildren(QtWidgets.QWidget):
            if isinstance(widget, (QtWidgets.QLabel, QtWidgets.QAbstractButton)):
                visible_texts.append(widget.text())
            if isinstance(widget, QtWidgets.QTabWidget):
                visible_texts.extend(
                    widget.tabText(index) for index in range(widget.count())
                )

        forbidden = {
            "Load default params",
            "Apply params from analysis",
            "Reset",
            "Import candidate rule",
            "Run backtest",
            "Run parameter scan",
            "Run walk-forward",
            "Export backtest",
            "Trades",
            "Equity",
            "Manual vs Rule",
            "symbol",
            "backtest_start",
            "notional_per_trade",
        }
        assert forbidden.intersection(visible_texts) == set()
    finally:
        panel.close()
        host.close()
        app.processEvents()


def test_chinese_backtest_result_summary_uses_chinese_labels():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _ChineseHost()
    panel = BacktestPanel(host, controller=BacktestController(service=_Service()))
    try:
        panel.run_backtest()

        result = panel.resultText.toPlainText()
        assert "历史模拟只用于规则假设研究" in result
        assert "所选时间段没有发生规则交易" in result
        assert "Historical simulation" not in result
        assert "Warning:" not in result
    finally:
        panel.close()
        host.close()
        app.processEvents()


def test_chinese_backtest_result_tables_localize_enum_and_metric_values():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _ChineseHost()
    panel = BacktestPanel(
        host,
        controller=BacktestController(service=_Service(with_trade=True)),
    )
    try:
        panel.run_backtest()

        assert panel.tradeResultTable.item(0, 6).text() == "多"
        assert panel.tradeResultTable.item(0, 9).text() == "止盈"
        assert panel.comparisonTable.item(0, 0).text() == "手动交易数"
        assert "manual_trade_count" not in {
            panel.comparisonTable.item(row, 0).text()
            for row in range(panel.comparisonTable.rowCount())
        }
    finally:
        panel.close()
        host.close()
        app.processEvents()


def test_existing_backtest_result_is_retranslated_after_language_switch():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _Host()
    panel = BacktestPanel(host, controller=BacktestController(service=_Service()))
    try:
        panel.run_backtest()
        assert "Historical simulation" in panel.resultText.toPlainText()

        host.current_language = "zh_CN"
        panel.retranslate_ui()

        result = panel.resultText.toPlainText()
        assert "历史模拟" in result
        assert "Historical simulation" not in result
        assert "Backtest result is for research only" not in result
    finally:
        panel.close()
        host.close()
        app.processEvents()


def test_backtest_panel_exposes_minimum_inputs_applies_analysis_and_displays_result():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _Host()
    service = _Service()
    panel = BacktestPanel(host, controller=BacktestController(service=service))

    assert panel.directionBox.currentData() == "long_only"
    assert [panel.directionBox.itemText(i) for i in range(panel.directionBox.count())] == ["Long Only"]
    assert panel.trendLookbackSpin.value() == 20
    assert panel.btnLoadDefaults.text()
    assert panel.btnApplyAnalysis.text()
    assert panel.btnReset.text()

    panel.set_analysis_params_source({"drop_pct_threshold": 0.05, "future_window": 12})
    panel.apply_analysis_params()
    assert panel.minDropSpin.value() == 0.05
    assert panel.maxHoldingBarsSpin.value() == 12

    panel.run_backtest()

    assert len(service.calls) == 1
    assert "No rule trades" in panel.resultText.toPlainText()
    assert panel.equityResultTable.rowCount() == 1
    assert panel.comparisonTable.rowCount() > 0
    panel.close()


def test_backtest_panel_displays_strategy_random_and_initial_equity_curves():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _Host()
    panel = BacktestPanel(
        host,
        controller=BacktestController(
            service=_Service(
                with_trade=True,
                with_random_baseline=True,
                equity_points=2,
            )
        ),
    )

    panel.run_backtest()

    plot_item = panel.equityCurveWidget.plot.getPlotItem()
    strategy_x, strategy_y = panel.equityCurveWidget.strategyCurve.getData()
    random_x, random_y = panel.equityCurveWidget.randomBaselineCurve.getData()
    assert list(strategy_y) == [10000, 10010]
    assert list(random_y) == [9998, 10004]
    assert list(strategy_x) == list(random_x)
    assert panel.equityCurveWidget.initialEquityLine.value() == 10000
    assert tuple(plot_item.vb.state["mouseEnabled"]) == (True, True)
    assert plot_item.autoBtn.isVisible()
    assert plot_item.autoBtn.parentItem() is plot_item
    panel.close()


def test_backtest_equity_curve_displays_named_legend_items():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _Host()
    panel = BacktestPanel(
        host,
        controller=BacktestController(
            service=_Service(
                with_trade=True,
                with_random_baseline=True,
                equity_points=2,
            )
        ),
    )

    panel.run_backtest()

    labels = [
        sample_label[1].text
        for sample_label in panel.equityCurveWidget.legend.items
    ]
    assert labels == [
        "Strategy Equity",
        "Random Entry Baseline",
        "Initial Equity",
    ]
    panel.close()


def test_backtest_panel_displays_trade_review_candles_volume_and_strategy_markers():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _review_host()
    panel = BacktestPanel(
        host,
        controller=BacktestController(service=_Service(with_trade=True)),
    )

    panel.run_backtest()

    review = panel.tradeReviewWidget
    assert review.pricePlot.isHidden() is False
    assert review.volumePlot.isHidden() is False
    assert len(review.entryMarkers.points()) == 1
    assert len(review.exitMarkers.points()) == 1
    assert len(review.randomBaselineMarkers.points()) == 0
    review.pricePlot.setXRange(1, 3, padding=0)
    app.processEvents()
    assert review.volumePlot.getPlotItem().vb.viewRange()[0] == pytest.approx([1, 3])
    assert tuple(review.pricePlot.getPlotItem().vb.state["mouseEnabled"]) == (True, True)
    assert tuple(review.volumePlot.getPlotItem().vb.state["mouseEnabled"]) == (True, True)
    assert review.volumePlot.getPlotItem().autoBtn.isVisible()
    assert review.volumePlot.getPlotItem().autoBtn.parentItem() is review.volumePlot.getPlotItem()
    panel.close()


def test_backtest_trade_review_list_selection_navigation_and_highlight():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _review_host_with_bars(220)
    panel = BacktestPanel(
        host,
        controller=BacktestController(
            service=_Service(trades=[_trade(30, 40), _trade(100, 115)])
        ),
    )

    panel.run_backtest()

    review = panel.tradeReviewWidget
    assert review.tradeTable.isHidden() is True
    review.tradeListToggle.click()
    assert review.tradeTable.isHidden() is False
    assert review.tradeTable.rowCount() == 2

    review.tradeTable.cellClicked.emit(1, 0)

    assert review.selectedTradeIndex == 1
    assert len(review.selectedEntryMarker.points()) == 1
    assert len(review.selectedExitMarker.points()) == 1
    assert review.holdingRegion.isVisible()
    selected_trade = review.current_trade()
    x_range = review.pricePlot.getPlotItem().vb.viewRange()[0]
    assert x_range[0] < selected_trade.entry_x < x_range[1]
    assert x_range[0] < selected_trade.exit_x < x_range[1]

    review.btnPrevEntry.click()
    assert review.selectedTradeIndex == 0
    review.btnNextEntry.click()
    assert review.selectedTradeIndex == 1
    review.btnPrevExit.click()
    assert review.selectedTradeIndex == 0
    review.btnNextExit.click()
    assert review.selectedTradeIndex == 1
    panel.close()


def test_backtest_trade_review_navigation_buttons_clamp_at_edges():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _review_host_with_bars(220)
    panel = BacktestPanel(
        host,
        controller=BacktestController(
            service=_Service(trades=[_trade(30, 40), _trade(100, 115)])
        ),
    )

    panel.run_backtest()

    review = panel.tradeReviewWidget
    assert review.selectedTradeIndex == 0
    review.btnPrevEntry.click()
    assert review.selectedTradeIndex == 0
    review.btnPrevExit.click()
    assert review.selectedTradeIndex == 0

    review.select_trade(1)
    review.btnNextEntry.click()
    assert review.selectedTradeIndex == 1
    review.btnNextExit.click()
    assert review.selectedTradeIndex == 1
    panel.close()


def test_clicking_strategy_equity_entry_marker_selects_trade_review_trade():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _review_host()
    panel = BacktestPanel(
        host,
        controller=BacktestController(
            service=_Service(trades=[_trade(1, 2), _trade(2, 3)], equity_points=2)
        ),
    )

    panel.run_backtest()

    points = panel.equityCurveWidget.strategyEntryMarkers.points()
    assert len(points) == 2
    panel.equityCurveWidget.strategyEntryMarkers.sigClicked.emit(
        panel.equityCurveWidget.strategyEntryMarkers,
        [points[1]],
        None,
    )

    assert panel.tradeReviewWidget.selectedTradeIndex == 1
    assert panel.tradeReviewWidget.tradeTable.currentRow() == 1
    assert len(panel.tradeReviewWidget.selectedEntryMarker.points()) == 1
    selected_trade = panel.tradeReviewWidget.current_trade()
    x_range = panel.tradeReviewWidget.pricePlot.getPlotItem().vb.viewRange()[0]
    assert x_range[0] < selected_trade.entry_x < x_range[1]
    panel.close()


def test_backtest_trade_review_theme_updates_charts_markers_and_highlight():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _review_host()
    panel = BacktestPanel(
        host,
        controller=BacktestController(service=_Service(with_trade=True)),
    )

    panel.run_backtest()
    panel.apply_theme(LIGHT_THEME)

    review = panel.tradeReviewWidget
    assert review.pricePlot.backgroundBrush().color() == QtGui.QColor(
        LIGHT_THEME["chart_bg"]
    )
    assert review.volumePlot.backgroundBrush().color() == QtGui.QColor(
        LIGHT_THEME["chart_bg"]
    )
    assert review.pricePlot.getPlotItem().getAxis("left").pen().color() == QtGui.QColor(
        LIGHT_THEME["chart_axis"]
    )
    assert review.volumePlot.getPlotItem().getAxis("left").pen().color() == QtGui.QColor(
        LIGHT_THEME["chart_axis"]
    )
    assert review.entryMarkers.opts["pen"].color() == QtGui.QColor(
        LIGHT_THEME["success"]
    )
    assert review.exitMarkers.opts["pen"].color() == QtGui.QColor(
        LIGHT_THEME["marker_close_long"]
    )
    assert review.holdingRegion.lines[0].pen.color() == QtGui.QColor(
        LIGHT_THEME["warning"]
    )
    panel.close()


def test_backtest_trade_review_markers_match_main_chart_trade_semantics():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _review_host()
    panel = BacktestPanel(
        host,
        controller=BacktestController(service=_Service(with_trade=True)),
    )

    panel.run_backtest()
    panel.apply_theme(LIGHT_THEME)

    review = panel.tradeReviewWidget
    assert review.entryMarkers.opts["symbol"] == "t1"
    assert review.exitMarkers.opts["symbol"] == "x"
    assert review.selectedEntryMarker.opts["symbol"] == "t1"
    assert review.selectedExitMarker.opts["symbol"] == "x"
    assert review.entryMarkers.opts["size"] == 14
    assert review.exitMarkers.opts["size"] == 12
    assert review.selectedEntryMarker.opts["size"] > review.entryMarkers.opts["size"]
    assert review.selectedExitMarker.opts["size"] > review.exitMarkers.opts["size"]
    assert review.entryMarkers.opts["pen"].color() == QtGui.QColor(LIGHT_THEME["chart_up"])
    assert review.exitMarkers.opts["pen"].color() == QtGui.QColor(
        LIGHT_THEME["marker_close_long"]
    )
    panel.close()


def test_backtest_charts_have_larger_readable_typography():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _review_host()
    panel = BacktestPanel(
        host,
        controller=BacktestController(
            service=_Service(with_trade=True, with_random_baseline=True, equity_points=2)
        ),
    )

    panel.run_backtest()

    assert panel.equityCurveWidget.plot.minimumHeight() >= 280
    assert panel.tradeReviewWidget.pricePlot.minimumHeight() >= 320
    assert panel.tradeReviewWidget.volumePlot.minimumHeight() >= 120
    assert panel.equityCurveWidget.titleLabel.font().bold()
    assert panel.tradeReviewWidget.titleLabel.font().bold()
    axis = panel.equityCurveWidget.plot.getPlotItem().getAxis("left")
    tick_font = axis.style.get("tickFont")
    assert tick_font is not None
    assert tick_font.pointSize() >= 10
    legend_label = panel.equityCurveWidget.legend.items[0][1]
    assert "font-size" in legend_label.item.toHtml()
    assert "font-weight" in legend_label.item.toHtml()
    panel.close()


def test_backtest_result_tables_and_summary_color_signed_values():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _review_host()
    service = _Service(
        trades=[_trade(1, 2), _loss_trade(3, 4)],
        equity_points=2,
    )
    panel = BacktestPanel(host, controller=BacktestController(service=service))

    panel.run_backtest()
    panel.apply_theme(LIGHT_THEME)

    assert hasattr(panel, "summaryWidget")
    assert panel.summaryWidget.table.rowCount() > 0
    assert panel.resultText.toPlainText()
    assert _item_color(panel.tradeResultTable.item(0, 7)) == QtGui.QColor(
        LIGHT_THEME["success"]
    )
    assert _item_color(panel.tradeResultTable.item(1, 7)) == QtGui.QColor(
        LIGHT_THEME["danger"]
    )
    assert _item_color(panel.tradeResultTable.item(0, 8)) == QtGui.QColor(
        LIGHT_THEME["success"]
    )
    assert _item_color(panel.tradeResultTable.item(1, 8)) == QtGui.QColor(
        LIGHT_THEME["danger"]
    )
    assert _item_color(panel.equityResultTable.item(0, 2)) == QtGui.QColor(
        LIGHT_THEME["text_secondary"]
    )
    summary_rows = {
        panel.summaryWidget.table.item(row, 0).data(QtCore.Qt.UserRole):
        panel.summaryWidget.table.item(row, 1)
        for row in range(panel.summaryWidget.table.rowCount())
    }
    assert _item_color(summary_rows["avg_return"]) == QtGui.QColor(LIGHT_THEME["success"])
    assert _item_color(summary_rows["total_return"]) == QtGui.QColor(LIGHT_THEME["danger"])
    assert _item_color(summary_rows["max_drawdown"]) == QtGui.QColor(LIGHT_THEME["danger"])
    panel.close()


def test_backtest_trade_review_expands_jump_window_for_long_trades():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _review_host_with_bars(260)
    panel = BacktestPanel(
        host,
        controller=BacktestController(service=_Service(trades=[_trade(30, 225)])),
    )

    panel.run_backtest()

    review = panel.tradeReviewWidget
    selected_trade = review.current_trade()
    x_range = review.pricePlot.getPlotItem().vb.viewRange()[0]
    assert review.visible_bar_window() == (10, 245)
    assert x_range[0] < selected_trade.entry_x < x_range[1]
    assert x_range[0] < selected_trade.exit_x < x_range[1]
    panel.close()


def test_backtest_panel_keeps_strategy_curve_when_random_baseline_is_partial():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _Host()
    panel = BacktestPanel(
        host,
        controller=BacktestController(
            service=_Service(
                with_trade=True,
                with_random_baseline=True,
                random_status="partial",
                equity_points=2,
            )
        ),
    )

    panel.run_backtest()

    _strategy_x, strategy_y = panel.equityCurveWidget.strategyCurve.getData()
    _random_x, random_y = panel.equityCurveWidget.randomBaselineCurve.getData()
    assert list(strategy_y) == [10000, 10010]
    assert random_y is None or len(random_y) == 0
    assert panel.equityCurveWidget.randomBaselineCurve.isVisible() is False
    assert panel.equityCurveWidget.initialEquityLine.value() == 10000
    assert "random baseline partial" in panel.resultText.toPlainText()
    panel.close()


def test_backtest_equity_curve_theme_updates_chart_and_series_colors():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _Host()
    panel = BacktestPanel(
        host,
        controller=BacktestController(
            service=_Service(
                with_trade=True,
                with_random_baseline=True,
                equity_points=2,
            )
        ),
    )

    panel.run_backtest()
    panel.apply_theme(LIGHT_THEME)

    plot_item = panel.equityCurveWidget.plot.getPlotItem()
    assert panel.equityCurveWidget.plot.backgroundBrush().color() == QtGui.QColor(
        LIGHT_THEME["chart_bg"]
    )
    assert plot_item.getAxis("left").pen().color() == QtGui.QColor(
        LIGHT_THEME["chart_axis"]
    )
    assert panel.equityCurveWidget.strategyCurve.opts["pen"].color() == QtGui.QColor(
        LIGHT_THEME["success"]
    )
    assert panel.equityCurveWidget.randomBaselineCurve.opts["pen"].color() == QtGui.QColor(
        LIGHT_THEME["info"]
    )
    assert panel.equityCurveWidget.initialEquityLine.pen.color() == QtGui.QColor(
        LIGHT_THEME["text_tertiary"]
    )
    assert LIGHT_THEME["text_secondary"] in panel.equityCurveWidget.stateLabel.styleSheet()
    panel.close()


def test_backtest_panel_shows_missing_analysis_error_and_trade_rows():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _Host()
    panel = BacktestPanel(host, controller=BacktestController(service=_Service(with_trade=True)))

    panel.apply_analysis_params()
    assert "No analysis candidate parameters" in panel.resultText.toPlainText()

    panel.run_backtest()
    assert panel.tradeResultTable.rowCount() == 1
    assert panel.tradeResultTable.item(0, 6).text() == "Long"
    panel.close()


def test_backtest_panel_default_range_includes_last_loaded_bar():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _Host()
    host.df = pd.DataFrame(
        {
            "open_time_bjt": pd.date_range(
                "2026-01-01 09:00",
                periods=3,
                freq="5min",
                tz="Asia/Shanghai",
            )
        }
    )
    panel = BacktestPanel(host, controller=BacktestController(service=_Service()))

    values = panel.collect_form_values()

    assert pd.Timestamp(values["backtest_end"]) > host.df["open_time_bjt"].iloc[-1].tz_localize(None)
    panel.close()


def test_backtest_panel_can_apply_current_analysis_workspace_candidate():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _Host()
    host._analysis_workspace = SimpleNamespace(
        selected_candidate_rule_params=lambda: {
            "drop_pct_threshold": 0.06,
            "volume_spike_threshold": 2.5,
        }
    )
    panel = BacktestPanel(host, controller=BacktestController(service=_Service()))

    panel.apply_analysis_params()

    assert panel.minDropSpin.value() == 0.06
    assert panel.volumeSpikeSpin.value() == 2.5
    panel.close()


def test_backtest_panel_applies_strategy_spec_without_running_backtest():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _Host()
    service = _Service()
    panel = BacktestPanel(host, controller=BacktestController(service=service))
    spec = StrategySpec.from_dict(
        {
            "schema_version": "strategy_spec_v1",
            "provenance": {
                "source": "decision_research",
                "setup_version_id": "setup-version-1",
                "research_snapshot_id": "snapshot-abc",
                "decision_mode": "entry_research",
                "formula_version": "decision-research-v1",
                "feature_version": "features-v1",
                "application_version": "1.6.0",
                "random_seed": 42,
                "maturity": "EXPLORATORY_HYPOTHESIS",
                "warnings": [],
            },
            "market": {
                "symbol": "BTCUSDT",
                "interval": "5m",
                "data_start_utc_ms": 1_700_000_000_000,
                "data_end_utc_ms": 1_700_086_400_000,
            },
            "entry": {"rule": {"all": [{"feature": "volume_ratio_20", "op": ">=", "value": 1.8}]}},
            "exit": {
                "mode": "tp_sl_timeout",
                "take_profit_pct": 0.04,
                "stop_loss_pct": 0.02,
                "max_holding_bars": 30,
            },
            "position": {
                "direction": "long_only",
                "allow_overlap_positions": False,
                "cooldown_bars": 5,
                "notional_per_trade": 3000.0,
                "fee_bps": 6.0,
                "slippage_bps": 1.25,
            },
        }
    )

    panel.apply_strategy_spec(spec)

    assert panel.symbolEdit.text() == "BTCUSDT"
    assert panel.intervalCombo.currentText() == "5m"
    assert panel.takeProfitParamSpin.value() == 0.04
    assert panel.stopLossParamSpin.value() == 0.02
    assert panel.maxHoldingBarsSpin.value() == 30
    assert panel.notionalParamSpin.value() == 3000.0
    assert panel.feeParamSpin.value() == 6.0
    assert panel.slippageParamSpin.value() == 1.25
    assert panel._strategy_spec_source["provenance"]["research_snapshot_id"] == "snapshot-abc"
    assert service.calls == []
    panel.close()


def test_backtest_panel_exports_service_result_with_strategy_spec_and_random_baseline(
    tmp_path, monkeypatch
):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _review_host()
    service = _Service(
        with_trade=True,
        with_random_baseline=True,
        equity_points=2,
    )
    panel = BacktestPanel(host, controller=BacktestController(service=service))
    spec = StrategySpec.from_dict(
        {
            "schema_version": "strategy_spec_v1",
            "provenance": {
                "source": "decision_research",
                "setup_version_id": "setup-version-1",
                "research_snapshot_id": "snapshot-export",
                "decision_mode": "entry_research",
                "formula_version": "decision-research-v1",
                "feature_version": "features-v1",
                "application_version": "1.6.0",
                "random_seed": 42,
                "maturity": "EXPLORATORY_HYPOTHESIS",
                "warnings": [],
            },
            "market": {
                "symbol": "BTCUSDT",
                "interval": "5m",
                "data_start_utc_ms": 1_700_000_000_000,
                "data_end_utc_ms": 1_700_086_400_000,
            },
            "entry": {"rule": {"all": [{"feature": "volume_ratio_20", "op": ">=", "value": 1.8}]}},
            "exit": {
                "mode": "tp_sl_timeout",
                "take_profit_pct": 0.04,
                "stop_loss_pct": 0.02,
                "max_holding_bars": 30,
            },
            "position": {
                "direction": "long_only",
                "allow_overlap_positions": False,
                "cooldown_bars": 5,
                "notional_per_trade": 3000.0,
                "fee_bps": 6.0,
                "slippage_bps": 1.25,
            },
        }
    )
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getExistingDirectory",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    try:
        panel.apply_strategy_spec(spec)
        assert service.calls == []

        panel.run_backtest()
        panel.export_result()

        assert (tmp_path / "backtest_trades.csv").exists()
        assert (tmp_path / "backtest_equity_curve.csv").exists()
        assert (tmp_path / "random_baseline_median_equity_curve.csv").exists()
        assert (tmp_path / "random_baseline_summary.json").exists()
        strategy_spec = (tmp_path / "strategy_spec_v1.json").read_text(encoding="utf-8")
        assert "snapshot-export" in strategy_spec
        assert "run a backtest first" not in panel.resultText.toPlainText()
    finally:
        panel.close()
        host.close()
        app.processEvents()


def test_backtest_panel_does_not_export_failed_service_result(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _review_host()
    panel = BacktestPanel(host, controller=BacktestController(service=_FailingService()))
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getExistingDirectory",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    try:
        panel.run_backtest()
        panel.export_result()

        assert not (tmp_path / "backtest_trades.csv").exists()
        assert "Run a backtest first" in panel.resultText.toPlainText()
    finally:
        panel.close()
        host.close()
        app.processEvents()


def test_backtest_panel_rejects_market_selection_that_does_not_match_loaded_data():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _Host()
    service = _Service()
    panel = BacktestPanel(host, controller=BacktestController(service=service))
    panel.symbolEdit.setText("ETHUSDT")

    panel.run_backtest()

    assert service.calls == []
    assert "does not match the loaded K-line data" in panel.resultText.toPlainText()
    panel.close()


def test_backtest_value_inputs_do_not_change_on_wheel():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _Host()
    panel = BacktestPanel(host, controller=BacktestController(service=_Service()))
    controls = (
        (panel.backtestStartEdit, panel.backtestStartEdit.dateTime),
        (panel.backtestEndEdit, panel.backtestEndEdit.dateTime),
        (panel.trendLookbackSpin, panel.trendLookbackSpin.value),
        (panel.minDropSpin, panel.minDropSpin.value),
        (panel.fastSpin, panel.fastSpin.value),
        (panel.stopSpin, panel.stopSpin.value),
    )

    before = [getter() for _widget, getter in controls]
    for widget, _getter in controls:
        _send_wheel(widget)

    assert [getter() for _widget, getter in controls] == before
    panel.close()
    host.close()
    app.processEvents()
