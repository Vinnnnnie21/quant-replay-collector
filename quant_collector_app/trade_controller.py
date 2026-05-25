from __future__ import annotations

from typing import Any

from execution import ExecutionSettings


class TradeController:
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
