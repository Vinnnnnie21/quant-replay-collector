from __future__ import annotations

import csv
import json
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from app_config import EXPORT_DIR
from app_i18n import tr
from app_logger import get_logger
from ui_style import SPACING, style_secondary_button


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
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        self.last_research_dir: Path | None = None
        self._research_output_loaded = False
        self.last_time_series_summary: dict | None = None
        self.last_time_series_report_text = ""
        self._candidate_rule_rows: list[dict] = []
        self._localized_placeholders: list[tuple[QtWidgets.QPlainTextEdit, str, bool]] = []
        self._build_ui()
        self.retranslate_ui()

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
        self.btnRefresh.setStyleSheet(style_secondary_button())
        self.btnRefresh.clicked.connect(self.refresh)
        header.addWidget(self.titleLabel)
        header.addWidget(self.sessionLabel)
        header.addStretch(1)
        header.addWidget(self.btnRefresh)
        root.addLayout(header)

        self.tabs = QtWidgets.QTabWidget()
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
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        self.performanceTabs = QtWidgets.QTabWidget()
        self.closedTradesTab = self._existing_analysis_widget("closedTradesTable", "workspace.no_closed_trades")
        self.performanceTextTab = self._existing_analysis_widget("performanceText", "workspace.no_performance")
        self.equityTab = self._existing_analysis_widget("equityTable", "workspace.no_equity")
        self.performanceTabs.addTab(self.closedTradesTab, "")
        self.performanceTabs.addTab(self.performanceTextTab, "")
        self.performanceTabs.addTab(self.equityTab, "")
        layout.addWidget(self.performanceTabs)
        return tab

    def _event_study_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        self.eventTabs = QtWidgets.QTabWidget()
        self.eventStudyTableTab = self._existing_analysis_widget("eventStudyTable", "workspace.no_event_study")
        self.datasetTab = self._existing_analysis_widget("datasetText", "workspace.no_dataset")
        self.eventTabs.addTab(self.eventStudyTableTab, "")
        self.eventTabs.addTab(self.datasetTab, "")
        layout.addWidget(self.eventTabs)
        return tab

    def _is_main_trading_tab_widget(self, widget: QtWidgets.QWidget) -> bool:
        right_tabs = getattr(self.app_window, "rightTabs", None)
        if not isinstance(right_tabs, QtWidgets.QTabWidget):
            return False
        current = widget
        while current is not None:
            if right_tabs.indexOf(current) >= 0:
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
            button.setStyleSheet(style_secondary_button())
            controls.addWidget(button)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.researchWarning = QtWidgets.QLabel()
        self.researchWarning.setWordWrap(True)
        self.researchWarning.setStyleSheet("color: #d97706; font-weight: 600;")
        layout.addWidget(self.researchWarning)
        self.researchTabs = QtWidgets.QTabWidget()
        self.auditTable = self._research_table(AUDIT_COLUMNS)
        self.researchEventTable = self._research_table(EVENT_STUDY_COLUMNS)
        self.factorBinningTable = self._research_table(FACTOR_BINNING_COLUMNS)
        self.factorIcTable = self._research_table(FACTOR_IC_COLUMNS)
        self.ruleTable = self._research_table(RULE_COLUMNS)
        self.walkForwardTable = self._research_table(WALK_FORWARD_COLUMNS)
        self.reportText = self._placeholder("")
        for widget in (
            self.auditTable,
            self.researchEventTable,
            self.factorBinningTable,
            self.factorIcTable,
            self.ruleTable,
            self.walkForwardTable,
            self.reportText,
        ):
            self.researchTabs.addTab(widget, "")
        layout.addWidget(self.researchTabs, stretch=1)
        self.btnRunResearch.clicked.connect(self.run_research_analysis)
        self.btnExportResearch.clicked.connect(self.export_research_pack)
        self.btnOpenResearchFolder.clicked.connect(self.open_export_folder)
        self.btnCopyResearchContext.clicked.connect(self.copy_llm_context)
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
            button.setStyleSheet(style_secondary_button())
            controls.addWidget(button)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.timeSeriesHint = QtWidgets.QLabel()
        self.timeSeriesHint.setWordWrap(True)
        self.timeSeriesHint.setStyleSheet("color: #d97706; font-weight: 600;")
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
            warning_style = "color: #dc2626; font-weight: 700;"
        elif "exploratory" in warning_lower or "initial analysis" in warning_lower:
            warning_style = "color: #d97706; font-weight: 700;"
        else:
            warning_style = "color: #16a34a; font-weight: 600;"
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
        self.performanceTabs.setTabText(self.performanceTabs.indexOf(self.closedTradesTab), self._tr("closed_trades"))
        self.performanceTabs.setTabText(self.performanceTabs.indexOf(self.performanceTextTab), self._tr("trading_performance"))
        self.performanceTabs.setTabText(self.performanceTabs.indexOf(self.equityTab), self._tr("workspace.equity"))
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

    def closeEvent(self, event):
        event.ignore()
        self.hide()
