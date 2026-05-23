from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from PySide6 import QtWidgets

from app_i18n import tr
from backtesting.engine import run_backtest
from backtesting.export import export_backtest_result
from backtesting.optimization import grid_search, walk_forward_grid_search
from backtesting.strategies import FeatureRuleLongStrategy, MovingAverageCrossStrategy, load_candidate_rule
from backtesting.types import BacktestConfig
from ui_style import style_primary_button, style_secondary_button


class BacktestPanel(QtWidgets.QWidget):
    def __init__(self, app_window, parent=None):
        super().__init__(parent)
        self.app_window = app_window
        self.last_result = None
        self.last_scan = pd.DataFrame()
        self.last_walk_forward = None
        self.loaded_rule_conditions = None
        self.loaded_rule_path = ""
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()

        self.strategyBox = QtWidgets.QComboBox()
        self.strategyBox.addItems(["MA Cross", "Feature Rule Long"])
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
        self.btnImportRule.setStyleSheet(style_secondary_button())

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
        self.btnRun.setStyleSheet(style_primary_button())
        self.btnScan.setStyleSheet(style_secondary_button())
        self.btnWalkForward.setStyleSheet(style_secondary_button())
        self.btnExport.setStyleSheet(style_secondary_button())
        button_row.addWidget(self.btnRun)
        button_row.addWidget(self.btnScan)
        button_row.addWidget(self.btnWalkForward)
        button_row.addWidget(self.btnExport)
        layout.addLayout(button_row)

        self.resultText = QtWidgets.QPlainTextEdit()
        self.resultText.setReadOnly(True)
        self.resultText.setPlainText("Backtest results are for research only and do not represent live trading returns.")
        layout.addWidget(self.resultText, stretch=1)

        self.btnImportRule.clicked.connect(self.import_candidate_rule)
        self.btnRun.clicked.connect(self.run_backtest)
        self.btnScan.clicked.connect(self.run_scan)
        self.btnWalkForward.clicked.connect(self.run_walk_forward)
        self.btnExport.clicked.connect(self.export_result)
        self.retranslate_ui()

    def _language(self) -> str:
        return str(getattr(self.app_window, "current_language", "zh_CN") or "zh_CN")

    def retranslate_ui(self):
        language = self._language()
        self.btnRun.setText(tr("run_backtest", language))
        self.btnScan.setText(tr("run_parameter_scan", language))
        self.btnWalkForward.setText(tr("run_walk_forward", language))
        self.btnExport.setText(tr("export_session", language))

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
            self.strategyBox.setCurrentText("Feature Rule Long")
            self.resultText.setPlainText(f"Imported rule {self.ruleIndexSpin.value()} from candidate_rules.csv")
        except Exception as exc:
            self.resultText.setPlainText(f"Candidate rule import failed: {type(exc).__name__}: {exc}")

    def run_backtest(self):
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
