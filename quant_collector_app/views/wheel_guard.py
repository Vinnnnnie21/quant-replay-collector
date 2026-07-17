"""Prevent accidental wheel edits while preserving container scrolling."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets


_FILTER_ATTRIBUTE = "_qrc_no_wheel_value_input_filter"
_INSTALLED_PROPERTY = "qrcNoWheelGuardInstalled"


def _is_value_input(widget: QtCore.QObject) -> bool:
    if isinstance(widget, QtWidgets.QAbstractSpinBox):
        return True
    if not isinstance(widget, QtWidgets.QLineEdit):
        return False
    return (
        widget.property("role") == "numericInput"
        or isinstance(widget.parentWidget(), QtWidgets.QAbstractSpinBox)
    )


def _scroll_viewport(widget: QtWidgets.QWidget) -> QtWidgets.QWidget | None:
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QtWidgets.QAbstractScrollArea):
            return parent.viewport()
        parent = parent.parentWidget()
    return None


def _forward_wheel_to_scroll_area(
    widget: QtWidgets.QWidget,
    event: QtGui.QWheelEvent,
) -> None:
    viewport = _scroll_viewport(widget)
    if viewport is None:
        return
    global_position = event.globalPosition()
    local_position = QtCore.QPointF(viewport.mapFromGlobal(global_position.toPoint()))
    forwarded = QtGui.QWheelEvent(
        local_position,
        global_position,
        event.pixelDelta(),
        event.angleDelta(),
        event.buttons(),
        event.modifiers(),
        event.phase(),
        event.inverted(),
    )
    QtCore.QCoreApplication.sendEvent(viewport, forwarded)


class _NoWheelValueInputFilter(QtCore.QObject):
    def install_subtree(self, root: QtCore.QObject) -> None:
        candidates: list[QtWidgets.QWidget] = []
        if isinstance(root, QtWidgets.QWidget):
            candidates.append(root)
        candidates.extend(root.findChildren(QtWidgets.QWidget))
        for candidate in candidates:
            if candidate.property(_INSTALLED_PROPERTY):
                continue
            candidate.installEventFilter(self)
            candidate.setProperty(_INSTALLED_PROPERTY, True)

    def eventFilter(self, watched, event):  # noqa: N802 - Qt override
        if event.type() == QtCore.QEvent.ChildAdded:
            child = event.child()
            if isinstance(child, QtWidgets.QWidget):
                self.install_subtree(child)
            return False
        if event.type() == QtCore.QEvent.Wheel and _is_value_input(watched):
            _forward_wheel_to_scroll_area(watched, event)
            event.accept()
            return True
        return False


def install_no_wheel_on_value_inputs(root: QtCore.QObject) -> None:
    """Guard existing and future value editors below ``root`` from wheel edits."""

    if root is None or getattr(root, _FILTER_ATTRIBUTE, None) is not None:
        return
    event_filter = _NoWheelValueInputFilter(root)
    setattr(root, _FILTER_ATTRIBUTE, event_filter)
    event_filter.install_subtree(root)


__all__ = ["install_no_wheel_on_value_inputs"]
