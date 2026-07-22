from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

try:
    from i18n import tr
    from research.entry_blind_review import (
        BlindJudgmentInput,
        BlindReviewBatch,
        BlindedKline,
        BlindedTimeframeChart,
        ENTRY_REASONS_BY_LABEL,
        EntryJudgmentLabel,
        EntryJudgmentVersion,
        RevealedCandidateAudit,
        RevealedOriginalEntryAction,
    )
    from research.exit_blind_review import (
        ExitBlindJudgmentInput,
        EXIT_REASONS_BY_LABEL,
        ExitJudgmentVersion,
        RevealedOriginalExitAction,
    )
    from ui_style import SPACING, WORKSPACE_SIZES, normalize_theme_settings
    from views.candlestick_item import CandlestickItem
    from views.volume_item import VolumeItem
    from views.main_window_presentation import (
        apply_role_button_styles,
        apply_themed_input_styles,
    )
    from views.plot_lifecycle import (
        close_parent_owned_graphics_view,
        prepare_plot_for_shutdown,
    )
    from views.widget_effects import apply_role_button_shadows
except ImportError:  # pragma: no cover - package import path
    from ..i18n import tr
    from ..research.entry_blind_review import (
        BlindJudgmentInput,
        BlindReviewBatch,
        BlindedKline,
        BlindedTimeframeChart,
        ENTRY_REASONS_BY_LABEL,
        EntryJudgmentLabel,
        EntryJudgmentVersion,
        RevealedCandidateAudit,
        RevealedOriginalEntryAction,
    )
    from ..research.exit_blind_review import (
        ExitBlindJudgmentInput,
        EXIT_REASONS_BY_LABEL,
        ExitJudgmentVersion,
        RevealedOriginalExitAction,
    )
    from ..ui_style import SPACING, WORKSPACE_SIZES, normalize_theme_settings
    from .candlestick_item import CandlestickItem
    from .volume_item import VolumeItem
    from .main_window_presentation import (
        apply_role_button_styles,
        apply_themed_input_styles,
    )
    from .plot_lifecycle import (
        close_parent_owned_graphics_view,
        prepare_plot_for_shutdown,
    )
    from .widget_effects import apply_role_button_shadows


_DEFAULT_REASONS_BY_KIND = {
    "entry": {
        label.value: reasons
        for label, reasons in ENTRY_REASONS_BY_LABEL.items()
    },
    "exit": {
        label.value: reasons
        for label, reasons in EXIT_REASONS_BY_LABEL.items()
    },
}

JudgmentInput = BlindJudgmentInput | ExitBlindJudgmentInput
JudgmentVersion = EntryJudgmentVersion | ExitJudgmentVersion
RevealedOriginalAction = (
    RevealedOriginalEntryAction | RevealedOriginalExitAction
)
_BJT = ZoneInfo("Asia/Shanghai")


class _BlindedTimeAxis(pg.AxisItem):
    """Display blinded timestamps without exposing the concrete year."""

    def __init__(self) -> None:
        super().__init__(orientation="bottom")
        try:
            self.enableAutoSIPrefix(False)
        except Exception:
            pass

    def tickStrings(self, values, scale, spacing):
        labels: list[str] = []
        show_intraday = float(spacing or 0.0) < 86_400.0
        for value in values:
            try:
                point = datetime.fromtimestamp(
                    float(value) * float(scale),
                    UTC,
                ).astimezone(_BJT)
            except (OverflowError, OSError, ValueError):
                labels.append("")
                continue
            labels.append(
                point.strftime("%m-%d %H:%M")
                if show_intraday
                else point.strftime("%m-%d")
            )
        return labels


