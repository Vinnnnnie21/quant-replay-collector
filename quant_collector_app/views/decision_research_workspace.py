from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    try:
        from research.market_episodes import EpisodeAuditSummary
    except ImportError:  # pragma: no cover - package import path
        from ..research.market_episodes import EpisodeAuditSummary

from PySide6 import QtCore, QtWidgets

try:
    from decision_research_state import (
        DIRECTIONS,
        PRIMARY_TABS,
        RESEARCH_STEPS,
        RESEARCH_TIMEFRAMES,
        DecisionResearchPageState,
    )
    from i18n import tr
    from research.setups import (
        SetupLookupError,
        SetupLibrary,
        SetupPersistenceError,
        SetupValidationError,
        SetupVersion,
        SetupWithVersion,
    )
    from services.ui_message_localizer import sanitize_worker_error_detail
    from ui_style import SPACING
    from views.main_window_presentation import (
        apply_role_button_styles,
        apply_themed_input_styles,
    )
    from views.widget_effects import apply_role_button_shadows
    from views.setup_editor import SetupEditorForm
    from views.entry_blind_review_workspace import EntryBlindReviewWorkspace
    from views.entry_similarity_browser import EntrySimilarityBrowser
    from views.entry_behavior_model_workspace import (
        EntryBehaviorModelWorkspace,
    )
    from views.entry_outcome_comparison_workspace import (
        EntryOutcomeComparisonWorkspace,
    )
    from views.research_snapshot_workspace import ResearchSnapshotWorkspace
except ImportError:  # pragma: no cover - package import path
    from ..decision_research_state import (
        DIRECTIONS,
        PRIMARY_TABS,
        RESEARCH_STEPS,
        RESEARCH_TIMEFRAMES,
        DecisionResearchPageState,
    )
    from ..i18n import tr
    from ..research.setups import (
        SetupLookupError,
        SetupLibrary,
        SetupPersistenceError,
        SetupValidationError,
        SetupVersion,
        SetupWithVersion,
    )
    from ..services.ui_message_localizer import sanitize_worker_error_detail
    from ..ui_style import SPACING
    from .main_window_presentation import (
        apply_role_button_styles,
        apply_themed_input_styles,
    )
    from .widget_effects import apply_role_button_shadows
    from .setup_editor import SetupEditorForm
    from .entry_blind_review_workspace import EntryBlindReviewWorkspace
    from .entry_similarity_browser import EntrySimilarityBrowser
    from .entry_behavior_model_workspace import (
        EntryBehaviorModelWorkspace,
    )
    from .entry_outcome_comparison_workspace import (
        EntryOutcomeComparisonWorkspace,
    )
    from .research_snapshot_workspace import ResearchSnapshotWorkspace

def _horizontal_scroll_area(
    content: QtWidgets.QWidget,
) -> QtWidgets.QScrollArea:
    scroll = QtWidgets.QScrollArea()
    scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    scroll.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.AdjustToContents)
    scroll.setSizePolicy(
        QtWidgets.QSizePolicy.Expanding,
        QtWidgets.QSizePolicy.Fixed,
    )
    scroll.setWidget(content)
    return scroll


def _missing_conditions_message(
    *,
    step: str,
    state: DecisionResearchPageState,
    translator: Callable[[str], str],
    data_deficit_text: str,
) -> str:
    missing = state.missing_conditions(step)
    if not missing:
        return ""
    separator = translator("decision_research.list_separator")
    conditions = separator.join(
        (
            data_deficit_text
            if condition == "completeness" and data_deficit_text
            else translator(f"decision_research.missing.{condition}")
        )
        for condition in missing
    )
    return translator("decision_research.gate.missing").format(
        conditions=conditions
    )


