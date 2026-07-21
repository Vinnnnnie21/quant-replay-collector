from __future__ import annotations

from datetime import timedelta

import pytest


QtCore = pytest.importorskip("PySide6.QtCore")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from research.entry_candidate_generation import (
    CandidateMaturity,
    CandidateScanOverview,
    CandidateScanStatus,
    CandidateSimilarityDistribution,
)
from research.exit_candidate_generation import (
    ExitCandidateMaturity,
    ExitCandidateScanOverview,
    ExitCandidateScanRequest,
    ExitCandidateScanStatus,
    ExitCandidateSimilarityDistribution,
)
from services.entry_structural_similarity import EntryStructuralSimilarityService
from storage import StorageManager
from tests.research.test_entry_blind_review import DECISION_TIME
from tests.research.test_entry_structural_similarity import (
    _create_revealed_pair,
    _store_similarity_history,
)
from ui_style import DARK_THEME, LIGHT_THEME
from views.entry_similarity_browser import EntrySimilarityBrowser
from views.decision_research_workspace import DecisionResearchWorkspace


class _EmptyBrowseService:
    def list_browsable_samples(self, **_kwargs):
        return ()


class _CandidateOverviewController(QtCore.QObject):
    resultReady = QtCore.Signal(object)
    progress = QtCore.Signal(object)
    failed = QtCore.Signal(str)
    cancelled = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.request = None
        self.is_running = False

    def start(self, request):
        self.request = request
        self.is_running = True
        return 1

    def cancel(self):
        self.is_running = False

    def invalidate(self):
        self.is_running = False


def test_free_browse_ui_shows_chinese_formula_and_full_three_timeframe_breakdown(
    tmp_path,
):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    storage = StorageManager(tmp_path / "entry_similarity_ui.db")
    setup, _, _ = _create_revealed_pair(storage)
    second_time = DECISION_TIME + timedelta(days=7)
    _store_similarity_history(storage, DECISION_TIME.replace(second=0, microsecond=0))
    _store_similarity_history(storage, second_time.replace(second=0, microsecond=0))
    browser = EntrySimilarityBrowser(
        service=EntryStructuralSimilarityService(storage),
        language="zh_CN",
    )
    browser.resize(760, 520)
    browser.show()

    try:
        browser.set_research_context(
            setup_version_id=setup.setup_version_id,
            direction="LONG",
        )
        assert browser.leftSampleBox.count() == 2
        assert browser.rightSampleBox.count() == 2
        browser.leftSampleBox.setCurrentIndex(0)
        browser.rightSampleBox.setCurrentIndex(1)
        browser.compareButton.click()
        app.processEvents()

        assert "100.00" in browser.totalSimilarityLabel.text()
        assert "5/20/60" in browser.formulaExplanation.text()
        assert "不能进入正式模型或正式匹配" in browser.evidenceWarning.text()
        assert browser.breakdownTree.topLevelItemCount() == 3
        assert all(
            browser.breakdownTree.topLevelItem(index).childCount() == 4
            for index in range(3)
        )
        assert len(browser.referencePlaceholders) == 3
        assert all("本轮不扫描" in label.text() for label in browser.referencePlaceholders)

        browser.apply_theme(DARK_THEME)
        browser.apply_theme(LIGHT_THEME)
        browser.resize(360, 520)
        app.processEvents()
        assert browser.scrollArea.horizontalScrollBar().maximum() > 0
    finally:
        browser.close()
        app.processEvents()


