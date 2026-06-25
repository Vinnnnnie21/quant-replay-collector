from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui

try:
    from ui_style import COLORS
except ImportError:  # pragma: no cover - package import path
    from ..ui_style import COLORS


class VolumeItem(pg.GraphicsObject):
    def __init__(self):
        super().__init__()
        self._picture = None
        self._bounds = QtCore.QRectF(0, 0, 1, 1)
        self._data = None
        self._w = 0.7
        self._brush_up = pg.mkBrush(COLORS["chart_volume_up"])
        self._brush_dn = pg.mkBrush(COLORS["chart_volume_down"])
        self._pen_none = pg.mkPen(None)

    def set_data(self, x, volume, upmask, bar_width=0.7):
        self._data = (
            np.asarray(x, dtype=float),
            np.asarray(volume, dtype=float),
            np.asarray(upmask, dtype=bool),
        )
        self._w = float(bar_width)
        self._rebuild()

    def set_style(self, up_color: str, down_color: str):
        self._brush_up = pg.mkBrush(up_color)
        self._brush_dn = pg.mkBrush(down_color)
        if self._data is not None:
            self._rebuild()

    def _rebuild(self):
        if self._data is None or len(self._data[0]) == 0:
            self._picture = QtGui.QPicture()
            self.prepareGeometryChange()
            self._bounds = QtCore.QRectF(0, 0, 1, 1)
            self.update()
            return
        x, volume, up = self._data
        picture = QtGui.QPicture()
        painter = QtGui.QPainter(picture)
        painter.setPen(self._pen_none)
        for x_value, volume_value, is_up in zip(x, volume, up):
            painter.setBrush(self._brush_up if is_up else self._brush_dn)
            painter.drawRect(QtCore.QRectF(x_value - self._w / 2.0, 0.0, self._w, max(0.0, float(volume_value))))
        painter.end()
        self._picture = picture
        self.prepareGeometryChange()
        self._bounds = QtCore.QRectF(
            float(x.min()) - 1.0,
            0.0,
            float(x.max() - x.min()) + 2.0,
            max(1e-6, float(volume.max()) if len(volume) else 1.0),
        )
        self.update()

    def paint(self, painter, option, widget):
        if self._picture is not None:
            painter.drawPicture(0, 0, self._picture)

    def boundingRect(self):
        return self._bounds


__all__ = ["VolumeItem"]
