from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from app_config import BJT
from execution import ExecutionSettings, fill_price, trade_outcome
from market_data.features import build_feature_row, build_window_rows, compute_price_proxy


@dataclass(frozen=True)
class OpenTradeTransaction:
    trade_row: dict[str, Any]
    event_row: dict[str, Any]
    window_rows: list[dict[str, Any]]
    feature_row: dict[str, Any]


@dataclass(frozen=True)
class CloseTradeTransaction:
    original_trade: dict[str, Any]
    event_row: dict[str, Any]
    window_rows: list[dict[str, Any]]
    feature_row: dict[str, Any]
    close_update: dict[str, Any]
    outcome: dict[str, float]
    entry_event_id: str
    holding_bars: int


class TradeController:
    def __init__(self, storage, export_version: str = "") -> None:
        self.storage = storage
        self.export_version = str(export_version)

    @staticmethod
    def execution_settings(fill_mode: str, fee_bps: float, slippage_bps: float, notional_quote: float) -> ExecutionSettings:
        return ExecutionSettings(
            fill_mode=str(fill_mode).upper(),
            fee_bps=float(fee_bps),
            slippage_bps=float(slippage_bps),
            notional_quote=float(notional_quote),
        )

    @staticmethod
    def event_row(
        event_id: str,
        trade_id: str,
        event_type: str,
        side: str,
        session_id: str,
        symbol: str,
        interval: str,
        bar_index: int,
        bar_time_bjt: str,
        real_time_bjt: str,
        price_proxy: float,
        label_tags: list[str],
        note: str,
        created_at: str,
    ) -> dict[str, Any]:
        return {
            "event_id": event_id,
            "session_id": session_id,
            "trade_id": trade_id,
            "event_type": event_type,
            "side": side,
            "symbol": symbol,
            "interval": interval,
            "bar_index": int(bar_index),
            "bar_open_time_bjt": bar_time_bjt,
            "real_key_time_bjt": real_time_bjt,
            "price_proxy": float(price_proxy),
            "label_tags": list(label_tags),
            "note": note,
            "created_at": created_at,
        }

    @staticmethod
    def _bar_time(bar: pd.Series) -> str:
        return pd.to_datetime(bar["open_time_bjt"]).tz_convert(BJT).isoformat(timespec="seconds")

    def _feature_row(self, df: pd.DataFrame, event_row: dict[str, Any]) -> dict[str, Any]:
        base = build_feature_row(df, int(event_row["bar_index"]), event_row["side"])
        return {
            "event_id": event_row["event_id"],
            "session_id": event_row["session_id"],
            "trade_id": event_row["trade_id"],
            "event_type": event_row["event_type"],
            "side": event_row["side"],
            "symbol": event_row["symbol"],
            "interval": event_row["interval"],
            **base,
            "manual_trade_final_return_pct": None,
            "manual_trade_holding_bars": None,
            "export_version": self.export_version,
            "created_at": event_row["created_at"],
        }

    def prepare_open(
        self,
        df: pd.DataFrame,
        bar: pd.Series,
        *,
        event_idx: int,
        session_id: str,
        symbol: str,
        interval: str,
        side: str,
        event_id: str,
        trade_id: str,
        label_tags: list[str],
        note: str,
        settings: ExecutionSettings,
        now_iso: str,
    ) -> OpenTradeTransaction:
        side = str(side).upper()
        if side not in {"LONG", "SHORT"}:
            raise ValueError(f"Unsupported open side: {side}")
        price_proxy = compute_price_proxy(bar)
        entry_raw_price, entry_fill_price = fill_price(bar, side, "OPEN", settings)
        entry_fee_quote = settings.notional_quote * max(0.0, settings.fee_bps) / 10_000.0
        bar_time = self._bar_time(bar)
        trade_row = {
            "trade_id": trade_id,
            "session_id": session_id,
            "symbol": symbol,
            "interval": interval,
            "side": side,
            "status": "OPEN",
            "entry_event_id": event_id,
            "exit_event_id": None,
            "entry_bar_index": int(event_idx),
            "exit_bar_index": None,
            "entry_bar_time_bjt": bar_time,
            "exit_bar_time_bjt": None,
            "entry_real_time_bjt": now_iso,
            "exit_real_time_bjt": None,
            "entry_price_proxy": price_proxy,
            "exit_price_proxy": None,
            "holding_bars": None,
            "final_return_pct": None,
            "fill_mode": settings.fill_mode,
            "fee_bps": settings.fee_bps,
            "slippage_bps": settings.slippage_bps,
            "notional_quote": settings.notional_quote,
            "quantity": None,
            "entry_price_raw": entry_raw_price,
            "exit_price_raw": None,
            "entry_fill_price": entry_fill_price,
            "exit_fill_price": None,
            "entry_fee_quote": entry_fee_quote,
            "exit_fee_quote": None,
            "gross_pnl_quote": None,
            "net_pnl_quote": None,
            "gross_return_pct": None,
            "net_return_pct": None,
            "fee_return_pct": None,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        event_row = self.event_row(
            event_id,
            trade_id,
            "OPEN",
            side,
            session_id,
            symbol,
            interval,
            int(event_idx),
            bar_time,
            now_iso,
            price_proxy,
            label_tags,
            note,
            now_iso,
        )
        return OpenTradeTransaction(
            trade_row=trade_row,
            event_row=event_row,
            window_rows=build_window_rows(df, int(event_idx)),
            feature_row=self._feature_row(df, event_row),
        )

    def commit_open(self, transaction: OpenTradeTransaction) -> None:
        self.storage.insert_open_trade_bundle(
            transaction.trade_row,
            transaction.event_row,
            transaction.window_rows,
            transaction.feature_row,
        )

    def undo_open(self, transaction: OpenTradeTransaction) -> None:
        self.storage.undo_open_trade_bundle(transaction.trade_row["trade_id"], transaction.event_row["event_id"])

    @staticmethod
    def _close_settings(trade: dict[str, Any], fallback: ExecutionSettings) -> ExecutionSettings:
        return ExecutionSettings(
            fill_mode=str(trade.get("fill_mode") or fallback.fill_mode).upper(),
            fee_bps=float(trade.get("fee_bps") if trade.get("fee_bps") is not None else fallback.fee_bps),
            slippage_bps=float(trade.get("slippage_bps") if trade.get("slippage_bps") is not None else fallback.slippage_bps),
            notional_quote=float(
                trade.get("notional_quote") if trade.get("notional_quote") is not None else fallback.notional_quote
            ),
        )

    def prepare_close(
        self,
        df: pd.DataFrame,
        bar: pd.Series,
        *,
        event_idx: int,
        trade: dict[str, Any],
        event_id: str,
        label_tags: list[str],
        note: str,
        fallback_settings: ExecutionSettings,
        now_iso: str,
    ) -> CloseTradeTransaction:
        side = str(trade["side"]).upper()
        if side not in {"LONG", "SHORT"}:
            raise ValueError(f"Unsupported close side: {side}")
        bar_index = int(event_idx)
        entry_bar_index = int(trade["entry_bar_index"])
        if bar_index < entry_bar_index:
            raise ValueError("Close bar cannot precede entry bar.")
        price_proxy = compute_price_proxy(bar)
        entry_price = float(trade["entry_price_proxy"])
        if side == "LONG":
            final_return_pct = ((price_proxy / entry_price) - 1.0) * 100.0 if entry_price else None
        else:
            final_return_pct = ((entry_price - price_proxy) / entry_price) * 100.0 if entry_price else None
        holding_bars = bar_index - entry_bar_index
        settings = self._close_settings(trade, fallback_settings)
        exit_raw_price, exit_fill_price = fill_price(bar, side, "CLOSE", settings)
        entry_fill_price = float(trade.get("entry_fill_price") or trade.get("entry_price_proxy") or entry_price)
        outcome = trade_outcome(side, entry_fill_price, exit_fill_price, settings)
        event_row = self.event_row(
            event_id,
            trade["trade_id"],
            "CLOSE",
            side,
            trade["session_id"],
            trade["symbol"],
            trade["interval"],
            bar_index,
            self._bar_time(bar),
            now_iso,
            price_proxy,
            label_tags,
            note,
            now_iso,
        )
        feature_row = self._feature_row(df, event_row)
        feature_row["manual_trade_final_return_pct"] = outcome["net_return_pct"]
        feature_row["manual_trade_holding_bars"] = holding_bars
        close_update = {
            "trade_id": trade["trade_id"],
            "status": "CLOSED",
            "exit_event_id": event_id,
            "exit_bar_index": bar_index,
            "exit_bar_time_bjt": event_row["bar_open_time_bjt"],
            "exit_real_time_bjt": now_iso,
            "exit_price_proxy": price_proxy,
            "holding_bars": holding_bars,
            "final_return_pct": final_return_pct,
            "quantity": outcome["quantity"],
            "exit_price_raw": exit_raw_price,
            "exit_fill_price": exit_fill_price,
            "exit_fee_quote": outcome["exit_fee_quote"],
            "gross_pnl_quote": outcome["gross_pnl_quote"],
            "net_pnl_quote": outcome["net_pnl_quote"],
            "gross_return_pct": outcome["gross_return_pct"],
            "net_return_pct": outcome["net_return_pct"],
            "fee_return_pct": outcome["fee_return_pct"],
            "updated_at": now_iso,
        }
        return CloseTradeTransaction(
            original_trade=dict(trade),
            event_row=event_row,
            window_rows=build_window_rows(df, bar_index),
            feature_row=feature_row,
            close_update=close_update,
            outcome=outcome,
            entry_event_id=trade["entry_event_id"],
            holding_bars=holding_bars,
        )

    def commit_close(self, transaction: CloseTradeTransaction) -> None:
        self.storage.close_trade_bundle(
            transaction.event_row,
            transaction.window_rows,
            transaction.feature_row,
            transaction.close_update,
            transaction.entry_event_id,
            transaction.outcome["net_return_pct"],
            transaction.holding_bars,
        )

    def undo_close(self, transaction: CloseTradeTransaction, updated_at: str) -> None:
        self.storage.undo_close_trade_bundle(
            transaction.close_update["trade_id"],
            transaction.event_row["event_id"],
            transaction.entry_event_id,
            updated_at,
        )

    def fetch_trade(self, trade_id: str):
        return self.storage.fetch_trade(trade_id)

    def replace_equity_curve(self, session_id: str, rows: list[dict[str, Any]]) -> None:
        self.storage.replace_equity_curve(session_id, rows)
