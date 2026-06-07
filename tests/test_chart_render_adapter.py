from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from render.chart_render_adapter import clamp_xrange, current_xrange, should_render_now


def test_chart_render_adapter_reads_and_clamps_visible_range():
    window = SimpleNamespace(
        vb_price=SimpleNamespace(viewRange=lambda: ((2.5, 8.5), (0.0, 1.0))),
        df=pd.DataFrame({"close": range(10)}),
        cursor=7,
        pad_right=2,
        playing=False,
        _last_render_msec=0,
        _render_interval_ms=50,
    )

    assert current_xrange(window) == (2.5, 8.5)
    assert clamp_xrange(window, -10.0, 100.0) == (0.0, 110.0)
    assert should_render_now(window) is True
