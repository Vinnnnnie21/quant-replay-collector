from __future__ import annotations

from PySide6 import QtGui
import pyqtgraph as pg


def apply_readable_plot_text(plot_widget: pg.PlotWidget, theme: dict) -> None:
    plot_item = plot_widget.getPlotItem()
    tick_font = QtGui.QFont()
    tick_font.setPointSize(10)
    label_font = QtGui.QFont()
    label_font.setPointSize(11)
    label_font.setBold(True)
    for side in ("left", "bottom", "right", "top"):
        axis = plot_item.getAxis(side)
        if axis is None:
            continue
        axis.setStyle(tickFont=tick_font)
        axis.label.setFont(label_font)
        axis.label.setDefaultTextColor(QtGui.QColor(theme["chart_axis"]))


def make_bold(widget, *, point_size: int | None = None) -> None:
    font = widget.font()
    font.setBold(True)
    if point_size is not None:
        font.setPointSize(point_size)
    widget.setFont(font)


__all__ = ["apply_readable_plot_text", "make_bold"]
