from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from PySide6 import QtCore, QtGui, QtWidgets

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
        localize_warnings,
        trade_rows,
    )
    from presenters.backtest_result_display import value_tone
    from presenters.formatters import side_label
    from views.backtest_equity_curve_widget import BacktestEquityCurveWidget
    from views.backtest_summary_widget import BacktestSummaryWidget
    from views.backtest_trade_review_widget import BacktestTradeReviewWidget
    from ui_style import normalize_theme_settings
    from views.wheel_guard import install_no_wheel_on_value_inputs
    from views.i18n_bindings import (
        add_combo_item,
        bind_table_headers,
        bind_tab,
        bind_text,
        retranslate_bound_widgets,
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
        localize_warnings,
        trade_rows,
    )
    from .presenters.backtest_result_display import value_tone
    from .presenters.formatters import side_label
    from .views.backtest_equity_curve_widget import BacktestEquityCurveWidget
    from .views.backtest_summary_widget import BacktestSummaryWidget
    from .views.backtest_trade_review_widget import BacktestTradeReviewWidget
    from .ui_style import normalize_theme_settings
    from .views.wheel_guard import install_no_wheel_on_value_inputs
    from .views.i18n_bindings import (
        add_combo_item,
        bind_table_headers,
        bind_tab,
        bind_text,
        retranslate_bound_widgets,
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
        self._strategy_spec_source: dict[str, Any] | None = None
        self._theme_settings = normalize_theme_settings(
            getattr(self.app_window, "theme_settings", None)
        )
        self._build_ui()
        install_no_wheel_on_value_inputs(self)

    def _tr(self, key: str, default: str | None = None) -> str:
        return tr(key, self._language(), default)

    def _form_label(self, key: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel()
        bind_text(label, key, self._tr)
        return label

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
        add_combo_item(
            self.directionBox,
            "backtest.direction.long_only",
            "long_only",
            self._tr,
        )
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

        for key, widget in (
            ("backtest.field.symbol", self.symbolEdit),
            ("backtest.field.interval", self.intervalCombo),
            ("backtest.field.start", self.backtestStartEdit),
            ("backtest.field.end", self.backtestEndEdit),
            ("backtest.field.direction", self.directionBox),
            ("backtest.field.trend_lookback", self.trendLookbackSpin),
            ("backtest.field.min_drop_pct", self.minDropSpin),
            ("backtest.field.volume_spike_multiple", self.volumeSpikeSpin),
            ("backtest.field.lower_shadow_min_ratio", self.lowerShadowSpin),
            ("backtest.field.bullish_next_candle_min_body_ratio", self.bullishNextCandleSpin),
            ("backtest.field.take_profit_pct", self.takeProfitParamSpin),
            ("backtest.field.stop_loss_pct", self.stopLossParamSpin),
            ("backtest.field.max_holding_bars", self.maxHoldingBarsSpin),
            ("backtest.field.fee_bps", self.feeParamSpin),
            ("backtest.field.slippage_bps", self.slippageParamSpin),
            ("backtest.field.notional_per_trade", self.notionalParamSpin),
        ):
            research_form.addRow(self._form_label(key), widget)
        layout.addLayout(research_form)

        param_button_row = QtWidgets.QHBoxLayout()
        self.btnLoadDefaults = QtWidgets.QPushButton()
        self.btnApplyAnalysis = QtWidgets.QPushButton()
        self.btnReset = QtWidgets.QPushButton()
        bind_text(self.btnLoadDefaults, "backtest.load_defaults", self._tr)
        bind_text(self.btnApplyAnalysis, "backtest.apply_analysis", self._tr)
        bind_text(self.btnReset, "backtest.reset", self._tr)
        for button in (self.btnLoadDefaults, self.btnApplyAnalysis, self.btnReset):
            button.setProperty("role", "secondaryButton")
            param_button_row.addWidget(button)
        layout.addLayout(param_button_row)

        form = QtWidgets.QFormLayout()

        self.strategyBox = QtWidgets.QComboBox()
        for key, value in (
            ("backtest.strategy.deep_v", "Deep V Reversal"),
            ("backtest.strategy.ma_cross", "MA Cross"),
            ("backtest.strategy.feature_rule_long", "Feature Rule Long"),
        ):
            add_combo_item(self.strategyBox, key, value, self._tr)
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
        self.btnImportRule = QtWidgets.QPushButton()
        bind_text(self.btnImportRule, "backtest.import_rule", self._tr)
        self.btnImportRule.setProperty("role", "secondaryButton")

        for key, widget in (
            ("backtest.field.strategy", self.strategyBox),
            ("backtest.field.fast_window", self.fastSpin),
            ("backtest.field.slow_window", self.slowSpin),
            ("backtest.field.exit_bars", self.exitBarsSpin),
            ("backtest.field.stop_loss_pct", self.stopSpin),
            ("backtest.field.take_profit_pct", self.takeSpin),
            ("backtest.field.rule_index", self.ruleIndexSpin),
            ("backtest.field.candidate_rules", self.btnImportRule),
        ):
            form.addRow(self._form_label(key), widget)
        layout.addLayout(form)

        button_row = QtWidgets.QHBoxLayout()
        self.btnRun = QtWidgets.QPushButton()
        self.btnScan = QtWidgets.QPushButton()
        self.btnWalkForward = QtWidgets.QPushButton()
        self.btnExport = QtWidgets.QPushButton()
        bind_text(self.btnRun, "run_backtest", self._tr)
        bind_text(self.btnScan, "run_parameter_scan", self._tr)
        bind_text(self.btnWalkForward, "run_walk_forward", self._tr)
        bind_text(self.btnExport, "backtest.export", self._tr)
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
        self.resultText.setPlainText(self._tr("backtest.initial_message"))
        layout.addWidget(self.resultText)

        self.summaryWidget = BacktestSummaryWidget(
            language_provider=self._language,
            parent=self,
        )
        self.summaryWidget.apply_theme(
            getattr(self.app_window, "theme_settings", None)
        )
        layout.addWidget(self.summaryWidget)

        self.equityCurveWidget = BacktestEquityCurveWidget(
            language_provider=self._language,
            parent=self,
        )
        self.equityCurveWidget.apply_theme(
            getattr(self.app_window, "theme_settings", None)
        )
        layout.addWidget(self.equityCurveWidget)

        self.tradeReviewWidget = BacktestTradeReviewWidget(
            language_provider=self._language,
            parent=self,
        )
        self.tradeReviewWidget.apply_theme(
            getattr(self.app_window, "theme_settings", None)
        )
        self.equityCurveWidget.strategyEntryClicked.connect(
            self.tradeReviewWidget.select_trade
        )
        layout.addWidget(self.tradeReviewWidget)

        result_tabs = QtWidgets.QTabWidget()
        self.resultTabs = result_tabs
        self.tradeResultTable = self._result_table(TRADE_COLUMNS)
        self.equityResultTable = self._result_table(EQUITY_COLUMNS)
        self.comparisonTable = self._result_table(("metric", "value"))
        result_tabs.addTab(self.tradeResultTable, "")
        result_tabs.addTab(self.equityResultTable, "")
        result_tabs.addTab(self.comparisonTable, "")
        bind_tab(result_tabs, self.tradeResultTable, "backtest.tab.trades", self._tr)
        bind_tab(result_tabs, self.equityResultTable, "backtest.tab.equity", self._tr)
        bind_tab(result_tabs, self.comparisonTable, "backtest.tab.comparison", self._tr)
        bind_table_headers(
            self.tradeResultTable,
            (f"backtest.column.{column}" for column in TRADE_COLUMNS),
            self._tr,
        )
        bind_table_headers(
            self.equityResultTable,
            (f"backtest.column.{column}" for column in EQUITY_COLUMNS),
            self._tr,
        )
        bind_table_headers(
            self.comparisonTable,
            ("backtest.column.metric", "backtest.column.value"),
            self._tr,
        )
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
                "direction": self.directionBox.currentData() or "long_only",
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
        self.resultText.setPlainText(self._tr("backtest.initial_message"))
        for table in (self.tradeResultTable, self.equityResultTable, self.comparisonTable):
            table.setRowCount(0)
        self.summaryWidget.clear()
        self.equityCurveWidget.clear()
        self.tradeReviewWidget.clear()

    def set_analysis_params_source(self, value: dict[str, Any] | None) -> None:
        self._analysis_params_source = dict(value) if value else None

    def apply_strategy_spec(self, value: Any) -> None:
        values = self.controller.apply_strategy_spec(
            value,
            current_values=self.collect_form_values(),
        )
        self._strategy_spec_source = dict(values["strategy_spec"])
        self._set_form_values(values)

    def apply_analysis_params(self) -> None:
        try:
            source = self._available_analysis_params()
            values = self.controller.apply_analysis_params(
                source,
                current_values=self.collect_form_values(),
            )
            self._set_form_values(values)
            self.resultText.setPlainText(self._tr("backtest.analysis_applied"))
        except Exception as exc:
            self.resultText.setPlainText(format_errors([str(exc)], translator=self._tr))

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
        direction = str(values.get("direction") or "long_only")
        index = self.directionBox.findData(direction)
        self.directionBox.setCurrentIndex(max(0, index))
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

    def closeEvent(self, event) -> None:
        self.equityCurveWidget.shutdown()
        trade_review = getattr(self, "tradeReviewWidget", None)
        if trade_review is not None:
            trade_review.shutdown()
        super().closeEvent(event)

    def retranslate_ui(self):
        language = self._language()
        retranslate_bound_widgets(self, self._tr)
        self.btnRun.setText(tr("run_backtest", language))
        self.btnScan.setText(tr("run_parameter_scan", language))
        self.btnWalkForward.setText(tr("run_walk_forward", language))
        self.btnExport.setText(tr("backtest.export", language))
        self.btnLoadDefaults.setText(tr("backtest.load_defaults", language))
        self.btnApplyAnalysis.setText(tr("backtest.apply_analysis", language))
        self.btnReset.setText(tr("backtest.reset", language))
        locale = QtCore.QLocale(
            QtCore.QLocale.English if language == "en_US" else QtCore.QLocale.Chinese,
            QtCore.QLocale.UnitedStates if language == "en_US" else QtCore.QLocale.China,
        )
        self.backtestStartEdit.setLocale(locale)
        self.backtestEndEdit.setLocale(locale)
        if self.last_service_result is not None:
            self._apply_service_result(self.last_service_result)
        elif self.last_result is not None:
            self._display_metrics(self.last_result.metrics)
            self.summaryWidget.retranslate_ui()
            self.equityCurveWidget.retranslate_ui()
            self.tradeReviewWidget.retranslate_ui()
        else:
            self.summaryWidget.retranslate_ui()
            self.equityCurveWidget.retranslate_ui()
            self.tradeReviewWidget.retranslate_ui()

    def apply_theme(self, theme: dict | None) -> None:
        self._theme_settings = normalize_theme_settings(theme)
        self.summaryWidget.apply_theme(theme)
        self.equityCurveWidget.apply_theme(theme)
        self.tradeReviewWidget.apply_theme(theme)
        for table, columns in (
            (self.tradeResultTable, TRADE_COLUMNS),
            (self.equityResultTable, EQUITY_COLUMNS),
            (self.comparisonTable, ("metric", "value")),
        ):
            self._refresh_result_table_tones(table, columns)

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
        if self.strategyBox.currentData() == "MA Cross":
            return MovingAverageCrossStrategy(self.fastSpin.value(), self.slowSpin.value(), "LONG_ONLY")
        return FeatureRuleLongStrategy(
            self._conditions(),
            exit_bars=self.exitBarsSpin.value(),
            stop_loss_pct=self.stopSpin.value() or None,
            take_profit_pct=self.takeSpin.value() or None,
        )

    def _strategy_factory_grid(self):
        if self.strategyBox.currentData() == "MA Cross":
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
        lines = [self._tr("backtest.initial_message"), ""]
        for key in keys:
            lines.append(f"{self._tr(f'backtest.metric.{key}')}: {metrics.get(key)}")
        self.resultText.setPlainText("\n".join(lines))

    def import_candidate_rule(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self._tr("backtest.select_rule_file"),
            "",
            self._tr("backtest.csv_filter"),
        )
        if not path:
            return
        try:
            strategy = load_candidate_rule(path, self.ruleIndexSpin.value())
            self.loaded_rule_conditions = strategy.conditions
            self.loaded_rule_path = path
            self.set_analysis_params_source({"conditions_json": list(strategy.conditions)})
            self.strategyBox.setCurrentIndex(
                max(0, self.strategyBox.findData("Feature Rule Long"))
            )
            self.resultText.setPlainText(
                self._tr("backtest.rule_imported").format(
                    index=self.ruleIndexSpin.value()
                )
            )
        except Exception as exc:
            self.resultText.setPlainText(
                self._tr("backtest.rule_import_failed").format(
                    error=f"{type(exc).__name__}: {exc}"
                )
            )

    def run_backtest(self):
        if self.strategyBox.currentData() != "Deep V Reversal":
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
            self.last_result = None
            self._apply_service_result(result)
        except Exception as exc:
            self.resultText.setPlainText(
                format_errors([f"{type(exc).__name__}: {exc}"], translator=self._tr)
            )

    def _run_legacy_backtest(self):
        try:
            data = self._df()
            if data.empty:
                self.resultText.setPlainText(self._tr("backtest.no_data"))
                self.summaryWidget.clear()
                self.equityCurveWidget.clear()
                self.tradeReviewWidget.clear()
                return
            symbol, interval = self._symbol_interval()
            self.last_result = run_backtest(data, self._strategy(), self._config(), symbol, interval)
            self.last_service_result = None
            self._display_metrics(self.last_result.metrics)
            self.summaryWidget.set_summary(self.last_result.metrics)
            self.equityCurveWidget.set_result(
                self.last_result,
                initial_equity=self._config().initial_equity,
            )
            self.tradeReviewWidget.set_result(data, self.last_result)
        except Exception as exc:
            self.resultText.setPlainText(
                self._tr("backtest.failed").format(
                    error=f"{type(exc).__name__}: {exc}"
                )
            )
            self.equityCurveWidget.clear()
            self.summaryWidget.clear()
            self.tradeReviewWidget.clear()

    def _apply_service_result(self, result) -> None:
        if not result.success:
            self.resultText.setPlainText(format_errors(result.errors, translator=self._tr))
            for table in (self.tradeResultTable, self.equityResultTable, self.comparisonTable):
                table.setRowCount(0)
            self.summaryWidget.clear()
            self.equityCurveWidget.clear()
            self.tradeReviewWidget.clear()
            return
        self.resultText.setPlainText(
            format_summary(
                result.summary,
                warnings=result.warnings,
                translator=self._tr,
            )
        )
        self._populate_result_table(self.tradeResultTable, trade_rows(result.trades), TRADE_COLUMNS)
        self._populate_result_table(self.equityResultTable, equity_rows(result.equity_curve), EQUITY_COLUMNS)
        self._populate_result_table(
            self.comparisonTable,
            comparison_rows(result.manual_vs_rule_comparison),
            ("metric", "value"),
        )
        self.summaryWidget.set_summary(result.summary)
        self.equityCurveWidget.set_result(
            result,
            initial_equity=self.controller.build_config(self.collect_form_values()).initial_equity,
        )
        self.tradeReviewWidget.set_result(self._df(), result)

    def _populate_result_table(
        self,
        table: QtWidgets.QTableWidget,
        rows: list[dict[str, Any]],
        columns: tuple[str, ...],
    ) -> None:
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, column in enumerate(columns):
                value = row.get(column)
                if value is None:
                    text = ""
                elif column == "side":
                    text = side_label(value, self._language())
                elif column == "exit_reason":
                    text = self._tr(
                        f"backtest.exit_reason.{value}",
                        default=str(value),
                    )
                elif column == "metric":
                    text = self._tr(
                        f"backtest.comparison.{value}",
                        default=str(value),
                    )
                else:
                    text = str(value)
                item = QtWidgets.QTableWidgetItem(text)
                self._apply_result_item_tone(item, column, value)
                table.setItem(row_index, column_index, item)
        table.resizeColumnsToContents()

    def _apply_result_item_tone(
        self,
        item: QtWidgets.QTableWidgetItem,
        column: str,
        value: Any,
    ) -> None:
        tone = value_tone(column, value)
        color = self._tone_color(tone)
        if color:
            item.setForeground(QtGui.QBrush(QtGui.QColor(color)))

    def _refresh_result_table_tones(
        self,
        table: QtWidgets.QTableWidget,
        columns: tuple[str, ...],
    ) -> None:
        for row in range(table.rowCount()):
            for column_index, column in enumerate(columns):
                item = table.item(row, column_index)
                if item is None:
                    continue
                self._apply_result_item_tone(item, column, item.text())

    def _tone_color(self, tone: str) -> str:
        normalized = self._theme_settings
        if tone == "success":
            return normalized["success"]
        if tone == "danger":
            return normalized["danger"]
        return normalized["text_secondary"]

    def run_scan(self):
        try:
            data = self._df()
            if data.empty:
                self.resultText.setPlainText(self._tr("backtest.no_scan_data"))
                return
            symbol, interval = self._symbol_interval()
            factory, grid = self._strategy_factory_grid()
            self.last_scan = grid_search(data, factory, grid, self._config(), symbol, interval)
            top = self.last_scan.sort_values("sharpe", ascending=False, na_position="last").head(10)
            self.resultText.setPlainText(
                self._tr("backtest.scan_disclaimer") + "\n\n"
                + top.to_string(index=False)
            )
        except Exception as exc:
            self.resultText.setPlainText(
                self._tr("backtest.scan_failed").format(
                    error=f"{type(exc).__name__}: {exc}"
                )
            )

    def run_walk_forward(self):
        try:
            data = self._df()
            if data.empty:
                self.resultText.setPlainText(self._tr("backtest.no_walk_forward_data"))
                return
            symbol, interval = self._symbol_interval()
            factory, grid = self._strategy_factory_grid()
            self.last_walk_forward = walk_forward_grid_search(data, factory, grid, self._config(), symbol, interval)
            valid = pd.DataFrame(self.last_walk_forward.get("valid_results") or pd.DataFrame())
            valid_top = valid.sort_values("sharpe", ascending=False, na_position="last").head(1) if not valid.empty and "sharpe" in valid.columns else valid.head(1)
            lines = [
                self._tr("backtest.walk_forward_disclaimer"),
                "",
                f"{self._tr('backtest.walk_forward_selected')}: {self.last_walk_forward.get('selected_params')}",
                f"{self._tr('backtest.walk_forward_test')}: {self.last_walk_forward.get('test_result')}",
                f"{self._tr('backtest.warnings')}: "
                f"{localize_warnings(self.last_walk_forward.get('warnings'), translator=self._tr)}",
                "",
                f"{self._tr('backtest.walk_forward_validation_top')}:",
                valid_top.to_string(index=False) if not valid_top.empty else self._tr("backtest.empty"),
            ]
            self.resultText.setPlainText("\n".join(lines))
        except Exception as exc:
            self.resultText.setPlainText(
                self._tr("backtest.walk_forward_failed").format(
                    error=f"{type(exc).__name__}: {exc}"
                )
            )

    def export_result(self):
        result = self._exportable_result()
        if result is None:
            self.resultText.setPlainText(self._tr("backtest.run_first"))
            return
        target = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            self._tr("backtest.select_export_directory"),
        )
        if not target:
            return
        try:
            out = export_backtest_result(
                result,
                Path(target),
                self.last_scan,
                self.last_walk_forward,
                strategy_spec=self._strategy_spec_source,
                applied_params=self.collect_form_values(),
            )
            self.resultText.appendPlainText(
                "\n" + self._tr("backtest.exported").format(path=out)
            )
        except Exception as exc:
            self.resultText.appendPlainText(
                "\n"
                + self._tr("backtest.export_failed").format(
                    error=f"{type(exc).__name__}: {exc}"
                )
            )

    def _exportable_result(self):
        if self.last_service_result is not None:
            return self.last_service_result if self.last_service_result.success else None
        return self.last_result
