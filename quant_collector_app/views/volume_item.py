from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui

try:
    from ui_style import COLORS
except ImportError:  # pragma: no cover - package import path
    from ..ui_style import COLORS


class VolumeItem(pg.GraphicsObject):
    CHUNK_SIZE = 32

    def __init__(self):
        super().__init__()
        self._chunk_cache: dict[int, tuple[tuple, QtGui.QPicture]] = {}
        self._active_pictures: list[QtGui.QPicture] = []
        self._rebuilt_last_update = 0
        self._bounds = QtCore.QRectF(0, 0, 1, 1)
        self._data = None
        self._w = 0.7
        self._brush_up = pg.mkBrush(COLORS["chart_volume_up"])
        self._brush_dn = pg.mkBrush(COLORS["chart_volume_down"])
        self._pen_none = pg.mkPen(None)

    def set_data(self, x, volume, upmask, bar_width=0.7, data_version=None):
        self._data = (
            np.asarray(x, dtype=float),
            np.asarray(volume, dtype=float),
            np.asarray(upmask, dtype=bool),
        )
        self._w = float(bar_width)
        self._rebuild(data_version=data_version)

    def set_style(self, up_color: str, down_color: str):
        self._brush_up = pg.mkBrush(up_color)
        self._brush_dn = pg.mkBrush(down_color)
        self._chunk_cache.clear()
        if self._data is not None:
            self._rebuild()

    def _build_chunk(self, x, volume, up) -> QtGui.QPicture:
        picture = QtGui.QPicture()
        painter = QtGui.QPainter(picture)
        painter.setPen(self._pen_none)
        for x_value, volume_value, is_up in zip(x, volume, up):
            painter.setBrush(self._brush_up if is_up else self._brush_dn)
            painter.drawRect(QtCore.QRectF(x_value - self._w / 2.0, 0.0, self._w, max(0.0, float(volume_value))))
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
        x, volume, up = self._data
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
                picture = self._build_chunk(x[indexes], volume[indexes], up[indexes])
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
            0.0,
            float(x.max() - x.min()) + 2.0,
            max(1e-6, float(volume.max()) if len(volume) else 1.0),
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


__all__ = ["VolumeItem"]
