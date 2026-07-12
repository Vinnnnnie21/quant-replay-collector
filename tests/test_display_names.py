from display_names import session_display_name, trade_display_name


def test_display_names_hide_internal_identifiers_and_use_replay_time():
    session = {
        "session_id": "sess_random",
        "symbol": "btcusdt",
        "interval": "5m",
        "start_date_bjt": "2025-04-01",
        "end_date_bjt": "2025-05-01",
    }
    assert session_display_name(session) == "BTCUSDT · 5m · 2025-04-01—2025-05-01"
    assert "sess_random" not in session_display_name(session)
    trade = {"trade_id": "trd_random", "side": "LONG", "entry_bar_time_bjt": "2025-04-03T14:25:00+08:00"}
    assert trade_display_name(trade, 3) == "多 · 2025-04-03 14:25 · #03"
