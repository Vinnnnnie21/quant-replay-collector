from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from analytics.trade_analysis import analyze_trades
from backtesting.types import BacktestConfig, BacktestResult, Signal
from execution import ExecutionSettings, apply_slippage, fill_price, order_action, trade_outcome


REQUIRED_COLUMNS = {"bar_index", "open_time_bjt", "open", "high", "low", "close", "volume"}
VALID_SIGNAL_TIMINGS = {"on_close", "next_open"}


@dataclass(frozen=True)
class RiskExit:
    signal: str
    reason: str | None = None
    trigger_price: float | None = None


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _empty_result(config: BacktestConfig, strategy_name: str, warnings: list[str], interval: str) -> BacktestResult:
    trades = pd.DataFrame()
    equity = pd.DataFrame()
    metrics = analyze_trades(trades, equity, interval=interval, initial_equity=config.initial_equity)
    metrics["basis"] = "backtest_records"
    return BacktestResult(trades, equity, metrics, config.to_dict(), strategy_name, warnings)


def _time_value(row: pd.Series) -> str:
    value = row.get("open_time_bjt")
    if value is None:
        return ""
    try:
        return value.isoformat(timespec="seconds")
    except AttributeError:
        return str(value)


def _mark_equity(equity_rows: list[dict], i: int, row: pd.Series, equity: float, peak: float, realized_net_pnl: float = 0.0, trade_id: str | None = None):
    peak = max(peak, equity)
    drawdown = (equity / peak - 1.0) * 100.0 if peak else 0.0
    equity_rows.append(
        {
            "sequence_no": i + 1,
            "bar_index": int(row.get("bar_index")),
            "bar_open_time_bjt": _time_value(row),
            "trade_id": trade_id,
            "equity_after": equity,
            "realized_net_pnl": realized_net_pnl,
            "equity_return_pct": 0.0,
            "drawdown_pct": drawdown,
            "is_continuous": True,
        }
    )


def _risk_signal(row: pd.Series, position: dict, config: BacktestConfig, strategy=None) -> RiskExit:
    side = str(position.get("side") or "").upper()
    try:
        entry = float(position.get("entry_fill_price"))
        high = float(row.get("high"))
        low = float(row.get("low"))
    except (TypeError, ValueError):
        return RiskExit(Signal.HOLD)
    if entry <= 0:
        return RiskExit(Signal.HOLD)
    stop_loss_pct = config.stop_loss_pct
    take_profit_pct = config.take_profit_pct
    if stop_loss_pct is None and strategy is not None and hasattr(strategy, "stop_loss_pct"):
        stop_loss_pct = getattr(strategy, "stop_loss_pct")
    if take_profit_pct is None and strategy is not None and hasattr(strategy, "take_profit_pct"):
        take_profit_pct = getattr(strategy, "take_profit_pct")
    if side == "LONG":
        stop_price = entry * (1.0 - max(0.0, float(stop_loss_pct)) / 100.0) if stop_loss_pct is not None else None
        take_price = entry * (1.0 + max(0.0, float(take_profit_pct)) / 100.0) if take_profit_pct is not None else None
        if stop_price is not None and low <= stop_price:
            return RiskExit(Signal.CLOSE_LONG, "stop_loss", stop_price)
        if take_price is not None and high >= take_price:
            return RiskExit(Signal.CLOSE_LONG, "take_profit", take_price)
    if side == "SHORT":
        stop_price = entry * (1.0 + max(0.0, float(stop_loss_pct)) / 100.0) if stop_loss_pct is not None else None
        take_price = entry * (1.0 - max(0.0, float(take_profit_pct)) / 100.0) if take_profit_pct is not None else None
        if stop_price is not None and high >= stop_price:
            return RiskExit(Signal.CLOSE_SHORT, "stop_loss", stop_price)
        if take_price is not None and low <= take_price:
            return RiskExit(Signal.CLOSE_SHORT, "take_profit", take_price)
    return RiskExit(Signal.HOLD)


def _normalize_signal_timing(value: str | None, warnings: list[str]) -> str:
    timing = str(value or "next_open").strip().lower()
    if timing not in VALID_SIGNAL_TIMINGS:
        warnings.append(f"Unsupported signal_timing={value!r}; using next_open.")
        return "next_open"
    return timing


