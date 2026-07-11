from __future__ import annotations

import pyqtgraph as pg
from PySide6 import QtCore


class KViewBox(pg.ViewBox):
    userInteracted = QtCore.Signal()
    dragStarted = QtCore.Signal()
    dragFinished = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.setMouseEnabled(x=True, y=True)
        self.setMenuEnabled(False)
        # True once the user has manually zoomed the price (Y) axis; while set,
        # the render loop stops auto-fitting Y so the manual zoom is preserved.
        self.yManual = False

    def reset_y_auto(self) -> None:
        """Re-enable automatic vertical fitting (called by 重置缩放)."""
        self.yManual = False

    def wheelEvent(self, event, axis=None):
        try:
            delta = event.delta() if hasattr(event, "delta") else event.angleDelta().y()
            if delta == 0:
                event.ignore()
                return
            self.userInteracted.emit()
            factor = 0.9 if delta > 0 else 1.1
            (left, right), _ = self.viewRange()
            _, (bottom, top) = self.viewRange()
            span_x = max(1.0, right - left)
            span_y = max(1e-9, top - bottom)
            center = self.mapSceneToView(event.scenePos())
            new_left = center.x() - (center.x() - left) * factor
            new_bottom = center.y() - (center.y() - bottom) * factor
            self.yManual = True
            self.setXRange(new_left, new_left + span_x * factor, padding=0.0)
            self.setYRange(new_bottom, new_bottom + span_y * factor, padding=0.0)
            event.accept()
        except Exception:
            event.ignore()

    def mouseDragEvent(self, event, axis=None):
        if event.button() == QtCore.Qt.LeftButton:
            if event.isStart():
                self.dragStarted.emit()
                self.userInteracted.emit()
                self.yManual = True
        super().mouseDragEvent(event, axis=axis)
        if event.button() == QtCore.Qt.LeftButton and event.isFinish():
            self.dragFinished.emit()


__all__ = ["KViewBox"]
