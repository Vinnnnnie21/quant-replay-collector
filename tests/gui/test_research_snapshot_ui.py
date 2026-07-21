from __future__ import annotations

import pytest


QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from views.decision_research_workspace import DecisionResearchWorkspace
from views.research_snapshot_workspace import ResearchSnapshotWorkspace


def test_version_report_distinguishes_draft_from_published_and_preserves_version():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    workspace = DecisionResearchWorkspace(language="zh_CN")
    try:
        page = workspace.stepPages["version_report"]
        assert isinstance(page, ResearchSnapshotWorkspace)

        page.render_draft(
            content_hash="a" * 64,
            summary_zh="当前草稿包含最新数据。",
        )
        page.render_published_versions(
            (("snapshot-old", "2026-02-02T00:00:00+00:00"),)
        )
        page.viewTabs.setCurrentIndex(1)
        selected_before = page.publishedVersionBox.currentData()
        page.mark_new_evidence()

        assert page.viewTabs.tabText(0) == "当前草稿"
        assert page.viewTabs.tabText(1) == "已发布版本"
        assert selected_before == "snapshot-old"
        assert page.publishedVersionBox.currentData() == selected_before
        assert "创建新版本" in page.newEvidenceLabel.text()
        assert page.actionButton.text() == "发布研究快照"
    finally:
        workspace.close()
        app.processEvents()


def test_publish_button_emits_workspace_request_without_doing_widget_io():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    workspace = DecisionResearchWorkspace(language="zh_CN")
    requested: list[bool] = []
    try:
        workspace.snapshotPublishRequested.connect(
            lambda: requested.append(True)
        )
        page = workspace.researchSnapshotWorkspace
        page.render_draft(
            content_hash="b" * 64,
            summary_zh="可以发布的当前草稿。",
        )

        page.actionButton.click()

        assert requested == [True]
    finally:
        workspace.close()
        app.processEvents()


def test_snapshot_cancel_button_emits_dedicated_workspace_request():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    workspace = DecisionResearchWorkspace(language="zh_CN")
    requested = []
    try:
        workspace.snapshotCancelRequested.connect(
            lambda: requested.append(True)
        )
        page = workspace.researchSnapshotWorkspace
        page.render_draft(
            content_hash="e" * 64,
            summary_zh="可取消的报告草稿。",
        )
        page.begin_publish("正在生成中文研究报告")

        page.cancelButton.click()

        assert requested == [True]
    finally:
        workspace.close()
        app.processEvents()


def test_verified_published_report_can_be_rendered_without_mutating_draft():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    page = ResearchSnapshotWorkspace(language="zh_CN")
    try:
        page.render_draft(
            content_hash="c" * 64,
            summary_zh="仍可刷新的草稿。",
        )
        page.render_published_versions(
            (("snapshot-v1", "2026-02-02T00:00:00+00:00"),)
        )

        page.render_published_snapshot(
            snapshot_id="snapshot-v1",
            report_markdown="# 已核验报告\n\n证据不足也保留。",
        )

        assert page.viewTabs.currentIndex() == 1
        assert page.publishedReport.toPlainText().startswith("# 已核验报告")
        assert "仍可刷新的草稿" in page.draftSummary.toPlainText()
    finally:
        page.close()
        app.processEvents()


def test_published_version_selector_requests_the_chosen_immutable_version():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    page = ResearchSnapshotWorkspace(language="zh_CN")
    requested = []
    page.publishedVersionRequested.connect(requested.append)
    try:
        page.render_published_versions(
            (
                ("snapshot-v1", "2026-02-02T00:00:00+00:00"),
                ("snapshot-v2", "2026-02-03T00:00:00+00:00"),
            )
        )

        page.publishedVersionBox.activated.emit(1)

        assert requested == ["snapshot-v2"]
    finally:
        page.close()
        app.processEvents()


def test_snapshot_publish_progress_exposes_cooperative_cancel_without_blocking_page():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    page = ResearchSnapshotWorkspace(language="zh_CN")
    cancelled = []
    page.cancelRequested.connect(lambda: cancelled.append(True))
    try:
        page.render_draft(
            content_hash="d" * 64,
            summary_zh="当前草稿可发布。",
        )

        page.begin_publish("正在生成中文研究报告")

        assert page.actionButton.isEnabled() is False
        assert page.cancelButton.isHidden() is False
        assert "正在生成" in page.gateHint.text()
        page.cancelButton.click()
        assert cancelled == [True]

        page.render_publish_cancelled()
        assert page.actionButton.isEnabled() is True
        assert page.cancelButton.isHidden() is True
    finally:
        page.close()
        app.processEvents()
