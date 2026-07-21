from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from project_paths import APP_DIR

QtCore = pytest.importorskip("PySide6.QtCore")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


def test_decision_research_pages_do_not_use_private_numeric_size_literals():
    view_dir = APP_DIR / "views"
    paths = tuple(
        view_dir / name
        for name in (
            "decision_research_workspace.py",
            "entry_behavior_model_workspace.py",
            "entry_blind_review_workspace.py",
            "entry_outcome_comparison_workspace.py",
            "entry_similarity_browser.py",
            "research_snapshot_workspace.py",
            "setup_editor.py",
        )
    )
    forbidden = {
        "setFixedHeight",
        "setFixedSize",
        "setFixedWidth",
        "setMaximumHeight",
        "setMaximumWidth",
        "setMinimumHeight",
        "setMinimumSize",
        "setMinimumWidth",
    }
    hits = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in forbidden:
                continue
            if any(
                isinstance(argument, ast.Constant)
                and isinstance(argument.value, (int, float))
                for argument in node.args
            ):
                hits.append((path.name, node.lineno, node.func.attr))
    assert hits == []

from analysis_workspace import AnalysisWorkspace
from app_i18n import tr as i18n_tr
from decision_research_state import DecisionResearchPageState
from services.research_data_availability import (
    MissingKlineRange,
    ResearchCompletenessReport,
    TimeframeCompleteness,
)
from services.research_data_backfill import ResearchBackfillProgress
from research.market_episodes import EpisodeAuditSummary, EpisodeSource
from research.entry_candidate_generation import (
    CandidateMaturity,
    CandidateScanOverview,
    CandidateScanStatus,
    CandidateSimilarityDistribution,
)
from ui_style import (
    DARK_THEME,
    LIGHT_THEME,
    WORKSPACE_SIZES,
    normalize_theme_settings,
)
from views.decision_research_workspace import DecisionResearchWorkspace
from research.setups import (
    CreateSetup,
    DecisionProtocol,
    SetupDirection,
    SetupLibrary,
    SetupVersionSpec,
    TimeframeProfile,
)
from storage import StorageManager


class Host(QtWidgets.QWidget):
    current_language = "zh_CN"
    session_id = "session_decision_research"


class _EmptyBrowseService:
    def list_browsable_samples(self, **_kwargs):
        return ()


class _CandidateController(QtCore.QObject):
    resultReady = QtCore.Signal(object)
    progress = QtCore.Signal(object)
    failed = QtCore.Signal(str)
    cancelled = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.is_running = False

    def invalidate(self):
        self.is_running = False

    def cancel(self):
        self.is_running = False


class _BehaviorController(QtCore.QObject):
    resultReady = QtCore.Signal(object)
    progress = QtCore.Signal(object)
    failed = QtCore.Signal(str)
    cancelled = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.is_running = False

    def invalidate(self):
        self.is_running = False

    def cancel(self):
        self.is_running = False


class _BehaviorService:
    def list_models(self, **_kwargs):
        return ()


def _incomplete_report() -> ResearchCompletenessReport:
    incomplete = TimeframeCompleteness(
        interval="1m",
        required_start_time_utc_ms=1_000,
        required_end_time_utc_ms=121_000,
        expected_bars=3,
        present_bars=2,
        missing_bar_count=1,
        missing_field_counts={
            "quote_volume": 2,
            "trade_count": 1,
            "taker_buy_base_volume": 1,
            "taker_buy_quote_volume": 1,
        },
        missing_ranges=(
            MissingKlineRange(
                start_time_utc_ms=61_000,
                end_time_utc_ms=121_000,
                missing_fields=(
                    "quote_volume",
                    "trade_count",
                    "taker_buy_base_volume",
                    "taker_buy_quote_volume",
                ),
            ),
        ),
        coverage_ratio=1 / 3,
    )
    complete = lambda interval: TimeframeCompleteness(
        interval=interval,
        required_start_time_utc_ms=1_000,
        required_end_time_utc_ms=1_000,
        expected_bars=1,
        present_bars=1,
        missing_bar_count=0,
        missing_field_counts={
            "quote_volume": 0,
            "trade_count": 0,
            "taker_buy_base_volume": 0,
            "taker_buy_quote_volume": 0,
        },
        missing_ranges=(),
        coverage_ratio=1.0,
    )
    return ResearchCompletenessReport(
        formula_version="decision-research-v1.6",
        symbol="BTCUSDT",
        research_start_time_utc_ms=1_000,
        research_end_time_utc_ms=121_000,
        timeframes=(incomplete, complete("5m"), complete("15m")),
    )


