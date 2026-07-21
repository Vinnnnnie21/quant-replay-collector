from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

try:
    from research.exit_behavior_features import build_exit_position_state
    from services.entry_structural_similarity import load_entry_structural_snapshots
except ImportError:  # pragma: no cover - package import path
    from ..research.exit_behavior_features import build_exit_position_state
    from .entry_structural_similarity import load_entry_structural_snapshots


def load_exit_structural_context(
    storage: Any,
    event: dict[str, Any],
    intervals: tuple[str, str, str],
):
    """Load the one authoritative market-plus-holding state at the cutoff."""

    entry_time = _utc_ms(
        event.get("entry_real_time_bjt") or event.get("entry_bar_time_bjt")
    )
    cutoff = int(event["decision_cutoff_utc_ms"])
    rows = storage.fetch_klines_for_range(
        symbol=str(event["symbol"]),
        interval=str(event["decision_timeframe"]),
        start_time_utc_ms=entry_time,
        end_time_utc_ms=cutoff - 1,
    )
    closed_rows = tuple(
        row
        for row in rows
        if row.get("close_time_utc_ms") is not None
        and int(row["close_time_utc_ms"]) <= cutoff
    )
    position = build_exit_position_state(
        closed_rows,
        direction=str(event["direction"]),
        actual_entry_price=event.get("actual_entry_price"),
        entry_atr20=event.get("entry_atr20"),
        take_profit_status=event["take_profit_status"],
        take_profit_price=event.get("take_profit_price"),
        stop_loss_status=event["stop_loss_status"],
        stop_loss_price=event.get("stop_loss_price"),
    )
    market = load_entry_structural_snapshots(storage, event, intervals)
    return market, position


def _utc_ms(value: Any) -> int:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("position entry time must include an explicit timezone")
    return int(parsed.astimezone(UTC).timestamp() * 1_000)


__all__ = ["load_exit_structural_context"]
