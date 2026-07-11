from __future__ import annotations

from tp_sl_engine import find_tp_sl_triggers, risk_prices_for_trade


def test_risk_prices_for_trade_snapshots_percentages_from_entry():
    long_prices = risk_prices_for_trade("LONG", 100.0, take_profit_pct=2.0, stop_loss_pct=1.0)
    short_prices = risk_prices_for_trade("SHORT", 100.0, take_profit_pct=2.0, stop_loss_pct=1.0)

    assert long_prices["take_profit_price"] == 102.0
    assert long_prices["stop_loss_price"] == 99.0
    assert short_prices["take_profit_price"] == 98.0
    assert short_prices["stop_loss_price"] == 101.0


def test_find_tp_sl_triggers_uses_target_price_and_stop_loss_priority():
    bars = [
        {"bar_index": 0, "high": 101.0, "low": 99.5},
        {"bar_index": 1, "high": 103.0, "low": 98.0},
    ]
    trades = [
        {
            "trade_id": "long_1",
            "status": "OPEN",
            "side": "LONG",
            "entry_bar_index": 0,
            "created_at": "1",
            "take_profit_price": 102.0,
            "stop_loss_price": 99.0,
        }
    ]

    triggers = find_tp_sl_triggers(bars, trades, from_bar_index=0, to_bar_index=1)

    assert len(triggers) == 1
    assert triggers[0]["trade_id"] == "long_1"
    assert triggers[0]["bar_index"] == 1
    assert triggers[0]["exit_reason"] == "STOP_LOSS"
    assert triggers[0]["exit_price"] == 99.0


def test_find_tp_sl_triggers_processes_multiple_positions_by_entry_time():
    bars = [
        {"bar_index": 1, "high": 110.0, "low": 90.0},
    ]
    trades = [
        {
            "trade_id": "newer_short",
            "status": "OPEN",
            "side": "SHORT",
            "entry_bar_index": 0,
            "created_at": "2",
            "take_profit_price": 95.0,
            "stop_loss_price": 105.0,
        },
        {
            "trade_id": "older_long",
            "status": "OPEN",
            "side": "LONG",
            "entry_bar_index": 0,
            "created_at": "1",
            "take_profit_price": 105.0,
            "stop_loss_price": 95.0,
        },
    ]

    triggers = find_tp_sl_triggers(bars, trades, from_bar_index=0, to_bar_index=1)

    assert [trigger["trade_id"] for trigger in triggers] == ["older_long", "newer_short"]
    assert [trigger["exit_reason"] for trigger in triggers] == ["STOP_LOSS", "STOP_LOSS"]