def run_backtest(
    df: pd.DataFrame,
    strategy,
    config: BacktestConfig,
    symbol: str,
    interval: str,
) -> BacktestResult:
    warnings: list[str] = ["Backtest result is for research only and does not represent live trading returns."]
    strategy_name = getattr(strategy, "name", strategy.__class__.__name__)
    signal_timing = _normalize_signal_timing(getattr(config, "signal_timing", "next_open"), warnings)
    if signal_timing == "on_close" and str(config.fill_mode or "").upper() != "CLOSE":
        warnings.append("signal_timing=on_close forces strategy fills to CLOSE to avoid look-ahead execution.")
    data = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    if data.empty:
        warnings.append("input dataframe is empty")
        return _empty_result(config, strategy_name, warnings, interval)
    missing = sorted(REQUIRED_COLUMNS - set(data.columns))
    if missing:
        raise ValueError(f"Backtest dataframe missing columns: {', '.join(missing)}")

    def settings_for(fill_mode: str) -> ExecutionSettings:
        return ExecutionSettings(
            fill_mode=fill_mode,
            fee_bps=config.fee_bps,
            slippage_bps=config.slippage_bps,
            notional_quote=config.notional_quote,
        )

    outcome_settings = settings_for("CLOSE")
    trades: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    equity = float(config.initial_equity)
    peak = equity
    position: dict | None = None
    pending_signal: dict[str, Any] | None = None

    def open_position(
        i: int,
        row: pd.Series,
        side: str,
        signal_i: int | None = None,
        signal_row: pd.Series | None = None,
        fill_mode_override: str | None = None,
    ):
        nonlocal position
        signal_row = row if signal_row is None else signal_row
        mode = fill_mode_override or config.fill_mode
        raw, filled = fill_price(row, side, "OPEN", settings_for(mode))
        position = {
            "trade_id": f"bt_{len(trades) + 1:06d}",
            "source": "backtest",
            "symbol": symbol,
            "interval": interval,
            "side": side,
            "status": "OPEN",
            "signal_bar_index": int(signal_row["bar_index"]),
            "execution_bar_index": int(row["bar_index"]),
            "entry_signal_bar_index": int(signal_row["bar_index"]),
            "entry_execution_bar_index": int(row["bar_index"]),
            "signal_i": int(i if signal_i is None else signal_i),
            "execution_i": int(i),
            "entry_i": int(i),
            "entry_bar_index": int(row["bar_index"]),
            "entry_bar_time_bjt": _time_value(row),
            "entry_price_raw": raw,
            "entry_fill_price": filled,
            "fee_bps": config.fee_bps,
            "slippage_bps": config.slippage_bps,
            "notional_quote": config.notional_quote,
            "fill_mode": mode,
            "signal_timing": signal_timing,
            "created_at": _utc_now_iso(),
        }

    def close_position(
        i: int,
        row: pd.Series,
        forced: bool = False,
        override_exit_price: float | None = None,
        exit_reason: str = "signal",
        signal_i: int | None = None,
        signal_row: pd.Series | None = None,
        fill_mode_override: str | None = None,
    ):
        nonlocal position, equity, peak
        if position is None:
            return
        side = str(position["side"]).upper()
        signal_row = row if signal_row is None else signal_row
        if override_exit_price is None:
            mode = fill_mode_override or config.fill_mode
            raw, filled = fill_price(row, side, "CLOSE", settings_for(mode))
        else:
            mode = "TRIGGER"
            raw = float(override_exit_price)
            filled = apply_slippage(raw, order_action(side, "CLOSE"), config.slippage_bps)
        outcome = trade_outcome(side, position["entry_fill_price"], filled, outcome_settings)
        before = equity
        equity = before + outcome["net_pnl_quote"]
        peak = max(peak, equity)
        trade = dict(position)
        trade.update(
            {
                "status": "CLOSED",
                "exit_signal_bar_index": int(signal_row["bar_index"]),
                "exit_execution_bar_index": int(row["bar_index"]),
                "exit_signal_i": int(i if signal_i is None else signal_i),
                "exit_execution_i": int(i),
                "exit_bar_index": int(row["bar_index"]),
                "exit_bar_time_bjt": _time_value(row),
                "exit_price_raw": raw,
                "exit_fill_price": filled,
                "holding_bars": (i - int(position["entry_i"]) + 1) if position.get("entry_i") is not None else int(row["bar_index"]) - int(position["entry_bar_index"]) + 1,
                "updated_at": _utc_now_iso(),
                "forced_exit": bool(forced),
                "exit_reason": exit_reason,
                "exit_fill_mode": mode,
                **outcome,
            }
        )
        trades.append(trade)
        if equity_rows:
            equity_rows[-1]["equity_return_pct"] = ((equity / before) - 1.0) * 100.0 if before else 0.0
            equity_rows[-1]["realized_net_pnl"] = outcome["net_pnl_quote"]
            equity_rows[-1]["trade_id"] = trade["trade_id"]
            equity_rows[-1]["equity_after"] = equity
            equity_rows[-1]["drawdown_pct"] = (equity / peak - 1.0) * 100.0 if peak else 0.0
        position = None

    def execute_signal(
        signal: str,
        execution_i: int,
        execution_row: pd.Series,
        signal_i: int,
        signal_row: pd.Series,
        fill_mode: str,
        exit_reason: str = "signal",
    ):
        if position:
            if signal == Signal.CLOSE_LONG and position["side"] == "LONG":
                close_position(
                    execution_i,
                    execution_row,
                    signal_i=signal_i,
                    signal_row=signal_row,
                    fill_mode_override=fill_mode,
                    exit_reason=exit_reason,
                )
            elif signal == Signal.CLOSE_SHORT and position["side"] == "SHORT":
                close_position(
                    execution_i,
                    execution_row,
                    signal_i=signal_i,
                    signal_row=signal_row,
                    fill_mode_override=fill_mode,
                    exit_reason=exit_reason,
                )
        elif signal == Signal.OPEN_LONG:
            open_position(execution_i, execution_row, "LONG", signal_i=signal_i, signal_row=signal_row, fill_mode_override=fill_mode)
        elif signal == Signal.OPEN_SHORT and config.allow_short:
            open_position(execution_i, execution_row, "SHORT", signal_i=signal_i, signal_row=signal_row, fill_mode_override=fill_mode)

    for i, row in data.reset_index(drop=True).iterrows():
        _mark_equity(equity_rows, i, row, equity, peak)
        if pending_signal is not None and pending_signal.get("execution_i") == i:
            execute_signal(
                pending_signal["signal"],
                i,
                row,
                pending_signal["signal_i"],
                pending_signal["signal_row"],
                "OPEN",
                pending_signal.get("exit_reason") or "signal",
            )
            pending_signal = None

        risk_exit = _risk_signal(row, position, config, strategy) if position else RiskExit(Signal.HOLD)
        signal = risk_exit.signal
        exit_reason = risk_exit.reason
        override_exit_price = risk_exit.trigger_price
        if signal != Signal.HOLD and position:
            if signal == Signal.CLOSE_LONG and position["side"] == "LONG":
                close_position(i, row, override_exit_price=override_exit_price, exit_reason=exit_reason or "signal", signal_i=i, signal_row=row)
                continue
            if signal == Signal.CLOSE_SHORT and position["side"] == "SHORT":
                close_position(i, row, override_exit_price=override_exit_price, exit_reason=exit_reason or "signal", signal_i=i, signal_row=row)
                continue

        if position and config.max_bars_hold is not None:
            if i - int(position.get("entry_i", i)) + 1 >= int(config.max_bars_hold):
                signal = Signal.CLOSE_LONG if position["side"] == "LONG" else Signal.CLOSE_SHORT
                exit_reason = "max_bars_hold"
        else:
            signal = Signal.HOLD

        if signal == Signal.HOLD:
            history = data.iloc[: i + 1].copy()
            signal = strategy.on_bar(i, row, history, dict(position) if position else None)
            if signal in {Signal.CLOSE_LONG, Signal.CLOSE_SHORT}:
                exit_reason = "signal"

        if signal == Signal.HOLD:
            continue
        if signal_timing == "on_close":
            execute_signal(signal, i, row, i, row, "CLOSE", exit_reason or "signal")
        elif i + 1 < len(data):
            pending_signal = {
                "signal": signal,
                "signal_i": i,
                "signal_row": row,
                "execution_i": i + 1,
                "exit_reason": exit_reason or "signal",
            }
        elif signal in {Signal.OPEN_LONG, Signal.OPEN_SHORT}:
            warnings.append("last-bar open signal ignored because signal_timing=next_open has no next bar.")

    if position is not None:
        warnings.append("open position was force-closed on the last bar")
        close_position(
            len(data) - 1,
            data.iloc[-1],
            forced=True,
            exit_reason="forced_last_bar",
            signal_i=len(data) - 1,
            signal_row=data.iloc[-1],
            fill_mode_override="CLOSE",
        )

    trades_df = pd.DataFrame(trades)
    equity_df = pd.DataFrame(equity_rows)
    metrics = analyze_trades(trades_df, equity_df, interval=interval, initial_equity=config.initial_equity)
    metrics["basis"] = "backtest_records"
    return BacktestResult(trades_df, equity_df, metrics, config.to_dict(), strategy_name, warnings)
