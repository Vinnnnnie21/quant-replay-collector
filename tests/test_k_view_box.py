from __future__ import annotations

import pytest


pytest.importorskip("PySide6")
pg = pytest.importorskip("pyqtgraph")
from PySide6 import QtCore

from views.k_view_box import KViewBox


def test_k_view_box_allows_free_x_and_y_mouse_navigation():
    view = KViewBox()

    assert view.state["mouseEnabled"] == [True, True]
    assert view.yManual is False


def test_k_view_box_emits_drag_lifecycle_once(monkeypatch):
    view = KViewBox()
    events: list[str] = []
    view.dragStarted.connect(lambda: events.append("start"))
    view.dragFinished.connect(lambda: events.append("finish"))
    monkeypatch.setattr(pg.ViewBox, "mouseDragEvent", lambda *_args, **_kwargs: None)

    class Event:
        def __init__(self, *, start=False, finish=False):
            self._start = start
            self._finish = finish

        def button(self):
            return QtCore.Qt.LeftButton

        def isStart(self):
            return self._start

        def isFinish(self):
            return self._finish

    view.mouseDragEvent(Event(start=True))
    view.mouseDragEvent(Event())
    view.mouseDragEvent(Event(finish=True))

    assert events == ["start", "finish"]

    view.yManual = True
    view.reset_y_auto()

    assert view.yManual is False