def _complete_report() -> ResearchCompletenessReport:
    timeframes = tuple(
        TimeframeCompleteness(
            interval=interval,
            required_start_time_utc_ms=1_000,
            required_end_time_utc_ms=1_000,
            expected_bars=1,
            present_bars=1,
            missing_bar_count=0,
            missing_field_counts={
                "quote_volume": 0,
                "trade_count": 0,
                "taker_buy_base_volume": 0,
                "taker_buy_quote_volume": 0,
            },
            missing_ranges=(),
            coverage_ratio=1.0,
        )
        for interval in ("1m", "5m", "15m")
    )
    return ResearchCompletenessReport(
        formula_version="decision-research-v1.6",
        symbol="BTCUSDT",
        research_start_time_utc_ms=1_000,
        research_end_time_utc_ms=121_000,
        timeframes=timeframes,
    )


def test_data_analysis_decision_research_keeps_context_across_tabs_and_steps():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = Host()
    workspace = AnalysisWorkspace(host)

    try:
        workspace.open_decision_research()
        decision = workspace.decisionResearchWorkspace

        decision.directionBox.setCurrentIndex(
            decision.directionBox.findData("SHORT")
        )
        decision.decisionTimeframeBox.setCurrentText("5m")
        decision.contextTimeframeOneBox.setCurrentText("15m")
        decision.contextTimeframeTwoBox.setCurrentText("1h")
        decision.modeTabs.setCurrentIndex(1)
        for step_name in (
            "sample_review",
            "similar_candidates",
            "behavior_model",
            "outcome_comparison",
            "version_report",
        ):
            decision.stepButtons[step_name].click()

        assert workspace.tabs.currentWidget() is workspace.decisionResearchTab
        tab_texts = [
            workspace.tabs.tabText(index)
            for index in range(workspace.tabs.count())
        ]
        assert tab_texts.count("决策研究") == 1
        assert "事件研究" not in tab_texts
        assert "研究分析" not in tab_texts
        assert decision.state.primary_tab == "exit"
        assert decision.state.current_step == "version_report"
        assert decision.state.direction == "LONG"
        assert decision.state.timeframes == ("1m", "5m", "15m")

        decision.modeTabs.setCurrentIndex(0)

        assert decision.state.direction == "SHORT"
        assert decision.state.timeframes == ("5m", "15m", "1h")
    finally:
        workspace.close()
        host.close()
        app.processEvents()


def test_unprepared_research_keeps_every_step_open_and_gates_only_the_action():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    workspace = AnalysisWorkspace(Host())

    try:
        decision = workspace.decisionResearchWorkspace

        for step_name, button in decision.stepButtons.items():
            assert button.isEnabled()
            button.click()
            page = decision.stepPages[step_name]
            assert page.isEnabled()
            assert page.emptyState.isVisibleTo(page)
            assert page.gateHint.text()
            assert page.actionButton.isEnabled() is False
    finally:
        workspace.close()
        app.processEvents()


