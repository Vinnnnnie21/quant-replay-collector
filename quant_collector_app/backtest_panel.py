from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from PySide6 import QtCore, QtWidgets

try:
    from app_i18n import tr
    from backtesting.engine import run_backtest
    from backtesting.export import export_backtest_result
    from backtesting.optimization import grid_search, walk_forward_grid_search
    from backtesting.strategies import FeatureRuleLongStrategy, MovingAverageCrossStrategy, load_candidate_rule
    from backtesting.types import BacktestConfig
    from controllers.backtest_controller import BacktestController
    from presenters.backtest_presenter import (
        COMPARISON_COLUMNS,
        EQUITY_COLUMNS,
        TRADE_COLUMNS,
        comparison_rows,
        equity_rows,
        format_errors,
        format_summary,
        trade_rows,
    )
except ImportError:  # pragma: no cover - package import path
    from .app_i18n import tr
    from .backtesting.engine import run_backtest
    from .backtesting.export import export_backtest_result
    from .backtesting.optimization import grid_search, walk_forward_grid_search
    from .backtesting.strategies import FeatureRuleLongStrategy, MovingAverageCrossStrategy, load_candidate_rule
    from .backtesting.types import BacktestConfig
    from .controllers.backtest_controller import BacktestController
    from .presenters.backtest_presenter import (
        COMPARISON_COLUMNS,
        EQUITY_COLUMNS,
        TRADE_COLUMNS,
        comparison_rows,
        equity_rows,
        format_errors,
        format_summary,
        trade_rows,
    )


