from __future__ import annotations

try:
    from app_i18n import tr
except ImportError:  # pragma: no cover - package import path
    from .app_i18n import tr


def _date(value) -> str:
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else text or "-"


def session_display_name(session: dict | None = None, *, symbol="-", interval="-", start="-", end="-") -> str:
    row = session or {}
    symbol = str(row.get("symbol") or symbol or "-").upper()
    interval = str(row.get("interval") or interval or "-")
    start = _date(row.get("start_date_bjt") or start)
    end = _date(row.get("end_date_bjt") or end)
    return f"{symbol} · {interval} · {start}—{end}"


def trade_display_name(
    trade: dict,
    sequence: int | None = None,
    *,
    language: str = "zh_CN",
) -> str:
    side_value = str(trade.get("side") or "").upper()
    side = tr("ui.long", language) if side_value == "LONG" else tr("ui.short", language)
    time_text = str(trade.get("entry_bar_time_bjt") or "-").replace("T", " ")[:16]
    suffix = f" · #{int(sequence):02d}" if sequence is not None else ""
    return f"{side} · {time_text}{suffix}"


__all__ = ["session_display_name", "trade_display_name"]
