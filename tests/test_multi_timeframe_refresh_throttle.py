from __future__ import annotations

import pandas as pd
import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6 import QtWidgets

import multi_timeframe_panel as panel_module
from multi_timeframe_panel import MultiTimeframePanel


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _htf_frame() -> pd.DataFrame:
    times = pd.date_range("2024-04-01 10:00:00", periods=40, freq="5min", tz="Asia/Shanghai")
    return pd.DataFrame(
        {
            "bar_index": range(40),
            "open_time_bjt": times,
            "close_time_bjt": times + pd.Timedelta(minutes=5),
            "open": range(100, 140),
            "high": range(101, 141),
            "low": range(99, 139),
            "close": [100.5 + index for index in range(40)],
            "volume": range(1000, 1040),
        }
    )


def test_same_htf_bar_does_not_rewrite_summary_text(qapp):
    panel = MultiTimeframePanel(language="zh_CN", start_worker=False)
    writes: list[str] = []
    original = panel.summaryText.setPlainText

    def record_write(text: str) -> None:
        writes.append(text)
        original(text)

    panel.summaryText.setPlainText = record_write
    panel.set_context_frames({"5m": _htf_frame()})

    panel.refresh_for_primary_row({"open_time_bjt": pd.Timestamp("2024-04-01 10:12:00", tz="Asia/Shanghai")})
    panel.refresh_for_primary_row({"open_time_bjt": pd.Timestamp("2024-04-01 10:13:00", tz="Asia/Shanghai")})
    panel.refresh_for_primary_row({"open_time_bjt": pd.Timestamp("2024-04-01 10:14:00", tz="Asia/Shanghai")})

    assert len(writes) == 1
    panel.shutdown()


def test_context_frames_are_normalized_once_and_reused(qapp):
    panel = MultiTimeframePanel(language="zh_CN", start_worker=False)
    panel.set_context_frames({"5m": _htf_frame()})
    stored = panel._context_frames["5m"]

    assert "_open_time" in stored.columns
    assert "_close_time" in stored.columns
    first_id = id(stored)
    panel.refresh_for_primary_row({"open_time_bjt": pd.Timestamp("2024-04-01 10:12:00", tz="Asia/Shanghai")})
    panel.refresh_for_primary_row({"open_time_bjt": pd.Timestamp("2024-04-01 10:17:00", tz="Asia/Shanghai")})

    assert id(panel._context_frames["5m"]) == first_id
    panel.shutdown()


def test_same_htf_bar_reuses_cached_summary_without_recomputing(qapp, monkeypatch):
    calls = []
    original = panel_module.build_multi_timeframe_context

    def wrapped(primary_row, context_frames):
        calls.append(primary_row)
        return original(primary_row, context_frames)

    monkeypatch.setattr(panel_module, "build_multi_timeframe_context", wrapped)
    panel = MultiTimeframePanel(language="zh_CN", start_worker=False)
    panel.set_context_frames({"5m": _htf_frame()})

    panel.refresh_for_primary_row({"open_time_bjt": pd.Timestamp("2024-04-01 10:12:00", tz="Asia/Shanghai")})
    panel.refresh_for_primary_row({"open_time_bjt": pd.Timestamp("2024-04-01 10:13:00", tz="Asia/Shanghai")})
    panel.refresh_for_primary_row({"open_time_bjt": pd.Timestamp("2024-04-01 10:14:00", tz="Asia/Shanghai")})

    assert len(calls) == 1
    panel.shutdown()
