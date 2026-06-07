from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import pandas as pd

try:
    from execution import ExecutionSettings
except ImportError:  # pragma: no cover - package import path
    from ..execution import ExecutionSettings


@dataclass(frozen=True)
class TradeUndoPayload:
    action: str
    transaction: Any
    trade_id: str
    event_id: str
    original_trade: dict[str, Any] | None = None


@dataclass(frozen=True)
class TradeActionResult:
    success: bool
    trade_id: str | None = None
    event_id: str | None = None
    trade: dict[str, Any] | None = None
    event: dict[str, Any] | None = None
    trade_update: dict[str, Any] | None = None
    undo_payload: TradeUndoPayload | None = None
    redo_payload: TradeUndoPayload | None = None
    message: str = ""
    error: Exception | None = None
    should_refresh_tables: bool = True
    should_persist_session: bool = True
    should_render: bool = True


class TradeUseCase:
    """Qt-free transaction orchestration for manual trade actions."""

    def __init__(self, trade_controller) -> None:
        self.trade_controller = trade_controller

    @staticmethod
    def _failure(message: str, error: Exception | None = None) -> TradeActionResult:
        return TradeActionResult(
            success=False,
            message=message,
            error=error,
            should_refresh_tables=False,
            should_persist_session=False,
            should_render=False,
        )

    @staticmethod
    def _valid_bar(bar: pd.Series | dict[str, Any] | None) -> bool:
        return bar is not None and "bar_index" in bar

    @staticmethod
    def _valid_price_bar(bar: pd.Series | dict[str, Any] | None) -> bool:
        if bar is None:
            return False
        for field in ("open", "high", "low", "close"):
            try:
                value = float(bar[field])
            except (KeyError, TypeError, ValueError):
                return False
            if not math.isfinite(value):
                return False
        return True

    def open_trade(
        self,
        df: pd.DataFrame,
        bar: pd.Series | dict[str, Any] | None,
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
    ) -> TradeActionResult:
        if df is None or df.empty:
            return self._failure("market data is empty")
        if not self._valid_bar(bar):
            return self._failure("current bar is invalid")
        if not self._valid_price_bar(bar):
            return self._failure("current price is invalid")
        if not session_id:
            return self._failure("session_id is required")

        try:
            transaction = self.trade_controller.prepare_open(
                df,
                bar,
                event_idx=event_idx,
                session_id=session_id,
                symbol=symbol,
                interval=interval,
                side=side,
                event_id=event_id,
                trade_id=trade_id,
                label_tags=label_tags,
                note=note,
                settings=settings,
                now_iso=now_iso,
            )
            self.trade_controller.commit_open(transaction)
        except Exception as exc:
            return self._failure(f"open trade failed: {exc}", exc)

        payload = TradeUndoPayload(
            action="open",
            transaction=transaction,
            trade_id=transaction.trade_row["trade_id"],
            event_id=transaction.event_row["event_id"],
        )
        return TradeActionResult(
            success=True,
            trade_id=transaction.trade_row["trade_id"],
            event_id=transaction.event_row["event_id"],
            trade=dict(transaction.trade_row),
            event=dict(transaction.event_row),
            undo_payload=payload,
            redo_payload=payload,
            message="open trade committed",
        )

    def close_trade(
        self,
        df: pd.DataFrame,
        bar: pd.Series | dict[str, Any] | None,
        *,
        event_idx: int,
        trade: dict[str, Any] | None,
        event_id: str,
        label_tags: list[str],
        note: str,
        fallback_settings: ExecutionSettings,
        now_iso: str,
    ) -> TradeActionResult:
        if df is None or df.empty:
            return self._failure("market data is empty")
        if not self._valid_bar(bar):
            return self._failure("current bar is invalid")
        if not self._valid_price_bar(bar):
            return self._failure("current price is invalid")
        if not trade:
            return self._failure("open trade is required")
        if trade.get("status") != "OPEN":
            return self._failure("trade is not open")

        try:
            transaction = self.trade_controller.prepare_close(
                df,
                bar,
                event_idx=event_idx,
                trade=trade,
                event_id=event_id,
                label_tags=label_tags,
                note=note,
                fallback_settings=fallback_settings,
                now_iso=now_iso,
            )
            self.trade_controller.commit_close(transaction)
        except Exception as exc:
            return self._failure(f"close trade failed: {exc}", exc)

        payload = TradeUndoPayload(
            action="close",
            transaction=transaction,
            trade_id=transaction.close_update["trade_id"],
            event_id=transaction.event_row["event_id"],
            original_trade=dict(transaction.original_trade),
        )
        return TradeActionResult(
            success=True,
            trade_id=transaction.close_update["trade_id"],
            event_id=transaction.event_row["event_id"],
            trade=dict(transaction.original_trade),
            event=dict(transaction.event_row),
            trade_update=dict(transaction.close_update),
            undo_payload=payload,
            redo_payload=payload,
            message="close trade committed",
        )

    def undo_open(self, payload: TradeUndoPayload) -> None:
        self.trade_controller.undo_open(payload.transaction)

    def redo_open(self, payload: TradeUndoPayload) -> None:
        self.trade_controller.commit_open(payload.transaction)

    def undo_close(self, payload: TradeUndoPayload, updated_at: str) -> None:
        self.trade_controller.undo_close(payload.transaction, updated_at)

    def redo_close(self, payload: TradeUndoPayload) -> None:
        self.trade_controller.commit_close(payload.transaction)


__all__ = ["TradeActionResult", "TradeUndoPayload", "TradeUseCase"]
