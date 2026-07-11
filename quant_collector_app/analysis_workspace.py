from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from app_config import EXPORT_DIR
from app_i18n import tr
from app_logger import get_logger
from analytics.metrics import max_drawdown, payoff_ratio, profit_factor, sharpe_ratio
from accounting import build_continuous_equity_curve
from performance_analysis import (
    build_performance_snapshot,
    performance_curve_end,
    smooth_curve_values,
    split_signed_curve,
)
from ui_style import COLORS, SPACING
from controllers.entry_annotation_controller import EntryAnnotationController
from services.entry_research_service import EntryResearchService


logger = get_logger(__name__)

AUDIT_COLUMNS = ["metric", "value"]
AUDIT_METRICS = [
    "sample_count",
    "valid_sample_count",
    "invalid_sample_count",
    "missing_feature_count",
    "missing_label_count",
    "duplicate_event_id_count",
    "symbol_distribution",
    "interval_distribution",
    "label_tag_distribution",
    "side_distribution",
    "event_type_distribution",
    "time_range",
    "leakage_audit_status",
    "small_sample_warning",
]
EVENT_STUDY_COLUMNS = [
    "group_by",
    "label_tag",
    "event_type",
    "side",
    "sample_count",
    "mean",
    "median",
    "std",
    "q25",
    "q75",
    "win_rate",
    "bootstrap_ci_low",
    "bootstrap_ci_high",
    "small_sample_warning",
]
FACTOR_BINNING_COLUMNS = [
    "factor",
    "bin_id",
    "sample_count",
    "mean_label",
    "median_label",
    "win_rate",
    "bootstrap_ci_low",
    "bootstrap_ci_high",
    "monotonicity_score",
    "warning",
]
FACTOR_IC_COLUMNS = ["factor", "pearson_ic", "spearman_rank_ic", "p_value", "sample_count", "stability_score", "warning"]
RULE_COLUMNS = [
    "readable_rule",
    "sample_count",
    "coverage",
    "mean_return",
    "win_rate",
    "train_score",
    "test_score",
    "degradation_pct",
    "warning",
]
WALK_FORWARD_COLUMNS = ["period", "train_start", "train_end", "test_start", "test_end", "test_mean", "test_win_rate", "warning"]
ENTRY_REVIEW_QUEUE_COLUMNS = [
    "observation_id",
    "human_entry_similarity",
    "setup_confidence",
    "review_reason",
    "review_mode",
]
RESEARCH_LABELS = [
    "fwd_ret_5_side_adj",
    "fwd_ret_10_side_adj",
    "fwd_ret_20_side_adj",
    "hit_tp_1pct_before_sl_1pct",
]
BACKTEST_PARAM_SOURCE_FIELDS = {
    "conditions_json",
    "drop_pct_threshold",
    "volume_spike_threshold",
    "lower_shadow_ratio",
    "next_candle_body_ratio",
    "trend_window",
    "future_window",
    "tp_threshold",
    "sl_threshold",
}
EQUITY_CURVE_MODE = "equity"
PNL_CURVE_MODE = "pnl"


