from __future__ import annotations

import numpy as np
import pyqtgraph as pg

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


__all__ = ["IndexTimeAxis"]
