from __future__ import annotations

from collections.abc import Callable

from PySide6 import QtGui, QtWidgets


def configure_high_refresh_viewport(
    graphics_view,
    *,
    viewport_factory: Callable[[], object] | None = None,
    platform_name: str | None = None,
) -> bool:
    """Install an OpenGL viewport for the main chart with a software fallback."""

    platform = str(platform_name or QtGui.QGuiApplication.platformName()).lower()
    if platform in {"offscreen", "minimal"}:
        graphics_view.setViewportUpdateMode(QtWidgets.QGraphicsView.MinimalViewportUpdate)
        return False
    try:
        if viewport_factory is None:
            from PySide6.QtOpenGLWidgets import QOpenGLWidget

            viewport_factory = QOpenGLWidget
        viewport = viewport_factory()
        surface_format = viewport.format()
        surface_format.setSwapInterval(1)
        viewport.setFormat(surface_format)
        graphics_view.setViewport(viewport)
        graphics_view.setViewportUpdateMode(QtWidgets.QGraphicsView.FullViewportUpdate)
        return True
    except Exception:
        graphics_view.setViewportUpdateMode(QtWidgets.QGraphicsView.MinimalViewportUpdate)
        return False


def verify_high_refresh_viewport(graphics_view) -> bool:
    """Fall back after show if Qt could not create a valid OpenGL context."""

    try:
        from PySide6.QtOpenGLWidgets import QOpenGLWidget

        viewport = graphics_view.viewport()
        if not isinstance(viewport, QOpenGLWidget):
            return False
        if viewport.isValid():
            return True
    except Exception:
        pass
    graphics_view.setViewport(QtWidgets.QWidget())
    graphics_view.setViewportUpdateMode(QtWidgets.QGraphicsView.MinimalViewportUpdate)
    return False


__all__ = ["configure_high_refresh_viewport", "verify_high_refresh_viewport"]