def _safe_float(value, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _fmt_money(value: float) -> str:
    return f"{value:.2f}" if math.isfinite(value) else "-"


def _fmt_pct(value: float) -> str:
    return f"{value:.2f}%" if math.isfinite(value) else "-"


class SortableTableItem(QtWidgets.QTableWidgetItem):
    def __init__(self, text: str, sort_value=None):
        super().__init__(text)
        self.sort_value = sort_value if sort_value is not None else text.casefold()

    def __lt__(self, other):
        if isinstance(other, SortableTableItem):
            return self.sort_value < other.sort_value
        return super().__lt__(other)


class AnalysisWorkspace(QtWidgets.QDialog):
    def __init__(self, app_window, parent=None):
        super().__init__(parent or app_window)
        self.app_window = app_window
        self.resize(1180, 760)
        self.setSizeGripEnabled(True)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        self.last_research_dir: Path | None = None
        self.last_entry_logic_dir: Path | None = None
        self._research_output_loaded = False
        self._entry_logic_output_loaded = False
        self._entry_review_queue_rows: list[dict] = []
        self._entry_annotation_controller: EntryAnnotationController | None = None
        self.last_time_series_summary: dict | None = None
        self.last_time_series_report_text = ""
        self.last_entry_logic_report_text = ""
        self._candidate_rule_rows: list[dict] = []
        self._localized_placeholders: list[tuple[QtWidgets.QPlainTextEdit, str, bool]] = []
        self._build_ui()
        self.retranslate_ui()
        self._apply_button_theme()

    def _apply_button_theme(self) -> None:
        """Give every button/input in the analysis panel the themed pill look."""
        theme = getattr(self.app_window, "theme_settings", None)
        if theme is None:
            return
        try:
            from views.main_window_presentation import (
                apply_role_button_styles,
                apply_themed_input_styles,
            )
            from views.widget_effects import apply_role_button_shadows

            apply_role_button_styles(self, theme)
            apply_themed_input_styles(self, theme)
            apply_role_button_shadows(self)
        except Exception:
            pass

    def _language(self) -> str:
        return str(getattr(self.app_window, "current_language", "zh_CN") or "zh_CN")

    def _tr(self, key: str, default: str | None = None) -> str:
        return tr(key, self._language(), default)

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        root.setSpacing(SPACING["md"])

        header = QtWidgets.QHBoxLayout()
        self.titleLabel = QtWidgets.QLabel()
        self.titleLabel.setProperty("role", "appTitle")
        self.sessionLabel = QtWidgets.QLabel()
        self.sessionLabel.setProperty("role", "muted")
        self.btnRefresh = QtWidgets.QPushButton()
        self.btnRefresh.setProperty("role", "secondaryButton")
        self.btnRefresh.clicked.connect(self.refresh)
        header.addWidget(self.titleLabel)
        header.addWidget(self.sessionLabel)
        header.addStretch(1)
        header.addWidget(self.btnRefresh)
        root.addLayout(header)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.performanceTab = self._performance_tab()
        self.eventStudyTab = self._event_study_tab()
        self.consistencyTab = self._scrollable_existing_widget(
            "strategyConsistencyPanel",
            "workspace.no_strategy_panel",
        )
        self.backtestTab = self._scrollable_existing_widget(
            "backtestPanel",
            "workspace.no_backtest_panel",
        )
        self.premiumTab = self._existing_analysis_widget("premiumBox", "workspace.no_premium_panel")
        self.aiTab = self._ai_tab()
        self.researchTab = self._research_tab()
        self.timeSeriesTab = self._time_series_tab()
        self.tabs.addTab(self.performanceTab, "")
        self.tabs.addTab(self.eventStudyTab, "")
        self.tabs.addTab(self.consistencyTab, "")
        self.tabs.addTab(self.backtestTab, "")
        self.tabs.addTab(self.premiumTab, "")
        self.tabs.addTab(self.aiTab, "")
        self.tabs.addTab(self.researchTab, "")
        self.tabs.addTab(self.timeSeriesTab, "")
        root.addWidget(self.tabs, stretch=1)

    def _performance_tab(self) -> QtWidgets.QWidget:
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        layout.setSpacing(SPACING["md"])
        controls = QtWidgets.QHBoxLayout()
        controls.addWidget(QtWidgets.QLabel(self._tr("performance.session")))
        self.performanceSessionBox = QtWidgets.QComboBox()
        self._populate_performance_sessions()
        self.performanceSessionBox.currentIndexChanged.connect(self._refresh_performance_workspace)
        controls.addWidget(self.performanceSessionBox)
        controls.addStretch(1)
        controls.addWidget(QtWidgets.QLabel(self._tr("performance.curve_mode")))
        self.performanceCurveMode = QtWidgets.QComboBox()
        self.performanceCurveMode.addItem(self._tr("performance.equity_curve"), EQUITY_CURVE_MODE)
        self.performanceCurveMode.addItem(self._tr("performance.pnl_curve"), PNL_CURVE_MODE)
        self.performanceCurveMode.currentIndexChanged.connect(self._refresh_performance_workspace)
        controls.addWidget(self.performanceCurveMode)
        layout.addLayout(controls)

        summary = QtWidgets.QFrame()
        summary.setProperty("role", "statusBlock")
        summary_l = QtWidgets.QVBoxLayout(summary)
        summary_l.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        summary_l.setSpacing(SPACING["md"])
        self.performanceMetricLabels = {}
        primary_metrics = (
            ("current_equity", "performance.current_equity"),
            ("total_pnl", "performance.total_pnl"),
            ("total_return", "performance.total_return"),
            ("unrealized_pnl", "performance.unrealized_pnl"),
        )
        secondary_metrics = (
            ("realized_pnl", "performance.realized_pnl"),
            ("win_rate", "performance.win_rate"),
            ("payoff", "performance.payoff"),
            ("sharpe", "performance.sharpe"),
            ("max_drawdown", "performance.max_drawdown"),
            ("trade_count", "performance.trade_count"),
        )
        for metric_defs, primary in ((primary_metrics, True), (secondary_metrics, False)):
            row_layout = QtWidgets.QGridLayout()
            row_layout.setHorizontalSpacing(SPACING["lg"])
            for index, (key, label_key) in enumerate(metric_defs):
                block = QtWidgets.QWidget()
                block_l = QtWidgets.QVBoxLayout(block)
                block_l.setContentsMargins(0, 0, 0, 0)
                name = QtWidgets.QLabel(self._tr(label_key))
                name.setProperty("role", "muted")
                value = QtWidgets.QLabel("-")
                value.setProperty("role", "metricValue" if primary else "statusValue")
                self.performanceMetricLabels[key] = value
                block_l.addWidget(name)
                block_l.addWidget(value)
                row_layout.addWidget(block, 0, index)
            summary_l.addLayout(row_layout)
        layout.addWidget(summary)

        self.equityCurvePlot = pg.PlotWidget()
        self.equityCurvePlot.setMinimumHeight(280)
        self.equityCurvePlot.showGrid(x=True, y=True, alpha=0.16)
        self.equityCurvePlot.setMouseEnabled(x=True, y=True)
        self.equityCurvePlot.setAntialiasing(True)
        self.equityCurve = self.equityCurvePlot.plot([], [], pen=pg.mkPen(COLORS["accent"], width=2))
        self.performanceCurveItems: list[pg.PlotDataItem] = []
        self.performanceBaseline = pg.InfiniteLine(angle=0, pen=pg.mkPen(COLORS["text_tertiary"], style=QtCore.Qt.DashLine))
        self.equityCurvePlot.addItem(self.performanceBaseline)
        self.performanceTradeMarkers = pg.ScatterPlotItem(size=11, pxMode=True)
        self.performanceTradeMarkers.sigClicked.connect(self._on_performance_trade_marker_clicked)
        self.equityCurvePlot.addItem(self.performanceTradeMarkers)
        self.equityCurvePlot.scene().sigMouseMoved.connect(self._on_performance_curve_mouse_moved)
        self.equityCurveData: list[float] = []
        layout.addWidget(self.equityCurvePlot, stretch=2)
        self.performanceHoverLabel = QtWidgets.QLabel(self._tr("performance.hover_empty"))
        self.performanceHoverLabel.setProperty("role", "muted")
        layout.addWidget(self.performanceHoverLabel)

        filter_row = QtWidgets.QHBoxLayout()
        self.performanceTradeFilter = QtWidgets.QComboBox()
        for key in ("all", "profit", "loss", "open", "closed", "flat"):
            self.performanceTradeFilter.addItem(self._tr(f"performance.filter.{key}"), key)
        self.performanceTradeFilter.setCurrentIndex(self.performanceTradeFilter.findData("closed"))
        self.performanceSideFilter = QtWidgets.QComboBox()
        for key in ("all", "long", "short"):
            self.performanceSideFilter.addItem(self._tr(f"performance.side.{key}"), key.upper())
        self.performanceTradeFilter.currentIndexChanged.connect(self._refresh_performance_workspace)
        self.performanceSideFilter.currentIndexChanged.connect(self._refresh_performance_workspace)
        filter_row.addWidget(self.performanceTradeFilter)
        filter_row.addWidget(self.performanceSideFilter)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        self.tradePnlTable = QtWidgets.QTableWidget()
        self.tradePnlTable.setColumnCount(13)
        self.tradePnlTable.setHorizontalHeaderLabels(
            [self._tr(f"performance.trade.{key}") for key in (
                "side", "entry_time", "exit_time", "entry_price", "exit_price", "notional",
                "fees", "pnl", "return", "holding", "take_profit", "stop_loss", "exit_reason",
            )]
        )
        self.tradePnlTable.verticalHeader().setVisible(False)
        self.tradePnlTable.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.tradePnlTable.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tradePnlTable.setAlternatingRowColors(True)
        self.tradePnlTable.setSortingEnabled(True)
        self.tradePnlTable.setMinimumHeight(260)
        self.tradePnlTable.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.tradePnlTable, stretch=2)

        distribution = QtWidgets.QFrame()
        distribution.setProperty("role", "statusBlock")
        distribution_l = QtWidgets.QHBoxLayout(distribution)
        stats = QtWidgets.QGridLayout()
        self.performanceDistributionLabels = {}
        distribution_defs = (
            "win_count", "loss_count", "win_rate", "average_win", "average_loss",
            "largest_win", "largest_loss", "gross_profit", "gross_loss",
        )
        for index, key in enumerate(distribution_defs):
            name = QtWidgets.QLabel(self._tr(f"performance.distribution.{key}"))
            name.setProperty("role", "muted")
            value = QtWidgets.QLabel("-")
            self.performanceDistributionLabels[key] = value
            stats.addWidget(name, index // 3, (index % 3) * 2)
            stats.addWidget(value, index // 3, (index % 3) * 2 + 1)
        distribution_l.addLayout(stats, 1)
        histogram_panel = QtWidgets.QWidget()
        histogram_l = QtWidgets.QVBoxLayout(histogram_panel)
        histogram_l.setContentsMargins(0, 0, 0, 0)
        histogram_l.setSpacing(SPACING["xs"])
        self.performanceHistogramTitle = QtWidgets.QLabel(
            self._tr("performance.histogram.title")
        )
        self.performanceHistogramTitle.setProperty("role", "statusValue")
        self.performanceHistogramDefinition = QtWidgets.QLabel(
            self._tr("performance.histogram.definition")
        )
        self.performanceHistogramDefinition.setProperty("role", "muted")
        self.performanceHistogramDefinition.setWordWrap(True)
        histogram_l.addWidget(self.performanceHistogramTitle)
        histogram_l.addWidget(self.performanceHistogramDefinition)
        self.performanceHistogramPlot = pg.PlotWidget()
        self.performanceHistogramPlot.setMinimumHeight(170)
        self.performanceHistogramPlot.showGrid(x=False, y=True, alpha=0.12)
        self.performanceHistogram = pg.BarGraphItem(x=[], height=[], width=0.75)
        self.performanceHistogramPlot.addItem(self.performanceHistogram)
        histogram_l.addWidget(self.performanceHistogramPlot, 1)
        distribution_l.addWidget(histogram_panel, 1)
        layout.addWidget(distribution)
        scroll.setWidget(tab)
        return scroll

    def _populate_performance_sessions(self) -> None:
        current_id = str(getattr(self.app_window, "session_id", "") or "")
        self.performanceSessionBox.blockSignals(True)
        self.performanceSessionBox.clear()
        self.performanceSessionBox.addItem(self._tr("performance.current_session"), current_id)
        storage = getattr(self.app_window, "storage", None)
        if storage is not None and hasattr(storage, "fetch_table"):
            try:
                sessions = storage.fetch_table("sessions")
            except Exception:
                sessions = []
            for session in sorted(sessions, key=lambda row: str(row.get("last_saved_at") or ""), reverse=True):
                session_id = str(session.get("session_id") or "")
                if not session_id or session_id == current_id:
                    continue
                label = f"{session.get('symbol') or '-'} {session.get('interval') or '-'} | {session_id[-8:]}"
                self.performanceSessionBox.addItem(label, session_id)
        self.performanceSessionBox.blockSignals(False)

    def _on_performance_trade_marker_clicked(self, _item, points, _event=None) -> None:
        if not points:
            return
        trade_id = str(points[0].data() or "")
        for row in range(self.tradePnlTable.rowCount()):
            item = self.tradePnlTable.item(row, 0)
            if item is not None and str(item.data(QtCore.Qt.UserRole) or "") == trade_id:
                self.tradePnlTable.selectRow(row)
                self.tradePnlTable.scrollToItem(item)
                return

    def _on_performance_curve_mouse_moved(self, scene_pos) -> None:
        if not self.equityCurvePlot.sceneBoundingRect().contains(scene_pos):
            return
        point = self.equityCurvePlot.getPlotItem().vb.mapSceneToView(scene_pos)
        self._update_performance_hover(int(round(point.x())))

    def _update_performance_hover(self, index: int) -> None:
        rows = getattr(self, "_performanceHoverRows", [])
        if index < 0 or index >= len(rows):
            return
        row = rows[index]
        initial = float(getattr(self, "_performanceInitialEquity", 0.0))
        equity = _safe_float(row.get("current_equity"), _safe_float(row.get("equity_after"), initial))
        realized = _safe_float(row.get("realized_net_pnl"))
        unrealized = _safe_float(row.get("unrealized_pnl"))
        text = self._tr("performance.hover_detail").format(
            time=row.get("time") or row.get("created_at") or "-",
            equity=_fmt_money(equity),
            pnl=_fmt_money(equity - initial),
            realized=_fmt_money(realized),
            unrealized=_fmt_money(unrealized),
            positions=int(_safe_float(row.get("open_position_count"))),
        )
        self.performanceHoverLabel.setText(text)

    def _event_study_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        self.eventTabs = QtWidgets.QTabWidget()
        self.eventStudyTableTab = self._existing_analysis_widget("eventStudyTable", "workspace.no_event_study")
        self.datasetTab = self._existing_analysis_widget("datasetText", "workspace.no_dataset")
        self.eventTabs.addTab(self.eventStudyTableTab, "")
        self.eventTabs.addTab(self.datasetTab, "")
        layout.addWidget(self.eventTabs, stretch=1)
        return tab

    def _spin_value(self, name: str, default: float) -> float:
        widget = getattr(self.app_window, name, None)
        if widget is None or not hasattr(widget, "value"):
            return float(default)
        return _safe_float(widget.value(), float(default))

    def _trade_notional(self, trade: dict) -> float:
        default_notional = self._spin_value("tradeNotionalSpin", 1_000.0)
        notional = _safe_float(trade.get("notional_quote"), default_notional)
        return notional if notional > 0 else default_notional

    def _trade_pnl(self, trade: dict) -> float:
        pnl = _safe_float(trade.get("net_pnl_quote"), float("nan"))
        if math.isfinite(pnl):
            return pnl
        ret = _safe_float(trade.get("net_return_pct"), _safe_float(trade.get("final_return_pct"), 0.0))
        return ret / 100.0 * self._trade_notional(trade)

    def _trade_return_pct(self, trade: dict) -> float:
        value = _safe_float(trade.get("net_return_pct"), float("nan"))
        if math.isfinite(value):
            return value
        notional = self._trade_notional(trade)
        return self._trade_pnl(trade) / notional * 100.0 if notional > 0 else 0.0

    def _performance_equity_rows(self) -> list[dict]:
        trades = [dict(trade) for trade in getattr(self.app_window, "trades", []) or []]
        frame = getattr(self.app_window, "df", None)
        initial = self._spin_value("initialEquitySpin", 10_000.0)
        notional = self._spin_value("tradeNotionalSpin", 1_000.0)
        if frame is not None and hasattr(frame, "empty") and not frame.empty:
            try:
                raw_cursor = getattr(self.app_window, "cursor", len(frame) - 1)
                replay_cursor = raw_cursor if isinstance(raw_cursor, (int, float)) else len(frame) - 1
                end = performance_curve_end(
                    trades,
                    cursor=int(replay_cursor),
                    row_count=len(frame),
                )
                return build_continuous_equity_curve(
                    frame.iloc[:end].to_dict("records"),
                    trades,
                    str(getattr(self.app_window, "session_id", "") or ""),
                    initial,
                    notional,
                )
            except Exception:
                logger.exception("Failed to build continuous equity curve for analysis workspace")
        current_rows = getattr(self.app_window, "_current_equity_rows", None)
        if callable(current_rows):
            try:
                return [dict(row) for row in current_rows()]
            except Exception:
                logger.exception("Failed to read current equity rows")
        return []

    def _refresh_performance_workspace(self) -> None:
        selected_id = str(self.performanceSessionBox.currentData() or "")
        current_id = str(getattr(self.app_window, "session_id", "") or "")
        initial = self._spin_value("initialEquitySpin", 10_000.0)
        notional = self._spin_value("tradeNotionalSpin", 1_000.0)
        if not selected_id or selected_id == current_id:
            trades = [dict(trade) for trade in getattr(self.app_window, "trades", []) or []]
            equity_rows = self._performance_equity_rows()
        else:
            storage = getattr(self.app_window, "storage", None)
            session = None
            trades = []
            equity_rows = []
            if storage is not None:
                try:
                    session, trades, _events = storage.load_session_snapshot(selected_id)
                    equity_rows = storage.fetch_table("account_equity", "session_id=?", (selected_id,))
                except Exception:
                    logger.exception("Failed to load historical performance session")
            if session:
                initial = _safe_float(session.get("initial_equity"), initial)
                notional = _safe_float(session.get("trade_notional"), notional)

        snapshot = build_performance_snapshot(
            equity_rows=equity_rows,
            trades=trades,
            initial_equity=initial,
            default_notional=notional,
        )
        self._performanceHoverRows = list(equity_rows)
        self._performanceInitialEquity = initial
        raw_metrics = snapshot["metrics"]
        metric_values = {
            "current_equity": _fmt_money(raw_metrics["current_equity"]),
            "total_pnl": _fmt_money(raw_metrics["total_pnl"]),
            "total_return": _fmt_pct(raw_metrics["total_return_pct"]),
            "unrealized_pnl": _fmt_money(raw_metrics["unrealized_pnl"]),
            "realized_pnl": _fmt_money(raw_metrics["realized_pnl"]),
            "win_rate": _fmt_pct(raw_metrics["win_rate_pct"]),
            "payoff": _fmt_money(raw_metrics["payoff_ratio"] if raw_metrics["payoff_ratio"] is not None else float("nan")),
            "sharpe": _fmt_money(raw_metrics["sharpe_ratio"] if raw_metrics["sharpe_ratio"] is not None else float("nan")),
            "max_drawdown": _fmt_pct(raw_metrics["max_drawdown_pct"] if raw_metrics["max_drawdown_pct"] is not None else float("nan")),
            "trade_count": str(raw_metrics["trade_count"]),
        }
        signed_metric_keys = {"total_pnl", "total_return", "unrealized_pnl", "realized_pnl"}
        signed_values = {
            "total_pnl": raw_metrics["total_pnl"],
            "total_return": raw_metrics["total_return_pct"],
            "unrealized_pnl": raw_metrics["unrealized_pnl"],
            "realized_pnl": raw_metrics["realized_pnl"],
        }
        for key, value in metric_values.items():
            label = self.performanceMetricLabels[key]
            label.setText(value)
            if key in signed_metric_keys:
                number = signed_values[key]
                color = COLORS["success"] if number > 0 else COLORS["danger"] if number < 0 else COLORS["text_secondary"]
                label.setStyleSheet(f"color: {color};")

        self.equityCurveData = list(snapshot["equity_values"])
        self.equityCurve.setData([], [])
        for item in self.performanceCurveItems:
            self.equityCurvePlot.removeItem(item)
        self.performanceCurveItems.clear()
        curve_mode = str(self.performanceCurveMode.currentData() or "equity")
        curve_values = snapshot["pnl_values"] if curve_mode == "pnl" else snapshot["equity_values"]
        display_curve_values = smooth_curve_values(curve_values, window=5)
        baseline = 0.0 if curve_mode == "pnl" else initial
        self.performanceBaseline.setValue(baseline)
        for side, points in split_signed_curve(display_curve_values, baseline):
            item = self.equityCurvePlot.plot(
                [point[0] for point in points],
                [point[1] for point in points],
                pen=pg.mkPen(COLORS["success"] if side == "positive" else COLORS["danger"], width=2),
                antialias=True,
            )
            item.setDownsampling(auto=True, method="mean")
            item.setClipToView(True)
            self.performanceCurveItems.append(item)
        bar_positions = {
            int(row.get("bar_index", index)): index
            for index, row in enumerate(equity_rows)
            if row.get("bar_index", index) is not None
        }
        marker_spots = []
        for trade in snapshot["trades"]:
            trade_id = str(trade.get("trade_id") or "")
            for index_key, symbol, color in (
                ("entry_bar_index", "t1", COLORS["chart_up"]),
                ("exit_bar_index", "x", COLORS["chart_down"]),
            ):
                try:
                    curve_index = bar_positions[int(trade.get(index_key))]
                    y_value = display_curve_values[curve_index]
                except (KeyError, TypeError, ValueError, IndexError):
                    continue
                marker_spots.append(
                    {
                        "pos": (float(curve_index), float(y_value)),
                        "data": trade_id,
                        "symbol": symbol,
                        "brush": pg.mkBrush(color),
                        "pen": pg.mkPen(color),
                    }
                )
        self.performanceTradeMarkers.setData(marker_spots)

        distribution = snapshot["distribution"]
        distribution_values = {
            "win_count": str(distribution["win_count"]),
            "loss_count": str(distribution["loss_count"]),
            "win_rate": _fmt_pct(raw_metrics["win_rate_pct"]),
            "average_win": _fmt_money(distribution["average_win"]),
            "average_loss": _fmt_money(distribution["average_loss"]),
            "largest_win": _fmt_money(distribution["largest_win"]),
            "largest_loss": _fmt_money(distribution["largest_loss"]),
            "gross_profit": _fmt_money(distribution["gross_profit"]),
            "gross_loss": _fmt_money(distribution["gross_loss"]),
        }
        for key, value in distribution_values.items():
            self.performanceDistributionLabels[key].setText(value)

        pnls = np.asarray(snapshot["closed_pnls"], dtype=float)
        if pnls.size:
            bin_count = min(12, max(3, int(math.sqrt(pnls.size)) + 1))
            counts, edges = np.histogram(pnls, bins=bin_count)
            centers = (edges[:-1] + edges[1:]) / 2.0
            width = max(1e-9, float(edges[1] - edges[0]) * 0.82)
            brushes = [pg.mkBrush(COLORS["success"] if center >= 0 else COLORS["danger"]) for center in centers]
            self.performanceHistogram.setOpts(x=centers, height=counts, width=width, brushes=brushes)
        else:
            self.performanceHistogram.setOpts(x=[], height=[], width=0.75)

        trade_filter = str(self.performanceTradeFilter.currentData() or "all")
        side_filter = str(self.performanceSideFilter.currentData() or "ALL")
        filtered = []
        for trade in snapshot["trades"]:
            status = str(trade.get("status") or "").upper()
            pnl = self._trade_pnl(trade)
            if side_filter != "ALL" and str(trade.get("side") or "").upper() != side_filter:
                continue
            if trade_filter == "profit" and pnl <= 0:
                continue
            if trade_filter == "loss" and pnl >= 0:
                continue
            if trade_filter == "open" and status != "OPEN":
                continue
            if trade_filter == "closed" and status != "CLOSED":
                continue
            if trade_filter == "flat" and abs(pnl) > 1e-12:
                continue
            filtered.append(trade)
        filtered.sort(key=lambda trade: str(trade.get("exit_bar_time_bjt") or trade.get("entry_bar_time_bjt") or ""), reverse=True)
        self.tradePnlTable.setSortingEnabled(False)
        self.tradePnlTable.setRowCount(len(filtered))
        for row, trade in enumerate(filtered):
            fees = _safe_float(trade.get("entry_fee_quote")) + _safe_float(trade.get("exit_fee_quote"))
            trade_pnl = self._trade_pnl(trade)
            trade_return = self._trade_return_pct(trade)
            values = (
                str(trade.get("side") or "-"),
                str(trade.get("entry_bar_time_bjt") or "-"),
                str(trade.get("exit_bar_time_bjt") or "-"),
                _fmt_money(_safe_float(trade.get("entry_fill_price"), float("nan"))),
                _fmt_money(_safe_float(trade.get("exit_fill_price"), float("nan"))),
                _fmt_money(self._trade_notional(trade)),
                _fmt_money(fees),
                _fmt_money(trade_pnl),
                _fmt_pct(trade_return),
                str(trade.get("holding_bars") or "-"),
                _fmt_money(_safe_float(trade.get("take_profit_price"), float("nan"))),
                _fmt_money(_safe_float(trade.get("stop_loss_price"), float("nan"))),
                str(trade.get("exit_reason") or "-"),
            )
            for col, value in enumerate(values):
                item = SortableTableItem(value)
                if col in {7, 8}:
                    signed_value = trade_pnl if col == 7 else trade_return
                    color = (
                        COLORS["success"]
                        if signed_value > 0
                        else COLORS["danger"]
                        if signed_value < 0
                        else COLORS["text_secondary"]
                    )
                    item.setForeground(QtGui.QBrush(QtGui.QColor(color)))
                self.tradePnlTable.setItem(row, col, item)
            self.tradePnlTable.item(row, 0).setData(QtCore.Qt.UserRole, str(trade.get("trade_id") or ""))
        self.tradePnlTable.setSortingEnabled(True)

    def _is_main_trading_tab_widget(self, widget: QtWidgets.QWidget) -> bool:
        owning_tabs = [
            tabs
            for tabs in (
                getattr(self.app_window, "rightTabs", None),
                getattr(self.app_window, "bottomTabs", None),
                getattr(self.app_window, "tradeResultsTabs", None),
                getattr(self.app_window, "eventResearchTabs", None),
            )
            if isinstance(tabs, QtWidgets.QTabWidget)
        ]
        current = widget
        while current is not None:
            if any(tabs.indexOf(current) >= 0 for tabs in owning_tabs):
                return True
            current = current.parentWidget()
        return False

    def _placeholder(self, text: str) -> QtWidgets.QWidget:
        placeholder = QtWidgets.QPlainTextEdit()
        placeholder.setReadOnly(True)
        placeholder.setPlainText(text)
        return placeholder

    def _localized_placeholder(self, key: str, owned_elsewhere: bool = False) -> QtWidgets.QWidget:
        placeholder = self._placeholder("")
        self._localized_placeholders.append((placeholder, key, owned_elsewhere))
        text = self._tr(key)
        if owned_elsewhere:
            text = f"{text}\n{self._tr('workspace.owned_elsewhere')}"
        placeholder.setPlainText(text)
        return placeholder

    def _existing_analysis_widget(self, name: str, empty_key: str) -> QtWidgets.QWidget:
        widget = getattr(self.app_window, name, None)
        if not isinstance(widget, QtWidgets.QWidget):
            return self._localized_placeholder(empty_key)
        # Lightweight migration only. These widgets should eventually become independent panels.
        # Do not reparent widgets that still belong to the main trading tabs.
        if self._is_main_trading_tab_widget(widget):
            return self._localized_placeholder(empty_key, owned_elsewhere=True)
        return widget

    def _scrollable_existing_widget(self, name: str, empty_key: str) -> QtWidgets.QWidget:
        widget = getattr(self.app_window, name, None)
        if not isinstance(widget, QtWidgets.QWidget):
            return self._localized_placeholder(empty_key)
        if self._is_main_trading_tab_widget(widget):
            return self._localized_placeholder(empty_key, owned_elsewhere=True)

        widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        scroll.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.AdjustIgnored)
        scroll.setWidget(widget)
        return scroll

    def _ai_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        self.aiText = QtWidgets.QPlainTextEdit()
        self.aiText.setReadOnly(True)
        layout.addWidget(self.aiText)
        return tab

    def _research_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        controls = QtWidgets.QHBoxLayout()
        self.selectedLabelText = QtWidgets.QLabel()
        self.selectedLabelBox = QtWidgets.QComboBox()
        self.selectedLabelBox.addItems(RESEARCH_LABELS)
        self.selectedLabelBox.setCurrentText("fwd_ret_10_side_adj")
        controls.addWidget(self.selectedLabelText)
        controls.addWidget(self.selectedLabelBox)
        self.btnRunResearch = QtWidgets.QPushButton()
        self.btnExportResearch = QtWidgets.QPushButton()
        self.btnOpenResearchFolder = QtWidgets.QPushButton()
        self.btnCopyResearchContext = QtWidgets.QPushButton()
        for button in (self.btnRunResearch, self.btnExportResearch, self.btnOpenResearchFolder, self.btnCopyResearchContext):
            button.setProperty("role", "secondaryButton")
            controls.addWidget(button)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.researchWarning = QtWidgets.QLabel()
        self.researchWarning.setWordWrap(True)
        self.researchWarning.setStyleSheet(f"color: {COLORS['warning']}; font-weight: 600;")
        layout.addWidget(self.researchWarning)
        self.researchTabs = QtWidgets.QTabWidget()
        self.auditTable = self._research_table(AUDIT_COLUMNS)
        self.researchEventTable = self._research_table(EVENT_STUDY_COLUMNS)
        self.factorBinningTable = self._research_table(FACTOR_BINNING_COLUMNS)
        self.factorIcTable = self._research_table(FACTOR_IC_COLUMNS)
        self.ruleTable = self._research_table(RULE_COLUMNS)
        self.walkForwardTable = self._research_table(WALK_FORWARD_COLUMNS)
        self.reportText = self._placeholder("")
        self.entryLogicTab = self._entry_logic_tab()
        for widget in (
            self.auditTable,
            self.researchEventTable,
            self.factorBinningTable,
            self.factorIcTable,
            self.ruleTable,
            self.walkForwardTable,
            self.reportText,
            self.entryLogicTab,
        ):
            self.researchTabs.addTab(widget, "")
        layout.addWidget(self.researchTabs, stretch=1)
        self.btnRunResearch.clicked.connect(self.run_research_analysis)
        self.btnExportResearch.clicked.connect(self.export_research_pack)
        self.btnOpenResearchFolder.clicked.connect(self.open_export_folder)
        self.btnCopyResearchContext.clicked.connect(self.copy_llm_context)
        self.btnRunEntryLogic.clicked.connect(self.run_entry_logic_report)
        self.btnExportEntryLogic.clicked.connect(self.export_entry_logic_report)
        self.entryReviewQueueTable.itemSelectionChanged.connect(self._on_entry_review_selection_changed)
        self.btnEntryPrevious.clicked.connect(lambda: self._move_entry_candidate("previous"))
        self.btnEntryNext.clicked.connect(lambda: self._move_entry_candidate("next"))
        self.btnMarkEntry.clicked.connect(lambda: self._save_entry_logic_annotation("ENTRY"))
        self.btnMarkReject.clicked.connect(lambda: self._save_entry_logic_annotation("REJECT"))
        self.btnMarkUncertain.clicked.connect(lambda: self._save_entry_logic_annotation("UNCERTAIN"))
        return tab

    def _entry_logic_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        tab.setMinimumHeight(0)
        tab.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Ignored)
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(0, SPACING["sm"], 0, 0)
        layout.setSpacing(SPACING["sm"])

        controls = QtWidgets.QHBoxLayout()
        self.btnRunEntryLogic = QtWidgets.QPushButton()
        self.btnExportEntryLogic = QtWidgets.QPushButton()
        for button in (self.btnRunEntryLogic, self.btnExportEntryLogic):
            button.setProperty("role", "secondaryButton")
            controls.addWidget(button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.entryLogicSummary = QtWidgets.QLabel()
        self.entryLogicSummary.setWordWrap(True)
        self.entryLogicSummary.setProperty("role", "muted")
        layout.addWidget(self.entryLogicSummary)

        self.entryLogicHint = QtWidgets.QLabel()
        self.entryLogicHint.setWordWrap(True)
        self.entryLogicHint.setStyleSheet(f"color: {COLORS['warning']}; font-weight: 600;")
        layout.addWidget(self.entryLogicHint)

        self.entryReviewQueueTable = self._research_table(ENTRY_REVIEW_QUEUE_COLUMNS)
        self.entryCandidateDetail = QtWidgets.QPlainTextEdit()
        self.entryCandidateDetail.setReadOnly(True)
        self.entryCandidateDetail.setMaximumHeight(96)
        self.entryFeatureText = QtWidgets.QPlainTextEdit()
        self.entryFeatureText.setReadOnly(True)
        self.entryFeatureText.setMaximumHeight(120)

        annotation_controls = QtWidgets.QHBoxLayout()
        self.btnEntryPrevious = QtWidgets.QPushButton(self._tr("entry_logic.previous"))
        self.btnEntryNext = QtWidgets.QPushButton(self._tr("entry_logic.next"))
        self.btnMarkEntry = QtWidgets.QPushButton(self._tr("entry_logic.entry"))
        self.btnMarkReject = QtWidgets.QPushButton(self._tr("entry_logic.reject"))
        self.btnMarkUncertain = QtWidgets.QPushButton(self._tr("entry_logic.uncertain"))
        self.entryConfidenceSpin = QtWidgets.QSpinBox()
        self.entryConfidenceSpin.setRange(1, 5)
        self.entryConfidenceSpin.setValue(3)
        self.entryReasonTagsEdit = QtWidgets.QLineEdit()
        self.entryReasonTagsEdit.setPlaceholderText(self._tr("entry_logic.reason_tags_placeholder"))
        for button in (self.btnEntryPrevious, self.btnEntryNext, self.btnMarkEntry, self.btnMarkReject, self.btnMarkUncertain):
            button.setProperty("role", "secondaryButton")
            annotation_controls.addWidget(button)
        annotation_controls.addWidget(QtWidgets.QLabel(self._tr("entry_logic.confidence")))
        annotation_controls.addWidget(self.entryConfidenceSpin)
        annotation_controls.addWidget(self.entryReasonTagsEdit, stretch=1)
        layout.addLayout(annotation_controls)
        self.entryNoteEdit = QtWidgets.QPlainTextEdit()
        self.entryNoteEdit.setPlaceholderText(self._tr("entry_logic.note"))
        self.entryNoteEdit.setMaximumHeight(72)

        self.entryLogicReportText = self._placeholder("")
        for widget in (self.entryReviewQueueTable, self.entryCandidateDetail, self.entryFeatureText, self.entryNoteEdit, self.entryLogicReportText):
            widget.setMinimumHeight(0)
            widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Ignored)
        layout.addWidget(self.entryReviewQueueTable, stretch=1)
        layout.addWidget(self.entryCandidateDetail)
        layout.addWidget(self.entryFeatureText)
        layout.addWidget(self.entryNoteEdit)
        layout.addWidget(self.entryLogicReportText, stretch=1)
        self._install_entry_logic_shortcuts(tab)
        return tab

    def _time_series_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        controls = QtWidgets.QHBoxLayout()
        self.btnRunTimeSeries = QtWidgets.QPushButton()
        self.btnExportTimeSeries = QtWidgets.QPushButton()
        self.btnCopyTimeSeries = QtWidgets.QPushButton()
        for button in (self.btnRunTimeSeries, self.btnExportTimeSeries, self.btnCopyTimeSeries):
            button.setProperty("role", "secondaryButton")
            controls.addWidget(button)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.timeSeriesHint = QtWidgets.QLabel()
        self.timeSeriesHint.setWordWrap(True)
        self.timeSeriesHint.setStyleSheet(f"color: {COLORS['warning']}; font-weight: 600;")
        layout.addWidget(self.timeSeriesHint)
        self.timeSeriesTabs = QtWidgets.QTabWidget()
        self.tsDistributionTable = self._research_table(AUDIT_COLUMNS)
        self.tsAcfTable = self._research_table(["lag", "acf", "sample_count"])
        self.tsVolatilityTable = self._research_table(AUDIT_COLUMNS)
        self.tsRiskTable = self._research_table(AUDIT_COLUMNS)
        self.tsMicrostructureTable = self._research_table(AUDIT_COLUMNS)
        self.tsFactorTable = self._research_table(AUDIT_COLUMNS)
        self.tsReportText = self._placeholder("")
        for widget in (
            self.tsDistributionTable,
            self.tsAcfTable,
            self.tsVolatilityTable,
            self.tsRiskTable,
            self.tsMicrostructureTable,
            self.tsFactorTable,
            self.tsReportText,
        ):
            self.timeSeriesTabs.addTab(widget, "")
        layout.addWidget(self.timeSeriesTabs, stretch=1)
        self.btnRunTimeSeries.clicked.connect(self.run_time_series_diagnostics)
        self.btnExportTimeSeries.clicked.connect(self.export_time_series_report)
        self.btnCopyTimeSeries.clicked.connect(self.copy_time_series_summary)
        return tab

    def _run_export_to(self, target: Path):
        session_id = getattr(self.app_window, "session_id", None)
        if not session_id:
            QtWidgets.QMessageBox.warning(self, self._tr("research.dialog_title"), self._tr("research.no_session"))
            return
        if hasattr(self.app_window, "start_export_task"):
            if self.app_window.start_export_task(
                target,
                self._research_export_finished,
                self._language(),
                self.selectedLabelBox.currentText(),
            ):
                self.reportText.setPlainText(self._tr("research.running"))
                self.researchWarning.setText(self._tr("research.running"))
            else:
                self.reportText.setPlainText(self._tr("research.task_busy"))
            return
        try:
            export_dir = self.app_window.exporter.export_session(
                session_id,
                target,
                language=self._language(),
                selected_label=self.selectedLabelBox.currentText(),
            )
            self.last_research_dir = Path(export_dir) / "research"
            self._load_research_views()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, self._tr("research.dialog_title"), f"{self._tr('research.failed')}: {exc}")

    def _research_export_finished(self, export_dir: Path):
        self.last_research_dir = Path(export_dir) / "research"
        self._load_research_views()

    def run_research_analysis(self):
        self._run_export_to(Path(EXPORT_DIR))

    def export_research_pack(self):
        target = QtWidgets.QFileDialog.getExistingDirectory(self, self._tr("research.export"), str(EXPORT_DIR))
        if target:
            self._run_export_to(Path(target))

    def _run_entry_logic_export_to(self, target: Path):
        session_id = getattr(self.app_window, "session_id", None)
        if not session_id:
            QtWidgets.QMessageBox.warning(self, self._entry_logic_title(), self._tr("research.no_session"))
            return
        if not hasattr(self.app_window, "start_export_task"):
            self.entryLogicHint.setText(self._tr("entry_logic.hint_no_backend"))
            return
        if self.app_window.start_export_task(
            target,
            self._entry_logic_export_finished,
            self._language(),
            self.selectedLabelBox.currentText(),
        ):
            self.entryLogicHint.setText(self._tr("entry_logic.hint_generating"))
        else:
            self.entryLogicHint.setText(self._tr("entry_logic.hint_export_busy"))

    def run_entry_logic_report(self):
        self._run_entry_logic_export_to(Path(EXPORT_DIR))

    def export_entry_logic_report(self):
        target = QtWidgets.QFileDialog.getExistingDirectory(self, self._entry_logic_export_title(), str(EXPORT_DIR))
        if target:
            self._run_entry_logic_export_to(Path(target))

    def _entry_logic_export_finished(self, export_dir: Path):
        self.last_entry_logic_dir = Path(export_dir)
        self._load_entry_logic_views()

    def _entry_logic_title(self) -> str:
        return self._tr("entry_logic.title")

    def _entry_logic_export_title(self) -> str:
        return self._tr("entry_logic.export_title")

    def _entry_logic_initial_hint(self) -> str:
        return self._tr("entry_logic.hint_signal")

    def _load_entry_logic_views(self):
        if self.last_entry_logic_dir is None:
            return
        directory = self.last_entry_logic_dir
        report = self._read_json_object(directory / "entry_logic_report.json")
        overview = report.get("annotation_overview") or {}
        entry_count = int(overview.get("ENTRY") or 0)
        reject_count = int(overview.get("REJECT") or 0)
        uncertain_count = int(overview.get("UNCERTAIN") or 0)
        unlabeled_count = int(overview.get("UNLABELED") or 0)
        total = entry_count + reject_count + uncertain_count + unlabeled_count
        self.entryLogicSummary.setText(
            self._tr("entry_logic.summary_fmt").format(
                total=total, entry_count=entry_count, reject_count=reject_count,
                uncertain_count=uncertain_count, unlabeled_count=unlabeled_count,
            )
        )

        queue_rows = self._read_csv_rows(directory / "entry_review_queue.csv")
        if not queue_rows:
            queue_rows = list(report.get("review_queue_top_k") or [])
        self._entry_review_queue_rows = self._normalize_entry_review_rows(queue_rows)
        self._entry_controller_for_queue().load_review_queue(self._entry_review_queue_rows)
        self._populate_entry_review_queue()

        self.last_entry_logic_report_text = self._read(directory / "entry_logic_report.md")
        if not self.last_entry_logic_report_text and report:
            self.last_entry_logic_report_text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
        self.entryLogicReportText.setPlainText(
            self.last_entry_logic_report_text or self._tr("entry_logic.report_not_available")
        )

        warnings = [str(item) for item in (report.get("warnings") or [])]
        if not report:
            warnings.append("entry_logic_report_missing")
        if warnings:
            self.entryLogicHint.setText(
                self._tr("entry_logic.hint_warning") + ": " + "; ".join(warnings)
            )
            self.entryLogicHint.setStyleSheet(f"color: {COLORS['warning']}; font-weight: 700;")
        else:
            self.entryLogicHint.setText(self._tr("entry_logic.hint_success"))
            self.entryLogicHint.setStyleSheet(f"color: {COLORS['green']}; font-weight: 600;")
        self._entry_logic_output_loaded = True

    def _entry_controller_for_queue(self) -> EntryAnnotationController:
        if self._entry_annotation_controller is None:
            repository = getattr(self.app_window, "storage", None)
            if repository is None:
                raise RuntimeError(self._tr("entry_logic.storage_unavailable"))
            self._entry_annotation_controller = EntryAnnotationController(
                EntryResearchService(repository=repository)
            )
        return self._entry_annotation_controller

    def _install_entry_logic_shortcuts(self, parent: QtWidgets.QWidget) -> None:
        for key in ("E", "R", "U", "N", "B", "1", "2", "3", "4", "5"):
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(key), parent)
            shortcut.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda key=key: self._handle_entry_logic_shortcut(key))

    def _handle_entry_logic_shortcut(self, key: str) -> bool:
        if self._entry_focus_is_text_entry():
            return False
        controller = self._entry_controller_for_queue()
        action = controller.handle_shortcut(key)
        if action is None:
            return False
        action_type, value = action
        if action_type == "decision":
            self._save_entry_logic_annotation(str(value))
        elif action_type == "navigate":
            self._select_entry_review_row(controller.current_candidate())
            self._jump_to_entry_candidate()
        elif action_type == "confidence":
            self.entryConfidenceSpin.setValue(int(value))
        self._refresh_entry_candidate_detail()
        return True

    def _entry_focus_is_text_entry(self) -> bool:
        widget = QtWidgets.QApplication.focusWidget()
        return isinstance(
            widget,
            (
                QtWidgets.QLineEdit,
                QtWidgets.QPlainTextEdit,
                QtWidgets.QTextEdit,
                QtWidgets.QSpinBox,
                QtWidgets.QDoubleSpinBox,
                QtWidgets.QComboBox,
            ),
        )

    def _normalize_entry_review_rows(self, rows: list[dict]) -> list[dict]:
        normalized: list[dict] = []
        for row in rows:
            item = dict(row)
            item.setdefault("session_id", getattr(self.app_window, "session_id", "") or "")
            item.setdefault("symbol", self._entry_host_text("symbolBox", "symbol"))
            item.setdefault("interval", self._entry_host_text("intervalBox", "interval"))
            if not item.get("decision_bar_index") and item.get("bar_index"):
                item["decision_bar_index"] = item.get("bar_index")
            if not item.get("setup_bar_index"):
                item["setup_bar_index"] = item.get("decision_bar_index")
            item.setdefault("decision_timing", "CURRENT_BAR_CLOSE")
            normalized.append(item)
        return normalized

    def _entry_host_text(self, widget_name: str, attr_name: str) -> str:
        widget = getattr(self.app_window, widget_name, None)
        if widget is not None and hasattr(widget, "currentText"):
            return str(widget.currentText() or "")
        return str(getattr(self.app_window, attr_name, "") or "")

    def _populate_entry_review_queue(self) -> None:
        controller = self._entry_controller_for_queue()
        self._populate_research_table(
            self.entryReviewQueueTable,
            controller.review_queue,
            ENTRY_REVIEW_QUEUE_COLUMNS,
            sort_column="human_entry_similarity",
        )
        self._refresh_entry_candidate_detail()
        if not controller.review_queue:
            self.entryLogicHint.setText(self._tr("entry_logic.no_candidates"))

    def _on_entry_review_selection_changed(self) -> None:
        observation_id = self._selected_entry_observation_id()
        if not observation_id:
            return
        controller = self._entry_controller_for_queue()
        for index, row in enumerate(controller.review_queue):
            if str(row.get("observation_id") or "") == observation_id:
                controller.current_index = index
                break
        self._refresh_entry_candidate_detail()
        self._jump_to_entry_candidate()

    def _selected_entry_observation_id(self) -> str | None:
        row = self.entryReviewQueueTable.currentRow()
        if row < 0:
            return None
        item = self.entryReviewQueueTable.item(row, 0)
        return item.text() if item is not None else None

    def _move_entry_candidate(self, direction: str) -> None:
        controller = self._entry_controller_for_queue()
        candidate = controller.move_previous() if direction == "previous" else controller.move_next()
        self._select_entry_review_row(candidate)
        self._refresh_entry_candidate_detail()
        self._jump_to_entry_candidate()

    def _select_entry_review_row(self, candidate: dict | None) -> None:
        if not candidate:
            return
        observation_id = str(candidate.get("observation_id") or "")
        for row in range(self.entryReviewQueueTable.rowCount()):
            item = self.entryReviewQueueTable.item(row, 0)
            if item is not None and item.text() == observation_id:
                self.entryReviewQueueTable.selectRow(row)
                return

    def _jump_to_entry_candidate(self) -> None:
        bar_index = self._entry_controller_for_queue().current_jump_bar_index()
        jump = getattr(self.app_window, "jump_to_bar", None)
        if bar_index is not None and callable(jump):
            jump(int(bar_index))

    def _refresh_entry_candidate_detail(self) -> None:
        controller = self._entry_controller_for_queue()
        candidate = controller.current_candidate()
        if candidate is None:
            self.entryCandidateDetail.setPlainText(self._tr("entry_logic.no_candidates"))
            self.entryFeatureText.setPlainText("")
            return
        detail = controller.current_candidate_detail()
        detail_lines = [
            f"observation_id: {detail.get('observation_id')}",
            f"symbol: {detail.get('symbol')} | interval: {detail.get('interval')}",
            f"setup_bar_index: {detail.get('setup_bar_index')} | decision_bar_index: {detail.get('decision_bar_index')}",
            f"decision_timing: {detail.get('decision_timing')}",
            f"candidate_reason: {detail.get('candidate_reason') or ''}",
        ]
        self.entryCandidateDetail.setPlainText("\n".join(detail_lines))
        features = detail.get("context_features") or {}
        feature_lines = [f"{key}: {value}" for key, value in sorted(features.items())]
        self.entryFeatureText.setPlainText("\n".join(feature_lines) or self._tr("entry_logic.context_features_empty"))

    def _entry_reason_tags(self) -> list[str]:
        text = self.entryReasonTagsEdit.text().strip()
        if not text:
            return []
        return [part.strip() for part in text.split(",") if part.strip()]

    def _save_entry_logic_annotation(self, human_decision: str) -> None:
        controller = self._entry_controller_for_queue()
        try:
            result = controller.save_current_annotation(
                human_decision,
                confidence=int(self.entryConfidenceSpin.value()),
                reason_tags=self._entry_reason_tags(),
                note=self.entryNoteEdit.toPlainText(),
                session_id=getattr(self.app_window, "session_id", None),
            )
        except ValueError as exc:
            self.entryLogicHint.setText(str(exc))
            return
        if not result.ok:
            self.entryLogicHint.setText(
                self._tr("entry_logic.save_failed") + f": {result.message}"
            )
            self.entryLogicHint.setStyleSheet(f"color: {COLORS['red']}; font-weight: 700;")
            return
        self.entryNoteEdit.clear()
        self.entryReasonTagsEdit.clear()
        self._populate_entry_review_queue()
        if controller.review_queue:
            self.entryLogicHint.setText(
                self._tr("entry_logic.save_success").format(decision=human_decision)
            )
            self.entryLogicHint.setStyleSheet(f"color: {COLORS['green']}; font-weight: 600;")
        else:
            self.entryLogicHint.setText(self._tr("entry_logic.no_candidates"))
            self.entryLogicHint.setStyleSheet(f"color: {COLORS['warning']}; font-weight: 700;")
    @staticmethod
    def _read(path: Path) -> str:
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def _headers(self, columns: list[str]) -> list[str]:
        return [self._tr(f"research.column.{column}", column) for column in columns]

    def _research_table(self, columns: list[str]) -> QtWidgets.QTableWidget:
        table = QtWidgets.QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(self._headers(columns))
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    @staticmethod
    def _format_cell(value) -> str:
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        return str(value)

    @staticmethod
    def _sort_value(value, absolute: bool = False):
        try:
            number = float(value)
            return (0, abs(number) if absolute else number)
        except (TypeError, ValueError):
            return (1, str(value or "").casefold())

    def _populate_research_table(
        self,
        table: QtWidgets.QTableWidget,
        rows: list[dict],
        columns: list[str],
        sort_column: str | None = None,
        absolute_sort: bool = False,
    ) -> None:
        table.setSortingEnabled(False)
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(self._headers(columns))
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, column in enumerate(columns):
                text = self._format_cell(row.get(column))
                item = SortableTableItem(text, self._sort_value(row.get(column), absolute_sort and column == sort_column))
                item.setToolTip(text)
                table.setItem(row_index, column_index, item)
        table.resizeColumnsToContents()
        table.setSortingEnabled(True)
        if sort_column in columns:
            table.sortItems(columns.index(sort_column), QtCore.Qt.DescendingOrder)

    @staticmethod
    def _read_csv_rows(path: Path) -> list[dict]:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    @staticmethod
    def _read_json_object(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _load_research_views(self):
        if self.last_research_dir is None:
            return
        directory = self.last_research_dir
        audit_path = directory / "data_audit.json"
        audit = self._read_json_object(audit_path)
        self._populate_research_table(
            self.auditTable,
            [{"metric": self._tr(f"research.column.{metric}", metric), "value": audit.get(metric)} for metric in AUDIT_METRICS],
            AUDIT_COLUMNS,
        )
        self._populate_research_table(
            self.researchEventTable,
            self._read_csv_rows(directory / "event_study_summary.csv"),
            EVENT_STUDY_COLUMNS,
            sort_column="sample_count",
        )
        self._populate_research_table(
            self.factorBinningTable,
            self._read_csv_rows(directory / "factor_binning_summary.csv"),
            FACTOR_BINNING_COLUMNS,
        )
        self._populate_research_table(
            self.factorIcTable,
            self._read_csv_rows(directory / "factor_ic_summary.csv"),
            FACTOR_IC_COLUMNS,
            sort_column="spearman_rank_ic",
            absolute_sort=True,
        )
        rule_rows = self._read_csv_rows(directory / "candidate_rules.csv")
        self._candidate_rule_rows = rule_rows
        rule_sort_column = "test_score" if any(str(row.get("test_score", "")).strip() for row in rule_rows) else "sample_count"
        self._populate_research_table(self.ruleTable, rule_rows, RULE_COLUMNS, sort_column=rule_sort_column)
        self._populate_research_table(
            self.walkForwardTable,
            self._read_csv_rows(directory / "walk_forward_results.csv"),
            WALK_FORWARD_COLUMNS,
        )
        self.reportText.setPlainText(self._read(directory / "research_report.md") or self._tr("research.no_report"))
        leakage_status = str(audit.get("leakage_audit_status") or self._tr("research.status_unknown"))
        sample_warning = str(audit.get("small_sample_warning") or self._tr("research.sample_status_unavailable"))
        self.researchWarning.setText(self._tr("research.warning_status").format(status=leakage_status, warning=sample_warning))
        self._research_output_loaded = True
        warning_lower = sample_warning.lower()
        if leakage_status != "PASS" or "severe" in warning_lower:
            warning_style = f"color: {COLORS['red']}; font-weight: 700;"
        elif "exploratory" in warning_lower or "initial analysis" in warning_lower:
            warning_style = f"color: {COLORS['warning']}; font-weight: 700;"
        else:
            warning_style = f"color: {COLORS['green']}; font-weight: 600;"
        self.researchWarning.setStyleSheet(warning_style)

    def selected_candidate_rule_params(self) -> dict | None:
        if not self._candidate_rule_rows:
            return None
        row_index = self.ruleTable.currentRow()
        row_index = row_index if row_index >= 0 else 0
        readable_item = self.ruleTable.item(row_index, RULE_COLUMNS.index("readable_rule"))
        readable_rule = readable_item.text() if readable_item is not None else ""
        selected = next(
            (
                row
                for row in self._candidate_rule_rows
                if str(row.get("readable_rule") or "") == readable_rule
            ),
            self._candidate_rule_rows[min(row_index, len(self._candidate_rule_rows) - 1)],
        )
        values = {
            key: value
            for key, value in selected.items()
            if key in BACKTEST_PARAM_SOURCE_FIELDS and str(value).strip()
        }
        return values or None

    def open_export_folder(self):
        if self.last_research_dir is not None and self.last_research_dir.exists():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self.last_research_dir)))

    def copy_llm_context(self):
        if self.last_research_dir is not None:
            QtWidgets.QApplication.clipboard().setText(self._read(self.last_research_dir / "research_report.md"))

    def _time_series_frame(self):
        return getattr(self.app_window, "df", None)

    def run_time_series_diagnostics(self):
        frame = self._time_series_frame()
        if frame is None or getattr(frame, "empty", True):
            QtWidgets.QMessageBox.warning(self, self._tr("time_series.workspace"), self._tr("time_series.no_data"))
            return
        try:
            from time_series_analysis.report import build_time_series_report, write_time_series_report

            interval = str(getattr(self.app_window, "interval", "") or "")
            self.last_time_series_summary = build_time_series_report(frame, interval=interval)
            report_path = Path(EXPORT_DIR) / "time_series_live_report.md"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            write_time_series_report(self.last_time_series_summary, report_path, language=self._language())
            self.last_time_series_report_text = report_path.read_text(encoding="utf-8")
            self._populate_time_series_views()
        except Exception as exc:
            logger.exception("Time-series diagnostics failed")
            QtWidgets.QMessageBox.critical(self, self._tr("time_series.workspace"), f"{self._tr('time_series.failed')}: {exc}")

    def _metric_rows(self, values: dict) -> list[dict]:
        from time_series_analysis.report import localized_payload

        return [
            {"metric": self._tr(f"time_series.metric.{key}", key), "value": localized_payload(value, self._language())}
            for key, value in values.items()
        ]

    def _populate_time_series_views(self):
        summary = self.last_time_series_summary or {}
        from time_series_analysis.report import localized_warning

        self._populate_research_table(self.tsDistributionTable, self._metric_rows(summary.get("distribution_diagnostics") or {}), AUDIT_COLUMNS)
        self._populate_research_table(self.tsAcfTable, summary.get("acf") or [], ["lag", "acf", "sample_count"])
        self._populate_research_table(self.tsVolatilityTable, self._metric_rows(summary.get("volatility_diagnostics") or {}), AUDIT_COLUMNS)
        self._populate_research_table(self.tsRiskTable, self._metric_rows(summary.get("risk_metrics") or {}), AUDIT_COLUMNS)
        self._populate_research_table(self.tsMicrostructureTable, self._metric_rows(summary.get("microstructure_diagnostics") or {}), AUDIT_COLUMNS)
        factor = summary.get("factor_model") or {}
        if factor.get("available") is False:
            factor_rows = [{"metric": self._tr("time_series.metric.status"), "value": self._tr("time_series.pca_unavailable")}]
        else:
            factor_rows = self._metric_rows(factor)
        self._populate_research_table(self.tsFactorTable, factor_rows, AUDIT_COLUMNS)
        self.tsReportText.setPlainText(self.last_time_series_report_text or self._tr("time_series.report_empty"))
        displayed_warnings = [localized_warning(message, self._language()) for message in summary.get("warnings") or []]
        self.timeSeriesHint.setText("; ".join(displayed_warnings) or self._tr("time_series.initial_hint"))

    def export_time_series_report(self):
        if not self.last_time_series_summary:
            self.run_time_series_diagnostics()
        if not self.last_time_series_summary:
            return
        target = QtWidgets.QFileDialog.getExistingDirectory(self, self._tr("time_series.export"), str(EXPORT_DIR))
        if not target:
            return
        try:
            from time_series_analysis.report import write_time_series_report

            directory = Path(target)
            (directory / "time_series_summary.json").write_text(
                json.dumps(self.last_time_series_summary, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            path = write_time_series_report(self.last_time_series_summary, directory / "time_series_report.md", language=self._language())
            self.last_time_series_report_text = path.read_text(encoding="utf-8")
            self.tsReportText.setPlainText(self.last_time_series_report_text)
        except Exception as exc:
            logger.exception("Time-series report export failed")
            QtWidgets.QMessageBox.critical(self, self._tr("time_series.workspace"), f"{self._tr('time_series.export_failed')}: {exc}")

    def copy_time_series_summary(self):
        if self.last_time_series_report_text:
            QtWidgets.QApplication.clipboard().setText(self.last_time_series_report_text)

    def retranslate_ui(self):
        self.setWindowTitle(self._tr("data_analysis"))
        self.titleLabel.setText(self._tr("data_analysis"))
        self.btnRefresh.setText(self._tr("refresh"))
        self.tabs.setTabText(self.tabs.indexOf(self.performanceTab), self._tr("trading_performance"))
        self.tabs.setTabText(self.tabs.indexOf(self.eventStudyTab), self._tr("event_study"))
        self.tabs.setTabText(self.tabs.indexOf(self.consistencyTab), self._tr("strategy_consistency"))
        self.tabs.setTabText(self.tabs.indexOf(self.backtestTab), self._tr("backtest_research"))
        self.tabs.setTabText(self.tabs.indexOf(self.premiumTab), self._tr("usdt_premium"))
        self.tabs.setTabText(self.tabs.indexOf(self.aiTab), self._tr("ai_summary"))
        self.tabs.setTabText(self.tabs.indexOf(self.researchTab), self._tr("research.pipeline"))
        self.tabs.setTabText(self.tabs.indexOf(self.timeSeriesTab), self._tr("time_series.workspace"))
        self.performanceHistogramTitle.setText(self._tr("performance.histogram.title"))
        self.performanceHistogramDefinition.setText(self._tr("performance.histogram.definition"))
        self.performanceHistogramPlot.setLabel(
            "bottom", self._tr("performance.histogram.x_axis")
        )
        self.performanceHistogramPlot.setLabel(
            "left", self._tr("performance.histogram.y_axis")
        )
        self.eventTabs.setTabText(self.eventTabs.indexOf(self.eventStudyTableTab), self._tr("event_study"))
        self.eventTabs.setTabText(self.eventTabs.indexOf(self.datasetTab), self._tr("dataset"))
        self.btnRunResearch.setText(self._tr("research.run"))
        self.selectedLabelText.setText(self._tr("research.selected_label"))
        self.btnExportResearch.setText(self._tr("research.export"))
        self.btnOpenResearchFolder.setText(self._tr("research.open_folder"))
        self.btnCopyResearchContext.setText(self._tr("research.copy_context"))
        self.researchTabs.setTabText(0, self._tr("research.tab.data_audit"))
        self.researchTabs.setTabText(1, self._tr("research.tab.event_study"))
        self.researchTabs.setTabText(2, self._tr("research.tab.factor_binning"))
        self.researchTabs.setTabText(3, self._tr("research.tab.factor_ic"))
        self.researchTabs.setTabText(4, self._tr("research.tab.candidate_rules"))
        self.researchTabs.setTabText(5, self._tr("research.tab.walk_forward"))
        self.researchTabs.setTabText(6, self._tr("research.tab.report"))
        self.researchTabs.setTabText(7, self._entry_logic_title())
        self.btnRunEntryLogic.setText(self._tr("entry_logic.generate_report"))
        self.btnExportEntryLogic.setText(self._entry_logic_export_title())
        self.btnEntryPrevious.setText(self._tr("entry_logic.previous"))
        self.btnEntryNext.setText(self._tr("entry_logic.next"))
        self.btnMarkEntry.setText(self._tr("entry_logic.entry"))
        self.btnMarkReject.setText(self._tr("entry_logic.reject"))
        self.btnMarkUncertain.setText(self._tr("entry_logic.uncertain"))
        self.entryReviewQueueTable.setHorizontalHeaderLabels(self._headers(ENTRY_REVIEW_QUEUE_COLUMNS))
        for table, columns in (
            (self.auditTable, AUDIT_COLUMNS),
            (self.researchEventTable, EVENT_STUDY_COLUMNS),
            (self.factorBinningTable, FACTOR_BINNING_COLUMNS),
            (self.factorIcTable, FACTOR_IC_COLUMNS),
            (self.ruleTable, RULE_COLUMNS),
            (self.walkForwardTable, WALK_FORWARD_COLUMNS),
        ):
            table.setHorizontalHeaderLabels(self._headers(columns))
        if not self._research_output_loaded:
            self.researchWarning.setText(self._tr("research.initial_warning"))
            self.reportText.setPlainText(self._tr("research.no_report"))
        if not self._entry_logic_output_loaded:
            self.entryLogicSummary.setText(self._tr("entry_logic.summary_empty"))
            self.entryLogicHint.setText(self._entry_logic_initial_hint())
            self.entryLogicReportText.setPlainText(self._tr("entry_logic.report_not_available"))
            self.entryCandidateDetail.setPlainText(self._tr("entry_logic.no_candidates"))
            self.entryFeatureText.setPlainText("")
        self.btnRunTimeSeries.setText(self._tr("time_series.run"))
        self.btnExportTimeSeries.setText(self._tr("time_series.export"))
        self.btnCopyTimeSeries.setText(self._tr("time_series.copy"))
        self.timeSeriesTabs.setTabText(0, self._tr("time_series.tab.distribution"))
        self.timeSeriesTabs.setTabText(1, self._tr("time_series.tab.autocorrelation"))
        self.timeSeriesTabs.setTabText(2, self._tr("time_series.tab.volatility"))
        self.timeSeriesTabs.setTabText(3, self._tr("time_series.tab.risk"))
        self.timeSeriesTabs.setTabText(4, self._tr("time_series.tab.microstructure"))
        self.timeSeriesTabs.setTabText(5, self._tr("time_series.tab.factor"))
        self.timeSeriesTabs.setTabText(6, self._tr("time_series.tab.report"))
        self.tsAcfTable.setHorizontalHeaderLabels(
            [self._tr("time_series.column.lag"), self._tr("time_series.column.acf"), self._tr("time_series.column.sample_count")]
        )
        if not self.last_time_series_summary:
            self.timeSeriesHint.setText(self._tr("time_series.initial_hint"))
            self.tsReportText.setPlainText(self._tr("time_series.report_empty"))
        for placeholder, key, owned_elsewhere in self._localized_placeholders:
            text = self._tr(key)
            if owned_elsewhere:
                text = f"{text}\n{self._tr('workspace.owned_elsewhere')}"
            placeholder.setPlainText(text)
        self.aiText.setPlainText(self._tr("workspace.ai_message"))
        self.refresh()

    def refresh(self):
        session_id = getattr(self.app_window, "session_id", None)
        self.sessionLabel.setText(self._tr("workspace.session").format(session_id=session_id) if session_id else self._tr("no_session_data"))
        for method_name in ("_refresh_tables", "_refresh_performance_summary", "_refresh_premium_plot"):
            method = getattr(self.app_window, method_name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    logger.exception("Analysis workspace refresh failed: %s", method_name)
        self._refresh_performance_workspace()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
