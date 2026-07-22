from __future__ import annotations

import csv
import bisect
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from app_config import EXPORT_DIR
from app_i18n import tr
from app_logger import get_logger
from analytics.metrics import max_drawdown, payoff_ratio, profit_factor, sharpe_ratio
from performance_analysis import (
    build_performance_snapshot,
    smooth_curve_values,
    split_signed_curve,
)
from ui_style import COLORS, SPACING, normalize_theme_settings
from controllers.entry_annotation_controller import EntryAnnotationController
from controllers.entry_blind_review_controller import EntryBlindReviewController
from controllers.exit_blind_review_controller import ExitBlindReviewController
from controllers.entry_candidate_scan_controller import EntryCandidateScanController
from controllers.exit_candidate_scan_controller import ExitCandidateScanController
from controllers.entry_behavior_training_controller import (
    EntryBehaviorTrainingController,
)
from controllers.entry_outcome_comparison_controller import (
    EntryOutcomeComparisonController,
)
from controllers.research_snapshot_controller import (
    ResearchSnapshotController,
    ResearchSnapshotPublishRequest,
)
from controllers.historical_performance_controller import HistoricalPerformanceController
from services.entry_research_service import EntryResearchService
from services.entry_blind_review import (
    EntryBlindReviewService,
    supports_entry_blind_review_storage,
)
from services.exit_blind_review import (
    ExitBlindReviewService,
    supports_exit_blind_review_storage,
)
from services.entry_structural_similarity import (
    EntryStructuralSimilarityService,
    supports_entry_similarity_storage,
)
from services.entry_candidate_generation import (
    EntryCandidateGenerationService,
    supports_entry_candidate_storage,
)
from services.exit_candidate_generation import (
    ExitCandidateGenerationService,
    supports_exit_candidate_storage,
)
from services.entry_behavior_training import (
    EntryBehaviorTrainingService,
    supports_entry_behavior_training_storage,
)
from services.entry_outcome_comparison import (
    EntryOutcomeComparisonService,
    supports_entry_outcome_storage,
)
from services.exit_outcome_comparison import (
    ExitOutcomeComparisonService,
    supports_exit_outcome_storage,
)
from services.research_snapshots import (
    ResearchSnapshotService,
    supports_research_snapshot_storage,
)
from services.decision_research_coordinator import (
    DecisionResearchCoordinator,
    DecisionResearchRequest,
    ResearchSnapshotInputAssembler,
)
from services.analysis_refresh import PerformanceWorkspacePayload
from services.research_data_availability import ResearchRangeRequest
from services.session_service import list_performance_session_options
from research.research_snapshot import (
    ResearchSnapshotDraft,
    ResearchSnapshotInput,
)
from research.setups import SetupLibrary
from views.performance_trade_table import (
    PerformanceTradeRow,
    PerformanceTradeTableModel,
    PerformanceTradeTableView,
)
from views.plot_lifecycle import (
    close_parent_owned_graphics_view,
    prepare_plot_for_shutdown,
)
from views.wheel_guard import install_no_wheel_on_value_inputs
from views.decision_research_workspace import DecisionResearchWorkspace
from views.episode_correction_dialog import (
    EpisodeMergeRequest,
    EpisodeSplitRequest,
    request_episode_correction,
)
from startup import mark_startup_stage


logger = get_logger(__name__)

BJT = timezone(timedelta(hours=8))


class _ManagedAnalysisPlotWidget(pg.PlotWidget):
    """Make explicit pyqtgraph shutdown safe under later Qt parent teardown."""

    def __init__(self, parent=None, **kwargs) -> None:
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


