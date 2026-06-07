from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from services.trade_use_cases import TradeUseCase


NOW = "2026-01-01T00:00:00+08:00"


class RecordingTradeController:
    def __init__(self, fail_commit: bool = False) -> None:
        self.fail_commit = fail_commit
        self.calls: list[tuple] = []

    def prepare_open(self, _df, _bar, **kwargs):
        self.calls.append(("prepare_open", kwargs["trade_id"], kwargs["event_id"]))
        return SimpleNamespace(
            trade_row={
                "trade_id": kwargs["trade_id"],
                "session_id": kwargs["session_id"],
                "symbol": kwargs["symbol"],
                "interval": kwargs["interval"],
                "side": kwargs["side"],
                "status": "OPEN",
                "entry_event_id": kwargs["event_id"],
                "entry_bar_index": kwargs["event_idx"],
            },
            event_row={
                "event_id": kwargs["event_id"],
                "trade_id": kwargs["trade_id"],
                "event_type": "OPEN",
                "side": kwargs["side"],
                "interval": kwargs["interval"],
            },
        )

    def commit_open(self, transaction) -> None:
        self.calls.append(("commit_open", transaction.trade_row["trade_id"], transaction.event_row["event_id"]))
        if self.fail_commit:
            raise RuntimeError("commit failed")

    def undo_open(self, transaction) -> None:
        self.calls.append(("undo_open", transaction.trade_row["trade_id"], transaction.event_row["event_id"]))

    def prepare_close(self, _df, _bar, **kwargs):
        trade = kwargs["trade"]
        self.calls.append(("prepare_close", trade["trade_id"], kwargs["event_id"]))
        return SimpleNamespace(
            original_trade=dict(trade),
            event_row={
                "event_id": kwargs["event_id"],
                "trade_id": trade["trade_id"],
                "event_type": "CLOSE",
                "side": trade["side"],
                "interval": trade["interval"],
            },
            close_update={
                "trade_id": trade["trade_id"],
                "status": "CLOSED",
                "exit_event_id": kwargs["event_id"],
                "exit_bar_index": kwargs["event_idx"],
            },
        )

    def commit_close(self, transaction) -> None:
        self.calls.append(("commit_close", transaction.close_update["trade_id"], transaction.event_row["event_id"]))
        if self.fail_commit:
            raise RuntimeError("commit failed")

    def undo_close(self, transaction, updated_at: str) -> None:
        self.calls.append(("undo_close", transaction.close_update["trade_id"], transaction.event_row["event_id"], updated_at))


def _df():
    return pd.DataFrame(
        [
            {
                "bar_index": 10,
                "open_time_bjt": "2026-01-01T00:00:00+08:00",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1000.0,
            }
        ]
    )


def _open_trade():
    return {
        "trade_id": "trd_1",
        "session_id": "sess_1",
        "symbol": "BTCUSDT",
        "interval": "5m",
        "side": "LONG",
        "status": "OPEN",
        "entry_event_id": "evt_open",
        "entry_bar_index": 10,
    }


def test_trade_use_case_open_success_returns_payload():
    controller = RecordingTradeController()
    use_case = TradeUseCase(controller)
    frame = _df()

    result = use_case.open_trade(
        frame,
        frame.iloc[0],
        event_idx=10,
        session_id="sess_1",
        symbol="BTCUSDT",
        interval="5m",
        side="LONG",
        event_id="evt_1",
        trade_id="trd_1",
        label_tags=["deep-v"],
        note="open",
        settings=object(),
        now_iso=NOW,
    )

    assert result.success is True
    assert result.trade_id == "trd_1"
    assert result.event_id == "evt_1"
    assert result.trade["status"] == "OPEN"
    assert result.undo_payload.trade_id == "trd_1"
    assert result.redo_payload is result.undo_payload
    assert [call[0] for call in controller.calls] == ["prepare_open", "commit_open"]


def test_trade_use_case_close_success_returns_payload():
    controller = RecordingTradeController()
    use_case = TradeUseCase(controller)
    frame = _df()

    result = use_case.close_trade(
        frame,
        frame.iloc[0],
        event_idx=12,
        trade=_open_trade(),
        event_id="evt_close",
        label_tags=["exit"],
        note="close",
        fallback_settings=object(),
        now_iso=NOW,
    )

    assert result.success is True
    assert result.trade_id == "trd_1"
    assert result.event_id == "evt_close"
    assert result.trade_update["status"] == "CLOSED"
    assert result.undo_payload.original_trade["status"] == "OPEN"
    assert [call[0] for call in controller.calls] == ["prepare_close", "commit_close"]


