"""Resolve and apply the shared QRC application icon."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets


HEADER_LOGO_SIZE = 18


def _application_asset_path(filename: str) -> Path:
    """Resolve an application asset in source and PyInstaller runtimes."""

    module_dir = Path(__file__).resolve().parent
    if getattr(sys, "frozen", False):
        bundle_dir = Path(getattr(sys, "_MEIPASS", module_dir))
        bundled = bundle_dir / "assets" / filename
        if bundled.is_file():
            return bundled
        external = Path(sys.executable).resolve().parent / "assets" / filename
        if external.is_file():
            return external
        return bundled
    return module_dir / "assets" / filename


def application_icon_path() -> Path:
    """Return the fixed Windows executable and shortcut icon path."""

    return _application_asset_path("app_icon.ico")


def application_logo_path(theme: dict | None = None) -> Path:
    """Return the logo variant that remains visible on the active theme."""

    background = QtGui.QColor(str((theme or {}).get("bg_primary", "")))
    is_light = background.isValid() and background.lightnessF() >= 0.5
    filename = "app_logo_light.png" if is_light else "app_logo.png"
    return _application_asset_path(filename)


def apply_application_icon(
    app: QtWidgets.QApplication,
    theme: dict | None = None,
    window: QtWidgets.QWidget | None = None,
) -> bool:
    """Apply the theme logo to the application and optional active window."""

    path = application_logo_path(theme)
    if not path.is_file():
        path = application_icon_path()
    if not path.is_file():
        return False
    icon = QtGui.QIcon(str(path))
    if icon.isNull():
        return False
    app.setWindowIcon(icon)
    if window is not None:
        window.setWindowIcon(icon)
    return True


def apply_header_logo(
    label: QtWidgets.QLabel,
    theme: dict | None = None,
    *,
    size: int = HEADER_LOGO_SIZE,
) -> bool:
    """Render the active theme logo at the header title's visual height."""

    pixmap = QtGui.QPixmap(str(application_logo_path(theme)))
    if pixmap.isNull():
        label.clear()
        return False
    label.setFixedSize(size, size)
    label.setAlignment(QtCore.Qt.AlignCenter)
    label.setPixmap(
        pixmap.scaled(
            size,
            size,
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )
    )
    return True


__all__ = [
    "HEADER_LOGO_SIZE",
    "application_icon_path",
    "application_logo_path",
    "apply_application_icon",
    "apply_header_logo",
]
