from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui


class CandlestickItem(pg.GraphicsObject):
    def __init__(self):
        super().__init__()
        self._picture = None
        self._bounds = QtCore.QRectF(0, 0, 1, 1)
        self._data = None
        self._w = 0.7
        self._pen_up = pg.mkPen("#00C853")
        self._pen_dn = pg.mkPen("#FF5252")
        self._brush_up = pg.mkBrush("#00C853")
        self._brush_dn = pg.mkBrush("#FF5252")
        self._wick_pen = pg.mkPen("#B0BEC5")

    def set_data(self, x, opening, high, low, close, candle_width=0.7):
        self._data = (
            np.asarray(x, dtype=float),
            np.asarray(opening, dtype=float),
            np.asarray(high, dtype=float),
            np.asarray(low, dtype=float),
            np.asarray(close, dtype=float),
        )
        self._w = float(candle_width)
        self._rebuild()

    def set_style(self, up_color: str, down_color: str, wick_color: str):
        self._pen_up = pg.mkPen(up_color)
        self._pen_dn = pg.mkPen(down_color)
        self._brush_up = pg.mkBrush(up_color)
        self._brush_dn = pg.mkBrush(down_color)
        self._wick_pen = pg.mkPen(wick_color)
        if self._data is not None:
            self._rebuild()

    def _rebuild(self):
        if self._data is None or len(self._data[0]) == 0:
            self._picture = QtGui.QPicture()
            self.prepareGeometryChange()
            self._bounds = QtCore.QRectF(0, 0, 1, 1)
            self.update()
            return
        x, opening, high, low, close = self._data
        picture = QtGui.QPicture()
        painter = QtGui.QPainter(picture)
        painter.setPen(self._wick_pen)
        for x_value, high_value, low_value in zip(x, high, low):
            painter.drawLine(QtCore.QPointF(x_value, low_value), QtCore.QPointF(x_value, high_value))
        for x_value, open_value, close_value in zip(x, opening, close):
            up = close_value >= open_value
            painter.setPen(self._pen_up if up else self._pen_dn)
            painter.setBrush(self._brush_up if up else self._brush_dn)
            top = max(open_value, close_value)
            bottom = min(open_value, close_value)
            if abs(top - bottom) < 1e-8:
                bottom = top - 1e-8
            painter.drawRect(QtCore.QRectF(x_value - self._w / 2.0, bottom, self._w, top - bottom))
        painter.end()
        self._picture = picture
        self.prepareGeometryChange()
        self._bounds = QtCore.QRectF(
            float(x.min()) - 1.0,
            float(low.min()),
            float(x.max() - x.min()) + 2.0,
            max(1e-6, float(high.max() - low.min())),
        )
        self.update()

    def paint(self, painter, option, widget):
        if self._picture is not None:
            painter.drawPicture(0, 0, self._picture)

    def boundingRect(self):
        return self._bounds


__all__ = ["CandlestickItem"]
