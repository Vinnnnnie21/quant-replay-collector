from __future__ import annotations

import pyqtgraph as pg
from PySide6 import QtWidgets


def prepare_plot_for_shutdown(plot: pg.PlotItem) -> None:
    """Disconnect callbacks that may re-enter PlotItem during Qt teardown."""

    view_box = plot.vb
    if view_box is None:
        return
    try:
        view_box.sigStateChanged.disconnect(plot.viewStateChanged)
    except (RuntimeError, TypeError):
        pass
    axes = getattr(plot, "axes", None) or {}
    for axis_state in axes.values():
        axis_state["item"].unlinkFromView()
    view_box.setXLink(None)
    view_box.setYLink(None)


def close_parent_owned_graphics_view(view: QtWidgets.QGraphicsView) -> bool:
    """Close a managed view without synchronously clearing its Qt-owned scene.

    pyqtgraph's GraphicsView.close() clears the scene immediately. On Windows,
    that can race the accepted parent-window teardown after PlotItem cleanup.
    Detaching the scene leaves its QObject parent responsible for destruction.
    """

    view.centralWidget = None
    view.currentItem = None
    view.closed = True
    view.setScene(None)
    return bool(QtWidgets.QGraphicsView.close(view))


__all__ = ["close_parent_owned_graphics_view", "prepare_plot_for_shutdown"]
