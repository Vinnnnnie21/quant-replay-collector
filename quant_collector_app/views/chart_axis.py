from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui

try:
    from market_data.types import make_bjt
except ImportError:  # pragma: no cover - package import path
    from ..market_data.types import make_bjt


class IndexTimeAxis(pg.AxisItem):
    def __init__(self, orientation="bottom"):
        super().__init__(orientation=orientation)
        self._times = None
        self._cache: dict[int, str] = {}
        try:
            self.enableAutoSIPrefix(False)
        except Exception:
            pass

    def set_times(self, times: np.ndarray | list):
        self._times = np.asarray(times, dtype=object)
        self._cache.clear()
        self.update()

    def tickStrings(self, values, scale, spacing):
        if self._times is None or len(self._times) == 0:
            return ["" for _ in values]
        result = []
        show_time = spacing <= 120
        count = len(self._times)
        for value in values:
            try:
                index = int(round(float(value) * float(scale)))
                if index < 0 or index >= count:
                    result.append("")
                    continue
                if index not in self._cache:
                    point = make_bjt(self._times[index])
                    self._cache[index] = point.strftime("%m-%d %H:%M") if show_time else point.strftime("%Y-%m-%d")
                result.append(self._cache[index])
            except Exception:
                result.append("")
        return result


class CurrentPriceAxis(pg.AxisItem):
    """Right-side price axis with an exchange-style current-price badge."""

    def __init__(self, orientation: str = "right"):
        super().__init__(orientation=orientation)
        self.current_price: float | None = None
        self.current_color = "#8C8983"
        self.current_text_color = "#07100D"
        self.setWidth(82)

    def set_current_price(
        self,
        value: float | None,
        color: str | None = None,
        text_color: str | None = None,
    ) -> None:
        self.current_price = None if value is None else float(value)
        if color:
            self.current_color = str(color)
        if text_color:
            self.current_text_color = str(text_color)
        self.update()

    def paint(self, painter, option, widget):
        super().paint(painter, option, widget)
        if self.current_price is None or self.orientation != "right":
            return
        low, high = (float(self.range[0]), float(self.range[1]))
        span = high - low
        if span <= 0 or not low <= self.current_price <= high:
            return
        rect = self.rect()
        y = rect.top() + (high - self.current_price) / span * rect.height()
        height = 22.0
        badge = QtCore.QRectF(rect.left(), y - height / 2.0, rect.width(), height)
        painter.save()
        painter.setPen(pg.mkPen(self.current_color))
        painter.setBrush(pg.mkBrush(self.current_color))
        painter.drawRoundedRect(badge, 2.0, 2.0)
        painter.setPen(QtGui.QColor(self.current_text_color))
        painter.drawText(badge, QtCore.Qt.AlignCenter, f"{self.current_price:.4f}")
        painter.restore()


__all__ = ["CurrentPriceAxis", "IndexTimeAxis"]
