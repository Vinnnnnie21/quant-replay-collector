from __future__ import annotations

import os
from types import SimpleNamespace

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from views.nullable_percent_input import NullablePercentInput
from main_app import MainWindow


def test_nullable_percent_input_clear_and_zero_are_none():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    control = NullablePercentInput()

    control.setValue(2.5)
    assert control.value() == 2.5
    control.clear()
    assert control.text() == ""
    assert control.value() is None
    control.setValue(0)
    assert control.text() == ""
    assert control.value() is None

    control.deleteLater()
    app.processEvents()


def test_nullable_percent_input_rejects_invalid_nonempty_value():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    control = NullablePercentInput()

    control.setText("not-a-number")

    with pytest.raises(ValueError, match="percentage"):
        control.value()

    control.deleteLater()
    app.processEvents()


def test_main_window_tp_sl_getters_preserve_nullable_values():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    take_profit = NullablePercentInput()
    stop_loss = NullablePercentInput()
    window = SimpleNamespace(
        takeProfitPctSpin=take_profit,
        stopLossPctSpin=stop_loss,
    )

    assert MainWindow.take_profit_pct_value(window) is None
    assert MainWindow.stop_loss_pct_value(window) is None
    take_profit.setValue(2.0)
    assert MainWindow.take_profit_pct_value(window) == 2.0
    assert MainWindow.stop_loss_pct_value(window) is None

    take_profit.deleteLater()
    stop_loss.deleteLater()
    app.processEvents()
