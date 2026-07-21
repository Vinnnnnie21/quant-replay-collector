from __future__ import annotations

from collections.abc import Iterable

from PySide6 import QtCore, QtWidgets

try:
    from i18n import tr
    from services.ui_message_localizer import sanitize_worker_error_detail
    from ui_style import SPACING
    from views.main_window_presentation import (
        apply_role_button_styles,
        apply_themed_input_styles,
    )
    from views.widget_effects import apply_role_button_shadows
except ImportError:  # pragma: no cover - package import path
    from ..i18n import tr
    from ..services.ui_message_localizer import sanitize_worker_error_detail
    from ..ui_style import SPACING
    from .main_window_presentation import (
        apply_role_button_styles,
        apply_themed_input_styles,
    )
    from .widget_effects import apply_role_button_shadows


class ResearchSnapshotWorkspace(QtWidgets.QFrame):
    """Present mutable draft state separately from immutable publications."""

    publishRequested = QtCore.Signal()
    cancelRequested = QtCore.Signal()
    publishedVersionRequested = QtCore.Signal(str)

    def __init__(
        self,
        *,
        language: str = "zh_CN",
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.language = language
        self._draft_hash: str | None = None
        self._draft_summary = ""
        self._build_ui()
        self.retranslate_ui(language)

    def _tr(self, key: str) -> str:
        return tr(key, self.language)

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING["md"])

        self.viewTabs = QtWidgets.QTabWidget()
        self.draftPage = QtWidgets.QWidget()
        draft_layout = QtWidgets.QVBoxLayout(self.draftPage)
        draft_layout.setContentsMargins(
            SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"]
        )
        draft_layout.setSpacing(SPACING["sm"])
        self.emptyState = QtWidgets.QFrame()
        self.emptyState.setProperty("role", "emptyState")
        empty_layout = QtWidgets.QVBoxLayout(self.emptyState)
        self.emptyTitle = QtWidgets.QLabel()
        self.emptyTitle.setProperty("role", "emptyTitle")
        self.emptyTitle.setAlignment(QtCore.Qt.AlignCenter)
        self.emptyBody = QtWidgets.QLabel()
        self.emptyBody.setProperty("role", "emptyText")
        self.emptyBody.setAlignment(QtCore.Qt.AlignCenter)
        self.emptyBody.setWordWrap(True)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.emptyTitle)
        empty_layout.addWidget(self.emptyBody)
        empty_layout.addStretch(1)
        draft_layout.addWidget(self.emptyState, stretch=1)
        self.draftSummary = QtWidgets.QPlainTextEdit()
        self.draftSummary.setReadOnly(True)
        self.draftSummary.hide()
        draft_layout.addWidget(self.draftSummary, stretch=1)

        self.publishedPage = QtWidgets.QWidget()
        published_layout = QtWidgets.QVBoxLayout(self.publishedPage)
        published_layout.setContentsMargins(
            SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"]
        )
        published_layout.setSpacing(SPACING["sm"])
        self.publishedLabel = QtWidgets.QLabel()
        self.publishedLabel.setProperty("role", "sectionTitle")
        self.publishedVersionBox = QtWidgets.QComboBox()
        self.publishedVersionBox.activated.connect(
            self._request_selected_published_version
        )
        self.publishedHint = QtWidgets.QLabel()
        self.publishedHint.setProperty("role", "mutedText")
        self.publishedHint.setWordWrap(True)
        self.publishedReport = QtWidgets.QPlainTextEdit()
        self.publishedReport.setReadOnly(True)
        published_layout.addWidget(self.publishedLabel)
        published_layout.addWidget(self.publishedVersionBox)
        published_layout.addWidget(self.publishedHint)
        published_layout.addWidget(self.publishedReport, stretch=1)

        self.viewTabs.addTab(self.draftPage, "")
        self.viewTabs.addTab(self.publishedPage, "")
        layout.addWidget(self.viewTabs, stretch=1)

        self.newEvidenceLabel = QtWidgets.QLabel()
        self.newEvidenceLabel.setProperty("role", "pillWarning")
        self.newEvidenceLabel.setWordWrap(True)
        self.newEvidenceLabel.hide()
        layout.addWidget(self.newEvidenceLabel)

        action_row = QtWidgets.QHBoxLayout()
        self.gateHint = QtWidgets.QLabel()
        self.gateHint.setProperty("role", "pillMuted")
        self.gateHint.setWordWrap(True)
        self.actionButton = QtWidgets.QPushButton()
        self.actionButton.setProperty("role", "primaryButton")
        self.actionButton.setEnabled(False)
        self.actionButton.clicked.connect(self.publishRequested)
        self.cancelButton = QtWidgets.QPushButton()
        self.cancelButton.setProperty("role", "secondaryButton")
        self.cancelButton.clicked.connect(self.cancelRequested)
        self.cancelButton.hide()
        action_row.addWidget(self.gateHint, stretch=1)
        action_row.addWidget(self.cancelButton)
        action_row.addWidget(self.actionButton)
        layout.addLayout(action_row)

    @QtCore.Slot(int)
    def _request_selected_published_version(self, index: int) -> None:
        snapshot_id = self.publishedVersionBox.itemData(index)
        if snapshot_id:
            self.publishedVersionRequested.emit(str(snapshot_id))

    def render_draft(self, *, content_hash: str, summary_zh: str) -> None:
        self._draft_hash = str(content_hash)
        self._draft_summary = str(summary_zh)
        self.emptyState.hide()
        self.draftSummary.setPlainText(
            self._tr("decision_research.snapshot.draft_summary").format(
                summary=self._draft_summary,
                content_hash=self._draft_hash,
            )
        )
        self.draftSummary.show()
        self.actionButton.setEnabled(True)
        self.gateHint.setText(
            self._tr("decision_research.snapshot.publish_ready")
        )

    def render_published_versions(
        self,
        versions: Iterable[tuple[str, str]],
    ) -> None:
        selected = self.publishedVersionBox.currentData()
        self.publishedVersionBox.clear()
        for snapshot_id, created_at in versions:
            self.publishedVersionBox.addItem(
                f"{snapshot_id} · {created_at}",
                snapshot_id,
            )
        if selected is not None:
            index = self.publishedVersionBox.findData(selected)
            if index >= 0:
                self.publishedVersionBox.setCurrentIndex(index)

    def mark_new_evidence(self) -> None:
        self.newEvidenceLabel.setText(
            self._tr("decision_research.snapshot.new_evidence")
        )
        self.newEvidenceLabel.show()

    def render_published_snapshot(
        self,
        *,
        snapshot_id: str,
        report_markdown: str,
    ) -> None:
        index = self.publishedVersionBox.findData(snapshot_id)
        if index < 0:
            raise ValueError("published snapshot is not present in the version list")
        self.publishedVersionBox.setCurrentIndex(index)
        self.publishedReport.setPlainText(report_markdown)
        self.viewTabs.setCurrentIndex(1)
        self.actionButton.setEnabled(self._draft_hash is not None)
        self.cancelButton.hide()
        self.newEvidenceLabel.hide()
        self.gateHint.setText(
            self._tr("decision_research.snapshot.publish_ready")
        )

    def render_publish_error(self, message: str) -> None:
        self.actionButton.setEnabled(self._draft_hash is not None)
        self.cancelButton.hide()
        self.gateHint.setText(
            self._tr("decision_research.snapshot.publish_failed").format(
                error=sanitize_worker_error_detail(message)
            )
        )

    def begin_publish(self, message: str) -> None:
        self.actionButton.setEnabled(False)
        self.cancelButton.show()
        self.gateHint.setText(str(message))

    def render_publish_cancelled(self) -> None:
        self.actionButton.setEnabled(self._draft_hash is not None)
        self.cancelButton.hide()
        self.gateHint.setText(
            self._tr("decision_research.snapshot.publish_cancelled")
        )

    def retranslate_ui(self, language: str | None = None) -> None:
        if language is not None:
            self.language = language
        self.viewTabs.setTabText(
            0, self._tr("decision_research.snapshot.tab.draft")
        )
        self.viewTabs.setTabText(
            1, self._tr("decision_research.snapshot.tab.published")
        )
        self.emptyTitle.setText(
            self._tr("decision_research.snapshot.empty_title")
        )
        self.emptyBody.setText(
            self._tr("decision_research.snapshot.empty_body")
        )
        self.publishedLabel.setText(
            self._tr("decision_research.snapshot.published_title")
        )
        self.publishedHint.setText(
            self._tr("decision_research.snapshot.published_hint")
        )
        self.actionButton.setText(
            self._tr("decision_research.snapshot.publish")
        )
        self.cancelButton.setText(
            self._tr("decision_research.snapshot.cancel")
        )
        if self._draft_hash is None:
            self.gateHint.setText(
                self._tr("decision_research.snapshot.draft_required")
            )
        else:
            self.render_draft(
                content_hash=self._draft_hash,
                summary_zh=self._draft_summary,
            )
        if self.newEvidenceLabel.isVisible():
            self.mark_new_evidence()

    def apply_theme(self, theme: dict) -> None:
        apply_role_button_styles(self, theme)
        apply_themed_input_styles(self, theme)
        apply_role_button_shadows(self)


__all__ = ["ResearchSnapshotWorkspace"]