class DecisionResearchStepPage(QtWidgets.QFrame):
    """Shared empty and gate presentation for one workflow step."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING["md"])

        self.emptyState = QtWidgets.QFrame()
        self.emptyState.setProperty("role", "emptyState")
        empty_layout = QtWidgets.QVBoxLayout(self.emptyState)
        empty_layout.setContentsMargins(
            SPACING["xl"],
            SPACING["xl"],
            SPACING["xl"],
            SPACING["xl"],
        )
        empty_layout.setSpacing(SPACING["sm"])
        self.titleLabel = QtWidgets.QLabel()
        self.titleLabel.setProperty("role", "emptyTitle")
        self.titleLabel.setAlignment(QtCore.Qt.AlignCenter)
        self.bodyLabel = QtWidgets.QLabel()
        self.bodyLabel.setProperty("role", "emptyText")
        self.bodyLabel.setAlignment(QtCore.Qt.AlignCenter)
        self.bodyLabel.setWordWrap(True)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.titleLabel)
        empty_layout.addWidget(self.bodyLabel)
        empty_layout.addStretch(1)
        layout.addWidget(self.emptyState, stretch=1)

        gate_row = QtWidgets.QHBoxLayout()
        gate_row.setSpacing(SPACING["md"])
        self.gateHint = QtWidgets.QLabel()
        self.gateHint.setProperty("role", "pillWarning")
        self.gateHint.setWordWrap(True)
        self.actionButton = QtWidgets.QPushButton()
        self.actionButton.setProperty("role", "primaryButton")
        gate_row.addWidget(self.gateHint, stretch=1)
        gate_row.addWidget(self.actionButton)
        layout.addLayout(gate_row)

    def render(
        self,
        *,
        step: str,
        state: DecisionResearchPageState,
        translator: Callable[[str], str],
        data_deficit_text: str = "",
    ) -> None:
        self.titleLabel.setText(translator(f"decision_research.step.{step}"))
        self.bodyLabel.setText(translator("decision_research.empty.body"))
        self.actionButton.setText(
            translator(f"decision_research.action.{step}")
        )
        missing_message = _missing_conditions_message(
            step=step,
            state=state,
            translator=translator,
            data_deficit_text=data_deficit_text,
        )
        self.actionButton.setEnabled(False)
        if missing_message:
            self.gateHint.setText(missing_message)
            self.gateHint.show()
        else:
            self.gateHint.setText(
                translator("decision_research.gate.ready")
            )
            self.gateHint.show()


class DecisionResearchWorkspace(QtWidgets.QWidget):
    """Shared entry/exit decision-research shell with one persistent state."""

    auditRequested = QtCore.Signal()
    backfillRequested = QtCore.Signal()
    cancelRequested = QtCore.Signal()
    retryRequested = QtCore.Signal()
    researchContextChanged = QtCore.Signal()
    episodeCorrectionRequested = QtCore.Signal(str)
    snapshotPublishRequested = QtCore.Signal()
    snapshotCancelRequested = QtCore.Signal()
    snapshotVersionRequested = QtCore.Signal(str)
    snapshotDraftRequested = QtCore.Signal()

    def __init__(
        self,
        *,
        language: str = "zh_CN",
        state: DecisionResearchPageState | None = None,
        setup_library: SetupLibrary | None = None,
        entry_review_controller=None,
        exit_review_controller=None,
        similarity_service=None,
        candidate_service=None,
        candidate_controller=None,
        exit_candidate_service=None,
        exit_candidate_controller=None,
        behavior_training_service=None,
        behavior_training_controller=None,
        outcome_comparison_service=None,
        outcome_comparison_controller=None,
        exit_outcome_comparison_service=None,
        exit_outcome_comparison_controller=None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Ignored,
        )
        self.language = language
        self.state = state or DecisionResearchPageState()
        self.setup_library = setup_library
        self.entry_review_controller = entry_review_controller
        self.exit_review_controller = exit_review_controller
        self.similarity_service = similarity_service
        self.candidate_service = candidate_service
        self.candidate_controller = candidate_controller
        self.exit_candidate_service = exit_candidate_service
        self.exit_candidate_controller = exit_candidate_controller
        self.behavior_training_service = behavior_training_service
        self.behavior_training_controller = behavior_training_controller
        self.outcome_comparison_service = outcome_comparison_service
        self.outcome_comparison_controller = outcome_comparison_controller
        self.exit_outcome_comparison_service = exit_outcome_comparison_service
        self.exit_outcome_comparison_controller = exit_outcome_comparison_controller
        self.contextFieldLabels: dict[str, QtWidgets.QLabel] = {}
        self.stepButtons: dict[str, QtWidgets.QPushButton] = {}
        self.stepPages: dict[str, QtWidgets.QWidget] = {}
        self.entryBlindReviewWorkspace: EntryBlindReviewWorkspace | None = None
        self.entrySimilarityBrowser: EntrySimilarityBrowser | None = None
        self.entryBehaviorModelWorkspace: (
            EntryBehaviorModelWorkspace | None
        ) = None
        self.entryOutcomeComparisonWorkspace: (
            EntryOutcomeComparisonWorkspace | None
        ) = None
        self.researchSnapshotWorkspace: ResearchSnapshotWorkspace | None = None
        self.timeframeCompletenessLabels: list[QtWidgets.QLabel] = []
        self._completeness_report = None
        self._data_deficit_text = ""
        self._completeness_reports = {"entry": None, "exit": None}
        self._data_deficit_texts = {"entry": "", "exit": ""}
        self._selected_setup_archived = False
        self._setup_error_code: str | None = None
        self._episode_summary = None
        self._episode_summaries = {"entry": None, "exit": None}
        self._page_scroll_positions: dict[tuple[str, str], int] = {}
        self.setupEditorForm: SetupEditorForm | None = None
        self._theme: dict | None = None
        self._build_ui()
        self.retranslate_ui(language)
        self._sync_controls_from_state()

    def _tr(self, key: str) -> str:
        return tr(key, self.language)

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(
            SPACING["md"],
            SPACING["md"],
            SPACING["md"],
            SPACING["md"],
        )
        root.setSpacing(SPACING["md"])

        self.modeTabs = QtWidgets.QTabBar()
        self.modeTabs.setExpanding(False)
        for primary_tab in PRIMARY_TABS:
            index = self.modeTabs.addTab("")
            self.modeTabs.setTabData(index, primary_tab)
        self.modeTabs.currentChanged.connect(self._on_primary_tab_changed)
        root.addWidget(self.modeTabs)

        self.contextBar = QtWidgets.QFrame()
        self.contextBar.setProperty("role", "workspaceToolbar")
        context_layout = QtWidgets.QHBoxLayout(self.contextBar)
        context_layout.setSizeConstraint(QtWidgets.QLayout.SetMinimumSize)
        context_layout.setContentsMargins(
            SPACING["md"],
            SPACING["sm"],
            SPACING["md"],
            SPACING["sm"],
        )
        context_layout.setSpacing(SPACING["md"])

        self.setupValueLabel = QtWidgets.QLabel()
        self.setupValueLabel.setProperty("role", "pillMuted")
        self.setupValueLabel.hide()
        self.setupBox = QtWidgets.QComboBox()
        self.versionBox = QtWidgets.QComboBox()

        self.directionBox = QtWidgets.QComboBox()
        for direction in DIRECTIONS:
            self.directionBox.addItem("", direction)

        self.decisionTimeframeBox = QtWidgets.QComboBox()
        self.contextTimeframeOneBox = QtWidgets.QComboBox()
        self.contextTimeframeTwoBox = QtWidgets.QComboBox()
        for combo in (
            self.decisionTimeframeBox,
            self.contextTimeframeOneBox,
            self.contextTimeframeTwoBox,
        ):
            combo.addItems(RESEARCH_TIMEFRAMES)

        self.completenessLabel = QtWidgets.QLabel()
        self.completenessLabel.setProperty("role", "pillWarning")
        self.maturityLabel = QtWidgets.QLabel()
        self.maturityLabel.setProperty("role", "pillMuted")
        for field, control in (
            ("setup", self.setupBox),
            ("setup_version", self.versionBox),
            ("direction", self.directionBox),
            ("decision_timeframe", self.decisionTimeframeBox),
            ("context_timeframe_one", self.contextTimeframeOneBox),
            ("context_timeframe_two", self.contextTimeframeTwoBox),
            ("completeness", self.completenessLabel),
            ("maturity", self.maturityLabel),
        ):
            field_widget = QtWidgets.QWidget()
            field_layout = QtWidgets.QVBoxLayout(field_widget)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(SPACING["xs"])
            field_label = QtWidgets.QLabel()
            field_label.setProperty("role", "mutedText")
            self.contextFieldLabels[field] = field_label
            field_layout.addWidget(field_label)
            field_layout.addWidget(control)
            context_layout.addWidget(field_widget)
        context_layout.addStretch(1)
        self.contextScroll = _horizontal_scroll_area(self.contextBar)
        root.addWidget(self.contextScroll)

        self.pageScroll = QtWidgets.QScrollArea()
        self.pageScroll.setObjectName("decisionResearchPageScroll")
        self.pageScroll.setWidgetResizable(True)
        self.pageScroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.pageScroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarAlwaysOff
        )
        self.pageScroll.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarAsNeeded
        )
        self.pageContent = QtWidgets.QWidget()
        self.pageContent.setObjectName("decisionResearchPageContent")
        body = QtWidgets.QVBoxLayout(self.pageContent)
        body.setSizeConstraint(QtWidgets.QLayout.SetMinimumSize)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(SPACING["md"])
        self.pageScroll.setWidget(self.pageContent)
        root.addWidget(self.pageScroll, stretch=1)

        self.setupStatusLabel = QtWidgets.QLabel()
        self.setupStatusLabel.setProperty("role", "pillWarning")
        self.setupStatusLabel.setWordWrap(True)
        self.setupStatusLabel.hide()
        body.addWidget(self.setupStatusLabel)

        self.setupActions = QtWidgets.QWidget()
        setup_action_layout = QtWidgets.QHBoxLayout(self.setupActions)
        setup_action_layout.setContentsMargins(0, 0, 0, 0)
        setup_action_layout.setSpacing(SPACING["sm"])
        self.btnCreateSetup = QtWidgets.QPushButton()
        self.btnCreateSetup.setProperty("role", "primaryButton")
        self.btnCreateSetupVersion = QtWidgets.QPushButton()
        self.btnCreateSetupVersion.setProperty("role", "secondaryButton")
        self.btnRenameSetup = QtWidgets.QPushButton()
        self.btnRenameSetup.setProperty("role", "secondaryButton")
        self.btnArchiveSetup = QtWidgets.QPushButton()
        self.btnArchiveSetup.setProperty("role", "secondaryButton")
        for button in (
            self.btnCreateSetup,
            self.btnCreateSetupVersion,
            self.btnRenameSetup,
            self.btnArchiveSetup,
        ):
            setup_action_layout.addWidget(button)
        setup_action_layout.addStretch(1)
        self.setupActionScroll = _horizontal_scroll_area(
            self.setupActions
        )
        body.addWidget(self.setupActionScroll)

        self.setupEditorContainer = QtWidgets.QFrame()
        self.setupEditorContainer.setProperty("role", "workspaceToolbar")
        self.setupEditorLayout = QtWidgets.QVBoxLayout(
            self.setupEditorContainer
        )
        self.setupEditorLayout.setContentsMargins(0, 0, 0, 0)
        self.setupEditorContainer.hide()
        body.addWidget(self.setupEditorContainer)

        self.dataAvailabilityPanel = QtWidgets.QFrame()
        self.dataAvailabilityPanel.setProperty("role", "workspaceToolbar")
        availability_layout = QtWidgets.QVBoxLayout(
            self.dataAvailabilityPanel
        )
        availability_layout.setContentsMargins(
            SPACING["md"],
            SPACING["sm"],
            SPACING["md"],
            SPACING["sm"],
        )
        availability_layout.setSpacing(SPACING["sm"])
        availability_header = QtWidgets.QHBoxLayout()
        self.dataAvailabilityTitle = QtWidgets.QLabel()
        self.dataAvailabilityTitle.setProperty("role", "sectionTitle")
        availability_header.addWidget(self.dataAvailabilityTitle)
        availability_header.addStretch(1)
        self.btnAuditResearchData = QtWidgets.QPushButton()
        self.btnAuditResearchData.setProperty("role", "secondaryButton")
        self.btnBackfillResearchRange = QtWidgets.QPushButton()
        self.btnBackfillResearchRange.setProperty("role", "primaryButton")
        self.btnCancelBackfill = QtWidgets.QPushButton()
        self.btnCancelBackfill.setProperty("role", "secondaryButton")
        self.btnRetryBackfill = QtWidgets.QPushButton()
        self.btnRetryBackfill.setProperty("role", "primaryButton")
        availability_layout.addLayout(availability_header)
        availability_actions = QtWidgets.QWidget()
        availability_action_row = QtWidgets.QHBoxLayout(
            availability_actions
        )
        availability_action_row.setContentsMargins(0, 0, 0, 0)
        availability_action_row.setSpacing(SPACING["sm"])
        availability_action_row.addWidget(self.btnAuditResearchData)
        availability_action_row.addWidget(self.btnBackfillResearchRange)
        availability_action_row.addWidget(self.btnCancelBackfill)
        availability_action_row.addWidget(self.btnRetryBackfill)
        availability_action_row.addStretch(1)
        self.dataAvailabilityActionScroll = _horizontal_scroll_area(
            availability_actions
        )
        availability_layout.addWidget(self.dataAvailabilityActionScroll)
        for _index in range(3):
            label = QtWidgets.QLabel()
            label.setProperty("role", "mutedText")
            label.setWordWrap(True)
            self.timeframeCompletenessLabels.append(label)
            availability_layout.addWidget(label)
        self.backfillProgress = QtWidgets.QProgressBar()
        self.backfillProgress.setRange(0, 100)
        self.backfillProgress.setTextVisible(True)
        self.backfillProgress.hide()
        availability_layout.addWidget(self.backfillProgress)
        self.backfillStatusLabel = QtWidgets.QLabel()
        self.backfillStatusLabel.setProperty("role", "pillMuted")
        self.backfillStatusLabel.setWordWrap(True)
        availability_layout.addWidget(self.backfillStatusLabel)
        body.addWidget(self.dataAvailabilityPanel)

        self.episodeAuditPanel = QtWidgets.QFrame()
        self.episodeAuditPanel.setProperty("role", "workspaceToolbar")
        episode_layout = QtWidgets.QVBoxLayout(self.episodeAuditPanel)
        episode_layout.setContentsMargins(
            SPACING["md"],
            SPACING["sm"],
            SPACING["md"],
            SPACING["sm"],
        )
        episode_layout.setSpacing(SPACING["sm"])
        episode_header = QtWidgets.QHBoxLayout()
        self.episodeAuditTitle = QtWidgets.QLabel()
        self.episodeAuditTitle.setProperty("role", "sectionTitle")
        self.btnCorrectEpisodes = QtWidgets.QPushButton()
        self.btnCorrectEpisodes.setProperty("role", "secondaryButton")
        self.btnCorrectEpisodes.setEnabled(False)
        episode_header.addWidget(self.episodeAuditTitle)
        episode_header.addStretch(1)
        episode_header.addWidget(self.btnCorrectEpisodes)
        episode_layout.addLayout(episode_header)
        self.episodeAuditSummary = QtWidgets.QLabel()
        self.episodeAuditSummary.setProperty("role", "mutedText")
        self.episodeCompositionText = QtWidgets.QLabel()
        self.episodeCompositionText.setProperty("role", "mutedText")
        self.episodeCompositionText.setWordWrap(True)
        episode_layout.addWidget(self.episodeAuditSummary)
        episode_layout.addWidget(self.episodeCompositionText)
        body.addWidget(self.episodeAuditPanel)

        self.stepBar = QtWidgets.QWidget()
        step_row = QtWidgets.QHBoxLayout(self.stepBar)
        step_row.setSizeConstraint(QtWidgets.QLayout.SetMinimumSize)
        step_row.setContentsMargins(0, 0, 0, 0)
        step_row.setSpacing(SPACING["sm"])
        self.stepGroup = QtWidgets.QButtonGroup(self)
        self.stepGroup.setExclusive(True)
        for index, step in enumerate(RESEARCH_STEPS):
            button = QtWidgets.QPushButton()
            button.setCheckable(True)
            button.setProperty("role", "workspaceNavButton")
            button.clicked.connect(
                lambda _checked=False, selected_step=step: self.select_step(
                    selected_step
                )
            )
            self.stepGroup.addButton(button, index)
            self.stepButtons[step] = button
            step_row.addWidget(button)
        step_row.addStretch(1)
        self.stepScroll = _horizontal_scroll_area(self.stepBar)
        body.addWidget(self.stepScroll)

        self.stepStack = QtWidgets.QStackedWidget()
        for step in RESEARCH_STEPS:
            if step == "sample_review" and self.entry_review_controller is not None:
                page = EntryBlindReviewWorkspace(
                    controller=self.entry_review_controller,
                    exit_controller=self.exit_review_controller,
                    language=self.language,
                )
                self.entryBlindReviewWorkspace = page
                page.batchLoaded.connect(self._record_blind_batch)
            elif step == "similar_candidates" and self.similarity_service is not None:
                page = EntrySimilarityBrowser(
                    service=self.similarity_service,
                    candidate_service=self.candidate_service,
                    candidate_controller=self.candidate_controller,
                    exit_candidate_service=self.exit_candidate_service,
                    exit_candidate_controller=self.exit_candidate_controller,
                    language=self.language,
                )
                page.formalBatchCreated.connect(
                    self._load_formal_candidate_batch
                )
                page.maturityChanged.connect(
                    self._on_candidate_maturity_changed
                )
                page.candidateResultAccepted.connect(
                    self._record_candidate_result
                )
                self.entrySimilarityBrowser = page
            elif (
                step == "behavior_model"
                and self.behavior_training_service is not None
                and self.behavior_training_controller is not None
            ):
                page = EntryBehaviorModelWorkspace(
                    service=self.behavior_training_service,
                    controller=self.behavior_training_controller,
                    language=self.language,
                )
                self.entryBehaviorModelWorkspace = page
                page.trainingResultAccepted.connect(
                    self._record_behavior_result
                )
            elif (
                step == "outcome_comparison"
                and self.outcome_comparison_service is not None
                and self.outcome_comparison_controller is not None
            ):
                page = EntryOutcomeComparisonWorkspace(
                    service=self.outcome_comparison_service,
                    controller=self.outcome_comparison_controller,
                    exit_service=self.exit_outcome_comparison_service,
                    exit_controller=self.exit_outcome_comparison_controller,
                    language=self.language,
                )
                self.entryOutcomeComparisonWorkspace = page
                page.comparisonResultAccepted.connect(
                    self._record_outcome_result
                )
            elif step == "version_report":
                page = ResearchSnapshotWorkspace(language=self.language)
                page.publishRequested.connect(self.snapshotPublishRequested)
                page.cancelRequested.connect(self.snapshotCancelRequested)
                page.publishedVersionRequested.connect(
                    self.snapshotVersionRequested
                )
                self.researchSnapshotWorkspace = page
            else:
                page = DecisionResearchStepPage()
            self.stepPages[step] = page
            self.stepStack.addWidget(page)
        self.stepStack.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Preferred,
        )
        body.addWidget(self.stepStack)

        self.directionBox.currentIndexChanged.connect(self._update_context_state)
        self.setupBox.currentIndexChanged.connect(self._on_setup_changed)
        self.versionBox.currentIndexChanged.connect(
            self._on_setup_version_changed
        )
        self.decisionTimeframeBox.currentIndexChanged.connect(
            self._update_context_state
        )
        self.contextTimeframeOneBox.currentIndexChanged.connect(
            self._update_context_state
        )
        self.contextTimeframeTwoBox.currentIndexChanged.connect(
            self._update_context_state
        )
        self.btnAuditResearchData.clicked.connect(self.auditRequested)
        self.btnBackfillResearchRange.clicked.connect(
            self.backfillRequested
        )
        self.btnCancelBackfill.clicked.connect(self.cancelRequested)
        self.btnRetryBackfill.clicked.connect(self.retryRequested)
        self.btnCorrectEpisodes.clicked.connect(
            self._request_episode_correction
        )
        self.btnBackfillResearchRange.setEnabled(False)
        self.btnCancelBackfill.setEnabled(False)
        self.btnRetryBackfill.setEnabled(False)
        self.btnCreateSetup.clicked.connect(self._show_create_setup_editor)
        self.btnCreateSetupVersion.clicked.connect(
            self._show_create_setup_version_editor
        )
        self.btnRenameSetup.clicked.connect(self._rename_selected_setup)
        self.btnArchiveSetup.clicked.connect(self._archive_selected_setup)
        self.refresh_setup_catalog()

    def refresh_setup_catalog(
        self,
        *,
        select_setup_id: str | None = None,
        select_version_id: str | None = None,
    ) -> None:
        setup_blocker = QtCore.QSignalBlocker(self.setupBox)
        version_blocker = QtCore.QSignalBlocker(self.versionBox)
        self.setupBox.clear()
        self.versionBox.clear()
        if self.setup_library is None:
            self.setupBox.addItem(
                self._tr("decision_research.context.setup_placeholder"),
                None,
            )
            version_text = (
                self.state.setup_version
                or self._tr(
                    "decision_research.context.setup_version_placeholder"
                )
            )
            self.versionBox.addItem(version_text, self.state.setup_version)
            del setup_blocker
            del version_blocker
            self._set_semantic_controls_frozen(False)
            self._sync_setup_actions()
            return
        setups = self.setup_library.list_setups(include_archived=True)
        for setup in setups:
            label = setup.display_name
            if setup.is_archived:
                label = self._tr(
                    "decision_research.setup.archived_name"
                ).format(name=label)
            self.setupBox.addItem(label, setup.setup_id)
        target_setup_id = select_setup_id or self.state.setup_id
        target_setup_index = self.setupBox.findData(target_setup_id)
        if target_setup_index >= 0:
            self.setupBox.setCurrentIndex(target_setup_index)
        del setup_blocker
        del version_blocker
        if setups:
            self._on_setup_changed(
                self.setupBox.currentIndex(),
                select_version_id=select_version_id,
            )
        else:
            self._selected_setup_archived = False
            self._set_semantic_controls_frozen(False)
            self.setupBox.addItem(
                self._tr("decision_research.context.setup_placeholder"),
                None,
            )
            self.versionBox.addItem(
                self._tr(
                    "decision_research.context.setup_version_placeholder"
                ),
                None,
            )
            self._sync_setup_actions()

    def _on_setup_changed(
        self,
        _index: int = -1,
        *,
        select_version_id: str | None = None,
    ) -> None:
        if self.setup_library is None:
            return
        setup_id = self.setupBox.currentData()
        blocker = QtCore.QSignalBlocker(self.versionBox)
        self.versionBox.clear()
        if not setup_id:
            del blocker
            return
        versions = self.setup_library.list_versions(str(setup_id))
        for version in reversed(versions):
            self.versionBox.addItem(
                self._tr("decision_research.setup.version_label").format(
                    number=version.version_number
                ),
                version.setup_version_id,
            )
        target_version_id = select_version_id or self.state.setup_version
        target_index = self.versionBox.findData(target_version_id)
        if target_index >= 0:
            self.versionBox.setCurrentIndex(target_index)
        del blocker
        self._on_setup_version_changed(self.versionBox.currentIndex())

    def _on_setup_version_changed(self, _index: int = -1) -> None:
        if self.setup_library is None:
            return
        version_id = self.versionBox.currentData()
        if not version_id:
            return
        version = self.setup_library.get_version(str(version_id))
        is_same_version = self.state.setup_version == version.setup_version_id
        setup = self.setup_library.get_setup(version.setup_id)
        self._selected_setup_archived = setup.is_archived
        blockers = (
            QtCore.QSignalBlocker(self.directionBox),
            QtCore.QSignalBlocker(self.decisionTimeframeBox),
            QtCore.QSignalBlocker(self.contextTimeframeOneBox),
            QtCore.QSignalBlocker(self.contextTimeframeTwoBox),
        )
        self.directionBox.setCurrentIndex(
            self.directionBox.findData(version.direction.value)
        )
        for combo, interval in zip(
            (
                self.decisionTimeframeBox,
                self.contextTimeframeOneBox,
                self.contextTimeframeTwoBox,
            ),
            version.timeframes.as_tuple(),
            strict=True,
        ):
            combo.setCurrentText(interval)
        del blockers
        self.state.update_setup_identity(version.setup_id)
        self.state.update_context(
            direction=version.direction.value,
            timeframes=version.timeframes.as_tuple(),
        )
        if not is_same_version:
            self.state.update_readiness(
                setup_version=version.setup_version_id,
                completeness="not_audited",
                maturity="not_ready",
            )
        self.setupValueLabel.setText(version.setup_version_id)
        self._set_semantic_controls_frozen(True)
        self._render_setup_status()
        self._sync_setup_actions()
        self.researchContextChanged.emit()
        self.retranslate_ui()
        self._sync_entry_review_context()
        self._sync_similarity_context()
        self._sync_behavior_context()
        self._sync_outcome_context()

    def _render_setup_status(self) -> None:
        if self._setup_error_code:
            key = (
                "decision_research.setup.error."
                f"{self._setup_error_code}"
            )
            localized = self._tr(key)
            self.setupStatusLabel.setText(
                localized if localized != key else self._setup_error_code
            )
            self.setupStatusLabel.show()
            return
        if self._selected_setup_archived:
            self.setupStatusLabel.setText(
                self._tr("decision_research.setup.status.archived")
            )
            self.setupStatusLabel.show()
            return
        self.setupStatusLabel.clear()
        self.setupStatusLabel.hide()

    def _show_setup_error(
        self,
        error: (
            SetupLookupError
            | SetupPersistenceError
            | SetupValidationError
        ),
    ) -> None:
        self._setup_error_code = error.code.value
        self._render_setup_status()

    def _set_semantic_controls_frozen(self, frozen: bool) -> None:
        for control in (
            self.directionBox,
            self.decisionTimeframeBox,
            self.contextTimeframeOneBox,
            self.contextTimeframeTwoBox,
        ):
            control.setEnabled(not frozen)

    def _sync_setup_actions(self) -> None:
        available = self.setup_library is not None
        selected = available and bool(self.setupBox.currentData())
        self.btnCreateSetup.setEnabled(available)
        self.btnCreateSetupVersion.setEnabled(
            bool(selected and not self._selected_setup_archived)
        )
        self.btnRenameSetup.setEnabled(bool(selected))
        self.btnArchiveSetup.setEnabled(
            bool(selected and not self._selected_setup_archived)
        )

    def _retranslate_setup_selectors(self) -> None:
        if self.setup_library is None:
            if self.setupBox.count():
                self.setupBox.setItemText(
                    0,
                    self._tr(
                        "decision_research.context.setup_placeholder"
                    ),
                )
            if self.versionBox.count() and not self.versionBox.itemData(0):
                self.versionBox.setItemText(
                    0,
                    self._tr(
                        "decision_research.context."
                        "setup_version_placeholder"
                    ),
                )
            return
        for index in range(self.setupBox.count()):
            setup_id = self.setupBox.itemData(index)
            if not setup_id:
                self.setupBox.setItemText(
                    index,
                    self._tr(
                        "decision_research.context.setup_placeholder"
                    ),
                )
                continue
            setup = self.setup_library.get_setup(str(setup_id))
            label = setup.display_name
            if setup.is_archived:
                label = self._tr(
                    "decision_research.setup.archived_name"
                ).format(name=label)
            self.setupBox.setItemText(index, label)
        for index in range(self.versionBox.count()):
            version_id = self.versionBox.itemData(index)
            if not version_id:
                self.versionBox.setItemText(
                    index,
                    self._tr(
                        "decision_research.context."
                        "setup_version_placeholder"
                    ),
                )
                continue
            version = self.setup_library.get_version(str(version_id))
            self.versionBox.setItemText(
                index,
                self._tr("decision_research.setup.version_label").format(
                    number=version.version_number
                ),
            )

    def _show_create_setup_editor(self) -> None:
        if self.setup_library is None:
            return
        self._replace_setup_editor(
            SetupEditorForm(
                setup_library=self.setup_library,
                language=self.language,
                parent=self.setupEditorContainer,
            )
        )

    def _show_create_setup_version_editor(self) -> None:
        if self.setup_library is None:
            return
        setup_id = self.setupBox.currentData()
        version_id = self.versionBox.currentData()
        if not setup_id or not version_id:
            return
        self._replace_setup_editor(
            SetupEditorForm(
                setup_library=self.setup_library,
                language=self.language,
                setup=self.setup_library.get_setup(str(setup_id)),
                based_on_version=self.setup_library.get_version(
                    str(version_id)
                ),
                parent=self.setupEditorContainer,
            )
        )

    def _replace_setup_editor(self, editor: SetupEditorForm) -> None:
        if self.setupEditorForm is not None:
            self.setupEditorLayout.removeWidget(self.setupEditorForm)
            self.setupEditorForm.deleteLater()
        self.setupEditorForm = editor
        self.setupEditorLayout.addWidget(editor)
        editor.saved.connect(self._on_setup_editor_saved)
        editor.cancelled.connect(self._close_setup_editor)
        if self._theme is not None:
            apply_role_button_styles(editor, self._theme)
            apply_themed_input_styles(editor, self._theme)
            apply_role_button_shadows(editor)
        editor.show()
        self.setupEditorContainer.show()

    def _on_setup_editor_saved(self, result: object) -> None:
        if isinstance(result, SetupWithVersion):
            setup_id = result.setup.setup_id
            version_id = result.version.setup_version_id
        elif isinstance(result, SetupVersion):
            setup_id = result.setup_id
            version_id = result.setup_version_id
        else:
            return
        self.refresh_setup_catalog(
            select_setup_id=setup_id,
            select_version_id=version_id,
        )
        self._close_setup_editor()

    def _close_setup_editor(self) -> None:
        editor = self.setupEditorForm
        self.setupEditorForm = None
        self.setupEditorContainer.hide()
        if editor is not None:
            self.setupEditorLayout.removeWidget(editor)
            editor.deleteLater()

    def _rename_selected_setup(self) -> None:
        if self.setup_library is None:
            return
        setup_id = self.setupBox.currentData()
        if not setup_id:
            return
        try:
            current = self.setup_library.get_setup(str(setup_id))
        except (
            SetupLookupError,
            SetupPersistenceError,
            SetupValidationError,
        ) as exc:
            self._show_setup_error(exc)
            return
        name, accepted = QtWidgets.QInputDialog.getText(
            self,
            self._tr("decision_research.setup.rename.title"),
            self._tr("decision_research.setup.field.name"),
            text=current.display_name,
        )
        if not accepted:
            return
        try:
            self.setup_library.rename_setup(str(setup_id), name)
        except (
            SetupLookupError,
            SetupPersistenceError,
            SetupValidationError,
        ) as exc:
            self._show_setup_error(exc)
            return
        self._setup_error_code = None
        self.refresh_setup_catalog(select_setup_id=str(setup_id))

    def _archive_selected_setup(self) -> None:
        if self.setup_library is None:
            return
        setup_id = self.setupBox.currentData()
        if not setup_id:
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            self._tr("decision_research.setup.archive.title"),
            self._tr("decision_research.setup.archive.message"),
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return
        try:
            self.setup_library.archive_setup(str(setup_id))
        except (
            SetupLookupError,
            SetupPersistenceError,
            SetupValidationError,
        ) as exc:
            self._show_setup_error(exc)
            return
        self._setup_error_code = None
        self.refresh_setup_catalog(select_setup_id=str(setup_id))

    def _sync_controls_from_state(self) -> None:
        controls = (
            self.modeTabs,
            self.directionBox,
            self.decisionTimeframeBox,
            self.contextTimeframeOneBox,
            self.contextTimeframeTwoBox,
        )
        blockers = [QtCore.QSignalBlocker(control) for control in controls]
        try:
            self.modeTabs.setCurrentIndex(
                PRIMARY_TABS.index(self.state.primary_tab)
            )
            self.directionBox.setCurrentIndex(
                self.directionBox.findData(self.state.direction)
            )
            for combo, value in zip(
                controls[2:],
                self.state.timeframes,
                strict=True,
            ):
                combo.setCurrentText(value)
        finally:
            for blocker in blockers:
                blocker.unblock()
        self.select_step(self.state.current_step)
        self._render_step_pages()

    def _on_primary_tab_changed(self, index: int) -> None:
        primary_tab = self.modeTabs.tabData(index)
        if primary_tab in PRIMARY_TABS:
            self._remember_page_scroll_position()
            self.state.select_primary_tab(str(primary_tab))
            self._episode_summary = self._episode_summaries[
                self.state.primary_tab
            ]
            self._completeness_report = self._completeness_reports[
                self.state.primary_tab
            ]
            self._data_deficit_text = self._data_deficit_texts[
                self.state.primary_tab
            ]
            self.refresh_setup_catalog(
                select_setup_id=self.state.setup_id,
                select_version_id=self.state.setup_version,
            )
            self._sync_entry_review_mode()
            self._sync_similarity_mode()
            self._sync_behavior_mode()
            self._sync_outcome_mode()
            self.retranslate_ui()
            self._render_step_pages()
            self._schedule_page_scroll_restore()

    def _update_context_state(self, _index: int = -1) -> None:
        direction = self.directionBox.currentData()
        timeframes = (
            self.decisionTimeframeBox.currentText(),
            self.contextTimeframeOneBox.currentText(),
            self.contextTimeframeTwoBox.currentText(),
        )
        if direction:
            self.state.update_context(
                direction=str(direction),
                timeframes=timeframes,
            )
            self._completeness_report = None
            self._data_deficit_text = ""
            self._completeness_reports[self.state.primary_tab] = None
            self._data_deficit_texts[self.state.primary_tab] = ""
            self.state.update_readiness(
                setup_version=self.state.setup_version,
                completeness="not_audited",
                maturity="not_ready",
            )
            self.researchContextChanged.emit()
            self.retranslate_ui()
            self._render_step_pages()
            self._sync_similarity_context()
            self._sync_behavior_context()
            self._sync_outcome_context()

    def select_step(self, step: str) -> None:
        self._remember_page_scroll_position()
        self.state.select_step(step)
        index = RESEARCH_STEPS.index(step)
        self.stepStack.setCurrentIndex(index)
        self.stepButtons[step].setChecked(True)
        self._schedule_page_scroll_restore()
        if step == "version_report":
            self.snapshotDraftRequested.emit()

    def _page_scroll_key(self) -> tuple[str, str]:
        return self.state.primary_tab, self.state.current_step

    def _remember_page_scroll_position(self) -> None:
        if not hasattr(self, "pageScroll"):
            return
        self._page_scroll_positions[self._page_scroll_key()] = (
            self.pageScroll.verticalScrollBar().value()
        )

    def _schedule_page_scroll_restore(self) -> None:
        if not hasattr(self, "pageScroll"):
            return
        key = self._page_scroll_key()
        QtCore.QTimer.singleShot(
            0,
            self,
            lambda selected=key: self._restore_page_scroll_position(selected),
        )

    def _restore_page_scroll_position(
        self,
        key: tuple[str, str],
    ) -> None:
        if key != self._page_scroll_key():
            return
        self.pageScroll.verticalScrollBar().setValue(
            self._page_scroll_positions.get(key, 0)
        )

    def retranslate_ui(self, language: str | None = None) -> None:
        if language is not None:
            self.language = language
        for index, primary_tab in enumerate(PRIMARY_TABS):
            self.modeTabs.setTabText(
                index,
                self._tr(f"decision_research.tab.{primary_tab}"),
            )
        for index, direction in enumerate(DIRECTIONS):
            self.directionBox.setItemText(
                index,
                self._tr(f"decision_research.direction.{direction.lower()}"),
            )
        for field, label in self.contextFieldLabels.items():
            label.setText(
                self._tr(f"decision_research.context.field.{field}")
            )
        self._retranslate_setup_selectors()
        self.setupValueLabel.setText(
            self.state.setup_version
            or self._tr("decision_research.context.setup_placeholder")
        )
        self.completenessLabel.setText(
            self._tr(
                f"decision_research.completeness.{self.state.completeness}"
            )
        )
        self.maturityLabel.setText(
            self._tr(f"decision_research.maturity.{self.state.maturity}")
        )
        self._render_setup_status()
        self.dataAvailabilityTitle.setText(
            self._tr("decision_research.data.title")
        )
        self.btnAuditResearchData.setText(
            self._tr("decision_research.data.audit")
        )
        self.btnBackfillResearchRange.setText(
            self._tr("decision_research.data.backfill")
        )
        self.btnCancelBackfill.setText(
            self._tr("decision_research.data.cancel")
        )
        self.btnRetryBackfill.setText(
            self._tr("decision_research.data.retry")
        )
        self.btnCreateSetup.setText(
            self._tr("decision_research.setup.action.create")
        )
        self.btnCreateSetupVersion.setText(
            self._tr(
                "decision_research.setup.action.create_version"
            )
        )
        self.btnRenameSetup.setText(
            self._tr("decision_research.setup.action.rename")
        )
        self.btnArchiveSetup.setText(
            self._tr("decision_research.setup.action.archive")
        )
        self.episodeAuditTitle.setText(
            self._tr("decision_research.episode.title")
        )
        self.btnCorrectEpisodes.setText(
            self._tr("decision_research.episode.correct")
        )
        self._render_episode_audit_text()
        if self._completeness_report is None:
            for index, label in enumerate(
                self.timeframeCompletenessLabels
            ):
                label.setText(
                    self._tr("decision_research.data.not_audited").format(
                        interval=self.state.timeframes[index]
                    )
                )
            if not self.backfillStatusLabel.text():
                self.backfillStatusLabel.setText(
                    self._tr("decision_research.data.audit_hint")
                )
        else:
            self._render_completeness_labels()
        for index, step in enumerate(RESEARCH_STEPS):
            text = self._tr(f"decision_research.step.{step}")
            self.stepButtons[step].setText(text)
        if self.entryBlindReviewWorkspace is not None:
            self.entryBlindReviewWorkspace.retranslate_ui(self.language)
        if self.entrySimilarityBrowser is not None:
            self.entrySimilarityBrowser.retranslate_ui(self.language)
        if self.entryBehaviorModelWorkspace is not None:
            self.entryBehaviorModelWorkspace.retranslate_ui(self.language)
        if self.entryOutcomeComparisonWorkspace is not None:
            self.entryOutcomeComparisonWorkspace.retranslate_ui(self.language)
        if self.researchSnapshotWorkspace is not None:
            self.researchSnapshotWorkspace.retranslate_ui(self.language)
        self._render_step_pages()
        self._sync_research_operation_gates()

    def apply_theme(self, theme: dict) -> None:
        """Apply the repository theme contract when used outside MainWindow."""
        self._theme = theme
        apply_role_button_styles(self, theme)
        apply_themed_input_styles(self, theme)
        apply_role_button_shadows(self)
        if self.entryBlindReviewWorkspace is not None:
            self.entryBlindReviewWorkspace.apply_theme(theme)
        if self.entrySimilarityBrowser is not None:
            self.entrySimilarityBrowser.apply_theme(theme)
        if self.entryBehaviorModelWorkspace is not None:
            self.entryBehaviorModelWorkspace.apply_theme(theme)
        if self.entryOutcomeComparisonWorkspace is not None:
            self.entryOutcomeComparisonWorkspace.apply_theme(theme)
        if self.researchSnapshotWorkspace is not None:
            self.researchSnapshotWorkspace.apply_theme(theme)

    def render_episode_audit(self, summary: EpisodeAuditSummary) -> None:
        """Render a domain audit summary without exposing grouping logic to Qt."""

        previous_grouping_id = (
            self._episode_summary.grouping_version_id
            if self._episode_summary is not None
            else None
        )
        self._episode_summary = summary
        self._episode_summaries[self.state.primary_tab] = summary
        self.state.update_research_versions(
            grouping_version_id=summary.grouping_version_id
        )
        if previous_grouping_id != summary.grouping_version_id:
            self.state.update_readiness(
                setup_version=self.state.setup_version,
                completeness=self.state.completeness,
                maturity="not_ready",
            )
        self.btnCorrectEpisodes.setEnabled(bool(summary.can_correct))
        self.retranslate_ui()
        self._sync_entry_review_context()
        self._sync_similarity_context()
        self._sync_behavior_context()
        self._sync_outcome_context()

    def clear_episode_audit(self) -> None:
        self._episode_summary = None
        self._episode_summaries[self.state.primary_tab] = None
        self.state.update_research_versions(grouping_version_id=None)
        self._render_episode_audit_text()
        self._sync_entry_review_context()
        self._sync_similarity_context()
        self._sync_behavior_context()
        self._sync_outcome_context()

    def _render_episode_audit_text(self) -> None:
        summary = self._episode_summary
        if summary is None:
            self.episodeAuditSummary.setText(
                self._tr("decision_research.episode.empty")
            )
            self.episodeCompositionText.clear()
            return
        source = self._tr(
            "decision_research.episode.source."
            f"{summary.grouping_source.value.lower()}"
        )
        self.episodeAuditSummary.setText(
            self._tr("decision_research.episode.summary").format(
                episode_count=summary.episode_count,
                sample_count=summary.sample_count,
                source=source,
            )
        )
        lines = []
        for item in summary.composition:
            item_source = self._tr(
                "decision_research.episode.source."
                f"{item.source.value.lower()}"
            )
            lines.append(
                self._tr("decision_research.episode.composition").format(
                    episode_id=item.episode_id,
                    sample_count=len(item.sample_ids),
                    symbols=", ".join(item.symbols),
                    timeframes=", ".join(item.timeframes),
                    source=item_source,
                )
            )
        self.episodeCompositionText.setText("\n".join(lines))

    def _request_episode_correction(self) -> None:
        if self._episode_summary is not None:
            self.episodeCorrectionRequested.emit(
                self._episode_summary.grouping_version_id
            )

    def update_readiness(
        self,
        *,
        setup_version: str | None,
        completeness: str,
        maturity: str,
    ) -> None:
        self.state.update_readiness(
            setup_version=setup_version,
            completeness=completeness,
            maturity=maturity,
        )
        self.retranslate_ui()
        self._sync_entry_review_context()
        self._sync_similarity_context()
        self._sync_behavior_context()
        self._sync_outcome_context()

    def begin_audit(self) -> None:
        self.btnAuditResearchData.setEnabled(False)
        self.btnBackfillResearchRange.setEnabled(False)
        self.btnCancelBackfill.setEnabled(True)
        self.btnRetryBackfill.setEnabled(False)
        self.backfillStatusLabel.setText(
            self._tr("decision_research.data.audit_running")
        )

    def render_audit_rejection(self, message: str) -> None:
        self.btnAuditResearchData.setEnabled(True)
        self.btnBackfillResearchRange.setEnabled(
            self._completeness_report is not None
            and not self._completeness_report.is_complete
        )
        self.btnCancelBackfill.setEnabled(False)
        self.btnRetryBackfill.setEnabled(False)
        self.backfillProgress.hide()
        self.backfillStatusLabel.setText(message)

    @QtCore.Slot(object)
    def render_audit_cancelled(self, _event=None) -> None:
        self.render_audit_rejection(
            self._tr("decision_research.data.audit_cancelled")
        )

    def invalidate_completeness(self) -> None:
        self._completeness_report = None
        self._data_deficit_text = ""
        self._completeness_reports[self.state.primary_tab] = None
        self._data_deficit_texts[self.state.primary_tab] = ""
        self.state.update_readiness(
            setup_version=self.state.setup_version,
            completeness="not_audited",
            maturity="not_ready",
        )
        self.btnAuditResearchData.setEnabled(True)
        self.btnBackfillResearchRange.setEnabled(False)
        self.btnCancelBackfill.setEnabled(False)
        self.btnRetryBackfill.setEnabled(False)
        self.backfillProgress.hide()
        self.backfillStatusLabel.setText(
            self._tr("decision_research.data.audit_context_changed")
        )
        self.retranslate_ui()

    def begin_backfill(self) -> None:
        self.btnAuditResearchData.setEnabled(False)
        self.btnBackfillResearchRange.setEnabled(False)
        self.btnCancelBackfill.setEnabled(True)
        self.btnRetryBackfill.setEnabled(False)
        self.backfillProgress.setValue(0)
        self.backfillProgress.show()
        self.backfillStatusLabel.setText(
            self._tr("decision_research.data.backfill_starting")
        )

    def render_completeness(self, report) -> None:
        self._completeness_report = report
        self._completeness_reports[self.state.primary_tab] = report
        completeness = "complete" if report.is_complete else "incomplete"
        self.state.update_readiness(
            setup_version=self.state.setup_version,
            completeness=completeness,
            maturity=self.state.maturity,
        )
        self.btnAuditResearchData.setEnabled(True)
        self.btnBackfillResearchRange.setEnabled(not report.is_complete)
        self.btnCancelBackfill.setEnabled(False)
        self.btnRetryBackfill.setEnabled(False)
        self.backfillProgress.hide()
        self._render_completeness_labels()
        self.retranslate_ui()

    def render_audit_result(self, report) -> None:
        self.render_completeness(report)
        message_key = (
            "decision_research.data.audit_complete"
            if report.is_complete
            else "decision_research.data.audit_incomplete"
        )
        self.backfillStatusLabel.setText(self._tr(message_key))

    def _render_completeness_labels(self) -> None:
        report = self._completeness_report
        if report is None:
            return
        deficit_lines: list[str] = []
        for label, timeframe in zip(
            self.timeframeCompletenessLabels,
            report.timeframes,
            strict=True,
        ):
            complete_bars = round(
                timeframe.expected_bars * timeframe.coverage_ratio
            )
            coverage = f"{timeframe.coverage_ratio * 100:.1f}%"
            if timeframe.is_complete:
                text = self._tr(
                    "decision_research.data.timeframe_complete"
                ).format(
                    interval=timeframe.interval,
                    complete=complete_bars,
                    expected=timeframe.expected_bars,
                    coverage=coverage,
                )
            else:
                fields = self._tr("decision_research.data.none")
                missing_parts = [
                    self._tr(
                        f"decision_research.data.field.{field}"
                    ).format(count=count)
                    for field, count in timeframe.missing_field_counts.items()
                    if count
                ]
                if missing_parts:
                    fields = self._tr(
                        "decision_research.list_separator"
                    ).join(missing_parts)
                text = self._tr(
                    "decision_research.data.timeframe_incomplete"
                ).format(
                    interval=timeframe.interval,
                    complete=complete_bars,
                    expected=timeframe.expected_bars,
                    coverage=coverage,
                    missing_bars=timeframe.missing_bar_count,
                    fields=fields,
                    ranges=len(timeframe.missing_ranges),
                )
                deficit_lines.append(text)
            label.setText(text)
        self._data_deficit_text = self._tr(
            "decision_research.data.gate_deficit"
        ).format(
            details=self._tr("decision_research.list_separator").join(
                deficit_lines
            )
        ) if deficit_lines else ""
        self._data_deficit_texts[
            self.state.primary_tab
        ] = self._data_deficit_text
        self.completenessLabel.setText(
            self._tr(
                f"decision_research.completeness.{self.state.completeness}"
            )
        )
        self._render_step_pages()

    def render_backfill_progress(self, progress) -> None:
        total = max(1, int(progress.total_chunks))
        completed = max(0, min(total, int(progress.completed_chunks)))
        self.backfillProgress.setValue(round(completed / total * 100))
        self.backfillProgress.show()
        self.backfillStatusLabel.setText(
            self._tr("decision_research.data.backfill_progress").format(
                completed=completed,
                total=total,
                bars=int(progress.downloaded_bars),
                interval=progress.interval,
            )
        )

    def render_backfill_failure(self, error: str) -> None:
        self.btnAuditResearchData.setEnabled(True)
        self.btnBackfillResearchRange.setEnabled(False)
        self.btnCancelBackfill.setEnabled(False)
        self.btnRetryBackfill.setEnabled(True)
        self.backfillStatusLabel.setText(
            self._tr("decision_research.data.backfill_failed").format(
                error=sanitize_worker_error_detail(error)
            )
        )

    def render_backfill_cancelled(self) -> None:
        self.btnAuditResearchData.setEnabled(True)
        self.btnBackfillResearchRange.setEnabled(False)
        self.btnCancelBackfill.setEnabled(False)
        self.btnRetryBackfill.setEnabled(True)
        self.backfillStatusLabel.setText(
            self._tr("decision_research.data.backfill_cancelled")
        )

    def render_backfill_finished(self, result) -> None:
        self.render_completeness(result.completeness)
        if result.completeness.is_complete:
            self.backfillStatusLabel.setText(
                self._tr("decision_research.data.backfill_complete")
            )
            return
        self.btnRetryBackfill.setEnabled(True)
        self.backfillStatusLabel.setText(
            self._tr("decision_research.data.backfill_partial")
        )

    def _render_step_pages(self) -> None:
        if not self.stepPages:
            return
        for step, page in self.stepPages.items():
            if not isinstance(page, DecisionResearchStepPage):
                continue
            page.render(
                step=step,
                state=self.state,
                translator=self._tr,
                data_deficit_text=self._data_deficit_text,
            )

    def _sync_research_operation_gates(self) -> None:
        if self.entrySimilarityBrowser is not None:
            allowed, message = self._research_operation_gate(
                "similar_candidates"
            )
            self.entrySimilarityBrowser.set_candidate_operation_gate(
                allowed=allowed,
                message=message,
            )
        if self.entryBehaviorModelWorkspace is not None:
            allowed, message = self._research_operation_gate(
                "behavior_model"
            )
            self.entryBehaviorModelWorkspace.set_training_operation_gate(
                allowed=allowed,
                message=message,
            )
        if self.entryOutcomeComparisonWorkspace is not None:
            allowed, message = self._research_operation_gate(
                "outcome_comparison"
            )
            self.entryOutcomeComparisonWorkspace.set_operation_gate(
                allowed=allowed,
                message=message,
            )

    def _research_operation_gate(self, step: str) -> tuple[bool, str]:
        message = _missing_conditions_message(
            step=step,
            state=self.state,
            translator=self._tr,
            data_deficit_text=self._data_deficit_text,
        )
        return not bool(message), message

    def _sync_entry_review_context(self) -> None:
        if self.entryBlindReviewWorkspace is None:
            return
        self._sync_entry_review_mode()
        grouping_version_id = (
            self._episode_summary.grouping_version_id
            if self._episode_summary is not None
            else None
        )
        self.entryBlindReviewWorkspace.set_research_context(
            setup_version_id=self.state.setup_version,
            grouping_version_id=grouping_version_id,
            setup_version_label=(
                f"{self.setupBox.currentText()} · {self.versionBox.currentText()}"
                if self.state.setup_version and self.setup_library is not None
                else None
            ),
        )

    def _sync_entry_review_mode(self) -> None:
        if self.entryBlindReviewWorkspace is None:
            return
        self.entryBlindReviewWorkspace.set_entry_mode_active(
            self.state.primary_tab == "entry"
        )

    def _sync_similarity_context(self) -> None:
        if self.entrySimilarityBrowser is None:
            return
        self._sync_similarity_mode()
        self.entrySimilarityBrowser.set_research_context(
            setup_version_id=self.state.setup_version,
            direction=self.state.direction,
            grouping_version_id=(
                self._episode_summary.grouping_version_id
                if self._episode_summary is not None else None
            ),
        )

    def _sync_behavior_context(self) -> None:
        if self.entryBehaviorModelWorkspace is None:
            return
        self._sync_behavior_mode()
        self.entryBehaviorModelWorkspace.set_research_context(
            setup_version_id=self.state.setup_version,
            direction=self.state.direction,
            grouping_version_id=(
                self._episode_summary.grouping_version_id
                if self._episode_summary is not None else None
            ),
        )

    def _sync_outcome_context(self) -> None:
        if self.entryOutcomeComparisonWorkspace is None:
            return
        self._sync_outcome_mode()
        self.entryOutcomeComparisonWorkspace.set_research_context(
            setup_version_id=self.state.setup_version,
            direction=self.state.direction,
            grouping_version_id=(
                self._episode_summary.grouping_version_id
                if self._episode_summary is not None else None
            ),
        )

    @QtCore.Slot(object)
    def _load_formal_candidate_batch(self, batch) -> None:
        if self.entryBlindReviewWorkspace is None:
            return
        self.entryBlindReviewWorkspace.load_existing_batch(batch)

    @QtCore.Slot(object)
    def _record_blind_batch(self, batch) -> None:
        self.state.update_research_versions(
            blind_batch_id=str(batch.batch_id),
        )

    @QtCore.Slot(object)
    def _record_candidate_result(self, result) -> None:
        self.state.update_research_versions(
            candidate_run_id=str(result.scan_id),
        )

    @QtCore.Slot(object)
    def _record_behavior_result(self, result) -> None:
        model = getattr(result, "model", None)
        if model is not None:
            self.state.update_research_versions(
                behavior_snapshot_id=str(model.model_version_id),
            )
            self.state.set_operation_state(loading=False, error=None)
            return
        failure = getattr(result, "failure", None)
        message = getattr(failure, "message_zh", None)
        self.state.set_operation_state(
            loading=False,
            error=str(message or "behavior_training_failed"),
        )

    @QtCore.Slot(object)
    def _record_outcome_result(self, result) -> None:
        self.state.update_research_versions(
            outcome_comparison_id=str(result.comparison_id),
        )

    def _sync_similarity_mode(self) -> None:
        if self.entrySimilarityBrowser is None:
            return
        self.entrySimilarityBrowser.set_entry_mode_active(
            self.state.primary_tab == "entry"
        )

    def _sync_behavior_mode(self) -> None:
        if self.entryBehaviorModelWorkspace is None:
            return
        self.entryBehaviorModelWorkspace.set_entry_mode_active(
            self.state.primary_tab == "entry"
        )

    def _sync_outcome_mode(self) -> None:
        if self.entryOutcomeComparisonWorkspace is None:
            return
        self.entryOutcomeComparisonWorkspace.set_entry_mode_active(
            self.state.primary_tab == "entry"
        )

    @QtCore.Slot(bool)
    def _on_candidate_maturity_changed(self, ready: bool) -> None:
        self.state.update_readiness(
            setup_version=self.state.setup_version,
            completeness=self.state.completeness,
            maturity="mature" if ready else "not_ready",
        )
        self.retranslate_ui()

    def closeEvent(self, event) -> None:
        if self.entryBlindReviewWorkspace is not None:
            self.entryBlindReviewWorkspace.shutdown()
        super().closeEvent(event)


__all__ = ["DecisionResearchWorkspace"]
