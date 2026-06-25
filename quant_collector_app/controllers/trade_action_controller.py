"""Manual trade UI orchestration over the Qt-free TradeUseCase."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from PySide6 import QtCore, QtWidgets

try:
    from app_logger import get_logger
    from market_data import bjt_now_iso, clamp
    from presenters.formatters import status_label
    from render_state import RenderState
    from services.trade_use_cases import TradeActionResult, TradeUseCase
except ImportError:  # pragma: no cover - package import path
    from ..app_logger import get_logger
    from ..market_data import bjt_now_iso, clamp
    from ..presenters.formatters import status_label
    from ..render_state import RenderState
    from ..services.trade_use_cases import TradeActionResult, TradeUseCase


logger = get_logger(__name__)


@dataclass
class ActionCommand:
    name: str
    do_fn: Callable[[], None]
    undo_fn: Callable[[], None]

    def do(self) -> None:
        self.do_fn()

    def undo(self) -> None:
        self.undo_fn()


def _render_state(window) -> RenderState:
    getter = getattr(window, "_chart_render_state", None)
    if callable(getter):
        return getter()
    state = getattr(window, "render_state", None)
    if state is None:
        state = RenderState()
        window.render_state = state
    return state


def _log_slow(window, name: str, started: float) -> None:
    callback = getattr(window, "_log_slow_operation", None)
    if callable(callback):
        callback(name, started)


def pause_replay_for_manual_trade(window) -> None:
    # Manual trades no longer pause playback (user preference). The trade is
    # recorded against the bar captured before this call, so replay can keep
    # running without affecting which bar the transaction is attributed to.
    return


def current_bar(window):
    if window.df.empty:
        return None
    return window.df.iloc[int(clamp(window.cursor, 0, len(window.df) - 1))]


def current_tags_and_note(window):
    tags = [checkbox.text() for checkbox in window.tag_checks if checkbox.isChecked()]
    note = window.noteEdit.toPlainText().strip()
    return tags, note


def display_interval(window) -> str:
    key = getattr(window, "_display_market_key", None)
    if key:
        return str(key[1])
    return window.intervalBox.currentText().strip()


def sample_interval(window) -> str:
    key = getattr(window, "_sample_market_key", None)
    if key:
        return str(key[1])
    for row in [*getattr(window, "trades", []), *getattr(window, "events", [])]:
        interval = row.get("interval")
        if interval:
            return str(interval)
    return window._display_interval()


def is_display_interval_same_as_sample_interval(window) -> bool:
    if not window.trades and not window.events:
        return True
    return window._display_interval() == window._sample_interval()


def is_trade_recording_allowed(window) -> bool:
    return window._is_display_interval_same_as_sample_interval()


def warn_trade_interval_mismatch(window) -> None:
    message = window.tr("trade_disabled_due_to_display_interval")
    window._log(message)
    QtWidgets.QMessageBox.warning(window, window.tr("trade_actions"), message)


def start_new_session_for_current_display_interval(window) -> None:
    window.playing = False
    window._accum = 0.0
    window.trades.clear()
    window.events.clear()
    window._trade_by_id.clear()
    window._event_by_id.clear()
    window.undo_stack.clear()
    window.redo_stack.clear()
    window.session_id = window._new_id("sess")
    window._sample_market_key = window._display_market_key or window._current_market_key()
    window.persist_session_state()
    window._refresh_tables()
    window._update_trade_buttons_enabled()
    _render_state(window).mark_events_changed()
    window._render(force=True)


def trade_use_case(window) -> TradeUseCase:
    use_case = getattr(window, "trade_use_cases", None)
    if use_case is None:
        use_case = TradeUseCase(window.trade_controller)
        window.trade_use_cases = use_case
    return use_case


def raise_trade_action_error(result: TradeActionResult) -> None:
    if result.error is not None:
        raise result.error
    raise RuntimeError(result.message or "交易操作失败")


def apply_open_trade_result(window, result: TradeActionResult) -> None:
    if not result.trade_id or not result.event_id:
        raise RuntimeError("开仓结果缺少交易ID或事件ID")
    window._trade_by_id[result.trade_id] = dict(result.trade or {})
    window._event_by_id[result.event_id] = dict(result.event or {})
    window.trades.append(window._trade_by_id[result.trade_id])
    window.events.append(window._event_by_id[result.event_id])
    window._sample_market_key = window._display_market_key or window._current_market_key()
    window._sample_cursor_bar_index = int(window.cursor)
    _render_state(window).mark_events_changed()


def undo_open_trade_result(window, result: TradeActionResult) -> None:
    if not result.trade_id or not result.event_id:
        return
    window.trades = [trade for trade in window.trades if trade["trade_id"] != result.trade_id]
    window.events = [event for event in window.events if event["event_id"] != result.event_id]
    window._trade_by_id.pop(result.trade_id, None)
    window._event_by_id.pop(result.event_id, None)
    _render_state(window).mark_events_changed()


def apply_close_trade_result(window, result: TradeActionResult, trade: dict[str, Any]) -> None:
    if not result.event_id:
        raise RuntimeError("平仓结果缺少事件ID")
    window._event_by_id[result.event_id] = dict(result.event or {})
    window.events.append(window._event_by_id[result.event_id])
    trade.update(result.trade_update or {})
    window._trade_by_id[trade["trade_id"]] = trade
    window._sample_cursor_bar_index = int(window.cursor)
    _render_state(window).mark_events_changed()


def undo_close_trade_result(window, result: TradeActionResult, trade: dict[str, Any]) -> None:
    if result.event_id:
        window.events = [event for event in window.events if event["event_id"] != result.event_id]
        window._event_by_id.pop(result.event_id, None)
    trade.clear()
    trade.update((result.undo_payload.original_trade if result.undo_payload else None) or {})
    window._trade_by_id[trade["trade_id"]] = trade
    _render_state(window).mark_events_changed()


def request_open_trade(window, side: str) -> None:
    if getattr(window, "_trade_transaction_active", False):
        window._log("trade transaction already in progress; ignored duplicate open request")
        return
    if window.df.empty:
        return
    if not window._is_trade_recording_allowed():
        window._warn_trade_interval_mismatch()
        return
    if side not in {"LONG", "SHORT"}:
        window._log(f"忽略未知开仓方向：{side}")
        return
    if not window.session_id:
        window.session_id = window._new_id("sess")
        window.persist_session_state()
    bar = window.current_bar()
    if bar is None or "bar_index" not in bar:
        window._log("开仓失败：当前K线无效。")
        return
    pause_replay_for_manual_trade(window)
    tags, note = window.current_tags_and_note()
    event_id = window._new_id("evt")
    trade_id = window._new_id("trd")
    result_holder: dict[str, TradeActionResult] = {}

    def do() -> None:
        started = time.perf_counter()
        window._trade_transaction_active = True
        window._update_trade_buttons_enabled()
        try:
            result = result_holder.get("result")
            if result is not None and result.redo_payload is not None:
                trade_use_case(window).redo_open(result.redo_payload)
            else:
                result = trade_use_case(window).open_trade(
                    window.df,
                    bar,
                    event_idx=int(bar["bar_index"]),
                    session_id=window.session_id,
                    symbol=window.symbolBox.currentText().strip().upper(),
                    interval=window.intervalBox.currentText().strip(),
                    side=side,
                    event_id=event_id,
                    trade_id=trade_id,
                    label_tags=tags,
                    note=note,
                    settings=window.execution_settings(),
                    now_iso=bjt_now_iso(),
                )
                if not result.success:
                    raise_trade_action_error(result)
                result_holder["result"] = result
            apply_open_trade_result(window, result)
            window.persist_session_state()
            window._refresh_tables(include_heavy=False)
            window.analysis_refresh_controller.schedule()
            window._render(force=True)
            window._log(f"开{('多' if side == 'LONG' else '空')}：交易ID={result.trade_id}")
        finally:
            window._trade_transaction_active = False
            window._update_trade_buttons_enabled()
            _log_slow(window, "request_open_trade", started)

    def undo_action() -> None:
        result = result_holder.get("result")
        if result is None or result.undo_payload is None:
            return
        trade_use_case(window).undo_open(result.undo_payload)
        undo_open_trade_result(window, result)
        window._refresh_tables()
        window._render(force=True)
        window._log(f"撤销开仓：交易ID={result.trade_id}")

    window.execute_command(ActionCommand(name=f"open_{side.lower()}", do_fn=do, undo_fn=undo_action))


def request_close_trade(window, expected_side: str) -> None:
    if getattr(window, "_trade_transaction_active", False):
        window._log("trade transaction already in progress; ignored duplicate close request")
        return
    if expected_side not in {"LONG", "SHORT"}:
        window._log(f"忽略未知平仓方向：{expected_side}")
        return
    if not window._is_trade_recording_allowed():
        window._warn_trade_interval_mismatch()
        return
    trade = window.selected_open_trade(verify_db=True)
    if not trade:
        trade = _auto_select_open_trade_if_needed(window, expected_side)
    if not trade:
        QtWidgets.QMessageBox.warning(window, "无法平仓", "当前没有可平仓的持仓。请先开仓。")
        return
    if trade.get("status") != "OPEN":
        QtWidgets.QMessageBox.warning(window, "仓位状态错误", "当前选中的交易不是未平仓状态，请刷新或重新选择。")
        window._log(f"平仓被拒绝：交易ID={trade.get('trade_id')} 状态={status_label(trade.get('status'))}")
        return
    if trade["side"] != expected_side:
        QtWidgets.QMessageBox.warning(
            window,
            "方向不匹配",
            f"当前选中仓位方向为 {trade['side']}，不能执行本次平仓。",
        )
        return
    bar = window.current_bar()
    if bar is None:
        return
    pause_replay_for_manual_trade(window)
    tags, note = window.current_tags_and_note()
    event_id = window._new_id("evt")
    bar_index = int(bar["bar_index"])
    entry_bar_index = int(trade["entry_bar_index"])
    if bar_index < entry_bar_index:
        QtWidgets.QMessageBox.warning(window, "平仓位置错误", "平仓K线不能早于开仓K线。请先跳到开仓之后的位置。")
        return
    result_holder: dict[str, TradeActionResult] = {}

    def do() -> None:
        started = time.perf_counter()
        window._trade_transaction_active = True
        window._update_trade_buttons_enabled()
        try:
            result = result_holder.get("result")
            if result is not None and result.redo_payload is not None:
                trade_use_case(window).redo_close(result.redo_payload)
            else:
                result = trade_use_case(window).close_trade(
                    window.df,
                    bar,
                    event_idx=bar_index,
                    trade=trade,
                    event_id=event_id,
                    label_tags=tags,
                    note=note,
                    fallback_settings=window.execution_settings(),
                    now_iso=bjt_now_iso(),
                )
                if not result.success:
                    raise_trade_action_error(result)
                result_holder["result"] = result
            apply_close_trade_result(window, result, trade)
            window.persist_session_state()
            window._sync_equity_curve()
            window._refresh_tables(include_heavy=False)
            window.analysis_refresh_controller.schedule()
            window._render(force=True)
            window._log(f"平{('多' if trade['side'] == 'LONG' else '空')}：交易ID={trade['trade_id']}")
        finally:
            window._trade_transaction_active = False
            window._update_trade_buttons_enabled()
            _log_slow(window, "request_close_trade", started)

    def undo_action() -> None:
        result = result_holder.get("result")
        if result is None or result.undo_payload is None:
            return
        trade_use_case(window).undo_close(result.undo_payload, bjt_now_iso())
        undo_close_trade_result(window, result, trade)
        window._sync_equity_curve()
        window._refresh_tables()
        window._render(force=True)
        window._log(f"撤销平仓：交易ID={trade['trade_id']}")

    window.execute_command(
        ActionCommand(name=f"close_{expected_side.lower()}", do_fn=do, undo_fn=undo_action)
    )


def _auto_select_open_trade_if_needed(window, expected_side: str | None = None) -> dict | None:
    trade = selected_open_trade(window)
    if trade:
        return trade
    if window.openTradesTable.rowCount() == 0:
        return None
    # No row selected: pick the most recently opened OPEN trade that matches the
    # requested side, so 平多/平空 (C/X) work even with several positions open.
    candidate_id = None
    for tid, candidate in reversed(list(window._trade_by_id.items())):
        if candidate.get("status") != "OPEN":
            continue
        if expected_side is not None and candidate.get("side") != expected_side:
            continue
        candidate_id = tid
        break
    if candidate_id is None and expected_side is None:
        candidate_id = _first_open_trade_id(window)
    if candidate_id:
        trade = window._trade_by_id.get(candidate_id)
        if trade and trade.get("status") == "OPEN":
            _select_row_for_trade_id(window.openTradesTable, candidate_id)
            return trade
    return None


def _first_open_trade_id(window) -> str | None:
    for tid, t in window._trade_by_id.items():
        if t.get("status") == "OPEN":
            return tid
    return None


def _select_row_for_trade_id(table, trade_id: str) -> None:
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        if item and item.data(QtCore.Qt.UserRole) == trade_id:
            table.selectRow(row)
            return


def selected_open_trade(window, verify_db: bool = False):
    trade_id = window._selected_id_from_table(window.openTradesTable)
    if not trade_id:
        return None
    trade = window._trade_by_id.get(trade_id)
    if not trade:
        window._log(f"选择的未平仓交易不在内存索引中：交易ID={trade_id}")
        return None
    if trade.get("status") != "OPEN":
        window._log(f"选择的交易不是未平仓状态：交易ID={trade_id} 状态={status_label(trade.get('status'))}")
        return None
    if verify_db:
        db_trade = window.trade_controller.fetch_trade(trade_id)
        if not db_trade:
            window._log(f"SQLite 中找不到选中的交易：交易ID={trade_id}")
            return None
        if db_trade.get("status") != "OPEN":
            window._log(
                f"SQLite 中选中交易不是未平仓：交易ID={trade_id} "
                f"状态={status_label(db_trade.get('status'))}"
            )
            return None
        if db_trade.get("session_id") != window.session_id:
            window._log(f"选中交易不属于当前会话：交易ID={trade_id}")
            return None
    return trade


def execute_command(window, command: ActionCommand) -> bool:
    try:
        command.do()
    except Exception as exc:
        window._operation_error("操作失败", exc)
        return False
    window.undo_stack.append(command)
    window.redo_stack.clear()
    return True


def undo(window) -> None:
    if not window.undo_stack:
        return
    command = window.undo_stack[-1]
    try:
        command.undo()
    except Exception as exc:
        window._operation_error("撤销失败", exc)
        return
    window.undo_stack.pop()
    window.redo_stack.append(command)


def redo(window) -> None:
    if not window.redo_stack:
        return
    command = window.redo_stack[-1]
    try:
        command.do()
    except Exception as exc:
        window._operation_error("重做失败", exc)
        return
    window.redo_stack.pop()
    window.undo_stack.append(command)


__all__ = [
    "ActionCommand",
    "apply_close_trade_result",
    "apply_open_trade_result",
    "current_bar",
    "current_tags_and_note",
    "display_interval",
    "execute_command",
    "is_display_interval_same_as_sample_interval",
    "is_trade_recording_allowed",
    "pause_replay_for_manual_trade",
    "raise_trade_action_error",
    "redo",
    "request_close_trade",
    "request_open_trade",
    "sample_interval",
    "selected_open_trade",
    "start_new_session_for_current_display_interval",
    "trade_use_case",
    "undo",
    "undo_close_trade_result",
    "undo_open_trade_result",
    "warn_trade_interval_mismatch",
]
