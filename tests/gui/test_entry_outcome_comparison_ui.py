from __future__ import annotations

import pytest


QtCore = pytest.importorskip("PySide6.QtCore")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from research.entry_outcome_comparison import (
    ENTRY_MATCH_SENSITIVITY_THRESHOLDS,
    ENTRY_OUTCOME_FORMULA_VERSION,
    EntryOutcomeComparisonRequest,
    EntryOutcomeComparisonResult,
    EntryOutcomeThresholdResult,
    build_entry_outcome_matrix,
)
from research.exit_outcome_comparison import ExitOutcomeComparisonRequest
from ui_style import DARK_THEME, LIGHT_THEME
from decision_research_state import DecisionResearchPageState
from views.decision_research_workspace import DecisionResearchWorkspace
from views.entry_outcome_comparison_workspace import (
    EntryOutcomeComparisonWorkspace,
)


class _OutcomeController(QtCore.QObject):
    resultReady = QtCore.Signal(object)
    progress = QtCore.Signal(object)
    failed = QtCore.Signal(str)
    cancelled = QtCore.Signal()

    def __init__(self) -> None:
        super().__init__()
        self.is_running = False
        self.start_calls = []
        self.invalidations = 0

    def start(self, request):
        self.start_calls.append(request)
        self.is_running = True
        return len(self.start_calls)

    def cancel(self):
        self.is_running = False

    def invalidate(self):
        self.invalidations += 1
        self.is_running = False


class _OutcomeService:
    pass


def _result() -> EntryOutcomeComparisonResult:
    sensitivities = tuple(
        EntryOutcomeThresholdResult(
            similarity_threshold=threshold,
            pairs=(),
            matrix=build_entry_outcome_matrix((), {}, random_seed=42),
        )
        for threshold in ENTRY_MATCH_SENSITIVITY_THRESHOLDS
    )
    return EntryOutcomeComparisonResult(
        comparison_id="comparison_1",
        setup_version_id="setup_version_1",
        grouping_version_id="grouping_version_1",
        direction="LONG",
        formula_version=ENTRY_OUTCOME_FORMULA_VERSION,
        feature_version="entry-structural-features-v1",
        random_seed=42,
        eligible_decisions=(),
        input_feature_fingerprint="0" * 64,
        sensitivities=sensitivities,
        created_at="2026-07-20T00:00:00+00:00",
    )


def test_complete_matrix_runs_only_after_gate_and_keeps_all_nonsignificant_cells():
    controller = _OutcomeController()
    page = EntryOutcomeComparisonWorkspace(
        service=_OutcomeService(),
        controller=controller,
        language="zh_CN",
    )
    page.set_research_context(
        setup_version_id="setup_version_1",
        grouping_version_id="grouping_version_1",
        direction="LONG",
    )

    assert page.runButton.isEnabled() is False
    page.set_operation_gate(allowed=True, message="")
    page.runButton.click()
    assert controller.start_calls == [
        EntryOutcomeComparisonRequest(
            "setup_version_1",
            "grouping_version_1",
            "LONG",
        )
    ]

    controller.is_running = False
    controller.resultReady.emit(_result())
    QtWidgets.QApplication.instance().processEvents()

    assert page.matrixTable.rowCount() == 5
    assert page.matrixTable.columnCount() == 3
    assert all(
        page.matrixTable.item(row, column) is not None
        for row in range(5)
        for column in range(3)
    )
    assert "正式证据不足" in page.matrixTable.item(0, 0).text()
    assert "门槛 70" in page.detailText.toPlainText()
    assert "门槛 75" in page.detailText.toPlainText()
    assert "门槛 80" in page.detailText.toPlainText()
    assert "不代表策略有效" in page.warningLabel.text()


def test_outcome_page_is_one_shared_entry_step_and_stays_usable_when_narrow():
    controller = _OutcomeController()
    workspace = DecisionResearchWorkspace(
        language="zh_CN",
        outcome_comparison_service=_OutcomeService(),
        outcome_comparison_controller=controller,
    )
    page = workspace.stepPages["outcome_comparison"]

    assert isinstance(page, EntryOutcomeComparisonWorkspace)
    workspace.resize(320, 640)
    workspace.show()
    QtWidgets.QApplication.instance().processEvents()
    assert page.scrollArea.widgetResizable()

    page.apply_theme(DARK_THEME)
    assert page.runButton.styleSheet()
    page.apply_theme(LIGHT_THEME)
    assert page.runButton.styleSheet()

    workspace.modeTabs.setCurrentIndex(1)
    QtWidgets.QApplication.instance().processEvents()
    assert page.runButton.isEnabled() is False


def test_shared_outcome_page_switches_to_exit_service_without_duplicate_layout():
    entry_controller = _OutcomeController()
    exit_controller = _OutcomeController()
    page = EntryOutcomeComparisonWorkspace(
        service=_OutcomeService(),
        controller=entry_controller,
        exit_service=_OutcomeService(),
        exit_controller=exit_controller,
        language="zh_CN",
    )
    page.set_research_context(
        setup_version_id="setup_version_1",
        grouping_version_id="grouping_version_1",
        direction="LONG",
    )
    page.set_operation_gate(allowed=True, message="")

    page.set_entry_mode_active(False)
    page.runButton.click()

    assert entry_controller.start_calls == []
    assert exit_controller.start_calls == [
        ExitOutcomeComparisonRequest(
            "setup_version_1",
            "grouping_version_1",
            "LONG",
        )
    ]
    assert "立即平仓/继续持有" in page.titleLabel.text()


def test_outcome_comparison_uses_its_own_pair_and_episode_evidence_gate():
    state = DecisionResearchPageState(
        setup_version="setup_version_1",
        completeness="complete",
        maturity="not_ready",
    )

    assert state.missing_conditions("outcome_comparison") == ()