def test_trade_use_case_missing_current_bar_fails_without_commit():
    controller = RecordingTradeController()
    use_case = TradeUseCase(controller)

    result = use_case.open_trade(
        _df(),
        None,
        event_idx=10,
        session_id="sess_1",
        symbol="BTCUSDT",
        interval="5m",
        side="LONG",
        event_id="evt_1",
        trade_id="trd_1",
        label_tags=[],
        note="",
        settings=object(),
        now_iso=NOW,
    )

    assert result.success is False
    assert result.error is None
    assert controller.calls == []


def test_trade_use_case_missing_session_fails_without_commit():
    controller = RecordingTradeController()
    use_case = TradeUseCase(controller)
    frame = _df()

    result = use_case.open_trade(
        frame,
        frame.iloc[0],
        event_idx=10,
        session_id="",
        symbol="BTCUSDT",
        interval="5m",
        side="LONG",
        event_id="evt_1",
        trade_id="trd_1",
        label_tags=[],
        note="",
        settings=object(),
        now_iso=NOW,
    )

    assert result.success is False
    assert "session_id" in result.message
    assert controller.calls == []


def test_trade_use_case_invalid_current_price_fails_without_commit():
    controller = RecordingTradeController()
    use_case = TradeUseCase(controller)
    frame = _df()
    bad_bar = frame.iloc[0].copy()
    bad_bar["high"] = float("nan")

    result = use_case.open_trade(
        frame,
        bad_bar,
        event_idx=10,
        session_id="sess_1",
        symbol="BTCUSDT",
        interval="5m",
        side="LONG",
        event_id="evt_1",
        trade_id="trd_1",
        label_tags=[],
        note="",
        settings=object(),
        now_iso=NOW,
    )

    assert result.success is False
    assert "current price" in result.message
    assert controller.calls == []


def test_trade_use_case_close_invalid_current_price_fails_without_commit():
    controller = RecordingTradeController()
    use_case = TradeUseCase(controller)
    frame = _df()
    bad_bar = frame.iloc[0].copy()
    bad_bar["low"] = None

    result = use_case.close_trade(
        frame,
        bad_bar,
        event_idx=12,
        trade=_open_trade(),
        event_id="evt_close",
        label_tags=[],
        note="",
        fallback_settings=object(),
        now_iso=NOW,
    )

    assert result.success is False
    assert "current price" in result.message
    assert controller.calls == []


def test_trade_use_case_close_without_open_position_fails():
    controller = RecordingTradeController()
    use_case = TradeUseCase(controller)
    frame = _df()

    result = use_case.close_trade(
        frame,
        frame.iloc[0],
        event_idx=12,
        trade=None,
        event_id="evt_close",
        label_tags=[],
        note="",
        fallback_settings=object(),
        now_iso=NOW,
    )

    assert result.success is False
    assert "open trade" in result.message
    assert controller.calls == []


def test_trade_use_case_exception_returns_error_without_state_mutation():
    controller = RecordingTradeController(fail_commit=True)
    use_case = TradeUseCase(controller)
    frame = _df()
    trade = _open_trade()

    result = use_case.close_trade(
        frame,
        frame.iloc[0],
        event_idx=12,
        trade=trade,
        event_id="evt_close",
        label_tags=[],
        note="",
        fallback_settings=object(),
        now_iso=NOW,
    )

    assert result.success is False
    assert isinstance(result.error, RuntimeError)
    assert trade["status"] == "OPEN"
    assert [call[0] for call in controller.calls] == ["prepare_close", "commit_close"]


def test_trade_use_case_undo_and_redo_payloads_call_controller():
    controller = RecordingTradeController()
    use_case = TradeUseCase(controller)
    frame = _df()
    open_result = use_case.open_trade(
        frame,
        frame.iloc[0],
        event_idx=10,
        session_id="sess_1",
        symbol="BTCUSDT",
        interval="5m",
        side="LONG",
        event_id="evt_1",
        trade_id="trd_1",
        label_tags=[],
        note="",
        settings=object(),
        now_iso=NOW,
    )

    use_case.undo_open(open_result.undo_payload)
    use_case.redo_open(open_result.redo_payload)

    assert [call[0] for call in controller.calls] == ["prepare_open", "commit_open", "undo_open", "commit_open"]


def test_trade_use_case_close_undo_and_redo_payloads_call_controller():
    controller = RecordingTradeController()
    use_case = TradeUseCase(controller)
    frame = _df()
    result = use_case.close_trade(
        frame,
        frame.iloc[0],
        event_idx=12,
        trade=_open_trade(),
        event_id="evt_close",
        label_tags=[],
        note="",
        fallback_settings=object(),
        now_iso=NOW,
    )

    use_case.undo_close(result.undo_payload, "2026-01-01T00:01:00+08:00")
    use_case.redo_close(result.redo_payload)

    assert [call[0] for call in controller.calls] == ["prepare_close", "commit_close", "undo_close", "commit_close"]
    assert controller.calls[2] == ("undo_close", "trd_1", "evt_close", "2026-01-01T00:01:00+08:00")
