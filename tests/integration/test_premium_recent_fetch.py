from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from main_app import MainWindow
from premium_controller import PremiumController
from storage import StorageManager
from task_lifecycle import BackgroundTaskLifecycle, TaskState


def _premium_row(index: int) -> dict:
    return {
        "sample_time_bjt": f"2024-04-01T{index // 60:02d}:{index % 60:02d}:00+08:00",
        "p2p_buy_price_cny": 7.0,
        "p2p_sell_price_cny": 7.1,
        "p2p_avg_price_cny": 7.05,
        "usd_cny_rate": 7.0,
        "buy_premium_pct": float(index),
        "sell_premium_pct": float(index) + 0.1,
        "avg_premium_pct": float(index) + 0.05,
        "premium_pct": float(index) + 0.05,
        "fx_source": "test",
        "sample_status": "OK",
        "error_message": None,
    }


def test_storage_fetch_recent_premium_samples_limits_rows(tmp_path):
    storage = StorageManager(tmp_path / "premium.db")
    for index in range(300):
        storage.insert_premium_sample(_premium_row(index))

    rows = storage.fetch_recent_premium_samples(limit=240)

    assert len(rows) == 240
    assert rows[0]["buy_premium_pct"] == 60.0
    assert rows[-1]["buy_premium_pct"] == 299.0


class _Curve:
    def __init__(self) -> None:
        self.values = None

    def setData(self, x, y):
        self.values = (list(x), list(y))


def test_premium_plot_uses_recent_fetch_not_full_table():
    calls: list[str] = []
    rows = [_premium_row(index) for index in range(10)]
    window = SimpleNamespace(
        storage=SimpleNamespace(
            fetch_recent_premium_samples=lambda limit=240: calls.append(f"recent:{limit}") or rows,
            fetch_table=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("full table read")),
        ),
        premiumBuyCurve=_Curve(),
        premiumSellCurve=_Curve(),
        premiumAvgCurve=_Curve(),
        _log_slow_operation=lambda *_args, **_kwargs: None,
    )

    MainWindow._refresh_premium_plot(window)

    assert calls == ["recent:240"]
    assert window.premiumBuyCurve.values[1][-1] == 9.0


def test_request_premium_sample_registers_the_background_task() -> None:
    emitted: list[bool] = []
    lifecycle = BackgroundTaskLifecycle()
    window = SimpleNamespace(
        premium_controller=PremiumController(),
        premium_worker=SimpleNamespace(request_stop=lambda: None),
        requestPremium=SimpleNamespace(emit=lambda: emitted.append(True)),
        task_lifecycle=lifecycle,
    )

    MainWindow.request_premium_sample(window)

    assert emitted == [True]
    assert lifecycle.state("premium_sample") is TaskState.RUNNING


def test_request_premium_sample_after_shutdown_does_not_change_state_or_emit() -> None:
    lifecycle = BackgroundTaskLifecycle()
    lifecycle.begin_shutdown()
    emitted: list[bool] = []
    controller = PremiumController()
    window = SimpleNamespace(
        premium_controller=controller,
        premium_worker=SimpleNamespace(request_stop=lambda: None),
        requestPremium=SimpleNamespace(emit=lambda: emitted.append(True)),
        task_lifecycle=lifecycle,
    )

    MainWindow.request_premium_sample(window)

    assert controller.inflight is False
    assert emitted == []
    assert lifecycle.state("premium_sample") is None


def test_completed_premium_sample_finishes_the_registered_task() -> None:
    lifecycle = BackgroundTaskLifecycle()
    lifecycle.start("premium_sample")
    window = SimpleNamespace(
        premium_controller=PremiumController(),
        storage=SimpleNamespace(insert_premium_sample=lambda _row: None),
        premiumStatus=SimpleNamespace(setText=lambda _text: None),
        premiumStats=SimpleNamespace(setPlainText=lambda _text: None),
        _set_widget_role=lambda *_args: None,
        _refresh_premium_plot=lambda: None,
        task_lifecycle=lifecycle,
    )

    MainWindow.on_premium_sample(window, _premium_row(1))

    assert lifecycle.state("premium_sample") is TaskState.COMPLETED


def test_cancelled_premium_sample_releases_the_task() -> None:
    lifecycle = BackgroundTaskLifecycle()
    lifecycle.start("premium_sample")
    lifecycle.request_stop_all()
    controller = PremiumController()
    controller.inflight = True
    window = SimpleNamespace(
        premium_controller=controller,
        task_lifecycle=lifecycle,
    )

    MainWindow.on_premium_cancelled(window)

    assert controller.inflight is False
    assert lifecycle.state("premium_sample") is TaskState.COMPLETED
