from __future__ import annotations

from services.session_service import (
    SessionSaveInput,
    SessionStateInput,
    build_session_restore_plan,
    build_session_state,
    load_session_snapshot_state,
    save_session_state,
    should_autosave,
)


def test_build_session_state_uses_current_market_when_no_trade_samples():
    result = build_session_state(
        SessionStateInput(
            session_id="sess_1",
            current_market_key=("BTCUSDT", "5m", "2024-04-01", "2024-05-01"),
            sample_market_key=None,
            has_trade_samples=False,
            display_interval_matches_sample=True,
            cursor=42,
            sample_cursor_bar_index=7,
            follow_latest=True,
            speed=6.3,
            latest_session=None,
            now_iso="2026-06-03T12:00:00+08:00",
            app_version="1.4.1",
            initial_equity=10_000.0,
            trade_notional=1_000.0,
            fee_bps=4.0,
            slippage_bps=1.0,
            fill_mode="MID",
        )
    )

    assert result.sample_cursor_bar_index == 42
    assert result.row["symbol"] == "BTCUSDT"
    assert result.row["interval"] == "5m"
    assert result.row["cursor_bar_index"] == 42
    assert result.row["last_opened_at"] == "2026-06-03T12:00:00+08:00"
    assert result.row["follow_latest"] == 1


def test_build_session_state_preserves_sample_interval_cursor_when_display_interval_differs():
    result = build_session_state(
        SessionStateInput(
            session_id="sess_1",
            current_market_key=("BTCUSDT", "5m", "2024-04-01", "2024-05-01"),
            sample_market_key=("BTCUSDT", "1m", "2024-04-01", "2024-05-01"),
            has_trade_samples=True,
            display_interval_matches_sample=False,
            cursor=99,
            sample_cursor_bar_index=37,
            follow_latest=False,
            speed=1.0,
            latest_session={"session_id": "sess_1", "last_opened_at": "old-opened"},
            now_iso="new-now",
            app_version="1.4.1",
            initial_equity=10_000.0,
            trade_notional=1_000.0,
            fee_bps=4.0,
            slippage_bps=1.0,
            fill_mode="MID",
        )
    )

    assert result.sample_cursor_bar_index == 37
    assert result.row["symbol"] == "BTCUSDT"
    assert result.row["interval"] == "1m"
    assert result.row["cursor_bar_index"] == 37
    assert result.row["last_opened_at"] == "old-opened"
    assert result.row["follow_latest"] == 0


def test_save_session_state_reads_latest_session_and_writes_row():
    class Storage:
        def __init__(self) -> None:
            self.written: list[dict] = []

        def get_latest_session(self):
            return {"session_id": "sess_1", "last_opened_at": "old-opened"}

        def upsert_session(self, row):
            self.written.append(row)

    storage = Storage()
    result = save_session_state(
        storage,
        SessionSaveInput(
            session_id="sess_1",
            current_market_key=("BTCUSDT", "5m", "2024-04-01", "2024-05-01"),
            sample_market_key=("BTCUSDT", "1m", "2024-04-01", "2024-05-01"),
            has_trade_samples=True,
            display_interval_matches_sample=False,
            cursor=99,
            sample_cursor_bar_index=37,
            follow_latest=False,
            speed=1.0,
            now_iso="new-now",
            app_version="1.4.1",
            initial_equity=10_000.0,
            trade_notional=1_000.0,
            fee_bps=4.0,
            slippage_bps=1.0,
            fill_mode="MID",
        ),
    )

    assert result.sample_cursor_bar_index == 37
    assert len(storage.written) == 1
    assert storage.written[0]["interval"] == "1m"
    assert storage.written[0]["cursor_bar_index"] == 37
    assert storage.written[0]["last_opened_at"] == "old-opened"