def test_candidate_overview_clears_stale_summary_when_context_changes(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    storage = StorageManager(tmp_path / "entry_similarity_ui_context.db")
    browser = EntrySimilarityBrowser(
        service=EntryStructuralSimilarityService(storage),
        language="zh_CN",
    )

    try:
        browser.candidateSummaryLabel.setText("stale candidate result")
        browser.set_research_context(
            setup_version_id=None,
            direction=None,
            grouping_version_id=None,
        )

        assert "stale" not in browser.candidateSummaryLabel.text()
        assert "尚未扫描" in browser.candidateSummaryLabel.text()
    finally:
        browser.close()
        app.processEvents()


def test_formal_candidate_page_receives_only_aggregate_distribution():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    controller = _CandidateOverviewController()
    browser = EntrySimilarityBrowser(
        service=_EmptyBrowseService(),
        candidate_service=object(),
        candidate_controller=controller,
        language="zh_CN",
    )

    try:
        browser.set_research_context(
            setup_version_id="setup_version_1",
            direction="LONG",
            grouping_version_id="grouping_version_1",
        )
        browser.set_candidate_operation_gate(allowed=True, message="")
        browser.scanCandidatesButton.click()
        assert controller.request.setup_version_id == "setup_version_1"
        overview = CandidateScanOverview(
            scan_id="scan_1",
            setup_version_id="setup_version_1",
            grouping_version_id="grouping_version_1",
            direction="LONG",
            status=CandidateScanStatus.COMPLETED,
            maturity=CandidateMaturity(10, 5),
            candidate_universe_count=7,
            usable_candidate_count=6,
            unavailable_candidate_count=1,
            episode_coverage_count=6,
            similarity_distribution=CandidateSimilarityDistribution(2, 3, 1),
        )
        controller.is_running = False
        controller.resultReady.emit(overview)
        app.processEvents()

        summary = browser.candidateSummaryLabel.text()
        assert "6/7" in summary
        assert "80—100：2" in summary
        assert "60—<80：3" in summary
        assert "candidate" not in summary.lower()
        assert browser.createBatchButton.isEnabled()
    finally:
        browser.close()
        app.processEvents()


def test_candidate_scan_is_blocked_until_ancillary_data_gate_is_complete():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    controller = _CandidateOverviewController()
    browser = EntrySimilarityBrowser(
        service=_EmptyBrowseService(),
        candidate_service=object(),
        candidate_controller=controller,
        language="zh_CN",
    )

    try:
        browser.set_research_context(
            setup_version_id="setup_version_1",
            direction="LONG",
            grouping_version_id="grouping_version_1",
        )

        assert browser.scanCandidatesButton.isEnabled() is False
        browser.scanCandidatesButton.click()
        assert controller.request is None

        browser.set_candidate_operation_gate(
            allowed=False,
            message="附加原始字段仍有差额：1m 计价币成交额 2 行。",
        )
        assert "计价币成交额 2 行" in browser.candidateGateLabel.text()

        controller.is_running = True
        browser.set_candidate_operation_gate(
            allowed=False,
            message="附加原始字段仍有差额：1m 计价币成交额 2 行。",
        )
        assert browser.cancelScanButton.isEnabled() is True
        controller.is_running = False

        browser.set_candidate_operation_gate(allowed=True, message="")
        assert browser.scanCandidatesButton.isEnabled() is True
        assert browser.candidateGateLabel.isHidden()
    finally:
        browser.close()
        app.processEvents()


def test_similar_candidates_step_hosts_free_browser_and_isolates_exit_tab(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    storage = StorageManager(tmp_path / "entry_similarity_shell.db")
    setup, _, _ = _create_revealed_pair(storage)
    workspace = DecisionResearchWorkspace(
        language="zh_CN",
        similarity_service=EntryStructuralSimilarityService(storage),
    )

    try:
        workspace.update_readiness(
            setup_version=setup.setup_version_id,
            completeness="complete",
            maturity="mature",
        )
        workspace.stepButtons["similar_candidates"].click()
        assert isinstance(
            workspace.stepPages["similar_candidates"],
            EntrySimilarityBrowser,
        )
        assert workspace.stepStack.currentWidget() is workspace.entrySimilarityBrowser
        assert workspace.entrySimilarityBrowser.leftSampleBox.count() == 2

        workspace.modeTabs.setCurrentIndex(1)
        app.processEvents()
        assert not workspace.entrySimilarityBrowser.content.isHidden()
        assert not workspace.entrySimilarityBrowser.compareButton.isEnabled()

        workspace.modeTabs.setCurrentIndex(0)
        app.processEvents()
        assert workspace.entrySimilarityBrowser.leftSampleBox.count() == 2
        assert workspace.entrySimilarityBrowser.rightSampleBox.count() == 2
        assert workspace.entrySimilarityBrowser.compareButton.isEnabled()
    finally:
        workspace.close()
        app.processEvents()


def test_similar_candidates_uses_only_the_workspace_vertical_scroll():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    workspace = DecisionResearchWorkspace(
        language="zh_CN",
        similarity_service=_EmptyBrowseService(),
    )
    workspace.resize(1366, 520)
    workspace.show()

    try:
        workspace.stepButtons["similar_candidates"].click()
        for _index in range(5):
            app.processEvents()

        active_vertical_scrolls = [
            area
            for area in workspace.findChildren(QtWidgets.QScrollArea)
            if area.isVisibleTo(workspace)
            and area.verticalScrollBarPolicy()
            != QtCore.Qt.ScrollBarAlwaysOff
            and area.verticalScrollBar().maximum() > 0
        ]

        assert active_vertical_scrolls == [workspace.pageScroll]
        workspace.pageScroll.verticalScrollBar().setValue(
            workspace.pageScroll.verticalScrollBar().maximum()
        )
        for _index in range(3):
            app.processEvents()
        assert not (
            workspace.entrySimilarityBrowser.referencePlaceholders[-1]
            .visibleRegion()
            .isEmpty()
        )
    finally:
        workspace.close()
        app.processEvents()


def test_exit_candidate_mode_uses_exit_request_and_chinese_holding_maturity():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    exit_controller = _CandidateOverviewController()
    browser = EntrySimilarityBrowser(
        service=_EmptyBrowseService(),
        exit_candidate_service=object(),
        exit_candidate_controller=exit_controller,
        language="zh_CN",
    )

    try:
        browser.set_entry_mode_active(False)
        browser.set_research_context(
            setup_version_id="setup_exit",
            direction="SHORT",
            grouping_version_id="grouping_exit",
        )
        browser.set_candidate_operation_gate(allowed=True, message="")
        browser.scanCandidatesButton.click()

        assert isinstance(exit_controller.request, ExitCandidateScanRequest)
        assert exit_controller.request.direction == "SHORT"
        assert not browser.content.isHidden()
        assert not browser.compareButton.isEnabled()

        exit_controller.is_running = False
        exit_controller.resultReady.emit(
            ExitCandidateScanOverview(
                scan_id="exit_scan",
                setup_version_id="setup_exit",
                grouping_version_id="grouping_exit",
                direction="SHORT",
                status=ExitCandidateScanStatus.COMPLETED,
                maturity=ExitCandidateMaturity(10, 5),
                candidate_universe_count=3,
                usable_candidate_count=2,
                unavailable_candidate_count=1,
                episode_coverage_count=2,
                similarity_distribution=ExitCandidateSimilarityDistribution(
                    1,
                    1,
                    0,
                ),
            )
        )
        app.processEvents()

        summary = browser.candidateSummaryLabel.text()
        assert "立即平仓" in summary
        assert "持仓片段" in summary
        assert "10" in summary
    finally:
        browser.close()
        app.processEvents()


def test_not_computable_ui_explains_timeframe_group_deficits_and_feature_reason(
    tmp_path,
):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    storage = StorageManager(tmp_path / "entry_similarity_ui_missing.db")
    setup, _, _ = _create_revealed_pair(storage)
    browser = EntrySimilarityBrowser(
        service=EntryStructuralSimilarityService(storage),
        language="zh_CN",
    )

    try:
        browser.set_research_context(
            setup_version_id=setup.setup_version_id,
            direction="LONG",
        )
        browser.leftSampleBox.setCurrentIndex(0)
        browser.rightSampleBox.setCurrentIndex(1)
        browser.compareButton.click()
        app.processEvents()

        assert "1m" in browser.statusLabel.text()
        assert "价格路径" in browser.statusLabel.text()
        assert "0/3" in browser.statusLabel.text()
        path_feature = browser.breakdownTree.topLevelItem(0).child(0).child(0)
        assert "历史不足" in path_feature.text(3)
    finally:
        browser.close()
        app.processEvents()


def test_sample_status_retranslates_without_losing_browse_context(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    storage = StorageManager(tmp_path / "entry_similarity_ui_i18n.db")
    setup, _, _ = _create_revealed_pair(storage)
    browser = EntrySimilarityBrowser(
        service=EntryStructuralSimilarityService(storage),
        language="zh_CN",
    )

    try:
        browser.set_research_context(
            setup_version_id=setup.setup_version_id,
            direction="LONG",
        )
        assert "2" in browser.statusLabel.text()

        browser.retranslate_ui("en_US")

        assert browser.statusLabel.text() == (
            "Found 2 revealed samples available for free browse."
        )
        assert browser.leftSampleBox.count() == 2
    finally:
        browser.close()
        app.processEvents()
