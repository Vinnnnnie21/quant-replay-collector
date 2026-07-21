from __future__ import annotations

import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore")
QtGui = pytest.importorskip("PySide6.QtGui")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
QtTest = pytest.importorskip("PySide6.QtTest")

from views.nullable_percent_input import NullablePercentInput
from views.wheel_guard import install_no_wheel_on_value_inputs


def _send_wheel(widget: QtWidgets.QWidget, delta: int = -120) -> None:
    local = QtCore.QPointF(widget.rect().center())
    global_pos = QtCore.QPointF(widget.mapToGlobal(local.toPoint()))
    event = QtGui.QWheelEvent(
        local,
        global_pos,
        QtCore.QPoint(),
        QtCore.QPoint(0, delta),
        QtCore.Qt.NoButton,
        QtCore.Qt.NoModifier,
        QtCore.Qt.ScrollUpdate,
        False,
    )
    QtWidgets.QApplication.sendEvent(widget, event)


@pytest.mark.parametrize(
    "factory,get_value",
    [
        (lambda: QtWidgets.QSpinBox(), lambda widget: widget.value()),
        (lambda: QtWidgets.QDoubleSpinBox(), lambda widget: widget.value()),
        (lambda: QtWidgets.QDateEdit(QtCore.QDate(2026, 7, 17)), lambda widget: widget.date()),
        (
            lambda: QtWidgets.QDateTimeEdit(
                QtCore.QDateTime(QtCore.QDate(2026, 7, 17), QtCore.QTime(12, 30))
            ),
            lambda widget: widget.dateTime(),
        ),
        (lambda: QtWidgets.QTimeEdit(QtCore.QTime(12, 30)), lambda widget: widget.time()),
    ],
)
def test_value_inputs_ignore_wheel_but_keep_programmatic_changes(factory, get_value):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    root = QtWidgets.QWidget()
    widget = factory()
    widget.setParent(root)
    if isinstance(widget, QtWidgets.QAbstractSpinBox) and not isinstance(
        widget, QtWidgets.QDateTimeEdit
    ):
        widget.setRange(-100, 100)
        widget.setValue(10)
    install_no_wheel_on_value_inputs(root)

    before = get_value(widget)
    _send_wheel(widget)

    assert get_value(widget) == before
    if isinstance(widget, QtWidgets.QSpinBox):
        widget.setValue(12)
        assert widget.value() == 12
        widget.show()
        widget.setFocus()
        QtTest.QTest.keyClick(widget, QtCore.Qt.Key_Up)
        assert widget.value() == 13

    root.deleteLater()
    app.processEvents()


def test_nullable_percent_input_ignores_wheel_and_parent_scrolls():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    scroll = QtWidgets.QScrollArea()
    scroll.resize(240, 120)
    content = QtWidgets.QWidget()
    content.setMinimumHeight(900)
    control = NullablePercentInput(content)
    control.setGeometry(20, 350, 120, 30)
    control.setValue(2.5)
    scroll.setWidget(content)
    scroll.setWidgetResizable(False)
    install_no_wheel_on_value_inputs(scroll)
    scroll.show()
    app.processEvents()
    scroll.verticalScrollBar().setValue(100)

    before_scroll = scroll.verticalScrollBar().value()
    _send_wheel(control)

    assert control.value() == 2.5
    assert scroll.verticalScrollBar().value() > before_scroll

    scroll.close()
    scroll.deleteLater()
    app.processEvents()


def test_spinbox_editor_surface_is_guarded_and_forwards_scroll():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    scroll = QtWidgets.QScrollArea()
    scroll.resize(240, 120)
    content = QtWidgets.QWidget()
    content.setMinimumHeight(900)
    spin = QtWidgets.QDoubleSpinBox(content)
    spin.setGeometry(20, 350, 120, 30)
    spin.setRange(0, 100)
    spin.setValue(10)
    scroll.setWidget(content)
    scroll.setWidgetResizable(False)
    install_no_wheel_on_value_inputs(scroll)
    scroll.show()
    app.processEvents()
    scroll.verticalScrollBar().setValue(100)

    before_scroll = scroll.verticalScrollBar().value()
    _send_wheel(spin.lineEdit())

    assert spin.value() == 10
    assert scroll.verticalScrollBar().value() > before_scroll

    scroll.close()
    scroll.deleteLater()
    app.processEvents()


def test_controls_added_after_installation_are_guarded_but_other_widgets_are_not():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    root = QtWidgets.QWidget()
    install_no_wheel_on_value_inputs(root)
    spin = QtWidgets.QSpinBox(root)
    spin.setRange(0, 20)
    spin.setValue(10)

    class WheelProbe(QtWidgets.QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.wheel_events = 0

        def wheelEvent(self, event):  # noqa: N802 - Qt override
            self.wheel_events += 1
            event.accept()

    probe = WheelProbe(root)

    _send_wheel(spin)
    _send_wheel(probe)

    assert spin.value() == 10
    assert probe.wheel_events == 1

    root.deleteLater()
    app.processEvents()
