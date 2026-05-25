from __future__ import annotations

import pyqtgraph as pg
from PySide6 import QtCore


class KViewBox(pg.ViewBox):
    userInteracted = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.setMouseEnabled(x=True, y=False)
        self.setMenuEnabled(False)

    def wheelEvent(self, event, axis=None):
        try:
            delta = event.delta() if hasattr(event, "delta") else event.angleDelta().y()
            if delta == 0:
                event.ignore()
                return
            self.userInteracted.emit()
            (left, right), _ = self.viewRange()
            span = max(1.0, right - left)
            center = self.mapSceneToView(event.scenePos()).x()
            factor = 0.9 if delta > 0 else 1.1
            new_left = center - (center - left) * factor
            self.setXRange(new_left, new_left + span * factor, padding=0.0)
            event.accept()
        except Exception:
            event.ignore()

    def mouseDragEvent(self, event, axis=None):
        if event.button() == QtCore.Qt.LeftButton:
            self.userInteracted.emit()
        super().mouseDragEvent(event, axis=axis)


__all__ = ["KViewBox"]
