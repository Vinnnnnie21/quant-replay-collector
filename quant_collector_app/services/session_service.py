from __future__ import annotations

from dataclasses import dataclass
from typing import Any


MarketKey = tuple[str, str, str, str]


@dataclass(frozen=True)
class SessionStateInput:
    session_id: str
    current_market_key: MarketKey
    sample_market_key: MarketKey | None
    has_trade_samples: bool
    display_interval_matches_sample: bool
    cursor: int
    sample_cursor_bar_index: int
    follow_latest: bool
    speed: float
    latest_session: dict[str, Any] | None
    now_iso: str
    app_version: str
    initial_equity: float
    trade_notional: float
    fee_bps: float
    slippage_bps: float
    fill_mode: str


@dataclass(frozen=True)
class SessionSaveInput:
    session_id: str
    current_market_key: MarketKey
    sample_market_key: MarketKey | None
    has_trade_samples: bool
    display_interval_matches_sample: bool
    cursor: int
    sample_cursor_bar_index: int
    follow_latest: bool
    speed: float
    now_iso: str
    app_version: str
    initial_equity: float
    trade_notional: float
    fee_bps: float
    slippage_bps: float
    fill_mode: str


@dataclass(frozen=True)
class SessionStateResult:
    row: dict[str, Any]
    sample_cursor_bar_index: int


@dataclass(frozen=True)
class SessionRestorePlan:
    session_id: str
    symbol: str | None
    interval: str | None
    start_date_bjt: str | None
    end_date_bjt: str | None
    follow_latest: bool
    speed_slider_value: int
    initial_equity: float
    trade_notional: float
    fee_bps: float
    slippage_bps: float
    fill_mode: str


@dataclass(frozen=True)
class SessionSnapshotState:
    trades: list[dict[str, Any]]
    events: list[dict[str, Any]]
    trade_by_id: dict[str, dict[str, Any]]
    event_by_id: dict[str, dict[str, Any]]
    cursor_bar_index: int | None
    follow_latest: bool | None


def _optional_text(value: Any) -> str | None:
    text = "" if value is None else str(value).strip()
    return text or None


def _float_or_default(value: Any, default: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float(default)
    return out


def build_session_restore_plan(
    row: dict[str, Any],
    *,
    default_initial_equity: float,
    default_trade_notional: float,
    default_fee_bps: float,
    default_slippage_bps: float,
    default_fill_mode: str,
) -> SessionRestorePlan:
    session_id = _optional_text(row.get("session_id"))
    if not session_id:
        raise ValueError("session_id is required")
    speed = _float_or_default(row.get("speed"), 1.0)
    speed_slider_value = max(1, min(1000, int(speed * 10)))
    return SessionRestorePlan(
        session_id=session_id,
        symbol=_optional_text(row.get("symbol")),
        interval=_optional_text(row.get("interval")),
        start_date_bjt=_optional_text(row.get("start_date_bjt")),
        end_date_bjt=_optional_text(row.get("end_date_bjt")),
        follow_latest=bool(row.get("follow_latest", 0)),
        speed_slider_value=speed_slider_value,
        initial_equity=_float_or_default(row.get("initial_equity"), default_initial_equity),
        trade_notional=_float_or_default(row.get("trade_notional"), default_trade_notional),
        fee_bps=_float_or_default(row.get("fee_bps"), default_fee_bps),
        slippage_bps=_float_or_default(row.get("slippage_bps"), default_slippage_bps),
        fill_mode=_optional_text(row.get("fill_mode")) or str(default_fill_mode),
    )


def build_session_state(input: SessionStateInput) -> SessionStateResult:
    protects_samples = input.has_trade_samples and not input.display_interval_matches_sample
    sample_cursor = input.sample_cursor_bar_index if protects_samples else int(input.cursor)
    cursor_bar_index = sample_cursor if protects_samples else int(input.cursor)
    market_key = (
        input.sample_market_key
        if input.has_trade_samples and input.sample_market_key is not None
        else input.current_market_key
    )
    latest = input.latest_session or {}
    if latest.get("session_id") == input.session_id:
        last_opened_at = latest.get("last_opened_at") or input.now_iso
    else:
        last_opened_at = input.now_iso
    row = {
        "session_id": input.session_id,
        "symbol": market_key[0],
        "interval": market_key[1],
        "start_date_bjt": market_key[2],
        "end_date_bjt": market_key[3],
        "cursor_bar_index": cursor_bar_index,
        "follow_latest": 1 if input.follow_latest else 0,
        "speed": input.speed,
        "last_opened_at": last_opened_at,
        "last_saved_at": input.now_iso,
        "app_version": input.app_version,
        "initial_equity": input.initial_equity,
        "trade_notional": input.trade_notional,
        "fee_bps": input.fee_bps,
        "slippage_bps": input.slippage_bps,
        "fill_mode": input.fill_mode,
    }
    return SessionStateResult(row=row, sample_cursor_bar_index=sample_cursor)


def save_session_state(storage: Any, input: SessionSaveInput) -> SessionStateResult:
    latest_session = storage.get_latest_session()
    result = build_session_state(
        SessionStateInput(
            session_id=input.session_id,
            current_market_key=input.current_market_key,
            sample_market_key=input.sample_market_key,
            has_trade_samples=input.has_trade_samples,
            display_interval_matches_sample=input.display_interval_matches_sample,
            cursor=input.cursor,
            sample_cursor_bar_index=input.sample_cursor_bar_index,
            follow_latest=input.follow_latest,
            speed=input.speed,
            latest_session=latest_session,
            now_iso=input.now_iso,
            app_version=input.app_version,
            initial_equity=input.initial_equity,
            trade_notional=input.trade_notional,
            fee_bps=input.fee_bps,
            slippage_bps=input.slippage_bps,
            fill_mode=input.fill_mode,
        )
    )
    storage.upsert_session(result.row)
    return result


def load_session_snapshot_state(storage: Any, session_id: str) -> SessionSnapshotState:
    _session, trades, events = storage.load_session_snapshot(session_id)
    trade_by_id = {trade["trade_id"]: trade for trade in trades}
    event_by_id = {event["event_id"]: event for event in events}
    latest_session = storage.get_latest_session()
    cursor_bar_index: int | None = None
    follow_latest: bool | None = None
    if latest_session and latest_session.get("session_id") == session_id:
        cursor_bar_index = int(latest_session.get("cursor_bar_index") or 0)
        follow_latest = bool(latest_session.get("follow_latest") or 0)
    return SessionSnapshotState(
        trades=trades,
        events=events,
        trade_by_id=trade_by_id,
        event_by_id=event_by_id,
        cursor_bar_index=cursor_bar_index,
        follow_latest=follow_latest,
    )


def should_autosave(
    *,
    is_transaction_active: bool,
    is_playing: bool,
    now_msec: int,
    last_autosave_msec: int,
    playing_interval_msec: int = 10_000,
) -> bool:
    if is_transaction_active:
        return False
    if is_playing and int(now_msec) - int(last_autosave_msec) < int(playing_interval_msec):
        return False
    return True


__all__ = [
    "MarketKey",
    "SessionRestorePlan",
    "SessionSaveInput",
    "SessionSnapshotState",
    "SessionStateInput",
    "SessionStateResult",
    "build_session_restore_plan",
    "build_session_state",
    "load_session_snapshot_state",
    "save_session_state",
    "should_autosave",
]
