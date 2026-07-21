from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from PySide6 import QtCore, QtWidgets

try:
    from i18n import tr
    from research.entry_candidate_generation import CandidateScanRequest
    from research.exit_candidate_generation import ExitCandidateScanRequest
    from research.entry_similarity import EntrySimilarityResult, SimilarityStatus
    from ui_style import SPACING
    from views.main_window_presentation import (
        apply_role_button_styles,
        apply_themed_input_styles,
    )
    from views.widget_effects import apply_role_button_shadows
except ImportError:  # pragma: no cover - package import path
    from ..i18n import tr
    from ..research.entry_candidate_generation import CandidateScanRequest
    from ..research.exit_candidate_generation import ExitCandidateScanRequest
    from ..research.entry_similarity import EntrySimilarityResult, SimilarityStatus
    from ..ui_style import SPACING
    from .main_window_presentation import (
        apply_role_button_styles,
        apply_themed_input_styles,
    )
    from .widget_effects import apply_role_button_shadows


_BJT = ZoneInfo("Asia/Shanghai")
_CONTENT_MIN_WIDTH = 680
_GROUP_KEYS = {
    "price_path": "price_path",
    "candle_shape": "candle_shape",
    "trend_volatility": "trend_volatility",
    "trading_activity": "trading_activity",
}


