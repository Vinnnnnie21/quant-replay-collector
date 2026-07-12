from __future__ import annotations


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


def trade_display_name(trade: dict, sequence: int | None = None) -> str:
    side = "多" if str(trade.get("side") or "").upper() == "LONG" else "空"
    time_text = str(trade.get("entry_bar_time_bjt") or "-").replace("T", " ")[:16]
    suffix = f" · #{int(sequence):02d}" if sequence is not None else ""
    return f"{side} · {time_text}{suffix}"


__all__ = ["session_display_name", "trade_display_name"]