def test_load_session_snapshot_state_builds_memory_indexes_and_cursor_restore():
    trade = {"trade_id": "trd_1", "status": "OPEN"}
    event = {"event_id": "evt_1", "trade_id": "trd_1"}

    class Storage:
        def load_session_snapshot(self, session_id):
            assert session_id == "sess_1"
            return {"session_id": "sess_1"}, [trade], [event]

        def get_latest_session(self):
            return {"session_id": "sess_1", "cursor_bar_index": 42, "follow_latest": 1}

    state = load_session_snapshot_state(Storage(), "sess_1")

    assert state.trades == [trade]
    assert state.events == [event]
    assert state.trade_by_id == {"trd_1": trade}
    assert state.event_by_id == {"evt_1": event}
    assert state.cursor_bar_index == 42
    assert state.follow_latest is True


def test_load_session_snapshot_state_ignores_latest_cursor_for_other_session():
    class Storage:
        def load_session_snapshot(self, _session_id):
            return {}, [], []

        def get_latest_session(self):
            return {"session_id": "other", "cursor_bar_index": 99, "follow_latest": 1}

    state = load_session_snapshot_state(Storage(), "sess_1")

    assert state.cursor_bar_index is None
    assert state.follow_latest is None


def test_should_autosave_skips_transactions_and_throttles_while_playing():
    assert should_autosave(
        is_transaction_active=True,
        is_playing=False,
        now_msec=20_000,
        last_autosave_msec=0,
    ) is False
    assert should_autosave(
        is_transaction_active=False,
        is_playing=True,
        now_msec=5_000,
        last_autosave_msec=0,
    ) is False
    assert should_autosave(
        is_transaction_active=False,
        is_playing=True,
        now_msec=11_000,
        last_autosave_msec=0,
    ) is True
    assert should_autosave(
        is_transaction_active=False,
        is_playing=False,
        now_msec=1_000,
        last_autosave_msec=999,
    ) is True


def test_build_session_restore_plan_maps_saved_values_and_slider_speed():
    plan = build_session_restore_plan(
        {
            "session_id": "sess_1",
            "symbol": "BTCUSDT",
            "interval": "5m",
            "start_date_bjt": "2024-04-01",
            "end_date_bjt": "2024-05-01",
            "follow_latest": 1,
            "speed": 6.3,
            "initial_equity": 20_000,
            "trade_notional": 2_000,
            "fee_bps": 5,
            "slippage_bps": 2,
            "fill_mode": "CLOSE",
        },
        default_initial_equity=10_000,
        default_trade_notional=1_000,
        default_fee_bps=4,
        default_slippage_bps=1,
        default_fill_mode="MID",
    )

    assert plan.session_id == "sess_1"
    assert plan.symbol == "BTCUSDT"
    assert plan.interval == "5m"
    assert plan.start_date_bjt == "2024-04-01"
    assert plan.end_date_bjt == "2024-05-01"
    assert plan.follow_latest is True
    assert plan.speed_slider_value == 63
    assert plan.initial_equity == 20_000.0
    assert plan.trade_notional == 2_000.0
    assert plan.fee_bps == 5.0
    assert plan.slippage_bps == 2.0
    assert plan.fill_mode == "CLOSE"


def test_build_session_restore_plan_uses_defaults_for_missing_or_invalid_values():
    plan = build_session_restore_plan(
        {
            "session_id": "sess_1",
            "speed": "bad",
            "initial_equity": None,
            "trade_notional": "",
            "fee_bps": "bad",
            "slippage_bps": None,
            "fill_mode": "",
        },
        default_initial_equity=10_000,
        default_trade_notional=1_000,
        default_fee_bps=4,
        default_slippage_bps=1,
        default_fill_mode="MID",
    )

    assert plan.symbol is None
    assert plan.interval is None
    assert plan.speed_slider_value == 10
    assert plan.initial_equity == 10_000.0
    assert plan.trade_notional == 1_000.0
    assert plan.fee_bps == 4.0
    assert plan.slippage_bps == 1.0
    assert plan.fill_mode == "MID"
