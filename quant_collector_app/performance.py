from __future__ import annotations

import math
from typing import Any


SIDES = ("LONG", "SHORT")
SIDE_LABELS = {"LONG": "多头", "SHORT": "空头"}


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _status(trade: dict[str, Any]) -> str:
    return str(trade.get("status") or "").upper()


def _side(trade: dict[str, Any]) -> str:
    return str(trade.get("side") or "").upper()


def _trade_sort_key(trade: dict[str, Any]) -> tuple[str, str]:
    return (
        str(
            trade.get("updated_at")
            or trade.get("exit_real_time_bjt")
            or trade.get("exit_bar_time_bjt")
            or trade.get("created_at")
            or trade.get("entry_real_time_bjt")
            or trade.get("entry_bar_time_bjt")
            or ""
        ),
        str(trade.get("trade_id") or ""),
    )


def _trade_return_pct(trade: dict[str, Any]) -> float | None:
    value = _safe_float(trade.get("net_return_pct"))
    if value is not None:
        return value
    return _safe_float(trade.get("final_return_pct"))


def _stats_for_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [t for t in trades if _status(t) == "CLOSED"]
    open_ = [t for t in trades if _status(t) == "OPEN"]
    returns = [
        value
        for value in (_trade_return_pct(t) for t in closed)
        if value is not None
    ]
    holding_bars = [
        float(value)
        for value in (_safe_int(t.get("holding_bars")) for t in closed)
        if value is not None
    ]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    avg_win = _mean(wins)
    avg_loss = _mean(losses)
    max_consecutive_wins = 0
    max_consecutive_losses = 0
    cur_wins = 0
    cur_losses = 0
    for value in returns:
        if value > 0:
            cur_wins += 1
            cur_losses = 0
        elif value < 0:
            cur_losses += 1
            cur_wins = 0
        else:
            cur_wins = 0
            cur_losses = 0
        max_consecutive_wins = max(max_consecutive_wins, cur_wins)
        max_consecutive_losses = max(max_consecutive_losses, cur_losses)
    return {
        "total_trades": len(trades),
        "closed_trades": len(closed),
        "open_trades": len(open_),
        "win_rate_pct": (len(wins) / len(returns) * 100.0) if returns else None,
        "average_return_pct": _mean(returns),
        "max_profit_pct": max(wins) if wins else None,
        "max_loss_pct": min(losses) if losses else None,
        "average_holding_bars": _mean(holding_bars),
        "profit_factor": (gross_profit / gross_loss) if gross_loss else None,
        "expectancy_pct": _mean(returns),
        "average_win_pct": avg_win,
        "average_loss_pct": avg_loss,
        "payoff_ratio": (avg_win / abs(avg_loss)) if avg_win is not None and avg_loss not in (None, 0) else None,
        "max_consecutive_wins": max_consecutive_wins,
        "max_consecutive_losses": max_consecutive_losses,
    }


def _recent_trade_summary(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "recent_trade_id": None,
            "recent_trade_side": None,
            "recent_trade_status": None,
            "recent_trade_return_pct": None,
            "recent_trade_holding_bars": None,
            "recent_trade_result": "暂无交易",
        }

    closed_trades = [t for t in trades if _status(t) == "CLOSED"]
    trade = max(closed_trades, key=_trade_sort_key) if closed_trades else max(trades, key=_trade_sort_key)
    status = _status(trade) or None
    side = _side(trade) or None
    ret = _trade_return_pct(trade)
    holding = _safe_int(trade.get("holding_bars"))
    trade_id = trade.get("trade_id")

    if status == "CLOSED" and ret is not None:
        result = f"{SIDE_LABELS.get(side, side or '-')} 已平仓，收益 {ret:+.4f}%"
        if holding is not None:
            result += f"，持仓 {holding} 根K线"
    elif status == "OPEN":
        result = f"暂无已平仓结果；最近交易为 {SIDE_LABELS.get(side, side or '-')} 未平仓"
        entry_time = trade.get("entry_bar_time_bjt")
        if entry_time:
            result += f"，入场 {entry_time}"
    else:
        result = f"{SIDE_LABELS.get(side, side or '-')} {status or '未知'}"

    return {
        "recent_trade_id": trade_id,
        "recent_trade_side": side,
        "recent_trade_status": status,
        "recent_trade_return_pct": ret,
        "recent_trade_holding_bars": holding,
        "recent_trade_result": result,
    }


