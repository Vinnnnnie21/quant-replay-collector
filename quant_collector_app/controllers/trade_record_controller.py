"""Manual trade-sample management actions kept outside MainWindow."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

try:
    from app_logger import get_logger
    from display_names import trade_display_name
    from presenters.formatters import side_label, status_label
    from render_state import RenderState
    from services.session_service import list_performance_session_options
except ImportError:  # pragma: no cover - package import path
    from ..app_logger import get_logger
    from ..display_names import trade_display_name
    from ..presenters.formatters import side_label, status_label
    from ..render_state import RenderState
    from ..services.session_service import list_performance_session_options


logger = get_logger(__name__)


_SESSION_TRADE_COLUMNS = (
    "symbol",
    "side",
    "return_pct",
    "pnl",
    "trade_id",
    "entry_time",
    "exit_time",
    "entry_price",
    "exit_price",
    "quantity",
    "status",
)


def _display_cell(value) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _set_profit_loss_color(window, item: QtWidgets.QTableWidgetItem, value) -> None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return
    theme = getattr(window, "theme_settings", {}) or {}
    color = theme.get("green") if number > 0 else theme.get("red") if number < 0 else None
    if color:
        item.setForeground(QtGui.QBrush(QtGui.QColor(str(color))))


def load_trade_management_session_trades(window) -> list[dict]:
    """Load only the bounded display rows for the selected saved session."""

    session_id = str(window.tradeManagementSessionBox.currentData() or "")
    try:
        rows = (
            window.storage.list_trade_samples_for_session(session_id, limit=500)
            if session_id
            else []
        )
    except Exception as exc:
        window._operation_error(window.tr("trade_data_management_preview_failed"), exc)
        rows = []
    table = window.tradeManagementSessionTradeTable
    language = str(getattr(window, "current_language", "zh_CN") or "zh_CN")
    table.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        for column, field in enumerate(_SESSION_TRADE_COLUMNS):
            value = row.get(field)
            if field == "side":
                text = side_label(value, language)
            elif field == "status":
                text = status_label(value, language)
            else:
                text = _display_cell(value)
            item = QtWidgets.QTableWidgetItem(text)
            if field in {"return_pct", "pnl"}:
                _set_profit_loss_color(window, item, value)
            if column == 0:
                item.setData(QtCore.Qt.UserRole, str(row.get("trade_id") or ""))
                item.setData(QtCore.Qt.UserRole + 1, dict(row))
            table.setItem(row_index, column, item)
    return rows


def refresh_trade_management_sessions(window) -> None:
    """Refresh the management selector from the shared performance catalog."""

    selected = str(window.tradeManagementSessionBox.currentData() or "")
    try:
        options = list_performance_session_options(window.storage)
    except Exception as exc:
        window._operation_error(window.tr("trade_data_management_preview_failed"), exc)
        options = ()
    combo = window.tradeManagementSessionBox
    combo.blockSignals(True)
    combo.clear()
    selected_index = -1
    for index, option in enumerate(options):
        combo.addItem(option.display_name, option.session_id)
        if option.session_id == selected:
            selected_index = index
    if selected_index >= 0 and hasattr(combo, "setCurrentIndex"):
        combo.setCurrentIndex(selected_index)
    combo.blockSignals(False)
    load_trade_management_session_trades(window)


def _trade_management_busy(window) -> bool:
    lifecycle = getattr(window, "task_lifecycle", None)
    active = set(getattr(lifecycle, "active_tasks", ()))
    analysis = getattr(window, "analysis_refresh_controller", None)
    return bool(
        getattr(window, "_loading_data", False)
        or getattr(getattr(getattr(window, "app_state", None), "export", None), "running", False)
        or getattr(window, "_trade_transaction_active", False)
        or getattr(lifecycle, "shutdown_in_progress", False)
        or bool(active)
        or getattr(analysis, "is_running", False)
    )


def _management_range(window) -> tuple[str, str]:
    start = window.tradeManagementStart.dateTime().toString(QtCore.Qt.ISODate)
    end = window.tradeManagementEnd.dateTime().toString(QtCore.Qt.ISODate)
    if not start or not end or start >= end:
        raise ValueError(window.tr("trade_data_management_invalid_range"))
    return str(start), str(end)


def _range_deletion_selection(window) -> tuple[list[dict], dict, str, str] | None:
    if _trade_management_busy(window):
        QtWidgets.QMessageBox.warning(
            window,
            window.tr("trade_data_management_title"),
            window.tr("trade_data_management_busy"),
        )
        return None
    try:
        start, end = _management_range(window)
        rows = window.storage.list_trade_samples_for_management(
            start_time=start,
            end_time=end,
        )
        preview = window.storage.preview_trade_sample_deletion(
            [str(row["trade_id"]) for row in rows]
        )
    except Exception as exc:
        window._operation_error(window.tr("trade_data_management_preview_failed"), exc)
        return None
    return rows, preview, start, end


def _format_deletion_preview(window, preview: dict, *, scope: str) -> str:
    sessions = ", ".join(preview.get("session_ids") or ()) or "-"
    return window.tr("trade_data_management_preview_message").format(
        scope=scope,
        trades=int(preview.get("trades", 0)),
        events=int(preview.get("trade_events", 0)),
        windows=int(preview.get("event_windows", 0)),
        features=int(preview.get("event_features", 0)),
        equity=int(preview.get("account_equity", 0)),
        session_count=len(preview.get("session_ids") or ()),
        sessions=sessions,
        sessions_deleted=int(preview.get("sessions", 0)),
        research_records=int(preview.get("research_records", 0)),
    )


def _confirm_phrase(
    window,
    *,
    title_key: str,
    prompt_key: str,
    phrase_key: str,
) -> bool:
    phrase, accepted = QtWidgets.QInputDialog.getText(
        window,
        window.tr(title_key),
        window.tr(prompt_key),
    )
    if not accepted:
        return False
    if phrase.strip() == window.tr(phrase_key):
        return True
    QtWidgets.QMessageBox.warning(
        window,
        window.tr(title_key),
        window.tr("trade_data_management_phrase_mismatch"),
    )
    return False


def _invalidate_analysis_workspace(window, session_ids: list[str]) -> None:
    workspace = getattr(window, "_analysis_workspace", None)
    invalidate = getattr(workspace, "invalidate_performance_sessions", None)
    if callable(invalidate):
        invalidate(session_ids)


def _apply_deleted_trade_samples(window, deleted: dict) -> None:
    session_ids = [str(value) for value in deleted.get("session_ids") or ()]
    current_session_id = str(getattr(window, "session_id", "") or "")
    if current_session_id and current_session_id in session_ids:
        trade_ids = {str(value) for value in deleted.get("trade_ids") or ()}
        event_ids = {str(value) for value in deleted.get("event_ids") or ()}
        window.trades[:] = [
            trade
            for trade in window.trades
            if str(trade.get("trade_id") or "") not in trade_ids
        ]
        window.events[:] = [
            event
            for event in window.events
            if str(event.get("event_id") or "") not in event_ids
        ]
        window._trade_by_id = {
            str(trade.get("trade_id")): trade
            for trade in window.trades
            if trade.get("trade_id")
        }
        window._event_by_id = {
            str(event.get("event_id")): event
            for event in window.events
            if event.get("event_id")
        }
        window.undo_stack.clear()
        window.redo_stack.clear()
        window._analysis_performance_payload = None
        window.persist_session_state()
        _render_state(window).mark_events_changed()
        window._sync_markers()
        window._refresh_tables()
        window._render_dirty = True
        window._render(force=True)
    _invalidate_analysis_workspace(window, session_ids)


def _delete_confirmed_trade_samples(
    window,
    trade_ids: list[str],
    *,
    operation: str,
) -> dict | None:
    return _execute_confirmed_deletion(
        window,
        lambda: window.storage.delete_trade_samples(trade_ids),
        operation=operation,
    )


def _execute_confirmed_deletion(
    window,
    delete_action,
    *,
    operation: str,
    result_handler=None,
) -> dict | None:
    if _trade_management_busy(window):
        QtWidgets.QMessageBox.warning(
            window,
            window.tr("trade_data_management_title"),
            window.tr("trade_data_management_busy"),
        )
        return None
    window._trade_transaction_active = True
    try:
        deleted = delete_action()
    except Exception as exc:
        window._operation_error(window.tr("trade_data_management_delete_failed"), exc)
        return None
    finally:
        window._trade_transaction_active = False
    handler = result_handler or _apply_deleted_trade_samples
    handler(window, deleted)
    if hasattr(window, "tradeManagementSessionBox"):
        refresh_trade_management_sessions(window)
    logger.info(
        "trade_sample_delete operation=%s trades=%s events=%s sessions=%s",
        operation,
        deleted.get("trades", 0),
        deleted.get("trade_events", 0),
        ",".join(deleted.get("session_ids") or ()),
    )
    message = window.tr("trade_data_management_delete_done").format(
        trades=int(deleted.get("trades", 0)),
        events=int(deleted.get("trade_events", 0)),
    )
    log = getattr(window, "_log", None)
    if callable(log):
        log(message)
    QtWidgets.QMessageBox.information(
        window,
        window.tr("trade_data_management_title"),
        message,
    )
    return deleted


def confirm_delete_trade_range(window) -> None:
    selection = _range_deletion_selection(window)
    if selection is None:
        return
    _rows, preview, start, end = selection
    if not preview.get("trade_ids"):
        QtWidgets.QMessageBox.information(
            window,
            window.tr("delete_trade_range_title"),
            window.tr("trade_data_management_no_matches"),
        )
        return
    response = QtWidgets.QMessageBox.warning(
        window,
        window.tr("delete_trade_range_title"),
        _format_deletion_preview(window, preview, scope=f"[{start}, {end})"),
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
        QtWidgets.QMessageBox.Cancel,
    )
    if response != QtWidgets.QMessageBox.Yes:
        return
    if not _confirm_phrase(
        window,
        title_key="delete_trade_range_title",
        prompt_key="delete_trade_range_phrase_prompt",
        phrase_key="delete_trade_range_phrase",
    ):
        return
    _delete_confirmed_trade_samples(
        window,
        [str(value) for value in preview.get("trade_ids") or ()],
        operation="time_range",
    )


def preview_trade_data_range(window) -> dict | None:
    selection = _range_deletion_selection(window)
    if selection is None:
        return None
    rows, preview, start, end = selection
    combo = window.tradeManagementCandidateBox
    combo.clear()
    for sequence, row in enumerate(rows, start=1):
        display_row = dict(row)
        display_row["entry_bar_time_bjt"] = row.get("entry_time")
        combo.addItem(
            trade_display_name(
                display_row,
                sequence,
                language=str(getattr(window, "current_language", "zh_CN") or "zh_CN"),
            ),
            str(row["trade_id"]),
        )
        combo.setItemData(combo.count() - 1, dict(row), QtCore.Qt.UserRole + 1)
    if rows:
        window.tradeManagementPreviewLabel.setText(
            _format_deletion_preview(window, preview, scope=f"[{start}, {end})")
        )
    else:
        window.tradeManagementPreviewLabel.setText(
            window.tr("trade_data_management_no_matches")
        )
    return preview


def confirm_delete_selected_trade(window) -> None:
    if _trade_management_busy(window):
        QtWidgets.QMessageBox.warning(
            window,
            window.tr("trade_data_management_title"),
            window.tr("trade_data_management_busy"),
        )
        return
    trade_id = str(window.tradeManagementCandidateBox.currentData() or "")
    if not trade_id:
        QtWidgets.QMessageBox.warning(
            window,
            window.tr("delete_selected_trade_title"),
            window.tr("trade_data_management_select_trade"),
        )
        return
    try:
        start, end = _management_range(window)
        rows = window.storage.list_trade_samples_for_management(
            start_time=start,
            end_time=end,
        )
        trade = next(
            (row for row in rows if str(row.get("trade_id") or "") == trade_id),
            None,
        )
        if trade is None:
            QtWidgets.QMessageBox.warning(
                window,
                window.tr("delete_selected_trade_title"),
                window.tr("trade_data_management_selection_stale"),
            )
            return
        preview = window.storage.preview_trade_sample_deletion([trade_id])
    except Exception as exc:
        window._operation_error(window.tr("trade_data_management_preview_failed"), exc)
        return
    pnl = trade.get("net_pnl_quote")
    scope = window.tr("delete_selected_trade_scope").format(
        side=side_label(
            trade.get("side"),
            str(getattr(window, "current_language", "zh_CN") or "zh_CN"),
        ) or "-",
        entry=trade.get("entry_time") or "-",
        exit=trade.get("exit_time") or "-",
        pnl="-" if pnl is None else f"{float(pnl):.2f}",
        trade_id=trade_id,
    )
    response = QtWidgets.QMessageBox.warning(
        window,
        window.tr("delete_selected_trade_title"),
        _format_deletion_preview(window, preview, scope=scope),
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
        QtWidgets.QMessageBox.Cancel,
    )
    if response != QtWidgets.QMessageBox.Yes:
        return
    if not _confirm_phrase(
        window,
        title_key="delete_selected_trade_title",
        prompt_key="delete_selected_trade_phrase_prompt",
        phrase_key="delete_selected_trade_phrase",
    ):
        return
    _delete_confirmed_trade_samples(
        window,
        [trade_id],
        operation="single_trade",
    )


def confirm_delete_session_trade(window) -> None:
    """Delete the selected row after revalidating it belongs to the selected session."""

    if _trade_management_busy(window):
        QtWidgets.QMessageBox.warning(
            window,
            window.tr("trade_data_management_title"),
            window.tr("trade_data_management_busy"),
        )
        return
    table = window.tradeManagementSessionTradeTable
    row_index = table.currentRow()
    item = table.item(row_index, 0) if row_index >= 0 else None
    trade_id = str(item.data(QtCore.Qt.UserRole) or "") if item is not None else ""
    session_id = str(window.tradeManagementSessionBox.currentData() or "")
    if not trade_id or not session_id:
        QtWidgets.QMessageBox.warning(
            window,
            window.tr("delete_session_trade_title"),
            window.tr("trade_data_management_select_session_trade"),
        )
        return
    try:
        rows = window.storage.list_trade_samples_for_session(session_id, limit=500)
        trade = next(
            (
                candidate
                for candidate in rows
                if str(candidate.get("trade_id") or "") == trade_id
                and str(candidate.get("session_id") or "") == session_id
            ),
            None,
        )
        if trade is None:
            QtWidgets.QMessageBox.warning(
                window,
                window.tr("delete_session_trade_title"),
                window.tr("trade_data_management_selection_stale"),
            )
            return
        preview = window.storage.preview_trade_sample_deletion([trade_id])
    except Exception as exc:
        window._operation_error(window.tr("trade_data_management_preview_failed"), exc)
        return
    if not preview.get("trade_ids"):
        return
    scope = window.tr("delete_selected_trade_scope").format(
        side=side_label(
            trade.get("side"),
            str(getattr(window, "current_language", "zh_CN") or "zh_CN"),
        ) or "-",
        entry=trade.get("entry_time") or "-",
        exit=trade.get("exit_time") or "-",
        pnl="-" if trade.get("pnl") is None else f"{float(trade['pnl']):.2f}",
        trade_id=trade_id,
    )
    response = QtWidgets.QMessageBox.warning(
        window,
        window.tr("delete_session_trade_title"),
        _format_deletion_preview(window, preview, scope=scope),
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
        QtWidgets.QMessageBox.Cancel,
    )
    if response != QtWidgets.QMessageBox.Yes:
        return
    if not _confirm_phrase(
        window,
        title_key="delete_session_trade_title",
        prompt_key="delete_session_trade_phrase_prompt",
        phrase_key="delete_session_trade_phrase",
    ):
        return
    _delete_confirmed_trade_samples(window, [trade_id], operation="session_trade")


def _apply_deleted_performance_session(window, deleted: dict) -> None:
    session_ids = [str(value) for value in deleted.get("session_ids") or ()]
    current_session_id = str(getattr(window, "session_id", "") or "")
    if current_session_id and current_session_id in session_ids:
        window.trades.clear()
        window.events.clear()
        window._trade_by_id.clear()
        window._event_by_id.clear()
        window.undo_stack.clear()
        window.redo_stack.clear()
        window._analysis_performance_payload = None
        window.session_id = None
        if hasattr(window, "restoring_session_id"):
            window.restoring_session_id = None
        _render_state(window).mark_events_changed()
        window._sync_markers()
        window._refresh_tables()
        window._render_dirty = True
        window._render(force=True)
    workspace = getattr(window, "_analysis_workspace", None)
    refresh_catalog = getattr(workspace, "refresh_performance_session_catalog", None)
    if callable(refresh_catalog):
        refresh_catalog()
    _invalidate_analysis_workspace(window, session_ids)
    refresh_replay = getattr(window, "refresh_replay_performance_sessions", None)
    if callable(refresh_replay):
        refresh_replay()


def confirm_delete_performance_session(window) -> None:
    """Delete the selected performance session, including an empty session."""

    if _trade_management_busy(window):
        QtWidgets.QMessageBox.warning(
            window,
            window.tr("trade_data_management_title"),
            window.tr("trade_data_management_busy"),
        )
        return
    session_id = str(window.tradeManagementSessionBox.currentData() or "")
    if not session_id:
        QtWidgets.QMessageBox.warning(
            window,
            window.tr("delete_performance_session_title"),
            window.tr("trade_data_management_select_session"),
        )
        return
    try:
        preview = window.storage.preview_performance_session_deletion(session_id)
    except Exception as exc:
        window._operation_error(window.tr("trade_data_management_preview_failed"), exc)
        return
    if not preview.get("sessions"):
        QtWidgets.QMessageBox.information(
            window,
            window.tr("delete_performance_session_title"),
            window.tr("trade_data_management_session_missing"),
        )
        return
    scope = window.tr("delete_performance_session_scope").format(session_id=session_id)
    response = QtWidgets.QMessageBox.warning(
        window,
        window.tr("delete_performance_session_title"),
        _format_deletion_preview(window, preview, scope=scope),
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
        QtWidgets.QMessageBox.Cancel,
    )
    if response != QtWidgets.QMessageBox.Yes:
        return
    if not _confirm_phrase(
        window,
        title_key="delete_performance_session_title",
        prompt_key="delete_performance_session_phrase_prompt",
        phrase_key="delete_performance_session_phrase",
    ):
        return
    _execute_confirmed_deletion(
        window,
        lambda: window.storage.delete_performance_session(session_id),
        operation="performance_session",
        result_handler=_apply_deleted_performance_session,
    )


def _render_state(window) -> RenderState:
    getter = getattr(window, "_chart_render_state", None)
    if callable(getter):
        return getter()
    state = getattr(window, "render_state", None)
    if state is None:
        state = RenderState()
        window.render_state = state
    return state


def confirm_clear_trade_records(window) -> None:
    if _trade_management_busy(window):
        QtWidgets.QMessageBox.warning(
            window,
            window.tr("clear_trade_records_title"),
            window.tr("clear_trade_records_busy"),
        )
        return
    try:
        preview = window.storage.preview_all_trade_sample_deletion()
    except Exception as exc:
        window._operation_error(window.tr("trade_data_management_preview_failed"), exc)
        return
    response = QtWidgets.QMessageBox.warning(
        window,
        window.tr("clear_trade_records_title"),
        _format_deletion_preview(
            window,
            preview,
            scope=window.tr("clear_trade_records_scope"),
        ),
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
        QtWidgets.QMessageBox.Cancel,
    )
    if response != QtWidgets.QMessageBox.Yes:
        return
    if not _confirm_phrase(
        window,
        title_key="clear_trade_records_title",
        prompt_key="clear_trade_records_phrase_prompt",
        phrase_key="clear_trade_records_phrase",
    ):
        return
    if _trade_management_busy(window):
        QtWidgets.QMessageBox.warning(
            window,
            window.tr("clear_trade_records_title"),
            window.tr("clear_trade_records_busy"),
        )
        return
    window._trade_transaction_active = True
    try:
        deleted = window.storage.clear_manual_research_records()
    except Exception as exc:
        window._operation_error(window.tr("clear_trade_records_failed"), exc)
        return
    finally:
        window._trade_transaction_active = False

    window.trades.clear()
    window.events.clear()
    window._trade_by_id.clear()
    window._event_by_id.clear()
    window.undo_stack.clear()
    window.redo_stack.clear()
    window._analysis_performance_payload = None
    window.persist_session_state()
    _render_state(window).mark_events_changed()
    window._sync_markers()
    window._refresh_tables()
    window._render_dirty = True
    window._render(force=True)
    session_ids = [str(value) for value in deleted.get("session_ids") or ()]
    current_id = str(getattr(window, "session_id", "") or "")
    if current_id and current_id not in session_ids:
        session_ids.append(current_id)
    _invalidate_analysis_workspace(window, session_ids)
    if hasattr(window, "tradeManagementSessionBox"):
        refresh_trade_management_sessions(window)
    logger.info(
        "trade_sample_delete operation=clear_all trades=%s events=%s sessions=%s",
        deleted.get("trades", 0),
        deleted.get("trade_events", 0),
        ",".join(session_ids),
    )
    message = window.tr("clear_trade_records_done").format(
        trades=int(deleted.get("trades", 0)),
        trade_events=int(deleted.get("trade_events", 0)),
    )
    log = getattr(window, "_log", None)
    if callable(log):
        log(message)
    QtWidgets.QMessageBox.information(window, window.tr("clear_trade_records_title"), message)


__all__ = [
    "confirm_clear_trade_records",
    "confirm_delete_selected_trade",
    "confirm_delete_trade_range",
    "confirm_delete_session_trade",
    "confirm_delete_performance_session",
    "preview_trade_data_range",
    "refresh_trade_management_sessions",
    "load_trade_management_session_trades",
]
