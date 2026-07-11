from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui

try:
    from ui_style import COLORS
except ImportError:  # pragma: no cover - package import path
    from ..ui_style import COLORS


class CandlestickItem(pg.GraphicsObject):
    CHUNK_SIZE = 32

    def __init__(self):
        super().__init__()
        self._chunk_cache: dict[int, tuple[tuple, QtGui.QPicture]] = {}
        self._active_pictures: list[QtGui.QPicture] = []
        self._rebuilt_last_update = 0
        self._bounds = QtCore.QRectF(0, 0, 1, 1)
        self._data = None
        self._w = 0.7
        self._pen_up = pg.mkPen(COLORS["chart_up"])
        self._pen_dn = pg.mkPen(COLORS["chart_down"])
        self._brush_up = pg.mkBrush(COLORS["chart_up"])
        self._brush_dn = pg.mkBrush(COLORS["chart_down"])
        self._wick_pen = pg.mkPen(COLORS["chart_wick"])

    def set_data(self, x, opening, high, low, close, candle_width=0.7, data_version=None):
        self._data = (
            np.asarray(x, dtype=float),
            np.asarray(opening, dtype=float),
            np.asarray(high, dtype=float),
            np.asarray(low, dtype=float),
            np.asarray(close, dtype=float),
        )
        self._w = float(candle_width)
        self._rebuild(data_version=data_version)

    def set_style(self, up_color: str, down_color: str, wick_color: str):
        self._pen_up = pg.mkPen(up_color)
        self._pen_dn = pg.mkPen(down_color)
        self._brush_up = pg.mkBrush(up_color)
        self._brush_dn = pg.mkBrush(down_color)
        self._wick_pen = pg.mkPen(wick_color)
        self._chunk_cache.clear()
        if self._data is not None:
            self._rebuild()

    def _build_chunk(self, x, opening, high, low, close) -> QtGui.QPicture:
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
        return picture

    def _rebuild(self, data_version=None):
        if self._data is None or len(self._data[0]) == 0:
            self._chunk_cache.clear()
            self._active_pictures = []
            self._rebuilt_last_update = 0
            self.prepareGeometryChange()
            self._bounds = QtCore.QRectF(0, 0, 1, 1)
            self.update()
            return
        x, opening, high, low, close = self._data
        chunk_ids = np.floor_divide(x.astype(np.int64), self.CHUNK_SIZE)
        active_cache: dict[int, tuple[tuple, QtGui.QPicture]] = {}
        active_pictures = []
        rebuilt = 0
        for chunk_id in np.unique(chunk_ids):
            indexes = np.flatnonzero(chunk_ids == chunk_id)
            key = (
                data_version,
                int(indexes.size),
                float(x[indexes[0]]),
                float(x[indexes[-1]]),
                float(self._w),
            )
            cached = self._chunk_cache.get(int(chunk_id))
            if cached is None or cached[0] != key:
                picture = self._build_chunk(
                    x[indexes], opening[indexes], high[indexes], low[indexes], close[indexes]
                )
                cached = (key, picture)
                rebuilt += 1
            active_cache[int(chunk_id)] = cached
            active_pictures.append(cached[1])
        self._chunk_cache = active_cache
        self._active_pictures = active_pictures
        self._rebuilt_last_update = rebuilt
        self.prepareGeometryChange()
        self._bounds = QtCore.QRectF(
            float(x.min()) - 1.0,
            float(low.min()),
            float(x.max() - x.min()) + 2.0,
            max(1e-6, float(high.max() - low.min())),
        )
        self.update()

    def paint(self, painter, option, widget):
        for picture in self._active_pictures:
            painter.drawPicture(0, 0, picture)

    def boundingRect(self):
        return self._bounds

    def cache_stats(self) -> dict[str, int]:
        return {
            "chunks": len(self._active_pictures),
            "rebuilt_last_update": self._rebuilt_last_update,
        }


__all__ = ["CandlestickItem"]
