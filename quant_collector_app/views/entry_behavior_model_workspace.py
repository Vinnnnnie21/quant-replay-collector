from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtWidgets

try:
    from i18n import tr
    from research.entry_behavior_model import (
        BehaviorModelTarget,
        BehaviorTrainingRequest,
    )
    from services.ui_message_localizer import sanitize_worker_error_detail
    from ui_style import SPACING
    from views.main_window_presentation import (
        apply_role_button_styles,
        apply_themed_input_styles,
    )
    from views.widget_effects import apply_role_button_shadows
except ImportError:  # pragma: no cover - package import path
    from ..i18n import tr
    from ..research.entry_behavior_model import (
        BehaviorModelTarget,
        BehaviorTrainingRequest,
    )
    from ..services.ui_message_localizer import sanitize_worker_error_detail
    from ..ui_style import SPACING
    from .main_window_presentation import (
        apply_role_button_styles,
        apply_themed_input_styles,
    )
    from .widget_effects import apply_role_button_shadows


class EntryBehaviorModelWorkspace(QtWidgets.QWidget):
    """Present immutable behavior-model audits and explicit training controls."""

    trainingResultAccepted = QtCore.Signal(object)

    def __init__(
        self,
        *,
        service: Any,
        controller: Any,
        language: str = "zh_CN",
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.controller = controller
        self.language = language
        self._setup_version_id: str | None = None
        self._grouping_version_id: str | None = None
        self._direction: str | None = None
        self._target = BehaviorModelTarget.ENTRY_SELECTION
        self._training_operation_allowed = False
        self._last_model = None
        self._last_failure_message: str | None = None
        self._freshness_state: str | None = None
        self._build_ui()
        self.controller.resultReady.connect(self._render_result)
        self.controller.progress.connect(self._render_progress)
        self.controller.failed.connect(self._render_worker_failure)
        self.controller.cancelled.connect(self._render_cancelled)
        self.retranslate_ui(language)

    def _tr(self, key: str) -> str:
        return tr(key, self.language)

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.scrollArea = QtWidgets.QScrollArea()
        self.scrollArea.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scrollArea.setWidgetResizable(True)
        self.content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.content)
        layout.setContentsMargins(
            SPACING["md"],
            SPACING["md"],
            SPACING["md"],
            SPACING["md"],
        )
        layout.setSpacing(SPACING["md"])

        header = QtWidgets.QHBoxLayout()
        self.titleLabel = QtWidgets.QLabel()
        self.titleLabel.setProperty("role", "sectionTitle")
        header.addWidget(self.titleLabel)
        header.addStretch(1)
        self.trainButton = QtWidgets.QPushButton()
        self.trainButton.setProperty("role", "primaryButton")
        self.cancelButton = QtWidgets.QPushButton()
        self.cancelButton.setProperty("role", "secondaryButton")
        self.trainButton.clicked.connect(self._start_training)
        self.cancelButton.clicked.connect(self.controller.cancel)
        header.addWidget(self.trainButton)
        header.addWidget(self.cancelButton)
        layout.addLayout(header)
        self.trainingGateLabel = QtWidgets.QLabel()
        self.trainingGateLabel.setProperty("role", "pillWarning")
        self.trainingGateLabel.setWordWrap(True)
        self.trainingGateLabel.hide()
        layout.addWidget(self.trainingGateLabel)

        self.explanationLabel = QtWidgets.QLabel()
        self.explanationLabel.setProperty("role", "mutedText")
        self.explanationLabel.setWordWrap(True)
        layout.addWidget(self.explanationLabel)
        self.statusLabel = QtWidgets.QLabel()
        self.statusLabel.setProperty("role", "statusBlock")
        self.statusLabel.setWordWrap(True)
        layout.addWidget(self.statusLabel)
        self.progressBar = QtWidgets.QProgressBar()
        self.progressBar.setRange(0, 100)
        self.progressBar.hide()
        layout.addWidget(self.progressBar)

        self.metricsTitle = QtWidgets.QLabel()
        self.metricsTitle.setProperty("role", "sectionTitle")
        self.metricsLabel = QtWidgets.QLabel()
        self.metricsLabel.setProperty("role", "mutedText")
        self.metricsLabel.setWordWrap(True)
        layout.addWidget(self.metricsTitle)
        layout.addWidget(self.metricsLabel)

        self.featuresTitle = QtWidgets.QLabel()
        self.featuresTitle.setProperty("role", "sectionTitle")
        self.featureTable = QtWidgets.QTableWidget(0, 4)
        self.featureTable.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers
        )
        self.featureTable.setSelectionMode(
            QtWidgets.QAbstractItemView.NoSelection
        )
        self.featureTable.setAlternatingRowColors(True)
        self.featureTable.horizontalHeader().setStretchLastSection(True)
        self.featureTable.verticalHeader().setVisible(False)
        layout.addWidget(self.featuresTitle)
        layout.addWidget(self.featureTable, stretch=1)

        self.scrollArea.setWidget(self.content)
        root.addWidget(self.scrollArea)

    def set_research_context(
        self,
        *,
        setup_version_id: str | None,
        grouping_version_id: str | None,
        direction: str | None,
    ) -> None:
        context = (setup_version_id, grouping_version_id, direction)
        previous = (
            self._setup_version_id,
            self._grouping_version_id,
            self._direction,
        )
        context_changed = context != previous
        if context_changed:
            self.controller.invalidate()
            self._last_model = None
            self._last_failure_message = None
            self._freshness_state = None
            self.featureTable.setRowCount(0)
            self.metricsLabel.clear()
        self._setup_version_id = setup_version_id
        self._grouping_version_id = grouping_version_id
        self._direction = direction
        if context_changed:
            self._load_latest_model()
        self._sync_actions()

    def set_entry_mode_active(self, active: bool) -> None:
        target = (
            BehaviorModelTarget.ENTRY_SELECTION
            if active
            else BehaviorModelTarget.EXIT_SELECTION
        )
        if target is self._target:
            self._sync_actions()
            return
        self._target = target
        self._last_model = None
        self._last_failure_message = None
        self._freshness_state = None
        self.featureTable.setRowCount(0)
        self.metricsLabel.clear()
        if self.controller.is_running:
            self.controller.invalidate()
        self.retranslate_ui()
        self._load_latest_model()

    def _load_latest_model(self) -> None:
        if not all(
            (
                self._setup_version_id,
                self._grouping_version_id,
                self._direction,
            )
        ):
            self.statusLabel.setText(
                self._tr("decision_research.behavior.context_missing")
            )
            return
        try:
            models = self.service.list_models(
                target=self._target,
                setup_version_id=self._setup_version_id,
                grouping_version_id=self._grouping_version_id,
                direction=self._direction,
            )
        except Exception as exc:
            self._render_worker_failure(f"{type(exc).__name__}: {exc}")
            return
        if not models:
            self.statusLabel.setText(
                self._tr("decision_research.behavior.empty")
            )
            return
        model = models[-1]
        self._last_model = model
        self._last_failure_message = None
        self._render_model(model)

    def _start_training(self) -> None:
        if not self._can_train():
            return
        self.progressBar.setValue(0)
        self.progressBar.show()
        self.statusLabel.setText(
            self._tr("decision_research.behavior.training")
        )
        self.controller.start(
            BehaviorTrainingRequest(
                setup_version_id=self._setup_version_id,
                grouping_version_id=self._grouping_version_id,
                direction=self._direction,
                target=self._target,
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
    def _render_result(self, result: Any) -> None:
        self.progressBar.hide()
        if result.model is None:
            self._last_model = None
            self._last_failure_message = result.failure.message_zh
            self.featureTable.setRowCount(0)
            self.metricsLabel.clear()
            self.statusLabel.setText(
                self._tr("decision_research.behavior.failed_experiment").format(
                    reason=result.failure.message_zh,
                )
            )
        else:
            self._last_model = result.model
            self._last_failure_message = None
            self._render_model(result.model)
        self._sync_actions()
        self.trainingResultAccepted.emit(result)

    def _render_model(
        self,
        model: Any,
        *,
        refresh_freshness: bool = True,
    ) -> None:
        maturity = str(model.maturity.value).lower()
        if refresh_freshness or self._freshness_state is None:
            try:
                freshness = self.service.model_freshness(
                    model.model_version_id,
                    target=self._target,
                )
            except Exception:
                self._freshness_state = "unknown"
            else:
                self._freshness_state = (
                    "retraining"
                    if freshness.needs_retraining
                    else "current"
                )
        self.statusLabel.setText(
            self._tr("decision_research.behavior.model_status").format(
                maturity=self._tr(
                    f"decision_research.behavior.maturity.{maturity}"
                ),
                model_id=model.model_version_id,
                freshness=self._tr(
                    "decision_research.behavior.freshness."
                    f"{self._freshness_state}"
                ),
            )
        )
        metrics = model.manifest.test_metrics
        validation = model.manifest.validation_metrics
        self.metricsLabel.setText(
            self._tr("decision_research.behavior.metrics").format(
                samples=metrics.sample_count,
                validation_log_loss=validation.balanced_log_loss,
                log_loss=metrics.balanced_log_loss,
                brier=metrics.brier_score,
                recall=_metric_text(metrics.recall),
                precision=_metric_text(metrics.precision),
                threshold=_metric_text(model.research_threshold),
                domain=_metric_text(model.applicability_threshold),
            )
        )
        self.featureTable.setRowCount(len(model.stable_features))
        for row, feature in enumerate(model.stable_features):
            direction_key = (
                "higher" if feature.coefficient > 0.0 else "lower"
            )
            target_key = (
                "entry"
                if self._target is BehaviorModelTarget.ENTRY_SELECTION
                else "exit"
            )
            values = (
                feature.name_zh,
                self._tr(
                    "decision_research.behavior.direction."
                    f"{target_key}.{direction_key}"
                ),
                f"{feature.coefficient:.4f}",
                (
                    f"{feature.nonzero_fold_count}/{feature.fold_count} · "
                    f"{feature.fold_coefficient_min:.4f} ~ "
                    f"{feature.fold_coefficient_max:.4f}"
                ),
            )
            for column, value in enumerate(values):
                self.featureTable.setItem(
                    row,
                    column,
                    QtWidgets.QTableWidgetItem(value),
                )

    @QtCore.Slot(str)
    def _render_worker_failure(self, message: str) -> None:
        self.progressBar.hide()
        self.statusLabel.setText(
            self._tr("decision_research.behavior.worker_failed").format(
                error=sanitize_worker_error_detail(message),
            )
        )
        self._sync_actions()

    @QtCore.Slot()
    def _render_cancelled(self) -> None:
        self.progressBar.hide()
        self.statusLabel.setText(
            self._tr("decision_research.behavior.cancelled")
        )
        self._sync_actions()

    def _can_train(self) -> bool:
        return bool(
            self._training_operation_allowed
            and self._setup_version_id
            and self._grouping_version_id
            and self._direction in {"LONG", "SHORT"}
            and not self.controller.is_running
        )

    def _sync_actions(self) -> None:
        running = bool(self.controller.is_running)
        self.trainButton.setEnabled(self._can_train())
        self.cancelButton.setEnabled(running)

    def set_training_operation_gate(
        self,
        *,
        allowed: bool,
        message: str,
    ) -> None:
        """Gate training while keeping immutable prior model audits visible."""

        self._training_operation_allowed = bool(allowed)
        gate_message = str(message or "")
        self.trainingGateLabel.setText(gate_message)
        self.trainingGateLabel.setVisible(
            not self._training_operation_allowed
            and bool(gate_message)
        )
        self._sync_actions()

    def retranslate_ui(self, language: str | None = None) -> None:
        if language is not None:
            self.language = language
        target_key = (
            "entry"
            if self._target is BehaviorModelTarget.ENTRY_SELECTION
            else "exit"
        )
        self.titleLabel.setText(
            self._tr(f"decision_research.behavior.{target_key}.title")
        )
        self.explanationLabel.setText(
            self._tr(f"decision_research.behavior.{target_key}.explanation")
        )
        self.trainButton.setText(
            self._tr("decision_research.behavior.train")
        )
        self.cancelButton.setText(
            self._tr("decision_research.behavior.cancel")
        )
        self.metricsTitle.setText(
            self._tr("decision_research.behavior.metrics_title")
        )
        self.featuresTitle.setText(
            self._tr("decision_research.behavior.features_title")
        )
        self.featureTable.setHorizontalHeaderLabels(
            [
                self._tr("decision_research.behavior.column.name"),
                self._tr("decision_research.behavior.column.direction"),
                self._tr("decision_research.behavior.column.coefficient"),
                self._tr("decision_research.behavior.column.stability"),
            ]
        )
        if self._last_model is not None:
            self._render_model(
                self._last_model,
                refresh_freshness=False,
            )
        elif self._last_failure_message is not None:
            self.statusLabel.setText(
                self._tr("decision_research.behavior.failed_experiment").format(
                    reason=self._last_failure_message,
                )
            )
        elif not self.statusLabel.text():
            self.statusLabel.setText(
                self._tr("decision_research.behavior.empty")
            )
        self._sync_actions()

    def apply_theme(self, theme: dict) -> None:
        apply_role_button_styles(self, theme)
        apply_themed_input_styles(self, theme)
        apply_role_button_shadows(self)


def _metric_text(value: float | None) -> str:
    return "—" if value is None else f"{float(value):.3f}"


__all__ = ["EntryBehaviorModelWorkspace"]
