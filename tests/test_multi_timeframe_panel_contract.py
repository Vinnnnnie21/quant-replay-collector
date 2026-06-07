from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6 import QtWidgets

from main_app import MainWindow
from multi_timeframe_panel import MultiTimeframePanel


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "quant_collector_app"


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _htf_frame() -> pd.DataFrame:
    times = pd.date_range("2026-05-27 09:00:00", periods=30, freq="5min", tz="Asia/Shanghai")
    return pd.DataFrame(
        {
            "bar_index": range(30),
            "open_time_bjt": times,
            "close_time_bjt": times + pd.Timedelta(minutes=5),
            "open": range(100, 130),
            "high": range(101, 131),
            "low": range(99, 129),
            "close": [100.5 + index for index in range(30)],
            "volume": range(1000, 1030),
        }
    )


def test_multi_timeframe_panel_imports_in_package_mode_without_app_dir_pythonpath():
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    probe = (
        "import importlib, pathlib, sys; "
        "import quant_collector_app; "
        f"app_dir = {str(APP_DIR)!r}; "
        "sys.path = [p for p in sys.path if p != app_dir]; "
        "assert app_dir not in sys.path; "
        "importlib.import_module('quant_collector_app.multi_timeframe_panel')"
    )

    run = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert run.returncode == 0, run.stderr


def test_panel_is_read_only_and_builds_cache_first_context_requests(qapp):
    panel = MultiTimeframePanel(language="zh_CN", start_worker=False)
    requests = panel.build_load_requests(
        "BTCUSDT",
        "1m",
        dt.datetime(2026, 5, 26, tzinfo=dt.timezone(dt.timedelta(hours=8))),
        dt.datetime(2026, 5, 27, tzinfo=dt.timezone(dt.timedelta(hours=8))),
    )

    assert "只读上下文" in panel.noticeLabel.text()
    assert [request.interval for request in requests] == ["5m", "15m"]
    assert all(request.symbol == "BTCUSDT" and request.use_cache is True for request in requests)
    panel.intervalChecks["1h"].setChecked(True)
    assert [request.interval for request in panel.build_load_requests("BTCUSDT", "1m", requests[0].start_dt_bjt, requests[0].end_dt_bjt)] == [
        "5m",
        "15m",
        "1h",
    ]
    panel.shutdown()


def test_cursor_change_refreshes_context_summary(qapp):
    panel = MultiTimeframePanel(language="zh_CN", start_worker=False)
    panel.set_context_frames({"5m": _htf_frame()})

    first = panel.refresh_for_primary_row({"open_time_bjt": pd.Timestamp("2026-05-27 10:42:00", tz="Asia/Shanghai")})
    first_text = panel.summaryText.toPlainText()
    second = panel.refresh_for_primary_row({"open_time_bjt": pd.Timestamp("2026-05-27 10:52:00", tz="Asia/Shanghai")})

    assert first["5m"]["htf_bar_index"] != second["5m"]["htf_bar_index"]
    assert panel.summaryText.toPlainText() != first_text
    panel.shutdown()


def test_context_failure_and_stale_state_do_not_touch_primary_samples(qapp):
    primary_df = pd.DataFrame({"close": [1.0, 2.0]})
    trades = [{"trade_id": "t1"}]
    events = [{"event_id": "e1"}]
    panel = MultiTimeframePanel(language="zh_CN", start_worker=False)

    panel.set_context_frames({}, {"5m": "network timeout"})
    assert "高周期上下文加载失败" in panel.summaryText.toPlainText()
    panel.mark_stale()

    assert primary_df["close"].tolist() == [1.0, 2.0]
    assert trades == [{"trade_id": "t1"}]
    assert events == [{"event_id": "e1"}]
    assert "待主周期重新加载" in panel.summaryText.toPlainText()
    panel.shutdown()


def test_main_window_context_refresh_reads_cursor_only_and_does_not_write_trade_events():
    received: list[dict] = []
    frame = pd.DataFrame({"open_time_bjt": [pd.Timestamp("2026-05-27 09:00:00", tz="Asia/Shanghai")]})
    window = SimpleNamespace(
        df=frame,
        cursor=0,
        trades=[{"trade_id": "t1"}],
        events=[{"event_id": "e1"}],
        multiTimeframePanel=SimpleNamespace(refresh_for_primary_row=lambda row: received.append(dict(row))),
    )

    MainWindow._refresh_multi_timeframe_context(window)

    assert len(received) == 1
    assert window.trades == [{"trade_id": "t1"}]
    assert window.events == [{"event_id": "e1"}]


def test_primary_context_load_uses_loaded_market_identity_without_changing_session():
    requests: list[tuple] = []
    window = SimpleNamespace(
        df=pd.DataFrame({"close": [1.0]}),
        market_dirty=False,
        _loaded_market_key=("BTCUSDT", "1m", "2026-05-26", "2026-05-27"),
        session_id="sess_primary",
        multiTimeframePanel=SimpleNamespace(request_context_load=lambda *args: requests.append(args)),
    )

    MainWindow._load_multi_timeframe_context(window)

    assert requests[0][0:2] == ("BTCUSDT", "1m")
    assert window.session_id == "sess_primary"


def test_dirty_primary_parameters_mark_old_context_stale_without_touching_samples():
    calls: list[str] = []
    window = SimpleNamespace(
        df=pd.DataFrame({"close": [1.0]}),
        playing=True,
        _accum=1.0,
        market_dirty=False,
        trades=[{"trade_id": "t1"}],
        events=[{"event_id": "e1"}],
        replay_controller=SimpleNamespace(playing=True, accumulated_bars=1.0),
        multiTimeframePanel=SimpleNamespace(mark_stale=lambda: calls.append("stale")),
        _is_market_params_dirty=lambda: True,
        _update_header=lambda: None,
        _show_market_dirty_feedback=lambda: None,
    )

    MainWindow.on_market_params_changed(window)

    assert calls == ["stale"]
    assert window.trades == [{"trade_id": "t1"}]
    assert window.events == [{"event_id": "e1"}]