def _equity_metrics(equity_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None, initial_equity: float | None):
    rows = [dict(r) for r in (equity_rows or [])]
    if not rows:
        return {
            "initial_equity": initial_equity,
            "final_equity": initial_equity,
            "total_net_pnl": None,
            "total_return_pct": None,
            "max_drawdown_pct": None,
            "sharpe_trade": None,
            "sortino_trade": None,
        }
    rows.sort(key=lambda r: (int(r.get("sequence_no") or 0), str(r.get("trade_id") or "")))
    start = _safe_float(initial_equity)
    if start is None:
        start = _safe_float(rows[0].get("equity_before"))
    final = _safe_float(rows[-1].get("equity_after"))
    returns = [
        value / 100.0
        for value in (_safe_float(r.get("equity_return_pct")) for r in rows)
        if value is not None
    ]
    downside = [r for r in returns if r < 0]
    mean_ret = _mean(returns)
    std_ret = None
    if len(returns) >= 2 and mean_ret is not None:
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        std_ret = math.sqrt(variance)
    down_std = None
    if downside:
        down_mean = _mean(downside) or 0.0
        down_std = math.sqrt(sum((r - down_mean) ** 2 for r in downside) / len(downside))
    drawdowns = [_safe_float(r.get("drawdown_pct")) for r in rows]
    drawdowns = [d for d in drawdowns if d is not None]
    return {
        "initial_equity": start,
        "final_equity": final,
        "total_net_pnl": (final - start) if final is not None and start is not None else None,
        "total_return_pct": ((final / start) - 1.0) * 100.0 if final is not None and start else None,
        "max_drawdown_pct": min(drawdowns) if drawdowns else None,
        "sharpe_trade": (mean_ret / std_ret) if mean_ret is not None and std_ret else None,
        "sortino_trade": (mean_ret / down_std) if mean_ret is not None and down_std else None,
    }


def build_performance_summary(
    trades: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    equity_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    initial_equity: float | None = None,
) -> dict[str, Any]:
    trade_list = [dict(t) for t in (trades or [])]
    summary = _stats_for_trades(trade_list)
    summary["by_side"] = {
        side: _stats_for_trades([t for t in trade_list if _side(t) == side])
        for side in SIDES
    }
    summary.update(_recent_trade_summary(trade_list))
    summary.update(_equity_metrics(equity_rows, initial_equity))
    summary["basis"] = "manual_replay_records"
    return summary


def flatten_performance_summary(summary: dict[str, Any], metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = dict(metadata or {})
    for key, value in summary.items():
        if key == "by_side":
            continue
        row[key] = value
    for side in SIDES:
        side_stats = summary.get("by_side", {}).get(side, {})
        prefix = side.lower()
        for key, value in side_stats.items():
            row[f"{prefix}_{key}"] = value
    return row


def _fmt_pct(value: Any) -> str:
    num = _safe_float(value)
    return "-" if num is None else f"{num:+.4f}%"


def _fmt_num(value: Any) -> str:
    num = _safe_float(value)
    return "-" if num is None else f"{num:.2f}"


def format_performance_report(summary: dict[str, Any]) -> str:
    by_side = summary.get("by_side", {})
    lines = [
        "交易绩效统计（仅基于手动回放记录）",
        "",
        f"总交易数：{summary.get('total_trades', 0)}",
        f"已平仓交易数：{summary.get('closed_trades', 0)}",
        f"未平仓交易数：{summary.get('open_trades', 0)}",
        f"胜率：{_fmt_pct(summary.get('win_rate_pct'))}",
        f"平均收益率：{_fmt_pct(summary.get('average_return_pct'))}",
        f"最大单笔盈利：{_fmt_pct(summary.get('max_profit_pct'))}",
        f"最大单笔亏损：{_fmt_pct(summary.get('max_loss_pct'))}",
        f"平均持仓K线数：{_fmt_num(summary.get('average_holding_bars'))}",
        f"总收益率：{_fmt_pct(summary.get('total_return_pct'))}",
        f"最大回撤：{_fmt_pct(summary.get('max_drawdown_pct'))}",
        f"盈亏比：{_fmt_num(summary.get('profit_factor'))}",
        f"期望收益：{_fmt_pct(summary.get('expectancy_pct'))}",
        f"Sharpe(按交易)：{_fmt_num(summary.get('sharpe_trade'))}",
        f"Sortino(按交易)：{_fmt_num(summary.get('sortino_trade'))}",
        "",
        "分方向统计",
    ]

    for side in SIDES:
        stats = by_side.get(side, {})
        lines.extend(
            [
                f"{SIDE_LABELS.get(side, side)}：总数 {stats.get('total_trades', 0)}，已平 {stats.get('closed_trades', 0)}，未平 {stats.get('open_trades', 0)}，胜率 {_fmt_pct(stats.get('win_rate_pct'))}，平均收益 {_fmt_pct(stats.get('average_return_pct'))}",
            ]
        )

    lines.extend(
        [
            "",
            f"最近一次交易结果：{summary.get('recent_trade_result') or '-'}",
        ]
    )
    return "\n".join(lines)
