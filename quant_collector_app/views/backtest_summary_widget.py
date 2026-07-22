from __future__ import annotations

from typing import Callable

from PySide6 import QtCore, QtGui, QtWidgets

try:
    from app_i18n import tr
    from presenters.backtest_result_display import (
        BacktestSummaryModel,
        build_backtest_summary_model,
    )
    from ui_style import SPACING, normalize_theme_settings
except ImportError:  # pragma: no cover - package import path
    from ..app_i18n import tr
    from ..presenters.backtest_result_display import (
        BacktestSummaryModel,
        build_backtest_summary_model,
    )
    from ..ui_style import SPACING, normalize_theme_settings


class BacktestSummaryWidget(QtWidgets.QFrame):
    def __init__(
        self,
        *,
        language_provider: Callable[[], str],
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._language_provider = language_provider
        self._theme = normalize_theme_settings(None)
        self._last_summary: dict | None = None
        self.setProperty("role", "statusBlock")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(SPACING["sm"], SPACING["sm"], SPACING["sm"], SPACING["sm"])
        layout.setSpacing(SPACING["xs"])

        self.titleLabel = QtWidgets.QLabel()
        self.titleLabel.setProperty("role", "sectionTitle")
        title_font = self.titleLabel.font()
        title_font.setBold(True)
        self.titleLabel.setFont(title_font)

        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(2)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(150)

        layout.addWidget(self.titleLabel)
        layout.addWidget(self.table)
        self.retranslate_ui()
        self.apply_theme(None)

    def set_summary(self, summary: dict | None) -> None:
        self._last_summary = dict(summary or {})
        self.set_model(
            build_backtest_summary_model(
                self._last_summary,
                translator=lambda key: tr(key, self._language_provider()),
            )
        )

    def set_model(self, model: BacktestSummaryModel) -> None:
        self.table.setRowCount(len(model.rows))
        for row_index, row in enumerate(model.rows):
            label_item = QtWidgets.QTableWidgetItem(row.label)
            label_item.setData(QtCore.Qt.UserRole, row.key)
            value_item = QtWidgets.QTableWidgetItem(row.value)
            value_item.setData(QtCore.Qt.UserRole, row.key)
            value_item.setForeground(QtGui.QBrush(QtGui.QColor(self._tone_color(row.tone))))
            self.table.setItem(row_index, 0, label_item)
            self.table.setItem(row_index, 1, value_item)
        self.table.resizeColumnsToContents()

    def clear(self) -> None:
        self._last_summary = None
        self.table.setRowCount(0)

    def retranslate_ui(self) -> None:
        language = self._language_provider()
        self.titleLabel.setText(tr("backtest.summary_table.title", language))
        self.table.setHorizontalHeaderLabels(
            [
                tr("backtest.summary_table.metric", language),
                tr("backtest.summary_table.value", language),
            ]
        )
        if self._last_summary is not None:
            self.set_summary(self._last_summary)

    def apply_theme(self, theme: dict | None) -> None:
        self._theme = normalize_theme_settings(theme)
        self.titleLabel.setStyleSheet(
            f"color: {self._theme['text_primary']}; font-weight: 700;"
        )
        self.table.setStyleSheet(
            f"""
            QTableWidget {{
                background-color: {self._theme['input_bg']};
                color: {self._theme['text_primary']};
                gridline-color: {self._theme['divider']};
                border: 1px solid {self._theme['border_default']};
                border-radius: 6px;
                selection-background-color: {self._theme['selection']};
                selection-color: {self._theme['text_primary']};
                font-size: 13px;
            }}
            QHeaderView::section {{
                background-color: {self._theme['bg_tertiary']};
                color: {self._theme['text_secondary']};
                font-weight: 700;
                padding: 6px 8px;
            }}
            """
        )
        if self._last_summary is not None:
            self.set_summary(self._last_summary)

    def _tone_color(self, tone: str) -> str:
        if tone == "success":
            return self._theme["success"]
        if tone == "danger":
            return self._theme["danger"]
        return self._theme["text_secondary"]


__all__ = ["BacktestSummaryWidget"]
