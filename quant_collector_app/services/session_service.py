from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

try:
    from display_names import session_display_name
except ImportError:  # pragma: no cover - package import path
    from ..display_names import session_display_name


MarketKey = tuple[str, str, str, str]


@dataclass(frozen=True)
class PerformanceSessionOption:
    session_id: str
    display_name: str
    symbol: str
    interval: str
    start_date_bjt: str
    end_date_bjt: str
    is_current: bool = False


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
    take_profit_pct: float | None
    stop_loss_pct: float | None


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
    take_profit_pct: float | None
    stop_loss_pct: float | None


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
    take_profit_pct: float | None
    stop_loss_pct: float | None


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


def _optional_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out) or out <= 0.0 or out > 100.0:
        return None
    return out


def _speed_slider_value(speed: Any) -> int:
    stops = (0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0)
    value = _float_or_default(speed, 1.0)
    return min(range(len(stops)), key=lambda index: abs(stops[index] - value))


def list_performance_session_options(
    storage: Any,
    *,
    current_session: dict[str, Any] | None = None,
) -> tuple[PerformanceSessionOption, ...]:
    """Return the shared, presentation-ready performance-session catalog."""

    reader = getattr(storage, "list_performance_sessions", None)
    if callable(reader):
        source_rows = reader()
    else:
        legacy_reader = getattr(storage, "fetch_table", None)
        source_rows = legacy_reader("sessions") if callable(legacy_reader) else []
    rows = [dict(row) for row in source_rows]
    current = dict(current_session or {})
    current_id = str(current.get("session_id") or "")
    if current_id:
        rows = [row for row in rows if str(row.get("session_id") or "") != current_id]
        rows.insert(0, current)
    label_counts: dict[str, int] = {}
    options: list[PerformanceSessionOption] = []
    for row in rows:
        session_id = str(row.get("session_id") or "")
        if not session_id:
            continue
        base_label = session_display_name(row)
        sequence = label_counts.get(base_label, 0) + 1
        label_counts[base_label] = sequence
        display_name = base_label if sequence == 1 else f"{base_label} · #{sequence}"
        options.append(
            PerformanceSessionOption(
                session_id=session_id,
                display_name=display_name,
                symbol=str(row.get("symbol") or "").upper(),
                interval=str(row.get("interval") or ""),
                start_date_bjt=str(row.get("start_date_bjt") or ""),
                end_date_bjt=str(row.get("end_date_bjt") or ""),
                is_current=session_id == current_id,
            )
        )
    return tuple(options)


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
    speed_slider_value = _speed_slider_value(row.get("speed"))
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
        take_profit_pct=_optional_float(row.get("take_profit_pct")),
        stop_loss_pct=_optional_float(row.get("stop_loss_pct")),
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
        "take_profit_pct": input.take_profit_pct,
        "stop_loss_pct": input.stop_loss_pct,
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
            take_profit_pct=input.take_profit_pct,
            stop_loss_pct=input.stop_loss_pct,
        )
    )
    storage.upsert_session(result.row)
    return result


def load_session_snapshot_state(storage: Any, session_id: str) -> SessionSnapshotState:
    session, trades, events = storage.load_session_snapshot(session_id)
    trade_by_id = {trade["trade_id"]: trade for trade in trades}
    event_by_id = {event["event_id"]: event for event in events}
    cursor_bar_index: int | None = None
    follow_latest: bool | None = None
    if session:
        raw_cursor = session.get("cursor_bar_index")
        try:
            cursor_bar_index = int(raw_cursor) if raw_cursor is not None else None
        except (TypeError, ValueError):
            cursor_bar_index = None
        if "follow_latest" in session and session.get("follow_latest") is not None:
            follow_latest = bool(session.get("follow_latest"))
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
    "PerformanceSessionOption",
    "SessionRestorePlan",
    "SessionSaveInput",
    "SessionSnapshotState",
    "SessionStateInput",
    "SessionStateResult",
    "build_session_restore_plan",
    "build_session_state",
    "load_session_snapshot_state",
    "list_performance_session_options",
    "save_session_state",
    "should_autosave",
]
