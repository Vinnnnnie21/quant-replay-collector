from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from controllers.exit_blind_review_controller import ExitBlindReviewController
from decision_research_state import DecisionResearchPageState
from research.entry_blind_review import (
    RevealedCandidateAudit,
    RevealedCandidateReference,
)
from services.entry_blind_review import EntryBlindReviewService
from services.exit_blind_review import (
    ExitBlindReviewService,
    PartialExitUnsupportedError,
)
from views.decision_research_workspace import DecisionResearchWorkspace
from views.entry_blind_review_workspace import EntryBlindReviewWorkspace

from tests.research.test_exit_blind_review import (
    _closed_trade,
    _grouping,
    _setup_version,
    _store_klines,
)


class _EntryController:
    review_kind = "entry"
    judgment_labels = ("ENTRY", "REJECT", "UNCERTAIN")


class _ExitController:
    review_kind = "exit"
    judgment_labels = ("EXIT_NOW", "HOLD", "UNCERTAIN")


def test_entry_and_exit_tabs_reuse_one_visible_three_column_review_workspace(
):
    qapp = QtWidgets.QApplication.instance()
    assert qapp is not None
    entry_controller = _EntryController()
    exit_controller = _ExitController()
    workspace = DecisionResearchWorkspace(
        language="zh_CN",
        state=DecisionResearchPageState(
            primary_tab="entry",
            current_step="sample_review",
        ),
        entry_review_controller=entry_controller,
        exit_review_controller=exit_controller,
    )
    workspace.resize(1200, 760)
    workspace.show()
    qapp.processEvents()

    review = workspace.entryBlindReviewWorkspace
    assert isinstance(review, EntryBlindReviewWorkspace)
    assert workspace.stepPages["sample_review"] is review
    assert review.controller is entry_controller
    assert not review.columnScroll.isHidden()

    exit_index = next(
        index
        for index in range(workspace.modeTabs.count())
        if workspace.modeTabs.tabData(index) == "exit"
    )
    workspace.modeTabs.setCurrentIndex(exit_index)
    qapp.processEvents()

    assert workspace.stepPages["sample_review"] is review
    assert review.controller is exit_controller
    assert not review.columnScroll.isHidden()
    assert [
        review.judgmentBox.itemData(index)
        for index in range(review.judgmentBox.count())
    ] == ["EXIT_NOW", "HOLD", "UNCERTAIN"]
    assert review.judgmentBox.itemText(0) == "现在平仓"
    assert review.judgmentBox.itemText(1) == "继续持有"
    assert "平仓" in review.formTitle.text()
    assert review.formPanel.minimumWidth() == 260
    assert review.chartPanel.minimumWidth() == 420

    workspace.close()
    workspace.deleteLater()
    qapp.processEvents()


def test_exit_review_narrow_layout_keeps_judgment_action_reachable():
    qapp = QtWidgets.QApplication.instance()
    assert qapp is not None
    workspace = EntryBlindReviewWorkspace(
        controller=_EntryController(),
        exit_controller=_ExitController(),
        language="zh_CN",
    )
    workspace.set_entry_mode_active(False)
    workspace.resize(780, 640)
    workspace.show()
    qapp.processEvents()

    assert workspace.batchToggleButton.isVisible()
    assert workspace.formPanel.isVisibleTo(workspace)
    assert workspace.saveButton.text() == "保存平仓判断"
    assert workspace.saveButton.focusPolicy() != QtCore.Qt.NoFocus
    workspace._show_failure(
        PartialExitUnsupportedError(
            "v1.6 exit research supports full closes only"
        )
    )
    assert "v1.6" in workspace.statusLabel.text()
    assert "部分减仓" in workspace.statusLabel.text()

    workspace.close()
    workspace.deleteLater()
    qapp.processEvents()


def test_real_exit_review_stays_blind_until_save_and_explicit_reveal(tmp_path):
    qapp = QtWidgets.QApplication.instance()
    assert qapp is not None
    from storage import StorageManager

    storage = StorageManager(tmp_path / "exit_review_ui.db")
    setup = _setup_version(storage)
    _closed_trade(storage)
    _store_klines(storage)
    grouping = _grouping(storage)
    EntryBlindReviewService(storage).enqueue_actual_open(
        trade_event_id="event_open_exit_review",
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    workspace = EntryBlindReviewWorkspace(
        controller=_EntryController(),
        exit_controller=ExitBlindReviewController(
            ExitBlindReviewService(storage)
        ),
        language="zh_CN",
    )
    workspace.set_entry_mode_active(False)
    workspace.set_research_context(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    workspace.show()
    qapp.processEvents()

    assert workspace.loadBatchButton.isEnabled()
    workspace.loadBatchButton.click()
    qapp.processEvents()

    assert workspace.batchList.count() == 1
    assert workspace.positionContextLabel.isVisible()
    assert "实际开仓价" in workspace.positionContextLabel.text()
    assert not workspace.sourceLabel.isVisible()
    hold_index = workspace.judgmentBox.findData("HOLD")
    workspace.judgmentBox.setCurrentIndex(hold_index)
    workspace.saveButton.click()
    qapp.processEvents()

    assert not workspace.sourceLabel.isVisible()
    assert workspace.revealButton.isEnabled()
    workspace.revealButton.click()
    qapp.processEvents()

    assert workspace.sourceLabel.isVisible()
    assert "实际全量平仓" in workspace.sourceLabel.text()
    assert workspace.relabelButton.isEnabled()

    workspace.close()
    workspace.deleteLater()
    qapp.processEvents()


def test_exit_candidate_audit_labels_position_distance_separately():
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    workspace = EntryBlindReviewWorkspace(
        controller=_EntryController(),
        exit_controller=ExitBlindReviewController(object()),
        language="zh_CN",
    )
    workspace.set_entry_mode_active(False)
    audit = RevealedCandidateAudit(
        similarity=81.25,
        group_distances=tuple(float(index) / 100 for index in range(12)),
        references=tuple(
            RevealedCandidateReference(
                decision_event_id=f"exit_reference_{index}",
                episode_id=f"holding_episode_{index}",
                similarity=85.0 - index,
            )
            for index in range(3)
        ),
        enqueue_reason="STRUCTURAL_SIMILARITY",
        selection_reason="HIGH_SIMILARITY",
        research_target="EXIT",
        position_distance=0.375,
    )

    try:
        workspace._render_candidate_audit(audit)

        text = workspace.candidateAuditLabel.text()
        assert "持仓状态 0.3750" in text
        assert "持仓片段" in text
        assert "高相似" in text
    finally:
        workspace.close()
        workspace.deleteLater()
        qapp.processEvents()
