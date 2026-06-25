from __future__ import annotations

import pyqtgraph as pg
from PySide6 import QtCore


class KViewBox(pg.ViewBox):
    userInteracted = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.setMouseEnabled(x=True, y=False)
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
            # Ctrl + wheel zooms the vertical (price) axis freely; plain wheel
            # keeps zooming the horizontal (time) axis.
            if event.modifiers() & QtCore.Qt.ControlModifier:
                self.yManual = True
                _, (bottom, top) = self.viewRange()
                span = max(1e-9, top - bottom)
                center = self.mapSceneToView(event.scenePos()).y()
                new_bottom = center - (center - bottom) * factor
                self.setYRange(new_bottom, new_bottom + span * factor, padding=0.0)
                event.accept()
                return
            (left, right), _ = self.viewRange()
            span = max(1.0, right - left)
            center = self.mapSceneToView(event.scenePos()).x()
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
