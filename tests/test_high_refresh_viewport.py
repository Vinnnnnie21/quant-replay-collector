from __future__ import annotations

import pytest


QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from views.high_refresh_viewport import configure_high_refresh_viewport


class _Format:
    def __init__(self) -> None:
        self.swap_interval = None

    def setSwapInterval(self, value: int) -> None:
        self.swap_interval = value


class _Viewport:
    def __init__(self) -> None:
        self.surface_format = _Format()

    def format(self):
        return self.surface_format

    def setFormat(self, surface_format) -> None:
        self.surface_format = surface_format


class _GraphicsView:
    def __init__(self) -> None:
        self.viewport = None
        self.update_mode = None

    def setViewport(self, viewport) -> None:
        self.viewport = viewport

    def setViewportUpdateMode(self, mode) -> None:
        self.update_mode = mode


def test_high_refresh_viewport_uses_opengl_and_full_updates_on_windows():
    view = _GraphicsView()

    enabled = configure_high_refresh_viewport(
        view,
        viewport_factory=_Viewport,
        platform_name="windows",
    )

    assert enabled is True
    assert isinstance(view.viewport, _Viewport)
    assert view.viewport.surface_format.swap_interval == 1
    assert view.update_mode == QtWidgets.QGraphicsView.FullViewportUpdate


def test_high_refresh_viewport_falls_back_when_opengl_initialization_fails():
    view = _GraphicsView()

    enabled = configure_high_refresh_viewport(
        view,
        viewport_factory=lambda: (_ for _ in ()).throw(RuntimeError("no OpenGL")),
        platform_name="windows",
    )

    assert enabled is False
    assert view.viewport is None
    assert view.update_mode == QtWidgets.QGraphicsView.MinimalViewportUpdate