def test_context_bar_renders_page_state_and_retranslates_every_field():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    state = DecisionResearchPageState(
        primary_tab="exit",
        setup_version="setup-v3",
        direction="SHORT",
        timeframes=("5m", "15m", "1h"),
        completeness="complete",
        maturity="mature",
    )
    decision = DecisionResearchWorkspace(language="zh_CN", state=state)

    try:
        assert decision.contextFieldLabels["setup"].text() == "策略模板"
        assert decision.contextFieldLabels["direction"].text() == "方向"
        assert decision.contextFieldLabels["decision_timeframe"].text() == "决策周期"
        assert decision.contextFieldLabels["context_timeframe_one"].text() == "上下文周期一"
        assert decision.contextFieldLabels["context_timeframe_two"].text() == "上下文周期二"
        assert decision.contextFieldLabels["completeness"].text() == "完整度"
        assert decision.contextFieldLabels["maturity"].text() == "成熟度"
        assert decision.modeTabs.currentIndex() == 1
        assert decision.state.primary_tab == "exit"
        assert decision.state.timeframes == ("5m", "15m", "1h")
        assert decision.decisionTimeframeBox.currentText() == "5m"
        assert decision.contextTimeframeOneBox.currentText() == "15m"
        assert decision.contextTimeframeTwoBox.currentText() == "1h"
        assert decision.setupValueLabel.text() == "setup-v3"
        assert decision.completenessLabel.text() == "完整"
        assert decision.maturityLabel.text() == "成熟"

        decision.retranslate_ui("en_US")

        assert decision.contextFieldLabels["setup"].text() == "Setup version"
        assert decision.contextFieldLabels["direction"].text() == "Direction"
        assert decision.completenessLabel.text() == "Complete"
        assert decision.maturityLabel.text() == "Mature"
    finally:
        decision.close()
        app.processEvents()


def test_narrow_workspace_keeps_context_and_all_steps_reachable():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    decision = DecisionResearchWorkspace(language="zh_CN")
    decision.resize(320, 640)
    decision.show()
    app.processEvents()

    try:
        assert decision.contextScroll.horizontalScrollBar().maximum() > 0
        assert decision.stepScroll.horizontalScrollBar().maximum() > 0

        decision.stepScroll.horizontalScrollBar().setValue(
            decision.stepScroll.horizontalScrollBar().maximum()
        )
        decision.stepButtons["version_report"].click()

        assert decision.state.current_step == "version_report"
        assert (
            decision.stepStack.currentWidget()
            is decision.stepPages["version_report"]
        )
    finally:
        decision.close()
        app.processEvents()


@pytest.mark.parametrize("size", ((320, 640), (1024, 768), (1366, 768), (1920, 1080)))
def test_setup_editor_uses_single_page_scroll_and_keeps_actions_first(
    tmp_path,
    size,
):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    decision = DecisionResearchWorkspace(
        language="zh_CN",
        setup_library=SetupLibrary(StorageManager(tmp_path / "layout.db")),
    )
    decision.resize(*size)
    decision.show()
    decision.btnCreateSetup.click()
    app.processEvents()

    try:
        editor = decision.setupEditorForm
        assert editor is not None
        assert decision.pageScroll.verticalScrollBarPolicy() != (
            QtCore.Qt.ScrollBarAlwaysOff
        )
        assert decision.pageScroll.verticalScrollBar().maximum() > 0
        assert editor.saveButton.geometry().bottom() < (
            editor.displayNameEdit.geometry().top()
        )
        assert editor.saveButton.isVisibleTo(decision.pageContent)
        assert editor.cancelButton.isVisibleTo(decision.pageContent)
        if decision.entryBlindReviewWorkspace is not None:
            assert (
                decision.entryBlindReviewWorkspace.columnScroll
                .verticalScrollBar().maximum()
                == 0
            )

        decision.pageScroll.verticalScrollBar().setValue(
            decision.pageScroll.verticalScrollBar().maximum()
        )
        app.processEvents()
        assert decision.stepBar.isVisibleTo(decision.pageContent)

        editor.cancelButton.click()
        app.processEvents()
        assert not decision.setupEditorContainer.isVisible()
        assert decision.setupEditorForm is None
    finally:
        decision.close()
        app.processEvents()


