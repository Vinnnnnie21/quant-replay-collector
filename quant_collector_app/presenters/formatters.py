from __future__ import annotations

import math
import unicodedata
from typing import Any

try:
    from app_i18n import tr
except ImportError:  # pragma: no cover - package import path
    from ..app_i18n import tr


_EVENT_TAG_KEYS = {
    "深V反转": "deep_v_reversal",
    "长下影": "long_lower_wick",
    "放量": "volume_spike",
    "恐慌针": "panic_wick",
    "跌破前低后收回": "reclaim_prior_low",
    "二次探底": "second_bottom",
    "假突破": "false_breakout",
    "加速衰竭": "acceleration_exhaustion",
    "主观高确定性": "high_conviction",
    "其他": "other",
}


def fill_mode_label(mode: Any, language: str = "zh_CN") -> str:
    value = str(mode or "").upper()
    key = {"MID": "mid", "CLOSE": "close", "OPEN": "open"}.get(value)
    return tr(f"ui.fill_mode.{key}", language) if key else str(mode or "")


def side_label(side: Any, language: str = "zh_CN") -> str:
    value = str(side or "").upper()
    key = {"LONG": "ui.long", "SHORT": "ui.short"}.get(value)
    return tr(key, language) if key else str(side or "")


def status_label(status: Any, language: str = "zh_CN") -> str:
    value = str(status or "").upper()
    key = {"OPEN": "ui.open_status", "CLOSED": "ui.closed_status"}.get(value)
    return tr(key, language) if key else str(status or "")


def event_type_label(event_type: Any, language: str = "zh_CN") -> str:
    value = str(event_type or "").upper()
    key = {"OPEN": "ui.open", "CLOSE": "ui.close"}.get(value)
    return tr(key, language) if key else str(event_type or "")


def event_tag_label(tag: Any, language: str = "zh_CN") -> str:
    value = str(tag or "")
    key = _EVENT_TAG_KEYS.get(value)
    return tr(f"ui.event_tag.{key}", language) if key else value


def short_id(value: Any, keep: int = 8) -> str:
    text = "" if value is None else str(value)
    if len(text) <= keep + 4:
        return text
    prefix = text.split("_", 1)[0]
    if "_" in text and len(prefix) <= 5:
        return f"{prefix}_{text[-keep:]}"
    return text[-keep:]


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def fmt_num(value: Any) -> str:
    if value is None:
        return ""
    try:
        v = float(value)
        return f"{v:.6f}" if abs(v) < 1000 else f"{v:.2f}"
    except Exception:
        return str(value)


def _visual_width(value: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in value)


def _detail_line(label: str, value: Any) -> str:
    padding = " " * max(1, 14 - _visual_width(label))
    return f"{label}{padding}: {value}"


def format_trade_detail(trade: dict[str, Any], language: str = "zh_CN") -> str:
    net_return = trade.get("net_return_pct") if trade.get("net_return_pct") is not None else trade.get("final_return_pct")
    lines = [
        tr("detail.trade_title", language),
        "",
        _detail_line(tr("ui.trade_id", language), trade.get("trade_id") or ""),
        _detail_line(tr("ui.side", language), side_label(trade.get("side"), language)),
        _detail_line(tr("ui.status", language), status_label(trade.get("status"), language)),
        _detail_line(tr("ui.entry_time", language), trade.get("entry_bar_time_bjt") or ""),
        _detail_line(tr("ui.exit_time", language), trade.get("exit_bar_time_bjt") or ""),
        _detail_line(
            tr("ui.entry_fill", language),
            fmt_num(trade.get("entry_fill_price") if trade.get("entry_fill_price") is not None else trade.get("entry_price_proxy")),
        ),
        _detail_line(
            tr("ui.exit_fill", language),
            fmt_num(trade.get("exit_fill_price") if trade.get("exit_fill_price") is not None else trade.get("exit_price_proxy")),
        ),
        _detail_line(tr("detail.proxy_return", language), f"{fmt_num(trade.get('final_return_pct'))}%"),
        _detail_line(tr("detail.net_return", language), f"{fmt_num(net_return)}%"),
        _detail_line(tr("ui.net_pnl", language), fmt_num(trade.get("net_pnl_quote"))),
        _detail_line(
            tr("detail.holding_bars", language),
            trade.get("holding_bars") if trade.get("holding_bars") is not None else "",
        ),
        _detail_line(tr("ui.execution_mode", language), fill_mode_label(trade.get("fill_mode"), language)),
    ]
    return "\n".join(lines)


def format_event_detail(event: dict[str, Any], language: str = "zh_CN") -> str:
    labels = event.get("label_tags", [])
    if isinstance(labels, str):
        labels = [labels]
    lines = [
        tr("detail.event_title", language),
        "",
        _detail_line(tr("ui.event_id", language), event.get("event_id") or ""),
        _detail_line(tr("ui.trade_id", language), event.get("trade_id") or ""),
        _detail_line(tr("detail.event_type", language), event_type_label(event.get("event_type"), language)),
        _detail_line(tr("ui.side", language), side_label(event.get("side"), language)),
        _detail_line(tr("ui.bar_time", language), event.get("bar_open_time_bjt") or ""),
        _detail_line(tr("ui.proxy_price", language), fmt_num(event.get("price_proxy"))),
        _detail_line(tr("ui.tags", language), ", ".join(event_tag_label(label, language) for label in labels)),
        "",
        tr("ui.note", language),
        event.get("note") or "",
    ]
    return "\n".join(lines)
