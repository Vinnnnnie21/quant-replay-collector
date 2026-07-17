from __future__ import annotations

import pandas as pd
import pytest
from types import SimpleNamespace


QtWidgets = pytest.importorskip("PySide6.QtWidgets")
QtCore = pytest.importorskip("PySide6.QtCore")
QtGui = pytest.importorskip("PySide6.QtGui")

from backtest_panel import BacktestPanel
from controllers.backtest_controller import BacktestController
from services.backtest_service import BacktestServiceResult


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
    def __init__(self, *, with_trade: bool = False) -> None:
        self.calls: list[dict] = []
        self.with_trade = with_trade

    def run(self, config, market_df, **kwargs):
        self.calls.append({"config": config, "market_df": market_df, **kwargs})
        trades = []
        if self.with_trade:
            trades.append(
                {
                    "entry_bar_index": 1,
                    "entry_time": "t1",
                    "entry_price": 100,
                    "exit_bar_index": 2,
                    "exit_time": "t2",
                    "exit_price": 101,
                    "side": "LONG",
                    "return_pct": 1,
                    "pnl": 10,
                    "exit_reason": "take_profit",
                    "holding_bars": 1,
                    "fee": 0,
                    "slippage": 0,
                }
            )
        return BacktestServiceResult(
            success=True,
            summary={"total_trades": len(trades), "closed_trades": len(trades)},
            trades=pd.DataFrame(trades),
            equity_curve=pd.DataFrame([{"bar_index": 1, "time": "t", "equity": 10000, "drawdown": 0}]),
            manual_vs_rule_comparison={
                "manual_trade_count": 1,
                "rule_trade_count": 0,
                "overlap_entry_bars": [],
                "manual_only_bars": [1],
                "rule_only_bars": [],
                "overlap_ratio": 0.0,
            },
            warnings=[
                "Backtest result is for research only and does not represent live trading returns."
            ],
            errors=[],
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