@pytest.mark.parametrize("scale", (1.0, 1.25, 1.5, 1.75))
def test_setup_editor_geometry_survives_windows_dpi_equivalent_viewports(
    tmp_path,
    scale,
):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    decision = DecisionResearchWorkspace(
        language="zh_CN",
        setup_library=SetupLibrary(StorageManager(tmp_path / "dpi-layout.db")),
    )
    decision.resize(round(1920 / scale), round(1080 / scale))
    decision.show()
    decision.btnCreateSetup.click()
    app.processEvents()

    try:
        editor = decision.setupEditorForm
        assert editor is not None
        controls = (
            editor.displayNameEdit,
            editor.directionBox,
            editor.protocolBox,
            editor.rulesEdit,
            editor.decisionTimeframeBox,
            editor.contextTimeframeOneBox,
            editor.contextTimeframeTwoBox,
            editor.cancelButton,
            editor.saveButton,
        )
        rectangles = [
            QtCore.QRect(control.mapTo(editor, QtCore.QPoint()), control.size())
            for control in controls
        ]
        for index, rectangle in enumerate(rectangles):
            assert rectangle.width() > 0 and rectangle.height() > 0
            assert all(
                not rectangle.intersects(other)
                for other in rectangles[index + 1 :]
            )
        assert editor.rulesEdit.height() >= WORKSPACE_SIZES[
            "setup_rules_min_height"
        ]
    finally:
        decision.close()
        app.processEvents()


def test_workspace_applies_existing_dark_and_light_theme_tokens():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    decision = DecisionResearchWorkspace(language="zh_CN")
    action = decision.stepPages["sample_review"].actionButton

    try:
        decision.apply_theme(DARK_THEME)
        dark = normalize_theme_settings(DARK_THEME)
        assert f"background-color: {dark['btn_bg']}" in action.styleSheet()

        decision.apply_theme(LIGHT_THEME)
        light = normalize_theme_settings(LIGHT_THEME)
        assert f"background-color: {light['btn_bg']}" in action.styleSheet()
        assert action.styleSheet() != ""
        assert decision.directionBox.styleSheet() != ""
    finally:
        decision.close()
        app.processEvents()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("primary_tab", "legacy"),
        ("current_step", "unknown"),
        ("direction", "BOTH"),
        ("timeframes", ("1m", "5m")),
        ("timeframes", ("1m", "5m", "13x")),
        ("completeness", "maybe"),
        ("maturity", "profitable"),
    ),
)
def test_page_state_rejects_unknown_context_values(field, value):
    kwargs = {field: value}

    with pytest.raises(ValueError):
        DecisionResearchPageState(**kwargs)


def test_entry_and_exit_modes_keep_independent_readiness_and_versions():
    state = DecisionResearchPageState()
    state.update_readiness(
        setup_version="setup-entry",
        completeness="complete",
        maturity="mature",
    )
    state.update_research_versions(
        grouping_version_id="group-entry",
        blind_batch_id="batch-entry",
        candidate_run_id="candidate-entry",
        behavior_snapshot_id="model-entry",
        outcome_comparison_id="outcome-entry",
    )

    state.select_primary_tab("exit")
    assert state.setup_version is None
    assert state.grouping_version_id is None
    assert state.maturity == "not_ready"
    state.update_readiness(
        setup_version="setup-exit",
        completeness="incomplete",
        maturity="not_ready",
    )
    state.update_research_versions(grouping_version_id="group-exit")

    state.select_primary_tab("entry")
    assert state.setup_version == "setup-entry"
    assert state.grouping_version_id == "group-entry"
    assert state.behavior_snapshot_id == "model-entry"
    assert state.maturity == "mature"

    state.update_research_versions(grouping_version_id="group-entry-v2")
    assert state.candidate_run_id is None
    assert state.behavior_snapshot_id is None
    assert state.outcome_comparison_id is None
    assert state.stale_dependencies == (
        "blind_batch",
        "candidate_run",
        "behavior_snapshot",
        "outcome_comparison",
    )

    state.select_primary_tab("exit")
    assert state.grouping_version_id == "group-exit"
    assert state.stale_dependencies == ()


def test_workspace_mode_switch_restores_readiness_without_resetting_same_setup(
    tmp_path,
):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    library = SetupLibrary(StorageManager(tmp_path / "mode-restore.db"))
    created = library.create_setup(
        CreateSetup(
            display_name="模式恢复",
            version=SetupVersionSpec(
                direction=SetupDirection.LONG,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="仅使用截止线前信息",
                timeframes=TimeframeProfile("1m", "5m", "15m"),
            ),
        )
    )
    decision = DecisionResearchWorkspace(
        language="zh_CN",
        setup_library=library,
    )

    try:
        decision.update_readiness(
            setup_version=created.version.setup_version_id,
            completeness="complete",
            maturity="mature",
        )
        decision.modeTabs.setCurrentIndex(1)
        decision.update_readiness(
            setup_version=created.version.setup_version_id,
            completeness="incomplete",
            maturity="not_ready",
        )

        decision.modeTabs.setCurrentIndex(0)

        assert decision.state.setup_version == created.version.setup_version_id
        assert decision.state.completeness == "complete"
        assert decision.state.maturity == "mature"
    finally:
        decision.close()
        app.processEvents()


