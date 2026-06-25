"""Reusable Qt widget effects: drop shadows for the OKX pill buttons.

Qt style sheets cannot render ``box-shadow``; a drop shadow is a per-widget
``QGraphicsDropShadowEffect``. This is only safe when the button paints its OWN
background via a LOCAL stylesheet (see ``apply_role_button_styles``). With a
window-level stylesheet the effect strips the fill (black buttons); with a local
stylesheet the fill survives — verified at runtime. Always run
``apply_role_button_styles`` BEFORE attaching shadows.

The helpers are defensive: a failure to attach an effect must never break theme
application.
"""

from __future__ import annotations

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except Exception:  # pragma: no cover - Qt always present at runtime
    QtCore = None
    QtGui = None
    QtWidgets = None


SHADOW_BUTTON_ROLES = (
    "primaryButton",
    "secondaryButton",
    "successButton",
    "dangerButton",
    "intervalChip",
    "compactButton",
    "dangerGhostButton",
    "tagChip",
    "timeframeChip",
)


def apply_button_shadow(button, *, blur: int = 16, y_offset: int = 3, alpha: int = 150) -> None:
    """Attach a soft drop shadow to a single control. No-op if Qt is unavailable."""
    if QtWidgets is None or button is None:
        return
    try:
        button.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        effect = QtWidgets.QGraphicsDropShadowEffect(button)
        effect.setBlurRadius(blur)
        effect.setXOffset(0)
        effect.setYOffset(y_offset)
        effect.setColor(QtGui.QColor(0, 0, 0, alpha))
        button.setGraphicsEffect(effect)
    except Exception:
        pass


def apply_role_button_shadows(root) -> int:
    """Attach drop shadows to every role button (QPushButton/QToolButton) under root.

    Returns the number of controls that received a shadow.
    """
    if QtWidgets is None or root is None:
        return 0
    count = 0
    for widget_cls in (QtWidgets.QPushButton, QtWidgets.QToolButton, QtWidgets.QCheckBox):
        try:
            controls = root.findChildren(widget_cls)
        except Exception:
            continue
        for button in controls:
            try:
                if button.property("role") in SHADOW_BUTTON_ROLES:
                    apply_button_shadow(button)
                    count += 1
            except Exception:
                continue
    return count


__all__ = ["apply_button_shadow", "apply_role_button_shadows", "SHADOW_BUTTON_ROLES"]