def _curve_timestamp(row: dict, fallback: int) -> float:
    value = row.get("time") or row.get("created_at")
    if value is None:
        return float(fallback)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=BJT)
        return parsed.timestamp()
    except (TypeError, ValueError, OSError):
        return float(fallback)

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
    def __init__(self, app_window, parent=None, *, embedded: bool = False):
        super().__init__(parent or app_window)
        self.app_window = app_window
        self._theme_settings = normalize_theme_settings(
            getattr(app_window, "theme_settings", None)
        )
        self.embedded = bool(embedded)
        if self.embedded:
            self.setWindowFlags(QtCore.Qt.Widget)
        else:
            self.resize(1180, 760)
        self.setSizeGripEnabled(not self.embedded)
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
        self._performance_payload = getattr(app_window, "_analysis_performance_payload", None)
        self._historical_performance_payloads: dict[str, PerformanceWorkspacePayload] = {}
        self._historical_performance_empty_states: dict[str, str] = {}
        self._historical_performance_requested_session_id: str | None = None
        self._performance_trade_rows: tuple[dict, ...] = ()
        self._research_backfill_controller = getattr(
            app_window,
            "research_backfill_controller",
            None,
        )
        storage = getattr(app_window, "storage", None)
        self.setup_library = (
            SetupLibrary(storage)
            if storage is not None
            and all(
                hasattr(storage, method)
                for method in (
                    "create_setup_with_version",
                    "get_setup",
                    "get_setup_version",
                    "list_setups",
                    "list_setup_versions",
                )
            )
            else None
        )
        self.decision_research_coordinator = (
            DecisionResearchCoordinator(storage)
            if self.setup_library is not None
            else None
        )
        self.research_snapshot_input_assembler = (
            ResearchSnapshotInputAssembler(storage)
            if self.decision_research_coordinator is not None
            else None
        )
        self._decision_research_contexts = {"entry": None, "exit": None}
        self.entry_blind_review_controller = (
            EntryBlindReviewController(EntryBlindReviewService(storage))
            if supports_entry_blind_review_storage(storage)
            else None
        )
        self.exit_blind_review_controller = (
            ExitBlindReviewController(ExitBlindReviewService(storage))
            if supports_exit_blind_review_storage(storage)
            else None
        )
        self.entry_similarity_service = (
            EntryStructuralSimilarityService(storage)
            if supports_entry_similarity_storage(storage)
            else None
        )
        self.entry_candidate_service = (
            EntryCandidateGenerationService(storage)
            if supports_entry_candidate_storage(storage)
            else None
        )
        self.entry_candidate_controller = (
            EntryCandidateScanController(
                self.entry_candidate_service,
                lifecycle=getattr(app_window, "task_lifecycle", None),
                parent=self,
            )
            if self.entry_candidate_service is not None
            else None
        )
        self.exit_candidate_service = (
            ExitCandidateGenerationService(storage)
            if supports_exit_candidate_storage(storage)
            else None
        )
        self.exit_candidate_controller = (
            ExitCandidateScanController(
                self.exit_candidate_service,
                lifecycle=getattr(app_window, "task_lifecycle", None),
                parent=self,
            )
            if self.exit_candidate_service is not None
            else None
        )
        self.entry_behavior_training_service = (
            EntryBehaviorTrainingService(storage)
            if supports_entry_behavior_training_storage(storage)
            else None
        )
        self.entry_behavior_training_controller = (
            EntryBehaviorTrainingController(
                self.entry_behavior_training_service,
                lifecycle=getattr(app_window, "task_lifecycle", None),
                parent=self,
            )
            if self.entry_behavior_training_service is not None
            else None
        )
        self.entry_outcome_comparison_service = (
            EntryOutcomeComparisonService(storage)
            if supports_entry_outcome_storage(storage)
            else None
        )
        self.entry_outcome_comparison_controller = (
            EntryOutcomeComparisonController(
                self.entry_outcome_comparison_service,
                lifecycle=getattr(app_window, "task_lifecycle", None),
                parent=self,
            )
            if self.entry_outcome_comparison_service is not None
            else None
        )
        self.exit_outcome_comparison_service = (
            ExitOutcomeComparisonService(storage)
            if supports_exit_outcome_storage(storage)
            else None
        )
        self.exit_outcome_comparison_controller = (
            EntryOutcomeComparisonController(
                self.exit_outcome_comparison_service,
                lifecycle=getattr(app_window, "task_lifecycle", None),
                task_name="exit_outcome_comparison",
                parent=self,
            )
            if self.exit_outcome_comparison_service is not None
            else None
        )
        self.research_snapshot_service = (
            ResearchSnapshotService(
                storage=storage,
                export_root=Path(EXPORT_DIR) / "research_snapshots",
            )
            if supports_research_snapshot_storage(storage)
            else None
        )
        self.research_snapshot_controller = (
            ResearchSnapshotController(
                self.research_snapshot_service,
                lifecycle=getattr(app_window, "task_lifecycle", None),
                parent=self,
            )
            if self.research_snapshot_service is not None
            else None
        )
        self._research_snapshot_input = None
        db_path = getattr(storage, "db_path", None)
        self.historical_performance_controller = (
            HistoricalPerformanceController(
                db_path=db_path,
                lifecycle=getattr(app_window, "task_lifecycle", None),
                parent=self,
            )
            if db_path
            else None
        )
        if self.historical_performance_controller is not None:
            self.historical_performance_controller.resultReady.connect(
                self._on_historical_performance_result
            )
            self.historical_performance_controller.failed.connect(
                self._on_historical_performance_failed
            )
        self._build_ui()
        install_no_wheel_on_value_inputs(self)
        self.retranslate_ui()
        self.apply_theme(self._theme_settings)

    def apply_theme(self, theme: dict | None) -> None:
        """Apply one theme to every Qt and chart surface in the workspace."""

        self._theme_settings = normalize_theme_settings(theme)
        self._apply_button_theme(self._theme_settings)
        self._apply_plot_theme(self._theme_settings)

    def _apply_plot_theme(self, theme: dict | None = None) -> None:
        theme = normalize_theme_settings(
            theme
            if theme is not None
            else getattr(self.app_window, "theme_settings", None)
        )
        grid_alpha = max(0.0, min(1.0, theme["grid_alpha"] / 100.0))
        for plot in (self.equityCurvePlot, self.performanceHistogramPlot):
            plot.setBackground(theme["chart_bg"])
            plot.showGrid(x=True, y=True, alpha=grid_alpha)
            item = plot.getPlotItem()
            for side in ("left", "bottom", "right", "top"):
                axis = item.getAxis(side)
                if axis is not None:
                    axis.setPen(pg.mkPen(theme["chart_axis"]))
                    axis.setTextPen(pg.mkPen(theme["chart_axis"]))
        self.equityCurve.setPen(pg.mkPen(theme["success"], width=2))
        self.performanceBaseline.setPen(
            pg.mkPen(theme["text_tertiary"], style=QtCore.Qt.DashLine)
        )
        self.performanceCurveStateLabel.setStyleSheet(
            f"color: {theme['text_secondary']}; background: transparent;"
        )

    def _apply_button_theme(self, theme: dict | None = None) -> None:
        """Give every button/input in the analysis panel the themed pill look."""
        theme = (
            theme
            if theme is not None
            else getattr(self.app_window, "theme_settings", None)
        )
        if theme is None:
            return
        self.decisionResearchWorkspace.apply_theme(theme)
        backtest_panel = getattr(self.app_window, "backtestPanel", None)
        apply_backtest_theme = getattr(backtest_panel, "apply_theme", None)
        if callable(apply_backtest_theme):
            apply_backtest_theme(theme)
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
            logger.exception("Failed to apply analysis control theme")

    def _language(self) -> str:
        return str(getattr(self.app_window, "current_language", "zh_CN") or "zh_CN")

    def _tr(self, key: str, default: str | None = None) -> str:
        return tr(key, self._language(), default)

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        margin = SPACING["md"] if self.embedded else SPACING["lg"]
        root.setContentsMargins(margin, margin, margin, margin)
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
        self.decisionResearchWorkspace = DecisionResearchWorkspace(
            language=self._language(),
            setup_library=self.setup_library,
            entry_review_controller=self.entry_blind_review_controller,
            exit_review_controller=self.exit_blind_review_controller,
            similarity_service=self.entry_similarity_service,
            candidate_service=self.entry_candidate_service,
            candidate_controller=self.entry_candidate_controller,
            exit_candidate_service=self.exit_candidate_service,
            exit_candidate_controller=self.exit_candidate_controller,
            behavior_training_service=(
                self.entry_behavior_training_service
            ),
            behavior_training_controller=(
                self.entry_behavior_training_controller
            ),
            outcome_comparison_service=(
                self.entry_outcome_comparison_service
            ),
            outcome_comparison_controller=(
                self.entry_outcome_comparison_controller
            ),
            exit_outcome_comparison_service=(
                self.exit_outcome_comparison_service
            ),
            exit_outcome_comparison_controller=(
                self.exit_outcome_comparison_controller
            ),
            parent=self,
        )
        self._bind_decision_research_data()
        self.decisionResearchTab = self.decisionResearchWorkspace
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
        self.tabs.addTab(self.decisionResearchTab, "")
        self.tabs.addTab(self.consistencyTab, "")
        self.tabs.addTab(self.backtestTab, "")
        self.tabs.addTab(self.premiumTab, "")
        self.tabs.addTab(self.aiTab, "")
        self.tabs.addTab(self.researchTab, "")
        self.tabs.addTab(self.timeSeriesTab, "")
        self.tabs.currentChanged.connect(self._ensure_lazy_analysis_panel)
        root.addWidget(self.tabs, stretch=1)

    def _performance_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        page_layout = QtWidgets.QVBoxLayout(page)
        page_layout.setContentsMargins(
            SPACING["md"],
            SPACING["md"],
            SPACING["md"],
            SPACING["md"],
        )
        page_layout.setSpacing(SPACING["md"])
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
        page_layout.addLayout(controls)

        self.performanceContentScroll = QtWidgets.QScrollArea()
        self.performanceContentScroll.setWidgetResizable(True)
        self.performanceContentScroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.performanceContentScroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarAlwaysOff
        )
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING["md"])

        summary = QtWidgets.QFrame()
        summary.setProperty("role", "statusBlock")
        summary_l = QtWidgets.QVBoxLayout(summary)
        summary_l.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        summary_l.setSpacing(SPACING["md"])
        self.performanceMetricLabels = {}
        self.performanceMetricCards = {}
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
        for metric_defs, primary, columns in ((primary_metrics, True, 4), (secondary_metrics, False, 3)):
            row_layout = QtWidgets.QGridLayout()
            row_layout.setHorizontalSpacing(SPACING["xl"])
            row_layout.setVerticalSpacing(SPACING["md"])
            for index, (key, label_key) in enumerate(metric_defs):
                block = QtWidgets.QFrame()
                block.setProperty("role", "metricBlock")
                block_l = QtWidgets.QVBoxLayout(block)
                block_l.setContentsMargins(SPACING["md"], SPACING["sm"], SPACING["md"], SPACING["sm"])
                block_l.setSpacing(SPACING["xs"])
                name = QtWidgets.QLabel(self._tr(label_key))
                name.setProperty("role", "performanceLabel")
                name.setAlignment(QtCore.Qt.AlignCenter)
                value = QtWidgets.QLabel("-")
                value.setProperty("role", "metricValue" if primary else "statusValue")
                value.setAlignment(QtCore.Qt.AlignCenter)
                self.performanceMetricLabels[key] = value
                self.performanceMetricCards[key] = block
                block_l.addWidget(name)
                block_l.addWidget(value)
                row_layout.addWidget(block, index // columns, index % columns)
            summary_l.addLayout(row_layout)
        layout.addWidget(summary)

        self.equityCurvePlot = _ManagedAnalysisPlotWidget(
            axisItems={"bottom": pg.DateAxisItem(orientation="bottom")}
        )
        self.equityCurvePlot.setMinimumHeight(280)
        self.equityCurvePlot.showGrid(x=True, y=True, alpha=0.16)
        self.equityCurvePlot.setMouseEnabled(x=True, y=True)
        self.equityCurvePlot.setAntialiasing(True)
        self.performanceCurveStateLabel = QtWidgets.QLabel(self.equityCurvePlot)
        self.performanceCurveStateLabel.setProperty("role", "muted")
        self.performanceCurveStateLabel.setAlignment(QtCore.Qt.AlignCenter)
        self.performanceCurveStateLabel.setWordWrap(True)
        self.performanceCurveStateLabel.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.performanceCurveStateLabel.setStyleSheet("background: transparent;")
        self.performanceCurveStateLabel.setGeometry(self.equityCurvePlot.rect())
        self.performanceCurveStateLabel.hide()
        self.equityCurvePlot.installEventFilter(self)
        self.equityCurve = self.equityCurvePlot.plot([], [], pen=pg.mkPen(COLORS["accent"], width=2))
        self.performanceCurveItems: list[pg.PlotDataItem] = []
        self.performanceBaseline = pg.InfiniteLine(angle=0, pen=pg.mkPen(COLORS["text_tertiary"], style=QtCore.Qt.DashLine))
        self.equityCurvePlot.addItem(self.performanceBaseline)
        self.performanceSinglePoint = pg.ScatterPlotItem(size=10, pxMode=True)
        self.performanceSinglePoint.setZValue(5)
        self.equityCurvePlot.addItem(self.performanceSinglePoint)
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
        self.performanceTradeFilter.currentIndexChanged.connect(self._refresh_performance_trade_table)
        self.performanceSideFilter.currentIndexChanged.connect(self._refresh_performance_trade_table)
        filter_row.addWidget(self.performanceTradeFilter)
        filter_row.addWidget(self.performanceSideFilter)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        trade_headers = [self._tr(f"performance.trade.{key}") for key in (
            "trade_number", "side", "entry_time", "exit_time", "entry_price", "exit_price", "notional",
            "fees", "pnl", "return", "holding", "take_profit", "stop_loss", "exit_reason",
        )]
        self.tradePnlTable = PerformanceTradeTableView()
        self.performanceTradeModel = PerformanceTradeTableModel(
            trade_headers,
            parent=self.tradePnlTable,
        )
        self.tradePnlTable.setModel(self.performanceTradeModel)
        self.tradePnlTable.verticalHeader().setVisible(False)
        self.tradePnlTable.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.tradePnlTable.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tradePnlTable.setAlternatingRowColors(True)
        self.tradePnlTable.setSortingEnabled(True)
        self.tradePnlTable.setMinimumHeight(260)
        self.tradePnlTable.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.tradePnlTable, stretch=2)
        page_row = QtWidgets.QHBoxLayout()
        page_row.addStretch(1)
        self.performanceTradePrevious = QtWidgets.QPushButton("‹")
        self.performanceTradeNext = QtWidgets.QPushButton("›")
        self.performanceTradePageLabel = QtWidgets.QLabel("1 / 1")
        self.performanceTradePrevious.clicked.connect(self.performanceTradeModel.previous_page)
        self.performanceTradeNext.clicked.connect(self.performanceTradeModel.next_page)
        self.performanceTradeModel.pageChanged.connect(self._on_performance_trade_page_changed)
        page_row.addWidget(self.performanceTradePrevious)
        page_row.addWidget(self.performanceTradePageLabel)
        page_row.addWidget(self.performanceTradeNext)
        layout.addLayout(page_row)

        distribution = QtWidgets.QFrame()
        distribution.setProperty("role", "statusBlock")
        distribution_l = QtWidgets.QHBoxLayout(distribution)
        stats = QtWidgets.QGridLayout()
        stats.setHorizontalSpacing(SPACING["lg"])
        stats.setVerticalSpacing(SPACING["md"])
        self.performanceDistributionLabels = {}
        self.performanceDistributionCards = {}
        distribution_defs = (
            "win_count", "loss_count", "win_rate", "average_win", "average_loss",
            "largest_win", "largest_loss", "gross_profit", "gross_loss",
        )
        for index, key in enumerate(distribution_defs):
            block = QtWidgets.QFrame()
            block.setProperty("role", "metricBlock")
            block_l = QtWidgets.QVBoxLayout(block)
            block_l.setContentsMargins(SPACING["lg"], SPACING["md"], SPACING["lg"], SPACING["md"])
            block_l.setSpacing(SPACING["sm"])
            name = QtWidgets.QLabel(self._tr(f"performance.distribution.{key}"))
            name.setProperty("role", "distributionLabel")
            name.setAlignment(QtCore.Qt.AlignCenter)
            name.setWordWrap(True)
            name.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
            value = QtWidgets.QLabel("-")
            value.setProperty("role", "distributionValue")
            value.setAlignment(QtCore.Qt.AlignCenter)
            value.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
            self.performanceDistributionLabels[key] = value
            self.performanceDistributionCards[key] = block
            block_l.addWidget(name, 3)
            block_l.addWidget(value, 4)
            stats.addWidget(block, index // 3, index % 3)
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
        self.performanceHistogramPlot = _ManagedAnalysisPlotWidget()
        self.performanceHistogramPlot.setMinimumHeight(170)
        self.performanceHistogramPlot.showGrid(x=False, y=True, alpha=0.12)
        self.performanceHistogram = pg.BarGraphItem(x=[], height=[], width=0.75)
        self.performanceHistogramPlot.addItem(self.performanceHistogram)
        self.performanceHistogramZeroLine = pg.InfiniteLine(
            angle=0, pen=pg.mkPen(COLORS["text_tertiary"], style=QtCore.Qt.DashLine)
        )
        self.performanceHistogramPlot.addItem(self.performanceHistogramZeroLine)
        histogram_l.addWidget(self.performanceHistogramPlot, 1)
        distribution_l.addWidget(histogram_panel, 1)
        layout.addWidget(distribution)
        self.performanceContentScroll.setWidget(tab)
        page_layout.addWidget(self.performanceContentScroll, stretch=1)
        return page

    def _populate_performance_sessions(self) -> None:
        current_id = str(getattr(self.app_window, "session_id", "") or "")
        symbol_box = getattr(self.app_window, "symbolBox", None)
        interval_box = getattr(self.app_window, "intervalBox", None)
        start_edit = getattr(self.app_window, "startDate", None)
        end_edit = getattr(self.app_window, "endDate", None)
        current_session = {
            "session_id": current_id,
            "symbol": symbol_box.currentText() if symbol_box is not None else "-",
            "interval": interval_box.currentText() if interval_box is not None else "-",
            "start_date_bjt": (
                start_edit.date().toString("yyyy-MM-dd") if start_edit is not None else "-"
            ),
            "end_date_bjt": (
                end_edit.date().toString("yyyy-MM-dd") if end_edit is not None else "-"
            ),
        }
        self.performanceSessionBox.blockSignals(True)
        self.performanceSessionBox.clear()
        storage = getattr(self.app_window, "storage", None)
        try:
            options = list_performance_session_options(
                storage,
                current_session=current_session if current_id else None,
            )
        except Exception:
            logger.exception("Failed to load performance-session catalog")
            options = ()
        for option in options:
            self.performanceSessionBox.addItem(option.display_name, option.session_id)
        self.performanceSessionBox.blockSignals(False)

    def refresh_performance_session_catalog(self) -> None:
        """Reload saved sessions while preserving a still-existing selection."""

        selected_session_id = str(self.performanceSessionBox.currentData() or "")
        self._populate_performance_sessions()
        selected_index = self.performanceSessionBox.findData(selected_session_id)
        if selected_index >= 0:
            self.performanceSessionBox.blockSignals(True)
            self.performanceSessionBox.setCurrentIndex(selected_index)
            self.performanceSessionBox.blockSignals(False)
        self._refresh_performance_workspace()

    def _on_performance_trade_marker_clicked(self, _item, points, _event=None) -> None:
        if not points:
            return
        trade_id = str(points[0].data() or "")
        model = getattr(self, "performanceTradeModel", None)
        if model is not None:
            row = model.show_trade(trade_id)
            if row is not None:
                self.tradePnlTable.selectRow(row)
                self.tradePnlTable.scrollTo(model.index(row, 0))
            return
        for row in range(self.tradePnlTable.rowCount()):
            item = self.tradePnlTable.item(row, 0)
            if item is not None and str(item.data(QtCore.Qt.UserRole) or "") == trade_id:
                self.tradePnlTable.selectRow(row)
                self.tradePnlTable.scrollToItem(item)
                return

    @QtCore.Slot(int, int)
    def _on_performance_trade_page_changed(self, page: int, page_count: int) -> None:
        self.performanceTradePageLabel.setText(f"{page + 1} / {page_count}")
        self.performanceTradePrevious.setEnabled(page > 0)
        self.performanceTradeNext.setEnabled(page + 1 < page_count)

    def eventFilter(self, watched, event):
        if (
            watched is getattr(self, "equityCurvePlot", None)
            and event.type() == QtCore.QEvent.Resize
        ):
            self.performanceCurveStateLabel.setGeometry(self.equityCurvePlot.rect())
        return super().eventFilter(watched, event)

    def _set_performance_curve_state(self, translation_key: str | None) -> None:
        if translation_key is None:
            self.performanceCurveStateLabel.hide()
            return
        self.performanceCurveStateLabel.setText(self._tr(translation_key))
        self.performanceCurveStateLabel.show()
        self.performanceCurveStateLabel.raise_()

    def _set_performance_curve_message(self, message: str) -> None:
        self.performanceCurveStateLabel.setText(str(message))
        self.performanceCurveStateLabel.show()
        self.performanceCurveStateLabel.raise_()

    def _clear_performance_curve_visuals(self) -> None:
        self.equityCurve.setData([], [])
        self.performanceSinglePoint.setData([])
        self.performanceTradeMarkers.setData([])
        for item in self.performanceCurveItems:
            self.equityCurvePlot.removeItem(item)
        self.performanceCurveItems.clear()
        self.equityCurveData = []
        self._performanceCurveX = []

    def _set_performance_value_tone(
        self,
        label: QtWidgets.QLabel,
        number: float,
        *,
        zero_is_negative: bool = False,
    ) -> None:
        theme = self._theme_settings
        if not math.isfinite(number):
            color = theme["text_secondary"]
        elif number > 0:
            color = theme["success"]
        elif number < 0 or zero_is_negative:
            color = theme["danger"]
        else:
            color = theme["text_secondary"]
        label.setStyleSheet(f"color: {color};")

    def _on_performance_curve_mouse_moved(self, scene_pos) -> None:
        if not self.equityCurvePlot.sceneBoundingRect().contains(scene_pos):
            return
        point = self.equityCurvePlot.getPlotItem().vb.mapSceneToView(scene_pos)
        x_values = getattr(self, "_performanceCurveX", [])
        if not x_values:
            return
        insertion = bisect.bisect_left(x_values, float(point.x()))
        if insertion <= 0:
            index = 0
        elif insertion >= len(x_values):
            index = len(x_values) - 1
        else:
            index = insertion if abs(x_values[insertion] - point.x()) < abs(x_values[insertion - 1] - point.x()) else insertion - 1
        self._update_performance_hover(index)

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

    def _spin_value(self, name: str, default: float) -> float:
        widget = getattr(self.app_window, name, None)
        if widget is None or not hasattr(widget, "value"):
            return float(default)
        return _safe_float(widget.value(), float(default))

    def _trade_notional(self, trade: dict) -> float:
        default_notional = _safe_float(
            getattr(self, "_performanceDefaultNotional", float("nan")),
            float("nan"),
        )
        if not math.isfinite(default_notional) or default_notional <= 0:
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

    def apply_performance_payload(self, payload: PerformanceWorkspacePayload) -> None:
        """Render a worker-produced current-session payload on the Qt thread."""

        self._performance_payload = payload
        self._refresh_performance_workspace()

    def invalidate_performance_sessions(self, session_ids) -> None:
        """Discard rendered payloads affected by committed trade-sample deletion."""

        affected = {str(value) for value in session_ids if str(value)}
        if not affected:
            return
        current_id = str(getattr(self.app_window, "session_id", "") or "")
        if current_id in affected:
            self._performance_payload = None
        for session_id in affected:
            self._historical_performance_payloads.pop(session_id, None)
            self._historical_performance_empty_states.pop(session_id, None)
        if self._historical_performance_requested_session_id in affected:
            self._historical_performance_requested_session_id = None
        selected_id = str(self.performanceSessionBox.currentData() or "")
        if not selected_id or selected_id in affected:
            self._refresh_performance_workspace()

    @QtCore.Slot(object)
    def _on_historical_performance_result(self, result) -> None:
        session_id = str(result.session_id)
        if result.payload is None:
            self._historical_performance_payloads.pop(session_id, None)
            self._historical_performance_empty_states[session_id] = str(
                result.empty_reason or "performance.curve_empty"
            )
        else:
            self._historical_performance_payloads[session_id] = result.payload
            self._historical_performance_empty_states.pop(session_id, None)
        if self._historical_performance_requested_session_id == session_id:
            self._historical_performance_requested_session_id = None
        if str(self.performanceSessionBox.currentData() or "") == session_id:
            self._refresh_performance_workspace()

    @QtCore.Slot(str)
    def _on_historical_performance_failed(self, error: str) -> None:
        logger.error("Historical performance refresh failed: %s", error)
        requested_session_id = self._historical_performance_requested_session_id
        self._historical_performance_requested_session_id = None
        selected_id = str(self.performanceSessionBox.currentData() or "")
        if requested_session_id and selected_id == requested_session_id:
            self._clear_performance_curve_visuals()
            self._set_performance_curve_message(
                self._tr("performance.curve_load_failed").format(error=error)
            )

    def _refresh_performance_workspace(self) -> None:
        selected_id = str(self.performanceSessionBox.currentData() or "")
        current_id = str(getattr(self.app_window, "session_id", "") or "")
        initial = self._spin_value("initialEquitySpin", 10_000.0)
        notional = self._spin_value("tradeNotionalSpin", 1_000.0)
        snapshot = None
        is_current_session = not selected_id or selected_id == current_id
        payload = (
            getattr(self, "_performance_payload", None)
            if is_current_session
            else self._historical_performance_payloads.get(selected_id)
        )
        if payload is not None:
            trades = [dict(trade) for trade in payload.trades]
            equity_rows = [dict(row) for row in payload.equity_rows]
            initial = float(payload.initial_equity)
            notional = float(payload.default_notional)
            snapshot = {
                "metrics": dict(payload.metrics),
                "distribution": dict(payload.distribution),
                "equity_values": list(payload.equity_values),
                "pnl_values": list(payload.pnl_values),
                "trades": trades,
                "closed_pnls": list(payload.closed_pnls),
                "markers": payload.markers,
            }
        elif is_current_session:
            self._clear_performance_curve_visuals()
            state_key = (
                "performance.curve_pause_to_update"
                if bool(getattr(self.app_window, "playing", False))
                else "performance.curve_empty"
            )
            self._set_performance_curve_state(state_key)
            return
        else:
            empty_state = self._historical_performance_empty_states.get(selected_id)
            if empty_state is not None:
                self._clear_performance_curve_visuals()
                self._set_performance_curve_state(empty_state)
                return
            self._clear_performance_curve_visuals()
            self._set_performance_curve_state("performance.curve_loading")
            controller = self.historical_performance_controller
            if (
                controller is not None
                and self._historical_performance_requested_session_id != selected_id
            ):
                self._historical_performance_requested_session_id = selected_id
                controller.request(selected_id)
            return

        if snapshot is None:
            snapshot = build_performance_snapshot(
                equity_rows=equity_rows,
                trades=trades,
                initial_equity=initial,
                default_notional=notional,
            )
        self._performanceDefaultNotional = float(notional)
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
            number = signed_values.get(key, float("nan"))
            if key == "sharpe":
                number = raw_metrics["sharpe_ratio"] if raw_metrics["sharpe_ratio"] is not None else float("nan")
                self._set_performance_value_tone(label, number, zero_is_negative=True)
            elif key == "payoff":
                number = raw_metrics["payoff_ratio"] if raw_metrics["payoff_ratio"] is not None else float("nan")
                self._set_performance_value_tone(label, number - 1.0 if math.isfinite(number) else number)
            elif key == "win_rate":
                number = raw_metrics["win_rate_pct"]
                self._set_performance_value_tone(label, number - 50.0 if math.isfinite(number) else number)
            elif key == "max_drawdown":
                number = raw_metrics["max_drawdown_pct"] if raw_metrics["max_drawdown_pct"] is not None else float("nan")
                self._set_performance_value_tone(label, number)
            elif key in signed_metric_keys:
                self._set_performance_value_tone(label, number)
            else:
                label.setStyleSheet("")

        self._clear_performance_curve_visuals()
        self.equityCurveData = list(snapshot["equity_values"])
        curve_mode = str(self.performanceCurveMode.currentData() or "equity")
        curve_values = snapshot["pnl_values"] if curve_mode == "pnl" else snapshot["equity_values"]
        display_curve_values = smooth_curve_values(curve_values, window=5)
        self._set_performance_curve_state(
            None if display_curve_values else "performance.curve_empty"
        )
        curve_x = [_curve_timestamp(row, index) for index, row in enumerate(equity_rows)]
        self._performanceCurveX = curve_x
        baseline = 0.0 if curve_mode == "pnl" else initial
        self.performanceBaseline.setValue(baseline)
        single_point_spots = []
        for side, points in split_signed_curve(display_curve_values, baseline):
            color = COLORS["success"] if side == "positive" else COLORS["danger"]
            if len(points) == 1:
                point = points[0]
                single_point_spots.append(
                    {
                        "pos": (float(curve_x[int(point[0])]), float(point[1])),
                        "brush": pg.mkBrush(color),
                        "pen": pg.mkPen(color),
                    }
                )
                continue
            item = self.equityCurvePlot.plot(
                [curve_x[int(point[0])] for point in points],
                [point[1] for point in points],
                pen=pg.mkPen(color, width=2),
                antialias=True,
            )
            item.setDownsampling(auto=True, method="mean")
            item.setClipToView(True)
            self.performanceCurveItems.append(item)
        self.performanceSinglePoint.setData(single_point_spots)
        marker_spots = []
        explicit_markers = snapshot.get("markers")
        if explicit_markers is not None:
            for marker in explicit_markers:
                is_entry = marker.kind == "entry"
                color = COLORS["chart_up"] if is_entry else COLORS["chart_down"]
                y_value = marker.pnl_value if curve_mode == "pnl" else marker.equity_value
                marker_spots.append(
                    {
                        "pos": (
                            _curve_timestamp({"time": marker.curve_time}, marker.bar_index),
                            float(y_value),
                        ),
                        "data": marker.trade_id,
                        "symbol": "t1" if is_entry else "x",
                        "brush": pg.mkBrush(color),
                        "pen": pg.mkPen(color),
                    }
                )
        else:
            bar_positions = {
                int(row.get("bar_index", index)): index
                for index, row in enumerate(equity_rows)
                if row.get("bar_index", index) is not None
            }
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
                            "pos": (float(curve_x[curve_index]), float(y_value)),
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
            label = self.performanceDistributionLabels[key]
            label.setText(value)
            number = distribution[key] if key in distribution else raw_metrics["win_rate_pct"]
            if key in {"loss_count", "average_loss", "largest_loss", "gross_loss"}:
                self._set_performance_value_tone(label, -abs(float(number)))
            elif key == "win_rate":
                self._set_performance_value_tone(label, float(number) - 50.0)
            else:
                self._set_performance_value_tone(label, float(number))

        pnls = np.asarray(snapshot["closed_pnls"], dtype=float)
        if pnls.size:
            trade_numbers = np.arange(1, pnls.size + 1, dtype=float)
            brushes = [pg.mkBrush(COLORS["success"] if pnl >= 0 else COLORS["danger"]) for pnl in pnls]
            self.performanceHistogram.setOpts(x=trade_numbers, height=pnls, width=0.65, brushes=brushes)
            self.performanceHistogramPlot.getAxis("bottom").setTicks([
                [(float(number), str(int(number))) for number in trade_numbers]
            ])
            self.performanceHistogramPlot.setXRange(0.4, float(pnls.size) + 0.6, padding=0)
        else:
            self.performanceHistogram.setOpts(x=[], height=[], width=0.75)
            self.performanceHistogramPlot.getAxis("bottom").setTicks([])

        self._performance_trade_rows = tuple(dict(trade) for trade in snapshot["trades"])
        self._render_performance_trade_table(self._performance_trade_rows)

    def _refresh_performance_trade_table(self, *_args) -> None:
        if not self._performance_trade_rows:
            return
        self._render_performance_trade_table(self._performance_trade_rows)

    def _render_performance_trade_table(self, trades) -> None:
        trade_rows = [dict(trade) for trade in trades]
        closed_trade_numbers: dict[str, int] = {}
        closed_fallback_numbers: dict[int, int] = {}
        next_trade_number = 1
        for trade in trade_rows:
            if str(trade.get("status") or "").upper() != "CLOSED":
                continue
            trade_id = str(trade.get("trade_id") or "")
            if trade_id:
                closed_trade_numbers[trade_id] = next_trade_number
            else:
                closed_fallback_numbers[id(trade)] = next_trade_number
            next_trade_number += 1

        trade_filter = str(self.performanceTradeFilter.currentData() or "all")
        side_filter = str(self.performanceSideFilter.currentData() or "ALL")
        filtered = []
        for trade in trade_rows:
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
        model_rows: list[PerformanceTradeRow] = []
        for trade in filtered:
            fees = _safe_float(trade.get("entry_fee_quote")) + _safe_float(trade.get("exit_fee_quote"))
            trade_pnl = self._trade_pnl(trade)
            trade_return = self._trade_return_pct(trade)
            trade_number = "-"
            if str(trade.get("status") or "").upper() == "CLOSED":
                trade_id = str(trade.get("trade_id") or "")
                mapped = closed_trade_numbers.get(trade_id) if trade_id else closed_fallback_numbers.get(id(trade))
                trade_number = str(mapped) if mapped is not None else "-"
            values = (
                trade_number,
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
            colors: list[str | None] = [None] * len(values)
            for column, signed_value in ((8, trade_pnl), (9, trade_return)):
                colors[column] = (
                    COLORS["success"]
                    if signed_value > 0
                    else COLORS["danger"]
                    if signed_value < 0
                    else COLORS["text_secondary"]
                )
            sort_values = (
                int(trade_number) if trade_number != "-" else -1,
                str(trade.get("side") or ""),
                str(trade.get("entry_bar_time_bjt") or ""),
                str(trade.get("exit_bar_time_bjt") or ""),
                _safe_float(trade.get("entry_fill_price"), float("-inf")),
                _safe_float(trade.get("exit_fill_price"), float("-inf")),
                self._trade_notional(trade),
                fees,
                trade_pnl,
                trade_return,
                _safe_float(trade.get("holding_bars"), -1.0),
                _safe_float(trade.get("take_profit_price"), float("-inf")),
                _safe_float(trade.get("stop_loss_price"), float("-inf")),
                str(trade.get("exit_reason") or ""),
            )
            model_rows.append(
                PerformanceTradeRow(
                    values=tuple(values),
                    trade_id=str(trade.get("trade_id") or ""),
                    sort_values=sort_values,
                    colors=tuple(colors),
                )
            )
        self.performanceTradeModel.set_rows(model_rows)

    def _is_main_trading_tab_widget(self, widget: QtWidgets.QWidget) -> bool:
        owning_tabs = [
            tabs
            for tabs in (
                getattr(self.app_window, "rightTabs", None),
                getattr(self.app_window, "bottomTabs", None),
                getattr(self.app_window, "tradeResultsTabs", None),
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

    def _ensure_lazy_analysis_panel(self, index: int) -> None:
        selected = self.tabs.widget(index)
        if selected is self.consistencyTab:
            panel_name = "strategyConsistencyPanel"
            tab_attribute = "consistencyTab"
        elif selected is self.backtestTab:
            panel_name = "backtestPanel"
            tab_attribute = "backtestTab"
        else:
            return
        if getattr(self.app_window, panel_name, None) is not None:
            return
        ensure = getattr(self.app_window, "ensure_analysis_support_panel", None)
        if not callable(ensure):
            return
        panel = ensure(panel_name)
        if panel is None:
            return
        replacement = self._scrollable_existing_widget(panel_name, "")
        blocker = QtCore.QSignalBlocker(self.tabs)
        self.tabs.removeTab(index)
        self.tabs.insertTab(index, replacement, "")
        self.tabs.setCurrentIndex(index)
        del blocker
        setattr(self, tab_attribute, replacement)
        self.retranslate_ui()

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
        self.btnRunResearch.setProperty("role", "primaryButton")
        self.btnExportResearch.hide()
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
        self.btnRunEntryLogic.hide()
        self.btnExportEntryLogic.hide()
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

    def _research_export_finished(self, export_dir: Path):
        self.last_research_dir = Path(export_dir) / "research"
        self._load_research_views()

    def run_research_analysis(self):
        self.open_decision_research()

    def export_research_pack(self):
        self.open_decision_research()

    def run_entry_logic_report(self):
        self.open_decision_research()

    def export_entry_logic_report(self):
        self.open_decision_research()

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
            logger.exception("Time-series analysis failed")
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
        for panel_name in ("backtestPanel", "strategyConsistencyPanel"):
            panel = getattr(self.app_window, panel_name, None)
            if panel is not None and hasattr(panel, "retranslate_ui"):
                panel.retranslate_ui()
        self.setWindowTitle(self._tr("data_analysis"))
        self.titleLabel.setText(self._tr("data_analysis"))
        self.btnRefresh.setText(self._tr("refresh"))
        self.tabs.setTabText(self.tabs.indexOf(self.performanceTab), self._tr("trading_performance"))
        self.tabs.setTabText(
            self.tabs.indexOf(self.decisionResearchTab),
            self._tr("decision_research.title"),
        )
        self.decisionResearchWorkspace.retranslate_ui(self._language())
        self.tabs.setTabText(self.tabs.indexOf(self.consistencyTab), self._tr("strategy_consistency"))
        self.tabs.setTabText(self.tabs.indexOf(self.backtestTab), self._tr("backtest_research"))
        self.tabs.setTabText(self.tabs.indexOf(self.premiumTab), self._tr("usdt_premium"))
        self.tabs.setTabText(self.tabs.indexOf(self.aiTab), self._tr("ai_summary"))
        self.tabs.setTabText(
            self.tabs.indexOf(self.researchTab),
            self._tr("research.legacy_results"),
        )
        self.tabs.setTabText(self.tabs.indexOf(self.timeSeriesTab), self._tr("time_series.workspace"))
        self.performanceHistogramTitle.setText(self._tr("performance.histogram.title"))
        self.performanceHistogramDefinition.setText(self._tr("performance.histogram.definition"))
        self.performanceHistogramPlot.setLabel(
            "bottom", self._tr("performance.histogram.x_axis")
        )
        self.performanceHistogramPlot.setLabel(
            "left", self._tr("performance.histogram.y_axis")
        )
        self.btnRunResearch.setText(
            self._tr("decision_research.redirect.open")
        )
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

    def open_decision_research(self) -> None:
        self.tabs.setCurrentWidget(self.decisionResearchTab)
        mark_startup_stage("analysis_shell_visible", flush=True)
        self._refresh_decision_research_context()

    def _bind_decision_research_data(self) -> None:
        workspace = self.decisionResearchWorkspace
        workspace.auditRequested.connect(
            self._inspect_decision_research_data
        )
        workspace.backfillRequested.connect(
            self._start_decision_research_backfill
        )
        workspace.cancelRequested.connect(
            self._cancel_decision_research_data_task
        )
        workspace.retryRequested.connect(
            self._retry_decision_research_backfill
        )
        workspace.researchContextChanged.connect(
            self._invalidate_decision_research_data
        )
        source_changed = getattr(
            self.app_window,
            "decisionResearchSourceChanged",
            None,
        )
        if source_changed is not None:
            source_changed.connect(self._refresh_decision_research_context)
        symbol_box = getattr(self.app_window, "symbolBox", None)
        if symbol_box is not None:
            symbol_box.currentTextChanged.connect(
                self._invalidate_decision_research_data
            )
        for date_control_name in ("startDate", "endDate"):
            date_control = getattr(
                self.app_window,
                date_control_name,
                None,
            )
            if date_control is not None:
                date_control.dateChanged.connect(
                    self._invalidate_decision_research_data
                )
        workspace.episodeCorrectionRequested.connect(
            self._on_episode_correction_requested
        )
        workspace.snapshotPublishRequested.connect(
            self._start_research_snapshot_publish
        )
        workspace.snapshotCancelRequested.connect(
            self._cancel_research_snapshot_publish
        )
        workspace.snapshotVersionRequested.connect(
            self._load_research_snapshot_version
        )
        workspace.snapshotDraftRequested.connect(
            self._prepare_current_research_snapshot
        )
        if self.research_snapshot_controller is not None:
            self.research_snapshot_controller.progress.connect(
                workspace.researchSnapshotWorkspace.begin_publish
            )
            self.research_snapshot_controller.finished.connect(
                self._on_research_snapshot_published
            )
            self.research_snapshot_controller.failed.connect(
                workspace.researchSnapshotWorkspace.render_publish_error
            )
            self.research_snapshot_controller.cancelled.connect(
                workspace.researchSnapshotWorkspace.render_publish_cancelled
            )
        controller = self._research_backfill_controller
        if controller is None:
            return
        controller.inspected.connect(
            self._on_decision_research_inspected
        )
        controller.progress.connect(
            self._on_decision_research_backfill_progress
        )
        controller.finished.connect(
            self._on_decision_research_backfill_finished
        )
        controller.auditFailed.connect(
            self._on_decision_research_audit_failed
        )
        controller.auditCancelled.connect(
            workspace.render_audit_cancelled
        )
        controller.failed.connect(
            self._on_decision_research_backfill_failed
        )
        controller.cancelled.connect(
            self._on_decision_research_backfill_cancelled
        )

    def prepare_research_snapshot(
        self,
        snapshot_input: ResearchSnapshotInput,
    ) -> ResearchSnapshotDraft:
        """Validate and display a dynamic draft supplied by research services."""

        service = self.research_snapshot_service
        if service is None:
            raise RuntimeError("research snapshot storage is unavailable")
        draft = service.build_draft(snapshot_input)
        self._research_snapshot_input = snapshot_input
        page = self.decisionResearchWorkspace.researchSnapshotWorkspace
        page.render_draft(
            content_hash=draft.content_hash,
            summary_zh=snapshot_input.hypothesis_card.summary_zh,
        )
        published = self.app_window.storage.list_research_snapshots(
            snapshot_input.versions.setup_version_id
        )
        page.render_published_versions(
            (item.snapshot_id, item.created_at) for item in published
        )
        if published and all(
            item.content_hash != draft.content_hash for item in published
        ):
            page.mark_new_evidence()
        return draft

    def _start_research_snapshot_publish(self) -> None:
        controller = self.research_snapshot_controller
        snapshot_input = self._research_snapshot_input
        page = self.decisionResearchWorkspace.researchSnapshotWorkspace
        if controller is None or snapshot_input is None:
            page.render_publish_error(
                self._tr("decision_research.snapshot.draft_unavailable")
            )
            return
        request = ResearchSnapshotPublishRequest(
            snapshot_input=snapshot_input,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        controller.start(request)
        if controller.is_running:
            page.begin_publish(
                self._tr("decision_research.snapshot.preparing")
            )

    def _cancel_research_snapshot_publish(self) -> None:
        controller = self.research_snapshot_controller
        if controller is not None:
            controller.cancel()

    def _load_research_snapshot_version(self, snapshot_id: str) -> None:
        controller = self.research_snapshot_controller
        if controller is not None:
            controller.load(snapshot_id)

    def _on_research_snapshot_published(self, event) -> None:
        page = self.decisionResearchWorkspace.researchSnapshotWorkspace
        snapshot_input = self._research_snapshot_input
        if event.publication is not None and snapshot_input is not None:
            published = self.app_window.storage.list_research_snapshots(
                snapshot_input.versions.setup_version_id
            )
            page.render_published_versions(
                (item.snapshot_id, item.created_at) for item in published
            )
        page.render_published_snapshot(
            snapshot_id=event.view.snapshot.snapshot_id,
            report_markdown=event.view.report_markdown,
        )

    def _decision_research_request(self) -> ResearchRangeRequest | None:
        symbol_box = getattr(self.app_window, "symbolBox", None)
        start_edit = getattr(self.app_window, "startDate", None)
        end_edit = getattr(self.app_window, "endDate", None)
        if symbol_box is None or start_edit is None or end_edit is None:
            return None
        symbol = str(symbol_box.currentText() or "").strip().upper()
        start_date = start_edit.date()
        end_date = end_edit.date()
        start_bjt = datetime(
            start_date.year(),
            start_date.month(),
            start_date.day(),
            tzinfo=BJT,
        )
        end_bjt = datetime(
            end_date.year(),
            end_date.month(),
            end_date.day(),
            23,
            59,
            59,
            999000,
            tzinfo=BJT,
        )
        return ResearchRangeRequest(
            symbol=symbol,
            timeframes=self.decisionResearchWorkspace.state.timeframes,
            start_time_utc_ms=int(
                start_bjt.astimezone(timezone.utc).timestamp() * 1_000
            ),
            end_time_utc_ms=int(
                end_bjt.astimezone(timezone.utc).timestamp() * 1_000
            ),
            as_of_utc_ms=int(
                datetime.now(timezone.utc).timestamp() * 1_000
            ),
        )

    def _decision_research_context_request(
        self,
    ) -> DecisionResearchRequest | None:
        range_request = self._decision_research_request()
        setup_version_id = self.decisionResearchWorkspace.state.setup_version
        if range_request is None or not setup_version_id:
            return None
        return DecisionResearchRequest(
            session_id=str(getattr(self.app_window, "session_id", "") or ""),
            setup_version_id=setup_version_id,
            mode=self.decisionResearchWorkspace.state.primary_tab,
            symbol=range_request.symbol,
            timeframes=range_request.timeframes,
            start_time_utc_ms=range_request.start_time_utc_ms,
            end_time_utc_ms=range_request.end_time_utc_ms,
        )

    def _refresh_decision_research_context(self) -> None:
        coordinator = self.decision_research_coordinator
        request = self._decision_research_context_request()
        workspace = self.decisionResearchWorkspace
        if coordinator is None or request is None:
            workspace.clear_episode_audit()
            return
        try:
            context = coordinator.open(request)
        except (KeyError, TypeError, ValueError):
            logger.exception("Decision research context composition failed")
            workspace.clear_episode_audit()
            return
        if not coordinator.is_current(context.revision):
            return
        if context.episode_summary is None:
            self._decision_research_contexts[request.mode] = context
            workspace.clear_episode_audit()
            return
        self._decision_research_contexts[request.mode] = context
        workspace.render_episode_audit(context.episode_summary)

    def _prepare_current_research_snapshot(self) -> None:
        mode = self.decisionResearchWorkspace.state.primary_tab
        context = self._decision_research_contexts.get(mode)
        assembler = self.research_snapshot_input_assembler
        if context is None or assembler is None:
            return
        try:
            snapshot_input = assembler.assemble(
                context,
                self.decisionResearchWorkspace.state.active_mode,
                completeness_report=(
                    self.decisionResearchWorkspace._completeness_report
                ),
            )
            self.prepare_research_snapshot(snapshot_input)
        except (KeyError, TypeError, ValueError):
            logger.exception("Research snapshot draft composition failed")

    def _on_episode_correction_requested(self, grouping_version_id: str) -> None:
        mode = self.decisionResearchWorkspace.state.primary_tab
        context = self._decision_research_contexts.get(mode)
        coordinator = self.decision_research_coordinator
        if (
            coordinator is None
            or context is None
            or context.grouping_version_id != grouping_version_id
            or context.episode_summary is None
        ):
            return
        try:
            request = request_episode_correction(
                self,
                context.episode_summary,
                self._tr,
            )
            if request is None:
                return
            if isinstance(request, EpisodeMergeRequest):
                corrected = coordinator.merge_episodes(
                    context,
                    request.episode_ids,
                    actor="desktop-user",
                    reason=request.reason,
                )
            elif isinstance(request, EpisodeSplitRequest):
                corrected = coordinator.split_episode(
                    context,
                    request.episode_id,
                    request.sample_groups,
                    actor="desktop-user",
                    reason=request.reason,
                )
            else:  # pragma: no cover - exhaustive immutable command union
                raise TypeError("unsupported episode correction request")
        except (KeyError, TypeError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(
                self,
                self._tr("decision_research.episode.correction.failed_title"),
                self._tr("decision_research.episode.correction.failed").format(
                    error=str(exc),
                ),
            )
            return
        if corrected is None:
            return
        self._decision_research_contexts[mode] = corrected
        self.decisionResearchWorkspace.render_episode_audit(
            corrected.episode_summary
        )
        QtWidgets.QMessageBox.information(
            self,
            self._tr("decision_research.episode.correction.done_title"),
            self._tr("decision_research.episode.correction.done"),
        )

    def _inspect_decision_research_data(self) -> None:
        self._refresh_decision_research_context()
        controller = self._research_backfill_controller
        request = self._decision_research_request()
        if controller is None:
            self.decisionResearchWorkspace.render_audit_rejection(
                self._tr(
                    "decision_research.data.audit_controller_unavailable"
                )
            )
            return
        if request is None:
            self.decisionResearchWorkspace.render_audit_rejection(
                self._tr("decision_research.data.audit_context_invalid")
            )
            return
        if controller.inspect(request):
            self.decisionResearchWorkspace.begin_audit()
            return
        lifecycle = getattr(self.app_window, "task_lifecycle", None)
        if bool(getattr(lifecycle, "shutdown_in_progress", False)):
            key = "decision_research.data.audit_shutting_down"
        elif controller.is_running or tuple(
            getattr(lifecycle, "active_tasks", ())
        ):
            key = "decision_research.data.audit_busy"
        else:
            key = "decision_research.data.audit_start_failed"
        self.decisionResearchWorkspace.render_audit_rejection(
            self._tr(key)
        )

    def _start_decision_research_backfill(self) -> None:
        controller = self._research_backfill_controller
        request = self._decision_research_request()
        if controller is None or request is None:
            return
        if controller.start(request):
            self.decisionResearchWorkspace.begin_backfill()

    def _cancel_decision_research_data_task(self) -> None:
        controller = self._research_backfill_controller
        if controller is not None:
            controller.cancel()

    def _retry_decision_research_backfill(self) -> None:
        controller = self._research_backfill_controller
        if controller is not None and controller.retry():
            self.decisionResearchWorkspace.begin_backfill()

    def _invalidate_decision_research_data(self) -> None:
        self._refresh_decision_research_context()
        self.decisionResearchWorkspace.invalidate_completeness()
        controller = self._research_backfill_controller
        if controller is not None:
            controller.invalidate()

    def _on_decision_research_backfill_failed(self, event) -> None:
        if event.result is not None:
            self.decisionResearchWorkspace.render_completeness(
                event.result.completeness
            )
        self.decisionResearchWorkspace.render_backfill_failure(
            event.message
        )

    @QtCore.Slot(object)
    def _on_decision_research_inspected(self, event) -> None:
        self.decisionResearchWorkspace.render_audit_result(event.report)

    @QtCore.Slot(object)
    def _on_decision_research_audit_failed(self, event) -> None:
        logger.error(
            "Decision research completeness audit failed: %s",
            getattr(event, "message", event),
        )
        self.decisionResearchWorkspace.render_audit_rejection(
            self._tr("decision_research.data.audit_failed")
        )

    @QtCore.Slot(object)
    def _on_decision_research_backfill_progress(self, event) -> None:
        self.decisionResearchWorkspace.render_backfill_progress(
            event.progress
        )

    @QtCore.Slot(object)
    def _on_decision_research_backfill_finished(self, event) -> None:
        self.decisionResearchWorkspace.render_backfill_finished(
            event.result
        )

    def _on_decision_research_backfill_cancelled(self, event) -> None:
        result = getattr(event, "result", None)
        if result is not None:
            self.decisionResearchWorkspace.render_completeness(
                result.completeness
            )
        self.decisionResearchWorkspace.render_backfill_cancelled()

    def refresh(self):
        session_id = getattr(self.app_window, "session_id", None)
        session_text = self._tr("workspace.session").format(session_id=session_id) if session_id else self._tr("no_session_data")
        if bool(getattr(self.app_window, "playing", False)):
            session_text = f"{session_text} · {self._tr('workspace.live')}"
        self.sessionLabel.setText(session_text)
        refresh_tables = getattr(self.app_window, "_refresh_tables", None)
        if callable(refresh_tables):
            try:
                refresh_tables(include_heavy=False)
            except Exception:
                logger.exception("Analysis workspace refresh failed: _refresh_tables")
        refresh_premium = getattr(self.app_window, "_refresh_premium_plot", None)
        if callable(refresh_premium):
            try:
                refresh_premium()
            except Exception:
                logger.exception("Analysis workspace refresh failed: _refresh_premium_plot")
        controller = getattr(self.app_window, "analysis_refresh_controller", None)
        if controller is not None:
            controller.schedule()
        self._refresh_performance_workspace()

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def shutdown(self) -> bool:
        """Release worker and pyqtgraph ownership only during app shutdown."""

        candidate_controller = self.entry_candidate_controller
        if (
            candidate_controller is not None
            and candidate_controller.shutdown() is False
        ):
            return False
        exit_candidate_controller = self.exit_candidate_controller
        if (
            exit_candidate_controller is not None
            and exit_candidate_controller.shutdown() is False
        ):
            return False
        behavior_controller = self.entry_behavior_training_controller
        if (
            behavior_controller is not None
            and behavior_controller.shutdown() is False
        ):
            return False
        outcome_controller = self.entry_outcome_comparison_controller
        if (
            outcome_controller is not None
            and outcome_controller.shutdown() is False
        ):
            return False
        exit_outcome_controller = self.exit_outcome_comparison_controller
        if (
            exit_outcome_controller is not None
            and exit_outcome_controller.shutdown() is False
        ):
            return False
        snapshot_controller = self.research_snapshot_controller
        if (
            snapshot_controller is not None
            and snapshot_controller.shutdown() is False
        ):
            return False
        controller = self.historical_performance_controller
        if controller is not None and controller.shutdown() is False:
            return False
        if bool(getattr(self, "_graphics_shutdown", False)):
            return True
        for plot_widget in (
            self.equityCurvePlot,
            self.performanceHistogramPlot,
        ):
            plot_widget.shutdown()
        self._graphics_shutdown = True
        return True
