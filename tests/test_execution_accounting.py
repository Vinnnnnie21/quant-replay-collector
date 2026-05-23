from __future__ import annotations

import pytest

from accounting import build_equity_curve
from execution import ExecutionSettings, fill_price, trade_outcome


def bar(open_=100.0, high=102.0, low=98.0, close=101.0):
    return {"open": open_, "high": high, "low": low, "close": close}


def test_fill_price_mid_mode_applies_adverse_slippage():
    settings = ExecutionSettings(fill_mode="MID", fee_bps=4.0, slippage_bps=10.0, notional_quote=1000.0)

    raw_buy, fill_buy = fill_price(bar(), "LONG", "OPEN", settings)
    raw_sell, fill_sell = fill_price(bar(), "LONG", "CLOSE", settings)

    assert raw_buy == pytest.approx(100.0)
    assert fill_buy == pytest.approx(100.1)
    assert raw_sell == pytest.approx(100.0)
    assert fill_sell == pytest.approx(99.9)


def test_trade_outcome_returns_net_after_fees():
    settings = ExecutionSettings(fill_mode="MID", fee_bps=4.0, slippage_bps=0.0, notional_quote=1000.0)

    outcome = trade_outcome("LONG", 100.0, 103.0, settings)

    assert outcome["quantity"] == pytest.approx(10.0)
    assert outcome["gross_pnl_quote"] == pytest.approx(30.0)
    assert outcome["entry_fee_quote"] == pytest.approx(0.4)
    assert outcome["exit_fee_quote"] == pytest.approx(0.412)
    assert outcome["net_pnl_quote"] == pytest.approx(29.188)
    assert outcome["gross_return_pct"] == pytest.approx(3.0)
    assert outcome["net_return_pct"] == pytest.approx(2.9188)


def test_equity_curve_uses_net_pnl_and_drawdown():
    trades = [
        {"trade_id": "trd_1", "status": "CLOSED", "net_pnl_quote": 100.0, "gross_pnl_quote": 105.0, "updated_at": "1"},
        {"trade_id": "trd_2", "status": "CLOSED", "net_pnl_quote": -50.0, "gross_pnl_quote": -45.0, "updated_at": "2"},
        {"trade_id": "trd_3", "status": "OPEN", "net_pnl_quote": 999.0, "updated_at": "3"},
    ]

    rows = build_equity_curve(trades, "sess_1", initial_equity=1000.0, default_notional=1000.0)

    assert len(rows) == 2
    assert rows[0]["equity_before"] == pytest.approx(1000.0)
    assert rows[0]["equity_after"] == pytest.approx(1100.0)
    assert rows[1]["equity_after"] == pytest.approx(1050.0)
    assert rows[1]["drawdown_pct"] == pytest.approx(-4.54545454545)
