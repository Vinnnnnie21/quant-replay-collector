from __future__ import annotations

import pytest


QtCore = pytest.importorskip("PySide6.QtCore")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from controllers.entry_blind_review_controller import (
    EntryBlindReviewController,
)
from analysis_workspace import AnalysisWorkspace
from research.market_episodes import MarketEpisodeService
from research.entry_blind_review import (
    BlindBatchItem,
    BlindReviewBatch,
    RevealedCandidateAudit,
    RevealedCandidateReference,
    ReviewStatus,
)
from services.entry_blind_review import EntryBlindReviewService
from storage import StorageManager
from ui_style import DARK_THEME, LIGHT_THEME, normalize_theme_settings
from tests.research.test_entry_blind_review import (
    _actual_open,
    _episode_grouping,
    _setup_version,
    _store_cutoff_fixture,
)
from views.entry_blind_review_workspace import EntryBlindReviewWorkspace
from views.decision_research_workspace import DecisionResearchWorkspace


class _AnalysisHost(QtWidgets.QWidget):
    current_language = "zh_CN"
    session_id = "entry_blind_session"

    def __init__(self, storage: StorageManager) -> None:
        super().__init__()
        self.storage = storage


class _CandidateAuditController:
    def load_existing_batch(self, batch):
        self.batch = batch
        return batch

    def save_blind_judgment(self, _judgment):
        from research.entry_blind_review import (
            EntryJudgmentLabel,
            EntryJudgmentVersion,
            ReviewPhase,
        )

        return EntryJudgmentVersion(
            judgment_id="judgment_1",
            decision_event_id="candidate_event_1",
            version_number=1,
            phase=ReviewPhase.BLIND,
            label=EntryJudgmentLabel.ENTRY,
            reason_tags=("long_lower_shadow",),
            confidence=3,
            note="",
            previous_judgment_id=None,
            eligible_for_primary_research=True,
            created_at="2026-01-01T00:00:00+00:00",
        )

    def candidate_audit_current(self):
        return RevealedCandidateAudit(
            similarity=88.5,
            group_distances=tuple(float(index) / 100 for index in range(12)),
            references=tuple(
                RevealedCandidateReference(
                    decision_event_id=f"anonymous_reference_{index}",
                    episode_id=f"episode_{index}",
                    similarity=90.0 - index,
                )
                for index in range(3)
            ),
            enqueue_reason="STRUCTURAL_SIMILARITY",
            selection_reason="HIGH_SIMILARITY",
        )