class BacktestPanel(QtWidgets.QWidget):
    def __init__(self, app_window, parent=None, controller: BacktestController | None = None):
        super().__init__(parent)
        self.app_window = app_window
        self.controller = controller or BacktestController()
        self.last_result = None
        self.last_service_result = None
        self.last_scan = pd.DataFrame()
        self.last_walk_forward = None
        self.loaded_rule_conditions = None
        self.loaded_rule_path = ""
        self._analysis_params_source: dict[str, Any] | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        research_form = QtWidgets.QFormLayout()

        self.symbolEdit = QtWidgets.QLineEdit()
        self.intervalCombo = QtWidgets.QComboBox()
        self.intervalCombo.setEditable(True)
        self.intervalCombo.addItems(["1m", "5m", "15m", "1h", "4h"])
        self.backtestStartEdit = QtWidgets.QDateTimeEdit()
        self.backtestEndEdit = QtWidgets.QDateTimeEdit()
        for widget in (self.backtestStartEdit, self.backtestEndEdit):
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("yyyy-MM-dd HH:mm:ss")

        self.directionBox = QtWidgets.QComboBox()
        self.directionBox.addItem("long_only")
        self.trendLookbackSpin = self._integer_spin(1, 10000)
        self.minDropSpin = self._fraction_spin()
        self.volumeSpikeSpin = self._number_spin(0.01, 100.0, 4)
        self.lowerShadowSpin = self._fraction_spin()
        self.bullishNextCandleSpin = self._fraction_spin()
        self.takeProfitParamSpin = self._fraction_spin()
        self.stopLossParamSpin = self._fraction_spin()
        self.maxHoldingBarsSpin = self._integer_spin(1, 100000)
        self.feeParamSpin = self._number_spin(0.0, 10000.0, 4)
        self.slippageParamSpin = self._number_spin(0.0, 10000.0, 4)
        self.notionalParamSpin = self._number_spin(0.01, 1_000_000_000.0, 2)

        research_form.addRow("symbol", self.symbolEdit)
        research_form.addRow("interval", self.intervalCombo)
        research_form.addRow("backtest_start", self.backtestStartEdit)
        research_form.addRow("backtest_end", self.backtestEndEdit)
        research_form.addRow("direction", self.directionBox)
        research_form.addRow("trend_lookback", self.trendLookbackSpin)
        research_form.addRow("min_drop_pct", self.minDropSpin)
        research_form.addRow("volume_spike_multiple", self.volumeSpikeSpin)
        research_form.addRow("lower_shadow_min_ratio", self.lowerShadowSpin)
        research_form.addRow("bullish_next_candle_min_body_ratio", self.bullishNextCandleSpin)
        research_form.addRow("take_profit_pct", self.takeProfitParamSpin)
        research_form.addRow("stop_loss_pct", self.stopLossParamSpin)
        research_form.addRow("max_holding_bars", self.maxHoldingBarsSpin)
        research_form.addRow("fee_bps", self.feeParamSpin)
        research_form.addRow("slippage_bps", self.slippageParamSpin)
        research_form.addRow("notional_per_trade", self.notionalParamSpin)
        layout.addLayout(research_form)

        param_button_row = QtWidgets.QHBoxLayout()
        self.btnLoadDefaults = QtWidgets.QPushButton("Load default params")
        self.btnApplyAnalysis = QtWidgets.QPushButton("Apply params from analysis")
        self.btnReset = QtWidgets.QPushButton("Reset")
        for button in (self.btnLoadDefaults, self.btnApplyAnalysis, self.btnReset):
            button.setProperty("role", "secondaryButton")
            param_button_row.addWidget(button)
        layout.addLayout(param_button_row)

        form = QtWidgets.QFormLayout()

        self.strategyBox = QtWidgets.QComboBox()
        self.strategyBox.addItems(["Deep V Reversal", "MA Cross", "Feature Rule Long"])
        self.fastSpin = QtWidgets.QSpinBox()
        self.fastSpin.setRange(1, 500)
        self.fastSpin.setValue(5)
        self.slowSpin = QtWidgets.QSpinBox()
        self.slowSpin.setRange(2, 1000)
        self.slowSpin.setValue(20)
        self.exitBarsSpin = QtWidgets.QSpinBox()
        self.exitBarsSpin.setRange(1, 1000)
        self.exitBarsSpin.setValue(10)
        self.stopSpin = QtWidgets.QDoubleSpinBox()
        self.stopSpin.setRange(0, 100)
        self.stopSpin.setDecimals(2)
        self.takeSpin = QtWidgets.QDoubleSpinBox()
        self.takeSpin.setRange(0, 100)
        self.takeSpin.setDecimals(2)
        self.ruleIndexSpin = QtWidgets.QSpinBox()
        self.ruleIndexSpin.setRange(0, 100000)
        self.ruleIndexSpin.setValue(0)
        self.btnImportRule = QtWidgets.QPushButton("Import candidate rule")
        self.btnImportRule.setProperty("role", "secondaryButton")

        form.addRow("Strategy", self.strategyBox)
        form.addRow("fast_window", self.fastSpin)
        form.addRow("slow_window", self.slowSpin)
        form.addRow("exit_bars", self.exitBarsSpin)
        form.addRow("stop_loss_pct", self.stopSpin)
        form.addRow("take_profit_pct", self.takeSpin)
        form.addRow("rule_index", self.ruleIndexSpin)
        form.addRow("candidate_rules.csv", self.btnImportRule)
        layout.addLayout(form)

        button_row = QtWidgets.QHBoxLayout()
        self.btnRun = QtWidgets.QPushButton("Run backtest")
        self.btnScan = QtWidgets.QPushButton("Run parameter scan")
        self.btnWalkForward = QtWidgets.QPushButton("Run walk-forward")
        self.btnExport = QtWidgets.QPushButton("Export backtest")
        self.btnRun.setProperty("role", "primaryButton")
        self.btnScan.setProperty("role", "secondaryButton")
        self.btnWalkForward.setProperty("role", "secondaryButton")
        self.btnExport.setProperty("role", "secondaryButton")
        button_row.addWidget(self.btnRun)
        button_row.addWidget(self.btnScan)
        button_row.addWidget(self.btnWalkForward)
        button_row.addWidget(self.btnExport)
        layout.addLayout(button_row)

        self.resultText = QtWidgets.QPlainTextEdit()
        self.resultText.setReadOnly(True)
        self.resultText.setPlainText("Backtest results are for research only and do not represent live trading returns.")
        layout.addWidget(self.resultText)

        result_tabs = QtWidgets.QTabWidget()
        self.tradeResultTable = self._result_table(TRADE_COLUMNS)
        self.equityResultTable = self._result_table(EQUITY_COLUMNS)
        self.comparisonTable = self._result_table(("metric", "value"))
        result_tabs.addTab(self.tradeResultTable, "Trades")
        result_tabs.addTab(self.equityResultTable, "Equity")
        result_tabs.addTab(self.comparisonTable, "Manual vs Rule")
        layout.addWidget(result_tabs, stretch=1)

        self.btnLoadDefaults.clicked.connect(self.load_default_params)
        self.btnApplyAnalysis.clicked.connect(self.apply_analysis_params)
        self.btnReset.clicked.connect(self.reset_form)
        self.btnImportRule.clicked.connect(self.import_candidate_rule)
        self.btnRun.clicked.connect(self.run_backtest)
        self.btnScan.clicked.connect(self.run_scan)
        self.btnWalkForward.clicked.connect(self.run_walk_forward)
        self.btnExport.clicked.connect(self.export_result)
        self.reset_form()
        self.retranslate_ui()

    @staticmethod
    def _integer_spin(minimum: int, maximum: int) -> QtWidgets.QSpinBox:
        widget = QtWidgets.QSpinBox()
        widget.setRange(minimum, maximum)
        return widget

    @staticmethod
    def _number_spin(minimum: float, maximum: float, decimals: int) -> QtWidgets.QDoubleSpinBox:
        widget = QtWidgets.QDoubleSpinBox()
        widget.setRange(minimum, maximum)
        widget.setDecimals(decimals)
        widget.setSingleStep(0.01)
        return widget

    @classmethod
    def _fraction_spin(cls) -> QtWidgets.QDoubleSpinBox:
        return cls._number_spin(0.000001, 1.0, 6)

    @staticmethod
    def _result_table(columns: tuple[str, ...]) -> QtWidgets.QTableWidget:
        table = QtWidgets.QTableWidget()
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(list(columns))
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        return table

    def collect_form_values(self) -> dict[str, Any]:
        values = self.controller.default_form_values()
        values.update(
            {
                "symbol": self.symbolEdit.text().strip().upper(),
                "interval": self.intervalCombo.currentText().strip(),
                "backtest_start": self.backtestStartEdit.dateTime().toString(QtCore.Qt.ISODate),
                "backtest_end": self.backtestEndEdit.dateTime().toString(QtCore.Qt.ISODate),
                "direction": self.directionBox.currentText(),
                "trend_lookback": self.trendLookbackSpin.value(),
                "min_drop_pct": self.minDropSpin.value(),
                "volume_spike_multiple": self.volumeSpikeSpin.value(),
                "lower_shadow_min_ratio": self.lowerShadowSpin.value(),
                "bullish_next_candle_min_body_ratio": self.bullishNextCandleSpin.value(),
                "take_profit_pct": self.takeProfitParamSpin.value(),
                "stop_loss_pct": self.stopLossParamSpin.value(),
                "max_holding_bars": self.maxHoldingBarsSpin.value(),
                "fee_bps": self.feeParamSpin.value(),
                "slippage_bps": self.slippageParamSpin.value(),
                "notional_per_trade": self.notionalParamSpin.value(),
            }
        )
        return values

    def load_default_params(self) -> None:
        current = self.collect_form_values()
        defaults = self.controller.default_form_values()
        defaults.update(
            {
                "symbol": current["symbol"],
                "interval": current["interval"],
                "backtest_start": current["backtest_start"],
                "backtest_end": current["backtest_end"],
            }
        )
        self._set_form_values(defaults)

    def reset_form(self) -> None:
        values = self.controller.default_form_values()
        values.update(self._host_market_values())
        self._set_form_values(values)
        self.resultText.setPlainText(
            "Backtest results are for research only and do not represent live trading returns."
        )
        for table in (self.tradeResultTable, self.equityResultTable, self.comparisonTable):
            table.setRowCount(0)

    def set_analysis_params_source(self, value: dict[str, Any] | None) -> None:
        self._analysis_params_source = dict(value) if value else None

    def apply_analysis_params(self) -> None:
        try:
            source = self._available_analysis_params()
            values = self.controller.apply_analysis_params(
                source,
                current_values=self.collect_form_values(),
            )
            self._set_form_values(values)
            self.resultText.setPlainText(
                "Applied analysis candidate parameters. Review them before running the historical simulation."
            )
        except Exception as exc:
            self.resultText.setPlainText(format_errors([str(exc)]))

    def _available_analysis_params(self) -> dict[str, Any] | None:
        if self._analysis_params_source:
            return dict(self._analysis_params_source)
        if self.loaded_rule_conditions:
            return {"conditions_json": list(self.loaded_rule_conditions)}
        for name in ("analysis_params_source", "_analysis_params_source"):
            value = getattr(self.app_window, name, None)
            if isinstance(value, dict) and value:
                return dict(value)
        workspace = getattr(self.app_window, "_analysis_workspace", None)
        selected_candidate = getattr(workspace, "selected_candidate_rule_params", None)
        if callable(selected_candidate):
            value = selected_candidate()
            if isinstance(value, dict) and value:
                return dict(value)
        return None

    def _host_market_values(self) -> dict[str, Any]:
        symbol = (
            self.app_window.symbolBox.currentText()
            if hasattr(self.app_window, "symbolBox")
            else ""
        )
        interval = (
            self.app_window.intervalBox.currentText()
            if hasattr(self.app_window, "intervalBox")
            else ""
        )
        frame = getattr(self.app_window, "df", pd.DataFrame())
        start = pd.Timestamp.now().floor("D")
        end = start + pd.Timedelta(days=1)
        if isinstance(frame, pd.DataFrame) and not frame.empty and "open_time_bjt" in frame.columns:
            timestamps = pd.to_datetime(frame["open_time_bjt"], errors="coerce").dropna()
            if not timestamps.empty:
                start = timestamps.iloc[0]
                bar_span = (
                    timestamps.iloc[-1] - timestamps.iloc[-2]
                    if len(timestamps) >= 2
                    else pd.Timedelta(minutes=1)
                )
                if bar_span <= pd.Timedelta(0):
                    bar_span = pd.Timedelta(minutes=1)
                end = timestamps.iloc[-1] + bar_span
        return {
            "symbol": str(symbol or "").strip().upper(),
            "interval": str(interval or "").strip(),
            "backtest_start": start,
            "backtest_end": end,
        }

    def _set_form_values(self, values: dict[str, Any]) -> None:
        self.symbolEdit.setText(str(values.get("symbol") or ""))
        interval = str(values.get("interval") or "")
        if self.intervalCombo.findText(interval) < 0 and interval:
            self.intervalCombo.addItem(interval)
        self.intervalCombo.setCurrentText(interval)
        self._set_datetime(self.backtestStartEdit, values.get("backtest_start"))
        self._set_datetime(self.backtestEndEdit, values.get("backtest_end"))
        self.directionBox.setCurrentText(str(values.get("direction") or "long_only"))
        self.trendLookbackSpin.setValue(int(values.get("trend_lookback", 20)))
        self.minDropSpin.setValue(float(values.get("min_drop_pct", 0.02)))
        self.volumeSpikeSpin.setValue(float(values.get("volume_spike_multiple", 2.0)))
        self.lowerShadowSpin.setValue(float(values.get("lower_shadow_min_ratio", 0.45)))
        self.bullishNextCandleSpin.setValue(float(values.get("bullish_next_candle_min_body_ratio", 0.6)))
        self.takeProfitParamSpin.setValue(float(values.get("take_profit_pct", 0.03)))
        self.stopLossParamSpin.setValue(float(values.get("stop_loss_pct", 0.015)))
        self.maxHoldingBarsSpin.setValue(int(values.get("max_holding_bars", 20)))
        self.feeParamSpin.setValue(float(values.get("fee_bps", 4.0)))
        self.slippageParamSpin.setValue(float(values.get("slippage_bps", 2.0)))
        self.notionalParamSpin.setValue(float(values.get("notional_per_trade", 1000.0)))

    @staticmethod
    def _set_datetime(widget: QtWidgets.QDateTimeEdit, value: Any) -> None:
        try:
            timestamp = pd.Timestamp(value)
        except (TypeError, ValueError):
            return
        if pd.isna(timestamp):
            return
        python_value = timestamp.to_pydatetime().replace(tzinfo=None)
        widget.setDateTime(QtCore.QDateTime(python_value))

    def _language(self) -> str:
        return str(getattr(self.app_window, "current_language", "zh_CN") or "zh_CN")

    def retranslate_ui(self):
        language = self._language()
        self.btnRun.setText(tr("run_backtest", language))
        self.btnScan.setText(tr("run_parameter_scan", language))
        self.btnWalkForward.setText(tr("run_walk_forward", language))
        self.btnExport.setText(tr("export_session", language))
        self.btnLoadDefaults.setText("加载默认参数" if language == "zh_CN" else "Load default params")
        self.btnApplyAnalysis.setText("应用分析候选参数" if language == "zh_CN" else "Apply params from analysis")
        self.btnReset.setText("重置" if language == "zh_CN" else "Reset")

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def _df(self) -> pd.DataFrame:
        df = getattr(self.app_window, "df", pd.DataFrame())
        data = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
        if data.empty:
            return data
        if "pre_ret_20" not in data.columns and "close" in data.columns:
            close = pd.to_numeric(data["close"], errors="coerce")
            data["pre_ret_20"] = close / close.shift(20) - 1.0
        return data

    def _config(self) -> BacktestConfig:
        app = self.app_window
        fill_mode = app._fill_mode_value() if hasattr(app, "_fill_mode_value") else "CLOSE"
        return BacktestConfig(
            initial_equity=self._safe_float(getattr(app, "initialEquitySpin").value(), 10000.0),
            notional_quote=self._safe_float(getattr(app, "tradeNotionalSpin").value(), 1000.0),
            fee_bps=self._safe_float(getattr(app, "feeBpsSpin").value(), 4.0),
            slippage_bps=self._safe_float(getattr(app, "slippageBpsSpin").value(), 1.0),
            fill_mode=fill_mode,
            signal_timing="next_open",
            stop_loss_pct=self.stopSpin.value() or None,
            take_profit_pct=self.takeSpin.value() or None,
        )

    def _conditions(self) -> list[dict]:
        return self.loaded_rule_conditions or [{"column": "pre_ret_20", "op": "<=", "value": -0.03}]

    def _strategy(self):
        if self.strategyBox.currentText() == "MA Cross":
            return MovingAverageCrossStrategy(self.fastSpin.value(), self.slowSpin.value(), "LONG_ONLY")
        return FeatureRuleLongStrategy(
            self._conditions(),
            exit_bars=self.exitBarsSpin.value(),
            stop_loss_pct=self.stopSpin.value() or None,
            take_profit_pct=self.takeSpin.value() or None,
        )

    def _strategy_factory_grid(self):
        if self.strategyBox.currentText() == "MA Cross":
            grid = {
                "fast_window": sorted({self.fastSpin.value(), max(1, self.fastSpin.value() // 2), self.fastSpin.value() * 2}),
                "slow_window": sorted({self.slowSpin.value(), max(2, self.slowSpin.value() // 2), self.slowSpin.value() * 2}),
                "direction": ["LONG_ONLY"],
            }
            return MovingAverageCrossStrategy, grid
        grid = {"conditions": [self._conditions()], "exit_bars": [5, self.exitBarsSpin.value(), 20]}
        return FeatureRuleLongStrategy, grid

    def _symbol_interval(self) -> tuple[str, str]:
        app = self.app_window
        symbol = app.symbolBox.currentText() if hasattr(app, "symbolBox") else "UNKNOWN"
        interval = app.intervalBox.currentText() if hasattr(app, "intervalBox") else "1m"
        return symbol, interval

    def _display_metrics(self, metrics: dict):
        keys = ["total_return_pct", "win_rate_pct", "profit_factor", "max_drawdown_pct", "trade_sharpe", "time_sharpe", "closed_trades"]
        lines = ["Backtest results are for research only and do not represent live trading returns.", ""]
        for key in keys:
            lines.append(f"{key}: {metrics.get(key)}")
        self.resultText.setPlainText("\n".join(lines))

    def import_candidate_rule(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select candidate_rules.csv", "", "CSV Files (*.csv)")
        if not path:
            return
        try:
            strategy = load_candidate_rule(path, self.ruleIndexSpin.value())
            self.loaded_rule_conditions = strategy.conditions
            self.loaded_rule_path = path
            self.set_analysis_params_source({"conditions_json": list(strategy.conditions)})
            self.strategyBox.setCurrentText("Feature Rule Long")
            self.resultText.setPlainText(f"Imported rule {self.ruleIndexSpin.value()} from candidate_rules.csv")
        except Exception as exc:
            self.resultText.setPlainText(f"Candidate rule import failed: {type(exc).__name__}: {exc}")

    def run_backtest(self):
        if self.strategyBox.currentText() != "Deep V Reversal":
            self._run_legacy_backtest()
            return
        try:
            result = self.controller.run(
                self.collect_form_values(),
                self._df(),
                manual_trades=getattr(self.app_window, "trades", None),
                loaded_market_key=getattr(self.app_window, "_loaded_market_key", None),
            )
            self.last_service_result = result
            self._apply_service_result(result)
        except Exception as exc:
            self.resultText.setPlainText(format_errors([f"{type(exc).__name__}: {exc}"]))

    def _run_legacy_backtest(self):
        try:
            data = self._df()
            if data.empty:
                self.resultText.setPlainText("No K-line data available for backtest.")
                return
            symbol, interval = self._symbol_interval()
            self.last_result = run_backtest(data, self._strategy(), self._config(), symbol, interval)
            self._display_metrics(self.last_result.metrics)
        except Exception as exc:
            self.resultText.setPlainText(f"Backtest failed: {type(exc).__name__}: {exc}")

    def _apply_service_result(self, result) -> None:
        if not result.success:
            self.resultText.setPlainText(format_errors(result.errors))
            for table in (self.tradeResultTable, self.equityResultTable, self.comparisonTable):
                table.setRowCount(0)
            return
        self.resultText.setPlainText(format_summary(result.summary, warnings=result.warnings))
        self._populate_result_table(self.tradeResultTable, trade_rows(result.trades), TRADE_COLUMNS)
        self._populate_result_table(self.equityResultTable, equity_rows(result.equity_curve), EQUITY_COLUMNS)
        self._populate_result_table(
            self.comparisonTable,
            comparison_rows(result.manual_vs_rule_comparison),
            ("metric", "value"),
        )

    @staticmethod
    def _populate_result_table(
        table: QtWidgets.QTableWidget,
        rows: list[dict[str, Any]],
        columns: tuple[str, ...],
    ) -> None:
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, column in enumerate(columns):
                value = row.get(column)
                text = "" if value is None else str(value)
                table.setItem(row_index, column_index, QtWidgets.QTableWidgetItem(text))
        table.resizeColumnsToContents()

    def run_scan(self):
        try:
            data = self._df()
            if data.empty:
                self.resultText.setPlainText("No K-line data available for parameter scan.")
                return
            symbol, interval = self._symbol_interval()
            factory, grid = self._strategy_factory_grid()
            self.last_scan = grid_search(data, factory, grid, self._config(), symbol, interval)
            top = self.last_scan.sort_values("sharpe", ascending=False, na_position="last").head(10)
            self.resultText.setPlainText(
                "Parameter scan is research-only. In-sample best parameters are not live-trading proof.\n\n"
                + top.to_string(index=False)
            )
        except Exception as exc:
            self.resultText.setPlainText(f"Parameter scan failed: {type(exc).__name__}: {exc}")

    def run_walk_forward(self):
        try:
            data = self._df()
            if data.empty:
                self.resultText.setPlainText("No K-line data available for walk-forward validation.")
                return
            symbol, interval = self._symbol_interval()
            factory, grid = self._strategy_factory_grid()
            self.last_walk_forward = walk_forward_grid_search(data, factory, grid, self._config(), symbol, interval)
            valid = pd.DataFrame(self.last_walk_forward.get("valid_results") or pd.DataFrame())
            valid_top = valid.sort_values("sharpe", ascending=False, na_position="last").head(1) if not valid.empty and "sharpe" in valid.columns else valid.head(1)
            lines = [
                "Walk-forward validation. Test is evaluated once only and must not be used for parameter tuning.",
                "",
                f"selected_params: {self.last_walk_forward.get('selected_params')}",
                f"test_result: {self.last_walk_forward.get('test_result')}",
                f"warnings: {self.last_walk_forward.get('warnings')}",
                "",
                "validation_top:",
                valid_top.to_string(index=False) if not valid_top.empty else "(empty)",
            ]
            self.resultText.setPlainText("\n".join(lines))
        except Exception as exc:
            self.resultText.setPlainText(f"Walk-forward failed: {type(exc).__name__}: {exc}")

    def export_result(self):
        if self.last_result is None:
            self.resultText.setPlainText("Run a backtest first.")
            return
        target = QtWidgets.QFileDialog.getExistingDirectory(self, "Select backtest export directory")
        if not target:
            return
        try:
            out = export_backtest_result(self.last_result, Path(target), self.last_scan, self.last_walk_forward)
            self.resultText.appendPlainText(f"\nExported: {out}")
        except Exception as exc:
            self.resultText.appendPlainText(f"\nExport failed: {type(exc).__name__}: {exc}")
