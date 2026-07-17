from __future__ import annotations

import pytest


QtCore = pytest.importorskip("PySide6.QtCore")

from services.session_service import SessionRestorePlan
from views.session_ui_adapter import apply_session_restore_plan, build_session_save_input


class _ValueWidget:
    def __init__(self, value=None) -> None:
        self.value = value

    def setValue(self, value) -> None:
        self.value = value

    def setCurrentText(self, value: str) -> None:
        self.value = value


class _DateWidget:
    def __init__(self) -> None:
        self.value = None

    def setDate(self, value) -> None:
        self.value = value


class _ReadableValueWidget:
    def __init__(self, value) -> None:
        self._value = value

    def value(self):
        return self._value


def test_apply_session_restore_plan_maps_saved_session_to_visible_controls():
    symbols: list[str] = []
    fill_modes: list[str] = []
    window = type("SessionView", (), {})()
    window.follow_latest = False
    window._set_symbol_value = symbols.append
    window.intervalBox = _ValueWidget()
    window.startDate = _DateWidget()
    window.endDate = _DateWidget()
    window.speedSlider = _ValueWidget()
    window.initialEquitySpin = _ValueWidget()
    window.tradeNotionalSpin = _ValueWidget()
    window.feeBpsSpin = _ValueWidget()
    window.slippageBpsSpin = _ValueWidget()
    window.takeProfitPctSpin = _ValueWidget()
    window.stopLossPctSpin = _ValueWidget()
    window._set_fill_mode_value = fill_modes.append

    apply_session_restore_plan(
        window,
        SessionRestorePlan(
            session_id="sess_1",
            symbol="BTCUSDT",
            interval="5m",
            start_date_bjt="2026-01-02",
            end_date_bjt="2026-03-04",
            follow_latest=True,
            speed_slider_value=5,
            initial_equity=20_000.0,
            trade_notional=2_000.0,
            fee_bps=5.0,
            slippage_bps=2.0,
            fill_mode="CLOSE",
            take_profit_pct=3.0,
            stop_loss_pct=1.5,
        ),
    )

    assert symbols == ["BTCUSDT"]
    assert window.intervalBox.value == "5m"
    assert window.startDate.value.toString("yyyy-MM-dd") == "2026-01-02"
    assert window.endDate.value.toString("yyyy-MM-dd") == "2026-03-04"
    assert window.follow_latest is True
    assert window.speedSlider.value == 5
    assert window.initialEquitySpin.value == 20_000.0
    assert window.tradeNotionalSpin.value == 2_000.0
    assert window.feeBpsSpin.value == 5.0
    assert window.slippageBpsSpin.value == 2.0
    assert window.takeProfitPctSpin.value == 3.0
    assert window.stopLossPctSpin.value == 1.5
    assert fill_modes == ["CLOSE"]


def test_apply_session_restore_plan_keeps_missing_tp_sl_as_empty_values():
    window = type("SessionView", (), {})()
    window.follow_latest = False
    window._set_symbol_value = lambda _value: None
    window.intervalBox = _ValueWidget()
    window.startDate = _DateWidget()
    window.endDate = _DateWidget()
    window.speedSlider = _ValueWidget()
    window.initialEquitySpin = _ValueWidget()
    window.tradeNotionalSpin = _ValueWidget()
    window.feeBpsSpin = _ValueWidget()
    window.slippageBpsSpin = _ValueWidget()
    window.takeProfitPctSpin = _ValueWidget("old")
    window.stopLossPctSpin = _ValueWidget("old")
    window._set_fill_mode_value = lambda _value: None

    apply_session_restore_plan(
        window,
        SessionRestorePlan(
            session_id="sess_1",
            symbol="BTCUSDT",
            interval="1m",
            start_date_bjt=None,
            end_date_bjt=None,
            follow_latest=False,
            speed_slider_value=3,
            initial_equity=10_000.0,
            trade_notional=1_000.0,
            fee_bps=2.0,
            slippage_bps=1.0,
            fill_mode="CLOSE",
            take_profit_pct=None,
            stop_loss_pct=None,
        ),
    )

    assert window.takeProfitPctSpin.value is None
    assert window.stopLossPctSpin.value is None


def test_build_session_save_input_captures_current_view_and_sample_state():
    window = type("SessionView", (), {})()
    window.session_id = "sess_1"
    window._current_market_key = lambda: ("BTCUSDT", "5m", "2026-01-01", "2026-02-01")
    window._sample_market_key = ("BTCUSDT", "1m", "2026-01-01", "2026-02-01")
    window.trades = [{"trade_id": "trade_1"}]
    window.events = []
    window._is_display_interval_same_as_sample_interval = lambda: False
    window.cursor = 99
    window._sample_cursor_bar_index = 37
    window.follow_latest = False
    window.current_speed = lambda: 2.0
    window.initialEquitySpin = _ReadableValueWidget(20_000.0)
    window.tradeNotionalSpin = _ReadableValueWidget(2_000.0)
    window.feeBpsSpin = _ReadableValueWidget(5.0)
    window.slippageBpsSpin = _ReadableValueWidget(2.0)
    window._fill_mode_value = lambda: "CLOSE"
    window.take_profit_pct_value = lambda: 3.0
    window.stop_loss_pct_value = lambda: 1.5

    state = build_session_save_input(
        window,
        now_iso="2026-07-14T12:00:00+08:00",
        app_version="1.4.1",
    )

    assert state.session_id == "sess_1"
    assert state.current_market_key == ("BTCUSDT", "5m", "2026-01-01", "2026-02-01")
    assert state.sample_market_key == ("BTCUSDT", "1m", "2026-01-01", "2026-02-01")
    assert state.has_trade_samples is True
    assert state.display_interval_matches_sample is False
    assert state.cursor == 99
    assert state.sample_cursor_bar_index == 37
    assert state.follow_latest is False
    assert state.speed == 2.0
    assert state.initial_equity == 20_000.0
    assert state.trade_notional == 2_000.0
    assert state.fee_bps == 5.0
    assert state.slippage_bps == 2.0
    assert state.fill_mode == "CLOSE"
    assert state.take_profit_pct == 3.0
    assert state.stop_loss_pct == 1.5