class _HorizontalOverflowArea(QtWidgets.QScrollArea):
    """Keep narrow-width overflow without becoming a second page scroller."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._height_sync_pending = False
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Preferred,
        )

    def setWidget(self, widget: QtWidgets.QWidget | None) -> None:
        previous = self.widget()
        if previous is not None:
            previous.removeEventFilter(self)
        super().setWidget(widget)
        if widget is not None:
            widget.installEventFilter(self)
        self._schedule_height_sync()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.widget() and event.type() in (
            QtCore.QEvent.LayoutRequest,
            QtCore.QEvent.Resize,
        ):
            self._schedule_height_sync()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_height_sync()

    def _schedule_height_sync(self) -> None:
        if self._height_sync_pending:
            return
        self._height_sync_pending = True
        QtCore.QTimer.singleShot(0, self, self._sync_content_height)

    def _sync_content_height(self) -> None:
        self._height_sync_pending = False
        content = self.widget()
        if content is None:
            return
        content_layout = content.layout()
        if content_layout is not None:
            content_layout.activate()
        content_height = max(
            content.sizeHint().height(),
            content.minimumSizeHint().height(),
        )
        needs_horizontal_scroll = (
            content.minimumWidth() > self.viewport().width()
        )
        horizontal_height = (
            self.horizontalScrollBar().sizeHint().height()
            if needs_horizontal_scroll
            else 0
        )
        required_height = (
            content_height
            + horizontal_height
            + self.frameWidth() * 2
        )
        if required_height > 0 and self.minimumHeight() != required_height:
            self.setMinimumHeight(required_height)


class EntrySimilarityBrowser(QtWidgets.QWidget):
    """Free-browse view for one audited, non-evidentiary sample pair."""

    formalBatchCreated = QtCore.Signal(object)
    maturityChanged = QtCore.Signal(bool)
    candidateResultAccepted = QtCore.Signal(object)

    def __init__(
        self,
        *,
        service: Any,
        candidate_service: Any | None = None,
        candidate_controller: Any | None = None,
        exit_candidate_service: Any | None = None,
        exit_candidate_controller: Any | None = None,
        language: str = "zh_CN",
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.candidate_service = candidate_service
        self.candidate_controller = candidate_controller
        self.exit_candidate_service = exit_candidate_service
        self.exit_candidate_controller = exit_candidate_controller
        self.language = language
        self._setup_version_id: str | None = None
        self._direction: str | None = None
        self._grouping_version_id: str | None = None
        self._candidate_result = None
        self._entry_mode_active = True
        self._candidate_operation_allowed = False
        self._last_result: EntrySimilarityResult | None = None
        self._status_key: str | None = None
        self._status_params: dict[str, Any] = {}
        self.lastError: Exception | None = None
        self.referencePlaceholders: list[QtWidgets.QLabel] = []
        self._build_ui()
        for controller in (
            self.candidate_controller,
            self.exit_candidate_controller,
        ):
            if controller is None:
                continue
            controller.resultReady.connect(self._render_candidate_result)
            controller.progress.connect(self._render_candidate_progress)
            controller.failed.connect(self._render_candidate_failure)
            controller.cancelled.connect(self._render_candidate_cancelled)
        self.retranslate_ui(language)

    def _tr(self, key: str) -> str:
        return tr(key, self.language)

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.scrollArea = _HorizontalOverflowArea()
        self.content = QtWidgets.QWidget()
        self.content.setMinimumWidth(_CONTENT_MIN_WIDTH)
        layout = QtWidgets.QVBoxLayout(self.content)
        layout.setContentsMargins(
            SPACING["md"],
            SPACING["md"],
            SPACING["md"],
            SPACING["md"],
        )
        layout.setSpacing(SPACING["md"])

        self.candidateTitle = QtWidgets.QLabel()
        self.candidateTitle.setProperty("role", "sectionTitle")
        candidate_actions = QtWidgets.QHBoxLayout()
        self.scanCandidatesButton = QtWidgets.QPushButton()
        self.scanCandidatesButton.setProperty("role", "primaryButton")
        self.cancelScanButton = QtWidgets.QPushButton()
        self.cancelScanButton.setProperty("role", "secondaryButton")
        self.createBatchButton = QtWidgets.QPushButton()
        self.createBatchButton.setProperty("role", "primaryButton")
        self.scanCandidatesButton.clicked.connect(self._scan_candidates)
        self.cancelScanButton.clicked.connect(self._cancel_candidate_scan)
        self.createBatchButton.clicked.connect(self._create_candidate_batch)
        for button in (self.scanCandidatesButton, self.cancelScanButton, self.createBatchButton):
            candidate_actions.addWidget(button)
        candidate_actions.addStretch(1)
        self.candidateSummaryLabel = QtWidgets.QLabel()
        self.candidateSummaryLabel.setProperty("role", "statusBlock")
        self.candidateSummaryLabel.setWordWrap(True)
        self.candidateGateLabel = QtWidgets.QLabel()
        self.candidateGateLabel.setProperty("role", "pillWarning")
        self.candidateGateLabel.setWordWrap(True)
        self.candidateGateLabel.hide()
        self.candidateProgress = QtWidgets.QProgressBar()
        self.candidateProgress.setRange(0, 100)
        self.candidateProgress.hide()
        layout.addWidget(self.candidateTitle)
        layout.addLayout(candidate_actions)
        layout.addWidget(self.candidateGateLabel)
        layout.addWidget(self.candidateSummaryLabel)
        layout.addWidget(self.candidateProgress)

        self.titleLabel = QtWidgets.QLabel()
        self.titleLabel.setProperty("role", "sectionTitle")
        self.formulaExplanation = QtWidgets.QLabel()
        self.formulaExplanation.setProperty("role", "mutedText")
        self.formulaExplanation.setWordWrap(True)
        self.evidenceWarning = QtWidgets.QLabel()
        self.evidenceWarning.setProperty("role", "pillWarning")
        self.evidenceWarning.setWordWrap(True)
        layout.addWidget(self.titleLabel)
        layout.addWidget(self.formulaExplanation)
        layout.addWidget(self.evidenceWarning)

        selectors = QtWidgets.QHBoxLayout()
        selectors.setSpacing(SPACING["sm"])
        self.leftSampleCaption = QtWidgets.QLabel()
        self.rightSampleCaption = QtWidgets.QLabel()
        self.leftSampleBox = QtWidgets.QComboBox()
        self.rightSampleBox = QtWidgets.QComboBox()
        self.compareButton = QtWidgets.QPushButton()
        self.compareButton.setProperty("role", "primaryButton")
        self.compareButton.clicked.connect(self._compare_selected)
        for widget in (
            self.leftSampleCaption,
            self.leftSampleBox,
            self.rightSampleCaption,
            self.rightSampleBox,
            self.compareButton,
        ):
            selectors.addWidget(widget)
        selectors.setStretchFactor(self.leftSampleBox, 1)
        selectors.setStretchFactor(self.rightSampleBox, 1)
        layout.addLayout(selectors)

        summary = QtWidgets.QHBoxLayout()
        summary.setSpacing(SPACING["sm"])
        self.totalSimilarityLabel = QtWidgets.QLabel()
        self.marketDistanceLabel = QtWidgets.QLabel()
        self.calendarDistanceLabel = QtWidgets.QLabel()
        for label in (
            self.totalSimilarityLabel,
            self.marketDistanceLabel,
            self.calendarDistanceLabel,
        ):
            label.setProperty("role", "statusBlock")
            summary.addWidget(label, stretch=1)
        layout.addLayout(summary)

        self.statusLabel = QtWidgets.QLabel()
        self.statusLabel.setProperty("role", "mutedText")
        self.statusLabel.setWordWrap(True)
        layout.addWidget(self.statusLabel)
        self.breakdownTree = QtWidgets.QTreeWidget()
        self.breakdownTree.setColumnCount(4)
        self.breakdownTree.setRootIsDecorated(True)
        self.breakdownTree.setAlternatingRowColors(True)
        layout.addWidget(self.breakdownTree, stretch=1)

        self.referencesTitle = QtWidgets.QLabel()
        self.referencesTitle.setProperty("role", "sectionTitle")
        layout.addWidget(self.referencesTitle)
        for _index in range(3):
            label = QtWidgets.QLabel()
            label.setProperty("role", "mutedText")
            self.referencePlaceholders.append(label)
            layout.addWidget(label)
        self.scrollArea.setWidget(self.content)
        root.addWidget(self.scrollArea)

    def set_research_context(
        self,
        *,
        setup_version_id: str | None,
        direction: str | None,
        grouping_version_id: str | None = None,
    ) -> None:
        context_changed = (
            setup_version_id,
            direction,
            grouping_version_id,
        ) != (
            self._setup_version_id,
            self._direction,
            self._grouping_version_id,
        )
        if context_changed:
            for controller in (
                self.candidate_controller,
                self.exit_candidate_controller,
            ):
                invalidate = getattr(controller, "invalidate", None)
                if callable(invalidate):
                    invalidate()
        if not context_changed and setup_version_id and direction:
            self._sync_compare_enabled()
            self._sync_candidate_actions(
                running=bool(
                    self._active_candidate_controller() is not None
                    and getattr(
                        self._active_candidate_controller(),
                        "is_running",
                        False,
                    )
                )
            )
            return
        self._setup_version_id = setup_version_id
        self._direction = direction
        self._grouping_version_id = grouping_version_id
        self._candidate_result = None
        self.candidateProgress.hide()
        self.candidateSummaryLabel.setText(
            self._tr("decision_research.candidates.empty")
        )
        self.leftSampleBox.clear()
        self.rightSampleBox.clear()
        self.breakdownTree.clear()
        self._last_result = None
        if not setup_version_id or not direction:
            self._set_status("decision_research.similarity.status.context_missing")
            self._sync_compare_enabled()
            self._sync_candidate_actions()
            return
        if not self._entry_mode_active:
            self._set_status("decision_research.similarity.status.exit_candidate_mode")
            self._sync_compare_enabled()
            self._sync_candidate_actions()
            return
        self._load_browsable_entry_samples()
        self._sync_candidate_actions()

    def _load_browsable_entry_samples(self) -> None:
        if not self._setup_version_id or not self._direction:
            return
        self.leftSampleBox.clear()
        self.rightSampleBox.clear()
        self.breakdownTree.clear()
        self._last_result = None
        try:
            samples = self.service.list_browsable_samples(
                setup_version_id=self._setup_version_id,
                direction=self._direction,
            )
        except Exception as exc:
            self._show_failure(exc)
            return
        self.lastError = None
        for sample in samples:
            text = self._sample_text(sample)
            self.leftSampleBox.addItem(text, sample.decision_event_id)
            self.rightSampleBox.addItem(text, sample.decision_event_id)
        if self.rightSampleBox.count() > 1:
            self.rightSampleBox.setCurrentIndex(1)
        self._set_status(
            "decision_research.similarity.status.samples",
            count=len(samples),
        )
        self._sync_compare_enabled()

    def _scan_candidates(self) -> None:
        if (
            self._active_candidate_controller() is None
            or not self._candidate_operation_allowed
        ):
            return
        self._candidate_result = None
        self.candidateSummaryLabel.setText(
            self._tr("decision_research.candidates.scanning")
        )
        self.candidateProgress.setValue(0)
        self.candidateProgress.show()
        request_type = (
            CandidateScanRequest
            if self._entry_mode_active
            else ExitCandidateScanRequest
        )
        controller = self._active_candidate_controller()
        assert controller is not None
        controller.start(
            request_type(
                setup_version_id=self._setup_version_id,
                grouping_version_id=self._grouping_version_id,
                direction=self._direction,
            )
        )
        running = bool(getattr(controller, "is_running", False))
        if not running:
            self.candidateProgress.hide()
        self._sync_candidate_actions(running=running)

    def _cancel_candidate_scan(self) -> None:
        controller = self._active_candidate_controller()
        if controller is not None:
            controller.cancel()

    def _render_candidate_progress(self, event: Any) -> None:
        percent = 0 if not event.total else int(event.completed * 100 / event.total)
        self.candidateProgress.setValue(percent)

    def _render_candidate_result(self, result: Any) -> None:
        self._candidate_result = result
        self.candidateProgress.hide()
        maturity = result.maturity
        self.maturityChanged.emit(bool(maturity.ready))
        distribution = result.similarity_distribution
        summary_key = (
            "decision_research.candidates.summary"
            if self._entry_mode_active
            else "decision_research.exit_candidates.summary"
        )
        maturity_values = (
            {
                "entries": maturity.complete_entry_count,
                "entry_episodes": maturity.entry_episode_count,
                "missing_entries": maturity.missing_entry_count,
                "missing_episodes": maturity.missing_episode_count,
            }
            if self._entry_mode_active
            else {
                "entries": maturity.complete_exit_now_count,
                "entry_episodes": maturity.holding_episode_count,
                "missing_entries": maturity.missing_exit_now_count,
                "missing_episodes": maturity.missing_holding_episode_count,
            }
        )
        self.candidateSummaryLabel.setText(
            self._tr(summary_key).format(
                count=result.usable_candidate_count,
                universe=result.candidate_universe_count,
                episodes=result.episode_coverage_count,
                unavailable=result.unavailable_candidate_count,
                **maturity_values,
                score_distribution=self._tr(
                    "decision_research.candidates.score_distribution"
                ).format(
                    score_80_to_100=distribution.score_80_to_100,
                    score_60_to_under_80=distribution.score_60_to_under_80,
                    score_0_to_under_60=distribution.score_0_to_under_60,
                ),
            )
        )
        self._sync_candidate_actions()
        self.candidateResultAccepted.emit(result)

    def _render_candidate_failure(self, _message: str) -> None:
        self.candidateProgress.hide()
        self.candidateSummaryLabel.setText(self._tr("decision_research.candidates.failed"))
        self._sync_candidate_actions()

    def _render_candidate_cancelled(self) -> None:
        self.candidateProgress.hide()
        self.candidateSummaryLabel.setText(self._tr("decision_research.candidates.cancelled"))
        self._sync_candidate_actions()

    def _create_candidate_batch(self) -> None:
        if (
            self._active_candidate_service() is None
            or self._candidate_result is None
            or not self._candidate_operation_allowed
        ):
            return
        try:
            formal = self._active_candidate_service().create_blind_review_batch(
                scan_id=self._candidate_result.scan_id
            )
        except Exception as exc:
            self.lastError = exc
            self.candidateSummaryLabel.setText(
                self._tr("decision_research.candidates.batch_failed")
            )
            self.createBatchButton.setEnabled(False)
            return
        self.lastError = None
        self.candidateSummaryLabel.setText(
            self._tr("decision_research.candidates.batch").format(
                total=len(formal.batch.items),
                high=formal.high_similarity_count,
                diverse=formal.diverse_count,
            )
        )
        self.formalBatchCreated.emit(formal.batch)

    def _sync_candidate_actions(self, running: bool = False) -> None:
        context_ready = bool(
            self._setup_version_id
            and self._direction
            and self._grouping_version_id
            and self._active_candidate_controller() is not None
        )
        self.scanCandidatesButton.setEnabled(
            context_ready
            and self._candidate_operation_allowed
            and not running
        )
        self.cancelScanButton.setEnabled(context_ready and running)
        self.createBatchButton.setEnabled(
            not running
            and self._candidate_operation_allowed
            and self._candidate_result is not None
            and self._candidate_result.usable_candidate_count > 0
        )

    def set_candidate_operation_gate(
        self,
        *,
        allowed: bool,
        message: str,
    ) -> None:
        """Gate formal scanning/batching without blocking free sample browse."""

        self._candidate_operation_allowed = bool(allowed)
        gate_message = str(message or "")
        self.candidateGateLabel.setText(gate_message)
        self.candidateGateLabel.setVisible(
            not self._candidate_operation_allowed
            and bool(gate_message)
        )
        self._sync_candidate_actions(
            running=bool(
                self._active_candidate_controller() is not None
                and getattr(
                    self._active_candidate_controller(),
                    "is_running",
                    False,
                )
            )
        )

    def set_entry_mode_active(self, active: bool) -> None:
        changed = self._entry_mode_active != bool(active)
        if changed:
            for controller in (
                self.candidate_controller,
                self.exit_candidate_controller,
            ):
                invalidate = getattr(controller, "invalidate", None)
                if callable(invalidate):
                    invalidate()
        self._entry_mode_active = bool(active)
        self.content.setVisible(True)
        self._candidate_result = None
        self.candidateSummaryLabel.setText(
            self._tr("decision_research.candidates.empty")
        )
        if not self._entry_mode_active:
            self.leftSampleBox.clear()
            self.rightSampleBox.clear()
            self.breakdownTree.clear()
            self._set_status("decision_research.similarity.status.exit_candidate_mode")
        elif changed:
            self._load_browsable_entry_samples()
        self._sync_compare_enabled()
        self._sync_candidate_actions()
        self.retranslate_ui()

    def _active_candidate_service(self):
        return (
            self.candidate_service
            if self._entry_mode_active
            else self.exit_candidate_service
        )

    def _active_candidate_controller(self):
        return (
            self.candidate_controller
            if self._entry_mode_active
            else self.exit_candidate_controller
        )

    def _sample_text(self, sample: Any) -> str:
        cutoff = datetime.fromtimestamp(
            sample.decision_cutoff_utc_ms / 1_000,
            UTC,
        ).astimezone(_BJT)
        return self._tr("decision_research.similarity.sample").format(
            symbol=sample.symbol,
            time=cutoff.strftime("%Y-%m-%d %H:%M"),
        )

    @QtCore.Slot()
    def _compare_selected(self) -> None:
        left_id = self.leftSampleBox.currentData()
        right_id = self.rightSampleBox.currentData()
        if not left_id or not right_id or left_id == right_id:
            self._set_status("decision_research.similarity.status.choose_distinct")
            return
        try:
            result = self.service.compare_revealed_samples(
                str(left_id),
                str(right_id),
            )
        except Exception as exc:
            self._show_failure(exc)
            return
        self.lastError = None
        self.render_result(result)

    def render_result(self, result: EntrySimilarityResult) -> None:
        self._last_result = result
        self.totalSimilarityLabel.setText(
            self._tr("decision_research.similarity.summary.total").format(
                value="—" if result.similarity is None else f"{result.similarity:.2f}"
            )
        )
        self.marketDistanceLabel.setText(
            self._tr("decision_research.similarity.summary.market").format(
                value="—" if result.market_distance is None else f"{result.market_distance:.4f}"
            )
        )
        self.calendarDistanceLabel.setText(
            self._tr("decision_research.similarity.summary.calendar").format(
                value=f"{result.calendar.distance:.4f}"
            )
        )
        self.breakdownTree.clear()
        for timeframe in result.timeframes:
            role = self._tr(
                f"decision_research.similarity.timeframe.{timeframe.role}"
            )
            top = QtWidgets.QTreeWidgetItem(
                [
                    f"{role} · {timeframe.interval}",
                    _distance_text(timeframe.distance),
                    "",
                    self._availability_text(timeframe.distance is not None),
                ]
            )
            self.breakdownTree.addTopLevelItem(top)
            for group in timeframe.groups:
                group_item = QtWidgets.QTreeWidgetItem(
                    [
                        self._tr(
                            "decision_research.similarity.group."
                            f"{_GROUP_KEYS[group.name]}"
                        ),
                        _distance_text(group.distance),
                        f"{group.comparable_count}/{group.total_count} · "
                        f"{group.completeness_ratio * 100:.1f}%",
                        self._availability_text(group.distance is not None),
                    ]
                )
                top.addChild(group_item)
                for feature in group.features:
                    group_item.addChild(
                        QtWidgets.QTreeWidgetItem(
                            [
                                self._tr(
                                    "decision_research.similarity.feature."
                                    f"{feature.name}"
                                ),
                                _distance_text(feature.distance),
                                "1/1" if feature.comparable else "0/1",
                                self._feature_availability_text(feature),
                            ]
                        )
                    )
        self.breakdownTree.expandToDepth(1)
        if result.status is SimilarityStatus.COMPUTED:
            self._set_status("decision_research.similarity.status.computed")
        else:
            self._set_status(
                "decision_research.similarity.status.not_computable",
                details=self._not_computable_details(result),
            )

    def _availability_text(self, available: bool) -> str:
        return self._tr(
            "decision_research.similarity.availability."
            f"{'available' if available else 'unavailable'}"
        )

    def _feature_availability_text(self, feature: Any) -> str:
        if feature.comparable:
            return self._availability_text(True)
        reason = str(feature.unavailable_reason or "")
        if "missing_bar_continuity" in reason:
            category = "bar_gap"
        elif "insufficient_history" in reason:
            category = "history"
        elif "zero_" in reason:
            category = "real_zero"
        elif "atr" in reason:
            category = "atr"
        elif "range" in reason or "ohlc" in reason:
            category = "price_range"
        elif "missing" in reason:
            category = "field_missing"
        else:
            category = "invalid"
        return self._tr(
            f"decision_research.similarity.reason.{category}"
        )

    def _not_computable_details(self, result: EntrySimilarityResult) -> str:
        deficits = []
        for timeframe in result.timeframes:
            for group in timeframe.groups:
                if group.distance is not None:
                    continue
                deficits.append(
                    self._tr(
                        "decision_research.similarity.status.group_deficit"
                    ).format(
                        interval=timeframe.interval,
                        group=self._tr(
                            "decision_research.similarity.group."
                            f"{_GROUP_KEYS[group.name]}"
                        ),
                        comparable=group.comparable_count,
                        total=group.total_count,
                        ratio=f"{group.completeness_ratio * 100:.1f}",
                    )
                )
        if deficits:
            return self._tr("decision_research.list_separator").join(deficits)
        return self._tr("decision_research.similarity.status.missing_details")

    def _set_status(self, key: str, **params: Any) -> None:
        self._status_key = key
        self._status_params = dict(params)
        self.statusLabel.setText(self._tr(key).format(**params))

    def _show_failure(self, error: Exception) -> None:
        self.lastError = error
        self._set_status("decision_research.similarity.status.failed")
        self._sync_compare_enabled()

    def _sync_compare_enabled(self) -> None:
        self.compareButton.setEnabled(
            self._entry_mode_active
            and self.leftSampleBox.count() >= 2
            and self.rightSampleBox.count() >= 2
        )

    def retranslate_ui(self, language: str | None = None) -> None:
        if language is not None:
            self.language = language
        self.titleLabel.setText(
            self._tr(
                "decision_research.similarity.title"
                if self._entry_mode_active
                else "decision_research.exit_similarity.title"
            )
        )
        self.candidateTitle.setText(
            self._tr(
                "decision_research.candidates.title"
                if self._entry_mode_active
                else "decision_research.exit_candidates.title"
            )
        )
        self.scanCandidatesButton.setText(self._tr("decision_research.candidates.scan"))
        self.cancelScanButton.setText(self._tr("decision_research.candidates.cancel"))
        self.createBatchButton.setText(self._tr("decision_research.candidates.create_batch"))
        if self._candidate_result is None and not self.candidateSummaryLabel.text():
            self.candidateSummaryLabel.setText(self._tr("decision_research.candidates.empty"))
        self.formulaExplanation.setText(
            self._tr(
                "decision_research.similarity.formula"
                if self._entry_mode_active
                else "decision_research.exit_similarity.formula"
            )
        )
        self.evidenceWarning.setText(
            self._tr("decision_research.similarity.evidence_warning")
        )
        self.leftSampleCaption.setText(
            self._tr("decision_research.similarity.sample_left")
        )
        self.rightSampleCaption.setText(
            self._tr("decision_research.similarity.sample_right")
        )
        self.compareButton.setText(
            self._tr("decision_research.similarity.compare")
        )
        self.breakdownTree.setHeaderLabels(
            [
                self._tr("decision_research.similarity.column.component"),
                self._tr("decision_research.similarity.column.distance"),
                self._tr("decision_research.similarity.column.completeness"),
                self._tr("decision_research.similarity.column.status"),
            ]
        )
        self.referencesTitle.setText(
            self._tr("decision_research.similarity.references")
        )
        for index, label in enumerate(self.referencePlaceholders, start=1):
            label.setText(
                self._tr("decision_research.similarity.reference_placeholder").format(
                    number=index
                )
            )
        if self._last_result is not None:
            self.render_result(self._last_result)
        elif self._status_key is not None:
            self._set_status(self._status_key, **self._status_params)

    def apply_theme(self, theme: dict | None) -> None:
        apply_role_button_styles(self, theme)
        apply_themed_input_styles(self, theme)
        apply_role_button_shadows(self)


def _distance_text(value: float | None) -> str:
    return "—" if value is None else f"{value:.4f}"


__all__ = ["EntrySimilarityBrowser"]