def test_workspace_keeps_independent_scroll_position_for_each_step():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    decision = DecisionResearchWorkspace(language="zh_CN")
    decision.resize(420, 420)
    decision.show()
    app.processEvents()

    try:
        scroll = decision.pageScroll.verticalScrollBar()
        assert scroll.maximum() > 2
        sample_position = max(1, scroll.maximum() // 3)
        scroll.setValue(sample_position)

        decision.stepButtons["similar_candidates"].click()
        app.processEvents()
        candidate_position = max(2, scroll.maximum() * 2 // 3)
        scroll.setValue(candidate_position)

        decision.stepButtons["sample_review"].click()
        app.processEvents()

        assert scroll.value() == sample_position
    finally:
        decision.close()
        app.processEvents()


def test_workspace_mode_switch_restores_each_completeness_report():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    decision = DecisionResearchWorkspace(language="zh_CN")

    try:
        decision.render_completeness(_incomplete_report())
        entry_details = tuple(
            label.text() for label in decision.timeframeCompletenessLabels
        )

        decision.modeTabs.setCurrentIndex(1)
        decision.render_completeness(_complete_report())
        assert decision.state.completeness == "complete"

        decision.modeTabs.setCurrentIndex(0)

        assert decision.state.completeness == "incomplete"
        assert tuple(
            label.text() for label in decision.timeframeCompletenessLabels
        ) == entry_details
        assert decision._completeness_report == _incomplete_report()
    finally:
        decision.close()
        app.processEvents()


@pytest.mark.parametrize(
    ("report", "message_key"),
    (
        (_complete_report(), "decision_research.data.audit_complete"),
        (_incomplete_report(), "decision_research.data.audit_incomplete"),
    ),
)
def test_audit_result_replaces_running_message_with_terminal_state(
    report,
    message_key,
):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    decision = DecisionResearchWorkspace(language="zh_CN")

    try:
        decision.begin_audit()
        decision.render_audit_result(report)

        assert decision.backfillStatusLabel.text() == i18n_tr(
            message_key,
            "zh_CN",
        )
        assert decision.btnAuditResearchData.isEnabled() is True
        assert decision.btnCancelBackfill.isEnabled() is False
    finally:
        decision.close()
        app.processEvents()


def test_workspace_records_result_versions_in_the_active_mode_only():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    decision = DecisionResearchWorkspace(language="zh_CN")

    try:
        decision._record_blind_batch(SimpleNamespace(batch_id="entry-batch"))
        decision._record_candidate_result(SimpleNamespace(scan_id="entry-scan"))
        decision._record_behavior_result(
            SimpleNamespace(
                model=SimpleNamespace(model_version_id="entry-model"),
                failure=None,
            )
        )
        decision._record_outcome_result(
            SimpleNamespace(comparison_id="entry-outcome")
        )
        decision.modeTabs.setCurrentIndex(1)

        assert decision.state.blind_batch_id is None
        assert decision.state.candidate_run_id is None
        assert decision.state.behavior_snapshot_id is None
        assert decision.state.outcome_comparison_id is None

        decision._record_candidate_result(SimpleNamespace(scan_id="exit-scan"))
        decision.modeTabs.setCurrentIndex(0)

        assert decision.state.blind_batch_id == "entry-batch"
        assert decision.state.candidate_run_id == "entry-scan"
        assert decision.state.behavior_snapshot_id == "entry-model"
        assert decision.state.outcome_comparison_id == "entry-outcome"
    finally:
        decision.close()
        app.processEvents()


def test_readiness_update_keeps_unimplemented_actions_disabled():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    decision = DecisionResearchWorkspace(language="zh_CN")

    try:
        assert all(
            not page.actionButton.isEnabled()
            for page in decision.stepPages.values()
        )

        decision.update_readiness(
            setup_version="setup-v1",
            completeness="complete",
            maturity="mature",
        )

        assert decision.setupValueLabel.text() == "setup-v1"
        assert decision.completenessLabel.text() == "完整"
        assert decision.maturityLabel.text() == "成熟"
        assert all(
            not page.actionButton.isEnabled()
            for page in decision.stepPages.values()
        )
        assert all(
            "后续切片" in page.gateHint.text()
            for step, page in decision.stepPages.items()
            if step != "version_report"
        )
        assert "当前草稿" in decision.stepPages[
            "version_report"
        ].gateHint.text()
    finally:
        decision.close()
        app.processEvents()


def test_incomplete_ancillary_data_does_not_block_manual_sample_review():
    state = DecisionResearchPageState(
        setup_version="setup-v1",
        completeness="incomplete",
        maturity="mature",
    )

    assert state.missing_conditions("sample_review") == ()
    assert state.missing_conditions("similar_candidates") == (
        "completeness",
    )
    assert state.missing_conditions("behavior_model") == (
        "completeness",
    )
    assert state.missing_conditions("outcome_comparison") == (
        "completeness",
    )


def test_workspace_shows_three_timeframe_deficits_and_backfill_action():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    decision = DecisionResearchWorkspace(language="zh_CN")

    try:
        decision.render_completeness(_incomplete_report())

        assert decision.state.completeness == "incomplete"
        assert len(decision.timeframeCompletenessLabels) == 3
        assert "1m" in decision.timeframeCompletenessLabels[0].text()
        assert "缺少 1 根 K 线" in decision.timeframeCompletenessLabels[0].text()
        assert "计价币成交额 2 行" in decision.timeframeCompletenessLabels[0].text()
        assert "5m" in decision.timeframeCompletenessLabels[1].text()
        assert "100.0%" in decision.timeframeCompletenessLabels[1].text()
        assert decision.btnBackfillResearchRange.isEnabled() is True
        assert decision.btnCancelBackfill.isEnabled() is False
    finally:
        decision.close()
        app.processEvents()


def test_workspace_propagates_completeness_gate_to_formal_candidate_actions():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    controller = _CandidateController()
    decision = DecisionResearchWorkspace(
        language="zh_CN",
        similarity_service=_EmptyBrowseService(),
        candidate_service=object(),
        candidate_controller=controller,
    )

    try:
        decision.update_readiness(
            setup_version="setup-v1",
            completeness="not_audited",
            maturity="not_ready",
        )
        browser = decision.entrySimilarityBrowser
        browser.set_research_context(
            setup_version_id="setup-v1",
            direction="LONG",
            grouping_version_id="grouping-v1",
        )

        decision.render_completeness(_incomplete_report())
        assert browser.scanCandidatesButton.isEnabled() is False
        assert "计价币成交额 2 行" in browser.candidateGateLabel.text()

        decision.render_completeness(_complete_report())
        assert browser.scanCandidatesButton.isEnabled() is True
        assert browser.candidateGateLabel.isHidden()
    finally:
        decision.close()
        app.processEvents()


def test_workspace_requires_complete_and_mature_context_before_training():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    controller = _BehaviorController()
    decision = DecisionResearchWorkspace(
        language="zh_CN",
        behavior_training_service=_BehaviorService(),
        behavior_training_controller=controller,
    )

    try:
        decision.render_episode_audit(
            EpisodeAuditSummary(
                grouping_version_id="grouping-v1",
                formula_version="episode-v1",
                grouping_source=EpisodeSource.AUTOMATIC,
                episode_count=0,
                sample_count=0,
                composition=(),
                can_correct=False,
            )
        )
        decision.update_readiness(
            setup_version="setup-v1",
            completeness="complete",
            maturity="not_ready",
        )
        page = decision.entryBehaviorModelWorkspace

        assert page.trainButton.isEnabled() is False
        assert "成熟度" in page.trainingGateLabel.text()

        decision.update_readiness(
            setup_version="setup-v1",
            completeness="complete",
            maturity="mature",
        )
        assert page.trainButton.isEnabled() is True
        assert page.trainingGateLabel.isHidden()
    finally:
        decision.close()
        app.processEvents()


def test_completed_candidate_maturity_updates_the_shared_research_context():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    controller = _CandidateController()
    decision = DecisionResearchWorkspace(
        language="zh_CN",
        similarity_service=_EmptyBrowseService(),
        candidate_service=object(),
        candidate_controller=controller,
    )

    try:
        decision.render_episode_audit(
            EpisodeAuditSummary(
                grouping_version_id="grouping-v1",
                formula_version="episode-v1",
                grouping_source=EpisodeSource.AUTOMATIC,
                episode_count=5,
                sample_count=10,
                composition=(),
                can_correct=True,
            )
        )
        decision.update_readiness(
            setup_version="setup-v1",
            completeness="complete",
            maturity="not_ready",
        )
        controller.resultReady.emit(
            CandidateScanOverview(
                scan_id="scan-v1",
                setup_version_id="setup-v1",
                grouping_version_id="grouping-v1",
                direction="LONG",
                status=CandidateScanStatus.COMPLETED,
                maturity=CandidateMaturity(10, 5),
                candidate_universe_count=0,
                usable_candidate_count=0,
                unavailable_candidate_count=0,
                episode_coverage_count=0,
                similarity_distribution=CandidateSimilarityDistribution(
                    0,
                    0,
                    0,
                ),
            )
        )
        app.processEvents()

        assert decision.state.maturity == "mature"
        assert decision.maturityLabel.text() == "成熟"
    finally:
        decision.close()
        app.processEvents()


def test_research_context_change_invalidates_completeness_and_maturity():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    decision = DecisionResearchWorkspace(language="zh_CN")

    try:
        decision.update_readiness(
            setup_version="setup-v1",
            completeness="complete",
            maturity="mature",
        )

        decision.directionBox.setCurrentIndex(
            decision.directionBox.findData("SHORT")
        )
        app.processEvents()

        assert decision.state.completeness == "not_audited"
        assert decision.state.maturity == "not_ready"
    finally:
        decision.close()
        app.processEvents()


def test_episode_grouping_version_change_invalidates_candidate_maturity():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    decision = DecisionResearchWorkspace(language="zh_CN")

    def summary(version: str) -> EpisodeAuditSummary:
        return EpisodeAuditSummary(
            grouping_version_id=version,
            formula_version="episode-v1",
            grouping_source=EpisodeSource.AUTOMATIC,
            episode_count=5,
            sample_count=10,
            composition=(),
            can_correct=True,
        )

    try:
        decision.render_episode_audit(summary("grouping-v1"))
        decision.update_readiness(
            setup_version="setup-v1",
            completeness="complete",
            maturity="mature",
        )

        decision.render_episode_audit(summary("grouping-v2"))

        assert decision.state.completeness == "complete"
        assert decision.state.maturity == "not_ready"
    finally:
        decision.close()
        app.processEvents()


def test_workspace_progress_cancel_retry_and_chinese_error_state():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    decision = DecisionResearchWorkspace(language="zh_CN")

    try:
        decision.begin_backfill()
        decision.render_backfill_progress(
            ResearchBackfillProgress(
                completed_chunks=1,
                total_chunks=2,
                downloaded_bars=1_000,
                interval="1m",
                start_time_utc_ms=1_000,
                end_time_utc_ms=60_941_000,
            )
        )

        assert decision.backfillProgress.value() == 50
        assert decision.btnCancelBackfill.isEnabled() is True
        assert decision.btnBackfillResearchRange.isEnabled() is False

        decision.render_backfill_failure("ConnectionError: offline")

        assert decision.btnRetryBackfill.isEnabled() is True
        assert decision.btnCancelBackfill.isEnabled() is False
        assert "补齐失败" in decision.backfillStatusLabel.text()
        assert "offline" in decision.backfillStatusLabel.text()
        assert "ConnectionError" not in decision.backfillStatusLabel.text()
    finally:
        decision.close()
        app.processEvents()
