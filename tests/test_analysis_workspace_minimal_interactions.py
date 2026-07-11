from __future__ import annotations

import pytest
import pandas as pd


QtWidgets = pytest.importorskip("PySide6.QtWidgets")
QtCore = pytest.importorskip("PySide6.QtCore")
from analysis_workspace import AnalysisWorkspace
from ui_style import COLORS


class Host(QtWidgets.QWidget):
    current_language = "zh_CN"


class PerformanceHost(QtWidgets.QWidget):
    current_language = "zh_CN"
    session_id = "sess_perf"

    def __init__(self) -> None:
        super().__init__()
        self.trades = [
            {
                "trade_id": "trd_win",
                "side": "LONG",
                "status": "CLOSED",
                "net_return_pct": 2.0,
                "net_pnl_quote": 20.0,
                "exit_reason": "TAKE_PROFIT",
                "exit_bar_index": 1,
            },
            {
                "trade_id": "trd_open",
                "side": "LONG",
                "status": "OPEN",
                "entry_fill_price": 100.0,
                "notional_quote": 500.0,
                "entry_bar_index": 1,
            },
        ]
        self.df = pd.DataFrame(
            [
                {"bar_index": 0, "close": 100.0, "open_time_bjt": "2026-01-01T00:00:00+08:00"},
                {"bar_index": 1, "close": 104.0, "open_time_bjt": "2026-01-01T00:01:00+08:00"},
            ]
        )
        self.initialEquitySpin = type("Spin", (), {"value": lambda _self: 1000.0})()
        self.tradeNotionalSpin = type("Spin", (), {"value": lambda _self: 500.0})()

    def _current_equity_rows(self):
        return [
            {"sequence_no": 1, "equity_after": 1000.0, "equity_return_pct": 0.0, "drawdown_pct": 0.0},
            {"sequence_no": 2, "equity_after": 1040.0, "equity_return_pct": 4.0, "drawdown_pct": 0.0},
        ]


def test_performance_workspace_shows_account_summary_curve_and_trade_pnl():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    dialog = AnalysisWorkspace(host)

    dialog.refresh()

    assert dialog.performanceMetricLabels["total_return"].text() == "4.00%"
    assert dialog.performanceMetricLabels["total_pnl"].text() == "40.00"
    assert dialog.performanceTradeFilter.currentData() == "closed"
    assert dialog.tradePnlTable.rowCount() == 1
    assert dialog.tradePnlTable.item(0, 0).data(QtCore.Qt.UserRole) == "trd_win"
    assert dialog.tradePnlTable.item(0, 7).text() == "20.00"
    assert dialog.tradePnlTable.item(0, 8).text() == "2.00%"
    assert dialog.equityCurveData == [1000.0, 1040.0]

    dialog.close()
    host.close()
    app.processEvents()


def test_performance_workspace_exposes_funds_management_controls():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    dialog = AnalysisWorkspace(host)

    try:
        assert {
            "current_equity",
            "total_pnl",
            "total_return",
            "unrealized_pnl",
            "realized_pnl",
            "win_rate",
            "payoff",
            "sharpe",
            "max_drawdown",
            "trade_count",
        }.issubset(dialog.performanceMetricLabels)
        assert dialog.performanceCurveMode.count() == 2
        assert dialog.equityCurvePlot.minimumHeight() >= 280
        assert dialog.tradePnlTable.columnCount() == 13
        assert dialog.tradePnlTable.minimumHeight() >= 240
        assert dialog.performanceTradeFilter.count() >= 6
        assert dialog.performanceSideFilter.count() >= 3
        assert dialog.performanceDistributionLabels
        assert dialog.performanceHistogram is not None
        assert "已实现盈亏金额" in dialog.performanceHistogramDefinition.text()
        assert "交易笔数" in dialog.performanceHistogramDefinition.text()
        assert not hasattr(dialog, "performanceTabs")
    finally:
        dialog.close()
        host.close()
        app.processEvents()


def test_performance_trade_pnl_and_return_cells_use_signed_colors():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    host.trades.append(
        {
            "trade_id": "trd_loss",
            "side": "SHORT",
            "status": "CLOSED",
            "net_return_pct": -1.5,
            "net_pnl_quote": -7.5,
            "exit_reason": "STOP_LOSS",
            "exit_bar_index": 1,
        }
    )
    dialog = AnalysisWorkspace(host)

    try:
        dialog.refresh()
        rows = {
            dialog.tradePnlTable.item(row, 0).data(QtCore.Qt.UserRole): row
            for row in range(dialog.tradePnlTable.rowCount())
        }
        win_row = rows["trd_win"]
        loss_row = rows["trd_loss"]

        for column in (7, 8):
            assert dialog.tradePnlTable.item(win_row, column).foreground().color().name() == COLORS["success"].lower()
            assert dialog.tradePnlTable.item(loss_row, column).foreground().color().name() == COLORS["danger"].lower()
    finally:
        dialog.close()
        host.close()
        app.processEvents()


def test_performance_curve_trade_marker_selects_matching_trade_row():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    dialog = AnalysisWorkspace(host)

    try:
        dialog.refresh()
        point = next(point for point in dialog.performanceTradeMarkers.points() if point.data() == "trd_win")

        dialog.performanceTradeMarkers.sigClicked.emit(dialog.performanceTradeMarkers, [point], None)
        app.processEvents()

        selected = dialog.tradePnlTable.selectedItems()
        assert selected
        assert dialog.tradePnlTable.item(selected[0].row(), 0).data(QtCore.Qt.UserRole) == "trd_win"
    finally:
        dialog.close()
        host.close()
        app.processEvents()


def test_performance_curve_hover_exposes_equity_and_pnl_breakdown():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    dialog = AnalysisWorkspace(host)

    try:
        dialog.refresh()
        dialog._update_performance_hover(1)

        text = dialog.performanceHoverLabel.text()
        assert "1040.00" in text
        assert "40.00" in text
        assert "20.00" in text
    finally:
        dialog.close()
        host.close()
        app.processEvents()


def test_research_controls_sorting_and_single_symbol_pca_hint():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    dialog = AnalysisWorkspace(Host())

    assert dialog.selectedLabelBox.currentText() == "fwd_ret_10_side_adj"
    assert dialog.selectedLabelBox.findText("hit_tp_1pct_before_sl_1pct") >= 0
    assert dialog.researchEventTable.isSortingEnabled()
    assert dialog.factorIcTable.isSortingEnabled()
    assert dialog.ruleTable.isSortingEnabled()

    dialog.last_time_series_summary = {"factor_model": {"available": False}}
    dialog._populate_time_series_views()
    assert "PCA 因子模型需要多币种收益矩阵" in dialog.tsFactorTable.item(0, 1).text()
    assert dialog.btnRunTimeSeries.text() == "运行时间序列诊断"
    dialog.close()
    app.processEvents()
