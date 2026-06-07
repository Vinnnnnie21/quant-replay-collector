from __future__ import annotations

import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from views.main_window_connections import setup_table


def test_setup_table_preserves_read_only_single_row_selection_contract():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    table = QtWidgets.QTableWidget()

    setup_table(table)

    assert table.selectionBehavior() == QtWidgets.QAbstractItemView.SelectRows
    assert table.selectionMode() == QtWidgets.QAbstractItemView.SingleSelection
    assert table.editTriggers() == QtWidgets.QAbstractItemView.NoEditTriggers
    assert table.showGrid() is False
    table.close()
    app.processEvents()
