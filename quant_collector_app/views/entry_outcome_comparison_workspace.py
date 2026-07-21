from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtWidgets

try:
    from i18n import tr
    from research.entry_outcome_comparison import (
        EntryOutcomeComparisonRequest,
        EntryOutcomeMetric,
    )
    from research.exit_outcome_comparison import ExitOutcomeComparisonRequest
    from services.ui_message_localizer import sanitize_worker_error_detail
    from ui_style import SPACING, WORKSPACE_SIZES
    from views.main_window_presentation import (
        apply_role_button_styles,
        apply_themed_input_styles,
    )
    from views.widget_effects import apply_role_button_shadows
except ImportError:  # pragma: no cover - package import path
    from ..i18n import tr
    from ..research.entry_outcome_comparison import (
        EntryOutcomeComparisonRequest,
        EntryOutcomeMetric,
    )
    from ..research.exit_outcome_comparison import ExitOutcomeComparisonRequest
    from ..services.ui_message_localizer import sanitize_worker_error_detail
    from ..ui_style import SPACING, WORKSPACE_SIZES
    from .main_window_presentation import (
        apply_role_button_styles,
        apply_themed_input_styles,
    )
    from .widget_effects import apply_role_button_shadows


class DecisionOutcomeComparisonWorkspace(QtWidgets.QWidget):
    """Show the complete preregistered matrix and audited cell details."""

    comparisonResultAccepted = QtCore.Signal(object)

    def __init__(
        self,
        *,
        service: Any,
        controller: Any,
        exit_service: Any | None = None,
        exit_controller: Any | None = None,
        language: str = "zh_CN",
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.controller = controller
        self.exit_service = exit_service
        self.exit_controller = exit_controller
        self.language = language
        self._setup_version_id: str | None = None
        self._grouping_version_id: str | None = None
        self._direction: str | None = None
        self._entry_mode_active = True
        self._operation_allowed = False
        self._result = None
        self._build_ui()
        for outcome_controller in self._controllers():
            outcome_controller.resultReady.connect(self.render_result)
            outcome_controller.progress.connect(self._render_progress)
            outcome_controller.failed.connect(self._render_failure)
            outcome_controller.cancelled.connect(self._render_cancelled)
        self.retranslate_ui(language)

    def _tr(self, key: str) -> str:
        return tr(key, self.language)

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.scrollArea = QtWidgets.QScrollArea()
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.content)
        layout.setContentsMargins(
            SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"]
        )
        layout.setSpacing(SPACING["md"])

        header = QtWidgets.QHBoxLayout()
        self.titleLabel = QtWidgets.QLabel()
        self.titleLabel.setProperty("role", "sectionTitle")
        header.addWidget(self.titleLabel)
        header.addStretch(1)
        self.runButton = QtWidgets.QPushButton()
        self.runButton.setProperty("role", "primaryButton")
        self.cancelButton = QtWidgets.QPushButton()
        self.cancelButton.setProperty("role", "secondaryButton")
        header.addWidget(self.runButton)
        header.addWidget(self.cancelButton)
        layout.addLayout(header)
        self.runButton.clicked.connect(self._start)
        self.cancelButton.clicked.connect(self._cancel)

        self.warningLabel = QtWidgets.QLabel()
        self.warningLabel.setProperty("role", "pillWarning")
        self.warningLabel.setWordWrap(True)
        layout.addWidget(self.warningLabel)
        self.gateLabel = QtWidgets.QLabel()
        self.gateLabel.setProperty("role", "pillWarning")
        self.gateLabel.setWordWrap(True)
        self.gateLabel.hide()
        layout.addWidget(self.gateLabel)
        self.statusLabel = QtWidgets.QLabel()
        self.statusLabel.setProperty("role", "statusBlock")
        self.statusLabel.setWordWrap(True)
        layout.addWidget(self.statusLabel)
        self.progressBar = QtWidgets.QProgressBar()
        self.progressBar.setRange(0, 100)
        self.progressBar.hide()
        layout.addWidget(self.progressBar)

        self.matrixTable = QtWidgets.QTableWidget(5, 3)
        self.matrixTable.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers
        )
        self.matrixTable.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        self.matrixTable.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectItems
        )
        self.matrixTable.setAlternatingRowColors(True)
        self.matrixTable.horizontalHeader().setStretchLastSection(True)
        self.matrixTable.verticalHeader().setVisible(True)
        self.matrixTable.currentCellChanged.connect(self._render_cell_detail)
        layout.addWidget(self.matrixTable)

        self.detailTitle = QtWidgets.QLabel()
        self.detailTitle.setProperty("role", "sectionTitle")
        self.detailText = QtWidgets.QPlainTextEdit()
        self.detailText.setReadOnly(True)
        self.detailText.setMinimumHeight(
            WORKSPACE_SIZES["audit_detail_min_height"]
        )
        layout.addWidget(self.detailTitle)
        layout.addWidget(self.detailText)

        self.descriptiveTitle = QtWidgets.QLabel()
        self.descriptiveTitle.setProperty("role", "sectionTitle")
        self.descriptiveText = QtWidgets.QLabel()
        self.descriptiveText.setProperty("role", "mutedText")
        self.descriptiveText.setWordWrap(True)
        layout.addWidget(self.descriptiveTitle)
        layout.addWidget(self.descriptiveText)
        layout.addStretch(1)
        self.scrollArea.setWidget(self.content)
        root.addWidget(self.scrollArea)

    def set_research_context(
        self,
        *,
        setup_version_id: str | None,
        grouping_version_id: str | None,
        direction: str | None,
    ) -> None:
        current = (setup_version_id, grouping_version_id, direction)
        previous = (
            self._setup_version_id,
            self._grouping_version_id,
            self._direction,
        )
        if current != previous:
            for controller in self._controllers():
                controller.invalidate()
            self._result = None
            self.matrixTable.clearContents()
            self.detailText.clear()
        self._setup_version_id = setup_version_id
        self._grouping_version_id = grouping_version_id
        self._direction = direction
        self._sync_actions()

    def set_entry_mode_active(self, active: bool) -> None:
        active = bool(active)
        if active != self._entry_mode_active:
            current = self._active_controller()
            if current is not None:
                current.invalidate()
            self._entry_mode_active = active
            self._result = None
            self.matrixTable.clearContents()
            self.detailText.clear()
            self.statusLabel.clear()
            self.retranslate_ui()
        self._sync_actions()

    def set_operation_gate(self, *, allowed: bool, message: str) -> None:
        self._operation_allowed = bool(allowed)
        self.gateLabel.setText(str(message or ""))
        self.gateLabel.setVisible(not allowed and bool(message))
        self._sync_actions()

    def _can_run(self) -> bool:
        controller = self._active_controller()
        return bool(
            controller is not None
            and self._operation_allowed
            and self._setup_version_id
            and self._grouping_version_id
            and self._direction in {"LONG", "SHORT"}
            and not controller.is_running
        )

    def _start(self) -> None:
        if not self._can_run():
            return
        self.progressBar.setValue(0)
        self.progressBar.show()
        controller = self._active_controller()
        if controller is None:
            return
        running_key = (
            "decision_research.outcome.running"
            if self._entry_mode_active
            else "decision_research.outcome.exit.running"
        )
        self.statusLabel.setText(self._tr(running_key))
        request_type = (
            EntryOutcomeComparisonRequest
            if self._entry_mode_active
            else ExitOutcomeComparisonRequest
        )
        controller.start(
            request_type(
                setup_version_id=self._setup_version_id,
                grouping_version_id=self._grouping_version_id,
                direction=self._direction,
            )
        )
        self._sync_actions()

    @QtCore.Slot(object)
    def _render_progress(self, event: Any) -> None:
        percent = (
            0
            if not event.total
            else round(int(event.completed) * 100 / int(event.total))
        )
        self.progressBar.setValue(percent)

    @QtCore.Slot(object)
    def render_result(self, result: Any) -> None:
        result_target = str(getattr(result, "research_target", "ENTRY"))
        expected_target = "ENTRY" if self._entry_mode_active else "EXIT"
        if result_target != expected_target:
            return
        self._result = result
        self.progressBar.hide()
        primary = result.primary
        self.statusLabel.setText(
            self._tr("decision_research.outcome.status").format(
                comparison_id=result.comparison_id,
                threshold=primary.similarity_threshold,
                pairs=len(primary.pairs),
                episodes=max((cell.episode_count for cell in primary.matrix), default=0),
                stage=self._tr(
                    "decision_research.outcome.stage."
                    f"{primary.stage.value.lower()}"
                ),
            )
        )
        self._populate_matrix(primary.matrix)
        self.descriptiveText.setText(
            self._tr(
                "decision_research.outcome.descriptive_body"
                if self._entry_mode_active
                else "decision_research.outcome.exit.descriptive_body"
            )
        )
        self.matrixTable.setCurrentCell(0, 0)
        self._sync_actions()
        self.comparisonResultAccepted.emit(result)

    def _populate_matrix(self, cells) -> None:
        by_key = {(cell.horizon_bars, cell.metric): cell for cell in cells}
        for row, horizon in enumerate((1, 3, 5, 10, 20)):
            for column, metric in enumerate(EntryOutcomeMetric):
                cell = by_key[(horizon, metric)]
                value = (
                    "—"
                    if cell.median_difference is None
                    else f"{cell.median_difference:.2%}"
                )
                status = self._tr(
                    "decision_research.outcome.evidence."
                    f"{cell.evidence_status.value.lower()}"
                )
                item = QtWidgets.QTableWidgetItem(f"{value}\n{status}")
                item.setData(QtCore.Qt.UserRole, (horizon, metric.value))
                item.setTextAlignment(QtCore.Qt.AlignCenter)
                self.matrixTable.setItem(row, column, item)

    @QtCore.Slot(int, int, int, int)
    def _render_cell_detail(
        self,
        row: int,
        column: int,
        _previous_row: int = -1,
        _previous_column: int = -1,
    ) -> None:
        if self._result is None or row < 0 or column < 0:
            return
        horizon = (1, 3, 5, 10, 20)[row]
        metric = tuple(EntryOutcomeMetric)[column]
        primary_cell = _cell(self._result.primary.matrix, horizon, metric)
        sensitivity_lines = []
        for sensitivity in self._result.sensitivities:
            cell = _cell(sensitivity.matrix, horizon, metric)
            sensitivity_lines.append(
                self._tr("decision_research.outcome.detail.sensitivity").format(
                    threshold=sensitivity.similarity_threshold,
                    pairs=cell.pair_count,
                    episodes=cell.episode_count,
                    median=_number(cell.median_difference),
                )
            )
        episode_lines = [
            self._tr("decision_research.outcome.detail.episode").format(
                episode=item.episode_id,
                pairs=item.pair_count,
                value=_number(item.value),
            )
            for item in primary_cell.episodes
        ]
        if self._entry_mode_active:
            pair_lines = [
                self._tr("decision_research.outcome.detail.pair").format(
                    entry=item.entry_decision_event_id,
                    reject=item.reject_decision_event_id,
                    value=_number(item.value),
                )
                for item in primary_cell.differences
            ]
        else:
            pair_lines = [
                self._tr("decision_research.outcome.exit.detail.pair").format(
                    exit_now=item.exit_now_decision_event_id,
                    hold=item.hold_decision_event_id,
                    value=_number(item.value),
                )
                for item in primary_cell.differences
            ]
        summary = self._tr("decision_research.outcome.detail.summary").format(
            horizon=horizon,
            metric=self._tr(
                f"decision_research.outcome.metric.{metric.value}"
            ),
            median=_number(primary_cell.median_difference),
            mean=_number(primary_cell.mean_difference),
            rank=_number(primary_cell.rank_biserial),
            ci=f"{_number(primary_cell.ci_low)} ~ {_number(primary_cell.ci_high)}",
            p=_number(primary_cell.p_value),
            q=_number(primary_cell.q_value),
        )
        self.detailText.setPlainText(
            "\n".join((summary, *sensitivity_lines, *episode_lines, *pair_lines))
        )

    @QtCore.Slot(str)
    def _render_failure(self, error: str) -> None:
        self.progressBar.hide()
        self.statusLabel.setText(
            self._tr("decision_research.outcome.failed").format(
                error=sanitize_worker_error_detail(error)
            )
        )
        self._sync_actions()

    @QtCore.Slot()
    def _render_cancelled(self) -> None:
        self.progressBar.hide()
        self.statusLabel.setText(
            self._tr("decision_research.outcome.cancelled")
        )
        self._sync_actions()

    def _sync_actions(self) -> None:
        controller = self._active_controller()
        running = bool(controller is not None and controller.is_running)
        self.runButton.setEnabled(self._can_run())
        self.cancelButton.setEnabled(running)

    def _controllers(self) -> tuple[Any, ...]:
        return tuple(
            controller
            for controller in (self.controller, self.exit_controller)
            if controller is not None
        )

    def _active_controller(self):
        return self.controller if self._entry_mode_active else self.exit_controller

    def _cancel(self) -> None:
        controller = self._active_controller()
        if controller is not None:
            controller.cancel()

    def retranslate_ui(self, language: str | None = None) -> None:
        if language is not None:
            self.language = language
        target_prefix = (
            "decision_research.outcome"
            if self._entry_mode_active
            else "decision_research.outcome.exit"
        )
        self.titleLabel.setText(self._tr(f"{target_prefix}.title"))
        self.runButton.setText(self._tr("decision_research.outcome.run"))
        self.cancelButton.setText(self._tr("decision_research.outcome.cancel"))
        self.warningLabel.setText(
            self._tr(f"{target_prefix}.warning")
        )
        self.detailTitle.setText(
            self._tr("decision_research.outcome.detail_title")
        )
        self.descriptiveTitle.setText(
            self._tr("decision_research.outcome.descriptive_title")
        )
        self.matrixTable.setHorizontalHeaderLabels(
            [
                self._tr(
                    f"decision_research.outcome.metric.{metric.value}"
                )
                for metric in EntryOutcomeMetric
            ]
        )
        self.matrixTable.setVerticalHeaderLabels(
            [
                self._tr("decision_research.outcome.horizon").format(
                    bars=bars
                )
                for bars in (1, 3, 5, 10, 20)
            ]
        )
        if self._result is None and not self.statusLabel.text():
            self.statusLabel.setText(
                self._tr(f"{target_prefix}.empty")
            )
        elif self._result is not None:
            self.render_result(self._result)

    def apply_theme(self, theme: dict) -> None:
        apply_role_button_styles(self, theme)
        apply_themed_input_styles(self, theme)
        apply_role_button_shadows(self)


def _cell(cells, horizon: int, metric: EntryOutcomeMetric):
    return next(
        item
        for item in cells
        if item.horizon_bars == horizon and item.metric is metric
    )


def _number(value: float | None) -> str:
    return "—" if value is None else f"{float(value):.6f}"


EntryOutcomeComparisonWorkspace = DecisionOutcomeComparisonWorkspace


__all__ = [
    "DecisionOutcomeComparisonWorkspace",
    "EntryOutcomeComparisonWorkspace",
]