def test_actual_open_completes_three_timeframe_blind_review_before_reveal(
    tmp_path,
):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    storage = StorageManager(tmp_path / "entry_blind_review_ui.db")
    setup = _setup_version(storage)
    _actual_open(storage)
    _store_cutoff_fixture(storage)
    grouping = _episode_grouping(storage)
    service = EntryBlindReviewService(storage)
    receipt = service.enqueue_actual_open(
        trade_event_id="event_open_1",
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    controller = EntryBlindReviewController(service)
    workspace = EntryBlindReviewWorkspace(
        controller=controller,
        language="zh_CN",
    )
    workspace.resize(1100, 720)
    workspace.show()

    try:
        workspace.set_research_context(
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping.grouping_version_id,
            setup_version_label="回踩确认 · 版本 1",
        )
        workspace.loadBatchButton.click()
        app.processEvents()

        assert workspace.setupVersionLabel.text() == "回踩确认 · 版本 1"
        assert "setup_version" not in workspace.setupVersionLabel.text()

        assert len(workspace.chartPanes) == 3
        assert [pane.interval for pane in workspace.chartPanes] == [
            "1m",
            "5m",
            "15m",
        ]
        cutoff = workspace.chartPanes[0].cutoff_time_utc_ms
        assert all(
            pane.cutoff_time_utc_ms == cutoff
            for pane in workspace.chartPanes
        )
        assert all(
            all(bar.close_time_utc_ms <= cutoff for bar in pane.bars)
            for pane in workspace.chartPanes
        )
        assert workspace.chartPanes[1].y() == workspace.chartPanes[2].y()
        assert isinstance(workspace.reasonBox, QtWidgets.QListWidget)
        assert (
            workspace.reasonBox.selectionMode()
            == QtWidgets.QAbstractItemView.ExtendedSelection
        )

        workspace.move_linked_crosshair(cutoff)
        assert all(
            pane.crosshair_time_utc_ms == cutoff
            for pane in workspace.chartPanes
        )
        visible_before_save = " ".join(
            widget.text()
            for widget in workspace.findChildren(QtWidgets.QLabel)
        )
        assert "实际开仓" not in visible_before_save
        assert "OPEN_LONG" not in visible_before_save

        workspace.judgmentBox.setCurrentIndex(
            workspace.judgmentBox.findData("ENTRY")
        )
        for index in range(workspace.reasonBox.count()):
            reason_item = workspace.reasonBox.item(index)
            reason_item.setSelected(
                reason_item.data(QtCore.Qt.UserRole)
                in {"long_lower_shadow", "volume_spike"}
            )
        workspace.confidenceSpin.setValue(4)
        workspace.noteEdit.setPlainText("盲态判断")
        workspace.saveButton.click()
        app.processEvents()

        assert workspace.revealButton.isEnabled() is True
        assert "已保存" in workspace.statusLabel.text()
        assert "已判断" in workspace.batchList.currentItem().text()
        assert workspace.blindJudgmentSummary.isVisible()
        assert "4" in workspace.blindJudgmentSummary.text()
        assert service.list_judgments(receipt.decision_event_id)[0].reason_tags == (
            "long_lower_shadow",
            "volume_spike",
        )

        workspace.revealButton.click()
        app.processEvents()

        assert "实际开仓" in workspace.sourceLabel.text()
        assert "时点近似" in workspace.sourceLabel.text()
        assert workspace.relabelButton.isEnabled() is True
        assert "已揭示" in workspace.batchList.currentItem().text()

        workspace.retranslate_ui("en_US")
        assert "Actual open" in workspace.sourceLabel.text()
        assert "Original blinded judgment" in workspace.blindJudgmentSummary.text()

        workspace.judgmentBox.setCurrentIndex(
            workspace.judgmentBox.findData("REJECT")
        )
        workspace.relabelButton.click()
        versions = service.list_judgments(receipt.decision_event_id)
        assert [version.phase.value for version in versions] == [
            "BLIND",
            "POST_OUTCOME",
        ]
        assert versions[-1].eligible_for_primary_research is False
    finally:
        workspace.close()
        app.processEvents()


def test_blind_workspace_empty_narrow_theme_and_translation_states(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    storage = StorageManager(tmp_path / "entry_blind_ui_empty.db")
    setup = _setup_version(storage)
    grouping = _episode_grouping(storage, "manual_not_enqueued")
    workspace = EntryBlindReviewWorkspace(
        controller=EntryBlindReviewController(
            EntryBlindReviewService(storage)
        ),
        language="zh_CN",
    )
    workspace.resize(320, 620)
    workspace.show()

    try:
        workspace.set_research_context(
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping.grouping_version_id,
        )
        workspace.loadBatchButton.click()
        app.processEvents()

        assert workspace.batchList.count() == 0
        assert all(pane.bars == () for pane in workspace.chartPanes)
        assert "没有待确认种子" in workspace.statusLabel.text()
        assert workspace.batchPanel.isHidden()
        assert workspace.batchToggleButton.isVisible()
        assert workspace.columnScroll.horizontalScrollBar().maximum() > 0

        workspace.apply_theme(DARK_THEME)
        dark = normalize_theme_settings(DARK_THEME)
        assert (
            workspace.chartPanes[0].plot.backgroundBrush().color().name().upper()
            == dark["chart_bg"]
        )
        workspace.apply_theme(LIGHT_THEME)
        light = normalize_theme_settings(LIGHT_THEME)
        assert (
            workspace.chartPanes[0].plot.backgroundBrush().color().name().upper()
            == light["chart_bg"]
        )

        workspace.retranslate_ui("en_US")
        assert workspace.batchTitle.text() == "Pending Seeds"
        assert workspace.saveButton.text() == "Save Blinded Judgment"
        assert workspace.judgmentBox.itemText(0) == "Entry"
    finally:
        workspace.close()
        app.processEvents()


def test_data_analysis_builds_the_real_entry_blind_review_controller(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _AnalysisHost(StorageManager(tmp_path / "analysis_blind_ui.db"))
    workspace = AnalysisWorkspace(host)

    try:
        assert workspace.decisionResearchWorkspace.entryBlindReviewWorkspace is not None
        assert isinstance(
            workspace.decisionResearchWorkspace.stepPages["sample_review"],
            EntryBlindReviewWorkspace,
        )
    finally:
        workspace.close()
        host.close()
        app.processEvents()


def test_decision_research_sample_review_step_hosts_the_shared_blind_workspace(
    tmp_path,
):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    storage = StorageManager(tmp_path / "entry_blind_review_shell.db")
    setup = _setup_version(storage)
    grouping = _episode_grouping(storage, "manual_seed_1")
    controller = EntryBlindReviewController(
        EntryBlindReviewService(storage)
    )
    workspace = DecisionResearchWorkspace(
        language="zh_CN",
        entry_review_controller=controller,
    )

    try:
        workspace.update_readiness(
            setup_version=setup.setup_version_id,
            completeness="incomplete",
            maturity="not_ready",
        )
        workspace.render_episode_audit(
            MarketEpisodeService(storage).audit_summary(
                grouping.grouping_version_id
            )
        )
        workspace.stepButtons["sample_review"].click()

        assert (
            workspace.stepStack.currentWidget()
            is workspace.entryBlindReviewWorkspace
        )
        assert (
            workspace.stepPages["sample_review"]
            is workspace.entryBlindReviewWorkspace
        )
        assert workspace.entryBlindReviewWorkspace.loadBatchButton.isEnabled()
        assert workspace.stepButtons["similar_candidates"].isEnabled()

        workspace.modeTabs.setCurrentIndex(1)
        app.processEvents()
        assert workspace.entryBlindReviewWorkspace.columnScroll.isHidden()
        assert not workspace.entryBlindReviewWorkspace.loadBatchButton.isEnabled()
        workspace.retranslate_ui("en_US")
        assert (
            workspace.entryBlindReviewWorkspace.statusLabel.text()
            == "Entry seed review is available only under Entry Research."
        )

        workspace.modeTabs.setCurrentIndex(0)
        app.processEvents()
        assert not workspace.entryBlindReviewWorkspace.columnScroll.isHidden()
        assert workspace.entryBlindReviewWorkspace.loadBatchButton.isEnabled()
        assert (
            workspace.entryBlindReviewWorkspace.batchTitle.text()
            == "Pending Seeds"
        )
    finally:
        workspace.close()
        app.processEvents()


def test_formal_candidate_batch_is_loaded_and_audit_unlocks_only_after_save():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    controller = _CandidateAuditController()
    workspace = EntryBlindReviewWorkspace(
        controller=controller,
        language="zh_CN",
    )
    batch = BlindReviewBatch(
        batch_id="formal_candidate_batch",
        setup_version_id="setup_version_1",
        grouping_version_id="grouping_version_1",
        items=(
            BlindBatchItem("anonymous_1", ReviewStatus.PENDING_CONFIRMATION),
            BlindBatchItem("anonymous_2", ReviewStatus.PENDING_CONFIRMATION),
        ),
    )

    try:
        assert workspace.candidateAuditLabel.isHidden()
        workspace.load_existing_batch(batch)
        assert workspace.batchList.count() == 2
        assert all(
            "88.5" not in workspace.batchList.item(index).text()
            for index in range(workspace.batchList.count())
        )

        workspace._save_blind_judgment()

        assert workspace.candidateAuditLabel.isHidden() is False
        audit_text = workspace.candidateAuditLabel.text()
        assert "88.50" in audit_text
        assert "3" in audit_text
        assert "高相似" in audit_text
    finally:
        workspace.close()
        app.processEvents()


def test_decision_workspace_routes_formal_candidate_batch_to_shared_review_list():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    controller = EntryBlindReviewController(object())
    workspace = DecisionResearchWorkspace(
        language="zh_CN",
        entry_review_controller=controller,
    )
    batch = BlindReviewBatch(
        batch_id="formal_batch_routed",
        setup_version_id="setup_version_1",
        grouping_version_id="grouping_version_1",
        items=(
            BlindBatchItem("anonymous_1", ReviewStatus.PENDING_CONFIRMATION),
        ),
    )

    try:
        workspace._load_formal_candidate_batch(batch)

        assert controller.batch == batch
        assert workspace.entryBlindReviewWorkspace.batchList.count() == 1
        assert "1" in workspace.entryBlindReviewWorkspace.statusLabel.text()
    finally:
        workspace.close()
        app.processEvents()
