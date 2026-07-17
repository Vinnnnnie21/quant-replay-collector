"""Small nullable percentage editor used by replay execution settings."""

from __future__ import annotations

import math
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets


class NullablePercentInput(QtWidgets.QLineEdit):
    """A percentage input where an empty string is the canonical unset value."""

    valueChanged = QtCore.Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        validator = QtGui.QDoubleValidator(0.0, 100.0, 6, self)
        validator.setLocale(QtCore.QLocale.c())
        validator.setNotation(QtGui.QDoubleValidator.StandardNotation)
        self.setValidator(validator)
        self.setProperty("role", "numericInput")
        self.setPlaceholderText("")
        self.setClearButtonEnabled(True)
        self.textChanged.connect(self._emit_value_changed)

    def _emit_value_changed(self, _text: str) -> None:
        try:
            value = self.value()
        except ValueError:
            value = None
        self.valueChanged.emit(value)

    def value(self) -> float | None:
        text = self.text().strip()
        if not text:
            return None
        try:
            value = float(text)
        except (TypeError, ValueError) as exc:
            raise ValueError("percentage must be a number") from exc
        if not math.isfinite(value) or value < 0.0 or value > 100.0:
            raise ValueError("percentage must be between 0 and 100")
        return value if value > 0.0 else None

    def setValue(self, value: Any) -> None:
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            self.clear()
            return
        if not math.isfinite(normalized) or normalized <= 0.0:
            self.clear()
            return
        if normalized > 100.0:
            self.clear()
            return
        self.setText(f"{normalized:g}")


__all__ = ["NullablePercentInput"]
