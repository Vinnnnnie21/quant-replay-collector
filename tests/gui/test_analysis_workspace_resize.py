from __future__ import annotations

import pytest


QtCore = pytest.importorskip("PySide6.QtCore")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from analysis_workspace import AnalysisWorkspace


class Host(QtWidgets.QWidget):
    current_language = "en_US"
    session_id = "resize-test"

    def __init__(self):
        super().__init__()
        self.backtestPanel = _large_panel("backtest")
        self.strategyConsistencyPanel = _large_panel("strategy consistency")


def _large_panel(label: str) -> QtWidgets.QWidget:
    panel = QtWidgets.QWidget()
    panel.setMinimumHeight(1200)
    layout = QtWidgets.QVBoxLayout(panel)
    layout.addWidget(QtWidgets.QLabel(label))
    layout.addStretch(1)
    return panel


def test_large_analysis_tabs_are_scrollable_and_workspace_can_shrink_vertically():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = Host()
    dialog = AnalysisWorkspace(host)

    assert dialog.sizePolicy().verticalPolicy() != QtWidgets.QSizePolicy.Fixed
    assert isinstance(dialog.backtestTab, QtWidgets.QScrollArea)
    assert dialog.backtestTab.widget() is host.backtestPanel
    assert dialog.backtestTab.widgetResizable() is True
    assert dialog.backtestTab.verticalScrollBarPolicy() != QtCore.Qt.ScrollBarAlwaysOff
    assert host.backtestPanel.sizePolicy().horizontalPolicy() == QtWidgets.QSizePolicy.Expanding
    assert host.backtestPanel.sizePolicy().verticalPolicy() == QtWidgets.QSizePolicy.Preferred

    dialog.show()
    app.processEvents()
    dialog.resize(720, 320)
    app.processEvents()

    assert dialog.height() <= 360
    assert dialog.backtestTab.verticalScrollBar().maximum() > 0

    dialog.close()
    host.close()
    app.processEvents()
