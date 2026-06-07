from __future__ import annotations

import math
from typing import Any


def fill_mode_label(mode: Any) -> str:
    labels = {
        "MID": "中间价",
        "CLOSE": "收盘价",
        "OPEN": "开盘价",
    }
    return labels.get(str(mode or "").upper(), str(mode or ""))


def side_label(side: Any) -> str:
    return {"LONG": "多", "SHORT": "空"}.get(str(side or "").upper(), str(side or ""))


def status_label(status: Any) -> str:
    return {"OPEN": "未平仓", "CLOSED": "已平仓"}.get(str(status or "").upper(), str(status or ""))


def event_type_label(event_type: Any) -> str:
    return {"OPEN": "开仓", "CLOSE": "平仓"}.get(str(event_type or "").upper(), str(event_type or ""))


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


def format_trade_detail(trade: dict[str, Any]) -> str:
    net_return = trade.get("net_return_pct") if trade.get("net_return_pct") is not None else trade.get("final_return_pct")
    lines = [
        "交易详情",
        "",
        f"交易ID        : {trade.get('trade_id') or ''}",
        f"方向          : {side_label(trade.get('side'))}",
        f"状态          : {status_label(trade.get('status'))}",
        f"入场时间      : {trade.get('entry_bar_time_bjt') or ''}",
        f"出场时间      : {trade.get('exit_bar_time_bjt') or ''}",
        f"入场成交价    : {fmt_num(trade.get('entry_fill_price') if trade.get('entry_fill_price') is not None else trade.get('entry_price_proxy'))}",
        f"出场成交价    : {fmt_num(trade.get('exit_fill_price') if trade.get('exit_fill_price') is not None else trade.get('exit_price_proxy'))}",
        f"代理收益      : {fmt_num(trade.get('final_return_pct'))}%",
        f"净收益        : {fmt_num(net_return)}%",
        f"净盈亏        : {fmt_num(trade.get('net_pnl_quote'))}",
        f"持仓K线数     : {trade.get('holding_bars') if trade.get('holding_bars') is not None else ''}",
        f"成交模式      : {fill_mode_label(trade.get('fill_mode'))}",
    ]
    return "\n".join(lines)


def format_event_detail(event: dict[str, Any]) -> str:
    labels = event.get("label_tags", [])
    if isinstance(labels, str):
        labels = [labels]
    lines = [
        "事件详情",
        "",
        f"事件ID        : {event.get('event_id') or ''}",
        f"交易ID        : {event.get('trade_id') or ''}",
        f"事件类型      : {event_type_label(event.get('event_type'))}",
        f"方向          : {side_label(event.get('side'))}",
        f"K线时间       : {event.get('bar_open_time_bjt') or ''}",
        f"代理价格      : {fmt_num(event.get('price_proxy'))}",
        f"标签          : {', '.join(labels)}",
        "",
        "备注",
        event.get("note") or "",
    ]
    return "\n".join(lines)