class _ManagedReviewPlotWidget(pg.PlotWidget):
    def __init__(
        self,
        parent: QtWidgets.QWidget | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(parent=parent, **kwargs)
        menu = self.plotItem.ctrlMenu
        menu.setParent(self)
        menu.hide()

    def shutdown(self) -> None:
        plot = self.plotItem
        if plot is None:
            return
        prepare_plot_for_shutdown(plot)
        plot.close()
        self.plotItem = None
        close_parent_owned_graphics_view(self)

    def close(self) -> bool:
        if self.plotItem is None:
            return bool(QtWidgets.QWidget.close(self))
        return bool(super().close())


class EntryReviewChartPane(QtWidgets.QFrame):
    crosshairMoved = QtCore.Signal(int)

    def __init__(
        self,
        *,
        language: str,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.language = language
        self.interval = ""
        self.cutoff_time_utc_ms = 0
        self.crosshair_time_utc_ms = 0
        self.bars: tuple[BlindedKline, ...] = ()
        self.setProperty("role", "statusBlock")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(
            SPACING["sm"],
            SPACING["sm"],
            SPACING["sm"],
            SPACING["sm"],
        )
        layout.setSpacing(SPACING["xs"])
        self.titleLabel = QtWidgets.QLabel()
        self.titleLabel.setProperty("role", "sectionTitle")
        self.emptyLabel = QtWidgets.QLabel()
        self.emptyLabel.setProperty("role", "mutedText")
        self.plot = _ManagedReviewPlotWidget(self)
        self.plot.setMinimumHeight(WORKSPACE_SIZES["blind_chart_min_height"])
        self.plot.setMouseEnabled(x=True, y=True)
        self.plot.hideButtons()
        self.volumePlot = _ManagedReviewPlotWidget(
            self,
            axisItems={"bottom": _BlindedTimeAxis()},
        )
        self.volumePlot.setMinimumHeight(
            WORKSPACE_SIZES["blind_volume_min_height"]
        )
        self.volumePlot.setMouseEnabled(x=True, y=True)
        self.volumePlot.setXLink(self.plot)
        self.plot.getPlotItem().hideAxis("bottom")
        self._show_auto_button()
        self.volumePlot.getPlotItem().autoBtn.clicked.connect(
            self._auto_scale_charts
        )
        self.candles = CandlestickItem()
        self.volumes = VolumeItem()
        self.plot.addItem(self.candles)
        self.volumePlot.addItem(self.volumes)
        self.cutoffLine = pg.InfiniteLine(angle=90)
        self.crosshairLine = pg.InfiniteLine(angle=90)
        self.volumeCutoffLine = pg.InfiniteLine(angle=90)
        self.volumeCrosshairLine = pg.InfiniteLine(angle=90)
        self.plot.addItem(self.cutoffLine)
        self.plot.addItem(self.crosshairLine)
        self.volumePlot.addItem(self.volumeCutoffLine)
        self.volumePlot.addItem(self.volumeCrosshairLine)
        self.plot.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self.volumePlot.scene().sigMouseMoved.connect(self._on_mouse_moved)
        layout.addWidget(self.titleLabel)
        layout.addWidget(self.emptyLabel)
        layout.addWidget(self.plot, stretch=3)
        layout.addWidget(self.volumePlot, stretch=1)
        self.retranslate_ui()
        self.apply_theme(None)

    def set_chart(self, chart: BlindedTimeframeChart) -> None:
        self.interval = chart.interval
        self.cutoff_time_utc_ms = int(chart.cutoff_time_utc_ms)
        self.crosshair_time_utc_ms = self.cutoff_time_utc_ms
        self.bars = tuple(chart.bars)
        self._render_bars()
        self.retranslate_ui()

    def append_revealed_bars(
        self,
        chart: BlindedTimeframeChart,
    ) -> None:
        by_open_time = {
            bar.open_time_utc_ms: bar
            for bar in (*self.bars, *chart.bars)
        }
        self.bars = tuple(
            by_open_time[key]
            for key in sorted(by_open_time)
        )
        self._render_bars()

    def move_crosshair(self, time_utc_ms: int) -> None:
        self.crosshair_time_utc_ms = int(time_utc_ms)
        value = self.crosshair_time_utc_ms / 1_000.0
        self.crosshairLine.setValue(value)
        self.volumeCrosshairLine.setValue(value)

    def _render_bars(self) -> None:
        if not self.bars:
            self.candles.set_data([], [], [], [], [])
            self.volumes.set_data([], [], [])
            self.emptyLabel.show()
        else:
            x = np.asarray(
                [bar.open_time_utc_ms / 1_000.0 for bar in self.bars],
                dtype=float,
            )
            width = self._bar_width_seconds()
            self.candles.set_data(
                x,
                [bar.open for bar in self.bars],
                [bar.high for bar in self.bars],
                [bar.low for bar in self.bars],
                [bar.close for bar in self.bars],
                width,
                data_version=(
                    self.interval,
                    len(self.bars),
                    self.bars[-1].open_time_utc_ms,
                ),
            )
            self.volumes.set_data(
                x,
                [bar.volume for bar in self.bars],
                [bar.close >= bar.open for bar in self.bars],
                width,
                data_version=(
                    self.interval,
                    len(self.bars),
                    self.bars[-1].open_time_utc_ms,
                ),
            )
            self._auto_scale_charts()
            self.emptyLabel.hide()
        cutoff_seconds = self.cutoff_time_utc_ms / 1_000.0
        self.cutoffLine.setValue(cutoff_seconds)
        self.volumeCutoffLine.setValue(cutoff_seconds)
        self.move_crosshair(self.crosshair_time_utc_ms)

    def _auto_scale_charts(self) -> None:
        if not self.bars:
            return
        width = self._bar_width_seconds()
        left = self.bars[0].open_time_utc_ms / 1_000.0 - width
        right = self.bars[-1].open_time_utc_ms / 1_000.0 + width
        self.plot.setXRange(left, right, padding=0.02)

        low = min(bar.low for bar in self.bars)
        high = max(bar.high for bar in self.bars)
        price_span = max(1e-6, high - low)
        self.plot.setYRange(
            low - price_span * 0.08,
            high + price_span * 0.08,
            padding=0.0,
        )

        volume_high = max(0.0, max(bar.volume for bar in self.bars))
        self.volumePlot.setYRange(
            0.0,
            max(1e-6, volume_high * 1.08),
            padding=0.0,
        )
        self._show_auto_button()

    def _show_auto_button(self) -> None:
        plot_item = self.volumePlot.getPlotItem()
        plot_item.mouseHovering = True
        plot_item.showButtons()
        plot_item.updateButtons()

    def _bar_width_seconds(self) -> float:
        if not self.bars:
            return 0.001
        return max(
            0.001,
            (self.bars[0].close_time_utc_ms - self.bars[0].open_time_utc_ms)
            / 1_000.0
            * 0.7,
        )

    def _on_mouse_moved(self, scene_position) -> None:
        point = self._map_scene_to_chart_point(scene_position)
        if point is None:
            return
        self.crosshairMoved.emit(round(point.x() * 1_000))

    def _map_scene_to_chart_point(self, scene_position: Any) -> Any | None:
        for chart in (self.plot, self.volumePlot):
            if chart.plotItem is None:
                continue
            view_box = chart.plotItem.vb
            if view_box.sceneBoundingRect().contains(scene_position):
                return view_box.mapSceneToView(scene_position)
        return None

    def retranslate_ui(self, language: str | None = None) -> None:
        if language is not None:
            self.language = language
        self.titleLabel.setText(
            tr("decision_research.entry_review.chart.title", self.language).format(
                interval=self.interval or "—"
            )
        )
        self.emptyLabel.setText(
            tr("decision_research.entry_review.chart.empty", self.language)
        )

    def apply_theme(self, theme: dict | None) -> None:
        settings = normalize_theme_settings(theme)
        self.plot.setBackground(settings["chart_bg"])
        self.volumePlot.setBackground(settings["chart_bg"])
        self.plot.showGrid(
            x=True,
            y=True,
            alpha=settings["grid_alpha"] / 100.0,
        )
        self.volumePlot.showGrid(
            x=True,
            y=True,
            alpha=settings["grid_alpha"] / 100.0,
        )
        for chart in (self.plot, self.volumePlot):
            for side in ("left", "bottom", "right", "top"):
                axis = chart.getPlotItem().getAxis(side)
                if axis is not None:
                    axis.setPen(pg.mkPen(settings["chart_axis"]))
                    axis.setTextPen(pg.mkPen(settings["chart_axis"]))
        self.candles.set_style(
            settings["chart_up"],
            settings["chart_down"],
            settings["chart_wick"],
        )
        self.volumes.set_style(
            settings["chart_volume_up"],
            settings["chart_volume_down"],
        )
        cutoff_pen = pg.mkPen(
            settings["warning"],
            style=QtCore.Qt.DashLine,
        )
        crosshair_pen = pg.mkPen(settings["chart_crosshair"])
        self.cutoffLine.setPen(cutoff_pen)
        self.volumeCutoffLine.setPen(cutoff_pen)
        self.crosshairLine.setPen(crosshair_pen)
        self.volumeCrosshairLine.setPen(crosshair_pen)

    def shutdown(self) -> None:
        try:
            self.plot.scene().sigMouseMoved.disconnect(self._on_mouse_moved)
        except (RuntimeError, TypeError):
            pass
        try:
            self.volumePlot.scene().sigMouseMoved.disconnect(
                self._on_mouse_moved
            )
        except (RuntimeError, TypeError):
            pass
        self.plot.shutdown()
        self.volumePlot.shutdown()


class EntryBlindReviewWorkspace(QtWidgets.QWidget):
    """Shared three-column entry/exit UI that consumes only blinded DTOs."""

    batchLoaded = QtCore.Signal(object)

    def __init__(
        self,
        *,
        controller: Any,
        exit_controller: Any | None = None,
        language: str = "zh_CN",
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._entry_controller = controller
        self._exit_controller = exit_controller
        self.controller = controller
        self._review_kind = "entry"
        self.language = language
        self._setup_version_id: str | None = None
        self._setup_version_label: str | None = None
        self._grouping_version_id: str | None = None
        self._current_item = None
        self._blind_judgment: JudgmentVersion | None = None
        self._revealed_original: RevealedOriginalAction | None = None
        self._candidate_audit: RevealedCandidateAudit | None = None
        self._batch_item_states: list[str] = []
        self._entry_mode_active = True
        self._status_key = "decision_research.entry_review.status.ready"
        self._status_params: dict[str, Any] = {}
        self._paused_status: tuple[str, dict[str, Any]] | None = None
        self._narrow_layout = False
        self._shutdown = False
        self.lastError: Exception | None = None
        self.chartPanes: list[EntryReviewChartPane] = []
        self._build_ui()
        self.retranslate_ui(language)
        self._sync_reason_choices()

    def set_entry_mode_active(self, active: bool) -> None:
        enabled = bool(active)
        if enabled == self._entry_mode_active:
            return
        self._entry_mode_active = enabled
        target_controller = (
            self._entry_controller if enabled else self._exit_controller
        )
        if target_controller is None:
            self._paused_status = (
                self._status_key,
                dict(self._status_params),
            )
            self.columnScroll.hide()
            self.loadBatchButton.setEnabled(False)
            self._set_status(
                "decision_research.entry_review.status.entry_only"
            )
            return
        self.controller = target_controller
        self._review_kind = str(
            getattr(target_controller, "review_kind", "entry" if enabled else "exit")
        )
        self.columnScroll.show()
        self.loadBatchButton.setEnabled(
            bool(self._setup_version_id and self._grouping_version_id)
        )
        key, params = (
            f"decision_research.{self._review_kind}_review.status.ready",
            {},
        )
        self._paused_status = None
        self.batchList.clear()
        self._batch_item_states = []
        self._clear_item()
        self._populate_judgment_labels()
        self.retranslate_ui()
        self._set_status(key, **params)

    def _tr(self, key: str) -> str:
        return tr(key, self.language)

    def _review_key(self, suffix: str) -> str:
        return f"decision_research.{self._review_kind}_review.{suffix}"

    def _populate_judgment_labels(self) -> None:
        if not hasattr(self, "judgmentBox"):
            return
        selected = self.judgmentBox.currentData()
        labels = tuple(
            str(label)
            for label in getattr(
                self.controller,
                "judgment_labels",
                tuple(label.value for label in EntryJudgmentLabel),
            )
        )
        blocker = QtCore.QSignalBlocker(self.judgmentBox)
        self.judgmentBox.clear()
        for label in labels:
            self.judgmentBox.addItem("", label)
        selected_index = self.judgmentBox.findData(selected)
        if selected_index >= 0:
            self.judgmentBox.setCurrentIndex(selected_index)
        blocker.unblock()

    def _set_status(self, key: str, **params: Any) -> None:
        self._status_key = key
        self._status_params = dict(params)
        self._render_status()

    def _render_status(self) -> None:
        self.statusLabel.setText(
            self._tr(self._status_key).format(**self._status_params)
        )

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SPACING["sm"])
        self.statusLabel = QtWidgets.QLabel()
        self.statusLabel.setProperty("role", "pillMuted")
        self.statusLabel.setWordWrap(True)
        status_row = QtWidgets.QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.addWidget(self.statusLabel, stretch=1)
        self.batchToggleButton = QtWidgets.QToolButton()
        self.batchToggleButton.setProperty("role", "secondaryButton")
        self.batchToggleButton.hide()
        self.batchToggleButton.clicked.connect(self._toggle_batch_panel)
        status_row.addWidget(self.batchToggleButton)
        root.addLayout(status_row)

        self.columnContent = QtWidgets.QWidget()
        columns = QtWidgets.QHBoxLayout(self.columnContent)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(SPACING["md"])

        self.batchPanel = QtWidgets.QFrame()
        self.batchPanel.setMinimumWidth(
            WORKSPACE_SIZES["blind_batch_min_width"]
        )
        self.batchPanel.setProperty("role", "workspaceToolbar")
        batch_layout = QtWidgets.QVBoxLayout(self.batchPanel)
        batch_layout.setContentsMargins(
            SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"]
        )
        self.batchTitle = QtWidgets.QLabel()
        self.batchTitle.setProperty("role", "sectionTitle")
        self.batchList = QtWidgets.QListWidget()
        self.batchList.currentRowChanged.connect(self._select_batch_item)
        self.loadBatchButton = QtWidgets.QPushButton()
        self.loadBatchButton.setProperty("role", "primaryButton")
        self.loadBatchButton.clicked.connect(self._load_batch)
        batch_layout.addWidget(self.batchTitle)
        batch_layout.addWidget(self.batchList, stretch=1)
        batch_layout.addWidget(self.loadBatchButton)

        self.chartPanel = QtWidgets.QFrame()
        self.chartPanel.setMinimumWidth(
            WORKSPACE_SIZES["blind_chart_column_min_width"]
        )
        self.chartPanel.setProperty("role", "workspaceToolbar")
        chart_layout = QtWidgets.QVBoxLayout(self.chartPanel)
        chart_layout.setContentsMargins(
            SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"]
        )
        chart_layout.setSpacing(SPACING["sm"])
        self.higherTimeframePanel = QtWidgets.QWidget()
        higher_layout = QtWidgets.QHBoxLayout(self.higherTimeframePanel)
        higher_layout.setContentsMargins(0, 0, 0, 0)
        higher_layout.setSpacing(SPACING["sm"])
        for index in range(3):
            pane = EntryReviewChartPane(language=self.language)
            pane.crosshairMoved.connect(self.move_linked_crosshair)
            self.chartPanes.append(pane)
            if index == 0:
                chart_layout.addWidget(pane, stretch=2)
            else:
                higher_layout.addWidget(pane, stretch=1)
        chart_layout.addWidget(self.higherTimeframePanel, stretch=1)

        self.formPanel = QtWidgets.QFrame()
        self.formPanel.setMinimumWidth(
            WORKSPACE_SIZES["blind_form_min_width"]
        )
        self.formPanel.setProperty("role", "workspaceToolbar")
        form_layout = QtWidgets.QVBoxLayout(self.formPanel)
        form_layout.setContentsMargins(
            SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"]
        )
        form_layout.setSpacing(SPACING["sm"])
        self.formTitle = QtWidgets.QLabel()
        self.formTitle.setProperty("role", "sectionTitle")
        self.setupVersionCaption = QtWidgets.QLabel()
        self.setupVersionCaption.setProperty("role", "mutedText")
        self.setupVersionLabel = QtWidgets.QLabel("—")
        self.setupVersionLabel.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse
        )
        self.blindJudgmentSummary = QtWidgets.QLabel()
        self.blindJudgmentSummary.setProperty("role", "pillMuted")
        self.blindJudgmentSummary.setWordWrap(True)
        self.blindJudgmentSummary.hide()
        self.positionContextLabel = QtWidgets.QLabel()
        self.positionContextLabel.setProperty("role", "statusBlock")
        self.positionContextLabel.setWordWrap(True)
        self.positionContextLabel.hide()
        self.candidateAuditLabel = QtWidgets.QLabel()
        self.candidateAuditLabel.setProperty("role", "statusBlock")
        self.candidateAuditLabel.setWordWrap(True)
        self.candidateAuditLabel.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse
        )
        self.candidateAuditLabel.hide()
        self.judgmentCaption = QtWidgets.QLabel()
        self.judgmentCaption.setProperty("role", "mutedText")
        self.judgmentBox = QtWidgets.QComboBox()
        self._populate_judgment_labels()
        self.judgmentBox.currentIndexChanged.connect(
            self._sync_reason_choices
        )
        self.reasonCaption = QtWidgets.QLabel()
        self.reasonCaption.setProperty("role", "mutedText")
        self.reasonBox = QtWidgets.QListWidget()
        self.reasonBox.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection
        )
        self.reasonBox.setMaximumHeight(
            WORKSPACE_SIZES["blind_reason_max_height"]
        )
        self.confidenceCaption = QtWidgets.QLabel()
        self.confidenceCaption.setProperty("role", "mutedText")
        self.confidenceSpin = QtWidgets.QSpinBox()
        self.confidenceSpin.setRange(1, 5)
        self.confidenceSpin.setValue(3)
        self.noteCaption = QtWidgets.QLabel()
        self.noteCaption.setProperty("role", "mutedText")
        self.noteEdit = QtWidgets.QPlainTextEdit()
        self.noteEdit.setMinimumHeight(
            WORKSPACE_SIZES["blind_note_min_height"]
        )
        self.saveButton = QtWidgets.QPushButton()
        self.saveButton.setProperty("role", "primaryButton")
        self.saveButton.clicked.connect(self._save_blind_judgment)
        self.revealButton = QtWidgets.QPushButton()
        self.revealButton.setProperty("role", "secondaryButton")
        self.revealButton.setEnabled(False)
        self.revealButton.clicked.connect(self._reveal)
        self.relabelButton = QtWidgets.QPushButton()
        self.relabelButton.setProperty("role", "secondaryButton")
        self.relabelButton.setEnabled(False)
        self.relabelButton.clicked.connect(self._relabel)
        self.sourceLabel = QtWidgets.QLabel()
        self.sourceLabel.setProperty("role", "pillWarning")
        self.sourceLabel.setWordWrap(True)
        self.sourceLabel.hide()
        for widget in (
            self.formTitle,
            self.setupVersionCaption,
            self.setupVersionLabel,
            self.positionContextLabel,
            self.blindJudgmentSummary,
            self.candidateAuditLabel,
            self.judgmentCaption,
            self.judgmentBox,
            self.reasonCaption,
            self.reasonBox,
            self.confidenceCaption,
            self.confidenceSpin,
            self.noteCaption,
            self.noteEdit,
            self.saveButton,
            self.revealButton,
            self.relabelButton,
            self.sourceLabel,
        ):
            form_layout.addWidget(widget)
        form_layout.addStretch(1)

        columns.addWidget(self.batchPanel, stretch=2)
        columns.addWidget(self.chartPanel, stretch=5)
        columns.addWidget(self.formPanel, stretch=3)
        self.columnContent.setMinimumWidth(
            WORKSPACE_SIZES["blind_columns_content_min_width"]
        )
        self.columnScroll = QtWidgets.QScrollArea()
        self.columnScroll.setWidgetResizable(True)
        self.columnScroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.columnScroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarAsNeeded
        )
        self.columnScroll.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarAlwaysOff
        )
        self.columnScroll.setWidget(self.columnContent)
        self.columnScroll.setMinimumHeight(
            self.columnContent.minimumSizeHint().height()
            + self.columnScroll.horizontalScrollBar().sizeHint().height()
        )
        root.addWidget(self.columnScroll, stretch=1)

    def _toggle_batch_panel(self) -> None:
        self.batchPanel.setVisible(self.batchPanel.isHidden())
        self._update_batch_toggle_text()

    def _update_batch_toggle_text(self) -> None:
        action = "hide" if self.batchPanel.isVisible() else "show"
        self.batchToggleButton.setText(
            self._tr(
                self._review_key(f"batch.toggle.{action}")
            )
        )

    def _set_narrow_layout(self, narrow: bool) -> None:
        if narrow == self._narrow_layout:
            return
        self._narrow_layout = narrow
        self.batchToggleButton.setVisible(narrow)
        self.batchPanel.setVisible(not narrow)
        self._update_batch_toggle_text()

    def set_research_context(
        self,
        *,
        setup_version_id: str | None,
        grouping_version_id: str | None,
        setup_version_label: str | None = None,
    ) -> None:
        if (
            setup_version_id == self._setup_version_id
            and grouping_version_id == self._grouping_version_id
            and setup_version_label == self._setup_version_label
        ):
            return
        self._setup_version_id = setup_version_id
        self._setup_version_label = setup_version_label
        self._grouping_version_id = grouping_version_id
        self.setupVersionLabel.setText(setup_version_label or "—")
        self.loadBatchButton.setEnabled(
            bool(
                setup_version_id
                and grouping_version_id
                and (
                    self._entry_mode_active
                    or self._exit_controller is not None
                )
            )
        )
        self.batchList.clear()
        self._batch_item_states = []
        self._clear_item()

    @QtCore.Slot()
    def _load_batch(self) -> None:
        if not self._setup_version_id or not self._grouping_version_id:
            self._set_status(
                self._review_key("status.context_missing")
            )
            return
        try:
            batch = self.controller.load_batch(
                setup_version_id=self._setup_version_id,
                grouping_version_id=self._grouping_version_id,
            )
        except Exception as exc:
            self._show_failure(exc)
            return
        self.lastError = None
        self.batchList.clear()
        self._batch_item_states = ["pending"] * len(batch.items)
        self._render_batch_item_texts()
        if batch.items:
            self.batchList.setCurrentRow(0)
            self._set_status(
                self._review_key("status.loaded"),
                count=len(batch.items),
            )
        else:
            self._clear_item()
            self._set_status(
                self._review_key("status.empty")
            )
        self.batchLoaded.emit(batch)

    def load_existing_batch(self, batch: BlindReviewBatch) -> None:
        """Present a formal candidate batch without creating another queue."""

        loaded = self.controller.load_existing_batch(batch)
        self.batchList.clear()
        self._batch_item_states = ["pending"] * len(loaded.items)
        self._render_batch_item_texts()
        self._clear_item()
        self._set_status(
            self._review_key("status.loaded"),
            count=len(loaded.items),
        )
        self.batchLoaded.emit(loaded)

    @QtCore.Slot(int)
    def _select_batch_item(self, index: int) -> None:
        if index < 0:
            return
        try:
            item = self.controller.select_item(index)
        except Exception as exc:
            self._show_failure(exc)
            return
        self.lastError = None
        self._current_item = item
        self._revealed_original = None
        self._render_position_context(item)
        self._render_blind_judgment_summary(item.judgment)
        self._render_candidate_audit(
            self._candidate_audit_after_judgment()
            if item.judgment is not None
            else None
        )
        for pane, chart in zip(self.chartPanes, item.charts, strict=True):
            pane.set_chart(chart)
        self.move_linked_crosshair(item.decision_cutoff_utc_ms)
        self.saveButton.setEnabled(item.judgment is None)
        self.revealButton.setEnabled(item.judgment is not None)
        self.relabelButton.setEnabled(False)
        self.sourceLabel.hide()

    @QtCore.Slot(int)
    def move_linked_crosshair(self, time_utc_ms: int) -> None:
        for pane in self.chartPanes:
            pane.move_crosshair(time_utc_ms)

    def _judgment_input(self) -> JudgmentInput:
        values = {
            "label": str(self.judgmentBox.currentData()),
            "reason_tags": tuple(
                str(item.data(QtCore.Qt.UserRole))
                for item in self.reasonBox.selectedItems()
            ),
            "confidence": self.confidenceSpin.value(),
            "note": self.noteEdit.toPlainText(),
        }
        factory = getattr(self.controller, "make_judgment", None)
        return (
            factory(**values)
            if callable(factory)
            else BlindJudgmentInput(**values)
        )

    @QtCore.Slot()
    def _save_blind_judgment(self) -> None:
        try:
            saved = self.controller.save_blind_judgment(
                self._judgment_input()
            )
        except Exception as exc:
            self._show_failure(exc)
            return
        self.lastError = None
        self.saveButton.setEnabled(False)
        self.revealButton.setEnabled(True)
        self._render_blind_judgment_summary(saved)
        self._render_candidate_audit(self._candidate_audit_after_judgment())
        self._set_current_batch_item_state("judged")
        self._set_status(
            self._review_key("status.saved")
        )

    @QtCore.Slot()
    def _reveal(self) -> None:
        try:
            revealed = self.controller.reveal_current()
        except Exception as exc:
            self._show_failure(exc)
            return
        self.lastError = None
        self._revealed_original = revealed.original
        self._render_revealed_source()
        self._render_candidate_audit(
            getattr(revealed, "candidate_audit", None)
        )
        for pane, chart in zip(
            self.chartPanes,
            revealed.future_charts,
            strict=True,
        ):
            pane.append_revealed_bars(chart)
        self.revealButton.setEnabled(False)
        self.relabelButton.setEnabled(True)
        self._set_current_batch_item_state("revealed")
        self._set_status(
            self._review_key("status.revealed")
        )

    @QtCore.Slot()
    def _relabel(self) -> None:
        try:
            self.controller.relabel_current(self._judgment_input())
        except Exception as exc:
            self._show_failure(exc)
            return
        self.lastError = None
        self._set_status(
            self._review_key("status.relabelled")
        )

    def _clear_item(self) -> None:
        self._current_item = None
        self._revealed_original = None
        self._candidate_audit = None
        self.positionContextLabel.clear()
        self.positionContextLabel.hide()
        self._render_blind_judgment_summary(None)
        self._render_candidate_audit(None)
        for pane in self.chartPanes:
            pane.set_chart(
                BlindedTimeframeChart(
                    interval="",
                    cutoff_time_utc_ms=0,
                    bars=(),
                )
            )
        self.saveButton.setEnabled(False)
        self.revealButton.setEnabled(False)
        self.relabelButton.setEnabled(False)
        self.sourceLabel.hide()

    def _render_position_context(self, item: Any) -> None:
        position = getattr(item, "position", None)
        pressure = getattr(item, "account_pressure", None)
        if position is None or pressure is None:
            self.positionContextLabel.clear()
            self.positionContextLabel.hide()
            return
        link = self._tr(
            self._review_key(
                "setup_link."
                f"{str(getattr(item, 'setup_link_status', 'LINKED')).lower()}"
            )
        )
        self.positionContextLabel.setText(
            self._tr(self._review_key("position_summary")).format(
                position_id=position.anonymous_position_id,
                entry_price=self._format_optional_number(
                    position.actual_entry_price
                ),
                entry_atr=self._format_optional_number(
                    position.entry_atr20
                ),
                take_profit=self._format_risk_level(
                    position.take_profit_status,
                    position.take_profit_price,
                ),
                stop_loss=self._format_risk_level(
                    position.stop_loss_status,
                    position.stop_loss_price,
                ),
                open_positions=pressure.open_position_count,
                exposure=self._format_optional_number(
                    pressure.total_exposure_ratio
                ),
                drawdown=self._format_optional_number(
                    pressure.account_drawdown_pct
                ),
                setup_link=link,
            )
        )
        self.positionContextLabel.show()

    def _format_optional_number(self, value: Any) -> str:
        if value is None:
            return self._tr("decision_research.exit_review.value.missing")
        return f"{float(value):.4f}"

    def _format_risk_level(self, status: Any, price: Any) -> str:
        return self._tr(
            self._review_key(f"risk.{status.value.lower()}")
        ).format(price=self._format_optional_number(price))

    def _show_failure(self, error: Exception) -> None:
        self.lastError = error
        user_message_key = getattr(error, "user_message_key", None)
        self._set_status(
            str(user_message_key)
            if user_message_key
            else self._review_key("status.failed")
        )

    def _render_revealed_source(self) -> None:
        original = self._revealed_original
        if original is None:
            self.sourceLabel.clear()
            self.sourceLabel.hide()
            return
        source = self._tr(
            self._review_key(
                f"source.{original.seed_source.value.lower()}"
            )
        )
        action = self._tr(
            self._review_key(
                f"action.{original.original_action.value.lower()}"
            )
        )
        approximation = (
            self._tr(self._review_key("approximate"))
            if original.timing_approximate
            else self._tr(self._review_key("exact"))
        )
        pnl = getattr(original, "realized_pnl_quote", None)
        pnl_suffix = (
            self._tr(self._review_key("realized_pnl")).format(
                pnl=f"{float(pnl):.4f}"
            )
            if pnl is not None
            else ""
        )
        self.sourceLabel.setText(
            self._tr(self._review_key("source_summary")).format(
                source=source,
                action=action,
                approximation=approximation,
                pnl_suffix=pnl_suffix,
            )
        )
        self.sourceLabel.show()

    def _candidate_audit_after_judgment(self) -> RevealedCandidateAudit | None:
        load = getattr(self.controller, "candidate_audit_current", None)
        return load() if callable(load) else None

    def _render_candidate_audit(
        self,
        audit: RevealedCandidateAudit | None,
    ) -> None:
        self._candidate_audit = audit
        if audit is None:
            self.candidateAuditLabel.clear()
            self.candidateAuditLabel.hide()
            return
        group_names = tuple(
            self._tr(f"decision_research.similarity.group.{name}")
            for name in (
                "price_path",
                "candle_shape",
                "trend_volatility",
                "trading_activity",
            )
        )
        roles = tuple(
            self._tr(f"decision_research.similarity.timeframe.{role}")
            for role in ("decision", "context_one", "context_two")
        )
        group_parts = []
        for index, distance in enumerate(audit.group_distances):
            role = roles[min(index // len(group_names), len(roles) - 1)]
            group = group_names[index % len(group_names)]
            group_parts.append(f"{role}/{group} {distance:.4f}")
        target = str(getattr(audit, "research_target", "ENTRY")).lower()
        position_distance = getattr(audit, "position_distance", None)
        if position_distance is not None:
            group_parts.append(
                self._tr(
                    "decision_research.exit_review.candidate.position_distance"
                ).format(distance=f"{float(position_distance):.4f}")
            )
        separator = self._tr("decision_research.list_separator")
        references = separator.join(
            self._tr(
                f"decision_research.{target}_review.candidate.reference"
            ).format(
                event_id=item.decision_event_id,
                episode_id=item.episode_id,
                similarity=f"{item.similarity:.2f}",
            )
            for item in audit.references
        )
        selection = self._tr(
            "decision_research.entry_review.candidate.selection."
            f"{audit.selection_reason.lower()}"
        )
        enqueue = self._tr(
            "decision_research.entry_review.candidate.enqueue."
            f"{audit.enqueue_reason.lower()}"
        )
        self.candidateAuditLabel.setText(
            self._tr(
                f"decision_research.{target}_review.candidate.audit"
            ).format(
                similarity=f"{audit.similarity:.2f}",
                groups=separator.join(group_parts),
                references=references,
                enqueue=enqueue,
                selection=selection,
            )
        )
        self.candidateAuditLabel.show()

    def _sync_reason_choices(self, _index: int = -1) -> None:
        raw = self.judgmentBox.currentData()
        if not raw:
            return
        selected = {
            str(item.data(QtCore.Qt.UserRole))
            for item in self.reasonBox.selectedItems()
        }
        reason_map = getattr(
            self.controller,
            "reason_tags_by_label",
            _DEFAULT_REASONS_BY_KIND[self._review_kind],
        )
        reasons = tuple(reason_map[str(raw)])
        blocker = QtCore.QSignalBlocker(self.reasonBox)
        self.reasonBox.clear()
        for reason in reasons:
            item = QtWidgets.QListWidgetItem(
                self._tr(
                    self._review_key(f"reason.{reason}")
                )
            )
            item.setData(QtCore.Qt.UserRole, reason)
            self.reasonBox.addItem(item)
            item.setSelected(reason in selected)
        if not self.reasonBox.selectedItems() and self.reasonBox.count():
            self.reasonBox.item(0).setSelected(True)
        blocker.unblock()

    def _render_blind_judgment_summary(
        self,
        judgment: JudgmentVersion | None,
    ) -> None:
        self._blind_judgment = judgment
        if judgment is None:
            self.blindJudgmentSummary.clear()
            self.blindJudgmentSummary.hide()
            return
        label = self._tr(
            self._review_key(f"label.{judgment.label.value.lower()}")
        )
        reasons = self._tr("decision_research.list_separator").join(
            self._tr(self._review_key(f"reason.{reason}"))
            for reason in judgment.reason_tags
        )
        note_suffix = (
            self._tr(
                self._review_key("blind_summary.note")
            ).format(note=judgment.note)
            if judgment.note
            else ""
        )
        self.blindJudgmentSummary.setText(
            self._tr(
                self._review_key("blind_summary")
            ).format(
                label=label,
                confidence=judgment.confidence,
                reasons=reasons,
                note_suffix=note_suffix,
            )
        )
        self.blindJudgmentSummary.show()

    def _set_current_batch_item_state(self, state: str) -> None:
        row = self.batchList.currentRow()
        if row < 0 or row >= len(self._batch_item_states):
            return
        self._batch_item_states[row] = state
        self._render_batch_item_texts()

    def _render_batch_item_texts(self) -> None:
        for index, state in enumerate(self._batch_item_states):
            text = self._tr(
                self._review_key(f"item.{state}")
            ).format(number=index + 1)
            if index < self.batchList.count():
                self.batchList.item(index).setText(text)
            else:
                self.batchList.addItem(text)

    def retranslate_ui(self, language: str | None = None) -> None:
        if language is not None:
            self.language = language
        self.batchTitle.setText(
            self._tr(self._review_key("batch.title"))
        )
        self.loadBatchButton.setText(
            self._tr(self._review_key("batch.load"))
        )
        self._update_batch_toggle_text()
        self.formTitle.setText(
            self._tr(self._review_key("form.title"))
        )
        self.setupVersionCaption.setText(
            self._tr(self._review_key("form.setup_version"))
        )
        self.judgmentCaption.setText(
            self._tr(self._review_key("form.judgment"))
        )
        self.reasonCaption.setText(
            self._tr(self._review_key("form.reason"))
        )
        self.confidenceCaption.setText(
            self._tr(self._review_key("form.confidence"))
        )
        self.noteCaption.setText(
            self._tr(self._review_key("form.note"))
        )
        self.saveButton.setText(
            self._tr(self._review_key("form.save"))
        )
        self.revealButton.setText(
            self._tr(self._review_key("form.reveal"))
        )
        self.relabelButton.setText(
            self._tr(self._review_key("form.relabel"))
        )
        for index in range(self.judgmentBox.count()):
            label = str(self.judgmentBox.itemData(index)).lower()
            self.judgmentBox.setItemText(
                index,
                self._tr(
                    self._review_key(f"label.{label}")
                ),
            )
        for pane in self.chartPanes:
            pane.retranslate_ui(self.language)
        self._sync_reason_choices()
        self._render_blind_judgment_summary(self._blind_judgment)
        self._render_candidate_audit(self._candidate_audit)
        self._render_revealed_source()
        if self._current_item is not None:
            self._render_position_context(self._current_item)
        self._render_batch_item_texts()
        self._render_status()

    def apply_theme(self, theme: dict | None) -> None:
        for pane in self.chartPanes:
            pane.apply_theme(theme)
        apply_role_button_styles(self, theme)
        apply_themed_input_styles(self, theme)
        apply_role_button_shadows(self)

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        for pane in self.chartPanes:
            pane.shutdown()

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._set_narrow_layout(event.size().width() < 900)


__all__ = [
    "EntryBlindReviewWorkspace",
    "EntryReviewChartPane",
]
